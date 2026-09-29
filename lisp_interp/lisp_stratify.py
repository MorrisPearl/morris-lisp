"""Stratification tables for the Lisp interpreter: stratify and stratify-all.

A STRATIFICATION of a big table (loans, say) is a small table with one row
per bucket of some column -- coupons from 3.0 to 5.0, 5.0 to 6.0, ...; ten
buckets of loan age with the same number of loans in each; one row per
state -- and, in each row, a summary of the loans in that bucket: how many
there are, their total balance and its share of the whole, and a summary of
each other column, usually its balance-weighted average. A last row gives
the same for the whole table.

stratify makes one such table; stratify-all makes one for each of a list of
ways of bucketing, from the same summaries. Rows go into buckets by
column: `how` says how --

  (3.0 5.0 6.0 7.0)   breakpoints: under 3.0, 3.0 to 5.0 (3.0 or more but
                      under 5.0), 5.0 to 6.0, 6.0 to 7.0, 7.0 and over
  (equal-count n)     n buckets with the same number of rows in each
  (equal-weight n)    n buckets with the same total weight in each
  (top n)             the n values with the most weight (or rows, with no
                      weight), then all the others as one bucket, "other"
  each                one bucket per distinct value
  year                one bucket per calendar year (for a column of dates)

A row whose value is missing (NaN, or '()) goes in a last bucket,
"missing". A bucket with no rows isn't shown. The summaries are done the way
table-group-by does them (see lisp_tables.aggregate), so they skip missing
values too.
"""

import numpy as np

from lisp_core import (
    Keyword, LispDate, LispError, LispString, LispVector, NIL, Pair, Symbol,
    _brief, _lisp_scalar, is_true, list_to_pairs, pairs_to_list, to_display_string,
)
from lisp_tables import aggregate, find_column, make_table_value, row_count, table_columns
from lisp_vector_math import factorize, floats_of, is_number, missing_mask, to_vector


# ---------------------------------------------------------------------------
# Putting rows in buckets
# ---------------------------------------------------------------------------
#
# Each way of bucketing gives every row a bucket number -- 0, 1, 2, ... in
# the order the buckets are to be shown -- and gives each bucket a label.
# Missing values get the number after the last bucket, labelled "missing".

MISSING = LispString("missing")


def is_date_column(v):
    """Whether the vector holds dates (and perhaps missing values)."""
    return v.items.dtype == object and any(isinstance(x, LispDate) for x in v.items.tolist())


def as_number(x):
    """A number, or a date as its day number, or NaN for a missing value."""
    if x is None:
        return np.nan
    return x.date.toordinal() if isinstance(x, LispDate) else x


def as_numbers(v, who):
    """A vector's values as float64 numbers: a date as its day number, a
    missing value as NaN."""
    if is_date_column(v):
        return np.array([as_number(x) for x in v.items.tolist()], dtype=np.float64)
    return floats_of(v, who)


def value_text(x):
    """A breakpoint or a value from a column (a number or a date), as text for
    a label: a number as display shows it, so 3.99 from a column of float32
    numbers is 3.99, not 3.990000009536743."""
    return str(to_display_string(_lisp_scalar(x)))


def with_missing_bucket(numbers, labels, missing):
    """Put the rows marked missing in a bucket of their own, after the rest."""
    if missing.any():
        numbers = numbers.copy()
        numbers[missing] = len(labels)
        labels = labels + [MISSING]
    return numbers, labels


def buckets_from_breakpoints(values, breakpoints):
    """under b1, b1 to b2, ..., bn and over. The breakpoints are numbers, or
    dates (for a column of dates)."""
    by_edge = {as_number(b): b for b in breakpoints}
    edges = sorted(by_edge)
    texts = [value_text(by_edge[e]) for e in edges]
    labels = ([LispString("under %s" % texts[0])] +
              [LispString("%s to %s" % (a, b)) for a, b in zip(texts, texts[1:])] +
              [LispString("%s and over" % texts[-1])])
    missing = np.isnan(values)
    numbers = np.searchsorted(edges, np.where(missing, 0.0, values), side="right")
    return with_missing_bucket(numbers, labels, missing)


def buckets_of_equal_size(v, values, weights, n):
    """n buckets holding the same number of rows, or (given weights) the same
    total weight. `values` are the vector v's values as numbers. The cuts fall
    between values, so rows with the same value are always in the same
    bucket; a bucket that ends up empty isn't shown."""
    missing = np.isnan(values)
    present = np.where(~missing)[0]
    order = present[np.argsort(values[present], kind="stable")]
    sorted_values = values[order]
    if weights is None:
        cut_positions = [round(len(order) * i / n) for i in range(1, n)]
    else:
        cumulative = np.cumsum(np.nan_to_num(weights[order]))
        cut_positions = [int(np.searchsorted(cumulative, cumulative[-1] * i / n, side="right"))
                         for i in range(1, n)]
    cuts = sorted(set(sorted_values[p] for p in cut_positions if 0 < p < len(order)))
    numbers = np.searchsorted(cuts, np.where(missing, 0.0, values), side="right")
    bucket_of_sorted = np.searchsorted(cuts, sorted_values, side="right")
    labels = []
    for b in range(len(cuts) + 1):
        rows = order[bucket_of_sorted == b]         # smallest value first
        if len(rows):
            labels.append(LispString("%s to %s" % (value_text(v.items[rows[0]]), value_text(v.items[rows[-1]]))))
        else:
            labels.append(LispString(""))       # an empty bucket: never shown
    return with_missing_bucket(numbers, labels, missing)


def buckets_for_each_value(v):
    """One bucket per distinct value, in order (see factorize)."""
    codes, distinct = factorize(v.items)
    labels = [_lisp_scalar(x) for x in distinct]      # a missing value's label is never shown
    return with_missing_bucket(codes, labels, missing_mask(v))


def buckets_for_top_values(v, weights, n):
    """The n values with the most weight (or rows), biggest first, then the
    rest as "other"."""
    codes, distinct = factorize(v.items)
    missing = missing_mask(v)
    totals = np.bincount(codes[~missing], minlength=len(distinct),
                         weights=None if weights is None else np.nan_to_num(weights[~missing]))
    top = [i for i in np.argsort(-totals, kind="stable")[:n] if totals[i] > 0]
    rank = np.full(len(distinct), len(top))             # a value not in the top: "other"
    rank[top] = np.arange(len(top))
    labels = [_lisp_scalar(distinct[i]) for i in top] + [LispString("other")]
    return with_missing_bucket(rank[codes], labels, missing)


def buckets_for_each_year(v, column_name):
    """One bucket per calendar year, for a column of dates."""
    if not is_date_column(v):
        raise LispError("stratify: bucketing %s by year needs a column of dates" % column_name)
    missing = missing_mask(v)
    years = np.array([0 if x is None else x.date.year for x in v.items.tolist()])
    labels = sorted(set(years[~missing].tolist()))
    numbers = np.searchsorted(labels, years)
    return with_missing_bucket(numbers, labels, missing)


def bucket_rows(columns, spec, weights):
    """For one (column how) spec: (column name, each row's bucket number, the
    buckets' labels)."""
    parts = pairs_to_list(spec) if isinstance(spec, Pair) else []
    if len(parts) != 2:
        raise LispError("stratify: each way of bucketing is (column how), such as "
                        "(\"rate\" (3 5 6 7)) or (\"state\" (top 10)) -- not %s" % (_brief(spec),))
    column_name, how = str(parts[0]), parts[1]
    v = find_column(columns, column_name, "stratify")
    if isinstance(how, Symbol) and str(how) == "each":
        return column_name, *buckets_for_each_value(v)
    if isinstance(how, Symbol) and str(how) == "year":
        return column_name, *buckets_for_each_year(v, column_name)
    how_parts = pairs_to_list(how) if isinstance(how, Pair) else []
    if how_parts and all(is_number(x) or isinstance(x, LispDate) for x in how_parts):
        return column_name, *buckets_from_breakpoints(as_numbers(v, "stratify"), how_parts)
    if len(how_parts) == 2 and isinstance(how_parts[0], Symbol) and is_number(how_parts[1]) \
            and str(how_parts[0]) in ("equal-count", "equal-weight", "top") and how_parts[1] >= 1:
        kind, n = str(how_parts[0]), int(how_parts[1])
        if kind == "top":
            return column_name, *buckets_for_top_values(v, weights, n)
        if kind == "equal-weight" and weights is None:
            raise LispError("stratify: equal-weight buckets need a weight -- give :weight \"column\"")
        return column_name, *buckets_of_equal_size(v, as_numbers(v, "stratify"),
                                                    weights if kind == "equal-weight" else None, n)
    raise LispError("stratify: can't bucket %s by %s -- use a list of breakpoints, (equal-count n), "
                    "(equal-weight n), (top n), each, or year" % (column_name, _brief(how)))


# ---------------------------------------------------------------------------
# The summaries
# ---------------------------------------------------------------------------

SUMMARY_FUNCTIONS = ("sum", "mean", "weighted-mean", "min", "max", "median", "stdev", "first", "last")


def summary_specs(columns, summaries, weight_vector):
    """The summaries, (column function [heading]), as (heading, function,
    column vector) tuples. The heading is "column (function)" unless given."""
    specs = []
    for spec in pairs_to_list(summaries):
        parts = pairs_to_list(spec) if isinstance(spec, Pair) else []
        if len(parts) not in (2, 3):
            raise LispError("stratify: each summary is (column function [heading]), such as "
                            "(\"rate\" weighted-mean \"WAC\") -- not %s" % (_brief(spec),))
        column_name, function = str(parts[0]), str(parts[1])
        if function not in SUMMARY_FUNCTIONS:
            raise LispError("stratify: %s isn't a summary -- use one of %s"
                            % (function, ", ".join(SUMMARY_FUNCTIONS)))
        if function == "weighted-mean" and weight_vector is None:
            raise LispError("stratify: a weighted-mean needs a weight -- give :weight \"column\"")
        heading = str(parts[2]) if len(parts) == 3 else "%s (%s)" % (column_name, function)
        specs.append((heading, function, find_column(columns, column_name, "stratify")))
    return specs


def keyword_options(options, allowed, who):
    """A builtin's trailing :name value arguments, as a dict (name -> value)."""
    if len(options) % 2:
        raise LispError("%s: after the first arguments come :name value pairs, such as :weight \"balance\"" % who)
    result = {}
    for name, value in zip(options[::2], options[1::2]):
        key = str(name)[1:] if isinstance(name, Keyword) else None
        if key not in allowed:
            raise LispError("%s: %s isn't an option -- the options are %s"
                            % (who, _brief(name), ", ".join(":" + a for a in allowed)))
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# stratify and stratify-all
# ---------------------------------------------------------------------------

def group_by_bucket(bucketings):
    """Group the rows by their buckets -- by the combination of their
    buckets, with several columns -- in the buckets' order, leaving out
    combinations with no rows. Returns (order, starts, counts, numbers), as
    lisp_tables.group_rows does: `order` lists the row numbers group by
    group, each group starting at `starts` and `counts` long; and `numbers`
    has, for each column, each group's bucket number."""
    combined = np.zeros(len(bucketings[0][1]), dtype=np.int64)
    for _, numbers, labels in bucketings:                # like digits: a number per combination
        combined = combined * (len(labels) + 1) + numbers
    groups, group_of_row, counts = np.unique(combined, return_inverse=True, return_counts=True)
    order = np.argsort(group_of_row.reshape(-1), kind="stable")
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.int64)
    numbers = []
    for _, _, labels in reversed(bucketings):            # take the digits back apart
        numbers.insert(0, (groups % (len(labels) + 1)).tolist())
        groups = groups // (len(labels) + 1)
    return order, starts, counts, numbers


def full_precision(values):
    """A numpy result as a vector of double-precision numbers. A
    stratification table has only a few rows, so there's no memory to save by
    storing its numbers in 32 bits, as big vectors are, and this way a total
    balance comes out to the dollar."""
    values = np.asarray(values)
    if np.issubdtype(values.dtype, np.floating):
        return LispVector(values.astype(np.float64))
    return to_vector(values)


def table_column(values):
    """A column of the stratification table, from a Python list: numbers with
    a fraction in double precision (see full_precision); anything else as
    any vector stores it."""
    if values and all(is_number(x) for x in values) and any(isinstance(x, float) for x in values):
        return LispVector(np.array(values, dtype=np.float64))
    return LispVector(values)


def stratify_table(columns, by, specs, weight_name, weight_vector, with_total):
    """One stratification table (see the top of this file)."""
    weights = None if weight_vector is None else floats_of(weight_vector, "stratify")
    one_column = isinstance(by, Pair) and not isinstance(by.car, Pair)
    bucketings = [bucket_rows(columns, spec, weights) for spec in ([by] if one_column else pairs_to_list(by))]
    if not bucketings:
        raise LispError("stratify: say how to bucket the rows: (column how), or a list of them")

    n = row_count(columns)
    if n == 0:
        raise LispError("stratify: the table has no rows")
    order, starts, counts, bucket_numbers = group_by_bucket(bucketings)
    everything = (np.arange(n), np.array([0]), np.array([n]))     # the whole table as one group
    result = []
    for (column_name, _, labels), numbers in zip(bucketings, bucket_numbers):
        label_column = [labels[b] for b in numbers]
        if with_total:
            label_column.append(LispString("total") if not result else LispString(""))
        result.append((column_name, label_column))

    count_column = list(counts) + ([n] if with_total else [])
    result.append(("count", [int(c) for c in count_column]))
    if weight_vector is not None:
        bucket_weights = aggregate("sum", weight_vector, None, order, starts, counts, full_precision)
        amounts = [_lisp_scalar(x) for x in bucket_weights.items]
        total_weight = float(np.nansum(weights))
        shares = [a / total_weight if total_weight else float("nan") for a in amounts]
        result.append(("total " + weight_name, amounts + ([total_weight] if with_total else [])))
        result.append(("percent", shares + ([1.0] if with_total else [])))
    else:
        result.append(("percent", [c / n for c in counts] + ([1.0] if with_total else [])))

    for heading, function, column in specs:
        values = [_lisp_scalar(x) for x in
                  aggregate(function, column, weight_vector, order, starts, counts, full_precision).items]
        if with_total:
            values += [_lisp_scalar(x) for x in
                       aggregate(function, column, weight_vector, *everything, full_precision).items]
        result.append((heading, values))

    headings = [heading for heading, _ in result]
    repeated = sorted({h for h in headings if headings.count(h) > 1})
    if repeated:
        raise LispError("stratify: two columns would both be called %s -- give a summary a heading "
                        "of its own: (column function \"heading\")" % ", ".join(repeated))
    return make_table_value([(heading, table_column(values)) for heading, values in result])


def stratify_options(table, summaries, options, who):
    """What stratify and stratify-all share: the table's columns, the
    summaries, the weight column (name and vector, or None), and whether to
    add a total row."""
    columns = table_columns(table, who)
    chosen = keyword_options(options, ("weight", "total"), who)
    weight_name = None if chosen.get("weight", NIL) is NIL else str(chosen["weight"])
    weight_vector = None if weight_name is None else find_column(columns, weight_name, who)
    specs = summary_specs(columns, summaries, weight_vector)
    return columns, specs, weight_name, weight_vector, is_true(chosen.get("total", True))


def stratify(table, by, summaries=NIL, *options):
    """(stratify table by summaries [:weight column] [:total #f]) -- one
    stratification table: a row per bucket, and a last row for the whole
    table (unless :total is #f). `by` is (column how) -- see the top of this
    file for `how` -- or a list of them, for a row per combination of
    buckets. The columns are the bucket(s); count; with :weight, the total
    weight ("total balance", for :weight "balance") and its share of the
    table's ("percent"; without :weight, the share of the rows); then one
    per summary, (column function [heading]), where
    function is sum, mean, weighted-mean (by the :weight column), min, max,
    median, stdev, first, or last."""
    columns, specs, weight_name, weight_vector, with_total = stratify_options(table, summaries, options, "stratify")
    return stratify_table(columns, by, specs, weight_name, weight_vector, with_total)


def stratify_all(table, bys, summaries=NIL, *options):
    """(stratify-all table bys summaries [:weight column] [:total #f]) -- a
    list of stratification tables, one for each `by` in the list bys, all
    with the same summaries (see stratify)."""
    columns, specs, weight_name, weight_vector, with_total = stratify_options(table, summaries, options,
                                                                               "stratify-all")
    return list_to_pairs([stratify_table(columns, by, specs, weight_name, weight_vector, with_total)
                          for by in pairs_to_list(bys)])


BUILTINS = {
    "stratify": stratify,
    "stratify-all": stratify_all,
}
