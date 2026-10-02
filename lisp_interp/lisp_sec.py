"""Financial statements from the SEC, for the Lisp interpreter.

Every 10-K and 10-Q a company files with the SEC has its numbers tagged in
XBRL -- an XML format in which each number is a "fact": a concept from a
standard list (the US-GAAP taxonomy: NetIncomeLoss, Assets, ...), a value,
a unit, and the period it covers. The SEC collects every fact a company
has ever filed into one JSON file, its "company facts"
(https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
which saves reading the XML filings one by one. These builtins download
that file and put the facts into tables:

  (sec-company creds ticker)            the company's name and CIK number
  (sec-concepts creds ticker)           every concept it has reported
  (sec-facts creds ticker concept)      every value reported for one concept
  (sec-income-statement creds ticker [:period :count :in-millions])
  (sec-balance-sheet creds ticker [...])
  (sec-cash-flow-statement creds ticker [...])
  (sec-financials creds ticker [:period :count])   all three, a row per period

NORMALIZED: companies don't all tag a number the same way. Revenue is
Revenues for some, RevenueFromContractWithCustomerExcludingAssessedTax for
others -- and Apple switched from one to the other in 2018. So each line
of the statements (LINE_ITEMS, below) has a list of concepts to try, in
order, for each period; and a few lines that a company may not report
directly, such as gross profit or total liabilities, are worked out from
others when they're missing. Companies that file IFRS statements (some
foreign companies) report in the ifrs-full taxonomy instead, and the main
lines try its concepts too.

PERIODS: a fiscal year is the period an annual report (10-K, 20-F, 40-F)
covers. A quarter's income and cash flows come from its 10-Q -- or, when
the 10-Q gives only the year to date (as cash flow statements do), or
there's no 10-Q (the fourth quarter), from the difference of two
year-to-date figures: the fourth quarter is the year less the first
three quarters. When a number was reported more than once (as last year's
column of this year's report, say), the most recently filed one is used,
so restatements are picked up.

The SEC asks that every request identify who's making it, with a name
and an email address: the "sec_user_agent" entry in the credentials file,
such as "Jane Smith jane@example.com". Downloads are kept for 12 hours
(in lisp_http's cache, which (http-clear-cache) empties), so asking for
several statements of one company downloads its facts once.
"""

import datetime
import json
import time

from lisp_core import LispDate, LispError, LispHashTable, LispString, Pair, list_to_pairs
from lisp_data_common import credential
from lisp_stratify import keyword_options
from lisp_tables import column_vector, make_table_value
import lisp_http

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json"
CACHE_HOURS = 12

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
YEAR_DAYS = (340, 390)        # how long a fiscal year can be, in days (52/53-week years, too)
QUARTER_DAYS = (80, 100)      # and a quarter


# ---------------------------------------------------------------------------
# The line items of the normalized statements
# ---------------------------------------------------------------------------
# Each is (key, label, statement, concepts, difference-of). The concepts
# are tried in order, for each period; a name without a taxonomy is a
# us-gaap concept. If none of them has a value, and difference-of is given
# -- two other items' keys, (a, b) -- the line is worked out as a less b.


LINE_ITEMS = [
    # The income statement, for a period of time
    ("revenue", "Revenue", "income",
     ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
      "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
      "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense", "ifrs-full:Revenue",
      "ifrs-full:RevenueFromContractsWithCustomers", "ifrs-full:RevenueFromSaleOfGoods"], None),
    ("cost-of-revenue", "Cost of revenue", "income",
     ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices",
      "ifrs-full:CostOfSales"], None),
    ("gross-profit", "Gross profit", "income",
     ["GrossProfit", "ifrs-full:GrossProfit"], ("revenue", "cost-of-revenue")),
    ("research-and-development", "Research and development", "income",
     ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"], None),
    ("selling-general-and-administrative", "Selling, general and administrative", "income",
     ["SellingGeneralAndAdministrativeExpense"], None),
    ("operating-expenses", "Operating expenses", "income", ["OperatingExpenses"], None),
    ("operating-income", "Operating income", "income",
     ["OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"], None),
    ("interest-expense", "Interest expense", "income",
     ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"], None),
    ("pretax-income", "Income before taxes", "income",
     ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic", "ifrs-full:ProfitLossBeforeTax"], None),
    ("income-tax", "Income tax", "income",
     ["IncomeTaxExpenseBenefit", "ifrs-full:IncomeTaxExpenseContinuingOperations"], None),
    ("net-income", "Net income", "income",
     ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss",
      "ifrs-full:ProfitLossAttributableToOwnersOfParent", "ifrs-full:ProfitLoss"], None),
    ("eps-basic", "Earnings per share, basic", "income",
     ["EarningsPerShareBasic", "ifrs-full:BasicEarningsLossPerShare"], None),
    ("eps-diluted", "Earnings per share, diluted", "income",
     ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "ifrs-full:DilutedEarningsLossPerShare"], None),
    ("shares-basic", "Average shares, basic", "income",
     ["WeightedAverageNumberOfSharesOutstandingBasic"], None),
    ("shares-diluted", "Average shares, diluted", "income",
     ["WeightedAverageNumberOfDilutedSharesOutstanding"], None),

    # The balance sheet, at a moment
    ("cash", "Cash and equivalents", "balance",
     ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
      "Cash", "ifrs-full:CashAndCashEquivalents"], None),
    ("short-term-investments", "Short-term investments", "balance",
     ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"], None),
    ("receivables", "Receivables", "balance",
     ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "ifrs-full:TradeAndOtherCurrentReceivables"], None),
    ("inventory", "Inventory", "balance", ["InventoryNet", "ifrs-full:Inventories"], None),
    ("current-assets", "Total current assets", "balance", ["AssetsCurrent", "ifrs-full:CurrentAssets"], None),
    ("property-plant-equipment", "Property, plant and equipment", "balance",
     ["PropertyPlantAndEquipmentNet", "ifrs-full:PropertyPlantAndEquipment"], None),
    ("goodwill", "Goodwill", "balance", ["Goodwill", "ifrs-full:Goodwill"], None),
    ("intangible-assets", "Intangible assets", "balance",
     ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet",
      "ifrs-full:IntangibleAssetsOtherThanGoodwill"], None),
    ("total-assets", "Total assets", "balance", ["Assets", "ifrs-full:Assets"], None),
    ("accounts-payable", "Accounts payable", "balance",
     ["AccountsPayableCurrent", "ifrs-full:TradeAndOtherCurrentPayables"], None),
    ("current-debt", "Current debt", "balance",
     ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings", "CommercialPaper"], None),
    ("current-liabilities", "Total current liabilities", "balance",
     ["LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"], None),
    ("long-term-debt", "Long-term debt", "balance",
     ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"], None),
    ("total-liabilities", "Total liabilities", "balance",
     ["Liabilities", "ifrs-full:Liabilities"], ("liabilities-and-equity", "equity-including-minority")),
    ("stockholders-equity", "Stockholders' equity", "balance",
     ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
      "ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"], None),
    ("equity-including-minority", "Equity, with minority interests", "balance",
     ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity",
      "ifrs-full:Equity"], None),
    ("liabilities-and-equity", "Total liabilities and equity", "balance",
     ["LiabilitiesAndStockholdersEquity", "ifrs-full:EquityAndLiabilities"], None),
    ("shares-outstanding", "Shares outstanding", "balance", ["CommonStockSharesOutstanding"], None),

    # The cash flow statement, for a period of time
    ("operating-cash-flow", "Cash from operations", "cash-flow",
     ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
      "ifrs-full:CashFlowsFromUsedInOperatingActivities"], None),
    ("depreciation-amortization", "Depreciation and amortization", "cash-flow",
     ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
      "DepreciationAndAmortization", "Depreciation"], None),
    ("stock-compensation", "Stock-based compensation", "cash-flow",
     ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"], None),
    ("capital-expenditures", "Capital expenditures", "cash-flow",
     ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
      "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
      "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"],
     None),
    ("free-cash-flow", "Free cash flow", "cash-flow", [], ("operating-cash-flow", "capital-expenditures")),
    ("investing-cash-flow", "Cash from investing", "cash-flow",
     ["NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
      "ifrs-full:CashFlowsFromUsedInInvestingActivities"], None),
    ("financing-cash-flow", "Cash from financing", "cash-flow",
     ["NetCashProvidedByUsedInFinancingActivities", "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
      "ifrs-full:CashFlowsFromUsedInFinancingActivities"], None),
    ("dividends-paid", "Dividends paid", "cash-flow",
     ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "ifrs-full:DividendsPaidClassifiedAsFinancingActivities"], None),
    ("share-repurchases", "Shares repurchased", "cash-flow", ["PaymentsForRepurchaseOfCommonStock"], None),
]

STATEMENT_NAMES = {"income": "sec-income-statement", "balance": "sec-balance-sheet",
                   "cash-flow": "sec-cash-flow-statement"}


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def user_agent(credentials_path, who):
    """The "sec_user_agent" entry of the credentials file: who's asking."""
    return credential(credentials_path, "sec_user_agent", who, 'the SEC asks for a name and email address, '
                      'such as "Jane Smith jane@example.com"')


def sec_download(url, credentials_path, who):
    """The JSON at an SEC address, as Python data."""
    headers = list_to_pairs([Pair(LispString("User-Agent"), LispString(user_agent(credentials_path, who)))])
    return json.loads(lisp_http.as_text(lisp_http.download(url, CACHE_HOURS, headers, who)))


def company_cik(credentials_path, company, who):
    """The CIK number the SEC knows a company by: from its ticker, such as
    "AAPL", looked up in the SEC's list; or given as a number already."""
    if isinstance(company, (int, float)) and not isinstance(company, bool):
        return int(company)
    text = str(company).strip().upper()
    if text.isdigit():
        return int(text)
    for entry in sec_download(TICKERS_URL, credentials_path, who).values():
        if entry["ticker"].upper() == text.replace(".", "-"):
            return int(entry["cik_str"])
    raise LispError("%s: the SEC has no company with the ticker %s" % (who, text))


# The company facts parsed from the last download of each company, so that
# several statements in a row don't parse the same file again:
# cik -> (time parsed, the facts).
_parsed_facts = {}


def company_facts(credentials_path, company, who):
    """Everything the SEC has for the company, as Python data."""
    cik = company_cik(credentials_path, company, who)
    saved = _parsed_facts.get(cik)
    if saved and time.time() - saved[0] < CACHE_HOURS * 3600:
        return saved[1]
    try:
        facts = sec_download(COMPANY_FACTS_URL % cik, credentials_path, who)
    except LispError as e:
        if "HTTP 404" in str(e):
            raise LispError("%s: the SEC has no XBRL financial data for CIK %d" % (who, cik))
        raise
    _parsed_facts[cik] = (time.time(), facts)
    return facts


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

def to_date(text):
    return datetime.date.fromisoformat(text) if text else None


def days_between(fact):
    return (to_date(fact["end"]) - to_date(fact["start"])).days if fact.get("start") else 0


def concept_facts(facts, concept):
    """Every fact reported for the concept -- "NetIncomeLoss" (us-gaap), or
    "taxonomy:Name" -- in the unit it has the most facts in: (unit, list of
    facts). (None, []) if the company never reported it."""
    taxonomy, name = concept.split(":", 1) if ":" in concept else ("us-gaap", concept)
    entry = facts.get("facts", {}).get(taxonomy, {}).get(name)
    if not entry:
        return None, []
    unit, unit_facts = max(entry["units"].items(), key=lambda item: len(item[1]))
    return unit, unit_facts


class ConceptFacts:
    """A concept's facts, arranged to find one period's quickly: by the date
    the period ends, each with its start (None for a balance, which is at a
    moment) and end as dates."""

    def __init__(self, facts, concept):
        self.unit, unit_facts = concept_facts(facts, concept)
        self.by_end = {}
        for fact in unit_facts:
            start = to_date(fact.get("start"))
            end = to_date(fact["end"])
            self.by_end.setdefault(end, []).append((start, fact))

    def balance_at(self, end):
        """The value at a moment, end."""
        at_end = [fact for start, fact in self.by_end.get(end, []) if start is None]
        return latest_filed(at_end)["val"] if at_end else None

    def flow(self, start, end, slack=7):
        """The value for the period from start (give or take slack days) to end."""
        matching = [fact for fact_start, fact in self.by_end.get(end, [])
                    if fact_start is not None and abs((fact_start - start).days) <= slack]
        return latest_filed(matching)["val"] if matching else None

    def flow_alone(self, end, length):
        """The value for a period of about length days ending at end."""
        matching = [fact for start, fact in self.by_end.get(end, [])
                    if start is not None and length[0] <= (end - start).days <= length[1]]
        return latest_filed(matching)["val"] if matching else None


def latest_filed(facts):
    """Of facts for the same period, the one filed last."""
    return max(facts, key=lambda f: (f.get("filed", ""), f.get("accn", "")))


# ---------------------------------------------------------------------------
# Periods: fiscal years and quarters
# ---------------------------------------------------------------------------

class Period:
    """A fiscal year or quarter: its end date, the start of the fiscal year
    it's in, the end of the quarter before it in that year (None for a
    year or a first quarter), and its fiscal labels."""

    def __init__(self, end, year_start, previous_end, fiscal_year, fiscal_period):
        self.end = end
        self.year_start = year_start
        self.previous_end = previous_end
        self.fiscal_year = fiscal_year
        self.fiscal_period = fiscal_period


def main_periods(facts, forms, length):
    """For each filing of these forms, its main period: the latest-ending
    period, among its facts, of about this length in days. A dict from end
    date to (start date, the filing's fiscal year and period)."""
    by_filing = {}
    for taxonomy in facts.get("facts", {}).values():
        for entry in taxonomy.values():
            for unit_facts in entry["units"].values():
                for fact in unit_facts:
                    if fact.get("form") in forms and fact.get("start") and \
                            length[0] <= days_between(fact) <= length[1]:
                        best = by_filing.get(fact["accn"])
                        if best is None or fact["end"] > best["end"]:
                            by_filing[fact["accn"]] = fact
    periods = {}
    for fact in by_filing.values():
        end = to_date(fact["end"])
        if end not in periods or fact.get("filed", "") > periods[end][2]:
            periods[end] = (to_date(fact["start"]), (fact.get("fy"), fact.get("fp")), fact.get("filed", ""))
    return {end: (start, labels) for end, (start, labels, _) in periods.items()}


def fiscal_years(facts):
    """The company's fiscal years, newest first."""
    years = main_periods(facts, ANNUAL_FORMS, YEAR_DAYS)
    return [Period(end, start, None, labels[0], "FY") for end, (start, labels) in sorted(years.items(), reverse=True)]


def fiscal_quarters(facts):
    """The company's fiscal quarters, newest first: the main periods of its
    10-Qs, and the fourth quarters, which end when the fiscal years do -- for
    a year with 10-Qs, since the fourth quarter is worked out as the year less
    the quarters before it. (A company outside the US files only annual
    reports, and so has no quarters here.)"""
    years = fiscal_years(facts)
    quarter_ends = {end: labels for end, (start, labels) in main_periods(facts, QUARTERLY_FORMS, (60, 290)).items()}
    quarters = []
    for year in years:
        ends = sorted(end for end in quarter_ends if year.year_start < end < year.end)
        previous = None
        for end in ends:
            fiscal_year, fiscal_period = quarter_ends[end]
            quarters.append(Period(end, year.year_start, previous, fiscal_year, fiscal_period))
            previous = end
        if ends:
            quarters.append(Period(year.end, year.year_start, previous, year.fiscal_year, "Q4"))
    # quarters of the current fiscal year, not yet covered by an annual report
    latest_year_end = years[0].end if years else None
    if latest_year_end:
        ends = sorted(end for end in quarter_ends if end > latest_year_end)
        previous = None
        for end in ends:
            fiscal_year, fiscal_period = quarter_ends[end]
            quarters.append(Period(end, latest_year_end + datetime.timedelta(days=1), previous,
                                   fiscal_year, fiscal_period))
            previous = end
    return sorted(quarters, key=lambda q: q.end, reverse=True)


# ---------------------------------------------------------------------------
# Values for a period
# ---------------------------------------------------------------------------

def flow_value(concept, period):
    """A flow -- income, a cash flow -- for a fiscal year or quarter. A
    quarter's value is reported for the quarter alone, or else worked out as
    the year to date at its end less the year to date at the end of the
    quarter before. But not for a per-share amount or a number of shares --
    an average, not a sum, so a difference of two means nothing."""
    if period.fiscal_period == "FY":
        return concept.flow(period.year_start, period.end)
    alone = concept.flow_alone(period.end, QUARTER_DAYS)
    if alone is not None:
        return alone
    if concept.unit == "shares" or "/" in (concept.unit or ""):
        return None
    to_date_now = concept.flow(period.year_start, period.end)
    if period.previous_end is None:
        return to_date_now
    to_date_before = concept.flow(period.year_start, period.previous_end)
    if to_date_now is None or to_date_before is None:
        return None
    return to_date_now - to_date_before


def line_item_values(facts, periods, statement=None):
    """For each line item (of one statement, or of all three), its value in
    each period: a list of (item, values, unit, sources), sources being
    the concepts the values came from."""
    concepts_seen = {}

    def concept(name):
        if name not in concepts_seen:
            concepts_seen[name] = ConceptFacts(facts, name)
        return concepts_seen[name]

    found = {}                                   # key -> [values, unit, sources]
    for key, label, item_statement, names, _ in LINE_ITEMS:
        values, unit, sources = [], None, []
        for period in periods:
            value = None
            for name in names:
                c = concept(name)
                value = c.balance_at(period.end) if item_statement == "balance" else flow_value(c, period)
                if value is not None:
                    unit = unit or c.unit
                    if name not in sources:
                        sources.append(name)
                    break
            values.append(value)
        found[key] = [values, unit, sources]

    # Then the lines worked out from two others, where they weren't reported.
    for key, label, item_statement, names, difference_of in LINE_ITEMS:
        if difference_of is None:
            continue
        a, b = difference_of
        values, unit, sources = found[key]
        for i in range(len(periods)):
            if values[i] is None and found[a][0][i] is not None and found[b][0][i] is not None:
                values[i] = found[a][0][i] - found[b][0][i]
                found[key][1] = unit or found[a][1]
                if "%s - %s" % (a, b) not in sources:
                    sources.append("%s - %s" % (a, b))

    return [(item, found[item[0]][0], found[item[0]][1], found[item[0]][2])
            for item in LINE_ITEMS if statement is None or item[2] == statement]


# ---------------------------------------------------------------------------
# The builtins
# ---------------------------------------------------------------------------

def chosen_periods(facts, options, who):
    period = str(options.get("period", "annual"))
    if period not in ("annual", "quarterly"):
        raise LispError('%s: :period is "annual" or "quarterly", not %s' % (who, period))
    periods = fiscal_years(facts) if period == "annual" else fiscal_quarters(facts)
    count = options.get("count", 5 if period == "annual" else 8)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise LispError("%s: :count is a whole number of periods, 1 or more" % who)
    if not periods and period == "quarterly":
        raise LispError("%s: the SEC has no quarterly reports (10-Qs) for this company -- a company "
                        "outside the US files only annual reports" % who)
    if not periods:
        raise LispError("%s: the SEC has no annual reports with XBRL data for this company" % who)
    return periods[:count]


def statement_table(credentials_path, company, statement, options):
    """One of the three statements, laid out as the company would: a row
    per line item, a column per period (newest first), and a column of the
    concepts the values came from."""
    who = STATEMENT_NAMES[statement]
    options = keyword_options(options, ["period", "count", "in-millions"], who)
    facts = company_facts(credentials_path, company, who)
    periods = chosen_periods(facts, options, who)
    in_millions = options.get("in-millions", True) is not False
    rows = line_item_values(facts, periods, statement)
    rows = [row for row in rows if any(v is not None for v in row[1])]     # leave out lines with no values

    def shown(value, unit):
        if value is None:
            return None
        if in_millions and unit and "/" not in unit:          # not a per-share number
            return value / 1e6
        return value
    columns = [("item", column_vector([LispString(item[1]) for item, _, _, _ in rows]))]
    for i, period in enumerate(periods):
        columns.append((period.end.isoformat(), column_vector([shown(values[i], unit) for _, values, unit, _ in rows])))
    columns.append(("unit", column_vector([LispString(unit or "") for _, _, unit, _ in rows])))
    columns.append(("source", column_vector([LispString(", ".join(sources)) for _, _, _, sources in rows])))
    return make_table_value(columns)


def sec_income_statement(credentials_path, company, *options):
    """(sec-income-statement creds ticker [:period "annual" :count 5
    :in-millions #t]) -- the income statement, a row per line item and a
    column per period, newest first. :period "quarterly" for quarters;
    :count how many periods (5 years or 8 quarters unless given); amounts
    in millions unless :in-millions is #f (per-share amounts never)."""
    return statement_table(credentials_path, company, "income", options)


def sec_balance_sheet(credentials_path, company, *options):
    """(sec-balance-sheet creds ticker [...]) -- the balance sheet at the
    end of each period, as sec-income-statement lays it out."""
    return statement_table(credentials_path, company, "balance", options)


def sec_cash_flow_statement(credentials_path, company, *options):
    """(sec-cash-flow-statement creds ticker [...]) -- the cash flow
    statement, as sec-income-statement lays it out."""
    return statement_table(credentials_path, company, "cash-flow", options)


def sec_financials(credentials_path, company, *options):
    """(sec-financials creds ticker [:period "annual" :count 5]) -- every
    line item of all three statements, a row per period (oldest first) and
    a column per item, in dollars (and shares) as reported: the form to use
    them in, with the table and vector functions."""
    who = "sec-financials"
    options = keyword_options(options, ["period", "count"], who)
    facts = company_facts(credentials_path, company, who)
    periods = list(reversed(chosen_periods(facts, options, who)))
    rows = line_item_values(facts, periods)
    columns = [("period-end", column_vector([LispDate(p.end.year, p.end.month, p.end.day) for p in periods])),
               ("fiscal-year", column_vector([p.fiscal_year for p in periods])),
               ("fiscal-period", column_vector([LispString(p.fiscal_period or "") for p in periods]))]
    for item, values, _, _ in rows:
        columns.append((item[0], column_vector(list(values))))
    return make_table_value(columns)


def sec_facts(credentials_path, company, concept):
    """(sec-facts creds ticker concept) -- every value the company has
    reported for one concept, such as "NetIncomeLoss" (us-gaap) or
    "ifrs-full:Revenue": a table with a row per fact, in the order filed."""
    who = "sec-facts"
    facts = company_facts(credentials_path, company, who)
    unit, unit_facts = concept_facts(facts, str(concept))
    if not unit_facts:
        raise LispError("%s: the company has never reported %s (sec-concepts lists what it has)" % (who, concept))

    def column(name, convert=lambda v: v):
        return column_vector([None if f.get(name) is None else convert(f[name]) for f in unit_facts])
    as_date = lambda text: LispDate(*map(int, text.split("-")))
    return make_table_value([
        ("start", column("start", as_date)), ("end", column("end", as_date)), ("value", column("val")),
        ("unit", column_vector([LispString(unit)] * len(unit_facts))),
        ("fiscal-year", column("fy")), ("fiscal-period", column("fp", LispString)),
        ("form", column("form", LispString)), ("filed", column("filed", as_date)),
        ("frame", column("frame", LispString)), ("accession", column("accn", LispString)),
    ])


def sec_concepts(credentials_path, company):
    """(sec-concepts creds ticker) -- every concept the company has
    reported: a table with its taxonomy, name, label, unit, how many facts,
    and the end of the first and last period."""
    facts = company_facts(credentials_path, company, "sec-concepts")
    rows = []
    for taxonomy, entries in facts.get("facts", {}).items():
        for name, entry in entries.items():
            unit, unit_facts = max(entry["units"].items(), key=lambda item: len(item[1]))
            ends = sorted(f["end"] for f in unit_facts)
            rows.append((taxonomy, name, entry.get("label") or "", unit, len(unit_facts), ends[0], ends[-1]))
    rows.sort(key=lambda r: (r[0], r[1]))
    as_date = lambda text: LispDate(*map(int, text.split("-")))
    return make_table_value([
        ("taxonomy", column_vector([LispString(r[0]) for r in rows])),
        ("concept", column_vector([LispString(r[1]) for r in rows])),
        ("label", column_vector([LispString(r[2]) for r in rows])),
        ("unit", column_vector([LispString(r[3]) for r in rows])),
        ("facts", column_vector([r[4] for r in rows])),
        ("first", column_vector([as_date(r[5]) for r in rows])),
        ("last", column_vector([as_date(r[6]) for r in rows])),
    ])


def sec_company(credentials_path, company):
    """(sec-company creds ticker) -- a hash table with the company's "name"
    and "cik" (the number the SEC knows it by)."""
    facts = company_facts(credentials_path, company, "sec-company")
    result = LispHashTable()
    result.table[LispString("name")] = LispString(facts.get("entityName", ""))
    result.table[LispString("cik")] = int(facts.get("cik", 0))
    return result


BUILTINS = {
    "sec-company": sec_company,
    "sec-concepts": sec_concepts,
    "sec-facts": sec_facts,
    "sec-income-statement": sec_income_statement,
    "sec-balance-sheet": sec_balance_sheet,
    "sec-cash-flow-statement": sec_cash_flow_statement,
    "sec-financials": sec_financials,
}
