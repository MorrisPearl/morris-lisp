"""Options on the 10-year note future (ZN): the Monte Carlo pricer and calibration of term_structure_model.py (Step 3b),
the note-option-rows library function, and the sofr-note-option-comparison, sofr-calibrate-note-options and
sofr-calibrate-jointly builtins that bring them to Lisp.

The numbers that can be worked out by hand are (Bachelier's formula, discount factors, a note's price and duration, the
variances of the simulated factors); the rest are checked as the model's own promises: no volatility gives the
discounted intrinsic value, prices rise with volatility, a price made by the model is fitted back to the volatility
that made it."""

import os

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

sys.path.insert(0, os.path.join(HERE, "..", "term_structure"))
import lisp_sofr  # noqa: E402
import term_structure_model as model  # noqa: E402

# A curve of monthly forward rates, 4% for the first month and rising to 5.5%.
FORWARDS = 0.04 + 0.015 * (1 - np.exp(-np.arange(1, 361) / 60.0))

DAYS_PER_YEAR = 365.0
FUTURES_PRICE = 105.5
STRIKES = [103.5, 104.5, 105.5, 106.5, 107.5]
EXPIRY_DAYS = [36, 70]


def synthetic_options(sigma1, sigma2, days=EXPIRY_DAYS, strikes=STRIKES, n_paths=4000, seed=42, **choices):
    """Calls and puts at each strike and expiry, whose market prices are the model's own at these volatilities."""
    options = []
    for expiry in days:
        for strike in strikes:
            for kind in ("call", "put"):
                options.append({"type": kind, "strike": strike, "expiry_years": expiry / DAYS_PER_YEAR,
                                "futures_price": FUTURES_PRICE, "market_price": 0.0})
    prices = model.price_note_future_options_mc(FORWARDS, options, sigma1, sigma2, n_paths=n_paths, seed=seed, **choices)
    for option, price in zip(options, prices):
        option["market_price"] = float(price)
    return options


class TestBachelier(unittest.TestCase):
    """The formula that puts the options of different futures on one footing (volatility in price points a year)."""

    def test_an_option_at_the_money_is_worth_a_fraction_of_the_spread(self):
        discount, vol, years = 0.99, 7.0, 0.1
        expected = discount * vol * math.sqrt(years) / math.sqrt(2 * math.pi)
        self.assertAlmostEqual(model._bachelier_price("call", 105.0, 105.0, vol, years, discount), expected, places=12)
        self.assertAlmostEqual(model._bachelier_price("put", 105.0, 105.0, vol, years, discount), expected, places=12)

    def test_a_call_less_a_put_is_the_discounted_forward_less_strike(self):
        for strike in (100.0, 105.0, 111.0):
            call = model._bachelier_price("call", 105.0, strike, 6.0, 0.25, 0.98)
            put = model._bachelier_price("put", 105.0, strike, 6.0, 0.25, 0.98)
            self.assertAlmostEqual(call - put, 0.98 * (105.0 - strike), places=10)

    def test_a_far_option_is_worth_its_intrinsic_value_or_nothing(self):
        self.assertAlmostEqual(model._bachelier_price("call", 120.0, 100.0, 1.0, 0.1, 0.9), 0.9 * 20.0, places=9)
        self.assertAlmostEqual(model._bachelier_price("call", 100.0, 120.0, 1.0, 0.1, 0.9), 0.0, places=9)

    def test_vega_is_the_change_in_price_for_a_point_of_volatility(self):
        for strike in (103.0, 105.0, 107.0):
            up = model._bachelier_price("call", 105.0, strike, 6.001, 0.2, 0.97)
            down = model._bachelier_price("call", 105.0, strike, 5.999, 0.2, 0.97)
            self.assertAlmostEqual(model._bachelier_vega(105.0, strike, 6.0, 0.2, 0.97), (up - down) / 0.002, places=6)

    def test_the_implied_volatility_gives_the_price_back(self):
        for kind in ("call", "put"):
            for strike in (102.0, 105.0, 108.0):
                price = model._bachelier_price(kind, 105.0, strike, 6.5, 0.15, 0.98)
                vol = model._implied_normal_vol(kind, price, 105.0, strike, 0.15, 0.98)
                self.assertAlmostEqual(vol, 6.5, places=6)

    def test_a_price_at_or_below_the_intrinsic_value_has_no_volatility(self):
        self.assertTrue(math.isnan(model._implied_normal_vol("call", 0.98 * 5.0, 105.0, 100.0, 0.1, 0.98)))
        self.assertTrue(math.isnan(model._implied_normal_vol("call", 0.5 * 0.98 * 5.0, 105.0, 100.0, 0.1, 0.98)))
        self.assertTrue(math.isnan(model._implied_normal_vol("put", 0.0, 105.0, 100.0, 0.1, 0.98)))


class TestMarketDiscountFactors(unittest.TestCase):

    def test_a_flat_curve_discounts_a_month_at_a_time(self):
        flat = np.full(360, 0.12)                                  # 1% a month
        np.testing.assert_allclose(model._market_discount_factors(flat, [0.0, 1.0, 2.5]),
                                   [1.0, 1.01 ** -12, 1.01 ** -30], rtol=1e-12)

    def test_between_month_ends_the_log_of_the_factor_is_on_a_straight_line(self):
        flat = np.full(360, 0.12)
        np.testing.assert_allclose(model._market_discount_factors(flat, [1 / 24, 5.5 / 12]),
                                   [1.01 ** -0.5, 1.01 ** -5.5], rtol=1e-12)

    def test_each_months_forward_rate_discounts_its_own_month(self):
        forwards = np.array([0.12, 0.24, 0.0] + [0.0] * 357)
        np.testing.assert_allclose(model._market_discount_factors(forwards, [1 / 12, 2 / 12, 3 / 12]),
                                   [1 / 1.01, 1 / (1.01 * 1.02), 1 / (1.01 * 1.02)], rtol=1e-12)

    def test_the_curve_must_reach_as_far_as_the_dates(self):
        with self.assertRaises(ValueError) as caught:
            model._market_discount_factors(np.full(120, 0.05), [9.0, 10.5])
        self.assertIn("ends at 10.0 years", str(caught.exception))
        model._market_discount_factors(np.full(120, 0.05), [10.0])            # exactly as far is enough


class TestTheNote(unittest.TestCase):
    """The note the future is taken to be: its cash flows, its par coupon on the forward curve, its price and duration."""

    def test_a_note_pays_every_six_months_back_from_its_maturity(self):
        np.testing.assert_allclose(model._note_cash_flow_times(6.75), 0.25 + 0.5 * np.arange(14))
        np.testing.assert_allclose(model._note_cash_flow_times(1.0), [0.5, 1.0])
        np.testing.assert_allclose(model._note_cash_flow_times(0.3), [0.3])
        np.testing.assert_allclose(model._note_cash_flow_times(7.0), 0.5 * np.arange(1, 15))
        self.assertEqual(len(model._note_cash_flow_times(float(np.nextafter(3.5, 4.0)))), 7)   # a hair over 3.5 years: 7 coupons

    def test_the_cash_flows_are_the_coupons_and_the_face_value(self):
        np.testing.assert_allclose(model._note_cash_flows(1.0, 0.05), [2.5, 102.5])
        np.testing.assert_allclose(model._note_cash_flows(0.3, 0.05), [102.5])

    def test_the_par_coupon_on_a_flat_curve_is_what_the_geometric_series_says(self):
        monthly = 0.06
        times = model._note_cash_flow_times(6.75)
        discount = [(1 + monthly / 12) ** (-12 * t) for t in times]
        expected = 2 * (1 - discount[-1]) / sum(discount)
        for expiry in (0.1, 0.5):
            self.assertAlmostEqual(model._forward_par_coupon(np.full(360, monthly), expiry, 6.75), expected, places=10)

    def test_the_note_with_its_par_coupon_is_worth_par_where_the_curve_is_the_markets(self):
        for expiry in (0.1, 0.4):
            coupon = model._forward_par_coupon(FORWARDS, expiry, 6.75)
            price = model._note_prices_at_expiry(FORWARDS, expiry, np.zeros(1), np.zeros(1), 1.0, 6.75, coupon)
            self.assertAlmostEqual(float(price[0]), 100.0, places=9)

    def test_the_price_falls_with_the_deviations_by_the_closed_form(self):
        # A 1-year note, 5% coupon, on a flat 6% (monthly) curve, 3 months from now.
        monthly, expiry = 0.06, 0.25
        delta_r, delta_theta = np.array([0.0, 0.01, -0.02]), np.array([0.0, 0.005, 0.01])
        for a in (1.0, 2.5):
            got = model._note_prices_at_expiry(np.full(360, monthly), expiry, delta_r, delta_theta, a, 1.0, 0.05)
            for path in range(3):
                expected = 0.0
                for t, flow in ((0.5, 2.5), (1.0, 102.5)):
                    b_of_t = (1 - math.exp(-a * t)) / a
                    a_of_t = t - b_of_t
                    expected += flow * (1 + monthly / 12) ** (-12 * t) * math.exp(-delta_theta[path] * a_of_t - delta_r[path] * b_of_t)
                self.assertAlmostEqual(float(got[path]), expected, places=9)

    def test_the_long_end_follows_theta_and_the_short_end_follows_r(self):
        # A rise in r alone moves the price less than the same rise in theta, as theta lasts.
        base = model._note_prices_at_expiry(FORWARDS, 0.1, np.zeros(1), np.zeros(1), 1.0, 6.75, 0.05)
        r_up = model._note_prices_at_expiry(FORWARDS, 0.1, np.array([0.01]), np.zeros(1), 1.0, 6.75, 0.05)
        theta_up = model._note_prices_at_expiry(FORWARDS, 0.1, np.zeros(1), np.array([0.01]), 1.0, 6.75, 0.05)
        self.assertLess(theta_up[0], r_up[0])
        self.assertLess(r_up[0], base[0])

    def test_the_duration_is_the_percent_fall_for_a_parallel_rise_in_rates(self):
        expiry = 0.1
        coupon = model._forward_par_coupon(FORWARDS, expiry, 6.75)
        duration = model._note_duration(FORWARDS, expiry, 6.75, coupon)
        shift = 1e-5                                  # r and theta both up by this: every forward rate is
        up = model._note_prices_at_expiry(FORWARDS, expiry, np.array([shift]), np.array([shift]), 1.0, 6.75, coupon)[0]
        down = model._note_prices_at_expiry(FORWARDS, expiry, np.array([-shift]), np.array([-shift]), 1.0, 6.75, coupon)[0]
        self.assertAlmostEqual(duration, -(up - down) / (2 * shift) / 100.0, places=6)
        self.assertGreater(duration, 5.0)
        self.assertLess(duration, 6.75)


class TestTheSimulation(unittest.TestCase):

    def test_with_no_volatility_the_factors_stay_where_the_curve_has_them(self):
        found = model._simulate_deviations([10, 40], 0.0, 0.0, 1.0, 0.15, 100, 7)
        for day in (10, 40):
            delta_r, delta_theta, adjustment = found[day]
            np.testing.assert_array_equal(delta_r, 0.0)
            np.testing.assert_array_equal(delta_theta, 0.0)
            np.testing.assert_array_equal(adjustment, 1.0)

    def test_every_path_has_a_mirror_image_so_the_averages_are_zero(self):
        delta_r, delta_theta, _ = model._simulate_deviations([60], 0.01, 0.012, 1.0, 0.15, 1000, 3)[60]
        self.assertEqual(len(delta_r), 1000)
        self.assertAlmostEqual(float(delta_r.mean()), 0.0, places=14)
        self.assertAlmostEqual(float(delta_theta.mean()), 0.0, places=14)
        np.testing.assert_allclose(delta_r[:500], -delta_r[500:], atol=1e-15)

    def test_an_odd_number_of_paths_is_rounded_up_to_an_even_number(self):
        self.assertEqual(len(model._simulate_deviations([5], 0.01, 0.01, 1.0, 0.15, 11, 3)[5][0]), 12)

    def test_the_variances_are_those_of_the_discrete_steps(self):
        a, b, sigma1, sigma2, days = 1.3, 0.2, 0.015, 0.011, 90
        dt = 1 / DAYS_PER_YEAR
        # x(k+1) = F x(k) + noise: the covariance of x = (delta_r, delta_theta) grows by F S F' + Q a day at a time.
        step = np.array([[1 - a * dt, a * dt], [0.0, 1 - b * dt]])
        noise = np.diag([sigma1 ** 2 * dt, sigma2 ** 2 * dt])
        covariance = np.zeros((2, 2))
        for _ in range(days):
            covariance = step @ covariance @ step.T + noise
        delta_r, delta_theta, _ = model._simulate_deviations([days], sigma1, sigma2, a, b, 400000, 11)[days]
        # (enough paths, 200000 and their mirror images, that a year of 360 days instead of 365 would show)
        # The shocks are independent: r and theta are correlated only because r is drawn towards theta.
        self.assertAlmostEqual(float(np.var(delta_r)) / covariance[0, 0], 1.0, delta=0.008)
        self.assertAlmostEqual(float(np.var(delta_theta)) / covariance[1, 1], 1.0, delta=0.008)
        correlation = covariance[0, 1] / math.sqrt(covariance[0, 0] * covariance[1, 1])
        self.assertAlmostEqual(float(np.corrcoef(delta_r, delta_theta)[0, 1]), correlation, delta=0.008)

    def test_the_discount_adjustment_is_the_exponential_of_minus_the_rate_over_the_days(self):
        found = model._simulate_deviations([1, 2, 3], 0.01, 0.01, 1.0, 0.15, 200, 5)
        dt = 1 / DAYS_PER_YEAR
        np.testing.assert_array_equal(found[1][2], 1.0)                       # r has not yet moved on the first day
        np.testing.assert_allclose(found[2][2], np.exp(-found[1][0] * dt), rtol=1e-14)
        np.testing.assert_allclose(found[3][2], np.exp(-(found[1][0] + found[2][0]) * dt), rtol=1e-14)

    def test_a_day_has_the_same_values_whatever_later_days_are_wanted(self):
        short = model._simulate_deviations([30], 0.01, 0.012, 1.0, 0.15, 300, 9)[30]
        long = model._simulate_deviations([30, 80], 0.01, 0.012, 1.0, 0.15, 300, 9)[30]
        for one, other in zip(short, long):
            np.testing.assert_array_equal(one, other)

    def test_the_same_seed_gives_the_same_paths_and_another_does_not(self):
        first = model._simulate_deviations([20], 0.01, 0.01, 1.0, 0.15, 200, 1)[20][0]
        again = model._simulate_deviations([20], 0.01, 0.01, 1.0, 0.15, 200, 1)[20][0]
        other = model._simulate_deviations([20], 0.01, 0.01, 1.0, 0.15, 200, 2)[20][0]
        np.testing.assert_array_equal(first, again)
        self.assertFalse(np.array_equal(first, other))

    def test_the_volatilities_scale_the_same_random_numbers(self):
        small = model._simulate_deviations([40], 0.0, 0.01, 1.0, 0.15, 200, 4)[40][1]
        large = model._simulate_deviations([40], 0.0, 0.02, 1.0, 0.15, 200, 4)[40][1]
        np.testing.assert_allclose(large, 2 * small, rtol=1e-12)

    def test_the_expiry_is_a_day_count_of_at_least_one(self):
        self.assertEqual(model._expiry_day({"expiry_years": 36 / 365.0}), 36)
        self.assertEqual(model._expiry_day({"expiry_years": 0.0}), 1)
        self.assertEqual(model._expiry_day({"expiry_years": 0.5 / 365.0}), 1)
        self.assertEqual(model._expiry_day({"expiry_years": 36.4 / 365.0}), 36)
        self.assertEqual(model._expiry_day({"expiry_years": 36.6 / 365.0}), 37)


class TestThePricer(unittest.TestCase):

    def option(self, kind, strike, days, price=FUTURES_PRICE):
        return {"type": kind, "strike": strike, "expiry_years": days / DAYS_PER_YEAR, "futures_price": price}

    def test_with_no_volatility_an_option_is_worth_its_discounted_intrinsic_value(self):
        options = [self.option("call", 104.0, 36), self.option("put", 104.0, 36), self.option("call", 107.0, 70),
                   self.option("put", 107.0, 70)]
        prices = model.price_note_future_options_mc(FORWARDS, options, 0.0, 0.0, n_paths=100)
        for option, price in zip(options, prices):
            discount = model._market_discount_factors(FORWARDS, [option["expiry_years"]])[0]
            intrinsic = max(FUTURES_PRICE - option["strike"], 0) if option["type"] == "call" else max(option["strike"] - FUTURES_PRICE, 0)
            self.assertAlmostEqual(float(price), discount * intrinsic, places=12)

    def test_the_prices_are_the_average_discounted_payoff_of_the_scaled_note_price(self):
        # The pricer again, from the pieces: deviations, the note at expiry, scaled to average 1, the payoff, the discount.
        days, strike = 50, 105.0
        expiry = days / DAYS_PER_YEAR
        sigma1, sigma2, a, b = 0.012, 0.011, 1.2, 0.2
        delta_r, delta_theta, adjustment = model._simulate_deviations([days], sigma1, sigma2, a, b, 2000, 5)[days]
        coupon = model._forward_par_coupon(FORWARDS, expiry, 6.75)
        note = model._note_prices_at_expiry(FORWARDS, expiry, delta_r, delta_theta, a, 6.75, coupon)
        futures = FUTURES_PRICE * note / note.mean()
        discount = model._market_discount_factors(FORWARDS, [expiry])[0] * adjustment
        for kind, payoff in (("call", np.maximum(futures - strike, 0)), ("put", np.maximum(strike - futures, 0))):
            price = model.price_note_future_options_mc(FORWARDS, [self.option(kind, strike, days)], sigma1, sigma2,
                                                       a=a, b=b, n_paths=2000, seed=5)[0]
            self.assertAlmostEqual(float(price), float(np.mean(discount * payoff)), places=12)

    def test_the_price_of_a_future_that_cannot_fall_below_zero_is_its_discounted_expected_value(self):
        # A call struck at 0 is the future itself, paid for now: worth its price today, discounted from the expiry.
        price = model.price_note_future_options_mc(FORWARDS, [self.option("call", 0.0, 60)], 0.01, 0.012, n_paths=20000)[0]
        discount = model._market_discount_factors(FORWARDS, [60 / DAYS_PER_YEAR])[0]
        self.assertAlmostEqual(float(price) / (discount * FUTURES_PRICE), 1.0, delta=0.002)

    def test_a_call_less_a_put_is_the_discounted_future_less_the_strike(self):
        days = 60
        discount = model._market_discount_factors(FORWARDS, [days / DAYS_PER_YEAR])[0]
        for strike in (103.0, 105.5, 108.0):
            call, put = model.price_note_future_options_mc(
                FORWARDS, [self.option("call", strike, days), self.option("put", strike, days)], 0.01, 0.012, n_paths=20000)
            self.assertAlmostEqual(float(call - put), discount * (FUTURES_PRICE - strike), delta=0.01)

    def test_prices_rise_with_either_volatility(self):
        options = [self.option("call", 105.5, 36), self.option("put", 105.5, 36), self.option("call", 107.0, 70)]
        base = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.01, n_paths=2000)
        more_theta = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.012, n_paths=2000)
        more_r = model.price_note_future_options_mc(FORWARDS, options, 0.015, 0.01, n_paths=2000)
        self.assertTrue(np.all(more_theta > base))
        self.assertTrue(np.all(more_r > base))

    def test_the_level_volatility_matters_more_than_the_short_rates(self):
        options = [self.option("call", 105.5, 36)]
        base = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.01, n_paths=4000)[0]
        short = model.price_note_future_options_mc(FORWARDS, options, 0.012, 0.01, n_paths=4000)[0]
        level = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.012, n_paths=4000)[0]
        self.assertGreater(level - base, 2 * (short - base))

    def test_a_longer_option_is_worth_more_at_the_money(self):
        prices = model.price_note_future_options_mc(
            FORWARDS, [self.option("call", FUTURES_PRICE, d) for d in (10, 36, 70, 120)], 0.01, 0.012, n_paths=4000)
        self.assertTrue(np.all(np.diff(prices) > 0))

    def test_the_price_of_an_option_does_not_depend_on_the_others_asked_for(self):
        one = model.price_note_future_options_mc(FORWARDS, [self.option("call", 105.0, 36)], 0.01, 0.012, n_paths=500)[0]
        several = model.price_note_future_options_mc(
            FORWARDS, [self.option("call", 105.0, 36), self.option("put", 104.0, 70), self.option("call", 108.0, 36)],
            0.01, 0.012, n_paths=500)
        self.assertEqual(float(several[0]), float(one))

    def test_an_option_is_priced_on_the_future_it_is_on(self):
        low = model.price_note_future_options_mc(FORWARDS, [self.option("call", 105.0, 36, price=104.0)], 0.01, 0.012, n_paths=500)[0]
        high = model.price_note_future_options_mc(FORWARDS, [self.option("call", 105.0, 36, price=106.0)], 0.01, 0.012, n_paths=500)[0]
        self.assertLess(low, high)

    def test_the_note_can_be_any_maturity_and_coupon(self):
        # A shorter note moves less with the rates, and so its future's options are worth less.
        options = [self.option("call", FUTURES_PRICE, 36)]
        prices = [model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.012, n_paths=2000, ctd_maturity_years=m)[0]
                  for m in (2.0, 4.0, 6.75, 9.0)]
        self.assertTrue(np.all(np.diff(prices) > 0))
        # By default the coupon makes the note a par bond on the forward curve; giving that coupon changes nothing.
        coupon = model._forward_par_coupon(FORWARDS, 36 / DAYS_PER_YEAR, 6.75)
        default = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.012, n_paths=2000)[0]
        given = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.012, n_paths=2000, ctd_coupon=coupon)[0]
        self.assertAlmostEqual(float(default), float(given), places=12)
        # A note of a smaller coupon lasts longer (a higher duration), and its future's options are worth more.
        low = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.012, n_paths=2000, ctd_coupon=0.02)[0]
        self.assertGreater(float(low), float(default) + 1e-4)

    def test_the_volatility_of_a_price_is_about_the_notes_duration_times_its_yield_volatility(self):
        # With the short rate following the level (a large), all the yields move together by about sigma2 a year;
        # the future's price then moves by duration * price * sigma2 a year, in points.
        options = [self.option("call", FUTURES_PRICE, 36)]
        price = model.price_note_future_options_mc(FORWARDS, options, 0.0, 0.01, a=20.0, n_paths=40000)[0]
        discount = model._market_discount_factors(FORWARDS, [36 / DAYS_PER_YEAR])[0]
        vol = model._implied_normal_vol("call", float(price), FUTURES_PRICE, FUTURES_PRICE, 36 / DAYS_PER_YEAR, discount)
        coupon = model._forward_par_coupon(FORWARDS, 36 / DAYS_PER_YEAR, 6.75)
        duration = model._note_duration(FORWARDS, 36 / DAYS_PER_YEAR, 6.75, coupon)
        # theta's own moves are over the weighted average of forwards (a factor a bit below the duration), so a range.
        ceiling = duration * FUTURES_PRICE * 0.01
        self.assertLess(vol, ceiling * 1.02)
        self.assertGreater(vol, ceiling * 0.7)


class TestTheComparison(unittest.TestCase):

    def test_the_rows_are_the_options_with_what_the_market_and_the_model_say(self):
        options = synthetic_options(0.01, 0.012, days=[36], strikes=[104.5, 106.5], n_paths=2000)
        rows = model.note_option_comparison(FORWARDS, options, 0.01, 0.012, n_paths=2000)
        self.assertEqual(len(rows), 4)
        for row, option in zip(rows, options):
            for key in ("type", "strike", "expiry_years", "futures_price", "market_price"):
                self.assertEqual(row[key], option[key])
            self.assertAlmostEqual(row["model_price"], option["market_price"], places=12)
            self.assertAlmostEqual(row["error"], 0.0, places=7)
            self.assertAlmostEqual(row["model_vol"], row["market_vol"], places=6)

    def test_the_volatilities_are_in_price_points_and_in_basis_points_of_yield(self):
        options = synthetic_options(0.01, 0.012, days=[36], strikes=[105.5], n_paths=2000)[:1]
        row = model.note_option_comparison(FORWARDS, options, 0.01, 0.012, n_paths=2000)[0]
        discount = model._market_discount_factors(FORWARDS, [36 / DAYS_PER_YEAR])[0]
        self.assertAlmostEqual(row["market_vol"], model._implied_normal_vol(
            "call", options[0]["market_price"], FUTURES_PRICE, 105.5, 36 / DAYS_PER_YEAR, discount), places=9)
        self.assertAlmostEqual(row["market_yield_vol"], 1e4 * row["market_vol"] / (FUTURES_PRICE * row["duration"]), places=9)
        self.assertAlmostEqual(row["model_yield_vol"], 1e4 * row["model_vol"] / (FUTURES_PRICE * row["duration"]), places=9)
        low = model.note_option_comparison(FORWARDS, options, 0.01, 0.012, n_paths=2000, ctd_coupon=0.02)[0]
        self.assertAlmostEqual(low["duration"], model._note_duration(FORWARDS, 36 / 365.0, 6.75, 0.02), places=12)
        self.assertGreater(low["duration"], row["duration"])
        self.assertGreater(row["market_yield_vol"], 50)               # basis points a year: the order of the market's
        self.assertLess(row["market_yield_vol"], 200)

    def test_the_error_is_the_relative_error_of_the_volatility(self):
        options = synthetic_options(0.01, 0.012, days=[36], strikes=[105.5], n_paths=2000)[:1]
        row = model.note_option_comparison(FORWARDS, options, 0.01, 0.0144, n_paths=2000)[0]     # 20% too much sigma2
        self.assertAlmostEqual(row["error"], (row["model_vol"] - row["market_vol"]) / row["market_vol"], places=12)
        self.assertGreater(row["error"], 0.1)


class TestCalibration(unittest.TestCase):

    def test_a_volatility_that_made_the_prices_is_found_again(self):
        options = synthetic_options(0.01, 0.0113)
        fit = model.calibrate_note_options(FORWARDS, options, sigma2=0.02, n_paths=4000)
        self.assertAlmostEqual(fit["sigma2"], 0.0113, delta=2e-5)
        self.assertLess(fit["error"], 1e-3)
        self.assertEqual(fit["options_used"], len(options))
        self.assertGreater(fit["evaluations"], 5)

    def test_the_parameters_not_fitted_keep_their_values(self):
        options = synthetic_options(0.014, 0.0113)
        fit = model.calibrate_note_options(FORWARDS, options, sigma1=0.014, a=1.0, b=0.15, n_paths=4000)
        self.assertEqual((fit["a"], fit["b"], fit["sigma1"]), (1.0, 0.15, 0.014))

    def test_two_parameters_can_be_fitted_together(self):
        options = synthetic_options(0.014, 0.0113)
        fit = model.calibrate_note_options(FORWARDS, options, fit=("sigma1", "sigma2"), sigma1=0.02, sigma2=0.02, n_paths=4000)
        self.assertLess(fit["error"], 2e-3)
        prices = model.price_note_future_options_mc(FORWARDS, options, fit["sigma1"], fit["sigma2"], n_paths=4000)
        np.testing.assert_allclose(prices, [o["market_price"] for o in options], rtol=0.02)

    def test_the_mean_reversion_speed_of_the_level_can_be_fitted_too(self):
        options = synthetic_options(0.01, 0.0113, b=0.8, days=[70, 120], n_paths=4000)
        fit = model.calibrate_note_options(FORWARDS, options, fit=("b",), b=0.15, sigma2=0.0113, n_paths=4000)
        self.assertGreater(fit["b"], 0.4)                              # from 0.15 towards the 0.8 that made the prices
        self.assertEqual(fit["sigma2"], 0.0113)

    def test_the_fit_is_not_thrown_by_prices_that_are_a_little_off(self):
        options = synthetic_options(0.01, 0.0113)
        rng = np.random.default_rng(1)
        for option in options:
            option["market_price"] *= 1 + 0.02 * rng.standard_normal()
        fit = model.calibrate_note_options(FORWARDS, options, sigma2=0.02, n_paths=4000)
        self.assertAlmostEqual(fit["sigma2"], 0.0113, delta=6e-4)

    def search_only_at_the_start(self):
        """Makes the search of calibrate_note_options a look at its starting point, returning where that is and how it fares."""
        starts = []

        def look(objective, start, **keywords):
            starts.append(np.array(start))
            return np.array(start), objective(np.array(start))

        patcher = mock.patch.object(model, "_nelder_mead", look)
        patcher.start()
        self.addCleanup(patcher.stop)
        return starts

    def test_the_search_starts_from_the_values_given_for_the_parameters_to_fit(self):
        starts = self.search_only_at_the_start()
        options = synthetic_options(0.01, 0.0113)
        fit = model.calibrate_note_options(FORWARDS, options, fit=("sigma1", "sigma2"), sigma1=0.02, sigma2=0.03,
                                           a=1.7, n_paths=1000)
        np.testing.assert_allclose(np.exp(starts[0]), [0.02, 0.03])
        self.assertAlmostEqual(fit["sigma1"], 0.02, places=12)
        self.assertAlmostEqual(fit["sigma2"], 0.03, places=12)
        self.assertEqual(fit["a"], 1.7)

    def test_the_error_is_the_root_mean_square_of_the_prices_off_in_units_of_volatility(self):
        # At a place of the search's choosing, by hand: each option's price error over its vega times its volatility.
        self.search_only_at_the_start()
        options = synthetic_options(0.01, 0.0113, days=[36, 70], strikes=[104.5, 105.5, 106.5])
        for option in options:
            option["market_price"] *= 1.03
        fit = model.calibrate_note_options(FORWARDS, options, sigma1=0.01, sigma2=0.0125, n_paths=4000)
        prices = model.price_note_future_options_mc(FORWARDS, options, 0.01, 0.0125, n_paths=4000)
        errors = []
        for option, price in zip(options, prices):
            years = option["expiry_years"]
            discount = model._market_discount_factors(FORWARDS, [years])[0]
            vol = model._implied_normal_vol(option["type"], option["market_price"], FUTURES_PRICE, option["strike"], years, discount)
            vega = model._bachelier_vega(FUTURES_PRICE, option["strike"], vol, years, discount)
            errors.append((price - option["market_price"]) / (vega * vol))
        self.assertAlmostEqual(fit["error"], math.sqrt(np.mean(np.square(errors))), places=12)

    def test_the_fitted_error_is_the_root_mean_square_of_the_volatility_errors(self):
        options = synthetic_options(0.01, 0.0113)
        for option in options:
            option["market_price"] *= 1.03
        fit = model.calibrate_note_options(FORWARDS, options, n_paths=4000)
        rows = model.note_option_comparison(FORWARDS, options, fit["sigma1"], fit["sigma2"], n_paths=4000)
        errors = np.array([r["error"] for r in rows])
        self.assertAlmostEqual(fit["error"], float(np.sqrt(np.mean(errors ** 2))), delta=0.15 * fit["error"])

    def test_options_with_no_volatility_or_far_from_the_money_or_too_soon_are_left_out(self):
        options = synthetic_options(0.01, 0.0113, days=[36], strikes=[105.5, 112.0])
        self.assertEqual(len(model._usable_note_options(FORWARDS, options, 10 / 365.0, 2.0)[0]), 2)       # 112 is 6 st.dev. out
        self.assertEqual(len(model._usable_note_options(FORWARDS, options, 10 / 365.0, 10.0)[0]), 4)
        self.assertEqual(len(model._usable_note_options(FORWARDS, options, 40 / 365.0, 10.0)[0]), 0)      # 36 days is too soon
        broke = dict(options[0], market_price=0.0)                                                          # nothing to speak of
        self.assertEqual(len(model._usable_note_options(FORWARDS, [broke], 10 / 365.0, float("inf"))[0]), 0)
        self.assertEqual(len(model._usable_note_options(FORWARDS, [broke], 10 / 365.0, 2.0)[0]), 0)
        below = dict(options[0], strike=100.0, type="call", market_price=3.0)                               # below intrinsic
        self.assertEqual(len(model._usable_note_options(FORWARDS, [below], 10 / 365.0, 20.0)[0]), 0)

    def test_the_weights_turn_a_price_error_into_a_volatility_error(self):
        option = synthetic_options(0.01, 0.0113, days=[36], strikes=[105.5])[0]
        usable, weights = model._usable_note_options(FORWARDS, [option], 10 / 365.0, 2.0)
        discount, vol, weight, moneyness = model._market_view(FORWARDS, option)
        self.assertAlmostEqual(weights[0], weight)
        bumped = model._bachelier_price("call", FUTURES_PRICE, 105.5, vol * 1.01, 36 / 365.0, discount) - option["market_price"]
        self.assertAlmostEqual(bumped * weight, 0.01, places=3)          # a 1% higher volatility is a 1% error
        self.assertAlmostEqual(moneyness, 0.0, places=9)

    def test_a_calibration_with_nothing_to_fit_to_says_so(self):
        too_soon = synthetic_options(0.01, 0.0113, days=[5], strikes=[105.5])
        too_far = synthetic_options(0.01, 0.0113, days=[36], strikes=[111.5])         # 3 standard deviations out
        for options in (too_soon, too_far):
            with self.assertRaises(ValueError) as caught:
                model.calibrate_note_options(FORWARDS, options)
            self.assertIn("no option can be used", str(caught.exception))
        model.calibrate_note_options(FORWARDS, too_far, moneyness_window=20.0)

    def test_the_parameters_to_fit_are_checked(self):
        options = synthetic_options(0.01, 0.0113, days=[36], strikes=[105.5])
        with self.assertRaises(ValueError) as caught:
            model.calibrate_note_options(FORWARDS, options, fit=("sigma3",))
        self.assertIn("'sigma3'", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            model.calibrate_note_options(FORWARDS, options, fit=())
        self.assertIn("names no parameter", str(caught.exception))


def sofr_options_from(sigma1, sigma2, a, curve_real_months, n_paths):
    """SOFR futures options whose market prices are the model's own at these parameters."""
    theta_bar = model._fit_sofr_theta_bar(FORWARDS, curve_real_months, a=a)
    options = []
    for expiry_months, start in ((3, 4), (6, 7), (9, 10), (12, 13)):
        price = 100 - 100 * float(np.mean(FORWARDS[start - 1:start + 2]))
        for strike in (price - 0.25, price, price + 0.25):
            for kind in ("call", "put"):
                option = {"type": kind, "strike": strike, "expiry_months": expiry_months, "quarter_start_months": start,
                          "quarter_end_months": start + 3, "underlying_price": price, "market_price": 0.0}
                option["market_price"] = model.price_sofr_future_option_mc(FORWARDS, option, sigma1, sigma2, n_paths, 42,
                                                                          a=a, theta_bar=theta_bar)
                options.append(option)
    return options


class TestFittingBothKindsOfOption(unittest.TestCase):

    def setUp(self):
        self.sofr = sofr_options_from(0.012, 0.01, 1.5, 24, n_paths=300)
        self.notes = synthetic_options(0.012, 0.01, a=1.5, n_paths=1500)

    def test_the_parameters_that_made_both_sets_of_prices_fit_with_no_error(self):
        fit = model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, self.sofr, self.notes, 24, fit=("sigma2",),
                                                    a=1.5, sigma1=0.012, sigma2=0.02, sofr_paths=300, note_paths=1500)
        self.assertAlmostEqual(fit["sigma2"], 0.01, delta=5e-5)
        self.assertLess(fit["error"], 1e-3)
        self.assertEqual(fit["a"], 1.5)

    def test_all_three_can_be_fitted_and_the_error_puts_the_two_kinds_together(self):
        fit = model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, self.sofr, self.notes, 24, a=1.0, sigma1=0.02,
                                                    sigma2=0.02, sofr_paths=300, note_paths=1500)
        self.assertLess(fit["error"], 0.02)
        self.assertAlmostEqual(fit["error"], math.sqrt(fit["sofr_error"] ** 2 + fit["note_error"] ** 2), places=12)
        self.assertEqual(fit["sofr_options_used"], len(self.sofr))
        self.assertEqual(fit["note_options_used"], len(self.notes))
        self.assertAlmostEqual(fit["theta_bar"], model._fit_sofr_theta_bar(FORWARDS, 24, a=fit["a"]), places=12)

    def test_the_sofr_options_of_the_first_months_are_left_out_by_default(self):
        fit = model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, self.sofr, self.notes, 24, fit=("sigma2",),
                                                    a=1.5, sigma1=0.012, sofr_paths=300, note_paths=1500)
        self.assertEqual(fit["sofr_options_used"], len(self.sofr))                 # the earliest here are at 3 months
        fit = model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, self.sofr, self.notes, 24, fit=("sigma2",),
                                                    a=1.5, sigma1=0.012, sofr_paths=300, note_paths=1500,
                                                    sofr_min_expiry_months=7)
        self.assertEqual(fit["sofr_options_used"], len(self.sofr) // 2)

    def test_when_the_two_kinds_of_option_disagree_the_fit_is_between_them(self):
        sofr = sofr_options_from(0.012, 0.008, 1.5, 24, n_paths=300)                 # the short rate's options say 0.008
        notes = synthetic_options(0.012, 0.014, a=1.5, n_paths=1500)                  # the note's, 0.014
        fit = model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, sofr, notes, 24, fit=("sigma2",), a=1.5,
                                                    sigma1=0.012, sofr_paths=300, note_paths=1500)
        self.assertGreater(fit["sigma2"], 0.0085)
        self.assertLess(fit["sigma2"], 0.0135)
        self.assertGreater(fit["sofr_error"], 0.01)
        self.assertGreater(fit["note_error"], 0.01)

    def test_each_kinds_error_is_worked_out_on_its_own_curve_in_units_of_volatility(self):
        patcher = mock.patch.object(model, "_nelder_mead", lambda objective, start, **keywords: (np.array(start), objective(np.array(start))))
        patcher.start()
        self.addCleanup(patcher.stop)
        sofr_curve = FORWARDS + 0.003
        a, sigma1, sigma2 = 1.5, 0.011, 0.013
        fit = model.calibrate_sofr_and_note_options(sofr_curve, FORWARDS, self.sofr, self.notes, 24, fit=("sigma2",), a=a,
                                                    sigma1=sigma1, sigma2=sigma2, sofr_paths=300, note_paths=1500)
        theta_bar = model._fit_sofr_theta_bar(sofr_curve, 24, a=a)
        sofr_errors = []
        for option in self.sofr:
            years = option["expiry_months"] / 12.0
            discount = model._market_discount_factors(sofr_curve, [years])[0]
            vol = model._implied_normal_vol(option["type"], option["market_price"], option["underlying_price"],
                                            option["strike"], years, discount)
            vega = model._bachelier_vega(option["underlying_price"], option["strike"], vol, years, discount)
            price = model.price_sofr_future_option_mc(sofr_curve, option, sigma1, sigma2, 300, 42, a=a, theta_bar=theta_bar)
            sofr_errors.append((price - option["market_price"]) / (vega * vol))
        note_prices = model.price_note_future_options_mc(FORWARDS, self.notes, sigma1, sigma2, a=a, n_paths=1500)
        note_errors = []
        for option, price in zip(self.notes, note_prices):
            years = option["expiry_years"]
            discount = model._market_discount_factors(FORWARDS, [years])[0]
            vol = model._implied_normal_vol(option["type"], option["market_price"], FUTURES_PRICE, option["strike"], years, discount)
            vega = model._bachelier_vega(FUTURES_PRICE, option["strike"], vol, years, discount)
            note_errors.append((price - option["market_price"]) / (vega * vol))
        self.assertAlmostEqual(fit["sofr_error"], math.sqrt(np.mean(np.square(sofr_errors))), places=12)
        self.assertAlmostEqual(fit["note_error"], math.sqrt(np.mean(np.square(note_errors))), places=12)
        self.assertAlmostEqual(fit["theta_bar"], theta_bar, places=12)
        self.assertGreater(fit["sofr_error"], 0.02)                          # (the numbers differ: the curves are not the same)

    def test_each_kind_of_option_needs_some_and_the_sofr_ones_the_price_of_their_future(self):
        with self.assertRaises(ValueError) as caught:
            model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, self.sofr, [], 24)
        self.assertIn("0 note options", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, [], self.notes, 24)
        self.assertIn("0 SOFR options", str(caught.exception))
        without = [{k: v for k, v in o.items() if k != "underlying_price"} for o in self.sofr]
        with self.assertRaises(ValueError) as caught:
            model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, without, self.notes, 24)
        self.assertIn("underlying_price", str(caught.exception))
        with self.assertRaises(ValueError):
            model.calibrate_sofr_and_note_options(FORWARDS, FORWARDS, self.sofr, self.notes, 24, fit=("b",))


class NoteOptionsLispTestCase(OptionChainTestCase):
    """The Lisp side: ZN rows from a chain, and the builtins."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "note_options.lsp")')
        self.env[lisp_core.Symbol("forwards")] = lisp_core.LispVector([float(f) for f in FORWARDS])

    def lisp_rows(self, options):
        """Source for the rows (type strike days futures-price market-price) of Python's options."""
        return "'(%s)" % " ".join('("%s" %r %d %r %r)' % (o["type"], float(o["strike"]), round(o["expiry_years"] * DAYS_PER_YEAR),
                                                          float(o["futures_price"]), float(o["market_price"])) for o in options)

    def alist(self, name):
        """A value of the last result, an association list."""
        return self.run_lisp("(cdr (assoc '%s result))" % name)


class TestNoteOptionRows(NoteOptionsLispTestCase):

    def setUp(self):
        super().setUp()
        self.make_chain([
            {"strike": 104.0, "bid": 1.5, "ask": 1.6, "type": "Call", "underlying_price": 105.5},
            {"strike": 104.0, "bid": 0.25, "ask": 0.3, "type": "Put", "underlying_price": 105.5},
            {"strike": 106.0, "bid": 0.0, "ask": 0.1, "type": "Call", "underlying_price": 105.5},          # no bid
            {"strike": 107.0, "bid": 0.3, "ask": 0.0, "type": "Call", "underlying_price": 105.5},          # no ask
            {"strike": 104.0, "bid": 1.0, "ask": 1.2, "type": "Call", "underlying_price": 105.9,
             "expiration": datetime.date(2026, 12, 24)},
            {"strike": 104.0, "bid": 0.9, "ask": 1.0, "type": "Call", "expiration": datetime.date(2026, 10, 20)},   # 5 days
            {"strike": 104.0, "bid": 0.9, "ask": 1.0, "type": "Call", "expiration": datetime.date(2028, 3, 24)},    # far
        ])

    def test_the_rows_are_the_options_with_a_bid_and_an_ask_in_a_range_of_days(self):
        self.assertShows('(note-option-rows chain :day (date 2026 10 15))',
                         '(("call" 104.0 36 105.5 1.55) ("put" 104.0 36 105.5 0.275) ("call" 104.0 70 105.9 1.1))')

    def test_the_range_of_days_can_be_changed(self):
        self.assertShows('(length (note-option-rows chain :day (date 2026 10 15) :min-days 1))', "4")
        self.assertShows('(length (note-option-rows chain :day (date 2026 10 15) :max-days 40))', "2")
        self.assertShows('(length (note-option-rows chain :day (date 2026 10 15) :min-days 6 :max-days 36))', "2")
        self.assertShows('(length (note-option-rows chain :day (date 2026 10 15) :min-days 36))', "3")        # 36 days is enough
        self.assertShows('(length (note-option-rows chain :day (date 2026 10 15) :min-days 37))', "1")
        self.assertShows('(length (note-option-rows chain :day (date 2026 10 15) :min-days 0 :max-days 700))', "5")      # with the 5 days one, and one 526 days out

    def test_the_days_are_counted_from_today_if_no_day_is_given(self):
        with mock.patch.object(lisp_clock, "now", lambda: datetime.datetime(2026, 10, 15, 11, 0)):
            self.assertShows('(note-option-rows chain)',
                             '(("call" 104.0 36 105.5 1.55) ("put" 104.0 36 105.5 0.275) ("call" 104.0 70 105.9 1.1))')

    def test_the_type_is_in_lower_case_whatever_the_chain_calls_it(self):
        self.make_chain([{"strike": 104.0, "bid": 1.5, "ask": 1.6, "type": "CALL"}], name="shouting")
        self.assertShows('(car (car (note-option-rows shouting :day (date 2026 10 15))))', '"call"')


class TestTheBuiltins(NoteOptionsLispTestCase):

    def setUp(self):
        super().setUp()
        self.options = synthetic_options(0.01, 0.0113, days=[36, 70], strikes=[104.5, 105.5, 106.5], n_paths=3000)
        self.run_lisp("(define rows %s)" % self.lisp_rows(self.options))

    def test_the_comparison_is_a_table_of_the_options_and_their_two_prices(self):
        self.run_lisp("(define result (sofr-note-option-comparison forwards rows 0.01 0.0113 :n-paths 3000))")
        names = [str(n) for n in lisp_core.pairs_to_list(self.run_lisp("(table-column-names result)"))]
        self.assertEqual(names, ["type", "strike", "days", "futures-price", "market-price", "model-price", "market-vol",
                                 "model-vol", "market-yield-vol", "model-yield-vol", "duration", "error"])
        self.assertEqual(self.run_lisp("(table-row-count result)"), len(self.options))
        column = lambda name: [x for x in self.run_lisp('(table-column result "%s")' % name).items]
        self.assertEqual([str(x) for x in column("type")], [o["type"] for o in self.options])
        self.assertEqual(column("days"), [36] * 6 + [70] * 6)
        # (a table's numbers are single precision)
        np.testing.assert_allclose(column("strike"), [o["strike"] for o in self.options], rtol=1e-6)
        np.testing.assert_allclose(column("market-price"), [o["market_price"] for o in self.options], rtol=1e-6)
        np.testing.assert_allclose(column("model-price"), [o["market_price"] for o in self.options], rtol=1e-5)
        np.testing.assert_allclose(column("error"), 0.0, atol=1e-5)

    def test_the_comparison_is_the_models_numbers(self):
        self.run_lisp("(define result (sofr-note-option-comparison forwards rows 0.01 0.0144 :n-paths 3000 :seed 7 :a 1.5 :b 0.3"
                      " :ctd-maturity 6.0 :ctd-coupon 0.05))")
        expected = model.note_option_comparison(FORWARDS, self.options, 0.01, 0.0144, a=1.5, b=0.3, n_paths=3000, seed=7,
                                                ctd_maturity_years=6.0, ctd_coupon=0.05)
        for lisp_name, python_name in (("model-price", "model_price"), ("model-vol", "model_vol"), ("market-yield-vol", "market_yield_vol"),
                                       ("duration", "duration"), ("error", "error")):
            np.testing.assert_allclose([x for x in self.run_lisp('(table-column result "%s")' % lisp_name).items],
                                       [r[python_name] for r in expected], rtol=1e-6)

    def test_the_calibration_finds_the_volatility_that_made_the_prices(self):
        self.run_lisp("(define result (sofr-calibrate-note-options forwards rows :sigma2 0.02 :n-paths 3000))")
        self.assertAlmostEqual(self.alist("sigma2"), 0.0113, delta=3e-5)
        self.assertEqual(self.alist("a"), 1.0)
        self.assertEqual(self.alist("b"), 0.15)
        self.assertEqual(self.alist("sigma1"), 0.01)
        self.assertLess(self.alist("error"), 1e-3)
        self.assertEqual(self.alist("options-used"), 12)
        self.assertGreater(self.alist("evaluations"), 5)
        self.assertShows("(map car result)", "(a b sigma1 sigma2 error options-used evaluations)")

    def test_the_calibration_takes_the_parameters_to_fit_and_the_options_to_use(self):
        self.run_lisp("(define result (sofr-calibrate-note-options forwards rows :fit '(sigma1 sigma2) :sigma1 0.02 :sigma2 0.02"
                      " :n-paths 3000 :min-days 40 :moneyness-window 3))")
        self.assertEqual(self.alist("options-used"), 6)                            # only the 70-day options
        self.assertLess(self.alist("error"), 1e-2)                                 # (two parameters, one expiry: loosely tied)

    def test_the_window_leaves_out_the_options_far_from_the_money(self):
        self.run_lisp("(define result (sofr-calibrate-note-options forwards rows :n-paths 1000 :moneyness-window 0.3))")
        self.assertEqual(self.alist("options-used"), 4)                  # the call and put at 105.5, for both expiries

    def test_the_curve_the_rows_and_the_choices_are_checked(self):
        self.assertLispError('(sofr-calibrate-note-options 5 rows)', "forward-rates must be a vector")
        self.assertLispError("(sofr-calibrate-note-options forwards '())", "there are no option rows")
        self.assertLispError("(sofr-calibrate-note-options forwards '((\"call\" 105.0 36 105.5)))", "(type strike days futures-price market-price)")
        self.assertLispError("(sofr-calibrate-note-options forwards '((\"swap\" 105.0 36 105.5 1.0)))", 'is "call" or "put"')
        self.assertLispError("(sofr-calibrate-note-options forwards rows :sigma3 1)", ":sigma3 isn't an option")
        self.assertLispError("(sofr-calibrate-note-options forwards rows :sigma2)", ":name value pairs")
        self.assertLispError("(sofr-calibrate-note-options forwards rows :fit '(sigma3))", "'sigma3'")
        self.assertLispError("(sofr-calibrate-note-options forwards rows :min-days 400)", "no option can be used")
        self.assertLispError("(sofr-note-option-comparison (vector 0.05 0.05) rows 0.01 0.01)", "forward curve ends at")

    def test_a_rate_in_the_rows_may_be_given_as_a_whole_number(self):
        self.assertShows("(table-row-count (sofr-note-option-comparison forwards '((\"Call\" 105 36 106 1)) 0.01 0.01))", "1")


class TestTheBuiltinForBothKinds(NoteOptionsLispTestCase):

    def setUp(self):
        super().setUp()
        self.sofr = sofr_options_from(0.012, 0.01, 1.5, 24, n_paths=300)
        self.notes = synthetic_options(0.012, 0.01, a=1.5, n_paths=1500)
        self.run_lisp("(define notes %s)" % self.lisp_rows(self.notes))
        self.run_lisp("(define sofr '(%s))" % " ".join('("%s" %r %d %d %d %r %r)' % (
            o["type"], o["strike"], o["expiry_months"], o["quarter_start_months"], o["quarter_end_months"],
            o["market_price"], o["underlying_price"]) for o in self.sofr))

    def test_the_fit_agrees_with_both_kinds_of_option(self):
        self.run_lisp("(define result (sofr-calibrate-jointly forwards forwards sofr notes 24 :fit '(sigma2) :a 1.5 :sigma1 0.012"
                      " :sigma2 0.02 :sofr-paths 300 :note-paths 1500))")
        self.assertAlmostEqual(self.alist("sigma2"), 0.01, delta=1e-4)
        self.assertLess(self.alist("error"), 2e-3)
        self.assertEqual(self.alist("a"), 1.5)
        self.assertEqual(self.alist("sofr-options-used"), len(self.sofr))
        self.assertEqual(self.alist("note-options-used"), len(self.notes))
        self.assertAlmostEqual(self.alist("theta-bar"), model._fit_sofr_theta_bar(FORWARDS, 24, a=1.5), places=8)
        self.assertShows("(map car result)", "(a sigma1 sigma2 theta-bar sofr-error note-error error sofr-options-used "
                                              "note-options-used evaluations)")

    def test_the_sofr_options_start_from_the_first_curve_and_the_notes_are_centered_on_the_second(self):
        sofr_curve = FORWARDS + 0.003
        self.env[lisp_core.Symbol("sofr-curve")] = lisp_core.LispVector([float(f) for f in sofr_curve])
        self.run_lisp("(define result (sofr-calibrate-jointly sofr-curve forwards sofr notes 24 :fit '(sigma2) :a 1.5 :sigma1 0.012"
                      " :sofr-paths 300 :note-paths 1500))")
        expected = model.calibrate_sofr_and_note_options(sofr_curve, FORWARDS, self.sofr, self.notes, 24, fit=("sigma2",), a=1.5,
                                                         sigma1=0.012, sofr_paths=300, note_paths=1500)
        self.assertAlmostEqual(self.alist("sigma2"), expected["sigma2"], delta=2e-5)
        self.assertAlmostEqual(self.alist("sofr-error"), expected["sofr_error"], delta=1e-4)
        self.assertAlmostEqual(self.alist("note-error"), expected["note_error"], delta=1e-4)
        self.assertAlmostEqual(self.alist("theta-bar"), expected["theta_bar"], delta=1e-8)

    def test_the_first_months_of_the_sofr_options_can_be_kept(self):
        self.run_lisp("(define result (sofr-calibrate-jointly forwards forwards sofr notes 24 :fit '(sigma2) :a 1.5 :sigma1 0.012"
                      " :sofr-paths 300 :note-paths 1500 :sofr-min-months 7))")
        self.assertEqual(self.alist("sofr-options-used"), len(self.sofr) // 2)

    def test_the_sofr_rows_need_the_price_of_the_future(self):
        self.assertLispError("(sofr-calibrate-jointly forwards forwards (list (list \"call\" 95.0 3 4 7 0.2)) notes 24)",
                             "needs 7 items")
        self.assertLispError("(sofr-calibrate-jointly forwards forwards sofr '() 24)", "there are no option rows")
        self.assertLispError("(sofr-calibrate-jointly forwards forwards sofr notes 24 :fit '(b))", "'b'")
        self.assertLispError("(sofr-calibrate-jointly forwards forwards sofr notes 24 :b 0.2)", ":b isn't an option")
        self.assertLispError("(sofr-calibrate-jointly forwards forwards sofr notes 24 :min-days 400)",
                             "0 note options that can be used")

    def test_sofr_calibration_data_has_the_price_of_each_future_in_its_rows(self):
        curve = [{"symbol": "/SR3Z6", "start_months": 2, "end_months": 5, "rate": 0.04}]
        options = [{"type": "call", "strike": 95.75, "expiry_months": 1, "quarter_start_months": 2, "quarter_end_months": 5,
                    "market_price": 0.015, "underlying_price": 95.7375}]
        with mock.patch.object(lisp_sofr, "_fetch_sofr_calibration_data", lambda *a: (curve, options)):
            self.assertShows('(cdr (sofr-calibration-data "/nowhere"))', '(("call" 95.75 1 2 5 0.015 95.7375))')
