"""Tables for the Lisp interpreter: select, filter, sort, group, join, and
summarize rows of data.

A TABLE is a list of (name . vector) columns, all the same length -- the
shape sqlite-query, load-csv, and tastytrade-option-chain return, and
display-table and write-columns-csv accept. There's no separate table
type: a table is ordinary Lisp data, so (car table) is its first column
and (table-column table "balance") is the vector named "balance".
table-rows gives the same data a row at a time (see "Rows", below).

Every function returns a new table and leaves its argument unchanged.
Rows are picked out with MASKS -- vectors of 1 and 0 made by comparing
vectors, e.g.
    (table-filter loans (> (table-column loans "balance") 100000))
All the work is done with numpy on whole columns, so tables of millions
of rows are practical.
"""

import numpy as np

from lisp_core import (
    LispDate, LispError, LispString, LispStruct, LispStructType, LispVector, NIL, Pair, Symbol,
    _brief, _lisp_scalar, is_true, list_to_pairs, pairs_to_list,
)
from lisp_vector_math import factorize, floats_of, is_number, to_vector, truth_of


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def table_columns(table, name):
    """A table as a Python list of (column_name, LispVector) pairs, after
    checking it is one: a list of (name . vector), all the same length."""
    if not (table is NIL or isinstance(table, Pair)):
        raise LispError("%s: not a table -- a table is a list of (name . vector) columns, not %s"
                        % (name, _brief(table)))
    columns = []
    for entry in pairs_to_list(table):
        if not (isinstance(entry, Pair) and isinstance(entry.cdr, LispVector)):
            raise LispError("%s: not a table -- a table is a list of (name . vector) columns" % name)
        columns.append((str(entry.car), entry.cdr))
    lengths = sorted({len(v.items) for _, v in columns})
    if len(lengths) > 1:
        raise LispError("%s: the table's columns have different lengths: %s"
                        % (name, ", ".join(str(n) for n in lengths)))
    return columns


def make_table_value(columns):
    """A Lisp table from a Python list of (column_name, LispVector) pairs."""
    return list_to_pairs([Pair(LispString(n), v) for n, v in columns])


def row_count(columns):
    return len(columns[0][1].items) if columns else 0


def names_argument(names, name):
    """A column-names argument -- one name, or a list of names -- as a
    Python list of strings."""
    if isinstance(names, str):
        return [str(names)]
    if names is NIL or isinstance(names, Pair):
        result = [str(n) for n in pairs_to_list(names)]
        if not result:
            raise LispError("%s: expected at least one column name" % name)
        return result
    raise LispError("%s: expected a column name or a list of column names" % name)


def find_column(columns, column_name, name):
    for n, v in columns:
        if n == column_name:
            return v
    raise LispError("%s: no column named %r (the columns are: %s)"
                    % (name, column_name, ", ".join(n for n, _ in columns)))


def take_rows(columns, index):
    """The rows at positions `index` (a numpy array of row numbers)."""
    return [(n, LispVector(v.items[index])) for n, v in columns]


def take_with_missing(v, index):
    """v's values at positions `index`, where -1 means "no row": missing
    there (NaN for numbers, '() for strings and dates)."""
    missing = index < 0
    if not missing.any():
        return LispVector(v.items[index])
    if v.items.dtype != object:
        values = np.full(len(index), np.nan)
        values[~missing] = v.items[index[~missing]]
        return to_vector(values)
    values = np.empty(len(index), dtype=object)
    values[:] = None
    values[~missing] = v.items[index[~missing]]
    return LispVector(values)


def symbol_argument(x):
    """A symbol-or-string option such as 'left or "left", as a string."""
    return str(x).lower()


# ---------------------------------------------------------------------------
# Building and looking at tables
# ---------------------------------------------------------------------------

def make_table(*names_and_vectors):
    """(make-table name1 vector1 name2 vector2 ...) -- a table from
    alternating column names and vectors."""
    if len(names_and_vectors) % 2 != 0:
        raise LispError("make-table: expected name vector pairs, but got an odd number of arguments")
    columns = []
    for i in range(0, len(names_and_vectors), 2):
        column_name, vector = names_and_vectors[i], names_and_vectors[i + 1]
        if not isinstance(vector, LispVector):
            raise LispError("make-table: the value for column %s isn't a vector" % (column_name,))
        columns.append((str(column_name), vector))
    table = make_table_value(columns)
    table_columns(table, "make-table")      # checks that the columns are the same length
    return table


def is_table(x):
    """(table? x) -- #t if x is a table: a list of (name . vector) columns,
    all the same length."""
    try:
        table_columns(x, "table?")
        return x is NIL or isinstance(x, Pair)
    except LispError:
        return False


def table_head(table, n=10):
    """(table-head table [n]) -- the first n rows (default 10)."""
    columns = table_columns(table, "table-head")
    return make_table_value([(name, LispVector(v.items[:int(n)])) for name, v in columns])


def table_slice(table, start, end=None):
    """(table-slice table start [end]) -- rows start up to, but not
    including, end (default: to the last row)."""
    columns = table_columns(table, "table-slice")
    stop = None if end is None or end is NIL else int(end)
    return make_table_value([(name, LispVector(v.items[int(start):stop])) for name, v in columns])


LOOKING_BUILTINS = {
    "make-table": make_table,
    "table?": is_table,
    "table-column-names": lambda t: list_to_pairs([LispString(n) for n, _ in table_columns(t, "table-column-names")]),
    "table-column": lambda t, column: find_column(table_columns(t, "table-column"), str(column), "table-column"),
    "table-row-count": lambda t: row_count(table_columns(t, "table-row-count")),
    "table-head": table_head,
    "table-slice": table_slice,
}


# ---------------------------------------------------------------------------
# Rows: a table seen one row at a time
# ---------------------------------------------------------------------------
#
# A table is stored as columns, which suits formulas over whole columns,
# such as (* balance rate). Some data is better seen a row at a time: each
# option in an option chain is a thing of its own. table-rows gives each row
# as a ROW, a struct whose slots are the table's columns, so
# (row-ref option "strike") reads one value, and (with-struct option ...)
# makes each column a variable. table-from-rows turns rows back into a
# table.

def row_type(column_names):
    """The struct type of a table's rows: one slot for each column, named
    after it. Rows print as #S(row :strike 450.0 ...)."""
    return LispStructType(Symbol("row"), [(Symbol(n), None) for n in column_names])


def column_values(v):
    """A column's values, as a Python list of Lisp values."""
    return [_lisp_scalar(x) for x in v.items]


def table_rows(table):
    """(table-rows table) -- the table's rows, in order, as a list of rows."""
    columns = table_columns(table, "table-rows")
    kind = row_type([n for n, _ in columns])
    slots = [Symbol(n) for n, _ in columns]
    values_by_column = [column_values(v) for _, v in columns]
    return list_to_pairs([LispStruct(kind, dict(zip(slots, values)))
                          for values in zip(*values_by_column)])


def table_row(table, i):
    """(table-row table i) -- row i (counting from 0), as a row."""
    columns = table_columns(table, "table-row")
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < row_count(columns):
        raise LispError("table-row: there's no row %s -- the table has %d rows"
                        % (_brief(i), row_count(columns)))
    kind = row_type([n for n, _ in columns])
    return LispStruct(kind, {Symbol(n): _lisp_scalar(v.items[i]) for n, v in columns})


def struct_value(row, column_name, who):
    """The value in `row`'s column (slot) called column_name."""
    if not isinstance(row, LispStruct):
        raise LispError("%s: not a row: %s" % (who, _brief(row)))
    slot = Symbol(column_name)
    if slot not in row.values:
        raise LispError("%s: the row has no column %s -- its columns are %s"
                        % (who, column_name, ", ".join(str(s) for s, _ in row.struct_type.slots)))
    return row.values[slot]


def row_ref(row, column_name):
    """(row-ref row name) -- the value in the row's column called name (a
    string or a symbol)."""
    return struct_value(row, str(column_name), "row-ref")


def check_table_value(value, column_name, who):
    """A table holds numbers, strings, and dates, and '() for a missing value."""
    if value is None or is_number(value) or isinstance(value, (LispString, LispDate)):
        return
    raise LispError("%s: a table holds numbers, strings, and dates, not %s (in column %s)"
                    % (who, _brief(value), column_name))


def table_from_rows(rows, names=NIL):
    """(table-from-rows rows [names]) -- a table made from a list of rows.
    Each row is a row from table-rows or table-row (or any struct), whose
    slots become the columns -- or a list of values, one per column, with
    the column names given as `names`. Given names, rows that are structs
    keep just those columns, in that order. A column of numbers with '() in
    it holds NaN there, as a column read from a CSV file would."""
    who = "table-from-rows"
    row_list = pairs_to_list(rows)
    column_names = None if names is NIL else [str(n) for n in pairs_to_list(names)]
    if not row_list:
        return make_table_value([(n, LispVector([])) for n in column_names or []])
    if isinstance(row_list[0], LispStruct):
        if column_names is None:
            column_names = [str(slot) for slot, _ in row_list[0].struct_type.slots]
        values_by_column = [[struct_value(row, n, who) for row in row_list] for n in column_names]
    else:
        if column_names is None:
            raise LispError("%s: these rows are lists, so give the column names: "
                            "(table-from-rows rows names)" % who)
        values_by_column = [[] for _ in column_names]
        for row in row_list:
            if not (row is NIL or isinstance(row, Pair)):
                raise LispError("%s: a row must be a row (a struct) or a list, not %s" % (who, _brief(row)))
            values = pairs_to_list(row)
            if len(values) != len(column_names):
                raise LispError("%s: the row %s has %d values, but there are %d column names"
                                % (who, _brief(row), len(values), len(column_names)))
            for column, value in zip(values_by_column, values):
                column.append(value)
    for n, values in zip(column_names, values_by_column):
        for value in values:
            check_table_value(value, n, who)
    return make_table_value([(n, column_vector(values)) for n, values in zip(column_names, values_by_column)])


def table_or_rows(data, who):
    """data as a table: a table as it is, or a list of rows (structs) made
    into one with table-from-rows."""
    if isinstance(data, Pair) and isinstance(data.car, LispStruct):
        return table_from_rows(data)
    table_columns(data, who)        # an error, if it isn't a table either
    return data


ROW_VIEW_BUILTINS = {
    "table-rows": table_rows,
    "table-row": table_row,
    "row-ref": row_ref,
    "table-from-rows": table_from_rows,
}


def parse_iso_date(text):
    """text as a LispDate if it's exactly YYYY-MM-DD, otherwise None."""
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return LispDate(int(text[:4]), int(text[5:7]), int(text[8:]))
    except ValueError:
        return None


def column_vector(values):
    """A column's values (a Python list of Lisp values, with None -- '() --
    for a missing one) as a vector, read the way load-csv reads a CSV
    column: if every value that isn't missing is a number, a numeric vector
    with NaN for the missing ones; if every one is YYYY-MM-DD text, a vector
    of dates (SQLite has no date type, so sqlite-write-table stores dates
    that way); otherwise the values as they are, with '() for the missing
    ones. Used for query results, table-from-rows, and the option chain."""
    present = [v for v in values if v is not None]
    if present and len(present) < len(values) and \
            all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return LispVector([float("nan") if v is None else v for v in values])
    if present and all(isinstance(v, str) for v in present):
        dates = [parse_iso_date(v) for v in present]
        if all(d is not None for d in dates):
            return LispVector([None if v is None else parse_iso_date(v) for v in values])
    return LispVector(values)


# ---------------------------------------------------------------------------
# Choosing and changing columns
# ---------------------------------------------------------------------------

def table_select(table, names):
    """(table-select table names) -- just the named columns, in the order
    given."""
    columns = table_columns(table, "table-select")
    return make_table_value([(n, find_column(columns, n, "table-select"))
                             for n in names_argument(names, "table-select")])


def table_drop_columns(table, names):
    """(table-drop-columns table names) -- every column except the named ones."""
    columns = table_columns(table, "table-drop-columns")
    drop = names_argument(names, "table-drop-columns")
    for n in drop:
        find_column(columns, n, "table-drop-columns")
    return make_table_value([(n, v) for n, v in columns if n not in drop])


def table_add_column(table, column_name, values):
    """(table-add-column table name values) -- the table with a column
    added at the end, or replaced if it already has one by that name.
    values is a vector with one value per row, or a single value to use in
    every row."""
    columns = table_columns(table, "table-add-column")
    n_rows = row_count(columns)
    if isinstance(values, LispVector):
        if columns and len(values.items) != n_rows:
            raise LispError("table-add-column: the table has %d rows, but the vector has %d values"
                            % (n_rows, len(values.items)))
        vector = values
    else:
        vector = LispVector([values] * n_rows)
    column_name = str(column_name)
    if any(n == column_name for n, _ in columns):
        return make_table_value([(n, vector if n == column_name else v) for n, v in columns])
    return make_table_value(columns + [(column_name, vector)])


def table_rename_column(table, old_name, new_name):
    """(table-rename-column table old new) -- the table with one column renamed."""
    columns = table_columns(table, "table-rename-column")
    find_column(columns, str(old_name), "table-rename-column")
    return make_table_value([(str(new_name) if n == str(old_name) else n, v) for n, v in columns])


COLUMN_BUILTINS = {
    "table-select": table_select,
    "table-drop-columns": table_drop_columns,
    "table-add-column": table_add_column,
    "table-rename-column": table_rename_column,
}


# ---------------------------------------------------------------------------
# Choosing and ordering rows
# ---------------------------------------------------------------------------

def table_filter(table, mask):
    """(table-filter table mask) -- just the rows where the mask is true (a
    vector of 1 and 0, one per row, as the vector comparisons make)."""
    columns = table_columns(table, "table-filter")
    keep = truth_of(mask, "table-filter")
    if len(keep) != row_count(columns):
        raise LispError("table-filter: the table has %d rows, but the mask has %d values"
                        % (row_count(columns), len(keep)))
    return make_table_value(take_rows(columns, np.flatnonzero(keep)))


def table_sort(table, names, descending=False):
    """(table-sort table names [descending?]) -- the rows sorted by one
    column, or by several (the first name first, ties broken by the next).
    Ascending unless descending? is #t. Rows that tie stay in their
    original order. Missing values sort last (first if descending)."""
    columns = table_columns(table, "table-sort")
    keys = []
    for n in names_argument(names, "table-sort"):
        codes, _ = factorize(find_column(columns, n, "table-sort").items)
        keys.append(-codes if is_true(descending) else codes)
    # np.lexsort sorts by its LAST key first, so give it the keys reversed.
    order = np.lexsort(list(reversed(keys))) if row_count(columns) else np.arange(0)
    return make_table_value(take_rows(columns, order))


def table_append(*tables):
    """(table-append table1 table2 ...) -- the rows of each table, one table
    after another. The tables must have the same column names; the columns
    are matched by name, in the first table's order."""
    if not tables:
        raise LispError("table-append: expected at least one table")
    all_columns = [table_columns(t, "table-append") for t in tables]
    names = [n for n, _ in all_columns[0]]
    for columns in all_columns[1:]:
        if sorted(n for n, _ in columns) != sorted(names):
            raise LispError("table-append: the tables have different columns: %s and %s"
                            % (", ".join(names), ", ".join(n for n, _ in columns)))
    result = []
    for n in names:
        parts = [find_column(columns, n, "table-append").items for columns in all_columns]
        if any(p.dtype == object for p in parts):
            result.append((n, LispVector(np.concatenate([p.astype(object) for p in parts]))))
        else:
            result.append((n, to_vector(np.concatenate(parts))))
    return make_table_value(result)


ROW_BUILTINS = {
    "table-filter": table_filter,
    "table-sort": table_sort,
    "table-append": table_append,
}


# ---------------------------------------------------------------------------
# Grouping: one row per distinct key, with totals, averages, ...
# ---------------------------------------------------------------------------

def group_rows(key_vectors):
    """Put rows with equal key values into groups, sorted by key.
    Returns (order, starts, counts, key_values):
      order        row numbers, arranged group by group
      starts       where each group begins in `order`
      counts       how many rows each group has
      key_values   for each key column, a list of that key's value per group"""
    factorized = [factorize(v.items) for v in key_vectors]
    codes = np.stack([c for c, _ in factorized], axis=1)
    group_codes, group_of_row = np.unique(codes, axis=0, return_inverse=True)
    group_of_row = group_of_row.reshape(-1)
    order = np.argsort(group_of_row, kind="stable")
    counts = np.bincount(group_of_row, minlength=len(group_codes))
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.int64)
    key_values = [[distinct[c] for c in group_codes[:, j]] for j, (_, distinct) in enumerate(factorized)]
    return order, starts, counts, key_values


def group_sums(values, starts):
    """The sum of each group's values (values already arranged by group),
    treating NaN as 0."""
    return np.add.reduceat(np.where(np.isnan(values), 0.0, values), starts)


def aggregate(function, column, weights, order, starts, counts, as_vector=to_vector):
    """One aggregated column: `function` applied to each group's values.
    as_vector makes the numpy result a vector: to_vector, which stores
    numbers the way every vector does (see LispVector), unless the caller
    wants otherwise -- stratify keeps its few totals in full precision."""
    if function == "count":
        return as_vector(counts)
    if function in ("first", "last"):
        arranged = column.items[order]
        return LispVector(arranged[starts if function == "first" else starts + counts - 1])
    if function in ("min", "max") and column.items.dtype == object:
        arranged = column.items[order].tolist()
        choose = min if function == "min" else max
        return LispVector([choose([x for x in arranged[s:s + c] if x is not None] or [NIL])
                           for s, c in zip(starts, counts)])
    if np.issubdtype(column.items.dtype, np.integer) and function in ("sum", "min", "max"):
        integers = column.items.astype(np.int64)[order]          # no missing values to skip
        reduce = {"sum": np.add, "min": np.minimum, "max": np.maximum}[function]
        return as_vector(reduce.reduceat(integers, starts))
    values = floats_of(column, "table-group-by")[order]
    present = (~np.isnan(values)).astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        if function == "sum":
            return as_vector(group_sums(values, starts))
        if function == "mean":
            return as_vector(group_sums(values, starts) / np.add.reduceat(present, starts))
        if function == "weighted-mean":
            w = floats_of(weights, "table-group-by")[order]
            both = ~np.isnan(values) & ~np.isnan(w)
            numerator = np.add.reduceat(np.where(both, values * w, 0.0), starts)
            denominator = np.add.reduceat(np.where(both, w, 0.0), starts)
            return as_vector(numerator / denominator)
        if function == "min":
            return as_vector(np.fmin.reduceat(values, starts))
        if function == "max":
            return as_vector(np.fmax.reduceat(values, starts))
        if function in ("median", "stdev"):
            results = []
            for s, c in zip(starts, counts):
                group = values[s:s + c]
                group = group[~np.isnan(group)]
                if function == "median":
                    results.append(np.median(group) if len(group) else np.nan)
                else:
                    results.append(group.std(ddof=1) if len(group) > 1 else np.nan)
            return as_vector(np.array(results, dtype=np.float64))
    raise LispError("table-group-by: unknown function %s (use count, sum, mean, weighted-mean, "
                    "min, max, median, stdev, first, or last)" % function)


def table_group_by(table, keys, aggregations):
    """(table-group-by table keys aggregations) -- one row per distinct
    value of the key column(s), sorted by key, with the key columns
    followed by one column per aggregation. Each aggregation is a list
        (new-name function column)       e.g. ("total" sum "balance")
        (new-name weighted-mean column weight-column)
        (new-name count)
    where function is count (rows in the group), sum, mean, weighted-mean,
    min, max, median, stdev, first, or last (in the table's row order).
    Missing values are skipped."""
    columns = table_columns(table, "table-group-by")
    key_names = names_argument(keys, "table-group-by")
    key_vectors = [find_column(columns, n, "table-group-by") for n in key_names]
    specs = []
    for spec in pairs_to_list(aggregations):
        parts = pairs_to_list(spec) if isinstance(spec, Pair) else []
        if len(parts) < 2:
            raise LispError("table-group-by: each aggregation is (new-name function [column [weights]]), "
                            "got %r" % (spec,))
        function = symbol_argument(parts[1])
        column = find_column(columns, str(parts[2]), "table-group-by") if len(parts) > 2 else None
        weights = find_column(columns, str(parts[3]), "table-group-by") if len(parts) > 3 else None
        if column is None and function != "count":
            raise LispError("table-group-by: %s needs a column: (%s %s column)" % (function, parts[0], function))
        if function == "weighted-mean" and weights is None:
            raise LispError("table-group-by: weighted-mean needs a weight column: "
                            "(%s weighted-mean column weight-column)" % (parts[0],))
        specs.append((str(parts[0]), function, column, weights))

    if row_count(columns) == 0:
        return make_table_value([(n, LispVector([])) for n in key_names] +
                                [(s[0], LispVector([])) for s in specs])
    order, starts, counts, key_values = group_rows(key_vectors)
    result = [(n, LispVector(values)) for n, values in zip(key_names, key_values)]
    for new_name, function, column, weights in specs:
        result.append((new_name, aggregate(function, column, weights, order, starts, counts)))
    return make_table_value(result)


# ---------------------------------------------------------------------------
# Joining two tables on matching key values
# ---------------------------------------------------------------------------

def matching_keys(left_vectors, right_vectors):
    """Number every row's key values so that rows with equal keys, on
    either side, get the same number. Returns (left_ids, right_ids)."""
    n_left = len(left_vectors[0].items)
    per_key = []
    for lv, rv in zip(left_vectors, right_vectors):
        if lv.items.dtype == object or rv.items.dtype == object:
            both = np.concatenate([lv.items.astype(object), rv.items.astype(object)])
        else:
            both = np.concatenate([lv.items, rv.items])
        codes, _ = factorize(both)
        per_key.append(codes)
    _, ids = np.unique(np.stack(per_key, axis=1), axis=0, return_inverse=True)
    ids = ids.reshape(-1)
    return ids[:n_left], ids[n_left:]


def table_join(left, right, keys, how="inner"):
    """(table-join left right keys [how]) -- combine rows of two tables whose
    key column(s) match. Each output row is a left row followed by the
    matching right row's other columns. how is 'inner (the default: only
    left rows with a match) or 'left (every left row; where there's no
    match, the right columns are missing). A left row matching several
    right rows appears once for each. Rows keep the left table's order. A
    right column with the same name as a left one gets "_right" added."""
    how = symbol_argument(how)
    if how not in ("inner", "left"):
        raise LispError("table-join: how must be 'inner or 'left, got %s" % how)
    left_columns = table_columns(left, "table-join")
    right_columns = table_columns(right, "table-join")
    key_names = names_argument(keys, "table-join")
    left_keys = [find_column(left_columns, n, "table-join") for n in key_names]
    right_keys = [find_column(right_columns, n, "table-join") for n in key_names]
    n_left, n_right = row_count(left_columns), row_count(right_columns)

    if n_left and n_right:
        left_ids, right_ids = matching_keys(left_keys, right_keys)
    else:
        left_ids, right_ids = np.zeros(n_left, dtype=np.int64), np.ones(n_right, dtype=np.int64)

    # For each left row, the range [lo, hi) of right rows (in id order) that match it.
    right_order = np.argsort(right_ids, kind="stable")
    right_sorted = right_ids[right_order]
    lo = np.searchsorted(right_sorted, left_ids, side="left")
    hi = np.searchsorted(right_sorted, left_ids, side="right")
    matches = hi - lo
    rows_per_left = matches if how == "inner" else np.maximum(matches, 1)

    left_index = np.repeat(np.arange(n_left), rows_per_left)
    first_output = np.cumsum(rows_per_left) - rows_per_left
    nth_match = np.arange(len(left_index)) - np.repeat(first_output, rows_per_left)
    has_match = np.repeat(matches > 0, rows_per_left)
    right_index = np.full(len(left_index), -1, dtype=np.int64)
    right_index[has_match] = right_order[np.repeat(lo, rows_per_left)[has_match] + nth_match[has_match]]

    result = take_rows(left_columns, left_index)
    left_names = {n for n, _ in left_columns}
    for n, v in right_columns:
        if n in key_names:
            continue
        result.append((n + "_right" if n in left_names else n, take_with_missing(v, right_index)))
    return make_table_value(result)


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def table_describe(table):
    """(table-describe table) -- a table with one row per numeric column:
    how many values are present, and their mean, standard deviation,
    minimum, 25th percentile, median, 75th percentile, and maximum. Missing
    values are skipped; columns of strings or dates are left out."""
    columns = table_columns(table, "table-describe")
    names, stats = [], []
    for n, v in columns:
        if v.items.dtype == object:
            continue
        values = floats_of(v, "table-describe")
        values = values[~np.isnan(values)]
        names.append(LispString(n))
        if len(values):
            q25, median, q75 = np.quantile(values, [0.25, 0.5, 0.75])
            stdev = values.std(ddof=1) if len(values) > 1 else np.nan
            stats.append([len(values), values.mean(), stdev, values.min(), q25, median, q75, values.max()])
        else:
            stats.append([0] + [np.nan] * 7)
    headings = ["count", "mean", "stdev", "min", "p25", "median", "p75", "max"]
    result = [("column", LispVector(names))]
    for j, heading in enumerate(headings):
        column = np.array([row[j] for row in stats], dtype=np.int64 if heading == "count" else np.float64)
        result.append((heading, to_vector(column)))
    return make_table_value(result)


SUMMARY_BUILTINS = {
    "table-group-by": table_group_by,
    "table-join": table_join,
    "table-describe": table_describe,
}


BUILTINS = {}
BUILTINS.update(LOOKING_BUILTINS)
BUILTINS.update(ROW_VIEW_BUILTINS)
BUILTINS.update(COLUMN_BUILTINS)
BUILTINS.update(ROW_BUILTINS)
BUILTINS.update(SUMMARY_BUILTINS)
