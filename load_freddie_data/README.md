# Freddie Mac loans, for a prepayment model

These scripts make a SQLite database of a sample of Freddie Mac's 30-year fixed-rate loans, every month of each, with what it prepaid and what a
prepayment model looks at. `lisp_interp/lib/freddie_prepayment.lsp` fits a model to it, and `lisp_interp/notebooks/freddie_prepayment_model.ipynb`
shows it.

## Making the database

```bash
python3 build_freddie_sample.py --proportion 0.02 --db /Users/morris/freddie_data/freddie_loans.db
python3 build_groups.py --db /Users/morris/freddie_data/freddie_loans.db
```

The first reads Freddie's files (a quarter at a time, without unzipping them to disk), samples 2% of the loans, and writes the table
`loan_months`: about 40 minutes for 1999 to 2025. The second puts the months of loans that are alike together, in the table `groups`.
`python3 -m unittest test_loan_months.py` tests the arithmetic of a loan's months on loans made by hand.

What they need:

| | Where | What |
|---|---|---|
| Freddie's loans | `/Users/morris/freddie_data/historical_data_*` | the Single-Family Loan-Level Dataset, from Freddie Mac |
| The survey rate | `/Users/morris/freddie_data/freddie_mortgage_rates.csv` | Freddie's weekly survey (PMMS) of the 30-year rate, `MORTGAGE30US` from FRED |
| Home prices | `/Users/morris/morris_lisp/zhvi_data/zhvi.db` | Zillow's home value index, by zip code and for the country (`zhvi_data/zhvi_loader.py`) |

## The files

| File | What it does |
|---|---|
| `freddie_files.py` | finds the files of a quarter, and names the fields of their rows |
| `market_data.py` | the survey rate of each month, and how much home prices have changed |
| `loan_months.py` | the months of one loan: its balances, what it prepaid, and what a model looks at |
| `build_freddie_sample.py` | samples the loans and writes `loan_months` (its `COLUMNS` say what each column is) |
| `build_groups.py` | writes `groups` |
| `test_loan_months.py` | tests of `loan_months.py` |

## What was prepaid

A month starts with the balance that the last month ended with. The scheduled payment pays some principal, and what the balance would then be
is the **scheduled balance**. A prepayment is what the borrower pays beyond that: all of it, if the loan was paid off (Freddie's zero balance code
01), or the part of it that was paid early (a **curtailment**), which shows when both balances are exact (Freddie rounds the balance to $1,000 in
the first six months), the loan was current, and nothing was modified. A loan that ended in a default, a short sale, a foreclosure or a repurchase
prepaid nothing: those are not prepayments, and need a model of their own.

The **smm** of a month is what was prepaid over the scheduled balance: 1 for a loan paid off. Over a pool it is the prepaid amounts added up over
the scheduled balances added up, so a model of it is fitted with each month weighted by its scheduled balance; the CPR is 1 - (1 - smm)^12.

The months of a loan four or more months delinquent are left out of a model: those loans are bought out of an agency's pools.

## What a model looks at

| Column | Is | The slot of a `collateral-piece` |
|---|---|---|
| `incentive` | the loan's rate less the survey rate of the month before, percent | (the wac, against the rate path) |
| `loan_age` | months | `age` |
| `start_upb` | the balance of the loan at the start of the month | `loan-size` |
| `credit_score` | when the loan was made | `credit-score` |
| `current_ltv` | the loan-to-value now: the original, times how much of the balance is left, over how much home prices in its 3-digit zip code have changed | `ltv` |
| `sato` | the loan's rate less the survey rate when it was made (two months before its first payment), percent | `sato` |
| `burnout` | the earlier months, after the first year, with an incentive above 0.75 percent | `burnout` |
| `occupancy` | P primary, I investment, S second home | `investor-share`, `second-home-share` |
| `purpose` | P purchase, C cash-out refinance, N and R other refinances | `cash-out-share`, `refinance-share` |
| `calendar_month` | 1-12, for the seasons | (the payment dates) |

A `collateral-piece` (in `lisp_interp/lib/prepayment_speed.lsp`) is a pool, so its slots are averages over its loans, weighted by balance, and
its shares are the shares of its balance.

Only 30-year loans are sampled, because the incentive compares a loan's rate with the survey rate of new 30-year loans. A model of 15-year
loans would need the 15-year survey rate (`MORTGAGE15US` from FRED), which is not loaded.

## The groups

`groups` has a row for each month, each incentive to the nearest 0.25 percent, and each band of loan age (1-6, 7-12, 13-24, 25-36, 37-60,
61-120 and 121 months on), for each of the two parts of the sample: `fit` (the loans with a `sample_bucket` below 80) and `test` (the rest).
Its `smm` is what its loans prepaid over their scheduled balances; its other columns are the averages of its loans, weighted by their scheduled
balances, and its `investor`, `second_home`, `cash_out`, `refinance`, `condo`, `pud` and `manufactured` are shares of its balance.
