"""Alpha Vantage data for the Lisp interpreter: the dividends a stock has
paid, its latest price, and what analysts expect it to earn
(https://www.alphavantage.co).

  (alpha-vantage-dividends creds symbol)
                     the stock's dividends, as a table: a row for each, oldest first
  (alpha-vantage-price creds symbol)
                     the latest price (the last trading day's close, or the price now during the day)
  (alpha-vantage-estimates creds symbol)
                     analysts' estimates of earnings per share and revenue, for the coming quarters and
                     years, and how they have been revised

Needs a free Alpha Vantage API key (https://www.alphavantage.co/support/#api-key)
as the "alpha_vantage_api_key" entry of the credentials file. A free key
is limited to 25 requests a day, and to one a second, so each download is
kept for 12 hours (in lisp_http's cache, which (http-clear-cache) empties).
"""

import json
import time
import urllib.parse

from lisp_core import LispError
from lisp_data_common import credential
from lisp_tables import column_vector, make_table_value
import lisp_http

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
CACHE_HOURS = 12
PRICE_CACHE_HOURS = 1                   # (a price is kept an hour, not 12)
SECONDS_BETWEEN_REQUESTS = 1.2

# Alpha Vantage's name for each field of a dividend, and the column it becomes
DIVIDEND_COLUMNS = [
    ("ex_dividend_date", "ex-date"),
    ("declaration_date", "declaration-date"),
    ("record_date", "record-date"),
    ("payment_date", "payment-date"),
    ("amount", "amount"),
]


def alpha_vantage_answer(credentials_path, function, symbol, field, cache_hours, who):
    """Alpha Vantage's answer to `function` for the symbol, as a dict that has `field` in it (or an error that says
    why not). The API key never shows in an error."""
    key = credential(credentials_path, "alpha_vantage_api_key", who,
                     "get a free one at https://www.alphavantage.co/support/#api-key")
    url = ALPHA_VANTAGE_URL + "?" + urllib.parse.urlencode(
        {"function": function, "symbol": str(symbol).replace("/", "-"), "apikey": key})
    shown_url = url.replace(key, "...")

    def check(data):
        read_answer(data, key, who, field)          # a problem isn't kept in the cache

    return read_answer(lisp_http.download(url, cache_hours, None, who, shown_url, check=check, wait=wait_a_moment), key,
                       who, field)


_last_request = [0.0]


def wait_a_moment():
    """Alpha Vantage's free key allows a request a second: wait until a second has passed since the last one."""
    passed = time.time() - _last_request[0]
    if passed < SECONDS_BETWEEN_REQUESTS:
        time.sleep(SECONDS_BETWEEN_REQUESTS - passed)
    _last_request[0] = time.time()


def alpha_vantage_dividends(credentials_path, symbol):
    """(alpha-vantage-dividends creds symbol) -- the dividends a stock or ETF
    has paid: a table with a row for each, oldest first, of its ex-date (the
    first day its shares trade without the dividend), declaration-date,
    record-date, payment-date, and amount per share. A date Alpha Vantage
    doesn't have is '(). A share class is written "BRK-B" or, as Schwab
    writes it, "BRK/B". The table has no rows for a stock that has paid no
    dividends -- or that Alpha Vantage doesn't know."""
    who = "alpha-vantage-dividends"
    answer = alpha_vantage_answer(credentials_path, "DIVIDENDS", symbol, "data", CACHE_HOURS, who)
    dividends = sorted(answer["data"], key=lambda dividend: str(dividend.get("ex_dividend_date")))
    return make_table_value([(column, column_vector([field_value(dividend, field) for dividend in dividends]))
                             for field, column in DIVIDEND_COLUMNS])


def read_answer(data, key, who, field="data"):
    """Alpha Vantage's answer, as a dict with `field` in it (a "data" list of
    dividends, a "Global Quote", a list of "estimates"). When it hasn't it says
    why -- as "Information" (a limit on requests), "Note", or "Error Message"
    -- in an answer that says it's fine (HTTP 200)."""
    try:
        answer = json.loads(lisp_http.as_text(data))
    except json.JSONDecodeError:
        raise LispError("%s: Alpha Vantage didn't return valid JSON; it starts: %s"
                        % (who, lisp_http.as_text(data)[:200].replace(key, "...")))
    if not isinstance(answer, dict) or answer.get(field) is None or answer.get(field) == {}:    # (an empty list is an answer)
        said = "there is no data in its answer"
        if isinstance(answer, dict):
            said = answer.get("Information") or answer.get("Note") or answer.get("Error Message") or said
        raise LispError("%s: Alpha Vantage says: %s" % (who, str(said).replace(key, "...")))
    return answer


def field_value(dividend, field):
    """One field of one of Alpha Vantage's dividends, as a Lisp value: a number
    for the amount, text for a date (column_vector reads it as one), and None
    -- '() -- for a field it doesn't have (it says "None", or leaves it out)."""
    value = dividend.get(field)
    if value is None or value == "None" or value == "":
        return None
    return float(value) if field == "amount" else str(value)


def alpha_vantage_price(credentials_path, symbol):
    """(alpha-vantage-price creds symbol) -- the stock's latest price: during the trading day, the price now (a few
    minutes late, as the free key has it); after it, the day's close. A number. Kept for an hour."""
    who = "alpha-vantage-price"
    quote = alpha_vantage_answer(credentials_path, "GLOBAL_QUOTE", symbol, "Global Quote", PRICE_CACHE_HOURS, who)
    price = quote["Global Quote"].get("05. price")
    if price in (None, "", "None"):
        raise LispError("%s: Alpha Vantage has no price for %s" % (who, symbol))
    return float(price)


# Alpha Vantage's fields of an estimate, and the columns they become (amounts of revenue are in millions)
ESTIMATE_COLUMNS = [
    ("date", "period-end"), ("horizon", "horizon"),
    ("eps_estimate_average", "eps"), ("eps_estimate_low", "eps-low"), ("eps_estimate_high", "eps-high"),
    ("eps_estimate_analyst_count", "eps-analysts"),
    ("eps_estimate_average_7_days_ago", "eps-7-days-ago"), ("eps_estimate_average_30_days_ago", "eps-30-days-ago"),
    ("eps_estimate_average_90_days_ago", "eps-90-days-ago"),
    ("eps_estimate_revision_up_trailing_30_days", "raised-30-days"),
    ("eps_estimate_revision_down_trailing_30_days", "lowered-30-days"),
    ("revenue_estimate_average", "revenue"), ("revenue_estimate_low", "revenue-low"),
    ("revenue_estimate_high", "revenue-high"), ("revenue_estimate_analyst_count", "revenue-analysts"),
]
TEXT_FIELDS = ("date", "horizon")


def estimate_value(estimate, field):
    """One field of an estimate: text for the date and horizon, a number for the rest (revenue in millions), None for
    one Alpha Vantage hasn't."""
    value = estimate.get(field)
    if value is None or value in ("None", ""):
        return None
    if field in TEXT_FIELDS:
        return str(value)
    number = float(value)
    return number / 1e6 if field.startswith("revenue_estimate") and not field.endswith("count") else number


def estimate_records(credentials_path, symbol):
    """Alpha Vantage's estimates for the symbol, oldest first: a list of dicts as Alpha Vantage gives them (the numbers
    as text). A company it has no estimates for has none."""
    answer = alpha_vantage_answer(credentials_path, "EARNINGS_ESTIMATES", symbol, "estimates", CACHE_HOURS,
                                  "alpha-vantage-estimates")
    return sorted(answer["estimates"], key=lambda estimate: (str(estimate.get("date")), str(estimate.get("horizon"))))


def fiscal_year_eps(records, after):
    """The analysts' estimates of earnings per share for the fiscal years that end after the date `after` (a datetime.date),
    soonest first: a list of (the year's end, the average estimate)."""
    years = []
    for estimate in records:
        value = estimate_value(estimate, "eps_estimate_average")
        if estimate.get("horizon") == "fiscal year" and str(estimate.get("date")) > after.isoformat() and value is not None:
            years.append((str(estimate["date"]), value))
    return sorted(years)


def alpha_vantage_estimates(credentials_path, symbol):
    """(alpha-vantage-estimates creds symbol) -- what analysts expect the company to earn: a table with a row for
    each coming fiscal quarter and year (and the ones just reported), oldest first, of its period-end, horizon
    ("fiscal quarter" or "fiscal year"), eps (the average of the analysts' estimates of earnings per share), eps-low,
    eps-high, eps-analysts (how many), eps-7-days-ago, eps-30-days-ago, eps-90-days-ago (what the average was then),
    eps-revision-30-days (the change since 30 days ago, as a fraction: estimates being raised is a good sign, being
    cut a bad one), raised-30-days and lowered-30-days (how many analysts did each), revenue, revenue-low,
    revenue-high (in millions), and revenue-analysts."""
    estimates = estimate_records(credentials_path, symbol)
    columns = []
    for field, name in ESTIMATE_COLUMNS:
        columns.append((name, column_vector([estimate_value(estimate, field) for estimate in estimates])))
        if name == "eps-90-days-ago":
            revisions = []
            for estimate in estimates:
                now, before = estimate_value(estimate, "eps_estimate_average"), estimate_value(
                    estimate, "eps_estimate_average_30_days_ago")
                revisions.append(now / before - 1 if now is not None and before else None)
            columns.append(("eps-revision-30-days", column_vector(revisions)))
    return make_table_value(columns)


BUILTINS = {
    "alpha-vantage-dividends": alpha_vantage_dividends,
    "alpha-vantage-price": alpha_vantage_price,
    "alpha-vantage-estimates": alpha_vantage_estimates,
}
