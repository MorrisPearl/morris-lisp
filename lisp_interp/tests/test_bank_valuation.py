"""A bank model's tangible common equity, its interest rates that follow the federal funds rate, and its Valuation tab
(lisp_financial_bank.py, lisp_financial_equity_valuation.py): a made-up bank with goodwill, preferred stock, and minority
interests, made-up federal funds rates, and sheet_formulas.py to work the formulas out -- no network."""

import datetime

from support import *  # noqa: F401,F403 -- the interpreter's modules, mock, and LispTestCase

import lisp_financial_bank as bank
import lisp_financial_equity_valuation as bank_valuation
import lisp_financial_model as fm
import lisp_financial_sensitivity as sensitivity
import lisp_nyfed
import lisp_sec
from lisp_core import LispError
from sheet_formulas import split_address
from test_financial_bank_insurer import ModelTestCase, company_facts, BANK_FLOWS, BANK_BALANCES, bank_amounts
from test_financial_model import set_input

GOODWILL, INTANGIBLES, PREFERRED, MINORITY, PREFERRED_DIVIDENDS = 30.0, 10.0, 20.0, 5.0, 2.0
FED_FUNDS = [0.001, 0.017, 0.050]          # (the made-up bank's three years: 2021, 2022, 2023)


def bank_with_more_facts():
    """The made-up bank, with goodwill and intangibles, preferred stock and its dividends, and minority interests
    (its equity with them is its parent's plus MINORITY)."""
    flows = dict(BANK_FLOWS, PreferredStockDividendsIncomeStatementImpact=lambda year: PREFERRED_DIVIDENDS)
    balances = dict(BANK_BALANCES, Goodwill=lambda year: GOODWILL, IntangibleAssetsNetExcludingGoodwill=lambda year: INTANGIBLES,
                    PreferredStockValue=lambda year: PREFERRED,
                    StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=
                    lambda year: bank_amounts(year)["equity"] + MINORITY)
    balances["Liabilities"] = lambda year: bank_amounts(year)["assets"] - bank_amounts(year)["equity"] - MINORITY
    return company_facts("ABC Bank", flows, balances)


def build(fed_funds=FED_FUNDS, price=None, facts=None, forecast=3):
    find = None if fed_funds is None else (lambda periods: (list(fed_funds), ""))
    return fm.build_model(facts or bank_with_more_facts(), "ABC", "annual", 3, forecast, "test", None, "bank", price=price,
                          find_fed_funds=find)


class TestTangibleCommonEquity(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(build())

    def test_goodwill_and_intangibles_are_a_line_of_their_own_and_the_balance_sheet_still_balances(self):
        self.assertAlmostEqual(self.v("Balance Sheet", "goodwill-and-intangibles", 2), GOODWILL + INTANGIBLES)
        self.assertAlmostEqual(self.v("Balance Sheet", "goodwill-and-intangibles", 5), GOODWILL + INTANGIBLES)
        self.assertAlmostEqual(self.v("Balance Sheet", "total-assets", 2), bank_amounts(2023)["assets"])
        self.assertBalances(6)

    def test_tangible_common_equity_is_equity_less_preferred_minority_goodwill_and_intangibles(self):
        equity = bank_amounts(2023)["equity"] + MINORITY
        self.assertAlmostEqual(self.v("Balance Sheet", "preferred-and-minority", 2), PREFERRED + MINORITY)
        self.assertAlmostEqual(self.v("Balance Sheet", "tangible-common-equity", 2),
                               equity - PREFERRED - MINORITY - GOODWILL - INTANGIBLES)
        for i in range(3, 6):
            self.assertAlmostEqual(self.v("Balance Sheet", "tangible-common-equity", i),
                                   self.v("Balance Sheet", "equity", i) - PREFERRED - MINORITY - GOODWILL - INTANGIBLES)

    def test_net_income_to_common_shareholders_is_after_the_preferred_dividends_and_earnings_per_share_follow_it(self):
        for i in (2, 4):
            to_common = self.v("Income Statement", "net-income", i) - PREFERRED_DIVIDENDS
            self.assertAlmostEqual(self.v("Income Statement", "preferred-dividends", i), PREFERRED_DIVIDENDS)
            self.assertAlmostEqual(self.v("Income Statement", "income-to-common", i), to_common)
            self.assertAlmostEqual(self.v("Income Statement", "eps", i), to_common / self.v("Income Statement", "shares", i))

    def test_the_return_on_tangible_common_equity_is_on_the_average_of_the_year(self):
        start, end = (self.v("Balance Sheet", "tangible-common-equity", i) for i in (1, 2))
        self.assertAlmostEqual(self.v("Income Statement", "return-on-tangible-equity", 2),
                               self.v("Income Statement", "income-to-common", 2) / ((start + end) / 2))

    def test_the_preferred_dividends_are_what_is_left_of_net_income_if_only_that_is_reported(self):
        flows = dict(BANK_FLOWS, NetIncomeLossAvailableToCommonStockholdersBasic=lambda year: bank_amounts(year)["net_income"] - 3)
        self.use(build(facts=company_facts("ABC Bank", flows, BANK_BALANCES)))
        self.assertAlmostEqual(self.v("Income Statement", "preferred-dividends", 2), 3.0)
        self.assertAlmostEqual(self.v("Balance Sheet", "preferred-and-minority", 2), 0.0)


class TestRatesThatFollowTheFed(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(build())

    def rate(self, key, i):
        return self.v("Assumptions", key, i)

    def test_the_federal_funds_rate_is_the_history_and_then_held(self):
        for i, rate in enumerate(FED_FUNDS):
            self.assertAlmostEqual(self.rate("fed-funds", i), rate)
        for i in range(3, 6):
            self.assertAlmostEqual(self.rate("fed-funds", i), FED_FUNDS[-1])

    def test_a_beta_is_how_much_the_rate_moved_over_how_much_the_feds_did(self):
        for rate_key, beta_key, _, _ in bank.RATE_BETAS:
            moved = (self.rate(rate_key, 2) - self.rate(rate_key, 1)) / (FED_FUNDS[2] - FED_FUNDS[1])
            expected = min(max(moved, bank.BETA_LIMITS[0]), bank.BETA_LIMITS[1])
            self.assertAlmostEqual(self.rate(beta_key, 3), expected, msg=beta_key)
            self.assertAlmostEqual(self.rate(beta_key, 5), expected, msg=beta_key)

    def test_with_the_feds_rate_held_the_rates_stay_the_last_periods(self):
        for rate_key, _, _, _ in bank.RATE_BETAS:
            for i in range(3, 6):
                self.assertAlmostEqual(self.rate(rate_key, i), self.rate(rate_key, 2), msg=rate_key)

    def test_a_cut_moves_each_rate_by_its_beta(self):
        set_input(self.sheets, self.model, "Assumptions", "fed-funds", 4, 0.03)      # (a cut of 2 points in the second year)
        for rate_key, beta_key, _, _ in bank.RATE_BETAS:
            beta = self.rate(beta_key, 4)
            self.assertAlmostEqual(self.rate(rate_key, 4), max(self.rate(rate_key, 3) - 0.02 * beta, 0), msg=rate_key)
            self.assertAlmostEqual(self.rate(rate_key, 5), self.rate(rate_key, 4), msg=rate_key)    # (held after)
        self.assertBalances(6)

    def test_a_rate_never_goes_below_zero(self):
        set_input(self.sheets, self.model, "Assumptions", "deposit-beta", 3, 1.0)
        set_input(self.sheets, self.model, "Assumptions", "fed-funds", 3, -0.50)
        self.assertEqual(self.rate("deposit-cost", 3), 0)

    def test_without_a_move_of_the_feds_rate_the_betas_are_typical_figures(self):
        self.use(build(fed_funds=[0.02, 0.021, 0.022]))
        for _, beta_key, _, typical in bank.RATE_BETAS:
            self.assertEqual(self.rate(beta_key, 3), typical)
        self.assertIn("typical figures", self.model.layouts["Assumptions"].lines[
            self.model.layouts["Assumptions"].row_of["betas-header"] - fm.FIRST_LINE_ROW].label)

    def test_without_the_federal_funds_rate_the_rates_are_as_before(self):
        self.use(build(fed_funds=None))
        self.assertNotIn("fed-funds", self.model.layouts["Assumptions"].row_of)
        self.assertNotIn("deposit-beta", self.model.layouts["Assumptions"].row_of)
        self.assertBalances(6)


class TestTheRateCycle(LispTestCase):

    def test_the_biggest_move_from_the_second_period(self):
        self.assertEqual(bank.rate_cycle([0.001, 0.002, 0.017, 0.05, 0.051, 0.04]), (1, 4))

    def test_a_fall_counts_too(self):
        self.assertEqual(bank.rate_cycle([0.05, 0.053, 0.045, 0.036, 0.0362]), (1, 4))

    def test_too_small_a_move_is_none(self):
        self.assertIsNone(bank.rate_cycle([0.04, 0.043, 0.045, 0.04]))


class TestFindingTheFederalFundsRate(LispTestCase):

    def test_the_average_of_each_periods_days(self):
        days = {}
        day = datetime.date(2022, 1, 1)
        while day <= datetime.date(2023, 12, 31):
            days[day] = {"percentRate": 1.0 if day.year == 2022 else 4.0 + (day.month >= 7)}
            day += datetime.timedelta(days=1)
        asked = []

        def records(name, options, who):
            asked.append((name, options))
            return days
        periods = [lisp_sec.Period(datetime.date(2022, 12, 31), datetime.date(2022, 1, 1), None, 2022, "FY"),
                   lisp_sec.Period(datetime.date(2023, 12, 31), datetime.date(2023, 1, 1), None, 2023, "FY")]
        with mock.patch.object(lisp_nyfed, "rate_records", records):
            rates, note = fm.fed_funds_finder("test")(periods)
        self.assertEqual(asked[0][0], "EFFR")
        self.assertEqual(asked[0][1]["start-date"], "2021-12-31")
        self.assertAlmostEqual(rates[0], 0.01)
        self.assertAlmostEqual(rates[1], (4.0 * 181 + 5.0 * 184) / 365 / 100)
        self.assertEqual(note, "")

    def test_not_reaching_the_new_york_fed_is_a_note(self):
        def records(name, options, who):
            raise LispError("the network is down")
        periods = [lisp_sec.Period(datetime.date(2022, 12, 31), datetime.date(2022, 1, 1), None, 2022, "FY")]
        with mock.patch.object(lisp_nyfed, "rate_records", records):
            rates, note = fm.fed_funds_finder("test")(periods)
        self.assertIsNone(rates)
        self.assertIn("the network is down", note)


class TestTheValuationTab(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(build(price=12.0))
        self.tab = next(tab for tab in self.model.sheets() if tab["name"] == bank_valuation.TAB_NAME)

    def named(self, key):
        tab, address = self.sheets.names[self.model.range_names[(fm.DCF, key)]]
        return self.sheets.at(tab, address)

    def test_a_bank_has_it_in_place_of_a_dcf_and_the_sensitivity_tabs_after_it(self):
        names = [tab["name"] for tab in self.model.sheets()]
        self.assertNotIn("DCF", names)
        at = names.index("Valuation")
        self.assertEqual(names[at:at + 4], ["Valuation", "Sensitivity", "Distributions", "Sensitivity Macro"])

    def test_the_cost_of_equity_is_the_risk_free_rate_plus_beta_times_the_premium(self):
        self.assertAlmostEqual(self.named("cost-of-equity"), 0.045 + bank_valuation.BankValuation.BETA * 0.05)

    def test_the_value_is_tangible_book_plus_the_present_value_of_the_excess_returns(self):
        cost, growth = self.named("cost-of-equity"), self.named("terminal-growth")
        tangible = [self.v("Balance Sheet", "tangible-common-equity", i) for i in range(6)]
        income = [self.v("Income Statement", "income-to-common", i) for i in range(6)]
        value, years = tangible[2], 0.0
        for i in range(3, 6):
            years += 365 / 365
            value += (income[i] - cost * tangible[i - 1]) / (1 + cost) ** years
        after = income[5] / tangible[4]
        self.assertAlmostEqual(self.named("terminal-return"), after)
        value += (after - cost) * tangible[5] / (cost - growth) / (1 + cost) ** years
        self.assertAlmostEqual(self.named("equity-value"), value, places=6)
        shares = self.v("Income Statement", "shares", 2)
        self.assertAlmostEqual(self.named("value-per-share"), value / shares, places=6)
        self.assertAlmostEqual(self.named("tangible-book-per-share"), tangible[2] / shares)
        self.assertAlmostEqual(self.named("price-to-tangible-book"), value / tangible[2], places=6)

    def test_a_bank_earning_its_cost_of_equity_after_the_forecast_adds_nothing_after_it(self):
        tab, address = self.sheets.names[self.model.range_names[(fm.DCF, "terminal-return")]]
        self.sheets.cells[tab][split_address(address)] = self.named("cost-of-equity")
        self.sheets.worked_out.clear()
        self.assertAlmostEqual(self.named("present-terminal-value"), 0.0)

    def test_the_multiples_and_the_return_the_price_implies(self):
        cost, growth, after = self.named("cost-of-equity"), self.named("terminal-growth"), self.named("terminal-return")
        self.assertAlmostEqual(self.named("justified-multiple"), (after - growth) / (cost - growth))
        multiple = 12.0 / self.named("tangible-book-per-share")
        self.assertAlmostEqual(self.named("market-multiple"), multiple)
        self.assertAlmostEqual(self.named("implied-return"), growth + multiple * (cost - growth))
        eps = self.v("Income Statement", "income-to-common", 2) / self.v("Income Statement", "shares", 2)
        self.assertAlmostEqual(self.named("price-to-earnings"), 12.0 / eps)
        self.assertAlmostEqual(self.named("against-price"), self.named("value-per-share") / 12.0 - 1)

    def test_the_middle_of_the_last_table_is_the_value_per_share(self):
        row = next(r for r, cells in enumerate(self.tab["cells"]) if cells[0] and str(cells[0][0]).startswith("Value per share: cost"))
        middle = len(bank_valuation.COST_STEPS) // 2
        self.assertAlmostEqual(self.sheets.value("Valuation", row + 1 + middle, 2 + len(bank_valuation.RETURN_STEPS) // 2),
                               self.named("value-per-share"), places=6)

    def test_every_formula_works_out(self):
        for tab in self.model.sheets():
            for (row, column) in list(self.sheets.cells[tab["name"]]):
                self.sheets.value(tab["name"], row, column)

    def test_the_sensitivity_tab_draws_the_banks_inputs_and_records_its_results(self):
        inputs, outputs = sensitivity.model_setup(self.model)
        drawn = [entry[0] for entry in inputs]
        for key in ("beta", "risk-premium", "terminal-growth", "terminal-return"):
            self.assertIn(self.model.range_names[(fm.DCF, key)], drawn)
        for key in ("loan-growth", "efficiency", "fed-funds"):
            self.assertIn(self.model.range_names[(fm.ASSUMPTIONS, key)], drawn)
        self.assertIn("Equity beta (Valuation tab)", [entry[6] for entry in inputs])
        recorded = [name for name, _ in outputs]
        for key in ("equity-value", "value-per-share", "price-to-tangible-book", "against-price"):
            self.assertIn(self.model.range_names[(fm.DCF, key)], recorded)

    def test_the_notes_explain_it(self):
        notes = self.model.sources_for_notes()
        self.assertIn("The Valuation tab", notes)
        self.assertTrue(any(line.startswith("Price to tangible book value is how banks and insurers are priced") for line in notes))

    def test_a_forecast_shorter_than_a_year_has_none(self):
        facts = company_facts("ABC Bank", BANK_FLOWS, BANK_BALANCES, quarterly=True)
        model = fm.build_model(facts, "ABC", "quarterly", 6, 3, "test", None, "bank")
        self.assertNotIn("Valuation", [tab["name"] for tab in model.sheets()])
        self.assertIn("The forecast is shorter than a year, which is too short to value a company by.",
                      model.sources_for_notes())
