"""Vector math for the Lisp interpreter: arithmetic, comparisons, and
statistics on whole vectors, plus time-series helpers (lag, differences,
cumulative sums, rolling averages).

Each builtin here is a single numpy operation over the whole vector, so
it's fast even on millions of values -- far faster than a Lisp loop over
vector-ref.

Arithmetic and comparisons take two vectors of the same length, or a
vector and a single number (which is used with every element).

MISSING VALUES are NaN ("not a number", written `nan` in Lisp): a SQLite
NULL in a numeric column, a division by zero, or a lag that reaches
before the start of a series. Arithmetic involving NaN gives NaN, and
every statistic (vector-sum, vector-mean, ...) skips NaN values. In a
vector of strings or dates, '() plays the same role. vector-nan? finds
missing values; vector-fill-nan and vector-fill-forward replace them.
"""

import math

import numpy as np

from lisp_core import (
    LispDate, LispError, LispVector, NIL, _lisp_scalar, is_true, numeric_value, to_string,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_vector(arr):
    """A numpy array as a LispVector, stored the way the interpreter's
    dtype policy says (see LispVector): floats as FLOAT_DTYPE, true/false
    as 0/1 in BOOL_INT_DTYPE, other integers as INT_DTYPE when they fit.
    Anything else (strings, dates) is kept as it is."""
    arr = np.asarray(arr)
    if arr.dtype == bool:
        return LispVector(arr.astype(LispVector.BOOL_INT_DTYPE))
    if np.issubdtype(arr.dtype, np.floating):
        return LispVector(arr.astype(LispVector.FLOAT_DTYPE))
    if np.issubdtype(arr.dtype, np.integer):
        limits = np.iinfo(LispVector.INT_DTYPE)
        if len(arr) == 0 or (arr.min() >= limits.min and arr.max() <= limits.max):
            return LispVector(arr.astype(LispVector.INT_DTYPE))
        return LispVector(arr.astype(np.int64))
    return LispVector(arr)


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def require_vector(v, name):
    if not isinstance(v, LispVector):
        raise LispError("%s: not a vector: %s" % (name, to_string(v)))


def numbers_of(v, name):
    """A vector's values as an int64 or float64 numpy array, ready for
    arithmetic. Integers stay integers; dates become day numbers; '()
    becomes NaN. A string is an error."""
    require_vector(v, name)
    items = v.items
    if np.issubdtype(items.dtype, np.integer):
        return items.astype(np.int64)
    if np.issubdtype(items.dtype, np.floating):
        return items.astype(np.float64)
    try:
        return np.array([numeric_value(x) for x in items.tolist()], dtype=np.float64)
    except (TypeError, ValueError):
        raise LispError("%s: the vector holds something that isn't a number or a date" % name)


def floats_of(v, name):
    """A vector's values as a float64 numpy array (see numbers_of)."""
    return numbers_of(v, name).astype(np.float64)


def operand(x, name):
    """One argument of an arithmetic builtin: a vector's values as a
    numpy array, or a single number as it is."""
    if is_number(x):
        return x
    return numbers_of(x, name)


def check_lengths(name, *arrays):
    """Every numpy array among `arrays` must be the same length, and there
    must be at least one (at least one argument must be a vector)."""
    lengths = {len(a) for a in arrays if isinstance(a, np.ndarray)}
    if not lengths:
        raise LispError("%s: expected at least one vector" % name)
    if len(lengths) > 1:
        raise LispError("%s: the vectors have different lengths: %s"
                        % (name, ", ".join(str(n) for n in sorted(lengths))))


def missing_mask(v):
    """A numpy bool array: True where v's element is missing -- NaN in a
    numeric vector, or '() or NaN in a vector of strings or dates."""
    items = v.items
    if np.issubdtype(items.dtype, np.floating):
        return np.isnan(items)
    if items.dtype != object:
        return np.zeros(len(items), dtype=bool)
    return np.array([x is None or (isinstance(x, float) and math.isnan(x)) for x in items.tolist()],
                    dtype=bool)


def truth_of(mask, name):
    """A 0/1 mask vector as a numpy bool array. Any nonzero number counts
    as true; 0 and NaN count as false."""
    values = floats_of(mask, name)
    return (values != 0) & ~np.isnan(values)


def sort_key(value):
    """An ordering for mixed values: numbers, then strings, then dates, then
    '() last (as numpy sorts NaN last)."""
    if is_number(value):
        return (0, value)
    if isinstance(value, str):
        return (1, value)
    if isinstance(value, LispDate):
        return (2, value.date)
    if value is None:
        return (4, 0)
    return (3, str(value))


def factorize(items):
    """Number the distinct values of a numpy array in sorted order.
    Returns (codes, distinct): codes[i] is the position of items[i] in the
    sorted list `distinct`. Used for grouping, sorting, and joining."""
    if items.dtype != object:
        distinct, codes = np.unique(items, return_inverse=True)
        return codes.reshape(-1).astype(np.int64), distinct.tolist()
    values = items.tolist()
    distinct = sorted(set(values), key=sort_key)
    position = {value: i for i, value in enumerate(distinct)}
    return np.array([position[value] for value in values], dtype=np.int64), distinct


_NO_DEFAULT = object()   # marks an optional argument that wasn't given


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def elementwise(name, a, b, operation):
    """Apply a numpy operation to two vectors, or a vector and a number."""
    x, y = operand(a, name), operand(b, name)
    check_lengths(name, x, y)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return to_vector(operation(x, y))


def vector_add(a, b):
    """(vector-add a b) -- a + b, element by element."""
    return elementwise("vector-add", a, b, np.add)


def vector_sub(a, b):
    """(vector-sub a b) -- a - b, element by element."""
    return elementwise("vector-sub", a, b, np.subtract)


def vector_mul(a, b):
    """(vector-mul a b) -- a * b, element by element."""
    return elementwise("vector-mul", a, b, np.multiply)


def vector_div(a, b):
    """(vector-div a b) -- a / b, element by element; dividing by zero gives
    NaN or infinity rather than an error."""
    return elementwise("vector-div", a, b, np.true_divide)


def vector_pow(a, b):
    """(vector-pow a b) -- a raised to the power b, element by element."""
    return elementwise("vector-pow", a, b, lambda x, y: np.power(np.asarray(x, dtype=np.float64), y))


def unary(name, v, operation):
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return to_vector(operation(numbers_of(v, name)))


def vector_round(v, decimals=0):
    """(vector-round v [decimals]) -- each element rounded to `decimals`
    places (default 0). Halves round to even, like the scalar round."""
    return unary("vector-round", v, lambda x: np.round(x, int(decimals)))


def vector_clip(v, low, high):
    """(vector-clip v low high) -- each element limited to the range
    [low, high]; pass '() for no limit on that side."""
    lo = None if low is NIL else low
    hi = None if high is NIL else high
    return unary("vector-clip", v, lambda x: np.clip(x, lo, hi))


ARITHMETIC_BUILTINS = {
    "vector-add": vector_add,
    "vector-sub": vector_sub,
    "vector-mul": vector_mul,
    "vector-div": vector_div,
    "vector-pow": vector_pow,
    "vector-log": lambda v: unary("vector-log", v, lambda x: np.log(np.asarray(x, dtype=np.float64))),
    "vector-exp": lambda v: unary("vector-exp", v, lambda x: np.exp(np.asarray(x, dtype=np.float64))),
    "vector-sqrt": lambda v: unary("vector-sqrt", v, lambda x: np.sqrt(np.asarray(x, dtype=np.float64))),
    "vector-abs": lambda v: unary("vector-abs", v, np.abs),
    "vector-round": vector_round,
    "vector-clip": vector_clip,
}


# ---------------------------------------------------------------------------
# Comparisons, masks, and selecting elements
# ---------------------------------------------------------------------------
#
# A comparison gives a MASK: a vector of 1 (true) and 0 (false), one per
# element. Masks combine with vector-and / vector-or / vector-not, pick out
# elements with vector-select, and pick out table rows with table-filter.

def comparable(x, name):
    """One argument of a comparison: a vector's values as a numpy array
    (strings and dates kept as they are), or a single value."""
    if not isinstance(x, LispVector):
        return x
    if x.items.dtype == object:
        return x.items
    return numbers_of(x, name)


def compare(name, a, b, operation):
    x, y = comparable(a, name), comparable(b, name)
    check_lengths(name, x, y)
    length = len(x) if isinstance(x, np.ndarray) else len(y)
    try:
        with np.errstate(invalid="ignore"):
            result = np.asarray(operation(x, y), dtype=bool)
    except TypeError:
        raise LispError("%s: can't compare these values (e.g. a number with a string)" % name)
    if result.shape != (length,):          # numpy gave one answer for the whole vector
        result = np.full(length, bool(result))
    return to_vector(result)


def vector_and(*masks):
    """(vector-and m1 m2 ...) -- 1 where every mask is true, else 0."""
    if not masks:
        raise LispError("vector-and: expected at least one mask")
    arrays = [truth_of(m, "vector-and") for m in masks]
    check_lengths("vector-and", *arrays)
    return to_vector(np.logical_and.reduce(arrays))


def vector_or(*masks):
    """(vector-or m1 m2 ...) -- 1 where any mask is true, else 0."""
    if not masks:
        raise LispError("vector-or: expected at least one mask")
    arrays = [truth_of(m, "vector-or") for m in masks]
    check_lengths("vector-or", *arrays)
    return to_vector(np.logical_or.reduce(arrays))


def where_values(x, length, name):
    """One of vector-where's two choices as a numpy array: a vector's
    values, or a single value repeated `length` times. Strings and dates
    are kept as objects."""
    if isinstance(x, LispVector):
        return x.items if x.items.dtype == object else numbers_of(x, name)
    if is_number(x):
        return np.full(length, x)
    result = np.empty(length, dtype=object)
    result[:] = x
    return result


def vector_where(mask, if_true, if_false):
    """(vector-where mask a b) -- element by element, a where the mask is
    true and b where it's false. a and b are vectors or single values."""
    choose = truth_of(mask, "vector-where")
    a = where_values(if_true, len(choose), "vector-where")
    b = where_values(if_false, len(choose), "vector-where")
    check_lengths("vector-where", choose, a, b)
    return to_vector(np.where(choose, a, b))


def vector_select(v, mask):
    """(vector-select v mask) -- just the elements of v where the mask is
    true, in order."""
    require_vector(v, "vector-select")
    keep = truth_of(mask, "vector-select")
    check_lengths("vector-select", v.items, keep)
    return LispVector(v.items[keep])


def vector_nan_p(v):
    """(vector-nan? v) -- a mask: 1 where v's element is missing (NaN, or
    '() in a vector of strings or dates)."""
    require_vector(v, "vector-nan?")
    return to_vector(missing_mask(v))


def vector_fill_nan(v, value):
    """(vector-fill-nan v value) -- v with every missing element replaced
    by value."""
    require_vector(v, "vector-fill-nan")
    missing = missing_mask(v)
    if v.items.dtype != object and is_number(value):
        values = numbers_of(v, "vector-fill-nan")
        result = values.astype(np.result_type(values.dtype, type(value)))
        result[missing] = value
        return to_vector(result)
    result = v.items.astype(object)
    result[missing] = value
    return LispVector(result)


def vector_fill_forward(v):
    """(vector-fill-forward v) -- v with each missing element replaced by
    the nearest earlier value that isn't missing. Missing values before
    the first real value stay missing."""
    require_vector(v, "vector-fill-forward")
    missing = missing_mask(v)
    # For each position, the index of the latest non-missing value so far.
    # Leading missing values point at index 0, which is itself missing.
    position = np.where(missing, 0, np.arange(len(missing)))
    np.maximum.accumulate(position, out=position)
    return LispVector(v.items[position])


COMPARISON_BUILTINS = {
    "vector=": lambda a, b: compare("vector=", a, b, lambda x, y: x == y),
    "vector/=": lambda a, b: compare("vector/=", a, b, lambda x, y: x != y),
    "vector<": lambda a, b: compare("vector<", a, b, lambda x, y: x < y),
    "vector<=": lambda a, b: compare("vector<=", a, b, lambda x, y: x <= y),
    "vector>": lambda a, b: compare("vector>", a, b, lambda x, y: x > y),
    "vector>=": lambda a, b: compare("vector>=", a, b, lambda x, y: x >= y),
    "vector-and": vector_and,
    "vector-or": vector_or,
    "vector-not": lambda m: to_vector(~truth_of(m, "vector-not")),
    "vector-where": vector_where,
    "vector-select": vector_select,
    "vector-nan?": vector_nan_p,
    "vector-fill-nan": vector_fill_nan,
    "vector-fill-forward": vector_fill_forward,
}


# ---------------------------------------------------------------------------
# Statistics -- each one skips missing values
# ---------------------------------------------------------------------------

def present_values(v, name):
    """v's numbers as a float64 numpy array, with missing values left out."""
    values = floats_of(v, name)
    return values[~np.isnan(values)]


def present_pairs(a, b, name):
    """Two vectors' numbers, keeping only positions where both are present."""
    x, y = floats_of(a, name), floats_of(b, name)
    check_lengths(name, x, y)
    keep = ~np.isnan(x) & ~np.isnan(y)
    return x[keep], y[keep]


def vector_sum(v):
    """(vector-sum v) -- the total of v's values."""
    values = numbers_of(v, "vector-sum")
    if np.issubdtype(values.dtype, np.integer):
        return int(values.sum())
    return float(np.nansum(values))


def vector_count(v):
    """(vector-count v) -- how many of v's elements aren't missing."""
    require_vector(v, "vector-count")
    return int((~missing_mask(v)).sum())


def vector_mean(v):
    """(vector-mean v) -- the average of v's values (NaN if there are none)."""
    values = present_values(v, "vector-mean")
    return float(values.mean()) if len(values) else float("nan")


def vector_median(v):
    """(vector-median v) -- the middle value of v (the average of the two
    middle values when there's an even number)."""
    values = present_values(v, "vector-median")
    return float(np.median(values)) if len(values) else float("nan")


def vector_variance(v, population=False):
    """(vector-variance v [population?]) -- the sample variance (dividing
    by n - 1), or the population variance (dividing by n) if population?
    is #t."""
    values = present_values(v, "vector-variance")
    ddof = 0 if is_true(population) else 1
    return float(values.var(ddof=ddof)) if len(values) > ddof else float("nan")


def vector_stdev(v, population=False):
    """(vector-stdev v [population?]) -- the standard deviation: the square
    root of vector-variance."""
    return math.sqrt(vector_variance(v, population))


def extreme(v, name, numeric_choice, python_choice):
    """The smallest or largest value: numbers compared as numbers; strings
    or dates (and missing values) handled in Python."""
    require_vector(v, name)
    if v.items.dtype != object:
        present = v.items[~missing_mask(v)]
        return _lisp_scalar(numeric_choice(present)) if len(present) else float("nan")
    values = [x for x in v.items.tolist() if x is not None]
    if not values:
        return NIL
    try:
        return python_choice(values)
    except TypeError:
        raise LispError("%s: the vector's values can't be compared with each other" % name)


def vector_quantile(v, q):
    """(vector-quantile v q) -- the value below which a fraction q of v's
    values fall (q between 0 and 1; 0.5 is the median), interpolating
    between values. q may also be a vector of fractions."""
    values = present_values(v, "vector-quantile")
    fractions = floats_of(q, "vector-quantile") if isinstance(q, LispVector) else float(q)
    if np.any((np.asarray(fractions) < 0) | (np.asarray(fractions) > 1)):
        raise LispError("vector-quantile: q must be between 0 and 1")
    if not len(values):
        return float("nan") if not isinstance(q, LispVector) else to_vector(np.full(len(fractions), np.nan))
    result = np.quantile(values, fractions)
    return to_vector(result) if isinstance(q, LispVector) else float(result)


def vector_weighted_mean(v, weights):
    """(vector-weighted-mean v weights) -- sum(v * w) / sum(w), e.g. a
    balance-weighted average rate."""
    x, w = present_pairs(v, weights, "vector-weighted-mean")
    total = w.sum()
    return float((x * w).sum() / total) if total != 0 else float("nan")


def vector_covariance(a, b, population=False):
    """(vector-covariance a b [population?]) -- the sample covariance of two
    vectors (dividing by n - 1), or the population covariance if #t."""
    x, y = present_pairs(a, b, "vector-covariance")
    ddof = 0 if is_true(population) else 1
    if len(x) <= ddof:
        return float("nan")
    return float(((x - x.mean()) * (y - y.mean())).sum() / (len(x) - ddof))


def vector_correlation(a, b):
    """(vector-correlation a b) -- the (Pearson) correlation of two vectors,
    between -1 and 1."""
    x, y = present_pairs(a, b, "vector-correlation")
    if len(x) < 2 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


STATISTICS_BUILTINS = {
    "vector-sum": vector_sum,
    "vector-count": vector_count,
    "vector-mean": vector_mean,
    "vector-median": vector_median,
    "vector-variance": vector_variance,
    "vector-stdev": vector_stdev,
    "vector-min": lambda v: extreme(v, "vector-min", np.min, min),
    "vector-max": lambda v: extreme(v, "vector-max", np.max, max),
    "vector-quantile": vector_quantile,
    "vector-weighted-mean": vector_weighted_mean,
    "vector-covariance": vector_covariance,
    "vector-correlation": vector_correlation,
}


# ---------------------------------------------------------------------------
# Time series: lags, differences, cumulative and rolling values
# ---------------------------------------------------------------------------
#
# These treat a vector as values in time order, one per period. For
# loan-level data -- many loans, each with its own run of months -- pass a
# `groups` vector (e.g. the loan id column): then a lag never reaches from
# one loan's rows into another's. The rows must be sorted by group, then
# by time, with one row per period.

def lagged_positions(length, n, groups, name):
    """For each position i, the position n periods earlier (i - n), and
    whether that position exists within the same group."""
    source = np.arange(length) - n
    valid = (source >= 0) & (source < length)
    if groups is not None and groups is not NIL:
        require_vector(groups, name)
        if len(groups.items) != length:
            raise LispError("%s: groups must be the same length as the vector" % name)
        codes, _ = factorize(groups.items)
        run = np.concatenate([[0], np.cumsum(codes[1:] != codes[:-1])])   # which block of rows
        clipped = np.clip(source, 0, max(length - 1, 0))
        valid &= run[clipped] == run
    return source, valid


def vector_lag(v, n=1, default=_NO_DEFAULT, groups=None):
    """(vector-lag v [n default groups]) -- each element's value n periods
    earlier (n defaults to 1; a negative n looks ahead). Where that would
    reach before the start of the vector -- or into another group -- the
    result is `default`, which is NaN if not given (or '() for a vector of
    strings or dates)."""
    require_vector(v, "vector-lag")
    length = len(v.items)
    source, valid = lagged_positions(length, int(n), groups, "vector-lag")
    if default is _NO_DEFAULT:
        default = NIL if v.items.dtype == object else float("nan")
    if v.items.dtype != object and is_number(default):
        values = numbers_of(v, "vector-lag")
        result = np.full(length, default, dtype=np.result_type(values.dtype, type(default)))
        result[valid] = values[source[valid]]
        return to_vector(result)
    result = np.empty(length, dtype=object)
    result[:] = default
    result[valid] = v.items.astype(object)[source[valid]]
    return LispVector(result)


def vector_diff(v, n=1, groups=None):
    """(vector-diff v [n groups]) -- each element minus its value n periods
    earlier; NaN where there's no earlier value."""
    values = floats_of(v, "vector-diff")
    earlier = floats_of(vector_lag(v, n, float("nan"), groups), "vector-diff")
    return to_vector(values - earlier)


def vector_pct_change(v, n=1, groups=None):
    """(vector-pct-change v [n groups]) -- the fractional change from n
    periods earlier: v / earlier - 1 (0.05 means up 5%)."""
    values = floats_of(v, "vector-pct-change")
    earlier = floats_of(vector_lag(v, n, float("nan"), groups), "vector-pct-change")
    with np.errstate(divide="ignore", invalid="ignore"):
        return to_vector(values / earlier - 1)


def vector_cumsum(v):
    """(vector-cumsum v) -- running totals: element i is the sum of elements
    0..i. Missing values count as 0 but stay missing in the result."""
    values = numbers_of(v, "vector-cumsum")
    if np.issubdtype(values.dtype, np.integer):
        return to_vector(np.cumsum(values))
    result = np.nancumsum(values)
    result[np.isnan(values)] = np.nan
    return to_vector(result)


def vector_cumprod(v):
    """(vector-cumprod v) -- running products: element i is the product of
    elements 0..i -- e.g. survival from monthly survival rates, or discount
    factors. Missing values count as 1 but stay missing in the result."""
    values = floats_of(v, "vector-cumprod")
    result = np.nancumprod(values)
    result[np.isnan(values)] = np.nan
    return to_vector(result)


def rolling(name, v, window, reduce):
    values = floats_of(v, name)
    window = int(window)
    if window < 1:
        raise LispError("%s: window must be at least 1" % name)
    result = np.full(len(values), np.nan)
    if len(values) >= window:
        windows = np.lib.stride_tricks.sliding_window_view(values, window)
        result[window - 1:] = reduce(windows, axis=1)
    return to_vector(result)


def vector_range(start, end=None, step=1):
    """(vector-range end) or (vector-range start end [step]) -- the numbers
    from start (default 0) up to, but not including, end."""
    if end is None:
        start, end = 0, start
    if step == 0:
        raise LispError("vector-range: step can't be 0")
    return to_vector(np.arange(start, end, step))


def vector_unique(v):
    """(vector-unique v) -- v's distinct values, sorted."""
    require_vector(v, "vector-unique")
    _, distinct = factorize(v.items)
    return LispVector(distinct)


TIME_SERIES_BUILTINS = {
    "vector-lag": vector_lag,
    "vector-diff": vector_diff,
    "vector-pct-change": vector_pct_change,
    "vector-cumsum": vector_cumsum,
    "vector-cumprod": vector_cumprod,
    "vector-rolling-mean": lambda v, window: rolling("vector-rolling-mean", v, window, np.mean),
    "vector-rolling-sum": lambda v, window: rolling("vector-rolling-sum", v, window, np.sum),
    "vector-range": vector_range,
    "vector-unique": vector_unique,
}


BUILTINS = {}
BUILTINS.update(ARITHMETIC_BUILTINS)
BUILTINS.update(COMPARISON_BUILTINS)
BUILTINS.update(STATISTICS_BUILTINS)
BUILTINS.update(TIME_SERIES_BUILTINS)
