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

# sofr_market_data fetches SOFR futures and options from tastytrade. It
# imports without the tastytrade package; that's checked when it's called.
try:
    from sofr_market_data import fetch_sofr_calibration_data as _fetch_sofr_calibration_data
    _SOFR_MARKET_DATA_AVAILABLE = True
except ImportError:
    _SOFR_MARKET_DATA_AVAILABLE = False


# An SR3 future covers the 3 months ending at its delivery month. Days per
# month, the same convention sofr_market_data.py uses.
_SOFR_DAYS_PER_MONTH = 30.436875


def sofr_forward_curve_fn(curve_rows):
    """(sofr-forward-curve curve-rows) -> (cons months-vector forward-rates-vector):
    a 360-month curve of 1-month forward rates bootstrapped from SOFR futures
    prices. curve-rows is the output of
    (tastytrade-futures-curve-rows creds "SR3").

    months-vector is 1..360; element i of forward-rates-vector is the
    annualized forward rate (a decimal, e.g. 0.045) for month i+1. Past the
    last listed contract the curve is flat -- see
    sofr-extend-curve-with-treasury. The method is
    term_structure_model.bootstrap_sofr_curve(); this only reshapes the rows.
    No network access."""
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
    """(sofr-calibration-data credentials-path [n-futures n-underlyings n-strikes])
    -> (cons curve-futures-rows options-rows): SOFR futures and a spread of
    SOFR futures options, fetched from tastytrade in one session.

      curve-futures-rows  (symbol start-months end-months rate), one per contract
                          -- for sofr-bootstrap-curve
      options-rows        (type strike expiry-months quarter-start-months
                          quarter-end-months market-price), near-the-money calls
                          and puts on n-underlyings contracts -- for
                          sofr-calibrate-model

    The options are spread across the whole curve, not just the nearest
    contracts, so the model's two volatilities can be told apart. See
    term_structure/sofr_market_data.py. Needs the tastytrade package and a
    credentials file (tasty_api/README.md)."""
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
    forward-rates-vector): the same curve as sofr-forward-curve, but from the
    rows sofr-calibration-data returns. No network access."""
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
      [blend-months]) -> forward-rates-vector

    A SOFR curve is flat past its last futures contract (about 5 years out).
    This replaces that flat part with the shape of the Treasury curve, built
    from today's par yields and blended in linearly over blend-months
    (default 12) so there's no kink. Useful for anything priced off the far
    end of the curve, such as a 30-year mortgage.

      forward-rates       from sofr-forward-curve or sofr-bootstrap-curve
      curve-real-months   how many months are backed by real futures prices
      yield-...           Treasury par yields as DECIMALS (0.045, not 4.5) --
                          e.g. FRED's DGS3MO ... DGS30 divided by 100

    It borrows the Treasury curve's shape as-is; there's no SOFR/Treasury
    basis adjustment. No network access."""
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
      [n-paths seed n-grid n-rounds]) -> (list a theta-bar sigma1 sigma2 error)

    Fits the two-factor model -- mean-reversion speed `a`, short-rate
    volatility sigma1, and the volatility sigma2 of the level the short
    rate reverts to -- to real SOFR futures option prices. It tries a grid
    of (a, sigma1, sigma2) values, keeps the one that prices the options
    best, narrows the grid around it, and repeats n-rounds times. theta-bar
    is refitted at each `a`. See term_structure_model.calibrate_sofr_model().

      forward-rates       from sofr-forward-curve or sofr-bootstrap-curve
      options-rows        from sofr-calibration-data
      curve-real-months   how many months of the curve come from real prices
      n-paths             Monte Carlo paths per option price (accuracy vs. speed)
      n-grid, n-rounds    grid size and number of rounds. Time grows roughly as
                          n-grid^3 * n-rounds * n-paths * options; the defaults
                          (2000, 7, 4) take ten to twenty seconds.

    No network access, so it's cheap to rerun with other settings."""
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
      n-paths [seed a theta-bar]) -> (list years short-rate-paths ten-year-paths)

    Simulates n-paths Monte Carlo scenarios of the two-factor model,
    horizon-years ahead, month by month.
      years            a vector of times: 0, 1/12, 2/12, ... horizon-years
      short-rate-paths a list of vectors, one per scenario: the short rate
      ten-year-paths   the same scenarios' approximate ten-year rate

    Pass the `a` and theta-bar from sofr-calibrate-model: the default
    theta-bar is the average of the curve's last 2 years, which for a SOFR
    curve is just the flat extrapolation. seed '() (the default) gives new
    random paths each time; an integer makes them reproducible. No network
    access."""
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
    -> (list years short-rate-paths underlying-paths mortgage-paths)

    The same simulation as sofr-simulate-rate-paths, plus a simple mortgage
    rate for each scenario and month: the model's tenor-years rate (default
    10) plus mortgage-spread. underlying-paths is that rate before adding
    the spread.

    A real mortgage rate depends on more than one spread over one rate
    (prepayment risk, the whole curve, costs); see
    term_structure/mortgage_spread.py for estimating the spread from FRED's
    MORTGAGE30US. No network access."""
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
