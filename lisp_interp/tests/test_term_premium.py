"""lisp_term_premium.py and the slope functions of lib/yield_curves.lsp: Treasury yields split into the rates the
market expects, convexity and a term premium (term-premium-decomposition, the New York Fed's ACM model); the slope
of the curve in the same pieces (yield-slope-decomposition); and the Fed's TIPS curve, with the slope as real
yields plus inflation compensation (tips-curve, yield-slope-inflation).

The Fed's files are faked: a made-up history of Svensson curves, in the form of the Fed's file, whose level, slope
and curvature wander month to month as a real curve's do. How the model's numbers compare with the ones the New
York Fed publishes is in "What the slope of the curve is made of", in doc/lisp_paths_manual.md: that needs the
network, which the tests never use."""

import datetime

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_term_premium


def month_end(year, month):
    following = datetime.date(year + month // 12, month % 12 + 1, 1)
    return following - datetime.timedelta(days=1)


def made_up_history(months=240, seed=1):
    """A made-up history of the Fed's curve: a day at each month's end from January 2000, a day in the middle
    of each month, and a last day, 2020-01-15, that isn't a month's end. The level, slope and curvature of the
    curve (beta0, beta1, beta2), where the curvature is (tau1) and a second hump (beta3) each wander back toward
    an average; the second hump is NA for the first two years, as the Fed's file has it before 1980. Returns
    the rows (date, beta0 ... tau2), in percent and years."""
    rng = np.random.default_rng(seed)
    level, slope, curvature, hump, bend = 5.0, -1.5, 0.0, 0.0, 1.8
    rows = []
    for i in range(months):
        level = 5.0 + 0.97 * (level - 5.0) + rng.normal(0, 0.25)
        slope = -1.5 + 0.93 * (slope + 1.5) + rng.normal(0, 0.35)
        curvature = 0.85 * curvature + rng.normal(0, 0.5)
        hump = 0.8 * hump + rng.normal(0, 0.4)
        bend = 1.8 + 0.7 * (bend - 1.8) + rng.normal(0, 0.15)      # where the curvature is: tau1
        year, month = 2000 + i // 12, i % 12 + 1
        second = (None, None) if i < 24 else (hump, 9.0)
        middle = datetime.date(year, month, 15)
        rows.append((middle, level + 0.05, slope, curvature, second[0], bend, second[1]))
        rows.append((month_end(year, month), level, slope, curvature, second[0], bend, second[1]))
    rows.append((datetime.date(2020, 1, 15), level + 0.1, slope - 0.1, curvature, hump, bend, 9.0))
    return rows


def gsw_file(rows):
    """The rows in the form of the Fed's file: notes, then the header, then a row a day, NA where there's no number."""
    lines = ['"Note: made up for the tests."', "", "Date,BETA0,BETA1,BETA2,BETA3,SVENY10,TAU1,TAU2"]
    for day, *numbers in rows:
        text = ["NA" if x is None else repr(float(x)) for x in numbers]
        lines.append(",".join([day.isoformat()] + text[:4] + ["5.0"] + text[4:]))
    return "\n".join(lines) + "\n"


# The Fed's TIPS file: notes, then the header; real zero rates (TIPSY) and inflation compensation (BKEVEN), in
# percent, and other columns that tips-curve leaves out. The 20-year has no number on the first day.
TIPS = '''"Note: made up for the tests."

Date,BETA0,BETA1,BKEVEN02,BKEVEN10,BKEVEN20,BKEVENF02,TIPSF02,TIPSPY10,TIPSY02,TIPSY10,TIPSY20,TAU1
2026-11-12,1.0,2.0,2.10,2.30,NA,2.2,1.4,2.1,1.40,2.00,NA,3.0
2026-11-13,1.0,2.0,2.00,2.25,2.40,2.2,1.4,2.1,1.50,2.10,2.50,3.0
'''


class TermPremiumTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.rows = made_up_history()
        files = {"feds200628.csv": gsw_file(self.rows), "feds200805.csv": TIPS}

        def download(url, cache_hours, headers, name, *more, **keywords):
            for part, text in files.items():
                if part in str(url):
                    return text.encode()
            raise lisp_core.LispError("%s: couldn't download %s: HTTP 404" % (name, url))
        patcher = mock.patch.object(lisp_http, "download", download)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run_lisp('(load "yield_curves.lsp")')
        self.run_lisp("(define fed (gsw-curve))")

    def column(self, table, name):
        return np.array(self.run_lisp('(table-column %s "%s")' % (table, name)).items, dtype=float)

    def dates(self, table):
        return [d.date for d in self.run_lisp('(table-column %s "date")' % table).items]


class TestTheDecomposition(TermPremiumTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("(define parts (term-premium-decomposition fed))")

    def test_the_columns_and_rows(self):
        self.assertShows("(table-column-names parts)",
                         '("date" "years" "yield" "fitted" "expected" "convexity" "term-premium" "error")')
        # each month's last day, and the last day, which isn't one: four maturities each
        days = self.dates("parts")
        self.assertEqual(len(days), (240 + 1) * 4)
        self.assertEqual(days[:4], [datetime.date(2000, 1, 31)] * 4)
        self.assertEqual(days[-8:], [datetime.date(2019, 12, 31)] * 4 + [datetime.date(2020, 1, 15)] * 4)
        np.testing.assert_allclose(self.column("parts", "years")[:8], [0.25, 2, 5, 10] * 2)

    def test_the_pieces_add_up_to_the_yield(self):
        total = sum(self.column("parts", name) for name in ("expected", "convexity", "term-premium", "error"))
        np.testing.assert_allclose(total, self.column("parts", "yield"), atol=1e-12)

    def test_the_yield_is_the_feds_zero_rate(self):
        """On the last day, the yield column is the Svensson curve of that day's six numbers."""
        expected = self.run_lisp("(svensson-zero-rates (gsw-parameters fed) (vector 0.25 2 5 10))")
        np.testing.assert_allclose(self.column("parts", "yield")[-4:], np.array(expected.items, dtype=float), rtol=1e-12)

    def test_five_factors_fit_the_curve(self):
        """A curve of level, slope and curvature (and a hump) is five factors' worth: the model's yields, worked
        out bond by bond from the 1-month rate, are the curve's, to a hundredth of a percentage point."""
        self.assertLess(np.abs(self.column("parts", "error")).max(), 1e-4)

    def test_fewer_factors_fit_it_less_well(self):
        self.run_lisp("(define two (term-premium-decomposition fed :factors 2))")
        self.assertGreater(np.abs(self.column("two", "error")).max(), 1e-3)

    def test_convexity_is_small_negative_grows_with_maturity_and_is_the_same_each_day(self):
        """In this model rates are as uncertain on one day as on any other, so convexity depends only on
        the maturity."""
        convexity = self.column("parts", "convexity").reshape(-1, 4)
        self.assertTrue((convexity < 0).all())
        self.assertTrue((np.diff(convexity[0]) < 0).all())
        np.testing.assert_allclose(convexity, np.tile(convexity[0], (len(convexity), 1)), atol=1e-12)
        self.assertGreater(convexity[0, 3], -0.01)

    def test_a_one_month_bond_has_no_term_premium(self):
        """Held for its one month, a 1-month bond has no risk to be paid for: its term premium is 0, and its
        expected rate is the model's short rate, which is close to the 1-month rate of the curve."""
        self.run_lisp("(define month (term-premium-decomposition fed :years (/ 1 12)))")
        np.testing.assert_allclose(self.column("month", "term-premium"), 0, atol=1e-15)
        np.testing.assert_allclose(self.column("month", "expected"), self.column("month", "yield"), atol=5e-4)

    def test_expected_rates_head_back_to_the_average(self):
        """When the short rate is far above its average, the rates expected over 10 years are below it."""
        self.run_lisp("(define month (term-premium-decomposition fed :years (list (/ 1 12) 10)))")
        expected = self.column("month", "expected").reshape(-1, 2)
        high = expected[:, 0] > np.mean(expected[:, 0]) + 1.5 * np.std(expected[:, 0])
        self.assertTrue(high.any())
        self.assertTrue((expected[high, 1] < expected[high, 0]).all())

    def test_years_daily_and_start_date(self):
        self.run_lisp("(define tens (term-premium-decomposition fed :years 10 :daily #t :start-date \"2005-01-01\"))")
        days = self.dates("tens")
        self.assertEqual(days[0], datetime.date(2005, 1, 15))
        self.assertEqual(len(days), 15 * 24 + 1)            # every day: two a month, and the last
        np.testing.assert_allclose(self.column("tens", "years"), 10)
        self.run_lisp("(define some (term-premium-decomposition fed :years (vector 1 3)))")
        np.testing.assert_allclose(self.column("some", "years")[:2], [1, 3])

    def test_a_python_list_of_years_in_any_order_is_sorted_and_without_repeats(self):
        self.assertEqual(lisp_term_premium._maturities_in_months(
            lisp_core.list_to_pairs([10, 0.25, 10]), "test"), [3, 120])

    def test_mistakes(self):
        self.assertLispError("(term-premium-decomposition fed :years 15)", "from 1/12 to 10 years, not 15")
        self.assertLispError("(term-premium-decomposition fed :years 0.1)", "whole number of months")
        self.assertLispError("(term-premium-decomposition fed :factors 0)", ":factors is a whole number from 1 to 10")
        self.assertLispError("(term-premium-decomposition fed :weight 2)", ":weight isn't an option")
        self.assertLispError('(term-premium-decomposition fed :start-date "2017-01-01")',
                             "needs at least 60 months of the Fed's curve to be fitted to, and there are 37")
        self.assertLispError('(term-premium-decomposition (make-table "date" (vector 1)))', "it has no beta0")


class TestTheSlope(TermPremiumTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("(define parts (term-premium-decomposition fed))")
        self.run_lisp("(define slope (yield-slope-decomposition parts))")

    def test_it_is_the_long_maturitys_pieces_less_the_short_ones(self):
        self.assertShows("(table-column-names slope)", '("date" "slope" "expected" "convexity" "term-premium" "error")')
        self.assertEqual(len(self.dates("slope")), 241)
        by_maturity = {name: self.column("parts", name).reshape(-1, 4) for name in
                       ("yield", "expected", "convexity", "term-premium", "error")}
        np.testing.assert_allclose(self.column("slope", "slope"), by_maturity["yield"][:, 3] - by_maturity["yield"][:, 0])
        for name in ("expected", "convexity", "term-premium", "error"):
            np.testing.assert_allclose(self.column("slope", name), by_maturity[name][:, 3] - by_maturity[name][:, 0])
        total = sum(self.column("slope", name) for name in ("expected", "convexity", "term-premium", "error"))
        np.testing.assert_allclose(total, self.column("slope", "slope"), atol=1e-12)

    def test_other_maturities(self):
        self.run_lisp("(define two-ten (yield-slope-decomposition parts :long 10 :short 2))")
        by_maturity = self.column("parts", "yield").reshape(-1, 4)
        np.testing.assert_allclose(self.column("two-ten", "slope"), by_maturity[:, 3] - by_maturity[:, 1])
        self.assertLispError("(yield-slope-decomposition parts :long 7)", "the table has no maturity of 7 years")


class TestTipsAndInflation(TermPremiumTestCase):

    def test_the_tips_curve_has_real_yields_and_inflation_compensation(self):
        self.run_lisp("(define tips (tips-curve))")
        self.assertShows("(table-column-names tips)",
                         '("date" "breakeven-2" "breakeven-10" "breakeven-20" "real-2" "real-10" "real-20")')
        np.testing.assert_allclose(self.column("tips", "real-10"), [0.02, 0.021])
        self.assertTrue(np.isnan(self.column("tips", "breakeven-20")[0]))
        self.run_lisp('(define later (tips-curve :start-date "2026-11-13"))')
        self.assertEqual(self.dates("later"), [datetime.date(2026, 11, 13)])

    def test_the_slope_is_real_plus_inflation(self):
        self.run_lisp("(define parts (yield-slope-inflation (tips-curve)))")
        self.assertShows("(table-column-names parts)", '("date" "slope" "real" "inflation")')
        np.testing.assert_allclose(self.column("parts", "real"), [0.006, 0.006])
        np.testing.assert_allclose(self.column("parts", "inflation"), [0.002, 0.0025])
        np.testing.assert_allclose(self.column("parts", "slope"), [0.008, 0.0085])
        # a day without a number at a maturity is left out
        self.run_lisp("(define long (yield-slope-inflation (tips-curve) :long 20 :short 10))")
        self.assertEqual(self.dates("long"), [datetime.date(2026, 11, 13)])
        self.assertLispError("(yield-slope-inflation (tips-curve) :short 1)", "whole numbers of years from 2 to 20, not 1")
