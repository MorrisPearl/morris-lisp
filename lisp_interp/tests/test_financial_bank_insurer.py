"""The bank and property and casualty insurer models (lisp_financial_bank.py, lisp_financial_insurer.py), and
the choice of model by the SEC's industry code: a made-up bank and a made-up insurer, and a fake Google -- no
network. sheet_formulas.py works out the formulas of the sheets as Google would, which is how these tests
know the models balance, and that the cash flow statement ends where the balance sheet does."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_financial_bank
import lisp_financial_insurer
import lisp_financial_model as fm
import lisp_google
import lisp_sec
import lisp_sec_segments
from sheet_formulas import Sheets
from test_financial_model import made_up_facts, value, set_input

MILLION = 1e6
YEARS = (2021, 2022, 2023)


# ---------------------------------------------------------------------------
# Made-up companies
# ---------------------------------------------------------------------------

def company_facts(name, flows, balances, years=YEARS, quarterly=False, shares_per_year=lambda year: 100.0):
    """SEC company facts for a made-up company whose fiscal year is the calendar year. `flows` and `balances`
    map a concept to a function of the year, giving millions. Each year has a 10-K; with `quarterly`, the later
    years have the first three quarters' 10-Qs too (a quarter's flows are the year's, shared 22, 24, 26%, and its
    balances are on the way from the year before's to the year's)."""
    facts = {}

    def add(concept, fact):
        facts.setdefault(concept, []).append(fact)

    for year in years:
        form = ("10-K", "%d-02-15" % (year + 1), year, "FY", "k%d" % year)
        for concept, amount in flows.items():
            add(concept, dict(zip(("start", "end", "val"), ("%d-01-01" % year, "%d-12-31" % year, amount(year) * MILLION)),
                              **dict(zip(("form", "filed", "fy", "fp", "accn"), form))))
        add("WeightedAverageNumberOfDilutedSharesOutstanding",
            dict(zip(("start", "end", "val"), ("%d-01-01" % year, "%d-12-31" % year, shares_per_year(year) * MILLION)),
                 **dict(zip(("form", "filed", "fy", "fp", "accn"), form))))
        for concept, amount in balances.items():
            add(concept, dict(zip(("end", "val"), ("%d-12-31" % year, amount(year) * MILLION)),
                              **dict(zip(("form", "filed", "fy", "fp", "accn"), form))))
    if quarterly:
        shares_of_year = [0.22, 0.24, 0.26]
        ends, starts = ["%d-03-31", "%d-06-30", "%d-09-30"], ["%d-01-01", "%d-04-01", "%d-07-01"]
        for year in years[1:]:
            for q in range(3):
                form = dict(zip(("form", "filed", "fy", "fp", "accn"),
                                ("10-Q", "%d-%02d-20" % (year, 4 + 3 * q), year, "Q%d" % (q + 1), "q%d%d" % (year, q + 1))))
                for concept, amount in flows.items():
                    add(concept, dict(start=starts[q] % year, end=ends[q] % year, val=amount(year) * MILLION * shares_of_year[q],
                                      **form))
                    if q == 2:                               # the third 10-Q also has the nine months
                        add(concept, dict(start="%d-01-01" % year, end=ends[2] % year,
                                          val=amount(year) * MILLION * sum(shares_of_year), **form))
                add("WeightedAverageNumberOfDilutedSharesOutstanding",
                    dict(start=starts[q] % year, end=ends[q] % year, val=shares_per_year(year) * MILLION, **form))
                for concept, amount in balances.items():
                    before, now = amount(year - 1), amount(year)
                    add(concept, dict(end=ends[q] % year, val=(before + (now - before) * (q + 1) / 4) * MILLION, **form))
    taxonomy = {}
    for concept, items in facts.items():
        unit = "shares" if concept.startswith("WeightedAverage") else "USD"
        taxonomy[concept] = {"label": "", "units": {unit: items}}
    return {"cik": 1234, "entityName": name, "facts": {"us-gaap": taxonomy}}


# A bank. g is the years since 2021; the amounts are in millions.
def bank_amounts(year):
    g = year - 2021
    a = {"loans": 1000 + 100 * g, "deposits": 1500 + 120 * g, "afs": 300 + 20 * g, "htm": 100, "other_assets": 200,
         "repo": 50, "short": 40, "long": 300 - 10 * g, "equity": 150 + 15 * g}
    a["allowance"] = 0.02 * a["loans"]
    a["cash"] = 0.10 * a["deposits"]
    a["assets"] = a["cash"] + a["afs"] + a["htm"] + a["loans"] - a["allowance"] + a["other_assets"]
    a["pretax"] = 15 + 3 * g
    a["tax"] = 0.2 * a["pretax"]
    a["net_income"] = a["pretax"] - a["tax"] - 1
    return a


BANK_FLOWS = {
    "InterestAndDividendIncomeOperating": lambda y: 90 + 8 * (y - 2021),
    "InterestAndFeeIncomeLoansAndLeases": lambda y: 62 + 6 * (y - 2021),
    "InterestExpenseOperating": lambda y: 32 + 3 * (y - 2021),
    "InterestExpenseDeposits": lambda y: 20 + 2 * (y - 2021),
    "ProvisionForLoanLeaseAndOtherLosses": lambda y: 15 + (y - 2021),
    "NoninterestIncome": lambda y: 40 + 4 * (y - 2021),
    "NoninterestExpense": lambda y: 70 + 5 * (y - 2021),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
        lambda y: bank_amounts(y)["pretax"],
    "IncomeTaxExpenseBenefit": lambda y: bank_amounts(y)["tax"],
    "NetIncomeLoss": lambda y: bank_amounts(y)["net_income"],
    "FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoffAfterRecovery": lambda y: 12,
    "NetCashProvidedByUsedInOperatingActivities": lambda y: bank_amounts(y)["net_income"] + 30,
    "NetCashProvidedByUsedInInvestingActivities": lambda y: -150,
    "NetCashProvidedByUsedInFinancingActivities": lambda y: 120,
    "PaymentsOfDividends": lambda y: 20,
    "PaymentsForRepurchaseOfCommonStock": lambda y: 10,
}
BANK_BALANCES = {
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": lambda y: bank_amounts(y)["cash"],
    "DebtSecuritiesAvailableForSaleExcludingAccruedInterest": lambda y: bank_amounts(y)["afs"],
    "DebtSecuritiesHeldToMaturityExcludingAccruedInterestAfterAllowanceForCreditLoss": lambda y: bank_amounts(y)["htm"],
    "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss": lambda y: bank_amounts(y)["loans"],
    "FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest": lambda y: bank_amounts(y)["allowance"],
    "Deposits": lambda y: bank_amounts(y)["deposits"],
    "FederalFundsPurchasedAndSecuritiesSoldUnderAgreementsToRepurchase": lambda y: bank_amounts(y)["repo"],
    "ShortTermBorrowings": lambda y: bank_amounts(y)["short"],
    "LongTermDebt": lambda y: bank_amounts(y)["long"],
    "Assets": lambda y: bank_amounts(y)["assets"],
    "Liabilities": lambda y: bank_amounts(y)["assets"] - bank_amounts(y)["equity"],
    "StockholdersEquity": lambda y: bank_amounts(y)["equity"],
    "LiabilitiesAndStockholdersEquity": lambda y: bank_amounts(y)["assets"],
}


def bank_facts(**options):
    return company_facts("ABC Bank", BANK_FLOWS, BANK_BALANCES, **options)


# An insurer.
def insurer_amounts(year):
    g = year - 2021
    a = {"premiums": 1000 + 100 * g, "investment_income": 80 + 8 * g, "gains": 5, "other_revenue": 20, "interest": 10,
         "cash": 100, "investments": 2500 + 200 * g, "receivable": 150 + 10 * g, "reinsurance": 200, "acquisition_costs": 80,
         "goodwill": 60, "intangibles": 20, "other_assets": 100, "unearned": 500 + 50 * g, "debt": 300, "reserves": 1500 + 150 * g,
         "other_liabilities": 100}
    a["losses"] = 0.65 * a["premiums"]
    a["revenue"] = a["premiums"] + a["investment_income"] + a["gains"] + a["other_revenue"]
    a["other_expenses"] = 0.30 * a["premiums"]
    a["pretax"] = a["revenue"] - a["losses"] - a["other_expenses"] - a["interest"]
    a["tax"] = 0.2 * a["pretax"]
    a["net_income"] = a["pretax"] - a["tax"]
    a["assets"] = (a["cash"] + a["investments"] + a["receivable"] + a["reinsurance"] + a["acquisition_costs"] + a["goodwill"]
                   + a["intangibles"] + a["other_assets"])
    a["equity"] = a["assets"] - a["reserves"] - a["unearned"] - a["debt"] - a["other_liabilities"]
    return a


def insurer_flow(key):
    return lambda y: insurer_amounts(y)[key]


INSURER_FLOWS = {
    "PremiumsEarnedNet": insurer_flow("premiums"), "NetInvestmentIncome": insurer_flow("investment_income"),
    "RealizedInvestmentGainsLosses": insurer_flow("gains"), "Revenues": insurer_flow("revenue"),
    "PolicyholderBenefitsAndClaimsIncurredNet": insurer_flow("losses"), "InterestExpense": insurer_flow("interest"),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": insurer_flow("pretax"),
    "IncomeTaxExpenseBenefit": insurer_flow("tax"), "NetIncomeLoss": insurer_flow("net_income"),
    "NetCashProvidedByUsedInOperatingActivities": lambda y: insurer_amounts(y)["net_income"] + 150,
    "NetCashProvidedByUsedInInvestingActivities": lambda y: -300, "NetCashProvidedByUsedInFinancingActivities": lambda y: -60,
    "PaymentsOfDividends": lambda y: 40, "PaymentsForRepurchaseOfCommonStock": lambda y: 20,
}
INSURER_BALANCES = {
    "CashAndCashEquivalentsAtCarryingValue": insurer_flow("cash"), "Investments": insurer_flow("investments"),
    "PremiumsReceivableAtCarryingValue": insurer_flow("receivable"), "ReinsuranceRecoverables": insurer_flow("reinsurance"),
    "DeferredPolicyAcquisitionCosts": insurer_flow("acquisition_costs"), "Goodwill": insurer_flow("goodwill"),
    "IntangibleAssetsNetExcludingGoodwill": insurer_flow("intangibles"), "Assets": insurer_flow("assets"),
    "LiabilityForClaimsAndClaimsAdjustmentExpense": insurer_flow("reserves"), "UnearnedPremiums": insurer_flow("unearned"),
    "LongTermDebt": insurer_flow("debt"), "StockholdersEquity": insurer_flow("equity"),
    "Liabilities": lambda y: insurer_amounts(y)["assets"] - insurer_amounts(y)["equity"],
    "LiabilitiesAndStockholdersEquity": insurer_flow("assets"),
}


def insurer_facts(**options):
    return company_facts("ABC Insurance", INSURER_FLOWS, INSURER_BALANCES, **options)


REAL_COMPANY_INDUSTRY = fm.company_industry          # (the tests of the choice of kind replace it)


def build(facts, kind, period="annual", history=3, forecast=3):
    return fm.build_model(facts, "ABC", period, history, forecast, "test", None, kind)


class ModelTestCase(LispTestCase):
    """A test case for models: `self.v(tab, key, i)` is a cell worked out."""

    def use(self, model):
        self.model = model
        self.sheets = Sheets(model.sheets())

    def v(self, tab, key, i):
        return value(self.sheets, self.model, tab, key, i)

    def assertBalances(self, periods):
        for i in range(periods):
            self.assertAlmostEqual(self.v("Balance Sheet", "check", i), 0, places=6)

    def assertNoCircularFormulas(self):
        for tab in ("Assumptions", "Income Statement", "Balance Sheet", "Cash Flow"):
            for (row, column) in list(self.sheets.cells[tab]):
                self.sheets.value(tab, row, column)


# ---------------------------------------------------------------------------
# The bank
# ---------------------------------------------------------------------------

class TestBankModel(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(build(bank_facts(), "bank"))

    def test_the_reported_subtotals_are_the_banks(self):
        for i, year in enumerate(YEARS):
            a = bank_amounts(year)
            g = year - 2021
            self.assertAlmostEqual(self.v("Income Statement", "interest-income", i), 90 + 8 * g)
            self.assertAlmostEqual(self.v("Income Statement", "interest-securities", i), 28 + 2 * g)
            self.assertAlmostEqual(self.v("Income Statement", "interest-expense", i), 32 + 3 * g)
            self.assertAlmostEqual(self.v("Income Statement", "interest-borrowings", i), 12 + g)
            self.assertAlmostEqual(self.v("Income Statement", "net-interest-income", i), 58 + 5 * g)
            self.assertAlmostEqual(self.v("Income Statement", "other-income", i), 2)
            self.assertAlmostEqual(self.v("Income Statement", "pretax-income", i), a["pretax"])
            self.assertAlmostEqual(self.v("Income Statement", "net-income", i), a["net_income"])
            self.assertAlmostEqual(self.v("Balance Sheet", "total-assets", i), a["assets"])
            self.assertAlmostEqual(self.v("Balance Sheet", "borrowings", i), 390 - 10 * g)
            self.assertAlmostEqual(self.v("Balance Sheet", "total-liabilities-and-equity", i), a["assets"])
            self.assertAlmostEqual(self.v("Balance Sheet", "other-assets", i), 200)
            self.assertAlmostEqual(self.v("Cash Flow", "operating-cash-flow", i), a["net_income"] + 30)
            self.assertAlmostEqual(self.v("Cash Flow", "investing-cash-flow", i), -150)
            self.assertAlmostEqual(self.v("Cash Flow", "financing-cash-flow", i), 120)

    def test_the_changes_in_loans_and_deposits_come_from_the_balance_sheet(self):
        self.assertAlmostEqual(self.v("Cash Flow", "change-in-loans", 1), -(1100 * 0.98 - 1000 * 0.98))
        self.assertAlmostEqual(self.v("Cash Flow", "change-in-deposits", 2), 120)
        self.assertIsNone(self.model.sheets()[3]["cells"][self.model.layouts["Cash Flow"].row_of["change-in-loans"] - 1][1])

    def test_everything_balances_and_the_cash_flow_statement_ends_with_the_balance_sheets_cash(self):
        self.assertBalances(6)
        for i in range(3, 6):
            self.assertAlmostEqual(self.v("Balance Sheet", "cash-check", i), 0, places=6)
            self.assertAlmostEqual(self.v("Balance Sheet", "cash", i), self.v("Cash Flow", "cash-end", i))
        self.assertNoCircularFormulas()

    def test_loans_and_deposits_grow_at_the_assumed_rates_and_cash_and_securities_follow_deposits(self):
        self.assertAlmostEqual(self.v("Assumptions", "loan-growth", 3), 1200 / 1100 * 1 - 1 + 0.0, places=6)
        self.assertAlmostEqual(self.v("Balance Sheet", "loans", 3), 1200 * 1200 / 1100)
        self.assertAlmostEqual(self.v("Balance Sheet", "deposits", 3), 1740 * 1740 / 1620)
        self.assertAlmostEqual(self.v("Balance Sheet", "cash", 3), 0.10 * self.v("Balance Sheet", "deposits", 3))
        self.assertAlmostEqual(self.v("Balance Sheet", "securities", 3),
                               (340 + 100) / 1740 * self.v("Balance Sheet", "deposits", 3))

    def test_interest_is_a_rate_on_the_balance_at_the_end_of_the_period_before(self):
        rate = self.v("Assumptions", "loan-yield", 3)
        self.assertAlmostEqual(rate, 74 / 1100)                       # the last year's: 74 on 2022's loans
        self.assertAlmostEqual(self.v("Income Statement", "interest-loans", 3), rate * 1200)
        deposit_cost = self.v("Assumptions", "deposit-cost", 3)
        self.assertAlmostEqual(self.v("Income Statement", "interest-deposits", 3),
                               deposit_cost * self.v("Balance Sheet", "deposits", 2))
        borrowing_cost = self.v("Assumptions", "borrowing-cost", 3)
        self.assertAlmostEqual(self.v("Income Statement", "interest-borrowings", 3),
                               borrowing_cost * self.v("Balance Sheet", "borrowings", 2))

    def test_the_provision_is_net_charge_offs_plus_the_growth_of_the_allowance(self):
        self.assertAlmostEqual(self.v("Assumptions", "charge-off-rate", 3), 12 / 1100)
        charge_offs = self.v("Income Statement", "net-charge-offs", 3)
        self.assertAlmostEqual(charge_offs, 12 / 1100 * 1200)
        growth = self.v("Balance Sheet", "allowance", 3) - self.v("Balance Sheet", "allowance", 2)
        self.assertAlmostEqual(self.v("Income Statement", "provision", 3), charge_offs + growth)
        self.assertAlmostEqual(self.v("Assumptions", "allowance-ratio", 3), 0.02)

    def test_noninterest_expense_is_the_efficiency_ratio_times_net_revenue(self):
        ratio = self.v("Assumptions", "efficiency", 3)
        self.assertAlmostEqual(ratio, 80 / (68 + 48))
        self.assertAlmostEqual(self.v("Income Statement", "noninterest-expense", 3),
                               ratio * self.v("Income Statement", "net-revenue", 3))

    def test_equity_rises_by_income_less_payouts(self):
        i = 3
        change = (self.v("Income Statement", "net-income", i) + self.v("Cash Flow", "dividends", i)
                  + self.v("Cash Flow", "repurchases", i))
        self.assertAlmostEqual(self.v("Balance Sheet", "equity", i) - self.v("Balance Sheet", "equity", i - 1), change)

    def test_borrowings_are_what_funds_the_rest(self):
        i = 3
        self.assertAlmostEqual(self.v("Balance Sheet", "borrowings", i),
                               self.v("Balance Sheet", "total-assets", i) - self.v("Balance Sheet", "deposits", i)
                               - self.v("Balance Sheet", "other-liabilities", i) - self.v("Balance Sheet", "equity", i))

    def test_changing_assumptions_changes_the_forecast_and_it_still_balances(self):
        set_input(self.sheets, self.model, "Assumptions", "loan-growth", 3, 0.30)
        set_input(self.sheets, self.model, "Assumptions", "deposit-growth", 4, -0.05)
        set_input(self.sheets, self.model, "Assumptions", "deposit-cost", 5, 0.04)
        set_input(self.sheets, self.model, "Assumptions", "dividend-payout", 5, 0.9)
        self.assertAlmostEqual(self.v("Balance Sheet", "loans", 3), 1200 * 1.3)
        self.assertBalances(6)
        for i in range(3, 6):
            self.assertAlmostEqual(self.v("Balance Sheet", "cash-check", i), 0, places=6)

    def test_the_ratios_are_worked_out_for_every_period(self):
        self.assertAlmostEqual(self.v("Balance Sheet", "loans-to-deposits", 0), 1000 / 1500)
        self.assertAlmostEqual(self.v("Balance Sheet", "equity-to-assets", 0), 150 / bank_amounts(2021)["assets"])
        self.assertAlmostEqual(self.v("Income Statement", "efficiency-ratio", 0), 70 / 98)
        # return on equity: the average of the equity at the start and end of the year
        self.assertAlmostEqual(self.v("Income Statement", "return-on-equity", 1),
                               bank_amounts(2022)["net_income"] / ((150 + 165) / 2))
        self.assertAlmostEqual(self.v("Income Statement", "return-on-equity", 0), bank_amounts(2021)["net_income"] / 150)

    def test_the_colors_say_what_kind_of_number_each_is(self):
        tab = self.model.sheets()[0]["cells"]
        row = self.model.layouts["Assumptions"].row_of["loan-growth"]
        self.assertIn("input-formula", tab[row - 1][4][1])          # a forecast assumption: a formula to type over
        self.assertNotIn("input-formula", tab[row - 1][2][1])       # a reported period's: a formula, from the statements

    def test_the_notes_describe_a_banks_forecast_and_where_the_numbers_came_from(self):
        notes = "\n".join(self.model.sources_for_notes())
        self.assertIn("Borrowings are what funds the rest of the balance sheet", notes)
        self.assertIn("Deposits: Deposits", notes)
        self.assertIn("Interest income: InterestAndDividendIncomeOperating", notes)


class TestQuarterlyBankModel(ModelTestCase):

    def test_quarters_balance_and_the_cash_flow_ends_with_the_balance_sheets_cash(self):
        self.use(build(bank_facts(quarterly=True), "bank", "quarterly", 6, 2))
        self.assertEqual(self.model.labels, ["Q3 FY2022", "Q4 FY2022", "Q1 FY2023", "Q2 FY2023", "Q3 FY2023", "Q4 FY2023",
                                             "Q1 FY2024E", "Q2 FY2024E"])
        self.assertBalances(8)
        for i in (6, 7):
            self.assertAlmostEqual(self.v("Balance Sheet", "cash-check", i), 0, places=6)
        # growth of balances is from the quarter before; a quarter has about a quarter of a year's interest
        self.assertAlmostEqual(self.v("Assumptions", "days", 6), 365 / 4)
        rate = self.v("Assumptions", "loan-yield", 6)
        self.assertAlmostEqual(self.v("Income Statement", "interest-loans", 6),
                               rate * self.v("Balance Sheet", "loans", 5) * 365 / 4 / 365)

    def test_a_fourth_quarter_is_the_year_less_nine_months(self):
        self.use(build(bank_facts(quarterly=True), "bank", "quarterly", 6, 1))
        self.assertAlmostEqual(self.v("Income Statement", "noninterest-income", 1), 0.28 * 44)       # Q4 FY2022: the year's 44


# ---------------------------------------------------------------------------
# The insurer
# ---------------------------------------------------------------------------

class TestInsurerModel(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(build(insurer_facts(), "insurer"))

    def test_the_reported_subtotals_are_the_insurers(self):
        for i, year in enumerate(YEARS):
            a = insurer_amounts(year)
            self.assertAlmostEqual(self.v("Income Statement", "premiums-earned", i), a["premiums"])
            self.assertAlmostEqual(self.v("Income Statement", "other-revenue", i), 20)
            self.assertAlmostEqual(self.v("Income Statement", "revenue", i), a["revenue"])
            self.assertAlmostEqual(self.v("Income Statement", "other-expenses", i), a["other_expenses"])
            self.assertAlmostEqual(self.v("Income Statement", "pretax-income", i), a["pretax"])
            self.assertAlmostEqual(self.v("Income Statement", "net-income", i), a["net_income"])
            self.assertAlmostEqual(self.v("Balance Sheet", "total-assets", i), a["assets"])
            self.assertAlmostEqual(self.v("Balance Sheet", "other-assets", i), 100)
            self.assertAlmostEqual(self.v("Balance Sheet", "other-liabilities", i), 100)
            self.assertAlmostEqual(self.v("Cash Flow", "operating-cash-flow", i), a["net_income"] + 150)
            self.assertAlmostEqual(self.v("Cash Flow", "investing-cash-flow", i), -300)
            self.assertAlmostEqual(self.v("Cash Flow", "financing-cash-flow", i), -60)

    def test_the_ratios_say_how_the_underwriting_did(self):
        self.assertAlmostEqual(self.v("Income Statement", "loss-ratio", 1), 0.65)
        self.assertAlmostEqual(self.v("Income Statement", "expense-ratio", 1), 0.30)
        self.assertAlmostEqual(self.v("Income Statement", "combined-ratio", 1), 0.95)
        self.assertAlmostEqual(self.v("Income Statement", "underwriting-income", 1), 1100 * 0.05)

    def test_everything_balances_and_nothing_refers_to_itself(self):
        self.assertBalances(6)
        self.assertNoCircularFormulas()

    def test_premiums_grow_and_losses_and_expenses_follow_the_ratios(self):
        growth = self.v("Assumptions", "premium-growth", 3)
        self.assertAlmostEqual(growth, 1200 / 1100 - 1)
        self.assertAlmostEqual(self.v("Income Statement", "premiums-earned", 3), 1200 * (1 + growth))
        premiums = self.v("Income Statement", "premiums-earned", 3)
        self.assertAlmostEqual(self.v("Income Statement", "losses", 3), 0.65 * premiums)
        self.assertAlmostEqual(self.v("Income Statement", "other-expenses", 3), 0.30 * premiums)
        self.assertAlmostEqual(self.v("Income Statement", "combined-ratio", 3), 0.95)

    def test_investment_income_is_a_yield_on_last_periods_investments_and_cash(self):
        rate = self.v("Assumptions", "investment-yield", 3)
        self.assertAlmostEqual(rate, 96 / (2700 + 100))
        self.assertAlmostEqual(self.v("Income Statement", "net-investment-income", 3),
                               rate * (self.v("Balance Sheet", "investments", 2) + self.v("Balance Sheet", "cash", 2)))

    def test_realized_gains_are_an_amount_typed_in_and_zero_to_begin_with(self):
        self.assertAlmostEqual(self.v("Assumptions", "realized-gains", 2), 5)
        self.assertAlmostEqual(self.v("Assumptions", "realized-gains", 3), 0)
        set_input(self.sheets, self.model, "Assumptions", "realized-gains", 4, 50.0)
        self.assertAlmostEqual(self.v("Income Statement", "realized-gains", 4), 50)
        self.assertBalances(6)

    def test_reserves_unearned_premiums_and_the_rest_follow_the_assumptions(self):
        years = self.v("Assumptions", "loss-reserve-years", 3)
        self.assertAlmostEqual(years, 1800 / (0.65 * 1200))
        self.assertAlmostEqual(self.v("Balance Sheet", "loss-reserves", 3), years * self.v("Income Statement", "losses", 3))
        percent = self.v("Assumptions", "unearned-percent", 3)
        self.assertAlmostEqual(self.v("Balance Sheet", "unearned-premiums", 3), percent * self.v("Income Statement", "premiums-earned", 3))
        self.assertAlmostEqual(self.v("Balance Sheet", "reinsurance-recoverable", 3),
                               self.v("Assumptions", "reinsurance-percent", 3) * self.v("Balance Sheet", "loss-reserves", 3))
        self.assertAlmostEqual(self.v("Balance Sheet", "deferred-acquisition-costs", 3),
                               self.v("Assumptions", "acquisition-cost-percent", 3) * self.v("Balance Sheet", "unearned-premiums", 3))
        days = self.v("Assumptions", "receivable-days", 3)
        self.assertAlmostEqual(self.v("Balance Sheet", "premiums-receivable", 3),
                               days / 365 * self.v("Income Statement", "premiums-earned", 3))

    def test_the_cash_flow_starts_with_income_and_adds_the_growth_of_the_float(self):
        i = 3
        self.assertAlmostEqual(self.v("Cash Flow", "change-in-reserves", i),
                               self.v("Balance Sheet", "loss-reserves", i) - self.v("Balance Sheet", "loss-reserves", i - 1))
        self.assertAlmostEqual(self.v("Cash Flow", "change-in-receivable", i),
                               self.v("Balance Sheet", "premiums-receivable", i - 1) - self.v("Balance Sheet", "premiums-receivable", i))
        parts = sum(self.v("Cash Flow", key, i) for key in ("net-income", "change-in-reserves", "change-in-unearned",
                                                           "change-in-receivable", "change-in-reinsurance",
                                                           "change-in-acquisition-costs", "other-operating"))
        self.assertAlmostEqual(self.v("Cash Flow", "operating-cash-flow", i), parts)

    def test_what_is_left_after_the_payouts_is_invested_in_the_share_assumed(self):
        i = 3
        self.assertAlmostEqual(self.v("Assumptions", "invest-share", i), 1.0)
        left = self.v("Cash Flow", "operating-cash-flow", i) + self.v("Cash Flow", "financing-cash-flow", i)
        self.assertAlmostEqual(self.v("Cash Flow", "investment-purchases", i), -left)
        self.assertAlmostEqual(self.v("Balance Sheet", "investments", i), self.v("Balance Sheet", "investments", i - 1) + left)
        self.assertAlmostEqual(self.v("Balance Sheet", "cash", i), self.v("Balance Sheet", "cash", i - 1))
        set_input(self.sheets, self.model, "Assumptions", "invest-share", 4, 0.5)
        left = self.v("Cash Flow", "operating-cash-flow", 4) + self.v("Cash Flow", "financing-cash-flow", 4)
        self.assertAlmostEqual(self.v("Balance Sheet", "cash", 4), self.v("Balance Sheet", "cash", 3) + 0.5 * left)
        self.assertBalances(6)

    def test_changing_assumptions_changes_the_forecast_and_it_still_balances(self):
        set_input(self.sheets, self.model, "Assumptions", "premium-growth", 3, 0.25)
        set_input(self.sheets, self.model, "Assumptions", "loss-ratio", 4, 0.90)
        set_input(self.sheets, self.model, "Assumptions", "net-borrowing", 5, 400.0)
        set_input(self.sheets, self.model, "Assumptions", "buyback-payout", 5, 2.0)
        self.assertAlmostEqual(self.v("Income Statement", "premiums-earned", 3), 1200 * 1.25)
        self.assertAlmostEqual(self.v("Balance Sheet", "debt", 5), 300 + 400)
        self.assertBalances(6)

    def test_equity_rises_by_income_less_payouts(self):
        i = 3
        change = (self.v("Income Statement", "net-income", i) + self.v("Cash Flow", "dividends", i)
                  + self.v("Cash Flow", "repurchases", i))
        self.assertAlmostEqual(self.v("Balance Sheet", "equity", i) - self.v("Balance Sheet", "equity", i - 1), change)

    def test_quarters_balance_too(self):
        self.use(build(insurer_facts(quarterly=True), "insurer", "quarterly", 6, 2))
        self.assertBalances(8)
        self.assertNoCircularFormulas()
        # a quarter's losses are a quarter of a year's, so the reserves are four of them times the years of losses they are
        years = self.v("Assumptions", "loss-reserve-years", 6)
        self.assertAlmostEqual(self.v("Balance Sheet", "loss-reserves", 6), years * 4 * self.v("Income Statement", "losses", 6))
        percent = self.v("Assumptions", "unearned-percent", 6)
        self.assertAlmostEqual(self.v("Balance Sheet", "unearned-premiums", 6), percent * 4 * self.v("Income Statement", "premiums-earned", 6))


# ---------------------------------------------------------------------------
# Lines that are missing, and the choice of model
# ---------------------------------------------------------------------------

class TestWhatTheSECHas(LispTestCase):

    def test_a_bank_without_loans_cannot_be_modeled_as_one(self):
        flows = dict(BANK_FLOWS)
        balances = {k: v for k, v in BANK_BALANCES.items() if "FinancingReceivable" not in k}
        with self.assertRaises(fm.MissingLines) as caught:
            build(company_facts("ABC Bank", flows, balances), "bank")
        self.assertIn("Loans, before the allowance or Loans, net of the allowance", str(caught.exception))

    def test_loans_of_the_net_kind_will_do(self):
        balances = {k: v for k, v in BANK_BALANCES.items() if "BeforeAllowance" not in k}
        balances["FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss"] = \
            lambda y: bank_amounts(y)["loans"] - bank_amounts(y)["allowance"]
        model = build(company_facts("ABC Bank", BANK_FLOWS, balances), "bank")
        self.assertAlmostEqual(model.h.loans[1], 1100)

    def test_older_periods_that_lack_lines_are_left_out_and_the_notes_say_so(self):
        loans = BANK_BALANCES["FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss"]
        facts = company_facts("ABC Bank", BANK_FLOWS, BANK_BALANCES, years=(2020,) + YEARS)
        # (take 2020's loans out of the facts: the SEC has the bank's other lines for that year, but not its loans)
        concept = facts["facts"]["us-gaap"]["FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss"]
        concept["units"]["USD"] = [f for f in concept["units"]["USD"] if f["end"] != "2020-12-31"]
        model = build(facts, "bank", history=4)
        self.assertEqual(model.labels[:3], ["FY2021", "FY2022", "FY2023"])
        self.assertEqual(model.history_count, 3)
        self.assertIn("The history starts at 2021-12-31", model.kind_note)
        self.assertIn("The history starts at 2021-12-31", "\n".join(model.sources_for_notes()))

    def test_too_few_complete_periods_is_a_missing_lines_error(self):
        facts = company_facts("ABC Bank", BANK_FLOWS, BANK_BALANCES, years=(2022, 2023))
        concept = facts["facts"]["us-gaap"]["Deposits"]
        concept["units"]["USD"] = [f for f in concept["units"]["USD"] if f["end"] != "2022-12-31"]
        with self.assertRaises(fm.MissingLines):
            build(facts, "bank", history=2)

    def test_an_insurer_needs_premiums_and_losses(self):
        flows = {k: v for k, v in INSURER_FLOWS.items() if k != "PolicyholderBenefitsAndClaimsIncurredNet"}
        with self.assertRaises(fm.MissingLines) as caught:
            build(company_facts("ABC Insurance", flows, INSURER_BALANCES), "insurer")
        self.assertIn("Losses and loss adjustment expense", str(caught.exception))

    def test_every_kind_is_known_and_an_ordinary_company_is_the_default(self):
        self.assertEqual(sorted(fm.templates()), ["asset-manager", "bank", "general", "insurer"])
        self.assertEqual(fm.kind_for_industry(6282), "asset-manager")
        self.assertEqual(fm.kind_for_industry(6021), "bank")
        self.assertEqual(fm.kind_for_industry(6331), "insurer")
        self.assertEqual(fm.kind_for_industry(3571), "general")
        self.assertEqual(fm.kind_for_industry(None), "general")


class TestChoosingTheKind(LispTestCase):
    """(three-statement-model creds "ABC" ...) with a made-up bank, insurer, or ordinary company, and the SEC's industry code."""

    def setUp(self):
        super().setUp()
        self.written = []
        self.industry = (6021, "National Commercial Banks")
        self.facts = bank_facts()
        for patcher in (mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: self.facts),
                        mock.patch.object(fm, "company_industry", lambda creds, company, who: self.industry),
                        mock.patch.object(lisp_google, "google_workbook",
                                          lambda creds, title, sheets: self.written.append((title, sheets)) or "https://sheet")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def labels(self):
        """The first column of the income statement of the sheet made."""
        return [cells[0][0] for cells in self.written[-1][1][1]["cells"] if cells and cells[0]]

    def notes(self):
        return "\n".join(cells[0][0] for cells in next(tab for tab in self.written[-1][1] if tab["name"] == "Notes")["cells"] if cells and cells[0])

    def test_a_bank_by_its_industry_code(self):
        self.run_lisp('(three-statement-model creds "ABC")')
        self.assertIn("Net interest income", self.labels())
        self.assertNotIn("Gross profit", self.labels())

    def test_an_insurer_by_its_industry_code(self):
        self.facts, self.industry = insurer_facts(), (6331, "Fire, Marine & Casualty Insurance")
        self.run_lisp('(three-statement-model creds "ABC")')
        self.assertIn("Premiums earned", self.labels())
        self.assertIn("Combined ratio (under 100% is an underwriting profit)", self.labels())

    def test_any_other_industry_is_an_ordinary_company(self):
        self.facts, self.industry = made_up_facts(), (3571, "Electronic Computers")
        self.run_lisp('(three-statement-model creds "ABC" :segments #f)')
        self.assertIn("Gross profit", self.labels())

    def test_a_bank_the_sec_does_not_have_enough_of_is_modeled_as_an_ordinary_company_and_the_notes_say_why(self):
        self.facts = made_up_facts()                                 # (no interest on loans, deposits, ...)
        self.run_lisp('(three-statement-model creds "ABC" :segments #f)')
        self.assertIn("Gross profit", self.labels())
        self.assertIn("The SEC classifies this company as National Commercial Banks, but it is modeled as an ordinary company "
                      "because a model of a bank needs", self.notes())

    def test_the_kind_can_be_asked_for_and_then_missing_lines_are_an_error(self):
        self.facts, self.industry = made_up_facts(), (3571, "Electronic Computers")
        self.assertLispError('(three-statement-model creds "ABC" :kind "bank")', "a model of a bank needs")
        self.facts = bank_facts()
        self.run_lisp('(three-statement-model creds "ABC" :kind "general" :segments #f)')
        self.assertIn("Gross profit", self.labels())
        self.industry = (3571, "Electronic Computers")
        self.run_lisp('(three-statement-model creds "ABC" :kind "bank")')
        self.assertIn("Net interest income", self.labels())

    def test_an_unknown_kind_is_an_error(self):
        self.assertLispError('(three-statement-model creds "ABC" :kind "airline")', ':kind is "auto", "general", "bank", "insurer"')

    def test_segments_are_not_looked_for_in_a_bank(self):
        def fake(*arguments):
            raise AssertionError("looked for segments")
        with mock.patch.object(lisp_sec_segments, "revenue_by_segment", fake):
            self.run_lisp('(three-statement-model creds "ABC")')
        self.assertIn("Net interest income", self.labels())

    def test_the_industry_of_a_company_comes_from_the_secs_submissions(self):
        with mock.patch.object(lisp_sec, "company_cik", lambda creds, company, who: 19617), \
                mock.patch.object(fm.lisp_sec_filings, "sec_json",
                                  lambda url, creds, who: {"sic": "6021", "sicDescription": "National Commercial Banks"}):
            self.assertEqual(REAL_COMPANY_INDUSTRY("creds.json", "JPM", "test"), (6021, "National Commercial Banks"))

    def test_an_industry_that_cannot_be_found_is_none(self):
        def fail(*arguments):
            raise lisp_core.LispError("no network")
        with mock.patch.object(lisp_sec, "company_cik", fail):
            self.assertEqual(REAL_COMPANY_INDUSTRY("creds.json", "JPM", "test"), (None, ""))


# ---------------------------------------------------------------------------
# Segments, with Berkshire Hathaway's overlapping members
# ---------------------------------------------------------------------------

class TestSegmentsThatOverlap(LispTestCase):

    def test_the_segments_must_add_up_in_the_earlier_periods_too(self):
        # 'Insurance and other' (300) contains the 'Insurance group' (250): together they count the insurance twice;
        # with 'Rail' (100) and 'Mills' (50) they come to 700 -- the total in the latest period, by accident. In the
        # period before, the total is 380 and they add up to 650: not a set that is the business.
        values = [300, 250, 100, 50]
        self.assertEqual(lisp_sec_segments.best_combination(values, 700), [0, 1, 2, 3])
        self.assertIsNone(lisp_sec_segments.best_combination(values, 700, [[280], [230], [90], [45]], [380]))
        # the parts that really add up, in both periods:
        self.assertEqual(lisp_sec_segments.best_combination([300, 100], 400, [[280], [90]], [370]), [0, 1])

    def test_a_member_without_a_number_for_an_earlier_period_cannot_be_used(self):
        self.assertIsNone(lisp_sec_segments.best_combination([300, 100], 400, [[280], [None]], [370]))
        self.assertEqual(lisp_sec_segments.best_combination([300, 100, 100], 400, [[280], [None], [90]], [370]), [0, 2])

    def test_a_set_that_adds_up_exactly_is_preferred_to_one_that_is_only_close(self):
        # 300 + 100 is exactly 400. 300 + 60 + 30 + 6 is 396: within 1%, and more members, but not the business
        self.assertEqual(lisp_sec_segments.best_combination([300, 100, 60, 30, 6], 400), [0, 1])
        # with no set that adds up exactly, the one with the most members
        self.assertEqual(lisp_sec_segments.best_combination([300, 60, 30, 6], 398), [0, 1, 2, 3])

    def test_a_total_of_the_other_members_is_not_a_segment(self):
        f2023 = ("2023-12-31", "10-K", "2024-02-15", "https://example.com/2023")
        figures = {"OperatingSegmentsMember": 900, "AAASegmentMember": 600, "BBBSegmentMember": 300, "CorporateMember": 100}
        numbers = [(f2023, [("Revenues", (("StatementBusinessSegmentsAxis", member),), "2023-01-01", "2023-12-31", value * MILLION)
                            for member, value in figures.items()])]
        periods = [lisp_sec.Period(datetime.date(2023, 12, 31), datetime.date(2023, 1, 1), None, 2023, "FY")]
        segments, reason = lisp_sec_segments.segments_on_axis(numbers, "StatementBusinessSegmentsAxis", periods, [1000.0])
        self.assertIsNone(reason)
        self.assertEqual([name for name, _ in segments], ["AAA", "BBB", "Corporate"])

    def test_segments_that_are_not_the_same_every_year_are_not_used_and_the_reason_is_given(self):
        f2023 = ("2023-12-31", "10-K", "2024-02-15", "https://example.com/2023")
        f2022 = ("2022-12-31", "10-K", "2023-02-15", "https://example.com/2022")

        def numbers(year, figures):
            return [("Revenues", (("StatementBusinessSegmentsAxis", member),), "%d-01-01" % year, "%d-12-31" % year, value * MILLION)
                    for member, value in figures.items()]
        in_2023 = numbers(2023, {"AAASegmentMember": 600, "BBBSegmentMember": 400}) + \
            numbers(2022, {"AAASegmentMember": 300, "BBBSegmentMember": 400})
        periods = [lisp_sec.Period(datetime.date(y, 12, 31), datetime.date(y, 1, 1), None, y, "FY") for y in (2022, 2023)]
        segments, reason = lisp_sec_segments.segments_on_axis([(f2023, in_2023), (f2022, [])], "StatementBusinessSegmentsAxis",
                                                              periods, [1000.0, 1000.0])
        self.assertIsNone(segments)
        self.assertIn("add up to the company's revenue in every period", reason)
