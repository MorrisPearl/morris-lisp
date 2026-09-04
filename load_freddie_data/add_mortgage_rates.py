#!/usr/bin/env python3
"""
add_mortgage_rates.py

Loads Freddie Mac's weekly PMMS 30-year fixed mortgage rate series
(freddie_mortgage_rates.csv, columns: observation_date, MORTGAGE30US)
into the database, derives a monthly-average table from it, and uses
that to populate an `incentive` column on loan_performance: for each
loan-month row, incentive = current_interest_rate - (average weekly
rate over the calendar month BEFORE monthly_reporting_period).

E.g. a row with monthly_reporting_period = 2025-07-01 gets incentive =
current_interest_rate - avg(MORTGAGE30US for June 2025).

Usage:
    python3 add_mortgage_rates.py --db freddie_sample.db \\
        --csv freddie_mortgage_rates.csv
"""

import argparse
import csv
import sqlite3

SCHEMA = """
DROP TABLE IF EXISTS mortgage_rates_weekly;
CREATE TABLE mortgage_rates_weekly (
    observation_date TEXT PRIMARY KEY,
    rate             REAL NOT NULL
);

DROP TABLE IF EXISTS mortgage_rates_monthly;
CREATE TABLE mortgage_rates_monthly (
    month    TEXT PRIMARY KEY,  -- YYYY-MM-01, the month these weekly readings fall in
    avg_rate REAL NOT NULL
);
"""


def load_weekly_rates(csv_path, conn):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [(row["observation_date"], float(row["MORTGAGE30US"])) for row in reader if row["MORTGAGE30US"]]
    conn.executemany("INSERT INTO mortgage_rates_weekly (observation_date, rate) VALUES (?, ?)", rows)
    print(f"Loaded {len(rows)} weekly rate observations from {csv_path}")


def build_monthly_average(conn):
    conn.execute("""
        INSERT INTO mortgage_rates_monthly (month, avg_rate)
        SELECT strftime('%Y-%m-01', observation_date), AVG(rate)
        FROM mortgage_rates_weekly
        GROUP BY strftime('%Y-%m', observation_date)
    """)
    n = conn.execute("SELECT COUNT(*) FROM mortgage_rates_monthly").fetchone()[0]
    print(f"Built {n} monthly averages")


def add_incentive_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(loan_performance)")]
    if "incentive" not in cols:
        conn.execute("ALTER TABLE loan_performance ADD COLUMN incentive REAL")
        print("Added incentive column to loan_performance")
    else:
        print("incentive column already exists; recomputing values")

    conn.execute("""
        UPDATE loan_performance
        SET incentive = current_interest_rate - m.avg_rate
        FROM mortgage_rates_monthly m
        WHERE m.month = date(loan_performance.monthly_reporting_period, '-1 month')
    """)
    n_set = conn.execute("SELECT COUNT(*) FROM loan_performance WHERE incentive IS NOT NULL").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    print(f"incentive populated on {n_set} / {n_total} rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--csv", required=True, help="Path to freddie_mortgage_rates.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)
    load_weekly_rates(args.csv, conn)
    build_monthly_average(conn)
    add_incentive_column(conn)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
