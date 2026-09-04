#!/usr/bin/env python3
"""
add_sample_bucket.py

Adds a `sample_bucket` column (integer 0-99) to loan_performance, derived
from a stable hash of loan_id (MD5 mod 100). Every row for a given loan
gets the same bucket, so any train/test split -- e.g.
"WHERE sample_bucket < 80" for an 80/20 split -- keeps a loan's full
history together on one side of the split. Not a cryptographic use, MD5
is just a convenient, fast, well-distributed stable hash.

Usage:
    python3 add_sample_bucket.py --db freddie_sample.db
"""

import argparse
import hashlib
import sqlite3


def bucket_for(loan_id):
    return int(hashlib.md5(loan_id.encode()).hexdigest(), 16) % 100


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    cols = [row[1] for row in conn.execute("PRAGMA table_info(loan_performance)")]
    if "sample_bucket" not in cols:
        conn.execute("ALTER TABLE loan_performance ADD COLUMN sample_bucket INTEGER")
        print("Added sample_bucket column to loan_performance")

    loan_ids = [row[0] for row in conn.execute("SELECT DISTINCT loan_id FROM loan_performance")]
    print(f"Hashing {len(loan_ids)} distinct loan_ids...")

    conn.execute("DROP TABLE IF EXISTS loan_bucket")
    conn.execute("CREATE TABLE loan_bucket (loan_id TEXT PRIMARY KEY, sample_bucket INTEGER)")
    conn.executemany(
        "INSERT INTO loan_bucket (loan_id, sample_bucket) VALUES (?, ?)",
        ((lid, bucket_for(lid)) for lid in loan_ids),
    )
    conn.commit()

    print("Updating loan_performance...")
    conn.execute("""
        UPDATE loan_performance
        SET sample_bucket = (SELECT sample_bucket FROM loan_bucket WHERE loan_bucket.loan_id = loan_performance.loan_id)
    """)
    conn.execute("DROP TABLE loan_bucket")
    conn.commit()

    n_total = conn.execute("SELECT COUNT(*) FROM loan_performance").fetchone()[0]
    dist = conn.execute("""
        SELECT MIN(sample_bucket), MAX(sample_bucket), COUNT(DISTINCT sample_bucket) FROM loan_performance
    """).fetchone()
    # sanity: every row for a loan should share one bucket
    mismatches = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT loan_id FROM loan_performance GROUP BY loan_id HAVING COUNT(DISTINCT sample_bucket) > 1
        )
    """).fetchone()[0]
    print(f"{n_total} rows updated. bucket range {dist[0]}-{dist[1]} ({dist[2]} distinct buckets). "
          f"loans with inconsistent bucket across rows: {mismatches}")
    conn.close()


if __name__ == "__main__":
    main()
