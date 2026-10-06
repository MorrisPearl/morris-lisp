"""Bureau of Labor Statistics data, for the Lisp interpreter.

The BLS's API (https://www.bls.gov/developers/) has the government's
numbers on prices, jobs, and pay: consumer and producer prices (CPI, PPI),
import and export prices, employment and unemployment -- for the country,
each state, each county, and each metro area -- payrolls, hours, and
earnings by industry, job openings and quits, the employment cost index,
and productivity. Each is a series with an ID, such as CUSR0000SA0 for
the CPI; https://www.bls.gov/help/hlpforma.htm explains how the IDs are
made, and the BLS's "Data Finder" (https://data.bls.gov/dataQuery/) finds
them. These builtins put them in tables:

  (bls-series creds series [:start-year :end-year :annual])
                                    series, by ID or by a short name such as
                                    "cpi": a table with a row per date
  (bls-series-info creds series)    what each series is
  (bls-names)                       the short names
  (bls-local-area creds places [:start-year :end-year])
                                    states' or counties' labor force,
                                    employment, and unemployment rate

The credentials file's "bureau_of_labor_statistics_api_key" entry is sent
with each request; without one, the BLS allows fewer series and years
per request, and fewer requests per day. Data is kept for 12 hours (in
lisp_http's cache).
"""

import datetime
import json
import math

from lisp_core import LispError, LispString, LispVector, NIL, Pair, keyword_options, list_to_pairs, pairs_to_list
from lisp_data_common import credential, dated_table, text_list, year_range
from lisp_tables import column_vector, make_table_value
import lisp_http

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CACHE_HOURS = 12
MOST_SERIES = 50         # the most series, and years, the BLS gives in one request
MOST_YEARS = 20

# Short names for some of the series most often wanted: (name, series ID,
# what it is).
NAMES = [
    ("cpi", "CUSR0000SA0", "Consumer prices (CPI-U), all items, seasonally adjusted, index 1982-84 = 100"),
    ("core-cpi", "CUSR0000SA0L1E", "Consumer prices (CPI-U), all items less food and energy, seasonally adjusted"),
    ("cpi-nsa", "CUUR0000SA0", "Consumer prices (CPI-U), all items, not seasonally adjusted"),
    ("cpi-food", "CUSR0000SAF1", "Consumer prices (CPI-U), food, seasonally adjusted"),
    ("cpi-rent", "CUSR0000SEHA", "Consumer prices (CPI-U), rent of primary residence, seasonally adjusted"),
    ("unemployment-rate", "LNS14000000", "Unemployment rate, percent, seasonally adjusted"),
    ("labor-force-participation", "LNS11300000", "Labor force participation rate, percent, seasonally adjusted"),
    ("employment-population-ratio", "LNS12300000", "Employment-population ratio, percent, seasonally adjusted"),
    ("nonfarm-payrolls", "CES0000000001", "All employees, total nonfarm, thousands, seasonally adjusted"),
    ("average-hourly-earnings", "CES0500000003", "Average hourly earnings, all private employees, dollars, "
                                                 "seasonally adjusted"),
    ("average-weekly-hours", "CES0500000002", "Average weekly hours, all private employees, seasonally adjusted"),
    ("job-openings", "JTS000000000000000JOL", "Job openings, total nonfarm, thousands, seasonally adjusted"),
    ("hires", "JTS000000000000000HIL", "Hires, total nonfarm, thousands, seasonally adjusted"),
    ("quits", "JTS000000000000000QUL", "Quits, total nonfarm, thousands, seasonally adjusted"),
    ("ppi-final-demand", "WPSFD4", "Producer prices, final demand, seasonally adjusted, index Nov 2009 = 100"),
    ("employment-cost-index", "CIS1010000000000I", "Employment cost index, total compensation, civilian "
                                                   "workers, seasonally adjusted (quarterly)"),
    ("productivity", "PRS85006092", "Labor productivity, nonfarm business, percent change from the previous "
                                    "quarter at an annual rate (quarterly)"),
    ("import-prices", "EIUIR", "Import prices, all commodities, index 2000 = 100"),
    ("export-prices", "EIUIQ", "Export prices, all commodities, index 2000 = 100"),
]
SERIES_OF_NAME = {name: series_id for name, series_id, _ in NAMES}

# The periods that are a year's average, rather than a month, quarter, or half.
ANNUAL_AVERAGE_PERIODS = {"M13", "Q05", "S03"}


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def bls_request(credentials_path, series_ids, start_year, end_year, who, catalog=False, annual=False):
    """One request: the series the BLS gives back (a list of dicts), for at
    most 50 series and 20 years. The key goes in the request but never
    into an error message."""
    key = credential(credentials_path, "bureau_of_labor_statistics_api_key", who)
    request = {"seriesid": series_ids, "startyear": str(start_year), "endyear": str(end_year)}
    if catalog:
        request["catalog"] = True
    if annual:
        request["annualaverage"] = True
    if key:
        request["registrationkey"] = key
    headers = list_to_pairs([Pair("Content-Type", "application/json")])
    body = json.dumps(request, sort_keys=True).encode()
    text = lisp_http.as_text(lisp_http.download(API_URL, CACHE_HOURS, headers, who, body=body))
    if key:
        text = text.replace(key, "...")
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        raise LispError("%s: the BLS didn't answer with data; it says: %s" % (who, " ".join(text.split())[:300]))
    messages = answer.get("message") or []
    if answer.get("status") != "REQUEST_SUCCEEDED":
        raise LispError("%s: the BLS says: %s" % (who, " ".join(messages) or answer.get("status")))
    bad = [m for m in messages if m.startswith("Invalid Series")]
    if bad:
        raise LispError("%s: the BLS has no such series: %s" % (who, ", ".join(m.split()[-1] for m in bad)))
    return answer.get("Results", {}).get("series", [])


def series_list(series, who):
    """The series asked for -- one, or a list or vector of them -- as
    (heading, series ID) pairs: a short name ("cpi") is its own heading, an
    ID is its."""
    result = []
    for name in text_list(series, who, "the series"):
        if name.lower() in SERIES_OF_NAME:
            result.append((name.lower(), SERIES_OF_NAME[name.lower()]))
        elif name.replace("_", "").isalnum():
            result.append((name.upper(), name.upper()))
        else:
            raise LispError("%s: %r isn't a series ID or one of the short names (see bls-names)" % (who, name))
    return result


def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def period_date(year, period):
    """The date a period starts: M05 is May 1, Q03 July 1, S02 July 1; the
    year itself (A01), or its average, Jan 1."""
    kind, number = period[0], int(period[1:])
    if kind == "M" and number <= 12:
        return datetime.date(year, number, 1)
    if kind == "Q" and number <= 4:
        return datetime.date(year, 3 * (number - 1) + 1, 1)
    if kind == "S" and number <= 2:
        return datetime.date(year, 6 * (number - 1) + 1, 1)
    return datetime.date(year, 1, 1)


def observations(series_ids, start_year, end_year, annual, credentials_path, who):
    """Each series' values, by date: a dict series ID -> {date: value},
    from as many requests as it takes. With annual, just the years'
    averages (and series that are only yearly); otherwise, everything but
    those averages."""
    values = {series_id: {} for series_id in series_ids}
    for some_series in chunks(series_ids, MOST_SERIES):
        for first_year in range(start_year, end_year + 1, MOST_YEARS):
            last_year = min(first_year + MOST_YEARS - 1, end_year)
            for s in bls_request(credentials_path, some_series, first_year, last_year, who, annual=annual):
                for point in s.get("data", []):
                    period = point["period"]
                    is_average = period in ANNUAL_AVERAGE_PERIODS
                    if is_average != annual and period != "A01":      # A01: a series that's only yearly
                        continue
                    try:
                        value = float(point["value"])
                    except ValueError:              # "-" for a value that's missing
                        value = math.nan
                    values[s["seriesID"]][period_date(int(point["year"]), period)] = value
    return values


# ---------------------------------------------------------------------------
# The builtins
# ---------------------------------------------------------------------------

def bls_series(credentials_path, series, *options):
    """(bls-series creds series [:start-year y :end-year y :annual #t]) -- one
    series or a list of them -- IDs, or short names (see bls-names) -- as
    a table: a date column (the first day of each month, quarter, or year)
    and a column for each series, oldest first, NaN where a series has no
    value. The last 10 years, unless :start-year or :end-year says
    otherwise. :annual #t gives the averages for each year instead (for
    the series that have them)."""
    who = "bls-series"
    options = keyword_options(options, ["start-year", "end-year", "annual"], who)
    wanted = series_list(series, who)
    start_year, end_year = year_range(options, who)
    annual = options.get("annual", NIL) not in (NIL, False)
    values = observations(sorted({series_id for _, series_id in wanted}), start_year, end_year, annual,
                          credentials_path, who)
    return dated_table([(heading, values[series_id]) for heading, series_id in wanted])


def bls_series_info(credentials_path, series):
    """(bls-series-info creds series) -- what each series (an ID or short
    name, or a list of them) is: a table of the name given, its series ID,
    its title, its survey, and whether it's seasonally adjusted. Some
    surveys (such as job openings) don't give titles; for a short name,
    its description from bls-names takes the place of a missing title."""
    who = "bls-series-info"
    wanted = series_list(series, who)
    this_year = datetime.date.today().year
    catalogs = {}
    for some_series in chunks(sorted({series_id for _, series_id in wanted}), MOST_SERIES):
        for s in bls_request(credentials_path, some_series, this_year - 1, this_year, who, catalog=True):
            catalogs[s["seriesID"]] = s.get("catalog") or {}
    descriptions = {series_id: description for _, series_id, description in NAMES}
    rows = []
    for heading, series_id in wanted:
        catalog = catalogs.get(series_id, {})
        rows.append((heading, series_id,
                     catalog.get("series_title") or descriptions.get(series_id, ""),
                     catalog.get("survey_name", ""), catalog.get("seasonality", "")))
    return make_table_value([(name, column_vector([LispString(r[j]) for r in rows]))
                             for j, name in enumerate(["name", "series-id", "title", "survey", "seasonality"])])


def bls_names():
    """(bls-names) -- the short names bls-series takes, with each one's
    series ID and what it is."""
    return make_table_value([
        ("name", column_vector([LispString(name) for name, _, _ in NAMES])),
        ("series-id", column_vector([LispString(series_id) for _, series_id, _ in NAMES])),
        ("description", column_vector([LispString(description) for _, _, description in NAMES])),
    ])


# Local Area Unemployment Statistics: the measures, by the code that ends
# each series ID.
LOCAL_AREA_MEASURES = [("labor-force", "06"), ("employed", "05"), ("unemployed", "04"),
                       ("unemployment-rate", "03")]


def place_fips(place, who):
    """A state's FIPS code ("36", from "36" or 36) or a county's ("36061"),
    as text."""
    code = str(int(place)) if isinstance(place, (int, float)) else str(place).strip()
    if code.isdigit() and len(code) <= 2:
        return code.zfill(2)
    if code.isdigit() and len(code) <= 5:
        return code.zfill(5)
    raise LispError("%s: %r isn't a state's FIPS code (2 digits, such as \"36\") or a county's "
                    "(5 digits, such as \"36061\")" % (who, place))


def local_area_series(fips):
    """A place's LAUS series IDs, by measure: "LA", then S if its numbers
    are seasonally adjusted (a state's are; a county's aren't) or U, then
    its 15-character area code, then the measure's code."""
    if len(fips) == 2:
        area, adjusted = "ST" + fips + "0" * 11, True
    else:
        area, adjusted = "CN" + fips + "0" * 8, False
    return {name: "LA" + ("S" if adjusted else "U") + area + measure for name, measure in LOCAL_AREA_MEASURES}


def bls_local_area(credentials_path, places, *options):
    """(bls-local-area creds places [:start-year y :end-year y]) -- the labor
    force, employment, unemployment, and unemployment rate (percent) of a
    state or a county, each month: a table with a row per month. places is
    a state's 2-digit FIPS code ("36") or a county's 5-digit code ("36061")
    -- the codes census-get gives -- or a list or vector of them, which
    gives a row per place per month, with the place's code in a fips
    column first. Up to 12 places come in one request. States' numbers are
    seasonally adjusted; counties' aren't."""
    who = "bls-local-area"
    options = keyword_options(options, ["start-year", "end-year"], who)
    several = isinstance(places, (Pair, LispVector))
    given = pairs_to_list(places) if isinstance(places, Pair) else places.items.tolist() if several else [places]
    codes = list(dict.fromkeys(place_fips(place, who) for place in given))     # (each once, in order)
    series_of = {fips: local_area_series(fips) for fips in codes}
    start_year, end_year = year_range(options, who)
    values = observations(sorted({sid for series in series_of.values() for sid in series.values()}),
                          start_year, end_year, False, credentials_path, who)
    tables = {fips: dated_table([(name, values[sid]) for name, sid in series_of[fips].items()]) for fips in codes}
    empty = [fips for fips in codes if not pairs_to_list(tables[fips])[0].cdr.items.size]
    if empty:
        raise LispError("%s: the BLS has no data for %s" % (who, ", ".join(empty)))
    if not several:
        return tables[codes[0]]
    rows = []                                   # (fips, date, the measures)
    for fips in codes:
        columns = [pair.cdr.items.tolist() for pair in pairs_to_list(tables[fips])]
        rows += [(fips,) + tuple(row) for row in zip(*columns)]
    names = ["fips", "date"] + [name for name, _ in LOCAL_AREA_MEASURES]
    return make_table_value([(name, column_vector([LispString(r[j]) if j == 0 else r[j] for r in rows]))
                             for j, name in enumerate(names)])



BUILTINS = {
    "bls-series": bls_series,
    "bls-series-info": bls_series_info,
    "bls-names": bls_names,
    "bls-local-area": bls_local_area,
}
