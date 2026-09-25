"""SQLite access for the Lisp interpreter: sqlite-open, sqlite-close,
sqlite-query, sqlite-execute, and sqlite-fetch-row.

sqlite-query returns its result column by column, as a list of
(name . vector) pairs -- the shape display-columns and the regression
builtins accept directly. Values for "?" placeholders are passed through
SQLite's own parameter binding (the `params` argument), never pasted into
the SQL text, so they can't cause SQL injection; template.lsp builds on
this."""

import sqlite3

import numpy as np

from lisp_core import LispDate, LispError, LispString, LispVector, NIL, Pair, list_to_pairs, pairs_to_list


class LispSQLiteConnection:
    """An open SQLite database, from (sqlite-open "file.db"): a wrapper around
    a sqlite3.Connection, so it can be stored in a variable like any value."""

    def __init__(self, path):
        self.path = str(path)
        # isolation_level=None means autocommit: every statement takes effect
        # immediately. Otherwise an INSERT would sit in an open transaction and be
        # lost if the connection closed without a commit.
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
    """One value from a SQLite row as a Lisp value: NULL becomes '(), text a
    LispString, a BLOB is decoded as UTF-8 text, and numbers are unchanged."""
    if v is None:
        return NIL
    if isinstance(v, bytes):
        return LispString(v.decode("utf-8", errors="replace"))
    if isinstance(v, str):
        return LispString(v)
    return v


def sqlite_open_fn(path):
    """(sqlite-open "file.db") -- open a SQLite database file (creating it if
    needed) and return a connection for sqlite-query, sqlite-execute, and
    sqlite-close."""
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
    """One Lisp value as a "?" parameter for sqlite3: '() becomes NULL, a date
    its YYYY-MM-DD string, and a LispString a plain str (sqlite3 rejects str
    subclasses). Numbers and booleans are unchanged."""
    if v is NIL:
        return None
    if isinstance(v, LispDate):
        return v.date.isoformat()
    if isinstance(v, LispString):
        return str(v)
    return v


def _sqlite_run(conn, sql, params=None):
    """Run `sql` and return the sqlite3 cursor. `params` is None, or a Lisp
    list of values for the "?" placeholders, in order. They go through
    sqlite3's own parameter binding, which sends them separately from the SQL
    text, so no value can ever be read as SQL -- unlike pasting values into
    the query string, which is how SQL injection happens."""
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
    """The numpy dtype for one character of sqlite-query's `dtypes` string:
    'B', 'I', or 'F' (either case) for LispVector's BOOL_INT_DTYPE, INT_DTYPE,
    or FLOAT_DTYPE. Any other character (conventionally '.') means no hint,
    and returns None."""
    code = code.upper()
    if code == "B":
        return LispVector.BOOL_INT_DTYPE
    if code == "I":
        return LispVector.INT_DTYPE
    if code == "F":
        return LispVector.FLOAT_DTYPE
    return None


def _sqlite_query_streamed(cursor, names, hints):
    """Read the rows when there's no `max-rows`: collect each column in a
    Python list, then build its vector at the end. A hinted column skips the
    dtype-guessing scan, but is briefly held twice (list and array)."""
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
    """Read the rows when `max-rows` is given: each hinted column's numpy
    array is allocated once, `cap` rows long, and filled as rows arrive --
    no Python list, and no dtype-guessing afterward. Un-hinted columns still
    collect into a list."""
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
    """(sqlite-query conn sql [dtypes max-rows params]) -- run a query and
    return the whole result column by column: a list of (name . vector)
    pairs, one per column, in order. That's the shape display-columns and
    the regression builtins take, e.g.
        (display-columns (sqlite-query conn "SELECT year, total FROM t"))
    A NULL becomes '(). For a result too big to hold at once, use
    sqlite-execute and sqlite-fetch-row instead.

    `params` (optional): a list of values for the "?" placeholders -- see
    _sqlite_run for why this prevents SQL injection.

    `dtypes` and `max-rows` (optional, used together) speed up very large
    results (millions of rows):
      dtypes    one character per column: 'B', 'I', or 'F' stores that column
                as 0/1 flags, integers, or floats without scanning it first;
                '.' leaves a column (e.g. a text one) to be inferred as usual.
                The hints are trusted: a value the type can't hold at all (a
                NULL in a 'B'/'I' column, a string) is an error naming the row
                and column, but a fraction in an 'I' column is silently
                truncated. A NULL in an 'F' column becomes NaN.
      max-rows  an upper bound on the row count, so each hinted column's
                array can be allocated once and filled directly. More rows
                than that is an error."""
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
    """(sqlite-execute conn sql [params]) -- run a statement and return a
    cursor, without reading any rows yet. Call (sqlite-fetch-row cursor)
    repeatedly to get one row at a time, as a list, until it returns '().
    Use it for a result too big to read at once, or for INSERT/UPDATE/...
    (where sqlite-fetch-row returns '() right away)."""
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
