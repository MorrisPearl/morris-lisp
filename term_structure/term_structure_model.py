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
# Small numerical helper: bisection root-finder (replaces scipy.optimize)
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


def ten_year_rate_from_state(r, theta, a=SHORT_RATE_REVERSION_SPEED, tenor_years=10):
    """
    Approximate "the ten-year rate" implied by the model's state (r, theta)
    at some date, for charting purposes.

    SIMPLIFICATION: rather than building the full 10-year curve and solving
    for a par yield, this uses the average of the modeled forward curve
    over the next 10 years. Because that forward curve is the simple
    exponential blend theta + (r - theta) * exp(-a * tau) (see
    _note_price_from_state), its average over tau = 0..10 has a closed
    form, so no simulation loop is needed:

        avg = theta + (r - theta) * (1 - exp(-a * tenor_years)) / (a * tenor_years)

    This is close to, but not identical to, a true compounded 10-year zero
    or par yield -- good enough for a quick chart, not for precise pricing.
    r and theta can be scalars or numpy arrays (e.g. a whole path).
    """
    return theta + (r - theta) * (1.0 - np.exp(-a * tenor_years)) / (a * tenor_years)


def simulate_rate_paths(forward_rates, sigma1, sigma2, horizon_years, n_paths, seed=None):
    """
    Public convenience wrapper (used by the GUI, or anyone who just wants
    to look at simulated rate paths without pricing an option or a bond).

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
        forward_rates, sigma1, sigma2, horizon_months, n_paths, seed)
    years = np.arange(horizon_months + 1) / MONTHS_PER_YEAR
    ten_year_paths = ten_year_rate_from_state(r_paths, theta_paths)
    return years, r_paths, ten_year_paths


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

def _fit_sofr_theta_bar(forward_rates, n_months, a=SHORT_RATE_REVERSION_SPEED):
    """
    Fit theta_bar (the long-run level _simulate_two_factor_paths()'s theta
    factor drifts toward) so the model's OWN deterministic curve shape --
    the same exponential blend f(0, tau) = theta_bar + (r0 - theta_bar) *
    exp(-a*tau) used everywhere else in this file -- best matches the
    first n_months of the supplied (bootstrapped) forward_rates, in a
    least-squares sense.

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
    months = np.arange(1, n_months + 1)
    tau1 = (months - 1) / MONTHS_PER_YEAR
    tau2 = months / MONTHS_PER_YEAR
    # weight_m = the model's own coefficient on r0 (vs. theta_bar) when
    # averaging f(0, tau) over the m-th month -- see
    # _sofr_futures_price_from_state()'s docstring for this same formula.
    weight = MONTHS_PER_YEAR * (np.exp(-a * tau1) - np.exp(-a * tau2))
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
                                 n_paths=2000, seed=42, theta_bar_months=24):
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

    theta_bar_months: how many months of forward_rates are the REAL
        (non-extrapolated) part of the curve -- used to fit the model's
        long-run mean-reversion anchor via _fit_sofr_theta_bar() instead
        of _simulate_two_factor_paths()'s own default (a flat average of
        the curve's LAST 2 years). That default would anchor theta at
        bootstrap_sofr_curve()'s arbitrary flat-extrapolated tail value,
        with no connection to real market data -- verified against real
        SR3 quotes to bias every near-dated option price by several
        basis points, in a way no amount of volatility calibration could
        fix (with sigma1=sigma2=0, i.e. NO randomness at all, it priced a
        1-month call/put spread at ~0.10 against a true parity-implied
        spread of ~0.03). Fitting theta_bar to the real curve directly,
        via the same blend formula used for pricing, removes that bias
        at its source -- see _fit_sofr_theta_bar()'s docstring.

    SIMPLIFICATION: CME SOFR futures options are American-style; this
    model prices them as European (exercise only at expiry), ignoring
    early-exercise value -- the same simplification price_cme_option_mc()
    makes for note-future options.
    """
    theta_bar = _fit_sofr_theta_bar(forward_rates, theta_bar_months)
    horizon = option['expiry_months']
    r_paths, theta_paths = _simulate_two_factor_paths(
        forward_rates, sigma1, sigma2, horizon, n_paths, seed,
        theta_bar=theta_bar)
    r_T = r_paths[:, -1]
    theta_T = theta_paths[:, -1]

    # Quarter bounds, expressed as offsets in years FROM the option's
    # expiry date T (rather than from today).
    tau1 = max(option['quarter_start_months'] - horizon, 0) / MONTHS_PER_YEAR
    tau2 = (option['quarter_end_months'] - horizon) / MONTHS_PER_YEAR
    if tau2 <= tau1:
        tau2 = tau1 + 1.0 / MONTHS_PER_YEAR

    futures_prices = _sofr_futures_price_from_state(r_T, theta_T, tau1, tau2)

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
