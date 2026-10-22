#!/usr/bin/env python3
"""
build_groups.py

Puts the months of loans that are alike together, as an older kind of
prepayment model was fitted to: the table `groups`, made from the table
loan_months (see build_freddie_sample.py), with a row for each

    month  x  incentive, to the nearest 0.25 percent  x  band of loan age  x  part of the sample

The parts are 'fit', the loans with a sample_bucket below 80, to fit a model
to, and 'test', the rest, to see how it does on loans it was not fitted to.

A group's smm is what its loans prepaid over their scheduled balances: the
share of the group that prepaid that month, by balance. Its other columns are
the averages of its loans, weighted by their scheduled balances: a share of
the loans (investor, cash_out, ...) is the share of the balance that has it.

The months of a loan that is four or more months delinquent are left out:
those loans are bought out of an agency's pools, so they are not in the pools
that a prepayment model is for. So are the months that have no incentive.

Usage
-----
    python3 build_groups.py --db freddie_loans.db
"""

import argparse
import sqlite3

AGE_BANDS = [1, 7, 13, 25, 37, 61, 121]       # the first month of each band: 1-6, 7-12, 13-24, 25-36, 37-60, 61-120, 121 on

# The averages of a group: (column, the expression of a loan's month that is averaged)
AVERAGES = [
    ("incentive", "incentive"),
    ("loan_age", "loan_age"),
    ("loan_size", "start_upb"),
    ("credit_score", "credit_score"),
    ("current_ltv", "current_ltv"),
    ("sato", "sato"),
    ("burnout", "burnout"),
    ("investor", "occupancy = 'I'"),
    ("second_home", "occupancy = 'S'"),
    ("cash_out", "purpose = 'C'"),
    ("refinance", "purpose IN ('N', 'R')"),
    ("condo", "property_type IN ('CO', 'CP')"),
    ("pud", "property_type = 'PU'"),
    ("manufactured", "property_type = 'MH'"),
]


def age_band_sql():
    """SQL for the first month of the age band of a loan's month."""
    cases = " ".join(f"WHEN loan_age >= {start} THEN {start}" for start in reversed(AGE_BANDS))
    return f"CASE {cases} ELSE 0 END"


def weighted_average_sql(expression):
    """SQL for the average of the expression over a group, weighted by the scheduled balances of the months that have a value for it."""
    return f"SUM(scheduled_upb * ({expression})) / SUM(CASE WHEN ({expression}) IS NOT NULL THEN scheduled_upb END)"


def groups_sql():
    averages = ",\n       ".join(f"{weighted_average_sql(expression)} AS {name}" for name, expression in AVERAGES)
    return f"""
CREATE TABLE groups AS
SELECT period,
       CASE WHEN sample_bucket < 80 THEN 'fit' ELSE 'test' END AS part,
       ROUND(incentive * 4) / 4.0 AS incentive_step,
       {age_band_sql()} AS age_band,
       calendar_month,
       COUNT(*) AS loans,
       SUM(payoff) AS payoffs,
       SUM(scheduled_upb) AS balance,
       SUM(prepaid) AS prepaid,
       SUM(prepaid) / SUM(scheduled_upb) AS smm,
       {averages}
FROM loan_months
WHERE COALESCE(months_delinquent, 99) < 4 AND scheduled_upb > 0 AND incentive IS NOT NULL
GROUP BY period, part, incentive_step, age_band
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="the database with the table loan_months")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("DROP TABLE IF EXISTS groups")
    conn.execute(groups_sql())
    conn.commit()
    groups, loan_months, smallest, median_loans = conn.execute("""
        SELECT COUNT(*), SUM(loans), MIN(loans), (SELECT loans FROM groups ORDER BY loans LIMIT 1 OFFSET (SELECT COUNT(*) / 2 FROM groups))
        FROM groups""").fetchone()
    print(f"{groups} groups of {loan_months} months of loans: from {smallest} months of loans in a group, {median_loans} in the middle one")
    conn.close()


if __name__ == "__main__":
    main()
