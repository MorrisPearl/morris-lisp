#!/usr/bin/env python3
"""
sofr_calibration_demo.py
==========================
End-to-end demo: fetch real, exchange-traded CME 3-Month SOFR (SR3)
futures and a few options on those futures via tastytrade, bootstrap a
SOFR forward curve, then calibrate the model -- (a, sigma1, sigma2), with
b left fixed; see term_structure_model.calibrate_sofr_model()'s docstring
for why -- so the calibration options price correctly under Monte Carlo.
Then use the calibrated model to run a small Monte Carlo mortgage-rate
example (SOFR curve -> approximate 10y rate + a flat spread assumption ->
a proxy 30y mortgage rate, per Monte Carlo path).

Run:
    python3 sofr_calibration_demo.py [path/to/credentials.json]
        [--mortgage-spread-bp BP] [--mortgage-paths N] [--mortgage-years N]

If no credentials path is given, defaults to ~/credentials.json (see
sofr_market_data.py / ../tasty_api/README.md for the one-time tastytrade
OAuth setup).
"""

import argparse
import functools

import numpy as np

import sofr_market_data as smd
import term_structure_model as tsm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("credentials_path", nargs="?", default=None)
    parser.add_argument("--mortgage-spread-bp", type=float, default=175.0,
                         help="Flat spread (bp) added to the model's ~10y rate to proxy a 30y mortgage rate.")
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
    # docstring. It grid-searches (a, sigma1, sigma2) directly against the
    # option prices (refitting theta_bar in closed form at each candidate
    # a) -- b is left fixed. This takes ten to twenty seconds, not the
    # sub-second the plain sigma1/sigma2 calibration used to take, since
    # it's now a 3-D grid search instead of a 2-D one.
    curve_real_months = curve_futures[-1]['end_months']
    print("\nCalibrating the SOFR model: grid-searching (a, sigma1, sigma2) "
          "directly against the fetched option prices (b is left fixed -- "
          "see calibrate_sofr_model()'s docstring). This takes a bit "
          "longer than before (~10-20s) since it's now a 3-D search...")
    a, theta_bar, sigma1, sigma2, error = tsm.calibrate_sofr_model(
        forward_rates, options, curve_real_months)
    price_fn = functools.partial(tsm.price_sofr_future_option_mc, a=a, theta_bar=theta_bar)
    print(f"  fitted a         = {a:.5f}   (module default: {tsm.SHORT_RATE_REVERSION_SPEED})")
    print(f"  fitted theta_bar = {theta_bar:.4%}")
    print(f"  fitted sigma1    = {sigma1:.5f}")
    print(f"  fitted sigma2    = {sigma2:.5f}")
    print(f"  total squared pricing error = {error:.6f}")

    print("\nModel price vs. market price after calibration:")
    for option in options:
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

    print(f"\nRunning a Monte Carlo mortgage-rate example off the calibrated "
          f"SOFR model ({args.mortgage_paths} paths, {args.mortgage_years}y "
          f"horizon, +{args.mortgage_spread_bp:.0f}bp flat spread over the "
          f"model's ~10y rate)...")
    years, short_rate_paths, ten_year_paths, mortgage_paths = tsm.simulate_mortgage_rate_paths(
        forward_rates, sigma1, sigma2,
        horizon_years=args.mortgage_years,
        n_paths=args.mortgage_paths,
        mortgage_spread=args.mortgage_spread_bp / 10000.0,
        a=a, theta_bar=theta_bar)

    print("  Simulated 30y-mortgage-rate proxy, percentiles across paths:")
    for y in [yy for yy in (1, 2, 3, 5, 10) if yy <= args.mortgage_years]:
        idx = min(int(round(y * tsm.MONTHS_PER_YEAR)), mortgage_paths.shape[1] - 1)
        col = mortgage_paths[:, idx] * 100.0
        p10, p50, p90 = np.percentile(col, [10, 50, 90])
        print(f"    year {y:>2}: p10 {p10:.2f}%  median {p50:.2f}%  p90 {p90:.2f}%")


if __name__ == '__main__':
    main()
