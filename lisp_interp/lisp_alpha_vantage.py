"""Alpha Vantage data for the Lisp interpreter: the dividends a stock has
paid (https://www.alphavantage.co).

  (alpha-vantage-dividends creds symbol)
                     the stock's dividends, as a table: a row for each, oldest first

Needs a free Alpha Vantage API key (https://www.alphavantage.co/support/#api-key)
as the "alpha_vantage_api_key" entry of the credentials file. A free key
is limited to 25 requests a day, and to one a second, so each download is
kept for 12 hours (in lisp_http's cache, which (http-clear-cache) empties).
"""

import json
import urllib.parse

from lisp_core import LispError
from lisp_data_common import credential
from lisp_tables import column_vector, make_table_value
import lisp_http

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
CACHE_HOURS = 12

# Alpha Vantage's name for each field of a dividend, and the column it becomes
DIVIDEND_COLUMNS = [
    ("ex_dividend_date", "ex-date"),
    ("declaration_date", "declaration-date"),
    ("record_date", "record-date"),
    ("payment_date", "payment-date"),
    ("amount", "amount"),
]


def alpha_vantage_dividends(credentials_path, symbol):
    """(alpha-vantage-dividends creds symbol) -- the dividends a stock or ETF
    has paid: a table with a row for each, oldest first, of its ex-date (the
    first day its shares trade without the dividend), declaration-date,
    record-date, payment-date, and amount per share. A date Alpha Vantage
    doesn't have is '(). A share class is written "BRK-B" or, as Schwab
    writes it, "BRK/B". The table has no rows for a stock that has paid no
    dividends -- or that Alpha Vantage doesn't know."""
    who = "alpha-vantage-dividends"
    key = credential(credentials_path, "alpha_vantage_api_key", who,
                     "get a free one at https://www.alphavantage.co/support/#api-key")
    url = ALPHA_VANTAGE_URL + "?" + urllib.parse.urlencode(
        {"function": "DIVIDENDS", "symbol": str(symbol).replace("/", "-"), "apikey": key})
    shown_url = url.replace(key, "...")             # so the API key never shows in an error

    def check(data):
        read_answer(data, key, who)                 # a problem isn't kept in the cache

    answer = read_answer(lisp_http.download(url, CACHE_HOURS, None, who, shown_url, check=check), key, who)
    dividends = sorted(answer["data"], key=lambda dividend: str(dividend.get("ex_dividend_date")))
    return make_table_value([(column, column_vector([field_value(dividend, field) for dividend in dividends]))
                             for field, column in DIVIDEND_COLUMNS])


def read_answer(data, key, who):
    """Alpha Vantage's answer, as a dict with a "data" list of dividends. When
    it has no "data" it says why -- as "Information" (a limit on requests),
    "Note", or "Error Message" -- in an answer that says it's fine (HTTP
    200)."""
    try:
        answer = json.loads(lisp_http.as_text(data))
    except json.JSONDecodeError:
        raise LispError("%s: Alpha Vantage didn't return valid JSON; it starts: %s"
                        % (who, lisp_http.as_text(data)[:200].replace(key, "...")))
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
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


BUILTINS = {
    "alpha-vantage-dividends": alpha_vantage_dividends,
}
