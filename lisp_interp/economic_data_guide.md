# Economic and financial data: what there is, and how to get it

This memo is for anyone who wants economic or financial numbers from this
Lisp interpreter but doesn't know which government agency publishes what.

- Start with [Where to find it](#2-where-to-find-it). It's organized by
  question, and each row gives the function that gets the number and where
  the number comes from.
- [Who publishes what](#3-who-publishes-what) says what each source is.
- [Numbers that are easy to mix up](#4-numbers-that-are-easy-to-mix-up)
  sorts out numbers that sound alike: two inflation rates, two counts of
  jobs, three kinds of income.

Every function is described fully in the library manual,
[lisp_library_reference.md](lisp_library_reference.md).

1. [Setting up](#1-setting-up)
2. [Where to find it](#2-where-to-find-it)
3. [Who publishes what](#3-who-publishes-what)
4. [Numbers that are easy to mix up](#4-numbers-that-are-easy-to-mix-up)
5. [When the numbers come out](#5-when-the-numbers-come-out)
6. [Putting sources together](#6-putting-sources-together)
7. [Every data function](#7-every-data-function)

## 1. Setting up

The data comes from the agencies' own websites, through their APIs. All of
it is free, except market prices, which come from a brokerage account
(tastytrade). Most sources want a *key*: a code that says who's asking.
Each gives one to anyone who asks for it, by email, in a minute or two.

Keep the keys in one JSON file, the *credentials file*, somewhere private.
Never put it in a repository.

```json
{
  "bureau_of_labor_statistics_api_key": "...",
  "bea_api_key": "...",
  "us_census_api_key": "...",
  "fred_api_key": "...",
  "fdic_api_key": "...",
  "sec_user_agent": "Your Name you@example.com"
}
```

| Entry | For | Where to get it |
|---|---|---|
| `bureau_of_labor_statistics_api_key` | Bureau of Labor Statistics | https://data.bls.gov/registrationEngine/ |
| `bea_api_key` | Bureau of Economic Analysis | https://apps.bea.gov/API/signup/ |
| `us_census_api_key` | Census Bureau | https://api.census.gov/data/key_signup.html |
| `fred_api_key` | FRED, the Federal Reserve Bank of St. Louis's data | https://fred.stlouisfed.org/docs/api/api_key.html |
| `fdic_api_key` | FDIC (optional) | https://api.fdic.gov/banks/docs/ |
| `sec_user_agent` | SEC. There's no key, but the SEC asks every program to send a name and an email address. | — |
| `client_secret`, `refresh_token` | tastytrade, a brokerage account | see `tasty_api/README.md` |
| `Schwab_Client_ID`, `Schwab_Client_Secret` | Charles Schwab, a brokerage account: your app's key and secret | https://developer.schwab.com; then sign in once a week with `(schwab-login creds)` |
| `google_client_id`, `google_client_secret` | Google Sheets (`google-sheet`): your app's client ID and secret | set up once at https://console.cloud.google.com ("Google Sheets", in `lisp_library_reference.md`, says how); then sign in with `(google-login creds)` |

Maps' outlines (`census-shapes`) need no key.

Then tell the interpreter where the file is. Put this line in `init.lsp`,
next to `lisp_interpreter.py`, which the interpreter loads every time it
starts:

```lisp
(define creds "/Users/you/credentials.json")
```

Every function below takes `creds` first, except `census-shapes`, which
doesn't need it.

Good to know:

- **Results are tables.** Each function gives a table: a row for each date
  (or place, or company) and a column for each number. `display-table`
  shows a table, `plot-chart` charts it, and `plot-map` maps it.
- **Downloads are kept.** A download is saved on disk for 12 hours, and
  lists of what there is for 30 days. Running a notebook again is quick
  and doesn't use up a source's daily allowance. A download that fails in
  a way that may pass (no answer, or the server's own trouble) is tried
  once more before giving up.
- **Maps' outlines are kept for good,** since they never change, in
  `~/.cache/morris_lisp/maps`. Delete the files there to free the space.
- **Limits.** The BLS allows 500 requests a day, and the BEA 100 a minute.
  The others are generous.

## 2. Where to find it

Each table below gives what you might want to know, how to ask for it, and
where it comes from. If a number isn't listed, look in its source's own
list; [Who publishes what](#3-who-publishes-what) says how to search each
one.

### The economy as a whole

| To know | Ask | From |
|---|---|---|
| GDP: the value of everything the country produces | `(bea-series creds "gdp")` | BEA |
| How fast the economy is growing | `(bea-series creds "real-gdp-growth")` | BEA |
| What made it grow: consumers, businesses, government, trade | `(bea-nipa creds "T10102" :lines '(1 2 7 15 22))` | BEA |
| Industrial production: factories, mines, utilities | `(fred-table creds "INDPRO")` | Federal Reserve, via FRED |
| How consumers feel | `(fred-table creds "UMCSENT")` | University of Michigan, via FRED |
| Corporate profits, all companies together | `(bea-series creds "corporate-profits")` | BEA |
| GDP of each state | `(bea-regional creds "SAGDP1" 3 "STATE")` (line 1 is real GDP) | BEA |

### Prices and inflation

| To know | Ask | From |
|---|---|---|
| Consumer prices (the CPI): the inflation rate in the news | `(bls-series creds '("cpi" "core-cpi"))` | BLS |
| The Federal Reserve's measure of inflation (the PCE price index) | `(bea-series creds '("pce-price-index" "core-pce-price-index"))` | BEA |
| The prices of food, rent, and other things | `(bls-series creds '("cpi-food" "cpi-rent"))` | BLS |
| What producers get for what they sell (the PPI) | `(bls-series creds "ppi-final-demand")` | BLS |
| Import and export prices | `(bls-series creds '("import-prices" "export-prices"))` | BLS |
| How expensive each state is, compared with the country as a whole (100) | `(bea-regional creds "SARPP" 1 "STATE")` | BEA |
| Home prices | `(fred-table creds "CSUSHPINSA")` (the Case-Shiller index) | S&P CoreLogic, via FRED |
| The price of oil | `(fred-table creds "DCOILWTICO")` | Energy Information Administration, via FRED |

Price measures are *index numbers*: the CPI is 100 for 1982–84. Inflation
is the change from a year before: `(vector-pct-change column 12)` works it
out, as [section 6](#6-putting-sources-together) shows.

### Jobs and pay

| To know | Ask | From |
|---|---|---|
| The unemployment rate | `(bls-series creds "unemployment-rate")` | BLS |
| How many jobs there are (payrolls) | `(bls-series creds "nonfarm-payrolls")` | BLS |
| Jobs in an industry: health care, construction | `(bls-series creds '("CES6562000001" "CES2000000001"))` | BLS |
| Pay | `(bls-series creds '("average-hourly-earnings" "employment-cost-index"))` | BLS |
| Job openings, hires, and quits | `(bls-series creds '("job-openings" "hires" "quits"))` | BLS |
| How many people are working or looking for work | `(bls-series creds '("labor-force-participation" "employment-population-ratio"))` | BLS |
| Unemployment in a state or county | `(bls-local-area creds "36061")` (Manhattan) | BLS |
| Jobs in a state | `(bls-series creds "SMS36000000000000001")` (New York) | BLS |
| Productivity | `(bls-series creds "productivity")` | BLS |

### Income, spending, and saving

| To know | Ask | From |
|---|---|---|
| Americans' total income (personal income) | `(bea-series creds '("personal-income" "disposable-income"))` | BEA |
| What consumers spend | `(bea-series creds "pce")` | BEA |
| How much of their income people save | `(bea-series creds "personal-saving-rate")` | BEA |
| Retail sales | `(fred-table creds "RSAFS")` | Census, via FRED |
| Consumer debt: credit cards, car loans, student loans | `(fred-table creds "TOTALSL")` | Federal Reserve, via FRED |
| Income per person in each state or county | `(bea-regional creds "CAINC1" 3 "NY")` (New York's counties) | BEA |
| The typical household's income, and poverty, in any place | `(census-profile creds "county:*" :within "state:36")` | Census |

### Interest rates and money

| To know | Ask | From |
|---|---|---|
| The Federal Reserve's interest rate (federal funds) | `(fred-table creds "FEDFUNDS")` (monthly; `"DFF"` is daily) | Federal Reserve, via FRED |
| SOFR, the rate that sets floating-rate loans | `(fred-table creds "SOFR")` | New York Fed, via FRED |
| Treasury yields | `(fred-table creds "DGS10")` (10 years; also `"DGS3MO"`, `"DGS2"`, `"DGS30"`) | Treasury, via FRED |
| The slope of the yield curve: 10 years less 2 | `(fred-table creds "T10Y2Y")` | FRED |
| Mortgage rates: 30 years, fixed | `(fred-table creds "MORTGAGE30US")` | Freddie Mac, via FRED |
| The money supply (M2) | `(fred-table creds "M2SL")` | Federal Reserve, via FRED |
| The Federal Reserve's balance sheet | `(fred-table creds "WALCL")` | Federal Reserve, via FRED |
| Banks' loans to businesses | `(fred-table creds "BUSLOANS")` | Federal Reserve, via FRED |
| Exchange rates: dollars per euro, and the dollar against all currencies | `(fred-table creds "DEXUSEU")`, `(fred-table creds "DTWEXBGS")` | Federal Reserve, via FRED |
| The Treasury's whole yield curve, each day | `http-get-csv`, from the Treasury's site (see the library manual's [Downloading data from the web](lisp_library_reference.md#downloading-data-from-the-web)) | Treasury |

### Housing

| To know | Ask | From |
|---|---|---|
| Home values, rents, homeownership, and vacancy, in any place | `(census-profile creds "county:*" :within "state:36")` | Census |
| Housing starts | `(fred-table creds "HOUST")` | Census, via FRED |
| Home prices | `(fred-table creds "CSUSHPINSA")` | S&P CoreLogic, via FRED |
| Mortgage rates | `(fred-table creds "MORTGAGE30US")` | Freddie Mac, via FRED |
| How fast rents are rising | `(bls-series creds "cpi-rent")` | BLS |

### People and places

| To know | Ask | From |
|---|---|---|
| Population, age, race, education, income, and housing of any place | `(census-profile creds "state:*")` | Census |
| Any of the American Community Survey's 28,000 numbers | `(census-variables creds "acs/acs5" "commute")` to find one, then `census-get` | Census |
| Exact counts from the 2020 census | `(census-get creds "dec/dhc" '("NAME" "P1_001N") "state:*" :year 2020)` | Census |
| The population of each state, each year | `(bea-regional creds "SAINC1" 2 "STATE")` | BEA |
| The outlines of states, counties, tracts, and ZIP code areas, for maps | `(census-shapes "county")` | Census |

### Businesses and industries

| To know | Ask | From |
|---|---|---|
| How many businesses, workers, and payroll in each county | `(census-get creds "cbp" '("NAME" "ESTAB" "EMP" "PAYANN") "county:*" :within "state:36" :predicates '(("NAICS2017" . "00")))` | Census (County Business Patterns) |
| Jobs in each industry, each month | `(bls-series creds "CES4200000001")` (retail) | BLS |
| GDP by industry | `(bea-get creds "GDPbyIndustry" '(("TableID" . "1") ("Frequency" . "A") ("Year" . "2024") ("Industry" . "ALL")))` | BEA |

### Banks

| To know | Ask | From |
|---|---|---|
| A bank's certificate number, from its name | `(fdic-find-bank creds "wells fargo")` | FDIC |
| A bank's balance sheet, income, and ratios | `(fdic-balance-sheet creds 3511)`, `(fdic-income-statement creds 3511)`, `(fdic-ratios creds 3511)` | FDIC |
| Banks that have failed | `(fdic-get creds "failures" '(("filters" . "FAILDATE:[2023-01-01 TO *]")))` | FDIC |
| All banks' lending together | `(fred-table creds "BUSLOANS")` | Federal Reserve, via FRED |

### Companies and markets

| To know | Ask | From |
|---|---|---|
| A company's income statement, balance sheet, or cash flows | `(sec-income-statement creds "AAPL")`, `(sec-balance-sheet creds "AAPL")`, `(sec-cash-flow-statement creds "AAPL")` | SEC |
| All three statements, laid out for working out margins and returns | `(sec-financials creds "KO")` | SEC |
| Any other number a company reports | `(sec-concepts creds "AAPL")` to find it, then `sec-facts` | SEC |
| Stock, ETF, option, futures, and crypto prices now | `(tastytrade-quotes creds '("SPY" "QQQ"))` | tastytrade |
| A stock's or ETF's daily prices, for years | `(schwab-price-history creds "AAPL")` | Schwab |
| What's in your own accounts | `(schwab-positions creds)` | Schwab |
| An option chain | `(tastytrade-option-chain creds "SPY")`; `fit-vol-smiles` then finds options priced out of line | tastytrade |
| A futures curve: oil, gold, the S&P 500, ... | `(tastytrade-futures-curve creds "CL")` | tastytrade |
| The stock market as a whole | `(fred-table creds "SP500")` (the last 10 years), `(fred-table creds "VIXCLS")` (its volatility) | S&P and Cboe, via FRED |

### Trade with other countries

| To know | Ask | From |
|---|---|---|
| The trade balance: exports less imports | `(fred-table creds "BOPGSTB")` | Census and BEA, via FRED |
| Import and export prices | `(bls-series creds '("import-prices" "export-prices"))` | BLS |
| Trade in each product | `census-get` with the dataset `"timeseries/intltrade/exports/hs"` | Census |
| All transactions with the rest of the world | `bea-get` with the dataset `"ITA"` | BEA |

## 3. Who publishes what

**Bureau of Labor Statistics (BLS)**, part of the Department of Labor. It
publishes prices and jobs:

- the CPI, the PPI, and import and export prices;
- the monthly jobs report: the unemployment rate (from a survey of
  households) and payrolls, hours, and pay (from a survey of employers);
- job openings and quits, the employment cost index, and productivity;
- unemployment in every state, metro area, and county.

Every number is a *series* with an ID, such as `CUSR0000SA0` for the CPI.
`bls-names` lists short names for the main ones, and the BLS's Data Finder
(https://data.bls.gov/dataQuery/) finds the rest. Functions: `bls-series`,
`bls-local-area`.

**Bureau of Economic Analysis (BEA)**, part of the Department of Commerce.
It publishes:

- the national accounts: GDP and its parts, personal income, consumer
  spending and saving, the PCE price index, and corporate profits;
- the regional accounts: GDP and personal income for every state, county,
  and metro area, and how expensive each state is;
- trade, international investment, and GDP by industry.

Its numbers are in numbered tables; `bea-parameter-values` finds them.
Functions: `bea-series`, `bea-nipa`, `bea-regional`, `bea-get`.

**Census Bureau**, also part of the Department of Commerce. It counts and
describes people, households, and homes in every place, down to
neighborhoods. Its sources are:

- the American Community Survey, every year;
- the census itself, every ten years;
- population estimates.

It also publishes:

- counts of businesses (County Business Patterns);
- monthly indicators: retail sales, housing starts, construction
  spending, factory orders, and trade;
- the outlines of every state, county, and neighborhood, for maps.

`census-datasets` and `census-variables` find what's there. Functions:
`census-profile`, `census-get`, `census-shapes`.

**Federal Reserve**, the central bank. It sets the federal funds rate. It
publishes interest rates, the money supply, bank lending, consumer credit,
industrial production, and its own balance sheet. Here, these come
through FRED.

**FRED** (Federal Reserve Economic Data), a library run by the Federal
Reserve Bank of St. Louis. It holds hundreds of thousands of series from
many sources, all under one kind of ID: the Fed's own data, Treasury
yields, exchange rates, and copies of most of the BLS's, BEA's, and
Census's main series. When you know a national number's FRED ID, FRED is
the easiest way to get it; search https://fred.stlouisfed.org to find the
ID. For numbers about places, and for detail, go to the agency itself.
Function: `fred-table`.

**Treasury** and **New York Fed.** The Treasury publishes the daily yield
curve; the New York Fed publishes SOFR. FRED has both. To get them
straight from the source, see the library manual's
[Downloading data from the web](lisp_library_reference.md#downloading-data-from-the-web)
(`http-get-csv`, `http-get-json`).

**SEC** (Securities and Exchange Commission). It publishes every public
company's filings: annual reports (10-K) and quarterly reports (10-Q),
with their financial statements. Functions: `sec-income-statement`,
`sec-balance-sheet`, `sec-cash-flow-statement`, `sec-financials`,
`sec-facts`.

**FDIC** (Federal Deposit Insurance Corporation). It insures bank deposits.
It publishes every insured bank's quarterly financial report (its *Call
Report*) back to 1984, the banks that have failed, and each branch's
deposits. Functions: `fdic-find-bank`, `fdic-balance-sheet`,
`fdic-income-statement`, `fdic-ratios`, `fdic-financials`, `fdic-get`.

**Schwab**, a brokerage: what's in your accounts, quotes, and years of
daily prices for any stock or ETF. It needs your account and a sign-in
each week. Functions: `schwab-positions`, `schwab-accounts`,
`schwab-quotes`, `schwab-price-history`.

**tastytrade**, a brokerage, not a government agency. It gives what
markets are trading at now: stocks, ETFs, options, futures, and crypto.
It needs an account; here, it only reads. Functions: `tastytrade-quotes`,
`tastytrade-option-chain`, `tastytrade-futures-curve`, `tastytrade-get`.

## 4. Numbers that are easy to mix up

**Two measures of inflation.**

- The **CPI** (BLS) is what urban consumers pay for a basket of goods and
  services.
- The **PCE price index** (BEA) covers everything spent by and for
  households, including what employers and the government pay for their
  health care. It also follows people as they switch what they buy.

The PCE usually runs a few tenths of a percentage point lower. The news
reports the CPI; the Federal Reserve's 2% goal is for the PCE. *Core*
leaves out food and energy, whose prices jump around.

**Two counts of jobs.** The monthly jobs report has two surveys:

- a survey of **households** gives the unemployment rate and labor force
  participation;
- a survey of **employers** gives payrolls, hours, and pay.

They can disagree for a month or two.

The Census's American Community Survey has an unemployment rate too, but
it's an average over five years; use the BLS's for now. When this was
written, Manhattan's rate was 7.6% in the ACS for 2020–2024, which
includes the pandemic, but 4.7% from the BLS for August 2026.

**Three kinds of income.**

- **The Census:** a household's income. The *median* is the household in
  the middle (`census-profile`).
- **The BEA's personal income:** all the income of everyone in a place,
  including employers' payments for health insurance and pensions,
  interest and dividends, and Social Security. *Per capita* is that
  divided by the number of people (`bea-regional`, `bea-series`).
- **The BLS:** what jobs pay, as average hourly earnings and the
  employment cost index.

In Manhattan, the median household's income was $103,931 (ACS,
2020–2024), but personal income per person was $217,075 (BEA, 2024). A
few very high incomes raise the average but not the median, and a
household often has more than one person.

**Annual rates.** The BEA states quarterly and monthly amounts *at an
annual rate*. GDP of $32.6 trillion for a quarter means the quarter's
output at a full year's pace, about four times what the quarter itself
produced. Growth at an annual rate is the quarter's growth compounded
over a year: 0.55% in a quarter is 2.2% at an annual rate.

**Real and nominal.** *Real* means adjusted for inflation. Real GDP is in
chained 2017 dollars, so it can be compared across years; plain
("current" or "nominal") dollars can't.

**Seasonally adjusted.** Many numbers rise and fall with the seasons:
retail sales in December, construction in winter. *Seasonally adjusted*
numbers have that taken out, so one month can be compared with the one
before. In BLS IDs, the S in `CUSR0000SA0` means seasonally adjusted and
the U in `CUUR0000SA0` means not. A county's unemployment isn't adjusted.

**Estimates are revised.**

- GDP is estimated three times in the three months after a quarter, then
  revised again in later years.
- Payrolls are revised for two months, then once a year.

So numbers downloaded today can differ from last month's.

**Surveys have margins of error.** The American Community Survey asks a
sample of households, so its numbers are estimates, and for a small place
they can be far off.

- A 5-year estimate (`acs/acs5`) averages five years of answers, so even
  small places have enough of them.
- A 1-year estimate (`acs/acs1`) is more current, but only covers places
  of 65,000 people or more.
- Each ACS variable that ends in E (an estimate) has a partner that ends
  in M, its margin of error: `B19013_001E` and `B19013_001M`.

**Index numbers.** A price index is a level: the CPI is 100 for 1982–84,
and the PCE price index is 100 for 2017. What matters is how it changes:
inflation is the percent change from a year before.

**A bank and its holding company.** The FDIC's numbers are for each
insured bank (Wells Fargo Bank, N.A.). A publicly traded holding company
(Wells Fargo & Company) files with the SEC, and its statements include
all its subsidiaries.

**FRED's copies.** FRED's `UNRATE` is the BLS's unemployment rate, and its
`GDP` is the BEA's. They're the same numbers: when this was written,
FRED's GDP for the second quarter of 2026 matched the BEA's $32,563
billion. Use whichever is easier.

## 5. When the numbers come out

The dates below are approximate.

| Number | From | When |
|---|---|---|
| The jobs report: unemployment, payrolls, pay | BLS | The first Friday of each month, for the month before |
| CPI and PPI | BLS | Around the middle of each month, for the month before |
| Job openings, hires, and quits | BLS | About five weeks after the month ends |
| GDP | BEA | About four weeks after each quarter ends; then revised a month later, and again a month after that |
| Personal income and spending, the PCE price index, the saving rate | BEA | Near the end of each month, for the month before |
| Corporate profits | BEA | About two months after each quarter |
| States' GDP and personal income | BEA | About three months after each quarter |
| Counties' personal income | BEA | Each November, for the year before |
| Retail sales, housing starts | Census | Around the middle of each month, for the month before |
| American Community Survey, 1-year | Census | Each September, for the year before |
| American Community Survey, 5-year | Census | Each December, for the five years ending the year before |
| Banks' Call Reports | FDIC | About two months after each quarter |
| Companies' reports | SEC | A 10-Q within 40–45 days after each quarter; a 10-K within 60–90 days after the year |
| Interest rates, exchange rates | Federal Reserve, Treasury | Every business day |

The agencies' calendars:

- BLS: https://www.bls.gov/schedule/
- BEA: https://www.bea.gov/news/schedule
- Census: https://www.census.gov/economic-indicators/

## 6. Putting sources together

**Dates line up.** Every function dates a value by the first day of its
period: a month's first day, a quarter's first day (the second quarter is
April 1), or January 1 for a year. `plot-chart` puts dates on a calendar,
so monthly, quarterly, and daily numbers from different sources share a
chart. Here are growth (BEA), unemployment (BLS), and the 10-year Treasury
yield (FRED), in three panels sharing one axis of dates:

```lisp
(define growth (bea-series creds "real-gdp-growth" :start-year 2015))
(define jobs (bls-series creds "unemployment-rate" :start-year 2015))
(define ten-year (fred-table creds "DGS10" :start-date "2015-01-01"))
(plot-panels (list (list (list (list "real GDP growth" (table-column growth "date")
                                     (table-column growth "real-gdp-growth") :bars #t))
                         :y-label "percent, annual rate")
                   (list (list (list "unemployment" (table-column jobs "date")
                                     (table-column jobs "unemployment-rate")))
                         :y-label "percent")
                   (list (list (list "10-year Treasury" (table-column ten-year "date")
                                     (table-column ten-year "DGS10")))
                         :y-label "percent"))
             :title "Growth (BEA), jobs (BLS), and interest rates (FRED)" :legend #f
             :shade (list (list (date 2020 2 1) (date 2020 4 30) "recession")))
```

**Inflation, from price indexes.** Inflation is an index's change from
12 months before, which `vector-pct-change` works out, as a fraction
(`0.03` is 3%). This charts it for the CPI (BLS) and the PCE price index
(BEA):

```lisp
(define cpi (bls-series creds '("cpi" "core-cpi") :start-year 2018))
(define pce (bea-series creds '("pce-price-index" "core-pce-price-index") :start-year 2018))

; A price index's inflation, as a series for plot-chart: (name dates changes)
(define (inflation table name)
  (list name (table-column table "date") (vector-pct-change (table-column table name) 12)))

(plot-chart (list (inflation cpi "cpi") (inflation cpi "core-cpi")
                  (inflation pce "pce-price-index") (inflation pce "core-pce-price-index"))
            :title "Inflation, measured two ways" :y-format "{:.0%}"
            :y-lines (list (list 0.02 "the Fed's goal: 2%, measured by the PCE")))
```

**Places line up by their FIPS codes.** Every state and county has a code.
A state's is 2 digits (New York is 36); a county adds 3 more (Manhattan,
New York County, is 061, so 36061 in all).

- `census-get` and `census-profile` give the state's and the county's
  codes in separate columns, `state` and `county`.
- `bls-local-area` takes the 5-digit code, or a list of them.
- `bea-regional` gives 5 characters: a county's code, or a state's code
  followed by 000 (`36000`).
- `census-shapes` gives each place's code as `GEOID`, and `plot-map`
  matches any of these.

This puts Census and BEA numbers for New York's counties side by side:

```lisp
(define people (census-profile creds "county:*" :within "state:36"))
(define fips (list->vector (map string-append (vector->list (table-column people "state"))
                                              (vector->list (table-column people "county")))))
(define people (table-add-column people "fips" fips))
(define income (bea-regional creds "CAINC1" 3 "NY" :start-year 2024 :end-year 2024))
(define both (table-join people income "fips"))
(display-table (table-head (table-sort (table-select both '("name" "median-household-income" "2024"))
                                       "2024" #t)
                           5)
               '(("median-household-income" ",") ("2024" ",")))
```

**Maps.** `plot-map` draws places from `census-shapes` with an equal-area
projection. Places can be colored by one value, and a symbol drawn on
each can be sized by another, matched to the places by these codes. This
map colors every county by its per capita income (BEA), with the states'
borders drawn over it:

```lisp
(define income (bea-regional creds "CAINC1" 3 "COUNTY" :start-year 2024 :end-year 2024))
(plot-map (census-shapes "county") :data income :key "fips" :fill "2024" :log #t :colors "YlGnBu"
          :format "${:,.0f}" :fill-label "per capita income" :borders (census-shapes "state")
          :title "Per capita personal income, 2024")
```

[`examples/map_example.lsp`](examples/map_example.lsp) has more maps:

- states colored by their poverty rate, with circles sized by their GDP;
- a circle on each of New York's ZIP code areas, sized by its population;
- Manhattan's census tracts, colored by median household income.

## 7. Every data function

| Functions | What they give | From | In the library manual |
|---|---|---|---|
| `bls-series`, `bls-series-info`, `bls-names`, `bls-local-area` | Prices, jobs, and pay, by date | BLS | [BLS data](lisp_library_reference.md#bls-data) |
| `bea-series`, `bea-names`, `bea-nipa`, `bea-nipa-lines` | The national accounts, by date | BEA | [BEA data](lisp_library_reference.md#bea-data) |
| `bea-regional`, `bea-regional-lines` | The regional accounts, by place | BEA | [BEA data](lisp_library_reference.md#bea-data) |
| `bea-get`, `bea-datasets`, `bea-parameters`, `bea-parameter-values` | Anything else the BEA has | BEA | [BEA data](lisp_library_reference.md#bea-data) |
| `census-profile` | A standard profile of any place | Census | [Census data](lisp_library_reference.md#census-data) |
| `census-get`, `census-variables`, `census-geographies`, `census-datasets` | Any Census dataset | Census | [Census data](lisp_library_reference.md#census-data) |
| `census-shapes`, `plot-map` | Outlines of places, and maps of them | Census | [Maps](lisp_library_reference.md#maps) |
| `fred-table` | Any FRED series, by date | FRED | [FRED](lisp_library_reference.md#fred-federal-reserve-bank-of-st-louis-data) |
| `http-get-json`, `http-get-csv`, `http-get-text` | Anything at a web address | any website | [Downloading data from the web](lisp_library_reference.md#downloading-data-from-the-web) |
| `sec-income-statement`, `sec-balance-sheet`, `sec-cash-flow-statement`, `sec-financials`, `sec-facts`, `sec-concepts`, `sec-company` | Companies' financial statements | SEC | [SEC financial statements](lisp_library_reference.md#sec-financial-statements) |
| `fdic-find-bank`, `fdic-balance-sheet`, `fdic-income-statement`, `fdic-ratios`, `fdic-financials`, `fdic-get`, `fdic-fields` | Banks' financial reports | FDIC | [FDIC bank data](lisp_library_reference.md#fdic-bank-data) |
| `tastytrade-quotes`, `tastytrade-option-chain`, `tastytrade-futures-curve`, `tastytrade-get`, `sofr-calibration-data` | Market prices, option chains, futures curves | tastytrade | [tastytrade](lisp_library_reference.md#tastytrade-real-broker-data) |
| `schwab-login`, `schwab-accounts`, `schwab-positions`, `schwab-quotes`, `schwab-price-history`, `schwab-orders` | Your accounts' holdings; quotes; years of daily prices | Schwab | [Schwab](lisp_library_reference.md#schwab-your-accounts) |

Example programs in [`examples/`](examples/) show each source at work:

- `census_bls_example.lsp`
- `bea_example.lsp`
- `fred_example.lsp`
- `sec_example.lsp`
- `fdic_example.lsp`
- `map_example.lsp`
- `tastytrade_example.lsp`
- `option_chain_example.lsp`
- `vol_smile_example.lsp`

**What isn't here:**

- Price histories for individual stocks without a Schwab account. FRED
  has the S&P 500 for the last 10 years, and tastytrade gives prices as of
  now.
- Most numbers about other countries' economies. FRED has some.
- Loan-level data, such as individual mortgages.
