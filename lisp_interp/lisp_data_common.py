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
import os

from lisp_core import LispDate, LispError, LispHashTable, LispString, LispVector, Pair, pairs_to_list
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
# Sign-in tokens (Schwab's and Google's: the provider is named as it is in a message, "Schwab")
# ---------------------------------------------------------------------------

def token_file(credentials_path, provider):
    """Where a provider's tokens are kept: schwab_tokens.json, for "Schwab", next to the credentials file."""
    return os.path.join(os.path.dirname(os.path.abspath(str(credentials_path))), provider.lower() + "_tokens.json")


def save_tokens(credentials_path, provider, tokens):
    """Save the provider's tokens, readable only by you."""
    path = token_file(credentials_path, provider)
    descriptor = os.open(path + ".part", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as f:
        json.dump(tokens, f)
    os.replace(path + ".part", path)


def load_tokens(credentials_path, provider, who):
    """The provider's saved tokens, or an error that says to sign in."""
    try:
        with open(token_file(credentials_path, provider)) as f:
            return json.load(f)
    except (OSError, ValueError):
        raise LispError("%s: not signed in to %s -- sign in with (%s-login creds)" % (who, provider, provider.lower()))


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

def name_value_pairs(parameters, who):
    """A list of (name . value) pairs, or a hash table, as a Python list of (name, value)."""
    if isinstance(parameters, LispHashTable):
        return list(parameters.table.items())
    pairs = []
    for entry in pairs_to_list(parameters):
        if not isinstance(entry, Pair):
            raise LispError("%s: parameters must be (name . value) pairs, not %r" % (who, entry))
        pairs.append((entry.car, entry.cdr))
    return pairs


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
