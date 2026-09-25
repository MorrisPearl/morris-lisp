"""CSV files for the Lisp interpreter: load-csv reads one into a table, and
write-columns-csv writes a table out. (lisp_http.py's http-get-csv reads a
downloaded CSV with the same code as load-csv.)

A table is a list of (name . vector) columns -- see lisp_tables.py.
"""

import csv

from lisp_core import LispDate, LispError, LispString, LispVector, NIL, Pair, list_to_pairs, pairs_to_list, to_display_string


def _parse_number(text):
    """text as an int or float, or None if it isn't a number."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(text):
    """text as a LispDate if it's written YYYY-MM-DD or MM/DD/YYYY (the
    American order, as US government data uses), otherwise None."""
    try:
        if "-" in text:
            year, month, day = text.split("-")
        else:
            month, day, year = text.split("/")
        if len(year) != 4:
            return None
        return LispDate(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def _column_vector(texts):
    """One CSV column (a list of strings) as a vector. If every non-blank
    value is a number, it's a numeric vector, with NaN for blanks. If every
    non-blank value is a date (YYYY-MM-DD or MM/DD/YYYY), it's a vector of dates.
    Otherwise it's a vector of strings. Blank dates and strings become '()."""
    stripped = [t.strip() for t in texts]
    present = [t for t in stripped if t != ""]
    numbers = [_parse_number(t) for t in present]
    if present and all(n is not None for n in numbers):
        if len(present) == len(stripped):
            return LispVector(numbers)
        return LispVector([_parse_number(t) if t != "" else float("nan") for t in stripped])
    dates = [_parse_date(t) for t in present]
    if present and all(d is not None for d in dates):
        return LispVector([_parse_date(t) if t != "" else NIL for t in stripped])
    return LispVector([LispString(t) if t != "" else NIL for t in stripped])


def table_from_csv_rows(rows, has_header, source):
    """A table from the rows of a CSV file (lists of strings). `source`
    names the file or URL in error messages."""
    if not rows:
        raise LispError("load-csv: %s is empty" % source)
    if has_header:
        header, data_rows = rows[0], rows[1:]
    else:
        header, data_rows = ["Column%d" % (i + 1) for i in range(len(rows[0]))], rows
    n_columns = len(header)
    for number, row in enumerate(data_rows, start=2 if has_header else 1):
        if len(row) > n_columns:
            raise LispError("load-csv: line %d of %s has %d values, but there are only %d columns"
                            % (number, source, len(row), n_columns))
    padded = [row + [""] * (n_columns - len(row)) for row in data_rows]
    columns = []
    for c, name in enumerate(header):
        columns.append(Pair(LispString(name), _column_vector([row[c] for row in padded])))
    return list_to_pairs(columns)


def load_csv_fn(filename, has_header=True):
    """(load-csv filename [has-header?]) -- a CSV file as a table: a list of
    (name . vector) columns, the same shape sqlite-query returns. A column
    of numbers becomes a numeric vector (blanks are NaN); a column of dates
    (YYYY-MM-DD or MM/DD/YYYY) becomes a vector of dates; anything else becomes a
    vector of strings (blanks are '()). With has-header? #f, the columns
    are named Column1, Column2, ..."""
    try:
        with open(str(filename), newline="") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        raise LispError("load-csv: could not open %r: %s" % (str(filename), e))
    return table_from_csv_rows(rows, has_header is not False, repr(str(filename)))


def parse_column_pairs(name_value_pairs):
    """Read the column list display-columns and write-columns-csv take: each
    element is (name . vector), or (name vector decimals) to give that
    column a number of decimal places. Returns (name, items,
    decimals-or-None) tuples."""
    out = []
    for p in pairs_to_list(name_value_pairs):
        name = str(p.car)
        rest = p.cdr
        if isinstance(rest, LispVector):
            out.append((name, rest.items.tolist(), None))
        elif isinstance(rest, Pair) and isinstance(rest.car, LispVector):
            decimals = rest.cdr.car if isinstance(rest.cdr, Pair) else None
            out.append((name, rest.car.items.tolist(), decimals))
        else:
            raise LispError(
                "expected (name . vector) or (name vector decimals), got %r" % (p,))
    return out


def write_columns_csv_fn(filename, name_value_pairs):
    """(write-columns-csv filename table) -- write a table (or the column
    list display-columns takes) to a CSV file: a header row of names, then
    one row per index. Numbers are written as plain numbers, rounded to the
    column's decimals if it has any; missing values are left blank. A
    shorter column is padded with empty cells."""
    parsed = parse_column_pairs(name_value_pairs)
    n_rows = max((len(items) for _, items, _ in parsed), default=0)
    with open(str(filename), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([name for name, _, _ in parsed])
        for i in range(n_rows):
            row = []
            for _, items, decimals in parsed:
                v = items[i] if i < len(items) else None
                if v is None or (isinstance(v, float) and v != v):     # missing, or NaN
                    row.append("")
                elif isinstance(v, bool) or not isinstance(v, (int, float)):
                    row.append(to_display_string(v))
                elif decimals is not None:
                    d = int(decimals)
                    row.append(int(round(float(v))) if d == 0 else round(float(v), d))
                else:
                    row.append(v)
            writer.writerow(row)
    return NIL


BUILTINS = {
    "load-csv": load_csv_fn,
    "write-columns-csv": write_columns_csv_fn,
}
