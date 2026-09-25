"""Monthly time series for the Lisp interpreter.

MONTH NUMBERS: a month is represented by the integer year * 12 + (month - 1),
so January 2020 is 24240 and February 2020 is 24241. Because they're plain
integers, month arithmetic is ordinary arithmetic: three months later is
(+ m 3), a loan's age in months is a subtraction, and vector-lag by 1 is
the previous month. date->month-number, month-number->date,
yyyymm->month-number (for loan data's 202301-style reporting periods), and
month-number->yyyymm convert back and forth; each takes a single value or a
whole vector.

SERIES: a time series is (dates . values) -- a pair of vectors, the shape
fred-series returns. series-monthly turns a daily or weekly series into a
monthly one; series-values-at looks a series up at chosen months (e.g. to
attach a market rate to every loan-month row); series-table lines several
series up, month by month, in one table.
"""

import calendar
import datetime

import numpy as np

from lisp_core import LispDate, LispError, LispVector, NIL, Pair, _date_from_pydate, is_true, pairs_to_list
from lisp_tables import make_table_value
from lisp_vector_math import floats_of, is_number, to_vector


# ---------------------------------------------------------------------------
# Month numbers
# ---------------------------------------------------------------------------

def month_of_date(d, name):
    if not isinstance(d, LispDate):
        raise LispError("%s: not a date: %r" % (name, d))
    return d.date.year * 12 + d.date.month - 1


def date_of_month(m):
    year, month_index = divmod(int(m), 12)
    return LispDate(year, month_index + 1, 1)


def month_of_yyyymm(n, name):
    year, month = divmod(int(n), 100)
    if not 1 <= month <= 12:
        raise LispError("%s: %s isn't a YYYYMM value (the month must be 01 to 12)" % (name, n))
    return year * 12 + month - 1


def yyyymm_of_month(m):
    year, month_index = divmod(int(m), 12)
    return year * 100 + month_index + 1


def is_missing(x):
    return x is None or (isinstance(x, float) and x != x)


def each(x, convert):
    """convert(x) for a single value; for a vector, a vector of
    convert(element), with missing elements left missing."""
    if not isinstance(x, LispVector):
        return convert(x)
    results = [NIL if is_missing(e) else convert(e) for e in x.items.tolist()]
    if any(r is NIL for r in results) and all(r is NIL or is_number(r) for r in results):
        results = [float("nan") if r is NIL else r for r in results]     # missing numbers are NaN
    return LispVector(results)


def date_to_month_number(d):
    """(date->month-number d) -- the month number of a date (or of each date
    in a vector): year * 12 + (month - 1). The day is ignored."""
    return each(d, lambda x: month_of_date(x, "date->month-number"))


def month_number_to_date(m):
    """(month-number->date m) -- the first day of month number m (or of
    each month number in a vector)."""
    return each(m, date_of_month)


def yyyymm_to_month_number(n):
    """(yyyymm->month-number n) -- the month number of a YYYYMM value such
    as 202301 (or of each value in a vector), as loan-level data often
    records its reporting period."""
    return each(n, lambda x: month_of_yyyymm(x, "yyyymm->month-number"))


def month_number_to_yyyymm(m):
    """(month-number->yyyymm m) -- month number m as a YYYYMM value such as
    202301 (or each month number in a vector)."""
    return each(m, yyyymm_of_month)


def add_months(d, n):
    year, month_index = divmod(d.date.year * 12 + d.date.month - 1 + int(n), 12)
    last_day = calendar.monthrange(year, month_index + 1)[1]
    return _date_from_pydate(datetime.date(year, month_index + 1, min(d.date.day, last_day)))


def date_add_months(d, n):
    """(date-add-months d n) -- the date n months after d (or before, if n
    is negative), for one date or each date in a vector. A day past the end
    of the new month becomes its last day: Jan 31 + 1 month is Feb 28 or 29."""
    def shift(x):
        if not isinstance(x, LispDate):
            raise LispError("date-add-months: not a date: %r" % (x,))
        return add_months(x, n)
    return each(d, shift)


def months_between(d1, d2):
    """(months-between d1 d2) -- how many calendar months from d1 to d2
    (the days of the month are ignored): the month number of d2 minus that
    of d1. Either may be a vector."""
    m1 = date_to_month_number(d1)
    m2 = date_to_month_number(d2)
    if isinstance(m1, LispVector) or isinstance(m2, LispVector):
        a = floats_of(m1, "months-between") if isinstance(m1, LispVector) else m1
        b = floats_of(m2, "months-between") if isinstance(m2, LispVector) else m2
        difference = np.asarray(b) - np.asarray(a)
        if np.isnan(difference).any():
            return to_vector(difference)
        return to_vector(difference.astype(np.int64))
    return m2 - m1


def as_month_number(x, name):
    """A month given as a date or as a month number, as a month number."""
    return month_of_date(x, name) if isinstance(x, LispDate) else int(x)


def month_range(first, last):
    """(month-range first last) -- a vector of every month number from
    first to last, inclusive. first and last may be dates or month numbers."""
    start = as_month_number(first, "month-range")
    end = as_month_number(last, "month-range")
    return to_vector(np.arange(start, end + 1))


MONTH_BUILTINS = {
    "date->month-number": date_to_month_number,
    "month-number->date": month_number_to_date,
    "yyyymm->month-number": yyyymm_to_month_number,
    "month-number->yyyymm": month_number_to_yyyymm,
    "date-add-months": date_add_months,
    "months-between": months_between,
    "month-range": month_range,
}


# ---------------------------------------------------------------------------
# Series: (dates . values)
# ---------------------------------------------------------------------------

def series_parts(series, name):
    """A series' month numbers and values as numpy arrays, in date order,
    leaving out missing values."""
    if not (isinstance(series, Pair) and isinstance(series.car, LispVector)
            and isinstance(series.cdr, LispVector)):
        raise LispError("%s: a series is (dates . values), a pair of vectors" % name)
    dates, values = series.car.items.tolist(), floats_of(series.cdr, name)
    if len(dates) != len(values):
        raise LispError("%s: the series has %d dates but %d values" % (name, len(dates), len(values)))
    keep = [i for i, d in enumerate(dates) if isinstance(d, LispDate) and not np.isnan(values[i])]
    days = np.array([dates[i].date.toordinal() for i in keep], dtype=np.int64)
    months = np.array([month_of_date(dates[i], name) for i in keep], dtype=np.int64)
    values = values[keep]
    order = np.argsort(days, kind="stable")
    return months[order], values[order]


def monthly_values(series, how, name):
    """One value per month that has data: (months, values) numpy arrays,
    months ascending. how is mean, last, first, sum, min, or max."""
    months, values = series_parts(series, name)
    if len(months) == 0:
        return months, values
    distinct, group = np.unique(months, return_inverse=True)
    starts = np.flatnonzero(np.concatenate([[True], months[1:] != months[:-1]]))
    counts = np.bincount(group.reshape(-1))
    if how == "mean":
        result = np.add.reduceat(values, starts) / counts
    elif how == "sum":
        result = np.add.reduceat(values, starts)
    elif how == "first":
        result = values[starts]
    elif how == "last":
        result = values[starts + counts - 1]
    elif how == "min":
        result = np.minimum.reduceat(values, starts)
    elif how == "max":
        result = np.maximum.reduceat(values, starts)
    else:
        raise LispError("%s: how must be mean, last, first, sum, min, or max, got %s" % (name, how))
    return distinct, result


def series_monthly(series, how="mean"):
    """(series-monthly series [how]) -- a daily or weekly series turned into
    a monthly one: one value per month that has data, dated the first of
    the month. how says which value: mean (the default), last, first, sum,
    min, or max. Missing values are skipped."""
    months, values = monthly_values(series, str(how).lower(), "series-monthly")
    return Pair(LispVector([date_of_month(m) for m in months]), to_vector(values))


def values_at(series, months, fill_forward, name):
    """The series' monthly averages at each of `months` (a numpy array of
    month numbers): NaN for a month without data -- or, with fill_forward,
    the value of the latest earlier month that has data."""
    series_months, series_values = monthly_values(series, "mean", name)
    result = np.full(len(months), np.nan)
    if len(series_months) == 0:
        return result
    # position of the latest series month at or before each requested month
    position = np.searchsorted(series_months, months, side="right") - 1
    found = position >= 0
    if not fill_forward:
        found &= series_months[np.clip(position, 0, None)] == months
    result[found] = series_values[position[found]]
    return result


def months_argument(months, name):
    """A vector of month numbers or dates, as a numpy array of month numbers."""
    if not isinstance(months, LispVector):
        raise LispError("%s: expected a vector of month numbers or dates" % name)
    if months.items.dtype == object:
        return np.array([month_of_date(d, name) for d in months.items.tolist()], dtype=np.int64)
    return months.items.astype(np.int64)


def series_values_at(series, months, fill_forward=False):
    """(series-values-at series months [fill-forward?]) -- the series' value
    in each of the given months (a vector of month numbers or dates), such
    as a loan table's month column. A series with several values in a month
    (weekly, daily) is averaged over the month. A month with no data gives
    NaN -- or, with fill-forward? #t, the latest earlier month's value."""
    wanted = months_argument(months, "series-values-at")
    return to_vector(values_at(series, wanted, is_true(fill_forward), "series-values-at"))


def series_table(named_series, fill_forward=False):
    """(series-table (list (cons name series) ...) [fill-forward?]) -- a
    table lining several series up by month. Its columns are "month" (month
    numbers), "date" (the first of each month), and one column per series,
    named as given. The months run from the earliest month any series has
    data to the latest, every month included. A series with several values
    in a month is averaged; a month with no data is NaN -- or, with
    fill-forward? #t, the series' latest earlier value."""
    entries = []
    for entry in pairs_to_list(named_series):
        if not isinstance(entry, Pair):
            raise LispError("series-table: expected a list of (name . series) pairs")
        entries.append((str(entry.car), entry.cdr))
    if not entries:
        raise LispError("series-table: expected at least one (name . series) pair")
    all_months = [monthly_values(s, "mean", "series-table")[0] for _, s in entries]
    non_empty = [m for m in all_months if len(m)]
    if not non_empty:
        raise LispError("series-table: none of the series has any data")
    months = np.arange(min(m[0] for m in non_empty), max(m[-1] for m in non_empty) + 1)
    columns = [("month", to_vector(months)), ("date", LispVector([date_of_month(m) for m in months]))]
    for column_name, series in entries:
        columns.append((column_name, to_vector(values_at(series, months, is_true(fill_forward), "series-table"))))
    return make_table_value(columns)


SERIES_BUILTINS = {
    "series-monthly": series_monthly,
    "series-values-at": series_values_at,
    "series-table": series_table,
}


BUILTINS = {}
BUILTINS.update(MONTH_BUILTINS)
BUILTINS.update(SERIES_BUILTINS)
