#!/usr/bin/env python3
"""
add_burnout.py

Adds a `burnout` column to loan_performance: for each loan-month row,
the count of that same loan's PRIOR months (loan_age strictly less than
this row's) that had loan_age > 12 and incentive > 0.75 (i.e. how many
months of "in the money to refinance" this loan has already been
exposed to without prepaying -- the standard prepayment-model burnout
proxy).

Computed as a single set-based UPDATE using a window function, rather
than a row-by-row Python loop, since the latter would mean tens of
millions of individual UPDATE statements.

Usage:
    python3 add_burnout.py --db freddie_sample.db
"""

import argparse
import sqlite3

INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_loan_performance_loan_age ON loan_performance (loan_id, loan_age)"

UPDATE_SQL = """
UPDATE loan_performance
SET burnout = sub.burnout
FROM (
    SELECT
        loan_id,
        monthly_reporting_period,
        SUM(CASE WHEN loan_age > 12 AND incentive > 0.75 THEN 1 ELSE 0 END)
            OVER (PARTITION BY loan_id ORDER BY loan_age
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS burnout
    FROM loan_performance
) AS sub
WHERE loan_performance.loan_id = sub.loan_id
  AND loan_performance.monthly_reporting_period = sub.monthly_reporting_period
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    cols = [row[1] for row in conn.execute("PRAGMA table_info(loan_performance)")]
    if "burnout" not in cols:
        conn.execute("ALTER TABLE loan_performance ADD COLUMN burnout INTEGER")
        print("Added burnout column to loan_performance")
    else:
        print("burnout column already exists; recomputing values")

    print("Building supporting index on (loan_id, loan_age)...")
    conn.execute(INDEX_SQL)
    conn.commit()

    print("Computing burnout via window function...")
    conn.execute(UPDATE_SQL)
    conn.commit()

    n_total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    n_positive = conn.execute("SELECT COUNT(*) FROM loan_performance WHERE burnout > 0").fetchone()[0]
    max_burnout = conn.execute("SELECT MAX(burnout) FROM loan_performance").fetchone()[0]
    print(f"burnout populated on {n_total} rows ({n_positive} with burnout > 0, max = {max_burnout})")
    conn.close()


if __name__ == "__main__":
    main()
