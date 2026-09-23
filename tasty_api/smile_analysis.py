"""
smile_analysis.py
===================
Relative-value analysis of a single stock's option chain: which
contracts look "rich" (priced expensive relative to the rest of the
chain) or "cheap" (priced inexpensive), using an implied-volatility
smile fit -- the options-market analogue of the futures term-structure
fit in relative_value.py.

Methodology (deliberately simple, stated plainly so results aren't
mistaken for more than they are):

1.  IV SMILE FIT (per expiration)
    Within each expiration, fit a smooth curve to implied volatility vs.
    log-moneyness x = ln(strike / underlying price). Calls and puts at
    the same expiration are fit together -- put-call parity says they
    should imply close to the same vol at a given strike, and pooling
    them doubles the points available to the fit. A low-order
    (quadratic, by default) polynomial is the standard, simplest way to
    capture smile curvature/skew.

    A contract trading at an implied vol ABOVE the fitted smile is
    flagged "Rich" (looks expensive relative to its neighbors at the
    same expiration); BELOW is "Cheap". This is the same "fit a smooth
    curve, flag the residual" idea as the futures curve-fit, just
    applied to the vol smile instead of the price curve, and it's what
    drives the Signal column -- IV residuals are comparable across
    strikes in a way raw price residuals are not (a deep ITM and a far
    OTM contract can differ in price by orders of magnitude for reasons
    that have nothing to do with mispricing).

    The fit is WEIGHTED by each contract's current-day Volume, on the
    assumption that the most actively-traded strikes are the ones the
    market has actually agreed on a price for, and are therefore the
    most trustworthy anchors for "where the smile should sit" -- a
    strike with heavy volume that still sits off the fitted curve is a
    much stronger signal than one with a single stale print. Untraded/
    zero-volume contracts get a small floor weight (so they don't cause
    a singular fit and are still scored against the resulting curve)
    but barely influence where that curve sits. If NO contract in an
    expiration traded today (e.g. testing outside market hours), every
    contract gets that same floor weight and the fit falls back to
    being effectively unweighted.

2.  FITTED PRICE (informational only)
    The fitted IV is re-priced through Black-Scholes (using your
    risk-free-rate/dividend-yield assumptions) to a theoretical "Fitted
    Price", so a vol mispricing can also be read in dollar terms
    alongside the vol-point residual. This does not drive the Rich/
    Cheap classification.

CAVEATS: single-name vol smiles are often genuinely skewed for real
reasons (equity skew: OTM puts priced above ATM is a standard risk
premium, not a mispricing). A quadratic fit captures the average shape
of THIS chain's OWN smile right now -- a strike sticking out from its
own chain's curve is what gets flagged, not a deviation from some
external "fair" smile. Wide bid/ask spreads, stale quotes, and low
volume/open interest can all produce an apparent-but-not-real flag --
check those columns before treating one as an opportunity. This is a
starting point for further research, not a trading signal by itself,
and nothing here is financial advice.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

_VOLUME_WEIGHT_FLOOR = 1.0  # keeps zero-volume contracts from causing a singular weighted fit

SMILE_COLUMNS = [
    "Symbol", "Type", "Strike", "Expiration Date", "Days to Expiration",
    "Underlying Price", "Log-Moneyness", "Bid", "Ask", "Mid", "Last Price",
    "Implied Volatility", "Fitted IV", "IV Residual (vol pts)",
    "Fitted Price", "Price vs Fitted %", "Delta", "Volume", "Open Interest",
    "Signal",
]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_price(is_call: bool, s: float, k: float, t_years: float,
                         vol: float, r: float, q: float = 0.0) -> float | None:
    """European Black-Scholes-Merton price with a continuous dividend
    yield q. Returns None for degenerate inputs (non-positive price,
    strike, time, or vol) rather than raising."""
    if s is None or k is None or t_years is None or vol is None:
        return None
    if s <= 0 or k <= 0 or t_years <= 0 or vol <= 0:
        return None
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(s / k) + (r - q + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc_r = math.exp(-r * t_years)
    disc_q = math.exp(-q * t_years)
    if is_call:
        return s * disc_q * _norm_cdf(d1) - k * disc_r * _norm_cdf(d2)
    return k * disc_r * _norm_cdf(-d2) - s * disc_q * _norm_cdf(-d1)


def compute_smile_fit(raw_df: pd.DataFrame, risk_free_rate_pct: float = 4.25,
                       dividend_yield_pct: float = 0.0,
                       iv_residual_threshold_vol_pts: float = 1.5,
                       poly_degree: int = 2) -> pd.DataFrame:
    """Fit implied vol vs. log-moneyness within each expiration and flag
    each contract's deviation from that fitted smile as Rich/Cheap/Fair.
    Contracts with no implied volatility (e.g. the Greeks stream timed
    out, or ran outside market hours and never got a snapshot) are kept
    with blank fit/signal fields rather than dropped."""
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(columns=SMILE_COLUMNS)

    r = risk_free_rate_pct / 100.0
    q = dividend_yield_pct / 100.0

    out_frames = []
    for _exp_date, group in raw_df.groupby("Expiration Date", sort=True):
        group = group.copy()
        has_price = group["Underlying Price"].notna() & group["Strike"].notna()
        group["Log-Moneyness"] = np.where(
            has_price,
            np.log(group["Strike"].astype(float) / group["Underlying Price"].astype(float)),
            np.nan,
        )

        fittable = group[group["Implied Volatility"].notna() & has_price]
        fitted_iv = pd.Series(np.nan, index=group.index)
        if len(fittable) >= 4:
            x = fittable["Log-Moneyness"].to_numpy(dtype=float)
            y = fittable["Implied Volatility"].to_numpy(dtype=float)
            # Volume-weighted: liquid (heavily-traded) strikes are treated as
            # the correctly-priced anchors, so they pull the fitted curve
            # toward themselves much more than a thinly-traded/untraded
            # strike. A small floor keeps zero-volume contracts from
            # producing a singular fit (or, if nothing traded today, from
            # skewing the fit at all -- they all get the same floor weight).
            volume = pd.to_numeric(fittable["Volume"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            weights = np.sqrt(volume + _VOLUME_WEIGHT_FLOOR)
            degree = max(1, min(poly_degree, len(fittable) - 2))
            coeffs = np.polyfit(x, y, degree, w=weights)
            all_x = group["Log-Moneyness"].to_numpy(dtype=float)
            fitted_iv = pd.Series(np.polyval(coeffs, all_x), index=group.index)
            fitted_iv[~has_price] = np.nan

        group["Fitted IV"] = fitted_iv
        group["IV Residual (vol pts)"] = (group["Implied Volatility"] - group["Fitted IV"]) * 100

        fitted_prices, price_pct = [], []
        for _, row in group.iterrows():
            fiv = row["Fitted IV"]
            dte = row["Days to Expiration"]
            t_years = dte / 365.0 if pd.notna(dte) else None
            if pd.isna(fiv) or not t_years or t_years <= 0:
                fitted_prices.append(np.nan)
                price_pct.append(np.nan)
                continue
            theo = black_scholes_price(
                row["Type"] == "Call", row["Underlying Price"], row["Strike"],
                t_years, float(fiv), r, q,
            )
            fitted_prices.append(theo if theo is not None else np.nan)
            ref_price = row["Mid"] if pd.notna(row.get("Mid")) else row.get("Last Price")
            if theo is not None and theo > 0 and pd.notna(ref_price):
                price_pct.append((ref_price - theo) / theo * 100)
            else:
                price_pct.append(np.nan)
        group["Fitted Price"] = fitted_prices
        group["Price vs Fitted %"] = price_pct

        def classify(resid):
            if pd.isna(resid):
                return "N/A"
            if resid > iv_residual_threshold_vol_pts:
                return "Rich"
            if resid < -iv_residual_threshold_vol_pts:
                return "Cheap"
            return "Fair"

        group["Signal"] = group["IV Residual (vol pts)"].apply(classify)
        out_frames.append(group)

    if not out_frames:
        return pd.DataFrame(columns=SMILE_COLUMNS)
    result = pd.concat(out_frames, ignore_index=True)
    return result[SMILE_COLUMNS]
