"""Charles Schwab accounts, for the Lisp interpreter: what's in each of your
accounts, quotes and price histories, and -- for whenever you want them --
orders.

Schwab's API (https://developer.schwab.com) signs in with OAuth. You log in
on Schwab's own site, which then sends the browser to the app's callback
URL with a code in it; the code is traded for an access token (good for 30
minutes, and renewed here as needed) and a refresh token (good for 7 days).
(schwab-login creds) shows Schwab's sign-in page in a small browser window
(PyQt6's web engine), watches for the callback, and saves the tokens.
After that the other functions just work, until the refresh token runs out
a week later; then (schwab-login creds) again.

  (schwab-login creds)                       sign in: opens a browser window
  (schwab-accounts creds)                    each account: its number, type, value, and cash
  (schwab-positions creds [:account a])      what's in each account: a row per holding
  (schwab-quotes creds symbols)              quotes
  (schwab-price-history creds symbol [:start-date :end-date :frequency])
                                             daily (or weekly or monthly) prices
  (schwab-orders creds [:account a :days n]) the orders of the last n days
  (schwab-get creds path [parameters])       any of the API's other requests
Orders:
  (schwab-order instruction symbol quantity [:type :price :stop-price :duration :asset-type])
                                             an order, to preview or place
  (schwab-preview-order creds account order) what Schwab would make of it; nothing is placed
  (schwab-place-order creds account order :confirm #t)
  (schwab-cancel-order creds account order-id)

The credentials file's "Schwab_Client_ID" and "Schwab_Client_Secret"
entries are the app's key and secret ("Schwab_Callback_URL" too, if the
app's isn't https://127.0.0.1). The tokens are kept in schwab_tokens.json,
next to the credentials file, readable only by you. Nothing is cached:
every call asks Schwab.
"""

import base64
import datetime
import importlib.util
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from lisp_core import Keyword, LispDate, LispError, LispHashTable, LispString, LispVector, NIL, Pair, pairs_to_list
from lisp_data_common import credential, text_list
from lisp_http import json_to_lisp
from lisp_stratify import keyword_options
from lisp_tables import column_vector, make_table_value

API_URL = "https://api.schwabapi.com"
AUTHORIZE_URL = API_URL + "/v1/oauth/authorize"
TOKEN_URL = API_URL + "/v1/oauth/token"
DEFAULT_CALLBACK = "https://127.0.0.1"
REFRESH_DAYS = 7                # how long a sign-in lasts
TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def schwab_message(text):
    """What Schwab's error answer says."""
    try:
        answer = json.loads(text)
    except ValueError:
        return " ".join(text.split())[:300] or "no reason given"
    if isinstance(answer, dict):
        for key in ("message", "error_description", "error"):
            if answer.get(key):
                return str(answer[key])
        if answer.get("errors"):
            return "; ".join(str(e.get("detail") or e.get("title") or e) if isinstance(e, dict) else str(e)
                             for e in answer["errors"])
    return " ".join(text.split())[:300]


def schwab_request(method, url, who, headers, body=None):
    """One request to Schwab: its status, its headers, and its answer's JSON
    (None if it has no answer). The tokens go in the headers, so they're
    never in an error message."""
    request = urllib.request.Request(url, data=body, method=method,
                                     headers=dict(headers, Accept="application/json"))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", errors="replace")
            return response.status, dict(response.headers), json.loads(text) if text.strip() else None
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        e.close()
        raise LispError("%s: Schwab says (HTTP %d): %s" % (who, e.code, schwab_message(text)))
    except (urllib.error.URLError, OSError) as e:
        raise LispError("%s: couldn't reach Schwab: %s" % (who, e))


# ---------------------------------------------------------------------------
# Signing in, and the tokens
# ---------------------------------------------------------------------------

def app_settings(credentials_path, who):
    """The app's key, secret, and callback URL, from the credentials file."""
    key = credential(credentials_path, "Schwab_Client_ID", who, "the app's key, from developer.schwab.com")
    secret = credential(credentials_path, "Schwab_Client_Secret", who, "the app's secret, from developer.schwab.com")
    callback = credential(credentials_path, "Schwab_Callback_URL", who) or DEFAULT_CALLBACK
    return key, secret, callback


def token_file(credentials_path):
    """Where the tokens are kept: schwab_tokens.json, next to the credentials file."""
    return os.path.join(os.path.dirname(os.path.abspath(str(credentials_path))), "schwab_tokens.json")


def save_tokens(credentials_path, tokens):
    """Save the tokens, readable only by you."""
    path = token_file(credentials_path)
    descriptor = os.open(path + ".part", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as f:
        json.dump(tokens, f)
    os.replace(path + ".part", path)


def load_tokens(credentials_path, who):
    try:
        with open(token_file(credentials_path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        raise LispError("%s: not signed in to Schwab -- sign in with (schwab-login creds)" % who)


def token_request(credentials_path, form, who):
    """Ask Schwab for tokens: the app's key and secret, and the form (a
    code to trade, or a refresh token)."""
    key, secret, _ = app_settings(credentials_path, who)
    basic = base64.b64encode(("%s:%s" % (key, secret)).encode()).decode()
    _, _, answer = schwab_request("POST", TOKEN_URL, who,
                                  {"Authorization": "Basic " + basic,
                                   "Content-Type": "application/x-www-form-urlencoded"},
                                  urllib.parse.urlencode(form).encode())
    if not answer or "access_token" not in answer:
        raise LispError("%s: Schwab didn't send a token" % who)
    return answer


def tokens_from(answer, refresh_expires):
    """The tokens to keep, from Schwab's answer: the access token runs out a
    minute before Schwab says, to be safe; the refresh token when the
    sign-in does."""
    return {"access_token": answer["access_token"],
            "refresh_token": answer.get("refresh_token"),
            "access_expires": time.time() + float(answer.get("expires_in", 1800)) - 60,
            "refresh_expires": refresh_expires}


def access_token(credentials_path, who):
    """A current access token: the saved one, or -- if it has run out -- a
    new one, from the refresh token."""
    tokens = load_tokens(credentials_path, who)
    if time.time() < tokens["access_expires"]:
        return tokens["access_token"]
    if time.time() >= tokens["refresh_expires"]:
        raise LispError("%s: the Schwab sign-in has run out (it lasts %d days) -- sign in again with "
                        "(schwab-login creds)" % (who, REFRESH_DAYS))
    try:
        answer = token_request(credentials_path, {"grant_type": "refresh_token",
                                                  "refresh_token": tokens["refresh_token"]}, who)
    except LispError as e:
        raise LispError("%s -- sign in again with (schwab-login creds)" % e)
    renewed = tokens_from(answer, tokens["refresh_expires"])
    renewed["refresh_token"] = renewed["refresh_token"] or tokens["refresh_token"]
    save_tokens(credentials_path, renewed)
    return renewed["access_token"]


_qt_application = None          # kept here, if this module made it, so it isn't thrown away


def login_in_window(url, callback):
    """Show Schwab's sign-in page in a small browser window, and wait until
    the page goes to the callback URL. Returns that URL -- with the code in
    it -- or None if the window is closed first."""
    global _qt_application
    from PyQt6.QtCore import QEventLoop, QUrl
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication

    if QApplication.instance() is None:
        _qt_application = QApplication(["morris-lisp"])     # (the web engine wants a program name)
    landed = []
    waiting = QEventLoop()

    def check(address):
        """Whether the page is going to the callback URL (and if so, note it and stop waiting)."""
        text = address.toString()
        if text.startswith(callback) and not landed:
            landed.append(text)
            waiting.quit()
        return bool(landed)

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, address, kind, is_main_frame):
            return not check(address)           # (never actually go to the callback URL)

    class Window(QWebEngineView):
        def closeEvent(self, event):
            waiting.quit()
            super().closeEvent(event)

    window = Window()
    page = Page(window)
    page.urlChanged.connect(check)               # (in case the callback comes some other way)
    window.setPage(page)
    window.setWindowTitle("Sign in to Schwab")
    window.resize(900, 800)
    window.load(QUrl(url))
    window.show()
    window.raise_()
    window.activateWindow()
    waiting.exec()
    window.close()
    return landed[0] if landed else None


def has_web_engine():
    """Whether PyQt6's web engine, for the sign-in window, is installed."""
    try:
        return importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is not None
    except ImportError:
        return False


def login_in_your_browser(url, callback):
    """Without PyQt6's web engine: open Schwab's sign-in page in your own
    browser, and ask for the address it ends up at."""
    print("Sign in to Schwab in your browser. Afterwards the browser will show an error page at an "
          "address starting %s -- copy that whole address, and paste it here." % callback)
    webbrowser.open(url)
    return input("The address: ").strip() or None


def schwab_login(credentials_path):
    """(schwab-login creds) -- sign in to Schwab: shows its sign-in page in a
    small browser window (or, without PyQt6's web engine, your own browser),
    where you log in and approve the app; then saves the tokens. The sign-in
    lasts 7 days. Returns #t."""
    who = "schwab-login"
    key, _, callback = app_settings(credentials_path, who)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({"client_id": key, "redirect_uri": callback})
    landed = login_in_window(url, callback) if has_web_engine() else login_in_your_browser(url, callback)
    if not landed:
        raise LispError("%s: the sign-in window was closed before signing in" % who)
    code = urllib.parse.parse_qs(urllib.parse.urlparse(landed).query).get("code")
    if not code:
        raise LispError("%s: Schwab didn't send a sign-in code (the address was %s)" % (who, landed.split("?")[0]))
    answer = token_request(credentials_path, {"grant_type": "authorization_code", "code": code[0],
                                              "redirect_uri": callback}, who)
    save_tokens(credentials_path, tokens_from(answer, time.time() + REFRESH_DAYS * 24 * 3600))
    return True


# ---------------------------------------------------------------------------
# Asking the API
# ---------------------------------------------------------------------------

def api_call(credentials_path, method, path, who, params=None, json_body=None):
    """One request to the API, signed in: its headers and its answer's JSON."""
    url = API_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"Authorization": "Bearer " + access_token(credentials_path, who)}
    body = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode()
    _, response_headers, answer = schwab_request(method, url, who, headers, body)
    return response_headers, answer


def api_get(credentials_path, path, who, params=None):
    return api_call(credentials_path, "GET", path, who, params)[1]


def find_account(credentials_path, account, who):
    """An account's number and the code ("hash") the API names it by: given
    as its number, or the last 3 or more digits of it (as text, to keep
    leading zeros)."""
    accounts = api_get(credentials_path, "/trader/v1/accounts/accountNumbers", who) or []
    text = str(int(account)) if isinstance(account, (int, float)) else str(account).strip()
    matches = [a for a in accounts
               if a["accountNumber"] == text or (len(text) >= 3 and a["accountNumber"].endswith(text))]
    if len(matches) != 1:
        raise LispError("%s: %s account matches %r -- the accounts end %s"
                        % (who, "more than one" if matches else "no", text,
                           ", ".join(a["accountNumber"][-4:] for a in accounts)))
    return matches[0]["accountNumber"], matches[0]["hashValue"]


def number(value):
    """A number from Schwab's answer, or NaN for none."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else float("nan")


def table_of(rows, names):
    """Rows (tuples) as a table with these column names; text as text."""
    def lisp_value(value):
        return LispString(value) if isinstance(value, str) else value
    return make_table_value([(name, column_vector([lisp_value(row[j]) for row in rows]))
                             for j, name in enumerate(names)])


# ---------------------------------------------------------------------------
# Accounts and positions
# ---------------------------------------------------------------------------

def schwab_accounts(credentials_path):
    """(schwab-accounts creds) -- each of your accounts: a table of its
    number, type (CASH or MARGIN), value (what it would be worth sold:
    Schwab's liquidation value), cash, and the market value of its long
    and short positions."""
    who = "schwab-accounts"
    rows = []
    for entry in api_get(credentials_path, "/trader/v1/accounts", who) or []:
        account = entry.get("securitiesAccount", {})
        balances = account.get("currentBalances", {})
        rows.append((account.get("accountNumber", ""), account.get("type", ""),
                     number(balances.get("liquidationValue")), number(balances.get("cashBalance")),
                     number(balances.get("longMarketValue")), number(balances.get("shortMarketValue"))))
    return table_of(rows, ["account", "type", "value", "cash", "long-value", "short-value"])


POSITION_COLUMNS = ["account", "symbol", "description", "asset-type", "quantity", "average-price",
                    "market-value", "unrealized-gain", "day-gain", "cusip"]


def position_row(account_number, position):
    """One holding: what it is, how much (short positions negative), what it
    cost on average, and what it's worth and has gained."""
    instrument = position.get("instrument", {})
    gains = [position.get(k) for k in ("longOpenProfitLoss", "shortOpenProfitLoss") if position.get(k) is not None]
    return (account_number, instrument.get("symbol", ""), instrument.get("description", ""),
            instrument.get("assetType", ""),
            number(position.get("longQuantity") or 0) - number(position.get("shortQuantity") or 0),
            number(position.get("averagePrice")), number(position.get("marketValue")),
            sum(gains) if gains else float("nan"), number(position.get("currentDayProfitLoss")),
            instrument.get("cusip", ""))


def schwab_positions(credentials_path, *options):
    """(schwab-positions creds [:account a]) -- what's in your accounts: a
    table with a row for each holding in each account -- or just one
    account's, given by its number or its last few digits -- of the
    account, symbol, description, asset type (EQUITY, OPTION, ...),
    quantity (negative for a short position), average price paid, market
    value, unrealized gain, today's gain, and CUSIP. Cash isn't a holding:
    see schwab-accounts."""
    who = "schwab-positions"
    options = keyword_options(options, ["account"], who)
    if options.get("account", NIL) is not NIL:
        _, account_hash = find_account(credentials_path, options["account"], who)
        entries = [api_get(credentials_path, "/trader/v1/accounts/" + account_hash, who, {"fields": "positions"})]
    else:
        entries = api_get(credentials_path, "/trader/v1/accounts", who, {"fields": "positions"}) or []
    rows = []
    for entry in entries:
        account = (entry or {}).get("securitiesAccount", {})
        for position in account.get("positions", []):
            rows.append(position_row(account.get("accountNumber", ""), position))
    return table_of(rows, POSITION_COLUMNS)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

QUOTE_FIELDS = [("bid", "bidPrice"), ("ask", "askPrice"), ("last", "lastPrice"), ("mark", "mark"),
                ("change", "netChange"), ("change-percent", "netPercentChange"), ("volume", "totalVolume"),
                ("52-week-high", "52WeekHigh"), ("52-week-low", "52WeekLow")]


def schwab_quotes(credentials_path, symbols):
    """(schwab-quotes creds symbols) -- quotes for a symbol, or a list or
    vector of them (stocks, ETFs, indexes such as $SPX, options): a table
    of symbol, description, bid, ask, last, mark, the change and percent
    change from the last close, volume, and the 52-week high and low, in
    the order given. A symbol Schwab doesn't know has NaNs."""
    who = "schwab-quotes"
    wanted = text_list(symbols, who, "the symbols")
    answer = api_get(credentials_path, "/marketdata/v1/quotes", who,
                     {"symbols": ",".join(wanted), "fields": "quote,reference"}) or {}
    rows = []
    for symbol in wanted:
        found = answer.get(symbol) or answer.get(symbol.upper()) or {}
        quote = found.get("quote", {})
        rows.append((symbol, found.get("reference", {}).get("description", ""))
                    + tuple(number(quote.get(field)) for _, field in QUOTE_FIELDS))
    return table_of(rows, ["symbol", "description"] + [name for name, _ in QUOTE_FIELDS])


def milliseconds(value, who, what):
    """A date (or "YYYY-MM-DD") as the milliseconds since 1970 Schwab takes."""
    if isinstance(value, LispDate):
        day = value.date
    else:
        try:
            day = datetime.date.fromisoformat(str(value))
        except ValueError:
            raise LispError("%s: %s must be a date, or YYYY-MM-DD text" % (who, what))
    return int(datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def schwab_price_history(credentials_path, symbol, *options):
    """(schwab-price-history creds symbol [:start-date d :end-date d
    :frequency f]) -- a stock's (or ETF's, or index's) prices: a table of
    date, open, high, low, close, and volume, oldest first, as Schwab gives
    them. :frequency is "daily" (the default), "weekly", or "monthly". The
    last 10 years, unless :start-date or :end-date (dates, or YYYY-MM-DD)
    says otherwise."""
    who = "schwab-price-history"
    options = keyword_options(options, ["start-date", "end-date", "frequency"], who)
    frequency = str(options.get("frequency", "daily")).lower()
    if frequency not in ("daily", "weekly", "monthly"):
        raise LispError('%s: :frequency is "daily", "weekly", or "monthly"' % who)
    today = datetime.date.today()
    end = options.get("end-date") or today.isoformat()
    start = options.get("start-date") or today.replace(year=today.year - 10).isoformat()
    answer = api_get(credentials_path, "/marketdata/v1/pricehistory", who,
                     {"symbol": str(symbol), "periodType": "year", "frequencyType": frequency, "frequency": 1,
                      "startDate": milliseconds(start, who, ":start-date"),
                      "endDate": milliseconds(end, who, ":end-date")}) or {}
    candles = answer.get("candles", [])
    if not candles:
        raise LispError("%s: Schwab has no prices for %s in those dates" % (who, symbol))
    rows = []
    for candle in candles:
        day = datetime.datetime.fromtimestamp(candle["datetime"] / 1000, tz=datetime.timezone.utc).date()
        rows.append((LispDate(day.year, day.month, day.day),) +
                    tuple(number(candle.get(k)) for k in ("open", "high", "low", "close", "volume")))
    return table_of(rows, ["date", "open", "high", "low", "close", "volume"])


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def iso_time(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def schwab_orders(credentials_path, *options):
    """(schwab-orders creds [:account a :days n]) -- the orders entered in
    the last n days (30, unless :days says; Schwab keeps 60): a table of
    account, order ID, when it was entered, status, instruction (BUY, SELL,
    ...), symbol, quantity, quantity filled, order type, price, and
    duration -- in all your accounts, or just :account's."""
    who = "schwab-orders"
    options = keyword_options(options, ["account", "days"], who)
    now = datetime.datetime.now(datetime.timezone.utc)
    params = {"fromEnteredTime": iso_time(now - datetime.timedelta(days=int(options.get("days", 30)))),
              "toEnteredTime": iso_time(now)}
    if options.get("account", NIL) is not NIL:
        _, account_hash = find_account(credentials_path, options["account"], who)
        orders = api_get(credentials_path, "/trader/v1/accounts/%s/orders" % account_hash, who, params)
    else:
        orders = api_get(credentials_path, "/trader/v1/orders", who, params)
    rows = []
    for order in orders or []:
        leg = (order.get("orderLegCollection") or [{}])[0]
        rows.append((str(order.get("accountNumber", "")), number(order.get("orderId")), order.get("enteredTime", ""),
                     order.get("status", ""), leg.get("instruction", ""), leg.get("instrument", {}).get("symbol", ""),
                     number(order.get("quantity")), number(order.get("filledQuantity")),
                     order.get("orderType", ""), number(order.get("price")), order.get("duration", "")))
    return table_of(rows, ["account", "order-id", "entered", "status", "instruction", "symbol", "quantity",
                           "filled", "type", "price", "duration"])


INSTRUCTIONS = {"EQUITY": ["BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER"],
                "OPTION": ["BUY_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_OPEN", "SELL_TO_CLOSE"]}
ORDER_TYPES = ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
DURATIONS = ["DAY", "GOOD_TILL_CANCEL", "FILL_OR_KILL"]


def schwab_order(instruction, symbol, quantity, *options):
    """(schwab-order instruction symbol quantity [:type t :price p :stop-price
    s :duration d :asset-type a]) -- an order, as a hash table in Schwab's
    form, to give to schwab-preview-order or schwab-place-order. It sends
    nothing. instruction is BUY, SELL, SELL_SHORT, or BUY_TO_COVER for a
    stock or ETF; BUY_TO_OPEN, BUY_TO_CLOSE, SELL_TO_OPEN, or SELL_TO_CLOSE
    for an option (:asset-type "OPTION", with the option's symbol). :type is
    MARKET (the default), LIMIT (needs :price), STOP (needs :stop-price), or
    STOP_LIMIT (needs both); :duration is DAY (the default),
    GOOD_TILL_CANCEL, or FILL_OR_KILL."""
    who = "schwab-order"
    options = keyword_options(options, ["type", "price", "stop-price", "duration", "asset-type"], who)
    asset_type = str(options.get("asset-type", "EQUITY")).upper()
    instruction = str(instruction).upper()
    order_type = str(options.get("type", "MARKET")).upper()
    duration = str(options.get("duration", "DAY")).upper()
    if asset_type not in INSTRUCTIONS:
        raise LispError('%s: :asset-type is "EQUITY" or "OPTION"' % who)
    if instruction not in INSTRUCTIONS[asset_type]:
        raise LispError("%s: an %s order's instruction is one of %s"
                        % (who, asset_type.lower(), ", ".join(INSTRUCTIONS[asset_type])))
    if order_type not in ORDER_TYPES or duration not in DURATIONS:
        raise LispError("%s: :type is one of %s; :duration one of %s"
                        % (who, ", ".join(ORDER_TYPES), ", ".join(DURATIONS)))
    if not (isinstance(quantity, (int, float)) and quantity > 0):
        raise LispError("%s: the quantity must be a number above 0" % who)
    order = {"session": "NORMAL", "duration": duration, "orderType": order_type, "orderStrategyType": "SINGLE",
             "orderLegCollection": [{"instruction": instruction, "quantity": quantity,
                                     "instrument": {"symbol": str(symbol).upper(), "assetType": asset_type}}]}
    for option, field, needed_by in (("price", "price", ("LIMIT", "STOP_LIMIT")),
                                     ("stop-price", "stopPrice", ("STOP", "STOP_LIMIT"))):
        if order_type in needed_by:
            if not isinstance(options.get(option), (int, float)):
                raise LispError("%s: a %s order needs :%s" % (who, order_type, option))
            order[field] = options[option]
    return json_to_lisp(order)


def lisp_to_json(value):
    """Lisp data as JSON's: a hash table as an object, a list or vector as
    an array."""
    if isinstance(value, LispHashTable):
        return {str(k): lisp_to_json(v) for k, v in value.table.items()}
    if isinstance(value, Pair) or value is NIL:
        return [lisp_to_json(v) for v in pairs_to_list(value)]
    if isinstance(value, LispVector):
        return [lisp_to_json(v) for v in value.items.tolist()]
    if isinstance(value, Keyword):
        return str(value)[1:]
    if isinstance(value, str):
        return str(value)
    return value


def order_json(order, who):
    if not isinstance(order, LispHashTable):
        raise LispError("%s: the order must be a hash table, such as schwab-order makes" % who)
    return lisp_to_json(order)


def schwab_preview_order(credentials_path, account, order):
    """(schwab-preview-order creds account order) -- what Schwab makes of an
    order, without placing it: its answer (as Lisp data), with any warnings
    or reasons it would be rejected, and the estimated cost."""
    who = "schwab-preview-order"
    _, account_hash = find_account(credentials_path, account, who)
    _, answer = api_call(credentials_path, "POST", "/trader/v1/accounts/%s/previewOrder" % account_hash, who,
                         json_body=order_json(order, who))
    return json_to_lisp(answer) if answer is not None else NIL


def schwab_place_order(credentials_path, account, order, *options):
    """(schwab-place-order creds account order :confirm #t) -- place an
    order, for real, in the account (its number, or its last few digits).
    Nothing is sent without :confirm #t. Returns the order's ID. (The app
    can place at most 10 orders a day.)"""
    who = "schwab-place-order"
    options = keyword_options(options, ["confirm"], who)
    if options.get("confirm") is not True:
        raise LispError("%s: nothing was sent -- to place the order, for real, give :confirm #t" % who)
    body = order_json(order, who)
    account_number, account_hash = find_account(credentials_path, account, who)
    headers, _ = api_call(credentials_path, "POST", "/trader/v1/accounts/%s/orders" % account_hash, who,
                          json_body=body)
    location = headers.get("Location") or headers.get("location") or ""
    order_id = location.rstrip("/").split("/")[-1]
    return int(order_id) if order_id.isdigit() else LispString(order_id)


def schwab_cancel_order(credentials_path, account, order_id):
    """(schwab-cancel-order creds account order-id) -- cancel an order that
    hasn't been filled. Returns #t."""
    who = "schwab-cancel-order"
    _, account_hash = find_account(credentials_path, account, who)
    api_call(credentials_path, "DELETE", "/trader/v1/accounts/%s/orders/%s" % (account_hash, int(order_id)), who)
    return True


def schwab_get(credentials_path, path, parameters=NIL):
    """(schwab-get creds path [parameters]) -- the answer to any of the API's
    requests for information, as Lisp data: path is its path, such as
    "/trader/v1/userPreference" or "/marketdata/v1/chains", and parameters
    a list of (name . value) pairs."""
    who = "schwab-get"
    params = {}
    for entry in pairs_to_list(parameters):
        if not isinstance(entry, Pair):
            raise LispError('%s: the parameters are a list of (name . value) pairs, such as ("symbol" . "AAPL")' % who)
        params[str(entry.car)] = str(entry.cdr.car if isinstance(entry.cdr, Pair) else entry.cdr)
    return json_to_lisp(api_get(credentials_path, "/" + str(path).lstrip("/"), who, params))


BUILTINS = {
    "schwab-login": schwab_login,
    "schwab-accounts": schwab_accounts,
    "schwab-positions": schwab_positions,
    "schwab-quotes": schwab_quotes,
    "schwab-price-history": schwab_price_history,
    "schwab-orders": schwab_orders,
    "schwab-get": schwab_get,
    "schwab-order": schwab_order,
    "schwab-preview-order": schwab_preview_order,
    "schwab-place-order": schwab_place_order,
    "schwab-cancel-order": schwab_cancel_order,
}
