#!/usr/bin/env python3
"""
add_seasonality.py

Adds 11 month-dummy columns to loan_performance (month_jan .. month_nov;
December is deliberately omitted as the reference category to avoid
perfect collinearity in a regression). Each column is 1 if
monthly_reporting_period falls in that calendar month, else 0.

Usage:
    python3 add_seasonality.py --db freddie_sample.db
"""

import argparse
import sqlite3

MONTHS = [
    ("01", "month_jan"), ("02", "month_feb"), ("03", "month_mar"), ("04", "month_apr"),
    ("05", "month_may"), ("06", "month_jun"), ("07", "month_jul"), ("08", "month_aug"),
    ("09", "month_sep"), ("10", "month_oct"), ("11", "month_nov"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    cols = [row[1] for row in conn.execute("PRAGMA table_info(loan_performance)")]
    for _, col in MONTHS:
        if col not in cols:
            conn.execute(f"ALTER TABLE loan_performance ADD COLUMN {col} INTEGER")
    conn.commit()
    print(f"Ensured columns: {', '.join(c for _, c in MONTHS)} (December omitted as reference)")

    set_clause = ", ".join(
        f"{col} = CASE WHEN strftime('%m', monthly_reporting_period) = '{mm}' THEN 1 ELSE 0 END"
        for mm, col in MONTHS
    )
    conn.execute(f"UPDATE loan_performance SET {set_clause}")
    conn.commit()

    n_total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    check = conn.execute(
        "SELECT " + " + ".join(c for _, c in MONTHS) + " AS s, COUNT(*) "
        "FROM loan_performance GROUP BY s ORDER BY s"
    ).fetchall()
    print(f"{n_total} rows updated. Row counts by (sum of 11 month dummies): {check}")
    conn.close()


if __name__ == "__main__":
    main()
