#!/usr/bin/env python3
"""
build_pool_dataset.py
======================

Turns Freddie Mac's Single-Family Loan-Level Dataset (SFLLD) -- origination
("orig") files plus monthly performance ("svcg") files -- into a pool/cohort
-level panel of characteristics and prepayment rates (SMM/CPR), in a CSV
format ready for lisp_interpreter.py's `load-csv`.

WHY COHORTS INSTEAD OF LITERAL MBS POOLS
-----------------------------------------
Freddie Mac's public data is LOAN-level, not tied to specific tradable
MBS/PC pool CUSIPs (that pool-level factor history sits behind a separate,
also-login-gated "MBS Data" system). The standard approach in both industry
and academic prepayment modeling -- and the more flexible one -- is to
build your own "pools" by grouping loans into cohorts that share
characteristics you care about (origination vintage, coupon, FICO, LTV,
state, loan purpose, ...), then track each cohort's dollar-weighted
prepayment rate over time. That's what this script does. Change
GROUP_BY_COLUMNS below to define your own pools.

BEFORE RUNNING THIS
--------------------
1. Register (free) and download data from either:
     Freddie Mac SFLLD:  https://freddiemac.com/research/datasets/sf-loanlevel-dataset
                          (download via Clarity Data Intelligence)
     Fannie Mae:          https://capitalmarkets.fanniemae.com/credit-risk-transfer/single-family-credit-risk-transfer/fannie-mae-single-family-loan-performance-data
   Non-commercial/research use is free; commercial redistribution needs a
   license. This script is written for Freddie Mac's file layout -- see the
   "ADAPTING FOR FANNIE MAE" note near the bottom for what to change.

2. Freddie Mac ships the data as one directory per year, named
   historical_data_YYYY (YYYY from 1999 to 2026), each containing one
   pipe-delimited, headerless origination file and one performance file
   per quarter: orig_YYYYQn.txt (origination/static) and perf_YYYYQn.txt
   (monthly performance), n = 1-4. Freddie Mac's own column layout has
   been revised more than once (new fields have been added over the
   years) -- ALWAYS check the "User Guide" PDF that comes with your
   download and fix ORIG_COLUMNS / SVCG_COLUMNS below to match it exactly
   if they differ. Getting this wrong will silently misalign every field,
   so it's worth the extra minute to check.

3. `pip install pandas` (not needed by the Lisp interpreter itself -- this
   ETL script is a separate, one-time preprocessing step you run yourself).

USAGE
-----
    python3 build_pool_dataset.py /path/to/freddie_mac_data_dir output.csv

where the data dir contains the historical_data_YYYY/ subdirectories, each
holding that year's orig_YYYYQn.txt / perf_YYYYQn.txt files.
"""

import sys
import glob
import os
import pandas as pd

# ---------------------------------------------------------------------------
# File layouts -- VERIFY against your downloaded User Guide (see note above)
# ---------------------------------------------------------------------------

# These layouts are taken directly from Freddie Mac's "Single-Family
# Loan-Level Dataset General User Guide" (Release 47, July 2026) and were
# verified by splitting real orig_2026Q1.txt / perf_2026Q1.txt sample lines
# and checking that every field lines up with its documented enumeration/
# range (e.g. property_type in {SF,CO,PU,MH,CP,99}, and a loan's orig_rate/
# orig_upb/orig_loan_term in the origination file exactly matching that
# same loan's current_rate/current_upb/remaining_months in its first
# performance row). If Freddie Mac revises the layout again in a later
# release, re-run that same cross-check against a fresh sample rather than
# trusting this list blindly.

ORIG_COLUMNS = [
    "credit_score", "first_payment_date", "first_time_homebuyer_flag",
    "maturity_date", "msa", "mi_pct", "num_units", "occupancy_status",
    "orig_cltv", "orig_dti", "orig_upb", "orig_ltv", "orig_rate", "channel",
    "ppm_flag", "amortization_type", "state", "property_type", "zip",
    "loan_id", "loan_purpose", "orig_loan_term", "num_borrowers",
    "seller_name", "super_conforming_flag", "pre_harp_loan_id",
    "special_eligibility_program", "harp_indicator",
    "property_valuation_method", "io_indicator", "vantage_score_4",
]

SVCG_COLUMNS = [
    "loan_id", "reporting_period", "current_upb", "delinquency_status",
    "loan_age", "remaining_months", "defect_settlement_date",
    "modification_flag", "zero_balance_code", "zero_balance_date",
    "current_rate", "current_non_interest_upb", "ddlpi", "mi_recoveries",
    "net_sales_proceeds", "non_mi_recoveries", "total_expenses",
    "legal_costs", "maintenance_costs", "taxes_and_insurance",
    "misc_expenses", "actual_loss", "cumulative_modification_cost",
    "step_modification_flag", "payment_deferral_flag", "eltv",
    "zero_balance_removal_upb", "delinquent_accrued_interest",
    "disaster_delinquency", "borrower_assistance_code",
    "current_period_modification_cost", "current_interest_bearing_upb",
    "mi_cancellation_indicator", "servicer_name",
    "bankruptcy_cramdown_costs",
]
# Note "Servicer Name" and "Mortgage Insurance Cancellation Indicator" live
# in the PERFORMANCE file, not the origination file (an easy mix-up, since
# both files also separately have a "seller_name"/similar-sounding field).
# If your svcg file has more/fewer trailing columns than this (Freddie has
# added fields over time -- this layout includes the newer
# current_period_modification_cost / current_interest_bearing_upb /
# bankruptcy_cramdown_costs fields), pandas will just fail to align -- pad
# or trim SVCG_COLUMNS to match the actual field count in your file, per
# your User Guide. The columns used below (loan_id, reporting_period,
# current_upb, zero_balance_code, zero_balance_date) are stable across
# versions and are all this script actually needs.

# Zero Balance Code 01 = "Prepaid or Matured" -- the standard proxy for a
# full voluntary prepayment (it also technically includes loans that simply
# reached full-term maturity, which are rare in this sample since most
# 30-year loans terminate early one way or another; if you want to be
# stricter, you can additionally filter on `remaining_months` being well
# above zero when the zero-balance event occurs).
PREPAID_ZERO_BALANCE_CODE = "01"

# ---------------------------------------------------------------------------
# Define your "pools": which characteristics to group loans by. Add/remove
# columns here to change the cohort definition. `orig_year_qtr` is always
# included (computed below) since prepayment behavior is strongly seasonal
# by vintage.
# ---------------------------------------------------------------------------
GROUP_BY_COLUMNS = ["orig_year_qtr", "wac_bucket", "occupancy_status","loan_purpose"]


def load_quarter(orig_file):
    """Load one quarter's origination + performance files. `orig_file` is
    the full path to an orig_YYYYQn.txt file; the matching perf_YYYYQn.txt
    is expected in the same directory."""
    directory = os.path.dirname(orig_file)
    base = os.path.basename(orig_file)  # e.g. "orig_2019Q3.txt"
    quarter_tag = base[len("orig_"):-len(".txt")]  # e.g. "2019Q3"
    svcg_file = os.path.join(directory, "perf_%s.txt" % quarter_tag)
    if not os.path.exists(svcg_file):
        print("  (skipping %s: no matching perf_%s.txt)" % (quarter_tag, quarter_tag))
        return None, None, quarter_tag

    print("Opening", orig_file)
    orig = pd.read_csv(orig_file, sep="|", header=None, names=ORIG_COLUMNS,
                        dtype=str, low_memory=False)
    print("Opening", svcg_file)
    svcg = pd.read_csv(svcg_file, sep="|", header=None, names=SVCG_COLUMNS,
                        dtype=str, low_memory=False)
    return orig, svcg, quarter_tag


def process_quarter(orig, svcg):
    orig = orig.copy()
    orig["orig_rate"] = pd.to_numeric(orig["orig_rate"], errors="coerce")
    orig["credit_score"] = pd.to_numeric(orig["credit_score"], errors="coerce")
    orig["first_payment_date"] = orig["first_payment_date"].astype(str)
    orig["orig_year"] = pd.to_numeric(orig["first_payment_date"].str.slice(0, 4), errors="coerce")
    orig["orig_month"] = pd.to_numeric(orig["first_payment_date"].str.slice(4, 6), errors="coerce")
    orig["orig_year_qtr"] = orig["first_payment_date"].str.slice(0, 4) + "Q" + (
        (orig["orig_month"] - 1) // 3 + 1
    ).astype("Int64").astype(str)

    # WAC buckets: quarter-point (0.25 percentage point) bins from 0% up to
    # 19.75%, i.e. bin edges [0, 0.25, 0.5, ..., 19.75] -- 80 edges, so 79
    # bins. Left at pandas' default Interval labels (e.g. "(4.0, 4.25]")
    # rather than custom names, since there are too many bins to name by
    # hand; a rate outside this range (essentially never, for a mortgage)
    # falls out as NaN, handled the same way as any other missing bucket
    # value (see dropna=False below).
    wac_bin_edges = [k * 0.25 for k in range(80)]
    orig["wac_bucket"] = pd.cut(orig["orig_rate"], bins=wac_bin_edges)

    orig["fico_bucket"] = pd.cut(orig["credit_score"], bins=[-1, 660, 700, 740, 780, 900],
                                  labels=["<660", "660-700", "700-740", "740-780", "780+"])

    # Numeric encoding of occupancy status (P=Primary/I=Investment/S=Second
    # home), for use as a spline-regression 'categorical predictor -- the
    # raw letter code itself isn't numeric, so it wouldn't survive
    # load-csv's numeric-or-date-only column filter. "9" (Not Available)
    # deliberately maps to NaN rather than a 4th code, consistent with the
    # dataset's own "not available" convention.
    orig["occupancy_code"] = orig["occupancy_status"].map({"P": 0, "I": 1, "S": 2})

    svcg = svcg.copy()
    svcg["current_upb"] = pd.to_numeric(svcg["current_upb"], errors="coerce")
    svcg["reporting_period"] = svcg["reporting_period"].astype(str)  # YYYYMM
    svcg = svcg.sort_values(["loan_id", "reporting_period"])

    # Beginning-of-month UPB for each loan-month = that loan's UPB as of the
    # PRIOR reporting period (falls back to the loan's own current UPB for
    # its very first observed month, i.e. treat month 1 as its own base).
    svcg["begin_upb"] = svcg.groupby("loan_id")["current_upb"].shift(1)
    svcg["begin_upb"] = svcg["begin_upb"].fillna(svcg["current_upb"])

    prepaid_mask = (svcg["zero_balance_code"] == PREPAID_ZERO_BALANCE_CODE)
    svcg["prepaid_upb"] = svcg["begin_upb"].where(prepaid_mask, 0.0)

    merged = svcg.merge(orig, on="loan_id", how="left")
    return merged


def aggregate_to_pools(panel):
    """Collapse the loan-month panel into (pool, calendar month) rows with
    dollar-weighted SMM/CPR and pool characteristics as of origination."""
    group_cols = GROUP_BY_COLUMNS + ["reporting_period"]

    # dropna=False: by default, pandas' groupby silently DROPS every row
    # where any group-by column is NaN -- e.g. a loan with a missing/blank
    # credit_score (so its fico_bucket is NaN) would simply vanish from
    # every pool aggregate with no warning. Keeping those as their own
    # "none"-bucketed group instead means every loan-month is accounted
    # for somewhere in the output.
    agg = panel.groupby(group_cols, observed=True, dropna=False).agg(
        begin_upb=("begin_upb", "sum"),
        prepaid_upb=("prepaid_upb", "sum"),
        avg_orig_rate=("orig_rate", "mean"),
        avg_fico=("credit_score", "mean"),
        avg_orig_ltv=("orig_ltv", lambda s: pd.to_numeric(s, errors="coerce").mean()),
        n_loans=("loan_id", "nunique"),
        orig_year=("orig_year", "mean"),
        orig_month=("orig_month", "mean"),
        occupancy_code=("occupancy_code", "first"),
    ).reset_index()

    nan_group_rows = agg[GROUP_BY_COLUMNS].isna().any(axis=1).sum()
    if nan_group_rows:
        print("  note: %d pool-month row(s) have a missing bucket value "
              "(e.g. a loan with no credit score or an out-of-range rate) "
              "-- these appear in the output as 'none' rather than being "
              "silently dropped" % nan_group_rows)

    agg = agg[agg["begin_upb"] > 0]
    agg["smm"] = agg["prepaid_upb"] / agg["begin_upb"]
    agg["cpr"] = 1 - (1 - agg["smm"]) ** 12
    agg["obs_date"] = pd.to_datetime(agg["reporting_period"], format="%Y%m").dt.strftime("%Y-%m-01")

    # Observation year/month as separate numeric columns (exact, since
    # they come straight from this row's own reporting_period).
    agg["obs_year"] = agg["reporting_period"].str.slice(0, 4).astype(int)
    agg["obs_month"] = agg["reporting_period"].str.slice(4, 6).astype(int)

    # Origination year/month as separate numeric columns: the average
    # across the loans in this pool (they can differ by up to two months
    # within the same origination quarter, since a pool spans a full
    # quarter). "loan_age_months" is then just the number of calendar
    # months between that average origination month and this row's
    # observation month.
    agg = agg.rename(columns={"orig_year": "avg_orig_year", "orig_month": "avg_orig_month"})
    agg["loan_age_months"] = (
        (agg["obs_year"] * 12 + agg["obs_month"]) - (agg["avg_orig_year"] * 12 + agg["avg_orig_month"])
    )

    # Build pool_id by concatenating the group columns with "_". Deliberately
    # not using df[cols].astype(str).agg("_".join, axis=1) here -- that
    # idiom's behavior around NaN/categorical columns has varied across
    # pandas versions (it can raise instead of just stringifying NaN), so a
    # NaN wac/fico bucket (from a loan whose rate or credit score fell
    # outside every bucket edge) could break the whole run. .fillna() also
    # doesn't reliably work directly on a Categorical column (it can raise
    # unless the fill value is already a registered category). The
    # per-value conversion below works the same way regardless of a
    # column's dtype, which matters more here since this only runs once
    # per already-aggregated pool-month row, not per loan.
    def safe_str(series):
        # Built from a plain Python list with an explicit dtype=object,
        # rather than series.apply(...) -- .apply() on a Categorical column
        # can itself return a Categorical-dtype Series, which then can't be
        # combined with "+" the way a plain string Series can. Going
        # through a plain list sidesteps dtype propagation entirely.
        values = ["none" if pd.isna(v) else str(v) for v in series]
        return pd.Series(values, index=series.index, dtype=object)

    agg["pool_id"] = safe_str(agg[GROUP_BY_COLUMNS[0]])
    for col in GROUP_BY_COLUMNS[1:]:
        agg["pool_id"] = agg["pool_id"] + "_" + safe_str(agg[col])

    out_cols = ["obs_date", "obs_year", "obs_month", "pool_id"] + GROUP_BY_COLUMNS + [
        "avg_orig_year", "avg_orig_month", "loan_age_months", "occupancy_code",
        "avg_orig_rate", "avg_fico", "avg_orig_ltv", "n_loans", "begin_upb", "cpr"
    ]
    return agg[out_cols].sort_values(["pool_id", "obs_date"])


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 build_pool_dataset.py <data_dir> <output.csv>")
        sys.exit(1)
    data_dir, out_path = sys.argv[1], sys.argv[2]

    # Layout: <data_dir>/historical_data_YYYY/orig_YYYYQn.txt (and the
    # matching perf_YYYYQn.txt in the same directory), for YYYY 1999-2026
    # and n 1-4. Glob for the year directories rather than hardcoding the
    # range, so this keeps working as later years are added.
    year_dirs = sorted(glob.glob(os.path.join(data_dir, "historical_data_*")))
    year_dirs = [d for d in year_dirs if os.path.isdir(d)]
    if not year_dirs:
        print("No historical_data_YYYY directories found in %r" % data_dir)
        sys.exit(1)

    orig_files = []
    for year_dir in year_dirs:
        orig_files.extend(sorted(glob.glob(os.path.join(year_dir, "orig_*.txt"))))
    if not orig_files:
        print("No orig_YYYYQn.txt files found under %r" % data_dir)
        sys.exit(1)

    all_pool_rows = []
    for orig_file in orig_files:
        orig, svcg, quarter_tag = load_quarter(orig_file)
        if orig is None:
            continue
        panel = process_quarter(orig, svcg)
        pool_rows = aggregate_to_pools(panel)
        all_pool_rows.append(pool_rows)

    result = pd.concat(all_pool_rows, ignore_index=True)
    result.to_csv(out_path, index=False)
    print("Wrote %d rows to %s" % (len(result), out_path))
    print("Columns:", list(result.columns))


# ---------------------------------------------------------------------------
# ADAPTING FOR FANNIE MAE
# ---------------------------------------------------------------------------
# Fannie Mae's data is broadly analogous but not identical:
#   - It's distributed as a single combined acquisition+performance file per
#     quarter (post-2020 format), pipe-delimited, ~110 columns, rather than
#     two separate files.
#   - The loan identifier column is "Loan Identifier" instead of "Loan
#     Sequence Number".
#   - Fannie's Zero Balance Code values are the same convention (01 =
#     prepaid/matured), but field positions differ -- check Fannie's own
#     published layout/glossary (linked from the Single-Family Loan
#     Performance Data page) before reusing ORIG_COLUMNS/SVCG_COLUMNS here.
#   - The overall SMM/CPR aggregation logic (beginning-of-month UPB, mark
#     zero-balance-code-01 months as prepaid, group into cohorts, compute
#     dollar-weighted SMM -> CPR) applies unchanged.

if __name__ == "__main__":
    main()
    
