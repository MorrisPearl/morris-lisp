#!/usr/bin/env python3
"""
fec_loader_sqlite.py

SQLite counterpart of fec_loader.py. Downloads the same FEC bulk data
files (Candidate Master, Candidate-Committee Linkages, Committee
Master, Contributions by Individuals) and loads them into a SQLite
database, using the `sqlite3` command-line tool's `.import` command
for the bulk loading step (the closest SQLite equivalent of MySQL's
`LOAD DATA LOCAL INFILE`).

    https://www.fec.gov/data/browse-data/?tab=bulk-data

Usage:
    python fec_loader_sqlite.py setup
    python fec_loader_sqlite.py load-static        [--cycle 2026]
    python fec_loader_sqlite.py load-indiv         [--cycle 2026]
    python fec_loader_sqlite.py load-all           [--cycle 2026]
    python fec_loader_sqlite.py sync-indiv         [--cycle 2026]   (OpenFEC API top-up)
    python fec_loader_sqlite.py inspect-schedule-a [--cycle 2026]   (sanity-check API fields)
    python fec_loader_sqlite.py status

Configuration is read from config.ini (see config.ini.example, [sqlite]
section) or can be overridden with --db-path.

Requires:
    pip install requests
    the `sqlite3` command-line tool on PATH (ships with macOS/most
    Linux distros; `brew install sqlite` / `apt install sqlite3` if not).

--------------------------------------------------------------------
Design notes
--------------------------------------------------------------------
This script is meant for unattended, single-writer, overnight runs
(e.g. cron) with no concurrent readers/writers, as SQLite is not a
great fit for concurrent write access. It trades some crash-safety for
load speed accordingly (see the PRAGMAs in run_sqlite_cli-fed scripts)
-- if you need concurrent access while loading, use fec_loader.py
(MySQL) instead.

- Candidate Master, Candidate-Committee Linkages and Committee Master
  are small reference files with no history/delta bulk files, so each
  run drops and reloads them from scratch, same as the MySQL version.
  Since the FEC files' column order matches these tables exactly, the
  file is `.import`ed directly into the (freshly recreated) table --
  no staging table needed.

- Contributions by Individuals is enormous and, like the MySQL
  version, is loaded incrementally: the full current-cycle file is
  downloaded every run, but only rows whose SUB_ID isn't already
  present get inserted. Because this table needs light transformation
  (MMDDYYYY -> ISO date, plus three bookkeeping columns not present in
  the raw file), the raw file is first `.import`ed into a throwaway
  staging table, then copied into indiv_contributions with a single
  `INSERT ... SELECT`. Deduplication is handled by SQLite itself:
  indiv_contributions declares `sub_id INTEGER PRIMARY KEY ON CONFLICT
  IGNORE`, so *any* insert that collides on sub_id -- including the
  plain INSERT used here -- is silently skipped, with no need for an
  explicit "OR IGNORE" at the call site.

  For true bandwidth-efficient incremental pulls (only rows added since
  your last run, without re-downloading the whole cycle), use `sync-indiv`
  instead, which queries the OpenFEC API (https://api.open.fec.gov) for
  records past the highest SUB_ID you already have. See the OpenFEC
  section further down for the same caveats that apply to the MySQL
  version's sync-indiv.

- FEC bulk files are Latin-1/Windows-1252 encoded. SQLite text storage
  is UTF-8, and the sqlite3 CLI's `.import` has no per-column charset
  option (unlike MySQL's `LOAD DATA ... CHARACTER SET latin1`), so each
  extracted file is first re-encoded latin1 -> utf-8 to a sibling
  `*.utf8` file before being imported, then that temporary file is
  deleted.
"""

import argparse
import configparser
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import datetime

import requests


# --------------------------------------------------------------------------
# FEC bulk file definitions (identical to fec_loader.py)
# --------------------------------------------------------------------------

BASE_URL = "https://www.fec.gov/files/bulk-downloads/{year}/{prefix}{yy}.zip"

# name -> (url prefix, table name, human description)
STATIC_FILES = {
    "cn":  ("cn",  "candidate_master",             "Candidate Master"),
    "cm":  ("cm",  "committee_master",             "Committee Master"),
    "ccl": ("ccl", "candidate_committee_linkage",  "Candidate-Committee Linkages"),
}

INDIV_FILE = ("indiv", "indiv_contributions", "Contributions by Individuals")

EXPECTED_INNER_NAME = {
    "cn": "cn.txt",
    "cm": "cm.txt",
    "ccl": "ccl.txt",
    "indiv": "itcont.txt",
}


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA_TABLES = {
    "candidate_master": """
        CREATE TABLE IF NOT EXISTS candidate_master (
            cand_id              TEXT PRIMARY KEY,
            cand_name            TEXT,
            cand_pty_affiliation TEXT,
            cand_election_yr     INTEGER,
            cand_office_st       TEXT,
            cand_office          TEXT,
            cand_office_district TEXT,
            cand_ici             TEXT,
            cand_status          TEXT,
            cand_pcc             TEXT,
            cand_st1             TEXT,
            cand_st2             TEXT,
            cand_city            TEXT,
            cand_st              TEXT,
            cand_zip             TEXT
        );
    """,
    "committee_master": """
        CREATE TABLE IF NOT EXISTS committee_master (
            cmte_id              TEXT PRIMARY KEY,
            cmte_nm              TEXT,
            tres_nm              TEXT,
            cmte_st1             TEXT,
            cmte_st2             TEXT,
            cmte_city            TEXT,
            cmte_st              TEXT,
            cmte_zip             TEXT,
            cmte_dsgn            TEXT,
            cmte_tp              TEXT,
            cmte_pty_affiliation TEXT,
            cmte_filing_freq    TEXT,
            org_tp               TEXT,
            connected_org_nm     TEXT,
            cand_id              TEXT
        );
    """,
    "candidate_committee_linkage": """
        CREATE TABLE IF NOT EXISTS candidate_committee_linkage (
            cand_id           TEXT NOT NULL,
            cand_election_yr  INTEGER NOT NULL,
            fec_election_yr   INTEGER NOT NULL,
            cmte_id           TEXT,
            cmte_tp           TEXT,
            cmte_dsgn         TEXT,
            linkage_id        INTEGER PRIMARY KEY
        );
    """,
}

SCHEMA_INDEXES = {
    "candidate_master": [
        "CREATE INDEX IF NOT EXISTS idx_cand_pcc ON candidate_master (cand_pcc);",
        "CREATE INDEX IF NOT EXISTS idx_cand_office_st ON candidate_master (cand_office_st, cand_office);",
    ],
    "committee_master": [
        "CREATE INDEX IF NOT EXISTS idx_cmte_cand_id ON committee_master (cand_id);",
    ],
    "candidate_committee_linkage": [
        "CREATE INDEX IF NOT EXISTS idx_ccl_cand_id ON candidate_committee_linkage (cand_id);",
        "CREATE INDEX IF NOT EXISTS idx_ccl_cmte_id ON candidate_committee_linkage (cmte_id);",
    ],
}

INDIV_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS indiv_contributions (
        cmte_id           TEXT,
        amndt_ind         TEXT,
        rpt_tp            TEXT,
        transaction_pgi   TEXT,
        image_num         TEXT,
        transaction_tp    TEXT,
        entity_tp         TEXT,
        name              TEXT,
        city              TEXT,
        state             TEXT,
        zip_code          TEXT,
        employer          TEXT,
        occupation        TEXT,
        transaction_dt    TEXT,
        transaction_amt   REAL,
        other_id          TEXT,
        tran_id           TEXT,
        file_num          INTEGER,
        memo_cd           TEXT,
        memo_text         TEXT,
        sub_id            INTEGER PRIMARY KEY ON CONFLICT IGNORE,
        election_cycle    TEXT,
        source_file       TEXT,
        load_batch_id     INTEGER,
        loaded_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

# name -> column expression, used to build both the CREATE INDEX
# statements (setup, and rebuilding after a bulk indiv load) and the
# DROP INDEX statements (dropped before a bulk indiv load so the insert
# doesn't pay to maintain them row-by-row -- see load_indiv_table).
INDIV_INDEX_DEFS = {
    "idx_indiv_cmte_id": "cmte_id",
    "idx_indiv_name": "name",
    "idx_indiv_transaction_dt": "transaction_dt",
    "idx_indiv_zip_code": "zip_code",
    "idx_indiv_election_cycle": "election_cycle",
    # Speeds up the post-load "how many rows did this batch actually
    # insert" bookkeeping query (SELECT COUNT(*) ... WHERE
    # load_batch_id=?), which would otherwise be a full table scan.
    "idx_indiv_load_batch_id": "load_batch_id",
}

INDIV_INDEXES = [
    "CREATE INDEX IF NOT EXISTS {} ON indiv_contributions ({});".format(name, cols)
    for name, cols in INDIV_INDEX_DEFS.items()
]

INDIV_INDEX_DROPS = [
    "DROP INDEX IF EXISTS {};".format(name) for name in INDIV_INDEX_DEFS
]

LOAD_HISTORY_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS load_history (
        load_batch_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name      TEXT NOT NULL,
        source_file     TEXT NOT NULL,
        election_cycle  TEXT,
        rows_in_file    INTEGER,
        rows_inserted   INTEGER,
        started_at      TEXT NOT NULL,
        finished_at     TEXT,
        status          TEXT NOT NULL DEFAULT 'running'
    );
"""

STATIC_LOAD_COLUMNS = {
    "candidate_master": (
        "cand_id, cand_name, cand_pty_affiliation, cand_election_yr, "
        "cand_office_st, cand_office, cand_office_district, cand_ici, "
        "cand_status, cand_pcc, cand_st1, cand_st2, cand_city, cand_st, cand_zip"
    ),
    "committee_master": (
        "cmte_id, cmte_nm, tres_nm, cmte_st1, cmte_st2, cmte_city, cmte_st, "
        "cmte_zip, cmte_dsgn, cmte_tp, cmte_pty_affiliation, cmte_filing_freq, "
        "org_tp, connected_org_nm, cand_id"
    ),
    "candidate_committee_linkage": (
        "cand_id, cand_election_yr, fec_election_yr, cmte_id, cmte_tp, "
        "cmte_dsgn, linkage_id"
    ),
}


# --------------------------------------------------------------------------
# Config / connection helpers
# --------------------------------------------------------------------------

def load_config(path):
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path)
    db_path = cfg.get("sqlite", "db_path", fallback="./fec.db")
    download_dir = cfg.get("download", "dest_dir", fallback="./fec_downloads")
    openfec_cfg = {
        "api_key": cfg.get("openfec", "api_key", fallback=""),
    }
    return db_path, download_dir, openfec_cfg


def apply_cli_overrides(db_path, args):
    if args.db_path is not None:
        return args.db_path
    return db_path


def get_connection(db_path):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    return sqlite3.connect(db_path)


def check_sqlite_cli():
    if shutil.which("sqlite3") is None:
        raise RuntimeError(
            "The 'sqlite3' command-line tool was not found on PATH. This "
            "script uses it (not the Python sqlite3 module) for bulk "
            "loading via '.import', which is far faster than row-by-row "
            "inserts. Install it (e.g. 'brew install sqlite' or "
            "'apt install sqlite3') and try again."
        )


def sql_quote(value):
    """Quotes a string as a SQLite text literal for embedding directly in
    a SQL script (doubling embedded single quotes). Only used for values
    this script itself generates (cycle labels, source zip filenames),
    never for untrusted FEC row data."""
    return "'" + str(value).replace("'", "''") + "'"


def run_sqlite_cli(db_path, script):
    """Feeds `script` (a sequence of dot-commands and/or SQL statements)
    to the sqlite3 CLI against db_path, the same way you'd pipe a .sql
    file into `sqlite3 mydb.db`."""
    check_sqlite_cli()
    proc = subprocess.run(
        ["sqlite3", db_path],
        input=script,
        text=True,
        capture_output=True,
    )
    if proc.stdout.strip():
        print(proc.stdout)
    if proc.returncode != 0:
        raise RuntimeError(
            "sqlite3 CLI exited with status {}:\n{}".format(
                proc.returncode, proc.stderr)
        )
    if proc.stderr.strip():
        print("  sqlite3 warnings:\n{}".format(proc.stderr), file=sys.stderr)


# --------------------------------------------------------------------------
# Cycle handling (identical to fec_loader.py)
# --------------------------------------------------------------------------

def current_cycle_year():
    year = datetime.now().year
    return year if year % 2 == 0 else year + 1


def cycle_label(cycle_year):
    return "{}-{}".format(cycle_year - 1, cycle_year)


# --------------------------------------------------------------------------
# Download / extract (identical to fec_loader.py)
# --------------------------------------------------------------------------

def download_file(url, dest_path, max_retries=5):
    """Downloads url to dest_path, retrying with backoff on transient
    network errors -- these bulk files are multi-GB and take minutes, so
    a single dropped connection shouldn't abort an unattended multi-cycle
    run. FEC's download URL redirects to S3; that combination doesn't
    reliably honor Range requests (confirmed: repeated 416 responses even
    for in-bounds ranges), so on a failure this just restarts the whole
    file rather than trying to resume from a byte offset."""
    for attempt in range(1, max_retries + 1):
        print("  Downloading {} ...".format(url))
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                last_pct = -1
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded * 100 / total)
                            if pct != last_pct and pct % 10 == 0:
                                print("    {}% ({:.1f} MB / {:.1f} MB)".format(
                                    pct, downloaded / 1e6, total / 1e6))
                                last_pct = pct
            print("  Saved to {}".format(dest_path))
            return
        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                raise
            wait = min(60, 2 ** attempt)
            print("  Download error ({}), retrying in {}s (attempt {}/{}) ...".format(
                e, wait, attempt + 1, max_retries))
            time.sleep(wait)


def extract_data_file(zip_path, extract_dir, expected_name=None):
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        all_names = [n for n in zf.namelist() if not n.endswith("/")]
        if not all_names:
            raise RuntimeError("Zip file {} is empty".format(zip_path))

        top_level = [n for n in all_names if "/" not in n]
        nested = [n for n in all_names if "/" in n]
        if nested:
            print("  Note: ignoring {} file(s) in subfolder(s) of {} "
                  "(e.g. {}) -- these are the same data pre-split into "
                  "smaller chunks, not additional records.".format(
                      len(nested), os.path.basename(zip_path), nested[0]))

        target = None
        if expected_name and expected_name in top_level:
            target = expected_name
        else:
            top_level_data = [n for n in top_level
                               if n.lower().endswith((".txt", ".csv"))]
            if len(top_level_data) == 1:
                target = top_level_data[0]

        if target is None:
            raise RuntimeError(
                "Could not unambiguously identify the data file inside {}. "
                "Top-level entries found: {}. Expected: {}.".format(
                    zip_path, top_level, expected_name)
            )

        zf.extract(target, extract_dir)
        return os.path.join(extract_dir, target)


def fetch_and_extract(prefix, cycle_year, download_dir):
    yy = str(cycle_year)[-2:]
    url = BASE_URL.format(year=cycle_year, prefix=prefix, yy=yy)
    zip_name = "{}{}.zip".format(prefix, yy)
    cycle_dir = os.path.join(download_dir, str(cycle_year))
    os.makedirs(cycle_dir, exist_ok=True)
    zip_path = os.path.join(cycle_dir, zip_name)
    download_file(url, zip_path)
    txt_path = extract_data_file(
        zip_path, os.path.join(cycle_dir, "extracted"),
        expected_name=EXPECTED_INNER_NAME.get(prefix),
    )
    print("  Using data file: {}".format(txt_path))
    return zip_name, zip_path, txt_path


def cleanup_download(zip_path, txt_path):
    """Removes the downloaded zip and extracted flat file once they've
    been loaded, so multi-cycle loads (especially indiv, several GB per
    cycle) don't pile up disk usage for files that are no longer needed
    once their rows are in the database."""
    for path in (zip_path, txt_path):
        if path and os.path.exists(path):
            os.remove(path)
    print("  Deleted downloaded/extracted flat files for this file.")


def count_lines(path):
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count


def recode_latin1_to_utf8(src_path):
    """FEC bulk files are Latin-1/Windows-1252. SQLite text storage (and
    the sqlite3 CLI's .import) is UTF-8 with no per-column charset
    option, so we stream-recode to a sibling *.utf8 file before
    importing. Every byte is a valid Latin-1 character, so this can be
    done in fixed-size chunks with no risk of splitting a character
    across a chunk boundary."""
    dst_path = src_path + ".utf8"
    with open(src_path, "rb") as fin, open(dst_path, "wb") as fout:
        while True:
            chunk = fin.read(4 * 1024 * 1024)
            if not chunk:
                break
            fout.write(chunk.decode("latin1").encode("utf-8"))
    return dst_path


# --------------------------------------------------------------------------
# Load history bookkeeping
# --------------------------------------------------------------------------

def start_batch(cur, table_name, source_file, election_cycle, rows_in_file):
    cur.execute(
        "INSERT INTO load_history "
        "(table_name, source_file, election_cycle, rows_in_file, started_at, status) "
        "VALUES (?, ?, ?, ?, ?, 'running')",
        (table_name, source_file, election_cycle, rows_in_file,
         datetime.now().isoformat(sep=" ", timespec="seconds")),
    )
    return cur.lastrowid


def finish_batch(cur, batch_id, rows_inserted, status="success"):
    cur.execute(
        "UPDATE load_history SET rows_inserted=?, finished_at=?, status=? "
        "WHERE load_batch_id=?",
        (rows_inserted, datetime.now().isoformat(sep=" ", timespec="seconds"),
         status, batch_id),
    )


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

def load_static_table(db_path, table_name, txt_path, source_file, election_cycle):
    rows_in_file = count_lines(txt_path)

    conn = get_connection(db_path)
    cur = conn.cursor()
    batch_id = start_batch(cur, table_name, source_file, election_cycle, rows_in_file)
    conn.commit()
    conn.close()

    utf8_path = recode_latin1_to_utf8(txt_path)
    try:
        index_stmts = "\n".join(SCHEMA_INDEXES[table_name])
        script = """
.bail on
.output /dev/null
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA locking_mode=EXCLUSIVE;
DROP TABLE IF EXISTS {table};
{create}
.mode ascii
.separator "|" "\\n"
.import "{path}" {table}
{indexes}
""".format(table=table_name, create=SCHEMA_TABLES[table_name],
           path=utf8_path, indexes=index_stmts)

        print("  Recreating and loading {} via sqlite3 .import ...".format(table_name))
        run_sqlite_cli(db_path, script)
    finally:
        os.remove(utf8_path)

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM {}".format(table_name))
    rows_inserted = cur.fetchone()[0]
    finish_batch(cur, batch_id, rows_inserted)
    conn.commit()
    conn.close()
    print("  {}: {} rows loaded.".format(table_name, rows_inserted))


def load_indiv_table(db_path, txt_path, source_file, election_cycle):
    table_name = INDIV_FILE[1]
    rows_in_file = count_lines(txt_path)

    conn = get_connection(db_path)
    cur = conn.cursor()
    batch_id = start_batch(cur, table_name, source_file, election_cycle, rows_in_file)
    conn.commit()
    conn.close()

    utf8_path = recode_latin1_to_utf8(txt_path)
    try:
        script = """
.bail on
.output /dev/null
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA locking_mode=EXCLUSIVE;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-200000;
{indiv_table}
{index_drops}
DROP TABLE IF EXISTS stg_indiv;
CREATE TABLE stg_indiv (
    cmte_id TEXT, amndt_ind TEXT, rpt_tp TEXT, transaction_pgi TEXT, image_num TEXT,
    transaction_tp TEXT, entity_tp TEXT, name TEXT, city TEXT, state TEXT, zip_code TEXT,
    employer TEXT, occupation TEXT, transaction_dt TEXT, transaction_amt TEXT,
    other_id TEXT, tran_id TEXT, file_num TEXT, memo_cd TEXT, memo_text TEXT, sub_id TEXT
);
.mode ascii
.separator "|" "\\n"
.import "{path}" stg_indiv
INSERT INTO indiv_contributions
    (cmte_id, amndt_ind, rpt_tp, transaction_pgi, image_num, transaction_tp, entity_tp,
     name, city, state, zip_code, employer, occupation, transaction_dt, transaction_amt,
     other_id, tran_id, file_num, memo_cd, memo_text, sub_id,
     election_cycle, source_file, load_batch_id)
SELECT
    cmte_id, amndt_ind, rpt_tp, transaction_pgi, image_num, transaction_tp, entity_tp,
    name, city, state, zip_code, employer, occupation,
    CASE WHEN length(transaction_dt) = 8
         THEN substr(transaction_dt,5,4) || '-' || substr(transaction_dt,1,2) || '-' || substr(transaction_dt,3,2)
         ELSE NULL END,
    NULLIF(transaction_amt, ''),
    other_id, tran_id, NULLIF(file_num, ''), memo_cd, memo_text, sub_id,
    {cycle}, {source}, {batch_id}
FROM stg_indiv;
DROP TABLE stg_indiv;
{index_creates}
""".format(indiv_table=INDIV_TABLE_SQL, path=utf8_path,
           index_drops="\n".join(INDIV_INDEX_DROPS),
           index_creates="\n".join(INDIV_INDEXES),
           cycle=sql_quote(election_cycle), source=sql_quote(source_file),
           batch_id=int(batch_id))

        print("  Loading into {} (existing SUB_IDs are skipped) ...".format(table_name))
        start = time.time()
        run_sqlite_cli(db_path, script)
        elapsed = time.time() - start
    finally:
        os.remove(utf8_path)

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM indiv_contributions WHERE load_batch_id=?",
        (batch_id,),
    )
    rows_inserted = cur.fetchone()[0]
    finish_batch(cur, batch_id, rows_inserted)
    conn.commit()
    conn.close()
    print("  {}: {} new rows inserted out of {} rows in file ({:.0f}s).".format(
        table_name, rows_inserted, rows_in_file, elapsed))
    # Rebuild the secondary indexes' statistics so the query planner has
    # up-to-date row estimates after a big incremental load.
    conn = get_connection(db_path)
    conn.execute("ANALYZE indiv_contributions")
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# OpenFEC API incremental sync (alternative to re-downloading the bulk file)
# --------------------------------------------------------------------------
#
# Same rationale/caveats as fec_loader.py's sync-indiv -- see that file's
# comments and the README for the full explanation. The only difference
# here is the destination (sqlite3 + INSERT OR IGNORE) instead of MySQL.

OPENFEC_SCHEDULE_A_URL = "https://api.open.fec.gov/v1/schedules/schedule_a/"

SCHEDULE_A_FIELD_ALIASES = {
    "cmte_id":         ["committee_id"],
    "amndt_ind":       ["amendment_indicator"],
    "rpt_tp":          ["report_type"],
    "transaction_pgi": ["primary_general_indicator", "election_type", "transaction_pgi"],
    "image_num":       ["image_number"],
    "transaction_tp":  ["transaction_type"],
    "entity_tp":       ["entity_type"],
    "name":            ["contributor_name"],
    "city":            ["contributor_city"],
    "state":           ["contributor_state"],
    "zip_code":        ["contributor_zip", "contributor_zip_code"],
    "employer":        ["contributor_employer"],
    "occupation":      ["contributor_occupation"],
    "transaction_dt":  ["contribution_receipt_date"],
    "transaction_amt": ["contribution_receipt_amount"],
    "other_id":        ["contributor_id", "donor_committee_id", "other_id"],
    "tran_id":         ["transaction_id"],
    "file_num":        ["file_number"],
    "memo_cd":         ["memo_code"],
    "memo_text":       ["memo_text"],
    "sub_id":          ["sub_id"],
}

INDIV_API_INSERT_COLUMNS = list(SCHEDULE_A_FIELD_ALIASES.keys()) + [
    "election_cycle", "source_file", "load_batch_id",
]


def resolve_field(record, aliases):
    for a in aliases:
        if a in record:
            return a, record[a]
    return None, None


def validate_schedule_a_schema(sample_record):
    resolved = {}
    missing = []
    for col, aliases in SCHEDULE_A_FIELD_ALIASES.items():
        key, _ = resolve_field(sample_record, aliases)
        if key is None:
            missing.append((col, aliases))
        else:
            resolved[col] = key
            if key != aliases[0]:
                print("  NOTE: column '{}' matched fallback field '{}' "
                      "(expected '{}') -- double-check this.".format(
                          col, key, aliases[0]))
    if missing:
        raise RuntimeError(
            "OpenFEC schema mismatch -- these columns had no matching "
            "field in the API response: {}\n"
            "Available fields in the sample record: {}\n"
            "Update SCHEDULE_A_FIELD_ALIASES in fec_loader_sqlite.py to "
            "match, then re-run. (Run 'python fec_loader_sqlite.py "
            "inspect-schedule-a' to see a full sample record.)".format(
                [c for c, _ in missing], sorted(sample_record.keys()))
        )
    print("  OpenFEC field mapping validated against sample record.")
    return resolved


def parse_schedule_a_date(value):
    if not value:
        return None
    s = str(value)[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def map_schedule_a_record(record, election_cycle, source_file, batch_id):
    row = []
    for col, aliases in SCHEDULE_A_FIELD_ALIASES.items():
        _, value = resolve_field(record, aliases)
        if col == "transaction_dt":
            value = parse_schedule_a_date(value)
        row.append(value)
    row.extend([election_cycle, source_file, batch_id])
    return tuple(row)


def fetch_schedule_a_page(session, api_key, cycle_year, per_page, last_index):
    params = {
        "api_key": api_key,
        "two_year_transaction_period": cycle_year,
        "sort": "index",
        "sort_hide_null": "true",
        "per_page": per_page,
    }
    if last_index is not None:
        params["last_index"] = last_index

    for attempt in range(5):
        resp = session.get(OPENFEC_SCHEDULE_A_URL, params=params, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = (2 ** attempt) * 2
            print("  OpenFEC API returned {}, retrying in {}s ...".format(
                resp.status_code, wait))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(
        "OpenFEC API request failed repeatedly for params: {}".format(params)
    )


def sync_indiv_via_api(db_path, openfec_cfg, cycle_year, per_page=100,
                        overlap=2000, max_pages=None, allow_full_sync=False):
    api_key = openfec_cfg.get("api_key")
    if not api_key:
        raise RuntimeError(
            "No OpenFEC API key configured. Get a free key at "
            "https://api.data.gov/signup/ and put it in config.ini under "
            "[openfec] api_key = ..."
        )

    election_cycle = cycle_label(cycle_year)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT MAX(sub_id) FROM indiv_contributions WHERE election_cycle = ?",
        (election_cycle,),
    )
    max_sub_id = cur.fetchone()[0]

    if max_sub_id is None:
        if not allow_full_sync:
            raise RuntimeError(
                "No existing rows found for cycle {} -- sync-indiv is meant "
                "for topping up a table that already has an initial load. "
                "Run 'load-indiv --cycle {}' first (much faster via the bulk "
                "file), or pass --allow-full-sync to pull the whole cycle "
                "through the API instead (slow, rate-limited).".format(
                    election_cycle, cycle_year)
            )
        last_index = None
        print("  No existing data for {} -- starting from the beginning "
              "via the API (this will be slow).".format(election_cycle))
    else:
        last_index = max(0, max_sub_id - overlap)
        print("  Highest SUB_ID already loaded for {}: {}. Resuming from "
              "index {} (includes a {}-row overlap for safety).".format(
                  election_cycle, max_sub_id, last_index, overlap))

    batch_id = start_batch(cur, "indiv_contributions", "openfec-api",
                            election_cycle, None)
    conn.commit()

    insert_sql = "INSERT OR IGNORE INTO indiv_contributions ({}) VALUES ({})".format(
        ", ".join(INDIV_API_INSERT_COLUMNS),
        ", ".join(["?"] * len(INDIV_API_INSERT_COLUMNS)),
    )

    session = requests.Session()
    total_seen = 0
    total_inserted = 0
    page_num = 0

    try:
        while True:
            page = fetch_schedule_a_page(
                session, api_key, cycle_year, per_page, last_index
            )
            results = page.get("results", [])
            if page_num == 0:
                if not results:
                    print("  No records returned -- nothing new to sync.")
                    break
                validate_schedule_a_schema(results[0])
            if not results:
                break

            rows = [
                map_schedule_a_record(r, election_cycle, "openfec-api", batch_id)
                for r in results
            ]
            cur.executemany(insert_sql, rows)
            conn.commit()
            page_inserted = max(cur.rowcount, 0)
            total_inserted += page_inserted
            total_seen += len(results)

            pagination = page.get("pagination", {}) or {}
            last_indexes = pagination.get("last_indexes") or {}
            next_last_index = last_indexes.get("last_index")
            page_num += 1
            print("  page {}: fetched {} records ({} total so far)".format(
                page_num, len(results), total_seen))

            if next_last_index is None or len(results) < per_page:
                break
            if max_pages and page_num >= max_pages:
                print("  Reached --max-pages limit ({}), stopping.".format(max_pages))
                break

            last_index = next_last_index
            time.sleep(0.25)

        finish_batch(cur, batch_id, total_inserted)
        conn.commit()
    except Exception:
        finish_batch(cur, batch_id, total_inserted, status="failed")
        conn.commit()
        raise
    finally:
        conn.close()

    print("  Done: {} records fetched from the API, {} new rows inserted "
          "(rest were already present).".format(total_seen, total_inserted))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_setup(args, db_path, download_dir, openfec_cfg):
    check_sqlite_cli()
    conn = get_connection(db_path)
    cur = conn.cursor()
    for table_name, create_stmt in SCHEMA_TABLES.items():
        cur.execute(create_stmt)
        for stmt in SCHEMA_INDEXES[table_name]:
            cur.execute(stmt)
    cur.execute(INDIV_TABLE_SQL)
    for stmt in INDIV_INDEXES:
        cur.execute(stmt)
    cur.execute(LOAD_HISTORY_TABLE_SQL)
    conn.commit()
    conn.close()
    print("Schema is ready ({}).".format(db_path))


def cmd_load_static(args, db_path, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    for prefix, table_name, desc in STATIC_FILES.values():
        print("== {} ({}) ==".format(desc, cycle_label(cycle_year)))
        zip_name, zip_path, txt_path = fetch_and_extract(prefix, cycle_year, download_dir)
        load_static_table(db_path, table_name, txt_path, zip_name, cycle_label(cycle_year))
        if not args.keep_downloads:
            cleanup_download(zip_path, txt_path)


def cmd_load_indiv(args, db_path, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    prefix, table_name, desc = INDIV_FILE
    print("== {} ({}) ==".format(desc, cycle_label(cycle_year)))
    zip_name, zip_path, txt_path = fetch_and_extract(prefix, cycle_year, download_dir)
    load_indiv_table(db_path, txt_path, zip_name, cycle_label(cycle_year))
    if not args.keep_downloads:
        cleanup_download(zip_path, txt_path)


def cmd_load_all(args, db_path, download_dir, openfec_cfg):
    cmd_load_static(args, db_path, download_dir, openfec_cfg)
    cmd_load_indiv(args, db_path, download_dir, openfec_cfg)


def cmd_sync_indiv(args, db_path, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    print("== Contributions by Individuals -- OpenFEC API sync ({}) ==".format(
        cycle_label(cycle_year)))
    sync_indiv_via_api(
        db_path, openfec_cfg, cycle_year,
        per_page=args.per_page, overlap=args.overlap,
        max_pages=args.max_pages, allow_full_sync=args.allow_full_sync,
    )


def cmd_inspect_schedule_a(args, db_path, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    api_key = openfec_cfg.get("api_key")
    if not api_key:
        raise RuntimeError(
            "No OpenFEC API key configured. Get a free key at "
            "https://api.data.gov/signup/ and put it in config.ini under "
            "[openfec] api_key = ..."
        )
    session = requests.Session()
    page = fetch_schedule_a_page(session, api_key, cycle_year, per_page=1,
                                  last_index=None)
    results = page.get("results", [])
    if not results:
        print("No records returned for cycle {}.".format(cycle_year))
        return
    record = results[0]
    print("Raw fields returned by OpenFEC for one schedule_a record "
          "(cycle {}):\n".format(cycle_year))
    for key in sorted(record.keys()):
        print("  {:<32} {!r}".format(key, record[key]))
    print("\nCurrent SCHEDULE_A_FIELD_ALIASES mapping in fec_loader_sqlite.py "
          "resolves as follows for this record:")
    for col, aliases in SCHEDULE_A_FIELD_ALIASES.items():
        key, value = resolve_field(record, aliases)
        status = "OK  " if key else "MISS"
        print("  [{}] {:<18} <- {:<28} {!r}".format(
            status, col, key or "(none of {})".format(aliases), value))


def cmd_status(args, db_path, download_dir, openfec_cfg):
    conn = get_connection(db_path)
    cur = conn.cursor()
    print("Row counts:")
    for table in ("candidate_master", "committee_master",
                   "candidate_committee_linkage", "indiv_contributions"):
        cur.execute("SELECT COUNT(*) FROM {}".format(table))
        print("  {:<28} {:>15,}".format(table, cur.fetchone()[0]))
    print("\nRecent load history:")
    cur.execute(
        "SELECT load_batch_id, table_name, source_file, election_cycle, "
        "rows_in_file, rows_inserted, started_at, finished_at, status "
        "FROM load_history ORDER BY load_batch_id DESC LIMIT 15"
    )
    for row in cur.fetchall():
        print("  {}".format(row))
    conn.close()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def build_arg_parser():
    p = argparse.ArgumentParser(
        description="Load FEC bulk data into SQLite via the sqlite3 CLI's .import."
    )
    p.add_argument("--config", default="config.ini", help="Path to config.ini")
    p.add_argument("--db-path", default=None, help="Path to the SQLite database file")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create the database file and tables (idempotent).")

    sp = sub.add_parser("load-static",
                         help="Download+reload Candidate Master, Committee "
                              "Master and Candidate-Committee Linkages from scratch.")
    sp.add_argument("--cycle", type=int, default=None,
                     help="Election cycle end year, e.g. 2026 (default: current cycle).")
    sp.add_argument("--keep-downloads", action="store_true",
                     help="Don't delete the downloaded zip/extracted flat "
                          "file after a successful load (deleted by default).")

    sp = sub.add_parser("load-indiv",
                         help="Download Contributions by Individuals and "
                              "incrementally add new rows (by SUB_ID).")
    sp.add_argument("--cycle", type=int, default=None,
                     help="Election cycle end year, e.g. 2026 (default: current cycle).")
    sp.add_argument("--keep-downloads", action="store_true",
                     help="Don't delete the downloaded zip/extracted flat "
                          "file after a successful load (deleted by default).")

    sp = sub.add_parser("load-all", help="Run load-static then load-indiv.")
    sp.add_argument("--cycle", type=int, default=None)
    sp.add_argument("--keep-downloads", action="store_true",
                     help="Don't delete downloaded zip/extracted flat files "
                          "after a successful load (deleted by default).")

    sp = sub.add_parser(
        "sync-indiv",
        help="Top up Contributions by Individuals via the OpenFEC API "
             "instead of re-downloading the whole bulk file. Requires an "
             "initial load-indiv run first (or --allow-full-sync).")
    sp.add_argument("--cycle", type=int, default=None,
                     help="Election cycle end year, e.g. 2026 (default: current cycle).")
    sp.add_argument("--per-page", type=int, default=100,
                     help="Records per API page (max 100). Default: 100.")
    sp.add_argument("--overlap", type=int, default=2000,
                     help="Re-fetch this many rows before your highest known "
                          "SUB_ID as a safety margin (cheap, deduped via "
                          "the sub_id PRIMARY KEY's ON CONFLICT IGNORE). "
                          "Default: 2000.")
    sp.add_argument("--max-pages", type=int, default=None,
                     help="Stop after this many pages (default: no limit).")
    sp.add_argument("--allow-full-sync", action="store_true",
                     help="Allow syncing a cycle with no existing rows from "
                          "scratch via the API (slow). Normally you should "
                          "run load-indiv first instead.")

    sp = sub.add_parser(
        "inspect-schedule-a",
        help="Fetch one record from the OpenFEC schedule_a endpoint and "
             "print its raw fields, to sanity-check the field mapping "
             "used by sync-indiv before relying on it.")
    sp.add_argument("--cycle", type=int, default=None)

    sub.add_parser("status", help="Show row counts and recent load history.")

    return p


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    db_path, download_dir, openfec_cfg = load_config(args.config)
    db_path = apply_cli_overrides(db_path, args)

    commands = {
        "setup": cmd_setup,
        "load-static": cmd_load_static,
        "load-indiv": cmd_load_indiv,
        "load-all": cmd_load_all,
        "sync-indiv": cmd_sync_indiv,
        "inspect-schedule-a": cmd_inspect_schedule_a,
        "status": cmd_status,
    }

    try:
        commands[args.command](args, db_path, download_dir, openfec_cfg)
    except sqlite3.Error as e:
        print("SQLite error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
