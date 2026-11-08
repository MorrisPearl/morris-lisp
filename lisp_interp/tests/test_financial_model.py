"""The three-statement model (lisp_financial_model.py), the segments it can use (lisp_sec_segments.py),
and the spreadsheets lisp_google.google_workbook writes: a made-up company's facts and filings, and a fake
Google -- no network. sheet_formulas.py works out the formulas of the sheets as Google would, which is how
these tests know the model balances."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_financial_model as fm
import lisp_google
import lisp_sec
import lisp_sec_segments
from sheet_formulas import Sheets

MILLION = 1e6


# ---------------------------------------------------------------------------
# A made-up company
# ---------------------------------------------------------------------------

def made_up_facts(years=(2021, 2022, 2023), quarterly=False):
    """SEC company facts for ABC Inc., whose fiscal year is the calendar year: each statement line a
    number for every year (a 10-K) -- and, from 2022 on, for each quarter (10-Qs; the fourth quarter is the
    year less nine months) when `quarterly`. Revenue grows 10% a year; the cost of revenue is 60% of it;
    and there are balance sheet and cash flow items that the model has no line for, which end up in its 'other' lines."""
    def usd(*facts):
        return {"label": "", "units": {"USD": list(facts)}}

    def shares(*facts):
        return {"label": "", "units": {"shares": list(facts)}}

    def flow(start, end, value, form, filed, fy, fp, accn):
        return {"start": start, "end": end, "val": value, "form": form, "filed": filed, "fy": fy, "fp": fp,
                "accn": accn}

    def balance(end, value, form, filed, fy, fp, accn):
        return {"end": end, "val": value, "form": form, "filed": filed, "fy": fy, "fp": fp, "accn": accn}

    # a year's amounts, from its year number: the base of each line, grown 10% a year
    def amounts(year):
        grow = 1.1 ** (year - 2021)
        return {
            "revenue": 1000 * grow, "cost": 600 * grow, "rnd": 50 * grow, "sga": 120 * grow,
            "operating": 1000 * grow - 600 * grow - 50 * grow - 120 * grow - 30 * grow,     # 30 other expenses
            "interest": 20, "pretax": 1000 * grow - 600 * grow - 50 * grow - 120 * grow - 30 * grow - 20 + 8,
            "tax": 40 * grow, "shares": 100 - (year - 2021), "da": 40 * grow, "sbc": 15 * grow,
            "capex": 60 * grow, "dividends": 25, "buybacks": 50,
            "cash": 200 + 20 * (year - 2021), "receivables": 120 * grow, "inventory": 80 * grow, "ppe": 400 + 10 * (year - 2021),
            "goodwill": 150, "payable": 70 * grow, "current_debt": 30, "long_debt": 300 - 10 * (year - 2021),
        }

    facts = {}

    def add(concept, fact):
        facts.setdefault(concept, []).append(fact)

    def year_facts(year, form, filed, accn):
        a = amounts(year)
        start, end = "%d-01-01" % year, "%d-12-31" % year
        net_income = a["pretax"] - a["tax"]
        total_current = a["cash"] + a["receivables"] + a["inventory"] + 25
        total_assets = total_current + a["ppe"] + a["goodwill"] + 60
        equity = 350 + 40 * (year - 2021)
        current_liabilities = a["payable"] + a["current_debt"] + 45
        liabilities = total_assets - equity
        cf = (form, filed, year, "FY", accn)
        for concept, value in (
                ("Revenues", a["revenue"]), ("CostOfRevenue", a["cost"]), ("ResearchAndDevelopmentExpense", a["rnd"]),
                ("SellingGeneralAndAdministrativeExpense", a["sga"]), ("OperatingIncomeLoss", a["operating"]),
                ("InterestExpense", a["interest"]),
                ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", a["pretax"]),
                ("IncomeTaxExpenseBenefit", a["tax"]), ("NetIncomeLoss", net_income),
                ("DepreciationDepletionAndAmortization", a["da"]), ("ShareBasedCompensation", a["sbc"]),
                ("PaymentsToAcquirePropertyPlantAndEquipment", a["capex"]), ("PaymentsOfDividends", a["dividends"]),
                ("PaymentsForRepurchaseOfCommonStock", a["buybacks"]),
                ("NetCashProvidedByUsedInOperatingActivities", net_income + a["da"] + a["sbc"] - 25),
                ("NetCashProvidedByUsedInInvestingActivities", -a["capex"] - 15),
                ("NetCashProvidedByUsedInFinancingActivities", -a["dividends"] - a["buybacks"] - 10)):
            add(concept, flow(start, end, value * MILLION, *cf))
        add("WeightedAverageNumberOfDilutedSharesOutstanding", flow(start, end, a["shares"] * MILLION, *cf))
        for concept, value in (
                ("CashAndCashEquivalentsAtCarryingValue", a["cash"]), ("AccountsReceivableNetCurrent", a["receivables"]),
                ("InventoryNet", a["inventory"]), ("AssetsCurrent", total_current),
                ("PropertyPlantAndEquipmentNet", a["ppe"]), ("Goodwill", a["goodwill"]), ("Assets", total_assets),
                ("AccountsPayableCurrent", a["payable"]), ("DebtCurrent", a["current_debt"]),
                ("LiabilitiesCurrent", current_liabilities), ("LongTermDebtNoncurrent", a["long_debt"]),
                ("Liabilities", liabilities), ("StockholdersEquity", equity),
                ("LiabilitiesAndStockholdersEquity", total_assets)):
            add(concept, balance(end, value * MILLION, *cf))

    for year in years:
        year_facts(year, "10-K", "%d-02-15" % (year + 1), "k%d" % year)
    if quarterly:
        # quarters of the later years: a quarter's lines are the year's, shared 22, 24, 26, 28%
        shares_of_year = [0.22, 0.24, 0.26, 0.28]
        flow_concepts = ["Revenues", "CostOfRevenue", "ResearchAndDevelopmentExpense",
                         "SellingGeneralAndAdministrativeExpense", "OperatingIncomeLoss", "InterestExpense",
                         "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                         "IncomeTaxExpenseBenefit", "NetIncomeLoss", "DepreciationDepletionAndAmortization",
                         "ShareBasedCompensation", "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsOfDividends",
                         "PaymentsForRepurchaseOfCommonStock", "NetCashProvidedByUsedInOperatingActivities",
                         "NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInFinancingActivities"]
        for year in years:
            if year == years[0]:
                continue
            annual = {c: next(f["val"] for f in facts[c] if f["end"] == "%d-12-31" % year and f["start"] == "%d-01-01" % year)
                      for c in flow_concepts}
            ends = ["%d-03-31" % year, "%d-06-30" % year, "%d-09-30" % year]
            starts = ["%d-01-01" % year, "%d-04-01" % year, "%d-07-01" % year]
            for quarter in range(3):
                cf = ("10-Q", "%d-%02d-20" % (year, 4 + 3 * quarter), year, "Q%d" % (quarter + 1), "q%d%d" % (year, quarter + 1))
                for concept in flow_concepts:
                    add(concept, flow(starts[quarter], ends[quarter], annual[concept] * shares_of_year[quarter], *cf))
                    if quarter == 2:           # the third 10-Q also has the nine months
                        add(concept, flow("%d-01-01" % year, ends[2], annual[concept] * sum(shares_of_year[:3]), *cf))
                add("WeightedAverageNumberOfDilutedSharesOutstanding", flow(starts[quarter], ends[quarter],
                                                                            (100 - (year - 2021)) * MILLION, *cf))
                # a balance sheet in each quarter: the year's end, a little changed
                for concept in [f for f in facts if f in (
                        "CashAndCashEquivalentsAtCarryingValue", "AccountsReceivableNetCurrent", "InventoryNet",
                        "AssetsCurrent", "PropertyPlantAndEquipmentNet", "Goodwill", "Assets", "AccountsPayableCurrent",
                        "DebtCurrent", "LiabilitiesCurrent", "LongTermDebtNoncurrent", "Liabilities", "StockholdersEquity",
                        "LiabilitiesAndStockholdersEquity")]:
                    base = next(f["val"] for f in facts[concept] if f["end"] == "%d-12-31" % year)
                    previous = next(f["val"] for f in facts[concept] if f["end"] == "%d-12-31" % (year - 1))
                    add(concept, balance(ends[quarter], previous + (base - previous) * (quarter + 1) / 4, *cf))
    taxonomy = {}
    for concept, items in facts.items():
        taxonomy[concept] = shares(*items) if concept.startswith("WeightedAverage") else usd(*items)
    return {"cik": 4321, "entityName": "ABC Inc.", "facts": {"us-gaap": taxonomy}}


def build(period="annual", history=3, forecast=3, segments=None, quarterly_facts=False):
    facts = made_up_facts(quarterly=quarterly_facts or period == "quarterly")
    finder = None if segments is None else (lambda periods, totals: (segments(totals), "test segments"))
    return fm.build_model(facts, "ABC", period, history, forecast, "test", finder)


def evaluated(model):
    return Sheets(model.sheets())


def value(sheets, model, tab, key, i):
    """What the cell of this line, in period i (counted from the first), works out to."""
    row = model.layouts[tab].row_of[key]
    return sheets.value(tab, row - 1, i + 1)


def set_input(sheets, model, tab, key, i, number):
    """Type a number into an assumption's cell, as a person would."""
    row = model.layouts[tab].row_of[key]
    sheets.cells[tab][(row - 1, i + 1)] = number
    sheets.worked_out.clear()


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

class TestModelFromReportedNumbers(LispTestCase):

    def setUp(self):
        super().setUp()
        self.model = build()
        self.sheets = evaluated(self.model)

    def v(self, tab, key, i):
        return value(self.sheets, self.model, tab, key, i)

    def test_there_are_five_tabs_with_the_periods_in_the_same_columns(self):
        tabs = self.model.sheets()
        self.assertEqual([t["name"] for t in tabs],
                         ["Assumptions", "Income Statement", "Balance Sheet", "Cash Flow", "Notes"])
        self.assertEqual(self.model.labels, ["FY2021", "FY2022", "FY2023", "FY2024E", "FY2025E", "FY2026E"])
        for tab in tabs[:4]:
            self.assertEqual([cell[0] for cell in tab["cells"][2][1:]], self.model.labels)
        self.assertEqual([cell[1][0] for cell in tabs[1]["cells"][4][1:]], ["italic"] * 6)
        self.assertEqual([cell[0] for cell in tabs[1]["cells"][4][1:]], ["Reported"] * 3 + ["Forecast"] * 3)
        self.assertEqual(self.model.ends[3:], [datetime.date(2024, 12, 31), datetime.date(2025, 12, 31),
                                               datetime.date(2026, 12, 31)])

    def test_the_subtotals_of_the_reported_periods_are_the_companys(self):
        for i, year in enumerate((2021, 2022, 2023)):
            grow = 1.1 ** (year - 2021)
            self.assertAlmostEqual(self.v("Income Statement", "revenue", i), 1000 * grow)
            self.assertAlmostEqual(self.v("Income Statement", "gross-profit", i), 400 * grow)
            self.assertAlmostEqual(self.v("Income Statement", "operating-income", i), 200 * grow)
            self.assertAlmostEqual(self.v("Income Statement", "other-operating", i), 30 * grow)
            self.assertAlmostEqual(self.v("Income Statement", "pretax-income", i), 200 * grow - 12)
            self.assertAlmostEqual(self.v("Income Statement", "net-income", i), 200 * grow - 12 - 40 * grow)
            self.assertAlmostEqual(self.v("Income Statement", "shares", i), 100 - i)
            self.assertAlmostEqual(self.v("Balance Sheet", "total-assets", i),
                                   self.v("Balance Sheet", "total-liabilities-and-equity", i))
            self.assertAlmostEqual(self.v("Balance Sheet", "other-current-assets", i), 25)
            self.assertAlmostEqual(self.v("Balance Sheet", "other-noncurrent-assets", i), 60)

    def test_cash_flow_subtotals_of_the_reported_periods_are_the_companys(self):
        for i, year in enumerate((2021, 2022, 2023)):
            grow = 1.1 ** (year - 2021)
            net_income = 200 * grow - 12 - 40 * grow
            self.assertAlmostEqual(self.v("Cash Flow", "operating-cash-flow", i), net_income + 40 * grow + 15 * grow - 25)
            self.assertAlmostEqual(self.v("Cash Flow", "investing-cash-flow", i), -60 * grow - 15)
            self.assertAlmostEqual(self.v("Cash Flow", "financing-cash-flow", i), -25 - 50 - 10)
            self.assertAlmostEqual(self.v("Cash Flow", "capital-expenditures", i), -60 * grow)
            self.assertAlmostEqual(self.v("Cash Flow", "dividends", i), -25)

    def test_the_first_period_has_no_changes_in_working_capital_and_later_ones_come_from_the_balance_sheet(self):
        row = self.model.layouts["Cash Flow"].row_of["change-in-receivables"]
        self.assertIsNone(self.model.sheets()[3]["cells"][row - 1][1])
        self.assertAlmostEqual(self.v("Cash Flow", "change-in-receivables", 1), -(132 - 120))
        self.assertAlmostEqual(self.v("Cash Flow", "change-in-payables", 2), 70 * 1.21 - 70 * 1.1)

    def test_the_balance_sheet_balances_in_every_period_reported_or_forecast(self):
        for i in range(6):
            self.assertAlmostEqual(self.v("Balance Sheet", "check", i), 0, places=6)

    def test_the_forecast_follows_the_assumptions(self):
        # revenue grows at the assumed rate: the last period's growth (10%, within the limits)
        self.assertAlmostEqual(self.v("Assumptions", "growth", 3), 0.10)
        self.assertAlmostEqual(self.v("Income Statement", "revenue", 3), 1210 * 1.1)
        self.assertAlmostEqual(self.v("Assumptions", "gross-margin", 3), 0.4)
        self.assertAlmostEqual(self.v("Income Statement", "cost-of-revenue", 3), 1210 * 1.1 * 0.6)
        # working capital from days: receivables stay 12% of a year's revenue (43.8 days)
        self.assertAlmostEqual(self.v("Balance Sheet", "receivables", 3), 120 * 1.1 ** 3)
        # plant: last period's, plus capital spending, less depreciation (both 6% / 4% of revenue)
        rev = 1210 * 1.1
        self.assertAlmostEqual(self.v("Balance Sheet", "property-plant-equipment", 3), 420 + rev * 0.06 - rev * 0.04)
        # interest on last period's debt: 20 on 2022's debt of 320 in 2023 (6.25%), and then on 2023's 310
        rate = self.v("Assumptions", "interest-rate", 3)
        self.assertAlmostEqual(rate, 20 / 320)
        self.assertAlmostEqual(self.v("Income Statement", "interest-expense", 3), rate * (30 + 280))

    def test_changing_an_assumption_changes_everything_that_depends_on_it_and_still_balances(self):
        set_input(self.sheets, self.model, "Assumptions", "growth", 3, 0.30)
        set_input(self.sheets, self.model, "Assumptions", "net-borrowing", 4, 500.0)
        set_input(self.sheets, self.model, "Assumptions", "dividend-payout", 5, 0.9)
        self.assertAlmostEqual(self.v("Income Statement", "revenue", 3), 1210 * 1.3)
        self.assertAlmostEqual(self.v("Balance Sheet", "long-term-debt", 4), 280 + 500.0)       # 2023's, and what is borrowed
        for i in range(6):
            self.assertAlmostEqual(self.v("Balance Sheet", "check", i), 0, places=6)

    def test_cash_is_last_periods_plus_the_net_change(self):
        for i in range(3, 6):
            self.assertAlmostEqual(self.v("Balance Sheet", "cash", i),
                                   self.v("Balance Sheet", "cash", i - 1) + self.v("Cash Flow", "net-change-in-cash", i))

    def test_equity_rises_by_income_and_stock_compensation_less_payouts(self):
        i = 3
        change = (self.v("Income Statement", "net-income", i) + self.v("Cash Flow", "stock-compensation", i)
                  + self.v("Cash Flow", "dividends", i) + self.v("Cash Flow", "repurchases", i))
        self.assertAlmostEqual(self.v("Balance Sheet", "equity", i) - self.v("Balance Sheet", "equity", i - 1), change)

    def test_no_formula_refers_to_itself(self):
        # the calculator raises on a circular reference: work out every cell of every tab
        for tab in ("Assumptions", "Income Statement", "Balance Sheet", "Cash Flow"):
            for (row, column) in list(self.sheets.cells[tab]):
                self.sheets.value(tab, row, column)

    def test_the_assumptions_of_the_reported_periods_are_what_the_statements_say(self):
        """Each assumption's formula, in a reported period, works out to the number the model's Python worked out."""
        for key, (_, _, _, series, _, _) in self.model.assumptions.items():
            for i, expected in enumerate(series):
                if expected is not None:
                    self.assertAlmostEqual(self.v("Assumptions", key, i), expected, places=9, msg="%s in period %d" % (key, i))

    def test_the_colors_say_what_kind_of_number_each_is(self):
        tabs = {t["name"]: t["cells"] for t in self.model.sheets()}
        income = self.model.layouts["Income Statement"].row_of
        revenue_row = tabs["Income Statement"][income["revenue"] - 1]
        self.assertIn("data", revenue_row[1][1])                    # reported: a number typed in
        self.assertNotIn("input", revenue_row[1][1])
        self.assertNotIn("data", revenue_row[4][1])                 # forecast: a formula
        assumptions = self.model.layouts["Assumptions"].row_of
        growth_row = tabs["Assumptions"][assumptions["growth"] - 1]
        self.assertNotIn("input", growth_row[3][1])                 # reported: a formula, from the statements
        self.assertIn("input", growth_row[4][1])                    # forecast: for you to change
        link = tabs["Cash Flow"][self.model.layouts["Cash Flow"].row_of["net-income"] - 1][1]
        self.assertIn("link", link[1])                              # a link to the income statement
        self.assertTrue(link[0].startswith("='Income Statement'!"))

    def test_a_forecast_period_without_enough_history_is_an_error(self):
        facts = made_up_facts(years=(2023,))
        with self.assertRaises(lisp_core.LispError) as caught:
            fm.build_model(facts, "ABC", "annual", 3, 3, "test")
        self.assertIn("growth needs at least 2", str(caught.exception))


class TestQuarterlyModel(LispTestCase):

    def setUp(self):
        super().setUp()
        self.model = build("quarterly", history=6, forecast=5)
        self.sheets = evaluated(self.model)

    def test_labels_and_dates_run_on_from_the_last_quarter(self):
        self.assertEqual(self.model.labels, ["Q3 FY2022", "Q4 FY2022", "Q1 FY2023", "Q2 FY2023", "Q3 FY2023", "Q4 FY2023",
                                             "Q1 FY2024E", "Q2 FY2024E", "Q3 FY2024E", "Q4 FY2024E", "Q1 FY2025E"])
        self.assertEqual(self.model.ends[5:8], [datetime.date(2023, 12, 31), datetime.date(2024, 3, 31),
                                                datetime.date(2024, 6, 30)])

    def test_revenue_grows_from_the_same_quarter_a_year_before(self):
        revenue = lambda i: value(self.sheets, self.model, "Income Statement", "revenue", i)
        growth = lambda i: value(self.sheets, self.model, "Assumptions", "growth", i)
        self.assertAlmostEqual(revenue(6), revenue(2) * (1 + growth(6)))
        self.assertAlmostEqual(revenue(10), revenue(6) * (1 + growth(10)))
        self.assertAlmostEqual(growth(6), 0.10, places=6)               # from the average of the last four quarters
        self.assertAlmostEqual(revenue(2), 1210 * 0.22)                 # a quarter's revenue is 22% of the year's

    def test_the_fourth_quarter_is_the_year_less_nine_months_and_everything_balances(self):
        self.assertAlmostEqual(value(self.sheets, self.model, "Income Statement", "revenue", 5), 1210 * 0.28)
        for i in range(self.model.count):
            self.assertAlmostEqual(value(self.sheets, self.model, "Balance Sheet", "check", i), 0, places=6)

    def test_days_in_a_quarter_are_a_quarter_of_a_year_and_receivables_follow_them(self):
        self.assertEqual(self.model.days_in_period, 91.25)
        days = value(self.sheets, self.model, "Assumptions", "receivable-days", 5)
        receivables = value(self.sheets, self.model, "Balance Sheet", "receivables", 5)
        revenue = value(self.sheets, self.model, "Income Statement", "revenue", 5)
        self.assertAlmostEqual(days, receivables / revenue * 91.25)

    def test_quarters_need_five_of_history(self):
        with self.assertRaises(lisp_core.LispError) as caught:
            build("quarterly", history=4)
        self.assertIn("growth needs at least 5", str(caught.exception))


class TestModelByInSegment(LispTestCase):

    @staticmethod
    def segments(totals):
        """Two segments, and what is left."""
        first = [0.5 * t for t in totals]
        second = [0.3 * t for t in totals]
        return [("Widgets", first), ("Services", second), ("Other revenue", [t - a - b for t, a, b in zip(totals, first, second)])]

    def setUp(self):
        super().setUp()
        self.model = build(segments=self.segments)
        self.sheets = evaluated(self.model)

    def test_revenue_is_the_sum_of_the_segments_and_the_company_reported(self):
        for i, year in enumerate((2021, 2022, 2023)):
            self.assertAlmostEqual(value(self.sheets, self.model, "Income Statement", "revenue", i), 1000 * 1.1 ** (year - 2021))
        self.assertAlmostEqual(value(self.sheets, self.model, "Income Statement", "segment-0", 2), 0.5 * 1210)

    def test_each_segment_has_its_own_growth_assumption(self):
        income = lambda key, i: value(self.sheets, self.model, "Income Statement", key, i)
        self.assertAlmostEqual(value(self.sheets, self.model, "Assumptions", "segment-growth-0", 3), 0.10)
        set_input(self.sheets, self.model, "Assumptions", "segment-growth-0", 3, 0.5)
        self.assertAlmostEqual(income("segment-0", 3), 0.5 * 1210 * 1.5)
        self.assertAlmostEqual(income("segment-1", 3), 0.3 * 1210 * 1.1)
        self.assertAlmostEqual(income("revenue", 3), 0.5 * 1210 * 1.5 + 0.3 * 1210 * 1.1 + 0.2 * 1210 * 1.1)
        for i in range(6):
            self.assertAlmostEqual(value(self.sheets, self.model, "Balance Sheet", "check", i), 0, places=6)

    def test_the_growth_of_total_revenue_is_then_a_result_not_an_assumption(self):
        tabs = {t["name"]: t["cells"] for t in self.model.sheets()}
        row = tabs["Assumptions"][self.model.layouts["Assumptions"].row_of["growth"] - 1]
        self.assertTrue(row[4][0].startswith("="))
        self.assertIn("Income Statement", row[4][0])
        self.assertNotIn("input", row[4][1])

    def test_the_notes_say_where_the_segments_came_from(self):
        self.assertIn("test segments", self.model.sources_for_notes())


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

class TestHelpers(LispTestCase):

    def test_column_letters(self):
        self.assertEqual([fm.column_letter(i) for i in (0, 1, 25, 26, 27, 51, 52, 701, 702)],
                         ["A", "B", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"])

    def test_adding_months_keeps_the_end_of_the_month(self):
        d = datetime.date
        self.assertEqual(fm.add_months(d(2023, 12, 31), 3), d(2024, 3, 31))
        self.assertEqual(fm.add_months(d(2024, 3, 31), 3), d(2024, 6, 30))
        self.assertEqual(fm.add_months(d(2024, 2, 29), 12), d(2025, 2, 28))
        self.assertEqual(fm.add_months(d(2025, 9, 27), 12), d(2026, 9, 27))

    def test_a_ratio_with_no_denominator_is_none(self):
        self.assertIsNone(fm.safe_ratio(3, 0))
        self.assertIsNone(fm.safe_ratio(None, 2))
        self.assertEqual(fm.safe_ratio(3, 2), 1.5)

    def test_a_guess_is_the_last_value_or_the_last_years_quarters_kept_within_limits(self):
        annual = build()
        self.assertEqual(annual.default_guess([0.1, None, 0.5], (0, 0.2)), 0.2)
        self.assertEqual(annual.default_guess([None, None], (0, 1)), 0.0)
        quarterly = build("quarterly", history=6)
        self.assertAlmostEqual(quarterly.default_guess([9, 1, 2, 3, 4], (-100, 100)), 2.5)

    def test_a_missing_line_is_zero_and_the_notes_say_so(self):
        model = build()
        notes = model.sources_for_notes()
        self.assertTrue(any(text.startswith("Lines the company has not reported") and "Intangible assets" in text
                            for text in notes))
        self.assertTrue(any(text.startswith("Revenue: Revenues") for text in notes))


# ---------------------------------------------------------------------------
# Revenue by segment, from filings
# ---------------------------------------------------------------------------

INLINE_XBRL = """
<html><body><ix:header><ix:resources>
<xbrli:context id="c1"><xbrli:entity/><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c2"><xbrli:entity><xbrli:segment>
  <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:WidgetsSegmentMember</xbrldi:explicitMember>
  <xbrldi:explicitMember dimension="srt:ConsolidationItemsAxis">us-gaap:OperatingSegmentsMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c3"><xbrli:entity><xbrli:segment>
  <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:ServicesSegmentMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c4"><xbrli:entity><xbrli:segment>
  <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">country:US</xbrldi:explicitMember>
  <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:WidgetsSegmentMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c5"><xbrli:entity/><xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources></ix:header>
<table><tr><td>Revenue</td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c1" unitRef="usd" scale="6" decimals="-6">1,000</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" contextRef="c2" scale="6">600</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c3" scale="6"><span>350</span></ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c4" scale="6">200</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c5" scale="6">7</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c3" scale="3" sign="-">12</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c3" format="ixt:fixed-zero">&#8212;</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c1" scale="6">99</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c3" scale="6">not a number</ix:nonFraction></td>
</tr></table></body></html>
"""


class TestSegmentsFromFilings(LispTestCase):

    def test_contexts_have_their_period_and_dimensions(self):
        contexts = lisp_sec_segments.contexts_of(INLINE_XBRL)
        self.assertEqual(contexts["c1"], ("2023-01-01", "2023-12-31", ()))
        self.assertEqual(contexts["c2"], ("2023-01-01", "2023-12-31",
                                          (("StatementBusinessSegmentsAxis", "WidgetsSegmentMember"),
                                           ("ConsolidationItemsAxis", "OperatingSegmentsMember"))))
        self.assertEqual(contexts["c5"], (None, "2023-12-31", ()))

    def test_revenue_numbers_are_in_dollars_with_their_signs_and_dashes_are_zero(self):
        numbers = lisp_sec_segments.revenue_numbers(INLINE_XBRL)
        values = [(concept, [m for _, m in dimensions], value) for concept, dimensions, start, end, value in numbers]
        self.assertEqual(values[0], ("Revenues", [], 1000e6))
        self.assertEqual(values[1], ("RevenueFromContractWithCustomerExcludingAssessedTax",
                                     ["WidgetsSegmentMember", "OperatingSegmentsMember"], 600e6))
        self.assertEqual(values[2][2], 350e6)                    # (a number can have tags inside it)
        self.assertIn(("Revenues", [], 7e6), values)             # a number at a moment is read; axis_facts leaves it out
        self.assertIn(("Revenues", ["ServicesSegmentMember"], -12e3), values)
        self.assertIn(("Revenues", ["ServicesSegmentMember"], 0.0), values)
        self.assertNotIn("NetIncomeLoss", [v[0] for v in values])
        self.assertEqual(len(values), 7)                         # the seven revenue tags that hold a number

    def test_member_names_are_readable(self):
        self.assertEqual(lisp_sec_segments.member_name("RestOfAsiaPacificSegmentMember"), "Rest Of Asia Pacific")
        self.assertEqual(lisp_sec_segments.member_name("IPhoneMember"), "IPhone")
        self.assertEqual(lisp_sec_segments.member_name("Member"), "Member")

    def test_the_best_combination_is_the_most_members_that_add_up_to_the_total(self):
        # Product (500) is made of iPhone (300) and Mac (200), so Product with Service (300), and iPhone
        # with Mac and Service, both add up to 800: the second has more members, and is the one wanted
        values = [500, 300, 300, 200]                       # Product, iPhone, Service, Mac
        self.assertEqual(lisp_sec_segments.best_combination(values, 800), [1, 2, 3])
        self.assertEqual(lisp_sec_segments.best_combination([500, 300], 800), [0, 1])
        self.assertIsNone(lisp_sec_segments.best_combination([500, 300], 5000))
        self.assertEqual(lisp_sec_segments.best_combination([500, 300], 796), [0, 1])         # (within 1%)

    def periods(self, years):
        return [lisp_sec.Period(datetime.date(y, 12, 31), datetime.date(y, 1, 1), None, y, "FY") for y in years]

    def numbers_for(self, year, figures, end=None):
        """The revenue numbers a filing for `year` has: figures is {axis member: value}."""
        return [("Revenues", (("StatementBusinessSegmentsAxis", member),), "%d-01-01" % year, "%d-12-31" % year, value * MILLION)
                for member, value in figures.items()]

    def filing(self, year, filed):
        return ("%d-12-31" % year, "10-K", filed, "https://example.com/%d" % year)

    def test_segments_that_add_up_are_found_for_each_period_and_what_is_left_is_other_revenue(self):
        f2023 = self.filing(2023, "2024-02-15")
        f2022 = self.filing(2022, "2023-02-15")
        numbers = [(f2023, self.numbers_for(2023, {"WidgetsSegmentMember": 600, "ServicesSegmentMember": 395})
                    + self.numbers_for(2022, {"WidgetsSegmentMember": 500, "ServicesSegmentMember": 300})),
                   (f2022, self.numbers_for(2022, {"WidgetsSegmentMember": 500, "ServicesSegmentMember": 300}))]
        segments, reason = lisp_sec_segments.segments_on_axis(numbers, "StatementBusinessSegmentsAxis",
                                                              self.periods([2022, 2023]), [820.0, 1000.0])
        self.assertIsNone(reason)
        self.assertEqual([name for name, _ in segments], ["Widgets", "Services", "Other revenue"])
        self.assertEqual(segments[0][1], [500.0, 600.0])
        self.assertEqual(segments[2][1], [20.0, 5.0])

    def test_segments_missing_for_a_period_are_not_used_and_the_reason_is_given(self):
        f2023 = self.filing(2023, "2024-02-15")
        numbers = [(f2023, self.numbers_for(2023, {"WidgetsSegmentMember": 600, "ServicesSegmentMember": 400}))]
        segments, reason = lisp_sec_segments.segments_on_axis(numbers, "StatementBusinessSegmentsAxis",
                                                              self.periods([2022, 2023]), [900.0, 1000.0])
        self.assertIsNone(segments)
        self.assertIn("has no number for every period", reason)
        segments, reason = lisp_sec_segments.segments_on_axis(numbers, "ProductOrServiceAxis",
                                                              self.periods([2023]), [1000.0])
        self.assertIn("tag no revenue by ProductOrServiceAxis", reason)
        segments, reason = lisp_sec_segments.segments_on_axis(numbers, "StatementBusinessSegmentsAxis",
                                                              self.periods([2023]), [5000.0])
        self.assertIn("add up to the company's revenue", reason)

    def test_a_member_of_zero_is_not_a_segment(self):
        f2023 = self.filing(2023, "2024-02-15")
        numbers = [(f2023, self.numbers_for(2023, {"AAA": 600, "BBB": 400, "CorporateNonSegmentMember": 0}))]
        segments, _ = lisp_sec_segments.segments_on_axis(numbers, "StatementBusinessSegmentsAxis",
                                                         self.periods([2023]), [1000.0])
        self.assertEqual([name for name, _ in segments], ["AAA", "BBB"])

    def test_the_filings_are_read_newest_first_until_every_period_is_covered(self):
        facts = made_up_facts()
        submissions = {"filings": {"recent": {
            "form": ["10-K", "10-Q", "10-K", "10-K"], "filingDate": ["2024-02-15", "2023-05-01", "2023-02-15", "2022-02-15"],
            "reportDate": ["2023-12-31", "2023-03-31", "2022-12-31", "2021-12-31"],
            "accessionNumber": ["0-24-1", "0-23-2", "0-23-1", "0-22-1"],
            "primaryDocument": ["a.htm", "q.htm", "b.htm", "c.htm"]}}}
        read = []
        document_numbers = {
            "a.htm": self.numbers_for(2023, {"W": 600, "S": 400}) + self.numbers_for(2022, {"W": 550, "S": 350})
            + self.numbers_for(2021, {"W": 500, "S": 300}),
        }

        def fake_numbers(credentials_path, url, who):
            read.append(url.rsplit("/", 1)[1])
            return document_numbers.get(url.rsplit("/", 1)[1], [])
        periods = list(reversed(lisp_sec.chosen_periods(facts, {"period": "annual", "count": 3}, "t")))
        with mock.patch.object(lisp_sec_filings_module(), "sec_json", lambda url, creds, who: submissions), \
                mock.patch.object(lisp_sec, "company_cik", lambda *a: 4321), \
                mock.patch.object(lisp_sec_segments, "numbers_in_filing", fake_numbers):
            segments, description = lisp_sec_segments.revenue_by_segment("creds", "ABC", periods, [800.0, 900.0, 1000.0],
                                                                         "auto", "t")
        self.assertEqual(read, ["a.htm"])                    # the 10-Q isn't read for an annual model, and the first 10-K had it all
        self.assertEqual([name for name, _ in segments], ["W", "S"])
        self.assertIn("StatementBusinessSegmentsAxis (W, S)", description)

    def test_a_kind_that_is_not_known_is_an_error(self):
        with self.assertRaises(lisp_core.LispError) as caught:
            lisp_sec_segments.revenue_by_segment("creds", "ABC", self.periods([2023]), [1.0], "regional", "t")
        self.assertIn(':segments is "auto"', str(caught.exception))


def lisp_sec_filings_module():
    import lisp_sec_filings
    return lisp_sec_filings


# ---------------------------------------------------------------------------
# The Google workbook, and the builtin
# ---------------------------------------------------------------------------

class TestGoogleWorkbook(LispTestCase):

    def setUp(self):
        super().setUp()
        self.requests = []
        for patcher in (mock.patch.object(lisp_google, "access_token", lambda *a: "token"),
                        mock.patch.object(lisp_google, "google_request", self.fake_request)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fail_on = None

    def fake_request(self, method, url, who, headers, body=None):
        body = json.loads(body)
        self.requests.append((url, body))
        if url == lisp_google.SHEETS_URL:
            return {"spreadsheetId": "ID1", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/ID1/edit",
                    "sheets": [{"properties": {"sheetId": 7 + i}} for i in range(len(body["sheets"]))]}
        if self.fail_on and self.fail_on in url:
            raise lisp_core.LispError("google-workbook: Google says (HTTP 500): oops")
        return {}

    def sheet(self, **more):
        sheet = {"name": "Model", "cells": [
            [("Title", ("title",)), None],
            [("Growth", ()), (0.1, ("input", "percent"))],
            [("Revenue", ("bold",)), ("=B2*100", ("money", "link"))],
            [("The date", ()), (datetime.date(2023, 12, 31), ("date",))],
            [("A flag", ()), (True, ())]]}
        sheet.update(more)
        return sheet

    def test_cells_are_written_with_their_kind_of_value_and_their_formats(self):
        url = lisp_google.google_workbook("creds", " My model ", [self.sheet(frozen_rows=1, frozen_columns=1,
                                                                             widths=[(0, 0, 300)])])
        self.assertEqual(url, "https://docs.google.com/spreadsheets/d/ID1/edit")
        made = self.requests[0][1]
        self.assertEqual(made["properties"]["title"], "My model")
        grid = made["sheets"][0]["properties"]["gridProperties"]
        self.assertEqual((grid["rowCount"], grid["columnCount"], grid["frozenRowCount"], grid["frozenColumnCount"]),
                         (5, 2, 1, 1))
        edits = self.requests[1][1]["requests"]
        rows = edits[0]["updateCells"]["rows"]
        self.assertEqual(edits[0]["updateCells"]["start"], {"sheetId": 7, "rowIndex": 0, "columnIndex": 0})
        self.assertEqual(rows[0]["values"][0]["userEnteredValue"], {"stringValue": "Title"})
        self.assertEqual(rows[0]["values"][1], {})                                         # an empty cell
        self.assertEqual(rows[1]["values"][1]["userEnteredValue"], {"numberValue": 0.1})
        self.assertEqual(rows[1]["values"][1]["userEnteredFormat"]["numberFormat"]["type"], "PERCENT")
        self.assertEqual(rows[1]["values"][1]["userEnteredFormat"]["backgroundColor"], lisp_google.PALE_YELLOW)
        self.assertEqual(rows[2]["values"][1]["userEnteredValue"], {"formulaValue": "=B2*100"})
        self.assertEqual(rows[2]["values"][1]["userEnteredFormat"]["textFormat"]["foregroundColor"], lisp_google.GREEN)
        self.assertEqual(rows[2]["values"][0]["userEnteredFormat"]["textFormat"]["bold"], True)
        self.assertEqual(rows[3]["values"][1]["userEnteredValue"], {"numberValue": 45291})        # 2023-12-31
        self.assertEqual(rows[4]["values"][1]["userEnteredValue"], {"boolValue": True})
        self.assertEqual(edits[1]["updateDimensionProperties"]["range"],
                         {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1})

    def test_a_long_tab_is_sent_in_pieces(self):
        cells = [[(i, ())] for i in range(450)]
        lisp_google.google_workbook("creds", "Long", [{"name": "Long", "cells": cells}])
        updates = [r for r in self.requests[1][1]["requests"] if "updateCells" in r]
        self.assertEqual([len(u["updateCells"]["rows"]) for u in updates], [200, 200, 50])
        self.assertEqual([u["updateCells"]["start"]["rowIndex"] for u in updates], [0, 200, 400])

    def test_styles_combine_and_an_unknown_one_is_an_error(self):
        combined = lisp_google.style_format(["total", "money", "data"])
        self.assertEqual(combined["textFormat"], {"bold": True, "foregroundColor": lisp_google.BLUE})
        self.assertIn("borders", combined)
        with self.assertRaises(lisp_core.LispError):
            lisp_google.style_format(["sparkly"])
        self.assertEqual(lisp_google.style_format(["title"])["textFormat"]["fontSize"], 14)

    def test_tabs_need_different_names(self):
        with self.assertRaises(lisp_core.LispError) as caught:
            lisp_google.google_workbook("creds", "T", [self.sheet(), self.sheet(name="model")])
        self.assertIn("different name", str(caught.exception))
        self.assertEqual(self.requests, [])

    def test_a_failure_after_the_spreadsheet_is_made_says_where_it_is(self):
        self.fail_on = ":batchUpdate"
        with self.assertRaises(lisp_core.LispError) as caught:
            lisp_google.google_workbook("creds", "T", [self.sheet()])
        self.assertIn("the spreadsheet was made, at https://docs.google.com/spreadsheets/d/ID1/edit, but isn't finished",
                      str(caught.exception))


class TestThreeStatementModelBuiltin(LispTestCase):
    """(three-statement-model creds "ABC" ...), from the facts (no network) to the request for Google."""

    def setUp(self):
        super().setUp()
        lisp_sec._parsed_facts.clear()
        self.addCleanup(lisp_sec._parsed_facts.clear)
        facts = made_up_facts(quarterly=True)
        self.written = []
        for patcher in (mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: facts),
                        mock.patch.object(lisp_google, "google_workbook",
                                          lambda creds, title, sheets: self.written.append((title, sheets)) or "https://sheet")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def test_it_makes_the_sheet_and_gives_its_address(self):
        self.assertShows('(three-statement-model creds "abc" :segments #f)', '"https://sheet"')
        title, sheets = self.written[0]
        self.assertEqual(title, "ABC Inc. annual model")
        self.assertEqual(sheets[1]["cells"][0][0][0], "ABC Inc. (ABC): Income Statement")
        self.assertEqual(len(sheets[1]["cells"][2]), 1 + 3 + 5)           # 3 years in the facts, so 3 reported, and 5 forecast

    def test_options_choose_the_periods_and_the_title(self):
        self.run_lisp('(three-statement-model creds "ABC" :period "quarterly" :history 6 :forecast 2 :title "Quarters" :segments #f)')
        title, sheets = self.written[0]
        self.assertEqual(title, "Quarters")
        self.assertEqual(len(sheets[0]["cells"][2]), 1 + 6 + 2)

    def test_a_model_of_the_sheet_the_builtin_made_balances(self):
        self.run_lisp('(three-statement-model creds "ABC" :history 3 :forecast 4 :segments #f)')
        tabs = self.written[0][1]
        sheets = Sheets(tabs)
        balance = next(tab for tab in tabs if tab["name"] == "Balance Sheet")
        row = next(i for i, cells in enumerate(balance["cells"]) if cells[0] and cells[0][0].startswith("Check:"))
        self.assertEqual([round(sheets.value("Balance Sheet", row, column), 6) for column in range(1, 8)], [0.0] * 7)

    def test_segments_are_looked_for_unless_turned_off(self):
        calls = []

        def fake(credentials_path, company, periods, totals, kind, who):
            calls.append(kind)
            return None, "not found"
        with mock.patch.object(lisp_sec_segments, "revenue_by_segment", fake):
            self.run_lisp('(three-statement-model creds "ABC")')
            self.assertEqual(calls, ["auto"])
            self.assertIn("Revenue is modeled in total, not by segment: not found", "\n".join(
                fm_text for fm_text in [cell[0][0] for cell in self.written[0][1][4]["cells"] if cell and cell[0]]))
            self.assertLispError('(three-statement-model creds "ABC" :segments "product")', "no product segments: not found")
            self.run_lisp('(three-statement-model creds "ABC" :segments #f)')
            self.assertEqual(calls, ["auto", "product"])

    def test_bad_options_are_errors(self):
        self.assertLispError('(three-statement-model creds "ABC" :period "monthly")', ':period is "annual" or "quarterly"')
        self.assertLispError('(three-statement-model creds "ABC" :history 0)', ":history is a whole number of periods")
        self.assertLispError('(three-statement-model creds "ABC" :forecast 2.5)', ":forecast is a whole number of periods")
        self.assertLispError('(three-statement-model creds "ABC" :years 5)', ":years isn't an option")


# ---------------------------------------------------------------------------
# Service companies: little inventory, costs and dividends tagged their own ways, acquired intangibles
# ---------------------------------------------------------------------------

def changed_facts(remove=(), rename=None, add=None):
    """ABC Inc.'s facts with some concepts taken out, renamed (old -> new), or added (new -> the amount of a year,
    in millions, as a function of its growth since 2021, for the three years)."""
    facts = made_up_facts()
    taxonomy = facts["facts"]["us-gaap"]
    for concept in remove:
        del taxonomy[concept]
    for old, new in (rename or {}).items():
        taxonomy[new] = taxonomy.pop(old)
    for concept, (kind, amount) in (add or {}).items():
        items = []
        for year in (2021, 2022, 2023):
            fact = {"val": amount(1.1 ** (year - 2021)) * MILLION, "form": "10-K", "filed": "%d-02-15" % (year + 1),
                    "fy": year, "fp": "FY", "accn": "k%d" % year}
            if kind == "flow":
                fact.update(start="%d-01-01" % year, end="%d-12-31" % year)
            else:
                fact["end"] = "%d-12-31" % year
            items.append(fact)
        taxonomy[concept] = {"label": "", "units": {"USD": items}}
    return facts


def build_from(facts, period="annual", history=3, forecast=3):
    return fm.build_model(facts, "ABC", period, history, forecast, "test", None)


class TestServiceCompanies(LispTestCase):

    def test_a_company_with_no_cost_of_revenue_has_payables_that_follow_revenue_not_zero(self):
        model = build_from(changed_facts(remove=["CostOfRevenue"]))
        sheets = evaluated(model)
        self.assertEqual(model.assumptions["payable-days"][1], "Payables, days of revenue")
        days = value(sheets, model, "Assumptions", "payable-days", 3)
        self.assertAlmostEqual(days, 70 * 1.21 / (1000 * 1.21) * 365)
        self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "accounts-payable", 3),
                               70 * 1.1 ** 3 * 1.0, places=6)
        for i in range(6):
            self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "check", i), 0, places=6)

    def test_a_company_with_a_cost_of_revenue_has_days_of_it(self):
        model = build()
        self.assertEqual(model.assumptions["payable-days"][1], "Payables, days of cost of revenue")

    def test_the_cost_of_services_excluding_depreciation_is_the_cost_of_revenue(self):
        model = build_from(changed_facts(rename={"CostOfRevenue": "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"}))
        self.assertAlmostEqual(model.h.cost_of_revenue[1], 660)
        self.assertEqual(model.reported.sources["cost-of-revenue"],
                         ["CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"])

    def test_selling_and_marketing_with_general_and_administrative_are_selling_general_and_administrative(self):
        model = build_from(changed_facts(remove=["SellingGeneralAndAdministrativeExpense"],
                                         add={"SellingAndMarketingExpense": ("flow", lambda g: 70 * g),
                                              "GeneralAndAdministrativeExpense": ("flow", lambda g: 50 * g)}))
        sheets = evaluated(model)
        for i, grow in enumerate((1.0, 1.1, 1.21)):
            self.assertAlmostEqual(value(sheets, model, "Income Statement", "selling", i), 120 * grow)
            self.assertAlmostEqual(value(sheets, model, "Income Statement", "operating-income", i), 200 * grow)

    def test_dividends_tagged_as_ordinary_dividends_are_found(self):
        model = build_from(changed_facts(rename={"PaymentsOfDividends": "PaymentsOfOrdinaryDividends"}))
        self.assertEqual(model.h.dividends, [-25.0] * 3)

    def test_depreciation_and_the_amortization_of_intangibles_reported_apart_are_added_for_the_total(self):
        facts = changed_facts(remove=["DepreciationDepletionAndAmortization"],
                              add={"Depreciation": ("flow", lambda g: 30 * g), "AmortizationOfIntangibleAssets": ("flow", lambda g: 10 * g),
                                   "IntangibleAssetsNetExcludingGoodwill": ("balance", lambda g: 100.0)})
        model = build_from(facts)
        sheets = evaluated(model)
        for i, grow in enumerate((1.0, 1.1, 1.21)):
            self.assertAlmostEqual(value(sheets, model, "Cash Flow", "depreciation", i), 30 * grow)
            self.assertAlmostEqual(value(sheets, model, "Cash Flow", "amortization", i), 10 * grow)
            # operating cash flow is as reported: net income + depreciation and amortization + stock compensation - 25
            self.assertAlmostEqual(value(sheets, model, "Cash Flow", "operating-cash-flow", i),
                                   value(sheets, model, "Income Statement", "net-income", i) + 40 * grow + 15 * grow - 25)

    def test_amortization_comes_off_the_intangibles_and_depreciation_off_the_plant(self):
        facts = changed_facts(remove=["DepreciationDepletionAndAmortization"],
                              add={"Depreciation": ("flow", lambda g: 30 * g), "AmortizationOfIntangibleAssets": ("flow", lambda g: 10 * g),
                                   "IntangibleAssetsNetExcludingGoodwill": ("balance", lambda g: 100.0)})
        model = build_from(facts)
        sheets = evaluated(model)
        rate = value(sheets, model, "Assumptions", "amortization-rate", 3)
        self.assertAlmostEqual(rate, 12.1 / 100)                          # 2023's amortization on 2022's intangibles
        self.assertAlmostEqual(value(sheets, model, "Cash Flow", "amortization", 3), rate * 100)
        self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "intangible-assets", 3), 100 - rate * 100)
        i = 3
        self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "property-plant-equipment", i),
                               value(sheets, model, "Balance Sheet", "property-plant-equipment", i - 1)
                               - value(sheets, model, "Cash Flow", "capital-expenditures", i)
                               - value(sheets, model, "Cash Flow", "depreciation", i))
        for i in range(6):
            self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "check", i), 0, places=6)

    def test_a_company_that_reports_no_amortization_apart_has_none_and_keeps_its_intangibles(self):
        model = build()
        sheets = evaluated(model)
        self.assertAlmostEqual(value(sheets, model, "Cash Flow", "amortization", 3), 0)
        self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "intangible-assets", 3),
                               value(sheets, model, "Balance Sheet", "intangible-assets", 2))

    def test_a_payouts_guess_for_years_is_the_average_of_the_last_three_not_the_last_one(self):
        model = build()
        sheets = evaluated(model)
        history = [value(sheets, model, "Assumptions", "buyback-payout", i) for i in range(3)]
        self.assertGreater(abs(history[2] - sum(history) / 3), 1e-4)
        self.assertAlmostEqual(value(sheets, model, "Assumptions", "buyback-payout", 3), sum(history) / 3)
        # (other assumptions are the last period's)
        self.assertAlmostEqual(value(sheets, model, "Assumptions", "tax-rate", 3), value(sheets, model, "Assumptions", "tax-rate", 2))
