"""Day counts and cash-flow math for the Lisp interpreter.

DAY COUNTS: how long the period from one date to another is, under a day
count basis -- as a number of days (day-count) or a fraction of a year
(year-fraction). The bases:

  30/360    every month counts as 30 days, and a year as 360 (the US bond
            basis, also used for mortgages and agency MBS). A 31st counts as
            the 30th; so does the second date's 31st when the first date is
            the 30th or 31st.
  30E/360   the same, except that any 31st counts as the 30th (the Eurobond
            basis).
  ACT/360   the actual number of days, over 360 (money markets, SOFR).
  ACT/365   the actual number of days, over 365 (sterling; Excel's XNPV).
  ACT/ACT   the actual number of days, over the actual length of each
            calendar year the period touches: 365 or 366 (ISDA; Treasuries
            are close to this).

A basis is written as a string or a symbol, in upper or lower case:
"30/360", 'act/360, ...

CASH FLOWS: a list or a vector of amounts, one per period, the periods
equally spaced (xnpv and xirr take a date for each amount instead). npv and
irr count the first amount as now; present-value, yield, duration, and
convexity count the first as one period from now, as a bond's cash flows
are. A rate is per period; a yield is per year, compounded periods-per-year
times a year.

The math is done with numpy in double precision, however the cash flows
are stored. irr, xirr, and yield find their rate by bisection -- halving an
interval that contains it until it's pinned down to 12 decimal places --
which is slower than cleverer methods, but always works once it has an
interval, and is easy to follow (see solve_rate).
"""

import calendar
import datetime

import numpy as np

from lisp_core import LispDate, LispError, LispVector, NIL, Pair, _brief, pairs_to_list
from lisp_vector_math import is_number, to_vector


# ---------------------------------------------------------------------------
# Day counts
# ---------------------------------------------------------------------------

BASES = ("30/360", "30E/360", "ACT/360", "ACT/365", "ACT/ACT")


def basis_name(basis, who):
    """A day count basis argument, checked, as one of BASES."""
    name = str(basis).upper()
    if name not in BASES:
        raise LispError("%s: unknown day count basis %s -- use one of %s"
                        % (who, _brief(basis), ", ".join(BASES)))
    return name


def days_30_360(d1, d2, european):
    """The days from d1 to d2 (Python dates) counting every month as 30 days."""
    day1, day2 = min(d1.day, 30), d2.day
    if european or day1 == 30:
        day2 = min(day2, 30)
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (day2 - day1)


def year_length(year):
    return 366 if calendar.isleap(year) else 365


def actual_actual_years(d1, d2):
    """ACT/ACT: the days in each calendar year from d1 to d2, over that year's
    length, added up."""
    if d2 < d1:
        return -actual_actual_years(d2, d1)
    total = 0.0
    start = d1
    while start.year < d2.year:
        next_new_year = datetime.date(start.year + 1, 1, 1)
        total += (next_new_year - start).days / year_length(start.year)
        start = next_new_year
    return total + (d2 - start).days / year_length(d2.year)


def days_under(d1, d2, basis):
    """The days from d1 to d2 (Python dates) under basis (a name from BASES)."""
    if basis == "30/360":
        return days_30_360(d1, d2, european=False)
    if basis == "30E/360":
        return days_30_360(d1, d2, european=True)
    return (d2 - d1).days


def years_under(d1, d2, basis):
    """The fraction of a year from d1 to d2 (Python dates) under basis."""
    if basis == "ACT/ACT":
        return actual_actual_years(d1, d2)
    if basis == "ACT/365":
        return (d2 - d1).days / 365
    return days_under(d1, d2, basis) / 360


def python_date(x, who):
    if not isinstance(x, LispDate):
        raise LispError("%s: not a date: %s" % (who, _brief(x)))
    return x.date


def for_each_pair_of_dates(d1, d2, function, who):
    """function(date1, date2) for two dates. If either is a vector of
    dates, a vector: function for each pair of elements, a single date being
    used with every element, and a missing date giving NaN."""
    if not isinstance(d1, LispVector) and not isinstance(d2, LispVector):
        return function(python_date(d1, who), python_date(d2, who))
    firsts = d1.items.tolist() if isinstance(d1, LispVector) else None
    seconds = d2.items.tolist() if isinstance(d2, LispVector) else None
    n = len(firsts if firsts is not None else seconds)
    if firsts is not None and seconds is not None and len(firsts) != len(seconds):
        raise LispError("%s: the vectors have different lengths: %d, %d" % (who, len(firsts), len(seconds)))
    results = []
    for i in range(n):
        a = firsts[i] if firsts is not None else d1
        b = seconds[i] if seconds is not None else d2
        if a is None or b is None:
            results.append(np.nan)
        else:
            results.append(function(python_date(a, who), python_date(b, who)))
    return to_vector(np.array(results))


def day_count(d1, d2, basis):
    """(day-count d1 d2 basis) -- the number of days from d1 to d2 under a
    day count basis (see the top of this file). Either may be a vector of
    dates."""
    name = basis_name(basis, "day-count")
    return for_each_pair_of_dates(d1, d2, lambda a, b: days_under(a, b, name), "day-count")


def year_fraction(d1, d2, basis):
    """(year-fraction d1 d2 basis) -- the fraction of a year from d1 to d2
    under a day count basis: the fraction of a year's interest that accrues
    between them. Either may be a vector of dates."""
    name = basis_name(basis, "year-fraction")
    return for_each_pair_of_dates(d1, d2, lambda a, b: years_under(a, b, name), "year-fraction")


# ---------------------------------------------------------------------------
# Cash flows
# ---------------------------------------------------------------------------

def amounts(cashflows, who):
    """Cash flows -- a list or a vector of numbers -- as a float64 numpy array."""
    if isinstance(cashflows, LispVector):
        values = cashflows.items.tolist()
    elif cashflows is NIL or isinstance(cashflows, Pair):
        values = pairs_to_list(cashflows)
    else:
        raise LispError("%s: the cash flows must be a list or a vector of numbers, not %s"
                        % (who, _brief(cashflows)))
    if not values:
        raise LispError("%s: there are no cash flows" % who)
    for v in values:
        if not is_number(v) or v != v:
            raise LispError("%s: every cash flow must be a number, not %s" % (who, _brief(v)))
    return np.array(values, dtype=np.float64)


def check_number(x, what, who):
    if not is_number(x):
        raise LispError("%s: %s must be a number, not %s" % (who, what, _brief(x)))


def discounted_total(flows, rate, times):
    """The sum of flows[i] / (1 + rate) ** times[i]: infinity or NaN if the
    rate is so extreme that the numbers overflow."""
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        return float(np.sum(flows / (1.0 + rate) ** times))


# Where solve_rate looks for a rate: -99%, every 1% from -95% to 100%, then
# a few higher rates (per period), in order.
RATE_GRID = [-0.99] + [i / 100 for i in range(-95, 101)] + [1.5, 2.0, 3.0, 5.0, 10.0]


def solve_rate(value_at, who, low=None, high=None):
    """The rate at which value_at(rate) is 0, to 12 decimal places.

    First an interval that contains it: [low, high] if given; otherwise, of
    the neighbouring rates in RATE_GRID between which value_at changes sign,
    the pair nearest 0. (A stream of cash flows that changes sign more than
    once can have more than one such rate; give low and high to choose
    another.) Then bisection: look at the middle of the interval, keep the
    half in which value_at changes sign, and repeat."""
    if low is None:
        low, high = bracket_rate(value_at, who)
    f_low, f_high = value_at(low), value_at(high)
    if f_low == 0:
        return low
    if f_high == 0:
        return high
    if not (np.isfinite(f_low) and np.isfinite(f_high)) or (f_low < 0) == (f_high < 0):
        raise LispError("%s: there's no rate between %s and %s where the value is 0" % (who, low, high))
    while high - low > 1e-12:
        middle = (low + high) / 2
        f_middle = value_at(middle)
        if f_middle == 0:
            return middle
        if (f_middle < 0) == (f_low < 0):
            low, f_low = middle, f_middle
        else:
            high = middle
    return (low + high) / 2


def bracket_rate(value_at, who):
    """Two neighbouring rates from RATE_GRID between which value_at changes
    sign -- the pair nearest 0 -- or an error if there are none."""
    values = [(rate, value_at(rate)) for rate in RATE_GRID]
    values = [(rate, v) for rate, v in values if np.isfinite(v)]
    for rate, v in values:
        if v == 0:
            return rate, rate
    pairs = [(a, b) for (a, fa), (b, fb) in zip(values, values[1:]) if (fa < 0) != (fb < 0)]
    if not pairs:
        raise LispError("%s: no rate from %g%% to %g%% a period gives a value of 0 -- do the cash "
                        "flows include both payments and receipts?" % (who, RATE_GRID[0] * 100, RATE_GRID[-1] * 100))
    return min(pairs, key=lambda pair: min(abs(pair[0]), abs(pair[1])))


def rate_range(low, high, who):
    """irr's optional low and high: both, or neither."""
    if low is None and high is None:
        return None, None
    if low is None or high is None:
        raise LispError("%s: give both low and high, or neither" % who)
    check_number(low, "low", who)
    check_number(high, "high", who)
    return float(low), float(high)


def npv(rate, cashflows):
    """(npv rate cashflows) -- the net present value, at `rate` per period, of
    cash flows one period apart, the first of them now (so it isn't
    discounted). (Excel's NPV counts the first cash flow as one period away.)"""
    check_number(rate, "the rate", "npv")
    flows = amounts(cashflows, "npv")
    return discounted_total(flows, rate, np.arange(len(flows)))


def irr(cashflows, low=None, high=None):
    """(irr cashflows [low high]) -- the internal rate of return: the rate per
    period at which the npv of cashflows is 0. See solve_rate for how it's
    found, and for low and high."""
    flows = amounts(cashflows, "irr")
    times = np.arange(len(flows))
    low, high = rate_range(low, high, "irr")
    return solve_rate(lambda rate: discounted_total(flows, rate, times), "irr", low, high)


def dated_times(dates, flows, basis, who):
    """The time, in years under basis, from the first date to each date."""
    if isinstance(dates, LispVector):
        date_list = dates.items.tolist()
    elif dates is NIL or isinstance(dates, Pair):
        date_list = pairs_to_list(dates)
    else:
        raise LispError("%s: the dates must be a list or a vector of dates, not %s" % (who, _brief(dates)))
    if len(date_list) != len(flows):
        raise LispError("%s: there are %d dates but %d cash flows" % (who, len(date_list), len(flows)))
    name = basis_name(basis, who)
    first = python_date(date_list[0], who)
    return np.array([years_under(first, python_date(d, who), name) for d in date_list])


def xnpv(rate, dates, cashflows, basis="ACT/365"):
    """(xnpv rate dates cashflows [basis]) -- the net present value, at
    `rate` a year, of cash flows on the given dates, discounted to the first
    date. The time to each date is its year-fraction under basis (ACT/365
    unless given, as in Excel's XNPV)."""
    check_number(rate, "the rate", "xnpv")
    flows = amounts(cashflows, "xnpv")
    return discounted_total(flows, rate, dated_times(dates, flows, basis, "xnpv"))


def xirr(dates, cashflows, basis="ACT/365"):
    """(xirr dates cashflows [basis]) -- the annual rate at which the xnpv of
    the cash flows is 0."""
    flows = amounts(cashflows, "xirr")
    times = dated_times(dates, flows, basis, "xirr")
    return solve_rate(lambda rate: discounted_total(flows, rate, times), "xirr")


def payment(rate, periods, principal):
    """(payment rate periods principal) -- the level payment each period that
    pays off `principal`, with interest at `rate` per period, in `periods`
    payments: for a mortgage, the monthly payment, with rate the annual rate
    / 12 and periods the number of months."""
    for x, what in ((rate, "the rate"), (periods, "the number of periods"), (principal, "the principal")):
        check_number(x, what, "payment")
    if periods <= 0:
        raise LispError("payment: the number of periods must be more than 0, not %s" % (periods,))
    if rate == 0:
        return principal / periods
    return principal * rate / (1 - (1 + rate) ** -periods)


def periodic_flows(yield_, periods_per_year, cashflows, who):
    """The cash flows (as numbers), their times in periods (1, 2, ...), and
    the yield per period."""
    check_number(yield_, "the yield", who)
    check_number(periods_per_year, "periods-per-year", who)
    if periods_per_year <= 0:
        raise LispError("%s: periods-per-year must be more than 0, not %s" % (who, periods_per_year))
    flows = amounts(cashflows, who)
    return flows, np.arange(1, len(flows) + 1), yield_ / periods_per_year


def present_value(yield_, periods_per_year, cashflows):
    """(present-value yield periods-per-year cashflows) -- what cash flows one
    period apart, the first one period from now, are worth at an annual
    `yield` compounded periods-per-year times a year: for a bond, its price."""
    flows, times, per_period = periodic_flows(yield_, periods_per_year, cashflows, "present-value")
    return discounted_total(flows, per_period, times)


def yield_of(price, periods_per_year, cashflows):
    """(yield price periods-per-year cashflows) -- the annual yield,
    compounded periods-per-year times a year, at which the cash flows'
    present value is `price`."""
    check_number(price, "the price", "yield")
    flows, times, _ = periodic_flows(0, periods_per_year, cashflows, "yield")
    per_period = solve_rate(lambda rate: discounted_total(flows, rate, times) - price, "yield")
    return per_period * periods_per_year


def duration(yield_, periods_per_year, cashflows):
    """(duration yield periods-per-year cashflows) -- the Macaulay duration,
    in years: the average time until the cash flows arrive, each weighted by
    its present value."""
    flows, times, per_period = periodic_flows(yield_, periods_per_year, cashflows, "duration")
    discounted = flows / (1 + per_period) ** times
    return float(np.sum(times / periods_per_year * discounted) / np.sum(discounted))


def modified_duration(yield_, periods_per_year, cashflows):
    """(modified-duration yield periods-per-year cashflows) -- the Macaulay
    duration divided by (1 + yield per period): the percentage change in
    price for a change of 1 (that is, 100%) in the yield, so a 1bp rise in
    the yield lowers the price by about modified-duration / 10000 of it."""
    macaulay = duration(yield_, periods_per_year, cashflows)
    return macaulay / (1 + yield_ / periods_per_year)


def convexity(yield_, periods_per_year, cashflows):
    """(convexity yield periods-per-year cashflows) -- the convexity, in years
    squared: how much the duration changes as the yield changes. A change dy
    in the yield changes the price by about
    price * (-modified-duration * dy + convexity * dy * dy / 2)."""
    flows, times, per_period = periodic_flows(yield_, periods_per_year, cashflows, "convexity")
    discounted = flows / (1 + per_period) ** times
    weighted = np.sum(times * (times + 1) * discounted)
    return float(weighted / (np.sum(discounted) * (1 + per_period) ** 2 * periods_per_year ** 2))


def bond_cashflows(coupon_rate, years, periods_per_year, face=100):
    """(bond-cashflows coupon-rate years periods-per-year [face]) -- a bond's
    cash flows from now to maturity: a coupon of face * coupon-rate /
    periods-per-year each period, and the face value with the last coupon.
    face is 100 unless given, so prices come out per 100 of face."""
    for x, what in ((coupon_rate, "the coupon rate"), (years, "the years"),
                    (periods_per_year, "periods-per-year"), (face, "the face value")):
        check_number(x, what, "bond-cashflows")
    n = round(years * periods_per_year)
    if n <= 0 or abs(n - years * periods_per_year) > 1e-9:
        raise LispError("bond-cashflows: years * periods-per-year must be a whole number of "
                        "periods, more than 0, not %s" % (years * periods_per_year,))
    flows = np.full(n, face * coupon_rate / periods_per_year, dtype=np.float64)
    flows[-1] += face
    return to_vector(flows)


BUILTINS = {
    "day-count": day_count,
    "year-fraction": year_fraction,
    "npv": npv,
    "irr": irr,
    "xnpv": xnpv,
    "xirr": xirr,
    "payment": payment,
    "present-value": present_value,
    "yield": yield_of,
    "duration": duration,
    "modified-duration": modified_duration,
    "convexity": convexity,
    "bond-cashflows": bond_cashflows,
}
