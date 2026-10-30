#!/usr/bin/env python3
"""
sofr_calibration_demo.py
==========================
End-to-end demo: fetch real, exchange-traded CME 3-Month SOFR (SR3)
futures and a few options on those futures via tastytrade, bootstrap a
SOFR forward curve, then calibrate the model -- (a, sigma1, sigma2), with
b left fixed; see term_structure_model.calibrate_to_sofr_options()'s docstring
for why -- so the calibration options price correctly under Monte Carlo.
Then uses the calibrated model to run a
small Monte Carlo mortgage-rate example: SOFR curve -> 10y par yield
+ a spread -> a proxy 30y mortgage rate, per Monte Carlo path. The
spread defaults to an EMPIRICAL one -- today's real 30-year mortgage rate
(FRED) minus the curve's current 10y par yield -- see mortgage_spread.py
for why this uses FRED rather than TBA MBS futures (tastytrade doesn't
offer any MBS/TBA product at all).

Run:
    python3 sofr_calibration_demo.py [path/to/credentials.json]
        [--min-expiry-months N]
        [--mortgage-spread-bp BP] [--mortgage-paths N] [--mortgage-years N]

If no credentials path is given, defaults to ~/credentials.json (see
sofr_market_data.py / ../tasty_api/README.md for the one-time tastytrade
OAuth setup; the same file's fred_api_key entry is used for the mortgage
spread lookup).
"""

import argparse

import numpy as np

import mortgage_spread as ms
import sofr_market_data as smd
import term_structure_model as tsm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("credentials_path", nargs="?", default=None)
    parser.add_argument("--min-expiry-months", type=int, default=3,
                         help="Leave out calibration options with fewer months than this to expiry "
                              "(3: the model's volatilities are the same at every date, and can't "
                              "match the front months, where the Fed's next move is nearly known).")
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

    print(f"\nCalibrating (a, sigma1, sigma2) to the options with at least {args.min_expiry_months} months "
          "to expiry, on the same paths simulate_rate_paths() draws (a Nelder-Mead search; some seconds)...")
    fit = tsm.calibrate_to_sofr_options(forward_rates, options, min_expiry_months=args.min_expiry_months)
    a, sigma1, sigma2 = fit['a'], fit['sigma1'], fit['sigma2']
    print(f"  a={a:.5f}  sigma1={sigma1:.5f}  sigma2={sigma2:.5f}  "
          f"({fit['options_used']} options; the model's volatilities are {fit['error']:.1%} from the market's)")

    used = [o for o in options if o['expiry_months'] >= args.min_expiry_months]
    print("\nModel price vs. market price after calibration:")
    for option, model_price in zip(used, tsm.price_sofr_future_options_mc(forward_rates, used, sigma1, sigma2, a=a)):
        print(f"  {option['type']:<4} strike {option['strike']:<9.4f} "
              f"expiry {option['expiry_months']}m -> "
              f"model {model_price:.4f}  market {option['market_price']:.4f}")

    print(
        "\nNote: some gap between the model's prices and the market's is "
        "expected even after calibration: the model's volatilities are the "
        "same at every date and every strike, and the market's are not (the "
        "front months move less, and options far from the money cost more). "
        "SOFR options say little about the long end (sigma2); for paths of "
        "long rates, fit to the 10-year note options too (calibrate_rate_model)."
    )

    if args.mortgage_spread_bp is not None:
        mortgage_spread = args.mortgage_spread_bp / 10000.0
        print(f"\nUsing the supplied flat mortgage spread: {args.mortgage_spread_bp:.0f}bp.")
    else:
        print("\nFetching today's 30-year mortgage rate from FRED "
              "(MORTGAGE30US) to compute the spread empirically...")
        mortgage_spread, mortgage_rate, model_rate, rate_date = ms.compute_sofr_mortgage_spread(
            forward_rates, credentials_path=credentials_path)
        print(f"  FRED 30y mortgage rate ({rate_date}): {mortgage_rate:.3%}")
        print(f"  The curve's current 10y par yield:     {model_rate:.3%}")
        print(f"  Implied spread:                        {mortgage_spread:.3%} "
              f"({mortgage_spread * 10000:.0f}bp)")

    print(f"\nRunning a Monte Carlo mortgage-rate example off the calibrated "
          f"SOFR model ({args.mortgage_paths} paths, {args.mortgage_years}y "
          f"horizon, +{mortgage_spread * 10000:.0f}bp spread over the "
          f"10-year par yield)...")
    years, short_rate_paths, ten_year_paths, mortgage_paths = tsm.simulate_mortgage_rate_paths(
        forward_rates, sigma1, sigma2,
        horizon_years=args.mortgage_years,
        n_paths=args.mortgage_paths,
        mortgage_spread=mortgage_spread,
        a=a)

    print("  Simulated 30y-mortgage-rate proxy, percentiles across paths:")
    for y in [yy for yy in (1, 2, 3, 5, 10) if yy <= args.mortgage_years]:
        idx = min(int(round(y * tsm.MONTHS_PER_YEAR)), mortgage_paths.shape[1] - 1)
        col = mortgage_paths[:, idx] * 100.0
        p10, p50, p90 = np.percentile(col, [10, 50, 90])
        print(f"    year {y:>2}: p10 {p10:.2f}%  median {p50:.2f}%  p90 {p90:.2f}%")


if __name__ == '__main__':
    main()
