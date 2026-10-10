# morris-lisp — The library

The functions for investment analysis: getting data (prices, option chains,
and accounts from Schwab and tastytrade; economic and financial data from
FRED, the SEC, the FDIC, the BLS, the BEA, the Census Bureau, and Alpha
Vantage; any web API, and SQLite), statistical models (regression, linear
programming, and stratification), dates and cash flows, and investments
(option prices, the volatility smile, simulated prices and the volatility
model, option checks, and portfolios), and maps. Most are builtins,
written in Python; the rest are libraries in `lib/`, written in Lisp.

The language itself, and the general builtins these all work with --
tables, vectors and statistics, dates, charts, and displaying and saving
things -- are in the language manual,
[lisp_interpreter_reference.md](lisp_interpreter_reference.md). A section
name in quotes is a section of this manual, unless it says it's in that
one.

For a guide to the economic and financial data by topic -- which agency
publishes what, and which function gets it -- see
[economic_data_guide.md](economic_data_guide.md).

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [Where things are](#where-things-are)
- [Getting data](#getting-data)
  - [Downloading data from the web](#downloading-data-from-the-web)
  - [FRED (Federal Reserve Bank of St. Louis) data](#fred-federal-reserve-bank-of-st-louis-data)
  - [SEC financial statements](#sec-financial-statements)
  - [FDIC bank data](#fdic-bank-data)
  - [Census data](#census-data)
  - [Maps](#maps)
  - [BLS data](#bls-data)
  - [BEA data](#bea-data)
  - [SQLite](#sqlite)
  - [tastytrade (real broker data)](#tastytrade-real-broker-data)
  - [Schwab (your accounts)](#schwab-your-accounts)
  - [Alpha Vantage (dividends)](#alpha-vantage-dividends)
  - [Google Sheets](#google-sheets)
- [Dates and cash flows](#dates-and-cash-flows)
  - [Monthly time series](#monthly-time-series)
  - [Trading days (the NYSE's calendar)](#trading-days-the-nyses-calendar)
  - [Day counts and cash flows](#day-counts-and-cash-flows)
- [Statistical models](#statistical-models)
  - [Regression models](#regression-models)
  - [How good is a model? The measures, explained](#how-good-is-a-model-the-measures-explained)
  - [Linear programming](#linear-programming)
  - [Stratification tables](#stratification-tables)
- [Investments](#investments)
  - [Option prices](#option-prices)
  - [Implied volatility smiles: finding options out of line](#implied-volatility-smiles-finding-options-out-of-line)
  - [Simulating investment prices](#simulating-investment-prices)
  - [Starting paths from today's volatility](#starting-paths-from-todays-volatility)
  - [Checking option prices against simulated paths](#checking-option-prices-against-simulated-paths)
  - [Valuing options three ways](#valuing-options-three-ways)
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
   "Google Sheets" sends tables out, to a spreadsheet.
2. **Tables and numbers.** In the language manual: "Tables", "Vectors",
   "Vector math and statistics" (`vector-drawdowns` is there), "Displaying
   tables", "Charting", and "Saving variables". Here: "Stratification
   tables" and "Maps".
3. **Dates.** "Dates", in the language manual. Here: "Trading days (the
   NYSE's calendar)", "Monthly time series" (daily data made monthly, and
   several series lined up), and "Day counts and cash flows" (`npv`, `irr`,
   `yield`, `duration`, ...).
4. **Simulated prices.** "Simulating investment prices": an investment's
   returns, with its dividends, and paths of its price made from its own
   history; `bootstrap-days` shows which days a path copied. "Starting
   paths from today's volatility": `volatility-model`, so that paths start
   as calm or as wild as the market is today. "Portfolios":
   several investments together, their covariance and correlation, a
   portfolio's value, and Markowitz's best weights.
5. **Options.** "Option prices": Black-Scholes, implied volatility, the
   Greeks, and American options (`binomial-tree` shows the tree). "Implied
   volatility smiles": options out of line with the rest of their chain.
   "Checking option prices against simulated paths": options out of line
   with the underlying's history. "Valuing options three ways": a stock's
   options by Black-Scholes, a binomial tree, and simulated paths, next to
   their bids and asks.
6. **Rates and mortgages.** The SOFR term structure and its two-factor
   model (`sofr-*`, under "tastytrade (real broker data)"), futures curves
   (`futures-curve-fit`), and `lib/oas_monte_carlo.lsp`, `lib/column_engine.lsp`,
   `lib/template.lsp`, and `lib/prepayment_model.lsp`, for mortgage pools and
   their tranches.
7. **Models.** "Regression models" (linear, logistic, spline, and least
   absolute deviation, which a spline can be fit by too), "Linear programming", and `lib/solver.lsp`.

**Built in, or loaded.** Everything above is built in, and there whenever
the interpreter is, except the libraries in `lib/`, which are loaded with
`(load "name.lsp")`: `vol_smile.lsp`, `option_check.lsp`, `option_methods.lsp`,
`oas_monte_carlo.lsp`, `solver.lsp`, `column_engine.lsp`, `template.lsp`,
`prepayment_model.lsp`, and `model_utils.lsp`. (Their functions can be
called without loading them, too, once `lib/autoloads.lsp` is loaded, as
`init.lsp` does: see `lazy-load`.) The rule: what has to be fast, or talks
to the world outside, is a builtin, written in Python; a model made of
those is a library, written in Lisp, to be read and changed.

**Examples.** `examples/` has a program for most of this, run from that
directory with `python3 ../lisp_interpreter.py name.lsp`:
`investment_paths_example.lsp` (simulated prices, an option on them, and
dividends), `option_methods_example.lsp` (a stock's listed options valued
by Black-Scholes, a binomial tree, and simulated paths, next to their bids
and asks: give it the stock's symbol), `vol_smile_example.lsp`, `option_chain_example.lsp`,
`fred_example.lsp`, `sec_example.lsp`, `fdic_example.lsp`,
`census_bls_example.lsp`, `bea_example.lsp`, `prepayment_demo.lsp`,
`regression_kinds_example.lsp` (the kinds of regression on the same data,
charted -- with a floor and ceiling, a quantile band, a smooth spline --
and cross-validated),
`oas_monte_carlo_example.lsp`, and `mortgage_amortization_example.lsp`.

## Getting data

Each of these gives a table (see "Tables", in the
[language manual](lisp_interpreter_reference.md#tables)), so the data from
all of them works the same way after that.

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

#### `(http-get-csv url [has-header? cache-hours headers])`
The CSV file at `url`, as a table, read exactly as `load-csv` reads a file.

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

#### `(sofr-forward-curve curve-rows)`
Pure function — no networking. `curve-rows` is
`(tastytrade-futures-curve-rows creds "SR3" [n-months])` — one row per
listed CME 3-Month SOFR future. Bootstraps a 360-month (30-year) curve of
1-month forward rates implied by those futures prices, reusing
`term_structure/term_structure_model.py`'s `bootstrap_sofr_curve()`
as-is (see that function's docstring for the full methodology and its
documented simplifications — flat extrapolation beyond the last listed
contract, no convexity adjustment, a whole reference quarter treated as
one flat rate). Returns `(cons months-vector forward-rates-vector)`,
1-indexed by month: `(vector-ref forward-rates-vector (- month 1))`.
Needs `term_structure/term_structure_model.py` (next to this repo's
`lisp_interp/`); raises `LispError` if it isn't importable, or if
`curve-rows` is empty.

```lisp
(define curve (sofr-forward-curve (tastytrade-futures-curve-rows creds "SR3" 40)))
(define sofr-months (car curve))
(define sofr-forward-rates (cdr curve))
(plot-chart (list (list "SOFR forward" sofr-months sofr-forward-rates)))
```

See `examples/sofr_floating_rate_example.lsp` for feeding
`sofr-forward-rates` into `column_engine.lsp` to drive a floating-rate
note's coupon, period by period. `prepayment_model.lsp` (a simple
PSA-style CPR/SMM curve — see that file) is the mortgage-prepayment
counterpart, incorporated into `mortgage_amortization_example.lsp`'s
collateral cashflows; `prepayment_demo.lsp`/`term_structure/
mortgage_spread.py` show a data-fit (rather than textbook-PSA) CPR model
and a way to estimate the SOFR-to-mortgage spread the rate-incentive
input to either kind of model would need.

#### `(sofr-calibration-data credentials-path [n-futures n-underlyings n-strikes])`
Fetches a SOFR futures curve AND a spread of SOFR futures OPTIONS in one
tastytrade session, reusing `term_structure/sofr_market_data.py`'s
`fetch_sofr_calibration_data()` as-is (see that module for the full
selection methodology — options are spread evenly across every curve
quarter with a listed chain, not just the nearest few, so `sigma1`/
`sigma2` below are separately identifiable). A SEPARATE fetch from
`tastytrade-futures-curve-rows` — this one also pulls option chains, not
just futures prices. `n-futures`/`n-underlyings`/`n-strikes` default to
`40`/`10`/`3`.

Returns `(cons curve-futures-rows options-rows)`:
- `curve-futures-rows` — one row per SR3 contract month used for the
  curve: `(symbol start-months end-months rate)`. Feed to
  `sofr-bootstrap-curve`.
- `options-rows` — up to `n-underlyings * n-strikes * 2` near-the-money
  call/put pairs: `(type strike expiry-months quarter-start-months
  quarter-end-months market-price)`. Feed to `sofr-calibrate-model`.

Needs the `tastytrade` package, a tastytrade account, and a credentials
JSON file (see `tasty_api/README.md`).

```lisp
(define data (sofr-calibration-data creds 40 8 3))
(define curve-futures-rows (car data))
(define options-rows (cdr data))
```

#### `(sofr-bootstrap-curve curve-futures-rows)`
Pure function — no networking. Like `sofr-forward-curve`, but takes
`sofr-calibration-data`'s `curve-futures-rows` shape (`(symbol
start-months end-months rate)`) instead of `tastytrade-futures-curve-
rows`'s — no day-count reshaping needed, since these rows already carry
`start-months`/`end-months` directly. Same return shape: `(cons
months-vector forward-rates-vector)`.

```lisp
(define curve (sofr-bootstrap-curve curve-futures-rows))
(define sofr-forward-rates (cdr curve))
```

#### `(sofr-extend-curve-with-treasury forward-rates curve-real-months yield-3m yield-6m yield-1y yield-2y yield-5y yield-10y yield-30y [blend-months])`
Pure function — no networking. Replaces the flat-extrapolated tail of a
curve from `sofr-bootstrap-curve`/`sofr-forward-curve` — past
`curve-real-months`, everything is held at the last real futures rate —
with the SHAPE of a separate curve bootstrapped from Treasury par yields,
linearly blended in over `blend-months` (default `12`) so the splice
doesn't visibly kink. Reuses `term_structure_model.py`'s
`extend_curve_long_end()` (and, internally, `bootstrap_forward_curve()`
for the Treasury side) as-is.

CME only lists roughly a 5-year strip of SR3 contracts, so any SOFR curve
is flat past there; for anything priced off the far end of the curve (a
30-year MBS, say), the free, much longer-dated Treasury par curve on FRED
is a better long-end *shape* than a flat line. This does **not** attempt
a SOFR/Treasury basis adjustment — it borrows the Treasury curve's shape
as-is past `curve-real-months`, a simplification worth being aware of.

- `forward-rates` — the curve to extend, e.g. `sofr-bootstrap-curve`'s or
  `sofr-forward-curve`'s second return value.
- `curve-real-months` — same meaning as `sofr-calibrate-model`'s argument
  of the same name: how many months of `forward-rates` are backed by real
  market data.
- `yield-3m`/`6m`/`1y`/`2y`/`5y`/`10y`/`30y` — today's Treasury par
  yields, as DECIMALS (`0.045`, not `4.5`) — e.g. FRED's
  `DGS3MO`/`DGS6MO`/`DGS1`/`DGS2`/`DGS5`/`DGS10`/`DGS30`, each divided by
  100 (FRED reports those series in percent).
- `blend-months` (default `12`) — width, in months starting at
  `curve-real-months`, of the linear transition zone.

Returns a new forward-rates vector (same length as the input; the input
is not modified).

```lisp
(define extended-forward-rates
  (sofr-extend-curve-with-treasury sofr-forward-rates curve-real-months
                                    0.043 0.041 0.039 0.038 0.040 0.043 0.046))
```

#### `(sofr-calibrate-model forward-rates options-rows curve-real-months [n-paths seed n-grid n-rounds])`
Pure function — no networking (cheap to re-run with different settings
once you've fetched `options-rows` once). Fits the two-factor model's
mean-reversion speed `a` and both volatilities — `sigma1` (the short-rate
factor) and `sigma2` (the slower-moving mean-reversion-*level* factor) —
directly against real SOFR futures option prices, by a "zooming grid
search": try a grid of `(a, sigma1, sigma2)` combinations, keep whichever
prices the options closest, shrink the search window around it, repeat
`n-rounds` times. Reuses `term_structure_model.py`'s
`calibrate_sofr_model()` as-is — see that function's docstring for the
full methodology, including *why* it fits `a` against option prices
directly rather than against today's curve shape (found, on real data, to
meaningfully improve the fit) and how `theta_bar` (the long-run level the
model's second factor drifts toward) gets refit in closed form at every
candidate `a`.

- `forward-rates` — `sofr-forward-curve`'s or `sofr-bootstrap-curve`'s
  second return value.
- `options-rows` — `sofr-calibration-data`'s second return value (or
  anything shaped the same way).
- `curve-real-months` — how many months of `forward-rates` are the REAL
  (non-extrapolated) part of the curve, i.e. the largest `end-months`
  among the `curve-futures-rows` used to build it.
- `n-paths` (default `2000`) — Monte Carlo paths used to price EACH
  option at EACH candidate tried; an accuracy/speed trade-off for the
  *calibration* itself, separate from how many scenario paths
  `sofr-simulate-rate-paths` later generates.
- `seed` (default `42`), `n-grid` (default `7`), `n-rounds` (default
  `4`) — grid resolution per round / how many times to zoom in. Cost is
  roughly `O(n-grid³ × n-rounds × n-paths × number of options)` — the
  `term_structure_model.py` module docstring reports **ten to twenty
  seconds** for its own real-data test at these same defaults and a
  handful of options; turn `n-paths`/`n-grid`/`n-rounds` down for a
  quicker first pass. See `sofr_monte_carlo_example.lsp`.

Returns `(list a theta-bar sigma1 sigma2 error)` — `error` is the total
squared pricing error at the winning parameters.

```lisp
(define fit (sofr-calibrate-model sofr-forward-rates options-rows 24
                                   500 42 5 3))    ; turned down for speed
(define fitted-a (list-ref fit 0))
(define fitted-theta-bar (list-ref fit 1))
(define fitted-sigma1 (list-ref fit 2))
(define fitted-sigma2 (list-ref fit 3))
```

#### `(sofr-simulate-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths [seed a theta-bar])`
Pure function — no networking. Simulates `n-paths` Monte Carlo scenarios
of the two-factor model (a short-rate factor and a slower mean-reversion-
level factor — see `term_structure/term_structure_model.py`'s module
docstring) `horizon-years` forward, reusing that module's
`simulate_rate_paths()` as-is. `seed` defaults to `'()` (a fresh random
seed each call); an integer gives reproducible paths.

Pass `sofr-calibrate-model`'s fitted `a`/`theta-bar` (its first two
return values) for `a`/`theta-bar` when `forward-rates` came from
`sofr-bootstrap-curve`/`sofr-forward-curve` — leaving them `'()` uses
this function's own default (theta-bar as the average of `forward-
rates`' last 2 years), which for a SOFR curve anchors theta-bar at an
arbitrary flat-extrapolated value with no connection to real market data.

Returns `(list years-vector short-rate-paths ten-year-paths)`:
- `years-vector` — times in years: `0, 1/12, 2/12, ..., horizon-years`.
- `short-rate-paths` / `ten-year-paths` — each a Lisp LIST of
  `(horizon-years×12 + 1)`-element vectors, one per path. `ten-year-
  paths[i]` is path `i`'s approximate ten-year rate, a closed-form
  function of that path's state at each month, not a separately-
  simulated factor.

```lisp
(define sim (sofr-simulate-rate-paths sofr-forward-rates 0.005 0.01 5.0 20 42))
(define years (list-ref sim 0))
(define short-rate-paths (list-ref sim 1))
(plot-chart (map (lambda (path) (list "short rate" years path)) short-rate-paths) :legend #f)
```

#### `(sofr-simulate-mortgage-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths mortgage-spread [seed a theta-bar tenor-years])`
Pure function — no networking. The same simulation as
`sofr-simulate-rate-paths`, plus a simple proxy mortgage rate per
path/month: `mortgage_rate = tenor-years-rate + mortgage-spread`
(`tenor-years` defaults to `10`, the usual rate-sensitivity proxy for a
30-year mortgage). Reuses `simulate_mortgage_rate_paths()` as-is.

**SIMPLIFICATION** (from the underlying model, not this bridge): a real
mortgage rate tracks current-coupon MBS yields — the whole curve,
prepayment risk, origination costs — not one flat spread over one tenor
point; `mortgage-spread` is a deliberate simplification, named so it's
obvious where to plug in something richer (`term_structure/
mortgage_spread.py`'s `fetch_current_mortgage_rate()` pulls FRED's
`MORTGAGE30US` for one way to estimate it from real data instead of
guessing).

Returns `(list years-vector short-rate-paths underlying-paths
mortgage-paths)` — `underlying-paths` is the `tenor-years` rate before
adding the spread; `mortgage-paths` is after.

**Example**: `examples/sofr_monte_carlo_example.lsp` runs the
full pipeline end to end — `sofr-calibration-data` →
`sofr-bootstrap-curve` → `sofr-calibrate-model` →
`sofr-simulate-mortgage-rate-paths` — then charts a few paths and writes
all of them to CSV via `write-columns-csv` (see "Displaying tables", in the [language manual](lisp_interpreter_reference.md#displaying-tables)). Its
header comment sketches feeding one simulated path into
`mortgage_amortization_example.lsp` in place of the deterministic
SOFR-forward-curve-derived rate, for a single Monte Carlo scenario's
cashflows (looping over several paths, each with its own
`column_engine.lsp` registry, is the natural next step toward a full
Monte Carlo distribution of cashflows — not built out there).

That "loop over several paths" step is exactly what
[`oas_monte_carlo.lsp`](lib/oas_monte_carlo.lsp) does, deliberately WITHOUT
`column_engine.lsp` (its per-row registry/topological-sort machinery is
built for readability on a single calculated table, not for generating
hundreds-to-thousands of per-path cashflow vectors fast). It adds:

- `annualized-realized-vol` — a historical-data cross-check for
  `sofr-calibrate-model`'s fitted `sigma1`/`sigma2` (or a quick sanity
  check with no options data at all), from a plain rate-level vector —
  see its docstring for a worked example with FRED's `"DFF"` and `"DGS10"`.
- `simple-mortgage-cashflows` / `mortgage-cashflows-per-path` — a fast,
  direct (not `column_engine.lsp`-based) fixed-rate, PSA-prepaying
  pass-through cashflow generator, reusing `prepayment_model.lsp`'s
  `cpr`/`smm-from-cpr`, either for one path or for every path in a
  `sofr-simulate-mortgage-rate-paths` result at once.
- `path-present-value` / `oas-model-price` / `oas-solve` — the
  Option-Adjusted Spread engine itself: discounts a cashflow stream along
  one Monte Carlo path using that path's own simulated short rate plus a
  trial spread (the SAME discounting convention `term_structure_model.py`'s
  `price_callable_bond_mc()` uses), averages across paths for a model
  price, then bisects for whichever spread reproduces a target market
  price — the "solve for OAS" direction that function's own docstring
  flags as unimplemented. Works for a single shared cashflow vector (an
  ordinary bond) or a per-path list of cashflow vectors (a prepaying
  mortgage, whose cashflows are path-dependent).

See [`oas_monte_carlo_example.lsp`](examples/oas_monte_carlo_example.lsp) for the
full pipeline end to end — curve extension → (illustrated) historical-vol
cross-check → `sofr-simulate-mortgage-rate-paths` →
`mortgage-cashflows-per-path` → `oas-solve` — runnable with no network
access or credentials (its curve/volatility/market-price numbers are all
illustrative, in the same spirit as `term_structure_model.py`'s own
`__main__` demo).

[`oas_monte_carlo_live_example.lsp`](examples/oas_monte_carlo_live_example.lsp) is
the same pipeline against REAL data instead: the SOFR futures curve and
calibration options from tastytrade (`sofr-calibration-data`), the
Treasury par curve and the DFF/DGS10 historical-vol cross-check from
`fred-table`, and the mortgage note rate from FRED's `MORTGAGE30US` —
only the security's own market price has no live source wired up
anywhere in this codebase, so that one number stays an assumption.
Writes `oas_monte_carlo_live_report.txt` (and prints the same report to
the console) listing every fetched data point and every assumption the
run used, split into separate sections so it's clear which is which.
Needs a credentials file with both tastytrade fields and a
`"fred_api_key"` entry (`creds` in `init.lsp`).

**Example** (also runnable as [`tastytrade_example.lsp`](examples/tastytrade_example.lsp) —
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
- orders, for whenever you want them.

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

#### `(schwab-orders creds [:account a :days n])`
The orders entered in the last `n` days (30, unless `:days` says;
Schwab keeps 60), in all your accounts or just `:account`'s, as a table:
`account`, `order-id`, `entered`, `status`, `instruction`, `symbol`,
`quantity`, `filled`, `type`, `price`, `duration`.

#### `(schwab-get creds path [parameters])`
The answer to any of the API's requests for information, as Lisp data.
`path` is its path, such as `"/trader/v1/userPreference"` or
`"/marketdata/v1/chains"`, and `parameters` a list of `(name . value)`
pairs. For example, every balance of every account, or a quote's
dividends and P/E:

```lisp
(schwab-get creds "/trader/v1/accounts")
(schwab-get creds "/marketdata/v1/quotes" '(("symbols" . "AAPL") ("fields" . "quote,fundamental")))
```

#### Orders: `schwab-order`, `schwab-preview-order`, `schwab-place-order`, `schwab-cancel-order`
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

`daily-returns` takes this table as its `:dividends`: see "Simulating investment prices".

### Google Sheets

(In `lisp_google.py`.) Tables, sent out to a new spreadsheet in your own
Google Drive: one tab for each table, with each column's numbers laid out
the way `display-table` lays them out. It's the way to hand a result to
someone who works in a spreadsheet, or to look at many tables at once --
all of `stratify-all`'s, say.

```lisp
(define strata (stratify-all loans '(("fico" (equal-count 5)) ("state" each)) '(("rate" weighted-mean)) :weight "balance"))
(apply google-sheet creds "Loan strata"
       '(("count" ",d") ("percent" ".1%") ("total balance" ",.0f") ("rate" ".3f"))
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
(google-sheet creds "Strata" '(("percent" ".1%") ("total balance")) strata)
```

writes every column of every table but `total balance`, with `percent`
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
`start`.

```lisp
(trading-days-between (date 2026 11 20) (date 2026 11 23))    ; => 1
(trading-days-between (date 2026 11 20) (date 2026 11 30))    ; => 5
(trading-days-between (date 2025 12 31) (date 2026 12 31))    ; => 251
```

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

[`model_utils.lsp`](lib/model_utils.lsp)'s `(model->function m)` wraps this into
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
(define formats '(("total balance" ",.0f") ("percent" ".1%") ("WAC" ".3f") ("WALA" ".1f")))

(display-table (stratify loans '("rate" (4.0 5.0 6.0 7.0)) summaries :weight "balance")
               formats)
```

prints

```
rate          count  total balance  percent    WAC  WALA
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
with `:weight`, the total weight — `total balance`, for
`:weight "balance"` — and its share of the whole, `percent` (without
`:weight`, `percent` is the share of the rows); then the summaries. The
last row is the `total`, unless `:total` is `#f`. The numbers in a
stratification table are kept in full (double) precision, unlike a big
vector's, so a total balance is exact to the cent.

```lisp
(define pool (make-table "rate" #(3.25 4.5 6.25 7.0 nan) "balance" #(100 200 300 400 50)))
(define by-rate (stratify pool '("rate" (4.0 6.0)) '(("rate" weighted-mean "WAC")) :weight "balance"))
(table-column-names by-rate)       ; => ("rate" "count" "total balance" "percent" "WAC")
(table-column by-rate "rate")      ; => #("under 4.0" "4.0 to 6.0" "6.0 and over" "missing" "total")
(table-column by-rate "count")     ; => #(1 1 2 1 5)
(table-column by-rate "total balance")   ; => #(100.0 200.0 700.0 50.0 1050.0)
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
state  rate          count  total balance  percent    WAC  WALA
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
  (display-table table '(("total balance" ",.0f") ("percent" ".1%") ("WAC" ".3f") ("WALA" ".1f")))
  (newline))
(map (lambda (t) (car (table-column-names t))) tables)   ; => ("rate" "age" "balance" "state")
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

(In `lisp_investment_paths.py`.) An investment's possible futures, made from its own
past, by a **block bootstrap**. Tomorrow is likely to be something like
the days in the investment's history, so a future is built by copying pieces of
the past, end to end. Each piece is a *block* of consecutive days, rather
than one day at a time, so that a stretch of wild days (or calm ones)
stays together, as it does in life. These functions work one after
another:

1. `daily-returns` makes a table of returns from prices (and dividends).
2. `adjust-returns` takes out those returns' average and puts in the
   return you expect.
3. `dividend-schedule`, for an investment that pays dividends, lists the
   ones to come in the days of a path.
4. `bootstrap-path` makes one path of future prices from them. Call it
   once for each path you want. With `:volatility`, a model that
   `volatility-model` makes, a path starts at today's volatility, not the
   history's average: see "Starting paths from today's volatility".
5. `option-value` is what an option is worth, from a list of paths. And
   `option-payoffs` is what many options pay at once, from a list of
   paths, for a whole option chain: see "Checking option prices against
   simulated paths".

**The returns are log returns**, ln(today's price / yesterday's), which
add up: the price after a run of days is the starting price times *e* to
the sum of the days' log returns. So changing a set of returns' average is
a matter of subtracting one number and adding another. A table of returns
has a `date` and a `log-return` column.

#### `(daily-returns prices [:dividends table])`
An investment's daily log returns: a table of `date` and `log-return`, oldest
first, with a row for each day of `prices` but the first. `prices` is a
table with `date` and `close` columns, oldest first, as `schwab-price-history`
makes.

Schwab's prices are not adjusted for dividends: on the day an investment first
trades without its dividend (its ex-date) the price drops, and the return
from prices alone is low by what the investment pays. `:dividends`, a table with
`ex-date` and `amount` columns, as `alpha-vantage-dividends` makes, puts
them back: a dividend is part of the return of its ex-date, which is
ln((close + dividend) / yesterday's close). (A dividend on a day with no
price, such as a Saturday, goes with the next day there is a price. One
before the first price, or after the last, is left out.) The returns then
are an investment's *total* return, so a path made from them is the price with
its dividends reinvested.

```lisp
(define prices (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4)))
                     (cons "close" (vector 100.0 110.0 99.0))))
(define dividends (list (cons "ex-date" (vector (date 2024 1 4)))
                        (cons "amount" (vector 1.0))))
(table-column (daily-returns prices) "date")                                             ; => #(2024-01-03 2024-01-04)
(vector-round (table-column (daily-returns prices) "log-return") 4)                      ; => #(0.0953 -0.1054)
(vector-round (table-column (daily-returns prices :dividends dividends) "log-return") 4) ; => #(0.0953 -0.0953)
```

#### `(adjust-returns returns annual-return [:days-per-year n] [:volatility-scale x])`
`returns` with its `log-return` column changed (its other columns stay as
they are): the average is taken out, then a number is added so that the
investment's **expected annual return** is `annual-return`, 0.08 for 8%.
(An investment's history has the return it happened to have; this is the
one you expect from here.)

Not just `annual-return` spread over the days, though. The price rises by
the daily returns, not by the log returns, and their average is higher
than the log returns' by about half the variance (more for one that
jumps around). So the number added makes the average of the *daily
returns* come out at (1 + `annual-return`) ^ (1 / `:days-per-year`) - 1,
the one that makes a year of them 8%. `:days-per-year` is 252 trading
days, unless said otherwise. With blocks of a single day, the paths'
average price a year out is exactly right (apart from chance); with longer
blocks, close to right. `annual-return` must be above -1 (a loss of all of
it).

For several investments' returns, as `combine-returns` makes (see
"Portfolios"), `annual-return` is one number for all of them, or a list
of `(name . annual-return)`, one for each.

`:volatility-scale` (1, no change, unless given) multiplies the returns'
spread about their average, so that the volatility is that many times the
history's: 1.2 is 20% more, and 0.8 is 20% less. The expected annual
return is still `annual-return`. It is for when the volatility to
expect isn't the history's, as `check-option-chain`'s `:match-volatility`
finds for an option chain.

```lisp
(define returns (list (cons "log-return" (vector 0.01 -0.02 0.015 0.0))))
(define adjusted (adjust-returns returns 0.08))
(format "{:.6f}" (vector-mean (vector-exp (table-column adjusted "log-return"))))   ; => "1.000305"
(format "{:.6f}" (expt 1.08 (/ 1.0 252)))                                           ; => "1.000305"
(define wilder (adjust-returns returns 0.08 :volatility-scale 2))
(format "{:.4f}" (/ (vector-stdev (table-column wilder "log-return"))
                    (vector-stdev (table-column adjusted "log-return"))))           ; => "2.0000"
(format "{:.6f}" (vector-mean (vector-exp (table-column wilder "log-return"))))     ; => "1.000305"
```

#### `(dividend-schedule dividends start-date days [:repeat-last-year #t])`
The dividends an investment will pay in the `days` trading days of a path
that starts the day after `start-date` (the date of the path's start
price): a table of `ex-date`, `day` (the ex-date's number among those
trading days, 1 for the first), and `amount`, in order, ready for
`bootstrap-path`'s `:dividends`. `dividends` is a table of `ex-date` and
`amount` columns, as `alpha-vantage-dividends` makes. The days are
counted with the NYSE's calendar, "Trading days".

- By default the schedule has the dividends of the table that come after
  `start-date`, up to the path's last day: the ones announced, if the table
  has any. (One on `start-date` is in the start price already.)
- **`:repeat-last-year #t`** supposes that the dividends of the year up to
  `start-date` go on, every year after, **on the same dates and in the same
  amounts**. A date the market is closed, such as a Saturday, is the next
  day it's open. (February 29 is February 28 in a year that isn't a leap
  year.) It is the way to look ahead for an investment that pays about the
  same dividends on about the same dates, as most do. The table's dividends
  after `start-date` aren't used with it.

A dividend that comes after the path's last day isn't in the schedule, so
an option that ends before an ex-date doesn't have its dividend taken off.

```lisp
(define actual (list (cons "ex-date" (vector (date 2025 11 14) (date 2026 2 13) (date 2026 5 15) (date 2026 8 14)))
                     (cons "amount" (vector 0.50 0.50 0.52 0.52))))
(define schedule (dividend-schedule actual (date 2026 10 5) 252 :repeat-last-year #t))
(table-column schedule "ex-date")     ; => #(2026-11-16 2027-02-16 2027-05-17 2027-08-16)
(table-column schedule "day")         ; => #(30 91 154 216)
(table-column schedule "amount")      ; => #(0.5 0.5 0.52 0.52)
```
(The four dates of a year later are Saturdays; and the Monday after the
second, February 15, 2027, is Washington's Birthday.)

#### `(bootstrap-path returns start-price days block-size [:seed n] [:dividends schedule] [:volatility model] [:start-volatility x])`
One path of future prices, as a vector of `days` prices: the first is the
day after `start-price`'s. `returns` is a table with a `log-return`
column, such as `adjust-returns` makes. The path is made of blocks of
`block-size` consecutive returns, each starting at a day of the history
picked at random, put end to end until there are `days` of them (the last
block is cut short if it has to be). The prices are what `start-price`
becomes with those returns.

- **Paths wrap.** A block that runs past the end of the history carries on
  from its start, so every day of the history is as likely as any other to
  be in a block.
- **`block-size`** is how many days stay together: 1 draws days one at a
  time, as an ordinary bootstrap does, with no memory of the day before.
  Something like 10 or 20 keeps an investment's stretches of high and low
  volatility. It can't be more than the number of returns.
- **`:seed`**, a whole number, makes the path the same every time. It has
  the function's own random numbers (as `vectors-shuffle`'s seed does),
  so it doesn't change the shared generator that `random-float` and
  `random-int` use. **Give each path its own seed**, such as `(+ 1000 i)`
  for the path numbered `i`, or every path is the same one. Without
  `:seed`, the shared generator is used, so one `(random-seed 42)` before
  you make all the paths makes them the same each time.
- **`:dividends`** is a schedule, as `dividend-schedule` makes, of the
  dividends the investment pays: when one comes, the price falls by its
  amount, in every path, whatever the price has done (to 0 at the lowest,
  and a price of 0 stays there). A dividend after the path's last day
  does nothing. The returns for such a path are **total returns**, dividends
  included, as `daily-returns` gives with `:dividends`, so that all of the
  investment's return, dividends too, grows at the rate `adjust-returns`
  was given.
- **`:volatility`** is a volatility model, as `volatility-model` makes: the
  path starts at today's volatility, and its volatility changes from day
  to day as the model says, going back toward the history's. Its days'
  returns are the history's shocks times the path's own volatility. See
  "Starting paths from today's volatility". **`:start-volatility`**, for
  a year (0.12 for 12%), starts it somewhere else, such as at the
  volatility the market expects.
- A path can't have a day more extreme than the days of the history it
  is made from, so the longer a history (that is still like the future)
  the better.

```lisp
(define returns (list (cons "log-return" (vector 0.01 -0.02 0.015 0.0 0.005))))
(vector-length (bootstrap-path returns 100 252 3))                   ; => 252
(vector-round (bootstrap-path returns 100 5 2 :seed 1) 2)            ; => #(98.02 99.5 100.0 101.01 102.02)
(equal? (bootstrap-path returns 100 5 2 :seed 1)
        (bootstrap-path returns 100 5 2 :seed 1))                    ; => #t

; two dividends, 1.50 on the 2nd day and 3.00 on the 5th, with returns that are 0:
(define flat (list (cons "log-return" (vector 0.0 0.0))))
(define dividends (list (cons "day" (vector 2 5)) (cons "amount" (vector 1.5 3.0))))
(bootstrap-path flat 100 6 1 :dividends dividends)                   ; => #(100.0 98.5 98.5 98.5 95.5 95.5)
```

A thousand paths of an investment's next year, and where they end up. This
needs a Schwab sign-in, and `examples/investment_paths_example.lsp` has it all:

```lisp
(define prices (schwab-price-history creds "BRK/A"))        ; ten years, as Schwab gives them
(define returns (adjust-returns (daily-returns prices) 0.08))
(define start-price (vector-ref (table-column prices "close") (- (table-row-count prices) 1)))
(define paths (map (lambda (i) (bootstrap-path returns start-price 252 10 :seed (+ 1000 i)))
                   (iota 1000)))                            ; a list of 1000 vectors of 252 prices
(define year-ends (list->vector (map (lambda (path) (vector-ref path 251)) paths)))
(vector-quantile (vector-div year-ends start-price) #(0.05 0.5 0.95))   ; the 5th, 50th, and 95th percentiles
```

#### `(bootstrap-days returns days block-size [:seed n] [:volatility model] [:start-volatility x])`
The days of the history a path is made of, to see how it was built: a
table of `day` (1 for the path's first), the `date` of the history's day
it copies (if the table of returns has dates), and that day's returns.
With the same `:seed`, `bootstrap-path` (and `bootstrap-paths`) make their
paths from these days: a path's price on a day is its start price times *e*
to the sum of the returns up to that day. With `:volatility`, for one
investment's returns, three columns more say how the path's returns were
made from them: `shock`, the history's day's; `volatility`, the path's
that day, for a year; and `path-return`, the path's return, which is what
its prices are made of then.

```lisp
(define returns (make-table "date" (vector (date 2024 1 3) (date 2024 1 4) (date 2024 1 5))
                            "log-return" #(-0.02 0.03 0.0)))
(table-column (bootstrap-days returns 4 2 :seed 3) "date")   ; => #(2024-01-03 2024-01-04 2024-01-05 2024-01-03)
(vector-round (bootstrap-path returns 100 4 2 :seed 3) 2)    ; => #(98.02 101.01 101.01 99.0)
```
(The second block starts on the history's last day, and carries on from
its first.)

#### `(option-value paths payoff rate years)`
What an option is worth, estimated from simulated paths of its
investment's price. `paths` is a list of paths, vectors of prices, such as
`bootstrap-path` makes. `payoff` is a procedure of one argument, a path,
that returns what the option pays at the end of it: for a call, the final
price less the strike, or 0 if that's less. The value is the payoffs'
present values averaged, each discounted for `years` at `rate`, the
interest rate, continuously compounded (0.04 for 4%, as `bsm-price`
takes it).

It returns a list of two numbers: the value, and its **standard error**,
which says how far chance may have put the value from the one these paths
are a sample of. The value is probably within two standard errors of it;
four times as many paths halve the error.

The procedure is given the whole path, so an option that depends on how the
price got there is as easy as one that depends only on where it ended.
And what's paid doesn't have to be an option's: anything paid after a
path of prices is valued the same way.

```lisp
(define returns (list (cons "log-return" (vector 0.01 -0.02 0.015 0.0 0.005 -0.01 0.02))))
(define rate 0.04)
(define fair-returns (adjust-returns returns (- (exp rate) 1)))     ; see below
(define paths (map (lambda (i) (bootstrap-path fair-returns 100 252 1 :seed i)) (iota 2000)))
(define (call-pays path) (max 0 (- (vector-ref path 251) 100)))     ; a call struck at 100, a year out
(define (show-value v) (format "{:.2f} +/- {:.2f}" (first v) (second v)))
(show-value (option-value paths call-pays rate 1))                  ; => "10.00 +/- 0.33"
(show-value (option-value paths (lambda (path) (max 0 (- (vector-mean path) 100))) rate 1))   ; => "5.77 +/- 0.18"
(show-value (option-value paths (lambda (path) (if (< (vector-min path) 90) 0 (call-pays path))) rate 1))   ; => "8.25 +/- 0.33"
```
The second is an Asian call, paid on the average price along the way, and
the third a call that is worth nothing if the price ever falls below 90.

**For a fair value, the paths must grow at the interest rate.** A price
that grows at 8% when money earns 4% makes calls look worth more, and puts
less, than anyone would pay: that is what the option pays on average if
the investment does earn 8%, not what it costs to be paid in every case.
(In a test on ten years of BRK/A, a call valued with 8% growth came out
26% higher.)

- Make the paths from `(adjust-returns returns (- (exp rate) 1))`: the
  annual return that grows a price at the continuously compounded `rate`.
- **Dividends take money out of the price, so the paths must lose it
  too.** When the investment pays dividends, make the returns *with*
  `:dividends` (they are then total returns, which `adjust-returns` makes
  grow at the interest rate, as above), and give `bootstrap-path` a
  schedule of the dividends to come. The price of every path then falls by
  the same dollar amounts on the same days, which is what known dividends
  do, and what an option on the price is paid on. A dividend after the
  option expires is not counted, because the schedule stops at the path's
  last day. For dividends not yet declared, `dividend-schedule` can suppose
  that the last year's go on, on the same dates and in the same amounts.
- **A yield, instead.** When dividends are small, regular, and spread
  through the year, as an index's are, or their dates aren't known, a
  continuous yield `q` is simpler: use returns *without* `:dividends`, and
  the annual return `(- (exp (- rate q)) 1)`.
  But a yield takes a bit of dividend off every day, and in proportion to
  the price (a path where the price doubles has doubled dividends), where
  real dividends come all at once, in set amounts. That makes little
  difference to a one-year option and its quarterly dividends, but a lot
  to one shorter than the time between them. In Black-Scholes, for a
  one-year at-the-money call at 20% volatility on 100, with four quarterly
  dividends of 0.50, a 2% yield is 0.1% from the known dividends' value;
  for a call that expires before the first ex-date it is 3.5% low, as the
  yield takes off a dividend that never comes.

```lisp
; a 3-month (63 trading days) call on an investment that pays dividends, struck at today's price
(define actual-dividends (alpha-vantage-dividends creds "SPY"))
(define prices (schwab-price-history creds "SPY"))
(define fair-returns (adjust-returns (daily-returns prices :dividends actual-dividends) (- (exp rate) 1)))
(define last-day (vector-ref (table-column prices "date") (- (table-row-count prices) 1)))
(define schedule (dividend-schedule actual-dividends last-day 63 :repeat-last-year #t))
(define start-price (vector-ref (table-column prices "close") (- (table-row-count prices) 1)))
(define paths (map (lambda (i) (bootstrap-path fair-returns start-price 63 1 :seed i :dividends schedule))
                   (iota 5000)))
(option-value paths (lambda (path) (max 0 (- (vector-ref path 62) start-price))) rate (/ 63 252.0))
```

- A path has a price for each trading day, so `years` is its days divided
  by the days in a year, as `adjust-returns` takes them (252): `years` of 1
  for 252 days.

**Block size changes the answer.** Paths of blocks of one day average a
price a year out of just what `adjust-returns` set, and agree with
Black-Scholes. Longer blocks keep what the history did over several days:
if it often fell and then recovered, as it did in March 2020, so do the
paths, and over a year they spread less than a day's spread would suggest.
In ten years of BRK/A (to October 2026), a year's at-the-money call came
out at 73,073 (+/- 736) with blocks of 1 day, 68,090 (+/- 678) with blocks
of 10, and 65,471 (+/- 634) with blocks of 21; Black-Scholes, with the
history's volatility, gave 72,350. The paths' volatility over the year was
19.1%, 18.1%, and 17.5%. (The average price a year out is also a little
low with longer blocks, 0.3% to 0.4%.) What comes out is the value if the
future is like this history, which is not the market's price: the market's
is from the volatility it expects.

**Paths with blocks of a day agree with Black-Scholes only over long
times.** The paths have the history's own returns, and those aren't
normally distributed: they have fat tails, which means more days of big
moves than a normal distribution would have, and more quiet days too, for
the same volatility. So over a few days or weeks, the paths value an option
near the money lower than the formula does, and one far out of the money
higher. Over a year, many days add up to something close to normal, and the
two agree. On October 8, 2026, for BRK/A, with 20,000 paths at the
history's 19.0% volatility and an interest rate of 4%:

```
option                      black-scholes    tree  monte-carlo  standard-error  standard-errors-apart
1 year, call at the money          72,504  72,432       72,719             733                   +0.3
1 year, put 20% below               4,775   4,782        5,063             141                   +2.0
1 month, call at the money         17,887  17,866       17,658             181                   -1.3
1 month, put 10% below                351     350          481              28                   +4.6
```

The tree (`american-price` with `:early-exercise #f`) is the formula's own
model, made of steps, so it agrees with the formula, but for having only so
many steps. `lib/option_methods.lsp` values a stock's listed options all
three ways, next to their bids and asks, and gives the chance that each
ends in the money by each: see "Valuing options three ways". For BRK/B's, at the
close of October 7, with the stock at 506.20, a call struck at 515 and
expiring in 6 trading days was worth 2.83 by the formula and 2.53 (± 0.05)
on the paths. Both were well above the market's
ask, 1.01: the market expected less volatility than the history had.

#### `(option-payoffs paths days strikes calls)`
What many European options pay, on average, over a list of paths: a table
with a row for each option, and these columns:

| Column | What it holds |
|---|---|
| `payoff` | the average of what the option pays at expiration, before discounting |
| `payoff-error` | its standard error |
| `paths-paid` | how many paths it pays something on |

`paths` is a list of paths, vectors of prices that are all the same
length. `days`, `strikes`, and `calls` are vectors with an element for
each option: `days`, the number of the path's day it expires on (1 for the
first); `strikes`; and `calls`, 1 for a call and 0 for a put. A call pays
the price on its day less the strike, if that is more than 0, and a put
the strike less the price. Discount the payoffs for the time to
expiration, as `option-value` does for one option. All the options are
valued from the same paths, so what they say about one another is not
noise.

```lisp
(define paths (list #(10.0 11.0 12.0) #(10.0 9.0 8.0) #(10.0 10.0 10.0) #(10.0 12.0 14.0)))
; a call on day 3 struck at 10, a put on day 3 at 11, a call on day 1 at 10, and a put on day 2 at 11
(define payoffs (option-payoffs paths #(3 3 1 2) #(10 11 10 11) #(1 0 1 0)))
(table-column payoffs "payoff")        ; => #(1.5 1.0 0.0 0.75)
(table-column payoffs "paths-paid")    ; => #(2 2 0 2)
```

### Starting paths from today's volatility

(In `lisp_investment_paths.py`.) A path made by `bootstrap-path` copies
blocks from anywhere in the history, so it starts out as wild as the
history is on average, however calm or wild the market is today. In
October 2026, SPY's volatility over the last month was 10%, and over the
last ten years 18%: its paths started at 18%, while the market priced the
next weeks at about 10%. A **volatility model** makes a path start at
today's volatility instead. Then the path's volatility changes from day to
day, as the model says: a big move makes the days after it wild, calm days
let it settle, and on average it goes back toward the history's. So the
paths still differ in volatility, some turning wild and some staying calm,
but they all start from today's. This is called *filtered historical
simulation*, and it works in three steps:

1. **Each day's volatility in the history is estimated** from the day
   before's, and from how big the day before's *move* was (its return less
   the average return):

   ```
   tomorrow's variance = constant
                       + up-day-weight   x today's move squared   (if it went up)
                         or down-day-weight x today's move squared (if it went down)
                       + variance-weight x today's variance
   ```

   A variance is a volatility squared, here a day's. For SPY's ten years
   to October 2026, the weights that fit best are 0.036 for an up day,
   0.236 for a down day, and 0.827 for the variance: a fall raises the
   volatility more than six times as much as a rise of the same size. The
   constant pulls the variance back toward the history's: each day, on
   average, its difference from it shrinks to its **persistence** of
   itself (0.980 for SPY), so that half of the difference is gone in its
   **half-life** (34 trading days).
2. **Each day's return becomes a shock**: its move divided by that day's
   volatility, so how many of its own standard deviations it moved. A 3%
   drop on a calm day is a big shock; on a wild day, a small one. The
   shocks keep the history's fat tails and its crashes, but not the calm or
   the wild stretch each one came in.
3. **A path is made of shocks.** It copies blocks of the history's days,
   as before, but takes their shocks: each day's return is its shock times
   the path's own volatility that day, and then the path's volatility is
   updated by the formula, with the move the path just made. It starts at
   the volatility the model gives the day after the history's last, or at
   `:start-volatility`, if that's given.

What SPY's model expected, from the close of October 6, 2026 (with
`volatility-forecast`):

| Over the next | 1 day | 1 week | 1 month | 3 months | 6 months | 1 year |
|---|---|---|---|---|---|---|
| Volatility | 9.6% | 10.0% | 11.5% | 13.8% | 15.4% | 16.7% |

```lisp
(define returns (adjust-returns (daily-returns (schwab-price-history creds "SPY")) 0.08))
(define model (volatility-model returns))
(display-table model)
(define paths (map (lambda (i) (bootstrap-path returns 100 252 10 :seed (+ 1000 i) :volatility model))
                   (iota 1000)))
```

**How the weights are found.** `volatility-model` tries every set of
weights on a grid: 0 to 0.3 for an up day, 0 to 0.5 for a down day, and
0.5 to 0.99 for the variance, 0.02 apart; then sets 0.005 apart, near the
best of those; and then 0.001 apart, near the best of them. The best set is
the one under which the history is most likely. Each day's move is
supposed to come from a normal distribution with the variance the model
gives that day, and the set that makes the moves most probable wins: its
`log-likelihood` is the highest. A big move on a day the model called
calm counts against a set of weights, and so does a wild forecast for a
quiet day. The constant isn't searched for: it is set to make the variance
go back toward the history's (*variance targeting*). A set whose
persistence would be more than 0.998 isn't taken, since its volatility
would hardly go back at all. In the usual names, the formula is a
*GJR-GARCH(1,1)* model: `up-day-weight` is alpha, `down-day-weight` is
alpha + gamma, and `variance-weight` is beta.

**Two details.** The persistence is the variance weight plus the up-day
and down-day weights, each counted for its share of the shocks' squares:
`down-share` is the share on down days (0.585 for SPY). And the shocks are
scaled so that their squares average exactly 1, as a volatility's shocks
should (they come out within a few percent of it anyway). Then a path's
volatility is the size of its moves, on average, and it goes back toward
the history's volatility.

**The paths are lopsided.** `volatility-forecast` is the square root of
the average variance: what the paths have on average, taken all together.
But a few paths turn very wild, and most stay calmer, so the typical path
is calmer than the forecast. For SPY's next 59 trading days, from October
7, 2026: the forecast was 13.7%, and the middle path's volatility 10.7%.
The paths' own implied volatility (from what an option is worth on them,
by Black's formula) was 11.4% at the money, 16.4% for a put struck 10%
below, and 9.9% for a call struck 5% above. That is a skew, like the
market's, and it comes from the down days' bigger weight and from the
crashes among the shocks. An option at the money is priced by the typical
path more than by the average one.

**What it leaves out.**

- **Correlation.** Each investment's volatility is modeled, and
  `bootstrap-paths` copies the same days' shocks for all of them, so their
  correlation is the history's. But it is the same correlation, whatever
  the volatility: in a crash, investments usually move together more than
  they do on average.
- **The weights are fitted to one history**, by one simple formula. Ten
  other years would give other weights, and the half-life especially is
  only roughly known.
- **Blocks.** With blocks of more than one day, a block's shocks are
  consecutive days, and the drift and the forecast are close to right
  rather than exact, as for `bootstrap-path`.

#### `(volatility-model returns [:symmetric #t] [:days-per-year n])`
A model of each investment's volatility, fitted to its history: a table
with a row for each column of returns (one, `log-return`, for one
investment's table; one for each investment, for `combine-returns`'). It
takes at least 100 returns, and a fraction of a second. Its columns:

| Column | What it holds |
|---|---|
| `investment` | the name of the column of returns |
| `next-day-volatility` | the volatility the model gives the day after the history's last, for a year: today's |
| `long-run-volatility` | the history's volatility, for a year, which the model's goes back toward |
| `half-life` | how many days it takes for half of a difference from the long-run variance to go, on average |
| `up-day-weight`, `down-day-weight`, `variance-weight` | the weights in the formula above |
| `persistence` | how much of a difference from the long-run variance is left the next day, on average |
| `down-share` | the share of the shocks' squares that is on down days |
| `log-likelihood` | how well the weights fit the history: the higher the better, for comparing models of the same returns |
| `days-per-year` | how many days the volatilities are for a year of: 252, unless `:days-per-year` says |

`:symmetric #t` makes the up-day and down-day weights the same: compare
the two models' `log-likelihood` to see how much better treating them
differently fits. (For SPY it was 42 higher: much better.)

A model is just a table, and you can change it: `table-add-column`
replaces a column, so `(table-add-column model "variance-weight" 0.9)` is
the same model with another weight. `bootstrap-path` uses the three
weights and `days-per-year`, and works out the rest from the returns it is
given, as `volatility-model` does. So a model of an investment's returns
works for those returns after `adjust-returns`, too: their average doesn't
matter, and if their volatility is scaled, the paths' is scaled the same
way.

```lisp
(random-seed 7)
(define (made-up-day i) (* (if (< i 250) 0.06 0.02) (- (random-float) 0.5)))   ; wild for 250 days, then calm for 50
(define history (make-table "log-return" (list->vector (map made-up-day (iota 300)))))
(define model (volatility-model history))
(vector-round (table-column model "long-run-volatility") 3)   ; => #(0.261)
(vector-round (table-column model "next-day-volatility") 3)   ; => #(0.111)
(vector-round (volatility-forecast model #(1 21 252)) 3)       ; => #(0.111 0.123 0.194)
(table-column-names (bootstrap-days history 5 2 :seed 1 :volatility model))
                                       ; => ("day" "log-return" "shock" "volatility" "path-return")
(vector-round (table-column (bootstrap-days history 5 2 :seed 1 :volatility model :start-volatility 0.5)
                            "volatility") 3)                   ; => #(0.5 0.464 0.446 0.447 0.451)
```

#### `(volatility-history returns model)`
What a volatility model says about each day of one investment's history: a
table of `date` (if the returns have dates), the returns, `volatility` (the
model's estimate of the day's volatility, made the day before, for a
year), and `shock` (the day's move divided by that, as a day's). Chart
`volatility` against `date` to see the history's calm and wild stretches.
The shocks are what the paths copy, and their squares average 1.

```lisp
(define days (volatility-history history model))
(table-column-names days)                     ; => ("log-return" "volatility" "shock")
(< (abs (- (vector-mean (* (table-column days "shock") (table-column days "shock"))) 1)) 0.000001)   ; => #t
```

#### `(volatility-forecast model days [:start-volatility x])`
The volatility a model expects over the next `days` days, on average, for
a year: a number, or for a vector of days, a vector. `model` is one
investment's, a table of one row: `(table-where model "investment" "SPY")`
picks one from a model of several. The first day's volatility is the
model's `next-day-volatility`, or `:start-volatility`. After that, the
variance's difference from the long-run variance shrinks to `persistence`
of itself each day, so the average variance of the first *n* days is

    long-run + (first day's - long-run) x (1 - persistence^n) / (n x (1 - persistence))

and the forecast is its square root. It uses only `next-day-volatility`,
`long-run-volatility`, and `persistence`. With a persistence of 0, the
variance is back to the long run's the second day:

```lisp
(define made-up (make-table "investment" #("log-return") "next-day-volatility" #(0.1)
                            "long-run-volatility" #(0.2) "persistence" #(0.0)))
(vector-round (volatility-forecast made-up #(4)) 4)       ; => #(0.1803)
```
(The square root of (0.1² + 3 × 0.2²) / 4.)

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
