#!/usr/bin/env python3
"""
build_freddie_sample.py

Draws a random sample of 30-year fixed-rate loans from Freddie Mac's
Single-Family Loan-Level Dataset and writes every month of each into the
table loan_months of a SQLite database: one row per loan per month, with what
it prepaid, whether it defaulted, what was lost, and what a model looks at
(see loan_months.py).

Sampling
--------
For each quarter's origination file, the random numbers start again from the
same seed, and each eligible loan (fixed rate, with the --term, 360 months to
begin with) is drawn with one random number, at the --proportion. So the
sample of any quarter is the same every time it is made.

Only 30-year loans, because the incentive compares a loan's rate with the
survey rate of new 30-year loans: a 15-year loan would be compared with the
15-year rate, which is not loaded.

Usage
-----
    python3 build_freddie_sample.py --proportion 0.02 --db freddie_loans.db
    python3 build_freddie_sample.py --proportion 0.02 --db test.db --start-year 2023 --end-year 2023   # a quick try

It needs freddie_mortgage_rates.csv (the weekly survey rate, MORTGAGE30US from
FRED) and zhvi.db (Zillow's home values, made by zhvi_data/zhvi_loader.py).
"""

import argparse
import random
import sqlite3
import sys
import time
from pathlib import Path

import freddie_files as ff
from loan_months import loan_months
from market_data import HomePrices, MortgageRates

# The columns of loan_months: (name, SQL type, what it is)
COLUMNS = [
    # the loan, the same in every month
    ("loan_id", "TEXT NOT NULL", "Freddie's loan sequence number"),
    ("sample_bucket", "INTEGER", "0-99 from a hash of the loan id: 'sample_bucket < 80' is the same 80% of the loans every time"),
    ("first_payment", "TEXT", "the date of the first payment, YYYY-MM-01"),
    ("orig_upb", "REAL", "the balance when it was made"),
    ("orig_rate", "REAL", "the note rate when it was made, percent"),
    ("orig_ltv", "INTEGER", "the loan-to-value when it was made, percent"),
    ("orig_term", "INTEGER", "months"),
    ("credit_score", "INTEGER", "the borrower's credit score when it was made"),
    ("dti", "INTEGER", "debt-to-income when it was made, percent"),
    ("mi_percent", "INTEGER", "the mortgage insurance, percent of the loss it covers (0 if none)"),
    ("borrowers", "INTEGER", "how many borrowers"),
    ("first_time_buyer", "INTEGER", "1 for a first-time homebuyer, 0 if not"),
    ("occupancy", "TEXT", "P primary home, I investment property, S second home"),
    ("purpose", "TEXT", "P purchase, C cash-out refinance, N no-cash-out refinance, R refinance not specified"),
    ("property_type", "TEXT", "SF single family, CO condo, CP co-op, PU planned unit development, MH manufactured housing"),
    ("channel", "TEXT", "R retail, B broker, C correspondent, T not specified"),
    ("state", "TEXT", "two letters"),
    ("zip3", "TEXT", "the first three digits of the zip code"),
    ("sato", "REAL", "the rate when it was made less the survey rate then, percent"),
    # the month
    ("period", "TEXT NOT NULL", "the month, YYYY-MM-01"),
    ("calendar_month", "INTEGER", "1-12"),
    ("loan_age", "INTEGER", "months since the month before the first payment"),
    ("rate", "REAL", "the note rate, percent"),
    ("months_delinquent", "INTEGER", "at the start of the month (NULL if the home was taken)"),
    ("exit_code", "TEXT", "how the loan ended, in its last month: 01 paid off, 02/03/09/15/16 defaults and sales, 06 repurchased, 96 removed"),
    ("start_upb", "REAL", "the balance at the start of the month"),
    ("scheduled_upb", "REAL", "what the balance would be after the scheduled payment: the weight of the month"),
    ("end_upb", "REAL", "the balance at the end of the month"),
    ("prepaid", "REAL", "what was paid beyond the scheduled payment: all of scheduled_upb on a payoff, or a curtailment"),
    ("smm", "REAL", "prepaid / scheduled_upb, 0 to 1"),
    ("payoff", "INTEGER", "1 if the loan was paid off this month"),
    ("curtailment_seen", "INTEGER", "1 if a partial prepayment, if there was one, would show in the balances"),
    ("survey_rate", "REAL", "the average 30-year survey rate of the month before, percent"),
    ("incentive", "REAL", "rate less survey_rate, percent"),
    ("burnout", "INTEGER", "earlier months, after the first year, with an incentive above 0.75 percent"),
    ("home_price_change", "REAL", "home prices now over when the loan was made, in its 3-digit zip code (or the country)"),
    ("current_ltv", "REAL", "the loan-to-value now, percent: orig_ltv x start_upb / orig_upb / home_price_change"),
    ("freddie_ltv", "INTEGER", "Freddie's own estimate of the loan-to-value now, percent, where it gives one"),
    # defaults and losses (see loan_months.py)
    ("in_forbearance", "INTEGER", "1 if the loan is in forbearance, or delinquent because of a disaster"),
    ("defaulted", "INTEGER", "1 in the month the loan defaulted"),
    ("after_default", "INTEGER", "1 in the months after it defaulted"),
    ("ltv_at_default", "REAL", "current_ltv in the month it defaulted, from then on"),
    ("months_since_default", "INTEGER", "months since the month it defaulted, from then on"),
    ("removal_upb", "REAL", "in the loan's last month: the balance when it was removed"),
    ("loss", "REAL", "on a third-party sale, short sale or REO sale: what was lost (positive), net of what was recovered"),
    ("severity", "REAL", "loss / removal_upb"),
]

COLUMN_NAMES = [name for name, _, _ in COLUMNS]
SCHEMA = ("CREATE TABLE IF NOT EXISTS loan_months (\n"
          + "".join(f"    {name:<20} {kind + ',':<15} -- {about}\n" for name, kind, about in COLUMNS)
          + "    PRIMARY KEY (loan_id, period)\n)")
INSERT_SQL = "INSERT OR REPLACE INTO loan_months (%s) VALUES (%s)" % (", ".join(COLUMN_NAMES), ", ".join("?" * len(COLUMN_NAMES)))
BATCH_SIZE = 20000


def sample_loans(orig_file, proportion, seed, term):
    """The origination records of the sampled loans of a quarter, by loan id, and how many loans could have been drawn."""
    random.seed(seed)
    sampled = {}
    eligible = 0
    for line in orig_file:
        fields = line.rstrip("\n").split("|")
        if fields[ff.O_AMORTIZATION_TYPE] != "FRM" or (term and int(fields[ff.O_ORIG_TERM]) != term):
            continue
        eligible += 1
        if random.random() < proportion:
            sampled[fields[ff.O_LOAN_ID]] = ff.origination_record(fields)
    return sampled, eligible


def sampled_loan_histories(perf_file, sampled):
    """(loan id, its performance records in order of month) for each sampled loan, from a performance file, which has each loan's rows
    together. The loan id is looked at first, so that the rows of the loans that were not sampled (nearly all of them) are not split."""
    current_id, records = None, []
    finished = set()
    for line in perf_file:
        loan_id = line[:line.index("|")]
        if loan_id not in sampled:
            continue
        if loan_id != current_id:
            if current_id is not None:
                yield current_id, sorted(records, key=lambda r: r["period"])
                finished.add(current_id)
            if loan_id in finished:
                raise ValueError(f"the rows of loan {loan_id} are not together in the performance file")
            current_id, records = loan_id, []
        records.append(ff.performance_record(line.rstrip("\n").split("|")))
    if current_id is not None:
        yield current_id, sorted(records, key=lambda r: r["period"])


def process_quarter(data_dir, year, quarter, args, rates, prices, conn):
    started = time.time()
    with ff.QuarterSource(data_dir, year, quarter) as (orig_file, perf_file):
        sampled, eligible = sample_loans(orig_file, args.proportion, args.seed, args.term)
        n_rows, batch = 0, []
        for loan_id, records in sampled_loan_histories(perf_file, sampled):
            for row in loan_months(sampled[loan_id], records, rates, prices):
                batch.append([row[name] for name in COLUMN_NAMES])
            if len(batch) >= BATCH_SIZE:
                conn.executemany(INSERT_SQL, batch)
                n_rows += len(batch)
                batch = []
        conn.executemany(INSERT_SQL, batch)
        n_rows += len(batch)
        conn.commit()
    print(f"  {year}Q{quarter}: {len(sampled)} loans sampled of {eligible} -> {n_rows} months ({time.time() - started:.0f} s)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proportion", type=float, required=True, help="the share of the eligible loans to sample, e.g. 0.02")
    parser.add_argument("--db", required=True, help="the SQLite database to write")
    parser.add_argument("--data-dir", default="/Users/morris/freddie_data", help="where the historical_data_* files are")
    parser.add_argument("--rates-csv", default="/Users/morris/freddie_data/freddie_mortgage_rates.csv", help="the weekly 30-year survey rate")
    parser.add_argument("--zhvi-db", default="/Users/morris/morris_lisp/zhvi_data/zhvi.db", help="Zillow's home value index")
    parser.add_argument("--seed", type=int, default=42, help="the seed that the random numbers of every quarter start from")
    parser.add_argument("--term", type=int, default=360, help="the original term, in months, of the loans to sample (0 for any)")
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    years = [y for y in ff.discover_years(data_dir)
             if (args.start_year is None or y >= args.start_year) and (args.end_year is None or y <= args.end_year)]
    if not years:
        print("No years found to process.", file=sys.stderr)
        sys.exit(1)

    print("Reading the survey rates and the home price index...", flush=True)
    rates = MortgageRates(args.rates_csv)
    prices = HomePrices(args.zhvi_db)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("DROP TABLE IF EXISTS loan_months")
    conn.execute(SCHEMA)

    print(f"Processing years {years[0]}-{years[-1]} from {data_dir}", flush=True)
    for year in years:
        for quarter in ff.discover_quarters(data_dir, year):
            process_quarter(data_dir, year, quarter, args, rates, prices, conn)

    loans, months = conn.execute("SELECT COUNT(DISTINCT loan_id), COUNT(*) FROM loan_months").fetchone()
    print(f"Done. {loans} loans, {months} months in {args.db}")
    conn.close()


if __name__ == "__main__":
    main()
