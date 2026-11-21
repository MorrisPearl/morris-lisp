"""What the valuation tabs say beyond the value: returns on invested capital, economic profit, and the growth the share
price implies (the DCF tab); the options market's range for the price (:volatility); an insurer's Valuation tab and
its reserve development and book value; an asset manager's net flows (:flows); and the market's multiples in
compare-companies (:prices). Made-up companies, no network; sheet_formulas.py works out the formulas."""

import math

from support import *  # noqa: F401,F403 -- the interpreter's modules, mock, and LispTestCase

import lisp_financial_dcf
import lisp_financial_equity_valuation as equity_valuation
import lisp_financial_model as fm
import lisp_sec
from sheet_formulas import Sheets
from test_financial_asset_manager import AUM
from test_financial_bank_insurer import ModelTestCase, insurer_facts, company_facts, INSURER_FLOWS, INSURER_BALANCES
from test_financial_dcf import DcfTestCase
from test_financial_model import build, made_up_facts

PRICE, VOLATILITY = 40.0, 0.3


def build_with_price(price=PRICE, volatility=None):
    model = fm.build_model(made_up_facts(), "ABC", "annual", 3, 3, "test", None, price=price)
    model.share_volatility = volatility
    return model


class TestReturnsOnInvestedCapital(DcfTestCase):

    def setUp(self):
        super().setUp()
        self.use(build())

    def test_roic_and_economic_profit_are_on_the_invested_capital_at_the_start(self):
        wacc = self.d("wacc")
        for i in (1, 2, 4):
            nopat = self.d("nopat", i)
            start = self.invested_capital(i - 1)
            self.assertAlmostEqual(self.d("invested-capital-of-period", i), self.invested_capital(i))
            self.assertAlmostEqual(self.d("roic", i), nopat / start)
            self.assertAlmostEqual(self.d("economic-profit", i), nopat - wacc * start)
            net_investment = self.invested_capital(i) - start
            self.assertAlmostEqual(self.d("net-investment", i), net_investment)
            self.assertAlmostEqual(self.d("reinvestment-rate", i), net_investment / nopat)
            self.assertAlmostEqual(self.d("reinvestment-growth", i), nopat / start * net_investment / nopat)

    def test_the_incremental_margin_is_over_a_year(self):
        for i in (1, 4):
            self.assertAlmostEqual(self.d("incremental-margin", i), (
                self.v("Income Statement", "operating-income", i) - self.v("Income Statement", "operating-income", i - 1)) / (
                self.v("Income Statement", "revenue", i) - self.v("Income Statement", "revenue", i - 1)))

    def test_the_last_years_return_and_the_reinvestment_the_terminal_growth_needs(self):
        last = self.model.count - 1
        roic = self.d("nopat", last) / self.invested_capital(last - 1)
        self.assertAlmostEqual(self.d("last-year-roic"), roic)
        self.assertAlmostEqual(self.d("needed-reinvestment"), self.d("terminal-growth") / roic)
        self.assertAlmostEqual(self.d("last-year-reinvestment"), self.d("net-investment", last) / self.d("nopat", last))


class TestWhatThePriceImplies(DcfTestCase):

    def setUp(self):
        super().setUp()
        self.use(build_with_price())

    def test_the_implied_terminal_growth_gives_back_the_price(self):
        for method in (0, 1):
            self.type_into("terminal-method", method)
            implied = self.d("implied-terminal-growth")
            self.type_into("terminal-growth", implied)
            self.assertAlmostEqual(self.d("value-per-share"), PRICE, places=6)
            self.sheets = Sheets(self.model.sheets())               # (as it was)

    def test_the_steady_growth_values_the_last_years_cash_flow_at_the_price(self):
        growth, wacc = self.d("implied-steady-growth"), self.d("wacc")
        flow = self.d("reported-year-fcf")
        self.assertAlmostEqual(flow, self.d("fcf", self.model.history_count - 1))
        self.assertAlmostEqual(flow * (1 + growth) / (wacc - growth), self.d("price-enterprise-value"), places=4)

    def test_without_a_price_there_is_no_such_section(self):
        self.assertNotIn("implied-terminal-growth", lisp_financial_dcf.Valuation(build()).row_of)


class TestTheOptionsMarketsRange(DcfTestCase):

    def test_the_range_is_the_price_times_e_to_the_volatility_either_way(self):
        self.use(build_with_price(volatility=VOLATILITY))
        self.assertAlmostEqual(self.d("price-low"), PRICE * math.exp(-VOLATILITY))
        self.assertAlmostEqual(self.d("price-high"), PRICE * math.exp(VOLATILITY))
        self.assertAlmostEqual(self.d("value-in-deviations"), math.log(self.d("value-per-share") / PRICE) / VOLATILITY)

    def test_without_the_volatility_there_is_no_range(self):
        self.assertNotIn("price-low", lisp_financial_dcf.Valuation(build_with_price()).row_of)

    def test_the_option_needs_a_price_and_a_sensible_number(self):
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")
        with mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: made_up_facts()), \
                mock.patch.object(fm, "company_industry", lambda creds, company, who: (3571, "Computers")):
            self.assertLispError('(three-statement-model creds "ABC" :volatility 0.3)', ":volatility goes with :price")
            self.assertLispError('(three-statement-model creds "ABC" :price 40 :volatility 30)',
                                 ":volatility is the implied volatility")


# ---------------------------------------------------------------------------
# An insurer
# ---------------------------------------------------------------------------

def insurer_with_development(development=lambda year: 15.0):
    flows = dict(INSURER_FLOWS, LiabilityForUnpaidClaimsAndClaimsAdjustmentExpenseIncurredClaimsPriorYears=development)
    return company_facts("ABC Insurance", flows, INSURER_BALANCES)


class TestAnInsurer(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(fm.build_model(insurer_with_development(), "ABC", "annual", 3, 3, "test", None, "insurer", price=50.0))

    def named(self, key):
        tab, address = self.sheets.names[self.model.range_names[(fm.DCF, key)]]
        return self.sheets.at(tab, address)

    def test_it_has_a_valuation_tab_and_every_formula_works(self):
        names = [tab["name"] for tab in self.model.sheets()]
        self.assertIn("Valuation", names)
        for tab in self.model.sheets():
            for (row, column) in list(self.sheets.cells[tab["name"]]):
                self.sheets.value(tab["name"], row, column)

    def test_the_value_is_tangible_book_plus_the_excess_returns(self):
        cost, growth = self.named("cost-of-equity"), self.named("terminal-growth")
        self.assertAlmostEqual(cost, 0.045 + equity_valuation.InsurerValuation.BETA * 0.05)
        book = [self.v("Balance Sheet", "tangible-book-value", i) for i in range(6)]
        income = [self.v("Income Statement", "net-income", i) for i in range(6)]
        value = book[2]
        for years, i in enumerate(range(3, 6), start=1):
            value += (income[i] - cost * book[i - 1]) / (1 + cost) ** years
        after = income[5] / book[4]
        value += (after - cost) * book[5] / (cost - growth) / (1 + cost) ** 3
        self.assertAlmostEqual(self.named("equity-value"), value, places=6)

    def test_tangible_book_value_and_book_value_per_share(self):
        for i in (2, 4):
            equity = self.v("Balance Sheet", "equity", i)
            self.assertAlmostEqual(self.v("Balance Sheet", "tangible-book-value", i),
                                   equity - self.v("Balance Sheet", "goodwill", i) - self.v("Balance Sheet", "intangible-assets", i))
            per_share = equity / self.v("Income Statement", "shares", i)
            self.assertAlmostEqual(self.v("Balance Sheet", "book-value-per-share", i), per_share)
            before = self.v("Balance Sheet", "equity", i - 1) / self.v("Income Statement", "shares", i - 1)
            self.assertAlmostEqual(self.v("Balance Sheet", "book-value-growth", i), per_share / before - 1)

    def test_the_reserve_development_as_reported_and_as_points_of_premiums(self):
        self.assertAlmostEqual(self.v("Income Statement", "reserve-development", 2), 15.0)
        self.assertAlmostEqual(self.v("Income Statement", "reserve-development-percent", 2),
                               15.0 / self.v("Income Statement", "premiums-earned", 2))
        row = self.model.layouts["Income Statement"].row_of["reserve-development"]
        self.assertNotIn((row - 1, 4), self.sheets.cells["Income Statement"])          # (none in the forecast)

    def test_without_it_there_are_no_such_lines(self):
        model = fm.build_model(insurer_facts(), "ABC", "annual", 3, 3, "test", None, "insurer")
        self.assertNotIn("reserve-development", model.layouts["Income Statement"].row_of)

    def test_the_notes_say_how(self):
        notes = self.model.sources_for_notes()
        self.assertIn("The Valuation tab", notes)
        self.assertTrue(any(line.startswith("An insurer's reserves and float are its raw material") for line in notes))


# ---------------------------------------------------------------------------
# An asset manager's flows
# ---------------------------------------------------------------------------

FLOWS = [40.0, -30.0, 25.0]


class TestNetFlows(ModelTestCase):

    def setUp(self):
        super().setUp()
        self.use(fm.build_model(made_up_facts(), "ABC", "annual", 3, 3, "test", None, "asset-manager", AUM, flows=FLOWS))

    def a(self, key, i):
        return self.v("Assumptions", key, i)

    def test_organic_growth_and_the_market_split_the_growth_of_aum(self):
        for i in (1, 2):
            organic = FLOWS[i] / AUM[i - 1]
            self.assertAlmostEqual(self.a("flows", i), FLOWS[i])
            self.assertAlmostEqual(self.a("organic-growth", i), organic)
            self.assertAlmostEqual(self.a("market-return", i), AUM[i] / AUM[i - 1] - 1 - organic)
            self.assertAlmostEqual(self.a("aum-growth", i), AUM[i] / AUM[i - 1] - 1)

    def test_in_the_forecast_aum_grows_by_both_and_the_flows_follow(self):
        for i in (3, 4):
            growth = self.a("organic-growth", i) + self.a("market-return", i)
            self.assertAlmostEqual(self.a("aum-growth", i), growth)
            self.assertAlmostEqual(self.a("aum", i), self.a("aum", i - 1) * (1 + growth))
            self.assertAlmostEqual(self.a("flows", i), self.a("organic-growth", i) * self.a("aum", i - 1))
        self.assertBalances(6)

    def test_the_growth_of_aum_is_a_result_not_an_assumption(self):
        line = next(line for line in self.model.layouts["Assumptions"].lines if line is not None and line.key == "aum-growth")
        self.assertFalse(line.editable)

    def test_fewer_flows_than_periods_leave_the_earliest_without_one(self):
        model = fm.build_model(made_up_facts(), "ABC", "annual", 3, 3, "test", None, "asset-manager", AUM, flows=[25.0])
        self.assertEqual(model.h.flows, [None, None, 25.0])

    def test_flows_need_the_aum(self):
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")
        with mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: made_up_facts()), \
                mock.patch.object(fm, "company_industry", lambda creds, company, who: (6282, "Investment Advice")):
            self.assertLispError("(three-statement-model creds \"ABC\" :flows '(1 2 3))", ":flows, an asset manager's net flows, goes with :aum")
            self.assertLispError("(three-statement-model creds \"ABC\" :aum '(5000 5500 6050) :flows '(\"a\"))",
                                 ":flows is a list of numbers")
