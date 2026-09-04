#!/usr/bin/env python3
"""
add_price_delta.py

Copies the zhvi table (Zillow Home Value Index, see
morris_lisp/zhvi_data/zhvi.db) into this database, adds derived
3-digit-zip-prefix rows (type='3') averaged from the zip-level (type='Z')
rows, and uses that to populate a `price_delta` column on
loan_performance: for each loan-month row,

    price_delta = zhvi(key, monthly_reporting_period)
                  / zhvi(key, monthly_reporting_period - loan_age months)

where `key` is the loan's 3-digit postal code (type='3') if a value
exists for BOTH dates at that key, otherwise the whole-US series
(type='U', key='United States').

Usage:
    python3 add_price_delta.py --db freddie_sample.db \\
        --zhvi-db /Users/morris/morris_lisp/zhvi_data/zhvi.db
"""

import argparse
import sqlite3

COPY_SCHEMA = """
DROP TABLE IF EXISTS zhvi;
CREATE TABLE zhvi (
    type  TEXT NOT NULL,
    key   TEXT NOT NULL,
    date  TEXT NOT NULL,
    value INTEGER,
    PRIMARY KEY (type, key, date)
);
"""

BUILD_ZIP3_SQL = """
INSERT INTO zhvi (type, key, date, value)
SELECT '3', substr(key, 1, 3), date, ROUND(AVG(value))
FROM zhvi
WHERE type = 'Z'
GROUP BY substr(key, 1, 3), date
"""

UPDATE_SQL = """
UPDATE loan_performance
SET price_delta = (
    SELECT CASE
        WHEN zn3.value IS NOT NULL AND zd3.value IS NOT NULL
            THEN CAST(zn3.value AS REAL) / zd3.value
        WHEN znU.value IS NOT NULL AND zdU.value IS NOT NULL
            THEN CAST(znU.value AS REAL) / zdU.value
        ELSE NULL
    END
    FROM (SELECT date(loan_performance.monthly_reporting_period,
                       '-' || loan_performance.loan_age || ' months') AS lag_date) d
    LEFT JOIN zhvi zn3 ON zn3.type = '3' AND zn3.key = loan_performance.postal_code
                       AND zn3.date = loan_performance.monthly_reporting_period
    LEFT JOIN zhvi zd3 ON zd3.type = '3' AND zd3.key = loan_performance.postal_code
                       AND zd3.date = d.lag_date
    LEFT JOIN zhvi znU ON znU.type = 'U' AND znU.key = 'United States'
                       AND znU.date = loan_performance.monthly_reporting_period
    LEFT JOIN zhvi zdU ON zdU.type = 'U' AND zdU.key = 'United States'
                       AND zdU.date = d.lag_date
)
WHERE loan_age IS NOT NULL
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--zhvi-db", required=True, help="Path to zhvi_data/zhvi.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    conn.executescript(COPY_SCHEMA)
    conn.execute(f"ATTACH DATABASE '{args.zhvi_db}' AS src")
    conn.execute("INSERT INTO zhvi SELECT type, key, date, value FROM src.zhvi")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    n_copied = conn.execute("SELECT COUNT(*) FROM zhvi").fetchone()[0]
    print(f"Copied {n_copied} rows from zhvi.db")

    conn.execute(BUILD_ZIP3_SQL)
    n_zip3 = conn.execute("SELECT COUNT(*) FROM zhvi WHERE type = '3'").fetchone()[0]
    print(f"Built {n_zip3} type='3' (3-digit zip prefix) rows")
    conn.commit()

    cols = [row[1] for row in conn.execute("PRAGMA table_info(loan_performance)")]
    if "price_delta" not in cols:
        conn.execute("ALTER TABLE loan_performance ADD COLUMN price_delta REAL")
        print("Added price_delta column to loan_performance")
    else:
        print("price_delta column already exists; recomputing values")

    conn.execute(UPDATE_SQL)
    conn.commit()

    n_set = conn.execute("SELECT COUNT(*) FROM loan_performance WHERE price_delta IS NOT NULL").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    print(f"price_delta populated on {n_set} / {n_total} rows")
    conn.close()


if __name__ == "__main__":
    main()
