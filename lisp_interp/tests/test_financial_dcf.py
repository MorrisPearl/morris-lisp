"""The DCF tab of the three-statement model (lisp_financial_dcf.py): a made-up company's facts, no network.
sheet_formulas.py works out the tab's formulas as Google would, and the tests check them against the
valuation worked out here in Python from the model's own statements."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_financial_dcf
import lisp_financial_model as fm
import lisp_google
import lisp_sec
from sheet_formulas import Sheets
from test_financial_bank_insurer import bank_facts, build as build_kind, insurer_facts
from test_financial_model import build, value, set_input


class DcfTestCase(LispTestCase):
    """`self.d(key)` is a value in column B of the DCF tab; `self.d(key, i)` a period's."""

    def use(self, model):
        self.model = model
        self.valuation = lisp_financial_dcf.Valuation(model)
        self.sheets = Sheets(model.sheets())

    def d(self, key, i=None):
        return self.sheets.value("DCF", self.valuation.row_of[key] - 1, 1 if i is None else i + 1)

    def v(self, tab, key, i):
        return value(self.sheets, self.model, tab, key, i)

    def type_into(self, key, number, i=None):
        """Type a number over a cell of the DCF tab, as a person would."""
        self.sheets.cells["DCF"][(self.valuation.row_of[key] - 1, 1 if i is None else i + 1)] = number
        self.sheets.worked_out.clear()

    def expected_free_cash_flow(self, i):
        tax = self.v("Assumptions", "tax-rate", i)
        operating = self.v("Income Statement", "operating-income", i)
        working_capital = sum(self.v("Cash Flow", key, i) for key in
                              ("change-in-receivables", "change-in-inventory", "change-in-payables"))
        return (operating * (1 - tax) + self.v("Cash Flow", "depreciation", i) + self.v("Cash Flow", "amortization", i)
                + self.v("Cash Flow", "capital-expenditures", i) + working_capital)

    def invested_capital(self, i):
        return (self.v("Balance Sheet", "property-plant-equipment", i) + self.v("Balance Sheet", "goodwill", i)
                + self.v("Balance Sheet", "intangible-assets", i) + self.v("Balance Sheet", "receivables", i)
                + self.v("Balance Sheet", "inventory", i) - self.v("Balance Sheet", "accounts-payable", i))

    def expected_value(self, wacc, growth, years_to_cash, ppy=1, method=0):
        """The equity value per share from the free cash flows, worked out here."""
        first = self.model.history_count
        flows = [self.expected_free_cash_flow(i) for i in range(first, self.model.count)]
        present = sum(f / (1 + wacc) ** t for f, t in zip(flows, years_to_cash))
        if method == 0:
            terminal_flow = sum(flows[-ppy:]) * (1 + growth)
        else:
            nopat = sum(self.v("Income Statement", "operating-income", i) * (1 - self.v("Assumptions", "tax-rate", i))
                        for i in range(self.model.count - ppy, self.model.count))
            terminal_flow = nopat * (1 + growth) - growth * self.invested_capital(self.model.count - 1)
        terminal = terminal_flow / (wacc - growth) / (1 + wacc) ** years_to_cash[-1]
        last = first - 1
        cash = self.v("Balance Sheet", "cash", last) + self.v("Balance Sheet", "short-term-investments", last)
        debt = self.v("Balance Sheet", "current-debt", last) + self.v("Balance Sheet", "long-term-debt", last)
        return (present + terminal - debt + cash) / self.v("Income Statement", "shares", last)


class TestTheTab(DcfTestCase):

    def setUp(self):
        super().setUp()
        self.use(build())

    def test_the_tab_comes_after_the_cash_flow_statement_and_every_formula_works(self):
        self.assertEqual([t["name"] for t in self.model.sheets()],
                         ["Assumptions", "Income Statement", "Balance Sheet", "Cash Flow", "DCF", "Notes"])
        for (row, column) in list(self.sheets.cells["DCF"]):
            self.sheets.value("DCF", row, column)

    def test_the_periods_are_in_the_same_columns_as_on_the_other_tabs(self):
        tabs = {t["name"]: t for t in self.model.sheets()}
        self.assertEqual([cell[0] for cell in tabs["DCF"]["cells"][2][1:4 + 3]], self.model.labels)
        self.assertEqual(self.d("operating-income", 4), self.v("Income Statement", "operating-income", 4))

    def test_free_cash_flow_is_the_operating_income_after_tax_plus_depreciation_less_capital_and_working_capital(self):
        for i in range(1, self.model.count):
            self.assertAlmostEqual(self.d("fcf", i), self.expected_free_cash_flow(i), places=6)
        self.assertAlmostEqual(self.d("nopat", 4), self.d("operating-income", 4) * (1 - self.v("Assumptions", "tax-rate", 4)))

    def test_the_first_period_has_no_working_capital_change_and_so_no_free_cash_flow(self):
        row = self.valuation.row_of["fcf"] - 1
        self.assertNotIn((row, 1), self.sheets.cells["DCF"])

    def test_the_cost_of_equity_and_wacc_come_from_the_inputs(self):
        self.assertAlmostEqual(self.d("cost-of-equity"), 0.045 + 1.0 * 0.05)
        first = self.model.history_count
        after_tax_debt = self.v("Assumptions", "interest-rate", first) * (1 - self.v("Assumptions", "tax-rate", first))
        self.assertAlmostEqual(self.d("debt-cost-after-tax"), after_tax_debt)
        self.assertAlmostEqual(self.d("wacc"), 0.8 * self.d("cost-of-equity") + 0.2 * after_tax_debt)

    def test_years_run_from_the_end_of_the_last_period_reported(self):
        self.assertEqual([self.d("years-to-end", i) for i in (3, 4, 5)], [1.0, 2.0, 3.0])
        self.assertEqual([self.d("years-to-cash", i) for i in (3, 4, 5)], [1.0, 2.0, 3.0])

    def test_the_enterprise_value_is_the_present_values_of_the_cash_flows_and_the_terminal_value(self):
        wacc, growth = self.d("wacc"), self.d("terminal-growth")
        flows = [self.d("fcf", i) for i in (3, 4, 5)]
        present = sum(f / (1 + wacc) ** t for f, t in zip(flows, (1, 2, 3)))
        terminal_value = flows[-1] * (1 + growth) / (wacc - growth)
        self.assertAlmostEqual(self.d("sum-present-values"), present, places=6)
        self.assertAlmostEqual(self.d("terminal-value"), terminal_value, places=6)
        self.assertAlmostEqual(self.d("enterprise-value"), present + terminal_value / (1 + wacc) ** 3, places=6)
        self.assertAlmostEqual(self.d("terminal-share"), terminal_value / (1 + wacc) ** 3 / self.d("enterprise-value"))

    def test_the_equity_value_takes_off_the_debt_and_adds_the_cash(self):
        self.assertAlmostEqual(self.d("value-per-share"), self.expected_value(self.d("wacc"), 0.025, (1, 2, 3)), places=8)
        last = self.model.history_count - 1
        debt = self.v("Balance Sheet", "current-debt", last) + self.v("Balance Sheet", "long-term-debt", last)
        self.assertAlmostEqual(self.d("less-debt"), -debt)
        self.assertAlmostEqual(self.d("equity-value"), self.d("enterprise-value") - debt + self.d("plus-cash"))
        self.assertAlmostEqual(self.d("shares"), self.v("Income Statement", "shares", last))

    def test_the_terminal_multiple_is_the_terminal_value_over_the_last_years_ebitda(self):
        ebitda = self.v("Income Statement", "operating-income", 5) + self.v("Cash Flow", "depreciation", 5) \
            + self.v("Cash Flow", "amortization", 5)
        self.assertAlmostEqual(self.d("terminal-multiple"), self.d("terminal-value") / ebitda)

    def test_the_middle_of_the_table_is_the_value_per_share(self):
        wacc_row = self.valuation.row_of["grid-2"] - 1
        self.assertAlmostEqual(self.sheets.value("DCF", wacc_row, 1), self.d("wacc"))
        self.assertAlmostEqual(self.sheets.value("DCF", wacc_row, 4), self.d("value-per-share"), places=8)

    def test_the_table_has_other_discount_rates_and_growth_rates_worked_out_in_full(self):
        wacc, growth = self.d("wacc"), self.d("terminal-growth")
        for number, rate_step in enumerate((-0.02, -0.01, 0.0, 0.01, 0.02)):
            row = self.valuation.row_of["grid-%d" % number] - 1
            self.assertAlmostEqual(self.sheets.value("DCF", row, 1), wacc + rate_step)
            for column, growth_step in zip(range(2, 7), (-0.01, -0.005, 0.0, 0.005, 0.01)):
                self.assertAlmostEqual(self.sheets.value("DCF", row, column),
                                       self.expected_value(wacc + rate_step, growth + growth_step, (1, 2, 3)), places=8)

    def test_a_higher_discount_rate_is_worth_less_and_higher_growth_more(self):
        grid = [[self.sheets.value("DCF", self.valuation.row_of["grid-%d" % r] - 1, c) for c in range(2, 7)] for r in range(5)]
        for r in range(4):
            for c in range(5):
                self.assertGreater(grid[r][c], grid[r + 1][c])
        for r in range(5):
            self.assertEqual(grid[r], sorted(grid[r]))

    def test_typing_a_different_wacc_changes_everything_after_it(self):
        before = self.d("value-per-share")
        self.type_into("wacc", 0.12)
        self.assertAlmostEqual(self.d("value-per-share"), self.expected_value(0.12, 0.025, (1, 2, 3)), places=8)
        self.assertLess(self.d("value-per-share"), before)

    def test_the_other_terminal_method_grows_the_operating_income_and_takes_off_the_investment_to_grow_it(self):
        self.type_into("terminal-method", 1)
        self.assertAlmostEqual(self.d("invested-capital"), self.invested_capital(5), places=6)
        self.assertAlmostEqual(self.d("terminal-fcf"), self.d("last-year-nopat") * 1.025 - 0.025 * self.d("invested-capital"),
                               places=6)
        self.assertAlmostEqual(self.d("value-per-share"), self.expected_value(self.d("wacc"), 0.025, (1, 2, 3), method=1), places=8)
        wacc_row = self.valuation.row_of["grid-2"] - 1
        self.assertAlmostEqual(self.sheets.value("DCF", wacc_row, 4), self.d("value-per-share"), places=8)
        self.assertAlmostEqual(self.sheets.value("DCF", wacc_row - 1, 2),
                               self.expected_value(self.d("wacc") - 0.01, 0.015, (1, 2, 3), method=1), places=8)

    def test_with_no_growth_the_other_method_needs_no_investment(self):
        self.type_into("terminal-method", 1)
        self.type_into("terminal-growth", 0.0)
        self.assertAlmostEqual(self.d("terminal-fcf"), self.d("last-year-nopat"), places=6)

    def test_cash_flows_in_the_middle_of_the_period_are_discounted_half_a_period_less(self):
        self.type_into("mid-period", 1)
        self.assertEqual([self.d("years-to-cash", i) for i in (3, 4, 5)], [0.5, 1.5, 2.5])
        self.assertAlmostEqual(self.d("value-per-share"), self.expected_value(self.d("wacc"), 0.025, (0.5, 1.5, 2.5)), places=8)


class TestTheSharePrice(DcfTestCase):

    def test_without_a_price_the_weight_of_debt_is_a_guess_and_there_is_no_comparison(self):
        self.use(build())
        self.assertAlmostEqual(self.d("debt-weight"), 0.2)
        self.assertNotIn("against-price", self.valuation.row_of)
        self.assertNotIn("share-price", self.valuation.row_of)

    def test_with_a_price_the_weight_of_debt_is_the_debt_over_the_debt_and_the_market_value_of_the_shares(self):
        model = build()
        model.share_price = 50.0
        self.use(model)
        last = model.history_count - 1
        debt = self.v("Balance Sheet", "current-debt", last) + self.v("Balance Sheet", "long-term-debt", last)
        market = 50.0 * self.v("Income Statement", "shares", last)
        self.assertAlmostEqual(self.d("market-value"), market)
        self.assertAlmostEqual(self.d("debt-weight"), debt / (debt + market))
        self.assertAlmostEqual(self.d("against-price"), self.d("value-per-share") / 50.0 - 1)


class TestQuarters(DcfTestCase):

    def setUp(self):
        super().setUp()
        self.use(build(period="quarterly", history=6, forecast=8))

    def test_the_years_count_quarters_of_a_year(self):
        self.assertAlmostEqual(self.d("years-to-end", 6), 91.25 / 365)
        self.assertAlmostEqual(self.d("years-to-end", 13), 2.0)

    def test_the_terminal_value_is_of_the_last_four_quarters_as_the_year(self):
        flows = [self.d("fcf", i) for i in range(10, 14)]
        self.assertAlmostEqual(self.d("last-year-fcf"), sum(flows), places=6)
        self.assertAlmostEqual(self.d("terminal-fcf"), sum(flows) * 1.025, places=6)

    def test_the_other_terminal_method_uses_the_last_four_quarters_operating_income(self):
        self.type_into("terminal-method", 1)
        years = [(k + 1) * 91.25 / 365 for k in range(8)]
        self.assertAlmostEqual(self.d("value-per-share"),
                               self.expected_value(self.d("wacc"), 0.025, years, ppy=4, method=1), places=8)

    def test_the_value_is_the_cash_flows_discounted_over_the_quarters_years(self):
        years = [(k + 1) * 91.25 / 365 for k in range(8)]
        self.assertAlmostEqual(self.d("value-per-share"), self.expected_value(self.d("wacc"), 0.025, years, ppy=4), places=8)

    def test_the_multiple_uses_the_last_four_quarters_too(self):
        ebitda = sum(self.v("Income Statement", "operating-income", i) + self.v("Cash Flow", "depreciation", i)
                     + self.v("Cash Flow", "amortization", i) for i in range(10, 14))
        self.assertAlmostEqual(self.d("terminal-multiple"), self.d("terminal-value") / ebitda)


class TestWhereThereIsNoTab(LispTestCase):

    def test_a_bank_and_an_insurer_have_no_dcf_tab_and_the_notes_say_why(self):
        for facts, kind in ((bank_facts(), "bank"), (insurer_facts(), "insurer")):
            model = build_kind(facts, kind)
            self.assertNotIn("DCF", [t["name"] for t in model.sheets()])
            self.assertIn("No DCF tab", model.sources_for_notes())

    def test_a_forecast_of_less_than_a_year_has_none(self):
        model = build(period="quarterly", history=6, forecast=3)
        self.assertNotIn("DCF", [t["name"] for t in model.sheets()])
        self.assertIn("The forecast is shorter than a year, which is too short to value a company by.",
                      model.sources_for_notes())

    def test_an_asset_manager_has_one(self):
        from test_financial_asset_manager import build as build_asset_manager
        model = build_asset_manager()
        self.assertIn("DCF", [t["name"] for t in model.sheets()])


class TestTheNotes(DcfTestCase):

    def test_the_notes_explain_the_tab(self):
        self.use(build())
        notes = self.model.sources_for_notes()
        self.assertIn("The DCF tab", notes)
        self.assertTrue(any("placeholders" in line for line in notes))
        self.assertTrue(any("share price was not given" in line for line in notes))


class TestTheBuiltin(LispTestCase):

    def setUp(self):
        super().setUp()
        lisp_sec._parsed_facts.clear()
        self.addCleanup(lisp_sec._parsed_facts.clear)
        from test_financial_model import made_up_facts
        facts = made_up_facts()
        self.written = []
        for patcher in (mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: facts),
                        mock.patch.object(lisp_google, "google_workbook",
                                          lambda creds, title, sheets: self.written.append((title, sheets)) or "https://sheet")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def test_price_is_the_share_price_for_the_dcf_tab(self):
        self.run_lisp('(three-statement-model creds "ABC" :segments #f :price 42.5)')
        tabs = self.written[0][1]
        sheets = Sheets(tabs)
        dcf = next(tab for tab in tabs if tab["name"] == "DCF")
        row = next(i for i, cells in enumerate(dcf["cells"]) if cells[0] and cells[0][0] == "Share price, today")
        self.assertEqual(sheets.value("DCF", row, 1), 42.5)

    def test_a_price_must_be_a_positive_number(self):
        self.assertLispError('(three-statement-model creds "ABC" :price 0)', "positive number")
        self.assertLispError('(three-statement-model creds "ABC" :price "high")', "positive number")
