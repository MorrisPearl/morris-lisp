"""The Python tools around the rate model (term_structure/): the callable bond pricer, the mortgage spread, the model's own
demo, and the GUI (run in a child process, with no screen), all on the paths that start on the market's curve."""

import os
import re
import subprocess
import textwrap

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase
from test_yield_curves import NOW, TREASURY_1990, TREASURY_2025, TREASURY_2026, TREASURY_2027   # the Treasury's files, faked

TERM_STRUCTURE = os.path.join(HERE, "..", "term_structure")
sys.path.insert(0, TERM_STRUCTURE)
import mortgage_spread  # noqa: E402
import term_structure_model as model  # noqa: E402

FORWARDS = 0.04 + 0.015 * (1 - np.exp(-np.arange(1, 361) / 60.0))


def present_value_by_hand(rates, oas, term_years, coupon_rate, call_years, call_price, face=100):
    """The callable bond's price along one path of short rates (the curve's own forward rates, if there is no volatility), worked
    out month by month: coupons before the call date, then the smaller of the call price and what the bond is worth then,
    discounted back."""
    months, call_month = term_years * 12, call_years * 12
    discount = [1.0]
    for k in range(months):
        discount.append(discount[-1] / (1 + (rates[k] + oas) / 12))
    coupon = face * coupon_rate / 2
    payment = lambda m: coupon + (face if m == months else 0.0)
    before = sum(coupon * discount[m] for m in range(6, call_month + 1, 6))
    continuation = sum(payment(m) * discount[m] / discount[call_month] for m in range(call_month + 6, months + 1, 6))
    return before + min(continuation, call_price) * discount[call_month]


class TestTheCallableBond(unittest.TestCase):

    def price(self, **keywords):
        arguments = dict(sigma1=0.0, sigma2=0.0, term_years=10, coupon_rate=0.05, call_years=3, call_price=100.0, oas=0.0075,
                         n_paths=4)
        arguments.update(keywords)
        return model.price_callable_bond_mc(FORWARDS, **arguments)

    def test_with_no_volatility_it_is_the_discounted_cash_flows_on_the_curve(self):
        for call_price in (100.0, 101.0, 1000.0):       # called, called, never called
            self.assertAlmostEqual(self.price(call_price=call_price),
                                   present_value_by_hand(FORWARDS, 0.0075, 10, 0.05, 3, call_price), places=9)

    def test_with_volatility_it_is_the_average_of_the_prices_along_the_paths_of_the_model(self):
        _, rates, _ = model.simulate_rate_paths(FORWARDS, 0.012, 0.007, 10, 20, seed=9, a=1.4, b=0.2)
        expected = np.mean([present_value_by_hand(path, 0.0075, 10, 0.05, 3, 100.0) for path in rates])
        got = self.price(sigma1=0.012, sigma2=0.007, n_paths=20, seed=9, a=1.4, b=0.2)
        self.assertAlmostEqual(got, expected, places=9)
        self.assertNotAlmostEqual(got, self.price(sigma1=0.007, sigma2=0.012, n_paths=20, seed=9, a=1.4, b=0.2), places=3)

    def test_an_odd_number_of_paths_is_rounded_up(self):
        self.assertAlmostEqual(self.price(sigma1=0.01, sigma2=0.01, n_paths=5, seed=2),
                               self.price(sigma1=0.01, sigma2=0.01, n_paths=6, seed=2), places=12)

    def test_a_bond_that_is_never_called_is_worth_the_same_at_any_volatility_to_within_convexity(self):
        plain = self.price(call_price=1e9)
        noisy = self.price(call_price=1e9, sigma1=0.01, sigma2=0.01, n_paths=4000)
        self.assertAlmostEqual(noisy / plain, 1.0, delta=0.01)

    def test_a_higher_spread_is_a_lower_price(self):
        prices = [self.price(oas=oas, sigma1=0.01, sigma2=0.01, n_paths=1000) for oas in (0.0, 0.005, 0.01, 0.02)]
        self.assertTrue(np.all(np.diff(prices) < 0))

    def test_the_call_makes_it_worth_less_the_more_the_rates_move(self):
        flat = self.price(oas=0.0, call_price=100.0)
        noisy = self.price(oas=0.0, call_price=100.0, sigma1=0.01, sigma2=0.015, n_paths=4000)
        self.assertLess(noisy, flat)

    def test_it_takes_the_models_speeds_and_the_seed(self):
        same = [self.price(sigma1=0.01, sigma2=0.01, n_paths=200, seed=3) for _ in range(2)]
        self.assertEqual(same[0], same[1])
        self.assertNotEqual(same[0], self.price(sigma1=0.01, sigma2=0.01, n_paths=200, seed=4))
        self.assertNotEqual(same[0], self.price(sigma1=0.01, sigma2=0.01, n_paths=200, seed=3, a=3.0))

    def test_a_bond_called_at_its_maturity_is_not_called(self):
        with self.assertRaises(ValueError) as caught:
            self.price(call_years=10)
        self.assertIn("strictly before", str(caught.exception))

    def test_a_thirty_year_bond_on_a_thirty_year_curve_is_priced(self):
        self.assertGreater(self.price(term_years=30, call_years=5, sigma1=0.01, sigma2=0.01, n_paths=50), 0)


class TestTheMortgageSpread(unittest.TestCase):

    def test_the_spread_is_the_mortgage_rate_less_the_curves_ten_year_yield(self):
        flat = np.full(360, 0.05)
        observed = (datetime.date(2026, 10, 15), 0.0675)
        with mock.patch.object(mortgage_spread, "fetch_current_mortgage_rate", lambda path, series: observed):
            spread, rate, model_rate, day = mortgage_spread.compute_sofr_mortgage_spread(flat, credentials_path="unused")
        expected = model.curve_par_yield(flat, 0.0, 10.0)
        self.assertAlmostEqual(model_rate, expected, places=12)
        self.assertAlmostEqual(spread, 0.0675 - expected, places=12)
        self.assertEqual((rate, day), (0.0675, datetime.date(2026, 10, 15)))

    def test_with_that_spread_the_first_month_of_the_paths_is_the_mortgage_rate(self):
        with mock.patch.object(mortgage_spread, "fetch_current_mortgage_rate", lambda path, series: (None, 0.0675)):
            spread = mortgage_spread.compute_sofr_mortgage_spread(FORWARDS, credentials_path="unused")[0]
        _, _, _, mortgage = model.simulate_mortgage_rate_paths(FORWARDS, 0.01, 0.01, 1, 4, spread, seed=1)
        np.testing.assert_allclose(mortgage[:, 0], 0.0675, rtol=1e-12)

    def test_another_tenor_can_be_asked_for(self):
        with mock.patch.object(mortgage_spread, "fetch_current_mortgage_rate", lambda path, series: (None, 0.0675)):
            spread = mortgage_spread.compute_sofr_mortgage_spread(FORWARDS, credentials_path="unused", tenor_years=5)[0]
        self.assertAlmostEqual(spread, 0.0675 - model.curve_par_yield(FORWARDS, 0.0, 5.0), places=12)


class TestTheRatePathsExample(LispTestCase):
    """examples/rate_paths_example.lsp, on the Treasury's curve of the yield-curve tests (its download faked)."""

    def setUp(self):
        super().setUp()
        files = {"daily-treasury-rates.csv/%d/all" % year: text
                 for year, text in ((1990, TREASURY_1990), (2025, TREASURY_2025), (2026, TREASURY_2026), (2027, TREASURY_2027))}

        def download(url, cache_hours, headers, name, *more, **keywords):
            for part, text in files.items():
                if part in str(url):
                    return text.encode()
            raise lisp_core.LispError("%s: couldn't download %s: HTTP 404" % (name, url))

        for target, replacement in ((lisp_http, ("download", download)), (lisp_clock, ("now", lambda: NOW))):
            patcher = mock.patch.object(target, replacement[0], replacement[1])
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_example(self):
        self.run_lisp('(load "autoloads.lsp")')          # (as the interpreter does when it starts)
        with in_a_temporary_folder() as folder:
            lisp_core.run_file(os.path.join(EXAMPLES, "rate_paths_example.lsp"), self.env)
            for chart in ("rate_paths_curve.png", "rate_paths_fan.png"):
                self.assertTrue(is_a_png(os.path.join(folder, chart)), chart)
        return self.printed()

    def percents(self, line):
        return [float(x) for x in re.findall(r"([-+]?\d+\.\d+)%", line)]

    def test_it_takes_a_path_apart_and_what_it_shows_agrees_with_itself(self):
        shown = self.run_example()
        lines = {line[:2]: line for line in shown.splitlines() if re.match(r"\d\. ", line)}
        self.assertEqual(sorted(lines), ["1.", "2.", "3.", "4.", "5.", "6."])
        # with no volatility, the short rate in two years is the curve's forward rate; and the yield is the curve's par yield then
        first, second = shown.split("2. ")[1].split("\n")[:2]
        short, forward = self.percents(first)
        self.assertEqual(short, forward)
        yield_in_2_years, par_yield = self.percents(second)
        self.assertEqual(yield_in_2_years, par_yield)
        # the short rate on the path in month 36 is the first month of the curve then
        short_on_path, first_month, ten_year = self.percents(lines["5."])
        self.assertEqual(short_on_path, first_month)
        # the paths' average discount factor is the curve's, to a few basis points
        curve_rate, paths_rate = self.percents(lines["6."])[:2]
        self.assertAlmostEqual(curve_rate, paths_rate, delta=0.1)
        self.assertIn("[chart] The curve 3 years from now", shown)

    def test_the_curve_it_starts_from_is_the_treasurys(self):
        shown = self.run_example()
        two, five, ten, thirty = self.percents(shown.split("1. ")[1].split("\n")[0])
        self.assertEqual((two, five, ten), (4.77, 4.91, 5.10))          # the par yields of the fake file's 2026-10-15
        self.assertAlmostEqual(thirty, 5.43, places=2)


class TestSofrForwardCurve(LispTestCase):
    """sofr-forward-curve, from either kind of row: tastytrade-futures-curve-rows's or sofr-calibration-data's."""

    def test_both_kinds_of_row_make_the_same_curve(self):
        # Two SR3 futures: the quarter ending 3 months out at 4% (a price of 96), the next one at 3.5% (96.5).
        self.run_lisp("""
          (define tastytrade-rows (list (list (date 2027 2 1) "SR3G7" 91 96.0) (list (date 2027 5 1) "SR3K7" 183 96.5)))
          (define calibration-rows (list (list "SR3G7" 0 3 0.04) (list "SR3K7" 3 6 0.035)))
          (define from-tastytrade (sofr-forward-curve tastytrade-rows))
          (define from-calibration (sofr-forward-curve calibration-rows))""")
        self.assertShows("(equal? from-tastytrade from-calibration)", "#t")
        self.assertShows("(table-column-names from-tastytrade)", '("months" "discount" "forward")')   # as curve-forward-rates
        self.assertShows("(table-row-count from-tastytrade)", "360")
        self.assertShows('(vector-ref (table-column from-tastytrade "months") 0)', "1")
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column from-tastytrade "discount") 2)'), (1 + 0.04 / 12) ** -3,
                               places=12)
        forwards = self.run_lisp('(table-column from-tastytrade "forward")').items
        self.assertAlmostEqual(forwards[0], 0.04, places=10)       # the first quarter's rate, each month of it
        self.assertAlmostEqual(forwards[2], 0.04, places=10)
        self.assertAlmostEqual(forwards[3], 0.035, places=10)      # then the second's
        self.assertAlmostEqual(forwards[359], 0.035, places=10)    # and flat after the last future

    def test_errors(self):
        self.assertLispError("(sofr-forward-curve '())", "sofr-forward-curve: curve-rows is empty")
        self.assertLispError('(sofr-forward-curve (list (list "SR3G7" 0 3)))', "each row should be")


class TestWhatWasRemoved(LispTestCase):

    def test_the_builtins_that_the_curve_functions_replaced_are_gone(self):
        for name in ("sofr-simulate-rate-paths", "sofr-extend-curve-with-treasury",
                     "sofr-bootstrap-curve",          # sofr-forward-curve takes its rows now
                     "calibrate-to-sofr-options",     # calibrate-rate-model fits the SOFR options with the notes'
                     "sofr-calibrate-model"):
            self.assertLispError("(%s 1 2 3)" % name, name)

    def test_the_builtins_that_were_renamed_are_under_their_new_names_only(self):
        renamed = {"sofr-simulate-curve-paths": "simulate-rate-paths",
                   "sofr-simulate-factor-paths": "simulate-rate-factors", "sofr-curve-on-date": "rate-curve-on-date",
                   "sofr-par-yield": "curve-par-yield", "sofr-calibrate-jointly": "calibrate-rate-model",
                   "sofr-calibrate-note-options": "calibrate-to-note-options",
                   "sofr-note-option-comparison": "note-option-comparison"}
        for old, new in renamed.items():
            self.assertLispError("(%s 1 2 3)" % old, old)                       # no longer a name
            self.assertTrue(callable(self.run_lisp(new)), new)                  # the symbol is bound to the builtin


class TestTheModelsOwnDemo(unittest.TestCase):

    def test_the_demo_runs_and_its_paths_start_on_its_curve(self):
        done = subprocess.run([sys.executable, "term_structure_model.py"], cwd=TERM_STRUCTURE, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        for expected in ("fitted sigma2", "Model price vs. market price", "The 10-year par yield starts at 4.300%",
                         "Callable bond example"):
            self.assertIn(expected, done.stdout)


class TestTheGui(unittest.TestCase):
    """The window, with no screen (Qt's offscreen platform), in a child process so that no other test sees its application."""

    SCRIPT = textwrap.dedent('''
        import sys
        sys.path.insert(0, %r)
        from PyQt6.QtWidgets import QApplication
        import term_structure_gui as gui
        app = QApplication([])
        window = gui.TermStructureWindow()
        window._on_bootstrap_clicked()
        asked = []
        simulate = gui.tsm.simulate_rate_paths
        gui.tsm.simulate_rate_paths = lambda *arguments, **keywords: (asked.append(keywords), simulate(*arguments, **keywords))[1]
        for radio in (window.treasury_rate_radio, window.mortgage_rate_radio, window.sofr_rate_radio):
            radio.setChecked(True)
            window._on_simulate_clicked()
            axes = window.figure.axes[0]
            print(axes.get_title().replace("\\n", " | "), len(axes.lines), round(float(axes.lines[0].get_ydata()[0]), 3))
        window.curve_source, window.sofr_a = "SOFR (live, tastytrade)", 2.5       # as if its SOFR curve had been calibrated
        window._on_simulate_clicked()
        print("speeds", asked[0]["a"], asked[-1]["a"])
        window._on_price_bond_clicked()
        print("bond priced")
        ''') % TERM_STRUCTURE

    def setUp(self):
        try:
            import PyQt6, matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("PyQt6/matplotlib not installed")

    def test_every_chart_is_drawn_from_the_curve_and_the_bond_is_priced(self):
        done = subprocess.run([sys.executable, "-c", self.SCRIPT], capture_output=True, text=True, timeout=600,
                              env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        lines = [line for line in done.stdout.splitlines() if not line.startswith("qt.")]
        self.assertEqual(len(lines), 5, done.stdout)
        self.assertIn("Simulated Treasury rate paths (10y par yield)", lines[0])
        self.assertTrue(lines[0].endswith(" 4.3"))                  # the first month's 10-year yield is the curve's: 4.3%
        self.assertIn("Simulated mortgage-rate paths (10y + 175bp)", lines[1])
        self.assertTrue(lines[1].endswith(" 6.05"))                 # and the mortgage rate 175bp over it
        self.assertIn("Simulated SOFR (short-end) rate paths", lines[2])
        self.assertEqual(lines[3], "speeds 1.0 2.5")          # the default speed, and a calibrated one
        self.assertEqual(lines[4], "bond priced")
