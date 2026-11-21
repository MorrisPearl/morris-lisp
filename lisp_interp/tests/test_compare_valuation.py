"""The valuation rows at the bottom of a compare-companies sheet (lisp_financial_compare_valuation.py), where their share
prices come from, analysts' estimates, and peers chosen from the table ticker_industry (lisp_financial_peers.py): made-up
companies, a made-up database, the SEC and Google faked -- no network. sheet_formulas.py works out the formulas."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_alpha_vantage
import lisp_financial_compare as fc
import lisp_financial_compare_valuation as valuation
import lisp_financial_peers as peers
from test_bank_valuation import bank_with_more_facts
from test_financial_bank_insurer import insurer_facts
from test_financial_compare import CompareTestCase, scaled
from test_financial_model import made_up_facts


class ValuationTestCase(CompareTestCase):

    def tab(self, name="Comparison"):
        return self.worked()[1][name]

    def value(self, label, column, tab="Comparison", exact=True):
        """The number in a column (B is 1) of the row with this label (or beginning with it, if not `exact`)."""
        _, cells, sheets = self.worked()
        for n, row in enumerate(cells[tab]):
            text = str(row[0][0]) if row and row[0] else ""
            if text == label or (not exact and text.startswith(label)):
                return sheets.value(tab, n, column)
        raise AssertionError("no row called %s" % label)

    def labels(self, tab="Comparison"):
        return [str(row[0][0]) for row in self.tab(tab) if row and row[0]]


# ---------------------------------------------------------------------------
# The rows of each kind
# ---------------------------------------------------------------------------

class TestAnOrdinaryCompanysValuation(ValuationTestCase):

    PRICES = (40.0, 90.0)

    def setUp(self):
        super().setUp()
        self.add("ABC", made_up_facts())
        self.add("BIG", scaled(made_up_facts(), 2.0, "Big Co"))
        self.compare(["ABC", "BIG"], ":prices '(40 90)")

    def v(self, label, column):
        return self.value(label, column)

    def test_the_valuation_is_at_the_bottom_below_the_ratios(self):
        labels = self.labels()
        self.assertGreater(labels.index("Valuation (at the share prices given)"), labels.index("Ratios"))
        self.assertEqual(labels[-1], "PEG: price / earnings, over the growth of earnings per share in points (under 1 is "
                                     "cheap for the growth)")

    def test_market_value_and_enterprise_value(self):
        for column, price in ((1, 40.0), (2, 90.0)):
            market = price * self.v("Diluted shares, millions", column)
            self.assertAlmostEqual(self.value("Market value of the shares", column, exact=False), market)
            debt = self.v("Current debt", column) + self.v("Long-term debt", column)
            cash = self.v("Cash and equivalents", column) + self.v("Short-term investments", column)
            self.assertAlmostEqual(self.value("Enterprise value, millions", column, exact=False), market + debt - cash)

    def test_the_enterprise_multiples(self):
        for column in (1, 2):
            enterprise = self.value("Enterprise value, millions", column, exact=False)
            operating = self.v("Operating income", column)
            ebitda = operating + self.v("Depreciation (and amortization, if not reported apart)", column) \
                + self.v("Amortization of intangible assets", column)
            free_cash_flow = self.v("Cash from operations", column) + self.v("Capital expenditures", column)
            self.assertAlmostEqual(self.value("Enterprise value / a year's EBITDA", column, exact=False), enterprise / ebitda)
            self.assertAlmostEqual(self.value("Enterprise value / a year's operating income", column, exact=False),
                                   enterprise / operating)
            self.assertAlmostEqual(self.value("Enterprise value / a year's revenue", column, exact=False),
                                   enterprise / self.v("Revenue", column))
            self.assertAlmostEqual(self.value("Enterprise value / a year's free cash flow", column, exact=False),
                                   enterprise / free_cash_flow)

    def test_the_price_multiples_and_yields(self):
        for column, price in ((1, 40.0), (2, 90.0)):
            shares = self.v("Diluted shares, millions", column)
            market = price * shares
            eps = self.v("Earnings per share, diluted", column)
            net_income = self.v("Net income", column)
            cash_earnings = net_income + self.v("Depreciation (and amortization, if not reported apart)", column) \
                + self.v("Amortization of intangible assets", column)
            self.assertAlmostEqual(self.value("Price / sales", column, exact=False), market / self.v("Revenue", column))
            self.assertAlmostEqual(self.value("Price / a year's earnings per share", column, exact=False), price / eps)
            self.assertAlmostEqual(self.value("Earnings yield", column, exact=False), eps / price)
            self.assertAlmostEqual(self.value("Price / cash earnings", column, exact=False), market / cash_earnings)
            free_cash_flow = self.v("Cash from operations", column) + self.v("Capital expenditures", column)
            self.assertAlmostEqual(self.value("Free cash flow yield", column, exact=False), free_cash_flow / market)
            dividends, buybacks = -self.v("Dividends paid", column), -self.v("Shares repurchased", column)
            self.assertAlmostEqual(self.value("Dividend yield", column, exact=False), dividends / market)
            self.assertAlmostEqual(self.value("Buyback yield", column, exact=False), buybacks / market)
            self.assertAlmostEqual(self.value("Shareholder yield", column, exact=False), (dividends + buybacks) / market)

    def test_price_to_book_and_tangible_book(self):
        for column, price in ((1, 40.0), (2, 90.0)):
            market = price * self.v("Diluted shares, millions", column)
            equity = self.v("Stockholders' equity (with minority interests)", column)
            tangible = equity - self.v("Goodwill", column) - self.v("Intangible assets", column)
            self.assertAlmostEqual(self.value("Price / book value", column, exact=False), market / equity)
            self.assertAlmostEqual(self.value("Price / tangible book value", column, exact=False), market / tangible)

    def test_return_on_invested_capital_and_enterprise_value_over_it(self):
        for column in (1, 2):
            tax = min(max(self.v("Tax rate (on income before taxes)", column), 0), valuation.TAX_RATE_MOST)
            capital = (self.v("Property, plant and equipment", column) + self.v("Goodwill", column)
                       + self.v("Intangible assets", column) + self.v("Receivables", column) + self.v("Inventory", column)
                       - self.v("Accounts payable", column))
            self.assertAlmostEqual(self.value("Return on invested capital", column, exact=False),
                                   self.v("Operating income", column) * (1 - tax) / capital)
            self.assertAlmostEqual(self.value("Enterprise value / that invested capital", column, exact=False),
                                   self.value("Enterprise value, millions", column, exact=False) / capital)

    def test_peg_is_the_price_over_earnings_over_the_growth_in_points(self):
        for column in (1, 2):
            eps, before = self.v("Earnings per share, diluted", column), self.v("Earnings per share, diluted, the year before", column)
            pe = self.value("Price / a year's earnings per share", column, exact=False)
            self.assertAlmostEqual(self.value("PEG", column, exact=False), pe / ((eps / before - 1) * 100))

    def test_the_median_column_is_of_every_company_when_none_were_chosen(self):
        _, cells, sheets = self.worked()
        row = next(n for n, r in enumerate(cells["Comparison"]) if r and r[0] and str(r[0][0]).startswith("Price / sales"))
        low, high = sheets.value("Comparison", row, 1), sheets.value("Comparison", row, 2)
        self.assertAlmostEqual(sheets.value("Comparison", row, 3), (low + high) / 2)
        self.assertEqual(self.labels().count("Peers' median"), 0)
        self.assertEqual(len(cells["Comparison"][row]), 4)                   # (no column beside the median)


class TestAMultipleThatMeansNothing(ValuationTestCase):

    def test_a_company_that_lost_money_has_no_price_to_earnings_but_a_negative_earnings_yield(self):
        self.add("ABC", made_up_facts())
        self.add("LOSS", scaled(made_up_facts(), 1.0, "Loss Co", {"NetIncomeLoss": -1.0}))
        self.compare(["ABC", "LOSS"], ":prices '(40 40)")
        self.assertGreater(self.value("Price / a year's earnings per share", 1, exact=False), 0)
        self.assertEqual(self.value("Price / a year's earnings per share", 2, exact=False), "")
        self.assertLess(self.value("Earnings yield", 2, exact=False), 0)
        self.assertEqual(self.value("PEG", 2, exact=False), "")
        self.assertEqual(self.value("Price / cash earnings", 2, exact=False) == "" or
                         self.value("Price / cash earnings", 2, exact=False) > 0, True)


    def test_a_peg_is_empty_where_earnings_fell(self):
        falling = made_up_facts()
        for fact in falling["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]:
            if fact["end"] == "2023-12-31":
                fact["val"] = fact["val"] * 0.5                       # (the last year's profit is half what it was)
        self.add("ABC", made_up_facts())
        self.add("FALL", falling)
        self.compare(["ABC", "FALL"], ":prices '(40 40)")
        self.assertGreater(self.value("PEG", 1, exact=False), 0)
        self.assertEqual(self.value("PEG", 2, exact=False), "")
        self.assertGreater(self.value("Price / a year's earnings per share", 2, exact=False), 0)


class TestABanksValuation(ValuationTestCase):

    def setUp(self):
        super().setUp()
        self.add("BNK", bank_with_more_facts(), industry=(6021, "National Commercial Banks"))
        self.add("BN2", scaled(bank_with_more_facts(), 2.0, "Bank Two"), industry=(6021, "National Commercial Banks"))
        self.compare(["BNK", "BN2"], ":prices '(12 25)")

    def v(self, label, column):
        return self.value(label, column)

    def test_a_banks_balance_sheet_adds_up_with_its_goodwill_and_intangibles(self):
        for column in (1, 2):
            assets = (self.v("Cash and equivalents", column) + self.v("Securities (available for sale and held to maturity)", column)
                      + self.v("Loans, net of the allowance", column) + self.v("Goodwill and intangible assets", column)
                      + self.v("Other assets", column))
            self.assertAlmostEqual(assets, self.v("Total assets", column))
        self.assertAlmostEqual(self.v("Goodwill and intangible assets", 1), 40.0)               # (30 + 10)

    def test_net_income_to_common_shareholders_and_earnings_per_share_are_after_the_preferred_dividends(self):
        for column in (1, 2):
            to_common = self.v("Net income", column) - self.v("Preferred dividends", column)
            self.assertAlmostEqual(self.v("Net income to common shareholders", column), to_common)
            self.assertAlmostEqual(self.value("Earnings per share, diluted", column, exact=False),
                                   to_common / self.v("Diluted shares, millions", column))

    def test_the_banks_multiples(self):
        for column, price in ((1, 12.0), (2, 25.0)):
            market = price * self.v("Diluted shares, millions", column)
            equity = self.v("Stockholders' equity (with minority interests)", column)
            tangible = equity - self.v("Memo: preferred stock and minority interests", column) \
                - self.v("Goodwill and intangible assets", column)
            to_common = self.v("Net income to common shareholders", column)
            self.assertAlmostEqual(self.value("Tangible common equity, millions", column, exact=False), tangible)
            self.assertAlmostEqual(self.value("Price / tangible book value", column, exact=False), market / tangible)
            self.assertAlmostEqual(self.value("Return on tangible common equity", column, exact=False), to_common / tangible)
            self.assertAlmostEqual(self.value("Price / book value", column, exact=False), market / equity)
            self.assertAlmostEqual(self.value("Market value / a year's profit before credit losses", column, exact=False),
                                   market / self.v("Profit before credit losses", column))
            self.assertAlmostEqual(self.value("Market value / deposits", column, exact=False), market / self.v("Deposits", column))
            self.assertAlmostEqual(self.value("Shareholder yield", column, exact=False),
                                   -(self.v("Dividends paid", column) + self.v("Shares repurchased", column)) / market)

    def test_a_bank_has_no_enterprise_value(self):
        self.assertNotIn("Enterprise value, millions (market value + debt - cash and short-term investments)", self.labels())


class TestAnInsurersValuation(ValuationTestCase):

    def test_price_to_tangible_book_and_to_premiums(self):
        self.add("INS", insurer_facts(), industry=(6331, "Fire, Marine & Casualty Insurance"))
        self.add("IN2", scaled(insurer_facts(), 3.0, "Insurer Two"), industry=(6331, "Fire, Marine & Casualty Insurance"))
        self.compare(["INS", "IN2"], ":prices '(50 120)")
        for column, price in ((1, 50.0), (2, 120.0)):
            market = price * self.value("Diluted shares, millions", column)
            equity = self.value("Stockholders' equity (with minority interests)", column)
            tangible = equity - self.value("Goodwill", column) - self.value("Intangible assets", column)
            self.assertAlmostEqual(self.value("Tangible book value, millions", column, exact=False), tangible)
            self.assertAlmostEqual(self.value("Price / tangible book value", column, exact=False), market / tangible)
            self.assertAlmostEqual(self.value("Market value / a year's premiums earned", column, exact=False),
                                   market / self.value("Premiums earned", column))
            self.assertAlmostEqual(self.value("Price / book value", column, exact=False), market / equity)


# ---------------------------------------------------------------------------
# Where the share prices come from
# ---------------------------------------------------------------------------

STOCKS = [("ABC", "Software", 10e9, 50.0), ("BIG", "Software", 20e9, 90.0)]


class TestWhereThePricesComeFrom(ValuationTestCase):

    def setUp(self):
        super().setUp()
        self.add("ABC", made_up_facts())
        self.add("BIG", scaled(made_up_facts(), 2.0, "Big Co"))

    def notes(self):
        return "\n".join(self.labels("Notes"))

    def test_by_default_the_databases_closing_prices(self):
        self.make_database(STOCKS)
        self.compare(["ABC", "BIG"])
        self.assertAlmostEqual(self.value("Share price", 1), 50.0)
        self.assertAlmostEqual(self.value("Share price", 2), 90.0)
        self.assertIn("Share prices: the closing prices on 2024-05-31 from the table stock_returns", self.notes())

    def test_not_all_in_the_database_is_no_valuation_rows_and_the_notes_say_why(self):
        self.make_database([STOCKS[0], ("BIG", "Software", 20e9, None)])
        self.compare(["ABC", "BIG"])
        self.assertNotIn("Share price", self.labels())
        self.assertIn("No valuation rows: there are no share prices in the database for BIG", self.notes())

    def test_without_a_database_there_are_no_valuation_rows_and_the_notes_say_so(self):
        self.compare(["ABC", "BIG"])
        self.assertNotIn("Share price", self.labels())
        self.assertIn("was not found", self.notes())

    def test_false_leaves_them_out_though_the_database_has_them(self):
        self.make_database(STOCKS)
        self.compare(["ABC", "BIG"], ":prices #f")
        self.assertNotIn("Share price", self.labels())

    def test_asking_for_the_database_without_all_the_prices_is_an_error(self):
        self.make_database([STOCKS[0], ("BIG", "Software", 20e9, None)])
        self.assertLispError("(compare-companies creds '(\"ABC\" \"BIG\") :prices \"database\")", "the database has no share price for BIG")

    def test_a_list_gives_them_and_must_have_one_for_each_company(self):
        self.compare(["ABC", "BIG"], ":prices '(40 90)")
        self.assertAlmostEqual(self.value("Share price", 2), 90.0)
        self.assertLispError("(compare-companies creds '(\"ABC\" \"BIG\") :prices '(40))", ":prices is the share price of each company")

    def test_alpha_vantage_gives_the_latest(self):
        asked = []
        with mock.patch.object(lisp_alpha_vantage, "alpha_vantage_price", lambda creds, ticker: asked.append(ticker) or 60.0):
            self.compare(["ABC", "BIG"], ":prices #t")
        self.assertEqual(asked, ["ABC", "BIG"])
        self.assertAlmostEqual(self.value("Share price", 1), 60.0)
        self.assertIn("Share prices: the latest, from Alpha Vantage", "\n".join(self.labels("Notes")))

    def test_a_database_that_is_asked_for_and_is_not_there_is_an_error_that_says_where_it_looked(self):
        self.assertLispError("(compare-companies creds '(\"ABC\" \"BIG\") :database \"/nowhere/x.db\")", "there is no database file /nowhere/x.db")
        self.assertLispError("(compare-companies creds '(\"ABC\" \"BIG\") :prices \"database\")", "no financial_data.db in the current folder")


# ---------------------------------------------------------------------------
# Analysts' estimates
# ---------------------------------------------------------------------------

def estimate(date, horizon, average):
    return {"date": date, "horizon": horizon, "eps_estimate_average": str(average)}


class TestEstimates(ValuationTestCase):

    def setUp(self):
        super().setUp()
        self.add("ABC", made_up_facts())
        self.add("BIG", scaled(made_up_facts(), 2.0, "Big Co"))
        records = {"ABC": [estimate("2023-12-31", "fiscal year", 9.0), estimate("2024-03-31", "fiscal quarter", 1.0),
                           estimate("2024-12-31", "fiscal year", 8.0), estimate("2025-12-31", "fiscal year", 10.0)],
                   "BIG": [estimate("2024-12-30", "fiscal year", 16.0)]}
        patcher = mock.patch.object(lisp_alpha_vantage, "estimate_records", lambda creds, symbol: records[symbol])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_next_two_fiscal_years_after_the_latest_reported(self):
        self.compare(["ABC", "BIG"], ":prices '(40 90) :estimates #t")
        self.assertAlmostEqual(self.value("Estimate for the next fiscal year", 1, exact=False), 8.0)     # (not FY2023's 9)
        self.assertAlmostEqual(self.value("Estimate for the fiscal year after that", 1, exact=False), 10.0)
        self.assertAlmostEqual(self.value("Estimate for the next fiscal year", 2, exact=False), 16.0)
        self.assertEqual(self.value("Estimate for the fiscal year after that", 2, exact=False), 0)      # (none: an empty cell)

    def test_forward_price_to_earnings_growth_expected_and_forward_peg(self):
        self.compare(["ABC", "BIG"], ":prices '(40 90) :estimates #t")
        eps = self.value("Earnings per share, diluted", 1)
        growth = 8.0 / eps - 1
        forward = 40.0 / 8.0
        self.assertAlmostEqual(self.value("Growth of earnings per share the estimate expects", 1, exact=False), growth)
        self.assertAlmostEqual(self.value("Price / the estimate for the next fiscal year", 1, exact=False), forward)
        self.assertAlmostEqual(self.value("Price / the estimate for the fiscal year after that", 1, exact=False), 4.0)
        self.assertAlmostEqual(self.value("Forward PEG", 1, exact=False), forward / (growth * 100))
        self.assertEqual(self.value("Price / the estimate for the fiscal year after that", 2, exact=False), "")

    def test_the_notes_say_where_they_came_from_and_who_has_none(self):
        self.compare(["ABC", "BIG"], ":prices '(40 90) :estimates #t")
        notes = "\n".join(self.labels("Notes"))
        self.assertIn("Analysts' estimates: the average of the analysts' estimates", notes)

    def test_estimates_are_for_fiscal_years_and_need_prices(self):
        self.assertLispError("(compare-companies creds '(\"ABC\" \"BIG\") :prices '(1 2) :estimates #t :period \"quarterly\")",
                             ":estimates are of fiscal years")
        self.assertLispError("(compare-companies creds '(\"ABC\" \"BIG\") :estimates #t)", ":estimates needs share prices")


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------

SOFTWARE = [
    ("ABC", "Software", 10e9, 50.0),             # the target
    ("NEAR", "Software", 9e9, 54.0),             # 0.9 times its size: the nearest
    ("UP", "Software", 12e9, 48.0),              # 1.2 times
    ("FAR", "Software", 30e9, 90.0),            # 3 times
    ("TINY", "Software", 1e9, 10.0),             # a tenth
    ("OTHER", "Banks", 10e9, 20.0),              # the same size, another industry
    ("NOCAP", "Software", None, 20.0),           # no market capitalization
    ("NOPRICE", "Software", 10e9, None),         # no price
]


class PeersTestCase(ValuationTestCase):

    def setUp(self):
        super().setUp()
        self.make_database(SOFTWARE)
        for ticker, scale in (("ABC", 1.0), ("NEAR", 0.9), ("UP", 1.2), ("FAR", 3.0), ("TINY", 0.1), ("NOCAP", 1.0), ("NOPRICE", 1.0)):
            self.add(ticker, scaled(made_up_facts(), scale, ticker + " Inc"))

    def peers_of(self, tab="Comparison"):
        """The tickers in the columns after the first, from the header."""
        header = self.tab(tab)[2]
        return [cell[0].split("(")[-1].rstrip(")") for cell in header[2:] if cell and cell[0] and "(" in str(cell[0])]


class TestChoosingPeers(PeersTestCase):

    def test_the_nearest_in_size_in_the_same_industry_that_trade_now(self):
        self.compare(["ABC"], ":peers 3")
        self.assertEqual(self.peers_of(), ["NEAR", "UP", "FAR"])
        first = self.tab()[2][1][0]
        self.assertTrue(first.endswith("(ABC)"))
        self.assertEqual(self.written[-1][0], "ABC and its peers compared (annual)")

    def test_a_single_name_is_enough_and_true_asks_for_five(self):
        self.run_lisp('(compare-companies creds "ABC" :peers #t)')
        self.assertEqual(self.peers_of(), ["NEAR", "UP", "FAR", "TINY"])                # (only four trade in the industry)

    def test_the_median_is_of_the_peers_alone_and_a_column_says_how_far_the_target_is_from_it(self):
        self.compare(["ABC"], ":peers 3")
        _, cells, sheets = self.worked()
        row = next(n for n, r in enumerate(cells["Comparison"]) if r and r[0] and str(r[0][0]).startswith("Price / sales"))
        values = [sheets.value("Comparison", row, column) for column in (1, 2, 3, 4)]
        target, peer_values = values[0], values[1:]
        median = sorted(peer_values)[1]
        self.assertAlmostEqual(sheets.value("Comparison", row, 5), median)
        self.assertAlmostEqual(sheets.value("Comparison", row, 6), target / median - 1)
        header = cells["Comparison"][2]
        self.assertEqual(header[5][0], "Peers' median")
        self.assertEqual(header[6][0], "ABC vs the peers' median")

    def test_only_the_multiples_have_a_column_against_the_peers(self):
        self.compare(["ABC"], ":peers 2")
        _, cells, _ = self.worked()
        by_label = {str(r[0][0]): r for r in cells["Comparison"] if r and r[0]}
        width = len(cells["Comparison"][2])
        self.assertIsNotNone(by_label["Price / sales (market value / a year's revenue)"][width - 1])
        self.assertIsNone(by_label["Gross margin"][width - 1])
        self.assertIsNone(by_label["Dividend yield (a year's dividends paid / market value)"][width - 1])

    def test_what_the_target_would_be_worth_at_the_peers_median_multiples(self):
        self.compare(["ABC"], ":peers 3")
        _, cells, sheets = self.worked()
        median = lambda label: self.value(label, 5, exact=False)
        shares = self.value("Diluted shares, millions", 1)
        eps = self.value("Earnings per share, diluted", 1)
        self.assertAlmostEqual(self.value("At the peers' median price / earnings", 1), median("Price / a year's earnings per share") * eps)
        ebitda = self.value("Operating income", 1) + self.value("Depreciation (and amortization, if not reported apart)", 1) \
            + self.value("Amortization of intangible assets", 1)
        debt = self.value("Current debt", 1) + self.value("Long-term debt", 1)
        cash = self.value("Cash and equivalents", 1) + self.value("Short-term investments", 1)
        self.assertAlmostEqual(self.value("At the peers' median enterprise value / EBITDA", 1),
                               (median("Enterprise value / a year's EBITDA") * ebitda - debt + cash) / shares)
        self.assertAlmostEqual(self.value("At the peers' median price / book value", 1),
                               median("Price / book value") * self.value("Stockholders' equity (with minority interests)", 1) / shares)
        implied = [self.value(label, 1) for label in (
            "At the peers' median price / earnings", "At the peers' median enterprise value / EBITDA",
            "At the peers' median enterprise value / operating income", "At the peers' median enterprise value / revenue",
            "At the peers' median enterprise value / free cash flow", "At the peers' median price / book value")]
        middle = sorted(implied)
        expected = (middle[2] + middle[3]) / 2
        self.assertAlmostEqual(self.value("Median of these prices", 1), expected)
        self.assertAlmostEqual(self.value("That median against the share price", 1, exact=False), expected / 50.0 - 1)

    def test_with_a_basis_the_comparison_links_to_the_numbers_for_the_implied_rows(self):
        self.compare(["ABC"], ':peers 2 :basis "revenue"')
        cells = self.tab("Comparison")
        row = next(r for r in cells if r and r[0] and r[0][0] == "At the peers' median price / earnings")
        self.assertTrue(row[1][0].startswith("='As reported'!B"))
        self.assertIsNone(row[2])                                    # (the first company's column alone)
        self.assertGreater(self.value("At the peers' median price / earnings", 1, tab="As reported"), 0)

    def test_the_notes_say_who_was_chosen_how_big_they_are_and_what_the_basis_was(self):
        self.compare(["ABC"], ":peers 2")
        notes = "\n".join(self.labels("Notes"))
        self.assertIn("How the peers of ABC were chosen", notes)
        self.assertIn('the stocks in the industry "Software" (7 of them)', notes)
        self.assertIn("NEAR (NEAR Inc): $9.0 billion, 0.90 times ABC's", notes)
        self.assertIn("UP (UP Inc): $12.0 billion, 1.20 times ABC's", notes)
        self.assertIn("Share prices: the closing prices on 2024-05-31", notes)

    def test_a_note_says_when_the_peers_are_far_from_the_target_in_size(self):
        self.compare(["ABC"], ":peers 3")                                  # (FAR is 3 times the size: not far)
        self.assertNotIn("is far from ABC in size", "\n".join(self.labels("Notes")))
        self.compare(["ABC"], ":peers 4")                                  # (TINY is a tenth of the size)
        self.assertIn("Note: ABC is far from TINY in size (TINY is 0.10 times its market capitalization)",
                      "\n".join(self.labels("Notes")))

    def test_a_bank_gets_a_banks_implied_rows(self):
        self.make_database([("BNK", "Bank", 5e9, 12.0), ("BN2", "Bank", 6e9, 20.0), ("BN3", "Bank", 5.5e9, 15.0)])
        self.add("BNK", bank_with_more_facts(), industry=(6021, "National Commercial Banks"))
        self.add("BN2", scaled(bank_with_more_facts(), 2.0, "Bank Two"), industry=(6021, "National Commercial Banks"))
        self.add("BN3", scaled(bank_with_more_facts(), 1.5, "Bank Three"), industry=(6021, "National Commercial Banks"))
        self.run_lisp('(compare-companies creds "BNK" :peers 2)')
        self.assertEqual(self.peers_of(), ["BN3", "BN2"])
        labels = self.labels()
        self.assertIn("At the peers' median price / tangible book value", labels)
        self.assertNotIn("At the peers' median enterprise value / EBITDA", labels)
        tangible = self.value("Tangible common equity, millions", 1, exact=False)
        self.assertAlmostEqual(self.value("At the peers' median price / tangible book value", 1),
                               self.value("Price / tangible book value", 4, exact=False) * tangible / self.value("Diluted shares, millions", 1))


class TestSkippingWhatCannotBeCompared(PeersTestCase):

    def setUp(self):
        super().setUp()
        # candidates, nearest first: each one that cannot be used, then two that can
        stocks = [("ABC", "Software", 10e9, 50.0), ("SAME", "Software", 10.1e9, 50.0), ("LENDER", "Software", 10.2e9, 50.0),
                  ("EURO", "Software", 10.3e9, 50.0), ("OLD", "Software", 10.4e9, 50.0), ("NOSEC", "Software", 10.5e9, 50.0),
                  ("GOOD1", "Software", 11e9, 55.0), ("GOOD2", "Software", 12e9, 60.0)]
        self.make_database(stocks)
        self.add("SAME", scaled(made_up_facts(), 1.0, "ABC Inc class B"), cik=self.companies["ABC"][0]["cik"])
        self.add("LENDER", bank_with_more_facts(), industry=(6021, "National Commercial Banks"))
        self.add("EURO", scaled(made_up_facts(), 1.0, "Euro Inc", unit="EUR"))
        self.add("OLD", made_up_facts(years=(2019, 2020, 2021)))
        self.add("GOOD1", scaled(made_up_facts(), 1.1, "Good One"))
        self.add("GOOD2", scaled(made_up_facts(), 1.2, "Good Two"))

    def test_each_is_skipped_with_its_reason_and_the_next_in_size_is_taken(self):
        self.compare(["ABC"], ":peers 2")
        self.assertEqual(self.peers_of(), ["GOOD1", "GOOD2"])
        notes = "\n".join(self.labels("Notes"))
        self.assertIn("Looked at, and skipped:", notes)
        self.assertIn("SAME ($10.1 billion): it is another stock of a company already here (ABC)", notes)
        self.assertIn("LENDER ($10.2 billion): it is a bank, and ABC is an ordinary company", notes)
        self.assertIn("EURO ($10.3 billion): it reports in EUR, and ABC in USD", notes)
        self.assertIn("OLD ($10.4 billion): its latest annual report is for the period that ended 2021-12-31, 883 days ago", notes)
        self.assertIn("NOSEC ($10.5 billion): the SEC has no company with the ticker NOSEC", notes)

    def test_two_stocks_of_one_company_among_the_peers_are_one_column(self):
        self.add("GOOD2", scaled(made_up_facts(), 1.2, "Good One class B"), cik=self.companies["GOOD1"][0]["cik"])
        self.compare(["ABC"], ":peers 2")
        self.assertEqual(self.peers_of(), ["GOOD1"])
        self.assertIn("GOOD2 ($12.0 billion): it is another stock of a company already here (GOOD1)", "\n".join(self.labels("Notes")))

    def test_none_that_can_be_used_is_an_error_that_says_why(self):
        self.make_database([("ABC", "Software", 10e9, 50.0), ("SAME", "Software", 10.1e9, 50.0), ("EURO", "Software", 10.3e9, 50.0)])
        self.assertLispError('(compare-companies creds "ABC" :peers 2)',
                             "none of the 2 stocks nearest in size to ABC in Software could be compared with it: "
                             "SAME: it is another stock of a company already here (ABC); EURO: it reports in EUR")


class TestWhatCannotBeChosen(PeersTestCase):

    def test_a_target_the_table_does_not_have(self):
        self.add("ZZZ", made_up_facts())
        self.assertLispError('(compare-companies creds "ZZZ" :peers 2)', "ZZZ is not in the table ticker_industry")

    def test_a_target_without_a_market_capitalization(self):
        self.assertLispError('(compare-companies creds "NOCAP" :peers 2)', "the table stock_returns has no market capitalization for NOCAP")

    def test_peers_come_with_one_company_not_a_list_and_without_given_prices(self):
        self.assertLispError("(compare-companies creds '(\"ABC\" \"NEAR\") :peers 2)", "with :peers give one company")
        self.assertLispError("(compare-companies creds \"ABC\" :peers 2 :prices '(40 90))", "with :peers the share prices are")

    def test_how_many_is_a_small_whole_number(self):
        self.assertLispError('(compare-companies creds "ABC" :peers 0)', ":peers is how many comparable companies to choose")
        self.assertLispError('(compare-companies creds "ABC" :peers 99)', ":peers is how many comparable companies to choose")

    def test_the_industry_goes_with_the_peers_and_must_be_one_the_table_has(self):
        self.assertLispError("(compare-companies creds '(\"ABC\" \"NEAR\") :industry \"Software\")", ":industry says what industries to choose peers from")
        self.assertLispError('(compare-companies creds "ABC" :peers 2 :industry "Sofware")', "no industry called Sofware -- did you mean")

    def test_another_industry_can_be_asked_for(self):
        self.make_database(SOFTWARE + [("BK1", "Bank", 10.5e9, 20.0)])
        self.add("BK1", scaled(made_up_facts(), 1.0, "Bank Co"))
        self.compare(["ABC"], ':peers 2 :industry (list "Bank" "Software")')
        self.assertEqual(self.peers_of(), ["BK1", "NEAR"])                # (BK1: 1.05 times its size, NEAR 0.9: 1.11 times)
        self.make_database([("ABC", "Software", 10e9, 50.0), ("BK1", "Bank", 10.5e9, 20.0)])
        self.compare(["ABC"], ':peers 1 :industry "Bank"')
        self.assertEqual(self.peers_of(), ["BK1"])


# ---------------------------------------------------------------------------
# The list of candidates
# ---------------------------------------------------------------------------

class TestComparableCompanies(PeersTestCase):

    def test_the_stocks_of_the_industry_nearest_in_size_first(self):
        self.run_lisp('(define c (comparable-companies "ABC" :count 3))')
        self.assertShows('(table-column c "ticker")', "#(NEAR UP FAR)")
        self.assertShows('(table-column c "industry")', "#(Software Software Software)")
        self.assertShows('(table-column c "market-cap")', "#(9000.0 12000.0 30000.0)")          # (millions)
        self.assertShows('(table-column c "relative-size")', "#(0.9 1.2 3.0)")
        self.assertShows('(table-column c "price")', "#(54.0 48.0 90.0)")
        self.assertShows('(table-column c "price-date")', "#(2024-05-31 2024-05-31 2024-05-31)")

    def test_it_leaves_out_the_stock_itself_other_industries_and_those_that_do_not_trade(self):
        self.run_lisp('(define c (comparable-companies "ABC" :count 20))')
        self.assertShows('(table-column c "ticker")', "#(NEAR UP FAR TINY)")

    def test_a_ticker_may_be_written_with_a_dash_or_a_slash_for_its_share_class(self):
        self.make_database([("BRK.B", "Insurance", 900e9, 450.0), ("AIG", "Insurance", 40e9, 70.0)])
        self.assertShows('(table-column (comparable-companies "BRK-B") "ticker")', "#(AIG)")
        self.assertShows('(table-column (comparable-companies "brk/b") "ticker")', "#(AIG)")

    def test_it_says_what_is_wrong(self):
        self.assertLispError('(comparable-companies "ZZZ")', "ZZZ is not in the table ticker_industry")
        self.assertLispError('(comparable-companies "NOCAP")', "has no market capitalization for NOCAP")
        self.assertLispError('(comparable-companies "ABC" :count 0)', ":count is a whole number of companies")
        self.assertLispError('(comparable-companies "ABC" :industry "Sofware")', "no industry called Sofware")
        self.assertLispError('(comparable-companies "ABC" :database "/nowhere/x.db")', "there is no database file /nowhere/x.db")

    def test_without_the_table_of_returns_there_is_nothing_to_be_near_in_size_to(self):
        path = self.make_database(SOFTWARE)
        import sqlite3
        connection = sqlite3.connect(path)
        connection.execute("DROP TABLE stock_returns")
        connection.commit()
        connection.close()
        self.assertLispError('(comparable-companies "ABC")', "the table stock_returns has no market capitalization for ABC")
        stocks = peers.load_stocks(path, "test")
        self.assertEqual(stocks["ABC"].industry, "Software")
        self.assertIsNone(stocks["ABC"].market_cap)

    def test_another_industry_than_the_stocks_own(self):
        self.make_database(SOFTWARE + [("BK1", "Bank", 10.5e9, 20.0)])
        self.assertShows('(table-column (comparable-companies "ABC" :industry "Bank") "ticker")', "#(BK1)")
        self.assertShows('(table-column (comparable-companies "ABC" :industry (list "Bank" "Banks")) "ticker")', "#(OTHER BK1)")


class TestTheDatabase(ValuationTestCase):

    def test_it_is_found_in_the_current_folder_or_the_data_folder_unless_a_path_is_given(self):
        self.assertIsNone(peers.locate_database())
        path = self.make_database(SOFTWARE)
        self.assertEqual(peers.locate_database(), path)
        self.assertEqual(peers.locate_database(path), path)
        self.assertIsNone(peers.locate_database(path + ".missing"))

    def test_a_stock_trades_if_it_has_a_market_capitalization_and_a_price(self):
        self.assertTrue(peers.Stock("A", "x", 1e9, 5.0).trades)
        self.assertFalse(peers.Stock("A", "x", None, 5.0).trades)
        self.assertFalse(peers.Stock("A", "x", 1e9, None).trades)
        self.assertFalse(peers.Stock("A", "x", 0, 5.0).trades)

    def test_the_prices_date_of_a_group_is_one_date_or_the_first_and_the_last(self):
        stocks = [peers.Stock("A", "x", 1, 1, "2024-05-30"), peers.Stock("B", "x", 1, 1, "2024-05-31")]
        self.assertEqual(fc.price_dates(stocks[:1]), "2024-05-30")
        self.assertEqual(fc.price_dates(stocks), "2024-05-30 to 2024-05-31")
        self.assertEqual(fc.price_dates([peers.Stock("A", "x")]), "unknown")
