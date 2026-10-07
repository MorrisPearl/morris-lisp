"""Futures curves, for the Lisp interpreter: how each contract's price
compares with the curve, and the carry between neighboring months.

  (futures-curve-fit curve-rows [rich-cheap-threshold-pct poly-degree])
                     each contract against a smooth curve fitted to them all
  (futures-leg-carry curve-rows funding-rate-pct storage-cost-pct [leg-signal-threshold-pct])
                     the carry rate between each month and the next

Both work on a futures curve's rows, as tastytrade-futures-curve-rows makes
them: a list of rows (delivery-month futures-symbol days-to-delivery
last-price ...), and neither downloads anything, so a curve fetched once can
be analyzed many ways.
"""

import numpy as np

from lisp_core import LispDate, LispString, NIL, is_true, list_to_pairs, pairs_to_list


def row_field(row, index):
    """Field `index` of a curve row (a Python list, from pairs_to_list), with
    a date as a datetime.date."""
    val = row[index]
    return val.date if isinstance(val, LispDate) else val


def futures_curve_fit(curve_rows, rich_cheap_threshold_pct=0.75, poly_degree=None):
    """(futures-curve-fit curve-rows [rich-cheap-threshold-pct poly-degree])
    -> a list of rows (delivery-month futures-symbol days-to-delivery
    last-price fitted-price rich-cheap-pct signal).

    Fits a low-degree polynomial (degree min(3, n-1) unless poly-degree is
    given) to ln(price) against days to delivery, then compares each
    contract to the fitted curve: signal is "Rich" if it trades more than
    rich-cheap-threshold-pct above the fit, "Cheap" if that far below, else
    "Fair". No network access. Returns '() with fewer than 3 rows."""
    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if len(rows) < 3:
        return NIL

    rows = sorted(rows, key=lambda r: row_field(r, 2))
    x = np.array([float(row_field(r, 2)) for r in rows], dtype=float)
    y = np.log(np.array([float(row_field(r, 3)) for r in rows], dtype=float))

    n = len(rows)
    degree = int(poly_degree) if poly_degree is not None and is_true(poly_degree) else min(3, max(1, n - 1))
    degree = max(1, min(degree, n - 1))

    coeffs = np.polyfit(x, y, degree)
    fitted_price = np.exp(np.polyval(coeffs, x))
    threshold = float(rich_cheap_threshold_pct)

    out_rows = []
    for r, fitted in zip(rows, fitted_price):
        last_price = float(row_field(r, 3))
        pct = (last_price - fitted) / fitted * 100
        if pct > threshold:
            signal = "Rich"
        elif pct < -threshold:
            signal = "Cheap"
        else:
            signal = "Fair"
        out_rows.append(list_to_pairs([
            r[0], r[1], r[2], r[3],
            float(fitted), float(pct), LispString(signal),
        ]))
    return list_to_pairs(out_rows)


def futures_leg_carry(curve_rows, funding_rate_pct, storage_cost_pct,
                             leg_signal_threshold_pct=1.0):
    """(futures-leg-carry curve-rows funding-rate-pct storage-cost-pct
         [leg-signal-threshold-pct])
    -> a list of rows (near-month far-month near-price far-price days-between
    implied-carry-rate-pct implied-net-storage-cost-pct
    implied-convenience-yield-pct signal), one per pair of adjacent months.

    For each pair, the implied annual carry rate is
    c = ln(far-price / near-price) / (days-between / 365). Given your funding
    rate r and storage cost u, net storage cost = c - r and convenience yield
    = r + u - c. signal flags a pair whose carry rate differs from the median
    across all pairs by more than leg-signal-threshold-pct points.

    Storage cost and convenience yield only really mean something for a
    physical commodity such as CL; for financial futures, read them as a
    breakdown of the carry rate, which is meaningful either way. No network
    access. Returns '() with fewer than 2 rows."""
    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if len(rows) < 2:
        return NIL

    rows = sorted(rows, key=lambda r: row_field(r, 2))
    r = float(funding_rate_pct) / 100.0
    u = float(storage_cost_pct) / 100.0

    legs = []
    carries = []
    for i in range(len(rows) - 1):
        near, far = rows[i], rows[i + 1]
        near_days = float(row_field(near, 2))
        far_days = float(row_field(far, 2))
        days_between = far_days - near_days
        if days_between <= 0:
            continue
        near_price = float(row_field(near, 3))
        far_price = float(row_field(far, 3))
        dt_years = days_between / 365.0
        c = np.log(far_price / near_price) / dt_years
        net_storage = c - r
        convenience_yield = r + u - c
        carries.append(c)
        legs.append((near, far, near_price, far_price, days_between, c, net_storage, convenience_yield))

    if not legs:
        return NIL

    median_carry = float(np.median(carries))
    threshold = float(leg_signal_threshold_pct)

    out_rows = []
    for near, far, near_price, far_price, days_between, c, net_storage, convenience_yield in legs:
        pct_diff = (c - median_carry) * 100
        if pct_diff > threshold:
            signal = "Far month rich / near cheap"
        elif pct_diff < -threshold:
            signal = "Far month cheap / near rich"
        else:
            signal = "Fair"
        out_rows.append(list_to_pairs([
            near[0], far[0], near_price, far_price, int(days_between),
            float(c * 100), float(net_storage * 100), float(convenience_yield * 100),
            LispString(signal),
        ]))
    return list_to_pairs(out_rows)


BUILTINS = {
    "futures-curve-fit": futures_curve_fit,
    "futures-leg-carry": futures_leg_carry,
}
