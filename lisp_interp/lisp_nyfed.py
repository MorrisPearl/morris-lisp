"""The New York Fed's reference rates, for the Lisp interpreter
(https://www.newyorkfed.org/markets/reference-rates), from its free API --
no key or account needed.

  (nyfed-rates names [:start-date d :end-date d :cache-hours h])
        one rate or several, as a table with a row per business day
  (nyfed-rate-details name [:start-date d :end-date d :cache-hours h])
        one rate with the rest of what the Fed publishes about it: the
        percentiles of the day's trades, their volume, and (for EFFR) the
        Fed's target range

The rates, by the names these take:

  SOFR         the Secured Overnight Financing Rate (from April 2018)
  TGCR, BGCR   the Tri-Party and Broad General Collateral Rates
  EFFR         the Effective Federal Funds Rate (from July 2000)
  OBFR         the Overnight Bank Funding Rate (from March 2016)
  SOFR-30, SOFR-90, SOFR-180   the 30-, 90- and 180-day averages of SOFR,
               as floating-rate loans use them (from March 2020)
  SOFR-INDEX   what $1 put in SOFR on April 2, 2018 has grown to

Rates are in percent, as the Fed publishes them (3.94, not 0.0394).
"""

import datetime
import json
import urllib.parse

from lisp_core import LispError, date_argument, keyword_options
from lisp_data_common import dated_table, text_list
import lisp_http

API_URL = "https://markets.newyorkfed.org/api/rates"
CACHE_HOURS = 12                        # the rates are published once a day
EARLIEST = datetime.date(2000, 1, 1)    # before the first of them (EFFR's history starts in July 2000)

# Each name: the API's path for it, and the field of its records that holds the value.
RATES = {
    "SOFR": ("secured/sofr", "percentRate"),
    "TGCR": ("secured/tgcr", "percentRate"),
    "BGCR": ("secured/bgcr", "percentRate"),
    "EFFR": ("unsecured/effr", "percentRate"),
    "OBFR": ("unsecured/obfr", "percentRate"),
    "SOFR-30": ("secured/sofrai", "average30day"),
    "SOFR-90": ("secured/sofrai", "average90day"),
    "SOFR-180": ("secured/sofrai", "average180day"),
    "SOFR-INDEX": ("secured/sofrai", "index"),
}

# When each rate's history starts, for the error when there's none.
FIRST_DATES = dict({name: "it starts on April 2, 2018" for name in ("SOFR", "TGCR", "BGCR")},
                   EFFR="it starts on July 3, 2000", OBFR="it starts on March 1, 2016",
                   **{name: "they start on March 2, 2020" for name in ("SOFR-30", "SOFR-90", "SOFR-180", "SOFR-INDEX")})

# The details' columns, and the fields they come from. A rate has only some of them.
DETAILS = [("rate", "percentRate"), ("percentile-1", "percentPercentile1"), ("percentile-25", "percentPercentile25"),
           ("percentile-75", "percentPercentile75"), ("percentile-99", "percentPercentile99"),
           ("volume-billions", "volumeInBillions"), ("target-from", "targetRateFrom"), ("target-to", "targetRateTo"),
           ("average-30-day", "average30day"), ("average-90-day", "average90day"),
           ("average-180-day", "average180day"), ("index", "index")]


def rate_name(name, who):
    """The name of a rate, in capitals, or an error listing the names there are."""
    upper = str(name).upper()
    if upper not in RATES:
        raise LispError("%s: there's no rate named %r; the rates are %s" % (who, str(name), ", ".join(RATES)))
    return upper


def date_option(value, default, who, what):
    """A date option, as a datetime.date, or the default if it isn't given."""
    return default if value is None else date_argument(value, who, what)


def rate_records(name, options, who):
    """The Fed's records of a rate for the dates asked for (all of them, unless :start-date or :end-date says),
    each a dict with an "effectiveDate" and the values, as a dict from date to record."""
    path = RATES[name][0]
    start = date_option(options.get("start-date"), EARLIEST, who, ":start-date")
    end = date_option(options.get("end-date"), datetime.date.today(), who, ":end-date")
    if start > end:
        raise LispError("%s: :start-date %s is after :end-date %s" % (who, start, end))
    url = "%s/%s/search.json?%s" % (API_URL, path, urllib.parse.urlencode({"startDate": start.isoformat(),
                                                                         "endDate": end.isoformat()}))
    text = lisp_http.as_text(lisp_http.download(url, options.get("cache-hours", CACHE_HOURS), None, who))
    try:
        records = json.loads(text)["refRates"]
    except (ValueError, KeyError, TypeError):
        raise LispError("%s: the New York Fed didn't answer with rates; it says: %s" % (who, " ".join(text.split())[:300]))
    if not records:
        raise LispError("%s: the New York Fed has no %s for those dates (%s)" % (who, name, FIRST_DATES[name]))
    return {datetime.date.fromisoformat(record["effectiveDate"]): record for record in records}


def number(value):
    """A value from a record, as a number: NaN if it's missing or isn't one."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def nyfed_rates(names, *options):
    """(nyfed-rates names [:start-date d :end-date d :cache-hours h]) -- one of the New York Fed's reference rates,
    or a list of them, by name ("SOFR", "EFFR", "SOFR-30", ...), as a table: a date column, oldest first, and a
    column for each rate, in percent, with NaN where a rate has no value for a date. All of each rate's history,
    unless :start-date or :end-date (a date, or "YYYY-MM-DD") says otherwise. Each download is kept for 12 hours,
    unless :cache-hours says otherwise (0: download it every time). No key needed."""
    who = "nyfed-rates"
    options = keyword_options(options, ["start-date", "end-date", "cache-hours"], who)
    columns = []
    for name in text_list(names, who, "the rates' names"):
        name = rate_name(name, who)
        field = RATES[name][1]
        records = rate_records(name, options, who)
        columns.append((name, {date: number(record.get(field)) for date, record in records.items()}))
    return dated_table(columns)


def nyfed_rate_details(name, *options):
    """(nyfed-rate-details name [:start-date d :end-date d :cache-hours h]) -- one of the New York Fed's reference
    rates with everything the Fed publishes about it each day, as a table: date, rate, the 1st, 25th, 75th and 99th
    percentiles of the rates the day's trades were at, volume-billions (the dollars traded, in billions), and for
    EFFR target-from and target-to (the Fed's target range). For SOFR-30, SOFR-90, SOFR-180 and SOFR-INDEX it is
    the three averages and the index. The options are as for nyfed-rates."""
    who = "nyfed-rate-details"
    options = keyword_options(options, ["start-date", "end-date", "cache-hours"], who)
    name = rate_name(name, who)
    records = rate_records(name, options, who)
    present = [(heading, field) for heading, field in DETAILS
               if any(field in record for record in records.values())]
    return dated_table([(heading, {date: number(record.get(field)) for date, record in records.items()})
                        for heading, field in present])


BUILTINS = {
    "nyfed-rates": nyfed_rates,
    "nyfed-rate-details": nyfed_rate_details,
}
