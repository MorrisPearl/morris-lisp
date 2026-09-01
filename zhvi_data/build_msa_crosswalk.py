#!/usr/bin/env python3
"""
build_msa_crosswalk.py

Matches Zillow metro-level ZHVI region names (e.g. "New York, NY") to
official OMB/Census CBSA codes (e.g. 35620), using the Census Bureau's
CBSA delineation file as ground truth.

Zillow's metro RegionName is always "<first principal city>, <first
state>" -- i.e. everything in the CBSA title after the first hyphen (in
the city part) or first hyphen (in the state part) is dropped. E.g. the
official CBSA title "New York-Newark-Jersey City, NY-NJ" becomes
Zillow's "New York, NY", and "Winston-Salem, NC" (a single city whose
own name contains a hyphen) becomes Zillow's "Winston, NC". This script
mirrors that same truncation rule when deriving a match key from each
CBSA title, so it works for both cases.

Usage:
    python build_msa_crosswalk.py --db zhvi.db --delineation list1_2023.xlsx
"""

import argparse
import csv
import sqlite3

import openpyxl

SCHEMA = """
CREATE TABLE IF NOT EXISTS msa_crosswalk (
    cbsa_code    INTEGER PRIMARY KEY,
    cbsa_title   TEXT NOT NULL,
    area_type    TEXT NOT NULL,   -- 'Metropolitan Statistical Area' or 'Micropolitan Statistical Area'
    zillow_name  TEXT             -- matching Zillow RegionName from the metro ZHVI file, if found
);
"""


def load_cbsas(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header_idx = next(i for i, r in enumerate(rows) if r[0] == "CBSA Code")
    cbsas = {}
    for row in rows[header_idx + 1:]:
        if not row[0]:
            continue
        if not str(row[0]).isdigit():
            break
        code = int(row[0])
        title = row[3]
        area_type = row[4]
        cbsas[code] = (title, area_type)
    return cbsas


def city_components(city_part):
    # Zillow keeps only one principal city, but doesn't always pick the
    # first one listed in the official title (e.g. "Massena-Ogdensburg, NY"
    # -> Zillow's "Ogdensburg, NY"), and drops sub-components like
    # "Louisville/Jefferson County" -> "Louisville". So every "-" or "/"
    # separated component is a candidate match, not just the first.
    parts = []
    for piece in city_part.replace("/", "-").split("-"):
        piece = piece.strip()
        if piece.lower().startswith("town of "):
            piece = piece[len("town of "):]
        if piece.lower().startswith("city of "):
            piece = piece[len("city of "):]
        parts.append(piece)
    return parts


ZILLOW_MOJIBAKE_FIX = str.maketrans({"±": "ñ"})  # Zillow's CSV corrupts n-tilde ('n') to plus-minus ('+/-')


def match_keys(title):
    city_part, state_part = title.split(",")
    state = state_part.strip().split("-")[0].strip()
    return [(city, state) for city in city_components(city_part)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--delineation", required=True, help="Path to the Census list1_YYYY.xlsx file")
    parser.add_argument("--metro-csv", required=True, help="Path to the Metro_zhvi_*.csv file")
    args = parser.parse_args()

    cbsas = load_cbsas(args.delineation)
    print(f"Loaded {len(cbsas)} CBSAs/Micropolitan areas from {args.delineation}")

    by_key = {}
    for code, (title, area_type) in cbsas.items():
        for key in match_keys(title):
            by_key.setdefault(key, set()).add(code)

    with open(args.metro_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        zillow_names = [row["RegionName"] for row in reader if row["RegionType"] == "msa"]

    matched = {}
    unmatched = []
    ambiguous = []
    for name in zillow_names:
        fixed_name = name.translate(ZILLOW_MOJIBAKE_FIX)
        city, state = fixed_name.split(",")
        key = (city.strip(), state.strip())
        candidates = by_key.get(key, set())
        if len(candidates) == 1:
            matched[next(iter(candidates))] = name
        elif len(candidates) == 0:
            unmatched.append(name)
        else:
            ambiguous.append((name, sorted(candidates)))

    print(f"Matched: {len(matched)} / {len(zillow_names)}")
    if unmatched:
        print(f"Unmatched ({len(unmatched)}):")
        for n in unmatched:
            print(f"  {n}")
    if ambiguous:
        print(f"Ambiguous ({len(ambiguous)}):")
        for n, cands in ambiguous:
            print(f"  {n} -> {cands}")

    conn = sqlite3.connect(args.db)
    conn.execute(SCHEMA)
    conn.execute("DELETE FROM msa_crosswalk")
    rows = [
        (code, title, area_type, matched.get(code))
        for code, (title, area_type) in cbsas.items()
    ]
    conn.executemany(
        "INSERT INTO msa_crosswalk (cbsa_code, cbsa_title, area_type, zillow_name) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"Wrote {len(rows)} rows to msa_crosswalk in {args.db}")
    conn.close()


if __name__ == "__main__":
    main()
