"""
term_structure_model.py

A simple two-factor term structure ("Hull-White style") model:

  1. bootstrap_forward_curve(...) / bootstrap_sofr_curve(...)
     Turn a handful of market yields -- either T-bill rates + semiannual
     par bond yields, or a strip of exchange-traded 3-month SOFR futures
     -- into a full curve of 1-month forward rates, one for every month
     out to 30 years.

  2. simulate_rate_factors(...) / simulate_rate_paths(...)
     The model's two random factors -- how far the short rate, and the
     long-run level it follows, have strayed from where today's curve has
     them -- simulated by Monte Carlo, and the paths of rates they make when
     they bend the market's curve (see THE IDEA below).

  3. price_note_future_options_mc(...) / price_sofr_future_options_mc(...)
     Options on the 10-year note future and on 3-month SOFR futures, priced
     on those same paths.

  4. calibrate_to_note_options(...) / calibrate_to_sofr_options(...) /
     calibrate_rate_model(...)
     Find the model's parameters (the short rate's mean-reversion speed a,
     and the volatilities sigma1 and sigma2 of the two factors) for which its
     prices of real options are nearest the market's: one kind, or both
     together (calibrate_rate_model, the one to use).

  5. price_callable_bond_mc(...)
     A callable bond, priced on the paths at a given option-adjusted spread.

This module is deliberately free of any network/broker dependency -- it
only ever sees plain numbers. Real market data (SOFR futures prices,
option quotes) is fetched separately by sofr_market_data.py, which
shapes tastytrade data into the dicts these functions expect.

DESIGN PHILOSOPHY: this code favors readability over speed or textbook
completeness. Every simplifying assumption is called out in a comment
starting with "SIMPLIFICATION:". Read those before using this for anything
beyond learning / prototyping. No exotic libraries are used -- just numpy
for arrays and plain Python loops, so every step can be traced by hand.
"""

import math

import numpy as np

# ---------------------------------------------------------------------------
# Fixed model constants -- feel free to change these
# ---------------------------------------------------------------------------

# How fast the short-rate factor pulls back toward the mean-reversion level.
SHORT_RATE_REVERSION_SPEED = 1.0     # "a" -- bigger = snaps back faster

# How fast the mean-reversion level itself drifts back to its long-run average.
MEAN_LEVEL_REVERSION_SPEED = 0.15    # "b" -- much slower than the short rate

MONTHS_PER_YEAR = 12
TOTAL_MONTHS = 30 * MONTHS_PER_YEAR   # 360 -- 30 years of monthly forwards


# ---------------------------------------------------------------------------
# Small numerical helpers: bisection root-finder and Nelder-Mead simplex
# minimizer (both replace scipy.optimize)
# ---------------------------------------------------------------------------

def _bisection(f, lo, hi, tol=1e-8, max_iter=100):
    """Find x such that f(x) == 0, given f(lo) and f(hi) have opposite signs."""
    f_lo = f(lo)
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        if abs(f_mid) < tol:
            return mid
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def _nelder_mead(objective, x0, step=0.5, max_iter=200, xtol=1e-6, ftol=1e-8,
                  alpha=1.0, gamma=2.0, rho=0.5, shrink=0.5):
    """
    Minimal Nelder-Mead simplex minimizer of objective(x) -> scalar, where
    x is a 1-D numpy array. The calibrations search with it (see _search()).

    METHOD: the textbook simplex algorithm -- track n+1 points (a
    "simplex") for an n-dimensional problem; each iteration, reflect the
    worst point through the centroid of the rest, and expand, contract,
    or shrink the simplex depending on whether that improves things.
    SIMPLIFICATION: this collapses the textbook's separate "inside" and
    "outside" contraction cases into one (contract toward the centroid
    whenever reflection doesn't beat the second-worst point) -- a common
    simplification that's a little less thorough about which side to
    contract toward, but simpler to trace by hand and works fine in
    practice for a smooth, low-dimensional objective like this one.

    x0: starting point. The initial simplex is x0 plus one point per
        dimension, each nudged by `step` along that axis.

    Returns (best_x, best_f).
    """
    n = len(x0)
    simplex = [np.array(x0, dtype=float)]
    for i in range(n):
        point = np.array(x0, dtype=float)
        point[i] += step
        simplex.append(point)
    f_values = [objective(p) for p in simplex]

    for _ in range(max_iter):
        order = np.argsort(f_values)
        simplex = [simplex[i] for i in order]
        f_values = [f_values[i] for i in order]

        spread_x = max(np.max(np.abs(simplex[i] - simplex[0])) for i in range(1, n + 1))
        spread_f = abs(f_values[-1] - f_values[0])
        if spread_x < xtol and spread_f < ftol:
            break

        centroid = np.mean(simplex[:-1], axis=0)  # every point except the worst
        worst, f_worst = simplex[-1], f_values[-1]
        f_best, f_second_worst = f_values[0], f_values[-2]

        reflected = centroid + alpha * (centroid - worst)
        f_reflected = objective(reflected)

        if f_best <= f_reflected < f_second_worst:
            simplex[-1], f_values[-1] = reflected, f_reflected
            continue

        if f_reflected < f_best:
            expanded = centroid + gamma * (reflected - centroid)
            f_expanded = objective(expanded)
            if f_expanded < f_reflected:
                simplex[-1], f_values[-1] = expanded, f_expanded
            else:
                simplex[-1], f_values[-1] = reflected, f_reflected
            continue

        contracted = centroid + rho * (worst - centroid)
        f_contracted = objective(contracted)
        if f_contracted < f_worst:
            simplex[-1], f_values[-1] = contracted, f_contracted
            continue

        best = simplex[0]
        for i in range(1, n + 1):
            simplex[i] = best + shrink * (simplex[i] - best)
            f_values[i] = objective(simplex[i])

    order = np.argsort(f_values)
    return simplex[order[0]], f_values[order[0]]


# ---------------------------------------------------------------------------
# Step 1: bootstrap the curve of 1-month forward rates
# ---------------------------------------------------------------------------

def bootstrap_forward_curve(rates):
    """
    Bootstrap a monthly curve of 1-month forward rates from market yields.

    rates: dict with these keys, values as decimals (5% -> 0.05):
        '3m', '6m', '12m'         -- T-bill rates (simple / money-market yield)
        '2y', '5y', '10y', '30y'  -- semiannual-coupon par bond yields

    Returns a dict:
        'months'          -- [1, 2, ..., 360]
        'forward_rates'   -- 1-month forward rate for each of those months
                              (annualized, simple monthly compounding, so
                              a path discounts one month at rate/12)
        'anchor_times'    -- bootstrapped zero-curve maturities (years),
                              kept around for reference / debugging
        'anchor_zeros'    -- zero rates (continuously compounded) at those
                              maturities
    """
    # --- Step 1a: turn the three T-bill rates into zero rates -------------
    # SIMPLIFICATION: T-bill rates are treated as simple money-market
    # yields, i.e. price = 100 / (1 + bill_rate * years). That price is
    # then converted into a continuously-compounded zero rate, purely
    # because continuous compounding makes the interpolation math below
    # a one-liner (discount factor = exp(-zero_rate * time)).
    anchor_times = []
    anchor_zeros = []
    for years, key in [(0.25, '3m'), (0.5, '6m'), (1.0, '12m')]:
        bill_rate = rates[key]
        discount_factor = 1.0 / (1.0 + bill_rate * years)
        zero_rate = -np.log(discount_factor) / years
        anchor_times.append(years)
        anchor_zeros.append(zero_rate)

    # --- Step 1b: bootstrap the par bonds, from short to long maturity ----
    # For each par bond maturity, every coupon date before maturity is
    # priced off the zero curve we've already built (interpolated). Only
    # the zero rate AT the new maturity is unknown, so we solve for the
    # single value that makes the bond price equal par (100).
    for maturity_years, key in [(2, '2y'), (5, '5y'), (10, '10y'), (30, '30y')]:
        par_yield = rates[key]
        coupon = 100 * par_yield / 2  # semiannual coupon on 100 face
        coupon_dates = np.arange(0.5, maturity_years + 0.001, 0.5)

        def price_at(candidate_zero, coupon_dates=coupon_dates,
                     maturity_years=maturity_years, coupon=coupon):
            # Build a temporary curve: existing anchors + this trial point.
            trial_times = anchor_times + [maturity_years]
            trial_zeros = anchor_zeros + [candidate_zero]
            zero_at = np.interp(coupon_dates, trial_times, trial_zeros)
            discount_factors = np.exp(-zero_at * coupon_dates)
            price = coupon * np.sum(discount_factors[:-1]) \
                + (100 + coupon) * discount_factors[-1]
            return price

        solved_zero = _bisection(lambda z: price_at(z) - 100, lo=0.0001, hi=0.30)
        anchor_times.append(maturity_years)
        anchor_zeros.append(solved_zero)

    # --- Step 1c: build a monthly zero curve, then convert to 1-month ------
    # forward rates.
    months = np.arange(1, TOTAL_MONTHS + 1)
    year_fractions = months / MONTHS_PER_YEAR
    zero_at_month = np.interp(year_fractions, anchor_times, anchor_zeros)
    discount_factors = np.exp(-zero_at_month * year_fractions)
    discount_factors = np.concatenate(([1.0], discount_factors))  # prepend DF(0)=1

    # (1 + F/12) = DF(m-1) / DF(m)  ->  F = 12 * (DF(m-1)/DF(m) - 1)
    forward_rates = 12.0 * (discount_factors[:-1] / discount_factors[1:] - 1.0)

    return {
        'months': months.tolist(),
        'forward_rates': forward_rates.tolist(),
        'anchor_times': anchor_times,
        'anchor_zeros': anchor_zeros,
    }


# ---------------------------------------------------------------------------
# Step 1 (alternate source): bootstrap the curve from exchange-traded
# 3-month SOFR futures instead of T-bills/par bonds
# ---------------------------------------------------------------------------

def bootstrap_sofr_curve(sofr_futures):
    """
    Bootstrap a monthly curve of 1-month forward rates from a strip of
    exchange-traded CME 3-Month SOFR (SR3) futures.

    sofr_futures: list of dicts, one per futures contract, each with:
        'start_months' -- int, months from today when this future's
                           3-month reference (accrual) quarter BEGINS
                           (0 if the quarter has already begun, i.e. this
                           is the front/currently-accruing contract)
        'end_months'   -- int, months from today when that quarter ENDS
                           (the future's own settlement date)
        'rate'         -- decimal rate implied by the future's price,
                           i.e. (100 - price) / 100

    Returns a dict shaped like bootstrap_forward_curve()'s output:
        'months'          -- [1, 2, ..., 360]
        'forward_rates'   -- 1-month forward rate for each of those months
        'quarters'        -- the input list, sorted by start_months (kept
                              around for reference/debugging)

    SIMPLIFICATIONS:
      - A 3-Month SOFR future settles to 100 minus the COMPOUNDED average
        daily SOFR over its reference quarter. This treats that as a flat
        1-month forward rate applied to every month the quarter covers --
        no attempt to back out day-by-day forwards, and no convexity
        adjustment between the futures-implied rate and a true forward
        rate (a standard simplification for short-dated strips; the
        convexity effect is only a few basis points out to ~2 years).
      - Months before the first future's start (front-contract stub) and
        any gap between non-adjacent contract months use the nearest
        available future's rate, held flat.
      - Months beyond the last supplied future are extrapolated flat at
        that future's rate -- there's no market information further out
        than what was supplied.
    """
    quarters = sorted(sofr_futures, key=lambda q: q['start_months'])
    months = np.arange(1, TOTAL_MONTHS + 1)

    # Default fill covers "beyond the last future" -- everything else
    # below overwrites this with a more specific rate.
    forward_rates = np.full(TOTAL_MONTHS, quarters[-1]['rate'])

    # Front-contract stub: months up to and including the first future's
    # start get that future's rate.
    first_start = max(quarters[0]['start_months'], 0)
    if first_start > 0:
        forward_rates[months <= first_start] = quarters[0]['rate']

    # Each future's own coverage window.
    for q in quarters:
        start, end = max(q['start_months'], 0), q['end_months']
        mask = (months > start) & (months <= end)
        forward_rates[mask] = q['rate']

    # Gaps between non-adjacent contract months: fill with the earlier
    # (near) contract's rate, held flat.
    for near, far in zip(quarters[:-1], quarters[1:]):
        gap_start, gap_end = near['end_months'], far['start_months']
        if gap_end > gap_start:
            mask = (months > gap_start) & (months <= gap_end)
            forward_rates[mask] = near['rate']

    return {
        'months': months.tolist(),
        'forward_rates': forward_rates.tolist(),
        'quarters': quarters,
    }


# ---------------------------------------------------------------------------
# Step 2: the paths, and options on the 10-year note future (ZN)
# ---------------------------------------------------------------------------
#
# WHY. SOFR futures options tell the model how much the SHORT rate
# moves. A mortgage depends on the LONG end, and a 10-year note option says
# how much that moves -- directly, instead of through the model's structure.
# In this model the 10-year yield is about 10% short-rate factor and 90%
# mean-reversion-level factor (at a = 1), so these options mostly pin down
# sigma2, the volatility of the level factor. They say little about sigma1,
# and nothing about b, since the options go out only a few months. So they
# are best fit TOGETHER with the SOFR options (calibrate_rate_model).
#
# THE IDEA. Simulate the model's two factors forward by Monte Carlo, from
# them work out the price of a note at each option's expiry, and price the
# option as the average discounted payoff over the paths. Then vary the
# parameters until the model's prices are near the market's. Four things make
# that work for a note future (and the same, but for the note, for a SOFR future):
#
#   1. TODAY'S CURVE IS THE CENTER. A model's own starting curve (a short rate
#      and a long-run level, blended exponentially) is too crude to match a
#      note: on one real day it priced the 6% 10-year note at 99.3, where
#      today's curve says 107.0 and the market's future said 105.6 -- a
#      six-point error, many times the premium of an at-the-money option
#      (about 0.9 points), which no volatility could fix. So the simulation
#      keeps only the DEVIATIONS of the two factors from their expected paths
#      (delta_r and delta_theta, which start at 0), and adds them to the
#      forward rates the market gives today:
#           f(T, T+tau) = f_market(0, T+tau) + delta_theta * (1 - exp(-a tau))
#                                            + delta_r * exp(-a tau)
#      -- the model's randomness around the market's own forward curve.
#
#   2. THE NOTE. A future on the 10-year note is settled by delivering any of
#      several notes, usually the cheapest, whose remaining maturity is not
#      ten years but 6.5 to 8 (CME's specification for the 10-Year T-Note
#      contract: at least 6 years 6 months and not more than 8 years from the
#      first day of the delivery month). Its price moves like a note of about
#      7 years' maturity, so the curve at 7 years, not at 10, is what matters.
#      SIMPLIFICATION: the future is a single representative note of
#      ctd_maturity_years (6.75) remaining at the option's expiry, with a
#      coupon that makes it a par bond on the forward curve, rather than a
#      basket with a cheapest-to-deliver switch.
#
#   3. THE FUTURE'S LEVEL. The note's model price is scaled, at each expiry, so
#      that its average over the paths is the future's price today. A future
#      is marked to market every day, so its price is a martingale: its
#      expected value at any date is today's price. The one scale absorbs what
#      isn't modeled -- the conversion factor, the basis, the carry, and the
#      convexity -- leaving the model to say how widely the price is spread
#      around it.
#
#   4. TIME IN DAYS. These options expire from one week to four months out,
#      so the paths step by the day, and an option expires on its own day, not
#      the month's end (monthly steps would put a 36-day option's expiry at 30
#      days). SIMPLIFICATION: these prices are European (the real options are
#      American, which is worth under a third of a percent of a premium at
#      these expiries, checked against a binomial tree).
#
# CALIBRATING. The error is in volatility, not price: each option's error is
# (model price - market price) / (its vega times its own volatility), the
# relative error of its volatility (a normal -- Bachelier -- volatility, in
# price points). That makes a 2-point option and a 0.1-point option, on
# different instruments, comparable, and keeps far out-of-the-money options,
# whose price barely depends on volatility, from counting: only the options
# within moneyness_window standard deviations of the money are used.

DAYS_PER_YEAR = 365.0
DEFAULT_CTD_MATURITY_YEARS = 6.75


def _normal_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bachelier_price(option_type, forward, strike, vol, years, discount):
    """
    The price of a European option on a forward price that moves as
    Brownian motion (volatility `vol` in price points per year) -- Bachelier's
    formula -- times `discount`, the discount factor to the option's expiry
    (the premium is paid now). Used only to put prices on a common footing
    (see CALIBRATING above), not to price the options in the model.
    """
    spread = vol * math.sqrt(years)
    d = (forward - strike) / spread
    intrinsic = (forward - strike) if option_type == 'call' else (strike - forward)
    sign = 1.0 if option_type == 'call' else -1.0
    return discount * (intrinsic * _normal_cdf(sign * d) + spread * _normal_pdf(d))


def _bachelier_vega(forward, strike, vol, years, discount):
    """How much the price changes for one point of volatility (see _bachelier_price)."""
    spread = vol * math.sqrt(years)
    return discount * math.sqrt(years) * _normal_pdf((forward - strike) / spread)


def _implied_normal_vol(option_type, price, forward, strike, years, discount):
    """
    The volatility (price points per year) at which _bachelier_price() gives
    `price`: found by bisection (the price rises with volatility), NaN where
    none does -- a price at or below the option's intrinsic value, say.
    """
    intrinsic = discount * max((forward - strike) if option_type == 'call' else (strike - forward), 0.0)
    if not price > intrinsic + 1e-9:
        return float('nan')
    high = max(abs(forward - strike), 1.0)
    while _bachelier_price(option_type, forward, strike, high, years, discount) < price and high < 1e6:
        high *= 2.0
    return _bisection(lambda v: _bachelier_price(option_type, forward, strike, v, years, discount) - price,
                      1e-9, high, tol=1e-10)


def _market_discount_factors(forward_rates, years):
    """
    D(0, t) for each t in `years` (an array), from the monthly forward rates:
    the product of 1 / (1 + f / 12) over the months, with the log of the
    discount factor on a straight line between month ends. The curve must
    reach as far as the latest t.
    """
    forward = np.asarray(forward_rates, dtype=float)
    if np.max(years) * MONTHS_PER_YEAR > len(forward) + 1e-9:
        raise ValueError(f"the forward curve ends at {len(forward) / MONTHS_PER_YEAR:.1f} years, "
                         f"before the {np.max(years):.1f} years that are needed")
    month_ends = np.arange(len(forward) + 1)
    log_discount = np.concatenate(([0.0], np.cumsum(-np.log1p(forward / MONTHS_PER_YEAR))))
    return np.exp(np.interp(np.asarray(years, dtype=float) * MONTHS_PER_YEAR, month_ends, log_discount))


def _note_cash_flow_times(maturity_years):
    """The times (years from the note's start date, rising) of a note's coupons: every six months back from its maturity."""
    count = int(np.ceil(maturity_years * 2 - 1e-9))
    return maturity_years - 0.5 * np.arange(count - 1, -1, -1)


def curve_par_yield(forward_rates, expiry_years, maturity_years):
    """
    The par yield -- the coupon (an annual rate, paid semiannually) that
    makes a note of maturity_years a par bond -- on the market's forward curve
    as of expiry_years from now: the one for which its price there is 100.
    With expiry_years = 0, today's par yield for that maturity.
    """
    return float(_par_yields_at_expiry(forward_rates, expiry_years, np.zeros(1), np.zeros(1), 1.0, maturity_years)[0])


def _note_cash_flows(maturity_years, coupon):
    """The note's cash flows per 100 of face, at _note_cash_flow_times()."""
    flows = np.full(len(_note_cash_flow_times(maturity_years)), 100.0 * coupon / 2.0)
    flows[-1] += 100.0
    return flows


def _discount_factors_at_expiry(forward_rates, expiry_years, delta_r, delta_theta, a, times):
    """
    D(T, T+tau), the discount factors at expiry_years (T) from now for the
    dates `times` (the taus, in years) after it, as an array with a row for each
    Monte Carlo path (its delta_r and delta_theta: numpy arrays) and a column for
    each tau.

    They come from the curve of the model (see THE IDEA above): the market's
    forward rates for those dates, plus deviations that fade from delta_r at the
    near end to delta_theta at the far end. With continuously compounded
    forwards that is closed-form:
        D(T, T+tau) = D_market(T, T+tau) * exp(-delta_theta * A(tau) - delta_r * B(tau))
        B(tau) = (1 - exp(-a tau)) / a,        A(tau) = tau - B(tau)
    (the integrals of exp(-a s) and of 1 - exp(-a s) over s from 0 to tau).
    """
    market = _market_discount_factors(forward_rates, expiry_years + times) / \
        _market_discount_factors(forward_rates, [expiry_years])[0]
    b_of_tau = -np.expm1(-a * times) / a
    a_of_tau = times - b_of_tau
    return market[None, :] * np.exp(-np.outer(delta_theta, a_of_tau) - np.outer(delta_r, b_of_tau))


def _note_prices_at_expiry(forward_rates, expiry_years, delta_r, delta_theta, a, maturity_years, coupon):
    """
    The price, per 100 of face, of a note of maturity_years remaining and the
    given coupon, at expiry_years from now, for each Monte Carlo path (its
    delta_r and delta_theta: numpy arrays), on the curve of the model (see
    _discount_factors_at_expiry()).
    """
    times = _note_cash_flow_times(maturity_years)
    discount = _discount_factors_at_expiry(forward_rates, expiry_years, delta_r, delta_theta, a, times)
    return discount @ _note_cash_flows(maturity_years, coupon)


def _par_yields_at_expiry(forward_rates, expiry_years, delta_r, delta_theta, a, maturity_years):
    """
    The par yield (the coupon, an annual rate paid semiannually, that makes the
    note worth par) of a note of maturity_years at expiry_years from now, for each
    Monte Carlo path, on the curve of the model.
    """
    times = _note_cash_flow_times(maturity_years)
    discount = _discount_factors_at_expiry(forward_rates, expiry_years, delta_r, delta_theta, a, times)
    return 2.0 * (1.0 - discount[:, -1]) / discount.sum(axis=1)


def _note_duration(forward_rates, expiry_years, maturity_years, coupon):
    """
    The duration of the note at expiry_years, on the market's curve: the fraction by which its price falls for a
    rise of 1 in all the (continuously compounded) forward rates -- the average time of its cash flows, weighted
    by their present values.
    """
    times = _note_cash_flow_times(maturity_years)
    present_values = _note_cash_flows(maturity_years, coupon) * _market_discount_factors(forward_rates, expiry_years + times)
    return float(np.sum(present_values * times) / np.sum(present_values))


def _simulate_deviations(expiry_days, sigma1, sigma2, a, b, n_paths, seed):
    """
    Monte Carlo paths of the deviations of the two factors from their expected
    paths, a day at a time (Euler steps):
        d(delta_r)     = a * (delta_theta - delta_r) * dt + sigma1 * sqrt(dt) * dW1
        d(delta_theta) = -b * delta_theta * dt           + sigma2 * sqrt(dt) * dW2
    Half the paths are the mirror images of the other half (antithetic), which
    makes their average closer to its expected value.

    Returns a dict from each day in expiry_days to (delta_r, delta_theta,
    discount_adjustment) at the end of that day, each an array with an
    entry per path. discount_adjustment = exp(-sum of delta_r * dt): what the
    paths' deviations do to the market's discount factor to that day.
    """
    wanted = set(expiry_days)
    rng = np.random.default_rng(seed)
    half = (n_paths + 1) // 2
    dt = 1.0 / DAYS_PER_YEAR
    delta_r = np.zeros(2 * half)
    delta_theta = np.zeros(2 * half)
    integral = np.zeros(2 * half)
    found = {}
    for day in range(1, max(wanted) + 1):
        z1 = rng.standard_normal(half)
        z2 = rng.standard_normal(half)
        z1 = np.concatenate([z1, -z1])
        z2 = np.concatenate([z2, -z2])
        integral += delta_r * dt
        new_delta_r = delta_r + a * (delta_theta - delta_r) * dt + sigma1 * np.sqrt(dt) * z1
        delta_theta = delta_theta - b * delta_theta * dt + sigma2 * np.sqrt(dt) * z2
        delta_r = new_delta_r
        if day in wanted:
            found[day] = (delta_r.copy(), delta_theta.copy(), np.exp(-integral))
    return found


def _expiry_day(option):
    """The option's expiry as a whole number of days from today (at least 1)."""
    return max(1, int(round(option['expiry_years'] * DAYS_PER_YEAR)))


def price_note_future_options_mc(forward_rates, options, sigma1, sigma2,
                                  a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED,
                                  n_paths=10000, seed=42,
                                  ctd_maturity_years=DEFAULT_CTD_MATURITY_YEARS, ctd_coupon=None):
    """
    Monte Carlo prices of options on the 10-year note future, as an array with
    a price per option, every price from the same Monte Carlo paths (a single
    simulation to the latest expiry), so that the prices of different strikes
    and expiries are made from the same random numbers. See THE IDEA above.

    options: a list of dicts with keys
        'type'          -- 'call' or 'put'
        'strike'        -- strike, in futures price points (e.g. 105.5)
        'expiry_years'  -- time from today until the option expires, in years
                           (calendar days / 365)
        'futures_price' -- today's price of the future the option is on
    forward_rates: the market's monthly forward rates, the curve the paths
        are centered on (use the Treasury's: see THE IDEA above).
    a, b, sigma1, sigma2: the model's parameters (the short rate's mean
        reversion speed, the level factor's, and their volatilities).
    n_paths: the number of paths (even; an odd number is rounded up).
    ctd_maturity_years, ctd_coupon: the representative note the future
        is taken to be: its remaining maturity at the option's expiry, and
        its coupon (by default the one that makes it a par bond on the
        forward curve at that date).
    """
    prices = np.zeros(len(options))
    days = [_expiry_day(o) for o in options]
    found = _simulate_deviations(days, sigma1, sigma2, a, b, n_paths, seed)
    for day in sorted(set(days)):
        expiry_years = day / DAYS_PER_YEAR
        delta_r, delta_theta, adjustment = found[day]
        coupon = ctd_coupon if ctd_coupon is not None else curve_par_yield(
            forward_rates, expiry_years, ctd_maturity_years)
        note = _note_prices_at_expiry(forward_rates, expiry_years, delta_r, delta_theta, a, ctd_maturity_years, coupon)
        relative = note / note.mean()                      # the future's price over today's: its average is 1
        discount = _market_discount_factors(forward_rates, [expiry_years])[0] * adjustment
        for i, option in enumerate(options):
            if days[i] != day:
                continue
            futures = option['futures_price'] * relative
            if option['type'] == 'call':
                payoffs = np.maximum(futures - option['strike'], 0.0)
            else:
                payoffs = np.maximum(option['strike'] - futures, 0.0)
            prices[i] = float(np.mean(discount * payoffs))
    return prices


def _sofr_expiry_day(option):
    """A SOFR option's expiry as a whole number of days from today (at least 1), from its expiry_months."""
    return max(1, int(round(option['expiry_months'] * DAYS_PER_YEAR / MONTHS_PER_YEAR)))


def _quarter_average_bend(delta_r, delta_theta, a, tau1, tau2):
    """
    How much the factors raise the average forward rate over the quarter from tau1 to tau2 years after the date they
    are of: the bend of THE IDEA above, delta_theta * (1 - exp(-a tau)) + delta_r * exp(-a tau), averaged over tau,
        delta_theta + (delta_r - delta_theta) * (exp(-a tau1) - exp(-a tau2)) / (a (tau2 - tau1))
    for each path (delta_r and delta_theta are arrays).
    """
    weight = (np.exp(-a * tau1) - np.exp(-a * tau2)) / (a * (tau2 - tau1))
    return delta_theta + (delta_r - delta_theta) * weight


def price_sofr_future_options_mc(forward_rates, options, sigma1, sigma2,
                                  a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED,
                                  n_paths=2000, seed=42):
    """
    Monte Carlo prices of options on CME 3-Month SOFR (SR3) futures, as an
    array with a price per option, on the same paths as the note options'
    (see THE IDEA above): one simulation by the day to the latest expiry.

    options: a list of dicts with keys
        'type'                  -- 'call' or 'put'
        'strike'                -- strike, in futures price points (e.g. 96.25: 100 less 3.75%)
        'expiry_months'         -- months from today until the option expires
        'quarter_start_months'  -- months from today until the future's quarter begins
        'quarter_end_months'    -- months from today until it ends
        'underlying_price'      -- the future's price today
    forward_rates: the market's monthly forward rates, which discount the
        payoffs to today. The Treasury's will do: SIMPLIFICATION, a curve a
        quarter of a point off changes a discount factor to a year by a quarter
        of a percent of a premium.

    A SOFR future settles to 100 less the rate over its quarter, and is marked
    to market every day, so its price is expected to stay where it is (as the
    note future's is, point 3 of THE IDEA). On each path, at the option's expiry,
    the factors move the rate the market expects for the quarter by their
    average bend over it (_quarter_average_bend); the future's price is today's,
    less that move (less its average over the paths, so that the price's
    average is today's: what isn't modeled, such as the convexity of the
    future, is absorbed there).

    SIMPLIFICATION: the future settles to the COMPOUNDED average of daily SOFR
    over its quarter; the move here is that of a simple average of the forward
    rates (a negligible difference for a 3-month window).
    """
    prices = np.zeros(len(options))
    days = [_sofr_expiry_day(o) for o in options]
    found = _simulate_deviations(days, sigma1, sigma2, a, b, n_paths, seed)
    for i, option in enumerate(options):
        expiry_years = days[i] / DAYS_PER_YEAR
        delta_r, delta_theta, adjustment = found[days[i]]
        tau1 = max(option['quarter_start_months'] / MONTHS_PER_YEAR - expiry_years, 0.0)
        tau2 = max(option['quarter_end_months'] / MONTHS_PER_YEAR - expiry_years, tau1 + 1.0 / MONTHS_PER_YEAR)
        move = _quarter_average_bend(delta_r, delta_theta, a, tau1, tau2)
        futures = option['underlying_price'] - 100.0 * (move - move.mean())
        if option['type'] == 'call':
            payoffs = np.maximum(futures - option['strike'], 0.0)
        else:
            payoffs = np.maximum(option['strike'] - futures, 0.0)
        discount = _market_discount_factors(forward_rates, [expiry_years])[0] * adjustment
        prices[i] = float(np.mean(discount * payoffs))
    return prices


def _continued_flat(forward_rates, months):
    """The monthly forward rates as an array of at least `months` of them: a curve that is shorter continues at its last rate."""
    forward = np.asarray(forward_rates, dtype=float)
    if len(forward) >= months:
        return forward
    return np.concatenate([forward, np.full(months - len(forward), forward[-1])])


def simulate_rate_factors(sigma1, sigma2, horizon_years, n_paths, seed=None,
                          a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED):
    """
    The model's two random factors along Monte Carlo paths, month by month: the
    heart of the paths, and all there is to them besides the market's curve.
        delta_r      -- how far the short rate has strayed from where today's
                        curve has it: it pulls back toward delta_theta, at speed a
        delta_theta  -- how far the long-run level has strayed from today's
                        curve (it pulls back toward 0, slowly, at speed b)
    both start at 0, and are stepped by the day with random shocks of size sigma1
    and sigma2 (independent). simulate_rate_paths() adds them to the market's curve.

    seed: an integer for the same paths each time; None (the default) for new ones.
    n_paths: the number of paths (an even number: an odd one is rounded up).

    Returns (years, delta_r_paths, delta_theta_paths):
        years               -- 0, 1/12, 2/12, ... out to horizon_years
        delta_r_paths       -- array (n_paths, len(years)), as rates (0.01 is one percent)
        delta_theta_paths   -- array (n_paths, len(years))
    """
    months = int(round(horizon_years * MONTHS_PER_YEAR))
    if months < 1:
        raise ValueError("the horizon must be at least a month")
    days = [int(round(month * DAYS_PER_YEAR / MONTHS_PER_YEAR)) for month in range(1, months + 1)]
    found = _simulate_deviations(days, sigma1, sigma2, a, b, n_paths, seed)
    paths = 2 * ((n_paths + 1) // 2)
    delta_r_paths = np.zeros((paths, months + 1))
    delta_theta_paths = np.zeros((paths, months + 1))
    for month in range(1, months + 1):
        delta_r_paths[:, month], delta_theta_paths[:, month], _ = found[days[month - 1]]
    return np.arange(months + 1) / MONTHS_PER_YEAR, delta_r_paths, delta_theta_paths


def _monthly_forwards(discount):
    """The one-month forward rates (annual, monthly interest: a month's money grows by 1 + rate / 12) of discount factors
    D(0), D(1 month), D(2 months), ... , where D(0) is 1: an array with a row for each path and a column for each month."""
    return MONTHS_PER_YEAR * (discount[:, :-1] / discount[:, 1:] - 1.0)


def rate_curve_on_date(forward_rates, months_ahead, delta_r, delta_theta,
                           a=SHORT_RATE_REVERSION_SPEED, months=None):
    """
    The model's forward curve on a date months_ahead from today, when the two
    factors have the values delta_r and delta_theta (a path's, at that date):
    today's curve for the dates from then on, bent by the factors. In
    continuous time the bend adds to each forward rate
        delta_theta * (1 - exp(-a tau)) + delta_r * exp(-a tau)
    at tau years after the date, so the short end follows delta_r, and the
    long end delta_theta (the two meet at the speed a). With both 0 it is
    today's curve itself: a path with no volatility. This is the curve the paths
    read what they report from: the short rate is its first month, and the par
    yield of a note is worked out from it.

    months: how many months of the curve to give (by default, all that
        forward_rates has after the date; a longer curve continues flat).

    Returns (month_numbers, today, on_date): arrays of that many monthly forward
    rates, as annual rates (a month's money grows by 1 + rate / 12) -- the rate
    for the month that starts month_number - 1 months after the date: today's
    curve, and the model's.
    """
    if months is None:
        months = len(forward_rates) - months_ahead
    if months < 1:
        raise ValueError(f"the forward curve has {len(forward_rates)} months, and nothing after month {months_ahead}")
    forward = _continued_flat(forward_rates, months_ahead + months)
    times = np.arange(months + 1) / MONTHS_PER_YEAR
    discount = _discount_factors_at_expiry(forward, months_ahead / MONTHS_PER_YEAR, np.array([delta_r]), np.array([delta_theta]), a, times)
    return np.arange(1, months + 1), forward[months_ahead:months_ahead + months], _monthly_forwards(discount)[0]


def simulate_rate_paths(forward_rates, sigma1, sigma2, horizon_years, n_paths, seed=None,
                         a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED, tenor_years=10):
    """
    Monte Carlo paths of the model that the note-option calibration fits
    (see THE IDEA above), month by month: the market's forward curve, bent by
    the two random factors of simulate_rate_factors(). The paths start where the
    market is today: the first month's short rate is the curve's first forward
    rate, and the tenor_years par yield at the start is the curve's own. With
    sigma1 = sigma2 = 0 every path is the curve itself, read forward in time.
    Each month, on each path, the two factors bend the curve (see
    rate_curve_on_date()), and what is reported is read from that curve.

    forward_rates: the market's monthly forward rates, the Treasury's (see THE
        IDEA above). SIMPLIFICATION: the yield at the end of a long horizon needs
        the curve tenor_years beyond it (a 30-year mortgage's last month needs a
        curve to year 40); where the curve is shorter, it continues flat at its
        last forward rate.
    seed: an integer for the same paths each time; None (the default) for new ones.
    n_paths: the number of paths (an even number: an odd one is rounded up).

    Returns (years, short_rate_paths, yield_paths):
        years              -- 0, 1/12, 2/12, ... out to horizon_years
        short_rate_paths   -- array (n_paths, len(years)): the model's short
                              rate at each date, the first month of its curve
                              then (the market's forward rate for the month that
                              starts then, plus the path's delta_r, to a hair)
        yield_paths        -- array (n_paths, len(years)): the par yield of a
                              note of tenor_years (as the Treasury publishes), at
                              each date, on the curve of the model that day
    """
    years, delta_r_paths, delta_theta_paths = simulate_rate_factors(sigma1, sigma2, horizon_years, n_paths, seed, a=a, b=b)
    forward = _continued_flat(forward_rates, int(len(years) - 1 + tenor_years * MONTHS_PER_YEAR) + 1)    # (a month too many is no harm)
    short_rate_paths = np.zeros(delta_r_paths.shape)
    yield_paths = np.zeros(delta_r_paths.shape)
    for month in range(len(years)):
        delta_r, delta_theta = delta_r_paths[:, month], delta_theta_paths[:, month]
        one_month = _discount_factors_at_expiry(forward, month / MONTHS_PER_YEAR, delta_r, delta_theta, a, np.array([0.0, 1.0 / MONTHS_PER_YEAR]))
        short_rate_paths[:, month] = _monthly_forwards(one_month)[:, 0]
        yield_paths[:, month] = _par_yields_at_expiry(forward, month / MONTHS_PER_YEAR, delta_r, delta_theta, a, tenor_years)
    return years, short_rate_paths, yield_paths


def simulate_mortgage_rate_paths(forward_rates, sigma1, sigma2, horizon_years, n_paths,
                                  mortgage_spread, seed=None,
                                  a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED, tenor_years=10):
    """
    Simulate a simple proxy mortgage rate alongside the model's own rate
    paths -- for Monte Carlo mortgage analysis (e.g. prepayment modeling).
    On every path, in every month,

        mortgage_rate = (the par yield of a note of tenor_years) + mortgage_spread

    where the yield (tenor_years defaults to 10, the usual rate-sensitivity
    proxy for a 30-year mortgage) is that of simulate_rate_paths(), and
    mortgage_spread is a constant spread you supply (e.g. 0.015 for 150bp).
    The paths start on forward_rates, the market's curve, so a spread found as
    today's mortgage rate less curve_par_yield(forward_rates, 0.0, 10) puts the
    first month's mortgage rate at today's.

    SIMPLIFICATION: mortgage rates actually track something closer to
    current-coupon MBS yields (which move with the whole curve,
    prepayment risk, and origination costs -- not just one point on it),
    and the mortgage-to-underlying spread is NOT constant in reality; it
    widens and narrows with MBS supply, bank demand, and rate volatility.
    A single flat spread is a deliberate simplification -- named in the
    function's own parameter (mortgage_spread) so it's obvious where to
    plug in a richer assumption later.

    Returns (years, short_rate_paths, underlying_paths, mortgage_paths): the
    years, short rates and tenor_years yields (called underlying_paths here)
    of simulate_rate_paths(), and underlying_paths + mortgage_spread.
    """
    years, short_rate_paths, underlying_paths = simulate_rate_paths(
        forward_rates, sigma1, sigma2, horizon_years, n_paths, seed, a=a, b=b, tenor_years=tenor_years)
    return years, short_rate_paths, underlying_paths, underlying_paths + mortgage_spread


def _market_view(forward_rates, option):
    """
    What the option's own market price says, as (discount, vol, weight,
    moneyness): the discount factor to its expiry; its normal volatility
    (price points per year); the weight that turns a price error into a
    relative volatility error, 1 / (vega * volatility); and how far the strike
    is from the future's price, in standard deviations of the price over
    the option's life. Where the price has no volatility (see
    _implied_normal_vol()), vol and weight are NaN and moneyness is infinite.
    """
    discount = _market_discount_factors(forward_rates, [option['expiry_years']])[0]
    forward = option['futures_price']
    vol = _implied_normal_vol(option['type'], option['market_price'], forward, option['strike'], option['expiry_years'], discount)
    if not np.isfinite(vol):
        return discount, float('nan'), float('nan'), float('inf')
    vega = _bachelier_vega(forward, option['strike'], vol, option['expiry_years'], discount)
    weight = 1.0 / (vega * vol)
    moneyness = abs(forward - option['strike']) / (vol * math.sqrt(option['expiry_years']))
    return discount, vol, weight, moneyness


def _usable_note_options(forward_rates, options, min_expiry_years, moneyness_window):
    """The options a calibration can use, with their weights: those that have a volatility, are at least min_expiry_years from expiry, and are within moneyness_window standard deviations of the money. Returns (options, weights)."""
    usable, weights = [], []
    for option in options:
        if option['expiry_years'] < min_expiry_years:
            continue
        _, _, weight, moneyness = _market_view(forward_rates, option)
        if np.isfinite(weight) and moneyness <= moneyness_window:
            usable.append(option)
            weights.append(weight)
    return usable, np.array(weights)


def note_option_comparison(forward_rates, options, sigma1, sigma2,
                            a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED,
                            n_paths=10000, seed=42,
                            ctd_maturity_years=DEFAULT_CTD_MATURITY_YEARS, ctd_coupon=None):
    """
    The model's prices of the options next to their market prices (each option's
    dict has 'market_price' too), as a list of dicts with the keys 'type',
    'strike', 'expiry_years', 'futures_price', 'market_price', 'model_price',
    'market_vol' and 'model_vol' (the normal volatility each price gives, in
    price points per year), 'market_yield_vol' and 'model_yield_vol' (the same
    as a volatility of the yield of the note the future is taken to be, in
    basis points a year: the price volatility over the price and the note's
    duration), 'duration', and 'error' (the relative error of the model's
    volatility, (model_vol - market_vol) / market_vol).
    """
    prices = price_note_future_options_mc(forward_rates, options, sigma1, sigma2, a=a, b=b, n_paths=n_paths,
                                          seed=seed, ctd_maturity_years=ctd_maturity_years, ctd_coupon=ctd_coupon)
    rows = []
    for option, price in zip(options, prices):
        discount, market_vol, _, _ = _market_view(forward_rates, option)
        model_vol = _implied_normal_vol(option['type'], float(price), option['futures_price'], option['strike'],
                                         option['expiry_years'], discount)
        coupon = ctd_coupon if ctd_coupon is not None else curve_par_yield(
            forward_rates, option['expiry_years'], ctd_maturity_years)
        duration = _note_duration(forward_rates, option['expiry_years'], ctd_maturity_years, coupon)
        row = dict(option)
        row.update({
            'model_price': float(price), 'market_vol': market_vol, 'model_vol': model_vol, 'duration': duration,
            'market_yield_vol': 1e4 * market_vol / (option['futures_price'] * duration),
            'model_yield_vol': 1e4 * model_vol / (option['futures_price'] * duration),
            'error': (model_vol - market_vol) / market_vol,
        })
        rows.append(row)
    return rows


def _search(fit, values, allowed, error_of, max_iter):
    """
    The values of the parameters named in `fit` (each one of `allowed`) for
    which error_of(parameters) -- parameters being a dict of every value -- is
    least: a Nelder-Mead search in their logarithms, so that none can go to 0 or
    below, starting from `values`, which also hold the parameters not fitted.
    Returns (the parameters at the best fit, how many sets of them were tried).
    """
    for name in fit:
        if name not in allowed:
            raise ValueError(f"fit is a list of {', '.join(repr(n) for n in allowed)}, not {name!r}")
    if not fit:
        raise ValueError("fit names no parameter to fit")
    evaluations = [0]

    def objective(log_values):
        parameters = dict(values)
        parameters.update({name: float(np.exp(x)) for name, x in zip(fit, log_values)})
        evaluations[0] += 1
        return error_of(parameters)

    best_log_values, _ = _nelder_mead(objective, np.log([values[name] for name in fit]),
                                      step=0.5, max_iter=max_iter, xtol=1e-4, ftol=1e-10)
    best = dict(values)
    best.update({name: float(np.exp(x)) for name, x in zip(fit, best_log_values)})
    return best, evaluations[0]


def _volatility_error(prices, market, weights):
    """The root mean square of the options' relative volatility errors (see CALIBRATING above)."""
    return float(np.sqrt(np.mean(((prices - market) * weights) ** 2)))


def _usable_sofr_options(forward_rates, options, min_expiry_years, min_expiry_months, moneyness_window):
    """The SOFR options a calibration can use, with their weights, as _usable_note_options() picks note options; and
    none with fewer than min_expiry_months to expiry. Returns (options, weights)."""
    usable, weights = [], []
    for option in options:
        if 'underlying_price' not in option:
            raise ValueError("each SOFR option needs 'underlying_price', the SOFR future's price today")
        years = option['expiry_months'] / MONTHS_PER_YEAR
        view = dict(option, expiry_years=years, futures_price=option['underlying_price'])
        _, _, weight, moneyness = _market_view(forward_rates, view)
        long_enough = years >= min_expiry_years and option['expiry_months'] >= min_expiry_months
        if long_enough and np.isfinite(weight) and moneyness <= moneyness_window:
            usable.append(option)
            weights.append(weight)
    return usable, np.array(weights)


def calibrate_to_note_options(forward_rates, options, fit=('sigma2',),
                            a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED,
                            sigma1=0.01, sigma2=0.01,
                            n_paths=10000, seed=42,
                            ctd_maturity_years=DEFAULT_CTD_MATURITY_YEARS, ctd_coupon=None,
                            min_expiry_years=10.0 / DAYS_PER_YEAR, moneyness_window=2.0,
                            max_iter=100):
    """
    Find the parameters in `fit` -- any of 'a', 'b', 'sigma1', 'sigma2' --
    for which the model's prices of the options (see
    price_note_future_options_mc(), whose options and other arguments
    these are; each option also has a 'market_price') are as close to the
    market's as possible, in the sense of CALIBRATING above: the root mean
    square of the options' relative volatility errors. The parameters not in
    `fit` keep the values given, which are also where the search of those that
    are starts (see _search()).

    The same random numbers are used for every set of parameters tried, so
    the Monte Carlo noise is the same at each, and the error is a smooth
    function of the parameters; the price of that is that the fit has the
    noise of those numbers in it. More paths make it less (the error of a price
    falls as the square root of their number).

    Only the options that are at least min_expiry_years from expiry and within
    moneyness_window standard deviations of the money are used (see
    CALIBRATING above).

    Returns a dict with the keys 'a', 'b', 'sigma1', 'sigma2' (their values
    at the best fit), 'error' (the root mean square relative volatility error
    there), 'options_used', and 'evaluations' (how many sets of parameters
    were tried).
    """
    usable, weights = _usable_note_options(forward_rates, options, min_expiry_years, moneyness_window)
    if not usable:
        raise ValueError("no option can be used to calibrate: each needs a market price above its intrinsic value, "
                         f"to be at least {min_expiry_years * DAYS_PER_YEAR:.0f} days from expiry and to be within "
                         f"{moneyness_window} standard deviations of the money")
    market = np.array([o['market_price'] for o in usable])

    def error_of(p):
        prices = price_note_future_options_mc(forward_rates, usable, p['sigma1'], p['sigma2'], a=p['a'], b=p['b'],
                                              n_paths=n_paths, seed=seed, ctd_maturity_years=ctd_maturity_years,
                                              ctd_coupon=ctd_coupon)
        return _volatility_error(prices, market, weights)

    best, evaluations = _search(fit, {'a': a, 'b': b, 'sigma1': sigma1, 'sigma2': sigma2},
                                ('a', 'b', 'sigma1', 'sigma2'), error_of, max_iter)
    return dict(best, error=error_of(best), options_used=len(usable), evaluations=evaluations)


def calibrate_to_sofr_options(forward_rates, options, fit=('a', 'sigma1', 'sigma2'),
                              a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED,
                              sigma1=0.01, sigma2=0.01, n_paths=2000, seed=42,
                              min_expiry_years=10.0 / DAYS_PER_YEAR, min_expiry_months=3, moneyness_window=2.0,
                              max_iter=150):
    """
    As calibrate_to_note_options(), for options on SOFR futures (see
    price_sofr_future_options_mc(), whose options and other arguments these
    are; each option also has a 'market_price'). By default it fits a, sigma1
    and sigma2. The options with fewer than min_expiry_months (3) months to
    expiry are left out: a model whose volatilities are the same at every date
    cannot match the very front of the market, where the Fed's next move is
    nearly known and the volatility is a fifth of that a year out; such options
    would decide the fit by their large relative errors, and push sigma1 to 0.

    SOFR options alone reach only two or three years, so they say little about
    the long end (sigma2): calibrate_rate_model(), with the note options too,
    is the fit to use for paths.

    Returns a dict as calibrate_to_note_options() does.
    """
    usable, weights = _usable_sofr_options(forward_rates, options, min_expiry_years, min_expiry_months, moneyness_window)
    if not usable:
        raise ValueError("no SOFR option can be used to calibrate: each needs a market price above its intrinsic value, "
                         f"to be at least {min_expiry_months} months from expiry and to be within "
                         f"{moneyness_window} standard deviations of the money")
    market = np.array([o['market_price'] for o in usable])

    def error_of(p):
        prices = price_sofr_future_options_mc(forward_rates, usable, p['sigma1'], p['sigma2'], a=p['a'], b=p['b'],
                                              n_paths=n_paths, seed=seed)
        return _volatility_error(prices, market, weights)

    best, evaluations = _search(fit, {'a': a, 'b': b, 'sigma1': sigma1, 'sigma2': sigma2},
                                ('a', 'b', 'sigma1', 'sigma2'), error_of, max_iter)
    return dict(best, error=error_of(best), options_used=len(usable), evaluations=evaluations)


def calibrate_rate_model(forward_rates, sofr_options, note_options,
                         fit=('a', 'sigma1', 'sigma2'),
                         a=SHORT_RATE_REVERSION_SPEED, sigma1=0.01, sigma2=0.01,
                         sofr_paths=2000, note_paths=10000, seed=42,
                         ctd_maturity_years=DEFAULT_CTD_MATURITY_YEARS, ctd_coupon=None,
                         min_expiry_years=10.0 / DAYS_PER_YEAR, moneyness_window=2.0,
                         sofr_min_expiry_months=3, max_iter=150):
    """
    Calibrate the model to SOFR futures options (as calibrate_to_sofr_options()
    does) AND to options on the 10-year note future (as
    calibrate_to_note_options()) together: the short-rate options pin down a and
    sigma1, the note options sigma2, and a and sigma1 together with sigma2
    decide how far apart the two sets of options' volatilities are. Both kinds
    are priced on the same paths of the same model, the one simulate_rate_paths()
    draws.

    forward_rates: the market's curve, the Treasury's, which the note options'
        paths are centered on and both kinds' payoffs are discounted on.
    sofr_options: as for calibrate_to_sofr_options(); note_options: as for
        calibrate_to_note_options(). The weights are those of CALIBRATING above, so
        the two kinds of option -- one in price points of 100 less the rate, the
        other of a note -- count alike. Each kind's error is the root mean
        square of its options' errors, and the error that is minimized is
        the square root of the two kinds' mean squares added, so that a
        kind with a poor fit pulls the parameters towards itself in
        proportion to how poor it is (the sum of the two root mean squares
        would be least at the best fit of the kind that is steeper, and
        ignore the other).
    sofr_min_expiry_months: as min_expiry_months of calibrate_to_sofr_options() (3).
    fit, a, sigma1, sigma2, ...: as for calibrate_to_note_options(). b is not
        fitted: the options reach a few months to a few years, and say nothing
        of how slowly the level reverts (MEAN_LEVEL_REVERSION_SPEED).

    Returns a dict with 'a', 'sigma1', 'sigma2', 'sofr_error' and
    'note_error' (each kind's root mean square relative volatility error,
    at the best fit), 'error' (the square root of the sum of their squares),
    'sofr_options_used', 'note_options_used', and 'evaluations'.
    """
    sofr_usable, sofr_weights = _usable_sofr_options(forward_rates, sofr_options, min_expiry_years,
                                                     sofr_min_expiry_months, moneyness_window)
    note_usable, note_weights = _usable_note_options(forward_rates, note_options, min_expiry_years, moneyness_window)
    if not sofr_usable or not note_usable:
        raise ValueError(f"there are {len(sofr_usable)} SOFR options and {len(note_usable)} note options that can be "
                         "used to calibrate; each kind needs some (see calibrate_to_note_options() for what makes one usable)")
    sofr_market = np.array([o['market_price'] for o in sofr_usable])
    note_market = np.array([o['market_price'] for o in note_usable])

    def errors_of(p):
        sofr_prices = price_sofr_future_options_mc(forward_rates, sofr_usable, p['sigma1'], p['sigma2'], a=p['a'],
                                                   n_paths=sofr_paths, seed=seed)
        note_prices = price_note_future_options_mc(forward_rates, note_usable, p['sigma1'], p['sigma2'], a=p['a'],
                                                   n_paths=note_paths, seed=seed, ctd_maturity_years=ctd_maturity_years,
                                                   ctd_coupon=ctd_coupon)
        return _volatility_error(sofr_prices, sofr_market, sofr_weights), _volatility_error(note_prices, note_market, note_weights)

    best, evaluations = _search(fit, {'a': a, 'sigma1': sigma1, 'sigma2': sigma2}, ('a', 'sigma1', 'sigma2'),
                                lambda p: float(np.hypot(*errors_of(p))), max_iter)
    sofr_error, note_error = errors_of(best)
    return dict(best, sofr_error=sofr_error, note_error=note_error, error=float(np.hypot(sofr_error, note_error)),
                sofr_options_used=len(sofr_usable), note_options_used=len(note_usable), evaluations=evaluations)


# ---------------------------------------------------------------------------
# Step 3: price a callable bond given an option-adjusted spread (OAS)
# ---------------------------------------------------------------------------

def price_callable_bond_mc(forward_rates, sigma1, sigma2, term_years,
                            coupon_rate, call_years, call_price, oas,
                            n_paths=2000, seed=123, face=100,
                            a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED):
    """
    Monte Carlo price of a callable bond, given an option-adjusted spread.
    The rates are the short-rate paths of simulate_rate_paths() (so, around
    forward_rates, the market's curve: use the Treasury's), with the fitted
    a, b, sigma1 and sigma2.

    term_years   -- bond's total maturity, in years from today
    coupon_rate  -- annual coupon rate (decimal, e.g. 0.05 for 5%), paid
                    semiannually
    call_years   -- the single date (years from today) at which the issuer
                    may call the bond (see SIMPLIFICATION below)
    call_price   -- price per 100 face the issuer pays to call the bond
    oas          -- option-adjusted spread (decimal, e.g. 0.005 for 50bp):
                    a constant spread added to every simulated short rate
                    before discounting, meant to capture the bond's
                    credit/liquidity risk on top of the risk-free curve.
                    This is an INPUT here -- you supply the OAS, the model
                    tells you the resulting price. (The reverse direction,
                    solving for the OAS that reproduces a market price, is
                    what the deal library's OAS does: lisp_interp/lib/deal_paths.lsp.)

    SIMPLIFICATIONS:
      - Models a single, one-time call right at call_years (a "European"
        call) rather than a continuously- or periodically-callable
        American/Bermudan structure. Real callable bonds are usually
        callable on any coupon date from the call date to maturity; this
        keeps the pricing a straightforward two-stage discounting exercise
        (value the bond as of the call date, compare to the call price,
        discount back to today) instead of requiring backward induction
        or Longstaff-Schwartz regression across many exercise dates.
      - The issuer's call decision uses that path's own realized future
        rates (perfect foresight along the path). A fully rigorous model
        would only let the issuer act on information available at the
        call date. This simplification tends to slightly overstate the
        value of the call option to the issuer (understate the bond price).
    """
    horizon_months = int(round(term_years * MONTHS_PER_YEAR))
    call_month = int(round(call_years * MONTHS_PER_YEAR))
    if call_month >= horizon_months:
        raise ValueError(
            "call_years must be strictly before term_years -- a bond "
            "'called' exactly at maturity is just a bond maturing.")

    _, r_paths, _ = simulate_rate_paths(forward_rates, sigma1, sigma2, term_years, n_paths, seed, a=a, b=b)
    n_paths = r_paths.shape[0]      # (rounded up to an even number)

    # Discount factors from today to every month, per path, using the
    # simulated short rate PLUS the option-adjusted spread.
    monthly_factors = 1.0 / (1.0 + (r_paths[:, :-1] + oas) / MONTHS_PER_YEAR)
    cum_df = np.cumprod(monthly_factors, axis=1)  # cum_df[:, m-1] = DF(0, m)

    coupon = face * coupon_rate / 2
    coupon_months = np.arange(6, horizon_months + 1, 6)

    df_to_call = cum_df[:, call_month - 1]  # DF(0, call_month), per path

    # Value, AS OF the call date, of all cash flows that would be paid
    # AFTER the call date if the bond were not called (the "continuation
    # value" the issuer compares to the call price).
    coupon_months_after_call = coupon_months[coupon_months > call_month]
    continuation_value = np.zeros(n_paths)
    for cm in coupon_months_after_call:
        payment = coupon + (face if cm == horizon_months else 0.0)
        df_to_payment = cum_df[:, cm - 1]
        # discount the payment from its own date back to the call date,
        # path by path, using the ratio of cumulative discount factors
        continuation_value += payment * (df_to_payment / df_to_call)

    # The issuer calls whenever continuation value exceeds the call price,
    # so the bondholder receives whichever is smaller.
    value_at_call = np.minimum(continuation_value, call_price)

    # Coupons paid before the call date are received regardless of the
    # call decision.
    coupon_months_before_call = coupon_months[coupon_months <= call_month]
    pv_coupons_before_call = np.zeros(n_paths)
    for cm in coupon_months_before_call:
        pv_coupons_before_call += coupon * cum_df[:, cm - 1]

    price_per_path = pv_coupons_before_call + value_at_call * df_to_call
    return float(np.mean(price_per_path))


# ---------------------------------------------------------------------------
# Demo -- illustrative numbers only, NOT live market data
# ---------------------------------------------------------------------------

if __name__ == '__main__':

    # An illustrative (made-up) yield curve. Replace with real market rates.
    example_curve = {
        '3m': 0.043,
        '6m': 0.041,
        '12m': 0.039,
        '2y': 0.038,
        '5y': 0.040,
        '10y': 0.043,
        '30y': 0.046,
    }

    curve = bootstrap_forward_curve(example_curve)
    forward_rates = curve['forward_rates']

    print("Bootstrapped 1-month forward rates (first 6 months):")
    for m, f in zip(curve['months'][:6], forward_rates[:6]):
        print(f"  month {m:>3}: {f:.4%}")
    print("...")
    print("Bootstrapped 1-month forward rates (last 6 months, i.e. ~year 30):")
    for m, f in zip(curve['months'][-6:], forward_rates[-6:]):
        print(f"  month {m:>3}: {f:.4%}")

    # A handful of illustrative quotes for options on the 10-year note future (the
    # future's price is made up, and so are the option prices: Bachelier's formula
    # at a volatility of 6.5 points a year). Replace with real market quotes.
    futures_price, expiry_years = 108.0, 45 / 365.0
    discount = _market_discount_factors(forward_rates, [expiry_years])[0]
    example_options = [
        {'type': kind, 'strike': strike, 'expiry_years': expiry_years, 'futures_price': futures_price,
         'market_price': _bachelier_price(kind, futures_price, strike, 6.5, expiry_years, discount)}
        for kind, strike in (('call', 107.0), ('call', 108.0), ('put', 108.0), ('put', 109.0))
    ]

    print("\nCalibrating sigma2 (the level factor's volatility) to the example "
          "option prices...")
    fit = calibrate_to_note_options(forward_rates, example_options)
    sigma1, sigma2 = fit['sigma1'], fit['sigma2']
    print(f"  fitted sigma2 = {sigma2:.5f}  (sigma1 = {sigma1:.5f}, as given)")
    print(f"  root mean square relative volatility error = {fit['error']:.5f}")

    print("\nModel price vs. market price after calibration:")
    for option, model_price in zip(example_options, price_note_future_options_mc(
            forward_rates, example_options, sigma1, sigma2)):
        print(f"  {option['type']:<4} strike {option['strike']:<7} "
              f"expiry {option['expiry_years'] * DAYS_PER_YEAR:.0f}d -> "
              f"model {model_price:.4f}  market {option['market_price']:.4f}")

    # A few paths of the calibrated model, five years: they start on the curve.
    years, short_rate_paths, ten_year_paths = simulate_rate_paths(
        forward_rates, sigma1, sigma2, 5, 1000, seed=1)
    low, middle, high = np.percentile(ten_year_paths[:, -1], [10, 50, 90])
    print(f"\nThe 10-year par yield starts at {ten_year_paths[0, 0]:.3%}; after 5 years, "
          f"over 1000 paths: p10 {low:.3%}  median {middle:.3%}  p90 {high:.3%}")

    # A small example of the callable bond pricer, using the just-calibrated
    # sigmas: a 10-year, 5% coupon bond, callable at par starting in year 3,
    # priced at a 75bp OAS.
    bond_price = price_callable_bond_mc(
        forward_rates, sigma1, sigma2,
        term_years=10, coupon_rate=0.05,
        call_years=3, call_price=100.0, oas=0.0075)
    print(f"\nCallable bond example (10y, 5% coupon, callable at 100 "
          f"starting year 3, 75bp OAS): price = {bond_price:.3f}")
