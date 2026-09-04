#!/usr/bin/env python3
"""
add_estimated_current_ltv.py

Adds `estimated_current_ltv` (integer percentage) to loan_performance:

    orig_ltv * (current_actual_upb / orig_upb) / price_delta

i.e. the original LTV scaled by how much the balance has paid down and
by how much the home's estimated value has moved (via price_delta)
since origination. Stored as a rounded integer percentage to match the
convention of orig_ltv/orig_dti and avoid false precision.

Usage:
    python3 add_estimated_current_ltv.py --db freddie_sample.db
"""

import argparse
import sqlite3

UPDATE_SQL = """
UPDATE loan_performance
SET estimated_current_ltv = CASE
    WHEN orig_ltv IS NOT NULL
     AND orig_upb IS NOT NULL AND orig_upb != 0
     AND current_actual_upb IS NOT NULL
     AND price_delta IS NOT NULL AND price_delta != 0
    THEN CAST(ROUND(orig_ltv * (CAST(current_actual_upb AS REAL) / orig_upb) / price_delta) AS INTEGER)
    ELSE NULL
END
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    cols = [row[1] for row in conn.execute("PRAGMA table_info(loan_performance)")]
    if "estimated_current_ltv" not in cols:
        conn.execute("ALTER TABLE loan_performance ADD COLUMN estimated_current_ltv INTEGER")
        print("Added estimated_current_ltv column to loan_performance")
    else:
        print("estimated_current_ltv column already exists; recomputing values")

    conn.execute(UPDATE_SQL)
    conn.commit()

    n_total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    n_set = conn.execute("SELECT COUNT(*) FROM loan_performance WHERE estimated_current_ltv IS NOT NULL").fetchone()[0]
    stats = conn.execute("SELECT MIN(estimated_current_ltv), MAX(estimated_current_ltv), AVG(estimated_current_ltv) FROM loan_performance").fetchone()
    print(f"estimated_current_ltv populated on {n_set} / {n_total} rows. min={stats[0]} max={stats[1]} avg={stats[2]:.1f}")
    conn.close()


if __name__ == "__main__":
    main()
