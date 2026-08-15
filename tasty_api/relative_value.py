"""
relative_value.py
==================
Relative-value analysis of a CME futures curve: which contract months look
"rich" or "cheap", and what that implies about the market's priced-in
cost of carry.

This module only contains pure analysis functions (no networking). The
raw curve data (Delivery Month / Futures Symbol / Days to Delivery / Last
Price) is fetched by `tastytrade_source.TastytradeFuturesCurveWorker` for
whichever product is selected in the app.

Methodology (deliberately simple, and stated plainly so results aren't
mistaken for more than they are):

1.  PER-CONTRACT RICH/CHEAP (curve-fit residuals)
    Fit a smooth curve to ln(price) vs. time-to-delivery across ALL
    listed months (a low-order polynomial). Contracts trading above the
    fitted curve are flagged "Rich" (priced high relative to their
    neighbors' curve shape); contracts trading below are flagged
    "Cheap". This is a standard "rich/cheap-to-curve" technique (the
    futures-curve analogue of bond rich/cheap-to-curve analysis) and
    doesn't require any external rate assumptions. It's generic — it
    applies equally well to a commodity, equity-index, or rates curve.

2.  CALENDAR-SPREAD DECOMPOSITION (implied storage / funding cost)
    For each pair of adjacent contract months, the no-arbitrage
    cost-of-carry relationship for a storable physical commodity is:

        F2 = F1 * exp[(r + u - y) * (T2 - T1)]

    where r = funding (risk-free) rate, u = storage cost, y =
    convenience yield, all annualized. Rearranged:

        implied total carry rate   c = ln(F2/F1) / (T2-T1)   [OBSERVED]
        implied net storage cost   (u - y) = c - r            [given your r assumption]
        implied convenience yield   y = r + u - c              [given your r AND u assumptions]

    You supply r (funding rate) and u (storage cost) as editable
    assumptions in the app; the model backs out what's implied by the
    actual curve. This can't fully separate storage cost from
    convenience yield from price data alone (that needs your storage
    cost assumption too) — that limitation is inherent to the model,
    not a bug.

    IMPORTANT for non-commodity products: "storage cost" and
    "convenience yield" are physical-commodity concepts. For CL/MCL they
    have a real economic interpretation. For financial futures (ES, NQ,
    ZN, SR3, ZQ) there's no physical storage — the *math* (implied carry
    rate `c`) is still valid and meaningful, but the storage/convenience
    yield decomposition doesn't map to anything real. Read those two
    columns as "what a storage-cost story would require to be true, if
    you insisted on one" for non-commodity products, not as an actual
    estimate. The per-contract rich/cheap curve-fit (item 1 above) is
    the more broadly meaningful of the two views for those products.

CAVEATS: this is a simplified, single-factor model. Real curves have
seasonal effects (commodities), dividend/coupon effects (equities/rates),
and convenience yield / carry is not usually constant across maturities.
Treat "Rich"/"Cheap" flags as a starting point for further research, not
a trading signal on their own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CURVE_COLUMNS = [
    "Delivery Month", "Futures Symbol", "Days to Delivery", "Last Price",
    "Fitted Price", "Rich/Cheap %", "Signal",
]

LEG_COLUMNS = [
    "Near Month", "Far Month", "Near Price", "Far Price", "Days Between",
    "Implied Carry Rate %", "Implied Net Storage Cost %",
    "Implied Convenience Yield %", "Signal",
]


def compute_curve_fit(raw_df: pd.DataFrame, rich_cheap_threshold_pct: float = 0.75,
                       poly_degree: int | None = None) -> pd.DataFrame:
    """Fit ln(price) vs. days-to-delivery and flag each contract's
    deviation from that fitted curve as Rich / Cheap / Fair."""
    if raw_df is None or raw_df.empty or len(raw_df) < 3:
        return pd.DataFrame(columns=CURVE_COLUMNS)

    df = raw_df.sort_values("Days to Delivery").reset_index(drop=True)
    x = df["Days to Delivery"].to_numpy(dtype=float)
    y = np.log(df["Last Price"].to_numpy(dtype=float))

    n = len(df)
    degree = poly_degree if poly_degree is not None else min(3, max(1, n - 1))
    degree = max(1, min(degree, n - 1))

    coeffs = np.polyfit(x, y, degree)
    fitted_log = np.polyval(coeffs, x)
    fitted_price = np.exp(fitted_log)

    out = pd.DataFrame({
        "Delivery Month": df["Delivery Month"],
        "Futures Symbol": df["Futures Symbol"],
        "Days to Delivery": df["Days to Delivery"],
        "Last Price": df["Last Price"],
        "Fitted Price": fitted_price,
    })
    out["Rich/Cheap %"] = (out["Last Price"] - out["Fitted Price"]) / out["Fitted Price"] * 100

    def classify(pct):
        if pct > rich_cheap_threshold_pct:
            return "Rich"
        if pct < -rich_cheap_threshold_pct:
            return "Cheap"
        return "Fair"

    out["Signal"] = out["Rich/Cheap %"].apply(classify)
    return out[CURVE_COLUMNS]


def compute_leg_carry(raw_df: pd.DataFrame, funding_rate_pct: float,
                       storage_cost_pct: float,
                       leg_signal_threshold_pct: float = 1.0) -> pd.DataFrame:
    """Pairwise (adjacent-month) implied carry decomposition."""
    if raw_df is None or raw_df.empty or len(raw_df) < 2:
        return pd.DataFrame(columns=LEG_COLUMNS)

    df = raw_df.sort_values("Days to Delivery").reset_index(drop=True)
    r = funding_rate_pct / 100.0
    u = storage_cost_pct / 100.0

    rows = []
    carries = []
    for i in range(len(df) - 1):
        near, far = df.iloc[i], df.iloc[i + 1]
        days_between = far["Days to Delivery"] - near["Days to Delivery"]
        if days_between <= 0:
            continue
        dt_years = days_between / 365.0
        c = np.log(far["Last Price"] / near["Last Price"]) / dt_years  # implied carry rate
        net_storage = c - r          # = u - y, given funding rate assumption
        convenience_yield = r + u - c  # given both assumptions
        carries.append(c)
        rows.append({
            "Near Month": near["Delivery Month"],
            "Far Month": far["Delivery Month"],
            "Near Price": near["Last Price"],
            "Far Price": far["Last Price"],
            "Days Between": int(days_between),
            "Implied Carry Rate %": c * 100,
            "Implied Net Storage Cost %": net_storage * 100,
            "Implied Convenience Yield %": convenience_yield * 100,
        })

    if not rows:
        return pd.DataFrame(columns=LEG_COLUMNS)

    median_carry = float(np.median(carries))

    def classify(c):
        pct_diff = (c - median_carry) * 100
        if pct_diff > leg_signal_threshold_pct:
            return "Far month rich / near cheap"
        if pct_diff < -leg_signal_threshold_pct:
            return "Far month cheap / near rich"
        return "Fair"

    out = pd.DataFrame(rows)
    out["Signal"] = [classify(c) for c in carries]
    return out[LEG_COLUMNS]
