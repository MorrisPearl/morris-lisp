#!/usr/bin/env python3
"""
sofr_calibration_demo.py
==========================
End-to-end demo: fetch real, exchange-traded CME 3-Month SOFR (SR3)
futures and a few options on those futures via tastytrade, bootstrap a
SOFR forward curve, then calibrate the model -- (a, sigma1, sigma2), with
b left fixed; see term_structure_model.calibrate_sofr_model()'s docstring
for why -- so the calibration options price correctly under Monte Carlo.
Can run the grid-search calibrator, the Nelder-Mead one, or both side by
side for comparison (--method). Then uses the calibrated model to run a
small Monte Carlo mortgage-rate example: SOFR curve -> approximate 10y
rate + a spread -> a proxy 30y mortgage rate, per Monte Carlo path. The
spread defaults to an EMPIRICAL one -- today's real 30-year mortgage rate
(FRED) minus the model's own current ~10y rate -- see mortgage_spread.py
for why this uses FRED rather than TBA MBS futures (tastytrade doesn't
offer any MBS/TBA product at all).

Run:
    python3 sofr_calibration_demo.py [path/to/credentials.json]
        [--method {grid,nelder-mead,both}] [--min-expiry-months N]
        [--mortgage-spread-bp BP] [--mortgage-paths N] [--mortgage-years N]

If no credentials path is given, defaults to ~/credentials.json (see
sofr_market_data.py / ../tasty_api/README.md for the one-time tastytrade
OAuth setup; the same file's fred_api_key entry is used for the mortgage
spread lookup).
"""

import argparse
import functools

import numpy as np

import mortgage_spread as ms
import sofr_market_data as smd
import term_structure_model as tsm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("credentials_path", nargs="?", default=None)
    parser.add_argument("--method", choices=["grid", "nelder-mead", "both"], default="both",
                         help="Which calibration algorithm(s) to run. 'both' (the default) runs "
                              "both and prints them side by side; the grid-search result is used "
                              "for everything downstream (the model-vs-market table and the "
                              "mortgage Monte Carlo).")
    parser.add_argument("--min-expiry-months", type=int, default=0,
                         help="Exclude calibration options with expiry_months <= this value "
                              "(e.g. 1 to drop 1-month-or-shorter options -- useful for checking "
                              "whether they're behaving anomalously relative to the rest).")
    parser.add_argument("--mortgage-spread-bp", type=float, default=None,
                         help="Override: use this flat spread (bp) instead of computing it from "
                              "the current FRED 30-year mortgage rate.")
    parser.add_argument("--mortgage-paths", type=int, default=1000)
    parser.add_argument("--mortgage-years", type=int, default=10)
    args = parser.parse_args()
    credentials_path = args.credentials_path

    print("Fetching SR3 (3-Month SOFR) futures + options from tastytrade "
          "(as many contract months as are listed, options spread across "
          "the curve)...")
    curve_futures, options = smd.fetch_sofr_calibration_data(credentials_path)

    print(f"\n{len(curve_futures)} SR3 futures contract months fetched:")
    for q in curve_futures:
        print(f"  {q['symbol']:<10} price {q['price']:>8.4f}  "
              f"rate {q['rate']:>7.4%}  "
              f"accrual quarter: month {q['start_months']:>3} -> {q['end_months']:>3} "
              f"(settles {q['expiration_date']})")

    underlyings = sorted({(o['underlying_symbol'], o['underlying_price']) for o in options})
    print(f"\n{len(options)} calibration options fetched, spread across "
          f"{len(underlyings)} underlying contract month(s):")
    for sym, px in underlyings:
        print(f"  underlying {sym:<8} future price {px:.4f}")
    for o in options:
        print(f"  {o['symbol']:<24} {o['type']:<4} strike {o['strike']:>8.4f}  "
              f"expiry {o['expiry_months']:>3}m  market {o['market_price']:.4f}")

    print("\nBootstrapping SOFR forward curve...")
    curve = tsm.bootstrap_sofr_curve(curve_futures)
    forward_rates = curve['forward_rates']
    print(f"  1-month forward: {forward_rates[0]:.4%}   "
          f"1-year forward: {forward_rates[11]:.4%}   "
          f"2-year forward: {forward_rates[23]:.4%}")

    # curve_real_months: how many months of forward_rates are the REAL
    # (non-extrapolated) part of the curve -- see calibrate_sofr_model()'s
    # docstring. b is left fixed in both calibrators.
    curve_real_months = curve_futures[-1]['end_months']
    if args.min_expiry_months > 0:
        print(f"\nExcluding options with expiry_months <= {args.min_expiry_months} "
              f"from calibration...")

    results = {}
    if args.method in ("grid", "both"):
        print("\nCalibrating (grid search): grid-searching (a, sigma1, sigma2) "
              "directly against the fetched option prices. Takes roughly "
              "10-20 seconds (it's a 3-D search)...")
        results["grid search"] = tsm.calibrate_sofr_model(
            forward_rates, options, curve_real_months, min_expiry_months=args.min_expiry_months)
    if args.method in ("nelder-mead", "both"):
        print("\nCalibrating (Nelder-Mead): simplex search for (a, sigma1, sigma2) "
              "against the same option prices. Typically a few seconds...")
        results["Nelder-Mead"] = tsm.calibrate_sofr_model_nelder_mead(
            forward_rates, options, curve_real_months, min_expiry_months=args.min_expiry_months)

    print("\nCalibration results:")
    for label, (a, theta_bar, sigma1, sigma2, error) in results.items():
        print(f"  {label:<12}  a={a:.5f}  theta_bar={theta_bar:.4%}  "
              f"sigma1={sigma1:.5f}  sigma2={sigma2:.5f}  total_sq_error={error:.6f}")
    if len(results) > 1:
        print(f"  (module default a = {tsm.SHORT_RATE_REVERSION_SPEED} for reference)")

    # Use the grid-search result (if it ran) for everything downstream --
    # arbitrary but consistent choice between two methods that, per
    # calibrate_sofr_model_nelder_mead()'s docstring, should usually agree
    # closely; if they don't, that itself is worth a look.
    a, theta_bar, sigma1, sigma2, error = results.get("grid search") or results["Nelder-Mead"]

    calibration_options = tsm._filter_calibration_options(options, args.min_expiry_months)
    price_fn = functools.partial(tsm.price_sofr_future_option_mc, a=a, theta_bar=theta_bar)
    print(f"\nModel price vs. market price after calibration "
          f"({'grid search' if 'grid search' in results else 'Nelder-Mead'}):")
    for option in calibration_options:
        model_price = price_fn(forward_rates, option, sigma1, sigma2)
        print(f"  {option['type']:<4} strike {option['strike']:<9.4f} "
              f"expiry {option['expiry_months']}m -> "
              f"model {model_price:.4f}  market {option['market_price']:.4f}")

    print(
        "\nNote: some residual gap between model and market prices is "
        "expected here even after calibration. The model represents the "
        "whole future rate path with just two state variables (r, theta) "
        "gliding along a fixed exponential shape, while the real SR3 curve "
        "is a genuinely stepped/humped strip of quarterly rates -- a 1-2 "
        "month SOFR option is very sensitive to exactly that near-term "
        "shape, more so than the multi-year note-future options this model "
        "was originally built around (their price integrates coupons across "
        "a full 10-year curve, which smooths over the same shape mismatch). "
        "See _fit_sofr_theta_bar()'s docstring in term_structure_model.py "
        "for more."
    )

    if args.mortgage_spread_bp is not None:
        mortgage_spread = args.mortgage_spread_bp / 10000.0
        print(f"\nUsing the supplied flat mortgage spread: {args.mortgage_spread_bp:.0f}bp.")
    else:
        print("\nFetching today's 30-year mortgage rate from FRED "
              "(MORTGAGE30US) to compute the spread empirically...")
        mortgage_spread, mortgage_rate, model_rate, rate_date = ms.compute_sofr_mortgage_spread(
            forward_rates, a, theta_bar, credentials_path=credentials_path)
        print(f"  FRED 30y mortgage rate ({rate_date}): {mortgage_rate:.3%}")
        print(f"  Model's current ~10y rate:             {model_rate:.3%}")
        print(f"  Implied spread:                        {mortgage_spread:.3%} "
              f"({mortgage_spread * 10000:.0f}bp)")

    print(f"\nRunning a Monte Carlo mortgage-rate example off the calibrated "
          f"SOFR model ({args.mortgage_paths} paths, {args.mortgage_years}y "
          f"horizon, +{mortgage_spread * 10000:.0f}bp spread over the "
          f"model's ~10y rate)...")
    years, short_rate_paths, ten_year_paths, mortgage_paths = tsm.simulate_mortgage_rate_paths(
        forward_rates, sigma1, sigma2,
        horizon_years=args.mortgage_years,
        n_paths=args.mortgage_paths,
        mortgage_spread=mortgage_spread,
        a=a, theta_bar=theta_bar)

    print("  Simulated 30y-mortgage-rate proxy, percentiles across paths:")
    for y in [yy for yy in (1, 2, 3, 5, 10) if yy <= args.mortgage_years]:
        idx = min(int(round(y * tsm.MONTHS_PER_YEAR)), mortgage_paths.shape[1] - 1)
        col = mortgage_paths[:, idx] * 100.0
        p10, p50, p90 = np.percentile(col, [10, 50, 90])
        print(f"    year {y:>2}: p10 {p10:.2f}%  median {p50:.2f}%  p90 {p90:.2f}%")


if __name__ == '__main__':
    main()
