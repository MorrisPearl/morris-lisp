"""FINRA's market data, for the Lisp interpreter: the prices that agency
mortgage-backed securities traded at each day, as reported to TRACE.

  (finra-tba-prices creds [:start-date d :end-date d :agency a])
        TBAs: UMBS, FHLMC and GNMA 15- and 30-year, by coupon and settlement month
  (finra-mbs-prices creds [:start-date d :end-date d :agency a])
        specified pools: fixed-rate pass-throughs, by agency and coupon
  (finra-arm-prices creds [:start-date d :end-date d :agency a])
        specified ARM and hybrid pools, by agency and fixed-rate period
  (finra-get creds group dataset [:start-date d :end-date d :filters f])
        any of the API's other datasets, as FINRA sends it

Each pricing table has a row for each day, product, agency, (settlement
month,) and coupon, and a column for each of the statistics FINRA gives:
the average price, the weighted average, the quartiles, the averages of the
5 lowest and 5 highest trades, the standard deviation, the dollar volume
(in thousands), and the number of trades.

FINRA's API (https://developer.finra.org) needs a free account (an
Individual one, with a "Public" credential, costs $0). Its client ID and
secret go in the credentials file as "finra_client_id" and
"finra_client_secret". They are traded for a token, which is kept (in
memory) for 30 minutes. Answers are kept for CACHE_HOURS, as http-get-json
keeps them, so that running a notebook again doesn't ask FINRA again.
"""

import base64
import datetime
import json
import math
import re
import time

from lisp_core import LispDate, LispError, LispString, NIL, Pair, date_argument, keyword_options, list_to_pairs
from lisp_data_common import credential, name_value_pairs, records_table, text_list
from lisp_tables import column_vector, make_table_value
import lisp_http


API_URL = "https://api.finra.org"
TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
TOKEN_SECONDS = 30 * 60     # FINRA asks that a token be kept no longer than 30 minutes
PAGE_SIZE = 5000            # the most records FINRA sends in one answer
CACHE_HOURS = 12            # the prices change once a day
DEFAULT_DAYS = 7            # without :start-date, the last week

_tokens = {}                # the credentials file's path -> (token, when it runs out)


def headers(pairs):
    """A dict of headers as lisp_http.download takes them: a list of (name . value) pairs."""
    return list_to_pairs([Pair(LispString(name), LispString(value)) for name, value in pairs.items()])


def access_token(credentials_path, who):
    """A token for FINRA's API: the one got in the last 30 minutes, or a new one, for the app's client ID and
    secret. Neither the secret nor the token goes into an error message."""
    saved = _tokens.get(str(credentials_path))
    if saved and saved[1] > time.time():
        return saved[0]
    needed = ("FINRA's API needs one: make a free Individual account at https://developer.finra.org, "
              "and a Public credential")
    client_id = credential(credentials_path, "finra_client_id", who, needed)
    secret = credential(credentials_path, "finra_client_secret", who, needed)
    basic = base64.b64encode(("%s:%s" % (client_id, secret)).encode()).decode()
    data = lisp_http.download(TOKEN_URL, 0, headers({"Authorization": "Basic " + basic}), who, body=b"")
    try:
        token = json.loads(lisp_http.as_text(data))["access_token"]
    except (ValueError, KeyError, TypeError):
        raise LispError("%s: FINRA didn't send a token -- check finra_client_id and finra_client_secret" % who)
    _tokens[str(credentials_path)] = (token, time.time() + TOKEN_SECONDS)
    return token


def finra_records(credentials_path, group, dataset, request, who):
    """All the records of a dataset that the request (a dict: FINRA's filters) asks for, a page at a time."""
    token = access_token(credentials_path, who)
    url = "%s/data/group/%s/name/%s" % (API_URL, group, dataset)
    records = []
    while True:
        body = json.dumps(dict(request, limit=PAGE_SIZE, offset=len(records))).encode()
        data = lisp_http.download(url, CACHE_HOURS, headers({"Authorization": "Bearer " + token,
                                                              "Accept": "application/json",
                                                              "Content-Type": "application/json"}),
                                  who, body=body)
        text = lisp_http.as_text(data).strip()
        try:
            page = json.loads(text) if text else []
        except ValueError:
            raise LispError("%s: FINRA didn't answer with data; it says: %s" % (who, " ".join(text.split())[:300]))
        if not isinstance(page, list):
            raise LispError("%s: FINRA didn't answer with data; it says: %s" % (who, text[:300]))
        records.extend(page)
        if len(page) < PAGE_SIZE:
            return records


def date_filter(options, who):
    """FINRA's filter for the report dates asked for: from :start-date (a week ago, unless it is given) to
    :end-date (today, unless it is given)."""
    end = date_argument(options["end-date"], who, ":end-date") if "end-date" in options else datetime.date.today()
    start = (date_argument(options["start-date"], who, ":start-date") if "start-date" in options
             else end - datetime.timedelta(days=DEFAULT_DAYS))
    if start > end:
        raise LispError("%s: :start-date %s is after :end-date %s" % (who, start, end))
    return {"fieldName": "reportDate", "startDate": start.isoformat(), "endDate": end.isoformat()}


def value_of(text):
    """A record's value: a number, or NaN for none."""
    try:
        return float(text) if text is not None else math.nan
    except (TypeError, ValueError):
        return math.nan


def coupon_order(text):
    """Where a coupon bucket goes, in order: "<= 3.5" before "4", and "> 6" after "6"."""
    found = re.search(r"[\d.]+", str(text))
    value = float(found.group()) if found else math.inf
    return value - 0.001 if "<" in str(text) else value + 0.001 if ">" in str(text) else value


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def settlement_order(text, report_date):
    """Where a TBA's settlement month ("July Settlement") goes, in order: how many months after the report date's
    month it is, so that January comes after December."""
    words = str(text).lower().split()
    if not words or words[0] not in MONTHS:
        return 99
    return (MONTHS.index(words[0]) + 1 - int(report_date[5:7])) % 12


def product_of(table_name):
    """The product, from FINRA's name for the pricing table: "SINGLE FAMILY 30Y", from
    "AGENCY PASS-THRU (TBA, STIP, $ ROLLS) - SINGLE FAMILY 30Y"."""
    return str(table_name or "").rsplit(" - ", 1)[-1]


def pricing_table(records, keys, who):
    """FINRA's pricing records -- one for each statistic of each day, product, agency, and coupon -- as a table with a
    row for each of these and a column for each statistic. keys are the record's fields that tell the rows apart, after
    the date and product, with their column names: [("agencyCode", "agency"), ...]."""
    if not records:
        raise LispError("%s: FINRA has no prices for those dates (it has none for weekends and holidays, and a day's "
                        "come the next morning)" % who)
    statistics = []
    rows = {}
    for record in records:
        statistic = str(record.get("categoryCode", "")).lower()
        if statistic not in statistics:
            statistics.append(statistic)
        row = (str(record.get("reportDate", "")), product_of(record.get("pricingTableName"))) + \
            tuple(str(record.get(field, "")) for field, _ in keys)
        rows.setdefault(row, {})[statistic] = value_of(record.get("valueAmount"))
    def order(row):
        """Rows in order of date, product, and agency, then (for a TBA) settlement month, then coupon."""
        date, product, agency, *rest = row
        if len(rest) == 2:
            rest = [settlement_order(rest[0], date)] + rest[1:]
        return (date, product, agency) + tuple(rest[:-1]) + (coupon_order(rest[-1]), rest[-1])

    ordered = sorted(rows, key=order)
    columns = [("date", column_vector([LispDate(*map(int, row[0][:10].split("-"))) for row in ordered])),
               ("product", column_vector([LispString(row[1]) for row in ordered]))]
    for i, (_, name) in enumerate(keys):
        columns.append((name, column_vector([LispString(row[2 + i]) for row in ordered])))
    for statistic in statistics:
        columns.append((statistic, column_vector([rows[row].get(statistic, math.nan) for row in ordered])))
    return make_table_value(columns)


def pricing_request(options, who):
    """The filters for a pricing dataset: the dates, and the agencies if :agency names any."""
    request = {"dateRangeFilters": [date_filter(options, who)]}
    if "agency" in options:
        request["domainFilters"] = [{"fieldName": "agencyCode",
                                     "values": [a.upper() for a in text_list(options["agency"], who, ":agency")]}]
    return request


def finra_tba_prices(credentials_path, *options):
    """(finra-tba-prices creds [:start-date d :end-date d :agency a]) -- the prices TBAs traded at each day: UMBS,
    FHLMC and GNMA single-family 15- and 30-year, a row for each day, product, agency, settlement month, and coupon,
    with a column for each statistic FINRA gives (average price, weighted average price, quartiles, the lowest and
    highest trades, standard deviation, dollar volume in thousands, number of trades). The last week, unless
    :start-date or :end-date says; :agency is "UMBS", "FHLMC", or "GNMA", or a list of them."""
    who = "finra-tba-prices"
    options = keyword_options(options, ["start-date", "end-date", "agency"], who)
    records = finra_records(credentials_path, "fixedIncomeMarket", "agencyTbaPricing", pricing_request(options, who), who)
    return pricing_table(records, [("agencyCode", "agency"), ("settlementCode", "settlement"),
                                   ("couponRateCode", "coupon")], who)


def finra_mbs_prices(credentials_path, *options):
    """(finra-mbs-prices creds [:start-date d :end-date d :agency a]) -- the prices specified pools traded at each day:
    fixed-rate agency pass-throughs, a row for each day, product (SINGLE FAMILY 30Y, ...), agency, and coupon, with a
    column for each statistic FINRA gives, as finra-tba-prices has them."""
    who = "finra-mbs-prices"
    options = keyword_options(options, ["start-date", "end-date", "agency"], who)
    records = finra_records(credentials_path, "fixedIncomeMarket", "agencyMbsPricing", pricing_request(options, who), who)
    return pricing_table(records, [("agencyCode", "agency"), ("couponRateCode", "coupon")], who)


def finra_arm_prices(credentials_path, *options):
    """(finra-arm-prices creds [:start-date d :end-date d :agency a]) -- the prices specified ARM and hybrid pools
    traded at each day: a row for each day, agency, and fixed-rate period (5/1, 7/1, ...), with a column for each
    statistic FINRA gives, as finra-tba-prices has them."""
    who = "finra-arm-prices"
    options = keyword_options(options, ["start-date", "end-date", "agency"], who)
    records = finra_records(credentials_path, "fixedIncomeMarket", "agencyMbsArmHybridPricing",
                            pricing_request(options, who), who)
    return pricing_table(records, [("agencyCode", "agency"), ("fixedRatePeriodCode", "period")], who)


def finra_get(credentials_path, group, dataset, *options):
    """(finra-get creds group dataset [:start-date d :end-date d :filters f]) -- any of the datasets of FINRA's API, as
    a table with a column for each of FINRA's fields: group and dataset as FINRA names them ("fixedIncomeMarket" and
    "agencyCmoPricing"). :start-date and :end-date ask for those report dates (the last week, if either is given);
    :filters is a list of (field . value) pairs, the records whose field has that value."""
    who = "finra-get"
    options = keyword_options(options, ["start-date", "end-date", "filters"], who)
    request = {}
    if "start-date" in options or "end-date" in options:
        request["dateRangeFilters"] = [date_filter(options, who)]
    if options.get("filters", NIL) is not NIL:
        request["compareFilters"] = [{"fieldName": str(field), "fieldValue": str(value), "compareType": "EQUAL"}
                                     for field, value in name_value_pairs(options["filters"], who)]
    return records_table(finra_records(credentials_path, str(group), str(dataset), request, who))


BUILTINS = {
    "finra-tba-prices": finra_tba_prices,
    "finra-mbs-prices": finra_mbs_prices,
    "finra-arm-prices": finra_arm_prices,
    "finra-get": finra_get,
}
