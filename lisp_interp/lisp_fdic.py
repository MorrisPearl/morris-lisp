"""Bank financial data from the FDIC, for the Lisp interpreter.

Every FDIC-insured bank files a Call Report each quarter: its balance sheet,
income, loans, deposits, and capital. The FDIC publishes them, with ratios
it works out (return on assets, net interest margin, ...), through its
BankFind API (https://api.fdic.gov/banks/docs/), back to 1984. These
builtins put them in tables:

  (fdic-find-bank creds name)              banks whose names match, with their
                                           certificate numbers
  (fdic-balance-sheet creds bank [:period :count :in-millions])
  (fdic-income-statement creds bank [...])
  (fdic-ratios creds bank [...])
  (fdic-financials creds bank [:period :count])   all of it, a row per period
  (fdic-get creds dataset [parameters])    any of the FDIC's datasets: failures,
                                           branch locations, history, ...
  (fdic-fields creds dataset [search])     what the fields of a dataset mean

A bank is its FDIC certificate number (Wells Fargo Bank is 3511), or a name
that matches just one bank that's open now. The data is for each insured
bank, not its holding company: Wells Fargo Bank, N.A., not Wells Fargo &
Company.

The FDIC reports dollar amounts in thousands; these give them in dollars
(or, for the statements, in millions). Ratios are percents, as the FDIC
gives them: 1.46 means 1.46%. Income in a Call Report is for the year to
date; a quarter's is the FDIC's quarterly figure, where it has one, or the
year to date less the year to date at the end of the quarter before. A
year is the four quarters to December 31, every bank's fiscal year in a
Call Report.

The credentials file's "fdic_api_key" entry is sent with each request, if
it has one. Downloads are kept for 12 hours (in lisp_http's cache).
"""

import json
import urllib.parse

from lisp_core import LispDate, LispError, LispString, NIL, Pair, keyword_options, pairs_to_list
from lisp_data_common import credential, records_table
from lisp_tables import column_vector, make_table_value
import lisp_http

API_URL = "https://api.fdic.gov/banks/"
DOCS_URL = "https://api.fdic.gov/banks/docs/"
CACHE_HOURS = 12

# Each dataset of the API, and the file that describes its fields.
DATASETS = {
    "financials": "risview_properties.yaml", "institutions": "institution_properties.yaml",
    "failures": "failure_properties.yaml", "locations": "location_properties.yaml",
    "history": "history_properties.yaml", "summary": "summary_properties.yaml",
    "sod": "sod_properties.yaml", "demographics": "demographics_properties.yaml",
}


# ---------------------------------------------------------------------------
# The items of the normalized reports
# ---------------------------------------------------------------------------
# Each is (key, label, report, kind, field, quarterly-field):
#   kind "balance"   dollars (in thousands, from the FDIC) at the end of the quarter
#        "income"    dollars for the year to date; quarterly-field, if there is one,
#                    is the FDIC's figure for the quarter alone
#        "ratio"     a percent: for the year to date (annualized), or, from
#                    quarterly-field, for the quarter alone; or, with no
#                    quarterly-field, at the end of the quarter
#        "count"     a number of people

LINE_ITEMS = [
    ("cash", "Cash and due from banks", "balance", "balance", "CHBAL", None),
    ("securities", "Securities", "balance", "balance", "SC", None),
    ("fed-funds-sold", "Fed funds sold and reverse repos", "balance", "balance", "FREPO", None),
    ("gross-loans", "Loans and leases", "balance", "balance", "LNLSGR", None),
    ("loan-loss-allowance", "Allowance for credit losses", "balance", "balance", "LNATRES", None),
    ("net-loans", "Net loans and leases", "balance", "balance", "LNLSNET", None),
    ("total-assets", "Total assets", "balance", "balance", "ASSET", None),
    ("total-deposits", "Total deposits", "balance", "balance", "DEP", None),
    ("insured-deposits", "Insured deposits (estimated)", "balance", "balance", "DEPINS", None),
    ("uninsured-deposits", "Uninsured deposits (estimated)", "balance", "balance", "DEPUNA", None),
    ("brokered-deposits", "Brokered deposits", "balance", "balance", "BRO", None),
    ("fed-funds-purchased", "Fed funds purchased and repos", "balance", "balance", "FREPP", None),
    ("other-borrowings", "Other borrowed money", "balance", "balance", "OTHBOR", None),
    ("total-liabilities", "Total liabilities", "balance", "balance", "LIAB", None),
    ("equity", "Equity capital", "balance", "balance", "EQ", None),
    ("real-estate-loans", "Real estate loans", "balance", "balance", "LNRE", None),
    ("residential-loans", "  1-4 family residential", "balance", "balance", "LNRERES", None),
    ("multifamily-loans", "  Multifamily", "balance", "balance", "LNREMULT", None),
    ("construction-loans", "  Construction and land development", "balance", "balance", "LNRECONS", None),
    ("commercial-real-estate-loans", "  Nonfarm nonresidential", "balance", "balance", "LNRENRES", None),
    ("commercial-loans", "Commercial and industrial loans", "balance", "balance", "LNCI", None),
    ("consumer-loans", "Consumer loans", "balance", "balance", "LNCON", None),
    ("agricultural-loans", "Agricultural loans", "balance", "balance", "LNAG", None),

    ("interest-income", "Interest income", "income", "income", "INTINC", None),
    ("interest-expense", "Interest expense", "income", "income", "EINTEXP", None),
    ("net-interest-income", "Net interest income", "income", "income", "NIM", "NIMQ"),
    ("noninterest-income", "Noninterest income", "income", "income", "NONII", "NONIIQ"),
    ("noninterest-expense", "Noninterest expense", "income", "income", "NONIX", "NONIXQ"),
    ("provision", "Provision for credit losses", "income", "income", "ELNATR", None),
    ("pretax-income", "Income before taxes", "income", "income", "PTAXNETINC", "PTAXNETINCQ"),
    ("income-taxes", "Income taxes", "income", "income", "ITAX", "ITAXQ"),
    ("net-income", "Net income", "income", "income", "NETINC", "NETINCQ"),
    ("net-charge-offs", "Net charge-offs", "income", "income", "NTLNLS", "NTLNLSQ"),

    ("return-on-assets", "Return on assets", "ratios", "ratio", "ROA", "ROAQ"),
    ("return-on-equity", "Return on equity", "ratios", "ratio", "ROE", "ROEQ"),
    ("net-interest-margin", "Net interest margin", "ratios", "ratio", "NIMY", "NIMYQ"),
    ("efficiency-ratio", "Efficiency ratio", "ratios", "ratio", "EEFFR", "EEFFQR"),
    ("net-charge-off-rate", "Net charge-offs / loans", "ratios", "ratio", "NTLNLSR", "NTLNLSQR"),
    ("noncurrent-loan-rate", "Noncurrent loans / loans", "ratios", "ratio", "NCLNLSR", None),
    ("loans-to-deposits", "Net loans / deposits", "ratios", "ratio", "LNLSDEPR", None),
    ("equity-to-assets", "Equity / assets", "ratios", "ratio", "EQV", None),
    ("leverage-ratio", "Tier 1 leverage ratio", "ratios", "ratio", "RBC1AAJ", None),
    ("cet1-ratio", "Common equity tier 1 ratio", "ratios", "ratio", "RBCT1CER", None),
    ("total-capital-ratio", "Total risk-based capital ratio", "ratios", "ratio", "RBCRWAJ", None),
    ("employees", "Full-time employees", "ratios", "count", "NUMEMP", None),
]

REPORT_NAMES = {"balance": "fdic-balance-sheet", "income": "fdic-income-statement", "ratios": "fdic-ratios"}


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def fdic_request(credentials_path, dataset, params, who):
    """One request to the API: its JSON answer, as Python data."""
    key = credential(credentials_path, "fdic_api_key", who)
    query = dict(params, **({"api_key": key} if key else {}))
    url = API_URL + dataset + "?" + urllib.parse.urlencode(query)
    shown_url = url.replace(str(key), "...") if key else url        # so the key never shows in an error
    text = lisp_http.as_text(lisp_http.download(url, CACHE_HOURS, None, who, shown_url))
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        raise LispError("%s: the FDIC didn't answer with JSON; it starts: %s" % (who, text[:200]))
    if "data" not in answer:
        raise LispError("%s: %s" % (who, answer.get("message") or answer.get("error") or text[:200]))
    return answer


def fdic_records(credentials_path, dataset, params, who):
    """Every record the request matches -- as many requests as that takes,
    the API giving at most 10,000 at a time (500 when asking for every
    field) -- as a list of dicts. If params gives a limit, just that many."""
    params = dict(params)
    if "limit" in params:
        return [r["data"] for r in fdic_request(credentials_path, dataset, params, who)["data"]]
    page = 10000 if "fields" in params else 500
    records = []
    while True:
        answer = fdic_request(credentials_path, dataset, dict(params, limit=page, offset=len(records)), who)
        records.extend(r["data"] for r in answer["data"])
        if not answer["data"] or len(records) >= answer["meta"]["total"]:
            return records


# ---------------------------------------------------------------------------
# Banks
# ---------------------------------------------------------------------------

BANK_FIELDS = "CERT,NAME,CITY,STALP,ASSET,ACTIVE,NAMEHCR,REPDTE"


def find_banks(credentials_path, name, who):
    """The institutions whose names (now or before) match name, largest
    first, as dicts."""
    return fdic_records(credentials_path, "institutions",
                        {"search": "NAME:%s" % str(name), "fields": BANK_FIELDS,
                         "sort_by": "ASSET", "sort_order": "DESC", "limit": 100}, who)


def bank_cert(credentials_path, bank, who):
    """The certificate number of a bank: given as a number, or as a name
    that matches just one bank open now (or one exactly)."""
    if isinstance(bank, (int, float)) and not isinstance(bank, bool):
        return int(bank)
    text = str(bank).strip()
    if text.isdigit():
        return int(text)
    open_now = [b for b in find_banks(credentials_path, text, who) if b.get("ACTIVE") == 1]
    exact = [b for b in open_now if b["NAME"].lower() == text.lower()]
    if len(exact) == 1 or len(open_now) == 1:
        return int((exact or open_now)[0]["CERT"])
    if not open_now:
        raise LispError("%s: no bank open now has a name like %s -- (fdic-find-bank creds name) "
                        "finds closed ones too" % (who, text))
    choices = "; ".join("%s, %s %s: %s" % (b["NAME"], b.get("CITY", ""), b.get("STALP", ""), b["CERT"])
                        for b in open_now[:8])
    raise LispError("%s: %d banks have names like %s -- give the certificate number of one: %s"
                    % (who, len(open_now), text, choices))


def fdic_find_bank(credentials_path, name):
    """(fdic-find-bank creds name) -- the banks, open or closed, whose names
    (now or before) match name, largest first: a table of cert (the
    certificate number), name, city, state, total-assets (in dollars, at
    the last report), active (1 if open), holding-company, and
    last-report."""
    banks = find_banks(credentials_path, name, "fdic-find-bank")

    def column(field, convert=lambda v: v):
        return column_vector([None if b.get(field) is None else convert(b[field]) for b in banks])
    return make_table_value([
        ("cert", column("CERT", int)), ("name", column("NAME", LispString)),
        ("city", column("CITY", LispString)), ("state", column("STALP", LispString)),
        ("total-assets", column("ASSET", lambda v: v * 1000)), ("active", column("ACTIVE")),
        ("holding-company", column("NAMEHCR", LispString)), ("last-report", column("REPDTE", report_date)),
    ])


# ---------------------------------------------------------------------------
# Call Report data, quarter by quarter
# ---------------------------------------------------------------------------

def report_date(text):
    """A report date -- given as YYYYMMDD in the financials, MM/DD/YYYY in
    the institutions -- as a Lisp date."""
    text = str(text)
    if "/" in text:
        month, day, year = text.split("/")
        return LispDate(int(year), int(month), int(day))
    return LispDate(int(text[:4]), int(text[4:6]), int(text[6:8]))


def bank_quarters(credentials_path, bank, who):
    """Every quarter's report for the bank, newest first: a list of dicts,
    with the fields of LINE_ITEMS."""
    cert = bank_cert(credentials_path, bank, who)
    fields = ["REPDTE", "NAME"] + sorted({f for item in LINE_ITEMS for f in item[4:] if f})
    quarters = fdic_records(credentials_path, "financials",
                            {"filters": "CERT:%d" % cert, "fields": ",".join(fields),
                             "sort_by": "REPDTE", "sort_order": "DESC"}, who)
    if not quarters:
        raise LispError("%s: the FDIC has no reports for certificate number %d" % (who, cert))
    return quarters


def quarter_before(date_text):
    """The report date of the quarter before, in the same calendar year, or
    None for a first quarter: 20240630 -> 20240331."""
    month_day = {"0630": "0331", "0930": "0630", "1231": "0930"}.get(date_text[4:])
    return date_text[:4] + month_day if month_day else None


def item_value(item, report, by_date, quarterly):
    """One item's value in one report: dollars (not thousands), or a percent,
    or a count. For a quarter, income is the quarter's alone."""
    key, label, statement, kind, field, quarterly_field = item
    if quarterly and quarterly_field:
        value = report.get(quarterly_field)
    elif quarterly and kind == "income":
        value = report.get(field)
        before = quarter_before(report["REPDTE"])
        if value is not None and before is not None:
            earlier = by_date.get(before, {}).get(field)
            value = None if earlier is None else value - earlier
    else:
        value = report.get(field)
    if value is None:
        return None
    return value * 1000 if kind in ("balance", "income") else value


def chosen_reports(credentials_path, bank, options, who):
    """The reports for the periods asked for: (reports newest first, a
    dict of every report by date, whether they're quarters)."""
    period = str(options.get("period", "quarterly"))
    if period not in ("quarterly", "annual"):
        raise LispError('%s: :period is "quarterly" or "annual", not %s' % (who, period))
    count = options.get("count", 8 if period == "quarterly" else 5)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise LispError("%s: :count is a whole number of periods, 1 or more" % who)
    quarters = bank_quarters(credentials_path, bank, who)
    by_date = {q["REPDTE"]: q for q in quarters}
    reports = quarters if period == "quarterly" else [q for q in quarters if q["REPDTE"].endswith("1231")]
    return reports[:count], by_date, period == "quarterly"


def report_table(credentials_path, bank, report, options):
    """One report laid out as a statement: a row per item, a column per
    period (newest first), and a column saying what the numbers are."""
    who = REPORT_NAMES[report]
    options = keyword_options(options, ["period", "count", "in-millions"], who)
    reports, by_date, quarterly = chosen_reports(credentials_path, bank, options, who)
    in_millions = options.get("in-millions", True) is not False
    items = [item for item in LINE_ITEMS if item[2] == report]
    units = {"balance": "$ millions" if in_millions else "$", "income": "$ millions" if in_millions else "$",
             "ratio": "percent", "count": "people"}

    def shown(item, value):
        if value is not None and in_millions and item[3] in ("balance", "income"):
            return value / 1e6
        if value is not None and item[3] == "ratio":
            return round(value, 2)              # the FDIC gives many more digits than mean anything
        return value
    columns = [("item", column_vector([LispString(item[1]) for item in items]))]
    for r in reports:
        date = report_date(r["REPDTE"]).date.isoformat()
        columns.append((date, column_vector([shown(item, item_value(item, r, by_date, quarterly)) for item in items])))
    columns.append(("unit", column_vector([LispString(units[item[3]]) for item in items])))
    columns.append(("field", column_vector([LispString(item[5] if quarterly and item[5] else item[4]) for item in items])))
    return make_table_value(columns)


def fdic_balance_sheet(credentials_path, bank, *options):
    """(fdic-balance-sheet creds bank [:period "quarterly" :count 8
    :in-millions #t]) -- the bank's balance sheet, with its loans by type: a
    row per item and a column per report date, newest first. :period
    "annual" for year ends; :count how many periods (8 quarters or 5 years
    unless given); amounts in millions unless :in-millions is #f."""
    return report_table(credentials_path, bank, "balance", options)


def fdic_income_statement(credentials_path, bank, *options):
    """(fdic-income-statement creds bank [...]) -- the bank's income, for
    each quarter (or year), laid out as fdic-balance-sheet does."""
    return report_table(credentials_path, bank, "income", options)


def fdic_ratios(credentials_path, bank, *options):
    """(fdic-ratios creds bank [...]) -- the FDIC's ratios for the bank, in
    percent: profitability for the quarter (or year), annualized; loan
    quality; and capital."""
    return report_table(credentials_path, bank, "ratios", options)


def fdic_financials(credentials_path, bank, *options):
    """(fdic-financials creds bank [:period "quarterly" :count 8]) -- every
    item, a row per period (oldest first) and a column per item, in
    dollars and percents: the form to use them in, with the table and
    vector functions."""
    who = "fdic-financials"
    options = keyword_options(options, ["period", "count"], who)
    reports, by_date, quarterly = chosen_reports(credentials_path, bank, options, who)
    reports = list(reversed(reports))
    columns = [("report-date", column_vector([report_date(r["REPDTE"]) for r in reports])),
               ("name", column_vector([LispString(r.get("NAME") or "") for r in reports]))]
    for item in LINE_ITEMS:
        columns.append((item[0], column_vector([item_value(item, r, by_date, quarterly) for r in reports])))
    return make_table_value(columns)


# ---------------------------------------------------------------------------
# Any dataset, and what its fields mean
# ---------------------------------------------------------------------------

def dataset_name(dataset, who):
    name = str(dataset).strip().strip("/").lower()
    if name not in DATASETS:
        raise LispError("%s: there's no dataset %s -- they're %s" % (who, dataset, ", ".join(DATASETS)))
    return name


def request_parameters(parameters, who):
    """Parameters, as a list of (name . value) pairs or '(), as a dict."""
    if parameters is NIL or parameters is None:
        return {}
    result = {}
    for entry in pairs_to_list(parameters):
        if not isinstance(entry, Pair):
            raise LispError("%s: parameters must be (name . value) pairs, not %r" % (who, entry))
        result[str(entry.car)] = str(entry.cdr)
    return result


def fdic_get(credentials_path, dataset, parameters=NIL):
    """(fdic-get creds dataset [parameters]) -- the records of one of the
    FDIC's datasets ("financials", "institutions", "failures", "locations",
    "history", "summary", "sod", "demographics") that the parameters ask
    for -- a list of (name . value) pairs: "filters", "fields", "sort_by",
    "search", ... as the API takes them -- as a table, a column per field.
    Every matching record, unless "limit" is given."""
    who = "fdic-get"
    records = fdic_records(credentials_path, dataset_name(dataset, who),
                           request_parameters(parameters, who), who)
    return records_table(records)


def fdic_fields(credentials_path, dataset, search=NIL):
    """(fdic-fields creds dataset [search]) -- what the fields of one of the
    FDIC's datasets are: a table of field, title, and description, with
    only the fields whose name or title has search in it, if it's given."""
    who = "fdic-fields"
    try:
        import yaml
    except ImportError:
        raise LispError("%s: needs the yaml package (pip install pyyaml) to read the FDIC's field lists" % who)
    name = dataset_name(dataset, who)
    text = lisp_http.as_text(lisp_http.download(DOCS_URL + DATASETS[name], 24 * 30, None, who))
    properties = yaml.safe_load(text)["properties"]["data"]["properties"]
    wanted = None if search is NIL or search is None else str(search).lower()
    rows = [(field, str(p.get("title") or ""), " ".join(str(p.get("description") or "").split()))
            for field, p in properties.items()
            if wanted is None or wanted in field.lower() or wanted in str(p.get("title") or "").lower()]
    return make_table_value([
        ("field", column_vector([LispString(r[0]) for r in rows])),
        ("title", column_vector([LispString(r[1]) for r in rows])),
        ("description", column_vector([LispString(r[2]) for r in rows])),
    ])


BUILTINS = {
    "fdic-find-bank": fdic_find_bank,
    "fdic-balance-sheet": fdic_balance_sheet,
    "fdic-income-statement": fdic_income_statement,
    "fdic-ratios": fdic_ratios,
    "fdic-financials": fdic_financials,
    "fdic-get": fdic_get,
    "fdic-fields": fdic_fields,
}
