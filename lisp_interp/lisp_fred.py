"""FRED data access for the Lisp interpreter: the fred-series builtin,
which downloads one economic data series from the Federal Reserve Bank of
St. Louis (https://fred.stlouisfed.org) and returns it as a pair of
vectors, (dates . values).

Needs a free FRED API key -- see fred_series() for the three ways to
supply one. Uses only the standard library (urllib), no extra packages.
"""

import json
import os
import urllib.parse
import urllib.request

from lisp_core import LispDate, LispError, LispVector, Pair


def _parse_fred_observations(observations):
    """Turn FRED's list of {"date": "...", "value": "..."} dicts into a
    (dates-vector . values-vector) pair, skipping missing observations
    (FRED marks those with a value of ".")."""
    dates = []
    values = []
    for obs in observations:
        value_str = obs.get("value", ".")
        if value_str == ".":
            continue
        try:
            value = float(value_str)
        except (TypeError, ValueError):
            continue
        year, month, day = obs["date"].split("-")
        dates.append(LispDate(int(year), int(month), int(day)))
        values.append(value)
    return Pair(LispVector(dates), LispVector(values))


def _fred_api_key_from_file(path):
    """Load a "fred_api_key" entry out of a JSON credentials file -- the
    same file used for tastytrade-* credentials, so both APIs' keys can
    live in one place (see _tasty_load_credentials)."""
    try:
        with open(str(path)) as f:
            data = json.load(f)
    except OSError as e:
        raise LispError("fred-series: could not open credentials file %r: %s" % (str(path), e))
    except json.JSONDecodeError as e:
        raise LispError("fred-series: credentials file %r isn't valid JSON: %s" % (str(path), e))
    key = data.get("fred_api_key")
    if not key:
        raise LispError(
            "fred-series: credentials file %r has no \"fred_api_key\" entry" % (str(path),))
    return str(key).strip()


def fred_series(series_id, api_key=None, start_date=None, end_date=None):
    """Fetch one FRED data series and return (dates-vector . values-vector).

    `api_key` may be a literal FRED API key, or the path to a JSON
    credentials file with a "fred_api_key" entry (the same file used for
    tastytrade-* credentials, so both APIs' keys can live in one place).
    It may also be omitted entirely if the FRED_API_KEY environment
    variable is set. A free API key can be requested at
    https://fred.stlouisfed.org/docs/api/api_key.html
    `start_date` / `end_date`, if given, are "YYYY-MM-DD" strings (or
    LispDate values) limiting the observation range.
    """
    if api_key is not None and os.path.exists(str(api_key)):
        api_key = _fred_api_key_from_file(api_key)
    if api_key is None:
        api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise LispError(
            "fred-series: no API key given (pass one, pass the path to a "
            "credentials JSON file with a \"fred_api_key\" entry, or set "
            "the FRED_API_KEY environment variable)")

    params = {
        "series_id": str(series_id),
        "api_key": str(api_key),
        "file_type": "json",
    }
    if start_date is not None:
        params["observation_start"] = (
            start_date.date.isoformat() if isinstance(start_date, LispDate) else str(start_date))
    if end_date is not None:
        params["observation_end"] = (
            end_date.date.isoformat() if isinstance(end_date, LispDate) else str(end_date))

    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise LispError("fred-series: request failed: %s" % e)

    if "observations" not in data:
        raise LispError("fred-series: %s" % data.get("error_message", "unknown error from FRED"))

    return _parse_fred_observations(data["observations"])


BUILTINS = {
    "fred-series": fred_series,
}
