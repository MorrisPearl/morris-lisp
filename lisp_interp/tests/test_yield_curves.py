"""lib/yield_curves.lsp: the Treasury's par yield curve and the Federal Reserve's fitted curve, read from their files
(faked here, in their own forms); the zero curve that par yields give, and the forward rates of a zero curve."""

import datetime

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


# The Treasury's file for a year, as it is written: the newest day first, dates as MM/DD/YYYY, yields in percent,
# and only the maturities the Treasury published that year.
TREASURY_2026 = '''Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
10/15/2026,4.17,4.15,4.19,4.28,4.35,4.35,4.49,4.77,4.85,4.91,5.00,5.10,5.48,5.43
10/14/2026,4.11,4.15,4.15,4.28,4.36,4.37,4.53,4.82,4.92,5.00,5.09,5.19,5.57,5.52
10/13/2026,4.10,4.15,4.15,4.26,4.32,4.34,4.48,4.79,4.90,5.00,5.11,5.21,5.60,5.56
'''
TREASURY_2025 = '''Date,"1 Mo","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
12/31/2025,4.30,4.31,4.32,4.33,4.34,4.40,4.60,4.70,4.80,4.90,5.00,5.40,5.30
12/30/2025,4.29,4.30,4.31,4.32,4.33,4.39,4.59,4.69,4.79,4.89,4.99,5.39,5.29
'''
TREASURY_1990 = '''Date,"3 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","30 Yr"
12/31/1990,6.63,6.73,6.82,7.15,7.40,7.68,8.00,8.08,8.26
12/28/1990,6.64,6.85,6.91,7.25,7.48,7.78,8.08,8.14,8.31
'''
TREASURY_2027 = 'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'

# The Fed's file: notes, then the header, then a row a day, with NA where the Fed gives no number. The row of
# 2026-10-09 is the Fed's own, as published, for the columns here: percents, and the six numbers of the curve.
GSW = '''"Note: This is not an official Federal Reserve statistical release, and it is subject to revision."

Series,Compounding Convention,Mnemonic(s)
Zero-coupon yield,Continuously Compounded,SVENYXX
Par yield,Coupon-Equivalent,SVENPYXX
Instantaneous forward rate,Continuously Compounded,SVENFXX
One-year forward rate,Coupon-Equivalent,SVEN1FXX
Parameters,N/A,BETA0 to TAU2

Date,BETA0,BETA1,BETA2,BETA3,SVEN1F01,SVEN1F04,SVEN1F09,SVENF01,SVENF05,SVENF10,SVENF30,SVENPY10,SVENY01,SVENY02,SVENY05,SVENY10,SVENY30,TAU1,TAU2
1961-06-14,3.91760612208239,-1.2779552459795,-1.94939709504669,0,3.8067,3.9562,NA,3.5492,3.9176,NA,NA,NA,3.7,3.8,3.9,NA,NA,1.5,3
2026-10-08,0.5,3.8,4.9,16.0,5.07,5.2,5.9,4.87,5.18,5.88,4.83,5.26,4.49,4.75,4.98,5.25,5.64,1.9,15.7
2026-10-09,2.22056170437177e-14,3.92393143398782,4.93949592518691,17.0123153461406,5.0888,5.2226,5.9035,4.8753,5.186,5.8903,4.8251,5.2692,4.4929,4.7593,4.9865,5.2514,5.6402,1.93134743096879,15.7551507296816
'''

NOW = datetime.datetime(2026, 10, 15, 11, 0)


def svensson_zero(parameters, t):
    """The Svensson curve's zero rate at t years, in plain Python."""
    beta0, beta1, beta2, beta3, tau1, tau2 = parameters
    s1, s2 = (1 - math.exp(-t / tau1)) / (t / tau1), (1 - math.exp(-t / tau2)) / (t / tau2)
    return beta0 + beta1 * s1 + beta2 * (s1 - math.exp(-t / tau1)) + beta3 * (s2 - math.exp(-t / tau2))


def svensson_forward(parameters, t):
    beta0, beta1, beta2, beta3, tau1, tau2 = parameters
    return (beta0 + beta1 * math.exp(-t / tau1) + beta2 * (t / tau1) * math.exp(-t / tau1)
            + beta3 * (t / tau2) * math.exp(-t / tau2))


# The Fed's numbers for 2026-10-09 (the curve's, as decimals; the others are percents)
FED_PARAMETERS = [2.22056170437177e-16, 0.0392393143398782, 0.0493949592518691, 0.170123153461406,
                  1.93134743096879, 15.7551507296816]


class YieldCurvesTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.files = {}                                   # what each year's file, and the Fed's, says
        self.asked = []
        for year, text in ((1990, TREASURY_1990), (2025, TREASURY_2025), (2026, TREASURY_2026), (2027, TREASURY_2027)):
            self.files["daily-treasury-rates.csv/%d/all" % year] = text
        self.files["feds200628.csv"] = GSW
        patcher = mock.patch.object(lisp_http, "download", self.download)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(lisp_clock, "now", lambda: NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run_lisp('(load "yield_curves.lsp")')

    def download(self, url, cache_hours, headers, name, *more, **keywords):
        self.asked.append((str(url), cache_hours))
        for part, text in self.files.items():
            if part in str(url):
                return text.encode()
        raise lisp_core.LispError("%s: couldn't download %s: HTTP 404" % (name, url))

    def numbers(self, source):
        """A Lisp vector's values, as a numpy array."""
        return np.array(self.run_lisp(source).items, dtype=float)


class TestTreasuryParCurve(YieldCurvesTestCase):

    def test_the_curve_of_a_year_as_decimals_with_a_column_for_each_maturity(self):
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 2026 1 1) :end-date (date 2026 12 31)))")
        self.assertShows("(table-column-names curve)",
                         '("date" "1m" "1.5m" "2m" "3m" "4m" "6m" "1y" "2y" "3y" "5y" "7y" "10y" "20y" "30y")')
        self.assertShows('(table-column curve "date")', "#(2026-10-13 2026-10-14 2026-10-15)")      # the oldest first
        np.testing.assert_allclose(self.numbers('(table-column curve "10y")'), [0.0521, 0.0519, 0.0510], atol=1e-6)
        np.testing.assert_allclose(self.numbers('(table-column curve "1m")'), [0.0410, 0.0411, 0.0417], atol=1e-6)
        self.assertEqual(self.asked, [("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                                       "daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"
                                       "&field_tdr_date_value=2026&page&_format=csv", 12)])
        self.asked.clear()
        self.run_lisp("(define two (treasury-par-curve :start-date (date 2025 1 1) :end-date (date 2026 12 31)))")
        self.assertEqual([url for url, _ in self.asked],
                         ["https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                          "%d/all?type=daily_treasury_yield_curve&field_tdr_date_value=%d&page&_format=csv" % (year, year)
                          for year in (2025, 2026)])

    def test_a_maturity_the_treasury_did_not_publish_is_missing_and_years_go_together(self):
        self.run_lisp('(define curve (treasury-par-curve :start-date "2025-12-31" :end-date "2026-10-14"))')
        self.assertShows('(table-column curve "date")', "#(2025-12-31 2026-10-13 2026-10-14)")      # (the text dates, and the range)
        np.testing.assert_allclose(self.numbers('(table-column curve "1.5m")'), [np.nan, 0.0415, 0.0415], atol=1e-6)
        # (2025's file has no 1.5 month)
        np.testing.assert_allclose(self.numbers('(table-column curve "30y")'), [0.0530, 0.0556, 0.0552], atol=1e-6)
        self.assertEqual([url.split("/")[-2] for url, _ in self.asked], ["2025", "2026"])

    def test_a_year_of_1990_has_the_maturities_of_that_year(self):
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 1990 12 28) :end-date (date 1990 12 31)))")
        self.assertShows('(table-column curve "date")', "#(1990-12-28 1990-12-31)")
        np.testing.assert_allclose(self.numbers('(table-column curve "10y")'), [0.0814, 0.0808], atol=1e-6)
        self.assertShows('(table-column curve "1m")', "#(nan nan)")                 # (no month, no 20 years, then)
        self.assertShows('(table-column curve "20y")', "#(nan nan)")
        np.testing.assert_allclose(self.numbers('(table-column curve "3m")'), [0.0664, 0.0663], atol=1e-6)

    def test_this_year_so_far_is_the_default_and_a_year_with_no_days_yet_is_empty(self):
        self.files["daily-treasury-rates.csv/2026/all"] = TREASURY_2026 + "01/01/2026,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0,3.0\n"
        self.run_lisp("(define curve (treasury-par-curve))")
        self.assertShows('(table-column curve "date")', "#(2026-01-01 2026-10-13 2026-10-14 2026-10-15)")        # (from January 1)
        self.assertEqual(len(self.asked), 1)
        self.asked.clear()
        with mock.patch.object(lisp_clock, "now", lambda: datetime.datetime(2027, 1, 2, 9, 0)):
            self.run_lisp("(define curve (treasury-par-curve :cache-hours 0))")
        self.assertShows("(table-row-count curve)", "0")
        self.assertEqual(self.asked[0][1], 0)                                          # (:cache-hours is passed on)

    def test_what_it_will_not_take(self):
        self.assertLispError("(treasury-par-curve :start-date (date 2026 10 15) :end-date (date 2026 10 14))",
                             ":start-date is after :end-date")
        self.assertLispError("(treasury-par-curve :start-date (date 1989 6 1))", "the Treasury's curve begins in 1990")
        self.assertLispError("(treasury-par-curve :start-date (date 2024 1 1) :end-date (date 2026 1 1))", "HTTP 404")


class TestFromParYieldsToZeroRates(YieldCurvesTestCase):

    def zeros(self, years, yields):
        self.run_lisp("(define zeros (par-curve-zeros (vector %s) (vector %s)))"
                      % (" ".join(map(str, years)), " ".join(map(str, yields))))
        return {name: self.numbers('(table-column zeros "%s")' % name) for name in ("years", "par", "discount", "zero")}

    def test_a_flat_curve_of_semiannual_par_yields_has_discount_factors_that_are_powers(self):
        """A par bond of 4% pays 2 every 6 months: each coupon is discounted at 2%, so D(n half-years) is 1.02^-n."""
        zeros = self.zeros([0.5, 5, 30], [0.04, 0.04, 0.04])
        np.testing.assert_allclose(zeros["years"], np.arange(1, 61) * 0.5)
        np.testing.assert_allclose(zeros["discount"], 1.02 ** -np.arange(1, 61), rtol=1e-6)
        np.testing.assert_allclose(zeros["zero"], 2 * math.log(1.02), rtol=1e-5)
        np.testing.assert_allclose(zeros["par"], 0.04)

    def test_each_discount_factor_is_found_from_the_ones_before_it_by_hand(self):
        """Par yields of 2% at 6 months, 3% at a year, and 4% at 18 months: D(.5) = 1/1.01; the year's bond has a
        coupon of 1.5 at 6 months and 101.5 at a year: D(1) = (1 - .015 D(.5)) / 1.015; and the 18 months', with
        coupons of 2: D(1.5) = (1 - .02 (D(.5) + D(1))) / 1.02."""
        zeros = self.zeros([0.5, 1, 1.5], [0.02, 0.03, 0.04])
        d1 = 1 / 1.01
        d2 = (1 - 0.015 * d1) / 1.015
        d3 = (1 - 0.02 * (d1 + d2)) / 1.02
        np.testing.assert_allclose(zeros["discount"], [d1, d2, d3], rtol=1e-6)
        np.testing.assert_allclose(zeros["zero"], [-math.log(d1) / 0.5, -math.log(d2), -math.log(d3) / 1.5], rtol=1e-5)
        self.assertAlmostEqual(d1, 0.990099, places=6)
        self.assertAlmostEqual(d2, 0.970590, places=6)              # (0.98514851 / 1.015)

    def test_a_bill_of_less_than_six_months_is_priced_from_its_simple_yield(self):
        zeros = self.zeros([0.25, 0.5, 1], [0.04, 0.04, 0.05])
        self.assertEqual(len(zeros["years"]), 3)                            # the 3 months, and the 6 and 12
        np.testing.assert_allclose(zeros["years"], [0.25, 0.5, 1.0])
        np.testing.assert_allclose(zeros["discount"][0], 1 / (1 + 0.04 * 0.25), rtol=1e-6)
        np.testing.assert_allclose(zeros["zero"][0], -math.log(1 / 1.01) / 0.25, rtol=1e-5)
        np.testing.assert_allclose(zeros["discount"][1], 1 / 1.02, rtol=1e-6)    # (6 months: the same by either way)

    def test_the_par_yield_between_maturities_is_on_the_line_and_flat_beyond(self):
        zeros = self.zeros([1, 3], [0.03, 0.05])
        self.assertEqual(len(zeros["years"]), 6)                            # (6 months, then to 3 years)
        np.testing.assert_allclose(zeros["par"], [0.03, 0.03, 0.035, 0.04, 0.045, 0.05], atol=1e-7)   # (flat before the first: 6 months)

    def test_every_par_bond_the_zeros_come_from_is_worth_par(self):
        """The curve of 2026-10-15: every maturity on the grid, with its par yield (the Treasury's, or between), has
        a price of 1 at the discount factors, the coupons being half the yield every six months."""
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 2026 10 15)))")
        self.run_lisp("(define zeros (treasury-zero-curve curve))")
        years, par, discount = (self.numbers('(table-column zeros "%s")' % n) for n in ("years", "par", "discount"))
        semiannual = years >= 0.5
        d, c, y = discount[semiannual], par[semiannual], years[semiannual]
        self.assertEqual(len(d), 60)
        for n in range(1, 61):
            price = c[n - 1] / 2 * d[:n - 1].sum() + (1 + c[n - 1] / 2) * d[n - 1]
            self.assertAlmostEqual(price, 1.0, places=5, msg="%d half-years" % n)
        # and the zero rates are the ones the discount factors say, rising here to 20 years
        zeros_found = self.numbers('(table-column zeros "zero")')
        np.testing.assert_allclose(zeros_found, -np.log(discount) / years, rtol=1e-5)
        self.assertGreater(zeros_found[-1], zeros_found[10])

    def test_the_yields_the_treasury_gave_are_the_ones_the_curve_has(self):
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 2026 10 15)))")
        self.run_lisp("(define zeros (treasury-zero-curve curve))")
        years, par = (self.numbers('(table-column zeros "%s")' % n) for n in ("years", "par"))
        for maturity, yield_ in [(1 / 12, 0.0417), (0.25, 0.0428), (0.5, 0.0435), (1, 0.0449), (2, 0.0477), (5, 0.0491),
                                 (10, 0.0510), (20, 0.0548), (30, 0.0543)]:
            found = np.argmin(abs(years - maturity))
            self.assertAlmostEqual(years[found], maturity, places=5)
            self.assertAlmostEqual(par[found], yield_, places=6, msg=str(maturity))

    def test_the_par_yields_between_the_maturities_are_on_a_smooth_curve_that_does_not_overshoot(self):
        """The Treasury publishes the 10, 20, and 30 years only: between them the par yield follows a monotone cubic
        (scipy's PCHIP), not a straight line, and does not go above the 20 years' 5.48% or below the 10 years' 5.10%."""
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 2026 10 15)))")
        self.run_lisp("(define zeros (treasury-zero-curve curve))")
        years, par = (self.numbers('(table-column zeros "%s")' % n) for n in ("years", "par"))
        between = (years > 10) & (years < 20)
        self.assertTrue((par[between] > 0.0510).all() and (par[between] < 0.0548 + 1e-6).all())
        self.assertGreater(abs(par[years == 15][0] - (0.0510 + 0.0548) / 2), 1e-4)            # (it is not the straight line)
        try:
            from scipy.interpolate import PchipInterpolator
        except ImportError:
            return
        tenors = np.array([1, 1.5, 2, 3, 4, 6, 12, 24, 36, 60, 84, 120, 240, 360]) / 12
        published = np.array([0.0417, 0.0415, 0.0419, 0.0428, 0.0435, 0.0435, 0.0449, 0.0477, 0.0485, 0.0491, 0.05, 0.051, 0.0548, 0.0543])
        semiannual = years >= 0.5
        np.testing.assert_allclose(par[semiannual], PchipInterpolator(tenors, published)(years[semiannual]), atol=2e-7)

    def test_the_forward_rates_of_the_treasurys_curve_do_not_jump_after_the_first_year(self):
        """With straight lines between the par yields they jumped by 1.5 points where the 20-year line meets the 30-year's:
        smoothly, no month's rate is more than a tenth of a point from the one before it (after the first year, when the
        bills' kinks are)."""
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 2026 10 15)))")
        self.run_lisp("(define forwards (curve-forward-rates (treasury-zero-curve curve)))")
        forward = self.numbers('(table-column forwards "forward")')
        self.assertLess(abs(np.diff(forward[12:])).max(), 0.0015)
        self.assertTrue(((forward > 0.04) & (forward < 0.07)).all())

    def test_a_last_maturity_that_is_not_a_whole_number_of_half_years_goes_on_to_the_next(self):
        zeros = self.zeros([0.5, 1.2], [0.02, 0.03])
        np.testing.assert_allclose(zeros["years"], [0.5, 1.0, 1.5])
        np.testing.assert_allclose(zeros["par"], [0.02, 0.02 + 0.01 * 0.5 / 0.7, 0.03], atol=1e-6)      # (flat after 1.2)
        self.assertEqual(len(self.zeros([0.5], [0.02])["years"]), 1)

    def test_missing_yields_are_left_out_and_nothing_is_an_error(self):
        zeros = self.zeros([0.5, 1, 2], [0.02, "nan", 0.03])
        self.assertEqual(len(zeros["years"]), 4)                            # (6 months to 2 years)
        np.testing.assert_allclose(zeros["par"], [0.02, 0.0233333, 0.0266667, 0.03], atol=1e-6)
        self.assertLispError("(par-curve-zeros (vector 1 2) (vector nan nan))", "there is no par yield")


class TestForwardRates(YieldCurvesTestCase):

    def test_a_flat_zero_curve_has_the_forward_rate_of_a_month_of_that_rate(self):
        self.run_lisp('(define flat (make-table "years" (vector 1 30) "zero" (vector 0.05 0.05)))')
        self.run_lisp("(define forwards (curve-forward-rates flat))")
        self.assertShows("(table-row-count forwards)", "360")
        self.assertShows('(table-column-names forwards)', '("months" "discount" "forward")')
        months = self.numbers('(table-column forwards "months")')
        np.testing.assert_allclose(months, np.arange(1, 361))
        np.testing.assert_allclose(self.numbers('(table-column forwards "forward")'), 12 * (math.exp(0.05 / 12) - 1), rtol=1e-4)
        np.testing.assert_allclose(self.numbers('(table-column forwards "discount")'), np.exp(-0.05 * months / 12), rtol=1e-6)

    def test_discounting_a_month_at_a_time_at_the_forward_rates_gives_the_discount_factors(self):
        self.run_lisp('(define zeros (make-table "years" (vector 0.5 2 10) "zero" (vector 0.03 0.04 0.06)))')
        self.run_lisp("(define forwards (curve-forward-rates zeros :months 120))")
        forward = self.numbers('(table-column forwards "forward")')
        discount = self.numbers('(table-column forwards "discount")')
        self.assertEqual(len(forward), 120)
        np.testing.assert_allclose(np.cumprod(1 / (1 + forward / 12)), discount, rtol=2e-5)
        # the zero rate of each month is on a smooth curve through the ones given (and flat before the first)
        try:
            from scipy.interpolate import PchipInterpolator
        except ImportError:
            return
        years = np.arange(1, 121) / 12
        zero = PchipInterpolator([0.5, 2, 10], [0.03, 0.04, 0.06])(np.clip(years, 0.5, 10))
        np.testing.assert_allclose(discount, np.exp(-zero * years), rtol=1e-6)

    def test_what_a_month_is_for(self):
        self.run_lisp('(define zeros (make-table "years" (vector 1) "zero" (vector 0.06)))')
        self.run_lisp("(define forwards (curve-forward-rates zeros :months 3))")
        self.assertShows('(table-column forwards "months")', "#(1 2 3)")
        # the first month's money grows by D(0) / D(1/12) = e^(.06/12)
        self.assertAlmostEqual(self.numbers('(table-column forwards "forward")')[0], 12 * (math.exp(0.005) - 1), places=5)


class TestTheTreasurysZeroCurve(YieldCurvesTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("(define curve (treasury-par-curve :start-date (date 2026 10 1)))")

    def yield_of(self, call, maturity):
        self.run_lisp("(define zeros %s)" % call)
        years, par = (self.numbers('(table-column zeros "%s")' % n) for n in ("years", "par"))
        return par[np.argmin(abs(years - maturity))]

    def test_it_is_the_latest_day_unless_a_day_is_given(self):
        self.assertAlmostEqual(self.yield_of("(treasury-zero-curve curve)", 10), 0.0510, places=6)
        self.assertAlmostEqual(self.yield_of("(treasury-zero-curve curve :date (date 2026 10 14))", 10), 0.0519, places=6)
        self.assertAlmostEqual(self.yield_of('(treasury-zero-curve curve :date "2026-10-13")', 10), 0.0521, places=6)

    def test_a_day_with_no_curve_has_the_last_one_before_it(self):
        self.assertAlmostEqual(self.yield_of("(treasury-zero-curve curve :date (date 2026 10 17))", 10), 0.0510, places=6)   # a Saturday
        self.assertAlmostEqual(self.yield_of("(treasury-zero-curve curve :date (date 2026 11 30))", 10), 0.0510, places=6)
        self.assertLispError("(treasury-zero-curve curve :date (date 2026 9 30))", "has no day on or before 2026-09-30")

    def test_the_zero_curve_goes_to_the_forwards_of_a_model(self):
        self.run_lisp("(define forwards (curve-forward-rates (treasury-zero-curve curve)))")
        forward = self.numbers('(table-column forwards "forward")')
        self.assertEqual(len(forward), 360)
        self.assertTrue(((forward > 0.03) & (forward < 0.09)).all())


class TestTheFedsCurve(YieldCurvesTestCase):

    def test_the_columns_have_names_and_decimals_and_na_is_missing(self):
        self.run_lisp("(define fed (gsw-curve))")
        self.assertShows("(table-column-names fed)",
                         '("date" "beta0" "beta1" "beta2" "beta3" "year-forward-1" "year-forward-4" "year-forward-9" '
                         '"forward-1" "forward-5" "forward-10" "forward-30" "par-10" "zero-1" "zero-2" "zero-5" "zero-10" '
                         '"zero-30" "tau1" "tau2")')
        self.assertShows('(table-column fed "date")', "#(1961-06-14 2026-10-08 2026-10-09)")
        np.testing.assert_allclose(self.numbers('(table-column fed "zero-10")'), [np.nan, 0.0525, 0.052514], atol=1e-7)     # (NA is nan)
        np.testing.assert_allclose(self.numbers('(table-column fed "year-forward-9")'), [np.nan, 0.059, 0.059035], atol=1e-7)
        np.testing.assert_allclose(self.numbers('(table-column fed "tau2")'), [3, 15.7, 15.7551507296816], rtol=1e-6)    # (years, not percents)
        np.testing.assert_allclose(self.numbers('(table-column fed "beta1")')[2], 0.0392393143398782, rtol=1e-6)
        self.assertEqual(self.asked[0][0], "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv")
        self.assertEqual(self.asked[0][1], 12)

    def test_a_range_of_days(self):
        self.run_lisp('(define fed (gsw-curve :start-date (date 2026 10 9)))')
        self.assertShows('(table-column fed "date")', "#(2026-10-09)")
        self.run_lisp('(define fed (gsw-curve :start-date "1961-06-15" :end-date "2026-10-08"))')
        self.assertShows('(table-column fed "date")', "#(2026-10-08)")

    def test_the_six_numbers_of_a_day(self):
        self.run_lisp("(define fed (gsw-curve))")
        latest = self.run_lisp("(gsw-parameters fed)")
        np.testing.assert_allclose([float(x) for x in lisp_core.pairs_to_list(latest)], FED_PARAMETERS, rtol=1e-6, atol=1e-12)
        before = self.run_lisp("(gsw-parameters fed :date (date 2026 10 8))")
        self.assertAlmostEqual(lisp_core.pairs_to_list(before)[5], 15.7, places=4)
        on_a_saturday = self.run_lisp('(gsw-parameters fed :date "2026-10-10")')
        self.assertAlmostEqual(lisp_core.pairs_to_list(on_a_saturday)[5], 15.7551507, places=4)
        self.assertLispError("(gsw-parameters fed :date (date 1950 1 1))", "has no day on or before 1950-01-01")

    def test_the_svensson_curve_gives_the_zero_and_forward_rates_the_fed_publishes(self):
        """The Fed's own zero rates (SVENY) and forward rates (SVENF) of 2026-10-09, in percent to 4 places."""
        self.run_lisp("(define fed (gsw-curve))")
        self.run_lisp("(define parameters (gsw-parameters fed))")
        zeros = self.numbers("(svensson-zero-rates parameters (vector 1 2 5 10 30))")
        np.testing.assert_allclose(zeros, [0.044929, 0.047593, 0.049865, 0.052514, 0.056402], atol=1.5e-6)
        forwards = self.numbers("(svensson-forward-rates parameters (vector 1 5 10 30))")
        np.testing.assert_allclose(forwards, [0.048753, 0.05186, 0.058903, 0.048251], atol=1.5e-6)
        # a number for a vector, a number
        self.assertAlmostEqual(self.run_lisp("(svensson-zero-rates parameters 10)"), 0.052514, places=5)
        self.assertAlmostEqual(self.run_lisp("(svensson-forward-rates parameters 10)"), 0.058903, places=5)

    def test_the_formulas_are_the_svensson_curve_at_any_parameters(self):
        parameters = [0.04, -0.02, 0.03, 0.05, 1.5, 8.0]
        self.run_lisp("(define parameters (list %s))" % " ".join(repr(p) for p in parameters))
        years = [0.25, 1, 3, 7, 12, 25, 30]
        self.run_lisp("(define years (vector %s))" % " ".join(str(y) for y in years))
        np.testing.assert_allclose(self.numbers("(svensson-zero-rates parameters years)"),
                                   [svensson_zero(parameters, t) for t in years], rtol=1e-5)
        np.testing.assert_allclose(self.numbers("(svensson-forward-rates parameters years)"),
                                   [svensson_forward(parameters, t) for t in years], rtol=1e-5)
        # the zero rate is the average of the forward rates before it
        steps = np.arange(0.0005, 10, 0.001)
        average = np.mean([svensson_forward(parameters, t) for t in steps])
        self.assertAlmostEqual(average, svensson_zero(parameters, 10), places=5)

    def test_the_zero_curve_of_a_day_by_the_month_goes_to_the_forwards_of_a_model(self):
        self.run_lisp("(define fed (gsw-curve))")
        self.run_lisp("(define zeros (gsw-zero-curve fed))")
        years = self.numbers('(table-column zeros "years")')
        self.assertEqual(len(years), 360)
        np.testing.assert_allclose(years, np.arange(1, 361) / 12, rtol=1e-6)
        np.testing.assert_allclose(self.numbers('(table-column zeros "zero")'),
                                   [svensson_zero(FED_PARAMETERS, t) for t in years], rtol=1e-5)
        self.run_lisp("(define forwards (curve-forward-rates zeros))")
        forward = self.numbers('(table-column forwards "forward")')
        discount = self.numbers('(table-column forwards "discount")')
        self.assertAlmostEqual(discount[119], math.exp(-svensson_zero(FED_PARAMETERS, 10) * 10), places=6)     # (10 years)
        # a month's forward rate, with monthly interest, is near the instantaneous one at its middle
        for month in (12, 60, 120, 300):
            self.assertAlmostEqual(forward[month - 1], svensson_forward(FED_PARAMETERS, (month - 0.5) / 12), delta=0.0004)
        # a day before: another curve
        self.run_lisp("(define earlier (gsw-zero-curve fed :date (date 2026 10 8) :months 24))")
        self.assertShows('(table-row-count earlier)', "24")
        np.testing.assert_allclose(self.numbers('(table-column earlier "zero")')[11],       # (a year out)
                                   svensson_zero([0.005, 0.038, 0.049, 0.16, 1.9, 15.7], 1.0), rtol=1e-5)


class TestExtendingAForwardCurve(YieldCurvesTestCase):

    def extend(self, short, real, long, blend=""):
        self.run_lisp("(define short (vector %s))" % " ".join(repr(float(x)) for x in short))
        self.run_lisp("(define long (vector %s))" % " ".join(repr(float(x)) for x in long))
        return self.numbers("(extend-forward-curve short %d long %s)" % (real, blend))

    def test_the_short_curve_to_the_months_it_is_known_then_a_straight_line_to_the_long_one(self):
        both = self.extend([0.04] * 360, 60, [0.05] * 360, ":blend-months 12")
        np.testing.assert_allclose(both[:61], 0.04, atol=1e-7)                      # (the 61st month starts the change)
        np.testing.assert_allclose(both[60:72], 0.04 + 0.01 * np.arange(12) / 12, atol=1e-7)
        np.testing.assert_allclose(both[72:], 0.05, atol=1e-7)
        self.assertEqual(len(both), 360)

    def test_the_blend_is_twelve_months_unless_it_is_given(self):
        both = self.extend([0.04] * 360, 60, [0.05] * 360)
        np.testing.assert_allclose(both[60:72], 0.04 + 0.01 * np.arange(12) / 12, atol=1e-7)
        wider = self.extend([0.04] * 360, 60, [0.05] * 360, ":blend-months 24")
        np.testing.assert_allclose(wider[60:84], 0.04 + 0.01 * np.arange(24) / 24, atol=1e-7)
        np.testing.assert_allclose(wider[84:], 0.05, atol=1e-7)
        abrupt = self.extend([0.04] * 360, 60, [0.05] * 360, ":blend-months 1")
        np.testing.assert_allclose(abrupt[:61], 0.04, atol=1e-7)
        np.testing.assert_allclose(abrupt[61:], 0.05, atol=1e-7)

    def test_a_blend_of_the_curves_as_they_are_at_each_month(self):
        rng = np.random.default_rng(3)
        short, long = rng.uniform(0.02, 0.06, 360), rng.uniform(0.02, 0.06, 360)
        both = self.extend(list(short), 40, list(long), ":blend-months 18")
        weight = np.clip((np.arange(360) - 40) / 18, 0, 1)
        np.testing.assert_allclose(both, (1 - weight) * short + weight * long, atol=2e-7)

    def test_a_curve_known_to_no_month_is_the_long_one_after_the_blend(self):
        both = self.extend([0.04] * 24, 0, [0.05] * 24, ":blend-months 6")
        np.testing.assert_allclose(both[:6], 0.04 + 0.01 * np.arange(6) / 6, atol=1e-7)
        np.testing.assert_allclose(both[6:], 0.05, atol=1e-7)
        known = self.extend([0.04] * 24, 24, [0.05] * 24)
        np.testing.assert_allclose(known, 0.04, atol=1e-7)

    def test_what_it_will_not_take(self):
        self.run_lisp("(define short (make-vector 12 0.04))")
        self.run_lisp("(define long (make-vector 24 0.05))")
        self.assertLispError("(extend-forward-curve short 6 long)", "forwards has 12 months and longer-forwards 24")
        self.assertLispError("(extend-forward-curve short 6 short :blend-months 0)", ":blend-months is a number of months above 0")
        self.assertLispError("(extend-forward-curve short 6 short :blend-months -3)", ":blend-months is a number of months above 0")

    def test_the_curves_of_this_library_extend_the_one_of_the_sofr_futures(self):
        """A curve flat at 4% to 5 years, carried on by the Fed's, which has its own at 10 years: the 4% to the 60th month,
        the Fed's after the 72nd, and between them in between."""
        self.run_lisp('(define fed (gsw-curve))')
        self.run_lisp('(define fed-forwards (table-column (curve-forward-rates (gsw-zero-curve fed)) "forward"))')
        self.run_lisp("(define both (extend-forward-curve (make-vector 360 0.04) 60 fed-forwards))")
        both, fed = self.numbers("both"), self.numbers("fed-forwards")
        np.testing.assert_allclose(both[:60], 0.04, atol=1e-7)
        np.testing.assert_allclose(both[72:], fed[72:], atol=1e-7)
        self.assertTrue((both[61:72] > 0.04).all() == (fed[61:72] > 0.04).all())


class TestTheExample(YieldCurvesTestCase):

    def test_it_shows_both_curves_for_the_latest_day_and_saves_two_charts(self):
        with in_a_temporary_folder() as folder:
            lisp_core.run_file(os.path.join(EXAMPLES, "yield_curve_example.lsp"), self.env)
            for chart in ("yield_curve_zero.png", "yield_curve_forward.png"):
                self.assertTrue(is_a_png(os.path.join(folder, chart)), chart)
        shown = self.printed()
        self.assertIn("The Treasury's par yield curve of 2026-10-15: 3 days this year.", shown)
        self.assertIn("The Fed's curve, to 2026-10-09: its 10-year zero rate is 5.25%; the Treasury's, from its par yields, 5.", shown)
        self.assertIn("[chart] Zero rates and par yields", shown)
        self.assertIn("[chart] One-month forward rates", shown)
        self.assertEqual([url for url, _ in self.asked if "treasury" in url][0].split("/")[-2], "2026")
