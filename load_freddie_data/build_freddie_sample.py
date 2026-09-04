#!/usr/bin/env python3
"""
build_freddie_sample.py

Draws a random sample of loans from Freddie Mac's Single-Family Loan-Level
Dataset (origination + monthly performance files) and loads their full
performance history into a SQLite database, one row per loan-month.

Source layout
-------------
For each year, /Users/morris/freddie_data has one of:
  - historical_data_<YYYY>.zip, containing four nested
    historical_data_<YYYY>Qn.zip files, each containing
    orig_<YYYY>Qn.txt + perf_<YYYY>Qn.txt, OR
  - a historical_data_<YYYY>/ directory containing those same quarter zips
    directly, and/or the orig/perf .txt files already extracted.
This script handles all three forms transparently, and never extracts
anything to disk itself -- quarter zips are read into memory (typically
well under 1GB each) and the orig/perf text members are streamed
line-by-line from there.

Sampling
--------
For each orig_<YYYY>Qn.txt file, the random module is re-seeded with the
same fixed seed before that file's loans are walked in file order. Only
FRM (fixed-rate) loans are eligible; for each one, one random.random()
draw decides inclusion at the given --proportion. This makes the sample
for any single quarter independently reproducible.

Every performance-file row (loan-month) for a sampled loan is written to
the `loan_performance` table, joined against that loan's origination
characteristics (constant across all of its rows).

Usage
-----
    python3 build_freddie_sample.py --proportion 0.01 --db freddie_sample.db
    python3 build_freddie_sample.py --proportion 0.01 --db freddie_sample.db \\
        --start-year 2023 --end-year 2023   # quick test run
"""

import argparse
import io
import random
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ENCODING = "latin-1"
DEFAULT_SEED = 42

SCHEMA = """
CREATE TABLE IF NOT EXISTS loan_performance (
    loan_id                  TEXT NOT NULL,
    monthly_reporting_period TEXT NOT NULL,
    current_actual_upb       INTEGER,
    loan_age                 INTEGER,
    zero_flag                INTEGER NOT NULL,
    current_interest_rate    REAL,
    estimated_ltv            INTEGER,
    msa                      INTEGER,
    maturity_date            TEXT,
    num_units                INTEGER,
    occupancy_primary        INTEGER NOT NULL,
    occupancy_investment     INTEGER NOT NULL,
    orig_dti                 INTEGER,
    orig_upb                 INTEGER,
    orig_ltv                 INTEGER,
    orig_interest_rate       REAL,
    prepayment_penalty       INTEGER NOT NULL,
    property_type_co_cp      INTEGER NOT NULL,
    property_type_mh         INTEGER NOT NULL,
    property_type_pu         INTEGER NOT NULL,
    postal_code               TEXT,
    PRIMARY KEY (loan_id, monthly_reporting_period)
);
"""

INSERT_SQL = """
INSERT OR REPLACE INTO loan_performance (
    loan_id, monthly_reporting_period, current_actual_upb, loan_age, zero_flag,
    current_interest_rate, estimated_ltv, msa, maturity_date, num_units,
    occupancy_primary, occupancy_investment, orig_dti, orig_upb, orig_ltv,
    orig_interest_rate, prepayment_penalty, property_type_co_cp,
    property_type_mh, property_type_pu, postal_code
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

BATCH_SIZE = 20000

# --- Origination file field positions (0-indexed, 31 pipe-delimited fields) ---
O_MATURITY_DATE = 3
O_MSA = 4
O_NUM_UNITS = 6
O_OCCUPANCY = 7
O_DTI = 9
O_ORIG_UPB = 10
O_ORIG_LTV = 11
O_ORIG_RATE = 12
O_PPM_INDICATOR = 14
O_AMORTIZATION_TYPE = 15
O_PROPERTY_TYPE = 17
O_POSTAL_CODE = 18
O_LOAN_ID = 19

# --- Performance file field positions (0-indexed, 35 pipe-delimited fields) ---
P_LOAN_ID = 0
P_PERIOD = 1
P_CURRENT_UPB = 2
P_LOAN_AGE = 4
P_ZERO_BALANCE_EFFECTIVE_DATE = 9
P_CURRENT_RATE = 10
P_ELTV = 25


def to_date(yyyymm):
    if not yyyymm:
        return None
    return f"{yyyymm[:4]}-{yyyymm[4:6]}-01"


def na_int(raw, na_value):
    if not raw:
        return None
    v = int(raw)
    return None if v == na_value else v


def parse_orig_row(fields):
    occupancy = fields[O_OCCUPANCY]
    prop_type = fields[O_PROPERTY_TYPE]
    postal_code = fields[O_POSTAL_CODE]
    return {
        "msa": int(fields[O_MSA]) if fields[O_MSA] else None,
        "maturity_date": to_date(fields[O_MATURITY_DATE]),
        "num_units": na_int(fields[O_NUM_UNITS], 99),
        "occupancy_primary": 1 if occupancy == "P" else 0,
        "occupancy_investment": 1 if occupancy == "I" else 0,
        "orig_dti": na_int(fields[O_DTI], 999),
        "orig_upb": int(fields[O_ORIG_UPB]) if fields[O_ORIG_UPB] else None,
        "orig_ltv": na_int(fields[O_ORIG_LTV], 999),
        "orig_interest_rate": float(fields[O_ORIG_RATE]) if fields[O_ORIG_RATE] else None,
        "prepayment_penalty": 1 if fields[O_PPM_INDICATOR] == "Y" else 0,
        "property_type_co_cp": 1 if prop_type in ("CO", "CP") else 0,
        "property_type_mh": 1 if prop_type == "MH" else 0,
        "property_type_pu": 1 if prop_type == "PU" else 0,
        "postal_code": postal_code if postal_code and postal_code != "000" else None,
    }


def parse_perf_row(fields, orig_data):
    period_raw = fields[P_PERIOD]
    loan_id = fields[P_LOAN_ID]
    zero_balance_date_raw = fields[P_ZERO_BALANCE_EFFECTIVE_DATE]
    zero_flag = 1 if zero_balance_date_raw and zero_balance_date_raw == period_raw else 0
    current_upb_raw = fields[P_CURRENT_UPB]
    return (
        loan_id,
        to_date(period_raw),
        round(float(current_upb_raw)) if current_upb_raw else None,
        int(fields[P_LOAN_AGE]) if fields[P_LOAN_AGE] else None,
        zero_flag,
        float(fields[P_CURRENT_RATE]) if fields[P_CURRENT_RATE] else None,
        na_int(fields[P_ELTV], 999),
        orig_data["msa"],
        orig_data["maturity_date"],
        orig_data["num_units"],
        orig_data["occupancy_primary"],
        orig_data["occupancy_investment"],
        orig_data["orig_dti"],
        orig_data["orig_upb"],
        orig_data["orig_ltv"],
        orig_data["orig_interest_rate"],
        orig_data["prepayment_penalty"],
        orig_data["property_type_co_cp"],
        orig_data["property_type_mh"],
        orig_data["property_type_pu"],
        orig_data["postal_code"],
    )


# --- Locating and opening orig/perf files across the three source layouts ---

QUARTER_ZIP_RE = re.compile(r"^historical_data_(\d{4})Q([1-4])\.zip$")


class QuarterSource:
    """Context manager yielding (orig_text_stream, perf_text_stream) for one quarter."""

    def __init__(self, data_dir, year, quarter):
        self.data_dir = data_dir
        self.year = year
        self.quarter = quarter
        self._zf = None
        self._files = []

    def _open_text(self, path):
        f = open(path, "r", encoding=ENCODING, newline="")
        self._files.append(f)
        return f

    def _open_zip_member(self, zf, name):
        raw = zf.open(name)
        wrapped = io.TextIOWrapper(raw, encoding=ENCODING, newline="")
        self._files.append(wrapped)
        return wrapped

    def __enter__(self):
        year, q = self.year, self.quarter
        year_dir = self.data_dir / f"historical_data_{year}"
        orig_name = f"orig_{year}Q{q}.txt"
        perf_name = f"perf_{year}Q{q}.txt"

        # 1. Already-extracted text files on disk.
        if year_dir.is_dir():
            orig_path = year_dir / orig_name
            perf_path = year_dir / perf_name
            if orig_path.is_file() and perf_path.is_file():
                return self._open_text(orig_path), self._open_text(perf_path)

        # 2. A quarter zip sitting directly on disk.
        quarter_zip_name = f"historical_data_{year}Q{q}.zip"
        candidates = []
        if year_dir.is_dir():
            candidates.append(year_dir / quarter_zip_name)
        candidates.append(self.data_dir / quarter_zip_name)
        for path in candidates:
            if path.is_file():
                self._zf = zipfile.ZipFile(path)
                return (
                    self._open_zip_member(self._zf, orig_name),
                    self._open_zip_member(self._zf, perf_name),
                )

        # 3. Nested inside the year's outer zip.
        outer_zip_path = self.data_dir / f"historical_data_{year}.zip"
        if outer_zip_path.is_file():
            with zipfile.ZipFile(outer_zip_path) as outer:
                if quarter_zip_name in outer.namelist():
                    nested_bytes = outer.read(quarter_zip_name)
                    self._zf = zipfile.ZipFile(io.BytesIO(nested_bytes))
                    return (
                        self._open_zip_member(self._zf, orig_name),
                        self._open_zip_member(self._zf, perf_name),
                    )

        raise FileNotFoundError(f"Could not locate {orig_name}/{perf_name} under {self.data_dir}")

    def __exit__(self, *exc):
        for f in self._files:
            f.close()
        if self._zf is not None:
            self._zf.close()


def discover_quarters(data_dir, year):
    """Return the sorted list of quarter numbers (1-4) available for a year."""
    year_dir = data_dir / f"historical_data_{year}"
    found = set()

    if year_dir.is_dir():
        for p in year_dir.iterdir():
            m = re.match(rf"^orig_{year}Q([1-4])\.txt$", p.name)
            if m:
                found.add(int(m.group(1)))
            m = QUARTER_ZIP_RE.match(p.name)
            if m and int(m.group(1)) == year:
                found.add(int(m.group(2)))

    outer_zip_path = data_dir / f"historical_data_{year}.zip"
    if outer_zip_path.is_file():
        with zipfile.ZipFile(outer_zip_path) as outer:
            for name in outer.namelist():
                m = QUARTER_ZIP_RE.match(name)
                if m and int(m.group(1)) == year:
                    found.add(int(m.group(2)))

    return sorted(found)


def discover_years(data_dir):
    years = set()
    for p in data_dir.iterdir():
        m = re.match(r"^historical_data_(\d{4})\.zip$", p.name)
        if m:
            years.add(int(m.group(1)))
        m = re.match(r"^historical_data_(\d{4})$", p.name)
        if m and p.is_dir():
            years.add(int(m.group(1)))
    return sorted(years)


def process_quarter(data_dir, year, quarter, proportion, seed, conn):
    with QuarterSource(data_dir, year, quarter) as (orig_f, perf_f):
        random.seed(seed)
        sampled = {}
        n_frm = 0
        for line in orig_f:
            fields = line.rstrip("\n").split("|")
            if fields[O_AMORTIZATION_TYPE] != "FRM":
                continue
            n_frm += 1
            if random.random() < proportion:
                sampled[fields[O_LOAN_ID]] = parse_orig_row(fields)

        n_rows = 0
        batch = []
        for line in perf_f:
            fields = line.rstrip("\n").split("|")
            orig_data = sampled.get(fields[P_LOAN_ID])
            if orig_data is None:
                continue
            batch.append(parse_perf_row(fields, orig_data))
            if len(batch) >= BATCH_SIZE:
                conn.executemany(INSERT_SQL, batch)
                n_rows += len(batch)
                batch = []
        if batch:
            conn.executemany(INSERT_SQL, batch)
            n_rows += len(batch)
        conn.commit()

        print(
            f"  {year}Q{quarter}: {len(sampled)} loans sampled of {n_frm} FRM "
            f"({n_frm} of file total) -> {n_rows} performance rows"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proportion", type=float, required=True, help="Fraction of FRM loans to sample, e.g. 0.01")
    parser.add_argument("--db", required=True, help="Path to the SQLite database to create/update")
    parser.add_argument("--data-dir", default="/Users/morris/freddie_data", help="Directory containing historical_data_* zips/dirs")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed re-applied at the start of every orig file")
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--fresh", action="store_true", help="Drop and recreate loan_performance before loading")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    if args.fresh:
        conn.execute("DROP TABLE IF EXISTS loan_performance")
    conn.executescript(SCHEMA)

    years = discover_years(data_dir)
    if args.start_year is not None:
        years = [y for y in years if y >= args.start_year]
    if args.end_year is not None:
        years = [y for y in years if y <= args.end_year]

    if not years:
        print("No years found to process.", file=sys.stderr)
        sys.exit(1)

    print(f"Processing years {years[0]}-{years[-1]} ({len(years)} years) from {data_dir}")
    for year in years:
        quarters = discover_quarters(data_dir, year)
        if not quarters:
            print(f"  {year}: no quarters found, skipping")
            continue
        for q in quarters:
            process_quarter(data_dir, year, q, args.proportion, args.seed, conn)

    total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    total_loans = conn.execute("SELECT COUNT(DISTINCT loan_id) FROM loan_performance").fetchone()[0]
    print(f"Done. {total_loans} loans, {total} performance rows in {args.db}")
    conn.close()


if __name__ == "__main__":
    main()
