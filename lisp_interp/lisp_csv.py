"""CSV files for the Lisp interpreter: load-csv reads one into a table, and
write-columns-csv writes a table out. (lisp_http.py's http-get-csv reads a
downloaded CSV with the same code as load-csv.)

A table is a list of (name . vector) columns -- see lisp_tables.py.
"""

import csv

from lisp_core import (
    Keyword, LispDate, LispError, LispString, LispVector, NIL, Pair, Symbol, keyword_options, list_to_pairs, pairs_to_list,
    to_display_string,
)


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


def _column_vector(texts, as_text=False):
    """One CSV column (a list of strings) as a vector. If every non-blank
    value is a number, it's a numeric vector, with NaN for blanks. If every
    non-blank value is a date (YYYY-MM-DD or MM/DD/YYYY), it's a vector of dates.
    Otherwise -- or if as_text, whatever its values look like -- it's a vector
    of strings, as written (a zip code 08701 stays "08701"). Blank dates and
    strings become '()."""
    stripped = [t.strip() for t in texts]
    if as_text:
        return LispVector([LispString(t) if t != "" else NIL for t in stripped])
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


def _texts(value, option, what, who):
    """An option's value -- a text, or a list of them -- as a list of strings."""
    if isinstance(value, str):
        texts = [value]
    elif value is NIL or isinstance(value, Pair):
        texts = pairs_to_list(value)
    else:
        raise LispError("%s: :%s must be %s, or a list of them, not %s" % (who, option, what, to_display_string(value)))
    for text in texts:
        if not isinstance(text, str):
            raise LispError("%s: :%s must be %s, or a list of them, not %s" % (who, option, what, to_display_string(text)))
    return [str(text) for text in texts]


def csv_arguments(arguments, most_positional, who):
    """load-csv's or http-get-csv's optional arguments: the positional ones,
    before the first keyword (at most most_positional of them), as a list; and
    the keyword options, as a dict:
      "text"     the names of the columns to keep as strings, a list (none, if :text isn't given)
      "skip"     the rows above the header to leave out: a number, or the text its first cell is (0, if no :skip)
      "missing"  the texts to read as blanks, a list (none, if :missing isn't given)"""
    first_keyword = next((i for i, a in enumerate(arguments) if isinstance(a, Keyword)), len(arguments))
    if first_keyword > most_positional:
        raise LispError("%s: expected at most %d argument(s) before the keyword options, not %d"
                        % (who, most_positional + 1, first_keyword + 1))
    options = keyword_options(arguments[first_keyword:], ["text", "skip", "missing"], who)
    skip = options.get("skip", 0)
    if isinstance(skip, bool) or not (isinstance(skip, (str, int)) and (isinstance(skip, str) or skip >= 0)):
        raise LispError("%s: :skip must be a number of rows, or the text that the header row begins with, not %s"
                        % (who, to_display_string(skip)))
    return list(arguments[:first_keyword]), {
        "text": _texts(options.get("text", NIL), "text", "a column's name", who),
        "skip": str(skip) if isinstance(skip, str) else skip,
        "missing": _texts(options.get("missing", NIL), "missing", "a text", who)}


def headings_argument(value, who):
    """What load-csv's and http-get-csv's has-header? argument says about the column names: #f (the columns are named Column1,
    Column2, ...), a list of names, which the file has no row of (they are the names), or anything else, #t if it is left out (the first
    row of the file is the names). Returns False, True, or the list of names as strings."""
    if value is False:
        return False
    if value is NIL:
        raise LispError("%s: has-header? is #t, #f, or a list of the column names, not the empty list" % who)
    if not isinstance(value, Pair):
        return True
    names = pairs_to_list(value)
    for name in names:
        if not isinstance(name, str) or isinstance(name, Symbol):
            raise LispError("%s: the column names are strings, such as (list \"date\" \"rate\"), not %s" % (who, to_display_string(name)))
    names = [str(name) for name in names]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise LispError("%s: the column names must differ, and %s is there more than once" % (who, ", ".join(repr(r) for r in repeated)))
    return names


def _rows_below(rows, skip, source, who):
    """The rows from the header on: without the first `skip` rows, or the rows above the first one whose first cell is
    the text skip."""
    if isinstance(skip, int):
        return rows[skip:]
    for number, row in enumerate(rows):
        if row and row[0].strip() == skip:
            return rows[number:]
    raise LispError("%s: no row of %s begins with %s" % (who, source, skip))


def table_from_csv_rows(rows, has_header, source, options=None, who="load-csv"):
    """A table from the rows of a CSV file (lists of strings). `source`
    names the file or URL in error messages. has_header is what headings_argument gives: True (the first row
    is the names), False (the names are Column1, Column2, ...), or a list of names (which the file has no row of).
    options is what csv_arguments gives: the :text columns are strings, as written, whatever their values
    look like; the :skip rows above the header are left out; and the :missing
    texts are blanks."""
    options = options or {"text": [], "skip": 0, "missing": []}
    text_columns = options["text"]
    rows = _rows_below(rows, options["skip"], source, who)
    if not rows:
        raise LispError("load-csv: %s is empty" % source)
    given_names = isinstance(has_header, list)
    if given_names:
        header, data_rows = has_header, rows
        widest = max(len(row) for row in rows)
        if len(header) > widest:
            raise LispError("%s: %d column names were given, but the widest line of %s has only %d values"
                            % (who, len(header), source, widest))
    elif has_header:
        header, data_rows = rows[0], rows[1:]
    else:
        header, data_rows = ["Column%d" % (i + 1) for i in range(len(rows[0]))], rows
    n_columns = len(header)
    for number, row in enumerate(data_rows, start=2 if has_header is True else 1):
        if len(row) > n_columns:
            raise LispError("load-csv: line %d of %s has %d values, but there are only %d columns"
                            % (number, source, len(row), n_columns))
    missing = [name for name in text_columns if name not in header]
    if missing:
        raise LispError("%s: :text names %s, which %s a column of %s"
                        % (who, ", ".join(missing), "isn't" if len(missing) == 1 else "aren't", source))
    blank = set(options["missing"])
    padded = [[("" if cell.strip() in blank else cell) for cell in row] + [""] * (n_columns - len(row))
              for row in data_rows]
    columns = []
    for c, name in enumerate(header):
        columns.append(Pair(LispString(name), _column_vector([row[c] for row in padded], name in text_columns)))
    return list_to_pairs(columns)


def load_csv_fn(filename, *arguments):
    """(load-csv filename [headings] [:text columns] [:skip rows] [:missing texts]) -- a CSV file as a
    table: a list of (name . vector) columns, the same shape sqlite-query
    returns. A column of numbers becomes a numeric vector (blanks are NaN); a
    column of dates (YYYY-MM-DD or MM/DD/YYYY) becomes a vector of dates;
    anything else becomes a vector of strings (blanks are '()). The :text
    columns -- a name, or a list of names -- are strings as written, whatever
    they look like: zip codes, say, which would lose their leading zeros as
    numbers. headings is #t (the default: the first row names the columns), #f (the file has no row of
    names, and the columns are named Column1, Column2, ...), or a list of strings, the names to use for
    the columns, which the file has no row of (to replace the names that it has, also give :skip 1). :skip
    leaves out the rows above the header -- notes, say -- a number of them, or the text
    that the header row begins with. :missing -- a text, or a list of them, such as "NA"
    -- names what is read as a blank."""
    positional, options = csv_arguments(arguments, 1, "load-csv")
    has_header = positional[0] if positional else True
    try:
        with open(str(filename), newline="") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        raise LispError("load-csv: could not open %r: %s" % (str(filename), e))
    return table_from_csv_rows(rows, headings_argument(has_header, "load-csv"), repr(str(filename)), options)


def parse_column_pairs(name_value_pairs):
    """Read the column list write-columns-csv takes: each element is
    (name . vector), as in a table, or (name vector decimals) to give that
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
    """(write-columns-csv filename table) -- write a table (or a list of
    (name vector decimals)) to a CSV file: a header row of names, then
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
