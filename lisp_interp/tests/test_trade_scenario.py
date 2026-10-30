"""lib/trade_scenario.lsp: a scenario (the underlying at a price on a date), and every position of options of every
expiration on or after the date, valued on the date and ranked. The chains here are made by the Black-Scholes formula,
so that each option's volatility, and what it is worth on the date, can be worked out again here."""

import datetime
import math

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

TODAY = datetime.date(2026, 11, 2)
NEAR = datetime.date(2026, 12, 18)
FAR = datetime.date(2027, 1, 15)
RATE = 0.04
STRIKES = [90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0]


def normal_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def black_scholes(kind, spot, strike, years, rate, vol, dividend_yield=0.0):
    """The Black-Scholes-Merton price, as bsm-price works it out (with a dividend yield: a future's option, Black's)."""
    if years <= 0:
        return max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + vol * vol / 2) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    if kind == "call":
        return spot * math.exp(-dividend_yield * years) * normal_cdf(d1) - strike * math.exp(-rate * years) * normal_cdf(d2)
    return strike * math.exp(-rate * years) * normal_cdf(-d2) - spot * math.exp(-dividend_yield * years) * normal_cdf(-d1)


def volatility_of(strike, expiration):
    """The made-up chain's volatility for each option: a smile, and a little more for the far expiration."""
    return 0.25 + 0.0004 * (strike - 100) ** 2 / 10 + (0.02 if expiration == FAR else 0.0)


class TradeScenarioTestCase(OptionChainTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "trade_scenario.lsp")')

    def chain_rows(self, stock="XYZ", price=100.0, expirations=(NEAR, FAR), futures=False, spread=0.10, symbol_of=None):
        """A chain of calls and puts at STRIKES for each expiration, each priced by the formula at volatility_of, with a
        bid and an ask spread apart around it."""
        rows = []
        for expiration in expirations:
            years = (expiration - TODAY).days / 365.0
            for strike in STRIKES:
                for kind in ("Call", "Put"):
                    middle = black_scholes(kind.lower(), price, strike, years, RATE, volatility_of(strike, expiration),
                                           RATE if futures else 0.0)
                    row = {"strike": strike, "type": kind, "expiration": expiration, "bid": max(middle - spread / 2, 0.01),
                           "ask": middle + spread / 2, "mid": middle, "underlying": stock, "underlying_price": price}
                    if symbol_of:
                        row["symbol"] = symbol_of(stock, expiration, kind[0], strike)
                    rows.append(row)
        return rows

    def make_scenario(self, price, day, options=""):
        self.run_lisp("(define scenario (trade-scenario-for-chain chain %r %s :rate %r :today (date 2026 11 2) %s))"
                      % (price, day, RATE, options))
        table = self.run_lisp("(trade-scenario-trades scenario)")
        return {str(name): list(vector.items) for name, vector in lisp_tables.table_columns(table, "test")}

    def find(self, trades, kind, expires, strikes):
        """The row of the position of the kind, expiring then (text), with these strikes, lowest first."""
        rows = [i for i in range(len(trades["kind"]))
                if str(trades["kind"][i]) == kind and str(trades["expires"][i]) == expires
                and all(trades["strike-%d" % (n + 1)][i] == strike for n, strike in enumerate(strikes))]
        self.assertEqual(len(rows), 1, "%s %s %s" % (kind, expires, strikes))
        return {name: column[rows[0]] for name, column in trades.items()}


class TestPositionsOfOneExpiration(TradeScenarioTestCase):

    def setUp(self):
        super().setUp()
        self.make_chain(self.chain_rows())

    def test_those_that_expire_on_the_date_are_what_option_spreads_finds(self):
        trades = self.make_scenario(108.0, "(date 2026 12 18)")
        found = self.find(trades, "bull-call", "2026-12-18", [100.0, 110.0])
        search = self.spreads_of("(option-spreads-for-chain chain 'bull-call (date 2026 12 18) 108.0 :min-volume 0)")
        row = [i for i in range(len(search["strike-1"])) if search["strike-1"][i] == 100 and search["strike-2"][i] == 110][0]
        for column in ("cost", "max-loss", "worth", "profit", "breakeven-1"):
            self.assertAlmostEqual(found[column], search[column][row], places=9, msg=column)
        self.assertAlmostEqual(found["roi"], found["profit"] / found["cost"], places=12)        # a debit: over its cost
        self.assertEqual(str(found["type-1"]), "call")
        self.assertEqual(found["quantity-2"], -1)
        self.assertEqual(str(found["type-3"]), "")

    def spreads_of(self, call):
        self.run_lisp("(define search %s)" % call)
        table = self.run_lisp("(spread-search-spreads search)")
        return {str(name): list(vector.items) for name, vector in lisp_tables.table_columns(table, "test")}

    def test_an_option_that_expires_later_is_worth_the_formula_at_its_own_volatility(self):
        trades = self.make_scenario(108.0, "(date 2026 12 1)")
        found = self.find(trades, "long-call", "2026-12-18", [105.0])
        vol = volatility_of(105.0, NEAR)
        left = (NEAR - datetime.date(2026, 12, 1)).days / 365.0
        self.assertAlmostEqual(found["worth"], black_scholes("call", 108.0, 105.0, left, RATE, vol), places=6)
        self.assertAlmostEqual(found["if-unchanged"], black_scholes("call", 100.0, 105.0, left, RATE, vol) - found["cost"], places=6)
        self.assertAlmostEqual(found["max-loss"], found["cost"], places=6)        # worth next to nothing at a price near 0
        self.assertAlmostEqual(found["profit"], found["worth"] - found["cost"], places=12)
        # the breakeven: where the formula's value on the date is the cost
        breakeven = found["breakeven-1"]
        self.assertAlmostEqual(black_scholes("call", breakeven, 105.0, left, RATE, vol), found["cost"], delta=0.01)

    def test_a_credit_is_measured_against_the_most_it_can_lose_and_a_put_sold_against_the_cash(self):
        trades = self.make_scenario(108.0, "(date 2026 12 18)")
        found = self.find(trades, "bull-put", "2026-12-18", [95.0, 105.0])
        self.assertLess(found["cost"], 0)
        self.assertAlmostEqual(found["roi"], found["profit"] / found["max-loss"], places=12)
        self.assertAlmostEqual(found["roi"], found["ratio"], places=12)
        put = self.find(trades, "cash-secured-put", "2026-12-18", [100.0])
        self.assertAlmostEqual(put["max-loss"], 100.0 + put["cost"], places=9)        # the strike, less what it paid
        self.assertAlmostEqual(put["roi"], put["profit"] / put["max-loss"], places=12)

    def test_shares_are_paid_for_in_full_and_owning_the_stock_is_a_row(self):
        trades = self.make_scenario(108.0, "(date 2026 12 1)")
        stock = [i for i in range(len(trades["kind"])) if str(trades["kind"][i]) == "long-stock"]
        self.assertEqual(len(stock), 1)
        row = stock[0]
        self.assertEqual((trades["cost"][row], trades["worth"][row], trades["profit"][row]), (100.0, 108.0, 8.0))
        self.assertEqual((trades["max-loss"][row], trades["if-unchanged"][row], trades["roi"][row]), (100.0, 0.0, 0.08))
        self.assertEqual(str(trades["expires"][row]), "")
        covered = self.find(trades, "covered-call", "2027-01-15", [110.0])
        self.assertAlmostEqual(covered["roi"], covered["profit"] / covered["cost"], places=12)
        self.assertGreater(covered["cost"], 90)

    def test_the_ranking(self):
        trades = self.make_scenario(108.0, "(date 2026 12 1)")
        self.assertEqual(trades["roi"], sorted(trades["roi"], reverse=True))
        by_profit = self.make_scenario(108.0, "(date 2026 12 1)", ":rank-by 'profit")
        self.assertEqual(by_profit["profit"], sorted(by_profit["profit"], reverse=True))
        kinds = self.make_scenario(108.0, "(date 2026 12 1)", ":kinds '(bull-call long-put)")
        self.assertEqual(sorted(set(str(k) for k in kinds["kind"])), ["bull-call", "long-put"])
        self.assertEqual(sorted(set(str(e) for e in kinds["expires"])), ["2026-12-18", "2027-01-15"])
        only_far = self.make_scenario(108.0, "(date 2026 12 19)", ":kinds '(long-call)")
        self.assertEqual(set(str(e) for e in only_far["expires"]), {"2027-01-15"})

    def test_errors(self):
        self.assertLispError("(trade-scenario-for-chain chain 108.0 (date 2027 2 1))", "no options expiring on or after 2027-02-01")
        self.assertLispError("(trade-scenario-for-chain chain 108.0 (date 2026 12 1) :rank-by 'cost)", ":rank-by is roi, ratio, or profit")
        self.assertLispError("(trade-scenario-for-chain chain 108.0 (date 2026 12 1) :kinds '(bull-cal))", "bull-cal isn't a kind of spread")


class TestCalendars(TradeScenarioTestCase):

    def setUp(self):
        super().setUp()
        self.make_chain(self.chain_rows())

    def test_a_calendar_sells_the_near_option_and_buys_the_far_one_of_the_same_strike(self):
        trades = self.make_scenario(105.0, "(date 2026 12 18)", ":kinds '(call-calendar put-calendar)")
        found = self.find(trades, "call-calendar", "2026-12-18 & 2027-01-15", [105.0, 105.0])
        rows = self.make_chain_rows_by_symbol()
        near, far = rows[("C", NEAR, 105.0)], rows[("C", FAR, 105.0)]
        self.assertAlmostEqual(found["cost"], far["ask"] - near["bid"], places=9)
        self.assertEqual((found["quantity-1"], found["quantity-2"]), (-1, 1))
        self.assertEqual((str(found["expiration-1"]), str(found["expiration-2"])), ("2026-12-18", "2027-01-15"))
        left = (FAR - NEAR).days / 365.0
        worth = black_scholes("call", 105.0, 105.0, left, RATE, volatility_of(105.0, FAR)) - 0.0     # the near call: nothing
        self.assertAlmostEqual(found["worth"], worth, places=6)
        self.assertAlmostEqual(found["max-loss"], found["cost"], delta=0.01)         # far from the strike, both are nothing
        self.assertLess(found["breakeven-1"], 105.0)
        self.assertGreater(found["breakeven-2"], 105.0)
        put = self.find(trades, "put-calendar", "2026-12-18 & 2027-01-15", [100.0, 100.0])
        self.assertEqual(str(put["type-1"]), "put")

    def make_chain_rows_by_symbol(self):
        return {(row["type"][0], row["expiration"], row["strike"]): row for row in self.chain_rows()}

    def test_it_says_the_positions_in_words(self):
        self.make_scenario(105.0, "(date 2026 12 18)", ":kinds '(call-calendar)")
        self.assertShows("(trade-scenario-position-in-words scenario 0)",
                         '"sell 1 105.00 call (2026-12-18), buy 1 105.00 call (2027-01-15)"')
        trades = self.make_scenario(105.0, "(date 2026 12 18)", ":kinds '(covered-call call-butterfly)")
        row_of = lambda kind: [i for i in range(len(trades["kind"])) if str(trades["kind"][i]) == kind][0]
        self.assertTrue(self.show("(trade-scenario-position-in-words scenario %d)" % row_of("covered-call"))
                        .startswith('"buy 100 shares, sell 1 '))
        self.assertIn("sell 2 105.00 calls", self.show("(trade-scenario-position-in-words scenario %d)" % row_of("call-butterfly")))


class TestFutures(TradeScenarioTestCase):
    """A future's options are on several futures, each with a price of its own: the scenario's price is of one, and the
    others keep their difference from it."""

    def setUp(self):
        super().setUp()
        symbol = lambda future, day, letter, strike: "./%s LO%s  %s%s%g" % (future, future[-2:], day.strftime("%y%m%d"), letter, strike)
        rows = (self.chain_rows("CLF7", 100.0, (NEAR,), futures=True, symbol_of=symbol)
                + self.chain_rows("CLG7", 98.0, (FAR,), futures=True, symbol_of=symbol))
        self.make_chain(rows)

    def test_the_first_future_is_the_reference_and_the_others_keep_their_difference(self):
        trades = self.make_scenario(80.0, "(date 2026 12 1)", ":kinds '(long-put long-stock) :contract-size 1000 :unit \"barrel\"")
        self.assertShows("(trade-scenario-symbol scenario)", '"CLF7"')
        self.assertShows('(table-column (trade-scenario-underlyings scenario) "scenario")', "#(80.0 78.0)")
        later = self.find(trades, "long-put", "2027-01-15", [95.0])
        left = (FAR - datetime.date(2026, 12, 1)).days / 365.0
        expected = black_scholes("put", 78.0, 95.0, left, RATE, volatility_of(95.0, FAR), RATE)    # Black's: on CLG7, at 78
        self.assertAlmostEqual(later["worth"], expected, places=5)
        self.assertEqual(str(later["underlying"]), "CLG7")
        self.make_scenario(80.0, "(date 2026 12 1)", ":kinds '(long-put) :underlying \"CLG7\"")
        self.assertShows('(table-column (trade-scenario-underlyings scenario) "scenario")', "#(82.0 80.0)")

    def test_it_says_the_futures_and_the_contract(self):
        self.make_scenario(80.0, "(date 2026 12 1)", ":kinds '(long-put long-stock) :contract-size 1000 :unit \"barrel\"")
        shown = self.show_output("(show-trade-scenario scenario :count 3)")
        self.assertIn("The scenario: CLF7 at 80.00 on 2026-12-01 (it is at 100.00 now).", shown)
        self.assertIn("Each future is taken to keep its difference from the first", shown)
        self.assertIn("a contract is 1,000 barrels: multiply by 1,000", shown)
        self.assertIn("buy CLF7", shown)
        self.assertIn("The strikes of the options go from 90.00 to 120.00, and the scenario's price is beyond them", shown)

    def show_output(self, src):
        self.run_lisp(src)
        return self.printed()


class TestFetching(TradeScenarioTestCase):
    """trade-scenario gets the chain from tastytrade, with the contract size of the future's options."""

    def test_it_asks_tastytrade_for_enough_months_and_knows_the_contract(self):
        self.make_chain(self.chain_rows("CLF7", 100.0, (NEAR,), futures=True,
                                        symbol_of=lambda f, d, l, k: "./%s LOF7  %s%s%g" % (f, d.strftime("%y%m%d"), l, k)))
        self.run_lisp("""(define asked '())
                         (define (tastytrade-option-chain creds symbol months strikes) (set! asked (list symbol months strikes)) chain)
                         (define (market-open?) #t)
                         (define (today) (date 2026 11 2))
                         (define scenario (trade-scenario "creds" "CL" 80.0 (date 2026 12 1) :rate 0.04 :kinds '(long-put)))""")
        self.assertShows("asked", '("CL" 4 40)')                 # a month to the date, and three more; 40 strikes
        self.assertShows("(trade-scenario-contract-size scenario)", "1000")
        self.assertShows("(trade-scenario-unit scenario)", '"barrel"')
        self.run_lisp("""(define scenario (trade-scenario "creds" "/CL" 80.0 (date 2026 12 1) :rate 0.04 :kinds '(long-put)
                                                          :strikes 60 :months 2 :contract-size 100 :unit "barrel"))""")
        self.assertShows("asked", '("/CL" 2 60)')
        self.assertShows("(trade-scenario-contract-size scenario)", "100")
        self.assertShows("(trade-scenario-unit (trade-scenario \"creds\" \"AAPL\" 80.0 (date 2026 12 1) :rate 0.04 :kinds '(long-put)))",
                         '"share"')
