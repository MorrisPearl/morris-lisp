# morris-lisp — The library

The functions for investment analysis: getting data (prices, option chains,
and accounts from Schwab and tastytrade; economic and financial data from
FRED, the SEC, the FDIC, the BLS, the BEA, the Census Bureau, and Alpha
Vantage; any web API, and SQLite), statistical models (regression, linear
programming, and stratification), dates and cash flows, and investments
(option prices, the volatility smile, option checks, and portfolios), and
maps. Yield curves, and simulated paths of interest rates and of investment
prices, are in their own manual, [lisp_paths_manual.md](lisp_paths_manual.md). Most are builtins,
written in Python; the rest are libraries in `lib/`, written in Lisp.

The language itself, and the general builtins these all work with --
tables, vectors and statistics, dates, charts, and displaying and saving
things -- are in the language manual,
[lisp_interpreter_reference.md](lisp_interpreter_reference.md). A section
name in quotes is a section of this manual, unless it says it's in that
one.

For a guide to the economic and financial data by topic -- which agency
publishes what, and which function gets it -- see
[economic_data_guide.md](economic_data_guide.md). The programs in `examples/`
that use all this are described in
[lisp_example_programs.md](lisp_example_programs.md).

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [Where things are](#where-things-are)
- [Getting data](#getting-data)
  - [Downloading data from the web](#downloading-data-from-the-web)
  - [FRED (Federal Reserve Bank of St. Louis) data](#fred-federal-reserve-bank-of-st-louis-data)
  - [The New York Fed's reference rates (SOFR, EFFR, ...)](#the-new-york-feds-reference-rates-sofr-effr-)
  - [SEC financial statements](#sec-financial-statements)
  - [SEC filings: what companies write](#sec-filings-what-companies-write)
  - [FDIC bank data](#fdic-bank-data)
  - [Census data](#census-data)
  - [Maps](#maps)
  - [BLS data](#bls-data)
  - [BEA data](#bea-data)
  - [SQLite](#sqlite)
  - [tastytrade (real broker data)](#tastytrade-real-broker-data)
  - [Schwab (your accounts)](#schwab-your-accounts)
  - [FINRA (agency MBS and TBA prices)](#finra-agency-mbs-and-tba-prices)
  - [Alpha Vantage (dividends)](#alpha-vantage-dividends)
- [Reporting](#reporting)
  - [Google Sheets](#google-sheets)
  - [Reports with control breaks](#reports-with-control-breaks)
- [Dates and cash flows](#dates-and-cash-flows)
  - [Monthly time series](#monthly-time-series)
  - [Trading days (the NYSE's calendar)](#trading-days-the-nyses-calendar)
  - [Day counts and cash flows](#day-counts-and-cash-flows)
- [Statistical models](#statistical-models)
  - [Yield curves and paths of rates](#yield-curves-and-paths-of-rates)
  - [Regression models](#regression-models)
  - [How good is a model? The measures, explained](#how-good-is-a-model-the-measures-explained)
  - [Models fitted to Freddie Mac's loans](#models-fitted-to-freddie-macs-loans)
  - [Linear programming](#linear-programming)
  - [Stratification tables](#stratification-tables)
- [Investments](#investments)
  - [Option prices](#option-prices)
  - [Implied volatility smiles: finding options out of line](#implied-volatility-smiles-finding-options-out-of-line)
  - [Simulating investment prices](#simulating-investment-prices)
  - [Checking option prices against simulated paths](#checking-option-prices-against-simulated-paths)
  - [Valuing options three ways](#valuing-options-three-ways)
  - [Call spreads](#call-spreads)
  - [Option spreads](#option-spreads)
  - [A scenario: every position, every expiration](#a-scenario-every-position-every-expiration)
  - [Portfolios](#portfolios)

## Where things are

The functions for investment analysis, in the order an analysis uses them.

1. **Data.** "Schwab (your accounts)": prices, quotes, your positions and
   orders. "tastytrade (real broker data)": option chains, futures curves,
   and SOFR rates. "FRED (Federal Reserve Bank of St. Louis) data", "SEC
   financial statements", "FDIC bank data", "BLS data", "BEA data",
   "Census data", and "Alpha Vantage (dividends)". Anything else on the
   web: "Downloading data from the web". Files: "SQLite", and `load-csv`
   (under "Input / output", in the language manual). Each gives a
   **table**, so they all work the same way after that. And the other way:
   "Google Sheets" sends tables out, to a spreadsheet, and "Reports with
   control breaks" writes a table as a text report, with totals for each group.
2. **Tables and numbers.** In the language manual: "Tables", "Vectors",
   "Vector math and statistics" (`vector-drawdowns` is there), "Displaying
   tables", "Charting", and "Saving variables". Here: "Stratification
   tables" and "Maps".
3. **Dates.** "Dates", in the language manual. Here: "Trading days (the
   NYSE's calendar)", "Monthly time series" (daily data made monthly, and
   several series lined up), and "Day counts and cash flows" (`npv`, `irr`,
   `yield`, `duration`, ...).
4. **Simulated prices.** An investment's returns, with its dividends, and
   paths of its price made from its own history, started as calm or as wild
   as the market is today: Part 4 of [lisp_paths_manual.md](lisp_paths_manual.md).
   "Portfolios":
   several investments together, their covariance and correlation, a
   portfolio's value, and Markowitz's best weights.
5. **Options.** "Option prices": Black-Scholes, implied volatility, the
   Greeks, and American options (`binomial-tree` shows the tree). "Implied
   volatility smiles": options out of line with the rest of their chain.
   "Checking option prices against simulated paths": options out of line
   with the underlying's history. "Valuing options three ways": a stock's
   options by Black-Scholes, a binomial tree, and simulated paths, next to
   their bids and asks. "Call spreads": the best pair of a stock's calls to buy
   and sell, if you expect it at a price on the day they expire, with the
   order to trade it. "Option spreads": the same for seventeen kinds of position
   (the other vertical spreads, butterflies, iron condors, straddles, strangles,
   single options, covered calls, protective puts, collars, and owning the stock),
   and the best of each side by side. "A scenario: every position, every expiration": for a
   price on any date, every position of every expiration on or after it, ranked by the return on
   the money it commits, with what it loses if you are wrong and if nothing happens.
6. **Rates and mortgages.** The Treasury's, the Fed's and SOFR futures' yield curves,
   and the two-factor model of rates, with paths of rates drawn from it and fitted to
   option prices, are in their own manual, [lisp_paths_manual.md](lisp_paths_manual.md); futures curves
   (`futures-curve-fit`), `lib/column_engine.lsp` and `lib/template.lsp`, tables of
   formulas, and `lib/freddie_prepayment.lsp` and `lib/freddie_default.lsp`, a prepayment model and a default model fitted to Freddie Mac's loans. A structured deal, a tree of tranches with interest, principal, losses
   and shortfalls, is in its own manual, [lisp_cmo_manual.md](lisp_cmo_manual.md)
   (`lib/deal.lsp`).
7. **Models.** "Regression models" (linear, logistic, spline, and least
   absolute deviation, which a spline can be fit by too), "Linear programming", and `lib/solver.lsp`.

**Built in, or loaded.** Everything above is built in, and there whenever
the interpreter is, except the libraries in `lib/`, which are loaded with
`(load "name.lsp")`: `vol_smile.lsp`, `option_check.lsp`, `option_methods.lsp`,
`solver.lsp`, `column_engine.lsp`, `template.lsp`, and `model_utils.lsp`, among others. (Their functions can be
called without loading them, too, once `lib/autoloads.lsp` is loaded, as
`init.lsp` does: see `lazy-load`.) The rule: what has to be fast, or talks
to the world outside, is a builtin, written in Python; a model made of
those is a library, written in Lisp, to be read and changed.

**Examples.** `examples/` has a program for most of this, run from that
directory with `python3 ../lisp_interpreter.py name.lsp`; all of them are
described in [lisp_example_programs.md](lisp_example_programs.md), which also
explains the programming techniques they show:
`investment_paths_example.lsp` (simulated prices, an option on them, and
dividends), `option_methods_example.lsp` (a stock's listed options valued
by Black-Scholes, a binomial tree, and simulated paths, next to their bids
and asks: give it the stock's symbol), `vol_smile_example.lsp`, `option_chain_example.lsp`,
`fred_example.lsp`, `sec_example.lsp`, `fdic_example.lsp`,
`census_bls_example.lsp`, `bea_example.lsp`, `prepayment_demo.lsp`,
`regression_kinds_example.lsp` (the kinds of regression on the same data,
charted -- with a floor and ceiling, a quantile band, a smooth spline --
and cross-validated), and `deal_example.lsp` (a structured deal).

## Getting data

Each of these gives a table (see "Tables", in the
[language manual](lisp_interpreter_reference.md#tables)), so the data from
all of them works the same way after that.

When a site can't be reached, doesn't answer, or says it can't answer now,
the error is a **network** error, which a program can catch alone and get
past -- use a saved copy, or try later -- while any other error stops it as
usual:

```lisp
(define rates
  (catch-error (fred-table creds '("DGS10")) (message) :only (network)
    (load-variables "rates.json")     ; a copy saved earlier with (save-variables "rates.json" rates)
    rates))
```

(See "Catching only the problems you expect" in the language manual.)

### Downloading data from the web

(In `lisp_http.py`.) These reach any web API that returns JSON, CSV, or
plain text — the New York Fed's SOFR history, the Treasury's yield curves,
the BLS, and so on — without writing any Python.

**Caching.** Each takes an optional `cache-hours`. Given a number of hours,
the download is saved on disk, and asking for the same URL again within
that many hours reads the saved copy instead of the network: reruns are
fast, you stay under the API's rate limits, and a notebook gives the same
answer twice. Without `cache-hours` (or with 0), every call downloads.
Saved copies go in `~/.cache/morris_lisp/http`, or the directory named by
the `LISP_HTTP_CACHE` environment variable. A saved copy more than 31
days old is deleted when a new one is saved, so the directory doesn't
only grow. (None of the built-in data functions keeps one longer, so a
`cache-hours` of more than 744 acts as 744.)

**Headers.** Each also takes an optional `headers`: a list of
`(name . value)` pairs to send with the request, for an API that wants a
key in a header.

A failed download — a bad URL, no network, or an error status from the
server — raises a `LispError` giving the URL and the server's reason.
Some failures may pass: no answer, a dropped connection, or the server's
own trouble (HTTP 500 and up). Those are tried once more, two seconds
later, before giving up. A failure that won't pass, such as a 404 (no
such page), isn't tried again.

#### `(http-get-json url [cache-hours headers])`
The JSON at `url`, as Lisp data: a JSON object becomes a hash table with
string keys (read it with `hash-table-ref`), an array becomes a list,
`true`/`false` become `#t`/`#f`, and `null` becomes `'()`.

```lisp
; The latest three SOFR fixings, from the New York Fed (no API key needed):
(define reply (http-get-json "https://markets.newyorkfed.org/api/rates/secured/sofr/last/3.json" 12))
(define fixings (hash-table-ref reply "refRates"))
(map (lambda (f) (list (hash-table-ref f "effectiveDate") (hash-table-ref f "percentRate")))
     fixings)
; e.g. (("2026-09-23" 3.87) ("2026-09-22" 3.87) ("2026-09-21" 3.85))
```

(`nyfed-rates`, below, gives these rates as a table.)

#### `(http-get-csv url [headings cache-hours headers] [:text columns] [:skip rows] [:missing texts] [:separator char])`
The CSV file at `url`, as a table, read exactly as `load-csv` reads a file:
`:text` names the columns to keep as strings, as written, such as zip
codes, which would lose their leading zeros as numbers; `:skip` leaves out the
notes above the header, and `:missing` names what is read as a blank, such as
`"NA"` (see `load-csv`, in the language manual). `headings` is `#t`, `#f`, or a list of the
column names to use, as for `load-csv`; `:separator` is the character between the values of a line, if it is not a comma
(`"|"`, `";"`, `"\t"` for a tab).

```lisp
; Zillow's home values by zip code: the zip is RegionName (RegionID is Zillow's own number)
(define zips (http-get-csv "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
                           #t 24 :text "RegionName"))
```

```lisp
; The Treasury's daily par yield curve for 2026 (dates are MM/DD/YYYY, read as dates):
(define ust (http-get-csv (string-append
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value=2026&page&_format=csv")
              #t 12))
(series-monthly (table-select ust '("Date" "10 Yr")))   ; monthly averages of the 10-year yield
```

#### `(http-get-text url [cache-hours headers])`
The page at `url`, as a string.

#### `(http-url base parameters)`
`base` with a query string built from `parameters` — a list of
`(name . value)` pairs, or a hash table. The values are encoded properly,
so spaces and symbols in them are safe.

```lisp
(http-url "https://x.org/data" (list (cons "series" "DGS10") (cons "limit" 5)))   ; => "https://x.org/data?series=DGS10&limit=5"
(http-url "https://x.org/data" (list (cons "q" "a b&c")))    ; => "https://x.org/data?q=a+b%26c"
```

#### `(http-clear-cache)`
Deletes every saved download, and returns how many there were. It doesn't
delete the maps' boundary files, which are kept for good in their own
directory (see "Maps").

### FRED (Federal Reserve Bank of St. Louis) data

#### `(fred-table creds ids [:start-date d :end-date d :cache-hours h])`
One FRED series, or a list or vector of them, by ID (`"UNRATE"`,
`"DGS10"`), as a table, like the other data functions give:

- a `date` column, oldest first;
- a column for each series, headed by its ID;
- NaN where a series has no value for a date, so daily, weekly, and
  monthly series line up by date.

`creds` is the credentials file's path; its `"fred_api_key"` entry goes
with each request. The table covers all of each series, unless
`:start-date` or `:end-date` (a date, or `"YYYY-MM-DD"`) says otherwise.
Each download is kept for 12 hours, unless `:cache-hours` says otherwise
(0 downloads it every time). FRED's site (https://fred.stlouisfed.org)
finds a series' ID.

```lisp
(define rates (fred-table creds '("DGS10" "FEDFUNDS" "MORTGAGE30US") :start-date (date 2020 1 1)))
(plot-chart (list (list "10-year Treasury" (table-column rates "date") (table-column rates "DGS10"))
                  (list "30-year mortgage" (table-column rates "date") (table-column rates "MORTGAGE30US"))))
```

`examples/fred_example.lsp` has more: a whole series, a date range, and
several series lined up by month.

### The New York Fed's reference rates (SOFR, EFFR, ...)

(In `lisp_nyfed.py`.) The overnight rates the Federal Reserve Bank of New York publishes
each business day, from its free API: no key or account needed. A rate is named by:

| Name | The rate | From |
|---|---|---|
| `"SOFR"` | the Secured Overnight Financing Rate: what overnight loans backed by Treasuries cost; floating-rate loans follow it | April 2, 2018 |
| `"TGCR"`, `"BGCR"` | the Tri-Party and Broad General Collateral Rates, parts of SOFR's market | April 2, 2018 |
| `"EFFR"` | the Effective Federal Funds Rate, the rate the Fed sets a target range for | July 3, 2000 |
| `"OBFR"` | the Overnight Bank Funding Rate | March 1, 2016 |
| `"SOFR-30"`, `"SOFR-90"`, `"SOFR-180"` | SOFR's average over 30, 90 and 180 days, as many floating-rate loans use it | March 2, 2020 |
| `"SOFR-INDEX"` | what $1 put in SOFR on April 2, 2018 has grown to, compounding each day | March 2, 2020 |

Rates are in percent, as the Fed publishes them (`3.94`, not `0.0394`). A rate's date is
the day it is for; the averages and the index are dated the day they are published, which
is the next business day. FRED has some of these too (`"SOFR"`, `"DFF"`), and FRED's
`"DFF"` goes back to 1954; these come straight from the Fed, with the rest of what it
publishes about them.

#### `(nyfed-rates names [:start-date d :end-date d :cache-hours h])`
One rate, or a list of them, by name, as a table like `fred-table`'s: a `date` column,
oldest first, and a column for each rate, headed by its name in capitals, with NaN where
a rate has no value for a date. The table covers each rate's whole history, unless
`:start-date` or `:end-date` (a date, or `"YYYY-MM-DD"`) says otherwise. Each download is
kept for 12 hours, unless `:cache-hours` says otherwise (0 downloads it every time).

```lisp
(define rates (nyfed-rates '("SOFR" "EFFR") :start-date "2025-01-01"))
(plot-chart (list (list "SOFR" (table-column rates "date") (table-column rates "SOFR"))
                  (list "EFFR" (table-column rates "date") (table-column rates "EFFR"))))
```

#### `(nyfed-rate-details name [:start-date d :end-date d :cache-hours h])`
One rate with all the Fed publishes about it each day, as a table: `date`; `rate`;
`percentile-1`, `percentile-25`, `percentile-75` and `percentile-99`, the rates that 1%,
25%, 75% and 99% of the day's dollars traded at or below; `volume-billions`, the dollars
traded, in billions; and for EFFR, `target-from` and `target-to`, the Fed's target range.
For `"SOFR-30"`, `"SOFR-90"`, `"SOFR-180"` and `"SOFR-INDEX"` it is all four:
`average-30-day`, `average-90-day`, `average-180-day` and `index`. The options are as for
`nyfed-rates`.

```lisp
(define effr (nyfed-rate-details "EFFR" :start-date "2026-01-01"))
(table-tail effr 3)       ; date, rate, the percentiles, volume-billions, target-from, target-to
```

`examples/sofr_and_mortgage_rates.lsp` asks whether the 30-year mortgage rate can be told
from SOFR. Over the years the two move together, but from week to week a mortgage rate
follows the 10-year Treasury yield, and SOFR adds nothing once that is known.

### SEC financial statements

(In `lisp_sec.py`.) The income statement, balance sheet, and cash flow
statement of any company that files with the SEC, in a standard form.
Every 10-K and 10-Q is filed with its numbers tagged in XBRL — XML in
which each number is a *fact*: a concept from a standard list (the
US-GAAP taxonomy: `NetIncomeLoss`, `Assets`, ...), a value, a unit, and
the period it covers. The SEC collects every fact a company has filed
into one file, its *company facts*; these functions download that and
arrange the facts as statements. That works for any company that files
XBRL: all US public companies since about 2011 (the largest since 2009),
and foreign companies that file annual reports (20-F, 40-F).

**Credentials.** The SEC asks every program that downloads from it to say
who's asking, with a name and an email address. Put them in your
credentials file (the one `tastytrade-*` and `fred-table` use) as
`"sec_user_agent"`:
```json
{"sec_user_agent": "Jane Smith jane@example.com", ...}
```
Each function takes the credentials file's path first, and a company: its
ticker (`"AAPL"`, `"BRK.B"`) or its CIK number (`320193`). A company's
facts are downloaded once and kept for 12 hours (in the cache
`http-clear-cache` empties), so asking for several statements is quick.

**Normalized.** Companies don't all tag a number the same way: revenue is
`Revenues` for some and `RevenueFromContractWithCustomerExcludingAssessedTax`
for others — and Apple switched from one to the other in 2018. So each line
of the statements has a list of concepts to try, in order, for each
period (`LINE_ITEMS` in `lisp_sec.py`; the `source` column of a statement
says which were used). Gross profit, total liabilities, and free cash flow
are worked out from other lines (revenue less cost of revenue, and so on)
when a company doesn't report them. A company that reports under IFRS
rather than US GAAP (many foreign companies) is covered too, in its own
currency (the `unit` column: `EUR`, `JPY`, ...). A line a company doesn't
report — interest expense, at many — is missing, and a statement leaves
out lines that have no values at all.

**Periods.** A fiscal year is the period an annual report covers, however
the company's year falls (Apple's ends in late September). A quarter's
income and cash flows come from its 10-Q; when the 10-Q gives only the
year to date (as most cash flow statements do), the quarter is the year to
date at its end less the year to date at the end of the quarter before,
and the fourth quarter, which has no 10-Q, is the year less the first three
quarters. Per-share amounts and share counts are averages, not sums, so a
fourth quarter has them only if the company reported them for the quarter
by itself. A company outside the US files only annual reports with the
SEC, so it has no quarters. When a number was reported more than once —
last year's figure appears again in this year's 10-K — the most recently
filed one is used, so restatements are picked up.

#### `(sec-income-statement creds company [:period p :count n :in-millions flag])`, `(sec-balance-sheet ...)`, `(sec-cash-flow-statement ...)`
A statement laid out as the company would show it: a table with a row per
line item (`item`), a column per period, named by the date it ends (newest
first), then `unit` and `source`. `:period` is `"annual"` (the default) or
`"quarterly"`; `:count` is how many periods (5 years or 8 quarters, unless
given). Amounts are in millions unless `:in-millions` is `#f`; per-share
amounts never are.

| Statement | Lines |
|---|---|
| income | revenue, cost of revenue, gross profit, research and development, selling, general and administrative, operating expenses, operating income, interest expense, income before taxes, income tax, net income, earnings per share (basic and diluted), average shares (basic and diluted) |
| balance sheet | cash and equivalents, short-term investments, receivables, inventory, total current assets, property, plant and equipment, goodwill, intangible assets, total assets, accounts payable, current debt, total current liabilities, long-term debt, total liabilities, stockholders' equity, equity with minority interests, total liabilities and equity, shares outstanding |
| cash flow | cash from operations, depreciation and amortization, stock-based compensation, capital expenditures, free cash flow (cash from operations less capital expenditures), cash from investing, cash from financing, dividends paid, shares repurchased |

Payments (capital expenditures, dividends, buybacks) are positive numbers,
as companies report them.

```lisp
(display-table (sec-income-statement creds "AAPL"))
(display-table (sec-balance-sheet creds "MSFT" :period "quarterly" :count 4))
```

#### `(sec-financials creds company [:period p :count n])`
Every line of all three statements, arranged for working with: a row per
period (oldest first) and a column per line, named by its key (`revenue`,
`net-income`, `total-assets`, `free-cash-flow`, ... — the lines above,
lower case, joined by hyphens), after `period-end`, `fiscal-year`, and
`fiscal-period` (`FY`, or `Q1` to `Q4`). Amounts are in dollars (or the
company's currency) and shares, as reported.

```lisp
(define f (sec-financials creds "KO"))
(define net-margin (/ (table-column f "net-income") (table-column f "revenue")))
(define return-on-equity (/ (table-column f "net-income") (table-column f "stockholders-equity")))
```

#### `(sec-facts creds company concept)`
Every value the company has reported for one concept — `"NetIncomeLoss"`
(US GAAP), or with its taxonomy, `"ifrs-full:Revenue"` — in every filing:
a table with the columns `start` (missing for a balance, which is at a
moment), `end`, `value`, `unit`, `fiscal-year` and `fiscal-period` (of the
filing), `form` (`10-K`, `10-Q`, ...), `filed`, `frame` (the calendar
period the SEC assigns it, as `CY2024Q3`), and `accession` (the filing's
number). For anything the statements don't include.

#### `(sec-concepts creds company)`
Every concept the company has reported: a table with its `taxonomy`,
`concept`, `label`, `unit`, how many `facts`, and the end of the `first`
and `last` period. To see what's there to ask `sec-facts` for.

#### `(sec-company creds company)`
A hash table with the company's `"name"` and `"cik"`.

`examples/sec_example.lsp` shows the three statements for Apple, quarters
for Microsoft, margins and returns for three companies, and every annual
EPS figure Coca-Cola has filed.

### SEC filings: what companies write

(In `lisp_sec_filings.py`, and `lib/filing_tone.lsp`.) The SEC financial
statements are the numbers companies report; these read the words. EDGAR
keeps every filing: 10-Ks and 10-Qs, 8-Ks (news a company must report
within days: its results, a new chief executive, a merger), and the rest.
They take the credentials file's path and a company (a ticker or a CIK
number), as the financial statements do, and need the same
`"sec_user_agent"` entry. A filing never changes, so its text is kept for
a week; a list of filings, for 12 hours.

**The tone of the words.** A filing's words are scored by the
Loughran-McDonald word lists: lists, made by Tim Loughran and Bill
McDonald of the University of Notre Dame from reading 10-Ks, of the words
that make a financial report sound negative, positive, uncertain,
litigious (about lawsuits), or constraining. Lists made for everyday
English call words such as "liability", "tax", and "cost" negative, which
in a 10-K they aren't. The lists are free for research, not for
commercial use, as one CSV file from
https://sraf.nd.edu/loughranmcdonald-master-dictionary/. Download it and
put it in `morris_lisp/data` (git leaves it out) or leave it in your
Downloads folder: `text-tone` finds it in either, or where `:word-lists`
says.

What a tone tells you is mostly a change: a company's next 10-K against
its last, or one company against others in its business. Filings are
written to sound cautious, so the negative words are always well ahead of
the positive ones. In 10-Ks' risk factors, about 3 to 5 percent of the
words are on the negative list, and under 1 percent on the positive.

#### `(sec-filings creds company [:forms f :count n])`
The company's filings: a table with a row for each, oldest first, of its
`filing-date`; `report-date`, the end of the period it reports on (`'()`
for a filing that doesn't report on one); `form` (`"10-K"`, `"10-Q"`,
`"8-K"`, ...); `items`, for an 8-K the numbers of the items it reports
(`"2.02"` is results, `"5.02"` a change of officers, `"1.01"` a major
agreement); `description`; `accession`, the SEC's number for the filing;
and `url`, its main document, for `sec-filing-text`. `:forms`, a form or a
list of them, keeps just those; `:count` keeps just the most recent that
many. A filing from before about 2001 has no main document, and its `url`
is the whole filing as one text file, the way it was sent to the SEC.

```lisp
(define apple-8ks (sec-filings creds "AAPL" :forms "8-K" :count 4))
(display-table apple-8ks '(("url" hide) ("description" hide)))
```

#### `(sec-filing-text creds url [:section s])`
The words of a filing, as plain text, a line for each paragraph (or row
of a table): the document at `url`, a `url` from `sec-filings`. With
`:section`, just one section of a 10-K or 10-Q, from its heading to the
next item's:

| `:section` | In a 10-K | In a 10-Q |
|---|---|---|
| `"risk-factors"` | Item 1A, Risk Factors (since 2005) | Part II, Item 1A: usually just the changes since the 10-K |
| `"management-discussion"` | Item 7, Management's Discussion and Analysis | Part I, Item 2, the same |

A filing without the section is an error of the kind `no-section`, which
`catch-error` can catch alone.

Some companies, most of the big banks among them, write their MD&A (and
sometimes their risk factors) as part of their annual report to
shareholders, and the 10-K's item only says where it is: *Information in
response to this Item 7 can be found in the 2025 Annual Report to
Shareholders under "Financial Review."* Then the section is read from
there, by the title the item quotes (or, if it quotes none, the section's
usual title, or one in parentheses on its heading): later in the 10-K's
own document, where JPMorgan and Exxon put their annual reports, or from
the annual report filed with it as Exhibit 13, as Wells Fargo does. It
runs from a line with that title to the next heading that starts another
part of the report (the risk factors, controls and procedures,
management's report on internal control, the auditors' report, or the
financial statements). An item that points to another filing -- a
10-Q's *see the risk factors in our Annual Report on Form 10-K* -- is
left as it is, a few dozen words; so is one that just says *Not
applicable*. A section of fewer than 150 words is most likely one of
these, and the `words` column of `filing-tone` shows it.

```lisp
(define latest (vector-ref (table-column (sec-filings creds "AAPL" :forms "10-K" :count 1) "url") 0))
(define risks (sec-filing-text creds latest :section "risk-factors"))
(display (substring risks 0 300))
```

#### `(text-tone text [:word-lists path])`
The tone of any text's words, by the Loughran-McDonald word lists: a hash
table of `"words"`, how many words the text has; `"negative"`,
`"positive"`, `"uncertainty"`, `"litigious"`, and `"constraining"`, the
percent of its words on each list; and `"net-tone"`, positive less
negative. A positive word just after "not", "no", "never", and the like
("not profitable") isn't counted, as Loughran and McDonald suggest. A text
with no words has NaN for each percent.

```lisp
(define tone (text-tone "Net sales declined on weak demand, though margins improved."))
(hash-table-ref tone "negative")   ; => 22.22... -- declined, weak: 2 of the 9 words
```

#### `(filing-tone creds company [:forms f :section s :count n :word-lists path])`
A company's filings, each scored by `text-tone` (in `lib/filing_tone.lsp`,
loaded when it's first called): a table with a row for each filing,
oldest first, of its `filing-date`, `report-date`, and `form`; `text-tone`'s
measures, as columns (`words`, `negative`, `positive`, `uncertainty`,
`litigious`, `constraining`, `net-tone`); and its `url`. `:forms` is
`"10-K"` unless it says; `:section` scores just that section of each (a
filing without it has 0 words, and NaN for the rest); `:count` keeps just
the most recent that many filings.

#### `(show-filing-tone tones)`, `(plot-filing-tone tones [:measures m :title t])`
A `filing-tone` table shown with each percent to two places; and a chart
of its measures, filing by filing -- negative, positive, and uncertainty,
unless `:measures` names others.

```lisp
(define apple (filing-tone creds "AAPL" :section "risk-factors" :count 10))
(show-filing-tone apple)
; filing-date  report-date  form   words  negative  positive  uncertainty  litigious  constraining  net-tone
; -----------  -----------  ----  ------  --------  --------  -----------  ---------  ------------  --------
; ...
; 2023-11-03   2023-09-30   10-K   9,827      4.59      0.50         2.61       1.40          1.13     -4.09
; 2024-11-01   2024-09-28   10-K   9,954      4.63      0.49         2.49       1.43          1.08     -4.14
; 2025-10-31   2025-09-27   10-K   9,817      4.75      0.49         2.71       1.68          1.16     -4.26
(plot-filing-tone apple :measures '("negative" "litigious"))
```

`examples/filing_tone_example.lsp` shows a company's risk factors, year by
year, and charts them.

### FDIC bank data

(In `lisp_fdic.py`.) Every FDIC-insured bank files a Call Report each
quarter — its balance sheet, income, loans, deposits, and capital — and the
FDIC publishes them, with ratios it works out from them, back to 1984,
through its BankFind API (https://api.fdic.gov/banks/docs/). These
functions put them in tables, in the same form as the SEC functions above.

The data is for each insured *bank*, not its holding company: Wells Fargo
Bank, N.A., not Wells Fargo & Company. A bank is its FDIC certificate
number (Wells Fargo Bank is 3511), or a name that matches just one bank
open now — `fdic-find-bank` looks them up. Each function takes the
credentials file's path first; its `"fdic_api_key"` entry, if it has one,
goes with each request (the key never appears in an error message).
Downloads are kept for 12 hours.

**Amounts and periods.** The FDIC reports dollars in thousands; these
functions give dollars (or millions, in the reports). Ratios are percents,
as the FDIC gives them: `1.46` means 1.46%. Income in a Call Report is for
the year to date; a quarter's figure is the FDIC's own quarterly one where
it has one (net income, net interest income, and most others), or else the
year to date less the year to date at the end of the quarter before. Ratios
for a quarter are for the quarter alone, annualized. A year is the four
quarters to December 31 — every bank's year, in a Call Report — so
`:period "annual"` gives the December reports, with income and ratios for
the whole year.

#### `(fdic-find-bank creds name)`
The banks, open or closed, whose names — now or before — match `name`,
largest first: a table of `cert` (the certificate number), `name`, `city`,
`state`, `total-assets` (dollars, at the last report), `active` (1 if
open), `holding-company`, and `last-report` (the date of its last Call
Report).

```lisp
(display-table (fdic-find-bank creds "silicon valley"))
```

#### `(fdic-balance-sheet creds bank [:period p :count n :in-millions flag])`, `(fdic-income-statement ...)`, `(fdic-ratios ...)`
A report laid out as a statement: a row per item, a column per report
date (newest first), then `unit` and `field` (the FDIC's name for it, for
`fdic-get` and `fdic-fields`). `:period` is `"quarterly"` (the default) or
`"annual"`; `:count` is how many periods (8 quarters or 5 years, unless
given); dollar amounts are in millions unless `:in-millions` is `#f`.
Ratios are rounded to two decimals here.

| Report | Items |
|---|---|
| balance sheet | cash and due from banks, securities, fed funds sold and reverse repos, loans and leases, allowance for credit losses, net loans, total assets, total deposits, insured and uninsured deposits (estimated), brokered deposits, fed funds purchased and repos, other borrowed money, total liabilities, equity capital; loans by type: real estate (1-4 family, multifamily, construction, nonfarm nonresidential), commercial and industrial, consumer, agricultural |
| income | interest income, interest expense, net interest income, noninterest income, noninterest expense, provision for credit losses, income before taxes, income taxes, net income, net charge-offs |
| ratios | return on assets, return on equity, net interest margin, efficiency ratio, net charge-offs / loans, noncurrent loans / loans, net loans / deposits, equity / assets, tier 1 leverage ratio, common equity tier 1 ratio, total risk-based capital ratio; and full-time employees |

```lisp
(display-table (fdic-balance-sheet creds 3511 :count 4))
(display-table (fdic-ratios creds "Wells Fargo Bank, National Association" :period "annual"))
```

#### `(fdic-financials creds bank [:period p :count n])`
Every item, arranged for working with: a row per period (oldest first)
and a column per item, named by its key (`total-assets`,
`uninsured-deposits`, `net-income`, `return-on-assets`, ... — the items
above, lower case, joined by hyphens), after `report-date` and `name`.
Dollars and percents.

```lisp
(define svb (fdic-financials creds 24735))          ; Silicon Valley Bank's last 8 quarters
(/ (table-column svb "uninsured-deposits") (table-column svb "total-deposits"))
```

#### `(fdic-get creds dataset [parameters])`
Any of the FDIC's datasets — `"financials"` (every Call Report field,
about 2,400 of them), `"institutions"`, `"failures"`, `"locations"`
(branches), `"history"` (mergers and other changes), `"summary"`, `"sod"`
(the summary of deposits, by branch), `"demographics"` — as a table, a
column per field, with fields as the FDIC gives them (dollars in
thousands; its own date formats). The parameters are a list of
`(name . value)` pairs, as the API takes them: `"filters"`, `"fields"`,
`"search"`, `"sort_by"`, `"sort_order"`, ... — all in upper case, as it
asks. Every matching record comes back (in as many requests as that
takes), unless `"limit"` is given.

```lisp
(fdic-get creds "failures" '(("filters" . "FAILDATE:[2023-01-01 TO *]")
                             ("fields" . "NAME,CITY,FAILDATE,QBFASSET,COST")))
(fdic-get creds "financials" '(("filters" . "CERT:3511 AND REPDTE:20241231")
                               ("fields" . "REPDTE,ASSET,DEP,LNCI,LNRENRES")))
```

#### `(fdic-fields creds dataset [search])`
What a dataset's fields mean: a table of `field`, `title`, and
`description` — only those whose name or title contains `search`, if it's
given. (Needs the `yaml` package, to read the FDIC's lists.)

```lisp
(display-table (fdic-fields creds "financials" "uninsured"))
```

`examples/fdic_example.lsp` finds a bank, shows Wells Fargo Bank's
reports, follows Silicon Valley Bank's uninsured deposits and securities
up to its failure, and lists the largest failures since 2023.

### Census data

(In `lisp_census.py`.) The Census Bureau's API
(https://www.census.gov/data/developers.html) has some 1,800 datasets. The
richest is the American Community Survey (ACS): population, age, race,
income, poverty, education, jobs, commuting, housing, rents, home values,
and much more, for every state, county, city, census tract, and zip code.
There are also the 2020 census, population estimates, County Business
Patterns, and monthly economic indicators. These functions put them in
tables.

Each function takes the credentials file's path first. Its
`"us_census_api_key"` entry, if it has one, goes with each request, and the
key never appears in an error message. Data is kept for 12 hours. The lists
of variables, places, and datasets are kept for 30 days.

**Places.** A place is given the way the Census writes it:

- `"state:*"` is every state.
- `"county:*"` with `:within "state:36"` is every county in New York.
- `"county:061"` with `:within "state:36"` is one county.
- `"tract:*"` with `:within "state:36 county:061"` is every census tract in Manhattan.
- Others include `"us:1"`, `"place:*"` (cities and towns), `"metropolitan statistical area/micropolitan statistical area:*"`, and `"zip code tabulation area:10027"`.

`census-geographies` lists the levels a dataset has. The codes are FIPS
codes, and they come back as text, in a column per level: `"36"`,
`"061"`, `"001"`. The leading zeros matter. A state's code followed by a
county's (`"36061"`) is what `bls-local-area` takes.

**Values.** The Census sends every value as text. Numbers become numbers.
The Census's special negative codes for "no estimate" (such as
-666666666) become NaN. Codes with leading zeros stay text.

**Years.** A dataset is named without its year, such as `"acs/acs5"`, and
`:year` picks the year. Without `:year`, the latest year of the last few
that has data is used. The latest 5-year ACS is 2024, the five years
2020–2024. A full path such as `"2019/acs/acs5"` works too. Time series
(`"timeseries/..."`) have no year; a `"time"` predicate picks their dates.

Some datasets worth knowing:

| Dataset | What it is |
|---|---|
| `acs/acs5` | ACS 5-year estimates: about 28,000 variables, for every place down to census tracts and block groups |
| `acs/acs1` | ACS 1-year estimates: more current, for places of 65,000 people or more |
| `acs/acs5/profile` | ACS data profiles: ready-made percents (`DP02` social, `DP03` economic, `DP04` housing, `DP05` demographic) |
| `acs/acs5/subject` | ACS subject tables (`S...`) |
| `dec/dhc` | The 2020 census: demographic and housing characteristics (`:year 2020`) |
| `pep/charv` | Population estimates by age, sex, race, and Hispanic origin |
| `cbp` | County Business Patterns: establishments, employment, and payroll by industry (NAICS) |
| `timeseries/poverty/saipe` | Income and poverty estimates for states and counties, each year |
| `timeseries/eits/resconst` | New residential construction: permits, starts, completions |
| `timeseries/eits/marts` | Advance monthly retail sales |
| `timeseries/eits/m3` | Manufacturers' shipments, inventories, and orders |
| `timeseries/eits/hv` | Housing vacancies and homeownership |
| `timeseries/intltrade/exports/hs`, `.../imports/hs` | Monthly trade, by product |

#### `(census-get creds dataset variables geography [:within w :year y :predicates p])`
The variables of a dataset, for each place that `geography` names, as a
table. There is a column per variable, and then a column per level of
place.

- `variables` is a name or a list of names, such as `"NAME"`,
  `"B19013_001E"`, or `"group(B19013)"` for a whole table.
- `:within` narrows the places. It is a string such as `"state:36"`, or a
  list of such strings.
- `:predicates` is a list of `(name . value)` pairs for anything else the
  dataset takes, such as a time series' `"time"`, or `"NAICS2017"` for
  County Business Patterns. A predicate's column comes back as text, as it
  was given (an industry's code `"52"`, like `"00"`), except `time`'s.

```lisp
(census-get creds "acs/acs5" '("NAME" "B19013_001E") "county:*" :within "state:36")
(census-get creds "acs/acs1" '("NAME" "B19013_001E") "state:*" :year 2019)
(census-get creds "timeseries/eits/resconst" '("cell_value" "time_slot_id") "us:*"
            :predicates '(("time" . "from 2025") ("category_code" . "APERMITS")
                          ("data_type_code" . "TOTAL") ("seasonally_adj" . "yes")))
```

#### `(census-profile creds geography [:within w :year y])`
A standard profile of each place, from the 5-year ACS. It is a table of
`name`, the place's codes, and these columns. The rates and shares are
percents of the group given, rounded to two decimals.

| Column | What it is |
|---|---|
| `population`, `median-age`, `households` | |
| `median-household-income`, `per-capita-income` | dollars |
| `poverty-rate` | of those whose poverty status is known |
| `labor-force-participation` | of those 16 and over |
| `unemployment-rate` | of the civilian labor force |
| `bachelors-degree-or-higher` | of those 25 and over |
| `median-home-value`, `median-gross-rent` | dollars |
| `homeownership-rate` | of occupied homes |
| `vacancy-rate` | of all homes |
| `white-non-hispanic`, `black`, `asian`, `hispanic` | of the population |

```lisp
(census-profile creds "state:*")
(census-profile creds "county:*" :within "state:*")       ; every county in the country
```

#### `(census-variables creds dataset [search] [:year y])`
A dataset's variables, as a table of `name`, `label`, `concept` (the table
the variable belongs to), `group`, and `type`. With `search`, only the
variables whose name, label, or concept contains it. The 5-year ACS's
list is 10 MB, so it takes a few seconds the first time; after that it is
kept.

```lisp
(census-variables creds "acs/acs5" "median gross rent as a percentage")
```

#### `(census-geographies creds dataset [:year y])`
The kinds of place a dataset has data for, as a table:

- `level` is the level, such as `"county"`.
- `within` lists the levels that a request for it must give with `:within`.
- `within-may-be-*` lists which of those may be `*`.

For example, `county` is within `state`, which may be `*`. A tract needs one
state, but its county may be `*`.

```lisp
(census-geographies creds "acs/acs5")
```

#### `(census-datasets creds [search])`
Every dataset, as a table of `title`, `dataset` (the name to give
`census-get`), `year` (empty for a time series), and `description`. With
`search`, only those whose title or name contains it.

```lisp
(census-datasets creds "business patterns")
```

### Maps

(In `lisp_maps.py`.) `census-shapes` gets places' outlines, and
`plot-map` draws maps of them:

- each place colored by a value (a *choropleth* map);
- a symbol on each place, sized by a value (a *proportional symbol* map);
- or both.

A map goes where every chart goes: inline in a notebook, the GUI's chart
tab, or a one-line summary at the console. `save-chart` saves it.

**The outlines** come from the Census Bureau's cartographic boundary
files (https://www.census.gov/geographies/mapping-files.html). These are
its boundaries simplified for maps and clipped to the shoreline. Each is a
zipped *shapefile*: a `.shp` file of outlines and a `.dbf` file of each
place's codes and name. `lisp_maps.py` reads them itself, so no other
package is needed. No key is needed.

**Where the files are kept.** A boundary file is downloaded once and kept
for good, since a year's boundaries never change.

- They're in `~/.cache/morris_lisp/maps`, or the directory the
  `LISP_MAPS_DIRECTORY` environment variable names.
- Each has the Census's own name for it, such as
  `cb_2025_us_county_20m.zip`. Most are small, but the ZIP code areas'
  file is 67 MB.
- To free the space, or to have a file downloaded again, delete it, or
  the whole directory.
- `http-clear-cache` leaves them alone.

**The projection.** A map is drawn with the Albers equal-area
projection: a place's size on the map is in proportion to its size on the
ground, so big places don't look bigger than they are.

A map of the whole country is drawn the usual way:

- The contiguous states use the standard projection for them (standard
  parallels 29.5° and 45.5° north, centered on 96° west).
- Alaska, Hawaii, and Puerto Rico each get their own projection, and are
  moved into the empty corners below. Alaska is drawn at 35% of the scale,
  as on most maps of the country, so areas compare truly only within each
  part.
- Guam, American Samoa, and the Northern Mariana Islands aren't drawn.

A map of anything smaller, such as one state or one county's tracts, has
a projection fitted to it.

#### `(census-shapes level [:state s :year y :resolution r])`
The places of one kind, as a table: a row for each place, with its codes
and names as the Census gives them, and its outline in the `shape`
column. `level` is one of these:

| Level | The places | Comes as |
|---|---|---|
| `"state"` | the 50 states, DC, and Puerto Rico | one file for the country |
| `"county"` | counties and the places counted as counties (3,222, with Puerto Rico's municipios) | one file for the country |
| `"tract"` | census tracts: neighborhoods of about 4,000 people | a file for each state: give `:state` |
| `"place"` | cities, towns, and villages | a file for each state: give `:state` |
| `"zcta"` (or `"zip"`) | ZIP code areas (ZCTAs), as drawn for the 2020 census | one file for the country (67 MB) |
| `"congressional-district"` (or `"cd"`) | the districts of the current Congress | one file for the country |
| `"metro-area"` (or `"cbsa"`) | metropolitan and micropolitan areas | one file for the country |
| `"nation"` | the country's outline | one file |

The columns that matter most:

- `GEOID`: the place's code. A state is 2 digits (`"36"`), a county 5
  (the state's and its own: `"36061"`), a tract 11 (its county's, then 6
  more), and a ZCTA its ZIP code.
- `NAME`.
- `STATEFP` and `STUSPS`: the state's code and its abbreviation.
- `ALAND` and `AWATER`: land and water area, in square meters.

The 2020 ZCTA file's columns end in `20`; that's dropped, so it has
`GEOID` and `NAME` too.

- `:state` picks one state's places, by abbreviation (`"NY"`) or code
  (`36`). Tracts and places need it.
- `:resolution` is `"20m"` (the simplest outlines, fine for the whole
  country), `"5m"`, or `"500k"` (the most detail). The default is 20m for
  the whole country and 500k for one state. Tracts, places, and ZCTAs
  come only at 500k.
- `:year` picks the boundaries' year. ZCTAs are always 2020's. Without
  `:year`, it's the newest year already downloaded, so a map needs no
  network once its file is kept. The first time, it's the newest year the
  Census has. To use a later year's boundaries once there are any, give
  `:year`.

```lisp
(define states (census-shapes "state"))
(define ny-counties (census-shapes "county" :state "NY"))
(define tracts (census-shapes "tract" :state "NY"))   ; New York's census tracts
(define zips (census-shapes "zcta"))                   ; every ZIP code area
```

#### `(plot-map shapes [options])`
A map of the places in `shapes`, a table from `census-shapes` (or a
part of one, such as `(table-filter ...)` or `(table-head ...)`). With
no options, each place is drawn in light gray, outlined.

**Values from a table.** To color places or size symbols by values, give
a table of them with `:data`, and say which of its columns holds the
places' codes with `:key`:

- `:key` is a column's name, or a list of columns whose values are put
  together. `(list "state" "county")` makes `"36"` and `"061"` into
  `"36061"`, which is how `census-get` gives a county's codes.
- The default key is the data's `GEOID` column, or else its `fips`, `zip`,
  or `zcta` column.

Codes match the shapes' `GEOID`s, written as they are:

- A number is padded with zeros: a state's `6` is `"06"`, a ZIP code's
  `1001` is `"01001"`.
- A state's 5-character BEA code (`"36000"`) is its 2-digit code.
- A place with no row in the data has no value. Two rows for one place
  are an error: add them up first, with `table-group-by`.

Without `:data`, `:fill` and `:symbols` name columns of `shapes` itself,
such as a column `table-join` added, or `ALAND`.

| Option | What it does |
|---|---|
| `:fill` | The data column that colors the places. A place with no value is gray, and the legend says so. |
| `:fill-label` | The color bar's label. The default is the column's name. |
| `:colors` | A matplotlib color map: `"viridis"` (the default), `"YlGnBu"`, `"Blues"`, `"YlOrRd"`, `"RdBu"`, ... |
| `:log` | `#t` for a log scale of colors, for values that run from small to very large, such as population. The values must be above 0. |
| `:fill-min`, `:fill-max` | The values at the two ends of the colors. The defaults are the smallest and largest values. Values beyond them get the end colors. |
| `:symbols` | The data column that sizes a symbol on each place. The symbol goes at the center of its largest piece. A symbol's *area* is in proportion to its value, so one twice as big stands for twice as much. A place with no value, or a value of 0 or less, has no symbol. |
| `:symbol-label` | The symbols' legend title. The default is the column's name. |
| `:symbols-on` | Other places to put the symbols on (another table from `census-shapes`), such as ZIP code areas on a map of states. Their codes then match the data. |
| `:symbol-data`, `:symbol-key` | A different table, and key, for the symbols, when the colors and the symbols come from different tables. The defaults are `:data` and `:key`. |
| `:symbol-size` | The largest symbol's width, in points (default 24) |
| `:symbol-color` | The symbols' color (default red). They're partly see-through. |
| `:symbol` | The symbols' shape: `"circle"` (the default), `"square"`, `"triangle"`, `"diamond"`, `"star"`, ... (as for `plot-chart`) |
| `:format` | How the legends write values: a template, such as `"${:,.0f}"` or `"{:.1%}"`, as for `plot-chart`'s `:y-format` |
| `:borders` | Another table from `census-shapes` whose outlines are drawn on top, such as the states' over a map of counties |
| `:edge-color`, `:edge-width` | The places' outlines (default white and thin when colored, gray otherwise) |
| `:title`, `:legend` | The title, and `#f` for no legends |
| `:width`, `:height` | The map's size in inches. The default is 8 wide, and as tall as the map needs. |

The color bar is beside the map. The symbols' sizes (three round values),
and gray for "no data", are shown below it. Returns `'()`.

```lisp
; Every county, colored by per capita personal income (BEA), with the states' borders
(define income (bea-regional creds "CAINC1" 3 "COUNTY" :start-year 2024 :end-year 2024))
(plot-map (census-shapes "county") :data income :key "fips" :fill "2024" :log #t :colors "YlGnBu"
          :format "${:,.0f}" :fill-label "per capita income" :borders (census-shapes "state"))

; New York's counties, with a circle on each ZIP code area, sized by its population (Census)
(define people (census-get creds "acs/acs5" '("B01003_001E") "zip code tabulation area:*"))
(plot-map (census-shapes "county" :state "NY") :symbols-on (census-shapes "zcta")
          :data people :key "zip code tabulation area" :symbols "B01003_001E" :symbol-label "people"
          :format "{:,.0f}")

; Manhattan's census tracts, colored by median household income (Census)
(define incomes (census-get creds "acs/acs5" '("B19013_001E") "tract:*" :within "state:36 county:061"))
(define ny-tracts (census-shapes "tract" :state "NY"))
(define manhattan (table-where ny-tracts "COUNTYFP" "061"))
(plot-map manhattan :data incomes :key '("state" "county" "tract") :fill "B19013_001E"
          :format "${:,.0f}" :fill-label "median household income")
```

### BLS data

(In `lisp_bls.py`.) The Bureau of Labor Statistics' API
(https://www.bls.gov/developers/) has the government's numbers on prices,
jobs, and pay:

- consumer, producer, import, and export prices;
- employment and unemployment for the country, each state, county, and metro area;
- payrolls, hours, and earnings by industry;
- job openings, hires, and quits;
- the employment cost index;
- productivity.

Each of these is a *series* with an ID, such as `CUSR0000SA0` for the CPI. The
BLS's Data Finder (https://data.bls.gov/dataQuery/) finds series IDs, and
https://www.bls.gov/help/hlpforma.htm explains how they are made.

Each function takes the credentials file's path first. Its
`"bureau_of_labor_statistics_api_key"` entry goes with each request, and the
key never appears in an error message. With a key, the BLS allows 500
requests a day, of up to 50 series and 20 years each. These functions split
bigger requests into as many as it takes. Data is kept for 12 hours.

**Dates.** Each value is dated the first day of its period:

| Period | Dated |
|---|---|
| monthly | the first of the month |
| quarterly | the first day of the quarter: April 1 for the second |
| semiannual | January 1 and July 1 |
| annual | January 1 |

Values the BLS doesn't have, written `-`, are NaN. October 2025 is one of
these: it wasn't collected because of the government shutdown.

**Changes from a year before.** Price indexes are levels; inflation is
their change from a year before. `(vector-pct-change column 12)` gives
each value's change from 12 rows before (a year, in a monthly table; use 4
for a quarterly one), as a fraction: `0.03` is 3%. The first 12 rows are
NaN. `vector-diff` gives the difference instead, such as the jobs added
each month (`(vector-diff payrolls 1)`).

#### `(bls-series creds series [:start-year y :end-year y :annual flag])`
One series, or a list or vector of them, as a table. Each series is an ID
or a short name from `bls-names`. The table has a `date` column and a
column per series, headed by the name given, oldest first. Where a series
has no value for a date, the value is NaN, so monthly and quarterly series
line up by date. It covers the last 10 years, unless `:start-year` or
`:end-year` says otherwise.

`:annual #t` gives each year's average instead. Not every series has
averages: seasonally adjusted ones usually don't, so use `"cpi-nsa"` for
the CPI's annual average.

```lisp
(bls-series creds '("cpi" "core-cpi" "unemployment-rate") :start-year 2020)
(bls-series creds "cpi-nsa" :start-year 1980 :annual #t)
(bls-series creds '("SMS36000000000000001" "SMS06000000000000001"))   ; payrolls in NY and CA
```

#### `(bls-names)`
The short names, as a table of `name`, `series-id`, and `description`:

| Name | Series |
|---|---|
| `cpi`, `core-cpi`, `cpi-nsa`, `cpi-food`, `cpi-rent` | Consumer prices (CPI-U). All seasonally adjusted except `cpi-nsa`. |
| `unemployment-rate`, `labor-force-participation`, `employment-population-ratio` | The household survey, in percent |
| `nonfarm-payrolls`, `average-hourly-earnings`, `average-weekly-hours` | The payroll survey |
| `job-openings`, `hires`, `quits` | JOLTS, in thousands |
| `ppi-final-demand` | Producer prices |
| `employment-cost-index`, `productivity` | Quarterly |
| `import-prices`, `export-prices` | Import and export prices |

Other IDs follow patterns:

- **CPI:** `CU`, then `S` or `U` (seasonally adjusted or not), `R`, an area (`0000` for the US), and an item (`SA0` for all items, `SA0L1E` for core).
- **National payrolls:** `CES`, an 8-digit industry (`00000000` for total nonfarm, `05000000` for total private), and a data type (`01` employees, `02` weekly hours, `03` hourly earnings).
- **State payrolls:** `SMS`, the state's FIPS code, `00000`, and the same industry and data type.
- **Local unemployment:** see `bls-local-area`.

#### `(bls-series-info creds series)`
What each series is, as a table of `name`, `series-id`, `title`, `survey`,
and `seasonality`. Some surveys, such as job openings, have no titles. For
a short name, its description from `bls-names` is used in place of a
missing title.

```lisp
(bls-series-info creds '("cpi" "LNS14000000"))
```

#### `(bls-local-area creds places [:start-year y :end-year y])`
States' or counties' labor force, employment, unemployment, and
unemployment rate (in percent), each month, as a table.

- `places` is a state's 2-digit code (`"36"`) or a county's 5-digit code
  (`"36061"`). These are the codes `census-get` gives.
- For one place, the table has a row per month: `date`, `labor-force`,
  `employed`, `unemployed`, and `unemployment-rate`.
- `places` can also be a list or vector of codes, such as a column of
  `census-shapes`' `GEOID`s. Then the table has a row per place per month,
  with the place's code in a `fips` column first. Up to 12 places come in
  one request, so every county in New York (62) takes 6 of the BLS's 500
  requests a day.
- States' numbers are seasonally adjusted; counties' aren't. The BLS
  doesn't adjust them.
- The series behind it are `LA`, then `S` or `U`, a 15-character area
  code, and a measure: `03` is the rate, `04` unemployed, `05` employed,
  `06` labor force.

```lisp
(bls-local-area creds "36")                      ; New York State
(bls-local-area creds "36061" :start-year 2020)  ; New York County (Manhattan)

; Every county in New York, mapped by its unemployment rate in the latest month
(define counties (census-shapes "county" :state "NY"))
(define jobless (bls-local-area creds (table-column counties "GEOID") :start-year 2026))
(define latest (table-where jobless "date" (vector-ref (table-column jobless "date")
                                                       (- (table-row-count jobless) 1))))
(plot-map counties :data latest :key "fips" :fill "unemployment-rate" :fill-label "unemployment rate, %")
```

`examples/census_bls_example.lsp` does these things:

- profiles the states;
- relates income to education across all US counties;
- finds and gets a Census variable;
- works out inflation and real wage growth from the BLS;
- shows Manhattan's unemployment.

### BEA data

(In `lisp_bea.py`.) The Bureau of Economic Analysis's API
(https://apps.bea.gov/api/) has these accounts:

- **The national accounts (NIPA tables):** GDP and its parts, personal
  income and spending, saving, the PCE price index, and corporate profits.
  Each table comes quarterly, monthly, or yearly.
- **The regional accounts:** GDP, personal income, population, and price
  levels for every state, county, and metro area.
- International trade and investment, GDP by industry, and more.

Each function takes the credentials file's path first. Its `"bea_api_key"`
entry goes with each request. The key never appears in an error message:
the BEA's own answers repeat it, so they're cleaned of it first. Data is
kept for 12 hours, and the lists of datasets, parameters, and their values
for 30 days.

**Units.** Amounts in the NIPA tables are given in billions of dollars,
as the BEA's tables show them. The BEA sends them in millions, and these
functions divide by 1,000. Most are at seasonally adjusted annual rates.
Other values come as the BEA sends them:

- price indexes are index numbers (2017 = 100);
- rates and percent changes are percents (`2.5` is 2.5%);
- population is in thousands.

A regional table's values are in its `unit` column, such as `"Dollars"`
or `"Thousands of dollars"`. A value the BEA marks as not available, such
as `(NA)` or `(D)`, is NaN.

**Dates.** A value is dated the first day of its period: a quarter's first
day (2026Q2 is April 1), a month's first day, or January 1 for a year.

**Changes from a year before.** The PCE price index is a level; inflation
is its change from a year before. `(vector-pct-change column 12)` gives
each value's change from 12 rows before (a year, in a monthly table; use 4
for a quarterly one), as a fraction: `0.03` is 3%. The first 12 rows are
NaN. `vector-diff` gives the difference instead, such as the change in the
saving rate.

#### `(bea-series creds names [:start-year y :end-year y :frequency f])`
Headline series by short name, as a table. `names` is one short name or a
list of them. The table has a `date` column and a column for each series,
headed by its name, oldest first. Monthly and quarterly series line up by
date, with NaN where a series has no value. It covers the last 10 years,
unless `:start-year` or `:end-year` says otherwise.

Each series comes at its usual frequency. `:frequency` asks for another:
`"A"` (annual), `"Q"`, or `"M"`. GDP isn't published monthly. A series
published monthly comes from one table, and quarterly or yearly from
another; `bea-series` picks the right one.

| Name | Usual frequency | What it is |
|---|---|---|
| `gdp`, `real-gdp` | quarterly | GDP in billions of dollars, and in billions of chained (2017) dollars |
| `real-gdp-growth` | quarterly | Real GDP, percent change from the quarter before, at an annual rate |
| `gdp-price-index` | quarterly | 2017 = 100 |
| `pce` | monthly | Personal consumption expenditures, billions of dollars |
| `pce-price-index`, `core-pce-price-index` | monthly | The PCE price index, and the index excluding food and energy (the Fed's measure of inflation), 2017 = 100 |
| `personal-income`, `disposable-income`, `real-disposable-income` | monthly | Billions of dollars (real: of chained 2017 dollars) |
| `personal-saving-rate` | monthly | Personal saving, percent of disposable personal income |
| `corporate-profits` | quarterly | With inventory valuation and capital consumption adjustments, billions of dollars |

```lisp
(bea-series creds '("real-gdp-growth" "core-pce-price-index" "personal-saving-rate") :start-year 2020)
(bea-series creds '("gdp" "personal-saving-rate") :frequency "A")
```

#### `(bea-names)`
The short names, as a table of `name`, `frequency` (its usual one),
`published` (the frequencies it comes at), `table` and `line` (where it
is, at its usual frequency), and `description`.

#### `(bea-nipa creds table [:frequency f :start-year y :end-year y :lines l])`
Any NIPA table, by its name, as a table. For example, `"T10101"` is the
percent change in real GDP, and `"T20600"` is personal income and its
disposition, monthly. The table has a `date` column and a column for each
of its lines. Each column is headed by its line's description. When two
lines have the same description, such as exports' and imports' `Goods`,
the line number is added: `Goods (line 17)`.

- `:lines` picks lines: a line number, or a list of them.
- `:frequency` is `"Q"`, `"M"`, or `"A"`. Without it, the table comes
  quarterly if it has quarterly data, or else monthly, or else annually.
- It covers the last 10 years, unless `:start-year` or `:end-year` says
  otherwise.

`bea-parameter-values` finds a table:
`(bea-parameter-values creds "NIPA" "TableName" "personal income")`.

```lisp
(bea-nipa creds "T10102" :lines '(1 2 7 15 22))     ; contributions to GDP growth, by its parts
(bea-nipa creds "T20600" :lines 35 :start-year 1990)  ; the saving rate, monthly
```

#### `(bea-nipa-lines creds table [:frequency f])`
A NIPA table's lines, as a table:

- `line`, `description`, and `series-code` (the BEA's code for the line);
- `unit`, as the BEA gives it, such as `"Level"` or `"Percent change, annual rate"`;
- `scale`: `"billions"` for amounts in billions (sent in millions),
  `"thousands"`, or nothing.

It lists the lines with data in the last two years.

#### `(bea-regional creds table line geography [:start-year y :end-year y])`
One statistic of a regional table, for each place. For example, table
`"SAINC1"`, line 3 is per capita personal income by state. The result is
a table with a row for each place:

- `fips`: the BEA's 5-character code for the place. A state's code is its
  FIPS code followed by `000` (New York is `36000`). A county's is its
  5-digit FIPS code.
- `name`.
- A column for each year, or each quarter (`"2025Q1"`) for a quarterly table, oldest first.
- `unit`.

It covers the last 5 years with data, unless `:start-year` or `:end-year`
says otherwise.

`geography` is one of these, or a list of codes:

- `"STATE"` for every state. This also gives the US (`00000`) and the
  BEA's eight regions (`91000` to `98000`).
- `"COUNTY"` for every county.
- `"MSA"` for every metro area.
- A state's abbreviation, such as `"NY"`, for its counties.
- A code: a state's 2-digit FIPS code (`"36"`, as `census-get` gives it),
  or a 5-digit code for a county or a metro area.

Some regional tables:

| Table | What it is |
|---|---|
| `SAINC1`, `CAINC1` | Personal income, population, and per capita personal income, by state and by county |
| `SQINC1` | Personal income by state, quarterly |
| `SAGDP1`, `SQGDP1`, `CAGDP2` | GDP by state (annual and quarterly) and by county |
| `SARPP` | Regional price parities by state: price levels relative to the US |

`(bea-parameter-values creds "Regional" "TableName")` lists them all.

```lisp
(bea-regional creds "SAINC1" 3 "STATE")                        ; per capita income, every state
(bea-regional creds "CAINC1" 3 "NY" :start-year 2015)          ; every county in New York
(bea-regional creds "SQGDP1" 1 '("36" "06" "48"))               ; real GDP, quarterly, three states
```

#### `(bea-regional-lines creds table)`
The statistics (lines) a regional table has, as a table of `line` and
`description`.

#### `(bea-get creds dataset [parameters])`
Any of the BEA's datasets, as the API gives it, as a table with a column
for each field. `parameters` is a list of `(name . value)` pairs, as the
API takes them. `DataValue` is a number, but not scaled: use `UNIT_MULT`,
the power of 10 it's in.

```lisp
(bea-get creds "GDPbyIndustry" '(("TableID" . "1") ("Frequency" . "A") ("Year" . "2024") ("Industry" . "ALL")))
```

#### `(bea-datasets creds)`, `(bea-parameters creds dataset)`, `(bea-parameter-values creds dataset parameter [search])`
What there is to ask for:

- `bea-datasets`: the datasets, as a table of `name` and `description`.
- `bea-parameters`: the parameters a dataset takes, as a table of `name`,
  `description`, `required`, `multiple` (whether it takes a list of
  values, separated by commas), and `all` (the value that means all of
  them).
- `bea-parameter-values`: the values a parameter can have, as a table of
  `value` and `description`. With `search`, only those that contain it.

`examples/bea_example.lsp` shows these things:

- the latest headline numbers;
- a stacked bar chart of what made GDP grow;
- core PCE inflation and the saving rate, in panels;
- the 15 states with the highest per capita income.

### SQLite

(In `lisp_sqlite.py`.) Builtins for reading and writing a local SQLite
database file, built on Python's standard-library `sqlite3` module. There
are two ways to get a query's results, matching two different needs:

- `sqlite-query` runs a statement to completion and hands back the WHOLE
  result set at once as a table (see "Tables", in the [language manual](lisp_interpreter_reference.md#tables)) — a list of
  `(name . vector)` columns.
- `sqlite-execute` + `sqlite-fetch-row` run a statement and then step
  through it one row at a time, for a result set you'd rather not
  materialize all at once, or want to process row-by-row in a loop.

`sqlite-write-table` goes the other way, saving a table as a SQLite table.

Both accept an optional trailing `params` argument — a Lisp list of values
bound, in order, to `?` placeholders in the SQL text, via SQLite's own
native parameter binding (not string-building), which is what makes this
safe against SQL injection no matter what a value contains. Writing the
placeholders and the query text that will fill them by hand is easy to get
out of sync on a query with more than a couple of parameters; `template.lsp`
(in `lib/`) is a small templating engine built to generate both
together instead — write `{{name}}` right where a value belongs (e.g.
`"...WHERE state = {{state}}"`), and `template-render-sql` produces the
`"?"`-ified SQL text and the matching params list as one pair; `{{name}}` is
ALWAYS a bound parameter there, never text spliced into the query, so it
can't be used to build an unsafe query even by accident. `template.lsp` is
also a general-purpose text templating engine on its own (variable
substitution, with format specs as `format` takes them, `{{#each}}`
loops, `{{#if}}` conditionals) — see its own
header comment for the full syntax and worked examples, and
`sqlite-query-template`/`sqlite-execute-template` (also there) for running
a template against a connection in one call.

#### `(sqlite-open "path/to/db.sqlite")`
Opens (creating it first if it doesn't already exist, same as Python's
`sqlite3.connect`) a SQLite database file and returns a connection value —
pass it to `sqlite-query`, `sqlite-execute`, and `sqlite-close`. Raises
`LispError` if the file can't be opened as a SQLite database.

#### `(sqlite-close conn)`
Closes a connection opened by `sqlite-open`. Returns `'()`.

Rather than calling `sqlite-open` and `sqlite-close` yourself, you can use
`(with-sqlite (conn "path/to/db.sqlite") body...)` (see "Standard
macros"). It opens the database, runs the body, and closes the connection
even if the body stops with an error:

```lisp
(with-sqlite (conn "loans.db")
  (sqlite-query conn "SELECT * FROM pools WHERE state = ?" '() '() (list "CA")))
```

#### `(sqlite-query conn "SELECT ..." [dtypes max-rows params])`
Runs a SQL statement and returns its ENTIRE result set at once, column-wise:
a table — a Lisp list of `(name . vector)` columns, one per output
column, in query order, named as the query names them. Each column is read
the way `load-csv` reads a CSV column: if every value that isn't `NULL` is
a number, the column is a vector of numbers with `nan` for `NULL`; if
every one is text in the form `YYYY-MM-DD`, it's a vector of dates (SQLite
has no date type, so that's how `sqlite-write-table` stores dates);
otherwise the values come back as they are, with `NULL` as `'()`. Raises
`LispError` on a SQL error (bad syntax, unknown column/table, etc) or if
`conn` isn't a value from `sqlite-open`.

```lisp
(define conn (sqlite-open "donors.db"))
(define cols (sqlite-query conn "SELECT name, amount FROM donors ORDER BY amount DESC"))
(display-table cols)                       ; shown as a table
(write-columns-csv "donors.csv" cols)      ; or straight out to a CSV file
(sqlite-close conn)
```

**`dtypes` and `max-rows`** — two optional arguments for a *huge* result
(tens of millions of rows), where the ordinary path above — grow a plain
Python list per column as rows stream in, then have each column's vector
figure out its own dtype by scanning every value — means briefly holding
the whole result twice over (once as a list of individually-boxed values,
once as the final packed vector) and spending real time on that scan.

`dtypes`: a string with exactly one character per output column, in query
order — `"B"`/`"I"`/`"F"` (case-insensitive) for Boolean/Integer/Float,
forcing that column straight to a vector of
`LispVector.BOOL_INT_DTYPE`/`INT_DTYPE`/`FLOAT_DTYPE` (see "Vectors", in the [language manual](lisp_interpreter_reference.md#vectors),
above) instead of inferring it from the data. Any other character —
conventionally `.` — leaves that one column un-hinted, inferred the normal
way, so a `dtypes` string only needs real letters over a query's numeric
columns; a text column, say, can be left un-hinted in an otherwise-hinted
query. **Hints are trusted, not verified against the data**: a value the
hinted dtype genuinely can't hold — a `NULL` in a `B`/`I` column (there's
no integer NaN), a string, a number too big for the dtype — raises a
`LispError` naming the row and column it happened at, but a value that
merely doesn't *match* — e.g. a fractional number arriving in an `"I"`
column — is silently truncated exactly the way an unchecked `vector-set!`
would be (see "Vectors", in the [language manual](lisp_interpreter_reference.md#vectors) for the general dtype-widening machinery this
bypasses on purpose, for speed). A `NULL` in an `"F"` column becomes `NaN`
instead of erroring, matching numpy/pandas' own convention for a missing
float — no special handling needed for that case specifically.

`max-rows`: an upper bound on how many rows the query will return. Given
*together with* `dtypes`, every hinted column's vector is allocated once,
up front, at this size, and each row's values are written directly into it
as they stream from the cursor — no intermediate Python list for that
column at all, and no separate dtype-scanning pass afterward (an un-hinted
column, if any, still collects into a plain list either way, since its
eventual dtype isn't known until every value's been seen). If the query
actually returns *more* than `max-rows` rows, that's a `LispError` — raise
the bound, or drop `max-rows` to fall back to an ordinary, unbounded
collection — rather than silently reallocating past the bound you gave, or
silently dropping rows.

Measured on a 3-column, 2,000,000-row table: `dtypes` alone cuts query time
by about 4x (skipping the per-value wrapping and the dtype-inference scan);
adding `max-rows` on top cuts peak memory by roughly 45% further (skipping
the intermediate Python list entirely, for hinted columns).

```lisp
(define big (sqlite-query conn "SELECT id, balance, delinquent FROM loans"
                           "IFB" 10000000))    ; up to 10M rows expected
```

**`params`** (last argument, so existing 2/3/4-argument calls keep working
unchanged): a Lisp list of values bound, in order, to `?` placeholders in
`sql`, via SQLite's own parameter binding — the value is sent to SQLite
separately from the SQL text, so it's never interpreted as SQL syntax no
matter what it contains, which is what actually prevents SQL injection (as
opposed to splicing a value into the query string, safely or not). See
"SQLite", above, for `template.lsp`, a small templating engine for
generating the `"?"`-placeholder text and this params list together instead
of writing both by hand and keeping them in sync yourself.

```lisp
(sqlite-query conn "SELECT * FROM loans WHERE state = ? AND balance > ?"
              '() '() (list "CA" 100000))
```

#### `(sqlite-write-table conn name table [mode])`
Saves a table (a list of `(name . vector)` columns — see "Tables", in the [language manual](lisp_interpreter_reference.md#tables)) as a
SQLite table called `name`, and returns how many rows were written.
`mode` says what to do if a table with that name already exists:

- `'create` (the default) — it's an error, so nothing is overwritten by
  accident;
- `'replace` — drop it and write the new table in its place;
- `'append` — add the rows to it (its columns must have the same names).

Each column gets the SQLite type `INTEGER`, `REAL`, or `TEXT` to match its
vector. Dates are stored as `YYYY-MM-DD` text, which `sqlite-query` reads
back as dates; `nan` and `'()` are stored as `NULL`. All the rows are
written in one transaction — fast, even for millions of rows — and if
anything goes wrong, the database is left unchanged. Table and column
names can contain spaces or other symbols; they're quoted.

```lisp
(define conn (sqlite-open ":memory:"))          ; a database held in memory
(define t (make-table "id" (vector "a" "b") "balance" (vector 100.5 nan)
                      "as_of" (vector (date 2024 1 1) (date 2024 2 1))))
(sqlite-write-table conn "loans" t)              ; => 2
(sqlite-query conn "SELECT * FROM loans")        ; => (("id" . #("a" "b")) ("balance" . #(100.5 nan)) ("as_of" . #(2024-01-01 2024-02-01)))
(sqlite-write-table conn "loans" t 'append)      ; => 2
```

#### `(sqlite-execute conn "SELECT ..." [params])`
Runs a SQL statement and returns a CURSOR immediately, without reading any
rows yet — pass it to `sqlite-fetch-row`, repeatedly, to pull one row at a
time. Also fine for a non-`SELECT` statement (`INSERT`/`UPDATE`/`CREATE
TABLE`/...); `sqlite-fetch-row` on the resulting cursor just returns `'()`
right away, since there's nothing to fetch. `params`: same as
`sqlite-query`'s. Raises `LispError` the same way `sqlite-query` does.

#### `(sqlite-fetch-row cursor)`
Pulls the next row from a cursor returned by `sqlite-execute`, as a Lisp
list of that row's values in column order (same NULL/text/number
conversion as `sqlite-query`), or `'()` once every row has already been
fetched — so a plain `while`/`null?` loop drains a cursor one row at a time:

```lisp
(define conn (sqlite-open "donors.db"))
(sqlite-execute conn "CREATE TABLE IF NOT EXISTS donors (name TEXT, amount REAL)")
(define cur (sqlite-execute conn "SELECT name, amount FROM donors ORDER BY name"))
(define row (sqlite-fetch-row cur))
(while (not (null? row))
  (begin
    (display (car row)) (display ": ") (display (car (cdr row))) (newline)
    (set! row (sqlite-fetch-row cur))))
(sqlite-close conn)
```

`sqlite-connection?` and `sqlite-cursor?` are the matching type predicates,
alongside `date?`/`vector?`/`struct?` and the rest (see "Comparison /
equality / booleans").

### tastytrade (real broker data)

Requires the `tastytrade` package (`pip install tastytrade`, version 12 or
later) and a tastytrade account. One general function, `tastytrade-get`,
makes any of the requests for information that tastytrade's API offers;
the others are special cases of it, for what's most often wanted: quotes,
option chains, and futures curves. **Every request only reads** — nothing
here places, changes, or cancels an order.

The functions that use the network take `credentials-path` first: a local
JSON file,
```json
{"client_secret": "...", "refresh_token": "...", "is_test": false}
```
(`is_test` defaults to `false` if omitted). This is the same file
`fred-table` reads a `"fred_api_key"` entry from, so one JSON file can
hold both APIs' credentials. See `tasty_api/README.md` for the one-time
OAuth setup (create an OAuth application on tastytrade, save the client
secret, then use "Create Grant" to generate a refresh token — refresh
tokens don't expire).

A request takes about a fifth of a second. The first one also logs in,
which takes about a second more; the login is good for 15 minutes, and
it's kept and reused by the calls after it, for each credentials file,
until it runs out (when the next call logs in again by itself). They all
work in a Jupyter notebook too.

`tastytrade-products` uses no network: it lists the futures product codes.
Nor do `futures-curve-fit` and `futures-leg-carry` (in `lisp_futures.py`),
which analyze a futures curve already fetched with
`tastytrade-futures-curve-rows`, so you can fetch a curve once and re-run
either analysis as often as you like.

#### `(tastytrade-get credentials-path path [parameters])`
The answer to any of tastytrade's requests for information, as Lisp data.
The requests are listed at https://developer.tastytrade.com/open-api-spec/ .
`path` is the request's path, such as `"/market-metrics"`, or a list of
its parts, such as `(list "option-chains" "BRK/B")`: each part is encoded,
so a `/` or a space in a symbol can't be taken for part of the path.
`parameters` is a list of `(name . value)` pairs, or a hash table. A value
that's a list is sent once for each of its items — `(cons "symbol[]"
(list "AAPL" "MSFT"))` asks about both — a date is sent as `YYYY-MM-DD`,
and `#t`/`#f` as `true`/`false`.

The result is the `data` part of tastytrade's JSON answer, as
`http-get-json` returns JSON: an object becomes a hash table with string
keys (read it with `hash-table-ref`), an array a list, `true`/`false`
`#t`/`#f`, and `null` `'()`. tastytrade sends decimal numbers as text with
a decimal point — `"765.53"`, `"10.0"` — and those become numbers; text
without a decimal point, such as an ID or a CUSIP, stays text. An answer
that comes in pages (a long list of transactions, say) is put together
from all of them, unless `parameters` asks for one page with
`"page-offset"`. A request tastytrade refuses is an error that says what
tastytrade said.

Some requests worth knowing:

| Path | What it gives |
|---|---|
| `/market-data/by-type` | Quotes, with the symbols in parameters named `equity`, `equity-option`, `future`, `future-option`, `index`, and `cryptocurrency`, up to 100 in all. `tastytrade-quotes` uses this. |
| `/market-metrics` | For the symbols in parameter `symbols` (`"SPY,QQQ"`): implied volatility, its rank and percentile, liquidity, beta, and earnings and dividend dates |
| `/option-chains/SYMBOL` | Every option on an equity or index; `/option-chains/SYMBOL/nested` groups them by expiration and strike |
| `/futures-option-chains/ROOT` | Every option on a futures product, such as `CL` |
| `/instruments/equities/SYMBOL`, `/instruments/equity-options/SYMBOL`, `/instruments/futures/SYMBOL` | What tastytrade knows about one instrument |
| `/customers/me/accounts` | Your accounts |
| `/accounts/NUMBER/positions`, `/accounts/NUMBER/balances` | An account's positions and balances |
| `/accounts/NUMBER/transactions` | An account's transactions (parameters `start-date`, `end-date`, ...) |
| `/accounts/NUMBER/orders/live` | Today's orders |

A request your login isn't allowed to make — the OAuth grant decides
which — is refused with `Token has insufficient scopes for this request`.
(Asking about several options at once, as `/instruments/equity-options`
with `symbol[]`, can be refused that way while asking about one at a
time, with the symbol in the path, is allowed.)

```lisp
(define creds "tastytrade_credentials.json")
(define spy (tastytrade-get creds (list "instruments" "equities" "SPY")))
(hash-table-ref spy "description")       ; "State Street SPDR S&P 500 ETF Trust"
(define metrics (tastytrade-get creds "/market-metrics" '(("symbols" . "SPY,QQQ"))))
(map (lambda (m) (hash-table-ref m "implied-volatility-index-rank"))
     (hash-table-ref metrics "items"))  ; (0.3496 0.4733), say
```

#### `(tastytrade-get-table credentials-path path [parameters])`
The same request as `tastytrade-get`, with what it returns as a table
(see "Tables", in the [language manual](lisp_interpreter_reference.md#tables)): a row for each of the answer's `items`, or one row if the
answer is a single object. Each key becomes a column, as `table-from-rows`
makes a table from hash tables: a value that is itself an object or a
list is left out, and `true`/`false` become 1 and 0.

```lisp
(display-table (table-select (tastytrade-get-table creds "/market-metrics" '(("symbols" . "SPY,QQQ")))
                             '("symbol" "implied-volatility-index" "implied-volatility-index-rank"))
               '(("implied-volatility-index" ".1%") ("implied-volatility-index-rank" ".1%")))
```

#### `(tastytrade-quotes credentials-path symbols)`
The current bid, ask, and more, for one symbol or a list of them, as a
table with a row for each, in the order given. The symbols can be any
mix of:

| Symbol | Kind |
|---|---|
| `"SPY"`, `"BRK/B"`, `"SPX"` | a stock, ETF, or index |
| `"SPY   261218C00700000"` | an equity option, in OCC's form: the root padded with spaces to six characters, the expiration as YYMMDD, `C` or `P`, and the strike times 1000 in eight digits — as `tastytrade-option-chain`'s `symbol` column has it |
| `"/CLZ6"` | a futures contract |
| `"./CLX6 LO1X6 261117P60"` | a futures option, as `tastytrade-option-chain` has it |
| `"BTC/USD"` | a cryptocurrency |

The columns: `symbol`, `instrument-type`, `bid`, `ask`, `mid`, `mark`,
`last`, `bid-size`, `ask-size`, `volume`, `open-interest`,
`implied-volatility`, `delta`, `gamma`, `theta`, `vega`, `prev-close`, and
`updated-at` (when tastytrade last updated it, as text). The implied
volatility and Greeks are there for options only; a value tastytrade
doesn't give, or a symbol it doesn't know, is missing (`nan`, or `'()`).
It asks for 100 symbols at a time, so any number can be given.

```lisp
(define q (tastytrade-quotes creds (list "SPY" "SPY   261218C00700000" "/CLZ6")))
(display-table (table-select q '("symbol" "bid" "ask" "mid" "implied-volatility")))
(vector-ref (table-column q "ask") 1)   ; the option's ask
```

#### `(tastytrade-option-chain credentials-path symbol [n-months max-strikes-per-expiration])`
Fetches an option chain — for a CME futures product **or for any equity
symbol** — with each option's current bid and ask. Returns a **table**
(see "Tables", in the [language manual](lisp_interpreter_reference.md#tables)), one row per option, sorted by expiration and then strike,
with these columns:

| Column | What it holds |
|---|---|
| `symbol` | the option's symbol, which `tastytrade-quotes` takes too |
| `type` | `"Call"` or `"Put"` |
| `strike` | the exercise price |
| `expiration-date` | the expiration, a date |
| `days-to-expiration` | a whole number of days |
| `delivery-month` | for a futures option, the contract's delivery month (a date); for an equity option, missing |
| `underlying` | the futures contract, e.g. `"CLZ6"`, or the equity's symbol |
| `underlying-price` | the underlying's price now: the middle of its bid and ask |
| `bid`, `ask`, `mid` | the option's bid, ask, and the middle of the two |
| `last-price` | the option's last trade |
| `implied-volatility` | e.g. `0.23` for 23% |
| `delta` | the option's delta |
| `vega` | how much its price changes for a 1-point change in volatility (from 0.20 to 0.21) |
| `volume`, `open-interest` | contracts |

A value tastytrade didn't report is missing: `nan` in a column of
numbers, `'()` otherwise. A comparison with a missing value is false, so
an option with no open interest never passes a test on open interest.
Being a table, the chain can be filtered, sorted, and summarized with the
table functions a whole column at a time, or looked at one option at a
time with `table-rows` (see "Rows", under "Tables", in the [language manual](lisp_interpreter_reference.md#tables)). `(table-row-count
chain)` is the number of options; `(length chain)` is the number of
columns.

`symbol` is classified into one of three cases:

| Form | Treated as | Notes |
|---|---|---|
| Starts with `"/"`, e.g. `"/CL"` | Futures, using the root exactly as given | tastytrade's own convention — works for **any** futures root, not just ones in `tastytrade-products` |
| A known short code, e.g. `"CL"` | Futures, translated to `"/CL"` | |
| Anything else, e.g. `"AAPL"`, `"BRK/B"` | Equity | used exactly as given (upper-cased) |

For a **futures** chain, `n-months` (default `12`) is how many upcoming
*delivery months* to include (as in `tastytrade-futures-curve`); for an
**equity** chain, how many months ahead to look for expirations. Each
expiration keeps only the `max-strikes-per-expiration` (default `15`)
strikes nearest the underlying's price, calls and puts both.

```lisp
(define creds "tastytrade_credentials.json")
(define chain (tastytrade-option-chain creds "/CL" 2 5))     ; futures, explicit root
(define chain2 (tastytrade-option-chain creds "CL" 2 5))     ; futures, short code (same as above)
(define aapl (tastytrade-option-chain creds "AAPL" 2 10))    ; equity
```

**Filtering and showing a chain.** Fetch it, pick the options that meet
your criteria, and show them. The formats say how to lay out each column
(see "Displaying tables", in the [language manual](lisp_interpreter_reference.md#displaying-tables)):

```lisp
(define spy (tastytrade-option-chain creds "SPY" 2 10))
(define chain-formats
  '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f") ("mid" ",.2f")
    ("implied-volatility" ".1%") ("volume" ",.0f") ("open-interest" ",.0f")))
(display-table spy chain-formats)                ; the whole chain

; Calls expiring in 20 to 60 days with at least 100 contracts open,
; tested a whole column at a time:
(define (column name) (table-column spy name))
(define liquid-calls
  (table-filter spy (vector-and (= (column "type") "Call")
                                (<= 20 (column "days-to-expiration") 60)
                                (>= (column "open-interest") 100))))
(display-table (table-sort liquid-calls "strike") chain-formats)

; Puts over 20% volatility and $1, tested one option at a time:
(define (expensive-put? option)
  (with-struct option
    (and (string=? type "Put") (> implied-volatility 0.20) (> mid 1.0))))
(display-table (filter expensive-put? (table-rows spy)) chain-formats)

; One row per expiration: how many options, and their average volatility.
(display-table (table-group-by spy "expiration-date"
                               '(("options" count) ("average-iv" mean "implied-volatility")))
               '(("average-iv" ".1%")))
```

`examples/option_chain_example.lsp` does all of this and a little more
(a column computed from two others, and one line of text per option).

#### `(tastytrade-futures-curve credentials-path product [n-months])`
Fetches the product's futures term structure. `product` is one of the
futures short codes — `(tastytrade-products)` lists them, e.g. `"ES"`,
`"CL"`, `"GC"`, `"6E"`, `"ZC"`, `"BTC"`; an unknown one is an error that
names them all. `n-months` (default `18`) is how many upcoming calendar
months to check for a listed contract — months that don't exist for this
product (e.g. non-quarterly months on ES/NQ/ZN) are skipped, not an error.
Returns `(cons delivery-dates-vector prices-vector)`, one entry per
contract month that has a price — its settlement price if it has one,
else its last trade — sorted by delivery date, ready for `plot-chart`,
`linear-regression`, `spline-regression`, and so on. For the contracts'
bids and asks, give their symbols (`"/CLZ6"`) to `tastytrade-quotes`.

```lisp
(define curve (tastytrade-futures-curve "tastytrade_credentials.json" "CL" 12))
(plot-chart (list (list "CL" (car curve) (cdr curve))))
```

#### `(tastytrade-futures-curve-rows credentials-path product [n-months])`
The same futures term structure as `tastytrade-futures-curve`, as a list
of rows, each a 4-element list:
```
(delivery-month futures-symbol days-to-delivery price)
```
`futures-symbol` has the leading `"/"` stripped (e.g. `"CLZ6"`);
`days-to-delivery` is an integer (negative if the contract's
first-of-month delivery date has passed but it's still trading). This is
the input `futures-curve-fit` and `futures-leg-carry` take — fetch
once with this, then call either one as often as you like.

```lisp
(define rows (tastytrade-futures-curve-rows "tastytrade_credentials.json" "CL" 8))
(define fit (futures-curve-fit rows 0.75))
```

#### `(tastytrade-test-connection credentials-path)`
Logs in and lists your accounts. Returns a status string naming the
account number(s) found (or noting that logging in worked but there are
no accounts). Raises an error if logging in fails — run this first to
check that your credentials work.

```lisp
(display (tastytrade-test-connection "tastytrade_credentials.json"))
```

#### `(tastytrade-products)`
The futures short codes (around 60) that `tastytrade-futures-curve`,
`tastytrade-futures-curve-rows`, and `tastytrade-option-chain` accept.

```lisp
(tastytrade-products)          ; => ("ES" "MES" "NQ" "MNQ" "YM" "MYM" ... "SR3" ...)
```

#### `(futures-curve-fit curve-rows [rich-cheap-threshold-pct poly-degree])`
(In `lisp_futures.py`.) Pure function — no networking. Per-contract rich/cheap analysis: fits
`ln(price)` vs. `days-to-delivery` with a low-order polynomial across
every row in `curve-rows` (the output of `tastytrade-futures-curve-rows`,
or anything shaped the same way), then flags each contract's deviation
from that fitted curve. This is the futures-curve analogue of bond
rich/cheap-to-curve analysis — generic, and doesn't require any rate
assumption. Returns a Lisp list of rows, each a 7-element list:
```
(delivery-month futures-symbol days-to-delivery last-price
 fitted-price rich-cheap-pct signal)
```
`signal` is the string `"Rich"` if the contract trades more than
`rich-cheap-threshold-pct` (default `0.75`) above the fit, `"Cheap"` if
that far below, else `"Fair"`.

`poly-degree` (optional) controls the fit's polynomial degree; omit it,
or pass `#f`/`'()`, for the automatic default (`min(3, max(1, n-1))`,
where `n` is the row count) — or pass an integer to override it.

Needs at least 3 rows; returns `'()` if `curve-rows` has fewer.

```lisp
(define rows (tastytrade-futures-curve-rows creds "CL" 8))
(define fit (futures-curve-fit rows 0.75))
(define fit-strict (futures-curve-fit rows 0.25))   ; re-run, no re-fetch, tighter threshold
```

#### `(futures-leg-carry curve-rows funding-rate-pct storage-cost-pct [leg-signal-threshold-pct])`
Pure function — no networking. Pairwise (adjacent contract month)
implied cost-of-carry decomposition. For each pair of adjacent months in
`curve-rows` (near, far) with positive spacing between them:
```
c = ln(far-price / near-price) / ((days-between) / 365)      -- OBSERVED
net storage cost  (u - y) = c - r                             -- given r
convenience yield  y = r + u - c                              -- given r AND u
```
where `r` = `funding-rate-pct` / 100 (your assumed annualized funding
rate) and `u` = `storage-cost-pct` / 100 (your assumed annualized storage
cost), both supplied by you as arguments — the model backs out what's
implied by the actual curve, and can't fully separate storage cost from
convenience yield without your `u` assumption too (that limitation is
inherent to the model). Returns a Lisp list of rows, each a 9-element
list:
```
(near-month far-month near-price far-price days-between
 implied-carry-rate-pct implied-net-storage-cost-pct
 implied-convenience-yield-pct signal)
```
`signal` is `"Far month rich / near cheap"` if that leg's implied carry
rate `c` exceeds the *median* carry rate across all legs by more than
`leg-signal-threshold-pct` percentage points (default `1.0`),
`"Far month cheap / near rich"` if that far below, else `"Fair"`.

**Important for non-commodity products:** "storage cost" and
"convenience yield" are physical-commodity concepts. For a storable
physical commodity (`CL`, `MCL`, ...) they have a real economic
interpretation. For financial futures (`ES`, `NQ`, `ZN`, `SR3`, ...)
there's no physical storage — the *math* (the implied carry rate `c`) is
still valid and meaningful, but the storage/convenience-yield split
doesn't map to anything real; read those two fields as "what a
storage-cost story would require to be true, if you insisted on one" for
those products, not as an actual estimate. `futures-curve-fit`'s
per-contract rich/cheap view is the more broadly meaningful of the two
for non-commodity products.

Needs at least 2 rows; returns `'()` if `curve-rows` has fewer, or if no
adjacent pair has positive day spacing.

```lisp
(define legs (futures-leg-carry rows 4.25 3.0 1.0))
```

#### SOFR futures and their options

`sofr-forward-curve` makes a curve of forward rates from SOFR futures' prices (`(tastytrade-futures-curve-rows creds
"SR3" 40)`), and `sofr-calibration-data` fetches SOFR futures and options on them, for fitting the model of interest
rates: see [lisp_paths_manual.md](lisp_paths_manual.md).

**Example** (also runnable as [`tastytrade_example.lsp`](../lisp_interp/examples/tastytrade_example.lsp) —
`python3 ../lisp_interpreter.py tastytrade_example.lsp`, from `examples/`). Exercises all
ten `tastytrade-*` builtins; abridged here:

```lisp
(define creds "tastytrade_credentials.json")   ; edit to your credentials file's path

; confirm the credentials work
(display (tastytrade-test-connection creds)) (newline)

; WTI Crude Oil (CL) futures term structure, next 6 contract months
(define curve (tastytrade-futures-curve creds "CL" 6))

; CL options on the next 2 delivery months, 5 strikes nearest the money
(define chain (tastytrade-option-chain creds "CL" 2 5))
(display-table chain '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f")
                       ("implied-volatility" ".1%") ("delta" ".3f")))

; bids and asks for a stock, an index, an equity option, a future, and the
; first CL option in the chain
(define quotes (tastytrade-quotes creds (list "SPY" "SPX" "SPY   261218C00700000" "/CLZ6"
                                              (vector-ref (table-column chain "symbol") 0))))
(display-table (table-select quotes '("symbol" "bid" "ask" "mid" "last")))

; an equity option chain
(define aapl-chain (tastytrade-option-chain creds "AAPL" 2 5))

; rich/cheap analysis and implied carry: fetch the curve rows once, then
; analyze with no further network use
(define curve-rows (tastytrade-futures-curve-rows creds "CL" 8))
(define fit (futures-curve-fit curve-rows 0.75))
(define legs (futures-leg-carry curve-rows 4.25 3.0 1.0))

; anything else the API offers: market metrics as a table, and one
; instrument's description
(display-table (tastytrade-get-table creds "/market-metrics" '(("symbols" . "SPY,QQQ"))))
(hash-table-ref (tastytrade-get creds (list "instruments" "equities" "BRK/B")) "description")
```

### Schwab (your accounts)

(In `lisp_schwab.py`.) Your Charles Schwab accounts, through Schwab's API
(https://developer.schwab.com):

- what's in each account;
- quotes, and daily price histories for stocks and ETFs;
- the options listed on a stock, with their bids and asks;
- what happened in each account: trades, dividends, fees, deposits;
- orders, for whenever you want them.

"Everything Schwab's API can do", at the end of this section, lists every
request Schwab's API takes and how to make it from Lisp.

It needs an app registered on Schwab's developer site, with its key and
secret in the credentials file as `"Schwab_Client_ID"` and
`"Schwab_Client_Secret"`. If the app's callback URL isn't
`https://127.0.0.1`, give it as `"Schwab_Callback_URL"`.

**Signing in.** Schwab signs in with OAuth, so a program never sees your
password. `(schwab-login creds)` opens a small browser window with
Schwab's sign-in page. There you go through whatever steps Schwab uses
for your account: logging in, perhaps two-factor authentication, and
approving the app for one or more of your accounts, which it may ask
about a few times.

- Schwab then sends the window to the app's callback URL, with a code in
  it. The window watches for that, closes, and uses the code to get the
  tokens that let the app connect to Schwab.
- The tokens are kept in `schwab_tokens.json`, next to the credentials
  file, readable only by you.
- The access token lasts 30 minutes and is renewed as needed. The sign-in
  itself lasts 7 days; then `schwab-login` again. A function that needs
  it says so when it has run out.
- The window needs PyQt6's web engine (`pip install PyQt6-WebEngine`).
  Without it, Schwab's page opens in your own browser instead. After you
  sign in, that browser ends on an error page at `https://127.0.0.1/...`;
  paste that address when asked.
- It works from the console, a notebook, or the GUI.

Nothing is cached: every call asks Schwab.

**Accounts are shown by name**, the nickname you gave each one on
Schwab's site; one without a nickname is shown as `...` and the last 4
digits of its number. Wherever a function wants an account (`:account`,
or an order's `account`), give its name (upper or lower case), its
number, or the last 3 or more digits of its number, as text: `"IRA"` or
`"1234"`.

**Every field.** Each table has the most useful of the fields Schwab
sends. The comments in each function in `lisp_schwab.py` list all of
the available fields: dozens of balances for an account, tax-lot prices
for a holding, dividends and P/E for a quote, fills for an order, etc.
`schwab-get` gets any of them, as Lisp data.

#### `(schwab-login creds)`
Sign in, as above. Returns `#t`.

#### `(schwab-accounts creds)`
Each of your accounts, as a table:

- `account`: its name;
- `type`: `CASH` or `MARGIN`;
- `value`: what it would be worth if everything were sold (Schwab's
  liquidation value);
- `cash`;
- `long-value`, `short-value`: the market value of its long and short
  positions.

#### `(schwab-positions creds [:account a])`
What's in your accounts, as a table with a row for each holding in each
account. Its columns:

- `account` (its name), `symbol`, `description`;
- `asset-type`: `EQUITY`, `OPTION`, `MUTUAL_FUND`, ...;
- `quantity`: negative for a short position;
- `average-price`: what was paid, on average;
- `market-value`, `unrealized-gain`, `day-gain`;
- `cusip`.

`:account` picks one account, by its name or number (see above). Cash
isn't a holding: see `schwab-accounts`.

```lisp
(define holdings (schwab-positions creds))
(display-table (table-sort holdings "market-value" #t) '(("market-value" ",.0f") ("unrealized-gain" ",.0f")))
(table-group-by holdings "account" '(("total" sum "market-value")))     ; each account's total
```

#### `(schwab-quotes creds symbols)`
Quotes for a symbol, or a list or vector of them, as a table: `symbol`,
`description`, `bid`, `ask`, `last`, `mark`, `change`, `change-percent`,
`volume`, `52-week-high`, `52-week-low`. A symbol can be a stock, an ETF,
an index (`$SPX`), or an option. One Schwab doesn't know has NaNs.

#### `(schwab-price-history creds symbol [:start-date d :end-date d :frequency f])`
A stock's, ETF's, or index's prices, as a table of `date`, `open`,
`high`, `low`, `close`, and `volume`, oldest first, as Schwab gives them.

- `:frequency` is `"daily"` (the default), `"weekly"`, or `"monthly"`.
- It covers the last 10 years, unless `:start-date` or `:end-date` (dates,
  or `"YYYY-MM-DD"`) says otherwise.

`vector-pct-change` turns closing prices into returns: `(vector-pct-change
(table-column h "close") 1)`.

#### `(schwab-option-chain creds symbol [:expiration d :type t :strikes n])`
The options listed on a stock or ETF, as a table with the columns of
`tastytrade-option-chain`'s -- so whatever takes one takes the other (the
option libraries below do): `symbol` (the option's, in the form orders
use), `type` (`"Call"` or `"Put"`), `strike`, `expiration-date`,
`days-to-expiration`, `delivery-month` (always `'()`), `underlying`,
`underlying-price`, `bid`, `ask`, `mid`, `last-price`,
`implied-volatility` (a fraction: 0.215 is 21.5%), `delta`, `vega`,
`volume`, and `open-interest`. What Schwab doesn't have, as a Greek for an
option with no volatility, is NaN.

- The bids and asks are live while the market is open, and the last close's
  after.
- `:expiration` (a date, or `"YYYY-MM-DD"`) asks for only that
  expiration's options. Without it you get every expiration Schwab has,
  which for a big ETF is a lot: ask for the one you want. If Schwab says it
  cut the chain short (more than it will send at once), this is an error
  rather than a table with strikes missing: ask for less.
- `:type` is `"CALL"`, `"PUT"`, or `"ALL"` (the default).
- `:strikes` asks for only that many strikes nearest the price, in each
  expiration.

```lisp
(define chain (schwab-option-chain creds "SPY" :expiration (date 2026 11 20) :type "CALL"))
(display-table (table-select chain '("strike" "bid" "ask" "volume" "open-interest")) '() :max-rows 10)
```

The comments in `lisp_schwab.py` list every field Schwab's answer has.
It was checked against Schwab's real answer for SPY (221 calls for one
expiration, the same as the number Schwab says it sent). To see the answer
itself, `(schwab-get creds "/marketdata/v1/chains" '(("symbol" . "SPY")
("contractType" . "CALL") ("fromDate" . "2026-11-20") ("toDate" . "2026-11-20")))`.

#### `(schwab-orders creds [:account a :days n])`
The orders entered in the last `n` days (30, unless `:days` says;
Schwab keeps 60), in all your accounts or just `:account`'s, as a table:
`account`, `order-id`, `entered`, `status`, `instruction`, `symbol`,
`quantity`, `filled`, `type`, `price`, `duration`.

#### `(schwab-transactions creds [:account a :days n :type t :symbol s])`
What happened in your accounts in the last `n` days (30, unless `:days`
says): trades, dividends and interest, fees, deposits, withdrawals, and
transfers. A table, oldest first, of:

- `account` (its name), `date`, `type` (Schwab's kind of transaction, as
  below), `description` (Schwab's words, such as `ORDINARY DIVIDEND`);
- `symbol`, `quantity`, `price`: the security, if there is one (a
  deposit has none), how much of it (below 0 for what went out), and at
  what price;
- `amount`: the money that came in, or, below 0, went out, fees and all;
- `fees`: the commission and other fees, as Schwab gives them;
- `transaction-id`.

`:account` picks one account (by its name, as everywhere). `:type` is one
of Schwab's kinds of transaction, or a list of them (upper or lower
case); without it, all of them: `TRADE`, `RECEIVE_AND_DELIVER`,
`DIVIDEND_OR_INTEREST`, `ACH_RECEIPT`, `ACH_DISBURSEMENT`, `CASH_RECEIPT`,
`CASH_DISBURSEMENT`, `ELECTRONIC_FUND`, `WIRE_OUT`, `WIRE_IN`, `JOURNAL`,
`MEMORANDUM`, `MARGIN_CALL`, `MONEY_MARKET`, `SMA_ADJUSTMENT`. `:symbol`
keeps only one security's. How far back Schwab goes is Schwab's to say;
it may refuse a long `:days`.

```lisp
(define dividends (schwab-transactions creds :days 90 :type "DIVIDEND_OR_INTEREST"))
(table-group-by dividends "account" '(("total" sum "amount")))     ; each account's dividends and interest
```

The table was checked only against a stand-in for Schwab, made from
Schwab's documentation of its answer; the comments in `lisp_schwab.py`
list every field that answer has.

#### `(schwab-get creds path [parameters] [:account a])`
The answer to any of the API's requests for information, as Lisp data.
`path` is its path, such as `"/trader/v1/userPreference"` or
`"/marketdata/v1/chains"`, and `parameters` a list of `(name . value)`
pairs. For example, every balance of every account, or a quote's
dividends and P/E:

```lisp
(schwab-get creds "/trader/v1/accounts")
(schwab-get creds "/marketdata/v1/quotes" '(("symbols" . "AAPL") ("fields" . "quote,fundamental")))
```

Schwab's paths name an account by a code of its own, not by its number.
Write `{account}` in the path where the account goes, and name the
account with `:account`, as everywhere else:

```lisp
(schwab-get creds "/trader/v1/accounts/{account}/orders/1004538291" :account "IRA")     ; one order, every field
```

#### Orders: `schwab-order`, `schwab-spread-order`, `schwab-multi-leg-order`, `schwab-preview-order`, `schwab-place-order`, `schwab-cancel-order`
For whenever you want to trade.

- `(schwab-order instruction symbol quantity [:type t :price p :stop-price s :duration d :asset-type a])`
  makes an order, as a hash table in Schwab's form. It sends nothing.
  - The `instruction` for a stock or ETF is `BUY`, `SELL`, `SELL_SHORT`,
    or `BUY_TO_COVER`.
  - For an option (`:asset-type "OPTION"`, with the option's symbol), it's
    `BUY_TO_OPEN`, `BUY_TO_CLOSE`, `SELL_TO_OPEN`, or `SELL_TO_CLOSE`.
  - `:type` is `MARKET` (the default), `LIMIT` (needs `:price`), `STOP`
    (needs `:stop-price`), or `STOP_LIMIT` (needs both).
  - `:duration` is `DAY` (the default), `GOOD_TILL_CANCEL`, or
    `FILL_OR_KILL`.
- `(schwab-spread-order buy-symbol sell-symbol quantity net-debit [:duration d])`
  makes an order for a **vertical spread**: buy one option and sell
  another of the same stock, expiration, and type, for a net debit -- a
  limit on what is paid in all, for a share (rounded to a cent). `quantity`
  is how many spreads, the contracts of each. For calls, the one bought has
  the lower strike; for puts, the higher; the other way round would be a
  credit spread, which this refuses to make, and so it does a pair that
  differ in stock, expiration, or type. The symbols are options' in the form
  the chain has (the stock's, padded to 6 characters, the expiration as
  YYMMDD, `C` or `P`, and the strike times 1000 in 8 digits). It sends
  nothing; it opens new positions (`BUY_TO_OPEN`, `SELL_TO_OPEN`) as a
  single order (`orderType` `NET_DEBIT`, `complexOrderStrategyType`
  `VERTICAL`), both legs filling together or not at all.
- `(schwab-multi-leg-order strategy legs price [:credit #t :duration d])`
  makes an order for the other usual spreads, of one stock and expiration, as
  one order that fills all together or not at all. `strategy` is `VERTICAL`,
  `BUTTERFLY`, `IRON_CONDOR`, `STRADDLE`, or `STRANGLE`; `legs` is a list of
  `(instruction symbol quantity)`, the instruction `BUY_TO_OPEN` or
  `SELL_TO_OPEN`, the symbol an option's (in the form `schwab-spread-order`
  takes), and the quantity the contracts; and `price` is a limit on the net
  debit for a share (what is paid in all), or with `:credit #t` on the net
  credit (what is got), above 0, rounded to a cent. The legs must have the
  shape of the strategy, which it checks, and says what is wrong: a vertical
  is two options of one type, one bought and one sold, in equal numbers; a
  butterfly is three of one type, the strikes equally far apart, the outer two
  bought and the middle sold, in the numbers 1, 2, 1 (or the other way round);
  an iron condor is two puts below two calls, the wings of equal width, the
  outer two bought and the inner two sold (or the other way round), in equal
  numbers; a straddle is a call and a put at one strike, both bought or both
  sold, in equal numbers; and a strangle is a put below a call. It sends
  nothing. `option-spread-order` (see "Option spreads") makes these from a
  search.
- `(schwab-preview-order creds account order)` gives what Schwab makes of
  the order, without placing it: any warnings or reasons it would be
  rejected, and the estimated cost.
- `(schwab-place-order creds account order :confirm #t)` places it, for
  real, and returns its order ID. **Nothing is sent without
  `:confirm #t`.** An app can place 10 orders a day.
- `(schwab-cancel-order creds account order-id)` cancels an order that
  hasn't been filled.

```lisp
(define order (schwab-order "BUY" "VTI" 10 :type "LIMIT" :price 250.00))
(schwab-preview-order creds "IRA" order)               ; check it first
; (schwab-place-order creds "IRA" order :confirm #t)   ; then, if you mean it
```

`schwab-spread-order`'s form of an order is Schwab's, from its documentation
of the Trader API. Schwab's preview accepted one for a SPY call spread (as
a limit order of the strategy `VERTICAL`, for the net debit given, with the
commission and fees, and no warnings), on 2026-10-14. The program's own
tests use a stand-in for Schwab, and no spread order has been placed by it.
Preview yours (that places nothing) before you place it. The forms
`schwab-multi-leg-order` makes for the other strategies, and for a net credit,
are from the same documentation and have not been previewed with Schwab.

#### Everything Schwab's API can do
Every request that Schwab's Trader API takes, and how to make it from
Lisp. The paths and parameters are Schwab's. (Its own documentation, on
https://developer.schwab.com, needs a sign-in; this list agrees with
`schwab-py`, a widely used client for the API.) A function in the second
column gives a table; `schwab-get` gives Schwab's whole answer as Lisp
data (hash tables and lists). Where a path has `{account}`, give
`:account` with the account's name.

**Your accounts**

| What | From Lisp | Schwab's request |
|---|---|---|
| Each account's balances | `schwab-accounts`; every balance: `(schwab-get creds "/trader/v1/accounts")` | `GET /trader/v1/accounts` (`fields=positions` adds the holdings) |
| One account | `(schwab-get creds "/trader/v1/accounts/{account}" :account "IRA")` | `GET /trader/v1/accounts/{account}` (`fields`) |
| What's in each account | `schwab-positions` | the two above, with `fields=positions` |
| Account numbers and their codes | used inside, to find an account by name | `GET /trader/v1/accounts/accountNumbers` |
| Your preferences: each account's nickname, and what the streaming service needs | `(schwab-get creds "/trader/v1/userPreference")` | `GET /trader/v1/userPreference` |
| Transactions | `schwab-transactions` | `GET /trader/v1/accounts/{account}/transactions` (`startDate`, `endDate`, `types`, `symbol`) |
| One transaction, every field | `(schwab-get creds "/trader/v1/accounts/{account}/transactions/ID" :account "IRA")` | `GET /trader/v1/accounts/{account}/transactions/ID` |

**Orders**

| What | From Lisp | Schwab's request |
|---|---|---|
| Orders in all accounts | `schwab-orders` | `GET /trader/v1/orders` (`fromEnteredTime`, `toEnteredTime`, `maxResults`, `status`) |
| Orders in one account | `(schwab-orders creds :account "IRA")` | `GET /trader/v1/accounts/{account}/orders` (the same) |
| One order, every field | `(schwab-get creds "/trader/v1/accounts/{account}/orders/ID" :account "IRA")` | `GET /trader/v1/accounts/{account}/orders/ID` |
| Preview an order | `schwab-preview-order` | `POST /trader/v1/accounts/{account}/previewOrder` |
| Place an order | `schwab-place-order` | `POST /trader/v1/accounts/{account}/orders` |
| Cancel an order | `schwab-cancel-order` | `DELETE /trader/v1/accounts/{account}/orders/ID` |
| Replace an order with another | not done here: cancel it and place the new one | `PUT /trader/v1/accounts/{account}/orders/ID` |

An order's `status` is one of `AWAITING_PARENT_ORDER`,
`AWAITING_CONDITION`, `AWAITING_STOP_CONDITION`, `AWAITING_MANUAL_REVIEW`,
`ACCEPTED`, `AWAITING_UR_OUT`, `PENDING_ACTIVATION`, `QUEUED`, `WORKING`,
`REJECTED`, `PENDING_CANCEL`, `CANCELED`, `PENDING_REPLACE`, `REPLACED`,
`FILLED`, `EXPIRED`, `NEW`, `AWAITING_RELEASE_TIME`,
`PENDING_ACKNOWLEDGEMENT`, `PENDING_RECALL`, `UNKNOWN`. To see only the
orders still working:
`(schwab-get creds "/trader/v1/orders" '(("status" . "WORKING") ("fromEnteredTime" . "2026-10-01T00:00:00.000Z") ("toEnteredTime" . "2026-10-29T00:00:00.000Z")))`.

**Market data**

| What | From Lisp | Schwab's request |
|---|---|---|
| Quotes for several symbols | `schwab-quotes` | `GET /marketdata/v1/quotes` (`symbols`; `fields`: `quote`, `fundamental`, `extended`, `reference`, `regular`; `indicative`) |
| A quote for one symbol | `(schwab-get creds "/marketdata/v1/AAPL/quotes")` | `GET /marketdata/v1/SYMBOL/quotes` (`fields`) |
| An option chain | `schwab-option-chain` | `GET /marketdata/v1/chains` (below) |
| The expiration dates of a stock's options | `(schwab-get creds "/marketdata/v1/expirationchain" '(("symbol" . "SPY")))` | `GET /marketdata/v1/expirationchain` (`symbol`) |
| Daily, weekly, or monthly prices | `schwab-price-history` | `GET /marketdata/v1/pricehistory` (below) |
| Prices by the minute | `(schwab-get creds "/marketdata/v1/pricehistory" '(("symbol" . "SPY") ("periodType" . "day") ("period" . "1") ("frequencyType" . "minute") ("frequency" . "5")))` | the same |
| The biggest movers in an index | `(schwab-get creds "/marketdata/v1/movers/$SPX" '(("sort" . "PERCENT_CHANGE_UP")))` | `GET /marketdata/v1/movers/INDEX` (`sort`, `frequency`) |
| When markets open and close | `(schwab-get creds "/marketdata/v1/markets" '(("markets" . "equity,option")))` | `GET /marketdata/v1/markets` (`markets`, `date`) |
| One market's hours | `(schwab-get creds "/marketdata/v1/markets/equity")` | `GET /marketdata/v1/markets/MARKET` (`date`) |
| Find a security by symbol or description | `(schwab-get creds "/marketdata/v1/instruments" '(("symbol" . "vanguard") ("projection" . "desc-search")))` | `GET /marketdata/v1/instruments` (`symbol`, `projection`) |
| A security by its CUSIP | `(schwab-get creds "/marketdata/v1/instruments/037833100")` | `GET /marketdata/v1/instruments/CUSIP` |

The parameters, where they have choices:

- **Option chains** (`/chains`): `symbol`; `contractType` (`CALL`, `PUT`,
  `ALL`); `strikeCount`; `includeUnderlyingQuote`; `strategy`
  (`SINGLE`, `ANALYTICAL`, `COVERED`, `VERTICAL`, `CALENDAR`, `STRANGLE`,
  `STRADDLE`, `BUTTERFLY`, `CONDOR`, `DIAGONAL`, `COLLAR`, `ROLL`);
  `interval`; `strike`; `range` (`ITM`, `NTM`, `OTM`, `SAK`, `SBK`, `SNK`,
  `ALL`); `fromDate` and `toDate` (`YYYY-MM-DD`); for `ANALYTICAL`,
  `volatility`, `underlyingPrice`, `interestRate`, and
  `daysToExpiration`; `expMonth` (`JAN` ... `DEC`, `ALL`); `optionType`
  (`S`, `NS`, `ALL`); `entitlement` (`PP`, `NP`, `PN`).
- **Price history** (`/pricehistory`): `symbol`; `periodType` (`day`,
  `month`, `year`, `ytd`) and `period` (how many of them); `frequencyType`
  (`minute`, `daily`, `weekly`, `monthly`) and `frequency` (for minutes,
  1, 5, 10, 15, or 30); `startDate` and `endDate` (milliseconds since
  1970); `needExtendedHoursData`; `needPreviousClose`.
- **Movers** (`/movers/INDEX`): the index is `$DJI`, `$COMPX`, `$SPX`,
  `NYSE`, `NASDAQ`, `OTCBB`, `INDEX_ALL`, `EQUITY_ALL`, `OPTION_ALL`,
  `OPTION_PUT`, or `OPTION_CALL`; `sort` is `VOLUME`, `TRADES`,
  `PERCENT_CHANGE_UP`, or `PERCENT_CHANGE_DOWN`; `frequency` is 0, 1, 5,
  10, 30, or 60.
- **Market hours** (`/markets`): `markets` is any of `equity`, `option`,
  `bond`, `future`, `forex`, joined by commas; `date` is `YYYY-MM-DD`.
- **Instruments** (`/instruments`): `projection` is `symbol-search`,
  `symbol-regex`, `desc-search`, `desc-regex`, `search`, or `fundamental`
  (the last gives a stock's fundamentals: P/E, dividend yield, and so on).

**Streaming.** Schwab also sends live quotes, charts, order books, and
your account's activity as they happen, over a WebSocket (its address and
your sign-in for it are in `/trader/v1/userPreference`'s `streamerInfo`).
That isn't done here: every function asks once and answers once.

### FINRA (agency MBS and TBA prices)

(In `lisp_finra.py`.) The prices that agency mortgage-backed securities
traded at each day, from FINRA (https://developer.finra.org), which
collects every trade in them through TRACE. They are not quotes or a
model's prices: they summarize the trades of the day, for each kind of
security.

- **TBAs**: UMBS, Freddie Mac, and Ginnie Mae single-family 15- and
  30-year, by coupon and settlement month (usually this month and next).
- **Specified pools**: fixed-rate pass-throughs, by agency and coupon.
- **ARMs and hybrids**: specified pools, by agency and fixed-rate period
  (5/1, 7/1, ...).

FINRA's API needs an account, which is free: an Individual account (from
"Console" on https://developer.finra.org) with a "Public" credential,
whose fee is $0 a month. FINRA emails a link to set the credential's
secret. Its client ID and secret go in the credentials file as
`"finra_client_id"` and `"finra_client_secret"`. The secret runs out
after a year.

A day's prices come the next morning, and there are none for weekends
and holidays. Each answer is kept for 12 hours, as the other data
functions' are (`(http-clear-cache)` deletes them).

Each table has a row for each day, `product` (`SINGLE FAMILY 30Y`, ...),
`agency`, `settlement` (for TBAs), and `coupon` (or `period`, for ARMs),
and a column for each of the ten statistics FINRA gives, named as FINRA
names them, in lower case: the average price, the weighted average price
(weighted by size), the average of the 5 lowest trades, the quartiles,
the average of the 5 highest trades, the standard deviation of the
prices, the dollar volume of the trades (in thousands), and the number of
trades. A statistic FINRA has no value for is NaN. A coupon is FINRA's
bucket, as text: `"<= 3.5"`, `"4"`, ... `"> 6"`.

#### `(finra-tba-prices creds [:start-date d :end-date d :agency a])`
The prices TBAs traded at each day. The last week, unless `:start-date`
or `:end-date` (dates, or `"YYYY-MM-DD"`) says otherwise. `:agency` is
`"UMBS"`, `"FHLMC"`, or `"GNMA"`, or a list of them.

```lisp
(define tbas (finra-tba-prices creds :agency "UMBS"))
(display-table (table-where tbas "product" "SINGLE FAMILY 30Y"))
```

#### `(finra-mbs-prices creds [:start-date d :end-date d :agency a])`
The prices specified pools (fixed-rate pass-throughs) traded at each day,
in the same form, without `settlement`. Comparing a coupon's price with
the TBA's shows the pay-up for specified pools.

#### `(finra-arm-prices creds [:start-date d :end-date d :agency a])`
The prices specified ARM and hybrid pools traded at each day, with a
`period` column (`5/1`, `7/1`, ...) in place of `coupon`.

#### `(finra-get creds group dataset [:start-date d :end-date d :filters f])`
Any of the datasets of FINRA's API, as a table with a column for each of
its fields, as FINRA sends them. `group` and `dataset` are FINRA's names,
from its catalog (https://developer.finra.org/catalog). `:start-date` and
`:end-date` ask for those report dates (the last week, if only one is
given); `:filters` is a list of `(field . value)` pairs, and keeps the
records whose field has that value. The others a Public credential can
read include, all in the group `"fixedIncomeMarket"`:

| Dataset | What |
|---|---|
| `agencyMbsTradingActivity` | How much traded each day: trades, securities, and dollars, for TBAs, specified pools, and CMOs |
| `agencyCmoPricing` | Agency CMO prices, by deal vintage |
| `nonAgencyCmoVintagePricing`, `nonAgencyCmoAbsPricing` | Non-agency CMO and ABS prices |
| `dailyCmbsPricing`, `weeklyCmbsPricing` | CMBS prices, by deal vintage |
| `collateralizedObligationPricing` | CBO, CDO, and CLO prices, by rating and vintage |
| `treasuryDailyAggregates`, `treasuryMonthlyAggregates` | How much of each kind of Treasury traded (no prices) |

```lisp
(finra-get creds "fixedIncomeMarket" "agencyMbsTradingActivity" :filters '(("agencyCode" . "GNMA")))
```

These functions were written from FINRA's documentation of its API and
tested against a stand-in for FINRA; they haven't yet been run against
FINRA itself.

### Alpha Vantage (dividends)

(In `lisp_alpha_vantage.py`.) The dividends a stock has paid, from Alpha
Vantage (https://www.alphavantage.co), a market-data site with a free tier.
Schwab's API gives only a stock's latest dividend, not its history.

It needs a free API key (https://www.alphavantage.co/support/#api-key), as
the `"alpha_vantage_api_key"` entry of the credentials file. A free key is
limited to 25 requests a day, and to one a second, so each download is
kept for 12 hours, as the other data functions' are (`(http-clear-cache)`
deletes them). An answer that says a limit has been passed is not kept.

#### `(alpha-vantage-dividends creds symbol)`
A stock's or ETF's dividends: a table with a row for each, oldest first,
of its `ex-date` (the first day its shares trade without the dividend),
`declaration-date`, `record-date`, `payment-date`, and `amount` per share.
A date Alpha Vantage doesn't have, as for the oldest dividends, is `'()`.
A share class is written `"BRK-B"` or, as Schwab writes it, `"BRK/B"`. A
stock that has paid no dividends (or one Alpha Vantage doesn't know) has a
table with no rows.

```lisp
(define dividends (alpha-vantage-dividends creds "SPY"))
(display-table (table-tail dividends 3))
; ex-date     declaration-date  record-date  payment-date    amount
; ----------  ----------------  -----------  ------------  --------
; 2026-03-20  2026-01-02        2026-03-20   2026-04-30    1.796999
; 2026-06-18  2026-01-02        2026-06-18   2026-07-31    1.903516
; 2026-09-18  2026-01-02        2026-09-18   2026-10-30    1.888834
```

`daily-returns` takes this table as its `:dividends`: see Part 4 of [lisp_paths_manual.md](lisp_paths_manual.md).

## Reporting
### Google Sheets

(In `lisp_google.py`.) Tables, sent out to a new spreadsheet in your own
Google Drive: one tab for each table, with each column's numbers laid out
the way `display-table` lays them out. It's the way to hand a result to
someone who works in a spreadsheet, or to look at many tables at once --
all of `stratify-all`'s, say.

```lisp
(define strata (stratify-all loans '(("fico" (equal-count 5)) ("state" each)) '(("rate" weighted-mean)) :weight "balance"))
(apply google-sheet creds "Loan strata"
       '(("count" ",d") ("percent" ".1%") ("total_balance" ",.0f") ("rate" ".3f"))
       strata)
; => "https://docs.google.com/spreadsheets/d/.../edit"
```

**Setting it up** takes about ten minutes, once. Google asks every program
that uses a Google account to be registered:

1. In the Google Cloud console (https://console.cloud.google.com), make a
   project -- "morris-lisp", say -- and, under "APIs & Services", turn on
   the **Google Sheets API**.
2. Set up the project's **OAuth consent screen** (now called "Google Auth
   Platform"): an app name, your email address, the audience "External",
   and yourself as a test user. For the data access ("scopes"), add
   `https://www.googleapis.com/auth/drive.file`. That's the one permission
   the program asks for: to see and change *the files it made itself*, and
   none of your others.
3. Under "Credentials", make an **OAuth client ID**, of the type "Desktop
   app". Google shows its client ID and client secret. (For a desktop app,
   the secret isn't one in the usual sense, but it stays in the credentials
   file with the others.)
4. Put them in the credentials file:

   ```
   "google_client_id": "....apps.googleusercontent.com",
   "google_client_secret": "..."
   ```

5. A project whose consent screen is in "Testing" signs you out after a
   week. To stay signed in, publish the app ("In production") on the same
   screen: `drive.file` isn't one of the scopes Google calls "sensitive", so
   an app that asks only for it, and that only you use, shouldn't need
   Google's review.

The wording of Google's console changes from time to time; those are the
four things it asks for.

**Signing in.** `(google-login creds)` opens Google's sign-in page in your
browser, where you sign in as you would to Gmail and approve the program.
(Google may say it hasn't verified the app; it's yours, so continue.)
Google then sends the browser back to a port on your own computer, which
the program is listening at, with a code in the address; it trades the
code for the tokens, and the browser shows a page saying you can close it.
Your password never reaches the program. The tokens are kept in
`google_tokens.json`, next to the credentials file, readable only by you;
the access token lasts an hour and is renewed as needed. It works from
the console, a notebook, or the GUI. If you aren't signed in,
`google-sheet` says so. (Schwab's sign-in shows its page in a small
window of its own; Google doesn't allow that, which is why this one uses
your browser.)

#### `(google-login creds)`
Sign in, as above. Returns `#t`.

#### `(google-sheet creds title formats table ... [:names names])`
Makes a new spreadsheet called `title`, in the Drive of whoever signed in,
with a tab for each `table`, and returns its address, as a string. Nothing
is shared with anyone: the spreadsheet is yours, to share from Google.

`formats` is a list, in the form `display-table` takes -- `'(("balance"
",.2f") ("rate" ".3%"))` -- for the columns' number formats, or `'()` for
none. A column that isn't in the list is written as it is. A column whose
format is `hide`, or that is *just* `(column-name)`, is left out. So a
list can say which columns to leave out, with no format for the rest:

```lisp
(google-sheet creds "Strata" '(("percent" ".1%") ("total_balance")) strata)
```

writes every column of every table but `total_balance`, with `percent`
as a percentage. A format for a column a table doesn't have isn't used,
so one list can serve all the tables, as for `display-table`.

Each tab has a bold heading row, which stays at the top as you scroll,
and a row for each row of the table, with the columns as wide as their
contents. A tab is named for its table's first column -- for a
`stratify-all` table, the column it was stratified by -- with a number
added to the second of two tabs with the same name (`state`, `state 2`).
`:names` gives them instead, a list of strings, one for each table:

```lisp
(google-sheet creds "Strata" '() by-fico by-state :names '("By FICO" "By state"))
```

What is written:

- **Numbers are numbers**, not text, so the sheet can add them up. A
  missing number (NaN) is an empty cell.
- **Dates are dates**, shown as `2025-06-30`, whatever the format says.
- **Text is text** -- never a formula: a name that begins with `=` or `+`
  stays as typed.
- The formats are display-table's, as a spreadsheet writes them. The ones
  that can be: `f` (decimals: `".2f"` is `0.00`), `d` (a whole number),
  `%` (a percentage: `".1%"` is `0.0%`, as for `format`), and `e` (powers
  of 10), each with `,` for commas (`",.2f"` is `#,##0.00`), `+` to always
  show the sign, and `.N` for the number of decimals; and `,` alone, which
  is a whole number with commas. A spec that only lays out text -- `">12"`,
  `"<20"` -- is ignored, since a sheet has its own column widths. One a
  spreadsheet has no equivalent of -- `g`, `x`, `b` -- is an error, naming
  the column. A number format is for a column of numbers; a text column
  with one is an error too, as it is in `display-table`.
- The values are the table's, to the digits they are stored in: a number
  that `display-table` rounds to show is not rounded in the sheet. The
  format only changes how the sheet shows it.

Everything is checked before the sign-in is used, so a mistake -- a bad
format, a table that isn't one -- sends nothing to Google. If a request
fails part way, the error says where the spreadsheet is, and that it isn't
finished. A spreadsheet holds at most 10,000,000 cells in all; a long table
is sent in pieces. Google limits how fast a program can make spreadsheets
-- about 60 changes a minute -- which a few tables don't come near.

### Reports with control breaks

(In `lib/report.lsp`, with `lib/template.lsp`.) A table, possibly a large one, written as a text report: the rows are in
**groups**, one inside another (by state, then by zip code within the state; or by client), and each group has a header
before its rows and a footer after them, with the group's totals. The report has a header and a footer of its own, with the
grand totals, and, if you ask for pages, each page has a header and a footer, with its page number and its own totals. What
each of these says, and what each row says, is a **template** with `{{name}}` where a value goes; and which columns the
groups are of is in the same **spec**, one value that holds it all. Pages can say "page X of Y", carry running totals, and
repeat a group's header when it goes over a page; and the report can be written as a web page, to go through a page at a time.
A report of mortgages, with subtotals for each zip code,
for each state, and a grand total:

```lisp
(load "report.lsp")
(define loans (make-table
  "loan-id" (vector "L1" "L2" "L3" "L4" "L5")
  "state"   (vector "NY" "CA" "CA" "CA" "NY")
  "zip"     (vector "10001" "90001" "90002" "90001" "10001")
  "balance" (vector 100.0 200.0 300.0 400.0 500.0)))

(define spec
  (make-report-spec
    :report-header "Mortgages ({{loans}} loans)"
    :detail "{{loan-id:<4}} {{zip:<6}} {{balance:>8,.2f}}"
    :summaries (list (list "loans" 'count) (list "total" 'sum "balance"))
    :breaks (list (make-report-break :field "state" :header "State {{state}}"
                                     :footer "  {{state}} total: {{loans}} loans {{total:>9,.2f}}")
                  (make-report-break :field "zip" :footer "    {{zip}}: {{total:>9,.2f}}"))
    :report-footer "All: {{loans}} loans {{total:>9,.2f}}"))

(display (report-text loans spec))       ; the report as a string: write-report writes it to a file
```
prints:
```
Mortgages (5 loans)
State CA
L2   90001    200.00
L4   90001    400.00
    90001:    600.00
L3   90002    300.00
    90002:    300.00
  CA total: 3 loans    900.00
State NY
L1   10001    100.00
L5   10001    500.00
    10001:    600.00
  NY total: 2 loans    600.00
All: 5 loans  1,500.00
```

The rows were not in order: the table is sorted by the break columns first (`"state"`, then `"zip"`), and not changed.
The groups' `:footer`s come out innermost first, and a group's `:header` outermost first. A letter to each client, with a list
of the client's transactions and a total, on a page of its own with its own page numbers, is the same with one break, on
`"client"`, that says `:new-page #t` and `:restart-page-numbers #t`: see `examples/report_example.lsp`, which makes this
report and the mortgage report below it, on pages, from made-up tables.

#### `(write-report table path spec)`, `(report-text table spec)`
`write-report` writes the report of `table`, as `spec` says, to the text file at `path`, replacing what was there, and gives
back the number of pages (1, if the spec has no `:page-lines`). It writes a thousand lines at a time, so a table of any size
is written without the report being held: a table of 50,000 rows takes about five seconds, and its pages are in the file.
`write-report-html`, below, writes it as a web page. `report-text` gives the report as one string, which is for a short one (to look at, or to test a spec on the first rows of a
table: `(table-head loans 20)`). Neither changes `table`. They stop, before anything is written, if a template says a name that
isn't there, or the spec says a column that isn't in the table.

#### `(make-report-spec :slot value ...)`
The spec of a report: a value whose slots are the templates and the choices of the report. Every slot is optional; a template
that is `'()` (the default) writes nothing, and one that is `""` writes a blank line. A template is a string, which is what
`template-render` takes (see `template.lsp`: `{{name}}`; `{{name:spec}}`, laid out as `format` lays a value out, such as
`{{balance:>12,.2f}}`; `{{#each item in list}}`; `{{#if name}}`), and may be several lines (`\n`). The slots:

| Slot | What it is |
|---|---|
| `:detail` | the template of each row of the table |
| `:breaks` | a list of `make-report-break`s, the outermost group first |
| `:summaries` | what is added up for each group, the whole report, and each page: a list of `(name function column)`, with the functions of `table-group-by` (`count`, `sum`, `mean`, `min`, `max`, `weighted-mean`, `median`, ...; see "Tables", in the language manual), such as `("total" sum "balance")` and `("wac" weighted-mean "rate" "balance")`. Each is a name in the templates: `{{total}}` |
| `:running` | running totals: a list of `(name sum column [scope])` and `(name count [scope])`, such as `("so-far" sum "balance")`: what has been added up to a point in the report, from the start of the report, or, if the scope is a break's column (`"state"`) from the start of the group of that break, or, if it is `page`, from the start of the page. Each is a name in the templates: `{{so-far}}`; see "Running totals", below |
| `:report-header`, `:report-footer` | the templates at the start and at the end of the report; they have the totals of the whole report |
| `:page-header`, `:page-footer` | the templates at the top and at the bottom of each page |
| `:page-lines` | how many lines a page is, header and footer included; `'()` (the default) for no pages: the page header is then at the top of the report, and the page footer at the bottom |
| `:page-separator` | a string written after each page: `"\f"`, a form feed, for a printer; `""` (the default), none |
| `:detail-order` | a list of columns to sort the rows of the innermost group by, after the break columns: `'("date")` |
| `:presorted` | `#t` if the table is already in the order of the break columns (and `:detail-order`), and need not be sorted: for a large table that is, or that you sorted yourself |
| `:variables` | a list of `(name value)`, such as `(list (list 'title "Mortgages") (list 'month "March"))`, for any template to use |
| `:markdown` | `#t` to write the rows as Markdown tables instead of with a `:detail` template; see "A report in Markdown", below |
| `:formats` | with `:markdown`, how the table's columns are laid out, as `display-table` takes them: `'(("balance" ",.2f") ("rate" ".3%") ("zip" hide))` |

#### `(make-report-break :field column [:header template] [:footer template] [:new-page #t] [:restart-page-numbers #t] [:repeat-header #t])`
One level of grouping: the rows with the same value of the column `:field` (a string, the name of a column of the table) are a
group, within the group of the break before it. `:header` is written before a group's first row and `:footer` after its last.
`:new-page #t` starts each of its groups on a new page (a letter to each client), and `:restart-page-numbers #t` too makes
the first page of each group page 1. `:repeat-header #t` writes the group's header again at the top of each page that the
group goes over onto, with `{{continued}}` true in it (and false when the header is first written), so a header can say
`State {{state}}{{#if continued}} (continued){{/if}}`. A group ends when the value of its column, or of a column of a break before it,
changes in the sorted table. A break column may not have missing values (it is an error: which group would
they be in?), and a table `:presorted` that is not in the order of its break columns is an error too.

#### What a template can use
A template may say only the names it has, and one that says another is an error, naming it and listing what it could have said:

| Template | Its names |
|---|---|
| `:detail` | the columns of the table; `row-number` (the row's place in the report, from 1); `page` and `pages`; the running totals; the variables |
| a break's `:header` and `:footer` | the columns of this break and of those before it (the group's values: `{{state}}`); the summaries, **of the group** (in a header, too: they are worked out before the report is written); `page` and `pages`; the running totals; the variables; and, in a header only, `continued` |
| `:report-header`, `:report-footer` | the summaries of the whole report; `page` and `pages`; the running totals; the variables |
| `:page-header` | the columns of every break, as of the first row on the page (the page's group); `page` and `pages`; the running totals; the variables |
| `:page-footer` | the same, as of the last row, and the summaries **of the rows on the page** |

Give the columns, the summaries and the variables different names: a template that says a name that is two of them
gets one, and which is not something to depend on.

#### Page X of Y
`{{page}}` is the number of the page, and `{{pages}}` the number of pages: `Page {{page}} of {{pages}}`. Any template may say
either. A group that says `:restart-page-numbers` starts a new run of page numbers, and `{{pages}}` is the number of pages in
the run: each letter of a report of letters can say "page 2 of 2", though the report has more pages. A report that says
`{{pages}}` is laid out twice, the first time to count the pages and write nothing: it takes twice as long.

#### Running totals
A running total is what has been added up to a point in the report. The `:running` slot lists them, each with a name:
`("so-far" sum "balance")` adds the column up from the first row of the report, `("in-state" sum "balance" "state")` from the
first row of each state, `("on-page" sum "balance" page)` from the first row of each page, and `("n" count "state")` counts the
rows. A **row** says the total through itself, so a detail of `{{balance}} {{in-state}}` shows a statement's running
balance. Everywhere else it is the total at that point, before what comes after: a **group header** says the total before the
group (0, if the total is of that group's break, or one inside it), a **group footer** through its last row, a **page header**
what was brought forward from the pages before (and 0, if the total is of the page), a **page footer** what is carried forward,
and the **report footer** the total of all. A missing value adds nothing to a sum.

#### How the pages are laid out
A page has a header and a footer, and a row, a group header or a group footer goes where it fits: if the page does not have
room for it and the page footer, the page ends, and the next page begins with its header. A group's header goes with its
first row: the page ends before both. A page footer is at the bottom of the page: when what is on a page is shorter than the page (at the end of the
report, before a group that starts a new page, or when the next thing is taller than what is left), blank lines are
written before the footer. A template taller than a page goes on a page of its own. The footer of a page that ends in the middle of a group is that page's, with
its totals (`{{total}}` in a page footer is the page's). A break that says `:repeat-header` has its header written again at the
top of the next page, after the page header, if its group goes on there: when the page begins with a row of it, or with the
footer of a group inside it. A page that begins with the group's own footer, or with a new group, does not repeat it.

The first page starts when the report does, with the page header, then the report header; the page of a break that says
`:new-page` starts before its group, except at the start of a page that has nothing yet but its header.

#### `(write-report-html table path spec [:title "Report"])`
Writes the report as a web page, to the file at `path`, replacing what was there, and gives back the number of pages. The
page shows one page of the report at a time, in a fixed-width font, with a bar at the bottom: **First**, **Previous**, the
number of the page, to type a page's number in, **of** the number of pages, **Next** and **Last**. The arrow keys, Page Up
and Page Down, Home and End work too, and the address of the page says which page (`report.html#p3`), so a link or a bookmark
goes to it. The pages are those of the text report, line for line, with `{{page}}`, `{{pages}}`, the running totals and the
repeated headers: the spec's `:page-lines` says how long a page is (50, if it has none), and `:page-separator` is not
written. The page is one file, with nothing to load, and fits a phone, a dark mode and, printed, every page in turn; where
the browser cannot run its script, it shows all the pages, one after another. The text is made safe for the web: `&`, `<`
and `>` in the data are shown as themselves. It is written ten pages at a time, as `write-report` writes a thousand lines.
`:title` is the title of the web page. `examples/report_example.lsp` writes the mortgage report both ways.

```lisp
(write-report-html mortgages "mortgages.html" spec :title "Mortgages, October")
```

#### A report in Markdown
With `:markdown #t` the rows are not written by a `:detail` template but as **Markdown tables**, laid out as `display-table`
lays out a table: a heading for each column of the table, numbers right-aligned and text left-aligned, a blank cell for a
missing value, and the characters that Markdown would read as something else (`|`, `*`, `_`, `$`, ...) shown as themselves.
`:formats` says how the columns are laid out, as `display-table` takes them, and a column whose format is `hide` (or just
`("state")`) is left out: the break columns, usually, since a group's header says them.

Each run of rows is a table: the rows of a group between its header and its footer. Where nothing is written between one group
and the next, they are one table. A blank line is written before and after each table, as Markdown needs. The headers and
footers are templates as before, and are Markdown as you write them (`"## State {{state}}"`; `"**{{state}}**: {{loans}} loans"`);
the values in them are written as they are. The summaries and the running totals are in them, but not in the tables.

A Markdown report has no pages: `:page-lines`, `:page-header` and `:page-footer` are errors. A break's `:new-page #t` writes
the `:page-separator` (`"---"`, a horizontal rule) between its groups. The report is a file for `write-report` (`.md`), or the string
`report-text` gives, which a notebook shows with `(display-markdown ...)`. `write-report-html` does not take one. A group is
formatted whole when it ends, so it has to fit in memory.

```lisp
(define markdown-spec
  (make-report-spec
    :markdown #t
    :formats '(("state" hide) ("balance" ",.2f") ("rate" ".3%"))
    :summaries (list (list "loans" 'count) (list "total" 'sum "balance"))
    :breaks (list (make-report-break :field "state" :header "## State {{state}}"
                                     :footer "{{loans}} loans, {{total:,.2f}}\n"))))
(write-report mortgages "mortgages.md" markdown-spec)
```

#### What it comes to
Each row is rendered once, at about a tenth of a millisecond when its template is only text and `{{name}}`s (which are
compiled, before the rows are written); a template with `{{#each}}` or `{{#if}}` takes several times as long. The group
totals are worked out first, by `table-group-by` on the whole table (a pass for each level of break), so a group's
header can say them. Sorting is `table-sort`. A report that says `{{pages}}` takes twice as long, and running totals add
a little to each row.

## Dates and cash flows

For dates themselves, and the clock, see "Dates" and "The clock", in the
[language manual](lisp_interpreter_reference.md#dates).

### Monthly time series

(In `lisp_time_series.py`.) Mortgages work by the month, so the month is
the basic unit of time here.

**Month numbers.** A month is represented by a **month number**, the
integer `year × 12 + (month − 1)`: January 2020 is `24240`, February 2020
is `24241`, and January 2021 is `24252`. Because month numbers are plain
integers, month arithmetic is ordinary arithmetic — three months later is
`(+ m 3)`, a loan's age in months is `(- m first-payment-month)`, and
`vector-lag` by 1 is the previous month — and joining tables on them is
fast. The functions below convert dates, and the `YYYYMM` values loan-level
data uses for reporting periods (e.g. `202301`), to and from month
numbers. Each takes a single value or a whole vector.

**Series.** A time series is a table with a column of dates and columns of
numbers, as `fred-table`, `schwab-price-history`, and `bls-series` make. Its
dates are its column named `date`, or, if it has none, its one column of
dates. Its values are its other columns of numbers (but a `month`
column).

#### `(date->month-number d)`, `(month-number->date m)`
A date's month number (the day of the month is ignored), and the first day
of a month number's month.

```lisp
(date->month-number (date 2020 1 15))        ; => 24240
(month-number->date 24241)                   ; => 2020-02-01
(date->month-number (vector (date 2020 1 1) (date 2020 3 9)))   ; => #(24240 24242)
```

#### `(yyyymm->month-number n)`, `(month-number->yyyymm m)`
Convert between `YYYYMM` values, as loan-level data records reporting
periods, and month numbers. A month outside 01–12 is an error.

```lisp
(yyyymm->month-number 202301)                ; => 24276
(yyyymm->month-number #(202212 202301))      ; => #(24275 24276)
(month-number->yyyymm 24276)                 ; => 202301
```

#### `(date-add-months d n)`
The date `n` months after `d` (before, if `n` is negative), for one date or
a vector of dates. A day past the end of the new month becomes its last
day.

```lisp
(date-add-months (date 2020 1 31) 1)         ; => 2020-02-29
(date-add-months (date 2020 3 15) -3)        ; => 2019-12-15
```

#### `(months-between d1 d2)`
How many calendar months from `d1` to `d2` (the day of the month is
ignored). Either may be a vector.

```lisp
(months-between (date 2020 1 31) (date 2021 3 1))   ; => 14
```

#### `(month-range first last)`
A vector of every month number from `first` to `last`, inclusive; `first`
and `last` may be dates or month numbers.

```lisp
(month-range (date 2020 11 1) (date 2021 2 1))      ; => #(24250 24251 24252 24253)
```

#### `(series-monthly table [:how h])`
A daily or weekly series made monthly: a table of `month` (month numbers),
`date` (the first of the month), and each of the table's columns of
numbers, with a row for each month that has data. `:how` chooses which of
a month's values: `'mean` (the default), `'last`, `'first`, `'sum`,
`'min`, or `'max`. Missing values are left out. With `:how 'last`, a table
of daily prices becomes one of month-end prices.

```lisp
(define weekly (make-table "date" (vector (date 2023 1 5) (date 2023 1 12) (date 2023 2 2))
                           "rate" #(6.5 6.25 6.0)))
(table-column (series-monthly weekly) "rate")              ; => #(6.375 6.0)
(table-column (series-monthly weekly :how 'last) "rate")   ; => #(6.25 6.0)
(table-column (series-monthly weekly) "date")              ; => #(2023-01-01 2023-02-01)
```

#### `(series-values-at table months [:column name] [:fill-forward #t])`
A column of a series in each of the given months (a vector of month
numbers, or of dates). `:column` says which, if the table has more than
one column of numbers. Several values in one month are averaged. A month
with no data gives `nan`, or, with `:fill-forward #t`, the latest earlier
month's value. This is the simplest way to attach a market series to every
loan-month row:

```lisp
(define weekly (make-table "date" (vector (date 2023 1 5) (date 2023 1 12) (date 2023 3 2))
                           "rate" #(6.5 6.25 6.0)))
(define months (month-range (date 2023 1 1) (date 2023 4 1)))
(series-values-at weekly months)                   ; => #(6.375 nan 6.0 nan)
(series-values-at weekly months :fill-forward #t)  ; => #(6.375 6.375 6.0 6.0)
```

#### `(series-table tables [:fill-forward #t])`
Several series, a list of tables, lined up by month in one table: `month`
(month numbers), `date` (the first of each month), and every column of
numbers of the tables, under its own name (two tables can't have a column
of the same name: `table-rename-column` one of them). The months run from
the earliest month any of them has data to the latest, every month
included. Several values in one month are averaged; a month with no data
is `nan`, or, with `:fill-forward #t`, that column's latest earlier value.

```lisp
(define mortgage (make-table "date" (vector (date 2023 1 5) (date 2023 1 12) (date 2023 3 2))
                             "mortgage" #(6.5 6.25 6.0)))
(define cpi (make-table "date" (vector (date 2023 1 1) (date 2023 2 1)) "cpi" #(300.5 301.1)))
(series-table (list mortgage cpi))   ; => (("month" . #(24276 24277 24278)) ("date" . #(2023-01-01 2023-02-01 2023-03-01)) ("mortgage" . #(6.375 nan 6.0)) ("cpi" . #(300.5 301.1 nan)))
```

**Putting it together** — attach the 30-year mortgage rate and the
10-year Treasury yield, month by month, to loan-level rows (this needs a
FRED API key):

```lisp
(define market (series-table (list (fred-table creds '("MORTGAGE30US" "DGS10"))) :fill-forward #t))
(define loans (sqlite-query conn "SELECT loan_id, monthly_reporting_period, current_interest_rate FROM loan_performance"))
(define loans (table-add-column loans "month"
                (yyyymm->month-number (table-column loans "monthly_reporting_period"))))
(define loans (table-join loans market "month" 'left))
(define loans (table-add-column loans "incentive"
                (vector-sub (table-column loans "current_interest_rate")
                            (table-column loans "MORTGAGE30US"))))
```

### Trading days (the NYSE's calendar)

(In `lisp_calendar.py`.) Which days the stock market is open, and counting
them. A **trading day** is a Monday through Friday that isn't a holiday of
the New York Stock Exchange. The NYSE publishes its holidays for the next
few years (https://www.nyse.com/trade/hours-calendars), but they follow
rules, so these functions work them out for any year:

- New Year's Day (January 1), Juneteenth (June 19, a holiday since 2022),
  Independence Day (July 4), and Christmas (December 25). One that falls on
  a Saturday is kept on the Friday before, and one on a Sunday on the
  Monday after. The exception is New Year's Day on a Saturday, which isn't
  kept at all: the market is open the Friday before.
- Martin Luther King Jr. Day (since 1998), the third Monday of January;
  Washington's Birthday, the third Monday of February; Memorial Day, the
  last Monday of May; Labor Day, the first Monday of September; and
  Thanksgiving, the fourth Thursday of November.
- Good Friday, the Friday before Easter.

A day the market closes early, such as the day after Thanksgiving, is a
trading day. Closings that weren't planned, for a funeral, a storm, or
September 11, 2001, are not known.

#### `(trading-day? date)`
`#t` if the market is open that day.

```lisp
(trading-day? (date 2026 10 7))      ; => #t
(trading-day? (date 2026 10 10))     ; => #f
(trading-day? (date 2026 11 26))     ; => #f
```

#### `(next-trading-day date)`
The date, if the market is open that day, and if not the first day after
it that it is.

```lisp
(next-trading-day (date 2026 11 14))     ; => 2026-11-16
(next-trading-day (date 2026 11 26))     ; => 2026-11-27
```

#### `(add-trading-days date n)`
The date `n` trading days after `date` (before it, if `n` is negative).
With `n` of 0, it is the date itself, a trading day or not.

```lisp
(add-trading-days (date 2026 11 20) 1)     ; => 2026-11-23
(add-trading-days (date 2026 11 20) 4)     ; => 2026-11-27
(add-trading-days (date 2026 11 30) -2)    ; => 2026-11-25
```

#### `(trading-days-between start end)`
How many trading days there are after `start`, up to and including `end`:
1 from a Friday to the Monday after it. Negative if `end` is before
`start`. Either can be a vector of dates -- the expirations of an option
chain, say -- and the answer is then a vector, with the other date used for
each.

```lisp
(trading-days-between (date 2026 11 20) (date 2026 11 23))    ; => 1
(trading-days-between (date 2026 11 20) (date 2026 11 30))    ; => 5
(trading-days-between (date 2025 12 31) (date 2026 12 31))    ; => 251
(trading-days-between (date 2026 11 20) (vector (date 2026 11 23) (date 2026 11 30)))    ; => #(1 5)
```

#### `(market-open?)`
`#t` if the stock market is open now: from 9:30 am to 4:00 pm on a trading
day. The computer's clock is taken to be on New York time. The functions that
fetch quotes (`option-spreads`, `option-positions`, `option-methods`) use it to
say that the bids and asks are the last close's.

#### `(nyse-holidays year)`
A vector of the dates in a year when the market is closed on a weekday.
For 2026 through 2028 they are the ones the NYSE publishes.

```lisp
(nyse-holidays 2028)
; => #(2028-01-17 2028-02-21 2028-04-14 2028-05-29 2028-06-19 2028-07-04 2028-09-04 2028-11-23 2028-12-25)
```

### Day counts and cash flows

(In `lisp_finance.py`.) How long a period is under a day count basis, and
the standard measures of a stream of cash flows: net present value,
internal rate of return, yield, duration, and convexity, and the level
payment on a loan. The math is done in double precision, however the cash
flows are stored.

**Day count bases.** A basis is written as a string or a symbol, in upper
or lower case — `"30/360"`, `'act/360`, ...:

| Basis | Days | Year | Used for |
|---|---|---|---|
| `30/360` | every month counts as 30 days: a 31st counts as the 30th, and so does the second date's 31st when the first date is the 30th or 31st | 360 | US corporate bonds, mortgages, agency MBS |
| `30E/360` | the same, except that any 31st counts as the 30th | 360 | Eurobonds |
| `ACT/360` | actual | 360 | money markets, SOFR |
| `ACT/365` | actual | 365 | sterling; Excel's `XNPV` and `XIRR` |
| `ACT/ACT` | actual | the actual length of each calendar year the period touches, 365 or 366 | ISDA swaps; Treasuries are close to it |

**Cash flows** are a list or a vector of amounts, one per period, the
periods equally spaced (`xnpv` and `xirr` take a date for each amount
instead). `npv` and `irr` count the first amount as now; `present-value`,
`yield`, `duration`, and `convexity` count the first as one period from
now, as a bond's cash flows are. A **rate** is per period; a **yield** is
per year, compounded `periods-per-year` times a year.

#### `(day-count d1 d2 basis)`
The number of days from `d1` to `d2` under `basis`. Either date may be a
vector of dates.

```lisp
(day-count (date 2024 1 31) (date 2024 3 1) "30/360")    ; => 31
(day-count (date 2024 1 31) (date 2024 3 1) "ACT/360")   ; => 30
(day-count (date 2024 1 29) (date 2024 3 31) "30/360")   ; => 62
(day-count (date 2024 1 29) (date 2024 3 31) "30E/360")  ; => 61
```

#### `(year-fraction d1 d2 basis)`
The fraction of a year from `d1` to `d2` under `basis`: the fraction of a
year's interest that accrues between them. Either date may be a vector of
dates.

```lisp
(year-fraction (date 2024 1 15) (date 2024 7 15) "30/360")    ; => 0.5
(year-fraction (date 2024 1 15) (date 2024 7 15) "ACT/360")   ; => 0.5055555555555555
(year-fraction (date 2024 1 15) (date 2024 7 15) "ACT/365")   ; => 0.4986301369863014
(year-fraction (date 2023 7 1) (date 2024 7 1) "ACT/ACT")     ; => 1.0013773486039375
(* 1000000 0.05 (year-fraction (date 2024 1 15) (date 2024 7 15) 'act/360))   ; => 25277.777777777777
```

The last line is the interest on $1,000,000 at 5% for that half year,
ACT/360.

#### `(npv rate cashflows)`
The net present value, at `rate` per period, of cash flows one period
apart, the first of them now (so it isn't discounted). Excel's `NPV`
counts the first cash flow as one period away instead.

```lisp
(npv 0.1 (list -100 60 60))    ; => 4.132231404958667
```

#### `(irr cashflows [low high])`
The internal rate of return: the rate per period at which the `npv` of
the cash flows is 0. It's found by bisection: first two rates between
which the npv changes sign — trying -99%, every 1% from -95% to 100%, and
a few higher rates, and taking the pair nearest 0 — then halving that
interval until the rate is known to 12 decimal places. Cash flows that
change sign more than once can have more than one IRR; give `low` and
`high` to look for one between them. An error if there's none.

The answers are exact to about 12 decimal places, which is why 10% prints
as 0.10000000000029105.

```lisp
(irr (list -100 60 60))                    ; => 0.13066238629195137
(irr (list -100 230 -132))                 ; => 0.10000000000029105
(irr (list -100 230 -132) 0.15 0.5)        ; => 0.20000000000022736
```

#### `(xnpv rate dates cashflows [basis])`, `(xirr dates cashflows [basis])`
`npv` and `irr` for cash flows on the given dates, which needn't be evenly
spaced. `rate` is per year; each cash flow is discounted to the first date
by its `year-fraction` from it, under `basis` — `ACT/365` unless given,
as in Excel's `XNPV` and `XIRR`.

```lisp
(define dates (list (date 2008 1 1) (date 2008 3 1) (date 2008 10 30)
                    (date 2009 2 15) (date 2009 4 1)))
(define amounts (list -10000 2750 4250 3250 2750))
(xnpv 0.09 dates amounts)      ; => 2086.647602031535
(xirr dates amounts)           ; => 0.3733625335191027
```

#### `(payment rate periods principal)`
The level payment each period that pays off `principal`, with interest
at `rate` per period, in `periods` payments — for a mortgage, the monthly
payment, with `rate` the annual rate divided by 12, and `periods` the
number of months. At a rate of 0 it's `principal / periods`.

```lisp
(payment (/ 0.065 12) 360 300000)          ; => 1896.2040704788958
(* 12 (irr (cons -300000 (loop repeat 360 collect (payment (/ 0.065 12) 360 300000)))))
                                           ; => 0.06499999999883582
```

The second line checks the first: the loan's cash flows, as the lender
sees them, have an IRR of 6.5% a year.

#### `(bond-cashflows coupon-rate years periods-per-year [face])`
A bond's cash flows from now to maturity, as a vector: a coupon of
`face * coupon-rate / periods-per-year` each period, and the face value
with the last coupon. `face` is 100 unless given, so prices come out per
100 of face value. `years * periods-per-year` must be a whole number.

```lisp
(bond-cashflows 0.06 5 2)      ; => #(3.0 3.0 3.0 3.0 3.0 3.0 3.0 3.0 3.0 103.0)
```

#### `(present-value yield periods-per-year cashflows)`
What cash flows one period apart, the first one period from now, are
worth at an annual `yield`, compounded `periods-per-year` times a year:
for a bond, its price.

```lisp
(define flows (bond-cashflows 0.06 5 2))
(present-value 0.05 2 flows)   ; => 104.37603196548555
```

#### `(yield price periods-per-year cashflows)`
The annual yield, compounded `periods-per-year` times a year, at which
the cash flows' `present-value` is `price` — found as `irr` finds a rate.

```lisp
(define flows (bond-cashflows 0.06 5 2))
(yield 104.376 2 flows)        ; => 0.050000071207177824
```

#### `(duration yield periods-per-year cashflows)`, `(modified-duration yield periods-per-year cashflows)`, `(convexity yield periods-per-year cashflows)`
`duration` is the Macaulay duration, in years: the average time until the
cash flows arrive, each weighted by its present value. `modified-duration`
is that divided by `1 + yield / periods-per-year`: how much the price
changes, as a fraction of itself, for a change of 1 (that is, 100%) in the
yield — so a rise of 0.0001 (1bp) lowers the price by about
`modified-duration / 10000` of itself. `convexity`, in years squared, is
how much the duration itself changes with the yield. Together, a change
`dy` in the yield changes the price by about
`price * (- (* modified-duration dy)) + price * convexity * dy * dy / 2`.

```lisp
(define flows (bond-cashflows 0.06 5 2))
(duration 0.05 2 flows)            ; => 4.4084075904925575
(modified-duration 0.05 2 flows)   ; => 4.300885454139081
(convexity 0.05 2 flows)           ; => 22.079043263522394
```

## Statistical models

For the statistics of a vector -- mean, standard deviation, quantiles,
correlation -- see "Vector math and statistics", in the
[language manual](lisp_interpreter_reference.md#vector-math-and-statistics).

### Yield curves and paths of rates

The Treasury's, the Fed's and SOFR futures' yield curves, and paths of interest rates made from them with
a two-factor model fitted to option prices, are in their own manual, [lisp_paths_manual.md](lisp_paths_manual.md):
what you do to make paths, from the very beginning, what the program does, and every function. The
functions: `treasury-par-curve`, `latest-treasury-points`, `par-curve-zeros`, `treasury-zero-curve`,
`curve-forward-rates`, `forward-rates-table`, `curve-discount-factors`, `bond-cash-flows`,
`bond-accrued-interest`, `bond-flows-by-month`, `gsw-curve`, `gsw-parameters`, `svensson-zero-rates`,
`svensson-forward-rates`, `gsw-zero-curve`, `sofr-forward-curve`, `extend-forward-curve`;
`simulate-rate-paths`, `simulate-mortgage-rate-paths`, `simulate-rate-factors`, `rate-curve-on-date`,
`curve-par-yield`, `path-present-values`, `price-callable-bond`; `calibrate-rate-model`,
`calibrate-to-note-options`, `note-option-comparison`, `note-option-rows`, `sofr-calibration-data`.

### Regression models

Eight kinds, one function each:

| | A straight line (or plane) | A line that bends at knots |
|---|---|---|
| Least squares | `linear-regression` | `spline-regression` |
| Least absolute deviation | `lad-regression` | `spline-lad` |
| A quantile (the 90th percentile, say) | `quantile-regression` | `spline-quantile` |
| Logistic | `logistic-regression` | `spline-logistic` |

`linear-regression`/`lad-regression`/`logistic-regression` fit a flat model
of the form `y = intercept + sum(coefficients[i] * x[i])` (linear, by least
squares or by least absolute deviation) or `p = sigmoid(intercept +
sum(coefficients[i] * x[i]))` (logistic), where
`coefficients` always has one entry per predictor, even when there's only
one. `spline-regression` fits a *spline* model: internally it expands each
predictor into an extra set of features (piecewise-linear "hinge"
functions, or category-indicator columns — see below), then fits an
ordinary regression on that expanded basis (`spline-lad` fits it by least
absolute deviation instead, and `spline-logistic` by logistic regression)
— so a spline model's
coefficients apply to the expanded basis, not the original predictors, and
`model-coefficients`/`model-intercept`/`model-slope` refuse to operate on
one (use `model-report`/`model-predict` instead, which work on every model
kind). `model-kind` reports which flavor you have: `"linear"`, `"lad"`,
`"quantile"`, `"logistic"`, `"spline"`, `"spline-lad"`, `"spline-quantile"`,
or `"spline-logistic"`.

All of the eight,
`model-predict`, and `model-evaluate` accept **either a single vector of X
values (one predictor) or a Lisp list of several vectors** — `(list x1 x2
...)` — for multiple predictors. Every predictor vector and the Y vector
must be the same length. Predictors are standardized internally before
fitting (for numerical stability) and converted back to the original scale
afterward, so this is transparent to you; date values anywhere a number is
expected are silently converted to their ordinal day count.

**Weighted fitting.** All eight take an optional `weights` vector, after
`x` and `y` (and after the quantile and `max-knots`, for the ones that take
them): one
non-negative number per observation, the same length as `y`. Omit it (or
pass `'()`) to weight every observation equally, exactly the original
behavior. Fitting still minimizes a sum of squared errors (or maximizes a
log-likelihood, for the logistic case) — weighting just means each
observation's contribution to that sum is multiplied by its own weight, so
a weight of `2` counts an observation as if it appeared twice, and a weight
of `0` excludes it entirely; only the weights' *relative* sizes matter, not
their absolute scale. This is the standard tool for fitting to **grouped**
data — e.g. one row per rate-incentive bucket rather than one row per loan
— where you want a bucket representing $500M of balance to influence the
fit far more than one representing $2M, and where a bucket's own average is
a more reliable (lower-variance) estimate the more balance stands behind
it:

```lisp
(define bucket-rate (vector 0.02 0.04 0.06 0.08))    ; one row per rate bucket
(define bucket-cpr   (vector 0.05 0.08 0.15 0.30))
(define bucket-balance (vector 450000000 12000000 8000000 300000000))
(define m (linear-regression bucket-rate bucket-cpr bucket-balance))
```

**Rows that come in groups.** Often the rows aren't each new information.
Twenty-four months of one loan are 24 rows, but one borrower, one house,
one set of habits: if the loan pays faster than the model says one month,
it probably does the next month too. The fit is still fine, but the
standard errors, which take every row to be new information, come out too
small -- the model looks surer than it is. All eight take `:groups`, after
the other arguments: a vector or list with a value for each row -- a
number, a string, or a date, such as the loan's ID -- and rows with the
same value are a group. The fit is the same, but the standard errors
allow for a group's rows being alike ("clustered" standard errors), by
taking each *group* to be new information, not each row. `model-report`
says how many groups there were.

```lisp
(random-seed 4)
(define loan (vector-map (lambda (i) (floor (/ i 24))) (vector-range 960)))    ; 40 loans, 24 months of each
(define (for-each-loan make)                                                  ; one value for each loan, on each of its rows
  (let ((value (list->vector (map (lambda (i) (make)) (iota 40)))))
    (vector-map (lambda (l) (vector-ref value l)) loan)))
(define coupon (for-each-loan (lambda () (+ 3 (* 4 (random-float))))))           ; 3% to 7%
(define habit (for-each-loan (lambda () (* 6 (- (random-float) 0.5)))))          ; how much faster or slower it pays
(define speed (+ (* 2 coupon) habit (vector-map (lambda (l) (* 4 (- (random-float) 0.5))) loan)))
(define (slope-error m) (format "{:.3f}" (vector-ref (table-column (model-coefficient-table m) "std_error") 1)))
(slope-error (linear-regression coupon speed))                  ; => "0.056"
(slope-error (linear-regression coupon speed :groups loan))     ; => "0.221"
```

The slope's standard error is four times as large: there are 40 loans'
worth of information about coupons, not 960 rows' worth. They're found by
the "sandwich" formula (`clustered_covariance` in `lisp_regression.py`
explains it), with the small-sample corrections Stata uses: `G / (G - 1)`,
`G` being the number of groups, and for least squares also `(n - 1) / (n -
p)`. The t values of the least-squares, LAD, and quantile kinds then have `G
- 1` degrees of freedom. The standard errors need a good many groups.
In simulations with 20 to 50 groups of 12 rows each, their 95% intervals
held the true coefficient 90% to 95% of the time, where the plain ones
held it only 60% to 76% of the time. With fewer groups they're less to be
trusted. With every row its own group -- `:groups (vector-range n)` --
they're the "robust" standard errors, which allow for the errors being
larger for some rows than others. `cross-validate` takes `:groups` too, to
keep each group's rows together.

#### `(linear-regression x y [weights] [:groups g])`
Ordinary (or weighted) least-squares fit of `y = intercept +
sum(coefficients[i] * x[i])`. `x` is a vector, a list of vectors for
multiple predictors, **or a list of `(name . vector)` pairs** — exactly
`sqlite-query`'s own column-wise result shape, so a query's results can be
fed straight in with no manual name-stripping; `y` is a vector, or
likewise a `(name . vector)` pair, the same length as each predictor
vector; `weights` is the optional per-observation weight vector described
above; `:groups`, for standard errors that allow for rows in the same group
being alike, is described above too. When `x`/`y` carry names this way, `model-report` (below) uses them
in place of the generic `x1`/`x2`/`y` placeholders. Returns a model of
kind `"linear"`. Raises an error if `x`/`y`/`weights` lengths mismatch, a
predictor has zero variance, the predictors are collinear, or a weight is
negative.

```lisp
; sqlite-query's result feeds straight in -- no (map cdr ...) needed:
(define rows (sqlite-query conn "select zero_flag, balance, loan_age from t"))
(define m (linear-regression (cdr rows) (car rows)))
(display (model-report m))   ; "Linear model:  zero_flag = ... + c*balance + c*loan_age"
```

**How the coefficients are found.** Fitting minimizes the (weighted) sum of
squared residuals —

```
sum over every observation i of:  weight[i] * (y[i] - prediction[i])^2
```

— the ordinary least-squares objective (with every `weight[i] = 1` unless
you pass your own, per "Weighted fitting" above). That objective is
*quadratic* in the coefficients, so its minimum has a closed-form solution:
setting its gradient to zero gives one linear equation per coefficient (the
"normal equations"), and the interpreter solves that linear system exactly,
in a single step, via Gauss-Jordan elimination with partial pivoting
(`solve_linear_system` in `lisp_regression.py`) — no searching, iterating,
or approximating, unlike `logistic-regression` below. (Predictors are
rescaled to mean 0 / unit variance first, purely to keep that linear system
numerically well-behaved regardless of a predictor's raw scale — a huge
ordinal date next to a small percentage, say — and the fitted coefficients
are converted back to the original scale afterward; this doesn't change
what's being minimized or the answer you get, only how reliably the solver
gets there.) Building the normal equations themselves is an O(n · p²)
reduction over every observation (`n` rows, `p` coefficients including the
intercept) — done with numpy matrix operations rather than a Python-level
loop, so a large `n` (e.g. a multi-million-row dataset pulled in via
`sqlite-query`) doesn't dominate fitting time; the actual `p`-by-`p` solve
afterward stays plain Python, since `p` (a handful of predictors) is never
the bottleneck.

```lisp
(define m (linear-regression prices demand))
(display (model-report m))
```

#### `(lad-regression x y [weights] [:groups g])`
A **least absolute deviation** fit of `y = intercept +
sum(coefficients[i] * x[i])`: the one that makes the sum of the absolute
residuals, `sum(weight[i] * |y[i] - prediction[i]|)`, smallest, rather than
the sum of their squares. It's a robust regression: a few outliers barely
move it. A point far from the others pulls a least-squares fit toward it
in proportion to the *square* of its distance, but a LAD fit only in
proportion to the distance itself. (With no predictors, LAD would give the
median of `y`, as least squares gives the mean.) It suits small data sets
where one or two points are wild -- a bad print, a data error, a month
with a one-off event -- and you'd rather they not decide the answer.
`x`, `y`, and `weights` are as for `linear-regression`; the model's kind is
`"lad"`, and `model-predict`, `model-report`, `model-evaluate`, and the rest
work on it as on any other.

```lisp
(define x #(1 2 3 4 5 6 7 8 9 10))
(define y #(3 5 7 9 11 13 15 17 19 100))       ; y = 2x + 1, but for the last one
(model-slope (linear-regression x y))           ; => 6.30909090909091
(model-slope (lad-regression x y))              ; => 2.0
(model-intercept (lad-regression x y))          ; => 1.0
(model-residuals (lad-regression x y) x y)      ; => #(0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 79.0)
```

`model-residuals` (below) shows which points the fit set aside: those with
the largest residuals.

**How it's found.** There's no formula for a LAD fit, as there is for
least squares, but one fact makes it easy to find: some best fit goes
exactly through `p` of the points, `p` being the number of coefficients
counting the intercept -- for a line, through two of them. So the fit
starts through the `p` points closest to the least-squares fit, and then,
over and over, holds the fit at `p - 1` of the points it goes through and
swings it -- for a line, rotates it about one point. How far to swing it
is a weighted median, which lands the fit on another of the points. When
no swing lowers the sum of absolute residuals, no fit does. This is
Wesolowsky's method (1981): each step is exact, the answer is the exact
LAD fit, and it usually takes only a few steps -- a hundred thousand
points take well under a second. (Another common method, iteratively
reweighted least squares, only approaches the answer, often over hundreds
of steps.)

**Standard errors** in `model-report` come from the usual large-sample
formula for LAD, which depends on how closely the errors crowd around 0.
That's estimated two ways -- as for normal errors, from the median
absolute residual, and from the residuals themselves, from how far apart
their quantiles just above and below the middle are -- and the larger is
used. Neither depends on the most extreme residuals, so moving an outlier
further out doesn't change the standard errors at all. In simulations with
as few as 8 points, and with normal, heavy-tailed, or contaminated errors,
the 95% intervals they give held the true coefficient 92% to 97% of the
time. With `p` points or fewer, the fit is exact and the standard errors
are `nan`.

For measures of fit, `model-report` gives the MAE, the average size of a
miss; a pseudo-R-squared, 1 − the MAE / the MAE of predicting the median of
`y` for every row (Koenker and Machado's R1, which, like R-squared, is 0
for a fit no better than that and 1 for a perfect one); the number of
steps; and `n`. Each measure is beside what a perfect model would get and
what predicting the median for every row would (see "How good is a
model?", below).

```lisp
(define month #(1 2 3 4 5 6 7 8 9 10 11 12))
(define cpr #(4.5 5 6.5 6 7.5 8.5 8 9.5 30 10.5 11 12.5))   ; month 9 had a one-off payoff
(display (model-report (lad-regression month cpr)))
```
prints:
```
Least absolute deviation model:  y = 3.78571 + 0.714286*x1
  term        coefficient     std error    t value    p value
  intercept       3.78571      0.612654      6.179   0.000104
  x1             0.714286     0.0832433      8.581   6.34e-06
  MAE              = 1.98214    (perfect: 0; predicting the median of y for every row: 3.70833)
  pseudo R-squared = 0.46549    (perfect: 1; predicting the median of y for every row: 0)
  iterations       = 2 (converged)
  n                = 12
```
Least squares, pulled up by month 9, gives a slope of 1.03 with a standard
error of 0.50.

#### `(quantile-regression x y quantile [weights] [:groups g])`
The fit with `quantile` of the points below it: `0.9` for the line that 90%
of the points are under, the 90th percentile of `y` at each `x`. Least
squares fits the average; quantile regression fits a percentile, so two
of them -- the 10th and the 90th, say -- make a band around the data, which
can widen or narrow as `x` changes. For risk, that's often the question:
not what prepayment speeds are on average at a 2-point incentive, but how
fast they are in the fastest tenth of pools. `quantile` is a number between
0 and 1; `0.5` gives the median, `lad-regression`'s fit. `x`, `y`, and
`weights` are as for `linear-regression`; the model's kind is `"quantile"`.

It makes the sum of the residuals' *losses* smallest, where a point above
the fit costs `quantile` times its distance and one below it `1 -
quantile` times its distance: for `0.9`, being above the fit costs nine
times as much as being below, so the fit settles where 90% of the points
are below it. It's found by `lad-regression`'s method, with a weighted
quantile in place of the weighted median at each swing; for the median it
is exactly that. Like LAD, it is barely moved by a point far out. Its
standard errors are found as LAD's are, for the quantile; far from the
median they need more points to be right -- with 30 points and
heavy-tailed errors, the 90th percentile's 95% intervals held the true
coefficient only about 80% of the time, but with 200, 94% of the time.

`model-report` gives the quantile, how many points are below the fit, on
it, and above it (with `n` points, at most `quantile * n` below it, and at
least that many below or on it), the average loss, and a
pseudo-R-squared, as for LAD -- each beside a perfect model's, and that of
predicting the quantile of `y` for every row.

```lisp
(define x (vector-range 400))
(random-seed 3)
(define y (+ (/ x 2) (list->vector (map (lambda (i) (* 20 (- (random-float) 0.5))) (iota 400)))))  ; noise from -10 to 10
(define upper (quantile-regression x y 0.9))
(define lower (quantile-regression x y 0.1))
(list (format "{:.1f}" (model-intercept upper)) (format "{:.1f}" (model-intercept lower)))   ; => ("8.3" "-8.7")
```
(The noise is spread evenly from -10 to 10, so the 90th percentile is 8
above the line `y = x / 2`, and the 10th, 8 below it: these 400 points
give about that.)

#### `(logistic-regression x y [weights] [:floor f :ceiling c :groups g])`
Maximum-likelihood fit of `p = sigmoid(intercept + sum(coefficients[i] *
x[i]))`, via Newton-Raphson (up to 50 iterations, or until convergence).
`x`/`y`/`weights` as `linear-regression`'s above (including `x`/`y`
accepting `(name . vector)` pairs); every value in `y` must be in `[0, 1]`
(a 0/1 label, or a probability) — values outside that range raise an
error. Returns a model of kind `"logistic"`. When the most likely curve
has a coefficient of infinity -- see below -- the fit stops, and
`model-report` says it did NOT converge.

**A floor and a ceiling.** A logistic curve is an S that flattens out at 0
on one side and at 1 on the other. For a curve that flattens out at other
levels -- a chance of prepaying that rises from about 3% to about 48%,
say -- give them as `:floor` and `:ceiling`, and the model is

```
y = floor + (ceiling - floor) * sigmoid(intercept + sum(coefficients[i] * x[i]))
```

One of the two can be left out: it is 0 or 1, as usual. The floor and
ceiling are yours to choose, from what you know of the data -- not its
smallest and largest values, which are often the points out of line. How
the model is fit depends on whether they are between 0 and 1:

- **Between 0 and 1, it is a probability** -- one that can't go below the
  floor or above the ceiling -- and every `y` must be between 0 and 1: 0s
  and 1s (did each loan prepay?) or shares (what share of a pool did?).
  It is fit by maximum likelihood, as it is, with `p` the curve above; the
  method (Fisher scoring) is the Newton-Raphson below, with a floor of 0
  and a ceiling of 1. A `y` beyond the floor or ceiling is just one that
  happened to be. `model-evaluate` treats the prediction as a probability
  (log-likelihood, AUC).
- **Outside 0 and 1, it is a number, not a probability**: a price, a
  percentage, a count, that rises in an S from the floor to the ceiling.
  `y` is rescaled to `(y - floor) / (ceiling - floor)`, which goes from 0
  to 1, and that is fit as a probability would be. Data scatters about the
  levels a curve flattens out at, so some of it is beyond them: a `y` below
  the floor is taken to be at the floor, and one above the ceiling at the
  ceiling (`model-report` says how many were). `model-evaluate` treats the
  prediction as any other number (R-squared, RMSE, MAE).

A probability that can't go below the floor, or above the ceiling, also
limits what a point far from the curve can cost the fit: with them, a
plain logistic curve is pulled much less by points out of line.

**Fitting the floor and ceiling.** Give `'fit` for either, or both --
`:ceiling 'fit` -- and it is the one that makes the data most likely,
with the curve fit for it. For a probability only: every `y` must be
between 0 and 1. It's found by trying every 0.05 from 0 to 1, fitting the
curve for each, then every 0.01 near the best, and every 0.002 near the
best of those. `model-report` gives each fitted one, and its 95% range:
how far it could move, either way, before the data is clearly less likely
-- its log-likelihood lower by 1.92, which for 0s and 1s makes the range
roughly a 95% confidence interval. (That's in the units of the average
weight; and for shares, which scatter less than 0s and 1s, it's 1.92
times how much less, which narrows the range accordingly -- a "quasi-
likelihood" ratio. It doesn't allow for `:groups`, and it's found to the
nearest 0.002.) A ceiling is only
well fitted where there is data on the curve's flat top: with none, the
range runs up to 1. A spline can level off by itself, at its knots, so a
`spline-logistic`'s fitted ceiling is only loosely set. `model-floor` and
`model-ceiling` give a model's floor and ceiling.

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; 3% to 48%
(define m (logistic-regression x y :floor 'fit :ceiling 'fit))
(list (model-floor m) (model-ceiling m))                        ; => (0.03 0.48)
```

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; 3% to 48%
(define m (logistic-regression x y :floor 0.03 :ceiling 0.48))
(vector-round (vector (model-intercept m) (model-slope m)) 6)   ; => #(-3.0 3.0)
(format "{:.3f}" (model-predict m 10))                          ; => "0.480"
(define percent (logistic-regression x (* 100 y) :floor 3 :ceiling 48))   ; the same, in percent
(format "{:.1f}" (model-predict percent 10))                     ; => "48.0"
```

**How the coefficients are found.** Fitting maximizes the (weighted)
log-likelihood of the data —

```
sum over every observation i of:
  weight[i] * ( y[i]*log(p[i]) + (1-y[i])*log(1-p[i]) )
```

— where `p[i]` is this model's own `sigmoid(...)` prediction for row `i`;
this is the standard maximum-likelihood objective for logistic regression
(equivalently, the negative of the weighted cross-entropy loss), with
every `weight[i] = 1` unless you pass your own. Unlike `linear-regression`'s
objective, this one is *not* quadratic in the coefficients, so there's no
closed-form solution — the interpreter instead finds the maximizing
coefficients iteratively, by Newton-Raphson (the same algorithm is also
called Iteratively Reweighted Least Squares, "IRLS", elsewhere). Starting
from all-zero coefficients, each iteration computes this objective's
gradient and Hessian at the current coefficients, solves for the step that
would exactly reach the maximum if the objective were quadratic right there
(via the very same linear-system solver `linear-regression` uses for its
one-shot solve), and takes that step -- or half of it, or a quarter, if
the whole step would make the data less likely (far from the top, the
objective isn't a parabola); this repeats until a step is smaller than
`1e-8`, or 50 iterations pass without converging. Sometimes the TRUE
maximum has a coefficient of infinity: when a predictor separates the 0s
from the 1s perfectly, or when every point of a spline's piece is at or
beyond the floor or ceiling, which the curve can come ever closer to by
getting steeper there. Then the Hessian becomes singular, the fit stops
where it is, and `model-report` says it did NOT converge: its predictions
are near the limit the curve was heading for, but its coefficients and
standard errors mean little. Each iteration's gradient/
Hessian (the same O(n · p²) shape as `linear-regression`'s normal
equations, above) is likewise built with numpy matrix operations, not a
Python-level loop — and since this whole computation repeats up to 50
times, it's where nearly all of `logistic-regression`'s fitting time goes
for a large dataset.

```lisp
(define m (logistic-regression prices demand))
(display (model-report m))
```

**Shares.** When `y` is all 0s and 1s -- did each loan prepay? -- the
standard errors are the usual ones for logistic regression, which take
each `y` to scatter about its chance `p` by `p (1 - p)`, as a 0 or a 1
does. A share -- the part of a pool that prepaid in a month -- is an
average over many loans, and scatters far less, so those would be much too
large. So when any `y` is between 0 and 1, the standard errors come from
how much `y` actually scatters about the fit (the "sandwich" of "Rows that
come in groups", above, with each row its own group), and `model-report`
says so. For a `spline-logistic` model of the pools' CPRs in
`examples/synthetic_mbs_pools.csv`, the usual ones would be 10 to 25 times
too large. Pools' months are alike, too: with each pool's months a group
(`:groups pool-id`), the standard errors are 2 to 4 times larger again.

The measures of fit are also different for shares: `model-report` gives
R-squared, RMSE, and MAE, as for least squares, and a perfect model's
log-likelihood, pseudo-R-squared, and AUC are short of 0, 1, and 1 (see
"How good is a model?", below).

#### `(spline-regression x y [max-knots weights] [:smooth #t :groups g])`
A simple, dependency-free way to let a model bend instead of insisting on a
straight line. For each predictor `x`, a handful of "knot" locations are
chosen (automatically, at quantiles of `x`'s own values, or exactly where
you specify), and the model gets one extra *hinge* feature `max(0, x -
knot)` per knot alongside the plain linear term — or, for a predictor
marked `'categorical`, one 0/1 indicator column per non-baseline distinct
value instead of hinges. Fitting then just reuses `linear-regression`'s own
fitting code on this expanded feature set (`spline-lad` and
`spline-logistic`, below, reuse `lad-regression`'s and
`logistic-regression`'s). Returns a model of kind `"spline"`. `x`/`y` accept
the same shapes `linear-regression`/`logistic-regression` do — including a
list of `(name . vector)` pairs for `x` and a `(name . vector)` pair for
`y` — and `model-report` (below) uses those names the same way.

**How the coefficients are found.** There's no separate spline-fitting
algorithm — `spline-regression` isn't a different way of minimizing
anything, it's a different set of *columns* to feed into one of the
algorithms already described above. Every knot's hinge column and every
category's 0/1 indicator column (see the table below) is computed first;
those expanded columns are then handed to `fit_linear` exactly as if you
had built those columns yourself and called `linear-regression` directly
on them — same objective, same closed-form solve, same optional `weights`,
just applied to `x`'s expansion instead of `x` itself. (`spline-lad` and
`spline-logistic` hand the same columns to `fit_lad` and to the logistic
fit.)

`max-knots` (default `3`) controls how *every* predictor is expanded:

| Form | Meaning |
|---|---|
| an integer, e.g. `3` | that many knots, auto-placed at quantiles of that predictor's values — applied to every predictor if there's more than one |
| `'categorical` (a symbol) | expand into 0/1 indicator columns, one per non-baseline distinct value (the smallest value becomes the implicit baseline) — applied to every predictor if there's more than one |
| a flat list of numbers/dates, e.g. `(list 25 35)` | **exact** knot locations — only valid shorthand when there is exactly **one** predictor |
| a list with one entry per predictor, e.g. `(list 3 0)` or `(list (list 25 35) 'categorical)` | full per-predictor control: each entry is itself an integer, an explicit knot list, or `'categorical`. An entry of `0` leaves that predictor purely linear |

A non-zero knot count on a predictor with 3 or fewer distinct values is
rejected up front (naming the predictor, since hinges are meaningless
there and can make the fit singular) — the error suggests `0` (stay
linear) or `'categorical` instead. At `model-predict` time, a categorical
value that wasn't seen while fitting raises a clear error naming the
predictor and the categories that were seen.

For a predictor with EXACTLY two distinct values (e.g. a 0/1 flag),
`'categorical` and a knot count of `0` (plain linear) produce the
identical fitted model — a two-category `'categorical` expansion is just
one 0/1 indicator column for the non-baseline value, which for an
already-0/1 predictor is the same number, unchanged. The only real
difference is validation: `'categorical` requires at least 2 distinct
values up front and rejects an unseen category at `model-predict` time,
where plain linear accepts (and silently extrapolates/interpolates)
anything numeric.

`weights` (optional, default: every observation weighted equally) — the
same per-observation weight vector `linear-regression` takes (see
"Weighted fitting", above); passed straight through to the fit on the
expanded basis.

**Smooth splines.** The hinges make a curve of straight pieces, with a
corner at each knot, and its last piece goes on as far as you predict.
`:smooth #t` makes a *restricted cubic spline* (a "natural" spline)
instead: cubic pieces that join smoothly at the knots, with no corners, and
a straight line below the first knot and above the last. That's often
truer to the data -- a prepayment curve bends; it doesn't turn corners --
and safer beyond it, since a straight line goes on as it was going, where
a cubic might turn anywhere. It works the same way: in place of a hinge at
each knot, a predictor gets one curved term for each knot but the last two
(see `restricted_cubic_terms` in `lisp_regression.py` for the formula),
and the same fit runs on them. So it takes at least 3 knots, and with `k`
knots it has `k - 1` coefficients for the predictor, where the hinges have
`k + 1`: with the same knots, it bends less freely. All four spline
functions take `:smooth`, and a categorical predictor stays categorical.

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; an S
(define smooth (spline-regression x y (list -1 0 1 2) :smooth #t))
(table-column (model-coefficient-table smooth) "term")   ; => #("intercept" "x1" "x1 (curve at knot -1)" "x1 (curve at knot 0)")
```

```lisp
(define home-type (vector 0 1 0 1 1))          ; 0=own, 1=rent
(define m (spline-regression (list income home-type) happiness
                              (list 2 'categorical)))
(display (model-report m))
(model-predict m (list 50000 0))                ; predict for "own", income=50000
```

#### `(spline-logistic x y [max-knots weights] [:floor f :ceiling c :smooth #t :groups g])`
A spline model with a logistic link: `spline-regression`'s expansion of
each predictor, from the same `max-knots`, fit as `logistic-regression`
fits, with the same `:floor` and `:ceiling` (and the same rules for `y`).
The prediction stays between 0 and 1 (or the floor and the ceiling), but
thanks to the hinges it doesn't have
to rise (or fall) all the way across, as a plain `logistic-regression`'s
does. Returns a model of kind `"spline-logistic"`. (This was
`spline-regression` with `logistic?` `#t`.)

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; 3% to 48%
(define s (spline-logistic x y 2 :floor 0.03 :ceiling 0.48))
(format "{:.3f}" (model-predict s 1))                          ; => "0.255"
```

#### `(spline-quantile x y quantile [max-knots weights] [:smooth #t :groups g])`
A spline model fit to a quantile: `spline-regression`'s expansion of each
predictor, from the same `max-knots`, fit as `quantile-regression` fits, so
the curve can bend, with `quantile` of the points below it. The model's
kind is `"spline-quantile"`. Two of them, at the 10th and 90th
percentiles, make a band that can bend with the data.

#### `(spline-lad x y [max-knots weights] [:smooth #t :groups g])`
A spline model fit by **least absolute deviation**: `spline-regression`'s
expansion of each predictor -- the same hinges at knots, or 0/1 columns for
categories, from the same `max-knots` -- fit as `lad-regression` fits,
making the sum of the absolute residuals smallest rather than the sum of
their squares. So the curve can bend, and a few outliers barely move it.
`x`, `y`, `max-knots`, and `weights` are as for `spline-regression`; the
model's kind is `"spline-lad"`, and `model-report` shows LAD's measures of
fit.

```lisp
(define xs (vector-range 21))
(define ys (vector-map (lambda (x) (abs (- x 10))) xs))     ; a V, bending at 10
(vector-set! ys 18 40)                                      ; and one outlier
(format "{:.2f}" (model-predict (spline-regression xs ys (list 10)) 20))   ; => "17.02"
(format "{:.2f}" (model-predict (spline-lad xs ys (list 10)) 20))          ; => "10.00"
```
(The least-squares spline's right arm is pulled up toward the outlier;
the LAD spline goes through the V's other points exactly.)

The four spline fits -- `spline-regression`, `spline-lad`,
`spline-quantile`, and `spline-logistic` -- expand the predictors the same
way: the knots depend only on `x` and `max-knots`, never on `y` or on how
the fit is made. `examples/regression_kinds_example.lsp` fits the kinds of
regression to the same made-up data and charts them, one above another --
with a floor and ceiling, a quantile band, and a smooth spline too -- and
cross-validates each.

#### `(model-report m)`
Returns a multi-line string describing a fitted model: its equation, a
table of coefficients, and measures of fit. It uses the real predictor and
`y` names if the model was fit on `(name . vector)` pairs (see above),
otherwise `x1`, `x2`, ... and `y`.

The coefficient table has one row for the intercept and one per
predictor:

| Column | Meaning |
|---|---|
| `coefficient` | the fitted value |
| `std error` | its standard error: how much it would vary from sample to sample |
| `t value` / `z value` | the coefficient divided by its standard error |
| `p value` | the chance of a coefficient at least this far from 0 if the true value were 0 — a small p value (say under 0.05) means the predictor genuinely matters |

A linear model uses the t distribution with n − p degrees of freedom (p
counting the intercept), or, with `:groups`, one fewer than the number of
groups; a logistic model uses the normal distribution (z). **With weights**, a linear model's standard errors don't depend on
the weights' scale, only their relative sizes. For a logistic model, the
weights are rescaled to average 1 for the standard errors, so weighting
by balance in dollars doesn't make the model look vastly more certain
than its row count justifies — the weights say how much each row counts
relative to the others, not how many copies of it there are.

Then the measures of fit, each beside two others: what a **perfect**
model would get -- one that predicted every `y` exactly -- and what a model
would get that **predicts the same for every row**: the average of `y`,
say, as a model with no predictors would. Where the model's value is,
between those two, says how good it is. "How good is a model?", below,
explains each measure. For a linear model: R-squared, RMSE, and MAE. For a
LAD or quantile model, see `lad-regression` and `quantile-regression`. For
a logistic model: the log-likelihood, McFadden's pseudo-R-squared, and the
AUC -- with R-squared, RMSE, and MAE first, if `y` is shares (see
`logistic-regression`) -- and the number of Newton-Raphson iterations and
whether it converged. Then `n`, and for a model fit with `:groups`, the
number of groups.

For a spline model: its predictors, each with its knot locations (or
categories and baseline value) — flagging a purely linear predictor with 3
or fewer distinct values as a candidate for `'categorical` — then the same
coefficient table for the expanded features (each labeled with its
predictor's name, e.g. `income (knot 40000)` or `home_type = 1`), and the
same measures of fit.

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(display (model-report m))
```
prints:
```
Linear model:  y = -0.7 + 10.3*x1
  term        coefficient     std error    t value    p value
  intercept          -0.7      0.834666    -0.8387      0.463
  x1                 10.3      0.251661      40.93   3.21e-05
  R-squared        = 0.998212   (perfect: 1; predicting the average of y for every row: 0)
  RMSE             = 0.616441   (perfect: 0; predicting the average of y for every row: 14.5794)
  MAE              = 0.48       (perfect: 0; predicting the median of y for every row: 12.4)
  n                = 5
```

#### `(model-coefficient-table m)`
The coefficient table from `model-report`, as a table (see "Tables", in the [language manual](lisp_interpreter_reference.md#tables)) with
the columns `term`, `coefficient`, `std_error`, `t_value` (`z_value` for a
logistic model), and `p_value`. The first row is the intercept. Its
numbers are kept at full precision, so it's the way to use them in further
calculations — or `display-table` it to see them.

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(table-column (model-coefficient-table m) "term")   ; => #("intercept" "x1")
```

#### `(model-lift-table m x y [bins weights])`
How well a model **ranks** rows — whether its highest predictions really
go with the highest outcomes, which is what matters when a model is used
to pick out or project the riskiest loans. The rows are sorted by
prediction, highest first, and split into `bins` groups of (nearly) equal
row count — 10 by default, i.e. deciles. The result is a table with one
row per group:

| Column | Meaning |
|---|---|
| `bin` | 1 holds the highest predictions |
| `rows` | the number of rows in the group |
| `weight` | their total weight (the row count, if no weights are given) |
| `mean_predicted` | the group's average prediction |
| `mean_actual` | the group's average actual `y` |
| `lift` | `mean_actual` divided by the overall average `y` |
| `cumulative_share` | the fraction of all `y` (e.g. of all payoffs) in groups 1 through this one |

With `weights` (e.g. balances), the averages are weighted. `x` and `y` are
as for `model-evaluate`; use held-out data to judge a model fairly. Good
ranking shows as `lift` well above 1 in the first bins and falling steadily.

```lisp
(define age #(1 2 3 4 5 6 7 8 9 10))
(define paid #(0 0 1 0 0 1 0 1 1 1))
(define m (logistic-regression age paid))
(table-column (model-lift-table m age paid 5) "lift")   ; => #(2.0 1.0 1.0 1.0 0.0)
```

#### `(model-evaluate m x y)`
Evaluates a fitted model's prediction quality against data — typically
held-out data it wasn't fit on — and returns a string report. `x`/`y`
follow the same shape rules as the fitting functions; the number of
predictor vectors in `x` must match the model's own predictor count. For a
non-probabilistic model (`"linear"`/`"lad"`/`"quantile"`/`"spline"`/`"spline-lad"`/`"spline-quantile"`, and a
logistic one with a `:floor` or `:ceiling` outside 0 and 1): reports
R-squared, RMSE, and MAE against this new data. For a probabilistic model
(`"logistic"`/`"spline-logistic"`, with its floor and ceiling, if any,
between 0 and 1): reports log-likelihood, McFadden's pseudo-R-squared, and
AUC -- after R-squared, RMSE, and MAE, if `y` is shares -- and, if `y` is
all 0s and 1s, accuracy: how often a prediction of 0.5 or more went with a
1, and one under 0.5 with a 0. As in `model-report`, each is beside a
perfect model's and that of predicting the same for every row -- here, the
average (or median) of *this* data's `y`; for accuracy, the commoner of 0
and 1. For a rare outcome, such as a monthly payoff, accuracy says little:
predicting "no payoff" for every row is usually 99% accurate, and the
report shows that beside it. "How good is a model?", below, explains each
measure. Works uniformly across every model kind, including spline
models.

```lisp
(define age #(1 2 3 4 5 6 7 8 9 10))
(define paid #(0 0 1 0 0 1 0 1 1 1))
(display (model-evaluate (logistic-regression age paid) age paid))
```
prints:
```
Evaluation on 10 held-out observation(s):
  log-likelihood   = -4.94158   (perfect: 0; predicting the average of y for every row: -6.93147)
  pseudo R-squared = 0.287081   (perfect: 1; predicting the average of y for every row: 0)
  AUC              = 0.84       (perfect: 1; predicting the same for every row: 0.5)
  accuracy         = 0.8        (perfect: 1; predicting the commoner outcome for every row: 0.5; a prediction of 0.5 or more counts as a 1)
```
(Here it's evaluated on the data it was fit to, to keep the example short;
held-out data is the fair test.)

```lisp
(define n-train (floor (* (vector-length x) 0.7)))
(define m (linear-regression (vector-take x n-train) (vector-take y n-train)))
(display (model-evaluate m (vector-drop x n-train) (vector-drop y n-train)))
```

#### `(cross-validate fit x y [:folds 5 :seed 1 :groups g])`, `(cross-validate fit x y :times t [:last 1])`
How well the models `fit` makes predict data they *weren't* fit to. `fit`
is a procedure of `x` and `y` that returns a model -- `(lambda (x y)
(spline-lad x y 3))`, say. The rows are shuffled (by `:seed`, so it comes
out the same every time) and dealt into `:folds` groups; for each group, a
model is fit to all the other rows and predicts this group's `y`. The
result is a table with a row for each fold and a last row, `"all"`, for
every row, each predicted by the model fit without it. With `:groups`, each
group's rows stay together, in one fold; with `:times`, the model is fit to
the earlier rows and predicts the latest ones (both below).

| Column | What it holds |
|---|---|
| `fold` | `"1"`, `"2"`, ..., and `"all"` -- or, with `:times`, `time`: each of the latest times, and `"all"` |
| `rows` | how many rows were predicted |
| `groups` | with `:groups`, how many groups they're in |
| `rmse` | the root mean squared error |
| `mae` | the mean absolute error |
| `log-loss` | for a model of a probability: the mean of −(y log p + (1 − y) log(1 − p)), how unlikely it found what happened |
| `quantile-loss` | for a quantile model: the mean of the loss it makes smallest, at its quantile |

The lower, the better it predicts. That's the fair way to choose among
models, or numbers of knots: a model always fits the data it was fit to
better the more freely it can bend -- more knots, more predictors -- but
past some point it bends to the noise, and predicts new data worse.
Measured on its own data, that never shows; measured this way, it does.
`x` and `y` can be in any shape the fitting functions take, names and all.

```lisp
(random-seed 2)
(define x (vector-range 60))
(define y (+ (/ x 2) (list->vector (map (lambda (i) (* 20 (- (random-float) 0.5))) (iota 60)))))   ; a line, and noise
(define (overall measure table) (vector-ref (table-column table measure) (- (table-row-count table) 1)))
(define line (cross-validate (lambda (x y) (linear-regression x y)) x y))
(define wiggly (cross-validate (lambda (x y) (spline-regression x y 12)) x y))
(list (format "{:.2f}" (overall "rmse" line)) (format "{:.2f}" (overall "rmse" wiggly)))   ; => ("5.84" "6.41")
```
(The 12-knot spline fits these 60 points more closely than the line does,
but predicts the ones it hasn't seen less well: the data is a line, and
noise.)

**Rows in groups.** When the rows come in groups whose rows are alike --
the months of a loan -- dealing them out one by one isn't a fair test.
Each loan's other months are among the rows the model is fit to, so it is
predicting more months of loans it has seen, which is easier than
predicting new loans. A model that can bend to fit each loan -- many knots
-- looks better than it is. With `:groups` -- a value for each row, a
loan's ID, say, as the fitting functions take it (see "Rows that come in
groups", above) -- the groups are shuffled and dealt out instead of the
rows: each, in turn, to the fold with the fewest rows so far. A group's
rows are all in one fold, so the folds come out about the same size, but
not exactly. (Without `:groups`, every row is its own group, which deals
the rows out one by one.) Don't give `:groups` to the fitting procedure:
it gets only some of the rows, and the groups change the standard errors,
not the predictions.

```lisp
(random-seed 4)
(define loan (vector-map (lambda (i) (floor (/ i 24))) (vector-range 960)))    ; 40 loans, 24 months of each
(define (for-each-loan make)                                                  ; one value for each loan, on each of its rows
  (let ((value (list->vector (map (lambda (i) (make)) (iota 40)))))
    (vector-map (lambda (l) (vector-ref value l)) loan)))
(define coupon (for-each-loan (lambda () (+ 3 (* 4 (random-float))))))           ; 3% to 7%
(define habit (for-each-loan (lambda () (* 6 (- (random-float) 0.5)))))          ; how much faster or slower it pays
(define speed (+ (* 2 coupon) habit (vector-map (lambda (l) (* 4 (- (random-float) 0.5))) loan)))
(define (overall table) (format "{:.2f}" (vector-ref (table-column table "rmse") (- (table-row-count table) 1))))
(define (line x y) (linear-regression x y))
(define (wiggly x y) (spline-regression x y 20))
(list (overall (cross-validate line coupon speed)) (overall (cross-validate wiggly coupon speed)))   ; => ("2.08" "1.73")
(list (overall (cross-validate line coupon speed :groups loan))
      (overall (cross-validate wiggly coupon speed :groups loan)))                                  ; => ("2.13" "3.59")
(table-column (cross-validate line coupon speed :groups loan :folds 3) "rows")                     ; => #(336 312 312 960)
```

A loan's speed here is twice its coupon, plus the loan's own habit, plus
noise; there are 40 coupons, one for each loan. Dealt out row by row, a
spline with 20 knots predicts better than the line: with knots between
the coupons, it learns each loan's habit from the loan's other months.
With each loan's months kept together, it predicts new loans far worse.

**The latest times.** `:times` gives each row's time -- a month, as a
number such as `202506` or `18`, a string such as `"2025-06"`, or a date
-- and the model is fit once, to every row before the latest `:last` times
(1, unless given), and predicts the rows of those times: the test of a
model that will be used on the months to come. The table has a row for
each of the latest times, in a `time` column in place of `fold`, and
`"all"`. Folds mix all the months, so they can't show a model that
predicts the months it was fit among well but the next ones badly,
because rates, the economy, or lenders' rules have changed; this can.
`:folds`, `:seed`, and `:groups` don't go with `:times`.

```lisp
(random-seed 4)
(define loan (vector-map (lambda (i) (floor (/ i 24))) (vector-range 960)))    ; as above
(define (for-each-loan make)
  (let ((value (list->vector (map (lambda (i) (make)) (iota 40)))))
    (vector-map (lambda (l) (vector-ref value l)) loan)))
(define coupon (for-each-loan (lambda () (+ 3 (* 4 (random-float))))))
(define habit (for-each-loan (lambda () (* 6 (- (random-float) 0.5)))))
(define speed (+ (* 2 coupon) habit (vector-map (lambda (l) (* 4 (- (random-float) 0.5))) loan)))
(define (overall table) (format "{:.2f}" (vector-ref (table-column table "rmse") (- (table-row-count table) 1))))
(define (line x y) (linear-regression x y))
(define month (vector-map (lambda (i) (+ 1 (mod i 24))) (vector-range 960)))      ; months 1 to 24, for each loan
(define faster (+ speed (vector-map (lambda (m) (if (> m 21) 3 0)) month)))     ; in the last 3, every loan pays faster
(overall (cross-validate line coupon faster :groups loan))                      ; => "2.36"
(define latest (cross-validate line coupon faster :times month :last 3))
(table-column latest "time")                                                   ; => #("22" "23" "24" "all")
(overall latest)                                                               ; => "3.62"
```

#### `(model-residuals m x y)`
The residuals, `y` minus the model's prediction, for each row of `x` and
`y`, as a vector. `x` and `y` are as for `model-evaluate`. Works on any
model. After a `lad-regression`, the rows with the largest residuals are
the outliers the fit set aside.

```lisp
(define m (linear-regression #(1 2 3) #(1 3 2)))
(model-residuals m #(1 2 3) #(1 3 2))          ; => #(-0.5 1.0 -0.5)
```

#### `(model-coefficients m)`
Returns a vector of the model's fitted coefficients, one per predictor, in
the order the predictors were given when fitting. Only valid for
`"linear"`/`"lad"`/`"logistic"` models — raises an error on a spline model (use
`model-report` instead).

```lisp
(model-coefficients m)         ; => #(10.3)
```

#### `(model-floor m)`, `(model-ceiling m)`
A logistic or spline-logistic model's floor and ceiling: 0 and 1, unless
they were given, or fit with `'fit`.

#### `(model-intercept m)`
The model's fitted intercept (a plain number). Like `model-coefficients`,
not for a spline model.

```lisp
(model-intercept m)            ; => -0.7
```

#### `(model-kind m)`
Returns `"linear"`, `"lad"`, `"quantile"`, `"logistic"`, `"spline"`,
`"spline-lad"`, `"spline-quantile"`, or `"spline-logistic"`. Works on any
model.

```lisp
(model-kind m)                 ; => "linear"
```

#### `(model-predict m x)`
Predicts the fitted value at a new point. `x` may be a bare number or date
when `m` has exactly one predictor, or `(list x1 x2 ...)` (in the same
order the model was fit with) for a multi-predictor model — a
single-predictor model accepts either form. Raises an error if the number
of values given doesn't match the model's predictor count. Returns a plain
number: the fitted value for `"linear"`/`"spline"` models, or a `[0, 1]`
probability for `"logistic"`/`"spline-logistic"` models.

```lisp
(define m (linear-regression (list income age) rent))
(model-predict m (list 50000 30))      ; two predictors -> a list
(define m2 (linear-regression income rent))
(model-predict m2 50000)               ; one predictor -> bare number is fine too
```

[`model_utils.lsp`](../lisp_interp/lib/model_utils.lsp)'s `(model->function m)` wraps this into
an ordinary Lisp function, one argument per predictor, instead of a list:

```lisp
(load "model_utils.lsp")
(define f (model->function m))
(f 50000 30)                           ; same as (model-predict m (list 50000 30))
```

#### `(model-slope m)`
Shorthand for "the (only) coefficient" — `(vector-ref (model-coefficients
m) 0)` — but raises a clear error if the model has more than one predictor
(use `model-coefficients` instead). Like `model-coefficients`, not for a
spline model.

```lisp
(model-slope m)                ; => 10.3
```

#### `(model? x)`
`#t` for any fitted model (linear, logistic, spline, or spline-logistic).

```lisp
(model? m)                     ; => #t
(model? 5)                     ; => #f
```

#### `(suggest-knots x y window n)`
Proposes up to `n` knot locations for `spline-regression`, based on where
`y` actually bends as a function of `x`, rather than generic quantiles:

1. Aggregates `y` (by mean) onto each *distinct* `x` value seen — matters
   for panel/pool-style data where many rows share an `x`; `window` counts
   steps along this distinct-`x` curve, not raw rows.
2. Estimates that curve's second derivative at every interior point (a
   3-point finite-difference formula that works for unevenly spaced `x`,
   including date `x` values).
3. Smooths that sequence with a centered moving average of `window`
   points.
4. Greedily picks the points with the largest smoothed `|second
   derivative|`, skipping any candidate within `window` of one already
   picked, so chosen knots represent genuinely distinct bends.

`window` must be a positive integer; `n` must be non-negative (`n = 0`
returns `'()` immediately). Requires at least 3 distinct `x` values.
Returns a Lisp list of up to `n` x-values (fewer if there aren't that many
usable candidates), sorted ascending, ready to hand straight to
`spline-regression` as an explicit knot list.

```lisp
(define knots (suggest-knots x y 5 3))
(define m (spline-regression x y knots))
```

A larger `window` smooths away small wiggles and flags only broader bends
(forcing suggested knots further apart); a smaller `window` is more
sensitive to sharp, narrow features but can suggest closely-spaced knots.
`x`/`y` don't need to be pre-sorted. Because `window` is measured in
distinct-`x` steps, size it relative to how many distinct `x` values the
data actually has, not the row count.

### How good is a model? The measures, explained

Every measure of a model compares its predictions with what actually
happened. A number by itself says little: is an RMSE of 0.046 good? So
`model-report` and `model-evaluate` put two others beside each:

- **perfect**: what a model would get that predicted every row exactly.
- **predicting the same for every row**: what a model would get that
  knows nothing about the predictors and predicts one number for every
  row -- the average of `y`, say (or whichever one number does best on
  that measure).

A model is worth something to the extent that it's closer to perfect than
to predicting the same for every row. Here is the report of a
`spline-logistic` model of the monthly CPRs of 600 pools
(`examples/synthetic_mbs_pools.csv`; the predictors are the rate
incentive, the loan age, and whether the loans were refinancings):

```
  R-squared        = 0.811845   (perfect: 1; predicting the average of y for every row: 0)
  RMSE             = 0.0461904  (perfect: 0; predicting the average of y for every row: 0.106486)
  MAE              = 0.0287087  (perfect: 0; predicting the median of y for every row: 0.078044)
  log-likelihood   = -13302.8   (perfect: -13116; predicting the average of y for every row: -14355.8)
  pseudo R-squared = 0.0733469  (perfect: 0.0863629; predicting the average of y for every row: 0)
  AUC              = 0.693018   (perfect: 0.706028; predicting the same for every row: 0.5)
```

The pseudo R-squared of 0.073 looks dreadful next to the R-squared of 0.81.
But a perfect model would get only 0.086, so this one gets 85% of the
way there. Without the "perfect" beside it, it would be easy to throw out
a good model.

In what follows, a **residual** (or error, or miss) is one row's actual
`y` minus the model's prediction for it: positive when the model
predicted too little.

**Measures of a number** -- a price, a CPR, a spread:

- **RMSE**, the root mean squared error: the typical size of a miss, in
  `y`'s own units. Square each residual, average them, and take the
  square root. An RMSE of 0.046 for CPRs means the predictions are
  typically about 4.6 percentage points off. Squaring makes big misses
  count far more than small ones: one miss of 10 counts as much as a
  hundred misses of 1. Predicting the average for every row gives the
  standard deviation of `y`.
- **MAE**, the mean absolute error: the average size of a miss, ignoring
  whether it was too high or too low. Big misses count only by their
  size. If the RMSE is much larger than the MAE, a few rows are missed
  by a lot. Predicting the median of `y` for every row does best on MAE,
  so that's the comparison.
- **R-squared**: the share of the variation in `y` the model accounts
  for. It's 1 − (the RMSE / the RMSE of predicting the average)²: 0.81
  means the model's squared misses are 19% of what they'd be predicting
  the average for every row. 1 is perfect; 0 is no better than the
  average. On data the model wasn't fit to, it can be below 0: worse
  than the average.
- **pseudo R-squared, for LAD and quantile models**: the same idea, with
  what that model makes smallest -- the MAE for LAD, the average loss for
  a quantile model -- in place of squared misses.
- **average loss, for a quantile model**: a quantile fit is meant to
  have some of the points above it -- 10% for the 0.9 quantile -- so a
  miss above isn't simply bad. A point above the fit costs `quantile`
  times its distance, and one below it `1 − quantile` times its distance;
  this is the average cost. Predicting the quantile of `y` for every row
  is the comparison.

**Measures of a probability** -- the chance a loan prepays, or the share
of a pool that does:

- **log-likelihood**: how likely the model found what actually happened.
  For each row it takes the log of the chance the model gave the
  outcome: for a loan that prepaid, log(p); for one that didn't, log(1 −
  p). Then it adds them up. A model that said 2% for a loan that then
  prepaid loses log(0.02) = −3.9 on that row; one that said 50% loses
  only −0.7. It's always 0 or less, and closer to 0 is better. The sum
  grows with the number of rows, so it means little by itself; compare
  it with the two beside it. For shares, a row with share `y` counts as
  `y` of a prepayment and `1 − y` of none.
- **log-loss** (in `cross-validate`): minus the log-likelihood divided by
  the number of rows -- the same, per row, so it can be compared across
  data of different sizes. Lower is better.
- **pseudo R-squared** (McFadden's): how far the log-likelihood has come
  from predicting the average chance for every row toward perfect, as R-
  squared does for squared misses. For 0s and 1s, perfect is 1. Even
  good models of rare events score low on it -- 0.2 to 0.4 is considered
  very good -- because no model can say which loans will prepay this
  month, only which are likelier to.
- **AUC** (the area under the ROC curve): how well the model *ranks*
  rows. Pick, at random, one loan that prepaid and one that didn't: the
  AUC is the chance the model gave the one that prepaid the higher
  chance. 0.5 is a coin toss, and is what predicting the same for every
  row gets; 1 is perfect ranking. It says nothing about whether the
  chances are the right *size*: doubling every prediction leaves it the
  same. For shares, each row is that share of a prepayment and the rest
  of none, so even perfect is short of 1.
- **accuracy** (in `model-evaluate`, for 0s and 1s): how often a
  prediction of 0.5 or more went with a 1, and one under 0.5 with a 0.
  For something rare, it's nearly useless: if 1% of loans prepay, a
  model that says "no" for every loan is 99% accurate, and knows
  nothing. The report puts that beside it ("predicting the commoner
  outcome for every row").

**Why perfect is short of 1 for shares.** A 0 or a 1 is an outcome a model
can be sure of: say 100% for a loan that prepays, and the row loses
nothing. A share of 0.1 isn't: even predicting exactly 0.1, the model
gives a 90% chance to "not prepaid" for that part of the pool, and the
log-likelihood can't reach 0. So with shares, judge the log-likelihood,
pseudo R-squared, and AUC against the perfect ones beside them, and look
at R-squared, RMSE, and MAE, which mean the same for shares as for any
number.

**The lift table** (`model-lift-table`) shows two things at once. It sorts
the rows by their prediction, highest first, and splits them into tenths.
For each tenth, compare `mean_predicted` with `mean_actual`: if they're
close all the way down, the predictions are the right size (the model is
"calibrated"). And `lift` -- each tenth's actual average divided by the
overall average -- should fall steadily from the top: the model puts the
rows that really prepay faster at the top. For the pool model above:

| bin | mean_predicted | mean_actual | lift |
|---|---|---|---|
| 1 | 0.343 | 0.340 | 2.10 |
| 2 | 0.287 | 0.300 | 1.86 |
| 5 | 0.137 | 0.123 | 0.76 |
| 10 | 0.046 | 0.057 | 0.35 |

The highest tenth prepaid at 2.1 times the average, the lowest at a third
of it, and each tenth's prediction is within a couple of percentage points
of what happened.

**Standard errors, and t, z, and p values** (the coefficient table) are
about the coefficients, not the predictions. A coefficient's standard
error is how much it would vary if the model were fit to another sample
of the same kind of data. Its t value (or z value) is the coefficient
divided by its standard error: how many standard errors it is from 0. Its
p value is the chance of a t value at least that far from 0 if the
predictor in fact had no effect. Under 0.05 is the usual sign that the
predictor matters. They assume each row is new information: when rows
come in groups that are alike, they're too small, and `:groups` fixes
that (see "Rows that come in groups", above).

**Fit to its own data, or new data?** Every measure in `model-report` is
of the data the model was fit to, which flatters it: a model that bends
to every point looks perfect there, and predicts new data badly. The
honest numbers are from data the model hasn't seen: `model-evaluate` on
rows held out, or `cross-validate`, which does that for every row. When
choosing between models, compare those.

### Models fitted to Freddie Mac's loans

Three libraries fit models to a sample of Freddie Mac's 30-year fixed-rate loans: a SQLite database, made by the scripts in `load_freddie_data/`
(its `README.md` says how), with every month of each loan.

- [`freddie_prepayment.lsp`](../lisp_interp/lib/freddie_prepayment.lsp): how fast loans prepay ([`notebooks/freddie_prepayment_model.ipynb`](../lisp_interp/notebooks/freddie_prepayment_model.ipynb));
- [`freddie_default.lsp`](../lisp_interp/lib/freddie_default.lsp): how many default, what is lost when they are sold, and what became of them
  ([`notebooks/freddie_default_model.ipynb`](../lisp_interp/notebooks/freddie_default_model.ipynb));
- [`freddie_loans.lsp`](../lisp_interp/lib/freddie_loans.lsp): what the two share.

**What they share.** Most of the models are of a **monthly rate**: the share of a loan's balance that something happened to in a month (that it prepaid, the
smm; that defaulted, the mdr), a `spline-logistic` of it, with each row weighted by the balance, so that over a pool it is the pool's rate. `(annual-rate monthly)`
is twelve months of it in percent, 1 - (1 - monthly)^12: the CPR of an smm, the CDR of an mdr; `(monthly-rate annual)` is the other way. (Both are in
`lib/prepayment_speed.lsp`, with the deal's prepayment speeds.) A model looks at a list of `predictor`s, each a name, what it is in
SQL, and its knots; a knot without data on both sides of it, from the 1st to the 99th percentile, is left out (`knots-within`): its hinge would be a column of
zeros, or one that a few rows could make as steep as they liked.

What a model is fitted to is a `loan-data` (the periods, the outcomes, the weights, and the predictors). A model is tried on loans it was not fitted to (a
`sample_bucket` of 80 or more): `(rate-by-month model data label)` is a table of the annual rate (`label`, `"CPR"` or `"CDR"`) of all the rows of a month together,
and what the model says it was; `(plot-rate-by-month (list (list name model data) ...) label)` draws it for several models; `(rate-misses (list (list name model data)
...) split label)` is a table of how far each model is from its data, on average over the months, before the date `split` and from it on. `(model-curve model predictors
loan name values)` is what a model says of a loan as one of its predictors takes each of the values.

**Prepayments.** A `spline-logistic` of the smm, the share of a loan's scheduled balance that it prepaid in a month (1 for a loan paid off, and a part for a loan paid
down early). The predictors are `prepayment-predictors`: the incentive (the loan's rate over the survey rate of new mortgages, in basis points), the age, the loan size,
the credit score, the loan-to-value now, the spread at origination, burnout, the shares on investment properties and second homes and of cash-out and other
refinances, and two seasons. It can be fitted two ways, on the same predictors, so that the two can be compared: `(freddie-loan-months conn where)`, every month of
every loan that is `where` (an SQL condition, such as `"sample_bucket < 80"`), and `(freddie-groups conn where)`, the months of loans that are alike put together,
each group's smm and the averages of its loans (the averages of groups are closer together than the loans, so the groups can lose a knot that the loans keep).
`(fit-prepayment-model data)` fits either. `(prepayment-s-curve model)` is the CPR of `typical-prepayment-loan` for each incentive from -200 to 400 basis points, and
`(plot-prepayment-s-curves (list (list name model) ...))` draws them.

**For a deal.** `(freddie-prepayment-model [:home-price-growth 3.0 :mortgage-spread 1.75 :fit model])` is a prepayment model of the kind that a deal is given,
`(model piece path)` (see "The prepayment model" in [lisp_cmo_manual.md](lisp_cmo_manual.md)): for a `collateral-piece` and a path of rates, the CPR of each month of
the piece, from what the fitted model looks at in each month, `(prepayment-model-columns piece path)`. The incentive is the wac less the rate of a new mortgage, the
path's 10-year yield plus `:mortgage-spread` (percent); the age goes on from the piece's; the loan size and the loan-to-value are paid down by the scheduled payments,
and the loan-to-value falls as home prices grow by `:home-price-growth` (percent a year); burnout counts the months in the money; the seasons are of the months from
the path's first payment. What a piece does not say is taken from `unknown-piece`. The fitted model is the one that comes with the library,
`lib/freddie_prepayment_fit.json`, which `(freddie-prepayment-fit)` reads, unless `:fit` is another; the prepayment notebook makes it, with
`(save-freddie-prepayment-fit model path)`. In the same way `(freddie-default-model [:home-price-growth :mortgage-spread :fit])` gives the CDR of each month of a piece
(from `(default-model-columns piece path)`), and `(freddie-severity-model [:home-price-growth :mortgage-spread :lag 18 :fit])` the severity, from 0 to 1, of the loans that
default in each month, sold `:lag` months later (from `(severity-model-columns piece path)`); they read `lib/freddie_default_fit.json` and
`lib/freddie_severity_fit.json`, which the default notebook makes with `(save-freddie-default-fits default-model severity-model directory)`. A deal uses them when it is
told that its loans default (see "Defaults, from the default model" in the CMO manual). What the three models share, the piece along the path of rates, is
`(piece-on-path piece path home-price-growth mortgage-spread)`, in `freddie_loans.lsp`.

**Defaults.** A loan defaults in the first month that it is six months delinquent, unless it is in forbearance or delinquent because of a disaster (as most loans that
were, in 2020 and 2021, were), or that the home is taken, or that the loan ends in a short sale, a third-party sale, an REO sale or a sale of the note while it is not
being paid; it defaults once. `(freddie-default-months conn where)` is the months of the loans that have not defaulted yet, the outcome 1 in the month of the default,
weighted by the balance, and `(fit-default-model data)` a `spline-logistic` of it: the mdr. The predictors are `default-predictors`: the credit score, the
loan-to-value now, the age, the debt-to-income, the spread at origination, the incentive, the loan size, an investment property, a second home, a cash-out refinance,
another refinance, and one borrower. `(default-ltv-curves model)` is the CDR of `typical-default-loan` against its loan-to-value now, a column for each of three
credit scores, and `(plot-default-ltv-curves model)` draws it.

**Losses.** `(freddie-liquidations conn where)` is the sales of defaulted loans that Freddie reports a loss for (short sales, third-party sales and REO sales): the
severity of each, the loss (the balance, the unpaid interest and the costs, less what the home sold for and what mortgage insurance and others paid) over the balance,
weighted by the balance, by the year of the sale. `(fit-severity-model data)` is a `spline-regression` of it on `severity-predictors`: the loan-to-value at the default,
the balance, the mortgage insurance, the months from the default to the sale, and an investment property. `(severity-by-year model data)` is the severity of each year's
sales together, and what the model says, in percent; `(severity-ltv-curve model)` is the severity of `typical-liquidation` against the loan-to-value at the default.
`(default-outcomes conn)` is a table of what became of the loans that defaulted each year: the share of their balance sold at a loss, sold as a note, paid off, sold as
a note after it was being paid again, and not over yet; the severity, the months to the sale, and the **loss given default**, the losses over all that defaulted, which
is less than the severity, as not every default is sold at a loss.

```lisp
(define conn (sqlite-open "/Users/morris/freddie_data/freddie_loans.db"))
(define by-loan (fit-prepayment-model (freddie-loan-months conn "sample_bucket < 80 AND period < '2019-01-01'")))
(plot-rate-by-month (list (list "loan by loan" by-loan (freddie-loan-months conn "sample_bucket >= 80"))) "CPR")   ; on loans it was not fitted to
(define defaults (fit-default-model (freddie-default-months conn "sample_bucket < 80 AND period < '2019-01-01'")))
(plot-default-ltv-curves defaults)
(display-table (default-outcomes conn))
```

### Linear programming

(In `lisp_simplex.py`, which uses the simplex solver in
`simplex/simplex_solver.py`, next to `lisp_interp/`.) These solve linear
programming problems: find the values of the variables `x1, x2, ...` that
**minimize** (or **maximize**) `c1·x1 + c2·x2 + ...`, subject to
constraints of the form `a1·x1 + a2·x2 + ... <= b` (or `>=`, or `=`), with
every variable at least 0. The variables can have names of your choosing,
such as `gnma_30`, so a problem with many variables stays readable.

**A problem** is an association list of six lists (the six things
`simplex_solver.py`'s `parse_lp_file` returns):

| Part | Holds |
|---|---|
| `"objective"` | the objective's coefficients, one per variable |
| `"constraints"` | one list per constraint, holding its coefficients, one per variable |
| `"relations"` | one per constraint: `"<="`, `">="`, or `"="` |
| `"rhs"` | one per constraint: its right-hand side |
| `"variables"` | the variables' names, one per variable (optional in `lp-solve`) |
| `"goal"` | `"minimize"` or `"maximize"` (optional in `lp-solve`: the default is `"minimize"`) |

`"objective"` and each list in `"constraints"` have one number for every
variable, in the same order as `"variables"`, with a `0.0` for a variable a
formula doesn't use. You don't have to write those zeros: `lp-read-file`
fills them in from a file that uses variable names. You can also build a
problem in Lisp; see `lp-solve`.

`examples/linear_programming_example.lsp` is a worked example. It reads a problem
from `linear_programming_example.txt`: invest $100 million in four mortgage
pools for the most yield, within limits on concentration, average
duration, and credit risk. It solves the problem and prints the
allocation. Then it changes the problem in Lisp to see how the income
depends on the duration limit, and shows how an impossible limit is
reported. Run it from `lisp_interp/examples/`, where the problem file is:

```bash
python3 ../lisp_interpreter.py linear_programming_example.lsp
```

#### `(lp-read-file path)`
Reads a problem from a text file, and returns it as a problem list. The
file has this shape:

```
maximize
<the objective>
subject to
<constraint 1>
<constraint 2>
...
```

- The first line is `minimize` or `maximize` (in any mix of upper and
  lower case), and then a line with the objective. Maximizing is solved
  by minimizing the negative, and the optimal value is still reported as
  the maximum: see `lp-solve`.
- `subject to` starts the constraints, one per line. Each is a
  left-hand side, then a relation (`<=`, `>=`, or `=`), then the
  right-hand side, which is a single number.
- Blank lines, and lines starting with `#`, are ignored.
- All the numbers are read as floats.

The objective and the left-hand sides can be written either of two ways.
The objective decides which way the whole file uses.

**1. With variable names.** Write each as a formula, a sum of terms. A term
is a number and then a variable's name (`3 x`, `0.5 rate`), or just the
name (which means 1 times it). A file like this, the same problem as the
one in the second form below:

```
# Maximize 3x1 + 5x2
maximize
3 x1 + 5 x2
subject to
x1 <= 4
2 x2 <= 12
3 x1 + 2 x2 <= 18
```

The rules:

- **Spaces around everything.** Write `3 x1 + 5 x2`, not `3x1+5x2`: put a
  space between a number and a name, and around each `+` and `-`.
  (Something like `3x1` is an error that says so.)
- **Names** start with a letter or underscore, and have only letters,
  digits, and underscores (`gnma_30`, `rate2`, `_x`). Upper and lower case
  are different names. Use `_` where you'd use a space or a hyphen.
- **Order.** The variables are numbered in the order they first appear,
  starting with the objective, then the constraints. That's the order of
  `"variables"`, of the coefficients, and of the solution. A variable that
  appears only in a constraint costs nothing in the objective (its
  coefficient there is 0), and a variable a constraint doesn't mention has
  coefficient 0 in it.
- **A formula** can start with a `-` (`- x + 2 y`), and a name can appear
  more than once (`x + x` is `2 x`).

**2. With coefficients only.** Write a coefficient for every variable, in the
same order in every line, zeros included. The variables are named `x1`,
`x2`, and so on. A file for the same problem (`simplex/example_problem.txt`
is this file):

```
# Maximize 3x1 + 5x2, which is the same as minimizing -3x1 - 5x2
minimize
-3 -5
subject to
1 0 <= 4
0 2 <= 12
3 2 <= 18
```

Use this form for a problem with few variables. With many, the rows of
zeros are long, and easy to get wrong. Constraint lines here must all have
as many numbers as the objective does.

A file that doesn't follow the format is an error that names the problem
and shows the line. For the second file above:

```lisp
(define problem (lp-read-file "../simplex/example_problem.txt"))
problem
; => (("objective" -3.0 -5.0)
;     ("constraints" (1.0 0.0) (0.0 2.0) (3.0 2.0))
;     ("relations" "<=" "<=" "<=")
;     ("rhs" 4.0 12.0 18.0)
;     ("variables" "x1" "x2")
;     ("goal" "minimize"))
(lp-solve problem)     ; => (("solution" 2.0 6.0) ("optimal-value" . -36.0))
```

For the first file, saved as `problem.txt`, the problem is the same, except
that the objective is `(3.0 5.0)` and the goal is `("maximize")`, and
solving it gives `(("solution" 2.0 6.0) ("optimal-value" . 36.0))`: the
same values of `x1` and `x2`, and the maximum, 36, of `3x1 + 5x2`.

`linear_programming_example.txt` is a larger example of the first form.

#### `(lp-solve problem [max-iterations])`
Solves a problem, returning

```
(("solution" x1 x2 ...) ("optimal-value" . v))
```

the value of each variable, in the same order as the problem's
`"variables"` and `"objective"`, and the optimal value of the objective:
its minimum, or, if the problem's goal is `"maximize"`, its maximum. Use
`assoc` to get each one. Here's a problem built in Lisp: minimize `x1 + x2`
subject to `x1 + 2x2 >= 4` and `3x1 + x2 >= 6`:

```lisp
(define problem
  (list (cons "objective"   (list 1 1))
        (cons "constraints" (list (list 1 2) (list 3 1)))
        (cons "relations"   (list ">=" ">="))
        (cons "rhs"         (list 4 6))))
(define result (lp-solve problem))
result                                 ; => (("solution" 1.6 1.2) ("optimal-value" . 2.8))
(cdr (assoc "solution" result))        ; => (1.6 1.2)
(cdr (assoc "optimal-value" result))   ; => 2.8
```

A quoted list works too. In it, the relations and the goal can be symbols
(`<=`, `maximize`) rather than strings (`"<="`, `"maximize"`), which
`lp-solve` also accepts:

```lisp
; Minimize 2x1 + 3x2 subject to x1 + x2 = 10 and x1 <= 6.
(lp-solve '(("objective" 2 3)
            ("constraints" (1 1) (1 0))
            ("relations" = <=)
            ("rhs" 10 6)))     ; => (("solution" 6.0 4.0) ("optimal-value" . 24.0))

; Maximize 3x1 + 5x2 subject to x1 <= 4, 2x2 <= 12, and 3x1 + 2x2 <= 18.
(lp-solve '(("objective" 3 5)
            ("constraints" (1 0) (0 2) (3 2))
            ("relations" <= <= <=)
            ("rhs" 4 12 18)
            ("goal" maximize)))  ; => (("solution" 2.0 6.0) ("optimal-value" . 36.0))
```

To print each value beside its variable's name, go through the two lists
together. For the problem read from the first file above:

```lisp
(define result (lp-solve problem))
(do ((names (cdr (assoc "variables" problem)) (cdr names))
     (values (cdr (assoc "solution" result)) (cdr values)))
    ((null? names))
  (display (format "{:<4}{:>8.2f}\n" (car names) (car values))))
```

prints

```
x1      2.00
x2      6.00
```

**The iteration limit.** The solver works in steps (pivots). Give
`max-iterations`, a whole number of at least 1, to stop it after that many
steps; if it isn't done by then, it's an error. If you don't, the limit
is **three times the number of variables the solver works with**. That's the
problem's own variables, plus the ones the solver adds: a slack variable
for each `<=` constraint, a surplus variable and an artificial variable for
each `>=` constraint, and an artificial variable for each `=` constraint.
A problem with 4 variables and 3 `<=` constraints has 7, so the limit is
21. Ordinary problems finish in far fewer steps than that.

It's an error, with a message saying why, if:

- the problem has no solution: "Problem is infeasible" (the constraints
  contradict each other), or "Problem is unbounded" (the objective can
  go down forever, or up forever if maximizing);
- the solver doesn't finish within the iteration limit ("did not
  converge within 21 iterations", say). This can also happen, though
  rarely, when a problem makes the solver go around in a circle, which
  no limit would cure;
- the problem is malformed: a missing part, a constraint with the wrong
  number of coefficients, a count of relations or right-hand sides that
  doesn't match the constraints, a relation other than `<=`, `>=`, or
  `=`, a `"goal"` that isn't `"minimize"` or `"maximize"`, or a
  `"variables"` list that doesn't have one name for each variable.

Two things to know about the answers:

- **Rounding.** They're floats, so a value can come out as, say,
  `5.999999999999999` instead of `6`. Use `format` to show them rounded.
- **Large numbers are fine.** Costs and balances in dollars, even in the
  hundreds of millions, don't need to be scaled down. The solver uses the
  Big-M method, but it keeps M symbolic (as larger than any number)
  rather than choosing a particular big number that real costs could
  exceed. And it decides what counts as zero relative to the size of the
  problem's numbers.

```lisp
; Costs above a million: minimize 5,000,000 x1 subject to x1 >= 1.
(lp-solve '(("objective" 5000000) ("constraints" (1)) ("relations" >=) ("rhs" 1)))
                               ; => (("solution" 1.0) ("optimal-value" . 5000000.0))
```

### Stratification tables

(In `lisp_stratify.py`.) A **stratification** of a big table — loans,
say — is a small table with a row for each **bucket** of one column:
coupons under 4.0, 4.0 to 5.0, 5.0 to 6.0, ...; ten buckets of loan age
with the same number of loans in each; one row per state. Each row shows
how many loans are in the bucket, their total balance and its share of
the whole, and a summary of each other column — usually its
balance-weighted average. A last row, `total`, shows the same for the
whole table. It's like `table-group-by`, except that a group can be a
range of values, not just one value. `stratify` makes one such table, and
`stratify-all` makes a whole set of them from the same big table, each
bucketed a different way.

```lisp
(define loans
  (make-table "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 6.0)
              "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000)
              "age"     #(12 24 36 6 48 60 3 72 18 30)
              "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA")))
(define summaries '(("rate" weighted-mean "WAC") ("age" weighted-mean "WALA")))
(define formats '(("total_balance" ",.0f") ("percent" ".1%") ("WAC" ".3f") ("WALA" ".1f")))

(display-table (stratify loans '("rate" (4.0 5.0 6.0 7.0)) summaries :weight "balance")
               formats)
```

prints

```
rate          count  total_balance  percent    WAC  WALA
------------  -----  -------------  -------  -----  ----
under 4.0         2        310,000    17.6%  3.751  16.1
4.0 to 5.0        1        250,000    14.2%  4.500  24.0
5.0 to 6.0        2        475,000    27.0%  5.520  17.1
6.0 to 7.0        3        265,000    15.1%  6.288  48.7
7.0 and over      2        460,000    26.1%  7.033  12.0
total            10      1,760,000   100.0%  5.574  21.3
```

#### `(stratify table by summaries [:weight column] [:total #f])`
One stratification table. **`by`** is `(column how)`: which column to
bucket, and how —

| `how` | The buckets |
|---|---|
| `(4.0 5.0 6.0 7.0)` | breakpoints: `under 4.0`, `4.0 to 5.0` (4.0 or more, but under 5.0), ..., `7.0 and over`. Dates work as breakpoints too, for a column of dates. |
| `(equal-count n)` | `n` buckets with the same number of rows in each |
| `(equal-weight n)` | `n` buckets with the same total weight in each (needs `:weight`) |
| `(top n)` | the `n` values with the most weight (or the most rows, without `:weight`), biggest first, then all the rest as `other` |
| `each` | one bucket per distinct value, in order |
| `year` | one bucket per calendar year, for a column of dates |
| `hide` | no table: `stratify-all` leaves the column out (`stratify-plan` marks a column this way when it has nothing to show) |

With `equal-count` and `equal-weight`, the cuts fall between values, so
rows with the same value are always in the same bucket — which can leave
fewer buckets than asked for, when many rows share a value — and each
bucket is labelled with its smallest and largest value. A row whose value
is missing (`nan`, or `'()`) goes in a last bucket, `missing`. A bucket
with no rows isn't shown. `by` can also be a list of `(column how)`, to
bucket by several columns at once, with a row for each combination of
buckets that has rows in it.

**`summaries`** is a list of `(column function [heading])`, one per
summary column. `function` is any of `table-group-by`'s (see the table
there): `sum`, `mean`, `weighted-mean`, `median`, `weighted-median`,
`(percentile p)`, `(weighted-percentile p)`, `min`, `max`, `stdev`, `mode`,
`weighted-mode`, `representative`, `first`, or `last`. The weighted ones
are weighted by the `:weight` column. `representative` is for a column
like a state, which can't be averaged: a value from the bucket that stands
for it. Missing values are skipped. The heading is `column (function)`
unless you give one, e.g. `("fico" (percentile 10) "FICO 10th")`.

```lisp
(define pool (make-table "rate"  #(3.25 4.5 3.99 5.75 7.0)
                         "fico"  #(700 720 730 750 710)
                         "state" (vector "CA" "NY" "CA" "TX" "FL")
                         "balance" #(100 250 210 300 400)))
(define by-rate
  (stratify pool '("rate" (5.0))
            '(("state" representative "a state") ("state" weighted-mode "biggest state")
              ("fico" weighted-median "FICO") ("fico" (percentile 10) "FICO 10th"))
            :weight "balance"))
(table-column by-rate "biggest state")   ; => #("CA" "FL" "FL")
(table-column by-rate "FICO")            ; => #(720.0 710.0 720.0)
(table-column by-rate "FICO 10th")       ; => #(704.0 714.0 704.0)
```

The table's columns are: the bucket, named after the column; `count`;
with `:weight`, the total weight — `total_balance`, for
`:weight "balance"` — and its share of the whole, `percent` (without
`:weight`, `percent` is the share of the rows); then the summaries. The
last row is the `total`, unless `:total` is `#f`. The numbers in a
stratification table are kept in full (double) precision, unlike a big
vector's, so a total balance is exact to the cent.

```lisp
(define pool (make-table "rate" #(3.25 4.5 6.25 7.0 nan) "balance" #(100 200 300 400 50)))
(define by-rate (stratify pool '("rate" (4.0 6.0)) '(("rate" weighted-mean "WAC")) :weight "balance"))
(table-column-names by-rate)       ; => ("rate" "count" "total_balance" "percent" "WAC")
(table-column by-rate "rate")      ; => #("under 4.0" "4.0 to 6.0" "6.0 and over" "missing" "total")
(table-column by-rate "count")     ; => #(1 1 2 1 5)
(table-column by-rate "total_balance")   ; => #(100.0 200.0 700.0 50.0 1050.0)
(table-column (stratify pool '("rate" (equal-count 2)) '()) "rate")
                                   ; => #("3.25 to 4.5" "6.25 to 7.0" "missing" "total")
```

Two columns at once — each state's loans, split at a 5.0 coupon:

```lisp
(display-table (stratify loans '(("state" (top 2)) ("rate" (5.0))) summaries
                         :weight "balance" :total #f)
               formats)
```

prints

```
state  rate          count  total_balance  percent    WAC  WALA
-----  ------------  -----  -------------  -------  -----  ----
CA     under 5.0         2        310,000    17.6%  3.751  16.1
CA     5.0 and over      2        300,000    17.0%  5.594  41.0
FL     5.0 and over      1        400,000    22.7%  7.000   3.0
other  under 5.0         1        250,000    14.2%  4.500  24.0
other  5.0 and over      4        500,000    28.4%  6.090  26.0
```

#### `(stratify-all table bys summaries [:weight column] [:total #f])`
A list of stratification tables, one for each `by` in the list `bys`, all
with the same summaries — the usual way to make a whole report at once,
then show each table:

```lisp
(define loans
  (make-table "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 6.0)
              "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000)
              "age"     #(12 24 36 6 48 60 3 72 18 30)
              "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA")))
(define tables
  (stratify-all loans
    '(("rate" (4.0 5.0 6.0 7.0))
      ("age" (equal-count 3))
      ("balance" (100000 200000 300000))
      ("state" (top 3)))
    '(("rate" weighted-mean "WAC") ("age" weighted-mean "WALA"))
    :weight "balance"))
(dolist (table tables)
  (display-table table '(("total_balance" ",.0f") ("percent" ".1%") ("WAC" ".3f") ("WALA" ".1f")))
  (newline))
(map (lambda (t) (car (table-column-names t))) tables)   ; => ("rate" "age" "balance" "state")
```

#### `(stratify-plan table [:weight column])`
A first look at a table you have not seen before, without choosing the
buckets yourself. It returns a list of three things, `(bys summaries
formats)`, which are the arguments `stratify-all` and `display-table`
take. Each column, but the weight column, gets a way of bucketing:

| The column | Its `by` |
|---|---|
| empty, or with one distinct value | `hide` (no table) |
| 10 distinct values or fewer | `each` |
| dates | `year` |
| text, with more than 10 values | `(top 5)` |
| numbers, with a `:weight` | `(equal-weight 5)` |
| numbers, without | `(equal-count 5)` |

Each numeric column that is not hidden also gets a summary, its average
(`weighted-mean` with a `:weight`, `mean` without), headed `avg rate` for
a column `rate`, and a format that suits its numbers: `",.0f"` if any are
above 10,000 or below -10,000 (dollars, or people, perhaps); `".1%"` if
all are from 0 to 1; `".3f"` if all are under 20 (interest rates,
perhaps); `",.2f"` otherwise. `count`, `percent` and the `total_` column get formats too.
Change any of it before you use it: it is only a list.

```lisp
(define pool (make-table "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000 70000 80000)
                         "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 6.0 5.5 5.0)
                         "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA" "OR" "NV")
                         "version" #(1 1 1 1 1 1 1 1 1 1 1 1)))
(define plan (stratify-plan pool :weight "balance"))
(first plan)    ; => (("rate" (equal-weight 5)) ("state" each) ("version" hide))
(second plan)   ; => (("rate" weighted-mean "avg rate"))
(third plan)    ; => (("count" ",d") ("percent" ".1%") ("total_balance" ",.0f") ("avg rate" ".3f"))

(destructuring-bind (bys summaries formats) plan
  (dolist (table (stratify-all pool bys summaries :weight "balance"))
    (display-table table formats)
    (newline)))
```

#### `(plot-stratification table [:formats formats] [:column heading])`
(In `lib/stratify_plot.lsp`.) A chart of one stratification table: a bar
for each bucket's share of the whole, and a line over the bars, on the
secondary axis, for what the buckets average, so that a change from
bucket to bucket is seen at once. The line is the table's first summary
unless `:column` names another column of the table. `:formats` is a list
of formats such as `display-table` takes, which write the axes' numbers.
The `total` row is left out, and a table with no summaries has only bars.
A table of several columns labels each bar with the buckets, joined by
` / `. It draws as `plot-chart` does, so it is a chart in a notebook cell.

```lisp
(destructuring-bind (bys summaries formats) (stratify-plan pool :weight "balance")
  (dolist (table (stratify-all pool bys summaries :weight "balance"))
    (display-table table formats)
    (plot-stratification table :formats formats)))
```

`examples/stratify_example.lsp` makes a report of eight tables from a
pool of 5,000 made-up loans, and shows how to load real loan data from
SQLite instead. The tables are ordinary tables, so `write-columns-csv`
writes one to a CSV file, and `table-filter` and the rest work on them.

## Investments

### Option prices

(In `lisp_options.py`.) Black-Scholes-Merton for European options on a
stock, Black's formula for them on a forward price, implied volatility, the
Greeks, the chance of ending in the money, and American options by a
binomial tree.

Every argument can be a number or a vector, with an element for each
option, so a whole option chain is priced at once, and the answer is then a
vector. `type` is `"call"` or `"put"`, in any case (tastytrade's `"Call"`
works), or `#t` or 1 for a call and `#f` or 0 for a put. `time` and `T` are
in years (30 days is 30/365.0), `rate` is the interest rate, continuously
compounded (0.04 for 4%), and `vol` is a year's volatility (0.2 for 20%).

#### `(bsm-price type spot strike time rate vol [:dividend-yield q])`
The Black-Scholes-Merton price of a European option on a stock at `spot`
that pays a continuous dividend yield `q` (0 unless given). For dividends
that are known amounts on known dates, see `american-price`, or Black's
formula on the forward.

```lisp
(format "{:.4f}" (bsm-price "call" 100 100 1 0.05 0.2))         ; => "10.4506"
(format "{:.4f}" (bsm-price "put" 100 100 1 0.05 0.2))          ; => "5.5735"
(vector-round (bsm-price (vector "call" "put") 100 #(95 105) 0.5 0.04 0.25) 4)   ; => #(10.7854 8.7008)
```

#### `(implied-vol price type spot strike time rate [:dividend-yield q])`
The volatility at which `bsm-price` gives `price`. It is found by
bisection: the range 0.1% to 500% is halved 50 times, each time keeping
the half the answer is in, since the price rises with volatility. `nan`
where no volatility gives the price, such as a price below what the option
would pay now.

```lisp
(format "{:.4f}" (implied-vol 10.4506 "call" 100 100 1 0.05))    ; => "0.2000"
```

#### `(bsm-delta ...)`, `(bsm-gamma ...)`, `(bsm-vega ...)`, `(bsm-theta ...)`, `(bsm-rho ...)`
The Greeks, with `bsm-price`'s arguments: how much the price changes.

| Greek | For |
|---|---|
| delta | a change of 1 in the stock's price |
| gamma | how much delta changes, for a change of 1 in the stock's price |
| vega | a change of 1 point (0.01) in volatility, as tastytrade has it |
| theta | a calendar day passing (1/365 of a year); negative, as an option loses value as it nears expiration |
| rho | a change of 1 point (0.01) in the interest rate |

```lisp
(format "{:.4f}" (bsm-delta "call" 100 100 1 0.05 0.2))     ; => "0.6368"
(format "{:.4f}" (bsm-gamma "call" 100 100 1 0.05 0.2))     ; => "0.0188"
(format "{:.4f}" (bsm-vega "call" 100 100 1 0.05 0.2))      ; => "0.3752"
(format "{:.4f}" (bsm-theta "call" 100 100 1 0.05 0.2))     ; => "-0.0176"
(format "{:.4f}" (bsm-rho "call" 100 100 1 0.05 0.2))       ; => "0.5323"
```

#### `(bsm-probability-in-the-money type spot strike time rate vol [:dividend-yield q])`
The chance that the option ends in the money (the stock's price at
expiration above the strike, for a call, or below it, for a put) in the
Black-Scholes model: N(d2) for a call and N(-d2) for a put, where
d2 = (ln(spot / strike) + (rate - q - vol²/2) time) / (vol √time). It is a
*risk-neutral* chance: one in a model where the stock grows at the
interest rate (less q), not at what it is expected to earn. So it isn't a
forecast of how likely the option is to pay off; it's a step in the
formula, and what an option that pays 1 if it ends in the money would cost,
before discounting.

```lisp
(format "{:.4f}" (bsm-probability-in-the-money "call" 100 100 1 0.05 0.2))   ; => "0.5596"
(format "{:.4f}" (bsm-probability-in-the-money "put" 100 100 1 0.05 0.2))    ; => "0.4404"
(vector-round (bsm-probability-in-the-money (vector "call" "put") 100 #(95 105) 0.5 0.04 0.25) 4)   ; => #(0.6236 0.5992)
```

#### `(black-price type forward strike T discount vol)`, `(black-implied-vol type price forward strike T discount)`
Black's formula, from the forward price `F` and the discount factor:
`discount * (F N(d1) - K N(d2))` for a call and `discount * (K N(-d2) -
F N(-d1))` for a put, with `d1 = log(F/K) / (vol sqrt(T)) + vol sqrt(T) /
2` and `d2 = d1 - vol sqrt(T)`. It is the same formula as `bsm-price`,
since `F = spot e^((rate - q) T)` and `discount = e^(-rate T)`; and for a
stock that pays known dividends, `F` is its price less their present value,
grown at the interest rate. `black-implied-vol` finds the volatility as
`implied-vol` does.

```lisp
(format "{:.4f}" (black-price "call" 105.13 100 1 0.9512 0.2))   ; => "10.4520"
```

#### `(normal-cdf x)`
The chance that a standard normal number is below `x`: `0.5 (1 + erf(x /
sqrt 2))`.

#### `(american-price type spot strike time rate vol [:dividend-yield q] [:dividends table] [:steps n] [:early-exercise #f])`
The price of an option that can be exercised before it expires, by a
binomial tree (Cox, Ross, and Rubinstein's). In each of `:steps` steps (200
unless given) the price goes up by a factor `u = e^(vol sqrt(dt))` or down
by `1/u`, with the chance of going up that makes the stock grow at the
interest rate, less `q`. Working back from expiration, the option is worth,
at each point, the larger of what it would pay if exercised then and what
keeping it is worth.

- `:dividends` is a table of `time` (in years from now) and `amount`
  columns, for dividends that are known amounts on known dates. The tree is
  of the price less the present value of the dividends still to come before
  expiration, and an option exercised early gets the whole price: the usual
  way to handle them ("escrowed dividends"). A dividend after the option
  expires counts for nothing.
- `:early-exercise #f` prices the European option with the same tree. The
  difference between the two is what the right to exercise early is worth,
  without the tree's own small error (about 0.01 on these examples): a
  tree's price is close to the formula's, not the same.
- An American call on a stock that pays no dividends is never worth
  exercising early, so it is worth what the European one is. An American put
  can be, and so can a call just before a dividend.

```lisp
(format "{:.4f}" (american-price "put" 100 100 1 0.05 0.2))                     ; => "6.0864"
(format "{:.4f}" (american-price "put" 100 100 1 0.05 0.2 :early-exercise #f))  ; => "5.5635"
(define dividend (make-table "time" #(0.5) "amount" #(5.0)))
(format "{:.4f}" (american-price "call" 100 100 1 0.05 0.2 :dividends dividend))                     ; => "7.9168"
(format "{:.4f}" (american-price "call" 100 100 1 0.05 0.2 :dividends dividend :early-exercise #f))  ; => "7.5802"
```

#### `(american-implied-vol price type spot strike time rate [american-price's options])`
The volatility at which `american-price` gives `price`, by bisection, as
`implied-vol` finds it; `nan` where none does. It prices a tree 50 times
for each option, so it takes a moment for a chain: fewer `:steps` make it
faster.

#### `(binomial-tree type spot strike time rate vol [american-price's options])`
Every node of the tree `american-price` prices one option with, to see how
it gets its answer: a table, from the first step to the last, with a row
for each node. It has 5 steps unless `:steps` says otherwise, so it can be
read. Its columns:

| Column | What it holds |
|---|---|
| `step` | the step, 0 for now |
| `ups` | how many of the steps to this node went up |
| `time` | in years |
| `price` | the stock's price there |
| `hold` | what keeping the option is worth there: the next step's values, weighted by the chances of going up and down, and discounted; `nan` at expiration |
| `exercise` | what exercising it there pays |
| `value` | the option's value there: the larger of `hold` and `exercise`, if it can be exercised early |
| `early` | 1 where exercising before expiration is worth more than keeping the option |
| `chance` | the chance of getting to the node: (its step choose `ups`) × *q*^`ups` × (1 − *q*)^downs, where *q* is the tree's chance of going up. Those of a step add up to 1 |

The first row's `value` is the option's price.

```lisp
(define tree (binomial-tree "put" 100 100 1 0.05 0.2 :steps 3))
(display-table tree)
(vector-round (table-column tree "value") 4)   ; => #(6.4996 2.1954 11.8691 0.0 4.893 20.6213 0.0 0.0 10.9053 29.2778)
(table-column tree "early")                    ; => #(0 0 0 0 0 1 0 0 0 0)
(vector-round (table-column tree "chance") 4)  ; => #(1.0 0.5438 0.4562 0.2957 0.4962 0.2081 0.1608 0.4047 0.3395 0.095)
```
After two steps down, at a price of 79.38, exercising the put pays
20.62, and keeping it is worth 18.97: it's exercised early.

#### `(binomial-probability-in-the-money type spot strike time rate vol [:dividend-yield q] [:dividends table] [:steps n])`
The chance that the option ends in the money in the tree `american-price`
uses (200 steps, unless `:steps` says): the `chance`s of the last step's
prices that are in the money, added up. It doesn't depend on whether the
option can be exercised early. Like `bsm-probability-in-the-money`, it is
a risk-neutral chance.

The tree's last step has only `steps` + 1 prices, so the chance jumps as
the strike passes each of them: it is near the formula's only to within the
chance of one of those prices, a few percent with 200 steps, and it gets
closer much more slowly than the tree's price does (a payoff changes
smoothly with the price at expiration; whether it is in the money doesn't).
With an even number of steps, one of the last prices is the stock's
price today, so for an option struck there, neither the call nor the put
is in the money at that price:

```lisp
(format "{:.4f}" (binomial-probability-in-the-money "put" 100 100 1 0.05 0.2 :steps 3))   ; => "0.4345"
(format "{:.4f}" (binomial-probability-in-the-money "call" 100 100 1 0.05 0.2))           ; => "0.5317"
(format "{:.4f}" (binomial-probability-in-the-money "call" 100 100 1 0.05 0.2 :steps 201)) ; => "0.5597"
```
(The 3-step put is in the money at the last two prices, 89.09 and 70.72:
0.3395 + 0.095 of the `chance` column above. The formula's call is
0.5596.)

### Implied volatility smiles: finding options out of line

`lib/vol_smile.lsp` fits a model of implied volatility to an option chain
from `tastytrade-option-chain`, to see which options are out of line with
the rest — which might be trading opportunities. For each option:

| | |
|---|---|
| `T` | the time to expiration in years: days / 365 |
| `F` | the forward price: the underlying's price, less the present value of any dividends before expiration, divided by the discount factor e^(−rT), for a fixed interest rate r |
| `K` | log(strike / F): how far the strike is from the forward |
| `Y` | T × implied volatility²: the total implied variance to expiration |

The implied volatilities are worked out from each option's bid, ask, and
mid with Black's formula on that same forward, rather than taken from
tastytrade, whose come from its own forward — far enough off, for BRK/B,
to put each call's implied volatility several points above the put's at
the same strike. Computing them here also gives the spread in volatility
terms (the volatility at the ask less that at the bid), the measure of
liquidity that matters for a model of volatility: a 1-cent spread on a
2-cent option is wide, and a 50-cent spread on a deep in-the-money
option can be wider still.

Only liquid options are fit: some volume today, some open interest, a bid,
and a spread no wider than `max-vol-spread` in volatility; and, unless
`:out-of-the-money-only` is `#f`, only out-of-the-money ones (calls above
the forward, puts below), since an in-the-money put's price includes
early exercise, which Black's formula leaves out. Then `Y` is fit by
least absolute deviation (`lad-regression`, so the options out of line
don't pull the fit toward themselves) to some of `T`, `sqrt(T)`, `K`,
`K*sqrt(T)`, and `K^2`. Within one expiration, `T` and `sqrt(T)` are the
same for every option, and `K*sqrt(T)` is `K` times a number, so each
expiration's fit is a parabola, `Y = a + b K + c K^2`; fit to all the
expirations at once (at least three), all five terms can be used.

#### `(fit-vol-smiles chain [:rate r :dividends table :max-vol-spread w :out-of-the-money-only flag :by-expiration flag :terms names])`
Fits the model. `:rate` (default `0.04`) is the interest rate; set it to
the current rate for the options' horizon. `:dividends` is a table of
`ex-date` and `amount` columns, as `alpha-vantage-dividends` and
`dividend-schedule` make; `'()`, none, by default. `:max-vol-spread` (default
`0.02`, 2 volatility points) is the widest spread an option can have and
be used. `:by-expiration` `#t` (the default) fits each expiration
separately, with the terms `("K" "K^2")` unless `:terms` gives others;
`#f` fits them all at once, with all five terms unless `:terms` gives
others. An expiration with fewer than twice as many options as the fit
has coefficients isn't fit. Returns a `vol-smile-fit` struct, whose
fields are:

- **`(vol-smile-fit-expirations fit)`**: a table with one row per expiration: `expiration-date`, `days`, `forward`, `parity-forward` (the forward that put-call parity implies, at the strike nearest the money — if it's far from `forward`, the rate is off, and calls will tend to look rich and puts cheap, or the other way around), `options` (how many were fit), `atm-vol` (the fit's volatility at the forward, K = 0), `intercept`, and a column for each term's coefficient.
- **`(vol-smile-fit-options fit)`**: a table of the options that were fit, with the chain's columns and `T`, `discount`, `forward`, `K`, `iv-bid`, `iv-mid`, `iv-ask`, `Y`, and what the model says about each: `fitted-iv`; `iv-residual`, `iv-mid` less `fitted-iv`; `model-price`, the option's price at `fitted-iv`; `signal`, `"rich"` if the bid is above `model-price` (it could be sold for more than the model says it's worth), `"cheap"` if the ask is below it, `""` otherwise; and `edge`, how far, in dollars per share: the bid less `model-price`, or `model-price` less the ask.
- **`(vol-smile-fit-models fit)`**: a list of `(expiration-date . model)`, for `model-report` and the other model functions.

#### `(show-vol-smiles fit [:count n])`
Shows the expirations table, the `n` (default 10) options furthest from
the fit, and every option marked rich or cheap, largest `edge` first.

#### `(plot-vol-smile fit expiration-date)`
Charts one expiration's implied volatilities against strike: at the bid,
at the ask, and the fit's.

The model uses `black-price` and `black-implied-vol`, which are built in:
see "Option prices".

```lisp
(load "vol_smile.lsp")
(define chain (tastytrade-option-chain creds "BRK/B" 4 25))
(define fit (fit-vol-smiles chain :rate 0.045))
(show-vol-smiles fit)
(plot-vol-smile fit (date 2026 11 20))

; one surface for all the expirations, with all five terms
(define surface (fit-vol-smiles chain :rate 0.045 :by-expiration #f))
(display (model-report (cdr (car (vol-smile-fit-models surface)))))
```

`examples/vol_smile_example.lsp` does all of this.

### Simulating investment prices

Paths of an investment's price, made from its own history (a block bootstrap), and started at the
market's volatility today with a volatility model, are in [lisp_paths_manual.md](lisp_paths_manual.md), Part 4.
The functions: `daily-returns`, `adjust-returns`, `dividend-schedule`, `bootstrap-path`, `bootstrap-days`,
`option-value`, `option-payoffs`, `volatility-model`, `volatility-history`, `volatility-forecast`.

### Checking option prices against simulated paths

`lib/option_check.lsp` finds the options in a chain whose prices are
furthest from what simulated paths of the underlying's price say they are
worth. `lib/vol_smile.lsp`, above, judges an option by the other options;
this judges it by the underlying's own history. It does all of it:

1. gets the option chain from tastytrade, the price history from Schwab,
   and the dividends from Alpha Vantage;
2. makes the returns, with the dividends in them, grown at the interest
   rate (see "Simulating investment prices");
3. makes a set of paths, as long as the longest option, with the last year's
   dividends supposed to go on;
4. values every option in the chain from those same paths, with
   `option-payoffs`, discounted at the interest rate; and
5. compares each option's price with its value, in volatility: the
   implied volatility of the price, `iv-mid`, and of the value, `model-iv`,
   as `vol_smile.lsp` works them out (Black's formula, on the forward that
   the dividends give).

```lisp
(load "option_check.lsp")
(define checked (check-option-prices creds "SPY" :rate 0.04))
(show-option-check checked)
```

#### `(check-option-prices creds symbol [options])`
The whole thing, for an underlying. `months` (3) is how many months ahead
to get expirations, and `strikes` (15) how many strikes nearest the price
to keep in each; its other options are `check-option-chain`'s, below. It
takes some seconds. The result is a table, with the options furthest out of
line first.

#### `(check-option-chain chain returns [options])`
The same, from a chain and returns you already have: `chain` is a table as
`tastytrade-option-chain` makes, and `returns` the underlying's table of
returns as `daily-returns` makes it, *with its dividends* if it pays any. It
is the function to use with a chain from another source, or for trying
other settings on one chain. Its options:

| Option | Default | What it does |
|---|---|---|
| `:start-date` | today | the date of the chain's prices. The time to each expiration is counted from it, in calendar days for the discounting and in trading days for the paths. (The rest of the day itself isn't counted: an option that expires today isn't checked.) |
| `:start-price` | the chain's `underlying-price` | the underlying's price at that time |
| `:rate` | 0.04 | the interest rate, continuously compounded: set it to the current one |
| `:dividends` | none | the table of the underlying's actual dividends, as `alpha-vantage-dividends` makes it, whose last year is supposed to go on (`dividend-schedule`); `'()` for none |
| `:paths` | 5000 | how many paths |
| `:block-size` | 10 | the days in a block of the history (see `bootstrap-path`: it changes the answer) |
| `:seed` | 1 | the paths' seeds are this one, and the next ones |
| `:max-vol-spread` | 0.02 | an option whose bid and ask are further apart than this in volatility isn't used |
| `:out-of-the-money-only` | `#t` | use only calls with strikes at or above the forward and puts at or below it: the paths' values leave out early exercise, which an option on a stock has, and an in-the-money option's price has more of it |
| `:min-paths-paid` | 50 | an option the paths pay something on in fewer paths than this is left out: they say too little about it |
| `:standard-errors` | 2 | a bid has to be above the value, or an ask below it, by this many standard errors of the paths' own noise to count as rich or cheap |
| `:forward-tolerance` | 0.002 | see below |
| `:match-volatility` | `#f` | `#t` multiplies the paths' volatility by the one number that makes the middle `iv-residual` 0: the market's overall level of volatility, in place of the history's (see below). The number is in the `volatility-scale` column, and `show-option-check` says it |
| `:expected-return` | none | the underlying's expected annual return, dividends included, 0.08 for 8%. It adds what each option is worth if the underlying does earn that: the last three columns below (see below) |
| `:volatility` | `#f` | `#t` fits a volatility model to the returns (`volatility-model`), or give one: the paths start at today's volatility and go back toward the history's (see "Starting paths from today's volatility"). The columns `start-volatility` and `long-run-volatility` have the two, and `show-option-check` says them |
| `:start-volatility` | the model's | with `:volatility`: the volatility the paths start at, for a year, such as the market's for the next month |
| `:early-exercise` | `#f` | `#t` allows for the right to exercise early: what it is worth (the American price less the European one, by `american-price`'s binomial tree at the option's own implied volatility) is taken off the bid, ask, and mid before they are compared with the paths' European values, and added to `model-price` after. Then in-the-money options can be checked too: give `:out-of-the-money-only #f` as well |

An option also has to be liquid, as `vol_smile.lsp` has it: traded today,
with open interest and a bid.

The result has the chain's own columns, and these:

| Column | What it holds |
|---|---|
| `iv-bid`, `iv-mid`, `iv-ask` | the implied volatility of the option's bid, mid, and ask |
| `model-price` | the option's value from the paths |
| `standard-error` | its error, from there being only so many paths |
| `paths-paid` | how many paths the option pays something on |
| `model-iv` | the implied volatility of `model-price` |
| `iv-residual` | `iv-mid` less `model-iv`: positive if the option is priced above the paths' value, negative if below. The options are in order of its distance from 0 |
| `iv-vs-expiration` | `iv-residual` less the middle (median) one of the options that expire the same day |
| `signal` | `"rich"` if the bid is above `model-price`, `"cheap"` if the ask is below it, `""` if neither |
| `edge` | how far: the bid less `model-price`, or `model-price` less the ask (0 for neither) |
| `volatility-scale` | with `:match-volatility`: the number the paths' volatility was multiplied by, the same in every row |
| `expected-value` | with `:expected-return`: the present value, at the interest rate, of what the option pays on average if the underlying earns that return |
| `favors` | with `:expected-return`: `"buying"` if `expected-value` is above the ask (by `:standard-errors` of its own error), `"selling"` if it is below the bid, `""` if neither |
| `expected-profit` | with `:expected-return`: how far: `expected-value` less the ask, or the bid less `expected-value` (0 for neither) |
| `start-volatility`, `long-run-volatility` | with `:volatility`: the volatility the paths started at, and the one they went back toward, the same in every row. With `:match-volatility`, both are scaled too (but not a `:start-volatility` that was given) |
| `early-exercise` | with `:early-exercise`: what the right to exercise early is worth. The implied volatilities are then of the prices without it, and `model-price` and `expected-value` have it in them |

#### `(show-option-check checked [:count n])`
Shows the middle `iv-residual` of each expiration, the `count` (10) options
furthest from the paths' values, the `count` furthest from the middle
`iv-residual` of their expiration, and every option that is rich or cheap;
and, with `:expected-return`, the `count` with the most `expected-profit`.
With `:match-volatility` it first says how much the volatility was scaled,
and with `:volatility`, where the paths' volatility started and what it
went back toward.

#### `(option-check-expirations checked)`
A table with a row for each expiration: its days, how many options were
checked, their middle `iv-residual`, and how many are rich and cheap.

**What "risk-neutral" means.** The paths grow at the interest rate, not at
the return the underlying is expected to earn. That is valuing as if
investors didn't charge for risk: every asset is supposed to earn the
interest rate on average, and an option is worth its discounted average
payoff. Nobody believes the stock earns the interest rate. It is a
calculation, and it works because an option can be copied. An example in one
step: a stock at 100 goes to 120 or 90, the interest rate is 5%, and a call
struck at 100 pays 20 or 0. Hold ⅔ of a share and borrow 57.14, and you owe
60 in either case, so you hold exactly what the call pays: 20 if the stock
rises, 0 if it falls. That costs 66.67 − 57.14 = 9.52, so the call must cost
9.52, whatever the chance of a rise. The probability that makes the stock
earn 5%, 100 × 1.05 = *q* × 120 + (1 − *q*) × 90, is *q* = 0.5, and
0.5 × 20 / 1.05 = 9.52 too. That *q* isn't a forecast: if the real chance of
a rise is 80%, the call still costs 9.52, though its real average payoff,
discounted, is 15.24. So the option's price depends on the stock's
volatility, not on how much it is expected to earn; and investors'
feelings about risk are in the stock's price already. Here only the drift
is changed: the paths keep the history's volatility, tails and skew, and
the market's own risk-neutral distribution also has a price for the risk of
a crash and of volatility in it, so an `iv-residual` is not all mistake in
the market's prices.

**What to make of it.** The paths know the history and nothing else, so:

- **The market's volatility is not the history's.** When the market expects
  more volatility than the history had, most of the options are rich; when
  less, most are cheap. And the difference is biggest for the options that
  expire soonest, since the history says the least about the next few days:
  it is the market's term structure of volatility, and the first table of
  `show-option-check` shows it. From the close of October 6, 2026, with SPY
  at 779.09 and the market calm:

  ```
  expiration-date  days-to-expiration  options  median-iv-residual  rich  cheap
  2026-10-07                        1       15               -8.9%     0     15
  2026-10-16                       10       15               -4.3%     0     15
  2026-11-20                       45       15               -2.6%     0     15
  2026-12-31                       86       15               -2.1%     0     15
  ```

  So the options "furthest from the paths' values" are the shortest ones,
  and say little. What is more telling is `iv-vs-expiration`: the options
  that are out of line with the rest of *their* expiration.
- **`:volatility #t` starts the paths at today's volatility.** On the
  afternoon of October 7, 2026, SPY's model put it at 9.6%, and the
  shortest options came into line. These are the middle `iv-residual`s of
  some of the expirations, without the model and with it:

  ```
  expiration-date  days-to-expiration  without  with
  2026-10-08                        1    -8.0%  -0.7%
  2026-10-09                        2    -7.0%  -0.4%
  2026-10-16                        9    -3.8%  +1.1%
  2026-10-30                       23    -3.1%  +2.1%
  2026-11-20                       44    -2.3%  +3.0%
  2026-12-31                       85    -2.0%  +2.8%
  ```

  The options one to three months out came out rich by 2 to 3 points
  instead. Part of that is what the market charges for volatility risk:
  options' implied volatility is usually above the volatility that
  follows. And part may be the model's: its paths are lopsided, and their
  volatility at the money is less than its forecast (see "The paths are
  lopsided", above).
- **The underlying's price and the options' must be from the same moment.**
  If the market is closed, the options' prices are the last close's, while
  the underlying's can be from after hours, and then calls look rich and
  puts cheap, or the other way around. So the check first sees that the
  forward from the underlying's price and the one from put-call parity
  agree for the first expiration, to `:forward-tolerance` (0.002 is 0.2%),
  and stops if they don't, saying what the underlying's price must have
  been. Give that as `:start-price` (and `:start-date`, if it was before
  today), or run it when the market is open. If the interest rate or the
  dividends are what's wrong, `:forward-tolerance` lets it go on, but the
  options are then out of line by that.
- **`:match-volatility` takes out the market's overall level.** It finds
  the number to multiply the paths' volatility by (it tries it, then
  multiplies it by the middle ratio of `iv-mid` to `model-iv`, up to 5 times
  or until that is within 0.2% of 1), so that the options left out of line
  are those out of line with the market's general level, not the history's.
  On the morning of October 7, 2026 it was 0.80 for SPY: the market was
  expecting 80% of the history's volatility, which had the crash of 2020 in
  it. One number can't remove the rest: the market's volatility rises with
  the time to expiration, and the history's doesn't, so the options that
  expire soonest come out cheap, and the ones that expire in months come
  out rich, by a point or two. The median `iv-residual` of each expiration,
  in `show-option-check`, shows it. (`:volatility` gives the paths a term
  structure of their own, and the two can be used together.)
- **`:expected-return` is not risk-neutral**, and is for a different
  question: not what an option should cost, but what it is expected to pay if
  the underlying earns that. The second paths are the first ones, with the
  same seeds and the same volatility, but growing at `:expected-return`, so
  the difference between the two values is only the growth. The result
  isn't adjusted for risk. When the expected return is above the interest
  rate, calls are expected to earn more than the interest rate and puts less:
  so calls tend to favor buying and puts selling, which is the underlying's
  risk premium (what investors are paid to bear its risk), and more for
  options that are more leveraged. A positive `expected-profit` is an
  expected value, and only worth having if you want the risk that comes with
  it.
- **Early exercise.** An option on a stock can be exercised before it
  expires, and the paths' values leave that out. It is worth little for an
  out-of-the-money option (and nothing for a call on a stock that pays no
  dividends), which is why only those are used by default. With
  `:early-exercise #t` it is worked out for each option, and in-the-money
  ones can be checked too. A put deep in the money may still be left out:
  its spread, in volatility, is wide.
- **An in-the-money option, or one the paths rarely pay on, says little**,
  which is why they're left out unless asked for.
- **Noise.** `standard-error` is the paths' own, and it makes a
  difference of about two standard errors the least that means anything.
  More `:paths` make it smaller (four times as many, half), but not the
  history's differences from the future.

### Valuing options three ways

`lib/option_methods.lsp` values the options listed on a stock three ways
-- Black-Scholes (`bsm-price`), a binomial tree (`american-price`), and
Monte Carlo paths copied from the stock's own history (`bootstrap-path`
and `option-payoffs`) -- next to the market's bids and asks, with the
chance each ends in the money by each (`bsm-probability-in-the-money`,
`binomial-probability-in-the-money`, and how many of the paths do). All
three use the history's volatility, count time in trading days, and grow
the price at the interest rate, so the differences between them are the
models' own: see "Paths with blocks of a day agree with Black-Scholes only
over long times", under `option-value`. The library's own comment says
more.

```lisp
(load "option_methods.lsp")
(define compared (option-methods creds "BRK/B"))       ; while the market is open
(show-option-methods compared)
(option-values-options compared)                        ; the table, to filter, sort, or chart
```

`examples/option_methods_example.lsp` does this for the symbol it's given
on the command line: `python3 ../lisp_interpreter.py
option_methods_example.lsp KO`.

#### `(option-methods creds symbol [options])`
Gets a stock's option chain (from tastytrade), its prices (from Schwab),
and its dividends (from Alpha Vantage), and values its liquid options three
ways. `:months` (3) is how many months ahead to look for expirations, and
`:strikes` (10) how many strikes nearest the price to keep in each; the
other options are `option-methods-for-chain`'s. If the market is closed,
it says so: the bids and asks are then the last close's, and the stock's
price may be from later.

#### `(option-methods-for-chain chain returns [options])`
The same, from a chain and returns you already have: `chain` as
`tastytrade-option-chain` makes it, and `returns` the stock's, as
`daily-returns` makes them (with its dividends, if it pays any). The
result is an `option-values` struct, with the slots `symbol`, `price` (the
stock's), `volatility` (the history's, for a year), `rate`, `paths`, and
`options`, a table with a row for each option compared. Its options:

| Option | Default | What it does |
|---|---|---|
| `:symbol` | `""` | the stock's, for `show-option-methods` to show |
| `:dividends` | none | the stock's actual dividends, as `alpha-vantage-dividends` makes them; the last year's are supposed to go on (`dividend-schedule`) |
| `:start-date` | today | the date of the chain's prices: the trading days to each expiration are counted from it (not counting it) |
| `:rate` | 0.04 | the interest rate, continuously compounded |
| `:max-vol-spread` | 0.02 | an option whose bid and ask are further apart than this, in volatility, isn't compared |
| `:paths` | 20000 | how many paths |
| `:seed` | 1000 | the paths' seeds are this one and the next ones |

The options compared are the liquid ones out of the money: traded today,
with open interest and a bid, a spread no wider than `:max-vol-spread`,
and calls struck at or above the stock's price and puts at or below it
(early exercise is worth little for those, and the formula and the paths
leave it out). The `options` table's columns:

| Column | What it holds |
|---|---|
| `expiration-date`, `type`, `strike`, `bid`, `ask` | the option's, from the chain |
| `days` | the trading days to expiration |
| `black-scholes`, `tree`, `monte-carlo` | each method's value. The tree allows for early exercise, as the listed options do |
| `mc-error` | the standard error of `monte-carlo` |
| `market-vol` | the volatility of the option's mid, by the formula |
| `bs-probability`, `tree-probability` | the formula's and the tree's chance that the option ends in the money |
| `paths-in-the-money`, `paths-probability` | how many of the paths it ends in the money on, and what share of them |

#### `(show-option-methods compared)`
Shows the stock's price and volatility, each option's value by each method
next to its bid and ask, the chance that each ends in the money by each,
the market's volatility (the middle of the options' `market-vol`), and
`option-methods-summary`.

#### `(option-methods-summary compared)`
A table with a row for each method, and how many of the options its value
is between the bid and the ask for, below the bid for (the market prices
the option higher), and above the ask for (the market prices it lower).

### Call spreads

(In `lib/call_spreads.lsp`; its functions work without loading it.) Of a
stock's calls that expire on one day, which pair is the best to **buy the
one with the lower strike, and sell the one with the higher** -- a *bull
call spread* -- if you expect the stock to be at a certain price on that
day? Every pair is ranked by the profit at the price you expect, as a share
of the most you could lose. (This is the first and simplest of seventeen kinds
of position that [Option spreads](#option-spreads) ranks the same way; the work
is done there, and these functions are its `bull-call` kind under their
original names, which stay as they were.)

**What a spread is.** A call lets you buy the stock at its strike on the
expiration day, so at expiration it is worth the stock's price less the
strike, or nothing, if that's less. Buying the call at the lower strike
`K1` and selling the one at the higher `K2` costs less than the first alone,
and gives up what the stock gains beyond `K2`. With the stock at `S` on the
expiration day, the pair is worth

```
(S - K1, or 0)  -  (S - K2, or 0)
```

which is 0 for `S` at or below `K1`, rises dollar for dollar with the stock
from there, and stops at `K2 - K1` for `S` at or above `K2`. What you pay is
the spread's **cost**, or net debit: the price of the call you buy, less the
price you get for the call you sell. The **most you can lose** is the cost,
if the stock ends at `K1` or below and both calls expire worthless. At the
price you expect, the **profit** is what the spread is worth there, less the
cost, and the **ratio** is

```
profit  /  the most you can lose
```

For example, with the stock at 108 on the day, and calls whose bids and asks
are 6.0 and 6.2 at 100, 3.0 and 3.2 at 105, and 1.2 and 1.4 at 110: buying the
100 and selling the 110 costs 6.2 - 1.2 = 5.0; it is worth 8 at 108, a profit
of 3.0, a ratio of 0.6 -- 60% of the most you can lose; buying the 100 and
selling the 105 costs 3.2, is worth 5, a profit of 1.8, a ratio of 0.5625; and
the 105 and 110 cost 2.0, are worth 3, a profit of 1.0, a ratio of 0.5. The
first is the best.

```lisp
(define day (date 2026 11 20))
(define chain (make-table "symbol" (vector "XYZ   261120C00100000" "XYZ   261120C00105000" "XYZ   261120C00110000")
                          "type" (vector "Call" "Call" "Call")
                          "strike" (vector 100.0 105.0 110.0)
                          "expiration-date" (vector day day day)
                          "underlying" (vector "XYZ" "XYZ" "XYZ") "underlying-price" (vector 104.0 104.0 104.0)
                          "bid" (vector 6.0 3.0 1.2) "ask" (vector 6.2 3.2 1.4) "mid" (vector 6.1 3.1 1.3)
                          "volume" (vector 5 5 5) "open-interest" (vector 10 10 10)))
(define search (call-spreads-for-chain chain day 108))
(table-column (spread-search-spreads search) "ratio")      ; => #(0.6 0.5625001 0.5)
(table-column (spread-search-spreads search) "cost")       ; => #(5.0 3.1999998 2.0)
```

#### `(call-spreads creds symbol expiration expected-price [:prices p :min-open-interest n :min-volume n :min-cost c])`
Gets the stock's calls that expire on `expiration` (a date, or
`"YYYY-MM-DD"`) from Schwab (`schwab-option-chain`) -- live bids and asks
while the market is open; it says so, and the quotes are the last close's, if
it is closed -- and ranks every pair: see `call-spreads-for-chain`. Returns a
`spread-search`.

#### `(call-spreads-for-chain chain expiration expected-price [:prices p :min-open-interest n :min-volume n :min-cost c :underlying u :contract-size n :unit w])`
The same for a chain you already have: a table as `schwab-option-chain` or
`tastytrade-option-chain` makes (`:underlying`, `:contract-size`, and `:unit`
are for a future's options, as in `option-spreads-for-chain`). Returns a
`spread-search`, whose accessors
are `spread-search-stock`, `-stock-price`, `-expiration`, `-expected-price`,
`-prices`, `-contract-size`, `-unit`, and `-spreads`: the table of spreads, a
row for each pair, the best first, with the columns

| Column | What it holds (prices are for a share) |
|---|---|
| `long-symbol`, `short-symbol` | the options bought and sold |
| `long-strike`, `short-strike` | their strikes |
| `long-price`, `short-price` | what is paid for the first, and got for the second |
| `cost` | the net: the most that can be lost |
| `worth` | what the spread is worth at `expected-price` on the day |
| `profit` | `worth` less `cost` |
| `ratio` | `profit` as a share of `cost`: 1.5 is 150% |
| `breakeven` | the stock's price at which the spread is worth its cost |
| `max-profit` | the most that can be made: the strikes' difference less `cost` |

The options:

- `:prices` is `'bid-ask` (the default: you buy at the ask and sell at the
  bid, so the cost is the ask of the call bought less the bid of the call
  sold) or `'mid` (the middle of each's bid and ask, which is what you'd
  pay if you could trade in the middle). Be careful with `'mid`: thin
  options have wide, ragged quotes, and their middles can make a pair look
  far cheaper than it can be traded. (On SPY, after the close, two deep
  in-the-money calls with open interest of 4 and 8 had middles only 0.38
  apart for strikes a dollar apart, so a spread worth 1.00 at expiration
  "cost" 0.38 and came out the best of all; at their asks and bids it is
  nowhere near.) A higher `:min-open-interest` guards against these.
- Both calls of a spread must have a bid and an ask above 0, and open
  interest (the contracts open) of at least `:min-open-interest` (1), and
  volume of at least `:min-volume` (1: the option has traded at least once
  today). A count the chain doesn't have is taken to be 0. Volume is the
  trades so far today, so it is 0 for every option before the market opens
  (and the search finds nothing, and says why): give `:min-volume 0` then.
- A pair that would pay you to buy it, or costs a tenth of a cent or less --
  from quotes that don't agree -- has no most you can lose to divide by, and
  is left out; so is one that costs less than `:min-cost` (0).

**The ratio favors cheap spreads.** A spread that costs a few cents has a
huge ratio if the stock gets to the higher strike, but there is almost no
chance it does: the price you expect is one price, and the stock can end
anywhere. The ratio ignores how likely things are, commissions, and that the
call you sold can be exercised before expiration (usually just before an
ex-dividend date, if it is in the money). `:min-cost` leaves out the very
cheap; looking at the next few spreads, not only the first, shows how the
ratio falls off.

#### `(show-call-spreads search [:count n])`
Shows the best spread in words -- what to buy and sell, what it costs for a
share and for a contract of 100, what it makes at the expected price, where it
breaks even, and the most it can make -- and a table of it and the next
`:count` (10) best.

#### `(plot-call-spreads search [:rows rows :low l :high h :points n])`
Charts the profit of one of the spreads -- the best, unless `:rows` (a list of row
numbers) says -- on the expiration day, against the price the stock might have then. It is
flat at a loss of the spread's cost with the stock at the lower strike or less, rises
dollar for dollar between the strikes, and is flat at a gain of the strikes' difference
less the cost at the higher strike or more; it crosses 0 at the breakeven. It is
`plot-option-profit`'s chart (see "Option spreads"), whose options these are, of the
bull call spread. `save-chart` saves it.

#### `(call-spread-order search [:row r :contracts c :price p])`
An order for one of the spreads, as a hash table in Schwab's form, made by
`schwab-spread-order`: buy the call with the lower strike, sell the one with
the higher, `:contracts` (1) of each, with a limit on the net debit of `:price`
-- the spread's `cost`, unless it is given. `:row` picks the spread: 0, the
best, is the default; 1 the next; and so on. **It sends nothing.** With bids
and asks, the order at the cost is likely to fill at once: it pays what is
asked for the call bought, and takes what is bid for the call sold. A lower
`:price` may fill at a better price, or not at all.

#### `(show-spread-order order)`
Says in words what a spread order -- as `call-spread-order` or
`schwab-spread-order` makes it -- would do: a day order to open so many
spreads, with a limit on the net debit of so much a share (so much for each,
and in all, at most), and the two options it buys and sells. Read it before
previewing or placing the order. It sends nothing. It also reads the orders
of the other kinds of spread: see [Option spreads](#option-spreads).

To trade it, look at it, preview it (which places nothing), and then place
it:

```lisp
(define search (call-spreads creds "SPY" (date 2026 11 20) 765))
(show-call-spreads search)
(define order (call-spread-order search :contracts 2))
(show-spread-order order)                                        ; the order, in words
(schwab-preview-order creds "Brokerage" order)                   ; what Schwab makes of it
; (schwab-place-order creds "Brokerage" order :confirm #t)       ; places it, for real
```

`examples/call_spread_example.lsp` does the first two lines for a stock, a
day, and a price from the command line: `python3 ../lisp_interpreter.py
call_spread_example.lsp SPY 2026-11-20 765`.

The reading of Schwab's chain was checked against its real answer (see
`schwab-option-chain`), and Schwab's preview accepted the spread order for a
SPY call spread (see `schwab-spread-order`). Even so, look at
`schwab-preview-order`'s answer for yours -- the commission and fees (here,
65 cents for each option, and a few cents in fees), and any warnings --
before placing anything.

### Option spreads

(In `lib/option_spreads.lsp` and `lib/option_positions.lsp`; their functions
work without loading them.) The question of "Call spreads" for seventeen
kinds of position: of a stock's options (or a future's: see "Options on
futures") that expire on one day, which spread,
single option, or position with shares of one kind is the best, if you
expect the stock to be at a certain price on that day? Every position that
can be made is ranked by the profit at the price you expect, as a share of the
most you could lose -- the **ratio** -- you can prepare the orders for the
best, and you can set the best of every kind side by side, with simply owning
the stock among them, to see what the options do for you.

**The kinds.** `(option-spread-kinds)` is a table of them. A position is some
options bought and some sold, and sometimes shares, all of one stock and
expiration. In the table, the strikes rise from the first leg to the last:

| Kind | Legs | Usually | It does well if the stock... |
|---|---|---|---|
| `bull-call` | buy a call, sell a higher one | costs you | rises |
| `bear-call` | sell a call, buy a higher one | pays you | stays below the strike sold |
| `bull-put` | buy a put, sell a higher one | pays you | stays above the strike sold |
| `bear-put` | sell a put, buy a higher one | costs you | falls |
| `call-butterfly` | buy a call, sell two at the middle strike, buy a call (the strikes equally far apart) | costs you | ends at the middle strike |
| `put-butterfly` | the same with puts | costs you | ends at the middle strike |
| `iron-condor` | buy a put, sell a higher put, sell a call above it, buy a higher call (the two wings the same width) | pays you | ends between the strikes sold |
| `iron-butterfly` | an iron condor whose put and call sold have one strike | pays you | ends at that strike |
| `long-straddle` | buy a call and a put at one strike | costs you | goes far, either way |
| `long-strangle` | buy a put, and a call at a higher strike | costs you | goes far, either way |
| `long-call` | buy a call | costs you | rises a lot |
| `long-put` | buy a put | costs you | falls a lot |
| `cash-secured-put` | sell a put, keeping the cash to buy the shares at its strike | pays you | stays above the strike (or you buy the shares there) |
| `long-stock` | buy 100 shares, and no options | costs you | rises |
| `covered-call` | buy shares, sell a call on them | costs you the shares, less the call | rises a little, or stays |
| `protective-put` | buy shares, buy a put on them | costs you the shares, and the put | rises (the put makes up a fall) |
| `collar` | buy shares, buy a put below the stock, sell a call above it | costs you the shares, and a little more or less | stays between the strikes |

The spreads that pay you (that have a *credit*: more is got for the options
sold than paid for those bought) make the most they can when they are opened,
and can lose the rest of their width; the ones that cost you (a *debit*) can
lose what they cost. A call sold alone, a short straddle or strangle, which
can lose without limit, spreads of several expirations (calendars, diagonals),
and those with uneven numbers of options (ratio spreads) are not here.

**Shares.** The kinds with shares have one for each share of each option: an
option contract is for 100 shares, so a covered call is 100 shares and one
call, and the numbers, here as everywhere, are for a share. They are bought at
the stock's price in the chain (`:stock-price` says another, such as the ask),
are worth the stock's price on the day, and are in the cost: a covered call
costs the shares' price less the call's. A stock can fall to 0, so shares can
lose all they cost, less what their options make up for. These kinds are for
stocks and ETFs, and for futures (see "Options on futures"), not for an index
such as SPX, which has nothing to buy. A
cash-secured put is a put sold with the cash to buy the shares at its strike
held back, so that it cannot lose without limit (the stock can only fall to 0);
that cash is your broker's to hold, and the ratio, like the others, is over the
most that can be lost, not over the money put up.

**The numbers.** With the stock at `S` on the day, an option is worth its
intrinsic value: a call `S` less its strike, or 0; a put its strike less `S`,
or 0. The position is **worth** the sum of its options' values, the ones bought
counted plus and the ones sold minus (a sold option is owed), and `S` for each
share. Its **cost** is what is paid for the ones bought (at their asks) and for
the shares, less what is got for the ones sold (at their bids), or at their
middles with `:prices 'mid`; a credit is a cost below 0. The **profit** is the
worth less the cost. As `S` changes, the profit is a line that bends only at the
strikes, so its extremes are at `S = 0` or at a strike (or it keeps rising
without limit: a straddle, a strangle, a long call, or shares with no call sold
against them, whose **max-profit** is missing). That is how the **max-loss** and
**max-profit** are found, exactly, and the **breakevens**, the prices where the
profit crosses 0, a line at a time. The ratio is the profit at the price you
expect over the max-loss.

For example, with the stock at 108 on the day, calls with bids and asks of 6.0
and 6.2 at 100, 3.0 and 3.2 at 105, 1.2 and 1.4 at 110, and 0.3 and 0.5 at
115, and puts with 1.4 and 1.6, 3.7 and 3.9, 6.8 and 7.0, and 11.0 and 11.2:
the iron condor that buys the 100 put at 1.6, sells the 105 put at 3.7, sells
the 110 call at 1.2, and buys the 115 call at 0.5 gets a credit of
3.7 + 1.2 - 1.6 - 0.5 = 2.8. At 108 everything expires worthless, so it
keeps the 2.8. It can lose the width of a wing less the credit, 5 - 2.8 =
2.2, if the stock ends at 100 or below or at 115 or above, and it breaks even
at 105 - 2.8 = 102.2 and at 110 + 2.8 = 112.8. The ratio is 2.8 / 2.2.

```lisp
(define day (date 2026 11 20))
(define chain (make-table "symbol" (vector "XYZ   261120C00100000" "XYZ   261120C00105000" "XYZ   261120C00110000" "XYZ   261120C00115000"
                                            "XYZ   261120P00100000" "XYZ   261120P00105000" "XYZ   261120P00110000" "XYZ   261120P00115000")
                          "type" (vector "Call" "Call" "Call" "Call" "Put" "Put" "Put" "Put")
                          "strike" (vector 100.0 105.0 110.0 115.0 100.0 105.0 110.0 115.0)
                          "expiration-date" (vector day day day day day day day day)
                          "underlying" (vector "XYZ" "XYZ" "XYZ" "XYZ" "XYZ" "XYZ" "XYZ" "XYZ")
                          "underlying-price" (vector 104.0 104.0 104.0 104.0 104.0 104.0 104.0 104.0)
                          "bid" (vector 6.0 3.0 1.2 0.3 1.4 3.7 6.8 11.0)
                          "ask" (vector 6.2 3.2 1.4 0.5 1.6 3.9 7.0 11.2)
                          "mid" (vector 6.1 3.1 1.3 0.4 1.5 3.8 6.9 11.1)
                          "volume" (vector 5 5 5 5 5 5 5 5) "open-interest" (vector 10 10 10 10 10 10 10 10)))
(define condors (option-spreads-for-chain chain 'iron-condor day 108))
(table-column (spread-search-spreads condors) "cost")          ; => #(-2.8000002)
(table-column (spread-search-spreads condors) "max-loss")      ; => #(2.1999998)
(table-column (spread-search-spreads condors) "ratio")         ; => #(1.2727275)
(table-column (spread-search-spreads condors) "breakeven-1")   ; => #(102.2)
(table-column (spread-search-spreads condors) "breakeven-2")   ; => #(112.8)
(define strangles (option-spreads-for-chain chain 'long-strangle day 108))
(table-column (spread-search-spreads strangles) "max-profit")  ; => #(nan nan nan nan nan nan)
(define covered (option-spreads-for-chain chain 'covered-call day 108))
(table-column (spread-search-spreads covered) "strike-1")      ; => #(110.0 115.0 105.0 100.0)
(table-column (spread-search-spreads covered) "cost")          ; => #(102.8 103.7 101.0 98.0)
(define owning (option-spreads-for-chain chain 'long-stock day 108))
(table-column (spread-search-spreads owning) "cost")           ; => #(104.0)
(table-column (spread-search-spreads owning) "ratio")          ; => #(0.03846154)
(define curve (option-profit-curve condors))                   ; the condor's profit at each price, to chart
(vector-ref (table-column curve "profit") 0)                   ; => -2.1999998
(vector-max (table-column curve "profit"))                     ; => 2.8000002
(vector-length (table-column curve "price"))                   ; => 206
```

With shares the same chain gives a covered call that buys a share at 104 and
sells the 110 call at 1.2: it costs 104 - 1.2 = 102.8, and at 108 the share is
worth 108 and the call nothing, a profit of 5.2, a ratio of 5.2 / 102.8, or
5.1%. The most it can make is 110 - 102.8 = 7.2, with the stock at 110 or more
(the call takes the rest); the most it can lose is all 102.8, if the stock
falls to 0; it breaks even at 102.8. Owning the stock alone (`long-stock`)
costs 104, makes 4 at 108, and can lose all 104: a ratio of 4 / 104, or
3.8%. Every search says how that compares.

#### `(option-spread-kinds)`
A table of the kinds: `kind` (the name to give the functions below), `label`,
`legs` (in words, lowest strike first, with the shares first), `schwab` (how
it is ordered: the name Schwab gives the kind of order; or `a plain order`, for
a single option or the long stock; or `an order for each part`, for shares with
options), and `about`.

#### `(option-spreads creds symbol kind expiration expected-price [:prices p :min-open-interest n :min-volume n :min-risk r :max-width w :stock-price s])`
Gets the stock's options that expire on `expiration` (a date, or
`"YYYY-MM-DD"`) from Schwab (`schwab-option-chain`) -- the calls, or the puts,
or both, as the kind needs (the calls, for the long stock, which needs none:
the chain says the stock's price) -- live bids and asks while the market is
open; it says so, and the quotes are the last close's, if it is closed -- and
ranks every position of the `kind`: see `option-spreads-for-chain`. Returns a
`spread-search`.

#### `(option-spreads-for-chain chain kind expiration expected-price [:prices p :min-open-interest n :min-volume n :min-risk r :max-width w :stock-price s :underlying u :contract-size n :unit w])`
The same for a chain you already have: a table as `schwab-option-chain` or
`tastytrade-option-chain` makes. Returns a `spread-search`, whose accessors
are `spread-search-kind`, `-stock`, `-stock-price`, `-expiration`,
`-expected-price`, `-prices`, `-contract-size`, `-unit`, and `-spreads`: the
table of positions, a row for each, the best first. For a position of *n* options (its legs, lowest strike
first; none, for the long stock) the columns are:

| Column | What it holds (prices are for a share) |
|---|---|
| `symbol-1` ... `symbol-n` | the options (the kind's legs say which are bought and which sold) |
| `strike-1` ... `strike-n` | their strikes |
| `price-1` ... `price-n` | the ask of each one bought, the bid of each one sold |
| `cost` | the net, with the shares if there are any: negative if the position pays you (a credit) |
| `max-loss` | the most that can be lost |
| `max-profit` | the most that can be made; missing if there is no limit |
| `worth` | what the position is worth at `expected-price` on the day |
| `profit` | `worth` less `cost` |
| `ratio` | `profit` as a share of `max-loss`: 1.5 is 150% |
| `breakeven-1`, `breakeven-2` | the stock's prices at which the position breaks even: the lower, and the higher if there are two; missing if there is none |

The options:

- `:prices` is `'bid-ask` (the default) or `'mid`; see "Call spreads" for why
  to be careful with the middles of thin options. (The shares are bought at
  the stock's price either way.)
- `:stock-price` is the price a share is bought at, for the kinds with shares:
  the chain's own price for the stock (its last trade), unless it is given --
  the ask, say, which is a cent or so more. A chain without the stock's price
  (tastytrade's may lack it) needs it for those kinds; the others don't.
- All the options of a spread must have a bid and an ask above 0, and open
  interest of at least `:min-open-interest` (1), and volume of at least
  `:min-volume` (1: the option has traded at least once today -- 0 for every
  option before the market opens, when you give `:min-volume 0`). A count the
  chain doesn't have is taken to be 0.
- All the options of a spread are of one *root*: a stock's own options, or its
  weeklies, or its minis. (SPX's options and SPXW's have the same strikes and
  expirations, and are not the same contract.) A future's options have the
  future and the kind of option on it for a root, `./CLZ6 LOZ6` for the monthly
  options on December crude oil. They are also all of one *underlying*; see
  `:underlying`, next.
- `:underlying`, `:contract-size`, and `:unit` are for a future's options; see
  "Options on futures", below. `:underlying` names the future (`"CLZ6"`), if the
  options that expire on the day are on more than one. `:contract-size` is how
  many of the underlying's units a contract covers (1000, for crude oil), the
  default being a stock's, 100, and `:unit` what to call one (`"barrel"`; the
  default, `"share"`). The search records them, and every "for a share" here
  is for one unit.
- A position that can lose nothing -- a credit as big as a spread's width, or
  a collar whose put is worth more than the stock and the collar cost, from
  quotes that don't agree -- is left out, as is one that can lose a tenth of a
  cent or less (the rounding of the numbers) or less than `:min-risk` (0).
- `:max-width` (in dollars) leaves out the spreads that are wider: a
  vertical spread whose strikes are farther apart, a butterfly or a condor
  whose wings are, a strangle or a collar whose strikes are. (A single option
  has no width.) It also makes the search of a big chain quicker.
- A kind that needs puts, or calls, when the chain has none that expire on
  `expiration`, is an error that says on which days it has them.

**What the ratio leaves out.** The ratio favors the positions that can lose
little: they make a lot for each dollar at risk if the stock gets where they
pay, and there is almost no chance it does. The price you expect is one price,
and the stock can end anywhere -- and the best butterfly or condor for a price
you expect to the penny is the most fragile of all. The ratio also ignores
commissions, margin (a position with an option sold needs some of your money
held back, and your broker's approval), the dividends that shares pay, and
that an option you sold can be exercised before expiration (usually to collect
a dividend). `:min-risk` leaves out the spreads that can lose very
little, and looking at the next few spreads, not only the first, shows how the
ratio falls off.

#### `(show-option-spreads search [:count n])`
Shows the best position in words -- what to buy and sell, what it costs, or
pays you, for a share and for a contract of 100 (and the 100 shares), what it
makes at the expected price, where it breaks even, and the most it can make --
how owning the stock instead would do (not for the long stock itself), and a
table of it and the next `:count` (10) best, and how to go on to the order (for
a stock's options: for a future's it says there are none). For a future's
options it says it with the search's `:contract-size` and `:unit`: a barrel for
a share, 1,000 for the 100.
For the condor above, up to its table:

```
XYZ is at 104.00. Iron condors expiring 2026-11-20, if it is at 108.00 then; bought and sold at the ask and bid prices. 1 spread.

The best: buy 1 100.00 put at 1.60, sell 1 105.00 put at 3.70, sell 1 110.00 call at 1.20, buy 1 115.00 call at 0.50.
  It pays you 2.80 a share: 280.00 for one contract of each option. The most you can lose is 2.20 a share (220.00).
  With XYZ at 108.00 on 2026-11-20, it is worth 0.00 a share, a profit of 2.80 (280.00): 127% of the most you can lose.
  The most it can make is 2.80 a share (280.00). It breaks even with XYZ at 102.20 and at 112.80.
  For comparison, owning the stock instead (100 shares at 104.00): a profit of 4.00 a share (400.00) with XYZ at 108.00, 3.8% of the 104.00 a share they could lose.
```

#### `(option-spread-order search [:row r :contracts c :price p :strategy s])`
An order for one of the positions, as a hash table in Schwab's form. For a
spread of several options (every kind but the single options and those with
shares) it is made by `schwab-multi-leg-order`: the options bought
(`BUY_TO_OPEN`) and sold (`SELL_TO_OPEN`), `:contracts` (1) of each -- two
times that for the middle of a butterfly -- as one order that fills all
together or not at all, with a limit on the net debit (`NET_DEBIT`) of
`:price`, or on the net credit (`NET_CREDIT`), if the spread pays you. The
price is the spread's `cost`, unless it is given. For a single option (a long
call or put, a cash-secured put) it is a plain limit order, made by
`schwab-order`, to buy or sell it to open `:contracts` of it at `:price`, the
price in the row unless it is given; and for the long stock a plain limit
order to buy 100 shares for each contract. `:row` picks the position: 0, the
best, is the default; 1 the next; and so on. `:strategy` is the name Schwab
gives the kind of spread order, which by default is the kind's own (the
`schwab` column of `(option-spread-kinds)`); a single order has none.
**It sends nothing.** With bids and asks, the order at the cost is likely to
fill at once; a better `:price` may fill at a better price, or not at all. The
orders are for a stock's options, Schwab's, whose symbols are OCC's and whose
contract is 100 shares: a search of a future's options, or of any other
`:contract-size`, is an error that says so.

#### `(option-position-orders search [:row r :contracts c])`
The orders for one of the positions, as a list, to preview and place one after
another. A spread, a single option, or the long stock is the one order
`option-spread-order` makes. A position with shares and options -- a covered
call, a protective put, a collar -- is **an order for each part**: the shares
first (a limit order for 100 to a contract, at the stock's price), then each
option (a limit order to buy it or to sell it, at its price in the row). They
are not one order, because Schwab's form for shares with options is not one
this has been able to check, and each of these is a plain order of a form
`schwab-order` makes. So place them in order, and let the shares fill first: a
call sold against shares you don't hold yet is a call sold naked, which your
broker may refuse. Because they are separate, the shares may be bought and an
option not fill. It sends nothing. (A future's options are refused, as above.)

#### `(show-spread-order order)`
Says in words what any of these orders would do: a day order to open so many
spreads (or butterflies, iron condors, straddles, strangles), with a limit on
the net debit or credit of so much a share (so much for each, and in all, at
most to pay or at least to get), and the options it buys and sells; or, for a
plain limit order, the limit a share and the most to pay or the least to get in
all, and what it buys or sells. Given a list of orders, as
`option-position-orders` makes, it says each in turn, numbered, in the order to
send them. Read it before previewing or placing an order. It sends nothing.

```lisp
(define search (option-spreads creds "SPY" 'iron-condor (date 2026 11 20) 765))
(show-option-spreads search)
(define order (option-spread-order search :contracts 2))
(show-spread-order order)                                        ; the order, in words
(schwab-preview-order creds "Brokerage" order)                   ; what Schwab makes of it
; (schwab-place-order creds "Brokerage" order :confirm #t)       ; places it, for real
```

`examples/option_spreads_example.lsp` does the first two lines for a stock, a
kind, a day, and a price from the command line: `python3 ../lisp_interpreter.py
option_spreads_example.lsp SPY iron-condor 2026-11-20 765`.

For a covered call, or any position with shares and options, the orders are a
list:

```lisp
(define search (option-spreads creds "SPY" 'covered-call (date 2026 11 20) 765))
(show-option-spreads search)
(define orders (option-position-orders search :contracts 2))     ; the shares, then the call
(show-spread-order orders)                                        ; the orders, in words
(dolist (order orders) (schwab-preview-order creds "Brokerage" order))   ; places nothing
; (schwab-place-order creds "Brokerage" (first orders) :confirm #t)     ; places the shares, for real
```

For two contracts of the best covered call of the chain above, the orders read:

```
These 2 orders have not been sent. If they were, you would send them in this order, each one filled before the next:

1. a day order with a limit of 104.00 a share (20,800.00 in all, at most):
  BUY           200 x XYZ

2. a day order with a limit of 1.20 a share (240.00 in all, at least):
  SELL_TO_OPEN  2 x XYZ   261120C00110000
```

#### Options on futures

The same functions rank a future's options. `tastytrade-option-chain` makes
the chain -- crude oil's, with `(tastytrade-option-chain creds "CL" 2 12)` --
with the columns they need: the options' bids, asks, volume, and open interest,
and the future's price. Three things are not as they are for a stock, and the
functions take a keyword for each.

- **Which future.** Each delivery month is a future with a price of its own, and
  an option is on one of them -- one that goes on trading for some days after the
  option has expired. Crude oil's options that expire in the middle of November
  are on the December future (as are its weeklies from the middle of October on).
  What an option is worth on its expiration day is set by *that future's* price
  that day. So the price you expect, `expected-price`, is that future's price on
  the expiration day: not the price of oil, nor the front month's future's (which
  can be dollars away, when the months are priced apart), nor what the future
  will be at delivery. The search takes the underlying's name and price from the
  options it is of. If the options that expire on one day are on more than one
  future, it is an error that says which, with their prices;
  `:underlying "CLZ6"` chooses one, and the search is of that future's options
  alone. (A chain of stock's options has just the one underlying, and never
  needs it.)
- **How much a contract is.** A contract of crude oil's options is for 1,000
  barrels, not 100 shares. `:contract-size` says how many of the underlying's
  units, and `:unit` what to call one, so that what is said of a contract is in
  its dollars (the price times `:contract-size`) and in its words: `a barrel`,
  `1,000 barrels`, and the `profit, for a barrel` on a chart's axis. Some of the
  usual ones (check the exchange's specifications for the contract you trade):

  | Future | `:contract-size` | `:unit` |
  |---|---|---|
  | crude oil, `CL` | 1000 | `"barrel"` |
  | natural gas, `NG` | 10000 | `"MMBtu"` |
  | gold, `GC` | 100 | `"ounce"` |
  | silver, `SI` | 5000 | `"ounce"` |
  | corn, `ZC` | 50 (prices are in cents: a cent is $50 of 5,000 bushels) | `"bushel"` |

  For corn the words that count the units of the kinds with shares say 50
  bushels where the contract is 5,000, and its prices are in cents: the
  dollars are right. The displays show prices to the cent, so natural gas's,
  quoted to a tenth of a cent, are rounded there; the tables hold them exactly.
- **The future is not paid for.** In the kinds with shares the shares are the
  future, bought: its profit is the same as that of shares bought at its price,
  but you put up only margin, a part of the price, for it. The cost and the most
  to lose count all of its price, as they do for shares, so the ratio of these
  kinds (`long-stock`, `covered-call`, `protective-put`, `collar`) is for each
  dollar of that, not of the margin. The kinds of options alone have nothing of
  the sort to count.

The orders are Schwab's, for a stock's options; for a future's they are not made
(an error says so), and the displays leave out how to order. Analysis only:
`tastytrade-option-chain` and the functions here only read.

```lisp
(define day (date 2026 11 20))
(define crude
  (make-table "symbol" (vector "./CLZ6 LOZ6  261120C94" "./CLZ6 LOZ6  261120C96" "./CLZ6 LOZ6  261120C98"
                               "./CLZ6 LOZ6  261120P94" "./CLZ6 LOZ6  261120P96" "./CLZ6 LOZ6  261120P98"
                               "./CLX6 LOX6  261120C96" "./CLX6 LOX6  261120P96")
              "type" (vector "Call" "Call" "Call" "Put" "Put" "Put" "Call" "Put")
              "strike" (vector 94.0 96.0 98.0 94.0 96.0 98.0 96.0 96.0)
              "expiration-date" (vector day day day day day day day day)
              "underlying" (vector "CLZ6" "CLZ6" "CLZ6" "CLZ6" "CLZ6" "CLZ6" "CLX6" "CLX6")
              "underlying-price" (vector 96.0 96.0 96.0 96.0 96.0 96.0 97.5 97.5)
              "bid" (vector 2.9 1.9 1.0 0.8 1.7 3.0 3.2 1.4)
              "ask" (vector 3.1 2.1 1.2 1.0 1.9 3.2 3.4 1.6)
              "mid" (vector 3.0 2.0 1.1 0.9 1.8 3.1 3.3 1.5)
              "volume" (vector 5 5 5 5 5 5 5 5) "open-interest" (vector 10 10 10 10 10 10 10 10)))
; (option-spreads-for-chain crude 'bull-call day 99.0)   is an error: the options expiring on 2026-11-20 are on more
; than one underlying: CLX6 at 97.5, CLZ6 at 96.0. Say which one, with :underlying
(define spreads (option-spreads-for-chain crude 'bull-call day 99.0
                                          :underlying "CLZ6" :contract-size 1000 :unit "barrel"))
(spread-search-stock spreads)                                   ; => "CLZ6"
(table-column (spread-search-spreads spreads) "strike-1")       ; => #(94.0 96.0 94.0)
(table-column (spread-search-spreads spreads) "strike-2")       ; => #(98.0 98.0 96.0)
(table-column (spread-search-spreads spreads) "cost")           ; => #(2.1 1.0999999 1.1999999)
(table-column (spread-search-spreads spreads) "ratio")          ; => #(0.90476197 0.818182 0.66666675)
(define covered (option-spreads-for-chain crude 'covered-call day 99.0
                                          :underlying "CLX6" :contract-size 1000 :unit "barrel"))
(spread-search-stock-price covered)                             ; => 97.5
(table-column (spread-search-spreads covered) "cost")           ; => #(94.3)
(spread-search-contract-size covered)                           ; => 1000
(spread-search-unit covered)                                    ; => "barrel"
```

The bull call spread of the 94 and 98 calls costs 3.1 - 1.0 = 2.1 a barrel, which
is 2,100 for a contract of 1,000 barrels. The covered call, on the November
future's options, buys the future at 97.5 and sells the 96 call at 3.2. For the
whole of the picture, `(show-option-positions (option-positions-for-chain chain
day 99.0 :underlying "CLZ6" :contract-size 1000 :unit "barrel"))` ranks the best
position of each kind, and `plot-option-profit` and `plot-option-positions` draw
them, with the profit "for a barrel" up the side.

#### The profit charts

A position's profit on the expiration day -- up the side -- against the price
the stock might have then -- along the bottom -- is the standard picture of
what an option position is: a *payoff diagram*. These functions draw it, for any
position of a search, and `option-profit-curve` gives its numbers.

```text
profit
 +2.8 |                    _____
      |                   /     \
    0 |------------------/-------\------------------
      |                 /         \
 -2.2 |________________/           \________________
      +----------------+-----+-----+----------------  price of the stock
                      100   105   110 115
```

(A sketch of the condor above, not to scale.) Above 0 the position has made money
-- the chart is green there -- and below 0 it has lost money, red. The line bends
only at the strikes, and is straight between them, so it is drawn through every
strike and every breakeven (where it crosses 0) as well as through a grid of
prices: the corners are sharp, and the green and red meet exactly at 0. With one
position, the chart marks where it breaks even (circles) and the stock at the
price you expect (a diamond, with the profit or loss there), draws dashed lines at
the most it can make and the most it can lose when they are within the chart
(a long call has no limit to what it can make, and the long stock loses all it cost
only with the stock at 0, far off the chart), and at the stock's price now and the
price expected. The profits are for a share, as everywhere here: a contract is 100 times
them (`:contract-size` times, for a future's options, and the axis says "for a barrel"). `save-chart` saves the chart, as for any other (`(save-chart "condor.png")`).

#### `(option-profit-curve search [:row r :low l :high h :points n])`
The profit of one of a search's positions -- the best, unless `:row` says -- on
the expiration day, for each price the stock might have then, as a table of
`price` and `profit` (for a share): `:points` (200) prices evenly from `:low` to
`:high`, and the position's strikes and breakevens among them, in order. Unless
they are given, `:low` and `:high` are 15% below the lowest price that matters --
a strike, a breakeven, the stock's price now, the price expected -- and 15% above
the highest. The profit at a price is the position's worth there, with its
shares, less its cost: what `show-option-spreads` works out at the price you expect,
at every price. This is the data of the charts, for your own.

#### `(plot-option-profit search [:rows rows :low l :high h :points n])`
Draws the chart of one position -- the best, unless `:rows` (a list of row
numbers: `(list 0)`, the best, is the default; 1 is the next) says -- as above. Given
several rows, the positions are lines on one chart, with each one's legs in the
legend, to compare them: the best three bull call spreads, say, whose lines cross
at the prices where one starts to beat another. The options are those of
`option-profit-curve`. Returns nothing; the chart goes where any other does: the
GUI's chart tab, a Jupyter cell, or a summary at the console, which is why a script
follows it with `save-chart`.

```lisp
(plot-option-profit search)                         ; the best position of the kind, in detail
(save-chart "iron_condor.png")
(plot-option-profit search :rows (list 0 1 2))      ; the best three, on one chart
```

#### `(option-profit-panel search [:row r :low l :high h :points n])`
The chart of one position as a panel for `plot-panels`, with its kind and legs as its
title and no legend, to put the charts of several kinds one above another on the
same prices. Give them the same `:low` and `:high`, and the figure the same
`:x-min` and `:x-max`, so that they line up:

```lisp
(plot-panels (map (lambda (kind) (option-profit-panel (position-comparison-search comparison kind) :low 85 :high 140))
                  '(call-butterfly put-butterfly iron-condor iron-butterfly))
             :title "Butterflies and condors" :x-min 85 :x-max 140 :height 12)
(save-chart "butterflies.png")
```

`examples/option_payoffs_example.lsp` draws every kind this way, from a made-up chain
(so it needs no Schwab account): one position in detail, the best few options-only
positions on one chart, the stock with a covered call, a protective put, and a collar, and
a gallery of the seventeen kinds in three figures. The other examples chart what they
find: `call_spread_example.lsp`, `option_spreads_example.lsp`, and
`option_positions_example.lsp` save a chart or two of the best positions of the stock you
give them. The pictures they save are not kept in the repository.

#### The kinds side by side

`lib/option_positions.lsp` takes the best position of every kind, and ranks
those by the same ratio -- the long stock among them, as the simplest thing
to compare the rest with.

#### `(option-positions creds symbol expiration expected-price [:kinds k :prices p :min-open-interest n :min-volume n :min-risk r :max-width w :stock-price s])`
Gets the stock's options that expire on `expiration` from Schwab -- the calls
and the puts, or only those the `:kinds` need -- and ranks the best position of
each kind: see `option-positions-for-chain`. Returns a `position-comparison`.

#### `(option-positions-for-chain chain expiration expected-price [:kinds k :prices p ... :underlying u :contract-size n :unit w])`
The same for a chain you already have. `:kinds` is a list of the names of the
kinds you want (the default is all seventeen); the other options are those of
`option-spreads-for-chain`, which does the searching, `:underlying`,
`:contract-size`, and `:unit` among them. A kind that needs puts, or calls,
that the chain has none of on that day (on the underlying), and a kind of which
no position can be made, are left out. Returns a `position-comparison`, whose
accessors are `position-comparison-stock`, `-stock-price`, `-expiration`,
`-expected-price`, `-prices`, `-contract-size`, `-unit`, `-positions`, and
`-searches`. Its table of
positions has a row for each kind, the best ratio first, with the columns `kind`;
`position`, what it buys and sells in words; and `cost`, `max-loss`, `max-profit`,
`worth`, `profit`, `ratio`, `breakeven-1`, and `breakeven-2`, as in the
tables of positions above.

#### `(position-comparison-search comparison kind)`
All the positions of one kind in the comparison, as the `spread-search` that
found them -- the best first -- to show with `show-option-spreads`, or to make
orders from.

#### `(plot-option-positions comparison [:kinds k :count n :low l :high h :points n])`
Charts the profits, on the expiration day, of the best position of each of several
kinds of a comparison, as lines on one chart, with the stock's price along the bottom
and the profit for a share up the side -- the same picture as `plot-option-profit`'s,
of different kinds, to compare their shapes. `:kinds` is a list of the names of the
kinds to draw. Unless it is given, they are the `:count` (4) best, by the ratio of
the comparison, of the kinds that have no shares: the options alone, whose profits
are of a size that can be set side by side. The long stock and the kinds with shares
are on a scale of their own, since they gain and lose what the stock does, so they go in a chart of their own:
`:kinds '(long-stock covered-call protective-put collar)` is the stock, and what each of
the three does to it -- the covered call stops rising at its strike, the protective put
stops falling at its strike, the collar both -- with the stock's line dashed. The legend
says what each position makes or loses at the price expected. `:low`, `:high`, and
`:points` are those of `option-profit-curve`.

#### `(show-option-positions comparison [:count n])`
Shows the table of the first `:count` (20) kinds, and where owning the stock
comes among them. For the chain above, with the stock expected at 108:

```
XYZ is at 104.00. The best position of each kind expiring 2026-11-20, if it is at 108.00 then; options bought and sold at the ask and bid prices, shares at 104.00. 17 positions.

Ranked by the ratio of profit to the most that can be lost (prices are for a share):
kind              position                                                                      cost  max-loss  max-profit  profit   ratio  breakeven-1  breakeven-2
----------------  --------------------------------------------------------------------------  ------  --------  ----------  ------  ------  -----------  -----------
call-butterfly    buy 1 105.00 call, sell 2 110.00 calls, buy 1 115.00 call                     1.30      1.30        3.70    1.70  130.8%       106.30       113.70
iron-condor       buy 1 100.00 put, sell 1 105.00 put, sell 1 110.00 call, buy 1 115.00 call   -2.80      2.20        2.80    2.80  127.3%       102.20       112.80
iron-butterfly    buy 1 105.00 put, sell 1 110.00 put, sell 1 110.00 call, buy 1 115.00 call   -3.60      1.40        3.60    1.60  114.3%       106.40       113.60
put-butterfly     buy 1 105.00 put, sell 2 110.00 puts, buy 1 115.00 put                        1.50      1.50        3.50    1.50  100.0%       106.50       113.50
collar            buy 100 shares, buy 1 100.00 put, sell 1 105.00 call                        102.60      2.60        2.40    2.40   92.3%       102.60
bull-put          buy 1 100.00 put, sell 1 105.00 put                                          -2.10      2.90        2.10    2.10   72.4%       102.90
bull-call         buy 1 100.00 call, sell 1 110.00 call                                         5.00      5.00        5.00    3.00   60.0%       105.00
protective-put    buy 100 shares, buy 1 100.00 put                                            105.60      5.60                2.40   42.9%       105.60
long-call         buy 1 100.00 call                                                             6.20      6.20                1.80   29.0%       106.20
bear-call         sell 1 110.00 call, buy 1 115.00 call                                        -0.70      4.30        0.70    0.70   16.3%       110.70
bear-put          sell 1 110.00 put, buy 1 115.00 put                                           4.40      4.40        0.60    0.60   13.6%       110.60
covered-call      buy 100 shares, sell 1 110.00 call                                          102.80    102.80        7.20    5.20    5.1%       102.80
cash-secured-put  sell 1 110.00 put                                                            -6.80    103.20        6.80    4.80    4.7%       103.20
long-stock        buy 100 shares                                                              104.00    104.00                4.00    3.8%       104.00
long-straddle     buy 1 100.00 call, buy 1 100.00 put                                           7.80      7.80                0.20    2.6%        92.20       107.80
long-put          buy 1 115.00 put                                                             11.20     11.20      103.80   -4.20  -37.5%       103.80
long-strangle     buy 1 100.00 put, buy 1 105.00 call                                           4.80      4.80               -1.80  -37.5%        95.20       109.80

Owning the stock (long-stock) is number 14 of 17, with a ratio of 3.8%: 13 of the positions make more for each dollar they could lose, with XYZ at 108.00 on 2026-11-20.

For the best few of one kind, and an order for it:
  (define search (position-comparison-search comparison 'covered-call))
  (show-option-spreads search)
```

Reading it: each row is the best position of its kind for the price you
expect, so the butterflies and condors, which make the most from a stock that
ends where you expect it, come first -- and are the ones that make nothing, or
lose, if it doesn't (which is why the ratio needs the caution above). The
positions with shares are of two sorts. The collar and the protective put
limit the loss to a few dollars a share, and give up a little of the gain for
it. The covered call keeps the call's price whatever the stock does, but
gives up the stock's rise past its strike, and still loses nearly all the
shares' price if the stock collapses. Owning the stock alone, down the list,
is what the rest are measured against: the positions above it make more for
each dollar they could lose, if the stock is where you say, and many of them
make less than it, or lose, if it is not.

**How much has been tried with Schwab.** Schwab's preview accepted an order
for a SPY call spread (a debit, of the strategy `VERTICAL`: see
`schwab-spread-order`) on 2026-10-14. The orders for the other kinds of spread
-- the credit spreads, which are `NET_CREDIT` orders, the butterflies, condors,
straddles, and strangles -- have the forms in Schwab's documentation of its
Trader API, and the program's tests check their legs, quantities, and prices,
but none has been previewed with Schwab. The iron butterfly is sent as an
`IRON_CONDOR`, which is a guess; if Schwab doesn't take it, `:strategy` says
what to call it instead. The plain orders -- the shares, and the single
options, alone or as the parts of a position with shares -- are the forms
`schwab-order` makes for a stock and for an option, and have not been
previewed either. **Always preview** (that places nothing), and read Schwab's
answer for the commission and any warning, before placing an order.

### A scenario: every position, every expiration

(In `lib/trade_scenario.lsp`; its functions work without loading it.) "Crude oil will be at 70 on December 1."
"Apple will be at 380 on December 18." What is the best way to trade on it with options, if it comes to pass, and
what does each way risk if it doesn't? `trade-scenario` gets the options of a stock or a future from tastytrade,
makes every position of nineteen kinds out of those that expire on or after the date -- the seventeen of "Option
spreads", and two calendar spreads -- values each on the date, and ranks them in one table.

```lisp
(define scenario (trade-scenario creds "AAPL" 380.0 (date 2026 12 18)))
(show-trade-scenario scenario)
```

**What is different from "Option spreads".** There, the price you expect is on an expiration day, and only that
day's options count. Here the date can be any day, and every expiration on or after it is searched:

- An option that **expires on the date** is worth what it pays then: a call the price less its strike, or nothing; a
  put the strike less the price, or nothing. These positions' numbers are exactly those of `option-spreads-for-chain`.
- An option that **expires later** still has time to run on the date, and is worth more than what it would pay: what
  the Black-Scholes formula says it is worth (Black's, for a future's option), with the time it has left, at the
  volatility its own price implies today (the middle of its bid and ask, through `implied-vol`). Keeping each option's
  volatility as it is today is an assumption: a big move usually changes volatilities too.
- **Calendar spreads** sell an option that expires on or after the date and buy the same strike's option that
  expires later: `call-calendar` and `put-calendar`. On the date the near one is worth little, and the far one still
  has its time, so the spread does best with the price near the strike.

**The numbers of each position**, for one unit (a share, or a barrel), on the date:

| Column | What it holds |
|---|---|
| `profit` | what it is worth at the scenario's price less what it costs today: if you are right |
| `max-loss` | the most it can lose, at any price: if you are wrong. Exact for a position that expires on the date; for one that expires later, the worst of its profits at 300 prices from 0 to three times the higher of today's price and the scenario's |
| `if-unchanged` | the profit if the price on the date is today's: if nothing happens. Options that expire later have lost some of their time by then |
| `roi` | the profit over the **money committed**: the cost of a position that costs you (a debit); the most it can lose, for one that pays you (a credit), which is about what a broker holds as margin (for a cash-secured put, the cash to buy the shares). Shares are paid for in full |
| `ratio` | the profit over the most it can lose, as "Option spreads" ranks |
| `breakeven-1`, `breakeven-2` | the prices on the date where it breaks even |

The positions are ranked by `roi`, unless `:rank-by` says `ratio` or `profit`.

**Futures.** A future's options are on several futures, one for each delivery month, with prices of their own
(crude oil's December options are on the January future). The scenario's price is the price of one of them -- the
future of the options that expire first on or after the date, unless `:underlying` names another -- and each of the
others is taken to keep its difference from it, as today. The amounts are for one unit; `trade-scenario` knows the
contract size and unit of the common futures (the list `trade-scenario-futures-units` in `lib/trade_scenario.lsp`: crude oil 1,000 barrels, gold 100
ounces, the E-mini S&P 50 points, ...), and the display says what a contract's dollars are.

**Strikes.** tastytrade sends each expiration's strikes nearest today's price (`:strikes`, 40 of them). For a
scenario far from today's price, the best positions may use strikes further out: the display says when the scenario's
price is beyond the strikes there are, and `:strikes 80` asks for more.

For Apple at 380 on December 18, 2026, from 344 on October 30 (abridged):

```
The scenario: AAPL at 380.00 on 2026-12-18 (it is at 344.46 now). 4146 positions, from options expiring on 2026-12-18 or later; ...
kind            expires                  position                                                    cost  max-loss  profit   roi  if-unchanged
call-butterfly  2026-12-18               buy 1 375.00 call, sell 2 380.00 calls, buy 1 385.00 call   0.67      0.67    4.33  646%         -0.67
bull-call       2026-12-18               buy 1 375.00 call, sell 1 380.00 call                       1.09      1.09    3.91  359%         -1.09
call-calendar   2026-12-18 & 2027-01-15  sell 1 380.00 call (2026-12-18), buy 1 380.00 call (2027-01-15)   2.29   2.29    8.09  353%         -1.56
long-call       2026-12-18               buy 1 360.00 call                                           7.30      7.30   12.70  174%         -7.30
long-stock                               buy 100 shares                                            344.46    344.46   35.54   10%          0.00
```

The butterfly makes the most for what it costs, but only if Apple ends near 380: it breaks even at 375.67 and at
384.33. The calendar makes less of its cost, but over a wider range of prices (356.87 to 412.90), because the
January call it keeps is worth something wherever Apple is. The long call makes something above 367.30, and more
the higher Apple goes. The ranking is for the one price; look at `max-loss`, `if-unchanged` and the breakevens to
choose among them. What is left out: commissions; that the options would be sold on the date at their bids, not at
the formula's middle; early exercise; and how likely the scenario is.

#### `(trade-scenario creds symbol price date [:kinds k :strikes n :months m :rate r :rank-by b :prices p :min-open-interest n :min-volume n :min-risk r :max-width w :underlying u :contract-size n :unit w])`
Gets `symbol`'s options -- a stock's (`"AAPL"`), or a future's, by its code in `(tastytrade-products)` (`"CL"`) --
from tastytrade, and ranks every position that could be traded on the scenario that it is at `price` on `date` (a
date, or `"YYYY-MM-DD"`): see `trade-scenario-for-chain`. `:strikes` (40) is how many strikes nearest today's price
to get of each expiration; `:months` how many months of expirations (of a stock's) or of delivery months (of a
future's), by default three more than the months to the date; `:rate` the interest rate, continuously compounded, by
default the Treasury curve's to the date. A future's `:contract-size` and `:unit` are from
`trade-scenario-futures-units` unless they are given; a stock's are 100 and `"share"`. The other options are
`trade-scenario-for-chain`'s. Returns a `trade-scenario`.

#### `(trade-scenario-for-chain chain price date [:kinds k :rate r :rank-by b :today d :prices p :min-open-interest n :min-volume n :min-risk r :max-width w :underlying u :contract-size n :unit w])`
The same, for a chain you have: a table as `tastytrade-option-chain` makes (or `schwab-option-chain`'s, with
`:today`, the day of its prices, since it has no days to expiration). `:kinds` is a list of the names of the kinds
to search -- those of `(option-spread-kinds)`, and `call-calendar` and `put-calendar` -- by default all of them.
`:rate` is 0.04 unless it is given. `:rank-by` is `roi` (the default), `ratio`, or `profit`. `:min-volume` is 0 here,
since a scenario is often looked at when the market is closed; the rest are those of `option-spreads-for-chain`.
Returns a `trade-scenario`, whose accessors are `trade-scenario-symbol` (the underlying the price is of),
`-today-price`, `-price`, `-date`, `-rate`, `-prices`, `-contract-size`, `-unit`, `-underlyings` (a table of each
underlying's price today and in the scenario), `-strikes` (the lowest and highest searched), and `-trades`: the table
of positions, the best first, with the columns `kind`; `expires` (the expiration, or a calendar's two);
`underlying`; `shares` (1 if it buys the underlying); for each of up to four options, `type-1`, `quantity-1`
(negative: sold), `expiration-1`, `symbol-1`, `strike-1` and `price-1` (the ask paid, or the bid got), and so on,
empty past its last; and `cost`, `max-loss`, `worth`, `profit`, `roi`, `ratio`, `if-unchanged`, `breakeven-1` and
`breakeven-2`, as above.

#### `(show-trade-scenario scenario [:count n])`
Says what the scenario is (and, for futures, what each future's price is taken to be), warns if the scenario's price
is beyond the strikes searched, and shows the best `:count` (15) positions and the best of each kind, with the
positions in words.

#### `(trade-scenario-best-of-each-kind scenario)`, `(trade-scenario-position-in-words scenario row)`
The table of the best position of each kind, as `show-trade-scenario` shows it; and one row's position in words
(`"sell 1 380.00 call (2026-12-18), buy 1 380.00 call (2027-01-15)"`).

`examples/trade_scenario_example.lsp` does it from the command line: `python3 ../lisp_interpreter.py
trade_scenario_example.lsp CL 70 2026-12-01`.

### Portfolios

(In `lisp_portfolio.py`.) Several investments together: their returns
lined up by date, paths of all of them, a portfolio's value, and the
weights that Markowitz's mean-variance analysis says are best.

Weights, start prices, and expected returns are lists of `(name .
number)` pairs: `(list (cons "SPY" 0.6) (cons "TLT" 0.4))`.

#### `(combine-returns named-returns)`
Several investments' returns, a list of `(name . returns)`, each a table
as `daily-returns` makes it, lined up by date: a table of `date` and a
column of returns for each investment, named for it, with a row for each
date they all have. `adjust-returns` gives each its expected return, and
`covariance-matrix` and `bootstrap-paths` take it.

```lisp
(define a (make-table "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4) (date 2024 1 5))
                      "log-return" #(0.01 -0.02 0.03 0.0)))
(define b (make-table "date" (vector (date 2024 1 3) (date 2024 1 4) (date 2024 1 5) (date 2024 1 8))
                      "log-return" #(0.005 0.01 -0.01 0.02)))
(define both (combine-returns (list (cons "A" a) (cons "B" b))))
(table-column both "date")      ; => #(2024-01-03 2024-01-04 2024-01-05)
```

#### `(bootstrap-paths returns start-prices days block-size [:seed n] [:dividends schedules] [:volatility model] [:start-volatility x])`
A path for each of several investments, made from **the same days** of
the history: when one had a bad day in the history, the others have that
day too, so their correlation is kept. A table of `day` (1 for the first)
and a column of prices for each investment. `returns` is a table as
`combine-returns` makes (and `adjust-returns` adjusts); `start-prices` a
list of `(name . price)`; `:dividends` a list of `(name . schedule)`, as
`dividend-schedule` makes, for those that pay them. `:volatility` is a
volatility model with a row for each investment (`volatility-model` of the
same table): each one's volatility starts at its own today's and changes
as its own model says, and the paths copy the same days' shocks.
`:start-volatility` is then one volatility for all of them, or a list of
`(name . volatility)`. Otherwise it is `bootstrap-path`, and
`bootstrap-days` shows the days it copied.

```lisp
(define paths (bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 4 2 :seed 3))
(vector-round (table-column paths "A") 2)     ; => #(98.02 101.01 101.01 99.0)
```

#### `(portfolio-value prices weights [:start-prices p] [:rebalance n] [:start-value v])`
A portfolio's value along a table of prices (a column for each investment
and a row for each day: a price history, or `bootstrap-paths`' paths), as a
vector with a value for each row. `weights` must add to 1. The portfolio is
bought with `:start-value` (1 unless given), at `:start-prices` if they're
given, and otherwise at the first row's prices. `:rebalance n` puts it back
to the weights every `n` rows (21 is about a month of trading days); without
it, it is bought and held. The prices should have any dividends in them
(total returns, with no `:dividends` schedule): the portfolio doesn't get
them otherwise.

```lisp
(define prices (make-table "A" #(100.0 110.0 121.0) "B" #(100.0 100.0 100.0)))
(vector-round (portfolio-value prices (list (cons "A" 0.5) (cons "B" 0.5))) 4)              ; => #(1.0 1.05 1.105)
(vector-round (portfolio-value prices (list (cons "A" 0.5) (cons "B" 0.5)) :rebalance 1) 4) ; => #(1.0 1.05 1.1025)
```
Bought and held, A grows to 60.5% of the portfolio; put back to half and
half each day, it doesn't.

#### `(covariance-matrix returns [:days-per-year n])`, `(correlation-matrix returns)`
The covariance and the correlation of each pair of investments' returns,
as a table: an `investment` column with their names, and a column for each
of them, so `display-table` shows the matrix. The covariance is for a year:
the daily returns' covariance times the days in a year (252, unless
`:days-per-year` says). A correlation is from -1 to 1.

```lisp
(vector-round (table-column (covariance-matrix both) "A") 4)    ; => #(0.1596 0.0231)
(vector-round (table-column (correlation-matrix both) "B") 4)   ; => #(0.35 1.0)
(display-table (correlation-matrix both))
```

#### `(minimum-variance-weights covariance [:long-only #t])`, `(mean-variance-weights expected-returns covariance risk-aversion [:long-only #t])`
The weights, adding to 1, that make a portfolio's variance least, or its
expected return less `risk-aversion` / 2 times its variance greatest,
as a list of `(name . weight)`. `covariance` is a table as
`covariance-matrix` makes; `expected-returns` a list of `(name . annual
return)`. The larger `risk-aversion`, the nearer the weights are to the
minimum-variance ones; the smaller, the more of the investments with the
highest expected returns.

- A weight can be below 0, selling the investment short, unless
  `:long-only #t`. Without it, the answer is a formula: a set of linear
  equations, solved.
- With `:long-only #t`, it is found by solving those equations for fewer
  and fewer of the investments: one that would have a weight below 0 is
  left out (its weight is 0), and one left out is let back in if the
  portfolio would be better with some of it, until neither happens. Then
  the answer meets the conditions for the best one.

```lisp
(define cov (make-table "investment" (vector "X" "Y" "Z")
                        "X" #(0.04 0.006 -0.01) "Y" #(0.006 0.09 0.02) "Z" #(-0.01 0.02 0.0225)))
(define (in-tenths-of-a-percent weights) (map (lambda (p) (cons (car p) (round (* 1000 (cdr p))))) weights))
(in-tenths-of-a-percent (minimum-variance-weights cov))                 ; => (("X" . 410) ("Y" . -70) ("Z" . 660))
(in-tenths-of-a-percent (minimum-variance-weights cov :long-only #t))   ; => (("X" . 394) ("Y" . 0) ("Z" . 606))
(in-tenths-of-a-percent (mean-variance-weights (list (cons "X" 0.06) (cons "Y" 0.12) (cons "Z" 0.04)) cov 4))
; => (("X" . 408) ("Y" . 206) ("Z" . 386))
```

#### `(portfolio-volatility weights covariance)`
The volatility of a portfolio with these weights, by the covariance matrix
(for a year, as `covariance-matrix` gives it): the square root of the sum
of `weight(i) × weight(j) × covariance(i, j)`.

```lisp
(format "{:.4f}" (portfolio-volatility (minimum-variance-weights cov) cov))   ; => "0.0968"
```

**Putting it together**: two ETFs' prices from Schwab, their returns lined
up, paths of a year that grow at the interest rate, and the value of a
60/40 portfolio rebalanced every month along each:

```lisp
(define spy (daily-returns (schwab-price-history creds "SPY") :dividends (alpha-vantage-dividends creds "SPY")))
(define tlt (daily-returns (schwab-price-history creds "TLT") :dividends (alpha-vantage-dividends creds "TLT")))
(define both (adjust-returns (combine-returns (list (cons "SPY" spy) (cons "TLT" tlt))) (- (exp 0.04) 1)))
(display-table (correlation-matrix both))
(define ends
  (map (lambda (i)
         (let ((paths (bootstrap-paths both (list (cons "SPY" 1) (cons "TLT" 1)) 252 10 :seed i)))
           (vector-ref (portfolio-value paths (list (cons "SPY" 0.6) (cons "TLT" 0.4))
                                        :start-prices (list (cons "SPY" 1) (cons "TLT" 1)) :rebalance 21)
                       251)))
       (iota 1000)))
(vector-quantile (list->vector ends) #(0.05 0.5 0.95))
```
