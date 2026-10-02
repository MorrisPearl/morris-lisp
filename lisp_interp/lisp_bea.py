"""Bureau of Economic Analysis data, for the Lisp interpreter.

The BEA's API (https://apps.bea.gov/api/) has the national accounts -- GDP
and its parts, personal income and spending, saving, prices (the PCE
price index), corporate profits -- in its NIPA tables, quarterly, monthly,
and yearly; and regional accounts: GDP, personal income, and price levels
for every state, county, and metro area. It also has international trade
and investment, GDP by industry, and more. These builtins put them in
tables:

  (bea-series creds names [:start-year :end-year :frequency])
                                       headline series by short name, such as
                                       "real-gdp-growth": a row per date
  (bea-names)                          the short names
  (bea-nipa creds table [:frequency :start-year :end-year :lines])
                                       any NIPA table: a row per date, a
                                       column per line
  (bea-nipa-lines creds table)         a NIPA table's lines
  (bea-regional creds table line geography [:start-year :end-year])
                                       a regional statistic: a row per place,
                                       a column per year (or quarter)
  (bea-regional-lines creds table)     a regional table's statistics
  (bea-get creds dataset parameters)   any dataset, as the API gives it
  (bea-datasets creds), (bea-parameters creds dataset),
  (bea-parameter-values creds dataset parameter [search])
                                       what there is to ask for

The credentials file's "bea_api_key" entry is sent with each request; it
never appears in an error message (the BEA's own answers repeat it, so
they're cleaned of it first). Data is kept for 12 hours, and the lists of
datasets, parameters, and their values for 30 days (in lisp_http's cache).
"""

import datetime
import json
import math
import urllib.parse

from lisp_core import LispError, LispString, LispVector, NIL, Pair, pairs_to_list
from lisp_data_common import credential, dated_table, records_table, text_list, year_range
from lisp_stratify import keyword_options
from lisp_tables import column_vector, make_table_value
import lisp_http

API_URL = "https://apps.bea.gov/api/data"
DATA_CACHE_HOURS = 12
LIST_CACHE_HOURS = 24 * 30

# Short names for some of the national accounts' headline series. Amounts
# are in billions of dollars, at seasonally adjusted annual rates, as the
# BEA's tables show them. A series published monthly is in one table, and
# quarterly and yearly in another (with the same line numbers).


def quarterly(table, line):
    """Where a series published quarterly and yearly is: frequency -> (table, line)."""
    return {"Q": (table, line), "A": (table, line)}


def monthly(monthly_table, quarterly_table, line):
    """Where a series published monthly, quarterly, and yearly is."""
    return {"M": (monthly_table, line), "Q": (quarterly_table, line), "A": (quarterly_table, line)}


# (name, its usual frequency, where it is, what it is)
NAMES = [
    ("gdp", "Q", quarterly("T10105", 1), "Gross domestic product, billions of dollars"),
    ("real-gdp", "Q", quarterly("T10106", 1), "Real GDP, billions of chained (2017) dollars"),
    ("real-gdp-growth", "Q", quarterly("T10101", 1),
     "Real GDP, percent change from the period before (at an annual rate, for a quarter)"),
    ("gdp-price-index", "Q", quarterly("T10104", 1), "GDP price index, 2017 = 100"),
    ("pce", "M", monthly("T20600", "T20100", 29), "Personal consumption expenditures, billions of dollars"),
    ("pce-price-index", "M", monthly("T20804", "T20304", 1), "PCE price index, 2017 = 100"),
    ("core-pce-price-index", "M", monthly("T20804", "T20304", 25),
     "PCE price index excluding food and energy, 2017 = 100"),
    ("personal-income", "M", monthly("T20600", "T20100", 1), "Personal income, billions of dollars"),
    ("disposable-income", "M", monthly("T20600", "T20100", 27), "Disposable personal income, billions of dollars"),
    ("real-disposable-income", "M", monthly("T20600", "T20100", 37),
     "Real disposable personal income, billions of chained (2017) dollars"),
    ("personal-saving-rate", "M", monthly("T20600", "T20100", 35),
     "Personal saving, percent of disposable personal income"),
    ("corporate-profits", "Q", quarterly("T61600D", 1),
     "Corporate profits with inventory valuation and capital consumption adjustments, billions of dollars"),
]
NAMED = {name: (usual, where) for name, usual, where, _ in NAMES}
FREQUENCIES = {"A": "annual", "Q": "quarterly", "M": "monthly"}


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def error_text(error):
    """What the BEA's error says: its description, and any detail."""
    detail = error.get("ErrorDetail") or {}
    text = error.get("APIErrorDescription", "an error")
    if isinstance(detail, dict) and detail.get("Description"):
        text += " " + detail["Description"]
    return text


def bea_request(credentials_path, params, cache_hours, who):
    """One request to the API: its "Results", as Python data. The key goes on
    the request but never into an error message."""
    key = credential(credentials_path, "bea_api_key", who,
                     "the BEA needs one, from https://apps.bea.gov/API/signup/")
    query = dict(params, UserID=key, ResultFormat="JSON")
    url = API_URL + "?" + urllib.parse.urlencode(query)
    shown_url = url.replace(key, "...")
    text = lisp_http.as_text(lisp_http.download(url, cache_hours, None, who, shown_url)).replace(key, "...")
    try:
        answer = json.loads(text).get("BEAAPI", {})
    except (json.JSONDecodeError, AttributeError):
        raise LispError("%s: the BEA didn't answer with data; it says: %s" % (who, " ".join(text.split())[:300]))
    results = answer.get("Results") or {}
    if isinstance(results, list):              # (some answers are a list of one)
        results = results[0] if results else {}
    error = answer.get("Error") or results.get("Error")
    if error:
        raise LispError("%s: the BEA says: %s" % (who, error_text(error)))
    return results


def data_records(credentials_path, params, who):
    """The data records a GetData request gives (a list of dicts)."""
    records = bea_request(credentials_path, dict(params, method="GetData"), DATA_CACHE_HOURS, who).get("Data", [])
    if not records:
        raise LispError("%s: the BEA has no data for that" % who)
    return records


def number_of(text):
    """A value as the BEA writes it -- "31,906,274" -- as a number (a whole
    number, if it's written as one); NaN for the ones it marks as not
    available, such as "(NA)" or "(D)"."""
    text = str(text).replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return math.nan
    return int(number) if "." not in text and number.is_integer() else number


def period_date(text):
    """The date a period starts: "2026Q2" is April 1, "2026M03" March 1,
    "2026" January 1."""
    year = int(text[:4])
    if "Q" in text:
        return datetime.date(year, 3 * (int(text.split("Q")[1]) - 1) + 1, 1)
    if "M" in text:
        return datetime.date(year, int(text.split("M")[1]), 1)
    return datetime.date(year, 1, 1)


def nipa_value(record):
    """A NIPA record's value, in the units the BEA's tables show: amounts it
    sends in millions (UNIT_MULT 6), in billions."""
    value = number_of(record["DataValue"])
    return value / 1000 if str(record.get("UNIT_MULT")) == "6" else value


def year_list(options, who):
    """The years asked for, as the API takes them ("2017,2018,..."): from
    :start-year to :end-year, the last 10 years if they aren't given."""
    first, last = year_range(options, who)
    return ",".join(str(year) for year in range(first, last + 1))


def frequency_code(value, who):
    code = str(value).upper()[:1]
    if code not in FREQUENCIES:
        raise LispError('%s: :frequency is "A" (annual), "Q" (quarterly), or "M" (monthly)' % who)
    return code


# ---------------------------------------------------------------------------
# The national accounts (NIPA)
# ---------------------------------------------------------------------------

def nipa_records(credentials_path, table, frequency, years, who):
    """A NIPA table's records for the years, at the frequency -- or, if
    frequency is None, quarterly if the table has quarterly data, or else
    monthly, or else annual."""
    last_error = None
    for code in ([frequency] if frequency else ["Q", "M", "A"]):
        try:
            return data_records(credentials_path, {"DataSetName": "NIPA", "TableName": str(table).upper(),
                                                   "Frequency": code, "Year": years}, who)
        except LispError as e:
            last_error = e
    raise last_error


def line_numbers(value, who):
    """:lines -- a line number, or a list or vector of them -- as a set."""
    if isinstance(value, Pair):
        numbers = pairs_to_list(value)
    elif isinstance(value, LispVector):
        numbers = value.items.tolist()
    else:
        numbers = [value]
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in numbers):
        raise LispError("%s: :lines is a line number, or a list of them (see bea-nipa-lines)" % who)
    return {int(n) for n in numbers}


def bea_nipa(credentials_path, table, *options):
    """(bea-nipa creds table [:frequency f :start-year y :end-year y :lines
    l]) -- a NIPA table, such as "T10101" (percent change in real GDP): a
    table with a date column and a column for each of its lines (or just
    the line numbers in :lines), headed by the line's description (with
    its line number, if another line has the same description). :frequency
    is "Q", "M", or "A"; without it, quarterly if the table has it, or else
    monthly, or else annual. The last 10 years, unless :start-year or
    :end-year says. Amounts the BEA sends in millions are in billions, as
    its tables show them."""
    who = "bea-nipa"
    options = keyword_options(options, ["frequency", "start-year", "end-year", "lines"], who)
    frequency = frequency_code(options["frequency"], who) if "frequency" in options else None
    records = nipa_records(credentials_path, table, frequency, year_list(options, who), who)
    wanted = line_numbers(options["lines"], who) if "lines" in options else None
    lines = {}                                  # line number -> (description, {date: value})
    for record in records:
        number = int(record["LineNumber"])
        if wanted is None or number in wanted:
            description, values = lines.setdefault(number, (record["LineDescription"], {}))
            values[period_date(record["TimePeriod"])] = nipa_value(record)
    if wanted and not wanted <= set(lines):
        raise LispError("%s: table %s has no line %s with data (see bea-nipa-lines)"
                        % (who, table, ", ".join(str(n) for n in sorted(wanted - set(lines)))))
    descriptions = [description for description, _ in lines.values()]
    columns = []
    for number in sorted(lines):
        description, values = lines[number]
        heading = description if descriptions.count(description) == 1 else "%s (line %d)" % (description, number)
        columns.append((heading, values))
    return dated_table(columns)


def bea_nipa_lines(credentials_path, table, *options):
    """(bea-nipa-lines creds table [:frequency f]) -- a NIPA table's lines: a
    table of line, description, series-code (the BEA's code for the
    series), unit (as the BEA gives it, such as "Level" or "Percent change,
    annual rate"), and scale ("billions" for amounts it sends in millions,
    which bea-nipa gives in billions; "thousands"; or nothing). The lines
    are those with data in the last two years (at the frequency, or as
    bea-nipa picks it)."""
    who = "bea-nipa-lines"
    options = keyword_options(options, ["frequency"], who)
    frequency = frequency_code(options["frequency"], who) if "frequency" in options else None
    this_year = datetime.date.today().year
    records = nipa_records(credentials_path, table, frequency, "%d,%d" % (this_year - 1, this_year), who)
    lines = {}
    for record in records:
        lines.setdefault(int(record["LineNumber"]), record)
    scales = {"6": "billions", "3": "thousands"}
    rows = [(number, r["LineDescription"], r["SeriesCode"], r.get("CL_UNIT", ""),
             scales.get(str(r.get("UNIT_MULT")), "")) for number, r in sorted(lines.items())]
    return make_table_value([
        ("line", column_vector([r[0] for r in rows])),
        ("description", column_vector([LispString(r[1]) for r in rows])),
        ("series-code", column_vector([LispString(r[2]) for r in rows])),
        ("unit", column_vector([LispString(r[3]) for r in rows])),
        ("scale", column_vector([LispString(r[4]) for r in rows])),
    ])


def bea_series(credentials_path, names, *options):
    """(bea-series creds names [:start-year y :end-year y :frequency f]) --
    headline series by their short names (see bea-names): a table with a
    date column and a column for each, oldest first, NaN where one has no
    value (so monthly and quarterly series line up by date). Each comes at
    its usual frequency, unless :frequency says ("A" for annual, "Q", or
    "M"; GDP isn't published monthly). The last 10 years, unless
    :start-year or :end-year says."""
    who = "bea-series"
    options = keyword_options(options, ["start-year", "end-year", "frequency"], who)
    wanted = [name.lower() for name in text_list(names, who, "the names")]
    for name in wanted:
        if name not in NAMED:
            raise LispError("%s: there's no series named %s -- see bea-names, or use bea-nipa for any table"
                            % (who, name))
    years = year_list(options, who)
    records_of = {}                             # (table, frequency) -> the records, one request each
    columns = []
    for name in wanted:
        usual, where = NAMED[name]
        frequency = frequency_code(options["frequency"], who) if "frequency" in options else usual
        if frequency not in where:
            raise LispError("%s: %s isn't published %s -- it's %s" % (who, name, FREQUENCIES[frequency],
                            " and ".join(FREQUENCIES[f] for f in where)))
        table, line = where[frequency]
        if (table, frequency) not in records_of:
            records_of[(table, frequency)] = nipa_records(credentials_path, table, frequency, years, who)
        values = {period_date(r["TimePeriod"]): nipa_value(r)
                  for r in records_of[(table, frequency)] if int(r["LineNumber"]) == line}
        columns.append((name, values))
    return dated_table(columns)


def bea_names():
    """(bea-names) -- the short names bea-series takes: a table of name, its
    usual frequency, the frequencies it's published at, the NIPA table and
    line it comes from (at its usual frequency), and what it is."""
    rows = [(name, FREQUENCIES[usual], ", ".join(FREQUENCIES[f] for f in where), where[usual][0], where[usual][1],
             description) for name, usual, where, description in NAMES]
    return make_table_value([
        ("name", column_vector([LispString(r[0]) for r in rows])),
        ("frequency", column_vector([LispString(r[1]) for r in rows])),
        ("published", column_vector([LispString(r[2]) for r in rows])),
        ("table", column_vector([LispString(r[3]) for r in rows])),
        ("line", column_vector([r[4] for r in rows])),
        ("description", column_vector([LispString(r[5]) for r in rows])),
    ])


# ---------------------------------------------------------------------------
# Regional accounts
# ---------------------------------------------------------------------------

def geography_code(geography, who):
    """Where a regional statistic is for, as the API takes it: "STATE" (every
    state), "COUNTY", "MSA" (metro areas), and the like, as they are; a
    state's abbreviation ("NY") for its counties; or FIPS codes -- a
    state's 2 digits ("36", which the BEA writes "36000"), or 5 for a
    county or metro area -- one, or a list of them."""
    codes = []
    for code in text_list(geography, who, "the geography"):
        code = code.strip()
        if code.isdigit() and len(code) <= 2:
            code = code.zfill(2) + "000"
        elif code.lower() in ("us", "usa", "united states"):
            code = "00000"
        elif code.isalpha():
            code = code.upper()
        codes.append(code)
    return ",".join(codes)


def bea_regional(credentials_path, table, line, geography, *options):
    """(bea-regional creds table line geography [:start-year y :end-year y])
    -- one statistic of a regional table, such as table "SAINC1" line 3 (per
    capita personal income, by state), for each place: a table with a row
    per place -- fips (the BEA's 5-character code: a state's is its FIPS
    code and "000"), name -- then a column for each year (or quarter, for a
    quarterly table), oldest first, and the unit (such as "Dollars" or
    "Thousands of dollars"). The last 5 years with data, unless :start-year
    or :end-year says. See geography_code for the geography."""
    who = "bea-regional"
    options = keyword_options(options, ["start-year", "end-year"], who)
    years = year_list(options, who) if options else "LAST5"
    records = data_records(credentials_path, {"DataSetName": "Regional", "TableName": str(table).upper(),
                                              "LineCode": str(line), "GeoFips": geography_code(geography, who),
                                              "Year": years}, who)
    places = {}                                 # fips -> (name, {period: value}), in the BEA's order
    for record in records:
        name = record["GeoName"].rstrip(" *")      # (a * marks a footnote)
        name, values = places.setdefault(record["GeoFips"], (name, {}))
        values[record["TimePeriod"]] = number_of(record["DataValue"])
    periods = sorted({period for _, values in places.values() for period in values})
    units = sorted({record.get("CL_UNIT", "") for record in records})
    columns = [("fips", column_vector([LispString(fips) for fips in places])),
               ("name", column_vector([LispString(name) for name, _ in places.values()]))]
    for period in periods:
        columns.append((period, column_vector([values.get(period, math.nan) for _, values in places.values()])))
    columns.append(("unit", column_vector([LispString(", ".join(units))] * len(places))))
    return make_table_value(columns)


def bea_regional_lines(credentials_path, table):
    """(bea-regional-lines creds table) -- the statistics (lines) a regional
    table has: a table of line and description."""
    who = "bea-regional-lines"
    results = bea_request(credentials_path, {"method": "GetParameterValuesFiltered", "DataSetName": "Regional",
                                             "TargetParameter": "LineCode", "TableName": str(table).upper()},
                          LIST_CACHE_HOURS, who)
    values = results.get("ParamValue", [])
    return make_table_value([
        ("line", column_vector([int(v["Key"]) if str(v["Key"]).isdigit() else LispString(v["Key"])
                                for v in values])),
        ("description", column_vector([LispString(v.get("Desc", "")) for v in values])),
    ])


# ---------------------------------------------------------------------------
# Anything else
# ---------------------------------------------------------------------------

def bea_get(credentials_path, dataset, parameters=NIL):
    """(bea-get creds dataset [parameters]) -- the data a dataset gives for
    the parameters, a list of (name . value) pairs as the API takes them,
    such as (("TableName" . "T10101") ("Frequency" . "Q") ("Year" . "2025")):
    a table with a column for each field, as the BEA sends them (DataValue
    as a number, not scaled)."""
    who = "bea-get"
    params = {"DataSetName": str(dataset)}
    for entry in pairs_to_list(parameters):
        if not isinstance(entry, Pair):
            raise LispError('%s: the parameters are a list of (name . value) pairs, such as ("Year" . "2025")' % who)
        value = entry.cdr.car if isinstance(entry.cdr, Pair) else entry.cdr
        params[str(entry.car)] = str(value)
    records = data_records(credentials_path, params, who)
    return records_table([dict(r, DataValue=number_of(r["DataValue"])) if "DataValue" in r else r
                          for r in records])


def bea_datasets(credentials_path):
    """(bea-datasets creds) -- the BEA's datasets: a table of name and
    description."""
    results = bea_request(credentials_path, {"method": "GetDataSetList"}, LIST_CACHE_HOURS, "bea-datasets")
    sets = results.get("Dataset", [])
    return make_table_value([
        ("name", column_vector([LispString(d["DatasetName"]) for d in sets])),
        ("description", column_vector([LispString(d.get("DatasetDescription", "")) for d in sets])),
    ])


def bea_parameters(credentials_path, dataset):
    """(bea-parameters creds dataset) -- the parameters a dataset takes: a
    table of name, description, required (#t or #f), multiple (whether it
    takes a list of values, separated by commas), and all (the value that
    means all of them, if there is one)."""
    who = "bea-parameters"
    results = bea_request(credentials_path, {"method": "GetParameterList", "DataSetName": str(dataset)},
                          LIST_CACHE_HOURS, who)
    found = results.get("Parameter", [])
    return make_table_value([
        ("name", column_vector([LispString(p["ParameterName"]) for p in found])),
        ("description", column_vector([LispString(p.get("ParameterDescription", "")) for p in found])),
        ("required", column_vector([str(p.get("ParameterIsRequiredFlag")) == "1" for p in found])),
        ("multiple", column_vector([str(p.get("MultipleAcceptedFlag")) == "1" for p in found])),
        ("all", column_vector([LispString(p.get("AllValue", "")) for p in found])),
    ])


def bea_parameter_values(credentials_path, dataset, parameter, search=NIL):
    """(bea-parameter-values creds dataset parameter [search]) -- the values
    a dataset's parameter can have, such as NIPA's TableName: a table of
    value and description -- only those with search in them, if given."""
    who = "bea-parameter-values"
    results = bea_request(credentials_path, {"method": "GetParameterValues", "DataSetName": str(dataset),
                                             "ParameterName": str(parameter)}, LIST_CACHE_HOURS, who)
    wanted = None if search is NIL else str(search).lower()
    rows = []
    for entry in results.get("ParamValue", []):
        fields = list(entry.values())           # the value first, then its description
        value, description = str(fields[0]), " ".join(str(f) for f in fields[1:])
        if wanted and wanted not in value.lower() and wanted not in description.lower():
            continue
        rows.append((value, description))
    return make_table_value([
        ("value", column_vector([LispString(r[0]) for r in rows])),
        ("description", column_vector([LispString(r[1]) for r in rows])),
    ])


BUILTINS = {
    "bea-series": bea_series,
    "bea-names": bea_names,
    "bea-nipa": bea_nipa,
    "bea-nipa-lines": bea_nipa_lines,
    "bea-regional": bea_regional,
    "bea-regional-lines": bea_regional_lines,
    "bea-get": bea_get,
    "bea-datasets": bea_datasets,
    "bea-parameters": bea_parameters,
    "bea-parameter-values": bea_parameter_values,
}
