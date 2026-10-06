"""FRED data access for the Lisp interpreter: economic data series from
the Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org).

  (fred-table creds ids [:start-date d :end-date d])
                     one series or several, as a table with a row per date
  (fred-series id [api-key start-date end-date cache-hours])
                     one series, as a pair of vectors: (dates . values)

Needs a free FRED API key -- see fred_series() for the three ways to
supply one. The download goes through lisp_http, so it can be cached.
"""

import json
import os
import urllib.parse

from lisp_core import LispDate, LispError, LispVector, NIL, Pair, keyword_options
from lisp_data_common import credential, dated_table, text_list
import lisp_http

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
CACHE_HOURS = 12        # fred-table's; fred-series keeps a download only if asked


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


def fred_series(series_id, api_key=None, start_date=None, end_date=None, cache_hours=None):
    """(fred-series id [api-key start-date end-date cache-hours]) -- one FRED
    series, as (dates-vector . values-vector); see download_series."""
    return download_series(series_id, api_key, start_date, end_date, cache_hours, "fred-series")


def download_series(series_id, api_key, start_date, end_date, cache_hours, who):
    """Fetch one FRED data series and return (dates-vector . values-vector).

    `api_key` may be a literal FRED API key, or the path to a JSON
    credentials file with a "fred_api_key" entry (the same file used for
    tastytrade-* credentials, so both APIs' keys can live in one place).
    It may also be omitted entirely if the FRED_API_KEY environment
    variable is set. A free API key can be requested at
    https://fred.stlouisfed.org/docs/api/api_key.html
    `start_date` / `end_date`, if given, are "YYYY-MM-DD" strings (or
    LispDate values) limiting the observation range; pass '() for either
    to leave it open. `cache_hours`, if given, keeps the download on disk
    for that many hours, as http-get-json does, so running the same
    notebook again doesn't fetch it again.
    """
    if api_key is not None and os.path.exists(str(api_key)):
        api_key = credential(api_key, "fred_api_key", who,
                             "FRED needs one, from https://fred.stlouisfed.org/docs/api/api_key.html")
    if api_key is None:
        api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise LispError(
            "%s: no API key given (pass one, pass the path to a "
            "credentials JSON file with a \"fred_api_key\" entry, or set "
            "the FRED_API_KEY environment variable)" % who)

    params = {
        "series_id": str(series_id),
        "api_key": str(api_key),
        "file_type": "json",
    }
    if start_date is not None and start_date is not NIL:
        params["observation_start"] = (
            start_date.date.isoformat() if isinstance(start_date, LispDate) else str(start_date))
    if end_date is not None and end_date is not NIL:
        params["observation_end"] = (
            end_date.date.isoformat() if isinstance(end_date, LispDate) else str(end_date))

    url = FRED_URL + "?" + urllib.parse.urlencode(params)
    shown_url = url.replace(str(api_key), "...")        # so the API key never shows in an error
    text = lisp_http.as_text(lisp_http.download(url, cache_hours, None, who, shown_url))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise LispError("%s: FRED didn't return valid JSON; it starts: %s" % (who, text[:200]))

    if "observations" not in data:
        raise LispError("%s: %s" % (who, data.get("error_message", "unknown error from FRED")))

    return _parse_fred_observations(data["observations"])


def fred_table(credentials_path, ids, *options):
    """(fred-table creds ids [:start-date d :end-date d]) -- one FRED series,
    or a list or vector of them, by ID ("UNRATE", "DGS10"), as a table: a
    date column, oldest first, and a column for each series, headed by its
    ID, with NaN where a series has no value for a date -- so daily,
    weekly, and monthly series line up by date. All of each series, unless
    :start-date or :end-date (a date, or "YYYY-MM-DD") says otherwise. Each
    download is kept for 12 hours, as the other data functions' are."""
    who = "fred-table"
    options = keyword_options(options, ["start-date", "end-date"], who)
    columns = []
    for series_id in text_list(ids, who, "the series IDs"):
        series = download_series(series_id, credentials_path, options.get("start-date"), options.get("end-date"),
                                 CACHE_HOURS, who)
        values = {date.date: value for date, value in zip(series.car.items, series.cdr.items.tolist())}
        columns.append((series_id, values))
    return dated_table(columns)


BUILTINS = {
    "fred-series": fred_series,
    "fred-table": fred_table,
}
