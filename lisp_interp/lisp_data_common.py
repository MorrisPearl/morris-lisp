"""What the modules that download economic and financial data share
(lisp_fred, lisp_sec, lisp_fdic, lisp_census, lisp_bls, lisp_bea, and
lisp_tastytrade): reading the credentials file, reading the arguments they
have in common, and making their tables.

The credentials file is a JSON object of keys and other entries -- such as
{"bea_api_key": "...", "sec_user_agent": "Jane Smith jane@example.com"} --
whose path is the first argument of most of the data functions.
"""

import datetime
import json
import math

from lisp_core import LispDate, LispError, LispString, LispVector, Pair, pairs_to_list
from lisp_tables import column_vector, make_table_value


# ---------------------------------------------------------------------------
# The credentials file
# ---------------------------------------------------------------------------

def read_credentials(credentials_path, who):
    """The credentials file's entries, as a dict."""
    try:
        with open(str(credentials_path)) as f:
            entries = json.load(f)
    except OSError as e:
        raise LispError("%s: couldn't open the credentials file %s: %s" % (who, credentials_path, e))
    except json.JSONDecodeError as e:
        raise LispError("%s: the credentials file %s isn't valid JSON: %s" % (who, credentials_path, e))
    if not isinstance(entries, dict):
        raise LispError('%s: the credentials file %s must hold a JSON object, such as {"bea_api_key": "..."}'
                        % (who, credentials_path))
    return entries


def credential(credentials_path, name, who, needed_for=None):
    """One entry of the credentials file, as text, without spaces around it;
    None if the file has no such entry -- unless needed_for says why the
    entry is needed, which makes a missing one an error."""
    value = read_credentials(credentials_path, who).get(name)
    value = str(value).strip() if value is not None else ""
    if value:
        return value
    if needed_for:
        raise LispError('%s: the credentials file has no "%s" entry -- %s' % (who, name, needed_for))
    return None


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

def text_list(value, who, what):
    """A string, or a list or vector of them, as a Python list of strings."""
    if isinstance(value, str):
        return [str(value)]
    if isinstance(value, Pair):
        return [str(v) for v in pairs_to_list(value)]
    if isinstance(value, LispVector):
        return [str(v) for v in value.items]
    raise LispError("%s: %s must be a string or a list of strings, not %r" % (who, what, value))


def year_range(options, who, default_years=10):
    """The years asked for, as (first, last): from :start-year to :end-year,
    the last default_years years if they aren't given, and no later than
    this year."""
    this_year = datetime.date.today().year
    end_year = int(options.get("end-year") or this_year)
    start_year = int(options.get("start-year") or end_year - default_years + 1)
    if start_year > end_year:
        raise LispError("%s: :start-year %d is after :end-year %d" % (who, start_year, end_year))
    return start_year, min(end_year, this_year)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def dated_table(columns_by_heading):
    """A table with a date column, oldest first, and a column for each of
    columns_by_heading -- (heading, {datetime.date: value}) -- with NaN
    where a column has no value for a date."""
    dates = sorted({date for _, by_date in columns_by_heading for date in by_date})
    columns = [("date", column_vector([LispDate(d.year, d.month, d.day) for d in dates]))]
    for heading, by_date in columns_by_heading:
        columns.append((heading, column_vector([by_date.get(d, math.nan) for d in dates])))
    return make_table_value(columns)


def records_table(records, columns=None):
    """Records (dicts, as an API's JSON gives them) as a table: a column for
    each field, in the order the fields first appear (or those given).
    Text stays text, true and false become 1 and 0, and a value that is
    itself an object or a list becomes its JSON text."""
    if columns is None:
        columns = []
        for record in records:
            for name in record:
                if name not in columns:
                    columns.append(name)

    def lisp_value(value):
        if isinstance(value, str):
            return LispString(value)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (dict, list)):
            return LispString(json.dumps(value))
        return value
    return make_table_value([(name, column_vector([lisp_value(r.get(name)) for r in records])) for name in columns])
