"""US Census Bureau data, for the Lisp interpreter.

The Census Bureau's API (https://www.census.gov/data/developers.html) has
some 1,800 datasets: the American Community Survey (ACS) -- population,
income, poverty, education, housing, commuting, and much more, for every
state, county, city, census tract, and zip code -- the decennial census,
population estimates, County Business Patterns, economic indicators, and
others. These builtins put them in tables:

  (census-get creds dataset variables geography [:within :year :predicates])
                                       any dataset, any variables, any places
  (census-profile creds geography [:within :year])
                                       a standard demographic and economic
                                       profile of each place, from the ACS
  (census-variables creds dataset [search] [:year])   what a dataset's variables are
  (census-geographies creds dataset [:year])          the places it covers
  (census-datasets creds [search])                    every dataset there is

A place is given as the Census writes it: "state:*" (every state),
"county:*" with :within "state:36" (every county in New York),
"county:061" with :within "state:36" (one county), "us:1", "place:*",
"tract:*", "zip code tabulation area:10027", ... The places' codes come
back as text -- "36" for New York, "061" for New York County -- since
the leading zeros matter; together they're the FIPS codes the BLS's local
area data (bls-local-area) takes.

The credentials file's "us_census_api_key" entry is sent with each
request, if it has one. Data is kept for 12 hours, and the lists of
variables, places, and datasets for 30 days (in lisp_http's cache).
"""

import datetime
import json
import math
import urllib.parse

from lisp_core import Keyword, LispError, LispString, NIL, keyword_options, pairs_to_list
from lisp_data_common import credential, text_list
from lisp_tables import column_vector, make_table_value
import lisp_http

API_URL = "https://api.census.gov/data/"
CATALOG_URL = "https://api.census.gov/data.json"
DATA_CACHE_HOURS = 12
LIST_CACHE_HOURS = 24 * 30

# The Census writes these in place of a number it doesn't have: for too few
# sample cases, a median at the top or bottom of its range, and so on.
MISSING_VALUES = {-111111111, -222222222, -333333333, -555555555, -666666666, -888888888, -999999999}


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def census_download(credentials_path, url, params, cache_hours, who):
    """The JSON at a Census address, as Python data -- [] if the Census
    found nothing. The key goes on the request but never into an error
    message."""
    key = credential(credentials_path, "us_census_api_key", who)
    query = urllib.parse.urlencode(dict(params, **({"key": key} if key else {})))
    full_url = url + ("?" + query if query else "")
    shown_url = full_url.replace(str(key), "...") if key else full_url
    text = lisp_http.as_text(lisp_http.download(full_url, cache_hours, None, who, shown_url))
    if not text.strip():                   # the Census's answer when nothing matches
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise LispError("%s: the Census didn't answer with data; it says: %s" % (who, " ".join(text.split())[:300]))


def needs_a_year(dataset):
    """Whether a dataset's path starts with a year (or vintage): every one
    except the time series, such as timeseries/eits/... ."""
    return not dataset.startswith("timeseries/")


# The latest year found for each dataset, so it's looked for only once.
_latest_years = {}


def dataset_path(credentials_path, dataset, year, who):
    """The dataset's path in the API, with its year: "acs/acs5" and 2023 is
    "2023/acs/acs5"; with no year, the latest one there's data for."""
    dataset = str(dataset).strip().strip("/")
    if dataset.split("/")[0].isdigit() or not needs_a_year(dataset):
        return dataset
    if year is not NIL:
        return "%d/%s" % (int(year), dataset)
    if dataset not in _latest_years:
        for candidate in range(datetime.date.today().year, datetime.date.today().year - 6, -1):
            try:
                census_download(credentials_path, API_URL + "%d/%s/geography.json" % (candidate, dataset), {},
                                LIST_CACHE_HOURS, who)
                _latest_years[dataset] = candidate
                break
            except LispError:
                continue
        else:
            raise LispError("%s: the Census has no dataset %s in the last few years -- give :year, or see "
                            "census-datasets" % (who, dataset))
    return "%d/%s" % (_latest_years[dataset], dataset)


def cell_value(text, is_code):
    """One value from the Census, which sends every value as text: a number
    as a number -- NaN for one of its codes for no data -- unless it's a
    code (a place's, or a predicate's), or another code with leading zeros
    ("001"), which stays text."""
    if text is None:
        return None
    if is_code or (len(text) > 1 and text.startswith("0") and not text.startswith("0.")):
        return LispString(text)
    try:
        number = float(text)
    except ValueError:
        return LispString(text)
    if number in MISSING_VALUES:
        return math.nan
    return int(number) if number.is_integer() and "." not in text else number


def rows_table(rows, code_columns):
    """The Census's answer -- a header row, then a row per place -- as a
    table, with the code_columns' values kept as text. (A time series
    repeats each predicate asked for as a column; a column comes only
    once.)"""
    header, records = rows[0], rows[1:]
    columns = []
    for j, name in enumerate(header):
        if name in header[:j]:
            continue
        is_code = name in code_columns
        columns.append((name, column_vector([cell_value(r[j], is_code) for r in records])))
    return make_table_value(columns)


def place_names(clauses):
    """The names of the columns that hold places' codes: the levels the
    clauses name -- "state" and "county" for "state:36 county:061", "zip
    code tabulation area" for "zip code tabulation area:10027"."""
    names = set()
    for clause in clauses:
        pieces = clause.split(":")
        names.add(pieces[0].strip())
        for piece in pieces[1:-1]:          # "36 county": one level's value, then the next level's name
            if " " in piece.strip():
                names.add(piece.strip().split(" ", 1)[1].strip())
    return names


def census_query(credentials_path, dataset, variables, geography, options, who):
    """The rows the Census gives for the query -- a list, header first --
    and the names of the columns that hold codes, to keep as text: the
    places' levels, and the predicates (as given, such as an industry's
    code), except time."""
    path = dataset_path(credentials_path, dataset, options.get("year"), who)
    within = text_list(options["within"], who, ":within") if options.get("within", NIL) is not NIL else []
    params = {"get": ",".join(variables), "for": str(geography)}
    if within:
        params["in"] = " ".join(within)
    for entry in pairs_to_list(options.get("predicates", NIL)):
        params[str(entry.car)] = str(entry.cdr)
    rows = census_download(credentials_path, API_URL + path, params, DATA_CACHE_HOURS, who)
    if not rows:
        raise LispError("%s: the Census found nothing for that" % who)
    predicates = {str(entry.car) for entry in pairs_to_list(options.get("predicates", NIL))} - {"time"}
    return rows, place_names([str(geography)] + within) | predicates


# ---------------------------------------------------------------------------
# The builtins
# ---------------------------------------------------------------------------

def census_get(credentials_path, dataset, variables, geography, *options):
    """(census-get creds dataset variables geography [:within w :year y
    :predicates p]) -- the variables (a name, or a list of them, such as
    "B19013_001E" or "group(B19013)") of a dataset (such as "acs/acs5") for
    each place the geography names ("county:*"): a table, a column per
    variable and per place code. :within narrows the places ("state:36",
    or a list of such); :year picks the year (the latest, if not given);
    :predicates is a list of (name . value) pairs for anything else the
    dataset takes, such as ("time" . "from 2020") or ("NAICS2017" . "52"); a
    predicate's column (but time's) holds text, as it was given."""
    who = "census-get"
    options = keyword_options(options, ["within", "year", "predicates"], who)
    rows, codes = census_query(credentials_path, dataset, text_list(variables, who, "the variables"),
                               geography, options, who)
    return rows_table(rows, codes)


# The standard profile: each item is (key, how it's worked out). An item
# that's a single ACS variable is just that; a share is a sum of variables
# divided by another, as a percent.
PROFILE_ITEMS = [
    ("population", "B01003_001E", None),
    ("median-age", "B01002_001E", None),
    ("households", "B11001_001E", None),
    ("median-household-income", "B19013_001E", None),
    ("per-capita-income", "B19301_001E", None),
    ("poverty-rate", ["B17001_002E"], "B17001_001E"),
    ("labor-force-participation", ["B23025_002E"], "B23025_001E"),
    ("unemployment-rate", ["B23025_005E"], "B23025_003E"),
    ("bachelors-degree-or-higher", ["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"], "B15003_001E"),
    ("median-home-value", "B25077_001E", None),
    ("median-gross-rent", "B25064_001E", None),
    ("homeownership-rate", ["B25003_002E"], "B25003_001E"),
    ("vacancy-rate", ["B25002_003E"], "B25002_001E"),
    ("white-non-hispanic", ["B03002_003E"], "B03002_001E"),
    ("black", ["B03002_004E"], "B03002_001E"),
    ("asian", ["B03002_006E"], "B03002_001E"),
    ("hispanic", ["B03002_012E"], "B03002_001E"),
]


def census_profile(credentials_path, geography, *options):
    """(census-profile creds geography [:within w :year y]) -- for each place,
    a standard profile from the ACS 5-year estimates: population, median
    age, households, median household income, per-capita income, median
    home value, and median gross rent; and, as percents, the poverty rate,
    labor force participation, unemployment rate, share with a bachelor's
    degree or more (of those 25 and over), homeownership rate, vacancy
    rate, and the shares white (not Hispanic), Black, Asian, and Hispanic."""
    who = "census-profile"
    options = keyword_options(options, ["within", "year"], who)
    variables = []
    for key, numerator, denominator in PROFILE_ITEMS:
        for name in ([numerator] if isinstance(numerator, str) else numerator) + ([denominator] if denominator else []):
            if name not in variables:
                variables.append(name)
    rows, places = census_query(credentials_path, "acs/acs5", ["NAME"] + variables, geography, options, who)
    header, records = rows[0], rows[1:]

    def number(record, name):
        value = cell_value(record[header.index(name)], False)
        return value if isinstance(value, (int, float)) else math.nan

    def item(record, numerator, denominator):
        if denominator is None:
            return number(record, numerator)
        total = number(record, denominator)
        if not total or math.isnan(total):
            return math.nan
        return round(100.0 * sum(number(record, name) for name in numerator) / total, 2)

    place_columns = [name for name in header if name in places]
    columns = [("name", column_vector([LispString(r[header.index("NAME")]) for r in records]))]
    for name in place_columns:
        columns.append((name, column_vector([LispString(r[header.index(name)]) for r in records])))
    for key, numerator, denominator in PROFILE_ITEMS:
        columns.append((key, column_vector([item(r, numerator, denominator) for r in records])))
    return make_table_value(columns)


def census_variables(credentials_path, dataset, *rest):
    """(census-variables creds dataset [search] [:year y]) -- the variables
    of a dataset: a table of name, label, concept, group, and type, with
    only those whose name, label, or concept has search in it, if given."""
    who = "census-variables"
    search = None
    if rest and not isinstance(rest[0], Keyword):
        search, rest = str(rest[0]).lower(), rest[1:]
    options = keyword_options(rest, ["year"], who)
    path = dataset_path(credentials_path, dataset, options.get("year"), who)
    variables = census_download(credentials_path, API_URL + path + "/variables.json", {},
                                LIST_CACHE_HOURS, who)["variables"]
    rows = []
    for name, v in sorted(variables.items()):
        if name in ("for", "in", "ucgid"):
            continue
        label = " ".join(str(v.get("label", "")).replace("!!", " - ").split())
        concept = str(v.get("concept", ""))
        if ";" in concept:                  # GEO_ID and NAME: the list of every concept there is
            concept = ""
        if search and search not in name.lower() and search not in label.lower() and search not in concept.lower():
            continue
        rows.append((name, label, concept, str(v.get("group", "")), str(v.get("predicateType", ""))))
    return make_table_value([(heading, column_vector([LispString(r[j]) for r in rows]))
                             for j, heading in enumerate(["name", "label", "concept", "group", "type"])])


def census_geographies(credentials_path, dataset, *options):
    """(census-geographies creds dataset [:year y]) -- the kinds of place a
    dataset has data for: a table of each level ("county"), the levels a
    request for it must give with :within ("state"), and which of those may
    be * for all of them ("state": county:* can be :within "state:*",
    every county in the country; a tract's :within needs one state)."""
    who = "census-geographies"
    options = keyword_options(options, ["year"], who)
    path = dataset_path(credentials_path, dataset, options.get("year"), who)
    levels = census_download(credentials_path, API_URL + path + "/geography.json", {},
                             LIST_CACHE_HOURS, who).get("fips", [])
    return make_table_value([
        ("level", column_vector([LispString(g.get("name", "")) for g in levels])),
        ("within", column_vector([LispString(", ".join(g.get("requires") or [])) for g in levels])),
        ("within-may-be-*", column_vector([LispString(", ".join(g.get("wildcard") or [])) for g in levels])),
    ])


def census_datasets(credentials_path, search=NIL):
    """(census-datasets creds [search]) -- every dataset the Census API has:
    a table of its title, its dataset name (to give census-get), its year
    (for census-get's :year; none for a time series), and its description
    -- only those whose title or name has search in it, if given."""
    who = "census-datasets"
    catalog = census_download(credentials_path, CATALOG_URL, {}, LIST_CACHE_HOURS, who)
    wanted = None if search is NIL else str(search).lower()
    rows = []
    for d in catalog.get("dataset", []):
        url = (d.get("distribution") or [{}])[0].get("accessURL", "")
        path = url.split("/data/", 1)[-1]           # "2024/acs/acs5", or "timeseries/eits/resconst"
        name = path.split("/", 1)[1] if path.split("/")[0].isdigit() else path
        title = str(d.get("title", ""))
        if wanted and wanted not in title.lower() and wanted not in name.lower():
            continue
        rows.append((title, name, d.get("c_vintage"), " ".join(str(d.get("description", "")).split())))
    rows.sort(key=lambda r: (r[1], r[2] or 0))      # by name, then year
    return make_table_value([
        ("title", column_vector([LispString(r[0]) for r in rows])),
        ("dataset", column_vector([LispString(r[1]) for r in rows])),
        ("year", column_vector([r[2] for r in rows])),
        ("description", column_vector([LispString(r[3]) for r in rows])),
    ])


BUILTINS = {
    "census-get": census_get,
    "census-profile": census_profile,
    "census-variables": census_variables,
    "census-geographies": census_geographies,
    "census-datasets": census_datasets,
}
