"""SOFR interest-rate modeling for the Lisp interpreter: the sofr-*
builtins, which bridge to term_structure/term_structure_model.py (a pure
model -- no networking) and term_structure/sofr_market_data.py (which
fetches SOFR futures and options from tastytrade).

  sofr-forward-curve, sofr-bootstrap-curve    build a 360-month forward curve
  sofr-extend-curve-with-treasury             replace its flat long end with
                                              the Treasury curve's shape
  sofr-calibration-data                       fetch futures + options (network)
  sofr-calibrate-model                        fit the two-factor model to options
  sofr-simulate-rate-paths,                   Monte Carlo rate scenarios
  sofr-simulate-mortgage-rate-paths

If term_structure/ isn't next to this directory, or numpy is missing, the
builtins raise a clear error when called.
"""

import os
import sys

from lisp_core import LispError, LispString, LispVector, Pair, list_to_pairs, pairs_to_list
from lisp_tastytrade import tasty_row_field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "term_structure"))

try:
    from term_structure_model import bootstrap_sofr_curve as _bootstrap_sofr_curve
    from term_structure_model import extend_curve_long_end as _extend_curve_long_end
    from term_structure_model import simulate_rate_paths as _simulate_rate_paths
    from term_structure_model import simulate_mortgage_rate_paths as _simulate_mortgage_rate_paths
    from term_structure_model import calibrate_sofr_model as _calibrate_sofr_model
    _TERM_STRUCTURE_AVAILABLE = True
except ImportError:
    _TERM_STRUCTURE_AVAILABLE = False

# sofr_market_data fetches the SOFR futures curve AND a spread of SOFR
# futures options in one tastytrade session, shaped for
# calibrate_sofr_model(). Importing it doesn't require the tastytrade
# package itself (that's checked when it's called).
try:
    from sofr_market_data import fetch_sofr_calibration_data as _fetch_sofr_calibration_data
    _SOFR_MARKET_DATA_AVAILABLE = True
except ImportError:
    _SOFR_MARKET_DATA_AVAILABLE = False


# CME 3-Month SOFR (SR3) futures reference a 3-month accrual quarter that
# ENDS at the contract's delivery month -- see term_structure_model.
# bootstrap_sofr_curve()'s docstring for exactly what start_months/
# end_months mean and the simplifications baked into treating a whole
# quarter as one flat forward rate. Same day-count convention
# sofr_market_data.py uses, for consistency with the rest of that module.
_SOFR_DAYS_PER_MONTH = 30.436875


def sofr_forward_curve_fn(curve_rows):
    """(sofr-forward-curve curve-rows) -> (cons months-vector forward-rates-vector)
    curve-rows is the output of (tastytrade-futures-curve-rows creds "SR3"
    [n-months]) -- one row per listed CME 3-Month SOFR (SR3) futures
    contract: (delivery-month symbol days-to-delivery last-price).
    Bootstraps a 360-month (30-year) curve of 1-month forward rates
    implied by those futures prices, by reusing
    term_structure_model.bootstrap_sofr_curve() as-is (see
    term_structure/term_structure_model.py for the full methodology and
    its documented simplifications -- flat extrapolation beyond the last
    listed contract, no convexity adjustment, etc.) -- this function's
    only job is shaping tastytrade-futures-curve-rows's output into the
    {start_months, end_months, rate} dicts that function expects.

    months-vector is 1..360; forward-rates-vector[i] (0-indexed) is the
    annualized 1-month forward rate (decimal, e.g. 0.045) for month i+1
    -- (vector-ref forward-rates-vector (- month 1)). Feed straight into
    plot-xy, or read a period's rate by row index in a column's
    value_calculation for a floating-rate coupon or a mortgage
    prepayment model's rate-incentive calculation -- see
    sofr_floating_rate_example.lsp. Pure function -- no networking --
    so it's cheap to re-run against the same fetched curve-rows.
    Needs at least 1 row; raises LispError if curve-rows is empty, or if
    term_structure_model.py (and numpy) aren't importable."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-forward-curve: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if not rows:
        raise LispError("sofr-forward-curve: curve-rows is empty")

    sofr_futures = []
    for r in rows:
        days = float(tasty_row_field(r, 2))
        price = float(tasty_row_field(r, 3))
        end_months = round(days / _SOFR_DAYS_PER_MONTH)
        sofr_futures.append({
            "start_months": end_months - 3,
            "end_months": end_months,
            "rate": (100.0 - price) / 100.0,
        })

    result = _bootstrap_sofr_curve(sofr_futures)
    months = LispVector([int(m) for m in result["months"]])
    forward_rates = LispVector([float(fr) for fr in result["forward_rates"]])
    return Pair(months, forward_rates)


def sofr_calibration_data_fn(credentials_path, n_futures=40, n_underlyings=10, n_strikes=3):
    """(sofr-calibration-data credentials-path [n-futures n-underlyings
    n-strikes]) -> (cons curve-futures-rows options-rows) -- everything
    needed to bootstrap a SOFR curve AND calibrate the two-factor model
    against real SOFR futures option prices, fetched in ONE tastytrade
    session. Reuses sofr_market_data.fetch_sofr_calibration_data() as-is
    (see term_structure/sofr_market_data.py for the full selection
    methodology: options spread evenly across every curve quarter that
    has a listed chain, not just the nearest few, so sigma1 and sigma2 --
    see sofr-calibrate-model -- are separately identifiable). A SEPARATE
    fetch from tastytrade-futures-curve-rows -- this one also pulls
    option chains, not just futures prices.

    curve-futures-rows: one row per SR3 contract month used for the
    curve, each (symbol start-months end-months rate) -- feed to
    sofr-bootstrap-curve.
    options-rows: up to n-underlyings*n-strikes*2 near-the-money call/put
    pairs spread across n-underlyings different quarterly contracts, each
    (type strike expiry-months quarter-start-months quarter-end-months
    market-price) -- feed to sofr-calibrate-model.

    Needs the `tastytrade` package, a tastytrade account, and a
    credentials JSON file -- see tasty_api/README.md. Raises LispError if
    sofr_market_data.py isn't importable (the tastytrade package itself,
    and any fetch failure, raise their own errors from inside
    fetch_sofr_calibration_data)."""
    if not _SOFR_MARKET_DATA_AVAILABLE:
        raise LispError(
            "sofr-calibration-data: sofr_market_data.py isn't available -- "
            "see term_structure/ next to lisp_interp/")
    curve, options = _fetch_sofr_calibration_data(
        str(credentials_path), int(n_futures), int(n_underlyings), int(n_strikes))
    curve_rows = list_to_pairs([
        list_to_pairs([LispString(c["symbol"]), int(c["start_months"]),
                        int(c["end_months"]), float(c["rate"])])
        for c in curve
    ])
    options_rows = list_to_pairs([
        list_to_pairs([LispString(o["type"]), float(o["strike"]), int(o["expiry_months"]),
                        int(o["quarter_start_months"]), int(o["quarter_end_months"]),
                        float(o["market_price"])])
        for o in options
    ])
    return Pair(curve_rows, options_rows)


def sofr_bootstrap_curve_fn(curve_futures_rows):
    """(sofr-bootstrap-curve curve-futures-rows) -> (cons months-vector
    forward-rates-vector). curve-futures-rows is sofr-calibration-data's
    FIRST return value (or anything shaped the same way: a list of
    (symbol start-months end-months rate) rows) -- bootstraps the
    360-month forward curve directly from it via
    term_structure_model.bootstrap_sofr_curve(), the same underlying
    function sofr-forward-curve uses, just taking sofr-calibration-data's
    row shape instead of tastytrade-futures-curve-rows's (no day-count
    reshaping needed here -- these rows already carry start-months/
    end-months directly). Pure function -- no networking. Raises
    LispError if curve-futures-rows is empty, or term_structure_model.py
    isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-bootstrap-curve: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    rows = [pairs_to_list(r) for r in pairs_to_list(curve_futures_rows)]
    if not rows:
        raise LispError("sofr-bootstrap-curve: curve-futures-rows is empty")
    sofr_futures = [
        {"start_months": int(r[1]), "end_months": int(r[2]), "rate": float(r[3])}
        for r in rows
    ]
    result = _bootstrap_sofr_curve(sofr_futures)
    months = LispVector([int(m) for m in result["months"]])
    forward_rates = LispVector([float(fr) for fr in result["forward_rates"]])
    return Pair(months, forward_rates)


def sofr_extend_curve_with_treasury_fn(forward_rates, curve_real_months,
                                        yield_3m, yield_6m, yield_1y, yield_2y,
                                        yield_5y, yield_10y, yield_30y, blend_months=12):
    """(sofr-extend-curve-with-treasury forward-rates curve-real-months
    yield-3m yield-6m yield-1y yield-2y yield-5y yield-10y yield-30y
    [blend-months]) -> forward-rates-vector -- replaces the flat-
    extrapolated tail of a SOFR curve (from sofr-bootstrap-curve or
    sofr-forward-curve) past curve-real-months with a SEPARATE curve
    bootstrapped from Treasury par yields, linearly blended in over
    blend-months (default 12) so the splice doesn't visibly kink.

    forward-rates: the curve to extend, e.g. sofr-bootstrap-curve's or
        sofr-forward-curve's second return value.
    curve-real-months: how many months of forward-rates are backed by
        real market data (the same quantity sofr-calibrate-model's
        curve-real-months argument means) -- everything past this was
        flat-extrapolated and is a candidate for replacement.
    yield-3m/6m/1y/2y/5y/10y/30y: today's Treasury par yields, as
        DECIMALS (e.g. 0.045, not 4.5) -- e.g. FRED's DGS3MO/DGS6MO/
        DGS1/DGS2/DGS5/DGS10/DGS30, each divided by 100 (FRED reports
        those series in percent).
    blend-months: width of the linear transition zone, in months,
        starting at curve-real-months.

    WHY: bootstrap_sofr_curve()/sofr-forward-curve are honest that they
    have no market data beyond the last SOFR futures contract used (CME
    lists roughly a 5-year strip) -- past that they hold the curve flat.
    For anything priced off the far end of the curve (a 30-year MBS),
    the free, much longer-dated Treasury par curve on FRED is a better
    long-end shape than a flat line. This does NOT attempt a SOFR/
    Treasury basis adjustment -- it borrows the Treasury curve's SHAPE
    as-is past curve-real-months, which is a simplification worth being
    aware of.

    Pure function -- no networking. Reuses term_structure_model.
    extend_curve_long_end() and bootstrap_forward_curve() as-is. Raises
    LispError if term_structure_model.py isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-extend-curve-with-treasury: term_structure_model.py (and "
            "numpy) aren't available -- see term_structure/ next to lisp_interp/")
    forward_rates_list = [float(v) for v in forward_rates.items]
    treasury_yields = {
        "3m": float(yield_3m), "6m": float(yield_6m), "12m": float(yield_1y),
        "2y": float(yield_2y), "5y": float(yield_5y), "10y": float(yield_10y),
        "30y": float(yield_30y),
    }
    extended = _extend_curve_long_end(
        forward_rates_list, int(curve_real_months), treasury_yields,
        blend_months=int(blend_months))
    return LispVector([float(fr) for fr in extended])


def sofr_calibrate_model_fn(forward_rates, options_rows, curve_real_months,
                             n_paths=2000, seed=42, n_grid=7, n_rounds=4):
    """(sofr-calibrate-model forward-rates options-rows curve-real-months
    [n-paths seed n-grid n-rounds]) -> (list a theta-bar sigma1 sigma2
    error) -- fits the two-factor model's mean-reversion speed (a) and
    both volatilities (sigma1: the short-rate factor; sigma2: the
    slower-moving mean-reversion-LEVEL factor) directly against real SOFR
    futures option prices, by a "zooming grid search" (try a grid of
    (a, sigma1, sigma2) combinations, keep whichever prices the options
    closest, shrink the search window around it, repeat n-rounds times).
    Reuses term_structure_model.calibrate_sofr_model() as-is; see that
    function's docstring for the full methodology, including WHY it fits
    `a` against option prices directly rather than against today's curve
    shape (found, on real data, to noticeably improve the fit over a
    curve-shape-only fit) and theta-bar's role (refit in closed form, so
    cheap, at every candidate `a` tried).

    forward-rates: sofr-forward-curve's or sofr-bootstrap-curve's second
        return value.
    options-rows: sofr-calibration-data's second return value (or
        anything shaped the same way).
    curve-real-months: how many months of forward-rates are the REAL
        (non-extrapolated) part of the curve -- i.e. the largest
        end-months among the curve-futures-rows sofr-calibration-data
        (or sofr-bootstrap-curve) was given.
    n-paths: Monte Carlo paths used to price EACH option at EACH
        candidate (a, sigma1, sigma2) tried -- an accuracy/speed
        trade-off for the CALIBRATION itself, separate from how many
        SCENARIO paths sofr-simulate-rate-paths later generates.
    n-grid / n-rounds: grid resolution per round / how many times to zoom
        in -- cost is roughly O(n-grid^3 * n-rounds * n-paths * number of
        options), so raising these can get slow fast; the
        term_structure_model.py module docstring reports ten-to-twenty
        seconds for its own real-data test at these same defaults
        (n-paths 2000, n-grid 7, n-rounds 4) and a handful of options.

    Pure function -- no networking -- so it's cheap to re-run with
    different options-rows/settings once you've fetched once. Raises
    LispError if options-rows is empty, or term_structure_model.py isn't
    available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-calibrate-model: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    options = [pairs_to_list(r) for r in pairs_to_list(options_rows)]
    if not options:
        raise LispError("sofr-calibrate-model: options-rows is empty")
    option_dicts = [{
        "type": str(o[0]), "strike": float(o[1]), "expiry_months": int(o[2]),
        "quarter_start_months": int(o[3]), "quarter_end_months": int(o[4]),
        "market_price": float(o[5]),
    } for o in options]
    forward_rates_list = [float(v) for v in forward_rates.items]
    a, theta_bar, sigma1, sigma2, error = _calibrate_sofr_model(
        forward_rates_list, option_dicts, int(curve_real_months),
        n_paths=int(n_paths), seed=int(seed), n_grid=int(n_grid), n_rounds=int(n_rounds))
    return list_to_pairs([float(a), float(theta_bar), float(sigma1), float(sigma2), float(error)])


def sofr_simulate_rate_paths_fn(forward_rates, sigma1, sigma2, horizon_years, n_paths,
                                 seed=None, a=None, theta_bar=None):
    """(sofr-simulate-rate-paths forward-rates sigma1 sigma2 horizon-years
    n-paths [seed a theta-bar]) -> (list years-vector short-rate-paths
    ten-year-paths) -- simulates n-paths Monte Carlo scenarios of the
    two-factor model (a short-rate factor and a slower mean-reversion-
    level factor -- see term_structure/term_structure_model.py's module
    docstring) forward horizon-years, reusing
    term_structure_model.simulate_rate_paths() as-is.

    years: a vector of times in years -- 0, 1/12, 2/12, ... out to
        horizon-years.
    short-rate-paths / ten-year-paths: each a Lisp LIST of
        (horizon-years*12 + 1)-element vectors, one vector per path:
        short-rate-paths[i] is Monte Carlo path i's short-rate factor
        over time; ten-year-paths[i] is that SAME path's approximate
        ten-year rate (a closed-form function of the path's state, not a
        separately-simulated factor).

    a / theta-bar: pass sofr-calibrate-model's fitted `a`/theta-bar (its
        first two return values) when forward-rates came from
        sofr-bootstrap-curve/sofr-forward-curve, rather than leaving
        these '() (this function's own default: a fixed mean-reversion
        speed, and theta-bar as the average of forward-rates' last 2
        years) -- a SOFR curve is flat-extrapolated past its last real
        futures quarter, so that default would anchor theta-bar at an
        arbitrary value with no connection to real market data. See
        calibrate_sofr_model()'s docstring in term_structure_model.py.
    seed: '() (the default) for a fresh random seed each call; an
        integer for reproducible paths.

    Pure function -- no networking. Raises LispError if
    term_structure_model.py isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-simulate-rate-paths: term_structure_model.py (and numpy) "
            "aren't available -- see term_structure/ next to lisp_interp/")
    forward_rates_list = [float(v) for v in forward_rates.items]
    kwargs = {}
    if a is not None:
        kwargs["a"] = float(a)
    if theta_bar is not None:
        kwargs["theta_bar"] = float(theta_bar)
    years, r_paths, ten_year_paths = _simulate_rate_paths(
        forward_rates_list, float(sigma1), float(sigma2), float(horizon_years), int(n_paths),
        seed=(int(seed) if seed is not None else None), **kwargs)
    years_vec = LispVector([float(y) for y in years])
    r_paths_list = list_to_pairs([LispVector([float(x) for x in row]) for row in r_paths])
    ten_year_list = list_to_pairs([LispVector([float(x) for x in row]) for row in ten_year_paths])
    return list_to_pairs([years_vec, r_paths_list, ten_year_list])


def sofr_simulate_mortgage_rate_paths_fn(forward_rates, sigma1, sigma2, horizon_years, n_paths,
                                          mortgage_spread, seed=None, a=None, theta_bar=None,
                                          tenor_years=10):
    """(sofr-simulate-mortgage-rate-paths forward-rates sigma1 sigma2
    horizon-years n-paths mortgage-spread [seed a theta-bar tenor-years])
    -> (list years-vector short-rate-paths underlying-paths
    mortgage-paths) -- the same simulation as sofr-simulate-rate-paths,
    plus a simple proxy mortgage rate per path/month:
        mortgage_rate = tenor-years-rate + mortgage-spread
    (tenor-years-rate is the model's approximate tenor-years rate --
    defaults to 10, the usual rate-sensitivity proxy for a 30-year
    mortgage; underlying-paths in the return is that same quantity,
    before adding the spread). Reuses term_structure_model.
    simulate_mortgage_rate_paths() as-is -- see its docstring, and
    sofr-simulate-rate-paths's, for a/theta-bar/seed.

    SIMPLIFICATION (from the underlying model, not this bridge): a real
    mortgage rate tracks current-coupon MBS yields -- the whole curve,
    prepayment risk, origination costs -- not one flat spread over one
    tenor point; mortgage-spread is a deliberate simplification, named so
    it's obvious where to plug in something richer (see term_structure/
    mortgage_spread.py for one way to estimate it from real data --
    fetch_current_mortgage_rate() there pulls FRED's MORTGAGE30US).

    Pure function -- no networking. Raises LispError if
    term_structure_model.py isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-simulate-mortgage-rate-paths: term_structure_model.py (and "
            "numpy) aren't available -- see term_structure/ next to lisp_interp/")
    forward_rates_list = [float(v) for v in forward_rates.items]
    kwargs = {}
    if a is not None:
        kwargs["a"] = float(a)
    if theta_bar is not None:
        kwargs["theta_bar"] = float(theta_bar)
    years, r_paths, underlying_paths, mortgage_paths = _simulate_mortgage_rate_paths(
        forward_rates_list, float(sigma1), float(sigma2), float(horizon_years), int(n_paths),
        float(mortgage_spread), seed=(int(seed) if seed is not None else None),
        tenor_years=float(tenor_years), **kwargs)
    years_vec = LispVector([float(y) for y in years])
    r_paths_list = list_to_pairs([LispVector([float(x) for x in row]) for row in r_paths])
    underlying_list = list_to_pairs([LispVector([float(x) for x in row]) for row in underlying_paths])
    mortgage_list = list_to_pairs([LispVector([float(x) for x in row]) for row in mortgage_paths])
    return list_to_pairs([years_vec, r_paths_list, underlying_list, mortgage_list])


BUILTINS = {
    "sofr-forward-curve": sofr_forward_curve_fn,
    "sofr-calibration-data": sofr_calibration_data_fn,
    "sofr-bootstrap-curve": sofr_bootstrap_curve_fn,
    "sofr-extend-curve-with-treasury": sofr_extend_curve_with_treasury_fn,
    "sofr-calibrate-model": sofr_calibrate_model_fn,
    "sofr-simulate-rate-paths": sofr_simulate_rate_paths_fn,
    "sofr-simulate-mortgage-rate-paths": sofr_simulate_mortgage_rate_paths_fn,
}
