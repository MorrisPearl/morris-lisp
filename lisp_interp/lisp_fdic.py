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
  (fdic-loan-losses creds bank)            the loans by type (mortgages, commercial real estate, credit
                                           cards, ...) and how much of each has been lost a year since 2001

A bank is its FDIC certificate number (Wells Fargo Bank is 3511), or a name
that matches just one bank that's open now. The data is for each insured
bank, not its holding company: Wells Fargo Bank, N.A., not Wells Fargo &
Company. (fdic-loan-losses also takes a holding company's name, or a list of
certificate numbers, and adds up its banks.)

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
import re
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


# ---------------------------------------------------------------------------
# A holding company's banks
# ---------------------------------------------------------------------------
# The SEC knows a bank holding company by one name (U.S. BANCORP \DE\) and the FDIC by another (U S BCORP), so names are
# compared by their words, after making the usual abbreviations the same and leaving out the words that say nothing.

SAME_WORDS = {"BANCORP": "BCORP", "BANCORPORATION": "BCORP", "FINANCIAL": "FINL", "SERVICES": "SVC", "SVCS": "SVC",
              "BANCSHARES": "BSHRS", "BANKSHARES": "BKSHRS", "NATIONAL": "NATL", "HOLDINGS": "HLDGS",
              "HOLDING": "HLDG", "BANK": "BK", "BANKING": "BKG", "CORPORATION": "CORP", "COMPANY": "CO",
              "SYSTEMS": "SYS", "SYSTEM": "SYS", "GROUP": "GRP", "INCORPORATED": "INC"}
EMPTY_WORDS = {"THE", "INC", "CORP", "CO", "LTD", "PLC", "AND", "OF", "NEW", "NA"}
STATE_SUFFIX = re.compile(r"\s*[/\\][A-Z]{2,3}[/\\]?\s*$")           # (the SEC's /DE/, \DE\, /MN at the end of a name)


def name_key(name):
    """The words of a company's name that tell it apart, in order: "U.S. BANCORP \\DE\\" and "U S BCORP" are both
    ('BCORP', 'US')."""
    text = str(name).upper()
    while STATE_SUFFIX.search(text):
        text = STATE_SUFFIX.sub("", text)
    text = text.replace("NATIONAL ASSOCIATION", " ").replace("&", " AND ")
    words = [SAME_WORDS.get(word, word) for word in re.findall(r"[A-Z0-9]+", text)]
    words = [word for word in words if word not in EMPTY_WORDS]
    joined = []                         # (single letters run together: U S is US, F N B is FNB)
    previous_single = False
    for word in words:
        single = len(word) == 1
        if single and previous_single:
            joined[-1] += word
        else:
            joined.append(word)
        previous_single = single
    return tuple(sorted(word for word in joined if word not in EMPTY_WORDS))       # (N A is NA)


def open_banks(credentials_path, who):
    """Every bank open now: a list of dicts with CERT, NAME, NAMEHCR (its holding company), RSSDHCR, and ASSET."""
    return fdic_records(credentials_path, "institutions",
                        {"filters": "ACTIVE:1", "fields": "CERT,NAME,NAMEHCR,RSSDHCR,ASSET"}, who)


def banks_of_company(credentials_path, name, who):
    """The banks open now that belong to the company of this name (its holding company has the name, or the bank
    itself has it): a list of (certificate number, bank name), largest first. If two holding companies have names
    alike, the larger one's. Empty if there are none."""
    wanted = name_key(name)
    banks = open_banks(credentials_path, who)
    by_holder = {}
    for bank in banks:
        if bank.get("NAMEHCR") and name_key(bank["NAMEHCR"]) == wanted:
            by_holder.setdefault(bank.get("RSSDHCR"), []).append(bank)
    if by_holder:
        chosen = max(by_holder.values(), key=lambda group: sum(b.get("ASSET") or 0 for b in group))
    else:
        chosen = [bank for bank in banks if name_key(bank["NAME"]) == wanted]
    chosen.sort(key=lambda b: -(b.get("ASSET") or 0))
    return [(int(b["CERT"]), str(b["NAME"])) for b in chosen]


def banks_given(credentials_path, given, who):
    """The banks a function was given: a certificate number, a list of them, or a name -- of a bank open now, or of
    a holding company (all its banks). A list of (certificate number, name)."""
    if isinstance(given, Pair) or given is NIL:
        certs = [int(x) for x in pairs_to_list(given)]
        if not certs:
            raise LispError("%s: the list of certificate numbers is empty" % who)
        return [(cert, "certificate %d" % cert) for cert in certs]
    if isinstance(given, (int, float)) and not isinstance(given, bool) or str(given).strip().isdigit():
        cert = int(str(given).strip()) if not isinstance(given, (int, float)) else int(given)
        return [(cert, "certificate %d" % cert)]
    found = banks_of_company(credentials_path, given, who)
    if found:
        return found
    return [(bank_cert(credentials_path, given, who), str(given))]


# ---------------------------------------------------------------------------
# Loans by type, and their losses
# ---------------------------------------------------------------------------
# Each type of loan: (key, label, the field of its balance, of its net charge-offs for the year to date, of the part
# of it that is noncurrent (90 days or more past due, or not accruing interest), and how much of a defaulted loan of
# this type a lender typically gets back -- a rough figure for a start, not the bank's own: the Call Report doesn't say).
# The types are the Call Report's; "everything else" is what is left of the total (loans to governments, to other
# banks, real estate abroad, ...).

LOAN_TYPES = [
    ("residential", "1-4 family residential mortgages (and home equity lines)", "LNRERES", "NTRERES", "NCRERES", 0.70),
    ("multifamily", "Multifamily (apartment) real estate", "LNREMULT", "NTREMULT", "NCREMULT", 0.65),
    ("construction", "Construction and land development", "LNRECONS", "NTRECONS", "NCRECONS", 0.50),
    ("commercial-real-estate", "Commercial real estate (nonfarm nonresidential)", "LNRENRES", "NTRENRES", "NCRENRES", 0.60),
    ("farmland", "Farmland", "LNREAG", "NTREAG", "NCREAG", 0.65),
    ("commercial", "Commercial and industrial", "LNCI", "NTCI", "NCCI", 0.55),
    ("credit-cards", "Credit cards", "LNCRCD", "NTCRCD", "NCCRCD", 0.10),
    ("auto", "Auto loans", "LNAUTO", "NTAUTO", "NCAUTO", 0.50),
    ("other-consumer", "Other consumer loans", "LNCONOTH", "NTCONOTH", "NCCONOTH", 0.30),
    ("agricultural", "Agricultural (not real estate)", "LNAG", "NTAG", "NCAG", 0.55),
    ("financial-and-other", "Loans to financial companies that are not banks, and other loans", "LNOTHER", "NTOTHER",
     "NCOTHLN", 0.50),
    ("leases", "Leases", "LS", "NTLS", "NCLS", 0.50),
]
EVERYTHING_ELSE = ("everything-else", "Everything else (governments, other banks, real estate abroad, ...)", 0.50)
TOTAL_FIELDS = {"balance": "LNLSGR", "charge-offs": "NTLNLS", "noncurrent": "NCLNLS"}
CAPITAL_FIELDS = {"common-equity": "RBCT1C", "risk-weighted-assets": "RWAJ"}
FIRST_YEAR = 2001                       # the first year of losses (the year before gives its starting loans)
MOST_GROWTH = 2.0                       # a year in which a type's loans grew more than this many times is left out,
LEAST_SHARE = 0.01                      # and one in which they were less than this share of all loans at the start


def year_before(date_text):
    return "%04d%s" % (int(date_text[:4]) - 1, date_text[4:])


class LoanBook:
    """The loans of a bank, or of all of a holding company's banks added up, by type, from every Call Report since
    FIRST_YEAR - 1: balances at a date, net charge-offs in the 12 months to it, and noncurrent loans at it, in dollars;
    and the banks' common equity tier 1 capital and risk-weighted assets."""

    def __init__(self, banks, reports):
        self.banks = banks                         # [(certificate number, name)]
        self.reports = reports                     # date (YYYYMMDD) -> field -> dollars, added up over the banks
        self.latest = max(reports)
        # the periods: the 12 months to the latest report's day of the year, each year back to FIRST_YEAR (the
        # first only for its loans at the end, which start the next one)
        self.period_ends = []
        date = self.latest
        while int(date[:4]) >= FIRST_YEAR - 1 and date in reports:
            self.period_ends.insert(0, date)
            date = year_before(date)
        self.keys = [t[0] for t in LOAN_TYPES] + [EVERYTHING_ELSE[0]]
        self.labels = dict([(t[0], t[1]) for t in LOAN_TYPES] + [EVERYTHING_ELSE[:2]])
        self.recoveries = dict([(t[0], t[5]) for t in LOAN_TYPES] + [(EVERYTHING_ELSE[0], EVERYTHING_ELSE[2])])

    def field(self, name, date):
        return self.reports.get(date, {}).get(name)

    def amount(self, kind, key, date):
        """One type's balance, year-to-date charge-offs, or noncurrent loans at the date (kind is "balance",
        "charge-offs", or "noncurrent"); for everything else, what the types leave of the total."""
        column = {"balance": 2, "charge-offs": 3, "noncurrent": 4}[kind]
        if key == "total":
            return self.field(TOTAL_FIELDS[kind], date)
        if key == EVERYTHING_ELSE[0]:
            total = self.field(TOTAL_FIELDS[kind], date)
            if total is None:
                return None
            return total - sum(self.field(t[column], date) or 0.0 for t in LOAN_TYPES)
        return self.field(next(t[column] for t in LOAN_TYPES if t[0] == key), date)

    def balance(self, key, date):
        return self.amount("balance", key, date)

    def noncurrent(self, key, date):
        return self.amount("noncurrent", key, date)

    def charge_offs(self, key, date):
        """Net charge-offs in the 12 months to the date: the year to date, and the rest of the year before (a Call
        Report's income is for the year to date)."""
        to_date = self.amount("charge-offs", key, date)
        if date.endswith("1231") or to_date is None:
            return to_date
        last_december = "%04d1231" % (int(date[:4]) - 1)
        whole_year, same_part = self.amount("charge-offs", key, last_december), self.amount("charge-offs", key, year_before(date))
        if whole_year is None or same_part is None:
            return None
        return to_date + whole_year - same_part

    def loss_rates(self, key):
        """The type's net charge-offs in each period, over its loans at the end of the period before: a list, one for
        each period after the first. None where there were no loans at the start; where the loans grew more than
        MOST_GROWTH times in the period -- a bank bought, or a new kind of lending begun -- since then the losses are
        mostly on loans that were not there at the start (PNC's credit cards, the year it bought National City); and
        where the type was less than LEAST_SHARE of all the loans at the start, since a few dollars lost on a few dollars
        lent says nothing about a kind of lending that is a large part of the bank today."""
        rates = []
        for before, end in zip(self.period_ends, self.period_ends[1:]):
            loans, lost, loans_after = self.balance(key, before), self.charge_offs(key, end), self.balance(key, end)
            all_loans = self.balance("total", before) or 0.0
            if not loans or loans <= 0 or lost is None or (loans_after or 0) > MOST_GROWTH * loans \
                    or loans < LEAST_SHARE * all_loans:
                rates.append(None)
            else:
                rates.append(lost / loans)
        return rates

    def capital(self, date):
        """(common equity tier 1 capital, risk-weighted assets) at the date, in dollars, or None for either."""
        return self.field(CAPITAL_FIELDS["common-equity"], date), self.field(CAPITAL_FIELDS["risk-weighted-assets"], date)

    def bank_names(self):
        return "; ".join("%s (%d)" % (name, cert) for cert, name in self.banks)


def loan_book(credentials_path, banks, who):
    """The LoanBook of these banks [(certificate number, name)]: every one of their Call Reports, added up date by date."""
    fields = sorted({f for t in LOAN_TYPES for f in t[2:5]} | set(TOTAL_FIELDS.values()) | set(CAPITAL_FIELDS.values()))
    reports = {}
    named = []
    for cert, name in banks:
        records = fdic_records(credentials_path, "financials",
                               {"filters": "CERT:%d" % cert, "fields": ",".join(["REPDTE", "NAME"] + fields),
                                "sort_by": "REPDTE", "sort_order": "DESC"}, who)
        if not records:
            raise LispError("%s: the FDIC has no reports for certificate number %d" % (who, cert))
        named.append((cert, str(records[0].get("NAME") or name)))
        for record in records:
            date = str(record["REPDTE"])
            if int(date[:4]) < FIRST_YEAR - 2:
                continue
            added = reports.setdefault(date, {})
            for field in fields:
                if record.get(field) is not None:
                    added[field] = added.get(field, 0.0) + record[field] * 1000.0        # (the FDIC's are thousands)
    return LoanBook(named, reports)


def fdic_loan_losses(credentials_path, bank):
    """(fdic-loan-losses creds bank) -- a bank's loans by type, from its latest Call Report, and what it has lost on
    each: a table with a row per type (and one for all loans) of type, loans (in millions), share (of all loans),
    noncurrent (the share 90 days or more past due or not accruing interest), losses-last-year (net charge-offs in
    the last 12 months, over the loans a year before), losses-average-5-years, losses-worst-year (since 2001), and
    worst-year (the year it ended). bank is a certificate number, a list of them, the name of a bank open now, or the
    name of a holding company ("KeyCorp"), whose banks are added up."""
    who = "fdic-loan-losses"
    book = loan_book(credentials_path, banks_given(credentials_path, bank, who), who)
    latest = book.latest
    total = book.balance("total", latest) or 0.0
    rows = []
    for key in book.keys + ["total"]:
        rates = book.loss_rates(key)
        known = [(rate, end) for rate, end in zip(rates, book.period_ends[1:]) if rate is not None]
        recent = [rate for rate in rates[-5:] if rate is not None]
        worst = max(known) if known else (None, None)
        loans = book.balance(key, latest)
        noncurrent = book.noncurrent(key, latest)
        rows.append((book.labels.get(key, "All loans"), None if loans is None else loans / 1e6,
                     safe_share(loans, total), safe_share(noncurrent, loans), rates[-1] if rates else None,
                     sum(recent) / len(recent) if recent else None, worst[0],
                     report_date(worst[1]) if worst[1] else None))
    names = ["type", "loans", "share", "noncurrent", "losses-last-year", "losses-average-5-years",
             "losses-worst-year", "worst-year"]
    columns = []
    for n, name in enumerate(names):
        values = [row[n] for row in rows]
        columns.append((name, column_vector([LispString(v) if n == 0 else v for v in values])))
    return make_table_value(columns)


def safe_share(part, whole):
    return part / whole if part is not None and whole else None


BUILTINS = {
    "fdic-loan-losses": fdic_loan_losses,
    "fdic-find-bank": fdic_find_bank,
    "fdic-balance-sheet": fdic_balance_sheet,
    "fdic-income-statement": fdic_income_statement,
    "fdic-ratios": fdic_ratios,
    "fdic-financials": fdic_financials,
    "fdic-get": fdic_get,
    "fdic-fields": fdic_fields,
}
