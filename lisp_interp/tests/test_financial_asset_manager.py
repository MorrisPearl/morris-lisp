"""The asset manager model (lisp_financial_asset_manager.py): ABC Inc.'s made-up facts, with assets under
management given, and a fake Google -- no network. sheet_formulas.py works out the formulas as Google would."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_financial_asset_manager as asset_manager
import lisp_financial_model as fm
import lisp_google
import lisp_sec
from sheet_formulas import Sheets
from test_financial_bank_insurer import ModelTestCase, company_facts, bank_facts
from test_financial_model import made_up_facts, changed_facts, evaluated, value, set_input

AUM = [5000.0, 5500.0, 6050.0]               # billions, the end of 2021, 2022, 2023 (10% a year, as revenue)


def build(aum=AUM, period="annual", history=3, forecast=3, facts=None):
    facts = facts or made_up_facts(quarterly=period == "quarterly")
    return fm.build_model(facts, "ABC", period, history, forecast, "test", None, "asset-manager", aum)


class TestAssetManagerModel(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(build())

    def test_the_history_has_the_aum_growth_and_the_fee_rate_worked_out(self):
        self.assertAlmostEqual(self.v("Assumptions", "aum", 1), 5500)
        self.assertAlmostEqual(self.v("Assumptions", "aum-growth", 1), 0.10)
        self.assertAlmostEqual(self.v("Assumptions", "fee-rate", 1), 1100 * 10 / 5250)       # basis points of the average AUM
        self.assertAlmostEqual(self.v("Assumptions", "fee-rate", 2), 1210 * 10 / 5775)
        row = self.model.layouts["Assumptions"].row_of["fee-rate"]
        self.assertIsNone(self.model.sheets()[0]["cells"][row - 1][1])          # (none for the first, with no average)

    def test_the_aum_is_typed_in_blue_for_the_periods_reported_and_a_formula_after(self):
        cells = self.model.sheets()[0]["cells"][self.model.layouts["Assumptions"].row_of["aum"] - 1]
        self.assertEqual(cells[1][0], 5000.0)
        self.assertIn("data", cells[1][1])
        self.assertTrue(cells[4][0].startswith("="))

    def test_the_forecast_aum_grows_at_the_assumed_rate_and_revenue_is_the_fee_rate_on_the_average(self):
        self.assertAlmostEqual(self.v("Assumptions", "aum-growth", 3), 0.10)
        self.assertAlmostEqual(self.v("Assumptions", "aum", 3), 6050 * 1.1)
        fee = self.v("Assumptions", "fee-rate", 3)
        self.assertAlmostEqual(fee, 1210 * 10 / 5775)
        self.assertAlmostEqual(self.v("Income Statement", "revenue", 3), fee * (6050 + 6050 * 1.1) / 2 / 10)
        # the growth of revenue is a result, in every period
        self.assertAlmostEqual(self.v("Assumptions", "growth", 3),
                               self.v("Income Statement", "revenue", 3) / 1210 - 1)

    def test_reported_revenue_is_the_companys(self):
        for i, grow in enumerate((1.0, 1.1, 1.21)):
            self.assertAlmostEqual(self.v("Income Statement", "revenue", i), 1000 * grow)

    def test_costs_follow_revenue_and_everything_balances(self):
        revenue = self.v("Income Statement", "revenue", 3)
        self.assertAlmostEqual(self.v("Income Statement", "other-operating", 3),
                               revenue * self.v("Assumptions", "other-operating-percent", 3))
        for i in range(6):
            self.assertAlmostEqual(self.v("Balance Sheet", "check", i), 0, places=6)
        self.assertNoCircularFormulas()

    def assertNoCircularFormulas(self):
        for tab in ("Assumptions", "Income Statement", "Balance Sheet", "Cash Flow"):
            for (row, column) in list(self.sheets.cells[tab]):
                self.sheets.value(tab, row, column)

    def test_changing_the_aum_growth_or_the_fee_rate_changes_revenue_and_it_still_balances(self):
        set_input(self.sheets, self.model, "Assumptions", "aum-growth", 3, 0.30)
        set_input(self.sheets, self.model, "Assumptions", "fee-rate", 4, 10.0)
        self.assertAlmostEqual(self.v("Assumptions", "aum", 3), 6050 * 1.3)
        self.assertAlmostEqual(self.v("Assumptions", "aum", 4), 6050 * 1.3 * 1.3)       # (the growth goes on, being the period before's)
        self.assertAlmostEqual(self.v("Income Statement", "revenue", 4), 10.0 * (6050 * 1.3 + 6050 * 1.3 * 1.3) / 2 / 10)
        for i in range(6):
            self.assertAlmostEqual(self.v("Balance Sheet", "check", i), 0, places=6)

    def test_a_correction_to_the_reported_aum_flows_through_the_fee_rate(self):
        set_input(self.sheets, self.model, "Assumptions", "aum", 1, 6000.0)
        self.assertAlmostEqual(self.v("Assumptions", "aum-growth", 1), 0.2)
        self.assertAlmostEqual(self.v("Assumptions", "fee-rate", 1), 1100 * 10 / 5500)

    def test_the_notes_say_where_the_aum_came_from_and_the_sheet_says_its_units(self):
        notes = "\n".join(self.model.sources_for_notes())
        self.assertIn("The AUM is not in the SEC's data: it was given to the program (:aum)", notes)
        self.assertIn("assets under management in billions", self.model.sheets()[1]["cells"][1][0][0])

    def test_quarters_use_a_quarter_of_a_years_fee(self):
        aum = [5000.0, 5100.0, 5200.0, 5300.0, 5400.0, 5500.0]
        self.use(build(aum, "quarterly", 6, 2))
        for i in range(8):
            self.assertAlmostEqual(self.v("Balance Sheet", "check", i), 0, places=6)
        fee = self.v("Assumptions", "fee-rate", 6)
        self.assertAlmostEqual(self.v("Income Statement", "revenue", 6),
                               fee * (self.v("Assumptions", "aum", 5) + self.v("Assumptions", "aum", 6)) / 2 / 10 * 91.25 / 365)
        # the rate is a year's: the reported quarter's revenue, over the average AUM, times four
        self.assertAlmostEqual(self.v("Assumptions", "fee-rate", 5),
                               self.v("Income Statement", "revenue", 5) * 10 / ((5400 + 5500) / 2) * 4)


class TestAssetsUnderManagementGiven(LispTestCase):

    def test_without_them_the_model_cannot_be_built_and_says_how_to_give_them(self):
        with self.assertRaises(fm.MissingLines) as caught:
            build(aum=None)
        self.assertIn("needs the assets under management at the end of each period", str(caught.exception))
        self.assertIn(":aum", str(caught.exception))

    def test_the_sec_facts_will_do_if_they_have_them_for_every_period(self):
        facts = changed_facts(add={"AssetsUnderManagementCarryingAmount": ("balance", lambda g: 5e6 * g)})
        model = build(aum=None, facts=facts)
        self.assertEqual(model.h.aum[0], 5000.0)
        self.assertAlmostEqual(model.h.aum[2], 5000 * 1.21)

    def test_fewer_than_the_periods_leave_the_older_ones_out_and_the_notes_say_so(self):
        model = build(aum=[5500.0, 6050.0])
        self.assertEqual(model.labels[:2], ["FY2022", "FY2023"])
        self.assertEqual(model.h.aum, [5500.0, 6050.0])
        self.assertIn("The history starts at 2022-12-31 because the assets under management were given from then.", model.kind_note)

    def test_more_than_the_periods_use_the_latest(self):
        model = build(aum=[1.0, 2.0] + AUM)
        self.assertEqual(model.h.aum, AUM)

    def test_one_period_is_too_few(self):
        with self.assertRaises(fm.LispError) as caught:
            build(aum=[6050.0])
        self.assertIn("growth needs at least 2", str(caught.exception))

    def test_a_list_of_numbers_is_needed(self):
        for bad in ("(1 2 \"x\")", "5000", "()", "(1 #t)"):
            with self.assertRaises(fm.LispError):
                asset_manager.number_list(self.eval_lisp(bad), "test")
        self.assertEqual(asset_manager.number_list(self.eval_lisp("(5000 5500.5)"), "test"), [5000.0, 5500.5])
        self.assertEqual(asset_manager.number_list(self.eval_lisp("#(1 2)"), "test"), [1.0, 2.0])

    def eval_lisp(self, text):
        return self.run_lisp("'" + text if text.startswith("(") else text)


class TestChoosingAnAssetManager(LispTestCase):

    def setUp(self):
        super().setUp()
        self.written = []
        self.industry = (6211, "Security Brokers, Dealers & Flotation Companies")
        for patcher in (mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: made_up_facts()),
                        mock.patch.object(fm, "company_industry", lambda creds, company, who: self.industry),
                        mock.patch.object(lisp_google, "google_workbook",
                                          lambda creds, title, sheets: self.written.append((title, sheets)) or "https://sheet")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def labels(self, tab=1):
        return [cells[0][0] for cells in self.written[-1][1][tab]["cells"] if cells and cells[0]]

    def test_giving_the_aum_makes_it_an_asset_manager_whatever_the_industry_code(self):
        self.run_lisp('(three-statement-model creds "ABC" :aum (list 5000 5500 6050) :segments #f)')
        self.assertIn("Revenue (fees on average assets under management)", self.labels())
        self.assertIn("Assets under management at the end of the period, billions", self.labels(0))

    def test_an_investment_adviser_without_the_aum_is_an_ordinary_company_and_the_notes_say_how_to_give_it(self):
        self.industry = (6282, "Investment Advice")
        self.run_lisp('(three-statement-model creds "ABC" :segments #f)')
        self.assertIn("Gross profit", self.labels())
        notes = "\n".join(self.labels(4))
        self.assertIn("The SEC classifies this company as Investment Advice, but it is modeled as an ordinary company because "
                      "a model of an asset manager needs the assets under management", notes)
        self.assertIn("give them with :aum", notes)

    def test_an_investment_adviser_with_the_aum_is_an_asset_manager(self):
        self.industry = (6282, "Investment Advice")
        self.run_lisp('(three-statement-model creds "ABC" :aum (list 5000 5500 6050))')
        self.assertIn("Revenue (fees on average assets under management)", self.labels())

    def test_asking_for_the_kind_without_the_aum_is_an_error(self):
        self.assertLispError('(three-statement-model creds "ABC" :kind "asset-manager")', "needs the assets under management")

    def test_the_aum_is_for_asset_managers_only(self):
        self.assertLispError('(three-statement-model creds "ABC" :kind "bank" :aum (list 1 2 3))', ":aum, the assets under management, is for")

    def test_an_unknown_kind_lists_the_kinds(self):
        self.assertLispError('(three-statement-model creds "ABC" :kind "airline")', '"insurer", "asset-manager"')

    def test_bad_aum_is_an_error(self):
        self.assertLispError('(three-statement-model creds "ABC" :aum "lots")', ":aum is a list of numbers")


class TestPlantNeverBelowZero(LispTestCase):

    def test_depreciation_is_never_more_than_the_plant_and_the_capital_spending_there_is_to_depreciate(self):
        # a company whose depreciation includes amortization it does not report apart: 40 a year on plant of 30
        facts = changed_facts(remove=["PropertyPlantAndEquipmentNet", "PaymentsToAcquirePropertyPlantAndEquipment"],
                              add={"PropertyPlantAndEquipmentNet": ("balance", lambda g: 30.0),
                                   "PaymentsToAcquirePropertyPlantAndEquipment": ("flow", lambda g: 2.0)})
        model = fm.build_model(facts, "ABC", "annual", 3, 4, "test", None)
        sheets = evaluated(model)
        for i in range(3, 7):
            self.assertGreaterEqual(value(sheets, model, "Balance Sheet", "property-plant-equipment", i), -1e-9)
            self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "check", i), 0, places=6)
        self.assertAlmostEqual(value(sheets, model, "Balance Sheet", "property-plant-equipment", 6), 0, places=6)
