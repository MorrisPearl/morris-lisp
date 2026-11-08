"""A three-statement financial model of a public company, in a Google Sheet.

  (three-statement-model creds ticker [:period "annual" :history 5 :forecast 5 :kind "auto" :price p :title t])

downloads the company's reported numbers from the SEC (lisp_sec.py), lays out
its income statement, balance sheet, and cash flow statement for the last
few years -- or quarters -- and extends all three into the future with
formulas, driven by assumptions that you change in the sheet. It makes six
tabs:

  Assumptions        what drives the forecast. For the periods reported, each
                     assumption is worked out from the statements (revenue
                     growth, the gross margin, the days of sales in
                     receivables, ...) so that you can see what happened; for
                     the periods to come it is a formula, on yellow, for you
                     to type over: in the first period a formula of the
                     history (the last period's value, say), in each later
                     period the period before's, so that the sheet works as
                     it comes and changing one period changes the rest.
  Income Statement
  Balance Sheet
  Cash Flow
  DCF                what the company is worth, by discounting the free cash flow
                     of the forecast (lisp_financial_dcf.py); not for banks or insurers.
  Notes              how to read the sheet, and where each number came from.

The statements have the same periods in the same columns, so the cell that
is a period's revenue, in column E of the income statement, is in column E
of the others too. Colors, as in most models: blue is a number typed in
(reported by the company, or an assumption), black is a formula, and green
is a link to another tab.

HOW THE FORECAST WORKS, in the order the sheet works it out (the usual
"integrated three-statement model", for example
https://www.wallstreetprep.com/knowledge/build-integrated-3-statement-financial-model/):

  Revenue grows at the assumed rate (from the same quarter a year before,
  for quarters, so the seasons stay). Costs are a percentage of revenue.
  Interest is worked out from the debt and cash at the END of the period
  before, so that nothing refers to itself: no circular formulas. Taxes are
  a percentage of income before taxes.
  The cash flow statement starts from net income, adds back depreciation and
  stock compensation, and subtracts the growth of receivables and inventory
  (and adds that of payables), which come from days-of-sales assumptions.
  The balance sheet's receivables, inventory, payables, plant and equipment
  (last period's plus capital expenditures less depreciation), debt (plus
  what is borrowed or repaid), and equity (plus net income and stock
  compensation, less dividends and buybacks) follow; the other lines stay
  as they were. Cash is last period's plus the cash flow statement's net
  change -- the end of the balance sheet, and the check that it balances
  (assets less liabilities and equity, at the bottom of the balance sheet,
  and zero in every period) is a test of all the formulas together.

KINDS OF COMPANY. What is written above is the model of an ordinary company ("general"). A bank has no
cost of revenue and an insurer no inventory, and their balance sheets are what they earn on, so each has a
model of its own with its own lines and assumptions, in lisp_financial_bank.py and
lisp_financial_insurer.py, and an asset manager's revenue is a fee on assets under management
(lisp_financial_asset_manager.py; the AUM is given with :aum, since the SEC's data lacks it). They are Templates (below): the lines taken from the SEC, a History that arranges
them, and a Model (a subclass of the one here) that lays out the sheets. :kind "auto" chooses by the SEC's
industry code (SIC), and falls back to "general", with a note, if the SEC's facts lack what the other kind needs.

THE REPORTED NUMBERS come from lisp_sec.line_item_values, which finds each
line under whichever of the company's tags it uses. The model's lines are a
little fewer than the company's, so each statement has a few lines that are
what is left over -- "other operating expenses", "other current assets" -- worked
out so that the subtotals are the company's. (A line a company doesn't
report is zero, and the Notes tab says so.)
"""

import calendar
import datetime
import re

from lisp_core import LispError, LispString, keyword_options
import lisp_google
import lisp_sec
import lisp_sec_filings
import lisp_sec_segments

INCOME, BALANCE, CASH_FLOW, ASSUMPTIONS, DCF, NOTES = \
    "Income Statement", "Balance Sheet", "Cash Flow", "Assumptions", "DCF", "Notes"
TAB_ORDER = [ASSUMPTIONS, INCOME, BALANCE, CASH_FLOW, DCF, NOTES]

HEADER_ROWS = 5                 # title, units, period names, period ends, period numbers
PERIOD_NUMBER_ROW = 5           # (the last of them: 0 in the first forecast period, 1 in the next, -1 in the last reported)
FIRST_LINE_ROW = 7              # (row 6 is empty)
LABEL_WIDTH = 330               # pixels
PERIOD_WIDTH = 90
MILLION = 1e6

# the names of assumptions in formulas, where the line's key won't do (growth and days are functions of Google Sheets);
# the others are the keys with underscores, and a segment's growth is called after the segment (greater_china_growth)
ASSUMPTION_NAMES = {"growth": "revenue_growth", "days": "days_in_period"}

DEFAULT_COUNTS = {"annual": 5, "quarterly": 8}     # periods reported, and periods forecast
PERIODS_PER_YEAR = {"annual": 1, "quarterly": 4}
QUARTER_AVERAGE = 4             # a forecast ratio starts as the average of this many quarters (the last year's)

# The guesses for the assumptions are the last period's ratios (the average of the last
# four, for quarters), kept within these limits so that, say, a year of 150% growth isn't
# assumed to go on forever. (low, high)
GROWTH_LIMITS = (-0.20, 0.20)
SHARE_GROWTH_LIMITS = (-0.05, 0.03)
INTEREST_RATE_LIMITS = (0.0, 0.15)
YIELD_LIMITS = (0.0, 0.05)
TAX_RATE_LIMITS = (0.0, 0.40)
PAYOUT_LIMITS = (0.0, 1.5)
AMORTIZATION_LIMITS = (0.0, 1.0)
NO_LIMITS = (-1e9, 1e9)
# A payout is lumpy (a company buys back no stock for years, and then a great deal in one), so its guess,
# for years, is the average of the last few years' rather than the last year's:
SMOOTHED_ASSUMPTIONS = ("dividend-payout", "buyback-payout")
SMOOTHED_YEARS = 3


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def column_letter(index):
    """The spreadsheet's name for the column with this 0-based index: A, B, ... Z, AA, ..."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def add_months(date, months):
    """The date this many months later; the last day of the month if `date` is the last of its month."""
    month_index = date.year * 12 + date.month - 1 + months
    year, month = divmod(month_index, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    day = last_day if date.day == calendar.monthrange(date.year, date.month)[1] else min(date.day, last_day)
    return datetime.date(year, month, day)


def quoted_tab(name):
    return "'%s'" % name


def is_formula(value):
    return isinstance(value, str) and value.startswith("=")


ASSUMPTION_LINK = re.compile(r"=(OFFSET\([a-z0-9_]+,0,[A-Z]+\$\d+\)|[a-z][a-z0-9_]*)$")


def is_plain_link(value):
    """A formula that is just another tab's cell: ='Income Statement'!E8, or an assumption's: =OFFSET(tax_rate,0,G$5)."""
    if is_formula(value) and ASSUMPTION_LINK.match(value):
        return True
    return is_formula(value) and "!" in value and all(c not in value[1:] for c in "+-*/(,")


def range_name(words):
    """A name Google Sheets accepts for a range, from words: lower case letters and numbers joined by underscores."""
    name = re.sub(r"[^a-z0-9]+", "_", words.lower()).strip("_")
    return "_" + name if not name or name[0].isdigit() else name


def safe_ratio(numerator, denominator):
    """numerator / denominator, or None if there is no denominator."""
    if numerator is None or not denominator:
        return None
    return numerator / denominator


# ---------------------------------------------------------------------------
# The reported numbers, in millions
# ---------------------------------------------------------------------------

# An ordinary company's lines are those of lisp_sec.LINE_ITEMS, with a few more. Service companies (Accenture,
# Equifax) report selling and marketing, and general and administrative, apart, and many report depreciation
# apart from the amortization of intangibles, which the model takes off the intangibles, not the plant.
GENERAL_ITEMS = [
    (item[0], item[1], item[2], [name for name in item[3] if name != "Depreciation"], item[4])
    if item[0] == "depreciation-amortization" else item for item in lisp_sec.LINE_ITEMS
] + [
    ("selling-and-marketing", "Selling and marketing", "income", ["SellingAndMarketingExpense"], None),
    ("general-and-administrative", "General and administrative", "income", ["GeneralAndAdministrativeExpense"], None),
    ("depreciation-only", "Depreciation", "cash-flow", ["Depreciation"], None),
    ("amortization-of-intangibles", "Amortization of intangible assets", "cash-flow",
     ["AmortizationOfIntangibleAssets"], None),
]

class Reported:
    """What the company reported, for the periods of the model's history
    (oldest first): `values[key]` is a list with a number (in millions) or
    None for each period, for the keys of `items` (lisp_sec.LINE_ITEMS, or
    a list like it for a kind of company that has other lines); `sources[key]`
    says which concepts they came from."""

    def __init__(self, facts, periods, items=None):
        self.periods = periods
        self.items = GENERAL_ITEMS if items is None else items
        self.values, self.sources = {}, {}
        currency = None
        for item, values, unit, sources in lisp_sec.line_item_values(facts, periods, items=self.items):
            key = item[0]
            per_share = bool(unit) and "/" in unit
            self.values[key] = [None if v is None else v if per_share else v / MILLION for v in values]
            self.sources[key] = sources
            if currency is None and unit and not per_share and unit != "shares":
                currency = unit
        self.currency = currency or "USD"
        # Q4 has no average share count of its own (the year's is not four quarters' sum): use the quarter before's
        if "shares-diluted" in self.values:
            for key in ("shares-diluted", "shares-basic"):
                self.values[key] = fill_gaps(self.values[key])
            if not any(self.values["shares-diluted"]):
                self.values["shares-diluted"] = self.values["shares-basic"]

    def zero_filled(self, key):
        """The key's numbers, with 0 where the company reported none."""
        return [0.0 if v is None else v for v in self.values[key]]

    def never_reported(self, key):
        return all(v is None for v in self.values[key])


def fill_gaps(values):
    """The list with each missing number replaced by the one before it (or, at the start, after it)."""
    filled = list(values)
    for i in range(1, len(filled)):
        if filled[i] is None:
            filled[i] = filled[i - 1]
    for i in range(len(filled) - 2, -1, -1):
        if filled[i] is None:
            filled[i] = filled[i + 1]
    return filled


class History:
    """The reported numbers arranged as the model's lines, each a list with a number for every period
    reported: the reported lines and the 'other' lines that make the subtotals come out as reported."""

    def __init__(self, reported, segments=None):
        r = reported
        count = len(r.periods)
        z = r.zero_filled
        self.count = count
        self.segments = segments or []         # [(name, [revenue, ...])], the last perhaps the leftover
        # --- income statement
        self.revenue = z("revenue")
        self.cost_of_revenue = z("cost-of-revenue")
        if r.never_reported("cost-of-revenue") and not r.never_reported("gross-profit"):
            self.cost_of_revenue = [rev - gp for rev, gp in zip(self.revenue, z("gross-profit"))]
        self.gross_profit = [rev - cost for rev, cost in zip(self.revenue, self.cost_of_revenue)]
        self.research = z("research-and-development")
        # (a company that reports selling and marketing, and general and administrative, apart has the two)
        self.selling_and_administrative = [
            sga if sga is not None else (sm or 0.0) + (ga or 0.0) for sga, sm, ga in
            zip(r.values["selling-general-and-administrative"], r.values["selling-and-marketing"],
                r.values["general-and-administrative"])]
        self.operating_income = []
        for i in range(count):
            if r.values["operating-income"][i] is not None:
                operating = r.values["operating-income"][i]
            elif r.values["operating-expenses"][i] is not None:
                operating = self.gross_profit[i] - r.values["operating-expenses"][i]
            else:
                operating = self.gross_profit[i] - self.research[i] - self.selling_and_administrative[i]
            self.operating_income.append(operating)
        self.other_operating_expenses = [gp - rd - sga - op for gp, rd, sga, op in
                                         zip(self.gross_profit, self.research, self.selling_and_administrative,
                                             self.operating_income)]
        self.interest_expense = z("interest-expense")
        self.income_tax = z("income-tax")
        self.pretax_income = []
        for i in range(count):
            if r.values["pretax-income"][i] is not None:
                pretax = r.values["pretax-income"][i]
            else:
                pretax = z("net-income")[i] + self.income_tax[i]
            self.pretax_income.append(pretax)
        self.other_income = [pre - op + interest for pre, op, interest in
                             zip(self.pretax_income, self.operating_income, self.interest_expense)]
        self.net_income = z("net-income")
        self.other_net_income = [ni - (pre - tax) for ni, pre, tax in
                                 zip(self.net_income, self.pretax_income, self.income_tax)]
        self.shares = z("shares-diluted")
        # --- balance sheet
        self.cash, self.short_term_investments = z("cash"), z("short-term-investments")
        self.receivables, self.inventory = z("receivables"), z("inventory")
        listed_current = [sum(x) for x in zip(self.cash, self.short_term_investments, self.receivables, self.inventory)]
        self.other_current_assets = [(reported_total or listed) - listed if reported_total is not None else 0.0
                                     for reported_total, listed in zip(r.values["current-assets"], listed_current)]
        self.current_assets = [a + b for a, b in zip(listed_current, self.other_current_assets)]
        self.property_plant_equipment, self.goodwill = z("property-plant-equipment"), z("goodwill")
        self.intangible_assets = z("intangible-assets")
        listed_assets = [sum(x) for x in zip(self.current_assets, self.property_plant_equipment, self.goodwill,
                                             self.intangible_assets)]
        self.total_assets = []
        for i in range(count):
            total = r.values["total-assets"][i]
            if total is None:
                total = r.values["liabilities-and-equity"][i]
            self.total_assets.append(listed_assets[i] if total is None else total)
        self.other_noncurrent_assets = [total - listed for total, listed in zip(self.total_assets, listed_assets)]
        self.accounts_payable, self.current_debt = z("accounts-payable"), z("current-debt")
        listed_liabilities = [a + b for a, b in zip(self.accounts_payable, self.current_debt)]
        self.other_current_liabilities = [(reported_total - listed) if reported_total is not None else 0.0
                                          for reported_total, listed in
                                          zip(r.values["current-liabilities"], listed_liabilities)]
        self.current_liabilities = [a + b for a, b in zip(listed_liabilities, self.other_current_liabilities)]
        self.long_term_debt = z("long-term-debt")
        self.equity = []
        for i in range(count):
            equity = r.values["equity-including-minority"][i]
            if equity is None:
                equity = r.values["stockholders-equity"][i]
            self.equity.append(0.0 if equity is None else equity)
        # whatever else is not equity: so that the balance sheet balances as reported, even with "mezzanine" equity
        self.other_noncurrent_liabilities = [assets - equity - current - debt for assets, equity, current, debt in
                                             zip(self.total_assets, self.equity, self.current_liabilities,
                                                 self.long_term_debt)]
        # --- cash flow statement
        # depreciation and amortization as reported, or depreciation and the amortization of intangibles added;
        # the amortization (if reported apart) is taken off the intangibles in the forecast, the rest off the plant
        total_da = [da if da is not None else dep + amort for da, dep, amort in
                    zip(r.values["depreciation-amortization"], z("depreciation-only"), z("amortization-of-intangibles"))]
        self.amortization = [min(amort, da) if da >= 0 else 0.0 for amort, da in zip(z("amortization-of-intangibles"), total_da)]
        self.depreciation = [da - amort for da, amort in zip(total_da, self.amortization)]
        self.stock_compensation = z("stock-compensation")
        self.change_in_receivables = [None] + [-(self.receivables[i] - self.receivables[i - 1]) for i in range(1, count)]
        self.change_in_inventory = [None] + [-(self.inventory[i] - self.inventory[i - 1]) for i in range(1, count)]
        self.change_in_payables = [None] + [self.accounts_payable[i] - self.accounts_payable[i - 1]
                                            for i in range(1, count)]
        working_capital = [sum(x or 0.0 for x in group) for group in
                           zip(self.change_in_receivables, self.change_in_inventory, self.change_in_payables)]
        self.other_operating = [cfo - (ni + da + sbc + wc) for cfo, ni, da, sbc, wc in
                                zip(z("operating-cash-flow"), self.net_income,
                                    [d + a for d, a in zip(self.depreciation, self.amortization)],
                                    self.stock_compensation, working_capital)]
        self.capital_expenditures = [-x for x in z("capital-expenditures")]
        self.other_investing = [cfi - capex for cfi, capex in zip(z("investing-cash-flow"), self.capital_expenditures)]
        self.dividends = [-x for x in z("dividends-paid")]
        self.repurchases = [-x for x in z("share-repurchases")]
        self.borrowing_and_other_financing = [cff - div - rep for cff, div, rep in
                                              zip(z("financing-cash-flow"), self.dividends, self.repurchases)]

    @property
    def debt(self):
        return [a + b for a, b in zip(self.current_debt, self.long_term_debt)]


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------

class Line:
    """A line of a statement: its key, label, number format, how its label looks, and its cells."""

    def __init__(self, key, label, number_format="money", label_style=(), cell=None):
        self.key, self.label, self.number_format = key, label, number_format
        self.label_style = tuple(label_style)
        self.cell = cell                      # a function of the period's index: its number or formula, or None
        self.editable = False                 # an assumption: its forecast cells are yellow, for you to change
        self.name = None                      # an assumption: the name its row has in formulas (see Model.make_range_names)


class SheetLayout:
    """A tab: its title, its lines (in order, a None for an empty one), and the cells filled in."""

    def __init__(self, name, title, lines):
        self.name, self.title, self.lines = name, title, lines
        self.row_of = {}
        for position, line in enumerate(lines):
            if line is not None:
                if line.key in self.row_of:
                    raise LispError("three-statement-model: two lines called %s on the %s tab" % (line.key, name))
                self.row_of[line.key] = FIRST_LINE_ROW + position


class Model:
    """The whole model: the tabs, and the periods their columns are."""

    has_valuation = True            # whether it has a DCF tab (not a bank's or an insurer's: see lisp_financial_dcf.py)

    def __init__(self, company_name, ticker, period, reported, history, forecast_count, segment_note=""):
        self.segment_note = segment_note
        self.kind_note = ""                            # (why the model is of this kind of company, if that needs saying)
        self.share_price = None                        # (today's, if given: for the DCF tab)
        self.company_name, self.ticker, self.period = company_name, ticker, period
        self.reported, self.h = reported, history
        self.history_count, self.forecast_count = history.count, forecast_count
        self.count = history.count + forecast_count
        self.lag = PERIODS_PER_YEAR[period]            # growth is measured against this many periods before
        self.days_in_period = 365 if period == "annual" else 365 / 4
        self.segments = history.segments
        self.make_period_labels()
        self.layouts = {}
        self.assumptions = {row[0]: row for row in self.assumption_series()}
        self.layouts[ASSUMPTIONS] = self.assumptions_layout()
        self.make_range_names()
        self.layouts[INCOME] = self.income_layout()
        self.layouts[BALANCE] = self.balance_layout()
        self.layouts[CASH_FLOW] = self.cash_flow_layout()

    # --- the periods

    def make_period_labels(self):
        """For each period (history, then forecast): its label, and the date it ends."""
        periods = self.reported.periods
        self.ends = [p.end for p in periods]
        self.labels = []
        for p in periods:
            year = p.fiscal_year or p.end.year
            self.labels.append("FY%s" % year if self.period == "annual" else "%s FY%s" % (p.fiscal_period, year))
        last = periods[-1]
        year = last.fiscal_year or last.end.year
        fiscal_period = last.fiscal_period or ""
        quarter = int(fiscal_period[1:]) if fiscal_period[:1] == "Q" and fiscal_period[1:].isdigit() else 1
        for step in range(1, self.forecast_count + 1):
            if self.period == "annual":
                year += 1
                self.ends.append(add_months(self.ends[self.history_count - 1], 12 * step))
                self.labels.append("FY%sE" % year)
            else:
                quarter += 1
                if quarter == 5:
                    quarter, year = 1, year + 1
                self.ends.append(add_months(self.ends[self.history_count - 1], 3 * step))
                self.labels.append("Q%d FY%sE" % (quarter, year))

    def is_forecast(self, i):
        return i >= self.history_count

    # --- references to cells

    def make_range_names(self):
        """Name each assumption's row, so that a formula on another tab reads =F9*(1+OFFSET(revenue_growth,0,G$5))
        and not =F9*(1+Assumptions!G12). The name is of the row's cell in the first forecast period; OFFSET moves
        along the row by the period number in row 5 of the formula's own column (0 in the first forecast period, 1
        in the next; the reported periods have -1, -2, ...)."""
        self.range_names = {}
        taken = set()
        for line in self.layouts[ASSUMPTIONS].lines:
            if line is None or line.cell is None:
                continue
            name = line.name or ASSUMPTION_NAMES.get(line.key) or range_name(line.key)
            while name in taken:
                name += "_"
            taken.add(name)
            self.range_names[line.key] = name

    def range_name_cells(self):
        """(name, address) of each named range on the Assumptions tab: the row's first forecast cell."""
        layout = self.layouts[ASSUMPTIONS]
        return [(name, "%s%d" % (column_letter(self.history_count + 1), layout.row_of[key]))
                for key, name in self.range_names.items()]

    def assumption_ref(self, key, i):
        """An assumption in period i, for a formula on another tab, as OFFSET(its name, 0, the period number in
        the column of period i) -- so in a formula in the same column, the period number is the one just above it."""
        return "OFFSET(%s,0,%s$%d)" % (self.range_names[key], column_letter(i + 1), PERIOD_NUMBER_ROW)

    def ref(self, tab, key, i, from_tab):
        """The address of a line's cell in period i, as written on the tab `from_tab`."""
        layout = self.layouts[tab]
        if key not in layout.row_of:
            raise LispError("three-statement-model: no line %s on the %s tab" % (key, tab))
        if tab == ASSUMPTIONS and from_tab != ASSUMPTIONS:
            return self.assumption_ref(key, i)
        address = "%s%d" % (column_letter(i + 1), layout.row_of[key])
        return address if tab == from_tab else "%s!%s" % (quoted_tab(tab), address)

    def refs(self, tab, from_tab):
        """A function (key, i) -> address, for formulas written on `from_tab` about `tab`."""
        return lambda key, i: self.ref(tab, key, i, from_tab)

    # --- Assumptions

    def assumption_series(self):
        """For each assumption: (key, label, number format, the history's value for each period reported
        (None where it can't be worked out), limits for the guess, the formula for the history's value)."""
        h, n, lag, days = self.h, self.history_count, self.lag, self.days_in_period
        a = self.refs(ASSUMPTIONS, ASSUMPTIONS)
        inc, bal, cf = self.refs(INCOME, ASSUMPTIONS), self.refs(BALANCE, ASSUMPTIONS), self.refs(CASH_FLOW, ASSUMPTIONS)
        year_fraction = days / 365

        def sec(numerator, denominator):
            return "=IFERROR(%s/%s,0)" % (numerator, denominator)

        def over_previous(i):                   # these need the period before
            return i >= 1

        rows = []
        growth = [safe_ratio(h.revenue[i], h.revenue[i - lag]) if i >= lag else None for i in range(n)]
        growth = [None if g is None else g - 1 for g in growth]
        rows.append(("growth", "Revenue growth" + (" (over a year before)" if self.period == "quarterly" else ""),
                     "percent", growth, GROWTH_LIMITS,
                     lambda i: "=IFERROR(%s/%s-1,0)" % (inc("revenue", i), inc("revenue", i - lag)) if i >= lag else None))
        rows.append(("gross-margin", "Gross margin", "percent", [safe_ratio(h.gross_profit[i], h.revenue[i]) for i in range(n)],
                     NO_LIMITS, lambda i: sec(inc("gross-profit", i), inc("revenue", i))))
        rows.append(("research-percent", "Research and development, % of revenue", "percent",
                     [safe_ratio(h.research[i], h.revenue[i]) for i in range(n)], NO_LIMITS,
                     lambda i: sec(inc("research", i), inc("revenue", i))))
        rows.append(("selling-percent", "Selling, general and administrative, % of revenue", "percent",
                     [safe_ratio(h.selling_and_administrative[i], h.revenue[i]) for i in range(n)], NO_LIMITS,
                     lambda i: sec(inc("selling", i), inc("revenue", i))))
        rows.append(("other-operating-percent", "Other operating expenses, % of revenue", "percent",
                     [safe_ratio(h.other_operating_expenses[i], h.revenue[i]) for i in range(n)], NO_LIMITS,
                     lambda i: sec(inc("other-operating", i), inc("revenue", i))))
        rows.append(("interest-rate", "Interest rate on debt (a year's, on last period's debt)", "percent",
                     [safe_ratio(h.interest_expense[i], h.debt[i - 1] * year_fraction) if i >= 1 else None
                      for i in range(n)], INTEREST_RATE_LIMITS,
                     lambda i: sec(inc("interest-expense", i), "((%s+%s)*%s/365)" % (
                         bal("current-debt", i - 1), bal("long-term-debt", i - 1), a("days", i))) if over_previous(i) else None))
        rows.append(("interest-yield", "Interest and other income, % of last period's cash (a year's)", "percent",
                     [safe_ratio(h.other_income[i], (h.cash[i - 1] + h.short_term_investments[i - 1]) * year_fraction)
                      if i >= 1 else None for i in range(n)], YIELD_LIMITS,
                     lambda i: sec(inc("other-income", i), "((%s+%s)*%s/365)" % (
                         bal("cash", i - 1), bal("short-term-investments", i - 1), a("days", i))) if over_previous(i) else None))
        rows.append(("stock-compensation-percent", "Stock compensation, % of revenue", "percent",
                     [safe_ratio(h.stock_compensation[i], h.revenue[i]) for i in range(n)], NO_LIMITS,
                     lambda i: sec(cf("stock-compensation", i), inc("revenue", i))))
        rows.append(("depreciation-percent", "Depreciation (with the amortization, if not reported apart), % of revenue",
                     "percent", [safe_ratio(h.depreciation[i], h.revenue[i]) for i in range(n)], NO_LIMITS,
                     lambda i: sec(cf("depreciation", i), inc("revenue", i))))
        rows.append(("amortization-rate", "Amortization of intangibles, % of last period's intangibles (a year's)", "percent",
                     [None if i < 1 or not h.intangible_assets[i - 1] else
                      h.amortization[i] / (h.intangible_assets[i - 1] * year_fraction) for i in range(n)], AMORTIZATION_LIMITS,
                     lambda i: sec(cf("amortization", i), "(%s*%s/365)" % (bal("intangible-assets", i - 1), a("days", i)))
                     if over_previous(i) else None))
        rows.append(("capital-expenditures-percent", "Capital expenditures, % of revenue", "percent",
                     [safe_ratio(-h.capital_expenditures[i], h.revenue[i]) for i in range(n)], NO_LIMITS,
                     lambda i: sec("-" + cf("capital-expenditures", i), inc("revenue", i))))
        rows.append(("receivable-days", "Receivables, days of revenue", "decimal",
                     [None if not h.revenue[i] else h.receivables[i] / h.revenue[i] * days for i in range(n)], NO_LIMITS,
                     lambda i: sec("%s*%s" % (bal("receivables", i), a("days", i)), inc("revenue", i))))
        cost_key, cost_values, cost_name = self.cost_base()
        rows.append(("inventory-days", "Inventory, days of %s" % cost_name, "decimal",
                     [None if not cost_values[i] else h.inventory[i] / cost_values[i] * days for i in range(n)],
                     NO_LIMITS, lambda i: sec("%s*%s" % (bal("inventory", i), a("days", i)), inc(cost_key, i))))
        rows.append(("payable-days", "Payables, days of %s" % cost_name, "decimal",
                     [None if not cost_values[i] else h.accounts_payable[i] / cost_values[i] * days for i in range(n)],
                     NO_LIMITS, lambda i: sec("%s*%s" % (bal("accounts-payable", i), a("days", i)), inc(cost_key, i))))
        rows += self.common_assumption_rows()
        return rows

    def common_assumption_rows(self):
        """The assumptions of every kind of company (each uses the same lines to work them out): the tax rate,
        the growth of the share count, and the payouts."""
        h, n = self.h, self.history_count
        inc, cf = self.refs(INCOME, ASSUMPTIONS), self.refs(CASH_FLOW, ASSUMPTIONS)

        def sec(numerator, denominator):
            return "=IFERROR(%s/%s,0)" % (numerator, denominator)

        def over_previous(i):
            return i >= 1

        rows = []
        rows.append(("tax-rate", "Tax rate (on income before taxes)", "percent",
                     [safe_ratio(h.income_tax[i], h.pretax_income[i]) for i in range(n)], TAX_RATE_LIMITS,
                     lambda i: sec(inc("income-tax", i), inc("pretax-income", i))))
        rows.append(("share-growth", "Growth of the diluted share count", "percent",
                     [None if i < 1 or not h.shares[i - 1] else h.shares[i] / h.shares[i - 1] - 1 for i in range(n)],
                     SHARE_GROWTH_LIMITS,
                     lambda i: "=IFERROR(%s/%s-1,0)" % (inc("shares", i), inc("shares", i - 1)) if over_previous(i) else None))
        rows.append(("dividend-payout", "Dividends, % of net income", "percent",
                     [safe_ratio(-h.dividends[i], h.net_income[i]) for i in range(n)], PAYOUT_LIMITS,
                     lambda i: sec("-" + cf("dividends", i), inc("net-income", i))))
        rows.append(("buyback-payout", "Share repurchases, % of net income", "percent",
                     [safe_ratio(-h.repurchases[i], h.net_income[i]) for i in range(n)], PAYOUT_LIMITS,
                     lambda i: sec("-" + cf("repurchases", i), inc("net-income", i))))
        return rows

    def guess_positions(self, series, smoothed=False):
        """Which periods the forecast's starting value for an assumption comes from: the last one with a value, or
        the last year's quarters (the last few years, if `smoothed`)."""
        known = [i for i, v in enumerate(series) if v is not None]
        if self.period == "quarterly":
            return known[-QUARTER_AVERAGE:]
        return known[-SMOOTHED_YEARS:] if smoothed else known[-1:]

    def default_guess(self, series, limits, smoothed=False):
        """The forecast's starting value for an assumption: the last period's, or the average of the last
        year's quarters (of the last few years, if `smoothed`); within the limits; 0 if the history has none."""
        recent = [series[i] for i in self.guess_positions(series, smoothed)]
        if not recent:
            return 0.0
        guess = sum(recent) / len(recent)
        return min(max(guess, limits[0]), limits[1])

    def assumption_cells(self, key, series, limits, smoothed, history_cell):
        """The cells of an assumption's row, as a function of the period's index. A reported period's is worked out
        from the statements (`history_cell`). The first forecast period's is a formula of the reported periods that
        starts the forecast -- the last period's value, or the average of the last year's quarters (or of the last
        years), within the limits -- and each later period's is the period before's. All can be typed over."""
        positions = self.guess_positions(series, smoothed)

        def cell(i):
            if not self.is_forecast(i):
                return history_cell(i)
            if i > self.history_count:
                return "=" + self.ref(ASSUMPTIONS, key, i - 1, ASSUMPTIONS)
            if not positions:
                return 0.0
            refs = [self.ref(ASSUMPTIONS, key, j, ASSUMPTIONS) for j in positions]
            guess = refs[0] if len(refs) == 1 else "AVERAGE(%s)" % ",".join(refs)
            if limits != NO_LIMITS:
                guess = "MIN(MAX(%s,%s),%s)" % (guess, "%.10g" % limits[0], "%.10g" % limits[1])
            return "=" + guess
        return cell

    def held_cells(self, key, first, history_cell):
        """The cells of an assumption that starts at `first` (a number), then stays what the period before had."""
        def cell(i):
            if not self.is_forecast(i):
                return history_cell(i)
            if i > self.history_count:
                return "=" + self.ref(ASSUMPTIONS, key, i - 1, ASSUMPTIONS)
            return first
        return cell

    def cost_base(self):
        """What inventory and payables are days of: (the income statement line, its history, its name) -- the cost
        of revenue, or, for a company that reports none (many service companies), revenue."""
        if any(self.h.cost_of_revenue):
            return "cost-of-revenue", self.h.cost_of_revenue, "cost of revenue"
        return "revenue", self.h.revenue, "revenue"

    def days_line(self):
        """The days in each period, at the bottom of the Assumptions tab where it is out of the way."""
        return Line("days", "Days in the period", "decimal", (), lambda i: self.days_in_period)

    def assumptions_layout(self):
        lines = [Line("revenue-header", "Revenue", "money", ("section",), None)]
        if self.segments:
            for number, (name, values) in enumerate(self.segments):
                lines.append(self.segment_growth_line(number, name, values))
        lines.append(self.total_growth_line() if self.segments else self.main_line_from_series("growth"))
        lines.append(None)
        lines.append(Line("costs-header", "Costs and taxes", "money", ("section",), None))
        for key in ("gross-margin", "research-percent", "selling-percent", "other-operating-percent", "tax-rate"):
            lines.append(self.main_line_from_series(key))
        lines.append(None)
        lines.append(Line("financing-header", "Interest, shares, and payouts", "money", ("section",), None))
        for key in ("interest-rate", "interest-yield", "share-growth", "dividend-payout", "buyback-payout"):
            lines.append(self.main_line_from_series(key))
        lines.append(self.net_borrowing_line())
        lines.append(None)
        lines.append(Line("cash-header", "Cash flow and the balance sheet", "money", ("section",), None))
        for key in ("stock-compensation-percent", "depreciation-percent", "amortization-rate",
                    "capital-expenditures-percent", "receivable-days", "inventory-days", "payable-days"):
            lines.append(self.main_line_from_series(key))
        lines += [None, self.days_line()]
        return SheetLayout(ASSUMPTIONS, "Assumptions", lines)

    def main_line_from_series(self, key):
        """The line for an assumption: formulas from the statements for the history, and for the forecast a formula
        that starts from the history and then follows the period before."""
        _, label, number_format, series, limits, formula = self.assumptions[key]
        line = Line(key, label, number_format, (),
                    self.assumption_cells(key, series, limits, key in SMOOTHED_ASSUMPTIONS, formula))
        line.editable = True
        return line

    def total_growth_line(self):
        """With revenue by segment, the growth of the total is a result, worked out in every period."""
        _, label, number_format, _, _, formula = self.assumptions["growth"]
        return Line("growth", label + ", as the segments add up", number_format, (), formula)

    def net_borrowing_line(self):
        """Debt borrowed (repaid), an amount: what it was in the periods reported; 0 to begin with, then what it was before."""
        bal = self.refs(BALANCE, ASSUMPTIONS)

        def history(i):
            if i == 0:
                return None
            return "=(%s+%s)-(%s+%s)" % (bal("current-debt", i), bal("long-term-debt", i),
                                        bal("current-debt", i - 1), bal("long-term-debt", i - 1))
        line = Line("net-borrowing", "Debt borrowed (repaid), millions", "money", (),
                    self.held_cells("net-borrowing", 0.0, history))
        line.editable = True
        return line

    def segment_growth_line(self, number, name, values):
        inc = self.refs(INCOME, ASSUMPTIONS)
        series = [safe_ratio(values[i], values[i - self.lag]) if i >= self.lag else None for i in range(len(values))]
        series = [None if s is None else s - 1 for s in series]
        key = "segment-growth-%d" % number

        def history(i):
            if i < self.lag:
                return None
            return "=IFERROR(%s/%s-1,0)" % (inc("segment-%d" % number, i), inc("segment-%d" % number, i - self.lag))
        line = Line(key, "%s, growth" % name, "percent", (),
                    self.assumption_cells(key, series, GROWTH_LIMITS, False, history))
        line.editable = True
        line.name = range_name(name) + "_growth"
        return line

    # --- Income statement

    def income_layout(self):
        h = self.h
        a = self.refs(ASSUMPTIONS, INCOME)
        inc = self.refs(INCOME, INCOME)
        bal = self.refs(BALANCE, INCOME)
        lag = self.lag

        lines = []
        if self.segments:
            for number, (name, values) in enumerate(self.segments):
                lines.append(Line("segment-%d" % number, name, "money", (),
                                  lambda i, number=number, values=values: values[i] if not self.is_forecast(i) else
                                  "=%s*(1+%s)" % (inc("segment-%d" % number, i - lag),
                                                  a("segment-growth-%d" % number, i))))
            first, last = "segment-0", "segment-%d" % (len(self.segments) - 1)
            lines.append(Line("revenue", "Revenue", "money", ("total",),
                              lambda i: "=SUM(%s:%s)" % (inc(first, i), inc(last, i))))
        else:
            lines.append(Line("revenue", "Revenue", "money", ("bold",),
                              lambda i: h.revenue[i] if not self.is_forecast(i) else
                              "=%s*(1+%s)" % (inc("revenue", i - lag), a("growth", i))))
        lines += [
            Line("cost-of-revenue", "Cost of revenue", "money", (),
                 lambda i: h.cost_of_revenue[i] if not self.is_forecast(i) else
                 "=%s*(1-%s)" % (inc("revenue", i), a("gross-margin", i))),
            Line("gross-profit", "Gross profit", "money", ("total",),
                 lambda i: "=%s-%s" % (inc("revenue", i), inc("cost-of-revenue", i))),
            Line("research", "Research and development", "money", (),
                 lambda i: h.research[i] if not self.is_forecast(i) else
                 "=%s*%s" % (inc("revenue", i), a("research-percent", i))),
            Line("selling", "Selling, general and administrative", "money", (),
                 lambda i: h.selling_and_administrative[i] if not self.is_forecast(i) else
                 "=%s*%s" % (inc("revenue", i), a("selling-percent", i))),
            Line("other-operating", "Other operating expenses", "money", (),
                 lambda i: h.other_operating_expenses[i] if not self.is_forecast(i) else
                 "=%s*%s" % (inc("revenue", i), a("other-operating-percent", i))),
            Line("operating-income", "Operating income", "money", ("total",),
                 lambda i: "=%s-%s-%s-%s" % (inc("gross-profit", i), inc("research", i), inc("selling", i),
                                             inc("other-operating", i))),
            None,
            Line("interest-expense", "Interest expense", "money", (),
                 lambda i: h.interest_expense[i] if not self.is_forecast(i) else
                 "=%s*(%s+%s)*%s/365" % (a("interest-rate", i), bal("current-debt", i - 1), bal("long-term-debt", i - 1),
                                         a("days", i))),
            Line("other-income", "Interest and other income, net", "money", (),
                 lambda i: h.other_income[i] if not self.is_forecast(i) else
                 "=%s*(%s+%s)*%s/365" % (a("interest-yield", i), bal("cash", i - 1),
                                         bal("short-term-investments", i - 1), a("days", i))),
            Line("pretax-income", "Income before taxes", "money", ("total",),
                 lambda i: "=%s-%s+%s" % (inc("operating-income", i), inc("interest-expense", i),
                                          inc("other-income", i))),
            Line("income-tax", "Income taxes", "money", (),
                 lambda i: h.income_tax[i] if not self.is_forecast(i) else
                 "=%s*%s" % (a("tax-rate", i), inc("pretax-income", i))),
            Line("other-net-income", "Minority interests, discontinued operations, other", "money", (),
                 lambda i: h.other_net_income[i] if not self.is_forecast(i) else 0.0),
            Line("net-income", "Net income", "money", ("total",),
                 lambda i: "=%s-%s+%s" % (inc("pretax-income", i), inc("income-tax", i), inc("other-net-income", i))),
            None,
            Line("shares", "Diluted shares, millions", "decimal", (),
                 lambda i: h.shares[i] if not self.is_forecast(i) else
                 "=%s*(1+%s)" % (inc("shares", i - 1), a("share-growth", i))),
            Line("eps", "Earnings per share, diluted", "per-share", (),
                 lambda i: '=IFERROR(%s/%s,"")' % (inc("net-income", i), inc("shares", i))),
        ]
        return SheetLayout(INCOME, "Income Statement", lines)

    # --- Balance sheet

    def balance_layout(self):
        h = self.h
        a = self.refs(ASSUMPTIONS, BALANCE)
        inc = self.refs(INCOME, BALANCE)
        bal = self.refs(BALANCE, BALANCE)
        cf = self.refs(CASH_FLOW, BALANCE)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def same_as_before(key):
            return lambda i: "=%s" % bal(key, i - 1)

        cost_key = self.cost_base()[0]
        lines = [
            line("cash", "Cash and equivalents", h.cash, lambda i: "=%s" % cf("cash-end", i)),
            line("short-term-investments", "Short-term investments", h.short_term_investments,
                 same_as_before("short-term-investments")),
            line("receivables", "Receivables", h.receivables,
                 lambda i: "=%s*%s/%s" % (inc("revenue", i), a("receivable-days", i), a("days", i))),
            line("inventory", "Inventory", h.inventory,
                 lambda i: "=%s*%s/%s" % (inc(cost_key, i), a("inventory-days", i), a("days", i))),
            line("other-current-assets", "Other current assets", h.other_current_assets,
                 same_as_before("other-current-assets")),
            Line("current-assets", "Total current assets", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (bal("cash", i), bal("other-current-assets", i))),
            line("property-plant-equipment", "Property, plant and equipment", h.property_plant_equipment,
                 lambda i: "=%s-%s-%s" % (bal("property-plant-equipment", i - 1), cf("capital-expenditures", i),
                                          cf("depreciation", i))),
            line("goodwill", "Goodwill", h.goodwill, same_as_before("goodwill")),
            line("intangible-assets", "Intangible assets", h.intangible_assets,
                 lambda i: "=%s-%s" % (bal("intangible-assets", i - 1), cf("amortization", i))),
            line("other-noncurrent-assets", "Other non-current assets", h.other_noncurrent_assets,
                 same_as_before("other-noncurrent-assets")),
            Line("total-assets", "Total assets", "money", ("total",),
                 lambda i: "=%s+SUM(%s:%s)" % (bal("current-assets", i), bal("property-plant-equipment", i),
                                                bal("other-noncurrent-assets", i))),
            None,
            line("accounts-payable", "Accounts payable", h.accounts_payable,
                 lambda i: "=%s*%s/%s" % (inc(cost_key, i), a("payable-days", i), a("days", i))),
            line("current-debt", "Current debt", h.current_debt, same_as_before("current-debt")),
            line("other-current-liabilities", "Other current liabilities", h.other_current_liabilities,
                 same_as_before("other-current-liabilities")),
            Line("current-liabilities", "Total current liabilities", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (bal("accounts-payable", i), bal("other-current-liabilities", i))),
            line("long-term-debt", "Long-term debt", h.long_term_debt,
                 lambda i: "=%s+%s" % (bal("long-term-debt", i - 1), cf("borrowing", i))),
            line("other-noncurrent-liabilities", "Other non-current liabilities", h.other_noncurrent_liabilities,
                 same_as_before("other-noncurrent-liabilities")),
            Line("total-liabilities", "Total liabilities", "money", ("total",),
                 lambda i: "=%s+%s+%s" % (bal("current-liabilities", i), bal("long-term-debt", i),
                                          bal("other-noncurrent-liabilities", i))),
            line("equity", "Stockholders' equity (with minority interests)", h.equity,
                 lambda i: "=%s+%s+%s+%s+%s" % (bal("equity", i - 1), inc("net-income", i), cf("stock-compensation", i),
                                                cf("dividends", i), cf("repurchases", i))),
            Line("total-liabilities-and-equity", "Total liabilities and equity", "money", ("total",),
                 lambda i: "=%s+%s" % (bal("total-liabilities", i), bal("equity", i))),
            None,
            Line("check", "Check: assets less liabilities and equity (should be 0)", "money", ("italic",),
                 lambda i: "=ROUND(%s-%s,3)" % (bal("total-assets", i), bal("total-liabilities-and-equity", i))),
        ]
        return SheetLayout(BALANCE, "Balance Sheet", lines)

    # --- Cash flow statement

    def cash_flow_layout(self):
        h = self.h
        a = self.refs(ASSUMPTIONS, CASH_FLOW)
        inc = self.refs(INCOME, CASH_FLOW)
        bal = self.refs(BALANCE, CASH_FLOW)
        cf = self.refs(CASH_FLOW, CASH_FLOW)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def sign_change(key, increase_uses_cash):
            """The change in a balance sheet line, from last period to this one, as cash: an increase in an
            asset uses cash; an increase in a liability supplies it."""
            def cell(i):
                if i == 0:
                    return None
                now, before = bal(key, i), bal(key, i - 1)
                return "=%s-%s" % ((before, now) if increase_uses_cash else (now, before))
            return cell

        lines = [
            Line("net-income", "Net income", "money", (), lambda i: "=%s" % inc("net-income", i)),
            # (never more than there is to depreciate: a company whose depreciation includes amortization it doesn't
            # report apart would otherwise take its plant below zero)
            line("depreciation", "Depreciation (and amortization, if not reported apart)", h.depreciation,
                 lambda i: "=MIN(%s*%s,%s-%s)" % (inc("revenue", i), a("depreciation-percent", i),
                                                  bal("property-plant-equipment", i - 1), cf("capital-expenditures", i))),
            line("amortization", "Amortization of intangible assets", h.amortization,
                 lambda i: "=%s*%s*%s/365" % (a("amortization-rate", i), bal("intangible-assets", i - 1), a("days", i))),
            line("stock-compensation", "Stock-based compensation", h.stock_compensation,
                 lambda i: "=%s*%s" % (inc("revenue", i), a("stock-compensation-percent", i))),
            Line("change-in-receivables", "Change in receivables", "money", (), sign_change("receivables", True)),
            Line("change-in-inventory", "Change in inventory", "money", (), sign_change("inventory", True)),
            Line("change-in-payables", "Change in payables", "money", (), sign_change("accounts-payable", False)),
            line("other-operating", "Other operating activities", h.other_operating, lambda i: 0.0),
            Line("operating-cash-flow", "Cash from operations", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("net-income", i), cf("other-operating", i))),
            None,
            line("capital-expenditures", "Capital expenditures", h.capital_expenditures,
                 lambda i: "=-%s*%s" % (inc("revenue", i), a("capital-expenditures-percent", i))),
            line("other-investing", "Other investing activities", h.other_investing, lambda i: 0.0),
            Line("investing-cash-flow", "Cash from investing", "money", ("total",),
                 lambda i: "=%s+%s" % (cf("capital-expenditures", i), cf("other-investing", i))),
            None,
            line("borrowing", "Debt borrowed (repaid) and other financing", h.borrowing_and_other_financing,
                 lambda i: "=%s" % a("net-borrowing", i)),
            line("dividends", "Dividends paid", h.dividends,
                 lambda i: "=-%s*MAX(%s,0)" % (a("dividend-payout", i), inc("net-income", i))),
            line("repurchases", "Shares repurchased", h.repurchases,
                 lambda i: "=-%s*MAX(%s,0)" % (a("buyback-payout", i), inc("net-income", i))),
            Line("financing-cash-flow", "Cash from financing", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("borrowing", i), cf("repurchases", i))),
            None,
            Line("net-change-in-cash", "Net change in cash", "money", ("total",),
                 lambda i: "=%s+%s+%s" % (cf("operating-cash-flow", i), cf("investing-cash-flow", i),
                                          cf("financing-cash-flow", i))),
            Line("cash-begin", "Cash at the start of the period", "money", (),
                 lambda i: "=%s" % bal("cash", i - 1) if self.is_forecast(i) else None),
            Line("cash-end", "Cash at the end of the period", "money", ("total",),
                 lambda i: "=%s+%s" % (cf("cash-begin", i), cf("net-change-in-cash", i)) if self.is_forecast(i) else None),
            None,
            Line("free-cash-flow", "Free cash flow (operations less capital expenditures)", "money", ("italic",),
                 lambda i: "=%s+%s" % (cf("operating-cash-flow", i), cf("capital-expenditures", i))),
        ]
        return SheetLayout(CASH_FLOW, "Cash Flow Statement", lines)

    # --- Filling in the cells

    def unit_description(self):
        return "%s millions, except per-share amounts and days" % self.reported.currency

    def header_rows(self, layout):
        """The first five rows of a tab: title, units, the periods' labels, their ends, and their numbers (0 in the
        first forecast period, 1 in the next, and -1 in the last period reported, -2 in the one before)."""
        rows = [[None] * (self.count + 1) for _ in range(HEADER_ROWS)]
        rows[0][0] = ("%s (%s): %s" % (self.company_name, self.ticker, layout.title), ("title",))
        rows[1][0] = (self.unit_description(), ("italic",))
        rows[2][0] = ("Period", ("bold",))
        rows[3][0] = ("Period ends", ())
        rows[4][0] = ("Period number (0 is the first forecast period)", ("italic",))
        for i in range(self.count):
            forecast = ("forecast",) if self.is_forecast(i) else ()
            rows[2][i + 1] = (self.labels[i], ("header",) + forecast)
            rows[3][i + 1] = (self.ends[i], ("date",) + forecast)
            rows[4][i + 1] = (i - self.history_count, ("italic",) + forecast)
        return rows

    def cell_styles(self, line, value, i):
        """The styles of a cell with this value: its number format, and the color for what kind of cell it is."""
        styles = [line.number_format] if line.number_format else []
        if is_formula(value):
            if is_plain_link(value):
                styles.append("link")
            elif line.editable and self.is_forecast(i):
                styles.append("input-formula")          # an assumption that is a formula: black on yellow
        elif value is not None:
            styles.append("input" if self.is_forecast(i) else "data")
        styles += [style for style in line.label_style if style in ("total", "bold", "italic")]
        return tuple(styles)

    def sheet_cells(self, layout):
        rows = self.header_rows(layout)
        rows.append([None] * (self.count + 1))
        for line in layout.lines:
            row = [None] * (self.count + 1)
            if line is not None:
                row[0] = (line.label, line.label_style)
                if line.cell is not None:
                    for i in range(self.count):
                        value = line.cell(i)
                        if value is not None:
                            row[i + 1] = (value, self.cell_styles(line, value, i))
                elif "section" in line.label_style:
                    for i in range(self.count):
                        row[i + 1] = (None, ("section",))
            rows.append(row)
        return rows

    def forecast_notes(self):
        """The Notes tab's lines on how the forecast works, for this kind of company."""
        return [
            "Revenue is the revenue of the year before (for quarters, the same quarter a year before) times one plus the growth assumption.",
            "Costs are a percentage of revenue (cost of revenue as one less the gross margin). Interest uses last period's debt and cash, so no formula refers to itself.",
            "Receivables, inventory, and payables follow from days of revenue or cost of revenue. Plant and equipment is last period's plus capital expenditures less depreciation.",
            "Debt is last period's plus what is borrowed (repaid), an assumption. Equity is last period's plus net income and stock compensation, less dividends and repurchases.",
            "Cash is last period's plus the net change in cash on the Cash Flow tab. Goodwill, intangibles, short-term investments, and the other assets and liabilities stay as they were.",
            "Nothing keeps cash from going negative if the payouts are more than the company earns: change the assumptions, or the borrowing.",
            "Depreciation and amortization all reduces plant and equipment here, though some of it is amortization of intangibles: if plant shrinks too fast, lower depreciation or raise capital expenditures.",
        ]

    def valuation_notes(self):
        """The Notes tab's section on the DCF tab, or why there is none."""
        if self.has_valuation_tab():
            import lisp_financial_dcf
            return ["The DCF tab"] + lisp_financial_dcf.valuation_notes(self)
        if not self.has_valuation:
            return ["No DCF tab", "A bank's or an insurer's debt is its raw material, not its financing, so a discounted free cash flow means nothing for it: its value is better found from its dividends and its equity. (A share price given with :price was not used.)"]
        return ["No DCF tab", "The forecast is shorter than a year, which is too short to value a company by."]

    def sources_for_notes(self):
        """The Notes tab: how to read the sheet, then the concept each reported number came from."""
        notes = [
            "How to read this sheet",
            "Blue numbers are typed in: reported by the company (from its filings with the SEC) or assumptions for you to change.",
            "Black numbers are formulas. Green ones are links to another tab. Grey columns are forecast periods.",
            "Yellow cells on the Assumptions tab are the assumptions. In the first forecast period each is a formula of the reported periods (the last period's value, or an average, within limits); in each later period it is the period before's. Type a number, or a formula that depends on the period before (=G12*0.9), over any of them; everything to the right follows. The Balance Sheet's check line should read 0 in every period.",
            "Amounts are in millions of %s, except per-share amounts." % self.reported.currency,
            "A formula on another tab reaches an assumption by its name: =D7*(1+OFFSET(revenue_growth,0,E$5)) is the revenue of the period before times one plus the revenue growth assumed for this period. The name is of the assumption's cell in the first forecast period, and OFFSET moves along its row by the period number in row 5 of the formula's own column (0 in the first forecast period, 1 in the next, -1 in the last reported). Data > Named ranges lists the names.",
            "",
            "How the forecast works",
            *self.forecast_notes(),
            "The starting assumptions are guesses from the reported periods (the last period's, or the average of the last year's quarters), kept within limits: replace them with your own.",
            "The lines called other are what is left between the lines shown and the company's own subtotals, so that the subtotals are as reported.",
            "",
            *self.valuation_notes(),
        ]
        concept_lines = {item[0] for item in self.reported.items if item[3]}       # the lines that come from concepts
        missing = [item[1] for item in self.reported.items if self.reported.never_reported(item[0])
                   and item[0] in concept_lines]
        if missing:
            notes += ["", "Lines the company has not reported in these periods, taken as zero: " + ", ".join(missing)]
        notes += ["", "Where the reported numbers came from (the company's XBRL tags)"]
        for item in self.reported.items:
            if item[0] in concept_lines and self.reported.sources[item[0]]:
                notes.append("%s: %s" % (item[1], ", ".join(self.reported.sources[item[0]])))
        if self.segment_note:
            notes += ["", self.segment_note]
        if self.kind_note:
            notes += ["", self.kind_note]
        return notes

    def notes_tab(self):
        rows = []
        for text in self.sources_for_notes():
            heading = text in ("How to read this sheet", "How the forecast works", "The DCF tab", "No DCF tab") or text.startswith("Where the reported")
            rows.append([(text, ("section",) if heading else ("wrap",))] if text else [None])
        return {"name": NOTES, "cells": [[(self.company_name + " model", ("title",))], [None]] + rows,
                "widths": [(0, 0, 900)]}

    def has_valuation_tab(self):
        """Whether the DCF tab is made: this kind of company has one, and the forecast is a year or more."""
        return self.has_valuation and self.forecast_count >= self.lag

    def sheets(self):
        """The model as the tabs for lisp_google.google_workbook."""
        result = []
        for name in TAB_ORDER:
            if name == NOTES:
                result.append(self.notes_tab())
                continue
            if name == DCF:
                if self.has_valuation_tab():
                    import lisp_financial_dcf
                    result.append(lisp_financial_dcf.valuation_sheet(self))
                continue
            layout = self.layouts[name]
            result.append({"name": name, "cells": self.sheet_cells(layout),
                           "frozen_rows": HEADER_ROWS, "frozen_columns": 1,
                           "widths": [(0, 0, LABEL_WIDTH), (1, self.count, PERIOD_WIDTH)]})
            if name == ASSUMPTIONS:
                result[-1]["names"] = self.range_name_cells()
        return result


# ---------------------------------------------------------------------------
# The builtin
# ---------------------------------------------------------------------------

class MissingLines(LispError):
    """The SEC's facts for a company lack numbers that a kind of model needs."""


class Template:
    """A kind of company the model can lay out: the lines it takes from the SEC's facts (`items`, as in
    lisp_sec.LINE_ITEMS), the classes that arrange them (a History of the reported numbers and a Model of the
    sheets), `required` -- the lines the model cannot do without, each a tuple of keys of which one must be
    reported for every period -- and the SEC's industry codes (SIC) of the companies it is for."""

    def __init__(self, name, description, items, history_class, model_class, required=(), sic_codes=(),
                 needs_aum=False):
        self.name, self.description, self.items = name, description, items
        self.history_class, self.model_class = history_class, model_class
        self.required, self.sic_codes = required, set(sic_codes)
        self.needs_aum = needs_aum              # (the assets under management of each period must be given)

    def lacking(self, reported, i):
        """The labels of the required lines that are not reported in period i."""
        labels = {item[0]: item[1] for item in self.items}
        return [" or ".join(labels[key] for key in alternatives) for alternatives in self.required
                if all(reported.values[key][i] is None for key in alternatives)]

    def first_complete_period(self, reported):
        """The index of the earliest period from which every period to the latest has all the required lines
        (the number of periods, if the latest hasn't)."""
        start = len(reported.periods)
        while start > 0 and not self.lacking(reported, start - 1):
            start -= 1
        return start

    def missing_lines(self, reported):
        """The labels of the required lines that are not reported in some period."""
        missing = []
        for i in range(len(reported.periods)):
            missing += [label for label in self.lacking(reported, i) if label not in missing]
        return missing


GENERAL = Template("general", "an ordinary company", GENERAL_ITEMS, History, Model)


def templates():
    """The kinds of company, by name. (The bank and insurer templates are loaded here and not at the top
    of the file because they are built on this module.)"""
    import lisp_financial_asset_manager
    import lisp_financial_bank
    import lisp_financial_insurer
    return {"general": GENERAL, "bank": lisp_financial_bank.TEMPLATE, "insurer": lisp_financial_insurer.TEMPLATE,
            "asset-manager": lisp_financial_asset_manager.TEMPLATE}


def count_option(options, name, default, who):
    value = options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LispError("%s: :%s is a whole number of periods, 1 or more" % (who, name))
    return value


def build_model(facts, ticker, period, history_count, forecast_count, who="three-statement-model",
                find_segments=None, kind="general", aum=None, price=None):
    """The Model of a company from its SEC facts, of the kind (a name in templates()) given. `find_segments`,
    if given (for an ordinary company), is a function of the periods (oldest first) and the company's total
    revenue in each, in millions, that gives the revenue by segment: (segments, a note), segments being
    [(name, a revenue for each period)] or None. `aum`, for an asset manager, is its assets under management
    in billions at the end of each period, oldest first, ending with the latest (the SEC's facts have them for
    few companies). `price`, if given, is today's share price, for the DCF tab. Raises MissingLines if the kind needs
    lines that the company's facts don't have."""
    template = templates()[kind]
    periods = lisp_sec.chosen_periods(facts, {"period": period, "count": history_count}, who)
    periods = list(reversed(periods))
    needed = PERIODS_PER_YEAR[period] + 1
    if len(periods) < needed:
        raise LispError("%s: the SEC has only %d %s periods for this company, and growth needs at least %d"
                        % (who, len(periods), period, needed))
    notes = []
    if template.needs_aum:
        import lisp_financial_asset_manager
        aum = list(aum) if aum is not None else lisp_financial_asset_manager.aum_from_facts(facts, periods)
        if aum is None:
            raise MissingLines("%s: a model of %s needs the assets under management at the end of each period, which "
                               "the SEC's facts for this company do not have: give them with :aum, a list of numbers "
                               "in billions, oldest first, ending with the latest period reported"
                               % (who, template.description))
        if len(aum) < len(periods):             # (periods without an AUM are left out)
            periods = periods[len(periods) - len(aum):]
            notes.append("The history starts at %s because the assets under management were given from then."
                         % periods[0].end.isoformat())
        aum = aum[len(aum) - len(periods):]
    if len(periods) < needed:
        raise LispError("%s: %d %s periods of assets under management were given, and growth needs at least %d"
                        % (who, len(periods), period, needed))
    reported = Reported(facts, periods, template.items)
    start = template.first_complete_period(reported)
    if len(periods) - start < needed:
        raise MissingLines("%s: a model of %s needs %s, which the SEC's facts for this company do not have for "
                           "every one of these periods" % (who, template.description,
                                                           ", ".join(template.missing_lines(reported))))
    if start > 0:                               # (the older periods that lack lines are left out)
        notes.append("The history starts at %s, not earlier, because the SEC's facts for this company lack %s "
                     "before then." % (periods[start].end.isoformat(), ", ".join(template.missing_lines(reported))))
        periods = periods[start:]
        if aum is not None:
            aum = aum[start:]
        reported = Reported(facts, periods, template.items)
    segments, note = None, ""
    if find_segments and kind == "general":
        segments, note = find_segments(periods, template.history_class(reported).revenue)
    history = template.history_class(reported, segments)
    if template.needs_aum:
        history.set_aum(aum)
    result = template.model_class(facts.get("entityName") or ticker, ticker, period, reported, history,
                                  forecast_count, note)
    result.kind_note = " ".join(notes)
    result.share_price = price
    return result


def segment_finder(credentials_path, company, kind, who):
    """build_model's find_segments, reading the filings: kind is "auto", "business", "product", or
    "geography". With "auto", a company without segments is modeled by its total revenue, and the note
    says why; asked for a kind in particular, it is an error not to find it."""
    def find(periods, totals):
        segments, description = lisp_sec_segments.revenue_by_segment(credentials_path, company, periods, totals,
                                                                     kind, who)
        if segments:
            return segments, ("Revenue by segment, from the company's filings: %s. A company that changes its segments "
                              "restates only the years it shows beside the new ones, so a jump between years may "
                              "be the definition, not the business." % description)
        if kind != "auto":
            raise LispError("%s: no %s segments: %s" % (who, kind, description))
        return None, "Revenue is modeled in total, not by segment: " + description
    return find


def company_industry(credentials_path, company, who):
    """The SEC's industry code (SIC) and its description for a company, such as (6021, "National Commercial
    Banks"), or (None, "") if they can't be found."""
    try:
        cik = lisp_sec.company_cik(credentials_path, company, who)
        answer = lisp_sec_filings.sec_json(lisp_sec_filings.SUBMISSIONS_URL % cik, credentials_path, who)
        return int(answer.get("sic") or 0) or None, str(answer.get("sicDescription") or "")
    except (LispError, ValueError):
        return None, ""


def kind_for_industry(sic):
    """The name of the kind of model for a company in this industry (SIC code): "general" unless a template is for it."""
    for name, template in templates().items():
        if sic in template.sic_codes:
            return name
    return "general"


def three_statement_model(credentials_path, company, *options):
    """(three-statement-model creds ticker [:period "annual" :history n :forecast n :kind "auto"
    :segments "auto" :price p :title t]) -- a new Google spreadsheet with the company's income statement, balance sheet,
    and cash flow statement as reported to the SEC, for the last `:history` years (or quarters), and forecast
    for the next `:forecast`, by formulas that follow assumptions on an Assumptions tab. Returns the
    spreadsheet's address. :period is "annual" or "quarterly" (5 years each way, or 8 quarters, unless
    :history and :forecast say). :kind is "general" (an ordinary company: revenue, costs, working capital,
    plant), "bank" (loans, deposits, interest rates, credit losses), "insurer" (a property and casualty
    insurer: premiums, loss and expense ratios, investments, reserves), or "asset-manager" (revenue is a fee
    on assets under management, which you give with :aum, a list of numbers in billions, one for the end of
    each period, oldest first, ending with the latest period reported); "auto", the default, chooses by the
    SEC's industry code for the company (an asset manager if you give :aum), and models it as an ordinary
    company if the SEC's facts lack what the other kind needs. An ordinary company or asset manager also has a DCF tab, a
    discounted-cash-flow valuation; :price, today's share price, makes the weight of debt in its discount rate the
    market's and shows how the value compares with the price. :segments, for an ordinary company: "auto" (the default) models revenue by business
    segment if the company reports them, or else by product; "business", "product", or "geography" asks
    for that one; #f for total revenue only. You need to be signed in to Google: (google-login creds)."""
    who = "three-statement-model"
    options = keyword_options(options, ["period", "history", "forecast", "kind", "aum", "price", "segments", "title"], who)
    period = str(options.get("period", "annual"))
    if period not in DEFAULT_COUNTS:
        raise LispError('%s: :period is "annual" or "quarterly", not %s' % (who, period))
    history_count = count_option(options, "history", DEFAULT_COUNTS[period], who)
    forecast_count = count_option(options, "forecast", DEFAULT_COUNTS[period], who)
    kind = str(options.get("kind", "auto"))
    if kind != "auto" and kind not in templates():
        raise LispError('%s: :kind is "auto", %s, not %s' % (who, ", ".join('"%s"' % name for name in templates()), kind))
    aum = None
    if "aum" in options:
        import lisp_financial_asset_manager
        aum = lisp_financial_asset_manager.number_list(options["aum"], who)
        if kind not in ("auto", "asset-manager"):
            raise LispError('%s: :aum, the assets under management, is for :kind "asset-manager", not %s' % (who, kind))
    price = options.get("price")
    if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0):
        raise LispError("%s: :price is today's share price, a positive number" % who)
    segments = options.get("segments", "auto")
    facts = lisp_sec.company_facts(credentials_path, company, who)
    ticker = str(company).upper()
    finder = None if segments is False else segment_finder(credentials_path, company, str(segments), who)
    kind_note = ""
    if kind == "auto":
        sic, description = company_industry(credentials_path, company, who)
        kind = kind_for_industry(sic)
        if aum is not None and kind == "general":              # (AUM given: an asset manager, if nothing else)
            kind = "asset-manager"
        try:
            model = build_model(facts, ticker, period, history_count, forecast_count, who, finder, kind, aum, price)
        except MissingLines as problem:
            if kind == "general":
                raise
            kind_note = ("The SEC classifies this company as %s, but it is modeled as an ordinary company because %s"
                         % (description or "another kind of company", str(problem).split(": ", 1)[1]))
            model = build_model(facts, ticker, period, history_count, forecast_count, who, finder, "general", None, price)
    else:
        model = build_model(facts, ticker, period, history_count, forecast_count, who, finder, kind, aum, price)
    model.kind_note = (model.kind_note + " " + kind_note).strip()
    title = options.get("title") or "%s %s model" % (model.company_name, period)
    return LispString(lisp_google.google_workbook(credentials_path, str(title), model.sheets()))


BUILTINS = {
    "three-statement-model": three_statement_model,
}
