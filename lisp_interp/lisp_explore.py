"""Exploring a table you have not seen before: table-profile, table-missing and table-outliers.

table-describe (lisp_tables.py) summarizes the numeric columns. These look at every column and at what is wrong with
the data -- what is missing, and where, and what is far from the rest:

  table-profile   a row for each column: its kind, how much is missing, how many distinct values, its range
  table-missing   which columns are missing together: a row for each pattern of missing values
  table-outliers  the lowest and highest values of each numeric column, and how far they are from the rest
"""

from collections import Counter

import numpy as np

from lisp_core import LispDate, LispError, LispString, LispVector, NIL, keyword_options
from lisp_stratify import is_date_column, is_numeric_column, table_column, value_text
from lisp_tables import make_table_value, row_count, table_columns
from lisp_vector_math import floats_of, missing_mask


def kind_of(v, present):
    """What a column holds: number, date, text, or mixed (several kinds, or truth values)."""
    if is_numeric_column(v):
        return "number"
    if is_date_column(v):
        return "date"
    if present.size and all(isinstance(x, str) for x in present.tolist()):
        return "text"
    return "mixed"


def most_common(present):
    """The value that occurs most often among the values that are not missing (the first of any that tie), as text;
    empty if there are none."""
    if present.size == 0:
        return ""
    counts = Counter(present.tolist())
    value, _ = max(counts.items(), key=lambda item: item[1])      # max keeps the first of equal counts
    return value_text(value)


def range_text(present):
    """For values that are not numbers: "lowest to highest", as text (empty if there are none). Dates are in date
    order and text is in alphabetical order."""
    values = present.tolist()
    if not values:
        return ""
    try:
        low, high = min(values), max(values)
    except TypeError:                       # several kinds of value cannot be put in order
        return ""
    if isinstance(low, LispDate):
        low, high = min(values, key=lambda d: d.date), max(values, key=lambda d: d.date)
    return "%s to %s" % (value_text(low), value_text(high))


def table_profile(table):
    """(table-profile table) -- a table with a row for each column of the table: its kind (number, date, text, or mixed),
    how many values are missing, how many different values it has, for a number its mean, smallest, median and
    largest, for anything else its range from the lowest to the highest, and its most common value."""
    columns = table_columns(table, "table-profile")
    rows = {name: [] for name in ("column", "kind", "missing", "distinct", "mean", "min", "median", "max", "range",
                                  "most common")}
    for name, v in columns:
        missing = missing_mask(v)
        present = v.items[~missing]
        kind = kind_of(v, present)
        numbers = floats_of(LispVector(present), "table-profile") if kind == "number" and present.size else None
        rows["column"].append(LispString(name))
        rows["kind"].append(LispString(kind))
        rows["missing"].append(int(missing.sum()))
        rows["distinct"].append(len(set(present.tolist())))
        for label, summary in (("mean", np.mean), ("min", np.min), ("median", np.median), ("max", np.max)):
            rows[label].append(float(summary(numbers)) if numbers is not None else float("nan"))
        rows["range"].append(LispString(range_text(present) if kind != "number" else ""))
        rows["most common"].append(LispString(most_common(present)))
    return make_table_value([(label, table_column(values)) for label, values in rows.items()])


def table_missing(table):
    """(table-missing table) -- which columns are missing together: a table with a row for each pattern of missing values
    that occurs, the most common first. `missing` names the columns that are missing in those rows ("none" for the rows
    that are complete), `rows` is how many rows have just that pattern, and `percent` is their share of the table."""
    columns = table_columns(table, "table-missing")
    n = row_count(columns)
    if n == 0:
        raise LispError("table-missing: the table has no rows")
    masks = np.array([missing_mask(v) for _, v in columns], dtype=bool).reshape(len(columns), n).T
    patterns, first_row, counts = np.unique(masks, axis=0, return_index=True, return_counts=True)
    order = sorted(range(len(counts)), key=lambda i: (-counts[i], first_row[i]))
    names = [name for name, _ in columns]
    texts = [", ".join(name for name, gone in zip(names, patterns[i]) if gone) or "none" for i in order]
    return make_table_value([
        ("missing", LispVector([LispString(t) for t in texts])),
        ("rows", LispVector([int(counts[i]) for i in order])),
        ("percent", table_column([counts[i] / n for i in order])),
    ])


def table_outliers(table, *options):
    """(table-outliers table [:count n]) -- the n lowest and the n highest values (5, unless :count says) of each numeric
    column, as a table with a row for each: its `column`, its `side` (low or high), its `row` in the table (counting from
    0), its `value`, and its `spread`: how far the value is from the column's median, in interquartile ranges (the
    distance from the 25th percentile to the 75th). A spread over 3 is far from the rest; nan when the column's
    quartiles are the same."""
    columns = table_columns(table, "table-outliers")
    count = keyword_options(options, ("count",), "table-outliers").get("count", 5)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise LispError("table-outliers: :count is how many low and high values to show for each column, a whole number "
                        "of 1 or more")
    rows = {name: [] for name in ("column", "side", "row", "value", "spread")}
    for name, v in columns:
        if not is_numeric_column(v):
            continue
        values = floats_of(v, "table-outliers")
        present = np.where(~np.isnan(values))[0]
        if present.size == 0:
            continue
        order = present[np.argsort(values[present], kind="stable")]         # row numbers, lowest value first
        low_quartile, median, high_quartile = np.percentile(values[present], [25, 50, 75])
        iqr = high_quartile - low_quartile
        lows = order[:count]
        already_low = set(lows.tolist())
        highs = [r for r in order[::-1][:count] if r not in already_low]            # biggest first; not in both
        for side, chosen in (("low", lows), ("high", highs)):
            for r in chosen:
                rows["column"].append(LispString(name))
                rows["side"].append(LispString(side))
                rows["row"].append(int(r))
                rows["value"].append(float(values[r]))
                rows["spread"].append(float((values[r] - median) / iqr) if iqr > 0 else float("nan"))
    return make_table_value([(label, table_column(column)) for label, column in rows.items()])


BUILTINS = {
    "table-profile": table_profile,
    "table-missing": table_missing,
    "table-outliers": table_outliers,
}
