"""Interest-rate modeling for the Lisp interpreter: the builtins that bridge to
term_structure/term_structure_model.py (a pure model -- no networking) and
term_structure/sofr_market_data.py (which fetches SOFR futures and options from
tastytrade).

The curve and the data of SOFR futures (sofr-*):
  sofr-forward-curve, sofr-bootstrap-curve    build a 360-month forward curve
                                              from SOFR futures (flat past the
                                              last one: for the long end, use
                                              the Treasury's: yield_curves.lsp)
  sofr-calibration-data                       fetch futures + options (network)

Paths of rates from the two-factor model, which start on any curve (the
Treasury's is the one to use):
  simulate-rate-paths,                        Monte Carlo rate scenarios
  simulate-rate-factors,                      what they are made of: the model's
  rate-curve-on-date, curve-par-yield         two random factors, the curve they
                                              bend on a date, a curve's par yields

Fitting the model to option prices:
  calibrate-rate-model                        to SOFR and 10-year note options at once
  calibrate-to-sofr-options                   to options on SOFR futures
  calibrate-to-note-options                   to options on the 10-year note future (ZN)
  note-option-comparison                      the model's prices of ZN options
                                              next to the market's

If term_structure/ isn't next to this directory, or numpy is missing, the
builtins raise a clear error when called.
"""

import os
import sys

import numpy as np

from lisp_core import (
    NETWORK, LispError, LispString, LispVector, Pair, Symbol, keyword_options, lisp_error_of_kind, list_to_pairs, pairs_to_list,
)
from lisp_tastytrade import NETWORK_FAILURES
from lisp_tables import make_table_value
from lisp_futures import row_field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "term_structure"))

try:
    from term_structure_model import bootstrap_sofr_curve as _bootstrap_sofr_curve
    from term_structure_model import rate_curve_on_date as _rate_curve_on_date
    from term_structure_model import curve_par_yield as _curve_par_yield
    from term_structure_model import simulate_rate_factors as _simulate_rate_factors
    from term_structure_model import calibrate_to_sofr_options as _calibrate_to_sofr_options
    from term_structure_model import calibrate_to_note_options as _calibrate_to_note_options
    from term_structure_model import calibrate_rate_model as _calibrate_rate_model
    from term_structure_model import note_option_comparison as _note_option_comparison
    from term_structure_model import simulate_rate_paths as _simulate_rate_paths
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
    last listed contract the curve is flat; extend-forward-curve (yield_curves.lsp)
    carries it on with the Treasury's. The method is
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
        days = float(row_field(r, 2))
        price = float(row_field(r, 3))
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
                          quarter-end-months market-price underlying-price),
                          near-the-money calls and puts on n-underlyings
                          contracts -- for calibrate-to-sofr-options (which does not
                          use the last number) and calibrate-rate-model

    The options are spread across the whole curve, not just the nearest
    contracts, so the model's two volatilities can be told apart. See
    term_structure/sofr_market_data.py. Needs the tastytrade package and a
    credentials file (tasty_api/README.md)."""
    if not _SOFR_MARKET_DATA_AVAILABLE:
        raise LispError(
            "sofr-calibration-data: sofr_market_data.py isn't available -- "
            "see term_structure/ next to lisp_interp/")
    try:
        curve, options = _fetch_sofr_calibration_data(
            str(credentials_path), int(n_futures), int(n_underlyings), int(n_strikes))
    except NETWORK_FAILURES as e:
        raise lisp_error_of_kind("sofr-calibration-data: couldn't reach tastytrade: %s" % (e or type(e).__name__), NETWORK)
    curve_rows = list_to_pairs([
        list_to_pairs([LispString(c["symbol"]), int(c["start_months"]),
                        int(c["end_months"]), float(c["rate"])])
        for c in curve
    ])
    options_rows = list_to_pairs([
        list_to_pairs([LispString(o["type"]), float(o["strike"]), int(o["expiry_months"]),
                        int(o["quarter_start_months"]), int(o["quarter_end_months"]),
                        float(o["market_price"]), float(o["underlying_price"])])
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


def calibrate_to_sofr_options_fn(forward_rates, options_rows, curve_real_months,
                             n_paths=2000, seed=42, n_grid=7, n_rounds=4):
    """(calibrate-to-sofr-options forward-rates options-rows curve-real-months
      [n-paths seed n-grid n-rounds]) -> (list a theta-bar sigma1 sigma2 error)

    Fits the two-factor model -- mean-reversion speed `a`, short-rate
    volatility sigma1, and the volatility sigma2 of the level the short
    rate reverts to -- to real SOFR futures option prices. It tries a grid
    of (a, sigma1, sigma2) values, keeps the one that prices the options
    best, narrows the grid around it, and repeats n-rounds times. theta-bar
    is refitted at each `a`. See term_structure_model.calibrate_to_sofr_options().

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
            "calibrate-to-sofr-options: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    options = [pairs_to_list(r) for r in pairs_to_list(options_rows)]
    if not options:
        raise LispError("calibrate-to-sofr-options: options-rows is empty")
    option_dicts = [{
        "type": str(o[0]), "strike": float(o[1]), "expiry_months": int(o[2]),
        "quarter_start_months": int(o[3]), "quarter_end_months": int(o[4]),
        "market_price": float(o[5]),
    } for o in options]
    forward_rates_list = [float(v) for v in forward_rates.items]
    a, theta_bar, sigma1, sigma2, error = _calibrate_to_sofr_options(
        forward_rates_list, option_dicts, int(curve_real_months),
        n_paths=int(n_paths), seed=int(seed), n_grid=int(n_grid), n_rounds=int(n_rounds))
    return list_to_pairs([float(a), float(theta_bar), float(sigma1), float(sigma2), float(error)])


# ---------------------------------------------------------------------------
# Options on the 10-year note future (ZN)
# ---------------------------------------------------------------------------

_DAYS_PER_YEAR = 365.0      # the model counts the time to an option's expiry in calendar days / 365


def _check_term_structure(who):
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "%s: term_structure_model.py (and numpy) aren't available -- see term_structure/ next to lisp_interp/" % who)


def _forward_rates_list(forward_rates, who):
    if not isinstance(forward_rates, LispVector):
        raise LispError("%s: forward-rates must be a vector of monthly forward rates, such as (sofr-forward-curve ...) or "
                        "(table-column (curve-forward-rates zeros) \"forward\") gives" % who)
    return [float(v) for v in forward_rates.items]


def _note_option_dicts(rows, who):
    """The ZN options for the model: from rows (type strike days futures-price market-price), type being "call" or "put" in any case."""
    dicts = []
    for row in pairs_to_list(rows):
        row = pairs_to_list(row)
        if len(row) != 5:
            raise LispError("%s: each option row is (type strike days futures-price market-price), but one has %d items"
                            % (who, len(row)))
        option_type = str(row[0]).lower()
        if option_type not in ("call", "put"):
            raise LispError("%s: an option's type is \"call\" or \"put\", not %s" % (who, row[0]))
        dicts.append({"type": option_type, "strike": float(row[1]), "expiry_years": float(row[2]) / _DAYS_PER_YEAR,
                      "futures_price": float(row[3]), "market_price": float(row[4])})
    if not dicts:
        raise LispError("%s: there are no option rows" % who)
    return dicts


def _model_choices(options, who, allowed):
    """The :name value choices of a note-option builtin as the keyword arguments of the model's functions
    (:ctd-maturity is the note's remaining years, :ctd-coupon its coupon)."""
    chosen = keyword_options(options, allowed, who)
    names = {"a": "a", "b": "b", "sigma1": "sigma1", "sigma2": "sigma2", "seed": "seed",
             "n-paths": "n_paths", "note-paths": "note_paths", "sofr-paths": "sofr_paths",
             "ctd-maturity": "ctd_maturity_years", "ctd-coupon": "ctd_coupon",
             "moneyness-window": "moneyness_window", "sofr-min-months": "sofr_min_expiry_months"}
    whole_numbers = ("seed", "n-paths", "note-paths", "sofr-paths", "sofr-min-months")
    arguments = {names[key]: (int(value) if key in whole_numbers else float(value))
                 for key, value in chosen.items() if key in names}
    if "min-days" in chosen:
        arguments["min_expiry_years"] = float(chosen["min-days"]) / _DAYS_PER_YEAR
    if "fit" in chosen:
        arguments["fit"] = tuple(str(name) for name in pairs_to_list(chosen["fit"]))
    return arguments


def _alist(names_and_values):
    """An association list ((name . value) ...) keyed by symbols, so (cdr (assoc 'sigma2 result)) reads a value."""
    return list_to_pairs([Pair(Symbol(name), value) for name, value in names_and_values])


_NOTE_MODEL_OPTIONS = ["a", "b", "n-paths", "seed", "ctd-maturity", "ctd-coupon"]
_NOTE_FIT_OPTIONS = ["fit", "sigma1", "sigma2", "min-days", "moneyness-window"]


def note_option_comparison_fn(forward_rates, option_rows, sigma1, sigma2, *options):
    """(note-option-comparison forward-rates option-rows sigma1 sigma2
      [:a :b :n-paths :seed :ctd-maturity :ctd-coupon]) -> table

    The model's prices of options on the 10-year note future (ZN) next to the
    market's, one row per option. option-rows are lists
    (type strike days futures-price market-price): "call" or "put"; the
    strike and the future's price in the future's own points (105.5 is
    105 and 32/64); the calendar days until the option expires; the market's
    price of the option, in the same points. forward-rates is the curve the
    paths are centered on, a vector of monthly forward rates -- the Treasury's
    (curve-forward-rates) is the one to use.

    The table's columns: type, strike, days, futures-price, market-price,
    model-price; market-vol and model-vol (the normal volatility each price
    gives, in points a year); market-yield-vol and model-yield-vol (the same
    as a volatility of the yield of the note the future is taken to be, in
    basis points a year); duration (that note's); error (model-vol over
    market-vol, less 1).

      :a :b             the mean-reversion speeds (1.0 and 0.15 if not given)
      :n-paths          Monte Carlo paths (10000)
      :seed             the random numbers' seed (42)
      :ctd-maturity     years left of the note the future is taken to be, at the
                        option's expiry (6.75)
      :ctd-coupon       its coupon (by default the one that makes it sell at
                        par on the forward curve)

    See term_structure_model.price_note_future_options_mc(). No network
    access."""
    who = "note-option-comparison"
    _check_term_structure(who)
    choices = _model_choices(options, who, _NOTE_MODEL_OPTIONS)
    rows = _note_option_dicts(option_rows, who)
    compared = _note_option_comparison(_forward_rates_list(forward_rates, who), rows, float(sigma1), float(sigma2), **choices)
    columns = [("type", LispVector([LispString(r["type"]) for r in compared]))]
    for name, key in (("strike", "strike"), ("days", None), ("futures-price", "futures_price"),
                      ("market-price", "market_price"), ("model-price", "model_price"),
                      ("market-vol", "market_vol"), ("model-vol", "model_vol"),
                      ("market-yield-vol", "market_yield_vol"), ("model-yield-vol", "model_yield_vol"),
                      ("duration", "duration"), ("error", "error")):
        if key is None:
            columns.append((name, LispVector([round(r["expiry_years"] * _DAYS_PER_YEAR) for r in compared])))
        else:
            columns.append((name, LispVector([float(r[key]) for r in compared])))
    return make_table_value(columns)


def calibrate_to_note_options_fn(forward_rates, option_rows, *options):
    """(calibrate-to-note-options forward-rates option-rows
      [:fit :sigma1 :sigma2 :a :b :n-paths :seed :ctd-maturity :ctd-coupon
       :min-days :moneyness-window]) -> association list

    Fits the two-factor model to options on the 10-year note future (ZN):
    it finds the parameters for which the model's Monte Carlo prices are
    closest to the market's, the error being the root mean square of the
    options' relative volatility errors. forward-rates and option-rows, and
    :a :b :n-paths :seed :ctd-maturity :ctd-coupon, are as for
    note-option-comparison.

      :fit               the parameters to fit, a list of a, b, sigma1, sigma2
                         (by default (sigma2): the long end's volatility is what
                         these options show; the others keep their values)
      :sigma1 :sigma2    the values of those not fitted, and the starting
                         points of those that are (0.01 each)
      :min-days          leave out options with fewer days to expiry (10)
      :moneyness-window  leave out options whose strike is more than this many
                         standard deviations from the future's price (2)

    The result is ((a . 1.0) (b . 0.15) (sigma1 . 0.01) (sigma2 . 0.013)
    (error . 0.03) (options-used . 24) (evaluations . 36)); read a value with
    (cdr (assoc 'sigma2 result)). See
    term_structure_model.calibrate_to_note_options(). No network access."""
    who = "calibrate-to-note-options"
    _check_term_structure(who)
    choices = _model_choices(options, who, _NOTE_MODEL_OPTIONS + _NOTE_FIT_OPTIONS)
    rows = _note_option_dicts(option_rows, who)
    fit = _calibrate_to_note_options(_forward_rates_list(forward_rates, who), rows, **choices)
    return _alist([(name, fit[name]) for name in ("a", "b", "sigma1", "sigma2", "error")]
                  + [("options-used", fit["options_used"]), ("evaluations", fit["evaluations"])])


def calibrate_rate_model_fn(sofr_forward_rates, note_forward_rates, sofr_rows, note_rows, curve_real_months, *options):
    """(calibrate-rate-model sofr-forward-rates treasury-forward-rates
      sofr-option-rows note-option-rows curve-real-months [:fit :sigma1 :sigma2 :a :sofr-paths :note-paths :seed
      :ctd-maturity :ctd-coupon :min-days :moneyness-window :sofr-min-months]) -> association list

    Fits the two-factor model to SOFR futures options and to options on the
    10-year note future at once. The SOFR options show how much the short
    rate moves (a and sigma1), the note options how much the long end does
    (sigma2); fitting both fixes a and sigma1 against the SOFR options and
    sigma2 against the note options, and the model has to agree with both.

      sofr-forward-rates      the SOFR curve (sofr-forward-curve or
                              sofr-bootstrap-curve), which the SOFR options'
                              paths start from
      treasury-forward-rates  the Treasury's monthly forward curve
                              (curve-forward-rates), which the note options'
                              paths are centered on
      sofr-option-rows        from sofr-calibration-data (the 7-item rows)
      note-option-rows        as for note-option-comparison
      curve-real-months       as for calibrate-to-sofr-options

    The error is the root mean square relative volatility error of the SOFR
    options and that of the note options, put together as the square root of
    the sum of their squares (so neither kind is ignored). :fit is a list of a, sigma1,
    sigma2 (by default all three); :sofr-paths (2000) and :note-paths (10000)
    are the numbers of Monte Carlo paths. SOFR options with fewer than
    :sofr-min-months (3) months to expiry are left out: a model whose
    volatilities are the same at all dates cannot match the market's front
    months (the Fed's next move being nearly known), and their large relative
    errors would decide the fit. :min-days and :moneyness-window are as for
    calibrate-to-note-options.

    The result is ((a . 1.0) (sigma1 . 0.01) (sigma2 . 0.013) (theta-bar . 0.05)
    (sofr-error . 0.02) (note-error . 0.03) (error . 0.05) (sofr-options-used . 30)
    (note-options-used . 24) (evaluations . 100)). No network access."""
    who = "calibrate-rate-model"
    _check_term_structure(who)
    allowed = ["fit", "sigma1", "sigma2", "a", "sofr-paths", "note-paths", "seed", "ctd-maturity", "ctd-coupon",
               "min-days", "moneyness-window", "sofr-min-months"]
    choices = _model_choices(options, who, allowed)
    sofr_options = []
    for row in pairs_to_list(sofr_rows):
        row = pairs_to_list(row)
        if len(row) < 7:
            raise LispError("%s: each SOFR option row needs 7 items, ending with the future's price (as "
                            "sofr-calibration-data gives); one has %d" % (who, len(row)))
        sofr_options.append({
            "type": str(row[0]).lower(), "strike": float(row[1]), "expiry_months": int(row[2]),
            "quarter_start_months": int(row[3]), "quarter_end_months": int(row[4]),
            "market_price": float(row[5]), "underlying_price": float(row[6])})
    notes = _note_option_dicts(note_rows, who)
    fit = _calibrate_rate_model(
        _forward_rates_list(sofr_forward_rates, who), _forward_rates_list(note_forward_rates, who),
        sofr_options, notes, int(curve_real_months), **choices)
    return _alist([("a", fit["a"]), ("sigma1", fit["sigma1"]), ("sigma2", fit["sigma2"]), ("theta-bar", fit["theta_bar"]),
                   ("sofr-error", fit["sofr_error"]), ("note-error", fit["note_error"]), ("error", fit["error"]),
                   ("sofr-options-used", fit["sofr_options_used"]), ("note-options-used", fit["note_options_used"]),
                   ("evaluations", fit["evaluations"])])


def _path_keywords(options, who):
    """The :a :b :seed :tenor-years choices of the path builtins as keyword arguments of the model's functions."""
    chosen = keyword_options(options, ["a", "b", "seed", "tenor-years"], who)
    conversions = {"a": float, "b": float, "seed": int, "tenor_years": float}
    return {name.replace("-", "_"): conversions[name.replace("-", "_")](value) for name, value in chosen.items()}


def _lisp_paths(paths):
    """An array with a row for each path, as a Lisp list with a vector for each path."""
    return list_to_pairs([LispVector([float(x) for x in row]) for row in paths])


def simulate_rate_paths_fn(forward_rates, sigma1, sigma2, horizon_years, n_paths, *options):
    """(simulate-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths
      [:a :b :seed :tenor-years]) -> (list years short-rate-paths yield-paths)

    Simulates n-paths Monte Carlo scenarios of the model that
    calibrate-to-note-options and calibrate-rate-model fit, horizon-years
    ahead, month by month. The paths start where the market is: they are the
    market's forward curve plus the model's random factors, as the calibration
    prices options, so the first month's yield is today's.
      years            a vector of times: 0, 1/12, 2/12, ... horizon-years
      short-rate-paths a list of vectors, one per scenario: the short rate
      yield-paths      the same scenarios' par yield for a note of :tenor-years
                       (10 if not given), as the Treasury publishes it

    forward-rates is the Treasury's monthly forward curve (curve-forward-rates);
    where it is shorter than the horizon plus :tenor-years it continues at its
    last rate. sigma1 and sigma2 are the volatilities from the calibration, :a
    (1.0) and :b (0.15) its mean-reversion speeds. :seed (an integer) makes the
    paths the same each time; without it they are new. n-paths is made even (an odd
    number is rounded up). See term_structure_model.simulate_rate_paths().
    No network access."""
    who = "simulate-rate-paths"
    _check_term_structure(who)
    years, short_rate_paths, yield_paths = _simulate_rate_paths(
        _forward_rates_list(forward_rates, who), float(sigma1), float(sigma2), float(horizon_years), int(n_paths),
        **_path_keywords(options, who))
    return list_to_pairs([LispVector([float(y) for y in years]), _lisp_paths(short_rate_paths), _lisp_paths(yield_paths)])


def simulate_rate_factors_fn(sigma1, sigma2, horizon_years, n_paths, *options):
    """(simulate-rate-factors sigma1 sigma2 horizon-years n-paths [:a :b :seed])
    -> (list years delta-r-paths delta-theta-paths)

    The two random factors of the model, which are all there is to its paths
    besides the market's curve (simulate-rate-paths adds them to it).
      delta-r      how far the short rate has strayed from where today's curve has it
      delta-theta  how far the long-run level has strayed (the long end of the curve)
    Both start at 0. Each is a list of vectors, one per scenario, as rates (0.01 is
    one percent), month by month like the years vector. The short rate pulls back
    toward delta-theta at speed :a (1.0), and delta-theta toward 0, slowly, at speed
    :b (0.15); sigma1 and sigma2 are the sizes of their random shocks. :seed (an
    integer) makes the paths the same each time; n-paths is made even. See
    term_structure_model.simulate_rate_factors(). No network access."""
    who = "simulate-rate-factors"
    _check_term_structure(who)
    chosen = keyword_options(options, ["a", "b", "seed"], who)
    conversions = {"a": float, "b": float, "seed": int}
    years, delta_r_paths, delta_theta_paths = _simulate_rate_factors(
        float(sigma1), float(sigma2), float(horizon_years), int(n_paths), **{name: conversions[name](value) for name, value in chosen.items()})
    return list_to_pairs([LispVector([float(y) for y in years]), _lisp_paths(delta_r_paths), _lisp_paths(delta_theta_paths)])


def rate_curve_on_date_fn(forward_rates, months_ahead, delta_r, delta_theta, *options):
    """(rate-curve-on-date forward-rates months-ahead delta-r delta-theta [:a :months])
    -> table

    The model's forward curve on a date months-ahead from today, when its two
    factors have the values delta-r and delta-theta (a scenario's, at that date, from
    simulate-rate-factors): today's curve for the dates from then on, bent by
    them. The short end follows delta-r, the long end delta-theta, and the two meet
    at speed :a (1.0). With both 0 it is today's curve itself.

    The table has a row for each month, the columns
      months  1, 2, ...: the rate is for the month that starts months - 1 months after the date
      today   the market's forward rate for that month, annual, from forward-rates
      model   the model's, on the date: today plus the bend
    :months (by default, all the months forward-rates has after the date) is how many
    to give; a curve that is shorter continues at its last rate. The first model rate
    is the scenario's short rate that month, and the par yield of a note is worked
    out from the whole curve (simulate-rate-paths gives those). No network
    access."""
    who = "rate-curve-on-date"
    _check_term_structure(who)
    chosen = keyword_options(options, ["a", "months"], who)
    conversions = {"a": float, "months": int}
    months, today, on_date = _rate_curve_on_date(
        _forward_rates_list(forward_rates, who), int(months_ahead), float(delta_r), float(delta_theta),
        **{name: conversions[name](value) for name, value in chosen.items()})
    return make_table_value([("months", LispVector([int(m) for m in months])),
                             ("today", LispVector([float(x) for x in today])),
                             ("model", LispVector([float(x) for x in on_date]))])


def curve_par_yield_fn(forward_rates, tenor_years, *options):
    """(curve-par-yield forward-rates tenor-years [:start-months]) -> number

    The par yield a curve gives a note of tenor-years that starts :start-months
    (0, today) from now: the coupon, an annual rate paid every six months, that
    makes the note worth its face value. forward-rates is a curve of monthly
    forward rates (curve-forward-rates), long enough to reach start-months plus
    tenor-years. With :start-months 0 it is the yield the Treasury would publish if
    the curve were its own; later, what the curve implies for that yield then (the
    first value of a path with no volatility, in simulate-rate-paths, is this
    for each month). No network access."""
    who = "curve-par-yield"
    _check_term_structure(who)
    chosen = keyword_options(options, ["start-months"], who)
    start_months = float(chosen.get("start-months", 0))
    return float(_curve_par_yield(_forward_rates_list(forward_rates, who), start_months / 12.0, float(tenor_years)))


def path_present_values_fn(flows, rate_paths, oas, first_fraction=1.0):
    """(path-present-values flows rate-paths oas [first-fraction]) -> a vector with the value of the cash flows on each path

    flows is a list of vectors, one for each path (a cash flow for each month, from the first payment), or one vector, which every path has;
    rate-paths a list of vectors, one for each path, of the short rate (a decimal) at the start of each month, at least as long as the flows, as
    simulate-rate-paths gives them; oas a decimal added to every month's rate (0.005 is 50 basis points). A month's cash flow is discounted by what a
    dollar is worth for each month of the path up to it, 1 / (1 + (rate + oas) / 12) a month,
    for all the paths at once. The first payment is first-fraction of a month from the start (1 if it is left out): its month is
    discounted by that power of the month's factor. A path's value is its cash flows, discounted, added up. No network access."""
    who = "path-present-values"
    paths = [np.asarray(v.items, dtype=float) for v in pairs_to_list(rate_paths)]
    if not paths:
        raise LispError("%s: there are no rate paths" % who)
    if isinstance(flows, LispVector):
        flow_rows = [np.asarray(flows.items, dtype=float)] * len(paths)
    else:
        flow_rows = [np.asarray(v.items, dtype=float) for v in pairs_to_list(flows)]
    if len(flow_rows) != len(paths):
        raise LispError("%s: %d cash flows for %d rate paths: there is one for each path" % (who, len(flow_rows), len(paths)))
    months = len(flow_rows[0])
    if any(len(row) != months for row in flow_rows) or any(len(path) < months for path in paths):
        raise LispError("%s: each path needs a rate for each of the %d months of the cash flows" % (who, months))
    rates = np.vstack([path[:months] for path in paths])
    factors = 1.0 + (rates + float(oas)) / 12.0
    if (factors <= 0).any():
        raise LispError("%s: an oas of %s makes a month's discount factor not above 0" % (who, oas))
    log_discounts = -np.log(factors)
    log_discounts[:, 0] *= float(first_fraction)
    values = (np.vstack(flow_rows) * np.exp(np.cumsum(log_discounts, axis=1))).sum(axis=1)
    return LispVector([float(x) for x in values])


BUILTINS = {
    "path-present-values": path_present_values_fn,
    "sofr-forward-curve": sofr_forward_curve_fn,
    "sofr-calibration-data": sofr_calibration_data_fn,
    "sofr-bootstrap-curve": sofr_bootstrap_curve_fn,
    "calibrate-to-sofr-options": calibrate_to_sofr_options_fn,
    "calibrate-to-note-options": calibrate_to_note_options_fn,
    "calibrate-rate-model": calibrate_rate_model_fn,
    "note-option-comparison": note_option_comparison_fn,
    "simulate-rate-paths": simulate_rate_paths_fn,
    "simulate-rate-factors": simulate_rate_factors_fn,
    "rate-curve-on-date": rate_curve_on_date_fn,
    "curve-par-yield": curve_par_yield_fn,
}
