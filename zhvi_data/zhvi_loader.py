#!/usr/bin/env python3
"""
zhvi_loader.py

Loads Zillow ZHVI (Zillow Home Value Index) CSV exports into a single
SQLite table with one row per (geography, month) observation.

Each source CSV is "wide": one row per geography, one column per
month. This script reshapes that into a "long" table:

    type   TEXT     'Z' (zip), 'M' (MSA/metro), 'U' (United States)
    key    TEXT     zip code, CBSA code, or 'US', as appropriate
    date   TEXT     ISO date, YYYY-MM-01 (always the 1st of the month)
    value  INTEGER  ZHVI value, rounded to the nearest dollar

For 'M' (metro) rows, Key is the official Census/OMB CBSA code, not
Zillow's metro name -- this makes the table joinable against other
CBSA-coded datasets (e.g. Freddie Mac's loan-level MSA field). The
name -> CBSA code mapping comes from the msa_crosswalk table, so
build_msa_crosswalk.py must be run against this database first. A
metro with no current CBSA code (see build_msa_crosswalk.py's output)
is skipped here and recorded in unmatched_zillow_metros instead.

Usage:
    python build_msa_crosswalk.py --db zhvi.db \
        --delineation list1_2023.xlsx --metro-csv /path/to/Metro_zhvi_*.csv
    python zhvi_loader.py --db zhvi.db \
        --zip /path/to/Zip_zhvi_*.csv --metro /path/to/Metro_zhvi_*.csv
"""

import argparse
import csv
import re
import sqlite3
from pathlib import Path

DATE_COL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Zillow's RegionType values, mapped to this database's single-letter Type.
REGION_TYPE_MAP = {
    "zip": "Z",
    "msa": "M",
    "country": "U",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS zhvi (
    type  TEXT NOT NULL,
    key   TEXT NOT NULL,
    date  TEXT NOT NULL,
    value INTEGER,
    PRIMARY KEY (type, key, date)
);

CREATE TABLE IF NOT EXISTS unmatched_zillow_metros (
    zillow_region_id INTEGER PRIMARY KEY,
    zillow_name       TEXT NOT NULL
);
"""


def date_columns(fieldnames):
    return [f for f in fieldnames if DATE_COL_RE.match(f)]


def load_msa_crosswalk(conn):
    rows = conn.execute(
        "SELECT zillow_name, cbsa_code FROM msa_crosswalk WHERE zillow_name IS NOT NULL"
    ).fetchall()
    if not rows:
        raise RuntimeError(
            "msa_crosswalk table is empty or missing -- run build_msa_crosswalk.py first"
        )
    return {name: str(code) for name, code in rows}


def load_csv(path, conn, metro_key_map=None):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        date_cols = date_columns(reader.fieldnames)
        rows = []
        unmatched_metros = []
        skipped_types = set()
        for row in reader:
            region_type = row["RegionType"]
            type_code = REGION_TYPE_MAP.get(region_type)
            if type_code is None:
                skipped_types.add(region_type)
                continue
            name = row["RegionName"]
            if type_code == "M":
                key = metro_key_map.get(name)
                if key is None:
                    unmatched_metros.append((int(row["RegionID"]), name))
                    continue
            else:
                key = name
            for col in date_cols:
                raw = row[col]
                if not raw:
                    continue
                date = f"{col[:7]}-01"
                rows.append((type_code, key, date, round(float(raw))))
        conn.executemany(
            "INSERT OR REPLACE INTO zhvi (type, key, date, value) VALUES (?, ?, ?, ?)",
            rows,
        )
        if unmatched_metros:
            conn.executemany(
                "INSERT OR REPLACE INTO unmatched_zillow_metros (zillow_region_id, zillow_name) VALUES (?, ?)",
                unmatched_metros,
            )
            print(f"  {len(unmatched_metros)} metro(s) with no current CBSA code skipped (see unmatched_zillow_metros)")
        if skipped_types:
            print(f"  skipped unrecognized RegionType(s): {sorted(skipped_types)}")
        print(f"  {path.name}: {len(rows)} rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to the SQLite database to create/update")
    parser.add_argument("--zip", required=True, help="Path to the Zip_zhvi_*.csv file")
    parser.add_argument("--metro", required=True, help="Path to the Metro_zhvi_*.csv file")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    metro_key_map = load_msa_crosswalk(conn)

    print(f"Loading into {args.db}")
    conn.execute("DELETE FROM zhvi WHERE type = 'M'")
    load_csv(Path(args.zip), conn)
    load_csv(Path(args.metro), conn, metro_key_map=metro_key_map)

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM zhvi").fetchone()[0]
    print(f"Done. {total} total rows in zhvi table.")
    conn.close()


if __name__ == "__main__":
    main()
