"""SQLite access for the Lisp interpreter: sqlite-open, sqlite-close,
sqlite-query, sqlite-execute, and sqlite-fetch-row, against a local
database file.

sqlite-query returns its whole result COLUMN-WISE, as a list of
(name . vector) pairs -- the shape display-columns and the regression
builtins accept directly. For a very large result, its optional `dtypes`
and `max-rows` arguments let it fill numpy arrays directly instead of
building Python lists first. Values for "?" placeholders are passed
through SQLite's own parameter binding (the `params` argument), never
pasted into the SQL text, so they can't cause SQL injection -- see
template.lsp for a templating engine built on that.
"""

import sqlite3

import numpy as np

from lisp_core import LispDate, LispError, LispString, LispVector, NIL, Pair, list_to_pairs, pairs_to_list


class LispSQLiteConnection:
    """An open SQLite database, from (sqlite-open "path/to/db.sqlite").
    Thin wrapper around sqlite3.Connection so it's an ordinary, passable-
    around Lisp value (bound to a variable, stored in a struct, etc.) --
    see sqlite_open_fn/sqlite_query_fn/sqlite_execute_fn/sqlite_close_fn."""

    def __init__(self, path):
        self.path = str(path)
        # isolation_level=None -> autocommit: every statement (SELECT
        # or otherwise) takes effect immediately, with no separate
        # sqlite-commit/sqlite-rollback builtin needed. Without this,
        # sqlite3's default mode silently defers INSERT/UPDATE/DELETE
        # in an open transaction that's lost if the connection is
        # closed (or never committed) -- surprising for a single
        # (sqlite-execute conn "INSERT ...") call, which reads as a
        # complete, self-contained action.
        self.connection = sqlite3.connect(self.path, isolation_level=None)

    def __repr__(self):
        return "#<sqlite-connection %s>" % (self.path,)


class LispSQLiteCursor:
    """An in-progress SQL query, from (sqlite-execute conn "SELECT ...").
    Wraps a sqlite3.Cursor -- repeated (sqlite-fetch-row cursor) calls
    pull one row at a time until the query is exhausted."""

    def __init__(self, cursor):
        self.cursor = cursor

    def __repr__(self):
        return "#<sqlite-cursor>"


def _sqlite_value_to_lisp(v):
    """Convert one value out of a sqlite3 row into the matching Lisp
    value: SQL NULL (None) becomes '(), TEXT becomes a LispString,
    everything else (INTEGER/REAL, already plain int/float) passes
    through unchanged. BLOB values (Python bytes) are decoded as UTF-8
    text on a best-effort basis -- this interpreter has no separate
    byte-vector type to hand them back as."""
    if v is None:
        return NIL
    if isinstance(v, bytes):
        return LispString(v.decode("utf-8", errors="replace"))
    if isinstance(v, str):
        return LispString(v)
    return v


def sqlite_open_fn(path):
    """(sqlite-open "path/to/db.sqlite") -- open a SQLite database file
    (creating it if it doesn't already exist, same as Python's own
    sqlite3.connect) and return a connection value to pass to
    sqlite-query / sqlite-execute / sqlite-close."""
    try:
        return LispSQLiteConnection(path)
    except sqlite3.Error as e:
        raise LispError("sqlite-open: could not open %r: %s" % (str(path), e))


def sqlite_close_fn(conn):
    """(sqlite-close conn) -- close a connection opened by sqlite-open.
    Safe to call on an already-closed connection."""
    if not isinstance(conn, LispSQLiteConnection):
        raise LispError("sqlite-close: not a sqlite connection: %r" % (conn,))
    conn.connection.close()
    return NIL


def _lisp_value_to_sqlite_param(v):
    """Convert one Lisp value into whatever Python's sqlite3 module wants
    to bind it as a `?` parameter: '() -> None (SQL NULL), a LispDate ->
    its ISO string, a LispString -> a plain str (sqlite3 rejects the
    LispString subclass otherwise -- it checks type(v) is str, not
    isinstance), everything else (plain int/float/bool) passes through
    unchanged -- sqlite3 already accepts those natively."""
    if v is NIL:
        return None
    if isinstance(v, LispDate):
        return v.date.isoformat()
    if isinstance(v, LispString):
        return str(v)
    return v


def _sqlite_run(conn, sql, params=None):
    """params: None (no parameters -- the plain sqlite-query case), or a
    Lisp list of values to bind to the SQL text's `?` placeholders, in
    order -- passed to sqlite3's OWN parameter binding (cursor.execute(
    sql, params)), which is what actually makes this safe against SQL
    injection: a bound value is sent to SQLite separately from the SQL
    text over the driver's own protocol, so it can NEVER be interpreted
    as SQL syntax no matter what characters it contains -- unlike
    building the query by splicing a value into the SQL string, which is
    exactly what SQL injection is. See template.lsp's `{{name}}` in
    "SQL mode" for the Lisp-level tool that generates a `?`-placeholder
    query and this params list together, so a value never has to be
    spliced into SQL text by hand at all."""
    if not isinstance(conn, LispSQLiteConnection):
        raise LispError("expected a sqlite connection (from sqlite-open), got %r" % (conn,))
    try:
        cursor = conn.connection.cursor()
        if params is None:
            cursor.execute(str(sql))
        else:
            bound = [_lisp_value_to_sqlite_param(v) for v in pairs_to_list(params)]
            cursor.execute(str(sql), bound)
        return cursor
    except sqlite3.Error as e:
        raise LispError("sqlite: %s" % e)


def _sqlite_dtype_for_code(code):
    """Map one character of sqlite-query's optional `dtypes` hint string
    to a numpy dtype -- 'B'/'I'/'F' (case-insensitive) for Boolean/
    Integer/Float, picking LispVector.BOOL_INT_DTYPE/INT_DTYPE/
    FLOAT_DTYPE respectively (looked up fresh here, not cached, so
    changing those class attributes -- see LispVector's own docstring --
    takes effect here too). Any other character (conventionally '.')
    means "no hint for this column" (None) -- it falls back to
    sqlite-query's normal per-value type inference, so a `dtypes` string
    only needs real letters over a query's numeric columns, leaving a
    text column (say) un-hinted."""
    code = code.upper()
    if code == "B":
        return LispVector.BOOL_INT_DTYPE
    if code == "I":
        return LispVector.INT_DTYPE
    if code == "F":
        return LispVector.FLOAT_DTYPE
    return None


def _sqlite_query_streamed(cursor, names, hints):
    """sqlite-query's original approach, used when no `max-rows` is
    given: grow a plain Python list per column as rows stream in from
    the cursor, then build each column's LispVector at the end. A
    hinted column (see sqlite-query's own docstring for `hints`) still
    skips per-value Lisp wrapping and has its final dtype forced
    directly instead of inferred -- a real saving on its own for a big
    column, since it skips re-scanning every value just to guess a
    dtype -- but, unlike the `max-rows` path below, doesn't avoid
    briefly holding the column twice over (once as this Python list,
    once as the final packed array), since the eventual row count isn't
    known ahead of time."""
    columns_raw = [[] for _ in names]
    for row in cursor:
        for j, v in enumerate(row):
            columns_raw[j].append(v if hints[j] is not None else _sqlite_value_to_lisp(v))

    result = []
    for j, values in enumerate(columns_raw):
        if hints[j] is None:
            result.append(LispVector(values))
            continue
        try:
            result.append(LispVector(np.array(values, dtype=hints[j])))
        except (TypeError, ValueError, OverflowError) as e:
            raise LispError("sqlite-query: column %r doesn't fit its dtypes hint: %s" % (names[j], e))
    return result


def _sqlite_query_preallocated(cursor, names, hints, cap):
    """sqlite-query's `max-rows` path -- see its own docstring. Every
    hinted column's numpy array is allocated ONCE, at `cap` rows, before
    a single row is even read, and each row's value is written directly
    into it (arrays[j][row_count] = v) as it streams from the cursor --
    no intermediate Python list, and no separate dtype-inference pass
    afterward, for that column. Un-hinted columns still grow a plain
    list, same as the no-max-rows path, since their eventual dtype isn't
    known until every value's been seen."""
    arrays = [np.empty(cap, dtype=hint) if hint is not None else None for hint in hints]
    raw_lists = [[] if hint is None else None for hint in hints]

    row_count = 0
    j = 0
    try:
        for row in cursor:
            if row_count >= cap:
                raise LispError(
                    "sqlite-query: the result has more than max-rows=%d rows "
                    "(row %d found) -- raise max-rows, or drop it to collect "
                    "an unbounded result the ordinary way" % (cap, row_count + 1))
            for j, v in enumerate(row):
                if hints[j] is not None:
                    arrays[j][row_count] = v
                else:
                    raw_lists[j].append(_sqlite_value_to_lisp(v))
            row_count += 1
    except LispError:
        raise
    except (TypeError, ValueError, OverflowError) as e:
        raise LispError(
            "sqlite-query: row %d, column %r doesn't fit its dtypes hint: %s"
            % (row_count, names[j], e))

    result = []
    for j in range(len(names)):
        if hints[j] is not None:
            result.append(LispVector(arrays[j][:row_count]))
        else:
            result.append(LispVector(raw_lists[j]))
    return result


def sqlite_query_fn(conn, sql, dtypes=None, max_rows=None, params=None):
    """(sqlite-query conn "SELECT ...") -- run a SQL statement to
    completion and return its result set COLUMN-WISE: a Lisp list of
    (name . vector) pairs, one per output column, in query order --
    exactly the shape (display-columns ...) / (write-columns-csv ...)
    already expect, so a query's results can be shown or exported
    directly:
        (display-columns (sqlite-query conn "SELECT year, total FROM t"))
    Column names come from the query itself; SQL NULL becomes '() (see
    _sqlite_value_to_lisp) in an un-hinted column. This reads the ENTIRE
    result set into memory before returning -- for a large result you'd
    rather step through one row at a time instead, see sqlite-execute /
    sqlite-fetch-row.

    `params` (optional, last argument so existing 2/3/4-argument calls
    keep working unchanged): a Lisp list of values to bind to `?`
    placeholders in `sql`, in order -- see _sqlite_run's docstring for
    why this (not string-building) is what actually prevents SQL
    injection. template.lsp builds the `sql`/`params` pair for you from
    a template and a set of named bindings; this is the low-level
    primitive it's built on.

    Two optional arguments, meant to be used TOGETHER to speed up a huge
    result set (tens of millions of rows), where the ordinary approach
    above -- grow a plain Python list per column, then hand each one to
    LispVector, which scans every value to infer a dtype -- means
    briefly holding the whole result twice over (once as boxed Python
    values, once as the final packed numpy array) and spending real time
    on that inference scan:

      `dtypes`: a string with one character per output column, in query
      order -- 'B'/'I'/'F' (case-insensitive) for Boolean/Integer/Float,
      forcing that column straight to LispVector.BOOL_INT_DTYPE/
      INT_DTYPE/FLOAT_DTYPE instead of inferring it from the data; any
      other character (conventionally '.') leaves that one column
      un-hinted, inferred the normal way -- handy for a query that mixes
      numeric columns with a text one. Hints are TRUSTED, not verified
      against the data: a value the hinted dtype genuinely can't hold (a
      NULL in a 'B'/'I' column, since there's no integer NaN; a string;
      a number too big for the dtype) raises a LispError naming the row
      and column, but a value that merely doesn't match -- e.g. a
      fractional number in an 'I' column -- is silently truncated the
      same way an unchecked vector-set! would be (see LispVector's
      docstring on _value_fits_dtype) -- this fast path deliberately
      skips that check. A NULL in an 'F' column becomes NaN, same as
      numpy/pandas' own convention for a missing float, and needs no
      special handling.

      `max-rows`: an upper bound on how many rows the query will
      return. Given together with `dtypes`, every HINTED column's numpy
      array is allocated once, up front, at this size, and each row's
      values are written directly into it as they stream from the
      cursor -- no intermediate Python list for that column at all, and
      no separate dtype-inference pass afterward. Un-hinted columns (no
      `dtypes` string, or a column left un-hinted within one) still
      collect into a plain list either way, since their eventual dtype
      isn't known until every value's been seen. If the query actually
      returns MORE than `max-rows` rows, that's a LispError -- raise the
      bound, or drop `max-rows` to fall back to an ordinary, unbounded
      collection -- rather than silently reallocating past the bound you
      gave, or silently dropping rows.
    """
    cursor = _sqlite_run(conn, sql, params)
    names = [d[0] for d in cursor.description] if cursor.description else []
    n_cols = len(names)

    hints = [None] * n_cols
    if dtypes is not None and dtypes is not NIL:
        dtype_str = str(dtypes)
        if len(dtype_str) != n_cols:
            raise LispError(
                "sqlite-query: dtypes must have exactly one character per "
                "column (%d column(s), got a %d-character string)" % (n_cols, len(dtype_str)))
        hints = [_sqlite_dtype_for_code(ch) for ch in dtype_str]

    if max_rows is not None and max_rows is not NIL:
        cap = int(max_rows)
        if cap < 0:
            raise LispError("sqlite-query: max-rows must not be negative")
        columns = _sqlite_query_preallocated(cursor, names, hints, cap)
    else:
        columns = _sqlite_query_streamed(cursor, names, hints)

    return list_to_pairs([Pair(LispString(name), column) for name, column in zip(names, columns)])


def sqlite_execute_fn(conn, sql, params=None):
    """(sqlite-execute conn "SELECT ...") -- run a SQL statement and
    return a CURSOR without reading any rows yet. Call (sqlite-fetch-row
    cursor) repeatedly to pull one row at a time (as a Lisp list of that
    row's values, in column order) until it returns '(), meaning no rows
    are left -- useful for a result set too large to materialize all at
    once with sqlite-query, or when you'd rather process rows one by one
    (e.g. in a `while`/`dolist` loop). Fine for a non-SELECT statement
    too (INSERT/UPDATE/...); sqlite-fetch-row just returns '() right
    away since there's nothing to fetch.

    `params` (optional): a Lisp list of values to bind to `?`
    placeholders in `sql`, in order -- see sqlite-query's docstring."""
    return LispSQLiteCursor(_sqlite_run(conn, sql, params))


def sqlite_fetch_row_fn(cursor):
    """(sqlite-fetch-row cursor) -- pull the next row from a cursor
    returned by sqlite-execute, as a Lisp list of that row's values in
    column order, or '() once every row has already been fetched."""
    if not isinstance(cursor, LispSQLiteCursor):
        raise LispError("sqlite-fetch-row: not a sqlite cursor: %r" % (cursor,))
    row = cursor.cursor.fetchone()
    if row is None:
        return NIL
    return list_to_pairs([_sqlite_value_to_lisp(v) for v in row])


BUILTINS = {
    "sqlite-open": sqlite_open_fn,
    "sqlite-close": sqlite_close_fn,
    "sqlite-query": sqlite_query_fn,
    "sqlite-execute": sqlite_execute_fn,
    "sqlite-fetch-row": sqlite_fetch_row_fn,
    "sqlite-connection?": lambda x: isinstance(x, LispSQLiteConnection),
    "sqlite-cursor?": lambda x: isinstance(x, LispSQLiteCursor),
}
