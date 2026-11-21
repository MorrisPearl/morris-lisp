"""Companies side by side, in a Google Sheet.

  (compare-companies creds '("ACN" "EFX" "CTSH") [:basis "revenue" :period "annual" :kind "auto" :title t])
  (compare-companies creds "KEY" :peers 5)            the company and the five comparable companies nearest to it in size

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

At the bottom of the sheet are the VALUATION rows (lisp_financial_compare_valuation.py): what the market pays for each
company, against what it earns, owns, and pays out -- market value, enterprise value, and the multiples and yields they
make. They need share prices, which :prices says where to get: a list of them, #t for Alpha Vantage's latest, or (the
default) the closing prices in the table stock_returns of the database financial_data.db, when it has them all.
:estimates adds what analysts expect the companies to earn (and the forward P/E that makes).

:peers chooses the companies to compare with: given one company, it finds those in its industry, in the table
ticker_industry of the database (lisp_financial_peers.py), nearest to it in market capitalization, and skips those the
SEC's statements cannot be used for (a second share class of the same company, another kind of company, another
currency, a report that is old). The company is the first column, the median column is of its peers alone, a column
beside it says how far the company is from them, and the valuation rows end with what the company would be worth at its
peers' median multiples. The Notes tab says who was chosen, and who was skipped, and why.
"""

import datetime
import math

from lisp_core import LispError, LispString, keyword_options
from lisp_data_common import text_list
import lisp_financial_compare_valuation as valuation
import lisp_financial_model as model
import lisp_financial_peers as peers_module
import lisp_google
import lisp_sec

COMPARISON, AS_REPORTED, NOTES = "Comparison", "As reported", "Notes"
BASES = ("none", "revenue", "assets")
LABEL_WIDTH = 330
COMPANY_WIDTH = 105
FIRST_COMPANY_COLUMN = 1               # (column A has the labels)
MOST_COMPANIES = 40
DEFAULT_PEERS = 5                      # :peers #t
MOST_PEERS = 15
TRIES_PER_PEER = 4                     # how many of the nearest in size to look at, for each peer wanted
OLDEST_REPORT_DAYS = {"annual": 456, "quarterly": 200}      # a peer's latest period ended no longer ago than this
FAR_IN_SIZE = 4                        # a peer more than this many times as big as the company, or less than a fourth of it, is far from it
ESTIMATE_GAP_DAYS = 180                # an analysts' estimate is of a year after the latest reported if it is this much later


def today():
    return datetime.date.today()


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
    ("money", "preferred-dividends", "Preferred dividends", attr("preferred_dividends"), ()),
    ("money", "income-to-common", "Net income to common shareholders",
     lambda h, i: h.net_income[i] - h.preferred_dividends[i], ("total",)),
    ("money", "net-charge-offs", "Memo: net charge-offs", attr("net_charge_offs"), ("italic",)),
    ("absolute", "shares", "Diluted shares, millions", attr("shares"), "decimal"),
    ("absolute", "eps", "Earnings per share, diluted (net income to common shareholders / shares)",
     lambda h, i: (h.net_income[i] - h.preferred_dividends[i]) / h.shares[i] if h.shares[i] else None, "per-share"),
    ("section", "Balance sheet"),
    ("money", "cash", "Cash and equivalents", attr("cash"), ()),
    ("money", "securities", "Securities (available for sale and held to maturity)", attr("securities"), ()),
    ("money", "loans", "Loans, before the allowance", attr("loans"), ()),
    ("money", "allowance", "Less: allowance for credit losses", attr("allowance"), ()),
    ("money", "net-loans", "Loans, net of the allowance", attr("net_loans"), ("total",)),
    ("money", "goodwill-and-intangibles", "Goodwill and intangible assets", attr("goodwill_and_intangibles"), ()),
    ("money", "other-assets", "Other assets", attr("other_assets"), ()),
    ("money", "total-assets", "Total assets", attr("total_assets"), ("total",)),
    ("money", "deposits", "Deposits", attr("deposits"), ()),
    ("money", "borrowings", "Borrowings", attr("borrowings"), ()),
    ("money", "other-liabilities", "Other liabilities", attr("other_liabilities"), ()),
    ("money", "total-liabilities", "Total liabilities", total(attr("deposits"), attr("borrowings"), attr("other_liabilities")), ("total",)),
    ("money", "equity", "Stockholders' equity (with minority interests)", attr("equity"), ("total",)),
    ("money", "preferred-and-minority", "Memo: preferred stock and minority interests", attr("preferred_and_minority"), ("italic",)),
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

IMPLIED_KINDS = ("implied", "implied-median", "implied-gap")
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
        self.cik = facts.get("cik")
        self.name = facts.get("entityName") or self.ticker
        self.market = {}                # what the market gives (a number for each of the keys): the price, analysts' estimates
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

    @property
    def price(self):
        return self.market.get("price")

    def value(self, row):
        """The value of a "money" or "absolute" row for this company: a number, or None."""
        if row[1] in self.market:
            return self.market[row[1]]
        if row[1] == "eps-before":
            before = self.latest - 1
            shares = self.history.shares[before]
            return self.history.net_income[before] / shares if shares else None
        if row[3] is None:                       # (a number the market gives, and has not given)
            return None
        number = row[3](self.history, self.latest)
        return None if number is None else float(number)


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------

class Comparison:
    """The comparison: the companies, the kind, the basis, and the tabs they make."""

    def __init__(self, columns, kind, basis, period, peers=False, estimates=False, notes=()):
        """`peers`: the first column is a company whose peers the others are. `estimates`: the companies have analysts'
        estimates (some of them). `notes`: more lines for the Notes tab, (text, style)."""
        self.columns, self.kind, self.basis, self.period = columns, kind, basis, period
        self.peers, self.extra_notes = peers, list(notes)
        self.rows = list(ROWS[kind])
        self.valued = all(column.price is not None for column in columns)         # (the market's rows need every price)
        if self.valued:
            self.rows += valuation.rows_for(kind, period, estimates, peers)
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
        self.implied_keys = []                       # the rows of what the target would be worth, in order
        position = 7
        result = []
        for row in lines:
            if row[0] == "section" and result:
                result.append(None)
                position += 1
            result.append(row)
            if row[0] != "section":
                self.row_of[row[1] if row[0] != "days" else "days"] = position
            if row[0] == "implied":
                self.implied_keys.append(row[1])
            position += 1
        return result

    def column_letter(self, j):
        return model.column_letter(FIRST_COMPANY_COLUMN + j)

    @property
    def median_index(self):
        """The index, in a row, of the median column: after the companies' columns."""
        return FIRST_COMPANY_COLUMN + self.count

    @property
    def median_column(self):
        return model.column_letter(self.median_index)

    @property
    def width(self):
        """How many columns a tab has: the labels, the companies, the median, and (with peers) how far the first company is
        from it."""
        return self.median_index + (2 if self.peers else 1)

    def basis_key(self):
        return {"revenue": "basis-revenue" if "basis-revenue" in self.row_of else "revenue", "assets": "total-assets"}[self.basis]

    # --- the header

    def header(self, title_text, units_text, with_median):
        width = self.width
        rows = [[None] * width for _ in range(5)]
        rows[0][0] = (title_text, ("title",))
        rows[1][0] = (units_text, ("italic",))
        rows[2][0], rows[3][0], rows[4][0] = ("Company", ("bold",)), ("Period ends", ()), ("Fiscal period, currency", ())
        for j, column in enumerate(self.columns):
            rows[2][FIRST_COMPANY_COLUMN + j] = ("%s (%s)" % (column.name, column.ticker), ("header", "wrap"))
            rows[3][FIRST_COMPANY_COLUMN + j] = (column.period.end, ("date",))
            rows[4][FIRST_COMPANY_COLUMN + j] = ("%s, %s" % (column.label, column.currency), ("italic",))
        if with_median:
            rows[2][self.median_index] = ("Peers' median" if self.peers else "Median", ("header", "wrap"))
            if self.peers:
                rows[2][self.median_index + 1] = ("%s vs the peers' median" % self.columns[0].ticker, ("header", "wrap"))
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
            elif kind in IMPLIED_KINDS:                                 # what the first company would be worth
                row[0] = (line[2], self.implied_label_styles(kind))
                row[FIRST_COMPANY_COLUMN] = (self.implied_formula(line), self.implied_styles(kind))
            else:                                                       # a ratio
                row[0] = (line[2], ("italic",))
                for j in range(self.count):
                    letter = self.column_letter(j)
                    formula = line[3](self.cell_function(letter), "365/%s%d" % (letter, self.row_of["days"]))
                    row[FIRST_COMPANY_COLUMN + j] = (formula, (self.ratio_format(line[1]),))
                if with_median:
                    self.add_median_cells(row, line[1])
            cells.append(row)
        return cells

    def cell_function(self, letter):
        """A function from a row's key to the address of its cell in the column with this letter."""
        return lambda key: "%s%d" % (letter, self.row_of[key])

    def median(self, key):
        """The median of a row's cells: of the companies (of the peers alone, leaving out the first company, if its peers
        were chosen)."""
        first, last = self.column_letter(1 if self.peers else 0), self.column_letter(self.count - 1)
        return "=IFERROR(MEDIAN(%s%d:%s%d),\"\")" % (first, self.row_of[key], last, self.row_of[key])

    def median_address(self, key):
        """The address of a row's cell in the median column."""
        return "%s%d" % (self.median_column, self.row_of[key])

    def add_median_cells(self, row, key):
        """The median of a ratio's row; and, with peers chosen, for the multiples, how far above (or below) their median
        the first company's multiple is."""
        row[self.median_index] = (self.median(key), (self.ratio_format(key),))
        if self.peers and key in valuation.MULTIPLES:
            target = self.column_letter(0)
            row[self.median_index + 1] = ('=IFERROR(%s%d/%s-1,"")' % (target, self.row_of[key], self.median_address(key)),
                                          ("percent",))

    # --- what the first company would be worth at its peers' median multiples

    def implied_label_styles(self, kind):
        return {"implied": (), "implied-median": ("total",), "implied-gap": ("italic",)}[kind]

    def implied_styles(self, kind, link=False):
        formats = ("percent",) if kind == "implied-gap" else ("per-share",) + (("total",) if kind == "implied-median" else ())
        return (("link",) if link else ()) + formats

    def implied_formula(self, line):
        """A formula, in the first company's column, of a row of what that company would be worth: the price at the
        peers' median of a multiple, the median of those prices, or how far that is above the share price."""
        letter = self.column_letter(0)
        cell = self.cell_function(letter)
        if line[0] == "implied":
            return line[3](cell, self.median_address, "365/%s%d" % (letter, self.row_of["days"]))
        if line[0] == "implied-median":
            return '=IFERROR(MEDIAN(%s%d:%s%d),"")' % (letter, self.row_of[self.implied_keys[0]], letter,
                                                       self.row_of[self.implied_keys[-1]])
        return '=IFERROR(%s/%s-1,"")' % (cell("implied-median"), cell("price"))

    # --- the formats of the ratios

    DECIMAL_RATIOS = ("receivable-days", "debt-to-equity", "net-debt-to-operating-income", "current-ratio", "premiums-to-equity",
                      "reserves-to-equity", "investments-to-equity") + valuation.MULTIPLES

    def is_percent_ratio(self, key):
        return key not in self.DECIMAL_RATIOS and key not in valuation.MONEY_KEYS

    def ratio_format(self, key):
        if key in valuation.MONEY_KEYS:
            return "money"
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
            elif kind in IMPLIED_KINDS:
                row[0] = (line[2], self.implied_label_styles(kind))
                row[FIRST_COMPANY_COLUMN] = ("=%s!%s%d" % (reported, self.column_letter(0), self.row_of[line[1]]),
                                             self.implied_styles(kind, link=True))
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
                if kind == "money":
                    row[self.median_index] = (self.median(line[1]), ("percent",))
                elif kind == "ratio":
                    self.add_median_cells(row, line[1])
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

    def median_note(self, text):
        """The note on the median column: with peers chosen, it is of the peers alone."""
        if not self.peers:
            return text
        return ("The Peers' median column is the middle peer's value in each row: %s, the first column, is left out of it. "
                "Beside it, for the multiples, is how far %s's is above (or below) the median." % (
                    self.columns[0].ticker, self.columns[0].ticker))

    def valuation_notes(self):
        """The Notes tab's lines on the rows at the bottom of the sheet."""
        lines = [
            ("", "wrap"),
            ("Valuation (the rows at the bottom of the sheet)", "section"),
            ("Each company's market value is its share price times its diluted shares, and its enterprise value that plus its "
             "debt, less its cash and short-term investments: what the whole business is priced at, whoever finances it. "
             "(A bank's or an insurer's debt is its raw material, so they have market value only.) A multiple is the price "
             "over what the company earns or owns, and is empty where that is not above 0: a company that lost money has no "
             "price / earnings. A yield is the inverse, and is not empty: it says what a company that lost money earns on its "
             "price (less than nothing). A year's flows are a quarter's times 365 over its days.", "wrap"),
            ("A multiple is only as comparable as the companies: a company that grows faster, earns more on its capital, or "
             "carries less risk deserves a higher one. The PEG and the return on invested capital are there to say so; the "
             "peers that were chosen for their size and industry are not twins.", "wrap"),
        ]
        if self.peers:
            lines.append(("The last section is what %s would be worth per share if it traded at the median of its peers' "
                          "multiples, one way after another, and the median of those: the price it would have if it were "
                          "priced like them. That is a comparison, not a forecast: it says whether the market prices %s above "
                          "or below its peers, not whether it should." % (self.columns[0].ticker, self.columns[0].ticker), "wrap"))
        return lines

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
                      (self.median_note("The Median column is the middle company's value in each row."), "wrap")]
        else:
            lines.append((self.median_note("The Median column, for the ratios, is the middle company's value."), "wrap"))
        lines.append(("Ratios use the period's end balances, and a year's flows (a quarter's times 365 over its days).", "wrap"))
        if self.valued:
            lines += self.valuation_notes()
        lines.append(("", "wrap"))
        lines.append(("The companies", "section"))
        for column in self.columns:
            lines.append(("%s (%s): %s, %s ending %s, in %s%s" % (
                column.name, column.ticker, column.industry or "industry unknown", column.label, column.period.end.isoformat(),
                column.currency, "" if column.kind == column.industry_kind else
                "; modeled as %s because you asked" % model.templates()[column.kind].description), "wrap"))
        for text, style in self.extra_notes:
            lines.append((text, style))
        return {"name": NOTES, "cells": [[(("Companies side by side"), ("title",))], [None]] + [[(text, (style,))] if text else [None] for text, style in lines],
                "widths": [(0, 0, 900)]}

    def sheets(self):
        width_settings = [(0, 0, LABEL_WIDTH), (1, self.width - 1, COMPANY_WIDTH)]
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

def build_comparison(columns, kind, basis, period, who, peers=False, estimates=False, notes=()):
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
    return Comparison(columns, kinds[0], basis, period, peers, estimates, notes)


# ---------------------------------------------------------------------------
# The peers
# ---------------------------------------------------------------------------

def peer_count(given, who):
    """How many peers :peers asks for, or None for no peers: a whole number, or #t for DEFAULT_PEERS."""
    if given is None or given is False:
        return None
    if given is True:
        return DEFAULT_PEERS
    if isinstance(given, int) and 1 <= given <= MOST_PEERS:
        return given
    raise LispError("%s: :peers is how many comparable companies to choose, 1 to %d (or #t for %d)"
                    % (who, MOST_PEERS, DEFAULT_PEERS))


def why_not(problem, ticker):
    """What went wrong building a company's column, without the name of the function, the ticker, and the advice that go
    with it."""
    text = str(problem).split(": ", 1)[-1]
    if text.startswith(ticker.upper() + ": "):
        text = text[len(ticker) + 2:]
    return text.split("; compare it as an ordinary company")[0]


def unfit(column, target, seen, period):
    """Why a company cannot be one of the target's peers -- or None if it can: it is the target's company, or one
    already chosen (another share class: they share their SEC number), it is another kind of company or reports in
    another currency (its rows would not be the same), or its latest report is old (it has stopped reporting)."""
    if column.cik is not None and column.cik in seen:
        return "it is another stock of a company already here (%s)" % seen[column.cik]
    if column.kind != target.kind:
        return "it is %s, and %s is %s" % (model.templates()[column.kind].description, target.ticker,
                                           model.templates()[target.kind].description)
    if column.currency != target.currency:
        return "it reports in %s, and %s in %s" % (column.currency, target.ticker, target.currency)
    age = (today() - column.period.end).days
    if age > OLDEST_REPORT_DAYS[period]:
        return "its latest %s report is for the period that ended %s, %d days ago" % (period, column.period.end.isoformat(), age)
    return None


def money_text(dollars):
    return "$%.1f billion" % (dollars / 1e9) if dollars >= 1e9 else "$%.0f million" % (dollars / 1e6)


def choose_peers(credentials_path, ticker, count, kind, period, stocks, database, industry, who):
    """The target's CompanyColumn, and its peers' (nearest in size first), and the lines for the Notes tab on how they
    were chosen: those in the target's industry (or :industry) in the table ticker_industry that trade now, nearest in
    market capitalization first, that the SEC's statements can be used for (see unfit); the others are skipped, and
    the notes say why."""
    target_stock = peers_module.find_target(stocks, ticker, who)
    industries = peers_module.chosen_industries(stocks, target_stock, industry, who)
    target = CompanyColumn(credentials_path, ticker, kind, period, who)
    seen = {target.cik: target.ticker} if target.cik is not None else {}
    chosen, chosen_stocks, skipped = [], [], []
    candidates = peers_module.nearest_in_size(stocks, target_stock, industries)
    for stock in candidates[:TRIES_PER_PEER * count + count]:
        if len(chosen) == count:
            break
        try:
            column = CompanyColumn(credentials_path, stock.ticker, kind, period, who)
        except LispError as problem:
            skipped.append((stock, why_not(problem, stock.ticker)))
            continue
        reason = unfit(column, target, seen, period)
        if reason:
            skipped.append((stock, reason))
            continue
        if column.cik is not None:
            seen[column.cik] = column.ticker
        chosen.append(column)
        chosen_stocks.append(stock)
    if not chosen:
        raise LispError("%s: none of the %d stocks nearest in size to %s in %s could be compared with it: %s" % (
            who, len(skipped), target.ticker, ", ".join(industries),
            "; ".join("%s: %s" % (stock.ticker, reason) for stock, reason in skipped[:4])))
    cap = target_stock.market_cap
    lines = [("", "wrap"), ("How the peers of %s were chosen" % target.ticker, "section"),
             ("From the table ticker_industry of %s: the stocks in the industry %s (%d of them) that trade now, nearest to "
              "%s in market capitalization first. The market capitalizations are from the table stock_returns, as of "
              "%s. A stock is skipped if the SEC's statements cannot be used for it: another stock of a company already "
              "here, another kind of company, another currency, or an old report." % (
                  database, " and ".join('"%s"' % name for name in industries),
                  sum(1 for stock in stocks.values() if stock.industry in industries), target.ticker, price_dates([target_stock])),
              "wrap"),
             ("%s: %s, in %s." % (target.ticker, money_text(cap), target_stock.industry), "wrap")]
    for column, stock in zip(chosen, chosen_stocks):
        lines.append(("%s (%s): %s, %.2f times %s's." % (column.ticker, column.name, money_text(stock.market_cap),
                                                          stock.market_cap / cap, target.ticker), "wrap"))
    farthest = max(chosen_stocks, key=lambda stock: abs(math.log(stock.market_cap / cap)))
    ratio = farthest.market_cap / cap
    if not 1 / FAR_IN_SIZE <= ratio <= FAR_IN_SIZE:
        lines.append(("Note: %s is far from %s in size (%s is %.2f times its market capitalization): few companies in this "
                      "industry are about its size, so the peers are not near it, and a multiple depends on size. Read them "
                      "with that in mind: :industry can look in more industries." % (
                          target.ticker, farthest.ticker, farthest.ticker, ratio), "wrap"))
    if skipped:
        lines.append(("Looked at, and skipped:", "wrap"))
        for stock, reason in skipped:
            lines.append(("%s (%s): %s." % (stock.ticker, money_text(stock.market_cap), reason), "wrap"))
    return [target] + chosen, lines


# ---------------------------------------------------------------------------
# The prices, and what analysts expect
# ---------------------------------------------------------------------------

def price_dates(stocks):
    """The date of the stocks' prices, as text: one date, or the first and the last."""
    dates = sorted({str(stock.price_date) for stock in stocks if stock.price_date})
    return "unknown" if not dates else dates[0] if len(dates) == 1 else "%s to %s" % (dates[0], dates[-1])


def price_source(given):
    """Where the share prices come from, by the option :prices: "none" (#f), "alpha-vantage" (#t), "database" (that
    word), "auto" (not given: the database's, if it has them all), or "list" (a number for each company)."""
    if given is False:
        return "none"
    if given is True:
        return "alpha-vantage"
    if given is None:
        return "auto"
    return "database" if isinstance(given, str) and str(given) == "database" else "list"


def share_prices(credentials_path, given, columns, stocks, database, who):
    """Put each company's share price in its column (column.market["price"]), and give the lines for the Notes tab on
    where they came from. `given` is the option :prices (see price_source). From the database (the table stock_returns
    of the one at `database`, read into `stocks`), it is an error not to have them all if the prices were asked for;
    if they were not, no prices is no valuation rows, and the Notes say how to get them."""
    tickers = [column.ticker for column in columns]
    source = price_source(given)
    if source == "none":
        return []
    if source == "alpha-vantage":
        import lisp_alpha_vantage
        for column in columns:
            column.market["price"] = lisp_alpha_vantage.alpha_vantage_price(credentials_path, column.ticker)
        return [("Share prices: the latest, from Alpha Vantage.", "wrap")]
    if source == "list":
        try:
            import lisp_financial_asset_manager
            prices = lisp_financial_asset_manager.number_list(given, who, ":prices")
        except LispError:
            prices = None
        if prices is None or len(prices) != len(columns) or any(price <= 0 for price in prices):
            raise LispError('%s: :prices is the share price of each company, in the order given (%d numbers), #t to get them '
                            'from Alpha Vantage, or "database" to take them from the database' % (who, len(columns)))
        for column, price in zip(columns, prices):
            column.market["price"] = price
        return [("Share prices: as given.", "wrap")]
    found = [stocks.get(peers_module.normal(ticker)) for ticker in tickers]
    missing = [ticker for ticker, stock in zip(tickers, found) if stock is None or not stock.price or stock.price <= 0]
    if missing:
        if source == "database":
            raise LispError("%s: the database has no share price for %s (the table stock_returns: stock-returns-update "
                            "gets them from Schwab)" % (who, ", ".join(missing)))
        return [("No valuation rows: there are no share prices%s. Give :prices -- a list, one for each company, or #t for "
                 "Alpha Vantage's latest." % (
                     " in the database for %s" % ", ".join(missing) if database else
                     " (the database financial_data.db, with the table stock_returns, was not found)"), "wrap")]
    for column, stock in zip(columns, found):
        column.market["price"] = float(stock.price)
    return [("Share prices: the closing prices on %s from the table stock_returns of %s (:prices #t gets the latest from "
             "Alpha Vantage)." % (price_dates(found), database), "wrap")]


def add_estimates(credentials_path, columns, who):
    """Put what analysts expect each company to earn, for its next two fiscal years (alpha-vantage-estimates), in its
    column (column.market["eps-forward-1"], "eps-forward-2"), and give the lines for the Notes tab. A fiscal year is the
    next if it ends more than ESTIMATE_GAP_DAYS after the end of the latest period reported (the fiscal year may end a
    few days either side of the date Alpha Vantage gives)."""
    import lisp_alpha_vantage
    without = []
    for column in columns:
        records = lisp_alpha_vantage.estimate_records(credentials_path, column.ticker)
        years = lisp_alpha_vantage.fiscal_year_eps(records, column.period.end + datetime.timedelta(days=ESTIMATE_GAP_DAYS))
        if not years:
            without.append(column.ticker)
        for number, (_, estimate) in enumerate(years[:2], start=1):
            column.market["eps-forward-%d" % number] = estimate
    lines = [("Analysts' estimates: the average of the analysts' estimates of earnings per share for each company's next two "
              "fiscal years, from Alpha Vantage (alpha-vantage-estimates), as of today.", "wrap")]
    if without:
        lines.append(("Alpha Vantage has no estimates for %s." % ", ".join(without), "wrap"))
    return lines


def compare_companies(credentials_path, companies, *options):
    """(compare-companies creds '("ACN" "EFX" "CTSH") [:basis "revenue" :period "annual" :kind "auto" :prices p
    :estimates #t :peers n :industry i :database path :title t]) -- a new Google spreadsheet with the companies' most
    recent annual (or quarterly) statements side by side, a column for each, the same rows for all: the income
    statement, balance sheet, cash flow statement, and ratios, of an ordinary company, a bank, or a property and
    casualty insurer (:kind; "auto" chooses by the SEC's industry codes, and the companies must be all one kind).
    :basis "none" (the default) shows the amounts in millions; "revenue" shows each as a percentage of the company's
    top line (a bank's net revenue), and "assets" of its total assets, so that companies of different sizes compare; a
    column of medians shows what is typical.
    At the bottom are the valuation rows: market value, enterprise value, and the multiples and yields they make
    (enterprise value over EBITDA, operating income, revenue, and free cash flow; price over sales, earnings, cash
    earnings, book, and tangible book; earnings, free cash flow, dividend, buyback, and shareholder yields; return on
    invested capital; PEG; a bank's price over tangible book, return on tangible equity, and price over its profit
    before credit losses and its deposits; an insurer's price over premiums). They need share prices: :prices is a list
    of them, one for each company; #t, the latest from Alpha Vantage; "database", the closing prices in the table
    stock_returns of the database financial_data.db; and #f, none. By default they are the database's, if it has them
    all. :estimates #t adds what analysts expect (from Alpha Vantage) and the forward price over earnings.
    :peers chooses the companies to compare with: given one company ("KEY"), n (or #t, for 5) peers -- the stocks in its
    industry in the table ticker_industry, nearest to it in market capitalization, that the SEC's statements can be used
    for. :industry (a name, or a list) looks in other industries than the company's own; :database is the database's
    path (the current folder, or the repository's data folder, if it is not given). The company is the first column,
    the median is of its peers alone, and the valuation ends with what the company would be worth at their median
    multiples. (comparable-companies lists the candidates.)
    Returns the spreadsheet's address. You need to be signed in to Google: (google-login creds)."""
    who = "compare-companies"
    options = keyword_options(options, ["basis", "period", "kind", "prices", "estimates", "peers", "industry", "database",
                                        "title"], who)
    tickers = text_list(companies, who, "the companies")
    peers = peer_count(options.get("peers"), who)
    if peers is None:
        if len(tickers) < 2:
            raise LispError("%s: give at least two companies, such as '(\"ACN\" \"EFX\"), or one with :peers to choose "
                            "its peers" % who)
        if len(tickers) > MOST_COMPANIES:
            raise LispError("%s: at most %d companies" % (who, MOST_COMPANIES))
        if len({t.upper() for t in tickers}) < len(tickers):
            raise LispError("%s: a company is given twice" % who)
        if options.get("industry") is not None:
            raise LispError("%s: :industry says what industries to choose peers from, and goes with :peers" % who)
    elif len(tickers) != 1:
        raise LispError("%s: with :peers give one company, whose peers are chosen (not a list of %d)" % (who, len(tickers)))
    basis = str(options.get("basis", "none"))
    if basis not in BASES:
        raise LispError('%s: :basis is "none", "revenue", or "assets", not %s' % (who, basis))
    period = str(options.get("period", "annual"))
    if period not in ("annual", "quarterly"):
        raise LispError('%s: :period is "annual" or "quarterly", not %s' % (who, period))
    kind = str(options.get("kind", "auto"))
    if kind != "auto" and kind not in ROWS:
        raise LispError('%s: :kind is "auto", "general", "bank", or "insurer", not %s' % (who, kind))
    estimates = options.get("estimates", False) is not False
    if estimates and period != "annual":
        raise LispError('%s: :estimates are of fiscal years, and go with :period "annual"' % who)
    given_prices = options.get("prices")
    source = price_source(given_prices)
    if peers is not None and source == "list":
        raise LispError('%s: with :peers the share prices are the database\'s (the default) or Alpha Vantage\'s (:prices '
                        '#t): the peers are not known until they are chosen, so you cannot give a price for each' % who)
    # the database: it has the industries the peers are chosen from, and the prices unless they are given or from Alpha Vantage
    database = peers_module.locate_database(options.get("database"))
    if database is None and (peers is not None or source == "database" or options.get("database") is not None):
        database = peers_module.find_database(options.get("database"), who)             # (an error that says where it looked)
    stocks = peers_module.load_stocks(database, who) if database and (peers is not None or source in ("auto", "database")) else {}
    if peers is not None:
        columns, notes = choose_peers(credentials_path, tickers[0], peers, kind, period, stocks, database,
                                      options.get("industry"), who)
    else:
        columns = [CompanyColumn(credentials_path, ticker, kind, period, who) for ticker in tickers]
        notes = []
    market_notes = share_prices(credentials_path, given_prices, columns, stocks, database, who)
    if estimates:
        if not all(column.price is not None for column in columns):
            raise LispError("%s: :estimates needs share prices (:prices), for the forward price over earnings" % who)
        market_notes += add_estimates(credentials_path, columns, who)
    if market_notes:
        notes += [("", "wrap"), ("Share prices and estimates", "section")] + market_notes
    comparison = build_comparison(columns, kind, basis, period, who, peers is not None, estimates, notes)
    if options.get("title"):
        title = options["title"]
    elif peers is not None:
        title = "%s and its peers compared (%s)" % (columns[0].ticker, basis if basis != "none" else period)
    else:
        title = "%s compared (%s)" % (", ".join(c.ticker for c in columns), basis if basis != "none" else period)
    return LispString(lisp_google.google_workbook(credentials_path, str(title), comparison.sheets()))


BUILTINS = {
    "compare-companies": compare_companies,
}
