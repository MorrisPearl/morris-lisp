"""Monthly time series for the Lisp interpreter.

MONTH NUMBERS: a month is represented by the integer year * 12 + (month - 1),
so January 2020 is 24240 and February 2020 is 24241. Because they're plain
integers, month arithmetic is ordinary arithmetic: three months later is
(+ m 3), a loan's age in months is a subtraction, and vector-lag by 1 is
the previous month. date->month-number, month-number->date,
yyyymm->month-number (for loan data's 202301-style reporting periods), and
month-number->yyyymm convert back and forth; each takes a single value or a
whole vector.

SERIES: a time series is a table with a column of dates and columns of
numbers, as fred-table, schwab-price-history, and bls-series make.
series-monthly turns a daily or weekly series into a monthly one;
series-values-at looks a series up at chosen months (e.g. to attach a
market rate to every loan-month row); series-table lines several series
up, month by month, in one table.
"""

import calendar
import datetime

import numpy as np

from lisp_core import LispDate, LispError, LispVector, NIL, Pair, _date_from_pydate, is_true, keyword_options, pairs_to_list
from lisp_tables import make_table_value, table_columns
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


def difference(a, b, name):
    """b - a, where each is a whole number or a vector of them (NaN where a
    value is missing)."""
    if isinstance(a, LispVector) or isinstance(b, LispVector):
        x = floats_of(a, name) if isinstance(a, LispVector) else a
        y = floats_of(b, name) if isinstance(b, LispVector) else b
        result = np.asarray(y) - np.asarray(x)
        if np.isnan(result).any():
            return to_vector(result)
        return to_vector(result.astype(np.int64))
    return b - a


def months_between(d1, d2):
    """(months-between d1 d2) -- how many calendar months from d1 to d2
    (the days of the month are ignored): the month number of d2 minus that
    of d1. Either may be a vector."""
    return difference(date_to_month_number(d1), date_to_month_number(d2), "months-between")


def check_date(x, name):
    if not isinstance(x, LispDate):
        raise LispError("%s: not a date: %r" % (name, x))
    return x


def days_between(d1, d2):
    """(days-between d1 d2) -- the actual number of days from d1 to d2
    (negative if d2 is earlier). Either may be a vector of dates. For a day
    count basis such as 30/360, see day-count."""
    days1 = each(d1, lambda x: check_date(x, "days-between").date.toordinal())
    days2 = each(d2, lambda x: check_date(x, "days-between").date.toordinal())
    return difference(days1, days2, "days-between")


def date_add_years(d, n):
    """(date-add-years d n) -- the date n years after d (or before, if n is
    negative), for one date or each date in a vector. February 29 becomes
    February 28 in a year that isn't a leap year."""
    return each(d, lambda x: add_months(check_date(x, "date-add-years"), 12 * int(n)))


def date_end_of_month(d):
    """(date-end-of-month d) -- the last day of d's month, for one date or
    each date in a vector."""
    def last_day(x):
        year, month = check_date(x, "date-end-of-month").date.year, x.date.month
        return LispDate(year, month, calendar.monthrange(year, month)[1])
    return each(d, last_day)


def date_day_of_week(d):
    """(date-day-of-week d) -- the day of the week, 1 for Monday to 7 for
    Sunday, of one date or each date in a vector."""
    return each(d, lambda x: check_date(x, "date-day-of-week").date.isoweekday())


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
    "date-add-years": date_add_years,
    "days-between": days_between,
    "date-end-of-month": date_end_of_month,
    "date-day-of-week": date_day_of_week,
    "month-range": month_range,
}


# ---------------------------------------------------------------------------
# Series: tables of dates and numbers
# ---------------------------------------------------------------------------

def is_date_column(vector):
    items = vector.items.tolist()
    return vector.items.dtype == object and any(isinstance(d, LispDate) for d in items) and \
        all(d is None or isinstance(d, LispDate) for d in items)


def series_columns(table, who):
    """A series table's rows' day numbers and month numbers (-1 for a row
    without a date), and its columns of values, as (name, float array): every
    column of numbers but its dates and a month column. Its dates are its
    column named date, or, if it has none, its one column of dates."""
    columns = table_columns(table, who)
    date_names = [name for name, _ in columns if name == "date"] or \
        [name for name, vector in columns if is_date_column(vector)]
    if len(date_names) != 1:
        raise LispError("%s: a series is a table with a column of dates (named date, if it has more than one)" % who)
    dates = dict(columns)[date_names[0]].items.tolist()
    days = np.array([d.date.toordinal() if isinstance(d, LispDate) else -1 for d in dates], dtype=np.int64)
    months = np.array([month_of_date(d, who) if isinstance(d, LispDate) else -1 for d in dates], dtype=np.int64)
    values = [(name, floats_of(vector, who)) for name, vector in columns
              if name not in (date_names[0], "month") and np.issubdtype(vector.items.dtype, np.number)]
    if not values:
        raise LispError("%s: the table has no column of numbers besides its dates" % who)
    return days, months, values


def monthly_values(days, months, values, how, who):
    """One column's values, one per month that has data: (months, values)
    numpy arrays, months ascending. how is mean, last, first, sum, min, or
    max. A row without a date or a value is left out."""
    keep = (days >= 0) & ~np.isnan(values)
    order = np.argsort(days[keep], kind="stable")
    months, values = months[keep][order], values[keep][order]
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
        raise LispError("%s: :how must be mean, last, first, sum, min, or max, not %s" % (who, how))
    return distinct, result


def values_at(series_months, series_values, months, fill_forward):
    """A column's monthly values (series_months, series_values) at each of
    `months` (a numpy array of month numbers): NaN for a month without data
    -- or, with fill_forward, the value of the latest earlier month that has
    data."""
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


def monthly_table(months, columns):
    """A table of month, date (the first of the month), and these (name,
    values) columns, for these month numbers."""
    return make_table_value([("month", to_vector(months)), ("date", LispVector([date_of_month(m) for m in months]))] +
                            [(name, to_vector(values)) for name, values in columns])


def series_monthly(table, *options):
    """(series-monthly table [:how h]) -- a daily or weekly series made
    monthly: a table of month, date (the first of the month), and each of
    the table's columns of numbers, with a row for each month that has data.
    :how says which of a month's values: mean (the default), last, first,
    sum, min, or max. Missing values are left out."""
    who = "series-monthly"
    options = keyword_options(options, ["how"], who)
    how = str(options.get("how", "mean")).lower()
    days, months, values = series_columns(table, who)
    monthly = [(name, monthly_values(days, months, column, how, who)) for name, column in values]
    all_months = np.unique(np.concatenate([m for _, (m, _) in monthly]))
    return monthly_table(all_months, [(name, values_at(m, v, all_months, False)) for name, (m, v) in monthly])


def months_argument(months, name):
    """A vector of month numbers or dates, as a numpy array of month numbers."""
    if not isinstance(months, LispVector):
        raise LispError("%s: expected a vector of month numbers or dates" % name)
    if months.items.dtype == object:
        return np.array([month_of_date(d, name) for d in months.items.tolist()], dtype=np.int64)
    return months.items.astype(np.int64)


def series_values_at(table, months, *options):
    """(series-values-at table months [:column name] [:fill-forward #t]) --
    a column of a series in each of the given months (a vector of month
    numbers or dates), such as a loan table's month column. :column is the
    column, if the table has more than one. A series with several values in
    a month (weekly, daily) is averaged over the month. A month with no data
    gives NaN -- or, with :fill-forward #t, the latest earlier month's value."""
    who = "series-values-at"
    options = keyword_options(options, ["column", "fill-forward"], who)
    days, series_months, values = series_columns(table, who)
    if "column" in options:
        chosen = [column for name, column in values if name == str(options["column"])]
        if not chosen:
            raise LispError("%s: the table has no column of numbers named %s (it has %s)"
                            % (who, options["column"], ", ".join(name for name, _ in values)))
        column = chosen[0]
    elif len(values) == 1:
        column = values[0][1]
    else:
        raise LispError("%s: the table has %d columns of numbers (%s): say which with :column"
                        % (who, len(values), ", ".join(name for name, _ in values)))
    months_with_data, monthly = monthly_values(days, series_months, column, "mean", who)
    return to_vector(values_at(months_with_data, monthly, months_argument(months, who),
                               is_true(options.get("fill-forward", False))))


def series_table(tables, *options):
    """(series-table tables [:fill-forward #t]) -- several series, a list of
    tables, lined up by month in one table: month, date (the first of each
    month), and every column of numbers of the tables, under its own name.
    The months run from the earliest month any of them has data to the
    latest, every month included. A column with several values in a month is
    averaged; a month with no data is NaN -- or, with :fill-forward #t, the
    column's latest earlier value."""
    who = "series-table"
    options = keyword_options(options, ["fill-forward"], who)
    fill_forward = is_true(options.get("fill-forward", False))
    monthly = []
    for table in pairs_to_list(tables) if (tables is NIL or isinstance(tables, Pair)) else [None]:
        if table is None:
            raise LispError("%s: expected a list of tables" % who)
        days, months, values = series_columns(table, who)
        for name, column in values:
            if name in [n for n, _ in monthly]:
                raise LispError("%s: two of the tables have a column named %s -- rename one (table-rename-column)"
                                % (who, name))
            monthly.append((name, monthly_values(days, months, column, "mean", who)))
    with_data = [m for _, (m, _) in monthly if len(m)]
    if not with_data:
        raise LispError("%s: none of the tables has any data" % who)
    all_months = np.arange(min(m[0] for m in with_data), max(m[-1] for m in with_data) + 1)
    return monthly_table(all_months, [(name, values_at(m, v, all_months, fill_forward)) for name, (m, v) in monthly])


SERIES_BUILTINS = {
    "series-monthly": series_monthly,
    "series-values-at": series_values_at,
    "series-table": series_table,
}


BUILTINS = {}
BUILTINS.update(MONTH_BUILTINS)
BUILTINS.update(SERIES_BUILTINS)
