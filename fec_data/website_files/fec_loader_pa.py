#!/usr/bin/env python3
"""
fec_loader_pa.py

PythonAnywhere deployment variant of fec_loader_sqlite.py, adapted for
the Patriotic Millionaires donor-lookup app:

  - indiv_contributions is trimmed to only the columns the app and the
    indiv_m rebuild actually use (plus zip_code and loader bookkeeping)
    -- see schema_pa.sql for the exact column list and rationale.
  - Adds ngp_contacts (the membership list) and indiv_m (a precomputed
    join of ngp_contacts x indiv_contributions, matched by
    indiv_contributions.name LIKE ngp_contacts.match_name), with two
    ways to keep indiv_m current:
      - rebuild-indiv-m: full rescan (DELETE + re-INSERT everything).
        Expensive -- use after a bulk historical load or a large
        change to ngp_contacts.
      - update-indiv-m: incremental. Tracks the highest
        indiv_contributions.load_batch_id already folded into indiv_m
        (in indiv_m_state), stages only newer rows in a temp table,
        and joins *that* against ngp_contacts -- appending new matches
        instead of rescanning the whole table. This is what nightly
        runs use, since a nightly top-up only adds a small number of
        rows and a full rescan every night would waste CPU quota.
  - Designed to run within PythonAnywhere's daily CPU-second quota:
    load-static/load-indiv/load-all/rebuild-indiv-m are meant to be run
    incrementally (e.g. one cycle at a time, via a scheduled task),
    not all at once.
  - load-indiv normally leaves indiv_contributions' secondary indexes
    in place and lets SQLite maintain them incrementally as new rows
    are inserted -- fine for a small nightly top-up. Pass --bulk for a
    large historical cycle backfill: this drops the indexes before the
    import for a much faster bulk load, but leaves them dropped
    afterward -- follow up with rebuild-indiv-indexes, which rebuilds
    them one at a time (each in its own sqlite3 process) so peak
    memory stays bounded instead of accumulating across all of them in
    one long-running process (which OOM-killed on a large table even
    with temp_store=FILE/cache_size capped).

Usage:
    python3 fec_loader_pa.py setup
    python3 fec_loader_pa.py load-static        [--cycle 2026]
    python3 fec_loader_pa.py load-indiv         [--cycle 2026] [--bulk]
    python3 fec_loader_pa.py load-all           [--cycle 2026] [--bulk]
    python3 fec_loader_pa.py rebuild-indiv-indexes
    python3 fec_loader_pa.py rebuild-indiv-m
    python3 fec_loader_pa.py update-indiv-m
    python3 fec_loader_pa.py nightly-update     [--cycle 2026]
    python3 fec_loader_pa.py status

`nightly-update` is what the scheduled task runs: load-indiv for the
given cycle (default: current cycle), then update-indiv-m (incremental).

Configuration is read from config.ini (see config.ini.example) or
overridden with --db-path.
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
# FEC bulk file definitions
# --------------------------------------------------------------------------

BASE_URL = "https://www.fec.gov/files/bulk-downloads/{year}/{prefix}{yy}.zip"

STATIC_FILES = {
    "cn":  ("cn",  "candidate_master",             "Candidate Master"),
    "cm":  ("cm",  "committee_master",             "Committee Master"),
}

INDIV_FILE = ("indiv", "indiv_contributions", "Contributions by Individuals")

EXPECTED_INNER_NAME = {
    "cn": "cn.txt",
    "cm": "cm.txt",
    "indiv": "itcont.txt",
}


# --------------------------------------------------------------------------
# Schema (kept in sync with schema_pa.sql)
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
            cmte_filing_freq     TEXT,
            org_tp               TEXT,
            connected_org_nm     TEXT,
            cand_id              TEXT
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
}

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
}

INDIV_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS indiv_contributions (
        cmte_id           TEXT,
        name              TEXT,
        city              TEXT,
        state             TEXT,
        zip_code          TEXT,
        employer          TEXT,
        transaction_dt    TEXT,
        transaction_amt   REAL,
        sub_id            INTEGER PRIMARY KEY ON CONFLICT IGNORE,
        election_cycle    TEXT,
        source_file       TEXT,
        load_batch_id     INTEGER,
        loaded_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

INDIV_INDEX_DEFS = {
    "idx_indiv_cmte_id": "cmte_id",
    "idx_indiv_name": "name",
    "idx_indiv_transaction_dt": "transaction_dt",
    "idx_indiv_zip_code": "zip_code",
    "idx_indiv_election_cycle": "election_cycle",
    "idx_indiv_load_batch_id": "load_batch_id",
}
INDIV_INDEXES = [
    "CREATE INDEX IF NOT EXISTS {} ON indiv_contributions ({});".format(n, c)
    for n, c in INDIV_INDEX_DEFS.items()
]
INDIV_INDEX_DROPS = ["DROP INDEX IF EXISTS {};".format(n) for n in INDIV_INDEX_DEFS]

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

NGP_CONTACTS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS ngp_contacts (
        last_name   TEXT,
        first_name  TEXT,
        city        TEXT,
        state       TEXT,
        match_name  TEXT,
        priv        INTEGER,
        pub         INTEGER,
        mem         INTEGER,
        prospect    INTEGER
    );
"""

INDIV_M_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS indiv_m (
        last_name       TEXT,
        first_name      TEXT,
        city            TEXT,
        state           TEXT,
        match_name      TEXT,
        priv            INTEGER,
        pub             INTEGER,
        mem             INTEGER,
        prospect        INTEGER,
        fec_name        TEXT,
        fec_city        TEXT,
        fec_state       TEXT,
        fec_employer    TEXT,
        committee_id    TEXT,
        trans_amount    REAL,
        trans_date      TEXT
    );
"""

# Tracks the highest indiv_contributions.load_batch_id already folded
# into indiv_m, so update_indiv_m() only has to look at rows added
# since the last update instead of rescanning the whole (growing)
# table against every ngp_contacts pattern each time.
INDIV_M_STATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS indiv_m_state (
        id                  INTEGER PRIMARY KEY CHECK (id = 1),
        last_load_batch_id  INTEGER NOT NULL DEFAULT 0
    );
"""


# --------------------------------------------------------------------------
# Config / connection helpers
# --------------------------------------------------------------------------

def load_config(path):
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path)
    db_path = cfg.get("sqlite", "db_path", fallback="./fec_pa.db")
    download_dir = cfg.get("download", "dest_dir", fallback="./fec_downloads")
    return db_path, download_dir


def get_connection(db_path):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    return sqlite3.connect(db_path)


def check_sqlite_cli():
    if shutil.which("sqlite3") is None:
        raise RuntimeError(
            "The 'sqlite3' command-line tool was not found on PATH."
        )


def sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_sqlite_cli(db_path, script):
    check_sqlite_cli()
    proc = subprocess.run(
        ["sqlite3", db_path], input=script, text=True, capture_output=True,
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
# Cycle handling
# --------------------------------------------------------------------------

def current_cycle_year():
    year = datetime.now().year
    return year if year % 2 == 0 else year + 1


def cycle_label(cycle_year):
    return "{}-{}".format(cycle_year - 1, cycle_year)


# --------------------------------------------------------------------------
# Download / extract
# --------------------------------------------------------------------------

def download_file(url, dest_path, max_retries=5):
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
                            if pct != last_pct and pct % 20 == 0:
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


def load_indiv_table(db_path, txt_path, source_file, election_cycle, bulk=False):
    """bulk=True drops the secondary indexes before the import (fast bulk
    load, but leaves indiv_contributions without them until a separate
    'rebuild-indiv-indexes' call) -- use for big historical cycle
    backfills. bulk=False (the default, used by nightly-update) leaves
    the indexes in place and lets SQLite maintain them incrementally as
    the new rows are inserted, which is fine for a small nightly top-up
    and keeps the live app's indexes always present."""
    table_name = INDIV_FILE[1]
    rows_in_file = count_lines(txt_path)

    conn = get_connection(db_path)
    cur = conn.cursor()
    batch_id = start_batch(cur, table_name, source_file, election_cycle, rows_in_file)
    conn.commit()
    conn.close()

    utf8_path = recode_latin1_to_utf8(txt_path)
    try:
        # Raw FEC field order for itcont.txt (21 fields); we only keep a
        # subset in the real table, so stage the raw file first, then
        # SELECT just the columns we want into indiv_contributions.
        script = """
.bail on
.output /dev/null
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=FILE;
PRAGMA cache_size=-20000;
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
    (cmte_id, name, city, state, zip_code, employer, transaction_dt, transaction_amt,
     sub_id, election_cycle, source_file, load_batch_id)
SELECT
    cmte_id, name, city, state, zip_code, employer,
    CASE WHEN length(transaction_dt) = 8
         THEN substr(transaction_dt,5,4) || '-' || substr(transaction_dt,1,2) || '-' || substr(transaction_dt,3,2)
         ELSE NULL END,
    NULLIF(transaction_amt, ''),
    sub_id, {cycle}, {source}, {batch_id}
FROM stg_indiv;
DROP TABLE stg_indiv;
""".format(indiv_table=INDIV_TABLE_SQL, path=utf8_path,
           index_drops="\n".join(INDIV_INDEX_DROPS) if bulk else "",
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
    if bulk:
        print("  (secondary indexes were dropped for this bulk load -- run "
              "'rebuild-indiv-indexes' to rebuild them.)")


def rebuild_indiv_indexes(db_path):
    """Rebuilds the secondary indexes on indiv_contributions one at a
    time, each in its own sqlite3 subprocess. load_indiv_table() drops
    all of them before every cycle load (cheap, since DROP is instant)
    but no longer rebuilds them in that same script -- building all 5
    back-to-back in one long-running process let memory pressure
    accumulate across indexes (each CREATE INDEX needs its own
    temp-sort space) and got OOM-killed partway through on a large
    table even with temp_store=FILE/cache_size capped. A fresh process
    per index releases that memory in between, keeping peak usage
    roughly constant regardless of how many indexes are left to build."""
    print("Rebuilding indiv_contributions secondary indexes, one at a time ...")
    for name, column in INDIV_INDEX_DEFS.items():
        start = time.time()
        script = """
.bail on
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=FILE;
PRAGMA cache_size=-20000;
CREATE INDEX IF NOT EXISTS {name} ON indiv_contributions ({column});
""".format(name=name, column=column)
        run_sqlite_cli(db_path, script)
        print("  {}: done ({:.0f}s).".format(name, time.time() - start))
    print("  All secondary indexes rebuilt.")


def rebuild_indiv_m(db_path):
    """Rebuilds indiv_m from scratch: every ngp_contacts member joined
    against every indiv_contributions row whose name matches that
    member's match_name pattern. This is the expensive step (a LIKE
    join with a per-row pattern can't use an index), which is exactly
    why indiv_m is precomputed instead of running this at request time."""
    print("Rebuilding indiv_m ...")
    start = time.time()
    script = """
.bail on
.output /dev/null
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
{indiv_m_table}
{indiv_m_state_table}
DELETE FROM indiv_m;
INSERT INTO indiv_m
    (last_name, first_name, city, state, match_name, priv, pub, mem, prospect,
     fec_name, fec_city, fec_state, fec_employer, committee_id, trans_amount, trans_date)
SELECT
    m.last_name, m.first_name, m.city, m.state, m.match_name,
    m.priv, m.pub, m.mem, m.prospect,
    d.name, d.city, d.state, d.employer, d.cmte_id, d.transaction_amt, d.transaction_dt
FROM ngp_contacts m
JOIN indiv_contributions d ON d.name LIKE m.match_name;
INSERT INTO indiv_m_state (id, last_load_batch_id)
    VALUES (1, (SELECT COALESCE(MAX(load_batch_id), 0) FROM indiv_contributions))
    ON CONFLICT (id) DO UPDATE SET last_load_batch_id = excluded.last_load_batch_id;
""".format(indiv_m_table=INDIV_M_TABLE_SQL, indiv_m_state_table=INDIV_M_STATE_TABLE_SQL)
    run_sqlite_cli(db_path, script)
    elapsed = time.time() - start

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM indiv_m")
    n = cur.fetchone()[0]
    conn.close()
    print("  indiv_m: {} rows ({:.0f}s).".format(n, elapsed))


def update_indiv_m(db_path):
    """Incremental counterpart to rebuild_indiv_m(): instead of
    rescanning the whole (and ever-growing) indiv_contributions table
    against every ngp_contacts pattern, this only looks at rows added
    since the last rebuild/update (tracked via indiv_m_state), stages
    just those rows in a temp table, and joins *that* against
    ngp_contacts -- appending new matches to indiv_m rather than
    replacing it. This is what the nightly scheduled task runs, since
    a nightly top-up only adds a small number of new rows and doing a
    full rebuild for that every night would waste CPU quota re-scanning
    everything already processed."""
    print("Updating indiv_m (incremental) ...")
    start = time.time()
    script = """
.bail on
.output /dev/null
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
{indiv_m_table}
{indiv_m_state_table}
INSERT OR IGNORE INTO indiv_m_state (id, last_load_batch_id) VALUES (1, 0);
DROP TABLE IF EXISTS stg_new_indiv;
CREATE TEMP TABLE stg_new_indiv AS
SELECT * FROM indiv_contributions
WHERE load_batch_id > (SELECT last_load_batch_id FROM indiv_m_state WHERE id = 1);
INSERT INTO indiv_m
    (last_name, first_name, city, state, match_name, priv, pub, mem, prospect,
     fec_name, fec_city, fec_state, fec_employer, committee_id, trans_amount, trans_date)
SELECT
    m.last_name, m.first_name, m.city, m.state, m.match_name,
    m.priv, m.pub, m.mem, m.prospect,
    d.name, d.city, d.state, d.employer, d.cmte_id, d.transaction_amt, d.transaction_dt
FROM ngp_contacts m
JOIN stg_new_indiv d ON d.name LIKE m.match_name;
UPDATE indiv_m_state SET last_load_batch_id =
    (SELECT COALESCE(MAX(load_batch_id), last_load_batch_id) FROM indiv_contributions)
    WHERE id = 1;
DROP TABLE stg_new_indiv;
""".format(indiv_m_table=INDIV_M_TABLE_SQL, indiv_m_state_table=INDIV_M_STATE_TABLE_SQL)
    run_sqlite_cli(db_path, script)
    elapsed = time.time() - start

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM indiv_m")
    n = cur.fetchone()[0]
    conn.close()
    print("  indiv_m: {} rows total ({:.0f}s).".format(n, elapsed))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_setup(args, db_path, download_dir):
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
    cur.execute(NGP_CONTACTS_TABLE_SQL)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ngp_match_name ON ngp_contacts (match_name);")
    cur.execute(INDIV_M_TABLE_SQL)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_indiv_m_match_name ON indiv_m (match_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_indiv_m_committee_id ON indiv_m (committee_id);")
    cur.execute(INDIV_M_STATE_TABLE_SQL)
    cur.execute("INSERT OR IGNORE INTO indiv_m_state (id, last_load_batch_id) VALUES (1, 0);")
    conn.commit()
    conn.close()
    print("Schema is ready ({}).".format(db_path))


def cmd_load_static(args, db_path, download_dir):
    cycle_year = args.cycle or current_cycle_year()
    for prefix, table_name, desc in STATIC_FILES.values():
        print("== {} ({}) ==".format(desc, cycle_label(cycle_year)))
        zip_name, zip_path, txt_path = fetch_and_extract(prefix, cycle_year, download_dir)
        load_static_table(db_path, table_name, txt_path, zip_name, cycle_label(cycle_year))
        if not args.keep_downloads:
            cleanup_download(zip_path, txt_path)


def cmd_load_indiv(args, db_path, download_dir):
    cycle_year = args.cycle or current_cycle_year()
    prefix, table_name, desc = INDIV_FILE
    print("== {} ({}) ==".format(desc, cycle_label(cycle_year)))
    zip_name, zip_path, txt_path = fetch_and_extract(prefix, cycle_year, download_dir)
    load_indiv_table(db_path, txt_path, zip_name, cycle_label(cycle_year),
                      bulk=getattr(args, "bulk", False))
    if not args.keep_downloads:
        cleanup_download(zip_path, txt_path)


def cmd_load_all(args, db_path, download_dir):
    cmd_load_static(args, db_path, download_dir)
    cmd_load_indiv(args, db_path, download_dir)


def cmd_rebuild_indiv_indexes(args, db_path, download_dir):
    rebuild_indiv_indexes(db_path)


def cmd_rebuild_indiv_m(args, db_path, download_dir):
    rebuild_indiv_m(db_path)


def cmd_update_indiv_m(args, db_path, download_dir):
    update_indiv_m(db_path)


def cmd_nightly_update(args, db_path, download_dir):
    cmd_load_indiv(args, db_path, download_dir)
    update_indiv_m(db_path)


def cmd_status(args, db_path, download_dir):
    conn = get_connection(db_path)
    cur = conn.cursor()
    print("Row counts:")
    for table in ("candidate_master", "committee_master",
                   "indiv_contributions", "ngp_contacts", "indiv_m"):
        cur.execute("SELECT COUNT(*) FROM {}".format(table))
        print("  {:<22} {:>15,}".format(table, cur.fetchone()[0]))
    cur.execute("SELECT last_load_batch_id FROM indiv_m_state WHERE id = 1")
    row = cur.fetchone()
    print("  indiv_m_state.last_load_batch_id: {}".format(row[0] if row else "(unset)"))
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
        description="Load FEC bulk data + rebuild indiv_m for the PA donor-lookup app."
    )
    p.add_argument("--config", default="config.ini")
    p.add_argument("--db-path", default=None)

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create the database file and tables (idempotent).")

    for name, help_text in [
        ("load-static", "Download+reload Candidate Master and Committee Master."),
        ("load-indiv", "Download+incrementally load Contributions by Individuals."),
        ("load-all", "Run load-static then load-indiv."),
    ]:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--cycle", type=int, default=None,
                         help="Election cycle end year, e.g. 2026 (default: current cycle).")
        sp.add_argument("--keep-downloads", action="store_true")
        if name in ("load-indiv", "load-all"):
            sp.add_argument("--bulk", action="store_true",
                             help="Drop indiv_contributions' secondary indexes before "
                                  "the import for a faster bulk load (e.g. a historical "
                                  "cycle backfill). Follow up with 'rebuild-indiv-indexes' "
                                  "afterward. Without this flag (the default, used by "
                                  "nightly-update), indexes are left in place and "
                                  "maintained incrementally, which is fine for a small "
                                  "top-up and keeps the live app's indexes always present.")

    sub.add_parser("rebuild-indiv-indexes",
                    help="Rebuild the secondary indexes on indiv_contributions, one "
                         "at a time in separate sqlite3 processes (load-indiv drops "
                         "them before every cycle load but no longer rebuilds them "
                         "itself, to avoid OOM kills from building several at once).")

    sub.add_parser("rebuild-indiv-m",
                    help="Full rebuild of indiv_m from ngp_contacts + indiv_contributions "
                         "(rescans everything -- expensive; use after a bulk historical "
                         "load or a big change to ngp_contacts).")

    sub.add_parser("update-indiv-m",
                    help="Incremental indiv_m update: only joins indiv_contributions rows "
                         "added since the last rebuild/update, appending new matches.")

    sp = sub.add_parser("nightly-update",
                         help="load-indiv then update-indiv-m (incremental) -- what the "
                              "scheduled task runs.")
    sp.add_argument("--cycle", type=int, default=None)
    sp.add_argument("--keep-downloads", action="store_true")

    sub.add_parser("status", help="Show row counts and recent load history.")

    return p


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    db_path, download_dir = load_config(args.config)
    if args.db_path is not None:
        db_path = args.db_path

    commands = {
        "setup": cmd_setup,
        "load-static": cmd_load_static,
        "load-indiv": cmd_load_indiv,
        "load-all": cmd_load_all,
        "rebuild-indiv-indexes": cmd_rebuild_indiv_indexes,
        "rebuild-indiv-m": cmd_rebuild_indiv_m,
        "update-indiv-m": cmd_update_indiv_m,
        "nightly-update": cmd_nightly_update,
        "status": cmd_status,
    }

    try:
        commands[args.command](args, db_path, download_dir)
    except sqlite3.Error as e:
        print("SQLite error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
