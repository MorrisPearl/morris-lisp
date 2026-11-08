"""Companies side by side, in a Google Sheet.

  (compare-companies creds '("ACN" "EFX" "CTSH") [:basis "revenue" :period "annual" :kind "auto" :title t])

takes each company's most recent period from the SEC (as three-statement-model does) and puts them in one sheet,
a column for each, with the same rows for every company: the income statement, the balance sheet, the cash flow
statement, and a few ratios. Two companies' numbers are not comparable until they are the same size, so
`:basis` can show every amount as a percentage of the company's top line ("revenue": for a bank, its net
revenue, net interest income plus noninterest income) or of its balance sheet total ("assets"). Then a column
of medians shows what is typical of the group, and what a company does differently shows.

The rows are those of the company's kind (see lisp_financial_model.py): the ordinary company's, a bank's, or a
property and casualty insurer's. A group must be all one kind, so that the rows can be the same; "auto" chooses
by the SEC's industry codes, and says so if they differ.

With a basis there are two tabs besides the Notes: "Comparison", which is formulas -- each amount over the basis --
and "As reported", the numbers from the SEC in millions (blue), which they refer to, with the ratios. Without a
basis the numbers are on the "Comparison" tab itself.
"""

from lisp_core import LispError, LispString, keyword_options
from lisp_data_common import text_list
import lisp_financial_model as model
import lisp_google
import lisp_sec

COMPARISON, AS_REPORTED, NOTES = "Comparison", "As reported", "Notes"
BASES = ("none", "revenue", "assets")
LABEL_WIDTH = 330
COMPANY_WIDTH = 105
FIRST_COMPANY_COLUMN = 1               # (column A has the labels)
MOST_COMPANIES = 40


# ---------------------------------------------------------------------------
# The rows of each kind of company
# ---------------------------------------------------------------------------
# A row is one of:
#   ("section", label)
#   ("money", key, label, getter, styles)      an amount, in millions: getter(history, i) -> number
#   ("absolute", key, label, getter, format)   a number that is not an amount to scale: shares, earnings per share
#   ("ratio", key, label, formula)             worked out on the sheet: formula(cell, year) -> text, where cell(key) is
#                                              the address of a row's cell in this column and year is 365 over the days
# The row with key "basis-revenue" is what "revenue" means for the kind; "total-assets" is what "assets" means.

def attr(name):
    return lambda h, i: getattr(h, name)[i]


def total(*getters):
    return lambda h, i: sum(getter(h, i) or 0.0 for getter in getters)


def ratio_of(numerator, denominator, annual=False):
    """A ratio row's formula: numerator over denominator (a year's, if `annual`), or blank."""
    def formula(cell, year):
        return '=IFERROR(%s%s/%s,"")' % (cell(numerator), "*" + year if annual else "", cell(denominator))
    return formula


def cash_flow_total(*names):
    return lambda h, i: sum((getattr(h, name)[i] or 0.0) for name in names)


GENERAL_ROWS = [
    ("section", "Income statement"),
    ("money", "revenue", "Revenue", attr("revenue"), ("bold",)),
    ("money", "cost-of-revenue", "Cost of revenue", attr("cost_of_revenue"), ()),
    ("money", "gross-profit", "Gross profit", attr("gross_profit"), ("total",)),
    ("money", "research", "Research and development", attr("research"), ()),
    ("money", "selling", "Selling, general and administrative", attr("selling_and_administrative"), ()),
    ("money", "other-operating", "Other operating expenses", attr("other_operating_expenses"), ()),
    ("money", "operating-income", "Operating income", attr("operating_income"), ("total",)),
    ("money", "interest-expense", "Interest expense", attr("interest_expense"), ()),
    ("money", "other-income", "Interest and other income, net", attr("other_income"), ()),
    ("money", "pretax-income", "Income before taxes", attr("pretax_income"), ("total",)),
    ("money", "income-tax", "Income taxes", attr("income_tax"), ()),
    ("money", "other-net-income", "Minority interests, discontinued operations, other", attr("other_net_income"), ()),
    ("money", "net-income", "Net income", attr("net_income"), ("total",)),
    ("absolute", "shares", "Diluted shares, millions", attr("shares"), "decimal"),
    ("absolute", "eps", "Earnings per share, diluted", lambda h, i: h.net_income[i] / h.shares[i] if h.shares[i] else None, "per-share"),
    ("section", "Balance sheet"),
    ("money", "cash", "Cash and equivalents", attr("cash"), ()),
    ("money", "short-term-investments", "Short-term investments", attr("short_term_investments"), ()),
    ("money", "receivables", "Receivables", attr("receivables"), ()),
    ("money", "inventory", "Inventory", attr("inventory"), ()),
    ("money", "other-current-assets", "Other current assets", attr("other_current_assets"), ()),
    ("money", "current-assets", "Total current assets", attr("current_assets"), ("total",)),
    ("money", "property-plant-equipment", "Property, plant and equipment", attr("property_plant_equipment"), ()),
    ("money", "goodwill", "Goodwill", attr("goodwill"), ()),
    ("money", "intangible-assets", "Intangible assets", attr("intangible_assets"), ()),
    ("money", "other-noncurrent-assets", "Other non-current assets", attr("other_noncurrent_assets"), ()),
    ("money", "total-assets", "Total assets", attr("total_assets"), ("total",)),
    ("money", "accounts-payable", "Accounts payable", attr("accounts_payable"), ()),
    ("money", "current-debt", "Current debt", attr("current_debt"), ()),
    ("money", "other-current-liabilities", "Other current liabilities", attr("other_current_liabilities"), ()),
    ("money", "current-liabilities", "Total current liabilities", attr("current_liabilities"), ("total",)),
    ("money", "long-term-debt", "Long-term debt", attr("long_term_debt"), ()),
    ("money", "other-noncurrent-liabilities", "Other non-current liabilities", attr("other_noncurrent_liabilities"), ()),
    ("money", "total-liabilities", "Total liabilities",
     total(attr("current_liabilities"), attr("long_term_debt"), attr("other_noncurrent_liabilities")), ("total",)),
    ("money", "equity", "Stockholders' equity (with minority interests)", attr("equity"), ("total",)),
    ("section", "Cash flow statement"),
    ("money", "cf-net-income", "Net income", attr("net_income"), ()),
    ("money", "depreciation", "Depreciation (and amortization, if not reported apart)", attr("depreciation"), ()),
    ("money", "amortization", "Amortization of intangible assets", attr("amortization"), ()),
    ("money", "stock-compensation", "Stock-based compensation", attr("stock_compensation"), ()),
    ("money", "change-in-receivables", "Change in receivables", attr("change_in_receivables"), ()),
    ("money", "change-in-inventory", "Change in inventory", attr("change_in_inventory"), ()),
    ("money", "change-in-payables", "Change in payables", attr("change_in_payables"), ()),
    ("money", "other-operating-activities", "Other operating activities", attr("other_operating"), ()),
    ("money", "operating-cash-flow", "Cash from operations",
     cash_flow_total("net_income", "depreciation", "amortization", "stock_compensation", "change_in_receivables",
                     "change_in_inventory", "change_in_payables", "other_operating"), ("total",)),
    ("money", "capital-expenditures", "Capital expenditures", attr("capital_expenditures"), ()),
    ("money", "other-investing", "Other investing activities", attr("other_investing"), ()),
    ("money", "investing-cash-flow", "Cash from investing", cash_flow_total("capital_expenditures", "other_investing"), ("total",)),
    ("money", "borrowing", "Debt borrowed (repaid) and other financing", attr("borrowing_and_other_financing"), ()),
    ("money", "dividends", "Dividends paid", attr("dividends"), ()),
    ("money", "repurchases", "Shares repurchased", attr("repurchases"), ()),
    ("money", "financing-cash-flow", "Cash from financing", cash_flow_total("borrowing_and_other_financing", "dividends", "repurchases"), ("total",)),
    ("section", "Ratios"),
    ("ratio", "gross-margin", "Gross margin", ratio_of("gross-profit", "revenue")),
    ("ratio", "operating-margin", "Operating margin", ratio_of("operating-income", "revenue")),
    ("ratio", "net-margin", "Net margin", ratio_of("net-income", "revenue")),
    ("ratio", "tax-rate", "Tax rate (on income before taxes)", ratio_of("income-tax", "pretax-income")),
    ("ratio", "free-cash-flow-margin", "Free cash flow (cash from operations less capital expenditures) / revenue",
     lambda cell, year: '=IFERROR((%s+%s)/%s,"")' % (cell("operating-cash-flow"), cell("capital-expenditures"), cell("revenue"))),
    ("ratio", "return-on-equity", "Return on equity (a year's net income / equity)", ratio_of("net-income", "equity", annual=True)),
    ("ratio", "return-on-assets", "Return on assets (a year's net income / assets)", ratio_of("net-income", "total-assets", annual=True)),
    ("ratio", "debt-to-equity", "Debt / equity",
     lambda cell, year: '=IFERROR((%s+%s)/%s,"")' % (cell("current-debt"), cell("long-term-debt"), cell("equity"))),
    ("ratio", "net-debt-to-operating-income", "Net debt / a year's operating income",
     lambda cell, year: '=IFERROR((%s+%s-%s-%s)/(%s*%s),"")' % (cell("current-debt"), cell("long-term-debt"), cell("cash"),
                                                                 cell("short-term-investments"), cell("operating-income"), year)),
    ("ratio", "current-ratio", "Current assets / current liabilities", ratio_of("current-assets", "current-liabilities")),
    ("ratio", "receivable-days", "Receivables, days of revenue",
     lambda cell, year: '=IFERROR(%s/(%s*%s)*365,"")' % (cell("receivables"), cell("revenue"), year)),
    ("ratio", "capital-expenditures-percent", "Capital expenditures / revenue",
     lambda cell, year: '=IFERROR(-%s/%s,"")' % (cell("capital-expenditures"), cell("revenue"))),
]

BANK_ROWS = [
    ("section", "Income statement"),
    ("money", "interest-loans", "Interest and fees on loans", attr("interest_on_loans"), ()),
    ("money", "interest-securities", "Interest on securities and other", attr("interest_on_securities"), ()),
    ("money", "interest-income", "Total interest income", attr("interest_income"), ("total",)),
    ("money", "interest-deposits", "Interest on deposits", attr("interest_on_deposits"), ()),
    ("money", "interest-borrowings", "Interest on borrowings", attr("interest_on_borrowings"), ()),
    ("money", "interest-expense", "Total interest expense", attr("interest_expense"), ("total",)),
    ("money", "net-interest-income", "Net interest income", attr("net_interest_income"), ("total",)),
    ("money", "noninterest-income", "Noninterest income", attr("noninterest_income"), ()),
    ("money", "basis-revenue", "Net revenue (net interest income plus noninterest income)",
     total(attr("net_interest_income"), attr("noninterest_income")), ("total",)),
    ("money", "noninterest-expense", "Noninterest expense", attr("noninterest_expense"), ()),
    ("money", "pre-provision-profit", "Profit before credit losses",
     lambda h, i: h.net_interest_income[i] + h.noninterest_income[i] - h.noninterest_expense[i], ("total",)),
    ("money", "provision", "Provision for credit losses", attr("provision"), ()),
    ("money", "other-income", "Other income (expense)", attr("other_income"), ()),
    ("money", "pretax-income", "Income before taxes", attr("pretax_income"), ("total",)),
    ("money", "income-tax", "Income taxes", attr("income_tax"), ()),
    ("money", "other-net-income", "Minority interests, preferred dividends, other", attr("other_net_income"), ()),
    ("money", "net-income", "Net income", attr("net_income"), ("total",)),
    ("money", "net-charge-offs", "Memo: net charge-offs", attr("net_charge_offs"), ("italic",)),
    ("absolute", "shares", "Diluted shares, millions", attr("shares"), "decimal"),
    ("absolute", "eps", "Earnings per share, diluted", lambda h, i: h.net_income[i] / h.shares[i] if h.shares[i] else None, "per-share"),
    ("section", "Balance sheet"),
    ("money", "cash", "Cash and equivalents", attr("cash"), ()),
    ("money", "securities", "Securities (available for sale and held to maturity)", attr("securities"), ()),
    ("money", "loans", "Loans, before the allowance", attr("loans"), ()),
    ("money", "allowance", "Less: allowance for credit losses", attr("allowance"), ()),
    ("money", "net-loans", "Loans, net of the allowance", attr("net_loans"), ("total",)),
    ("money", "other-assets", "Other assets", attr("other_assets"), ()),
    ("money", "total-assets", "Total assets", attr("total_assets"), ("total",)),
    ("money", "deposits", "Deposits", attr("deposits"), ()),
    ("money", "borrowings", "Borrowings", attr("borrowings"), ()),
    ("money", "other-liabilities", "Other liabilities", attr("other_liabilities"), ()),
    ("money", "total-liabilities", "Total liabilities", total(attr("deposits"), attr("borrowings"), attr("other_liabilities")), ("total",)),
    ("money", "equity", "Stockholders' equity (with minority interests)", attr("equity"), ("total",)),
    ("section", "Cash flow statement"),
    ("money", "cf-net-income", "Net income", attr("net_income"), ()),
    ("money", "other-operating-activities", "Other operating activities", attr("other_operating"), ()),
    ("money", "operating-cash-flow", "Cash from operations", cash_flow_total("net_income", "other_operating"), ("total",)),
    ("money", "change-in-loans", "Increase in loans, net of the allowance", attr("change_in_loans"), ()),
    ("money", "change-in-securities", "Increase in securities", attr("change_in_securities"), ()),
    ("money", "other-investing", "Other investing activities", attr("other_investing"), ()),
    ("money", "investing-cash-flow", "Cash from investing", cash_flow_total("change_in_loans", "change_in_securities", "other_investing"), ("total",)),
    ("money", "change-in-deposits", "Increase in deposits", attr("change_in_deposits"), ()),
    ("money", "change-in-borrowings", "Increase in borrowings", attr("change_in_borrowings"), ()),
    ("money", "dividends", "Dividends paid", attr("dividends"), ()),
    ("money", "repurchases", "Shares repurchased", attr("repurchases"), ()),
    ("money", "other-financing", "Other financing activities", attr("other_financing"), ()),
    ("money", "financing-cash-flow", "Cash from financing",
     cash_flow_total("change_in_deposits", "change_in_borrowings", "dividends", "repurchases", "other_financing"), ("total",)),
    ("section", "Ratios"),
    ("ratio", "efficiency-ratio", "Efficiency ratio (noninterest expense / net revenue)", ratio_of("noninterest-expense", "basis-revenue")),
    ("ratio", "net-interest-margin", "Net interest margin (a year's net interest income / cash, securities, loans)",
     lambda cell, year: '=IFERROR(%s*%s/(%s+%s+%s),"")' % (cell("net-interest-income"), year, cell("cash"), cell("securities"), cell("loans"))),
    ("ratio", "loan-yield", "Interest rate on loans (a year's interest / loans)", ratio_of("interest-loans", "loans", annual=True)),
    ("ratio", "deposit-cost", "Interest rate on deposits (a year's interest / deposits)", ratio_of("interest-deposits", "deposits", annual=True)),
    ("ratio", "return-on-equity", "Return on equity (a year's net income / equity)", ratio_of("net-income", "equity", annual=True)),
    ("ratio", "return-on-assets", "Return on assets (a year's net income / assets)", ratio_of("net-income", "total-assets", annual=True)),
    ("ratio", "loans-to-deposits", "Loans / deposits", ratio_of("loans", "deposits")),
    ("ratio", "equity-to-assets", "Equity / assets", ratio_of("equity", "total-assets")),
    ("ratio", "allowance-to-loans", "Allowance / loans", ratio_of("allowance", "loans")),
    ("ratio", "charge-off-rate", "Net charge-offs (a year's) / loans", ratio_of("net-charge-offs", "loans", annual=True)),
]

INSURER_ROWS = [
    ("section", "Income statement"),
    ("money", "premiums-earned", "Premiums earned", attr("premiums"), ()),
    ("money", "net-investment-income", "Net investment income", attr("investment_income"), ()),
    ("money", "realized-gains", "Realized investment gains (losses)", attr("gains"), ()),
    ("money", "other-revenue", "Other revenue", attr("other_revenue"), ()),
    ("money", "basis-revenue", "Total revenues", attr("revenue"), ("total",)),
    ("money", "losses", "Losses and loss adjustment expense", attr("losses"), ()),
    ("money", "other-expenses", "Policy acquisition, underwriting, and other expenses", attr("other_expenses"), ()),
    ("money", "interest-expense", "Interest expense", attr("interest_expense"), ()),
    ("money", "pretax-income", "Income before taxes", attr("pretax_income"), ("total",)),
    ("money", "income-tax", "Income taxes", attr("income_tax"), ()),
    ("money", "other-net-income", "Minority interests, preferred dividends, other", attr("other_net_income"), ()),
    ("money", "net-income", "Net income", attr("net_income"), ("total",)),
    ("money", "underwriting-income", "Memo: underwriting income (premiums less losses and other expenses)",
     lambda h, i: h.premiums[i] - h.losses[i] - h.other_expenses[i], ("italic",)),
    ("absolute", "shares", "Diluted shares, millions", attr("shares"), "decimal"),
    ("absolute", "eps", "Earnings per share, diluted", lambda h, i: h.net_income[i] / h.shares[i] if h.shares[i] else None, "per-share"),
    ("section", "Balance sheet"),
    ("money", "cash", "Cash and equivalents", attr("cash"), ()),
    ("money", "investments", "Investments", attr("investments"), ()),
    ("money", "premiums-receivable", "Premiums receivable", attr("premiums_receivable"), ()),
    ("money", "reinsurance-recoverable", "Reinsurance recoverables", attr("reinsurance_recoverable"), ()),
    ("money", "deferred-acquisition-costs", "Deferred policy acquisition costs", attr("deferred_acquisition_costs"), ()),
    ("money", "goodwill", "Goodwill", attr("goodwill"), ()),
    ("money", "intangible-assets", "Intangible assets", attr("intangible_assets"), ()),
    ("money", "other-assets", "Other assets", attr("other_assets"), ()),
    ("money", "total-assets", "Total assets", attr("total_assets"), ("total",)),
    ("money", "loss-reserves", "Loss and loss adjustment expense reserves", attr("loss_reserves"), ()),
    ("money", "unearned-premiums", "Unearned premiums", attr("unearned_premiums"), ()),
    ("money", "debt", "Debt", attr("debt"), ()),
    ("money", "other-liabilities", "Other liabilities", attr("other_liabilities"), ()),
    ("money", "total-liabilities", "Total liabilities",
     total(attr("loss_reserves"), attr("unearned_premiums"), attr("debt"), attr("other_liabilities")), ("total",)),
    ("money", "equity", "Stockholders' equity (with minority interests)", attr("equity"), ("total",)),
    ("section", "Cash flow statement"),
    ("money", "cf-net-income", "Net income", attr("net_income"), ()),
    ("money", "change-in-reserves", "Increase in loss reserves", attr("change_in_reserves"), ()),
    ("money", "change-in-unearned", "Increase in unearned premiums", attr("change_in_unearned"), ()),
    ("money", "change-in-receivable", "Increase in premiums receivable", attr("change_in_receivable"), ()),
    ("money", "change-in-reinsurance", "Increase in reinsurance recoverables", attr("change_in_reinsurance"), ()),
    ("money", "change-in-acquisition-costs", "Increase in deferred acquisition costs", attr("change_in_acquisition_costs"), ()),
    ("money", "other-operating-activities", "Other operating activities", attr("other_operating"), ()),
    ("money", "operating-cash-flow", "Cash from operations",
     cash_flow_total("net_income", "change_in_reserves", "change_in_unearned", "change_in_receivable", "change_in_reinsurance",
                     "change_in_acquisition_costs", "other_operating"), ("total",)),
    ("money", "investment-purchases", "Net purchases of investments", attr("investment_purchases"), ()),
    ("money", "other-investing", "Other investing activities", attr("other_investing"), ()),
    ("money", "investing-cash-flow", "Cash from investing", cash_flow_total("investment_purchases", "other_investing"), ("total",)),
    ("money", "borrowing", "Debt borrowed (repaid) and other financing", attr("borrowing_and_other_financing"), ()),
    ("money", "dividends", "Dividends paid", attr("dividends"), ()),
    ("money", "repurchases", "Shares repurchased", attr("repurchases"), ()),
    ("money", "financing-cash-flow", "Cash from financing", cash_flow_total("borrowing_and_other_financing", "dividends", "repurchases"), ("total",)),
    ("section", "Ratios"),
    ("ratio", "loss-ratio", "Loss ratio (losses / premiums earned)", ratio_of("losses", "premiums-earned")),
    ("ratio", "expense-ratio", "Expense ratio (other expenses / premiums earned)", ratio_of("other-expenses", "premiums-earned")),
    ("ratio", "combined-ratio", "Combined ratio (under 100% is an underwriting profit)",
     lambda cell, year: '=IFERROR((%s+%s)/%s,"")' % (cell("losses"), cell("other-expenses"), cell("premiums-earned"))),
    ("ratio", "investment-yield", "Net investment income (a year's) / investments and cash",
     lambda cell, year: '=IFERROR(%s*%s/(%s+%s),"")' % (cell("net-investment-income"), year, cell("investments"), cell("cash"))),
    ("ratio", "return-on-equity", "Return on equity (a year's net income / equity)", ratio_of("net-income", "equity", annual=True)),
    ("ratio", "premiums-to-equity", "A year's premiums earned / equity", ratio_of("premiums-earned", "equity", annual=True)),
    ("ratio", "reserves-to-equity", "Loss reserves / equity", ratio_of("loss-reserves", "equity")),
    ("ratio", "investments-to-equity", "Investments and cash / equity",
     lambda cell, year: '=IFERROR((%s+%s)/%s,"")' % (cell("investments"), cell("cash"), cell("equity"))),
]

ROWS = {"general": GENERAL_ROWS, "bank": BANK_ROWS, "insurer": INSURER_ROWS}
BASIS_NAMES = {"general": "revenue", "bank": "net revenue (net interest income plus noninterest income)",
               "insurer": "total revenues"}


# ---------------------------------------------------------------------------
# One company's numbers
# ---------------------------------------------------------------------------

class CompanyColumn:
    """One company's most recent period: its names, period, currency, and the value of every row."""

    def __init__(self, credentials_path, company, kind_wanted, period, who):
        facts = lisp_sec.company_facts(credentials_path, company, who)
        self.ticker = str(company).upper()
        self.name = facts.get("entityName") or self.ticker
        sic, self.industry = model.company_industry(credentials_path, company, who)
        guess = model.kind_for_industry(sic)
        self.industry_kind = "general" if guess == "asset-manager" else guess
        self.kind = kind_wanted if kind_wanted != "auto" else self.industry_kind
        template = model.templates()[self.kind]
        periods = list(reversed(lisp_sec.chosen_periods(facts, {"period": period, "count": 2}, who)))
        self.reported = model.Reported(facts, periods, template.items)
        latest = len(periods) - 1
        missing = template.lacking(self.reported, latest)
        if missing:
            raise LispError('%s: %s: a model of %s needs %s, which the SEC\'s facts do not have for the latest %s period; '
                            'compare it as an ordinary company with :kind "general", or leave it out'
                            % (who, self.ticker, template.description, ", ".join(missing), period))
        self.history = template.history_class(self.reported)
        self.latest = latest
        end = periods[latest]
        self.period = end
        self.label = ("FY%s" % (end.fiscal_year or end.end.year) if period == "annual"
                      else "%s FY%s" % (end.fiscal_period, end.fiscal_year or end.end.year))
        self.currency = self.reported.currency
        if end.fiscal_period == "FY":
            self.days = (end.end - end.year_start).days + 1
        elif end.previous_end is not None:
            self.days = (end.end - end.previous_end).days
        else:
            self.days = (end.end - end.year_start).days + 1

    def value(self, row):
        """The value of a "money" or "absolute" row for this company: a number, or None."""
        number = row[3](self.history, self.latest)
        return None if number is None else float(number)


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------

class Comparison:
    """The comparison: the companies, the kind, the basis, and the tabs they make."""

    def __init__(self, columns, kind, basis, period):
        self.columns, self.kind, self.basis, self.period = columns, kind, basis, period
        self.rows = ROWS[kind]
        self.count = len(columns)
        self.first_data_row = 0
        self.layout = self.layout_rows()

    # --- where things are

    def layout_rows(self):
        """The rows of the tabs below the header: a list of (the row, or None for a blank line), and the sheet row
        number (counted from 1) of each key. The header is the five rows 1-5, a blank 6; the days, a row of its own."""
        lines = [("days",)]
        lines += self.rows
        self.row_of = {}
        position = 7
        result = []
        for row in lines:
            if row[0] == "section" and result:
                result.append(None)
                position += 1
            result.append(row)
            if row[0] != "section":
                self.row_of[row[1] if row[0] != "days" else "days"] = position
            position += 1
        return result

    def column_letter(self, j):
        return model.column_letter(FIRST_COMPANY_COLUMN + j)

    @property
    def median_column(self):
        return model.column_letter(FIRST_COMPANY_COLUMN + self.count)

    def basis_key(self):
        return {"revenue": "basis-revenue" if "basis-revenue" in self.row_of else "revenue", "assets": "total-assets"}[self.basis]

    # --- the header

    def header(self, title_text, units_text, with_median):
        width = FIRST_COMPANY_COLUMN + self.count + (1 if with_median else 0)
        rows = [[None] * width for _ in range(5)]
        rows[0][0] = (title_text, ("title",))
        rows[1][0] = (units_text, ("italic",))
        rows[2][0], rows[3][0], rows[4][0] = ("Company", ("bold",)), ("Period ends", ()), ("Fiscal period, currency", ())
        for j, column in enumerate(self.columns):
            rows[2][FIRST_COMPANY_COLUMN + j] = ("%s (%s)" % (column.name, column.ticker), ("header", "wrap"))
            rows[3][FIRST_COMPANY_COLUMN + j] = (column.period.end, ("date",))
            rows[4][FIRST_COMPANY_COLUMN + j] = ("%s, %s" % (column.label, column.currency), ("italic",))
        if with_median:
            rows[2][width - 1] = ("Median", ("header",))
        return rows

    # --- the numbers as reported, and the ratios

    def reported_cells(self, with_median):
        """The rows of numbers: each company's value (blue), for the rows that are amounts or numbers, and the ratios
        as formulas of the rows above, in each company's column."""
        cells = self.header("Companies side by side: %s" % self.kind_description(),
                            "%s millions, as reported to the SEC (earnings per share, and shares, as they are)" % self.currency_text(),
                            with_median)
        cells.append([None] * len(cells[0]))
        width = len(cells[0])
        for line in self.layout:
            row = [None] * width
            if line is None:
                cells.append(row)
                continue
            kind = line[0]
            if kind == "section":
                row[0] = (line[1], ("section",))
                for j in range(1, width):
                    row[j] = (None, ("section",))
            elif kind == "days":
                row[0] = ("Days in the period", ())
                for j, column in enumerate(self.columns):
                    row[FIRST_COMPANY_COLUMN + j] = (float(column.days), ("data", "decimal"))
            elif kind in ("money", "absolute"):
                row[0] = (line[2], line[4] if kind == "money" else ())
                number_format = "money" if kind == "money" else line[4]
                for j, column in enumerate(self.columns):
                    number = column.value(line)
                    if number is not None:
                        row[FIRST_COMPANY_COLUMN + j] = (number, ("data", number_format) + (line[4] if kind == "money" else ()))
            else:                                                       # a ratio
                row[0] = (line[2], ("italic",))
                for j in range(self.count):
                    letter = self.column_letter(j)
                    formula = line[3](lambda key, letter=letter: "%s%d" % (letter, self.row_of[key]),
                                      "365/%s%d" % (letter, self.row_of["days"]))
                    row[FIRST_COMPANY_COLUMN + j] = (formula, ("percent" if self.is_percent_ratio(line[1]) else "decimal",))
                if with_median:
                    row[width - 1] = (self.median(line[1]), (self.ratio_format(line[1]),))
            cells.append(row)
        return cells

    def median(self, key):
        first, last = self.column_letter(0), self.column_letter(self.count - 1)
        return "=IFERROR(MEDIAN(%s%d:%s%d),\"\")" % (first, self.row_of[key], last, self.row_of[key])

    DECIMAL_RATIOS = ("receivable-days", "debt-to-equity", "net-debt-to-operating-income", "current-ratio", "premiums-to-equity",
                      "reserves-to-equity", "investments-to-equity")

    def is_percent_ratio(self, key):
        return key not in self.DECIMAL_RATIOS

    def ratio_format(self, key):
        return "percent" if self.is_percent_ratio(key) else "decimal"

    # --- the comparison

    def comparison_cells(self):
        """With a basis: each amount over the basis, as a formula referring to the 'As reported' tab, and the ratios
        linked from there; a median for each row."""
        reported = model.quoted_tab(AS_REPORTED)
        basis_row = self.row_of[self.basis_key()]
        basis_name = BASIS_NAMES[self.kind] if self.basis == "revenue" else "total assets"
        cells = self.header("Companies side by side, as a percentage of %s" % basis_name,
                            "Each amount in the company's statements divided by its %s; shares and earnings per share as they are" % basis_name,
                            True)
        cells.append([None] * len(cells[0]))
        width = len(cells[0])
        for line in self.layout:
            row = [None] * width
            if line is None:
                cells.append(row)
                continue
            kind = line[0]
            if kind == "section":
                row[0] = (line[1], ("section",))
                for j in range(1, width):
                    row[j] = (None, ("section",))
            elif kind == "days":
                row[0] = ("Days in the period", ())
                for j in range(self.count):
                    row[FIRST_COMPANY_COLUMN + j] = ("=%s!%s%d" % (reported, self.column_letter(j), self.row_of["days"]), ("link", "decimal"))
            else:
                row[0] = (line[2], line[4] if kind == "money" else (("italic",) if kind == "ratio" else ()))
                for j in range(self.count):
                    letter = self.column_letter(j)
                    source = "%s!%s%d" % (reported, letter, self.row_of[line[1]])
                    if kind == "money":
                        row[FIRST_COMPANY_COLUMN + j] = ('=IFERROR(%s/%s!%s$%d,"")' % (source, reported, letter, basis_row),
                                                         ("percent",) + tuple(s for s in line[4] if s in ("total", "bold", "italic")))
                    elif kind == "absolute":
                        row[FIRST_COMPANY_COLUMN + j] = ("=%s" % source, ("link", line[4]))
                    else:
                        row[FIRST_COMPANY_COLUMN + j] = ("=%s" % source, ("link", self.ratio_format(line[1])))
                if kind in ("money", "ratio"):
                    row[width - 1] = (self.median(line[1]), (("percent",) if kind == "money" else (self.ratio_format(line[1]),)))
            cells.append(row)
        return cells

    # --- the notes

    def kind_description(self):
        return {"general": "ordinary companies", "bank": "banks", "insurer": "property and casualty insurers"}[self.kind]

    def currency_text(self):
        currencies = []
        for column in self.columns:
            if column.currency not in currencies:
                currencies.append(column.currency)
        return "/".join(currencies)

    def notes_tab(self):
        lines = [
            ("Companies side by side", "section"),
            ("Each column is one company's most recent %s period from the SEC (its 10-K%s), with the same rows for every company. "
             "Fiscal years end at different times: the dates are at the top." % (self.period, "" if self.period == "annual" else " or 10-Q"), "wrap"),
            ("The rows are those of %s: the lines the companies report are put in them, and what a company reports that has no line "
             "of its own is in the 'other' lines, so that every subtotal is the company's." % self.kind_description(), "wrap"),
        ]
        if self.basis != "none":
            what = BASIS_NAMES[self.kind] if self.basis == "revenue" else "total assets"
            lines += [("Comparison is each amount divided by the company's %s, so that companies of different sizes can be compared; "
                       "the 'As reported' tab has the numbers themselves, in millions, and the ratios. Change a number there and "
                       "the Comparison follows." % what, "wrap"),
                      ("The Median column is the middle company's value in each row.", "wrap")]
        else:
            lines.append(("The Median column, for the ratios, is the middle company's value.", "wrap"))
        lines.append(("Ratios use the period's end balances, and a year's flows (a quarter's times 365 over its days).", "wrap"))
        lines.append(("", "wrap"))
        lines.append(("The companies", "section"))
        for column in self.columns:
            lines.append(("%s (%s): %s, %s ending %s, in %s%s" % (
                column.name, column.ticker, column.industry or "industry unknown", column.label, column.period.end.isoformat(),
                column.currency, "" if column.kind == column.industry_kind else
                "; modeled as %s because you asked" % model.templates()[column.kind].description), "wrap"))
        return {"name": NOTES, "cells": [[(("Companies side by side"), ("title",))], [None]] + [[(text, (style,))] if text else [None] for text, style in lines],
                "widths": [(0, 0, 900)]}

    def sheets(self):
        width_settings = [(0, 0, LABEL_WIDTH), (1, self.count + 1, COMPANY_WIDTH)]
        if self.basis == "none":
            tabs = [{"name": COMPARISON, "cells": self.reported_cells(True)}]
        else:
            tabs = [{"name": COMPARISON, "cells": self.comparison_cells()},
                    {"name": AS_REPORTED, "cells": self.reported_cells(True)}]
        for tab in tabs:
            tab.update(frozen_rows=5, frozen_columns=1, widths=width_settings)
        return tabs + [self.notes_tab()]


# ---------------------------------------------------------------------------
# The builtin
# ---------------------------------------------------------------------------

def build_comparison(columns, kind, basis, period, who):
    """The Comparison of these companies (CompanyColumns): checks that they are one kind and can be compared."""
    kinds = []
    for column in columns:
        if column.kind not in kinds:
            kinds.append(column.kind)
    if len(kinds) > 1:
        raise LispError('%s: these companies are not all of one kind (%s), so their statements do not have the same rows: '
                        'compare companies of one kind, or give :kind "general" to compare them all as ordinary companies'
                        % (who, ", ".join("%s: %s" % (c.ticker, c.kind) for c in columns)))
    currencies = {column.currency for column in columns}
    if basis == "none" and len(currencies) > 1:
        raise LispError("%s: these companies report in different currencies (%s), so their amounts cannot be compared "
                        'as they are: give :basis "revenue" or "assets"' % (who, ", ".join(sorted(currencies))))
    return Comparison(columns, kinds[0], basis, period)


def compare_companies(credentials_path, companies, *options):
    """(compare-companies creds '("ACN" "EFX" "CTSH") [:basis "revenue" :period "annual" :kind "auto" :title t])
    -- a new Google spreadsheet with the companies' most recent annual (or quarterly) statements side by side, a
    column for each, the same rows for all: the income statement, balance sheet, cash flow statement, and ratios,
    of an ordinary company, a bank, or a property and casualty insurer (:kind; "auto" chooses by the SEC's
    industry codes, and the companies must be all one kind). :basis "none" (the default) shows the amounts in
    millions; "revenue" shows each as a percentage of the company's top line (a bank's net revenue), and "assets"
    of its total assets, so that companies of different sizes compare; a column of medians shows what is typical.
    Returns the spreadsheet's address. You need to be signed in to Google: (google-login creds)."""
    who = "compare-companies"
    options = keyword_options(options, ["basis", "period", "kind", "title"], who)
    tickers = text_list(companies, who, "the companies")
    if len(tickers) < 2:
        raise LispError("%s: give at least two companies, such as '(\"ACN\" \"EFX\")" % who)
    if len(tickers) > MOST_COMPANIES:
        raise LispError("%s: at most %d companies" % (who, MOST_COMPANIES))
    if len({t.upper() for t in tickers}) < len(tickers):
        raise LispError("%s: a company is given twice" % who)
    basis = str(options.get("basis", "none"))
    if basis not in BASES:
        raise LispError('%s: :basis is "none", "revenue", or "assets", not %s' % (who, basis))
    period = str(options.get("period", "annual"))
    if period not in ("annual", "quarterly"):
        raise LispError('%s: :period is "annual" or "quarterly", not %s' % (who, period))
    kind = str(options.get("kind", "auto"))
    if kind != "auto" and kind not in ROWS:
        raise LispError('%s: :kind is "auto", "general", "bank", or "insurer", not %s' % (who, kind))
    columns = [CompanyColumn(credentials_path, ticker, kind, period, who) for ticker in tickers]
    comparison = build_comparison(columns, kind, basis, period, who)
    title = options.get("title") or "%s compared (%s)" % (", ".join(c.ticker for c in columns), basis if basis != "none" else period)
    return LispString(lisp_google.google_workbook(credentials_path, str(title), comparison.sheets()))


BUILTINS = {
    "compare-companies": compare_companies,
}
