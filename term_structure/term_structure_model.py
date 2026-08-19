"""
term_structure_model.py

A simple two-factor term structure ("Hull-White style") model, built in
three steps:

  1. bootstrap_forward_curve(...) / bootstrap_sofr_curve(...)
     Turns a handful of market yields -- either T-bill rates + semiannual
     par bond yields, or a strip of exchange-traded 3-month SOFR futures
     -- into a full curve of 1-month forward rates, one for every month
     out to 30 years.

  2. price_cme_option_mc(...) / price_sofr_future_option_mc(...)
     Simulates that curve forward in time with two random ("stochastic")
     factors -- a short-rate factor and a slower-moving long-term
     mean-reversion level -- using Monte Carlo, and uses the simulated
     paths to price a CME-style option on either a 10-year note future or
     a 3-month SOFR future.

  3. calibrate_volatilities(...)
     Searches for the two volatility parameters (one per factor) that make
     the model's option prices match a set of real market option prices
     you supply (works with either option pricer above via `price_fn`).

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

import numpy as np

# ---------------------------------------------------------------------------
# Fixed model constants -- feel free to change these
# ---------------------------------------------------------------------------

# How fast the short-rate factor pulls back toward the mean-reversion level.
SHORT_RATE_REVERSION_SPEED = 1.0     # "a" -- bigger = snaps back faster

# How fast the mean-reversion level itself drifts back to its long-run average.
MEAN_LEVEL_REVERSION_SPEED = 0.15    # "b" -- much slower than the short rate

# CME 10-year note futures are based on a notional 6%-coupon, 10-year note.
NOTIONAL_COUPON_RATE = 0.06
NOTIONAL_MATURITY_YEARS = 10

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
# Step 2: two-factor Monte Carlo simulation + option pricing
# ---------------------------------------------------------------------------

def _simulate_two_factor_paths(forward_rates, sigma1, sigma2, horizon_months,
                                n_paths, seed,
                                a=SHORT_RATE_REVERSION_SPEED,
                                b=MEAN_LEVEL_REVERSION_SPEED,
                                theta_bar=None):
    """
    Simulate n_paths Monte Carlo paths of the two factors:
        r      -- the short-rate factor
        theta  -- the (stochastic) long-term mean-reversion level

    dr     = a * (theta - r)      * dt + sigma1 * sqrt(dt) * dW1
    dtheta = b * (theta_bar - theta) * dt + sigma2 * sqrt(dt) * dW2

    SIMPLIFICATION: the two random shocks dW1, dW2 are independent (no
    correlation parameter). Adding one would be a one-line change.

    theta_bar: optional override for the long-run level theta drifts
        toward. If not supplied (the default), it's computed as the
        average forward rate over the last 2 years of the supplied curve
        (the "long end") -- this is the ORIGINAL behavior, appropriate
        when forward_rates spans a genuine multi-decade curve (e.g. the
        Treasury-bootstrapped curve this model was first built for).

        Pass an explicit value when that default would anchor theta
        somewhere not economically meaningful for what's being priced --
        e.g. price_sofr_future_option_mc() passes the average over the
        curve's real (non-extrapolated) SOFR-futures-implied months
        instead, since bootstrap_sofr_curve() extrapolates FLAT beyond
        its last real futures quarter, which would otherwise anchor theta
        at an arbitrary flat tail value that has nothing to do with a
        near-dated option's dynamics and biases the whole path's drift.

    Returns:
        r_paths     -- array (n_paths, horizon_months + 1), the short-rate
                        factor at month 0, 1, ..., horizon_months
        theta_paths -- array (n_paths, horizon_months + 1), the
                        mean-reversion-level factor at those same months
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / MONTHS_PER_YEAR

    r0 = forward_rates[0]
    if theta_bar is None:
        # Long-run level that theta drifts toward: the average forward
        # rate over the last 2 years of today's curve (the "long end").
        theta_bar = float(np.mean(forward_rates[-24:]))
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


def _average_forward_rate_from_state(r, theta, tau1, tau2, a=SHORT_RATE_REVERSION_SPEED):
    """
    Closed-form average of the model's own forward-rate curve
    f(tau) = theta + (r - theta) * exp(-a * tau) (see _note_price_from_state)
    over the window tau in [tau1, tau2], where tau is years forward from
    the state date. Used both by ten_year_rate_from_state (tau1=0,
    tau2=10) and by price_sofr_future_option_mc (tau1/tau2 = a SOFR
    future's 3-month reference quarter).

    r and theta can be scalars or numpy arrays (e.g. a whole path/state
    vector); tau1 and tau2 are scalars.
    """
    tau2 = max(tau2, tau1 + 1e-6)  # guard against a zero-width window
    return theta + (r - theta) * (np.exp(-a * tau1) - np.exp(-a * tau2)) / (a * (tau2 - tau1))


def ten_year_rate_from_state(r, theta, a=SHORT_RATE_REVERSION_SPEED, tenor_years=10):
    """
    Approximate "the ten-year rate" implied by the model's state (r, theta)
    at some date, for charting purposes.

    SIMPLIFICATION: rather than building the full 10-year curve and solving
    for a par yield, this uses the closed-form average of the modeled
    forward curve over the next 10 years (see _average_forward_rate_from_state).
    This is close to, but not identical to, a true compounded 10-year zero
    or par yield -- good enough for a quick chart, not for precise pricing.
    r and theta can be scalars or numpy arrays (e.g. a whole path).
    """
    return _average_forward_rate_from_state(r, theta, 0.0, tenor_years, a)


def simulate_rate_paths(forward_rates, sigma1, sigma2, horizon_years, n_paths, seed=None,
                         a=SHORT_RATE_REVERSION_SPEED, theta_bar=None):
    """
    Public convenience wrapper (used by the GUI, or anyone who just wants
    to look at simulated rate paths without pricing an option or a bond).

    a / theta_bar: optional overrides -- see _simulate_two_factor_paths()'s
        docstring. Pass the (a, theta_bar) from calibrate_sofr_model()
        when forward_rates came from bootstrap_sofr_curve() rather than
        bootstrap_forward_curve(), for the same reason
        price_sofr_future_option_mc() does -- otherwise the paths use the
        module-default a and the "last 2 years" theta_bar, which for a
        SOFR curve is an arbitrary flat-extrapolated value.

    Returns:
        years            -- array of times in years, 0, 1/12, 2/12, ... out
                             to horizon_years
        short_rate_paths -- array (n_paths, len(years)), the short-rate
                             factor along each path
        ten_year_paths   -- array (n_paths, len(years)), the approximate
                             ten-year rate along each path (see
                             ten_year_rate_from_state)
    """
    horizon_months = int(round(horizon_years * MONTHS_PER_YEAR))
    r_paths, theta_paths = _simulate_two_factor_paths(
        forward_rates, sigma1, sigma2, horizon_months, n_paths, seed, a=a, theta_bar=theta_bar)
    years = np.arange(horizon_months + 1) / MONTHS_PER_YEAR
    ten_year_paths = ten_year_rate_from_state(r_paths, theta_paths, a=a)
    return years, r_paths, ten_year_paths


def simulate_mortgage_rate_paths(forward_rates, sigma1, sigma2, horizon_years, n_paths,
                                  mortgage_spread, seed=None,
                                  a=SHORT_RATE_REVERSION_SPEED, theta_bar=None, tenor_years=10):
    """
    Simulate a simple proxy mortgage rate alongside the model's own rate
    paths -- for Monte Carlo mortgage analysis (e.g. prepayment modeling)
    off a SOFR curve. For every simulated month on every path:

        mortgage_rate = tenor_years_rate + mortgage_spread

    where tenor_years_rate is the model's own approximate long-tenor rate
    (see ten_year_rate_from_state; tenor_years defaults to 10, the usual
    rate-sensitivity proxy for a 30-year mortgage) at that path/month, and
    mortgage_spread is a constant spread you supply (e.g. 0.015 for 150bp).

    a / theta_bar: pass the (a, theta_bar) from calibrate_sofr_model() when
        forward_rates came from bootstrap_sofr_curve() -- see that
        function's docstring (and
        price_sofr_future_option_mc()'s) for why the module defaults
        (a fixed at SHORT_RATE_REVERSION_SPEED, theta_bar as the average
        of the curve's last 2 years) are the wrong anchors for a SOFR
        curve that's flat-extrapolated past its last real futures quarter.

    SIMPLIFICATION: mortgage rates actually track something closer to
    current-coupon MBS yields (which move with the whole curve,
    prepayment risk, and origination costs -- not just one point on it),
    and the mortgage-to-underlying spread is NOT constant in reality; it
    widens and narrows with MBS supply, bank demand, and rate volatility.
    A single flat spread is a deliberate simplification -- named in the
    function's own parameter (mortgage_spread) so it's obvious where to
    plug in a richer assumption later.

    Returns:
        years            -- as in simulate_rate_paths
        short_rate_paths -- as in simulate_rate_paths
        underlying_paths -- the tenor_years rate along each path (what
                             simulate_rate_paths calls ten_year_paths)
        mortgage_paths   -- underlying_paths + mortgage_spread, same shape
    """
    horizon_months = int(round(horizon_years * MONTHS_PER_YEAR))
    r_paths, theta_paths = _simulate_two_factor_paths(
        forward_rates, sigma1, sigma2, horizon_months, n_paths, seed, a=a, theta_bar=theta_bar)
    years = np.arange(horizon_months + 1) / MONTHS_PER_YEAR
    underlying_paths = ten_year_rate_from_state(r_paths, theta_paths, a=a, tenor_years=tenor_years)
    mortgage_paths = underlying_paths + mortgage_spread
    return years, r_paths, underlying_paths, mortgage_paths


def _note_price_from_state(r_T, theta_T, a=SHORT_RATE_REVERSION_SPEED,
                            coupon_rate=NOTIONAL_COUPON_RATE,
                            maturity_years=NOTIONAL_MATURITY_YEARS):
    """
    Approximate the price of the CME notional 6%-coupon, 10-year note as of
    a future simulation date T, given that date's simulated short-rate
    factor (r_T) and mean-reversion level (theta_T). r_T and theta_T are
    numpy arrays, one value per Monte Carlo path.

    SIMPLIFICATION: forward rates beyond T are assumed to follow a simple
    exponential blend from r_T (near end) to theta_T (far end):

        f(T, T+tau) = theta_T + (r_T - theta_T) * exp(-a * tau)

    This gives each future date a smooth, two-parameter curve shape (right
    level, right slope) but does not try to reproduce fine detail (humps,
    etc.) in the future curve -- a deliberate trade-off for simplicity.
    """
    months_ahead = np.arange(1, maturity_years * MONTHS_PER_YEAR + 1)
    tau = months_ahead / MONTHS_PER_YEAR

    r_T = r_T.reshape(-1, 1)
    theta_T = theta_T.reshape(-1, 1)
    forwards = theta_T + (r_T - theta_T) * np.exp(-a * tau)   # (n_paths, 120)

    monthly_factors = 1.0 / (1.0 + forwards / MONTHS_PER_YEAR)
    discount_factors = np.cumprod(monthly_factors, axis=1)    # DF(T, T+m/12)

    coupon = 100 * coupon_rate / 2
    coupon_months = np.arange(6, maturity_years * MONTHS_PER_YEAR + 1, 6)
    coupon_idx = coupon_months - 1  # zero-based column index

    df_at_coupons = discount_factors[:, coupon_idx]
    price = np.sum(coupon * df_at_coupons, axis=1) + 100 * df_at_coupons[:, -1]
    return price  # (n_paths,)


def _discount_to_today(r_paths):
    """Product of monthly discount factors along each path, from month 0 to
    the last month in r_paths (used to discount an option payoff back to
    today). Each month is discounted at the short-rate factor prevailing
    at the START of that month."""
    monthly_factors = 1.0 / (1.0 + r_paths[:, :-1] / MONTHS_PER_YEAR)
    return np.prod(monthly_factors, axis=1)


def price_cme_option_mc(forward_rates, option, sigma1, sigma2,
                         n_paths=2000, seed=42):
    """
    Monte Carlo price of one CME-style option on the 10-year note future.

    option: dict with keys
        'type'              -- 'call' or 'put'
        'strike'            -- strike price (note/futures price terms, e.g. 108.5)
        'expiry_months'     -- months from today until option expiry
        'conversion_factor' -- optional, default 1.0. Converts the model's
                               notional note price into an approximate
                               futures price: futures_price = note_price /
                               conversion_factor. Supply the conversion
                               factor of the note you expect to be cheapest
                               to deliver for a closer approximation.
        'market_price'      -- optional, only needed for calibration

    SIMPLIFICATIONS:
      - CME options on note futures are American-style; this model prices
        them as European (exercise only at expiry). It ignores early-
        exercise value.
      - The futures price is approximated as the notional 6% bond's price
        divided by a single supplied conversion factor, rather than
        modeling the full deliverable basket / cheapest-to-deliver
        optimization (which needs a whole basket of real bonds as input).
    """
    horizon = option['expiry_months']
    r_paths, theta_paths = _simulate_two_factor_paths(
        forward_rates, sigma1, sigma2, horizon, n_paths, seed)
    r_T = r_paths[:, -1]
    theta_T = theta_paths[:, -1]

    note_prices = _note_price_from_state(r_T, theta_T)
    conversion_factor = option.get('conversion_factor', 1.0)
    futures_prices = note_prices / conversion_factor

    strike = option['strike']
    if option['type'] == 'call':
        payoffs = np.maximum(futures_prices - strike, 0.0)
    else:
        payoffs = np.maximum(strike - futures_prices, 0.0)

    discount = _discount_to_today(r_paths)
    return float(np.mean(payoffs * discount))


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
        levels) -- the same style of approximation ten_year_rate_from_state()
        and _note_price_from_state() already use elsewhere in this file.
      - Uses the same "exponential blend" forward-curve shape as those
        functions, f(T, T+tau) = theta_T + (r_T - theta_T) * exp(-a*tau),
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
    early-exercise value -- the same simplification price_cme_option_mc()
    makes for note-future options.
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
# Step 3: calibrate the two volatilities to market option prices
# ---------------------------------------------------------------------------

def calibrate_volatilities(forward_rates, options, n_paths=2000, seed=42,
                            sigma1_range=(0.0005, 0.03),
                            sigma2_range=(0.0005, 0.02),
                            n_grid=7, n_rounds=4,
                            price_fn=price_cme_option_mc):
    """
    Find (sigma1, sigma2) -- the volatility of the short-rate factor and of
    the mean-reversion-level factor -- that make price_fn match each
    option's 'market_price' as closely as possible.

    price_fn defaults to price_cme_option_mc (options on the CME 10-year
    note future); pass price_sofr_future_option_mc instead to calibrate to
    SOFR futures options. Both take the same (forward_rates, option,
    sigma1, sigma2, n_paths, seed) signature -- only the shape of the
    `option` dict and what it prices differ.

    METHOD (deliberately simple, no external optimizer library):
    a "zooming grid search". Try a grid of (sigma1, sigma2) combinations,
    keep whichever combination has the lowest total squared pricing error,
    then shrink the search window around that point and repeat. This is
    slower than a gradient-based optimizer but much easier to follow.

    The same random seed is reused for every combination tried, so the
    Monte Carlo noise is identical across comparisons -- only the change in
    (sigma1, sigma2) affects the price, which is what makes "keep the best
    combination" a meaningful thing to do.

    Returns (best_sigma1, best_sigma2, best_total_squared_error).
    """
    lo1, hi1 = sigma1_range
    lo2, hi2 = sigma2_range
    best_sigma1, best_sigma2, best_error = None, None, None

    for _ in range(n_rounds):
        candidates1 = np.linspace(lo1, hi1, n_grid)
        candidates2 = np.linspace(lo2, hi2, n_grid)
        best_error = None

        for s1 in candidates1:
            for s2 in candidates2:
                total_error = 0.0
                for option in options:
                    model_price = price_fn(
                        forward_rates, option, s1, s2, n_paths, seed)
                    total_error += (model_price - option['market_price']) ** 2
                if best_error is None or total_error < best_error:
                    best_error = total_error
                    best_sigma1, best_sigma2 = s1, s2

        # Zoom in: narrow the search window around the best point found.
        span1 = (hi1 - lo1) / n_grid * 1.5
        span2 = (hi2 - lo2) / n_grid * 1.5
        lo1, hi1 = max(1e-6, best_sigma1 - span1), best_sigma1 + span1
        lo2, hi2 = max(1e-6, best_sigma2 - span2), best_sigma2 + span2

    return best_sigma1, best_sigma2, best_error


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
    SOFR futures option prices -- the same "zooming grid search"
    calibrate_volatilities() uses for sigma1/sigma2 alone, extended to a
    third dimension. b (MEAN_LEVEL_REVERSION_SPEED) is left fixed: it only
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
        (a * (tau2 - tau1)) in _sofr_futures_price_from_state() /
        _average_forward_rate_from_state() -- a fit landing at exactly 0
        would blow those up.

    min_expiry_months: drop calibration options with expiry_months <= this
        value before fitting (default 0 -- keep everything). Useful for
        checking whether the shortest-dated (e.g. 1-month) options are
        behaving anomalously relative to the rest of the curve -- run the
        calibration once with min_expiry_months=0 and once with
        min_expiry_months=1, and compare the fitted parameters and the
        remaining options' pricing errors between the two runs.

    Returns (a, theta_bar, sigma1, sigma2, error) -- theta_bar is
    _fit_sofr_theta_bar()'s fit at the winning a; error is the total
    squared pricing error at the winning (a, sigma1, sigma2), same
    definition calibrate_volatilities() returns (summed over whatever
    options survived the min_expiry_months filter).
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
# Step 4: price a callable bond given an option-adjusted spread (OAS)
# ---------------------------------------------------------------------------

def price_callable_bond_mc(forward_rates, sigma1, sigma2, term_years,
                            coupon_rate, call_years, call_price, oas,
                            n_paths=2000, seed=123, face=100):
    """
    Monte Carlo price of a callable bond, given an option-adjusted spread.

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
                    solving for the OAS that reproduces a market price,
                    could be added the same way calibrate_volatilities()
                    searches for sigmas -- not included here.)

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

    r_paths, _ = _simulate_two_factor_paths(
        forward_rates, sigma1, sigma2, horizon_months, n_paths, seed)

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

    # A handful of illustrative CME 10-year note option quotes, with strikes
    # placed near the model's own at-the-money futures level (~114) so the
    # example is internally consistent. Replace with real market quotes.
    # strike/market_price are in futures price points (e.g. 114-16 = 114.5).
    example_options = [
        {'type': 'call', 'strike': 114.0, 'expiry_months': 2,
         'market_price': 0.75, 'conversion_factor': 0.93},
        {'type': 'call', 'strike': 115.0, 'expiry_months': 2,
         'market_price': 0.36, 'conversion_factor': 0.93},
        {'type': 'put', 'strike': 113.0, 'expiry_months': 2,
         'market_price': 0.37, 'conversion_factor': 0.93},
        {'type': 'put', 'strike': 112.0, 'expiry_months': 3,
         'market_price': 0.27, 'conversion_factor': 0.93},
    ]

    print("\nCalibrating sigma1 (short-rate vol) and sigma2 (mean-reversion "
          "level vol) to the example option prices...")
    sigma1, sigma2, error = calibrate_volatilities(forward_rates, example_options)
    print(f"  fitted sigma1 = {sigma1:.5f}")
    print(f"  fitted sigma2 = {sigma2:.5f}")
    print(f"  total squared pricing error = {error:.6f}")

    print("\nModel price vs. market price after calibration:")
    for option in example_options:
        model_price = price_cme_option_mc(forward_rates, option, sigma1, sigma2)
        print(f"  {option['type']:<4} strike {option['strike']:<7} "
              f"expiry {option['expiry_months']}m -> "
              f"model {model_price:.4f}  market {option['market_price']:.4f}")

    # A small example of the callable bond pricer, using the just-calibrated
    # sigmas: a 10-year, 5% coupon bond, callable at par starting in year 3,
    # priced at a 75bp OAS.
    bond_price = price_callable_bond_mc(
        forward_rates, sigma1, sigma2,
        term_years=10, coupon_rate=0.05,
        call_years=3, call_price=100.0, oas=0.0075)
    print(f"\nCallable bond example (10y, 5% coupon, callable at 100 "
          f"starting year 3, 75bp OAS): price = {bond_price:.3f}")
