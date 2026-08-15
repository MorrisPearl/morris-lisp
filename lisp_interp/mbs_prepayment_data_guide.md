# Sourcing Data for a Prepayment Model — What's Really Available

## The short version

There is no free, no-login, bulk-downloadable source of GSE mortgage pool
data anywhere — not from Freddie Mac, not from Fannie Mae, not from FRED,
not from a GitHub mirror. Both GSEs' real datasets require a **free account
registration** (email address, confirm the email, accept terms of use)
before you can download anything in bulk. I can't complete that
registration for you — it needs a real, human-verifiable email — and I
found no legitimate redistributable copy of the underlying data anywhere
(the several GitHub repos that reference this data only contain *processing
code*, never the data itself, since both GSEs' terms explicitly prohibit
redistribution).

What I *can* give you, and have:

1. **Exactly where to get the real data**, and what's actually in it (below).
2. **`build_pool_dataset.py`** — an ETL script that turns the real Freddie
   Mac files, once you've downloaded them, into a pool/cohort-level CSV
   with monthly CPR, ready to load into `lisp_interpreter.py`. I validated
   its core SMM/CPR math against a small hand-built fixture file matching
   the real file format (see "How I tested this," below) — I could not
   test it against the actual dataset itself.
3. **`synthetic_mbs_pools.csv`** — a clearly-synthetic (not real) dataset
   with realistic prepayment dynamics (seasoning ramp, refinance
   S-curve, burnout), so you can build and test your full modeling
   pipeline today.
4. **`prepayment_demo.lsp`** — a working end-to-end example against that
   synthetic data: load, suggest knot locations, fit a multi-predictor
   spline-logistic model, evaluate on held-out data, and chart it.

## Where the real data actually lives

### Freddie Mac Single-Family Loan-Level Dataset (SFLLD)

- **Register/download**: https://freddiemac.com/research/datasets/sf-loanlevel-dataset
  (download happens through "Clarity Data Intelligence")
- **Coverage**: ~55 million 30-year fixed-rate mortgages originated
  January 1999 – September 2025, with monthly performance disclosed
  through the same end date. This is loan-level, not literally tied to a
  specific tradable MBS/PC pool — see "pools vs. cohorts" below.
- **Format**: one origination ("static") file and one monthly performance
  file per quarter, pipe-delimited text, no header row. **Freddie Mac's
  column layout has been revised more than once** — always check the User
  Guide PDF that ships with your download.
- **Cost/terms**: free for non-commercial/academic/research use; a
  license is required for commercial redistribution.
- **Key field for prepayment**: `Zero Balance Code` in the performance
  file. Code `01` = "Prepaid or Matured" — the standard proxy for a full
  voluntary prepayment.

### Fannie Mae Single-Family Loan Performance Data

- **Register/download**: https://capitalmarkets.fanniemae.com/credit-risk-transfer/single-family-credit-risk-transfer/fannie-mae-single-family-loan-performance-data
  (the actual download tool is "Data Dynamics")
- **Coverage**: comparable scope and history to Freddie Mac's dataset,
  loan-level, updated quarterly.
- **Format**: a single combined acquisition+performance file per quarter
  (current format), pipe-delimited, ~110 columns.
- Same free/non-commercial terms, same `01`-prepaid convention.

### Fannie Mae PoolTalk (actual MBS/pool-level disclosure data)

- https://mbsdisclosure.fanniemae.com/PoolTalk2/index.html
- This is the tool that gets you literal MBS pool/CUSIP-level data
  (factors, WAC, WAM, geography) rather than raw loan records. **Basic
  single-CUSIP lookups work without an account**, but bulk issuance/monthly
  file downloads (what you'd want for "a whole bunch of pools") also
  require the same free registration.
- Freddie Mac has an equivalent for its own MBS via Clarity
  (https://capitalmarkets.freddiemac.com/clarity), also login-gated for
  bulk data.

### What I checked and ruled out

- **FRED** has no GSE-specific CPR/prepayment series (I searched
  specifically for this).
- **Freddie Mac's own Daily/Supplemental Prepayment Reports** — also
  behind the same login.
- **Urban Institute's "Housing Finance at a Glance"** chartbook publishes
  real, free, no-login *aggregate market* prepayment charts (sourced from
  eMBS, a paid vendor) — but as PDF charts, not machine-readable pool-level
  data, so not directly usable as vectors.
- **eMBS** — the commercial data vendor essentially everyone in the
  industry actually uses for clean pool-level histories — is a paid
  subscription, not free.

## "Pools" vs. cohorts — a note on what you'll actually get

Freddie/Fannie's public datasets are loan-level, not organized by tradable
MBS pool. The standard practice — in industry and academic prepayment
modeling alike — is to build your own "pools" by grouping loans into
cohorts sharing characteristics you care about (origination vintage,
coupon/WAC bucket, FICO bucket, state, loan purpose, ...), then compute
each cohort's dollar-weighted prepayment rate over time. This is *more*
flexible than literal MBS pool histories, not less: you choose exactly how
fine-grained your "pools" are, and you get the full loan-level
characteristics to define them however your model needs. `build_pool_dataset.py`
does exactly this — edit `GROUP_BY_COLUMNS` near the top to change how
pools are defined.

## Using `build_pool_dataset.py`

```bash
pip install pandas          # not needed by the Lisp interpreter itself
python3 build_pool_dataset.py /path/to/downloaded/freddie/data output.csv
```

It expects the unzipped `historical_data_<QQYYYY>.txt` (origination) and
`historical_data_time_<QQYYYY>.txt` (performance) files for however many
quarters you downloaded, sitting in one directory. For each cohort/pool
and calendar month, it computes:

- **SMM** (Single Monthly Mortality) = dollars prepaid that month ÷
  dollars outstanding at the start of that month, aggregated across all
  loans in the cohort
- **CPR** = `1 - (1 - SMM)^12`

plus average origination rate, FICO, LTV, and loan count per cohort-month
— output as a CSV with only numeric/date columns (text labels like state
names are dropped, since `load-csv` only keeps numeric/date columns; if
you want a categorical predictor like state, re-encode it as a small
integer code first).

**Before trusting the output**, re-check `ORIG_COLUMNS`/`SVCG_COLUMNS`
against your actual downloaded User Guide — Freddie Mac has added fields
to both file formats over the dataset's history, and a mismatched column
count will silently misalign every field.

### How I tested this

I couldn't run this script against the real dataset (I don't have GSE
credentials and can't create them). Instead, I hand-built a small fixture
— four loans across two states, one prepaying loan in each, in the exact
pipe-delimited format described above — ran the script against it, and
hand-verified the resulting SMM/CPR numbers against my own calculation.
They matched exactly. That validates the core aggregation logic (the
beginning-of-month-UPB bookkeeping, the zero-balance-code prepayment flag,
the cohort grouping, the SMM→CPR conversion) but **not** the exact column
layout of the real files, which I can't check without the real data —
please verify that part yourself against the User Guide before relying on
the output.

## Using the synthetic dataset right now

`synthetic_mbs_pools.csv` has 600 synthetic pools (quarterly origination
cohorts × 3 coupon buckets × purchase/refi), each tracked monthly for up
to 5 years — 32,460 rows — with columns:

```
obs_date, pool_id, orig_date, wala_months, orig_wac_pct, avg_fico,
avg_ltv_pct, avg_loan_size_usd, purpose_refi, market_rate_pct,
rate_incentive_pct, cpr
```

CPR is driven by a seasoning ramp, a refinance-incentive S-curve, and
"burnout" (pools with a long history of high refi incentive prepay more
slowly than a fresh pool at the same incentive today) — real mechanisms,
built from an approximate (not official) historical mortgage-rate path.
**This is for testing your modeling pipeline, not for drawing real
conclusions.** `prepayment_demo.lsp` shows a complete workflow against it:
loading the CSV, `suggest-knots` for the refinance-incentive curve,
`spline-regression` with a logistic link and a categorical predictor,
train/test evaluation, and charting.

## Also useful once you have real data: FRED for macro covariates

Prepayment models typically include macro covariates like the mortgage
rate and HPI alongside pool characteristics. `lisp_interpreter.py` already
has `fred-series` built in, which *is* usable right now — FRED itself only
needs a free API key (https://fred.stlouisfed.org/docs/api/api_key.html),
not a GSE account:

```lisp
(define rates (fred-series "MORTGAGE30US" "YOUR_FRED_API_KEY"))
(define dates (car rates))
(define values (cdr rates))
```
