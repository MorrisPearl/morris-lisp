#!/usr/bin/env python3
"""
sofr_calibration_demo.py
==========================
End-to-end demo: fetch real, exchange-traded CME 3-Month SOFR (SR3)
futures and a few options on those futures via tastytrade, bootstrap a
SOFR forward curve, then calibrate the two-factor model's volatility
parameters (sigma1, sigma2) so the calibration options price correctly
under Monte Carlo.

Run:
    python3 sofr_calibration_demo.py [path/to/credentials.json]

If no path is given, defaults to ~/credentials.json (see
sofr_market_data.py / ../tasty_api/README.md for the one-time tastytrade
OAuth setup).
"""

import functools
import sys

import sofr_market_data as smd
import term_structure_model as tsm


def main():
    credentials_path = sys.argv[1] if len(sys.argv) > 1 else None

    print("Fetching SR3 (3-Month SOFR) futures + options from tastytrade...")
    curve_futures, options = smd.fetch_sofr_calibration_data(credentials_path)

    print(f"\n{len(curve_futures)} SR3 futures contract months fetched:")
    for q in curve_futures:
        print(f"  {q['symbol']:<10} price {q['price']:>8.4f}  "
              f"rate {q['rate']:>7.4%}  "
              f"accrual quarter: month {q['start_months']:>3} -> {q['end_months']:>3} "
              f"(settles {q['expiration_date']})")

    print(f"\n{len(options)} calibration options fetched "
          f"(underlying {options[0]['underlying_symbol']}, "
          f"future price {options[0]['underlying_price']:.4f}):")
    for o in options:
        print(f"  {o['symbol']:<24} {o['type']:<4} strike {o['strike']:>8.4f}  "
              f"expiry {o['expiry_months']}m  market {o['market_price']:.4f}")

    print("\nBootstrapping SOFR forward curve...")
    curve = tsm.bootstrap_sofr_curve(curve_futures)
    forward_rates = curve['forward_rates']
    print(f"  1-month forward: {forward_rates[0]:.4%}   "
          f"1-year forward: {forward_rates[11]:.4%}   "
          f"2-year forward: {forward_rates[23]:.4%}")

    # Fit the model's long-run mean-reversion anchor (theta_bar) to the
    # REAL (non-extrapolated) part of the curve only -- see
    # term_structure_model._fit_sofr_theta_bar()'s docstring for why this
    # matters for near-dated SOFR options specifically. Bound here via
    # functools.partial since calibrate_volatilities() calls price_fn
    # with a fixed (forward_rates, option, sigma1, sigma2, n_paths, seed)
    # signature.
    theta_bar_months = curve_futures[-1]['end_months']
    price_fn = functools.partial(
        tsm.price_sofr_future_option_mc, theta_bar_months=theta_bar_months)

    print("\nCalibrating sigma1 (short-rate vol) and sigma2 (mean-reversion "
          "level vol) to the fetched SOFR futures option prices...")
    sigma1, sigma2, error = tsm.calibrate_volatilities(
        forward_rates, options, price_fn=price_fn)
    print(f"  fitted sigma1 = {sigma1:.5f}")
    print(f"  fitted sigma2 = {sigma2:.5f}")
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


if __name__ == '__main__':
    main()
