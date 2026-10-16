"""
term_structure_model.py

A simple two-factor term structure ("Hull-White style") model, built in
three steps:

  1. bootstrap_forward_curve(...) / bootstrap_sofr_curve(...)
     Turns a handful of market yields -- either T-bill rates + semiannual
     par bond yields, or a strip of exchange-traded 3-month SOFR futures
     -- into a full curve of 1-month forward rates, one for every month
     out to 30 years.

  2. price_sofr_future_option_mc(...)
     Simulates a curve forward in time with two random ("stochastic")
     factors -- a short-rate factor and a slower-moving long-term
     mean-reversion level -- using Monte Carlo, and uses the simulated
     paths to price an option on a 3-month SOFR future.

  3. calibrate_sofr_model(...) / calibrate_sofr_model_nelder_mead(...)
     Search for the model's parameters (the short rate's mean-reversion
     speed and the volatility of each factor) that make its option prices
     match a set of real SOFR futures option prices you supply.

  3b. price_note_future_options_mc(...) / calibrate_note_options(...) /
      calibrate_sofr_and_note_options(...) / simulate_curve_paths(...)
     Options on the 10-year note future, for fitting the model to real ZN
     options: the paths are centered on today's Treasury curve, step by the
     day, and the fit is of relative volatility errors (see "Step 3b"
     below). simulate_curve_paths() draws paths of the fitted model, and
     calibrate_sofr_and_note_options() fits it together with the
     SOFR options.

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
    x is a 1-D numpy array. Used by calibrate_sofr_model_nelder_mead() as
    an alternative to calibrate_sofr_model()'s grid search -- see that
    function's docstring for the trade-offs between the two.

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
# Step 2: two-factor Monte Carlo simulation, and SOFR futures options
# ---------------------------------------------------------------------------

def _simulate_two_factor_paths(forward_rates, sigma1, sigma2, horizon_months,
                                n_paths, seed, theta_bar,
                                a=SHORT_RATE_REVERSION_SPEED,
                                b=MEAN_LEVEL_REVERSION_SPEED):
    """
    Simulate n_paths Monte Carlo paths of the two factors, month by month
    from the model's own starting state (r0 = the curve's first forward
    rate, theta0 = theta_bar):
        r      -- the short-rate factor
        theta  -- the (stochastic) long-term mean-reversion level

    dr     = a * (theta - r)      * dt + sigma1 * sqrt(dt) * dW1
    dtheta = b * (theta_bar - theta) * dt + sigma2 * sqrt(dt) * dW2

    SIMPLIFICATION: the two random shocks dW1, dW2 are independent (no
    correlation parameter). Adding one would be a one-line change.

    theta_bar: the long-run level theta drifts toward (and starts at).
        price_sofr_future_option_mc() fits it to the real, non-extrapolated
        part of a SOFR curve (see _fit_sofr_theta_bar()): bootstrap_sofr_curve()
        extrapolates FLAT beyond its last real futures quarter, which would
        otherwise anchor theta at an arbitrary flat tail value that has
        nothing to do with a near-dated option's dynamics.

    These paths start from the model's own crude curve, which fits today's
    only roughly. For paths that start on the market's curve, use
    simulate_curve_paths().

    Returns:
        r_paths     -- array (n_paths, horizon_months + 1), the short-rate
                        factor at month 0, 1, ..., horizon_months
        theta_paths -- array (n_paths, horizon_months + 1), the
                        mean-reversion-level factor at those same months
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / MONTHS_PER_YEAR

    r0 = forward_rates[0]
    theta0 = theta_bar

    r = np.full(n_paths, r0)
    theta = np.full(n_paths, theta0)

    r_paths = np.zeros((n_paths, horizon_months + 1))
    theta_paths = np.zeros((n_paths, horizon_months + 1))
    r_paths[:, 0] = r0
    theta_paths[:, 0] = theta0

    for month in range(1, horizon_months + 1):
        z1 = rng.standard_normal(n_paths)
        z2 = rng.standard_normal(n_paths)
        dr = a * (theta - r) * dt + sigma1 * np.sqrt(dt) * z1
        dtheta = b * (theta_bar - theta) * dt + sigma2 * np.sqrt(dt) * z2
        r = r + dr
        theta = theta + dtheta
        r_paths[:, month] = r
        theta_paths[:, month] = theta

    return r_paths, theta_paths


def _discount_to_today(r_paths):
    """Product of monthly discount factors along each path, from month 0 to
    the last month in r_paths (used to discount an option payoff back to
    today). Each month is discounted at the short-rate factor prevailing
    at the START of that month."""
    monthly_factors = 1.0 / (1.0 + r_paths[:, :-1] / MONTHS_PER_YEAR)
    return np.prod(monthly_factors, axis=1)


# ---------------------------------------------------------------------------
# Step 2b: option pricing for a CME 3-Month SOFR future (SR3)
# ---------------------------------------------------------------------------

def _sofr_curve_fit_weight(n_months, a):
    """
    weight_m = the model's own coefficient on r0 (vs. theta_bar) when
    averaging the deterministic blend f(0, tau) = theta_bar +
    (r0 - theta_bar) * exp(-a*tau) -- see _sofr_futures_price_from_state()'s
    docstring for this same formula -- over the m-th month, for
    m = 1..n_months. Used by _fit_sofr_theta_bar() to fit theta_bar for a
    given a.
    """
    months = np.arange(1, n_months + 1)
    tau1 = (months - 1) / MONTHS_PER_YEAR
    tau2 = months / MONTHS_PER_YEAR
    return MONTHS_PER_YEAR * (np.exp(-a * tau1) - np.exp(-a * tau2))


def _fit_sofr_theta_bar(forward_rates, n_months, a=SHORT_RATE_REVERSION_SPEED):
    """
    Fit theta_bar (the long-run level _simulate_two_factor_paths()'s theta
    factor drifts toward) so the model's OWN deterministic curve shape --
    the same exponential blend f(0, tau) = theta_bar + (r0 - theta_bar) *
    exp(-a*tau) used everywhere else in this file -- best matches the
    first n_months of the supplied (bootstrapped) forward_rates, in a
    least-squares sense, for a FIXED a (calibrate_sofr_model() calls this
    at each candidate a it tries).

    WHY THIS MATTERS (found by checking real SR3 quotes): naively setting
    theta_bar to some flat average of the curve -- either the file's
    original "average of the last 2 years" (meaningless for a SOFR curve
    that bootstrap_sofr_curve() extrapolates FLAT beyond its last real
    futures quarter) or even "average of the real near-term months" --
    still leaves a multi-basis-point LEVEL bias in near-dated SOFR option
    prices, because the model only has two free parameters (r0, theta_bar)
    to shape an entire curve, and a flat average doesn't account for HOW
    those two parameters combine through the exponential blend at each
    tenor. This fit does: it directly minimizes the blend formula's error
    against the real curve, so short-dated options (most sensitive to
    curve shape) get the best possible baseline from a model this simple.

    Since the blend is LINEAR in theta_bar for a fixed r0 and a, this has
    a closed-form (weighted least-squares) solution -- no iterative
    optimizer needed, consistent with the rest of this file.

    n_months should cover the REAL (non-extrapolated) part of the curve --
    e.g. however many months bootstrap_sofr_curve()'s input futures
    actually covered -- fitting against the flat-extrapolated tail would
    just pull theta_bar toward that arbitrary flat value again.
    """
    r0 = forward_rates[0]
    weight = _sofr_curve_fit_weight(n_months, a)
    real_rate = np.asarray(forward_rates[:n_months], dtype=float)

    # model_avg_m = theta_bar*(1 - weight_m) + r0*weight_m; minimize
    # sum_m (model_avg_m - real_rate_m)^2 over theta_bar.
    numerator = np.sum((1 - weight) * (real_rate - r0 * weight))
    denominator = np.sum((1 - weight) ** 2)
    return float(numerator / denominator)


def _sofr_futures_price_from_state(r_T, theta_T, tau1, tau2,
                                    a=SHORT_RATE_REVERSION_SPEED):
    """
    Approximate the price of a CME 3-Month SOFR future at simulation date
    T, given that date's simulated state (r_T, theta_T), for the future
    whose reference (accrual) quarter is [T+tau1, T+tau2] (both offsets
    from T, in years).

    SIMPLIFICATIONS:
      - The real future settles to 100 minus the COMPOUNDED average daily
        SOFR over its reference quarter; this uses 100 minus the SIMPLE
        average of the model's own forward curve over the quarter instead
        (a negligible difference for a 3-month window at typical rate
        levels).
      - Takes the model's forward curve at T to be an "exponential blend"
        from r_T (near end) to theta_T (far end),
        f(T, T+tau) = theta_T + (r_T - theta_T) * exp(-a*tau),
        averaged analytically over tau in [tau1, tau2]:
            avg = theta_T + (r_T - theta_T) * (exp(-a*tau1) - exp(-a*tau2))
                                                / (a * (tau2 - tau1))
    r_T and theta_T can be scalars or numpy arrays (e.g. one value per
    Monte Carlo path).
    """
    avg_rate = theta_T + (r_T - theta_T) * (
        (np.exp(-a * tau1) - np.exp(-a * tau2)) / (a * (tau2 - tau1))
    )
    return 100.0 - avg_rate * 100.0


def price_sofr_future_option_mc(forward_rates, option, sigma1, sigma2,
                                 n_paths=2000, seed=42,
                                 a=SHORT_RATE_REVERSION_SPEED,
                                 theta_bar=None, theta_bar_months=24):
    """
    Monte Carlo price of one European option on a CME 3-Month SOFR (SR3)
    future.

    option: dict with keys
        'type'                 -- 'call' or 'put'
        'strike'                -- strike, in futures price points
                                    (e.g. 96.25, i.e. 100 - 3.75%)
        'expiry_months'         -- months from today until the OPTION's
                                    own expiry
        'quarter_start_months'  -- months from today until the underlying
                                    future's reference quarter BEGINS
        'quarter_end_months'    -- months from today until that quarter
                                    ENDS (the future's own settlement date)
        'market_price'          -- optional, only needed for calibration

    The option's payoff is based on the FUTURES PRICE AS OF THE OPTION'S
    OWN EXPIRY (a mark-to-market of the market's then-current expectation
    for the quarter's average SOFR), not on the quarter's eventually-
    realized average -- see _sofr_futures_price_from_state().

    a: the short-rate mean-reversion speed, used for BOTH the Monte Carlo
        dynamics (_simulate_two_factor_paths) and the deterministic
        curve-shape blend (_sofr_futures_price_from_state) this prices
        off of. Defaults to the module constant SHORT_RATE_REVERSION_SPEED,
        but calibrate_sofr_model() searches over it directly against real
        option prices, the same way it searches sigma1/sigma2, and
        supplies its fitted value instead.

    theta_bar / theta_bar_months: how to anchor the model's long-run
        mean-reversion level, instead of _simulate_two_factor_paths()'s
        own default (a flat average of the curve's LAST 2 years). That
        default would anchor theta at bootstrap_sofr_curve()'s arbitrary
        flat-extrapolated tail value, with no connection to real market
        data -- verified against real SR3 quotes to bias every near-dated
        option price by several basis points, in a way no amount of
        volatility calibration could fix (with sigma1=sigma2=0, i.e. NO
        randomness at all, it priced a 1-month call/put spread at ~0.10
        against a true parity-implied spread of ~0.03).

        If theta_bar is supplied directly, it's used as-is (the fast
        path: calibrate_sofr_model() refits it once per candidate a via
        _fit_sofr_theta_bar -- closed-form, so cheap -- and reuses that
        one fit across every sigma1/sigma2 combination tried at that a,
        since the fit doesn't depend on sigma1/sigma2 at all). Otherwise
        it's fit on this call via
        _fit_sofr_theta_bar(forward_rates, theta_bar_months, a=a) -- fine
        for a one-off call outside a calibration loop.

    SIMPLIFICATION: CME SOFR futures options are American-style; this
    model prices them as European (exercise only at expiry), ignoring
    early-exercise value -- which is under a third of a percent of a
    premium for options of these expiries (checked against a binomial tree
    on options on the 10-year note future).
    """
    if theta_bar is None:
        theta_bar = _fit_sofr_theta_bar(forward_rates, theta_bar_months, a=a)
    horizon = option['expiry_months']
    r_paths, theta_paths = _simulate_two_factor_paths(
        forward_rates, sigma1, sigma2, horizon, n_paths, seed,
        a=a, theta_bar=theta_bar)
    r_T = r_paths[:, -1]
    theta_T = theta_paths[:, -1]

    # Quarter bounds, expressed as offsets in years FROM the option's
    # expiry date T (rather than from today).
    tau1 = max(option['quarter_start_months'] - horizon, 0) / MONTHS_PER_YEAR
    tau2 = (option['quarter_end_months'] - horizon) / MONTHS_PER_YEAR
    if tau2 <= tau1:
        tau2 = tau1 + 1.0 / MONTHS_PER_YEAR

    futures_prices = _sofr_futures_price_from_state(r_T, theta_T, tau1, tau2, a=a)

    strike = option['strike']
    if option['type'] == 'call':
        payoffs = np.maximum(futures_prices - strike, 0.0)
    else:
        payoffs = np.maximum(strike - futures_prices, 0.0)

    discount = _discount_to_today(r_paths)
    return float(np.mean(payoffs * discount))


# ---------------------------------------------------------------------------
# Step 3: calibrate the model to SOFR futures options
# ---------------------------------------------------------------------------

def _filter_calibration_options(options, min_expiry_months):
    """
    Drop options with expiry_months <= min_expiry_months (default 0, i.e.
    no filtering). Shared by calibrate_sofr_model() and
    calibrate_sofr_model_nelder_mead() -- see calibrate_sofr_model()'s
    min_expiry_months docstring for why you might want this (e.g. to test
    whether the shortest-dated options are behaving anomalously).
    """
    if min_expiry_months <= 0:
        return options
    filtered = [o for o in options if o['expiry_months'] > min_expiry_months]
    if not filtered:
        raise ValueError(
            f"min_expiry_months={min_expiry_months} filtered out every option "
            f"(all {len(options)} had expiry_months <= {min_expiry_months}) -- "
            "nothing left to calibrate against.")
    return filtered


def calibrate_sofr_model(forward_rates, options, curve_real_months,
                          n_paths=2000, seed=42,
                          a_range=(0.05, 10.0),
                          sigma1_range=(0.0005, 0.03),
                          sigma2_range=(0.0005, 0.02),
                          n_grid=7, n_rounds=4,
                          min_expiry_months=0):
    """
    Calibrate the SOFR model's (a, sigma1, sigma2) directly against real
    SOFR futures option prices, by a "zooming grid search" (try a grid of
    (a, sigma1, sigma2), keep the best, shrink the grid around it, repeat).
    b (MEAN_LEVEL_REVERSION_SPEED) is left fixed: it only
    shows up in slow, multi-year dynamics, and real SOFR option liquidity
    (per sofr_market_data.py) is thin past roughly the first couple of
    years, so there usually isn't enough independent information in the
    available options to identify it reliably.

    At each candidate a, theta_bar is refit via _fit_sofr_theta_bar()
    (closed-form, so effectively free) before pricing that round's
    options at every (sigma1, sigma2) combination -- so every candidate a
    is compared using the theta_bar that best fits IT, not some
    a-independent guess.

    WHY GRID-SEARCH a AGAINST OPTION PRICES DIRECTLY, RATHER THAN FITTING
    IT TO TODAY'S CURVE SHAPE FIRST (cheaper -- no Monte Carlo needed,
    since it would just be a curve-fit): an earlier version of this
    function did exactly that. Tested against real SR3 quotes, it made
    things WORSE, not better -- on one real snapshot, the curve-shape fit
    (a~0.74, vs. the module default of 1.0) pushed the total squared
    OPTION pricing error from 0.052 up to 0.079, because a's effect on
    option prices runs through the Monte Carlo dynamics (how fast
    sigma1's shocks decay before an option's own expiry), which isn't the
    same sensitivity as how a shapes today's static curve. Grid-searching
    a directly against the option prices, on that same snapshot, found
    a~3.6 with error 0.027 -- about half of the 2-parameter (sigma1/sigma2
    only, a fixed at 1.0) baseline. It also turned out to be cheap enough
    to just do directly: each SOFR option's Monte Carlo horizon is only a
    handful of monthly steps (these are near-dated options), so a full
    7x7x7 grid over 4 rounds runs in on the order of ten to twenty
    seconds, not the many minutes a naive cost estimate would suggest.

    curve_real_months: how many months of forward_rates are the REAL
        (non-extrapolated) part of the curve -- e.g. the last SOFR
        future's end_months. Passed to _fit_sofr_theta_bar() at every
        candidate a.

    a_range: (lo, hi) bounds for the search. The lower bound is kept
        comfortably above 0 because a appears in a DENOMINATOR
        (a * (tau2 - tau1)) in _sofr_futures_price_from_state() -- a fit
        landing at exactly 0 would blow it up.

    min_expiry_months: drop calibration options with expiry_months <= this
        value before fitting (default 0 -- keep everything). Useful for
        checking whether the shortest-dated (e.g. 1-month) options are
        behaving anomalously relative to the rest of the curve -- run the
        calibration once with min_expiry_months=0 and once with
        min_expiry_months=1, and compare the fitted parameters and the
        remaining options' pricing errors between the two runs.

    Returns (a, theta_bar, sigma1, sigma2, error) -- theta_bar is
    _fit_sofr_theta_bar()'s fit at the winning a; error is the total
    squared pricing error at the winning (a, sigma1, sigma2) (summed over
    whatever options survived the min_expiry_months filter).
    """
    options = _filter_calibration_options(options, min_expiry_months)
    lo_a, hi_a = a_range
    lo1, hi1 = sigma1_range
    lo2, hi2 = sigma2_range
    best_a = best_theta_bar = best_sigma1 = best_sigma2 = best_error = None

    for _ in range(n_rounds):
        candidates_a = np.linspace(lo_a, hi_a, n_grid)
        candidates1 = np.linspace(lo1, hi1, n_grid)
        candidates2 = np.linspace(lo2, hi2, n_grid)
        best_error = None

        for a in candidates_a:
            theta_bar = _fit_sofr_theta_bar(forward_rates, curve_real_months, a=a)
            for s1 in candidates1:
                for s2 in candidates2:
                    total_error = 0.0
                    for option in options:
                        model_price = price_sofr_future_option_mc(
                            forward_rates, option, s1, s2, n_paths, seed,
                            a=a, theta_bar=theta_bar)
                        total_error += (model_price - option['market_price']) ** 2
                    if best_error is None or total_error < best_error:
                        best_error = total_error
                        best_a, best_theta_bar = a, theta_bar
                        best_sigma1, best_sigma2 = s1, s2

        # Zoom in: narrow the search window around the best point found.
        span_a = (hi_a - lo_a) / n_grid * 1.5
        span1 = (hi1 - lo1) / n_grid * 1.5
        span2 = (hi2 - lo2) / n_grid * 1.5
        lo_a, hi_a = max(1e-4, best_a - span_a), best_a + span_a
        lo1, hi1 = max(1e-6, best_sigma1 - span1), best_sigma1 + span1
        lo2, hi2 = max(1e-6, best_sigma2 - span2), best_sigma2 + span2

    return best_a, best_theta_bar, best_sigma1, best_sigma2, best_error


def calibrate_sofr_model_nelder_mead(forward_rates, options, curve_real_months,
                                      n_paths=2000, seed=42,
                                      initial_a=SHORT_RATE_REVERSION_SPEED,
                                      initial_sigma1=0.005, initial_sigma2=0.01,
                                      initial_step=0.5, max_iter=200,
                                      xtol=1e-6, ftol=1e-8,
                                      min_expiry_months=0):
    """
    Calibrate the SOFR model's (a, sigma1, sigma2) directly against real
    SOFR futures option prices -- the exact same objective
    calibrate_sofr_model() grid-searches -- but using Nelder-Mead simplex
    minimization (_nelder_mead()) instead. Kept ALONGSIDE
    calibrate_sofr_model(), not as a replacement, specifically so the two
    can be compared on the same options.

    WHY HAVE BOTH: a grid search can't get fooled into a bad local
    minimum -- it samples the whole box you give it, every round -- and
    is trivial to reason about, but it only ever visits grid points and
    its cost grows fast with resolution. Nelder-Mead can, in principle,
    home in on a better minimum between grid points and typically needs
    far fewer objective evaluations to converge. Its trade-off is the
    usual one for any local search: no guarantee of finding the GLOBAL
    minimum, and real sensitivity to the starting point
    (initial_a/initial_sigma1/initial_sigma2) and initial_step -- there's
    no "start from a wide net and zoom in" safety margin the way the grid
    search has. Run both and compare their (a, sigma1, sigma2, error)
    before trusting either one blindly; if they agree, that's good
    evidence the fit is real and not an artifact of one method.

    Internally parameterized as (log a, log sigma1, log sigma2) rather
    than the raw values, so the unconstrained simplex search can never
    wander into a <= 0 or a sigma <= 0 -- either nonsensical (negative
    vol) or, for a, a blow-up in _sofr_futures_price_from_state()'s
    1/a term. There's no equivalent of calibrate_sofr_model()'s
    a_range/sigma1_range/sigma2_range bounds here; initial_a/
    initial_sigma1/initial_sigma2 (and initial_step, which sets how far
    the starting simplex spreads out in log-space) are the closest
    equivalent -- they set where the search STARTS, not where it's
    confined to stay.

    curve_real_months / min_expiry_months: same meaning as in
    calibrate_sofr_model().

    Returns (a, theta_bar, sigma1, sigma2, error) -- same shape as
    calibrate_sofr_model(), so callers can compare the two directly.
    """
    options = _filter_calibration_options(options, min_expiry_months)

    def total_squared_error(a, sigma1, sigma2):
        theta_bar = _fit_sofr_theta_bar(forward_rates, curve_real_months, a=a)
        total = 0.0
        for option in options:
            model_price = price_sofr_future_option_mc(
                forward_rates, option, sigma1, sigma2, n_paths, seed, a=a, theta_bar=theta_bar)
            total += (model_price - option['market_price']) ** 2
        return total

    def objective(log_params):
        a, sigma1, sigma2 = np.exp(log_params)
        return total_squared_error(a, sigma1, sigma2)

    x0 = np.log([initial_a, initial_sigma1, initial_sigma2])
    best_log_params, best_error = _nelder_mead(
        objective, x0, step=initial_step, max_iter=max_iter, xtol=xtol, ftol=ftol)

    a, sigma1, sigma2 = np.exp(best_log_params)
    theta_bar = _fit_sofr_theta_bar(forward_rates, curve_real_months, a=a)
    return float(a), theta_bar, float(sigma1), float(sigma2), float(best_error)


# ---------------------------------------------------------------------------
# Step 3b: options on the 10-year note future (ZN), and calibrating to them
# ---------------------------------------------------------------------------
#
# WHY. SOFR futures options (step 2b) tell the model how much the SHORT rate
# moves. A mortgage depends on the LONG end, and a 10-year note option says
# how much that moves -- directly, instead of through the model's structure.
# In this model the 10-year yield is about 10% short-rate factor and 90%
# mean-reversion-level factor (at a = 1), so these options mostly pin down
# sigma2, the volatility of the level factor. They say little about sigma1,
# and nothing about b, since the options go out only a few months. So they
# are best fit TOGETHER with the SOFR options (calibrate_sofr_and_note_options).
#
# THE IDEA. Simulate the model's two factors forward by Monte Carlo, from
# them work out the price of a note at each option's expiry, and price the
# option as the average discounted payoff over the paths. Then vary the
# parameters until the model's prices are near the market's. Four things make
# that work for a note future, and are different from the SOFR options above:
#
#   1. TODAY'S CURVE IS THE CENTER. The model's own starting curve
#      (theta_bar and r0, blended exponentially) is too crude to match a
#      note: on one real day it priced the 6% 10-year note at 99.3, where
#      today's curve says 107.0 and the market's future said 105.6 -- a
#      six-point error, many times the premium of an at-the-money option
#      (about 0.9 points), which no volatility could fix. So the simulation
#      here keeps only the DEVIATIONS of the factors from their expected paths
#      (delta_r, delta_theta, which start at 0, and follow the same dynamics as
#      _simulate_two_factor_paths(): theta_bar drops out), and adds them to
#      the forward rates the market gives today:
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
#      the month's end. (The monthly steps of the rest of this file would put
#      a 36-day option's expiry at 30 days.) SIMPLIFICATION: like the other
#      pricers here, these prices are European (the real options are American).
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


def forward_par_yield(forward_rates, expiry_years, maturity_years):
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
    paths, a day at a time (Euler steps, as _simulate_two_factor_paths()
    takes its monthly steps):
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
        coupon = ctd_coupon if ctd_coupon is not None else forward_par_yield(
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


def _continued_flat(forward_rates, months):
    """The monthly forward rates as an array of at least `months` of them: a curve that is shorter continues at its last rate."""
    forward = np.asarray(forward_rates, dtype=float)
    if len(forward) >= months:
        return forward
    return np.concatenate([forward, np.full(months - len(forward), forward[-1])])


def simulate_factor_paths(sigma1, sigma2, horizon_years, n_paths, seed=None,
                          a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED):
    """
    The model's two random factors along Monte Carlo paths, month by month: the
    heart of the paths, and all there is to them besides the market's curve.
        delta_r      -- how far the short rate has strayed from where today's
                        curve has it: it pulls back toward delta_theta, at speed a
        delta_theta  -- how far the long-run level has strayed from today's
                        curve (it pulls back toward 0, slowly, at speed b)
    both start at 0, and are stepped by the day with random shocks of size sigma1
    and sigma2 (independent). simulate_curve_paths() adds them to the market's curve.

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


def forward_curve_on_date(forward_rates, months_ahead, delta_r, delta_theta,
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


def simulate_curve_paths(forward_rates, sigma1, sigma2, horizon_years, n_paths, seed=None,
                         a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED, tenor_years=10):
    """
    Monte Carlo paths of the model that the note-option calibration fits
    (see THE IDEA above), month by month: the market's forward curve, bent by
    the two random factors of simulate_factor_paths(). The paths start where the
    market is today: the first month's short rate is the curve's first forward
    rate, and the tenor_years par yield at the start is the curve's own. With
    sigma1 = sigma2 = 0 every path is the curve itself, read forward in time.
    Each month, on each path, the two factors bend the curve (see
    forward_curve_on_date()), and what is reported is read from that curve.

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
    years, delta_r_paths, delta_theta_paths = simulate_factor_paths(sigma1, sigma2, horizon_years, n_paths, seed, a=a, b=b)
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
    proxy for a 30-year mortgage) is that of simulate_curve_paths(), and
    mortgage_spread is a constant spread you supply (e.g. 0.015 for 150bp).
    The paths start on forward_rates, the market's curve, so a spread found as
    today's mortgage rate less forward_par_yield(forward_rates, 0.0, 10) puts the
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
    of simulate_curve_paths(), and underlying_paths + mortgage_spread.
    """
    years, short_rate_paths, underlying_paths = simulate_curve_paths(
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
        coupon = ctd_coupon if ctd_coupon is not None else forward_par_yield(
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


def calibrate_note_options(forward_rates, options, fit=('sigma2',),
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
    are starts. It is a Nelder-Mead search (_nelder_mead()) in the logarithms of
    the parameters, so none can go to 0 or below.

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
    for name in fit:
        if name not in ('a', 'b', 'sigma1', 'sigma2'):
            raise ValueError(f"fit is a list of 'a', 'b', 'sigma1', 'sigma2', not {name!r}")
    if not fit:
        raise ValueError("fit names no parameter to fit")
    usable, weights = _usable_note_options(forward_rates, options, min_expiry_years, moneyness_window)
    if not usable:
        raise ValueError("no option can be used to calibrate: each needs a market price above its intrinsic value, "
                         f"to be at least {min_expiry_years * DAYS_PER_YEAR:.0f} days from expiry and to be within "
                         f"{moneyness_window} standard deviations of the money")
    values = {'a': a, 'b': b, 'sigma1': sigma1, 'sigma2': sigma2}
    market = np.array([o['market_price'] for o in usable])
    evaluations = [0]

    def error_with(parameters):
        prices = price_note_future_options_mc(
            forward_rates, usable, parameters['sigma1'], parameters['sigma2'], a=parameters['a'], b=parameters['b'],
            n_paths=n_paths, seed=seed, ctd_maturity_years=ctd_maturity_years, ctd_coupon=ctd_coupon)
        evaluations[0] += 1
        return float(np.sqrt(np.mean(((prices - market) * weights) ** 2)))

    def objective(log_values):
        parameters = dict(values)
        parameters.update({name: float(np.exp(x)) for name, x in zip(fit, log_values)})
        return error_with(parameters)

    best_log_values, best_error = _nelder_mead(objective, np.log([values[name] for name in fit]),
                                                step=0.5, max_iter=max_iter, xtol=1e-4, ftol=1e-10)
    result = dict(values)
    result.update({name: float(np.exp(x)) for name, x in zip(fit, best_log_values)})
    result.update({'error': float(best_error), 'options_used': len(usable), 'evaluations': evaluations[0]})
    return result


def calibrate_sofr_and_note_options(sofr_forward_rates, note_forward_rates, sofr_options, note_options, curve_real_months,
                                     fit=('a', 'sigma1', 'sigma2'),
                                     a=SHORT_RATE_REVERSION_SPEED, sigma1=0.01, sigma2=0.01,
                                     sofr_paths=2000, note_paths=10000, seed=42,
                                     ctd_maturity_years=DEFAULT_CTD_MATURITY_YEARS, ctd_coupon=None,
                                     min_expiry_years=10.0 / DAYS_PER_YEAR, moneyness_window=2.0,
                                     sofr_min_expiry_months=3, max_iter=150):
    """
    Calibrate the model to SOFR futures options (as calibrate_sofr_model()
    does) AND to options on the 10-year note future (as
    calibrate_note_options()) together: the short-rate options pin down a and
    sigma1, the note options sigma2, and a and sigma1 together with sigma2
    decide how far apart the two sets of options' volatilities are.

    sofr_forward_rates: the SOFR curve, which the SOFR options' paths start
        from (as in calibrate_sofr_model()); note_forward_rates: the curve the
        note options' paths are centered on, the Treasury's (see THE IDEA above).
    sofr_options: as for calibrate_sofr_model(), each also with
        'underlying_price' (the SOFR future's price today), for weighing
        its error as a volatility error; note_options: as for
        calibrate_note_options(). The weights are those of CALIBRATING above, so
        the two kinds of option -- one in price points of 100 less the rate, the
        other of a note -- count alike. Each kind's error is the root mean
        square of its options' errors, and the error that is minimized is
        the square root of the two kinds' mean squares added, so that a
        kind with a poor fit pulls the parameters towards itself in
        proportion to how poor it is (the sum of the two root mean squares
        would be least at the best fit of the kind that is steeper, and
        ignore the other). curve_real_months is as for calibrate_sofr_model():
        theta_bar is refit for each a it tries, as that function does.
    sofr_min_expiry_months: the SOFR options with fewer months than this to
        expiry are left out (3). A model whose volatilities are the same at
        every date cannot match the very front of the market, where the Fed's
        next move is nearly known and the volatility is a fifth of that at
        a year out; such options would decide the fit by their large relative
        errors, and push sigma1 to 0.
    fit, a, sigma1, sigma2, ...: as for calibrate_note_options(), the
        search being in the logarithms of the parameters in fit. b is not a
        parameter here: the SOFR options' paths fix it at
        MEAN_LEVEL_REVERSION_SPEED, and so do the note options'.

    Returns a dict with 'a', 'sigma1', 'sigma2', 'theta_bar' (for the
    SOFR model's paths, as calibrate_sofr_model() gives it), 'sofr_error' and
    'note_error' (each family's root mean square relative volatility error,
    at the best fit), 'error' (the square root of the sum of their squares),
    'sofr_options_used',
    'note_options_used', and 'evaluations'.
    """
    for name in fit:
        if name not in ('a', 'sigma1', 'sigma2'):
            raise ValueError(f"fit is a list of 'a', 'sigma1', 'sigma2', not {name!r}")
    if not fit:
        raise ValueError("fit names no parameter to fit")
    sofr_usable, sofr_weights = [], []
    for option in sofr_options:
        if 'underlying_price' not in option:
            raise ValueError("each SOFR option needs 'underlying_price', the SOFR future's price today")
        years = option['expiry_months'] / MONTHS_PER_YEAR
        view = dict(option, expiry_years=years, futures_price=option['underlying_price'])
        _, _, weight, moneyness = _market_view(sofr_forward_rates, view)
        long_enough = years >= min_expiry_years and option['expiry_months'] >= sofr_min_expiry_months
        if long_enough and np.isfinite(weight) and moneyness <= moneyness_window:
            sofr_usable.append(option)
            sofr_weights.append(weight)
    sofr_weights = np.array(sofr_weights)
    note_usable, note_weights = _usable_note_options(note_forward_rates, note_options, min_expiry_years, moneyness_window)
    if not sofr_usable or not note_usable:
        raise ValueError(f"there are {len(sofr_usable)} SOFR options and {len(note_usable)} note options that can be "
                         "used to calibrate; each kind needs some (see calibrate_note_options() for what makes one usable)")
    values = {'a': a, 'sigma1': sigma1, 'sigma2': sigma2}
    sofr_market = np.array([o['market_price'] for o in sofr_usable])
    note_market = np.array([o['market_price'] for o in note_usable])
    evaluations = [0]

    def errors_with(parameters):
        theta_bar = _fit_sofr_theta_bar(sofr_forward_rates, curve_real_months, a=parameters['a'])
        sofr_prices = np.array([
            price_sofr_future_option_mc(sofr_forward_rates, option, parameters['sigma1'], parameters['sigma2'], sofr_paths, seed,
                                        a=parameters['a'], theta_bar=theta_bar)
            for option in sofr_usable])
        note_prices = price_note_future_options_mc(
            note_forward_rates, note_usable, parameters['sigma1'], parameters['sigma2'], a=parameters['a'],
            n_paths=note_paths, seed=seed, ctd_maturity_years=ctd_maturity_years, ctd_coupon=ctd_coupon)
        evaluations[0] += 1
        return (float(np.sqrt(np.mean(((sofr_prices - sofr_market) * sofr_weights) ** 2))),
                float(np.sqrt(np.mean(((note_prices - note_market) * note_weights) ** 2))), theta_bar)

    def objective(log_values):
        parameters = dict(values)
        parameters.update({name: float(np.exp(x)) for name, x in zip(fit, log_values)})
        sofr_error, note_error, _ = errors_with(parameters)
        return float(np.hypot(sofr_error, note_error))

    best_log_values, best_error = _nelder_mead(objective, np.log([values[name] for name in fit]),
                                                step=0.5, max_iter=max_iter, xtol=1e-4, ftol=1e-10)
    result = dict(values)
    result.update({name: float(np.exp(x)) for name, x in zip(fit, best_log_values)})
    sofr_error, note_error, theta_bar = errors_with(result)
    result.update({'theta_bar': theta_bar, 'sofr_error': sofr_error, 'note_error': note_error,
                   'error': float(np.hypot(sofr_error, note_error)), 'sofr_options_used': len(sofr_usable),
                   'note_options_used': len(note_usable), 'evaluations': evaluations[0]})
    return result


# ---------------------------------------------------------------------------
# Step 4: price a callable bond given an option-adjusted spread (OAS)
# ---------------------------------------------------------------------------

def price_callable_bond_mc(forward_rates, sigma1, sigma2, term_years,
                            coupon_rate, call_years, call_price, oas,
                            n_paths=2000, seed=123, face=100,
                            a=SHORT_RATE_REVERSION_SPEED, b=MEAN_LEVEL_REVERSION_SPEED):
    """
    Monte Carlo price of a callable bond, given an option-adjusted spread.
    The rates are the short-rate paths of simulate_curve_paths() (so, around
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
                    what oas_monte_carlo.lsp's oas-solve does.)

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

    _, r_paths, _ = simulate_curve_paths(forward_rates, sigma1, sigma2, term_years, n_paths, seed, a=a, b=b)
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
    fit = calibrate_note_options(forward_rates, example_options)
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
    years, short_rate_paths, ten_year_paths = simulate_curve_paths(
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
