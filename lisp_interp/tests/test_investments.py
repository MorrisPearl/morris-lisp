"""Investments: option prices, futures curves, the volatility smile, simulated prices,
option chains checked against them, and portfolios.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class TestOptionPrices(LispTestCase):
    """lisp_options.py: Black-Scholes-Merton, Black's formula, implied volatility, the Greeks, and
    American options by binomial tree."""

    def price(self, src):
        return float(self.run_lisp(src))

    def test_black_scholes_prices_the_textbook_option(self):
        # S = K = 100, a year, 5%, 20% volatility: the call is 10.4506 and the put 5.5735
        self.assertAlmostEqual(self.price('(bsm-price "call" 100 100 1 0.05 0.2)'), 10.450584, places=5)
        self.assertAlmostEqual(self.price('(bsm-price "put" 100 100 1 0.05 0.2)'), 5.573526, places=5)
        self.assertAlmostEqual(self.price('(bsm-price "Call" 100 100 1 0.05 0.2)'), 10.450584, places=5)    # any case
        self.assertAlmostEqual(self.price('(bsm-price #t 100 100 1 0.05 0.2)'), 10.450584, places=5)
        self.assertAlmostEqual(self.price("(normal-cdf 0)"), 0.5, places=12)
        self.assertAlmostEqual(self.price("(normal-cdf 1.96)"), 0.9750021, places=6)

    def test_put_call_parity_holds_with_a_dividend_yield(self):
        call = self.price('(bsm-price "call" 100 110 0.75 0.04 0.3 :dividend-yield 0.02)')
        put = self.price('(bsm-price "put" 100 110 0.75 0.04 0.3 :dividend-yield 0.02)')
        self.assertAlmostEqual(call - put, 100 * math.exp(-0.02 * 0.75) - 110 * math.exp(-0.04 * 0.75), places=8)

    def test_black_s_formula_is_bsm_on_the_forward(self):
        forward, discount = 100 * math.exp(0.04 * 0.5), math.exp(-0.04 * 0.5)
        self.assertAlmostEqual(self.price('(black-price "put" %r 95 0.5 %r 0.25)' % (forward, discount)),
                               self.price('(bsm-price "put" 100 95 0.5 0.04 0.25)'), places=10)

    def test_vectors_price_many_options_at_once(self):
        prices = self.run_lisp('(bsm-price (vector "Call" "Put") 100 #(95 105) 0.5 0.04 0.25)')
        self.assertEqual(len(prices.items), 2)
        self.assertAlmostEqual(float(prices.items[1]), self.price('(bsm-price "put" 100 105 0.5 0.04 0.25)'), places=4)
        self.assertLispError('(bsm-price "call" 100 #(95 105 110) 0.5 0.04 #(0.2 0.3))', "the same length")

    def test_implied_volatility_gives_back_the_volatility(self):
        self.assertAlmostEqual(self.price('(implied-vol (bsm-price "put" 100 90 0.25 0.03 0.4) "put" 100 90 0.25 0.03)'),
                               0.4, places=9)
        vols = self.run_lisp("(black-implied-vol #(1 0) (black-price #(1 0) 100 #(110 95) 0.25 0.99 #(0.25 0.4)) "
                             "100 #(110 95) 0.25 0.99)")
        np.testing.assert_allclose(np.array(vols.items, dtype=float), [0.25, 0.4], atol=1e-6)
        self.assertShows('(implied-vol 1.0 "call" 100 90 0.5 0.0)', "nan")      # below what it pays now: no volatility

    def test_the_greeks_are_the_derivatives_of_the_price(self):
        h = 1e-4

        def bsm(kind, spot=100.0, time=0.5, rate=0.04, vol=0.25):
            return self.price('(bsm-price "%s" %r 105 %r %r %r :dividend-yield 0.01)' % (kind, spot, time, rate, vol))
        for kind in ("call", "put"):
            greek = lambda name: self.price('(bsm-%s "%s" 100 105 0.5 0.04 0.25 :dividend-yield 0.01)' % (name, kind))
            with self.subTest(kind=kind):
                self.assertAlmostEqual(greek("delta"), (bsm(kind, spot=100 + h) - bsm(kind, spot=100 - h)) / (2 * h), places=6)
                self.assertAlmostEqual(greek("gamma"), (bsm(kind, spot=100 + h) - 2 * bsm(kind) + bsm(kind, spot=100 - h)) / h ** 2,
                                       places=3)
                self.assertAlmostEqual(greek("vega"), (bsm(kind, vol=0.25 + h) - bsm(kind, vol=0.25 - h)) / (2 * h) / 100,
                                       places=6)          # for a volatility point
                self.assertAlmostEqual(greek("theta"), -(bsm(kind, time=0.5 + h) - bsm(kind, time=0.5 - h)) / (2 * h) / 365,
                                       places=6)          # for a day
                self.assertAlmostEqual(greek("rho"), (bsm(kind, rate=0.04 + h) - bsm(kind, rate=0.04 - h)) / (2 * h) / 100,
                                       places=6)          # for a point of interest

    def test_an_american_put_is_worth_more_than_a_european_one(self):
        american = self.price('(american-price "put" 100 100 1 0.05 0.2)')
        self.assertAlmostEqual(american, 6.09, delta=0.01)                     # the textbook value
        european = self.price('(american-price "put" 100 100 1 0.05 0.2 :early-exercise #f)')
        self.assertAlmostEqual(european, self.price('(bsm-price "put" 100 100 1 0.05 0.2)'), delta=0.015)   # the tree's error
        self.assertGreater(american - european, 0.4)

    def test_an_american_call_without_dividends_is_never_exercised_early(self):
        self.assertAlmostEqual(self.price('(american-price "call" 100 100 1 0.05 0.2)'),
                               self.price('(american-price "call" 100 100 1 0.05 0.2 :early-exercise #f)'), places=10)

    def test_a_dividend_can_make_it_worth_exercising_a_call_early(self):
        dividends = '(make-table "time" #(0.5) "amount" #(5.0))'
        american = self.price('(american-price "call" 100 100 1 0.05 0.2 :dividends %s)' % dividends)
        european = self.price('(american-price "call" 100 100 1 0.05 0.2 :dividends %s :early-exercise #f)' % dividends)
        self.assertGreater(american - european, 0.2)
        # the European one is Black's formula on the price less the dividend's present value
        forward = (100 - 5 * math.exp(-0.05 * 0.5)) * math.exp(0.05)
        self.assertAlmostEqual(european, self.price('(black-price "call" %r 100 1 %r 0.2)' % (forward, math.exp(-0.05))),
                               delta=0.02)
        later = self.price('(american-price "call" 100 100 0.4 0.05 0.2 :dividends %s)' % dividends)
        self.assertAlmostEqual(later, self.price('(bsm-price "call" 100 100 0.4 0.05 0.2)'), delta=0.02)   # (it's after expiring)

    def test_american_implied_volatility_gives_back_the_volatility(self):
        self.assertAlmostEqual(self.price('(american-implied-vol (american-price "put" 100 110 0.5 0.04 0.3 :steps 100) '
                                          '"put" 100 110 0.5 0.04 :steps 100)'), 0.3, places=7)

    def test_the_binomial_tree_shows_how_american_price_is_found(self):
        tree = dict(lisp_tables.table_columns(self.run_lisp('(binomial-tree "put" 100 100 1 0.05 0.2 :steps 3)'), "t"))
        self.assertEqual(sorted(tree), ["early", "exercise", "hold", "price", "step", "time", "ups", "value"])
        self.assertEqual(len(tree["step"].items), 10)                       # 1 + 2 + 3 + 4 nodes
        self.assertAlmostEqual(float(tree["value"].items[0]), self.price('(american-price "put" 100 100 1 0.05 0.2 :steps 3)'),
                               places=5)
        early = [(int(s), int(u)) for s, u, e in zip(tree["step"].items, tree["ups"].items, tree["early"].items) if e]
        self.assertEqual(early, [(2, 0)])                                   # two steps down: worth exercising
        for value, hold, exercise in zip(tree["value"].items, tree["hold"].items, tree["exercise"].items):
            if not math.isnan(float(hold)):
                self.assertAlmostEqual(float(value), max(float(hold), float(exercise)), places=4)
        calls = dict(lisp_tables.table_columns(self.run_lisp('(binomial-tree "call" 100 100 1 0.05 0.2)'), "t"))
        self.assertEqual(len(calls["step"].items), 21)                      # 5 steps unless asked
        self.assertEqual(sum(int(e) for e in calls["early"].items), 0)      # never, for a call without dividends
        self.assertLispError('(binomial-tree "put" #(100 110) 100 1 0.05 0.2)', "one option at a time")

    def test_what_the_option_functions_wont_take(self):
        self.assertLispError('(bsm-price "straddle" 100 100 1 0.05 0.2)', 'an option type is "call" or "put"')
        self.assertLispError('(bsm-price "call" "100" 100 1 0.05 0.2)', "spot must be a number or a vector")
        self.assertLispError('(bsm-price "call" 100 100 1 0.05 0.2 :dividend-yield "2%")', ":dividend-yield must be a number")
        self.assertLispError('(bsm-delta "call" 100 100 0 0.05 0.2)', "the time and the volatility must be above 0")
        self.assertLispError('(american-price "put" 100 100 1 0.05 0.2 :steps 0)', ":steps must be a whole number")
        self.assertLispError('(american-price "put" 100 100 1 0.9 0.01 :steps 2)', "too few")
        self.assertLispError('(american-price "put" 100 100 1 0.05 0.2 :dividends (make-table "when" #(0.5) "amount" #(1.0)))',
                             "no column named 'time'")


class TestFuturesCurve(LispTestCase):
    """lisp_futures.py: futures-curve-fit and futures-leg-carry, on made-up curve rows."""

    def setUp(self):
        super().setUp()
        # (delivery-month futures-symbol days-to-delivery price): a price growing 5% a year, but for one
        # contract 3% above it
        rows = []
        for i, days in enumerate((30, 120, 210, 300, 390, 480)):
            price = 70 * math.exp(0.05 * days / 365) * (1.03 if i == 3 else 1.0)
            rows.append("(list (date 2027 %d 1) \"CL%d\" %d %r)" % (i + 1, i, days, price))
        self.run_lisp("(define rows (list %s))" % " ".join(rows))

    def test_the_contract_above_the_curve_is_rich(self):
        fit = self.run_lisp("(futures-curve-fit rows 1.0 1)")
        signals = {str(lisp_core.pairs_to_list(row)[1]): str(lisp_core.pairs_to_list(row)[6])
                   for row in lisp_core.pairs_to_list(fit)}
        self.assertEqual(signals["CL3"], "Rich")
        self.assertEqual(sum(1 for s in signals.values() if s == "Rich"), 1)
        self.assertShows("(futures-curve-fit (list (car rows) (cadr rows)))", "()")      # too few to fit

    def test_the_carry_between_each_month_and_the_next(self):
        legs = [lisp_core.pairs_to_list(leg) for leg in lisp_core.pairs_to_list(self.run_lisp("(futures-leg-carry rows 4.0 1.0)"))]
        self.assertEqual(len(legs), 5)
        carries = [float(leg[5]) for leg in legs]
        self.assertAlmostEqual(carries[0], 5.0, places=6)      # 5% a year, in percent
        self.assertAlmostEqual(float(legs[0][6]), 1.0, places=6)   # net storage: carry less funding
        self.assertAlmostEqual(float(legs[0][7]), 0.0, places=6)   # convenience yield: funding + storage - carry
        self.assertGreater(carries[2], 5.5)                    # into the rich contract
        self.assertLess(carries[3], 4.5)                       # out of it
        self.assertShows("(futures-leg-carry (list (car rows)) 4.0 1.0)", "()")


class TestVolSmile(LispTestCase):
    """lib/vol_smile.lsp, on a made-up option chain whose implied volatilities
    follow a known smile, Y = a + b K + c K^2 for each expiration, with one
    option priced 2 volatility points too high."""

    RATE = 0.045
    SPOT = 100.0
    SMILES = {30: (0.0033, -0.02, 0.10), 60: (0.0066, -0.03, 0.12), 90: (0.0099, -0.035, 0.11)}

    @staticmethod
    def black(call, forward, strike, T, discount, vol):
        """Black's formula, written independently of vol_smile.lsp's."""
        N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
        d1 = math.log(forward / strike) / (vol * math.sqrt(T)) + vol * math.sqrt(T) / 2
        d2 = d1 - vol * math.sqrt(T)
        if call:
            return discount * (forward * N(d1) - strike * N(d2))
        return discount * (strike * N(-d2) - forward * N(-d1))

    def chain(self, smiles=None):
        """The made-up chain, as a table with the columns vol_smile.lsp uses."""
        columns = {name: [] for name in ("symbol", "type", "strike", "expiration-date", "days-to-expiration",
                                         "underlying-price", "bid", "ask", "mid", "volume", "open-interest")}
        for days, smile in (smiles or self.SMILES).items():
            T = days / 365
            discount = math.exp(-self.RATE * T)
            forward = self.SPOT / discount
            expiration = datetime.date(2099, 1, 1) + datetime.timedelta(days=days)
            for strike in range(85, 120, 5):
                for kind in ("Call", "Put"):
                    K = math.log(strike / forward)
                    vol = math.sqrt(smile(T, K) / T) if callable(smile) else \
                        math.sqrt((smile[0] + smile[1] * K + smile[2] * K * K) / T)
                    symbol = "XYZ %dd %s%d" % (days, kind[0], strike)
                    if symbol == "XYZ 30d C110":
                        vol += 0.02                          # the option out of line
                    mid = self.black(kind == "Call", forward, strike, T, discount, vol)
                    for name, value in (("symbol", lisp_core.LispString(symbol)),
                                        ("type", lisp_core.LispString(kind)), ("strike", float(strike)),
                                        ("expiration-date", lisp_core.LispDate(expiration.year, expiration.month,
                                                                               expiration.day)),
                                        ("days-to-expiration", days), ("underlying-price", self.SPOT),
                                        ("bid", mid - 0.002), ("ask", mid + 0.002), ("mid", mid),
                                        ("volume", 0 if symbol == "XYZ 60d C115" else 10),
                                        ("open-interest", 100)):
                        columns[name].append(value)
        return lisp_tables.make_table_value([(name, lisp_core.LispVector(values))
                                              for name, values in columns.items()])

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "vol_smile.lsp")')

    def test_dividends_present_value_counts_those_after_the_date_and_before_each_expiration(self):
        self.run_lisp("""(define dividends (list (cons "ex-date" (vector (date 2026 1 10) (date 2026 3 10) (date 2026 6 10)))
                                                (cons "amount" (vector 1.0 2.0 4.0))))""")
        values = self.run_lisp("(dividends-present-value (vector (date 2026 2 1) (date 2026 5 1) (date 2026 12 1)) 0.05 "
                               "dividends (date 2026 2 1))").items
        march = 2.0 * math.exp(-0.05 * 37 / 365)                 # (the one in January is before the date)
        june = 4.0 * math.exp(-0.05 * 129 / 365)
        np.testing.assert_allclose(np.array(values, dtype=float), [0.0, march, march + june], rtol=1e-6)
        self.assertShows("(dividends-present-value (vector (date 2026 5 1)) 0.05 '() (date 2026 2 1))", "#(0.0)")

    def test_black_price_and_implied_volatility(self):
        self.assertAlmostEqual(self.run_lisp("(vector-ref (black-price #(1) #(100) #(100) #(1) #(1) #(0.2)) 0)"),
                               7.965567, places=4)
        self.assertAlmostEqual(self.run_lisp("(vector-ref (black-price #(0) #(100) #(90) #(0.5) #(0.98) #(0.3)) 0)"),
                               self.black(False, 100, 90, 0.5, 0.98, 0.3), places=4)
        vols = self.run_lisp("(black-implied-vol #(1 0) (black-price #(1 0) #(100 100) #(110 95) #(0.25 0.25) "
                             "#(0.99 0.99) #(0.25 0.4)) #(100 100) #(110 95) #(0.25 0.25) #(0.99 0.99))")
        self.assertAlmostEqual(float(vols.items[0]), 0.25, places=5)
        self.assertAlmostEqual(float(vols.items[1]), 0.4, places=5)
        # a price below what the option is worth at expiration fits no volatility
        self.assertShows("(black-implied-vol #(1) #(5) #(110) #(100) #(0.5) #(1))", "#(nan)")

    def test_each_expirations_smile_is_found_and_the_option_out_of_line_is_rich(self):
        self.env[lisp_core.Symbol("chain")] = self.chain()
        self.run_lisp("(define fit (fit-vol-smiles chain :rate 0.045))"
                      "(define options (vol-smile-fit-options fit))"
                      "(define expirations (vol-smile-fit-expirations fit))")
        def column(table, name):
            return self.run_lisp('(table-column %s "%s")' % (table, name)).items.tolist()
        for i, (days, (a, b, c)) in enumerate(sorted(self.SMILES.items())):
            with self.subTest(days=days):
                self.assertAlmostEqual(column("expirations", "intercept")[i], a, places=5)
                self.assertAlmostEqual(column("expirations", "K")[i], b, places=4)
                self.assertAlmostEqual(column("expirations", "K^2")[i], c, places=3)
                self.assertAlmostEqual(column("expirations", "atm-vol")[i], math.sqrt(a / (days / 365)), places=4)
                self.assertAlmostEqual(column("expirations", "parity-forward")[i] / column("expirations", "forward")[i],
                                       1.0, places=5)
        signals = dict(zip(column("options", "symbol"), column("options", "signal")))
        self.assertEqual({symbol: signal for symbol, signal in signals.items() if signal}, {"XYZ 30d C110": "rich"})
        self.run_lisp('(define out (table-filter options (= (table-column options "symbol") "XYZ 30d C110")))')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column out "iv-residual") 0)'), 0.02, places=3)
        T, discount = 30 / 365, math.exp(-self.RATE * 30 / 365)
        a, b, c = self.SMILES[30]
        K = math.log(110 / (100 / discount))
        true_price = self.black(True, 100 / discount, 110, T, discount, math.sqrt((a + b * K + c * K * K) / T))
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column out "model-price") 0)'), true_price, places=3)
        # only liquid, out-of-the-money options: no 60-day 115 call (no volume), and
        # no calls below the forward or puts above it
        self.assertShows('(vector-length (vector-select (table-column options "symbol") '
                         '(= (table-column options "symbol") "XYZ 60d C115")))', "0")
        self.assertShows('(vector-sum (vector-and (= (table-column options "type") "Put") '
                         '(> (table-column options "K") 0)))', "0")

    def test_all_the_expirations_at_once(self):
        """With five terms and three expirations, one fit to them all."""
        def smile(T, K):
            return 0.001 + 0.03 * T + 0.002 * math.sqrt(T) - 0.01 * K - 0.04 * K * math.sqrt(T) + 0.1 * K * K
        self.env[lisp_core.Symbol("chain")] = self.chain({30: smile, 60: smile, 90: smile})
        self.run_lisp("(define fit (fit-vol-smiles chain :rate 0.045 :by-expiration #f))")
        self.assertEqual(len(lisp_core.pairs_to_list(self.run_lisp("(vol-smile-fit-models fit)"))), 3)
        coefficients = self.run_lisp("(model-coefficients (cdr (car (vol-smile-fit-models fit))))").items.tolist()
        for found, expected in zip(coefficients, [0.03, 0.002, -0.01, -0.04, 0.1]):
            self.assertAlmostEqual(found, expected, places=3)
        self.assertShows("(table-column-names (vol-smile-fit-expirations fit))",
                         '("expiration-date" "days" "forward" "parity-forward" "options" "atm-vol" "intercept" '
                         '"T" "sqrt(T)" "K" "K*sqrt(T)" "K^2")')

    def test_the_example_runs(self):
        """examples/vol_smile_example.lsp, with the made-up chain in place of
        tastytrade's."""
        chain = self.chain()
        self.env[lisp_core.Symbol("tastytrade-option-chain")] = lambda *args: chain
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("no-credentials-needed.json")
        lisp_core.run_file(os.path.join(EXAMPLES, "vol_smile_example.lsp"), self.env)
        out = self.printed()
        rich = out.split("ask below it (cheap):\n")[1].split("\n\n")[0]
        self.assertEqual([line.split("  ")[0] for line in rich.splitlines()[2:]], ["XYZ 30d C110"])
        self.assertIn("Least absolute deviation model:  Y = ", out)
        self.assertIn("[chart] Implied volatility, ", out)

    def test_too_few_options_and_unknown_terms(self):
        self.env[lisp_core.Symbol("chain")] = self.chain()
        self.run_lisp("(define fit (fit-vol-smiles chain :rate 0.045 :max-vol-spread 0.0001))")
        self.assertShows('(table-column (vol-smile-fit-expirations fit) "intercept")', "#(nan nan nan)")
        self.assertShows("(table-row-count (vol-smile-fit-options fit))", "0")
        self.assertLispError('(fit-vol-smiles chain :terms (list "K^3"))', "there's no term K^3")


class TestInvestmentPaths(LispTestCase):
    """lisp_investment_paths.py: daily-returns, adjust-returns, and bootstrap-path."""

    PRICES = """(define prices (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4)
                                                     (date 2024 1 5) (date 2024 1 8)))
                                    (cons "close" (vector 100.0 110.0 99.0 99.0 108.9))))"""
    # (a Saturday's ex-date, the 6th, goes with the next day there's a price, the 8th)
    DIVIDENDS = """(define dividends (list (cons "ex-date" (vector (date 2023 12 1) (date 2024 1 4)
                                                               (date 2024 1 6) (date 2024 2 1)))
                                           (cons "amount" (vector 5.0 1.0 2.0 7.0))))"""

    def numbers(self, src):
        return [float(x) for x in self.run_lisp(src).items]

    def assertNumbers(self, src, expected, places=6):
        actual = self.numbers(src)
        self.assertEqual(len(actual), len(expected), msg=src)
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=places, msg=src)

    def make_returns(self, name, values):
        """A table of log returns, called `name` in the Lisp environment."""
        table = lisp_tables.make_table_value([("log-return", lisp_vector_math.to_vector(np.array(values)))])
        self.env[lisp_core.Symbol(name)] = table

    def a_year_of_returns(self, name="history"):
        self.make_returns(name, np.random.default_rng(1).normal(0.0008, 0.012, 400))

    # -- daily-returns ------------------------------------------------------

    def test_daily_returns_are_log_returns_from_the_second_day(self):
        self.run_lisp(self.PRICES)
        self.assertShows("(table-column-names (daily-returns prices))", '("date" "log-return")')
        self.assertShows('(table-column (daily-returns prices) "date")', "#(2024-01-03 2024-01-04 2024-01-05 2024-01-08)")
        self.assertNumbers('(table-column (daily-returns prices) "log-return")',
                           [math.log(1.1), math.log(0.9), 0.0, math.log(1.1)])

    def test_a_dividend_is_part_of_the_return_of_the_day_it_goes_ex(self):
        self.run_lisp(self.PRICES + self.DIVIDENDS)
        self.assertNumbers('(table-column (daily-returns prices :dividends dividends) "log-return")',
                           [math.log(1.1), math.log((99 + 1) / 110), 0.0, math.log((108.9 + 2) / 99)])
        # (the ones before the first price and after the last count for nothing)

    def test_dividends_on_one_day_add_up(self):
        self.run_lisp(self.PRICES + """(define dividends (list (cons "ex-date" (vector (date 2024 1 4) (date 2024 1 4)))
                                                              (cons "amount" (vector 1.0 0.5))))""")
        self.assertNumbers('(table-column (daily-returns prices :dividends dividends) "log-return")',
                           [math.log(1.1), math.log((99 + 1.5) / 110), 0.0, math.log(1.1)])

    def test_no_dividends_changes_nothing(self):
        self.run_lisp(self.PRICES + """(define none (list (cons "ex-date" (vector)) (cons "amount" (vector))))""")
        plain = self.show("(daily-returns prices)")
        self.assertEqual(self.show("(daily-returns prices :dividends none)"), plain)
        self.assertEqual(self.show("(daily-returns prices :dividends '())"), plain)

    def test_what_daily_returns_wont_take(self):
        self.run_lisp(self.PRICES + self.DIVIDENDS)
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 3) (date 2024 1 2)))
                                                      (cons "close" (vector 1.0 2.0))))""", "oldest first")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2) (date 2024 1 2)))
                                                      (cons "close" (vector 1.0 2.0))))""", "oldest first")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3)))
                                                      (cons "close" (vector 1.0 0.0))))""", "above 0")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3)))
                                                      (cons "close" (vector 1.0 nan))))""", "above 0")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2)))
                                                      (cons "close" (vector 1.0))))""", "at least two prices")
        self.assertLispError('(daily-returns (table-drop-columns prices "close"))', "no column named 'close'")
        self.assertLispError('(daily-returns prices :dividends (table-drop-columns dividends "amount"))',
                             "no column named 'amount'")
        self.assertLispError("""(daily-returns prices :dividends (list (cons "ex-date" (vector (date 2024 1 4)))
                                                                      (cons "amount" (vector -1.0))))""", "0 or more")
        self.assertLispError("(daily-returns prices :dividend dividends)", ":dividend isn't an option")

    # -- adjust-returns -----------------------------------------------------

    def test_the_adjusted_returns_average_what_was_asked(self):
        self.a_year_of_returns()
        self.run_lisp("(define adjusted (adjust-returns history 0.08))")
        average_growth = self.run_lisp('(vector-mean (vector-exp (table-column adjusted "log-return")))')
        self.assertAlmostEqual(average_growth, 1.08 ** (1 / 252), places=7)
        self.run_lisp("(define in-days (adjust-returns history -0.5 :days-per-year 365))")
        average_growth = self.run_lisp('(vector-mean (vector-exp (table-column in-days "log-return")))')
        self.assertAlmostEqual(average_growth, 0.5 ** (1 / 365), places=7)

    def test_adjusting_moves_the_returns_without_spreading_them(self):
        self.a_year_of_returns()
        self.run_lisp("(define adjusted (adjust-returns history 0.08))")
        before = self.run_lisp('(vector-stdev (table-column history "log-return"))')
        self.assertAlmostEqual(self.run_lisp('(vector-stdev (table-column adjusted "log-return"))'), before, places=7)
        self.assertShows("(table-row-count adjusted)", "400")

    def test_a_volatility_scale_spreads_the_returns_and_keeps_the_average_return(self):
        self.a_year_of_returns()
        self.run_lisp("(define scaled (adjust-returns history 0.08 :volatility-scale 1.5))")
        before = self.run_lisp('(vector-stdev (table-column history "log-return"))')
        self.assertAlmostEqual(self.run_lisp('(vector-stdev (table-column scaled "log-return"))'), 1.5 * before, places=6)
        average_growth = self.run_lisp('(vector-mean (vector-exp (table-column scaled "log-return")))')
        self.assertAlmostEqual(average_growth, 1.08 ** (1 / 252), places=7)
        self.run_lisp("(define unscaled (adjust-returns history 0.08 :volatility-scale 1))")
        self.assertEqual(self.show('(table-column unscaled "log-return")'),
                         self.show('(table-column (adjust-returns history 0.08) "log-return")'))

    def test_adjusting_keeps_the_other_columns(self):
        self.run_lisp(self.PRICES + "(define adjusted (adjust-returns (daily-returns prices) 0.08))")
        self.assertShows("(table-column-names adjusted)", '("date" "log-return")')
        self.assertShows('(table-column adjusted "date")', "#(2024-01-03 2024-01-04 2024-01-05 2024-01-08)")

    def test_what_adjust_returns_wont_take(self):
        self.a_year_of_returns()
        self.assertLispError("(adjust-returns history -1)", "above -1")
        self.assertLispError('(adjust-returns history "8%")', "must be a number, or a list of (name . number) pairs")
        self.assertLispError("(adjust-returns history 0.08 :days-per-year 0)", ":days-per-year must be a number above 0")
        self.assertLispError("(adjust-returns (list (cons \"date\" (vector (date 2024 1 2)))) 0.08)", "no column of returns")
        self.assertLispError("(adjust-returns history 0.08 :days 252)", ":days isn't an option")
        self.assertLispError("(adjust-returns history 0.08 :volatility-scale 0)", ":volatility-scale must be a number above 0")
        self.assertLispError('(adjust-returns history 0.08 :volatility-scale "2")', ":volatility-scale must be a number above 0")

    # -- bootstrap-path -----------------------------------------------------

    def log_returns_along(self, path, start_price):
        """The log return of each step of a path (a LispVector of prices)."""
        return np.diff(np.log(np.concatenate([[start_price], np.array(path.items, dtype=np.float64)])))

    def test_a_path_is_blocks_of_consecutive_returns_that_wrap_around(self):
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        self.make_returns("five", returns)
        for seed in range(30):
            path = self.run_lisp("(bootstrap-path five 100 7 3 :seed %d)" % seed)
            self.assertEqual(len(path.items), 7)
            steps = self.log_returns_along(path, 100)
            which = [int(np.argmin(np.abs(np.array(returns) - step))) for step in steps]
            for step, day in zip(steps, which):
                self.assertAlmostEqual(step, returns[day], places=5)
            for block in (0, 3):                                # two blocks of 3, then one day of a third
                self.assertEqual(which[block + 1], (which[block] + 1) % 5)
                self.assertEqual(which[block + 2], (which[block] + 2) % 5)

    def test_every_start_is_possible_including_the_last_days_of_the_history(self):
        self.make_returns("three", [0.01, 0.02, 0.03])
        turns = set()
        for seed in range(40):
            path = self.run_lisp("(bootstrap-path three 100 3 3 :seed %d)" % seed)
            turns.add(tuple(np.round(self.log_returns_along(path, 100), 2)))
        self.assertEqual(turns, {(0.01, 0.02, 0.03), (0.02, 0.03, 0.01), (0.03, 0.01, 0.02)})

    def test_a_path_has_the_days_asked_for(self):
        self.a_year_of_returns()
        for days, block in ((252, 10), (1, 10), (10, 10), (11, 10), (5, 1), (400, 400)):
            with self.subTest(days=days, block=block):
                self.assertShows("(vector-length (bootstrap-path history 50 %d %d))" % (days, block), str(days))

    def test_a_seed_gives_the_same_path_every_time(self):
        self.a_year_of_returns()
        path = lambda seed: self.show("(bootstrap-path history 100 50 5 :seed %d)" % seed)
        self.assertEqual(path(3), path(3))
        self.assertNotEqual(path(3), path(4))

    def test_without_a_seed_the_paths_come_from_the_shared_generator(self):
        self.a_year_of_returns()
        self.run_lisp("(random-seed 7)")
        first = self.show("(bootstrap-path history 100 50 5)")
        second = self.show("(bootstrap-path history 100 50 5)")
        self.assertNotEqual(first, second)
        self.run_lisp("(random-seed 7)")
        self.assertEqual(self.show("(bootstrap-path history 100 50 5)"), first)

    def test_a_seeded_path_leaves_the_shared_generator_alone(self):
        self.a_year_of_returns()
        self.run_lisp("(random-seed 7)")
        expected = self.run_lisp("(random-float)")
        self.run_lisp("(random-seed 7)")
        self.run_lisp("(bootstrap-path history 100 50 5 :seed 1)")
        self.assertEqual(self.run_lisp("(random-float)"), expected)

    def test_the_expected_price_after_a_year_is_the_expected_return(self):
        self.a_year_of_returns()
        self.run_lisp("(define adjusted (adjust-returns history 0.08))")
        # exactly right for blocks of one day (the 4000 paths' average is within about 0.003 of it,
        # while leaving out the adjustment for the log returns' spread is off by 0.02); for longer
        # blocks it depends on the history's own ups and downs in a row, so only close
        for block, delta in ((1, 0.008), (21, 0.03)):
            with self.subTest(block=block):
                finals = self.run_lisp("""(vector-mean (list->vector
                    (map (lambda (i) (vector-ref (bootstrap-path adjusted 100 252 %d :seed i) 251))
                         (iota 4000))))""" % block)
                self.assertAlmostEqual(finals / 100, 1.08, delta=delta)

    def test_what_bootstrap_path_wont_take(self):
        self.make_returns("five", [0.01, 0.02, 0.03, 0.04, 0.05])
        self.assertLispError("(bootstrap-path five 100 0 3)", "days must be a whole number, 1 or more")
        self.assertLispError("(bootstrap-path five 100 2.5 3)", "days must be a whole number")
        self.assertLispError("(bootstrap-path five 100 7 0)", "block-size must be a whole number, 1 or more")
        self.assertLispError("(bootstrap-path five 100 7 6)", "block-size 6 is more than the 5 returns")
        self.assertLispError("(bootstrap-path five 0 7 3)", "start price must be a number above 0")
        self.assertLispError('(bootstrap-path five "100" 7 3)', "start price must be a number above 0")
        self.assertLispError("(bootstrap-path five 100 7 3 :seed -1)", ":seed must be a whole number, 0 or more")
        self.assertLispError("(bootstrap-path five 100 7 3 :seed 1.5)", ":seed must be a whole number")
        self.assertLispError("(bootstrap-path five 100 7 3 :wrap #f)", ":wrap isn't an option")
        self.assertLispError('(bootstrap-path (list (cons "date" (vector (date 2024 1 2)))) 100 7 3)', "no column of returns")
        self.assertLispError('(bootstrap-path (list (cons "a" (vector 0.01)) (cons "b" (vector 0.02))) 100 7 1)',
                             "the returns of 2 investments (a, b)")
        self.assertLispError('(bootstrap-path (list (cons "log-return" (vector 0.01 nan))) 100 7 1)', "not missing or infinite")
        self.assertLispError('(bootstrap-path (list (cons "log-return" (vector))) 100 7 1)', "there are no returns")

    # -- option-value -------------------------------------------------------

    def make_paths(self, count=3000, rate=0.04, block=1):
        """`paths`, in the Lisp environment: paths of a year growing at the interest rate."""
        self.a_year_of_returns()
        self.run_lisp("(define paths (map (lambda (i) (bootstrap-path (adjust-returns history (- (exp %s) 1)) 100 252 %d :seed i))"
                      "                   (iota %d)))" % (rate, block, count))

    def final_prices(self):
        return self.numbers("(list->vector (map (lambda (path) (vector-ref path 251)) paths))")

    def value_and_error(self, src):
        """The two numbers in an (option-value ...)'s answer."""
        value, error = lisp_core.pairs_to_list(self.run_lisp(src))
        return float(value), float(error)

    def test_a_payoff_is_discounted_for_the_years_at_the_interest_rate(self):
        self.make_paths(count=10)
        value, error = self.value_and_error("(option-value paths (lambda (path) 5) 0.04 2)")
        self.assertAlmostEqual(value, 5 * math.exp(-0.08), places=9)
        self.assertAlmostEqual(error, 0.0, places=9)

    def test_the_value_is_the_discounted_average_payoff_and_its_error_the_standard_error(self):
        self.make_paths(count=500)
        finals = np.array(self.final_prices())
        calls = np.maximum(finals - 100, 0) * math.exp(-0.05 * 1.5)
        value, error = self.value_and_error(
            "(option-value paths (lambda (path) (max 0 (- (vector-ref path 251) 100))) 0.05 1.5)")
        self.assertAlmostEqual(value, calls.mean(), places=5)
        self.assertAlmostEqual(error, calls.std(ddof=1) / math.sqrt(500), places=5)

    def test_a_payoff_can_depend_on_the_whole_path(self):
        self.make_paths(count=200)
        value, _ = self.value_and_error("(option-value paths (lambda (path) (max 0 (- (vector-mean path) 100))) 0 1)")
        by_hand = self.numbers("(list->vector (map (lambda (path) (max 0 (- (vector-mean path) 100))) paths))")
        self.assertAlmostEqual(value, float(np.mean(by_hand)), places=5)

    def test_paths_growing_at_the_interest_rate_are_worth_todays_price(self):
        # what an investment is worth is what it costs now, when it grows at the interest rate: the
        # average discounted final price is the start price (to within a few of its own standard errors)
        self.make_paths()
        value, error = self.value_and_error("(option-value paths (lambda (path) (vector-ref path 251)) 0.04 1)")
        self.assertAlmostEqual(value, 100, delta=3 * error)
        self.assertLess(error, 0.5)

    def test_what_option_value_wont_take(self):
        self.make_paths(count=5)
        payoff = "(lambda (path) 1)"
        self.assertLispError("(option-value 5 %s 0.04 1)" % payoff, "paths must be a list of vectors")
        self.assertLispError("(option-value (list 1 2) %s 0.04 1)" % payoff, "paths must be a list of vectors")
        self.assertLispError("(option-value (list (car paths)) %s 0.04 1)" % payoff, "at least two paths")
        self.assertLispError("(option-value paths %s \"4%%\" 1)" % payoff, "interest rate must be a number")
        self.assertLispError("(option-value paths %s 0.04 0)" % payoff, "years must be a number above 0")
        self.assertLispError("(option-value paths 5 0.04 1)", "not a procedure")
        self.assertLispError("(option-value paths (lambda (path) \"x\") 0.04 1)", "must return a number")
        self.assertLispError("(option-value paths (lambda (path) nan) 0.04 1)", "must return a number")

    # -- dividend-schedule and bootstrap-path's :dividends --------------------

    ACTUAL = """(define actual (list (cons "ex-date" (vector (date 2025 6 20) (date 2025 11 14) (date 2026 2 13)
                                                         (date 2026 5 15) (date 2026 8 14)))
                                    (cons "amount" (vector 0.40 0.50 0.50 0.52 0.52))))"""

    def schedule_rows(self, src):
        """A dividend schedule's rows, as (ex-date, day, amount)."""
        columns = lisp_tables.table_columns(self.run_lisp(src), "test")
        dates, days, amounts = [list(vector.items) for _, vector in columns]
        return [(str(d), int(day), round(float(a), 4)) for d, day, a in zip(dates, days, amounts)]

    def test_a_schedule_has_the_known_dividends_after_the_start_up_to_the_last_day(self):
        self.run_lisp(self.ACTUAL)
        self.assertShows("(table-column-names (dividend-schedule actual (date 2026 1 2) 100))", '("ex-date" "day" "amount")')
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 1 2) 100)"),
                         [("2026-02-13", 29, 0.5), ("2026-05-15", 92, 0.52)])      # (2026-08-14 is after day 100)
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 2 13) 100)"),
                         [("2026-05-15", 63, 0.52)])                              # not the one that day: it's in the price

    def test_a_schedule_can_repeat_the_last_years_dividends_on_the_same_dates(self):
        self.run_lisp(self.ACTUAL)
        # the last year, to October 5, 2026, had four: next year's are on a Saturday (the 14th, the 13th, the
        # 15th, and the 14th), so the next day the market is open: the Monday -- or, the Monday being
        # Washington's Birthday, the Tuesday
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 10 5) 252 :repeat-last-year #t)"),
                         [("2026-11-16", 30, 0.5), ("2027-02-16", 91, 0.5),
                          ("2027-05-17", 154, 0.52), ("2027-08-16", 216, 0.52)])
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 10 5) 252 :repeat-last-year #f)"),
                         [])                                                      # nothing is known after October 5

    def test_repeating_goes_on_for_as_many_years_as_the_path_lasts(self):
        self.run_lisp("""(define yearly (list (cons "ex-date" (vector (date 2026 3 2))) (cons "amount" (vector 1.0))))""")
        rows = self.schedule_rows("(dividend-schedule yearly (date 2026 10 5) 800 :repeat-last-year #t)")
        self.assertEqual([row[0] for row in rows], ["2027-03-02", "2028-03-02", "2029-03-02"])
        self.assertEqual(self.schedule_rows("(dividend-schedule yearly (date 2026 10 5) 100 :repeat-last-year #t)"), [])

    def test_a_dividend_on_the_start_date_is_in_the_price_but_comes_again_next_year(self):
        self.run_lisp("""(define on-start (list (cons "ex-date" (vector (date 2026 10 5))) (cons "amount" (vector 1.0))))""")
        self.assertEqual(self.schedule_rows("(dividend-schedule on-start (date 2026 10 5) 300)"), [])
        self.assertEqual(self.schedule_rows("(dividend-schedule on-start (date 2026 10 5) 300 :repeat-last-year #t)"),
                         [("2027-10-05", 251, 1.0)])

    def test_a_dividend_on_the_29th_of_february_comes_on_the_28th_in_other_years(self):
        self.run_lisp("""(define leap (list (cons "ex-date" (vector (date 2028 2 29))) (cons "amount" (vector 1.0))))""")
        self.assertEqual(self.schedule_rows("(dividend-schedule leap (date 2028 6 1) 252 :repeat-last-year #t)"),
                         [("2029-02-28", 186, 1.0)])

    def test_a_known_ex_date_the_market_is_closed_is_the_next_day_it_is_open(self):
        self.run_lisp("""(define odd (list (cons "ex-date" (vector (date 2026 11 26))) (cons "amount" (vector 1.0))))""")
        self.assertEqual(self.schedule_rows("(dividend-schedule odd (date 2026 11 20) 10)"), [("2026-11-27", 4, 1.0)])

    def test_a_schedule_without_dividends_is_a_table_without_rows(self):
        self.run_lisp(self.ACTUAL)
        self.assertShows("(table-row-count (dividend-schedule actual (date 2024 1 2) 100 :repeat-last-year #t))", "0")
        self.assertShows("(length (table-column-names (dividend-schedule actual (date 2024 1 2) 100)))", "3")

    def test_what_dividend_schedule_wont_take(self):
        self.run_lisp(self.ACTUAL)
        self.assertLispError("(dividend-schedule actual 5 100)", "the start date must be a date")
        self.assertLispError("(dividend-schedule actual (date 2026 1 2) 0)", "days must be a whole number")
        self.assertLispError('(dividend-schedule (table-drop-columns actual "amount") (date 2026 1 2) 100)',
                             "no column named 'amount'")
        self.assertLispError('(dividend-schedule (list (cons "ex-date" (vector (date 2026 1 5))) (cons "amount" (vector -1.0)))'
                             " (date 2026 1 2) 100)", "0 or more")
        self.assertLispError("(dividend-schedule actual (date 2026 1 2) 100 :repeat #t)", ":repeat isn't an option")

    def schedule(self, days_and_amounts):
        """A dividend schedule, as `schedule` in the Lisp environment."""
        self.env[lisp_core.Symbol("schedule")] = lisp_tables.make_table_value([
            ("day", lisp_vector_math.to_vector(np.array([d for d, _ in days_and_amounts]))),
            ("amount", lisp_vector_math.to_vector(np.array([a for _, a in days_and_amounts], dtype=np.float64)))])

    def test_a_dividend_takes_its_amount_off_the_price_on_its_day(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.schedule([(2, 1.5), (2, 0.5), (5, 3.0)])                # (two on day 2)
        self.assertNumbers("(bootstrap-path flat 100 8 1 :dividends schedule)", [100, 98, 98, 98, 95, 95, 95, 95])

    def test_the_price_grows_between_dividends_and_a_dividend_is_taken_off_what_it_has_grown_to(self):
        self.make_returns("steady", [0.01, 0.01])
        self.schedule([(3, 2.0), (6, 1.0)])
        price, expected = 100.0, []
        for day in range(1, 9):
            price *= math.exp(0.01)
            price -= {3: 2.0, 6: 1.0}.get(day, 0.0)
            expected.append(price)
        self.assertNumbers("(bootstrap-path steady 100 8 2 :dividends schedule)", expected, places=3)

    def test_the_schedule_may_be_out_of_order_and_go_on_past_the_path(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.schedule([(5, 3.0), (2, 2.0), (50, 40.0)])
        self.assertNumbers("(bootstrap-path flat 100 6 1 :dividends schedule)", [100, 98, 98, 98, 95, 95])

    def test_the_price_stops_at_0(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.schedule([(2, 500.0), (4, 1.0)])
        self.assertNumbers("(bootstrap-path flat 100 5 1 :dividends schedule)", [100, 0, 0, 0, 0])

    def test_no_dividends_in_the_schedule_is_no_change(self):
        self.a_year_of_returns()
        self.run_lisp(self.ACTUAL + "(define none (dividend-schedule actual (date 2024 1 2) 100))")
        plain = self.show("(bootstrap-path history 100 100 5 :seed 3)")
        self.assertEqual(self.show("(bootstrap-path history 100 100 5 :seed 3 :dividends none)"), plain)
        self.assertEqual(self.show("(bootstrap-path history 100 100 5 :seed 3 :dividends '())"), plain)

    def test_dividends_that_are_the_same_in_every_path_leave_the_expected_price_less_what_they_grow_to(self):
        # growing at the interest rate every day, as the returns are, the average price the last day is the
        # start price grown, less each dividend grown from its day on: S g^T - sum of D g^(T - t)
        self.a_year_of_returns()
        self.run_lisp("(define fair (adjust-returns history (- (exp 0.04) 1)))")
        self.schedule([(60, 1.0), (150, 2.0)])
        growth = math.exp(0.04 / 252)
        expected = 100 * growth ** 252 - 1.0 * growth ** (252 - 60) - 2.0 * growth ** (252 - 150)
        finals = self.run_lisp("""(vector-mean (list->vector
            (map (lambda (i) (vector-ref (bootstrap-path fair 100 252 1 :seed i :dividends schedule) 251))
                 (iota 4000))))""")
        self.assertAlmostEqual(finals, expected, delta=0.8)               # (about 3 standard errors)
        self.assertGreater(abs(100 * growth ** 252 - expected), 2.9)      # (without them it would be 3 off)

    def test_what_a_schedule_must_be(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.run_lisp(self.ACTUAL)
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends actual)", "as dividend-schedule makes")
        self.schedule([(0, 1.0)])
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends schedule)", "must be a whole number, 1 or more")
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.run_lisp("""(define fraction (list (cons "day" (vector 1.5)) (cons "amount" (vector 1.0))))""")
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends fraction)", "must be a whole number, 1 or more")
        self.schedule([(2, -1.0)])
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends schedule)", "0 or more")
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends 5)", "not a table")


class TestVolatilityModel(LispTestCase):
    """lisp_investment_paths.py: volatility-model, volatility-history, volatility-forecast, and paths whose
    volatility starts at today's (bootstrap-path, bootstrap-days, and bootstrap-paths with :volatility)."""

    WEIGHTS = (0.02, 0.15, 0.85)            # up-day, down-day, and variance weights, for made-up histories

    @staticmethod
    def made_up_history(weights, days=4000, seed=3, volatility=0.2):
        """Daily log returns made by the model itself, with these weights and normal shocks: a history whose
        volatility changes as the model says, around `volatility` (for a year)."""
        up, down, variance_weight = weights
        long_run = volatility ** 2 / 252
        variance = long_run
        constant = long_run * (1 - variance_weight - (up + down) / 2)
        returns = []
        for shock in np.random.default_rng(seed).standard_normal(days):
            move = math.sqrt(variance) * shock
            returns.append(0.0003 + move)
            variance = constant + (down if move < 0 else up) * move * move + variance_weight * variance
        return np.array(returns)

    def make_returns(self, name, values, column="log-return"):
        self.env[lisp_core.Symbol(name)] = lisp_tables.make_table_value(
            [(column, lisp_vector_math.to_vector(np.array(values)))])

    def table_numbers(self, src):
        return {str(p.car): [float(x) for x in p.cdr.items] if p.cdr.items.dtype.kind == "f" else list(p.cdr.items)
                for p in lisp_core.pairs_to_list(self.run_lisp(src))}

    def stored(self, name):
        """A table of returns' log-return column, as the interpreter has it (float32, as float64)."""
        return np.array(self.run_lisp('(table-column %s "log-return")' % name).items, dtype=np.float64)

    # -- volatility-model -------------------------------------------------------

    def test_the_fit_finds_the_weights_a_history_was_made_with(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS))
        model = self.table_numbers("(volatility-model history)")
        self.assertEqual([str(x) for x in model["investment"]], ["log-return"])
        self.assertAlmostEqual(model["up-day-weight"][0], 0.02, delta=0.03)
        self.assertAlmostEqual(model["down-day-weight"][0], 0.15, delta=0.05)
        self.assertAlmostEqual(model["variance-weight"][0], 0.85, delta=0.04)
        self.assertAlmostEqual(model["persistence"][0], 0.935, delta=0.02)
        self.assertAlmostEqual(model["long-run-volatility"][0], 0.2, delta=0.02)
        symmetric = self.table_numbers("(volatility-model history :symmetric #t)")
        self.assertEqual(symmetric["up-day-weight"], symmetric["down-day-weight"])
        self.assertGreater(model["log-likelihood"][0], symmetric["log-likelihood"][0] + 10)    # down days do differ

    def test_the_model_s_numbers_are_what_its_weights_make_of_the_history(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS))
        model = self.table_numbers("(volatility-model history)")
        up, down, variance_weight = (model[name][0] for name in ("up-day-weight", "down-day-weight", "variance-weight"))
        moves = self.stored("history") - self.stored("history").mean()
        long_run = np.mean(moves ** 2)
        # the variances, with the constant the weights were fitted with (from the moves' down share) ...
        moves_down_share = np.sum(moves[moves < 0] ** 2) / np.sum(moves ** 2)
        constant = long_run * (1 - variance_weight - up * (1 - moves_down_share) - down * moves_down_share)
        variances, variance = [], long_run
        for move in moves:
            variances.append(variance)
            variance = constant + (down if move < 0 else up) * move * move + variance_weight * variance
        # ... times the number that makes the shocks' squares average 1
        size = np.mean(moves ** 2 / np.array(variances))
        shocks = moves / np.sqrt(np.array(variances) * size)
        down_share = np.sum(shocks[shocks < 0] ** 2) / np.sum(shocks ** 2)
        persistence = variance_weight + up * (1 - down_share) + down * down_share
        self.assertAlmostEqual(model["next-day-volatility"][0], math.sqrt(variance * size * 252), places=5)
        self.assertAlmostEqual(model["long-run-volatility"][0], math.sqrt(long_run * 252), places=5)
        self.assertAlmostEqual(model["down-share"][0], down_share, places=5)
        self.assertAlmostEqual(model["persistence"][0], persistence, places=5)
        self.assertAlmostEqual(model["half-life"][0], math.log(0.5) / math.log(persistence), places=3)
        self.assertEqual(model["days-per-year"], [252.0])

        history = self.table_numbers("(volatility-history history (volatility-model history))")
        self.assertEqual(list(history), ["log-return", "volatility", "shock"])
        self.assertTrue(np.allclose(history["shock"], shocks, atol=1e-5))
        self.assertTrue(np.allclose(np.array(history["volatility"]) / math.sqrt(252) * np.array(history["shock"]),
                                    moves, atol=1e-7))
        self.assertAlmostEqual(np.mean(np.array(history["shock"]) ** 2), 1.0, places=5)

    def test_a_year_of_365_days_and_a_history_with_dates(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS, days=300))
        a_year = self.table_numbers("(volatility-model history)")
        every_day = self.table_numbers("(volatility-model history :days-per-year 365)")
        self.assertAlmostEqual(every_day["long-run-volatility"][0] / a_year["long-run-volatility"][0],
                               math.sqrt(365 / 252), places=5)
        self.run_lisp('(define dated (make-table "date" (vector-append (make-vector 299 (date 2024 1 2)) '
                      '(vector (date 2024 1 3))) "log-return" (table-column history "log-return")))')
        self.assertShows('(vector-ref (table-column (volatility-history dated (volatility-model dated)) "date") 299)',
                         "2024-01-03")

    def test_what_the_model_won_t_take(self):
        self.make_returns("short", [0.01, -0.01] * 40)
        self.assertLispError("(volatility-model short)", "it takes at least 100 returns to fit a volatility model, not 80")
        self.make_returns("flat", [0.01] * 200)
        self.assertLispError("(volatility-model flat)", "the returns are all the same")
        self.make_returns("history", self.made_up_history(self.WEIGHTS, days=300))
        self.assertLispError("(volatility-model history :days-per-year 0)", ":days-per-year must be a number above 0")
        self.run_lisp('(define two (make-table "A" (table-column history "log-return") '
                      '"B" (* 2 (table-column history "log-return"))))')
        self.assertLispError("(volatility-history two (volatility-model two))",
                             "the table has the returns of 2 investments (A, B) -- pick one with table-select")
        self.assertLispError("(volatility-forecast (volatility-model two) 5)",
                             "the model must be one investment's, a table of one row")
        self.assertLispError("(volatility-history history (volatility-model two))",
                             "the volatility model has no row for log-return (it has A, B)")
        self.run_lisp('(define model (table-add-column (volatility-model history) "variance-weight" 0.99))')
        self.assertLispError("(volatility-history history model)", "its persistence must be less than 1")
        self.run_lisp('(define model (table-add-column (volatility-model history) "up-day-weight" -0.1))')
        self.assertLispError("(bootstrap-path history 100 5 1 :volatility model)", "weights must all be 0 or more")
        self.assertLispError("(bootstrap-path history 100 5 1 :start-volatility 0.2)",
                             ":start-volatility needs :volatility")
        self.assertLispError("(bootstrap-path history 100 5 1 :volatility (volatility-model history) :start-volatility 0)",
                             ":start-volatility must be a number above 0")

    # -- volatility-forecast ------------------------------------------------------

    def test_the_forecast_goes_from_the_next_day_s_volatility_to_the_long_run(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS))
        self.run_lisp("(define model (volatility-model history))")
        model = self.table_numbers("model")
        next_day, long_run, persistence = (model[name][0] for name in
                                           ("next-day-volatility", "long-run-volatility", "persistence"))
        self.assertAlmostEqual(self.run_lisp("(volatility-forecast model 1)"), next_day, places=6)
        # the average of the first 3 days' variances, each persistence of the last's difference from the long run
        days = [long_run ** 2 + persistence ** k * (0.3 ** 2 - long_run ** 2) for k in range(3)]
        self.assertAlmostEqual(self.run_lisp("(volatility-forecast model 3 :start-volatility 0.3)"),
                               math.sqrt(sum(days) / 3), places=6)
        forecast = [float(x) for x in self.run_lisp("(volatility-forecast model #(1 10 100 10000))").items]
        self.assertEqual(len(forecast), 4)
        self.assertAlmostEqual(forecast[-1], long_run, delta=0.001)
        self.run_lisp('(define memoryless (table-add-column model "persistence" 0.0))')
        self.assertAlmostEqual(self.run_lisp("(volatility-forecast memoryless 4 :start-volatility 0.3)"),
                               math.sqrt((0.3 ** 2 + 3 * long_run ** 2) / 4), places=6)
        self.assertLispError("(volatility-forecast model 0)", "days must be whole numbers, 1 or more")
        self.assertLispError('(volatility-forecast (table-add-column model "persistence" 1.0) 5)',
                             "persistence must be at least 0 and less than 1")

    def test_the_paths_are_as_volatile_as_the_forecast_says(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS))
        self.run_lisp("(define model (volatility-model history))")
        log_returns = self.stored("history")
        weights = lisp_investment_paths.VolatilityWeights(*(self.table_numbers("model")[name][0] for name in
                                                            lisp_investment_paths.WEIGHT_COLUMNS))
        paths, days = 20000, 10
        for start in (None, 0.4):
            moves = np.empty((paths, days))
            for i in range(paths):
                rows = lisp_investment_paths.days_drawn(len(log_returns), days, 1, i, "test")
                start_variance = None if start is None else start ** 2 / 252
                moves[i], _ = lisp_investment_paths.returns_with_volatility(log_returns, weights, rows, start_variance)
            moves -= moves.mean(axis=0)               # (each day's average, over the paths)
            realized = math.sqrt(np.mean(moves ** 2) * 252)
            forecast = self.run_lisp("(volatility-forecast model %d%s)" % (days, "" if start is None else
                                                                         " :start-volatility %s" % start))
            self.assertAlmostEqual(realized / forecast, 1.0, delta=0.01, msg=start)

    # -- paths ----------------------------------------------------------------------

    def test_a_model_with_no_memory_makes_the_same_paths_as_none(self):
        # weights of 0: every day's variance is the long-run variance, so every shock times it is the day's move
        self.make_returns("history", self.made_up_history(self.WEIGHTS, days=300))
        self.run_lisp('(define model (table-add-column (table-add-column (table-add-column (volatility-model history) '
                      '"up-day-weight" 0.0) "down-day-weight" 0.0) "variance-weight" 0.0))')
        plain = self.run_lisp("(bootstrap-path history 100 50 5 :seed 4)").items
        modeled = self.run_lisp("(bootstrap-path history 100 50 5 :seed 4 :volatility model)").items
        self.assertTrue(np.allclose(plain, modeled, rtol=1e-6))

    def test_bootstrap_days_shows_how_the_path_s_returns_were_made(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS, days=500))
        self.run_lisp("(define model (volatility-model history))")
        days = self.table_numbers("(bootstrap-days history 30 4 :seed 2 :volatility model :start-volatility 0.3)")
        self.assertEqual(list(days), ["day", "log-return", "shock", "volatility", "path-return"])
        self.assertAlmostEqual(days["volatility"][0], 0.3, places=6)
        model = self.table_numbers("model")
        up, down, variance_weight = (model[name][0] for name in lisp_investment_paths.WEIGHT_COLUMNS)
        moves = self.stored("history") - self.stored("history").mean()
        constant = np.mean(moves ** 2) * (1 - model["persistence"][0])
        variance = 0.3 ** 2 / 252
        for day in range(29):                 # each day's variance, from the day before's and its move
            move = math.sqrt(variance) * days["shock"][day]
            variance = constant + (down if move < 0 else up) * move * move + variance_weight * variance
            self.assertAlmostEqual(days["volatility"][day + 1], math.sqrt(variance * 252), places=4)
        prices = self.run_lisp("(bootstrap-path history 100 30 4 :seed 2 :volatility model :start-volatility 0.3)")
        self.assertTrue(np.allclose(prices.items, 100 * np.exp(np.cumsum(days["path-return"])), rtol=1e-5))
        starting = self.table_numbers("(bootstrap-days history 30 4 :seed 2 :volatility model)")
        self.assertAlmostEqual(starting["volatility"][0], model["next-day-volatility"][0], places=6)
        self.assertEqual(starting["shock"], days["shock"])

    def test_paths_with_a_volatility_model_grow_at_the_expected_return(self):
        self.make_returns("history", self.made_up_history(self.WEIGHTS))
        self.run_lisp("(define adjusted (adjust-returns history 0.3)) (define model (volatility-model history))")
        ends = [self.run_lisp("(vector-ref (bootstrap-path adjusted 100 63 1 :seed %d :volatility model "
                              ":start-volatility 0.5) 62)" % i) for i in range(3000)]
        error = np.std(ends) / math.sqrt(len(ends))
        self.assertAlmostEqual(np.mean(ends), 100 * 1.3 ** (63 / 252), delta=3 * error)

    def test_paths_of_several_investments_each_have_their_own_model(self):
        a = self.made_up_history(self.WEIGHTS, days=600, seed=1)
        b = self.made_up_history((0.1, 0.1, 0.8), days=600, seed=2, volatility=0.4)
        self.env[lisp_core.Symbol("both")] = lisp_tables.make_table_value(
            [("A", lisp_vector_math.to_vector(a)), ("B", lisp_vector_math.to_vector(b))])
        self.run_lisp("(define model (volatility-model both))")
        self.assertShows('(table-column model "investment")', '#("A" "B")')
        paths = self.table_numbers('(bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 20 3 :seed 9 '
                                   ':volatility model :start-volatility (list (cons "A" 0.1) (cons "B" 0.6)))')
        for name, price, start in (("A", 100, 0.1), ("B", 50, 0.6)):
            alone = self.run_lisp('(bootstrap-path (table-select both "%s") %d 20 3 :seed 9 :volatility model '
                                  ':start-volatility %s)' % (name, price, start))
            self.assertTrue(np.allclose(paths[name], alone.items), msg=name)
        self.assertLispError('(bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 20 3 :volatility model '
                             ':start-volatility (list (cons "A" 0.1)))', ":start-volatility has none for B")


class TestOptionCheck(LispTestCase):
    """option-payoffs, and lib/option_check.lsp, on made-up option chains priced as
    paths from a made-up history say they should be, with some options priced out of line."""

    SPOT = 100.0
    RATE = 0.04

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "option_check.lsp")')
        values = np.random.default_rng(5).normal(0.0, 0.2 / math.sqrt(252), 2500)    # a history with 20% volatility
        self.volatility = values.std(ddof=1) * math.sqrt(252)
        self.env[lisp_core.Symbol("returns")] = lisp_tables.make_table_value(
            [("log-return", lisp_vector_math.to_vector(values))])

    def make_chain(self, start, planted=None, dividend=None, trading_days=(25, 60, 120), name="chain", priced_at=None,
                   vol_shift=None, vol_scale=1.0, american=False):
        """A chain, as `chain`, of options on 100 at these numbers of trading days after start, priced as
        paths of this history say they should be (Black's formula, with the volatility the paths have in
        calendar time) -- times a number, for the options in `planted`, {(expiration number, type, strike):
        number}. dividend, a (date, amount), is paid before the expirations after it. priced_at is the price of
        the underlying when the options were priced, if it isn't the 100 the chain says it is. vol_shift is
        {expiration number: volatility added to every option's of that expiration}; vol_scale, a number
        every option's volatility is multiplied by. american prices them as options that can be exercised
        early (by lisp_options' binomial tree)."""
        rows = []
        for number, trading in enumerate(trading_days):
            expiration = lisp_calendar.trading_days_after(start, trading)
            calendar_days = (expiration - start).days
            T = calendar_days / 365
            vol = self.volatility * math.sqrt((trading / 252) / T) * vol_scale + (vol_shift or {}).get(number, 0.0)
            discount = math.exp(-self.RATE * T)
            present_value = 0.0
            if dividend and dividend[0] <= expiration:
                present_value = dividend[1] * math.exp(-self.RATE * (dividend[0] - start).days / 365)
            forward = ((priced_at or self.SPOT) - present_value) / discount
            for strike in range(80, 125, 5):
                for kind in ("Call", "Put"):
                    if american:
                        price = lisp_options.tree_price(kind == "Call", self.SPOT, strike, T, self.RATE, vol, 0.0,
                                                        np.zeros(0), np.zeros(0), 200, True)
                    else:
                        price = TestVolSmile.black(kind == "Call", forward, strike, T, discount, vol)
                    rows.append(("X%d%s%d" % (number, kind[0], strike), kind, float(strike), expiration, calendar_days,
                                 price * (planted or {}).get((number, kind, strike), 1.0)))
        columns = {
            "symbol": [lisp_core.LispString(r[0]) for r in rows], "type": [lisp_core.LispString(r[1]) for r in rows],
            "strike": [r[2] for r in rows],
            "expiration-date": [lisp_core.LispDate(r[3].year, r[3].month, r[3].day) for r in rows],
            "days-to-expiration": [r[4] for r in rows], "underlying-price": [self.SPOT] * len(rows),
            "bid": [r[5] * 0.985 for r in rows], "ask": [r[5] * 1.015 for r in rows], "mid": [r[5] for r in rows],
            "volume": [100.0] * len(rows), "open-interest": [100.0] * len(rows)}
        self.env[lisp_core.Symbol(name)] = lisp_tables.make_table_value(
            [(heading, lisp_tables.column_vector(values)) for heading, values in columns.items()])

    START = datetime.date(2026, 10, 5)
    CHECK = ("(define checked (check-option-chain chain returns :start-date (date 2026 10 5) :rate 0.04 "
             ":paths 3000 :block-size 1 :seed 7 %s))")
    PLANTED = {(1, "Call", 105): 1.3, (1, "Call", 110): 1.3, (2, "Put", 90): 0.7, (2, "Put", 95): 0.7}

    def column(self, name, table="checked"):
        return list(self.run_lisp('(table-column %s "%s")' % (table, name)).items)

    # -- option-payoffs -------------------------------------------------------

    def test_what_options_pay_on_average_over_the_paths(self):
        self.run_lisp("(define paths (list #(10.0 11.0 12.0) #(10.0 9.0 8.0) #(10.0 10.0 10.0) #(10.0 12.0 14.0)))")
        self.assertShows("(table-column-names (option-payoffs paths #(3) #(10) #(1)))", '("payoff" "payoff-error" "paths-paid")')
        # the options, and what each pays on the four paths:
        #   a call on day 3, struck at 10:  2, 0, 0, and 4
        #   a put on day 3, struck at 11:   0, 3, 1, and 0
        #   a call on day 1, struck at 10:  0, 0, 0, and 0
        #   a put on day 2, struck at 11:   0, 2, 1, and 0
        pays = [[2, 0, 0, 4], [0, 3, 1, 0], [0, 0, 0, 0], [0, 2, 1, 0]]
        answer = "(option-payoffs paths #(3 3 1 2) #(10 11 10 11) #(1 0 1 0))"
        for column, expected in (("payoff", [np.mean(p) for p in pays]),
                                 ("payoff-error", [np.std(p, ddof=1) / 2 for p in pays]),
                                 ("paths-paid", [sum(1 for x in p if x > 0) for p in pays])):
            with self.subTest(column=column):
                actual = self.run_lisp('(table-column %s "%s")' % (answer, column)).items
                np.testing.assert_allclose(np.array(actual, dtype=np.float64), expected, rtol=1e-5)

    def test_what_option_payoffs_wont_take(self):
        self.run_lisp("(define paths (list #(10.0 11.0 12.0) #(10.0 9.0 8.0)))")
        self.assertLispError("(option-payoffs 5 #(1) #(10) #(1))", "paths must be a list of vectors")
        self.assertLispError("(option-payoffs (list #(1.0 2.0)) #(1) #(10) #(1))", "at least two paths")
        self.assertLispError("(option-payoffs (list #(1.0 2.0) #(1.0)) #(1) #(10) #(1))", "the same length")
        self.assertLispError("(option-payoffs paths #(1 2) #(10) #(1))", "an element for each option")
        self.assertLispError("(option-payoffs paths #(4) #(10) #(1))", "from 1 to the paths' 3 days")
        self.assertLispError("(option-payoffs paths #(0) #(10) #(1))", "from 1 to the paths' 3 days")
        self.assertLispError("(option-payoffs paths #(1.5) #(10) #(1))", "whole number")

    # -- check-option-chain -----------------------------------------------------

    def test_the_options_priced_out_of_line_come_first_and_are_rich_or_cheap(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % "")
        symbols = self.column("symbol")
        self.assertEqual({str(x) for x in symbols[:4]}, {"X1C105", "X1C110", "X2P90", "X2P95"})
        signals = {str(symbol): str(signal) for symbol, signal in zip(symbols, self.column("signal"))}
        self.assertEqual({symbol: signal for symbol, signal in signals.items() if signal},
                         {"X1C105": "rich", "X1C110": "rich", "X2P90": "cheap", "X2P95": "cheap"})
        distances = [abs(float(x)) for x in self.column("iv-residual")]
        self.assertEqual(distances, sorted(distances, reverse=True))
        self.assertShows("(table-column-names checked)", '("symbol" "type" "expiration-date" "days-to-expiration" "strike" '
                         '"bid" "ask" "iv-bid" "iv-mid" "iv-ask" "model-price" "standard-error" "paths-paid" "model-iv" '
                         '"iv-residual" "iv-vs-expiration" "signal" "edge")')

    def test_options_priced_as_the_paths_say_are_not_out_of_line(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)         # within a volatility point
        self.assertEqual({str(x) for x in self.column("signal")}, {""})

    def test_the_edge_is_how_far_the_bid_or_ask_is_from_the_value(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % "")
        for symbol, signal, edge, bid, ask, price in zip(*[self.column(name) for name in
                                                          ("symbol", "signal", "edge", "bid", "ask", "model-price")]):
            if str(signal) == "rich":
                self.assertAlmostEqual(float(edge), float(bid) - float(price), places=4)
            elif str(signal) == "cheap":
                self.assertAlmostEqual(float(edge), float(price) - float(ask), places=4)
            else:
                self.assertEqual(float(edge), 0.0)

    def test_only_the_out_of_the_money_options_unless_asked_for_all(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        only = int(self.run_lisp("(table-row-count checked)"))
        # (the forwards are 100.3 to 101.8, and the strikes are 80, 85, ..., 120)
        for kind, strike in zip(self.column("type"), self.column("strike")):
            if str(kind) == "Call":
                self.assertGreaterEqual(float(strike), 105)
            else:
                self.assertLessEqual(float(strike), 100)
        self.run_lisp(self.CHECK.replace("(define checked", "(define everything") % ":out-of-the-money-only #f")
        self.assertGreater(int(self.run_lisp("(table-row-count everything)")), only)

    def test_the_options_the_paths_say_too_little_about_are_left_out(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":min-paths-paid 1")
        everything = int(self.run_lisp("(table-row-count checked)"))
        self.run_lisp(self.CHECK % ":min-paths-paid 600")
        self.assertLess(int(self.run_lisp("(table-row-count checked)")), everything)
        self.assertGreaterEqual(min(float(x) for x in self.column("paths-paid")), 600)

    def test_the_same_seed_gives_the_same_check(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        first = self.show("checked")
        self.run_lisp(self.CHECK % "")
        self.assertEqual(self.show("checked"), first)

    def test_dividends_the_last_year_had_are_taken_off_the_options_that_expire_after_their_dates(self):
        today = datetime.date.today()
        last_year = today - datetime.timedelta(days=100)
        ex_date = lisp_calendar.first_trading_day_from(lisp_time_series.months_later(last_year, 12))
        self.make_chain(today, dividend=(ex_date, 2.0), trading_days=(60, 130, 220))
        self.env[lisp_core.Symbol("actual")] = lisp_tables.make_table_value([
            ("ex-date", lisp_core.LispVector([lisp_core.LispDate(last_year.year, last_year.month, last_year.day)])),
            ("amount", lisp_vector_math.to_vector(np.array([2.0])))])
        check = ("(define checked (check-option-chain chain returns :rate 0.04 :paths 3000 :block-size 1 :seed 7 "
                 ":dividends %s))")
        self.run_lisp(check % "actual")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)
        self.assertEqual({str(x) for x in self.column("signal")}, {""})
        self.run_lisp(check % "'()")                       # without them the later options are out of line
        self.assertGreater(max(abs(float(x)) for x in self.column("iv-residual")), 0.02)

    def test_an_expiration_the_market_prices_for_more_volatility_is_out_of_line_by_the_same_amount_in_all_its_options(self):
        # the second expiration is priced 3 volatility points above what the paths say, all of it: iv-residual
        # shows it, and iv-vs-expiration doesn't, since that is for what's out of line with the rest of an expiration
        self.make_chain(self.START, vol_shift={1: 0.03}, planted={(1, "Call", 110): 1.3})
        self.run_lisp(self.CHECK % "")
        expirations = self.column("expiration-date")
        residuals = [float(x) for x in self.column("iv-residual")]
        relative = [float(x) for x in self.column("iv-vs-expiration")]
        symbols = [str(x) for x in self.column("symbol")]
        for symbol, residual, relative_residual in zip(symbols, residuals, relative):
            if symbol.startswith("X1") and symbol != "X1C110":
                self.assertAlmostEqual(residual, 0.03, delta=0.01)
                self.assertLess(abs(relative_residual), 0.01)
            elif symbol.startswith("X0") or symbol.startswith("X2"):
                self.assertLess(abs(residual), 0.01)
        index = symbols.index("X1C110")                    # and the one priced out of line in it is, in both
        self.assertGreater(residuals[index], 0.04)
        self.assertGreater(relative[index], 0.015)

    def test_the_middle_iv_residual_of_each_expiration(self):
        self.make_chain(self.START, vol_shift={1: 0.03})
        self.run_lisp(self.CHECK % "")
        self.run_lisp("(define by-expiration (option-check-expirations checked))")
        self.assertShows("(table-column-names by-expiration)",
                         '("expiration-date" "days-to-expiration" "options" "median-iv-residual" "rich" "cheap")')
        self.assertEqual(int(self.run_lisp("(table-row-count by-expiration)")), 3)
        medians = [float(x) for x in self.column("median-iv-residual", "by-expiration")]
        self.assertAlmostEqual(medians[0], 0.0, delta=0.01)
        self.assertAlmostEqual(medians[1], 0.03, delta=0.01)
        self.assertAlmostEqual(medians[2], 0.0, delta=0.01)
        self.assertEqual(sum(int(x) for x in self.column("options", "by-expiration")),
                         int(self.run_lisp("(table-row-count checked)")))

    def test_a_dividend_after_the_start_date_counts_though_today_is_after_it(self):
        # the chain is priced as of October 5, 2026, and the dividend, the last year's, comes again on October 6
        last_year = datetime.date(2025, 10, 6)
        self.make_chain(self.START, dividend=(datetime.date(2026, 10, 6), 2.0))
        self.env[lisp_core.Symbol("actual")] = lisp_tables.make_table_value([
            ("ex-date", lisp_core.LispVector([lisp_core.LispDate(last_year.year, last_year.month, last_year.day)])),
            ("amount", lisp_vector_math.to_vector(np.array([2.0])))])
        self.run_lisp(self.CHECK % ":dividends actual")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)

    def test_with_early_exercise_in_the_money_options_can_be_checked_too(self):
        self.make_chain(self.START, american=True)                # (prices of options that can be exercised early)
        self.run_lisp(self.CHECK % ":out-of-the-money-only #f")
        self.assertGreater(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)   # the in-the-money puts
        self.run_lisp(self.CHECK % ":out-of-the-money-only #f :early-exercise #t")
        residuals = [abs(float(x)) for x in self.column("iv-residual")]
        self.assertLess(max(residuals), 0.01)
        self.assertEqual({str(x) for x in self.column("signal")}, {""})
        premiums = {str(symbol): float(premium) for symbol, premium
                    in zip(self.column("symbol"), self.column("early-exercise"))}
        self.assertGreater(premiums["X2P110"], 0.3)              # a put in the money: worth exercising early
        self.assertLess(max(premium for symbol, premium in premiums.items() if "C" in symbol), 1e-6)  # calls: never

    def test_with_early_exercise_the_bid_and_ask_are_the_market_s_and_the_value_includes_it(self):
        self.make_chain(self.START, american=True)
        self.run_lisp(self.CHECK % ":out-of-the-money-only #f :early-exercise #t :expected-return (- (exp 0.04) 1)")
        market = {str(symbol): (float(bid), float(ask)) for symbol, bid, ask
                  in zip(*[list(self.run_lisp('(table-column chain "%s")' % name).items) for name in ("symbol", "bid", "ask")])}
        for symbol, bid, ask, price, error, expected in zip(*[self.column(name) for name in
                                                              ("symbol", "bid", "ask", "model-price", "standard-error",
                                                               "expected-value")]):
            self.assertAlmostEqual(float(bid), market[str(symbol)][0], places=4)
            self.assertAlmostEqual(float(ask), market[str(symbol)][1], places=4)
            self.assertAlmostEqual(float(expected), float(price), places=4)
            mid = (float(bid) + float(ask)) / 2                    # the value is the market's, to the paths' noise
            self.assertLess(abs(float(price) - mid), 3 * float(error) + 0.01 * mid)

    def test_the_time_to_expiration_is_counted_from_the_start_date(self):
        # a chain priced as of Monday, October 5, 2026, whose own days-to-expiration were counted from some day
        # long after that: the check counts from the start date, so it isn't thrown off
        self.make_chain(self.START)
        self.run_lisp('(define chain (table-add-column chain "days-to-expiration" 1))')
        self.run_lisp(self.CHECK % "")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)

    def test_an_underlying_price_that_does_not_fit_the_options_is_refused_unless_it_is_given_right(self):
        self.make_chain(self.START, priced_at=101.0)                  # (the underlying's price says 100)
        with self.assertRaises(lisp_core.LispError) as raised:
            self.run_lisp(self.CHECK % "")
        message = str(raised.exception)
        self.assertIn("don't fit the underlying's price of 100.00", message)
        self.assertIn("put-call parity", message)
        self.assertRegex(message, r"about 10[01]\.\d\d when they were made")      # the price they were made at: 101
        suggested = float(re.search(r"about ([\d.]+) when they were made", message).group(1))
        self.assertAlmostEqual(suggested, 101.0, delta=0.05)
        self.run_lisp(self.CHECK % ":start-price 101.0")             # (their price, as the message says)
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)
        self.run_lisp(self.CHECK % ":forward-tolerance 0.05")        # or a looser test
        self.assertGreater(int(self.run_lisp("(table-row-count checked)")), 0)

    def test_what_check_option_chain_wont_take(self):
        self.make_chain(self.START)
        self.assertLispError("(check-option-chain chain returns :start-date (date 2030 1 1))", "no option that expires after")
        self.assertLispError("(check-option-chain chain returns :start-date (date 2026 10 5) :max-vol-spread -1)",
                             "no option is liquid enough")
        self.assertLispError("(check-option-chain chain returns :start-date (date 2026 10 5) :paths 1)", "at least two paths")

    # -- :match-volatility and :expected-return ---------------------------------------

    def test_without_matching_the_market_s_higher_volatility_makes_every_option_rich(self):
        self.make_chain(self.START, vol_scale=1.3)               # the market has 30% more volatility than the history
        self.run_lisp(self.CHECK % "")
        self.assertAlmostEqual(float(self.run_lisp('(vector-median (table-column checked "iv-residual"))')),
                               0.06, delta=0.01)                 # 0.3 of 20 volatility points
        self.assertGreater(sum(1 for x in self.column("signal") if str(x) == "rich"), 0.7 * len(self.column("signal")))

    def test_matching_the_volatility_finds_the_market_s_overall_level(self):
        self.make_chain(self.START, planted=self.PLANTED, vol_scale=1.3)
        self.run_lisp(self.CHECK % ":match-volatility #t")
        scales = [float(x) for x in self.column("volatility-scale")]
        self.assertAlmostEqual(scales[0], 1.3, delta=0.03)
        self.assertEqual(len(set(scales)), 1)                    # (one number, in every row)
        self.assertAlmostEqual(float(self.run_lisp('(vector-median (table-column checked "iv-residual"))')),
                               0.0, delta=0.005)
        symbols = self.column("symbol")
        self.assertEqual({str(x) for x in symbols[:4]}, {"X1C105", "X1C110", "X2P90", "X2P95"})
        self.assertEqual({str(s) for s, signal in zip(symbols, self.column("signal")) if str(signal)},
                         {"X1C105", "X1C110", "X2P90", "X2P95"})

    def test_matching_a_chain_the_paths_already_fit_changes_nothing_much(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":match-volatility #t")
        self.assertAlmostEqual(float(self.column("volatility-scale")[0]), 1.0, delta=0.02)

    def test_there_must_be_an_option_to_match_the_volatility_with(self):
        self.make_chain(self.START)
        self.assertLispError("(check-option-chain chain returns :start-date (date 2026 10 5) :paths 500 :min-paths-paid 100000 "
                             ":match-volatility #t)", "no option to match the volatility with")

    def test_no_expected_return_no_expected_columns(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        names = [str(x) for x in lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))]
        self.assertNotIn("expected-value", names)
        self.assertNotIn("volatility-scale", names)

    def test_an_expected_return_above_the_interest_rate_raises_calls_and_lowers_puts(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":expected-return 0.15")
        names = [str(x) for x in lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))]
        self.assertEqual(names[-3:], ["expected-value", "favors", "expected-profit"])
        for kind, price, expected in zip(self.column("type"), self.column("model-price"), self.column("expected-value")):
            if str(kind) == "Call":
                self.assertGreaterEqual(float(expected), float(price))      # (the same paths, growing faster)
            else:
                self.assertLessEqual(float(expected), float(price))

    def test_the_expected_return_that_is_the_interest_rate_changes_nothing_so_favors_is_signal(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % ":expected-return (- (exp 0.04) 1)")
        for price, expected in zip(self.column("model-price"), self.column("expected-value")):
            self.assertAlmostEqual(float(expected), float(price), places=5)
        words = {"rich": "selling", "cheap": "buying", "": ""}
        for signal, favors in zip(self.column("signal"), self.column("favors")):
            self.assertEqual(str(favors), words[str(signal)])

    def test_with_matched_volatility_the_expected_return_paths_have_the_same_volatility(self):
        self.make_chain(self.START, vol_scale=1.3)
        self.run_lisp(self.CHECK % ":match-volatility #t :expected-return (- (exp 0.04) 1)")
        for price, expected in zip(self.column("model-price"), self.column("expected-value")):
            self.assertAlmostEqual(float(expected), float(price), places=5)

    def test_a_much_higher_expected_return_favors_buying_calls_and_selling_puts(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":expected-return 0.6")
        favors = [(str(kind), str(side)) for kind, side in zip(self.column("type"), self.column("favors"))]
        self.assertIn(("Call", "buying"), favors)
        self.assertIn(("Put", "selling"), favors)
        self.assertNotIn(("Call", "selling"), favors)
        self.assertNotIn(("Put", "buying"), favors)
        for side, profit, expected, bid, ask in zip(*[self.column(name) for name in
                                                       ("favors", "expected-profit", "expected-value", "bid", "ask")]):
            if str(side) == "buying":
                self.assertAlmostEqual(float(profit), float(expected) - float(ask), places=4)
            elif str(side) == "selling":
                self.assertAlmostEqual(float(profit), float(bid) - float(expected), places=4)
            else:
                self.assertEqual(float(profit), 0.0)

    def test_showing_the_volatility_scale_and_the_expected_profit(self):
        self.make_chain(self.START, vol_scale=1.3)
        self.run_lisp(self.CHECK % ":match-volatility #t :expected-return 0.3")
        self.run_lisp("(show-option-check checked :count 3)")
        shown = self.printed()
        self.assertIn("The paths' volatility was multiplied by 1.", shown)
        self.assertIn("The 3 options with the most expected profit if the underlying earns its expected return", shown)

    # -- starting at today's volatility -----------------------------------------------

    def test_with_a_volatility_model_the_paths_start_at_today_s_volatility(self):
        # options priced at the history's volatility; paths that start at 10% and go back toward it, with a
        # half-life of about 14 days, value the options of each expiration at the volatility the model forecasts
        self.make_chain(self.START)
        self.run_lisp('(define model (table-add-column (table-add-column (table-add-column (volatility-model returns) '
                      '"up-day-weight" 0.05) "down-day-weight" 0.05) "variance-weight" 0.9))')
        self.run_lisp(self.CHECK % ":volatility model :start-volatility 0.1 :out-of-the-money-only #f")
        log_returns = np.array(self.run_lisp('(table-column returns "log-return")').items, dtype=np.float64)
        persistence = lisp_investment_paths.filtered_history(
            log_returns.tobytes(), lisp_investment_paths.VolatilityWeights(0.05, 0.05, 0.9)).persistence
        long_run = np.mean((log_returns - log_returns.mean()) ** 2) * 252
        for number, trading in enumerate((25, 60, 120)):
            expiration = lisp_calendar.trading_days_after(self.START, trading)
            T = (expiration - self.START).days / 365
            forecast = math.sqrt(long_run + (0.1 ** 2 - long_run) * (1 - persistence ** trading)
                                 / (trading * (1 - persistence)))
            date = "(date %d %d %d)" % (expiration.year, expiration.month, expiration.day)
            model_iv = self.run_lisp('(vector-median (table-column (table-where checked "expiration-date" %s) '
                                     '"model-iv"))' % date)
            self.assertAlmostEqual(model_iv, forecast * math.sqrt((trading / 252) / T), delta=0.005, msg=trading)
        self.assertAlmostEqual(float(self.column("start-volatility")[0]), 0.1, places=6)
        self.assertAlmostEqual(float(self.column("long-run-volatility")[0]), math.sqrt(long_run), places=5)

    def test_volatility_t_fits_a_model_and_show_option_check_says_where_it_started(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":volatility #t :match-volatility #t")
        self.run_lisp("(define model (volatility-model returns))")
        scale = float(self.column("volatility-scale")[0])
        self.assertAlmostEqual(float(self.column("start-volatility")[0]),
                               scale * self.run_lisp('(vector-ref (table-column model "next-day-volatility") 0)'),
                               places=5)
        self.assertAlmostEqual(float(self.column("long-run-volatility")[0]),
                               scale * self.run_lisp('(vector-ref (table-column model "long-run-volatility") 0)'),
                               places=5)
        self.run_lisp("(show-option-check checked :count 3)")
        shown = self.printed()
        self.assertRegex(shown, r"The paths' volatility started at \d+\.\d% and went back toward \d+\.\d%, "
                                r"as the volatility model says\.")
        self.assertNotIn("start-volatility", shown)
        self.run_lisp(self.CHECK % "")
        self.assertNotIn("start-volatility", [str(x) for x in
                                              lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))])

    # -- check-option-prices and show-option-check --------------------------------

    def test_check_option_prices_gets_the_chain_the_prices_and_the_dividends(self):
        today = datetime.date.today()
        self.make_chain(today, planted=self.PLANTED)
        dates, price, closes = [], 100.0, []
        values = np.random.default_rng(5).normal(0.0, 0.2 / math.sqrt(252), 2500)
        day = lisp_calendar.trading_days_after(today, 0)
        while not lisp_calendar.is_trading_day(day):
            day -= datetime.timedelta(days=1)
        for value in values[::-1]:
            dates.append(lisp_core.LispDate(day.year, day.month, day.day))
            closes.append(price)
            price *= math.exp(-value)
            day = lisp_calendar.trading_days_after(day, -1)
        prices = lisp_tables.make_table_value([("date", lisp_core.LispVector(dates[::-1])),
                                               ("close", lisp_vector_math.to_vector(np.array(closes[::-1])))])
        asked = []
        self.env[lisp_core.Symbol("tastytrade-option-chain")] = lambda creds, symbol, months, strikes: (
            asked.append(("chain", str(creds), str(symbol), months, strikes)) or self.env[lisp_core.Symbol("chain")])
        self.env[lisp_core.Symbol("schwab-price-history")] = lambda creds, symbol: (
            asked.append(("prices", str(creds), str(symbol))) or prices)
        self.env[lisp_core.Symbol("alpha-vantage-dividends")] = lambda creds, symbol: (
            asked.append(("dividends", str(creds), str(symbol))) or lisp_tables.make_table_value([
                ("ex-date", lisp_core.LispVector([])), ("amount", lisp_vector_math.to_vector(np.array([], dtype=np.float64)))]))
        self.run_lisp('(define checked (check-option-prices "creds.json" "XYZ" :months 4 :strikes 9 :paths 3000 '
                      ':block-size 1 :seed 7))')
        self.assertEqual(sorted(asked), [("chain", "creds.json", "XYZ", 4, 9), ("dividends", "creds.json", "XYZ"),
                                         ("prices", "creds.json", "XYZ")])
        self.assertEqual({str(x) for x in self.column("symbol")[:4]}, {"X1C105", "X1C110", "X2P90", "X2P95"})
        self.run_lisp('(define checked (check-option-prices "creds.json" "XYZ" :paths 2000 :block-size 1 :seed 7 '
                      ':expected-return 0.08 :match-volatility #t :early-exercise #t))')
        names = [str(x) for x in lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))]
        self.assertIn("expected-value", names)
        self.assertIn("volatility-scale", names)
        self.assertIn("early-exercise", names)

    def test_showing_the_check(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % "")
        self.run_lisp("(show-option-check checked :count 3)")
        shown = self.printed()
        self.assertIn("The middle iv-residual, the market's volatility less the paths', in each expiration:", shown)
        self.assertIn("The 3 options furthest from the paths' values", shown)
        self.assertIn("The 3 furthest from the middle iv-residual of their expiration", shown)
        self.assertIn("Options whose bid is above the paths' value (rich) or ask below it (cheap):", shown)
        for symbol in ("X1C105", "X2P95"):
            self.assertIn(symbol, shown)


class TestPortfolio(LispTestCase):
    """lisp_portfolio.py: several investments' returns, paths of them, a portfolio's value, covariance, and
    mean-variance weights."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define a (make-table "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4) (date 2024 1 5))
                                "log-return" #(0.01 -0.02 0.03 0.0)))
          (define b (make-table "date" (vector (date 2024 1 3) (date 2024 1 4) (date 2024 1 5) (date 2024 1 8))
                                "log-return" #(0.005 0.01 -0.01 0.02)))
          (define both (combine-returns (list (cons "A" a) (cons "B" b))))""")

    def pairs(self, src):
        return {str(p.car): float(p.cdr) for p in lisp_core.pairs_to_list(self.run_lisp(src))}

    def test_returns_are_lined_up_on_the_dates_they_all_have(self):
        self.assertShows("both", '(("date" . #(2024-01-03 2024-01-04 2024-01-05)) ("A" . #(-0.02 0.03 0.0)) '
                                 '("B" . #(0.005 0.01 -0.01)))')
        self.assertLispError('(combine-returns (list (cons "A" a) (cons "A" b)))', "two of them are named A")
        self.assertLispError('(combine-returns (list (cons "both" both)))', "the returns of more than one investment")
        self.assertLispError("(combine-returns 5)", "expected a list of (name . returns)")

    def test_each_investment_gets_its_own_expected_return(self):
        self.run_lisp('(define adjusted (adjust-returns both (list (cons "A" 0.10) (cons "B" 0.02))))')
        for name, rate in (("A", 0.10), ("B", 0.02)):
            growth = float(self.run_lisp('(vector-mean (vector-exp (table-column adjusted "%s")))' % name))
            self.assertAlmostEqual(growth, (1 + rate) ** (1 / 252), places=7)
        self.assertShows('(table-column adjusted "date")', "#(2024-01-03 2024-01-04 2024-01-05)")
        self.assertLispError('(adjust-returns both (list (cons "A" 0.10)))', "has none for B")

    def test_paths_of_several_investments_copy_the_same_days(self):
        self.run_lisp("""(define twice (make-table "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4))
                                                   "X" #(0.01 -0.02 0.03) "Y" #(0.02 -0.04 0.06)))""")
        paths = self.run_lisp('(bootstrap-paths twice (list (cons "X" 100) (cons "Y" 100)) 40 2 :seed 5)')
        columns = dict(lisp_tables.table_columns(paths, "test"))
        x = np.log(np.array(columns["X"].items, dtype=float) / 100)
        y = np.log(np.array(columns["Y"].items, dtype=float) / 100)
        np.testing.assert_allclose(y, 2 * x, atol=1e-5)          # Y's return is twice X's, every day
        self.assertEqual(list(columns["day"].items), list(range(1, 41)))

    def test_the_days_of_a_path_are_shown_by_bootstrap_days(self):
        days = dict(lisp_tables.table_columns(self.run_lisp("(bootstrap-days both 30 2 :seed 9)"), "test"))
        paths = dict(lisp_tables.table_columns(
            self.run_lisp('(bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 30 2 :seed 9)'), "test"))
        np.testing.assert_allclose(np.array(paths["A"].items, dtype=float),
                                   100 * np.exp(np.cumsum(np.array(days["A"].items, dtype=float))), rtol=1e-5)
        self.assertTrue(all(isinstance(d, lisp_core.LispDate) for d in days["date"].items))

    def test_a_dividend_schedule_is_for_the_investment_it_names(self):
        self.run_lisp('(define schedule (list (cons "day" (vector 1)) (cons "amount" (vector 1.0))))')
        plain = dict(lisp_tables.table_columns(
            self.run_lisp('(bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 3 1 :seed 1)'), "t"))
        paid = dict(lisp_tables.table_columns(self.run_lisp(
            '(bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 3 1 :seed 1 :dividends (list (cons "B" schedule)))'), "t"))
        self.assertEqual(list(paid["A"].items), list(plain["A"].items))
        self.assertAlmostEqual(float(paid["B"].items[0]), float(plain["B"].items[0]) - 1.0, places=4)
        self.assertLispError('(bootstrap-paths both (list (cons "A" 100)) 3 1)', "start-prices has none for B")
        self.assertLispError('(bootstrap-paths both (list (cons "A" 100) (cons "B" 50)) 3 1 :dividends (list (cons "C" schedule)))',
                             "for the investments A, B")

    def test_a_portfolio_bought_and_held_or_rebalanced(self):
        self.run_lisp('(define prices (make-table "A" #(100.0 110.0 121.0) "B" #(100.0 100.0 100.0)))')
        weights = '(list (cons "A" 0.5) (cons "B" 0.5))'
        # bought and held: 0.5 of A and 0.5 of B, at the first prices
        np.testing.assert_allclose(np.array(self.run_lisp("(portfolio-value prices %s)" % weights).items, dtype=float),
                                   [1.0, 1.05, 1.105], rtol=1e-6)
        # put back to half and half after each day: the second day starts from 1.05, half in A
        np.testing.assert_allclose(np.array(self.run_lisp("(portfolio-value prices %s :rebalance 1)" % weights).items,
                                            dtype=float), [1.0, 1.05, 1.05 * 1.05], rtol=1e-6)
        np.testing.assert_allclose(np.array(self.run_lisp(
            '(portfolio-value prices %s :start-prices (list (cons "A" 50) (cons "B" 100)) :start-value 100)' % weights).items,
            dtype=float), [150.0, 160.0, 171.0], rtol=1e-6)
        self.assertLispError('(portfolio-value prices (list (cons "A" 0.5) (cons "B" 0.6)))', "add up to")
        self.assertLispError('(portfolio-value prices (list (cons "A" 0.5) (cons "C" 0.5)))', "no column named 'C'")

    def test_covariance_and_correlation_are_numpy_s(self):
        data = np.array([[-0.02, 0.03, 0.0], [0.005, 0.01, -0.01]])
        cov = dict(lisp_tables.table_columns(self.run_lisp("(covariance-matrix both)"), "t"))
        self.assertEqual([str(n) for n in cov["investment"].items], ["A", "B"])
        np.testing.assert_allclose(np.column_stack([np.array(cov[n].items, dtype=float) for n in ("A", "B")]),
                                   np.cov(data) * 252, rtol=1e-5)
        monthly = dict(lisp_tables.table_columns(self.run_lisp("(covariance-matrix both :days-per-year 12)"), "t"))
        self.assertAlmostEqual(float(monthly["A"].items[0]), np.cov(data)[0, 0] * 12, places=6)
        corr = dict(lisp_tables.table_columns(self.run_lisp("(correlation-matrix both)"), "t"))
        self.assertAlmostEqual(float(corr["B"].items[0]), np.corrcoef(data)[0, 1], places=5)
        self.assertAlmostEqual(float(corr["A"].items[0]), 1.0, places=6)

    COVARIANCE = [[0.04, 0.006, -0.01], [0.006, 0.09, 0.02], [-0.01, 0.02, 0.0225]]

    def make_covariance(self, matrix=None, names=("X", "Y", "Z")):
        matrix = np.array(matrix or self.COVARIANCE)
        self.env[lisp_core.Symbol("cov")] = lisp_portfolio.matrix_table(list(names), matrix)
        return np.array(matrix, dtype=np.float32).astype(float)        # (as a vector stores it)

    def test_minimum_variance_weights_are_the_formula_s(self):
        matrix = self.make_covariance()
        inverse_ones = np.linalg.solve(matrix, np.ones(3))
        expected = inverse_ones / inverse_ones.sum()
        w = self.pairs("(minimum-variance-weights cov)")
        np.testing.assert_allclose([w["X"], w["Y"], w["Z"]], expected, atol=1e-9)
        self.assertAlmostEqual(float(self.run_lisp("(portfolio-volatility (minimum-variance-weights cov) cov)")),
                               math.sqrt(expected @ matrix @ expected), places=9)

    def test_long_only_weights_are_the_best_with_none_below_0(self):
        matrix = self.make_covariance([[0.04, 0.057, 0.0], [0.057, 0.09, 0.0], [0.0, 0.0, 0.09]])
        unconstrained = self.pairs("(minimum-variance-weights cov)")
        self.assertLess(min(unconstrained.values()), 0)                   # (selling one short helps here)
        w = self.pairs("(minimum-variance-weights cov :long-only #t)")
        weights = np.array([w["X"], w["Y"], w["Z"]])
        self.assertAlmostEqual(weights.sum(), 1.0, places=12)
        self.assertGreaterEqual(weights.min(), 0.0)
        best = min(np.array(g) @ matrix @ np.array(g)                       # every weighting on a fine grid
                   for g in ((i / 200, j / 200, 1 - i / 200 - j / 200) for i in range(201) for j in range(201 - i)))
        self.assertLessEqual(weights @ matrix @ weights, best + 1e-12)

    def test_long_only_weights_are_the_best_of_every_subset_of_investments(self):
        # The best long-only weights are the formula's on some subset of the investments (the others 0): so try
        # every subset, keep the answers with no weight below 0, and take the best -- for random problems in which
        # several investments are left out and let back in along the way.
        generator = np.random.default_rng(11)
        names = ("A", "B", "C", "D", "E", "F")
        # (the last: one of the few in which C, left out on the way, has to be let back in)
        problems = [(generator.normal(0, 0.2, (n, n)), n) for n in (5, 6) * 6]
        for trial in range(13):
            if trial < 12:
                factors, n = problems[trial]
                matrix = self.make_covariance(
                    (factors @ factors.T / n + np.diag(generator.uniform(0.001, 0.02, n))).tolist(), names=names[:n])
                mu = generator.normal(0.06, 0.05, n)
                risk_aversion = float(generator.choice([0.5, 2.0, 8.0]))
            else:
                n = 3
                matrix = self.make_covariance([[0.070427, -0.03459, 0.005215], [-0.03459, 0.051586, 0.020359],
                                               [0.005215, 0.020359, 0.020649]], names=names[:n])
                mu, risk_aversion = np.array([0.000653, 0.19507, 0.194107]), 0.5
            Q, c = risk_aversion * matrix, mu

            def objective(w):
                return w @ Q @ w / 2 - c @ w
            best = None
            for size in range(1, n + 1):
                for subset in itertools.combinations(range(n), size):
                    w, _ = lisp_portfolio.solve_on(list(subset), Q, c)
                    if w.min() >= -1e-12 and (best is None or objective(w) < objective(best)):
                        best = w
            expected = " ".join('(cons "%s" %r)' % (names[i], float(mu[i])) for i in range(n))
            found = self.pairs("(mean-variance-weights (list %s) cov %r :long-only #t)" % (expected, risk_aversion))
            weights = np.array([found[names[i]] for i in range(n)])
            with self.subTest(trial=trial):
                self.assertGreaterEqual(weights.min(), 0.0)
                self.assertAlmostEqual(weights.sum(), 1.0, places=12)
                self.assertAlmostEqual(objective(weights), objective(best), places=10)

    def test_mean_variance_weights(self):
        matrix = self.make_covariance()
        expected = '(list (cons "X" 0.06) (cons "Y" 0.12) (cons "Z" 0.04))'
        mu = np.array([0.06, 0.12, 0.04])
        w = self.pairs("(mean-variance-weights %s cov 4)" % expected)
        weights = np.array([w["X"], w["Y"], w["Z"]])
        # the best: 4 cov w - mu is the same for every investment, and the weights add to 1
        slopes = 4 * matrix @ weights - mu
        np.testing.assert_allclose(slopes, slopes[0], atol=1e-9)
        self.assertAlmostEqual(weights.sum(), 1.0, places=12)
        cautious = self.pairs("(mean-variance-weights %s cov 1e6)" % expected)
        least = self.pairs("(minimum-variance-weights cov)")
        for name in "XYZ":
            self.assertAlmostEqual(cautious[name], least[name], places=4)
        bold = self.pairs("(mean-variance-weights %s cov 0.01 :long-only #t)" % expected)
        self.assertAlmostEqual(bold["Y"], 1.0, places=9)                  # all in the highest expected return

    def test_what_the_portfolio_functions_wont_take(self):
        self.make_covariance([[0.04, 0.04], [0.04, 0.04]], names=("X", "Y"))
        self.assertLispError("(minimum-variance-weights cov)", "singular")
        self.make_covariance()
        self.assertLispError('(mean-variance-weights (list (cons "X" 0.1)) cov 2)', "expected-returns has none for Y, Z")
        self.assertLispError('(mean-variance-weights (list (cons "X" 0.1) (cons "Y" 0.1) (cons "Z" 0.1)) cov 0)',
                             "risk-aversion must be a number above 0")
        self.assertLispError("(minimum-variance-weights both)", "no column named 'investment'")


if __name__ == "__main__":
    unittest.main()
