#!/usr/bin/env python3
"""
fec_loader.py

Downloads FEC bulk data files (Candidate Master, Candidate-Committee
Linkages, Committee Master, Contributions by Individuals) and loads
them into a MySQL database using LOAD DATA LOCAL INFILE, with table
layouts that match the FEC flat files field-for-field.

    https://www.fec.gov/data/browse-data/?tab=bulk-data

Usage:
    python fec_loader.py setup
    python fec_loader.py load-static        [--cycle 2026]
    python fec_loader.py load-indiv         [--cycle 2026]
    python fec_loader.py load-all           [--cycle 2026]
    python fec_loader.py sync-indiv         [--cycle 2026]   (OpenFEC API top-up)
    python fec_loader.py inspect-schedule-a [--cycle 2026]   (sanity-check API fields)
    python fec_loader.py status

Configuration is read from config.ini (see config.ini.example) or can
be overridden with --host/--port/--user/--password/--database.

Requires:
    pip install mysql-connector-python requests

The MySQL server must have local_infile enabled:
    SET GLOBAL local_infile = 1;
(or set local-infile=1 in my.cnf)

--------------------------------------------------------------------
Design notes
--------------------------------------------------------------------
- Candidate Master, Candidate-Committee Linkages and Committee Master
  are small reference files. FEC only publishes "current state" bulk
  files for these (no history/delta files), so each run truncates and
  reloads them from scratch, as requested.

- Contributions by Individuals is enormous (tens of millions of rows
  per 2-year cycle) and FEC does not publish incremental/delta bulk
  files for it either -- the "indivNN.zip" for the current cycle is
  always a full extract as of download time. This script downloads
  that full extract every time you run load-indiv, but loads it with
  `LOAD DATA ... IGNORE INTO TABLE ...` keyed on SUB_ID (FEC's unique
  row id), so rows already present in your database are silently
  skipped and only genuinely new rows get inserted. That gives you
  "incremental" behavior at the database level even though the
  download itself is a full file. Each row is stamped with the
  election cycle and source zip file it came from (election_cycle,
  source_file, load_batch_id columns) so you can always tell which
  bulk file a given row was loaded from.

  For true bandwidth-efficient incremental pulls (only rows added since
  your last run, without re-downloading the whole cycle), use `sync-indiv`
  instead, which queries the OpenFEC API (https://api.open.fec.gov) for
  records past the highest SUB_ID you already have. Typical workflow:
  run `load-indiv` once for the initial full load of a cycle, then
  `sync-indiv` on a schedule to keep it current. See the OpenFEC section
  further down in this file for important caveats about that command.
"""

import argparse
import configparser
import os
import sys
import time
import zipfile
from datetime import datetime

import requests

try:
    import mysql.connector
    from mysql.connector import errorcode
except ImportError:
    print("This script requires mysql-connector-python: "
          "pip install mysql-connector-python", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------
# FEC bulk file definitions
# --------------------------------------------------------------------------

BASE_URL = "https://www.fec.gov/files/bulk-downloads/{year}/{prefix}{yy}.zip"

# name -> (url prefix, table name, human description)
STATIC_FILES = {
    "cn":  ("cn",  "candidate_master",             "Candidate Master"),
    "cm":  ("cm",  "committee_master",             "Committee Master"),
    "ccl": ("ccl", "candidate_committee_linkage",  "Candidate-Committee Linkages"),
}

INDIV_FILE = ("indiv", "indiv_contributions", "Contributions by Individuals")

# The .zip for each bulk file contains one authoritative top-level data
# file. Some zips (notably indivNN.zip) *also* contain a "by_date/"
# subfolder with the exact same data pre-split into several smaller
# date-range chunks (their sizes sum to the same total as the top-level
# file) -- that's a convenience for tools that can't open one huge file,
# not additional data. We always load the single top-level file below and
# ignore the by_date/ split so nothing gets double-loaded.
EXPECTED_INNER_NAME = {
    "cn": "cn.txt",
    "cm": "cm.txt",
    "ccl": "ccl.txt",
    "indiv": "itcont.txt",
}


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS candidate_master (
        cand_id                 VARCHAR(9)   NOT NULL,
        cand_name                VARCHAR(200),
        cand_pty_affiliation     VARCHAR(3),
        cand_election_yr         SMALLINT UNSIGNED,
        cand_office_st           VARCHAR(2),
        cand_office               VARCHAR(1),
        cand_office_district      VARCHAR(2),
        cand_ici                  VARCHAR(1),
        cand_status                VARCHAR(1),
        cand_pcc                   VARCHAR(9),
        cand_st1                   VARCHAR(34),
        cand_st2                   VARCHAR(34),
        cand_city                  VARCHAR(30),
        cand_st                    VARCHAR(2),
        cand_zip                   VARCHAR(9),
        PRIMARY KEY (cand_id),
        INDEX idx_cand_pcc (cand_pcc),
        INDEX idx_cand_office_st (cand_office_st, cand_office)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS committee_master (
        cmte_id                 VARCHAR(9)   NOT NULL,
        cmte_nm                  VARCHAR(200),
        tres_nm                  VARCHAR(90),
        cmte_st1                  VARCHAR(34),
        cmte_st2                  VARCHAR(34),
        cmte_city                 VARCHAR(30),
        cmte_st                   VARCHAR(2),
        cmte_zip                  VARCHAR(9),
        cmte_dsgn                  VARCHAR(1),
        cmte_tp                    VARCHAR(1),
        cmte_pty_affiliation       VARCHAR(3),
        cmte_filing_freq           VARCHAR(1),
        org_tp                     VARCHAR(1),
        connected_org_nm           VARCHAR(200),
        cand_id                    VARCHAR(9),
        PRIMARY KEY (cmte_id),
        INDEX idx_cand_id (cand_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS candidate_committee_linkage (
        cand_id               VARCHAR(9)  NOT NULL,
        cand_election_yr       SMALLINT UNSIGNED NOT NULL,
        fec_election_yr         SMALLINT UNSIGNED NOT NULL,
        cmte_id                  VARCHAR(9),
        cmte_tp                  VARCHAR(1),
        cmte_dsgn                 VARCHAR(1),
        linkage_id                 BIGINT UNSIGNED NOT NULL,
        PRIMARY KEY (linkage_id),
        INDEX idx_cand_id (cand_id),
        INDEX idx_cmte_id (cmte_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS indiv_contributions (
        cmte_id                 VARCHAR(9),
        amndt_ind                 VARCHAR(1),
        rpt_tp                     VARCHAR(3),
        transaction_pgi             VARCHAR(5),
        image_num                    VARCHAR(18),
        transaction_tp                VARCHAR(3),
        entity_tp                      VARCHAR(3),
        name                             VARCHAR(200),
        city                              VARCHAR(30),
        state                              VARCHAR(2),
        zip_code                           VARCHAR(9),
        employer                            VARCHAR(38),
        occupation                           VARCHAR(38),
        transaction_dt                        DATE,
        transaction_amt                        DECIMAL(14,2),
        other_id                                VARCHAR(9),
        tran_id                                  VARCHAR(32),
        file_num                                  BIGINT UNSIGNED,
        memo_cd                                    VARCHAR(1),
        memo_text                                   VARCHAR(100),
        sub_id                                       BIGINT UNSIGNED NOT NULL,
        -- extra bookkeeping columns, not part of the FEC file, used to
        -- support incremental loading:
        election_cycle    VARCHAR(9)   NULL,
        source_file       VARCHAR(60)  NULL,
        load_batch_id     INT          NULL,
        loaded_at         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (sub_id),
        INDEX idx_cmte_id (cmte_id),
        INDEX idx_name (name(40)),
        INDEX idx_transaction_dt (transaction_dt),
        INDEX idx_zip_code (zip_code),
        INDEX idx_election_cycle (election_cycle)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS load_history (
        load_batch_id   INT AUTO_INCREMENT PRIMARY KEY,
        table_name      VARCHAR(60)  NOT NULL,
        source_file     VARCHAR(120) NOT NULL,
        election_cycle  VARCHAR(9)   NULL,
        rows_in_file    BIGINT       NULL,
        rows_inserted   BIGINT       NULL,
        started_at      DATETIME     NOT NULL,
        finished_at     DATETIME     NULL,
        status          VARCHAR(20)  NOT NULL DEFAULT 'running'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
]


# --------------------------------------------------------------------------
# Config / connection helpers
# --------------------------------------------------------------------------

def load_config(path):
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path)
    mysql_cfg = {
        "host": cfg.get("mysql", "host", fallback="127.0.0.1"),
        "port": cfg.getint("mysql", "port", fallback=3306),
        "user": cfg.get("mysql", "user", fallback="root"),
        "password": cfg.get("mysql", "password", fallback=""),
        "database": cfg.get("mysql", "database", fallback="fec"),
    }
    download_dir = cfg.get("download", "dest_dir", fallback="./fec_downloads")
    openfec_cfg = {
        "api_key": cfg.get("openfec", "api_key", fallback=""),
    }
    return mysql_cfg, download_dir, openfec_cfg


def apply_cli_overrides(mysql_cfg, args):
    for key in ("host", "port", "user", "password", "database"):
        val = getattr(args, key, None)
        if val is not None:
            mysql_cfg[key] = val
    return mysql_cfg


def get_connection(mysql_cfg, database=True):
    kwargs = dict(
        host=mysql_cfg["host"],
        port=mysql_cfg["port"],
        user=mysql_cfg["user"],
        password=mysql_cfg["password"],
        allow_local_infile=True,
        autocommit=True,
    )
    if database:
        kwargs["database"] = mysql_cfg["database"]
    return mysql.connector.connect(**kwargs)


def ensure_database(mysql_cfg):
    conn = get_connection(mysql_cfg, database=False)
    cur = conn.cursor()
    cur.execute(
        "CREATE DATABASE IF NOT EXISTS `{}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci".format(
            mysql_cfg["database"]
        )
    )
    cur.close()
    conn.close()


def check_local_infile(conn):
    cur = conn.cursor()
    cur.execute("SHOW VARIABLES LIKE 'local_infile'")
    row = cur.fetchone()
    cur.close()
    if row and row[1] != "ON":
        print(
            "WARNING: the MySQL server variable 'local_infile' is OFF.\n"
            "  Run this on the server (as an admin) before loading data:\n"
            "      SET GLOBAL local_infile = 1;\n"
            "  or add 'local-infile=1' under [mysqld] in my.cnf and restart.",
            file=sys.stderr,
        )


def relax_sql_mode(cur):
    """Loosen strict mode for the session so odd/legacy FEC rows (blank
    dates, occasional overlong fields, etc.) become warnings instead of
    hard failures during LOAD DATA."""
    cur.execute(
        "SET SESSION sql_mode = "
        "REPLACE(REPLACE(@@sql_mode, 'STRICT_TRANS_TABLES', ''), "
        "'STRICT_ALL_TABLES', '')"
    )


# --------------------------------------------------------------------------
# Cycle handling
# --------------------------------------------------------------------------

def current_cycle_year():
    """FEC 2-year cycles are labeled by their ending (even) year, e.g.
    the 2025-2026 cycle is '2026'."""
    year = datetime.now().year
    return year if year % 2 == 0 else year + 1


def cycle_label(cycle_year):
    return "{}-{}".format(cycle_year - 1, cycle_year)


# --------------------------------------------------------------------------
# Download / extract
# --------------------------------------------------------------------------

def download_file(url, dest_path):
    print("  Downloading {} ...".format(url))
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


def extract_data_file(zip_path, extract_dir, expected_name=None):
    """Extracts the zip and returns the path to the single authoritative
    data file inside it, ignoring any "by_date/"-style split copies of
    the same data that some FEC zips (e.g. indivNN.zip) also include.

    Selection rule:
      1. If `expected_name` (e.g. "itcont.txt") exists as a *top-level*
         entry, use it.
      2. Otherwise, use the single top-level .txt/.csv entry, if there's
         exactly one.
      3. Otherwise, fail loudly rather than silently guessing -- picking
         the wrong file here would load partial data without any error.
    """
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
    return zip_name, txt_path


def count_lines(path):
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count


# --------------------------------------------------------------------------
# Load history bookkeeping
# --------------------------------------------------------------------------

def start_batch(cur, table_name, source_file, election_cycle, rows_in_file):
    cur.execute(
        "INSERT INTO load_history "
        "(table_name, source_file, election_cycle, rows_in_file, started_at, status) "
        "VALUES (%s, %s, %s, %s, %s, 'running')",
        (table_name, source_file, election_cycle, rows_in_file, datetime.now()),
    )
    return cur.lastrowid


def finish_batch(cur, batch_id, rows_inserted, status="success"):
    cur.execute(
        "UPDATE load_history SET rows_inserted=%s, finished_at=%s, status=%s "
        "WHERE load_batch_id=%s",
        (rows_inserted, datetime.now(), status, batch_id),
    )


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

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


def load_static_table(conn, table_name, txt_path, source_file, election_cycle):
    cur = conn.cursor()
    relax_sql_mode(cur)

    rows_in_file = count_lines(txt_path)
    batch_id = start_batch(cur, table_name, source_file, election_cycle, rows_in_file)

    print("  Truncating {} ...".format(table_name))
    cur.execute("TRUNCATE TABLE {}".format(table_name))

    columns = STATIC_LOAD_COLUMNS[table_name]
    sql = """
        LOAD DATA LOCAL INFILE %s
        INTO TABLE {table}
        CHARACTER SET latin1
        FIELDS TERMINATED BY '|'
        LINES TERMINATED BY '\\n'
        ({columns})
    """.format(table=table_name, columns=columns)

    print("  Loading into {} ...".format(table_name))
    cur.execute(sql, (txt_path,))
    cur.execute("SELECT ROW_COUNT()")
    rows_inserted = cur.fetchone()[0]

    finish_batch(cur, batch_id, rows_inserted)
    conn.commit()
    cur.close()
    print("  {}: {} rows loaded.".format(table_name, rows_inserted))


def load_indiv_table(conn, txt_path, source_file, election_cycle):
    table_name = INDIV_FILE[1]
    cur = conn.cursor()
    relax_sql_mode(cur)

    rows_in_file = count_lines(txt_path)
    batch_id = start_batch(cur, table_name, source_file, election_cycle, rows_in_file)

    # session variables consumed by the SET clause below
    cur.execute("SET @cycle_var = %s", (election_cycle,))
    cur.execute("SET @source_file_var = %s", (source_file,))
    cur.execute("SET @batch_id_var = %s", (batch_id,))

    sql = """
        LOAD DATA LOCAL INFILE %s
        IGNORE INTO TABLE indiv_contributions
        CHARACTER SET latin1
        FIELDS TERMINATED BY '|'
        LINES TERMINATED BY '\\n'
        (cmte_id, amndt_ind, rpt_tp, transaction_pgi, image_num,
         transaction_tp, entity_tp, name, city, state, zip_code,
         employer, occupation, @transaction_dt, transaction_amt,
         other_id, tran_id, file_num, memo_cd, memo_text, sub_id)
        SET
            transaction_dt = STR_TO_DATE(@transaction_dt, '%m%d%Y'),
            election_cycle = @cycle_var,
            source_file = @source_file_var,
            load_batch_id = @batch_id_var
    """

    print("  Loading into {} (existing SUB_IDs are skipped) ...".format(table_name))
    start = time.time()
    cur.execute(sql, (txt_path,))
    elapsed = time.time() - start
    cur.execute("SELECT ROW_COUNT()")
    rows_inserted = cur.fetchone()[0]

    finish_batch(cur, batch_id, rows_inserted)
    conn.commit()
    cur.close()
    print("  {}: {} new rows inserted out of {} rows in file ({:.0f}s).".format(
        table_name, rows_inserted, rows_in_file, elapsed))


# --------------------------------------------------------------------------
# OpenFEC API incremental sync (alternative to re-downloading the bulk file)
# --------------------------------------------------------------------------
#
# The bulk indivNN.zip is always a full extract -- there's no way to ask
# FEC's bulk endpoint for "just what's new." The OpenFEC API's schedule_a
# endpoint does support that, via seek-based pagination on a field called
# "index" that lines up with SUB_ID. We use it here to top up the table
# with only records newer than the highest SUB_ID we already have for a
# cycle, instead of re-downloading gigabytes of data we already loaded.
#
# IMPORTANT: this script could not verify OpenFEC's exact JSON field names
# against a live response in the environment it was written in (outbound
# access to api.open.fec.gov was blocked there). The mapping below is
# built from well-documented OpenFEC usage, but before you rely on
# `sync-indiv` for anything unattended, run:
#     python fec_loader.py inspect-schedule-a
# and eyeball the raw fields it prints. `sync-indiv` itself also validates
# the very first record it fetches against this mapping and refuses to
# proceed (loudly, before inserting anything) if an expected field is
# genuinely missing -- but a field that merely got *renamed* to something
# not in the alias list below could still slip through silently, so a
# manual look is worth it the first time you run this.

OPENFEC_SCHEDULE_A_URL = "https://api.open.fec.gov/v1/schedules/schedule_a/"

# our column -> list of candidate OpenFEC JSON field names, most-likely first
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
    """Checks the first fetched record against SCHEDULE_A_FIELD_ALIASES.
    Raises loudly on a genuine miss instead of silently inserting nulls
    into a financial dataset. Returns the resolved {our_col: json_key} map
    and prints a warning for any column that only matched a fallback
    (non-primary) alias, so you can double check it."""
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
            "Update SCHEDULE_A_FIELD_ALIASES in fec_loader.py to match, "
            "then re-run. (Run 'python fec_loader.py inspect-schedule-a' "
            "to see a full sample record.)".format(
                [c for c, _ in missing], sorted(sample_record.keys()))
        )
    print("  OpenFEC field mapping validated against sample record.")
    return resolved


def parse_schedule_a_date(value):
    """OpenFEC returns dates as ISO-ish strings (e.g. '2025-03-15' or
    '2025-03-15T00:00:00'), unlike the bulk file's MMDDYYYY. Returns a
    'YYYY-MM-DD' string MySQL will accept directly, or None."""
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


def sync_indiv_via_api(conn, openfec_cfg, cycle_year, per_page=100,
                        overlap=2000, max_pages=None, allow_full_sync=False):
    api_key = openfec_cfg.get("api_key")
    if not api_key:
        raise RuntimeError(
            "No OpenFEC API key configured. Get a free key at "
            "https://api.data.gov/signup/ and put it in config.ini under "
            "[openfec] api_key = ..."
        )

    election_cycle = cycle_label(cycle_year)
    cur = conn.cursor()

    cur.execute(
        "SELECT MAX(sub_id) FROM indiv_contributions WHERE election_cycle = %s",
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

    relax_sql_mode(cur)
    batch_id = start_batch(cur, "indiv_contributions", "openfec-api",
                            election_cycle, None)
    conn.commit()

    insert_sql = "INSERT IGNORE INTO indiv_contributions ({}) VALUES ({})".format(
        ", ".join(INDIV_API_INSERT_COLUMNS),
        ", ".join(["%s"] * len(INDIV_API_INSERT_COLUMNS)),
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
            cur.execute("SELECT ROW_COUNT()")
            page_inserted = cur.fetchone()[0]
            # ROW_COUNT() after a rewritten multi-row INSERT ... IGNORE
            # reports affected rows for that statement only.
            total_inserted += max(page_inserted, 0)
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
        cur.close()

    print("  Done: {} records fetched from the API, {} new rows inserted "
          "(rest were already present).".format(total_seen, total_inserted))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_setup(args, mysql_cfg, download_dir, openfec_cfg):
    ensure_database(mysql_cfg)
    conn = get_connection(mysql_cfg)
    check_local_infile(conn)
    cur = conn.cursor()
    for stmt in SCHEMA_STATEMENTS:
        cur.execute(stmt)
    conn.commit()
    cur.close()
    conn.close()
    print("Schema is ready.")


def cmd_load_static(args, mysql_cfg, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    conn = get_connection(mysql_cfg)
    check_local_infile(conn)
    for prefix, table_name, desc in STATIC_FILES.values():
        print("== {} ({}) ==".format(desc, cycle_label(cycle_year)))
        zip_name, txt_path = fetch_and_extract(prefix, cycle_year, download_dir)
        load_static_table(conn, table_name, txt_path, zip_name, cycle_label(cycle_year))
    conn.close()


def cmd_load_indiv(args, mysql_cfg, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    prefix, table_name, desc = INDIV_FILE
    print("== {} ({}) ==".format(desc, cycle_label(cycle_year)))
    conn = get_connection(mysql_cfg)
    check_local_infile(conn)
    zip_name, txt_path = fetch_and_extract(prefix, cycle_year, download_dir)
    load_indiv_table(conn, txt_path, zip_name, cycle_label(cycle_year))
    conn.close()


def cmd_load_all(args, mysql_cfg, download_dir, openfec_cfg):
    cmd_load_static(args, mysql_cfg, download_dir, openfec_cfg)
    cmd_load_indiv(args, mysql_cfg, download_dir, openfec_cfg)


def cmd_sync_indiv(args, mysql_cfg, download_dir, openfec_cfg):
    cycle_year = args.cycle or current_cycle_year()
    print("== Contributions by Individuals -- OpenFEC API sync ({}) ==".format(
        cycle_label(cycle_year)))
    conn = get_connection(mysql_cfg)
    sync_indiv_via_api(
        conn, openfec_cfg, cycle_year,
        per_page=args.per_page, overlap=args.overlap,
        max_pages=args.max_pages, allow_full_sync=args.allow_full_sync,
    )
    conn.close()


def cmd_inspect_schedule_a(args, mysql_cfg, download_dir, openfec_cfg):
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
    print("\nCurrent SCHEDULE_A_FIELD_ALIASES mapping in fec_loader.py "
          "resolves as follows for this record:")
    for col, aliases in SCHEDULE_A_FIELD_ALIASES.items():
        key, value = resolve_field(record, aliases)
        status = "OK  " if key else "MISS"
        print("  [{}] {:<18} <- {:<28} {!r}".format(
            status, col, key or "(none of {})".format(aliases), value))


def cmd_status(args, mysql_cfg, download_dir, openfec_cfg):
    conn = get_connection(mysql_cfg)
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
    cur.close()
    conn.close()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def build_arg_parser():
    p = argparse.ArgumentParser(description="Load FEC bulk data into MySQL.")
    p.add_argument("--config", default="config.ini", help="Path to config.ini")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--user", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--database", default=None)

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create the database and tables (idempotent).")

    sp = sub.add_parser("load-static",
                         help="Download+reload Candidate Master, Committee "
                              "Master and Candidate-Committee Linkages from scratch.")
    sp.add_argument("--cycle", type=int, default=None,
                     help="Election cycle end year, e.g. 2026 (default: current cycle).")

    sp = sub.add_parser("load-indiv",
                         help="Download Contributions by Individuals and "
                              "incrementally add new rows (by SUB_ID).")
    sp.add_argument("--cycle", type=int, default=None,
                     help="Election cycle end year, e.g. 2026 (default: current cycle).")

    sp = sub.add_parser("load-all", help="Run load-static then load-indiv.")
    sp.add_argument("--cycle", type=int, default=None)

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
                          "SUB_ID as a safety margin (cheap, deduped by "
                          "INSERT IGNORE). Default: 2000.")
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

    mysql_cfg, download_dir, openfec_cfg = load_config(args.config)
    mysql_cfg = apply_cli_overrides(mysql_cfg, args)

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
        commands[args.command](args, mysql_cfg, download_dir, openfec_cfg)
    except mysql.connector.Error as e:
        print("MySQL error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
