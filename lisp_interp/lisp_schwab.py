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
  (schwab-accounts creds)                    each account: its name, type, value, and cash
  (schwab-positions creds [:account a])      what's in each account: a row per holding
  (schwab-quotes creds symbols)              quotes
  (schwab-price-history creds symbol [:start-date :end-date :frequency])
                                             daily (or weekly or monthly) prices
  (schwab-option-chain creds symbol [:expiration d :type t :strikes n])
                                             the options listed on a stock: bids, asks, volume
  (schwab-orders creds [:account a :days n]) the orders of the last n days
  (schwab-get creds path [parameters])       any of the API's other requests
Orders:
  (schwab-order instruction symbol quantity [:type :price :stop-price :duration :asset-type])
                                             an order, to preview or place
  (schwab-spread-order buy-symbol sell-symbol quantity net-debit [:duration d])
                                             an order for a vertical spread: two options, for a net debit
  (schwab-multi-leg-order strategy legs price [:credit #t :duration d])
                                             an order for a vertical, butterfly, iron condor, straddle, or strangle
  (schwab-preview-order creds account order) what Schwab would make of it; nothing is placed
  (schwab-place-order creds account order :confirm #t)
  (schwab-cancel-order creds account order-id)

The credentials file's "Schwab_Client_ID" and "Schwab_Client_Secret"
entries are the app's key and secret ("Schwab_Callback_URL" too, if the
app's isn't https://127.0.0.1). The tokens are kept in schwab_tokens.json,
next to the credentials file, readable only by you. Nothing is cached:
every call asks Schwab.

Accounts are shown by name: the nickname you gave each one on Schwab's
site. Wherever an account is wanted, it can be given by that name, by its
number, or by the last few digits of its number.

The comments in each function list all the fields Schwab's answer has,
including the ones its table leaves out; (schwab-get creds path) gets them.
"""

import base64
import datetime
import importlib.util
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from lisp_core import (
    Keyword, LispDate, LispError, LispHashTable, LispString, LispVector, NIL, Pair, date_argument, keyword_options,
    NETWORK, is_true, lisp_error_of_kind, pairs_to_list,
)
import lisp_data_common
from lisp_data_common import credential, text_list
from lisp_http import json_to_lisp, unavailable
from lisp_tables import table_from_tuples
from lisp_tastytrade import OPTION_CHAIN_COLUMNS

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
        raise lisp_error_of_kind("%s: Schwab says (HTTP %d): %s" % (who, e.code, schwab_message(text)),
                                 NETWORK if unavailable(e.code) else None)
    except (urllib.error.URLError, OSError) as e:
        raise lisp_error_of_kind("%s: couldn't reach Schwab: %s" % (who, e), NETWORK)


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
    return lisp_data_common.token_file(credentials_path, "Schwab")


def save_tokens(credentials_path, tokens):
    """Save the tokens, readable only by you."""
    lisp_data_common.save_tokens(credentials_path, "Schwab", tokens)


def load_tokens(credentials_path, who):
    return lisp_data_common.load_tokens(credentials_path, "Schwab", who)


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
    from PyQt6.QtCore import QEventLoop, QTimer, QUrl
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
    # Close the window, then let Qt run for a second to carry that out. In a
    # notebook or at the console, nothing else runs Qt's events, so without
    # this the window would stay on the screen. (A quarter of a second isn't
    # enough: macOS's animation of the window closing would stop part way.)
    window.close()
    closing = QEventLoop()
    QTimer.singleShot(1000, closing.quit)
    closing.exec()
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


def account_names(credentials_path, who):
    """Each account's name, by its number: the nickname you gave it on
    Schwab's site, or -- for one without a nickname -- "..." and the last 4
    digits of its number.

    Schwab's /trader/v1/userPreference answer has, for each account (in
    "accounts"): accountNumber, primaryAccount, type, nickName,
    displayAcctId (such as "...1234"), autoPositionEffect, accountColor,
    lotSelectionMethod, hasFuturesAccount, hasForexAccount. (Besides
    "accounts", it has "streamerInfo" and "offers", which aren't used.)"""
    preferences = api_get(credentials_path, "/trader/v1/userPreference", who) or {}
    names = {}
    for account in preferences.get("accounts", []):
        number_text = str(account.get("accountNumber", ""))
        names[number_text] = (account.get("nickName") or "").strip() or "..." + number_text[-4:]
    return names


def account_name(names, account_number):
    """An account's name, from account_names (its number's last 4 digits if
    Schwab didn't list it)."""
    number_text = str(account_number)
    return names.get(number_text) or "..." + number_text[-4:]


def find_account(credentials_path, account, who):
    """An account's number and the code ("hash") the API names it by: given
    as its name (upper or lower case), its number, or the last 3 or more
    digits of it (as text, to keep leading zeros)."""
    accounts = api_get(credentials_path, "/trader/v1/accounts/accountNumbers", who) or []
    names = account_names(credentials_path, who)
    text = str(int(account)) if isinstance(account, (int, float)) else str(account).strip()
    matches = [a for a in accounts if account_name(names, a["accountNumber"]).lower() == text.lower()]
    if not matches:
        matches = [a for a in accounts
                   if a["accountNumber"] == text or (len(text) >= 3 and a["accountNumber"].endswith(text))]
    if len(matches) != 1:
        raise LispError("%s: %s account matches %r -- the accounts are %s"
                        % (who, "more than one" if matches else "no", text,
                           ", ".join(account_name(names, a["accountNumber"]) for a in accounts)))
    return matches[0]["accountNumber"], matches[0]["hashValue"]


def number(value):
    """A number from Schwab's answer, or NaN for none."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else float("nan")


# ---------------------------------------------------------------------------
# Accounts and positions
# ---------------------------------------------------------------------------

def schwab_accounts(credentials_path):
    """(schwab-accounts creds) -- each of your accounts: a table of its
    name, type (CASH or MARGIN), value (what it would be worth sold:
    Schwab's liquidation value), cash, and the market value of its long
    and short positions."""
    # Schwab's /trader/v1/accounts answer has, for each account:
    #
    #   securitiesAccount: accountNumber, type, roundTrips, isDayTrader,
    #     isClosingOnlyRestricted, isPortfolioMargin, isIntradayMargin, pfcbFlag;
    #     positions (see schwab-positions), with ?fields=positions;
    #     initialBalances (at the start of the day), currentBalances, and
    #     projectedBalances, each some of these:
    #       accountValue, accruedInterest, availableFunds,
    #       availableFundsNonMarginableTrade, bondValue, buyingPower,
    #       buyingPowerNonMarginableTrade, cashAvailableForTrading,
    #       cashAvailableForWithdrawal, cashBalance, cashCall, cashDebitCallValue,
    #       cashReceipts, dayTradingBuyingPower, dayTradingBuyingPowerCall,
    #       dayTradingEquityCall, equity, equityPercentage,
    #       intradayBuyingPowerAmount, isInCall, liquidationValue,
    #       longMarginValue, longMarketValue, longNonMarginableMarketValue,
    #       longOptionMarketValue, longStockValue, maintenanceCall,
    #       maintenanceRequirement, margin, marginBalance, marginEquity,
    #       moneyMarketFund, mutualFundValue, pendingDeposits, regTCall,
    #       savings, shortBalance, shortMarginValue, shortMarketValue,
    #       shortOptionMarketValue, shortStockValue, sma, stockBuyingPower,
    #       totalCash, unsettledCash
    #   aggregatedBalance: currentLiquidationValue, liquidationValue,
    #     intradayBuyingPowerAmount, currentIntradayBuyingPowerAmount
    #
    # The table uses type and currentBalances' liquidationValue, cashBalance,
    # longMarketValue, and shortMarketValue. The rest can be had with
    # (schwab-get creds "/trader/v1/accounts").
    who = "schwab-accounts"
    names = account_names(credentials_path, who)
    rows = []
    for entry in api_get(credentials_path, "/trader/v1/accounts", who) or []:
        account = entry.get("securitiesAccount", {})
        balances = account.get("currentBalances", {})
        rows.append((account_name(names, account.get("accountNumber", "")), account.get("type", ""),
                     number(balances.get("liquidationValue")), number(balances.get("cashBalance")),
                     number(balances.get("longMarketValue")), number(balances.get("shortMarketValue"))))
    return table_from_tuples(rows, ["account", "type", "value", "cash", "long-value", "short-value"])


POSITION_COLUMNS = ["account", "symbol", "description", "asset-type", "quantity", "average-price",
                    "market-value", "unrealized-gain", "day-gain", "cusip"]


def position_row(account, position):
    """One holding: what it is, how much (short positions negative), what it
    cost on average, and what it's worth and has gained."""
    instrument = position.get("instrument", {})
    gains = [position.get(k) for k in ("longOpenProfitLoss", "shortOpenProfitLoss") if position.get(k) is not None]
    return (account, instrument.get("symbol", ""), instrument.get("description", ""),
            instrument.get("assetType", ""),
            number(position.get("longQuantity") or 0) - number(position.get("shortQuantity") or 0),
            number(position.get("averagePrice")), number(position.get("marketValue")),
            sum(gains) if gains else float("nan"), number(position.get("currentDayProfitLoss")),
            instrument.get("cusip", ""))


def schwab_positions(credentials_path, *options):
    """(schwab-positions creds [:account a]) -- what's in your accounts: a
    table with a row for each holding in each account -- or just one
    account's, given by its name, its number, or its last few digits -- of
    the account's name, symbol, description, asset type (EQUITY, OPTION, ...),
    quantity (negative for a short position), average price paid, market
    value, unrealized gain, today's gain, and CUSIP. Cash isn't a holding:
    see schwab-accounts."""
    # Schwab's answer has, for each holding (securitiesAccount's "positions"):
    #
    #   longQuantity, shortQuantity, settledLongQuantity, settledShortQuantity,
    #   previousSessionLongQuantity, previousSessionShortQuantity, agedQuantity,
    #   averagePrice, averageLongPrice, averageShortPrice,
    #   taxLotAverageLongPrice, taxLotAverageShortPrice,
    #   marketValue, maintenanceRequirement, currentDayCost,
    #   longOpenProfitLoss, shortOpenProfitLoss,
    #   currentDayProfitLoss, currentDayProfitLossPercentage,
    #   instrument: assetType, symbol, cusip, description, netChange,
    #     uniformSymbol, type; and for an option, putCall and underlyingSymbol
    #
    # The table uses longQuantity less shortQuantity, averagePrice,
    # marketValue, longOpenProfitLoss plus shortOpenProfitLoss,
    # currentDayProfitLoss, and the instrument's symbol, description,
    # assetType, and cusip. The rest can be had with
    # (schwab-get creds "/trader/v1/accounts" '(("fields" . "positions"))).
    who = "schwab-positions"
    options = keyword_options(options, ["account"], who)
    if options.get("account", NIL) is not NIL:
        _, account_hash = find_account(credentials_path, options["account"], who)
        entries = [api_get(credentials_path, "/trader/v1/accounts/" + account_hash, who, {"fields": "positions"})]
    else:
        entries = api_get(credentials_path, "/trader/v1/accounts", who, {"fields": "positions"}) or []
    names = account_names(credentials_path, who)
    rows = []
    for entry in entries:
        account = (entry or {}).get("securitiesAccount", {})
        for position in account.get("positions", []):
            rows.append(position_row(account_name(names, account.get("accountNumber", "")), position))
    return table_from_tuples(rows, POSITION_COLUMNS)


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
    # Schwab's answer has, for each symbol (an index, such as $SPX, has fewer):
    #
    #   assetMainType, assetSubType, quoteType, realtime, ssid, symbol
    #   quote: 52WeekHigh, 52WeekLow, askMICId, askPrice, askSize, askTime,
    #     bidMICId, bidPrice, bidSize, bidTime, closePrice, highPrice, lastMICId,
    #     lastPrice, lastSize, lowPrice, mark, markChange, markPercentChange,
    #     netChange, netPercentChange, openPrice, postMarketChange,
    #     postMarketPercentChange, quoteTime, securityStatus, totalVolume,
    #     tradeTime (the times in milliseconds since 1970)
    #   reference: cusip, description, exchange, exchangeName, isHardToBorrow,
    #     isShortable, htbRate, optionable, ethOptionEligible, hasBinaryOptions
    #   fundamental (with "fundamental" in fields): avg10DaysVolume,
    #     avg1YearVolume, declarationDate, divAmount, divExDate, divFreq,
    #     divPayAmount, divPayDate, divYield, eps, fundLeverageFactor,
    #     lastEarningsDate, nextDivExDate, nextDivPayDate, peRatio,
    #     sharesOutstanding
    #   extended (with "extended"; trading outside market hours): askPrice,
    #     askSize, bidPrice, bidSize, lastPrice, lastSize, mark, quoteTime,
    #     totalVolume, tradeTime
    #   regular (with "regular"): regularMarketLastPrice,
    #     regularMarketLastSize, regularMarketNetChange,
    #     regularMarketPercentChange, regularMarketTradeTime
    #
    # The table uses reference's description and the quote fields in
    # QUOTE_FIELDS. The rest can be had with (schwab-get creds
    # "/marketdata/v1/quotes" '(("symbols" . "AAPL,SPY") ("fields" . "quote,reference,fundamental"))).
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
    return table_from_tuples(rows, ["symbol", "description"] + [name for name, _ in QUOTE_FIELDS])


def first_number(answer, *names):
    """The first of these fields of Schwab's answer that is a number, or NaN."""
    for name in names:
        value = answer.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return float("nan")


def known(value):
    """value, or NaN if it is one Schwab fills in when it has none: -999."""
    return float("nan") if value == -999 else value


def chain_row(kind, expiration_key, strike_key, contract, underlying, underlying_price):
    """One option's row of the chain table, in OPTION_CHAIN_COLUMNS' order."""
    day_text, _, days_text = expiration_key.partition(":")
    day = datetime.date.fromisoformat(day_text)
    bid, ask = first_number(contract, "bid", "bidPrice"), first_number(contract, "ask", "askPrice")
    strike = first_number(contract, "strikePrice")
    return (LispString(contract["symbol"]), LispString(kind),
            float(strike if strike == strike else strike_key),
            LispDate(day.year, day.month, day.day),
            int(days_text) if days_text.isdigit() else number(contract.get("daysToExpiration")),
            None, LispString(underlying), underlying_price, bid, ask, (bid + ask) / 2,
            first_number(contract, "last", "lastPrice"),
            known(first_number(contract, "volatility")) / 100,            # (Schwab gives it in percent)
            known(first_number(contract, "delta")), known(first_number(contract, "vega")),
            first_number(contract, "totalVolume"), first_number(contract, "openInterest"))


def chain_table(answer, who):
    """The table of the options in Schwab's answer to a request for a chain."""
    if not isinstance(answer, dict):
        raise LispError("%s: Schwab sent no chain" % who)
    if answer.get("status") not in (None, "SUCCESS"):
        raise LispError("%s: Schwab says the chain's status is %s" % (who, answer.get("status")))
    if answer.get("isChainTruncated") is True:
        raise LispError("%s: Schwab cut the chain short -- it has more than it will send at once. Ask for less: "
                        "one :expiration, or only some :strikes" % who)
    underlying = str(answer.get("symbol", ""))
    quote = answer.get("underlying") or {}
    price = first_number(answer, "underlyingPrice")
    if price != price:
        price = first_number(quote, "mark", "last", "lastPrice")
    rows = []
    for kind, field in (("Call", "callExpDateMap"), ("Put", "putExpDateMap")):
        for expiration_key, by_strike in (answer.get(field) or {}).items():
            for strike_key, contracts in by_strike.items():
                for contract in contracts:
                    if not contract.get("symbol"):
                        raise LispError("%s: Schwab's chain has an option with no symbol" % who)
                    rows.append(chain_row(kind, expiration_key, strike_key, contract, underlying, price))
    rows.sort(key=lambda row: (row[3].date, row[2], row[1]))
    return table_from_tuples(rows, OPTION_CHAIN_COLUMNS)


def schwab_option_chain(credentials_path, symbol, *options):
    """(schwab-option-chain creds symbol [:expiration d :type t :strikes n]) --
    the options listed on a stock or ETF, as a table with the columns of
    tastytrade-option-chain's -- so what takes one takes the other: symbol (the
    option's, in the form orders use), type ("Call" or "Put"), strike,
    expiration-date, days-to-expiration, delivery-month (always '()),
    underlying, underlying-price, bid, ask, mid, last-price,
    implied-volatility, delta, vega, volume, and open-interest. The bids and
    asks are live while the market is open, and the last close's after.
    :expiration (a date, or "YYYY-MM-DD") asks for only that expiration's;
    without it, every expiration Schwab has, which can be a lot. :type is
    "CALL", "PUT", or "ALL" (the default). :strikes asks for only that many
    strikes nearest the price, in each expiration."""
    # Schwab's answer (to /marketdata/v1/chains) has assetMainType, assetSubType, symbol, status,
    # strategy, interval, isDelayed, isIndex, isChainTruncated, numberOfContracts, daysToExpiration,
    # interestRate (percent), dividendYield, underlyingPrice, volatility, ethOptionEligible,
    # hasBinaryOptions, underlying (a quote: bid, ask, last, mark, ...), and callExpDateMap and
    # putExpDateMap: {"2026-11-20:35": {"700.0": [contract]}}, each contract with ask, askSize, bid,
    # bidSize, bidAskSize, breakEven, closePrice, daysToExpiration, deliverableNote, delta,
    # description, exchangeName, exerciseType, expirationDate, expirationType, extrinsicValue, gamma,
    # high52Week, highPrice, inTheMoney, intrinsicValue, last, lastSize, lastTradingDay, low52Week,
    # lowPrice, mark, markChange, markPercentChange, mini, multiplier, netChange, nonStandard,
    # openInterest, openPrice, optionDeliverablesList, optionRoot, pennyPilot, percentChange,
    # putCall, quoteTimeInLong, rho, settlementType, ssid, strikePrice, symbol,
    # theoreticalOptionValue, theoreticalVolatility, theta, timeValue, totalVolume,
    # tradeTimeInLong, and vega. Its volatility is in percent. -999 stands for a Greek or
    # volatility it doesn't have. The table has the most useful; (schwab-get creds
    # "/marketdata/v1/chains" '(("symbol" . "SPY") ("contractType" . "CALL"))) has the rest.
    who = "schwab-option-chain"
    options = keyword_options(options, ["expiration", "type", "strikes"], who)
    kind = str(options.get("type", "ALL")).upper()
    if kind not in ("CALL", "PUT", "ALL"):
        raise LispError('%s: :type is "CALL", "PUT", or "ALL", not %s' % (who, kind))
    params = {"symbol": str(symbol).strip().upper(), "contractType": kind, "strategy": "SINGLE",
              "includeUnderlyingQuote": "true"}
    if "expiration" in options:
        day = date_argument(options["expiration"], who, ":expiration").isoformat()
        params["fromDate"] = params["toDate"] = day
    if "strikes" in options:
        strikes = options["strikes"]
        if not isinstance(strikes, int) or isinstance(strikes, bool) or strikes < 1:
            raise LispError("%s: :strikes must be a whole number, 1 or more" % who)
        params["strikeCount"] = str(strikes)
    return chain_table(api_get(credentials_path, "/marketdata/v1/chains", who, params), who)


def milliseconds(value, who, what):
    """A date (or "YYYY-MM-DD") as the milliseconds since 1970 Schwab takes."""
    day = date_argument(value, who, what)
    return int(datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def schwab_price_history(credentials_path, symbol, *options):
    """(schwab-price-history creds symbol [:start-date d :end-date d
    :frequency f]) -- a stock's (or ETF's, or index's) prices: a table of
    date, open, high, low, close, and volume, oldest first, as Schwab gives
    them. :frequency is "daily" (the default), "weekly", or "monthly". The
    last 10 years, unless :start-date or :end-date (dates, or YYYY-MM-DD)
    says otherwise."""
    # Schwab's answer has symbol, empty (true if there are no prices), and
    # candles, each with datetime (milliseconds since 1970), open, high,
    # low, close, and volume -- all of which the table uses.
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
    return table_from_tuples(rows, ["date", "open", "high", "low", "close", "volume"])


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
    # Schwab's answer has, for each order:
    #
    #   accountNumber, orderId, status, enteredTime, closeTime, session,
    #   duration, orderType, complexOrderStrategyType, orderStrategyType,
    #   quantity, filledQuantity, remainingQuantity, price, cancelable,
    #   editable, requestedDestination, destinationLinkName
    #   orderLegCollection (one per leg): orderLegType, legId, instruction,
    #     positionEffect, quantity, instrument (assetType, cusip, symbol,
    #     uniformSymbol, description, instrumentId, type; for an option,
    #     putCall, underlyingSymbol, and optionDeliverables: symbol,
    #     deliverableUnits)
    #   orderActivityCollection (one per fill): activityType, activityId,
    #     executionType, quantity, orderRemainingQuantity, executionLegs
    #     (legId, quantity, mismarkedQuantity, price, time, instrumentId)
    #
    # Others appear on some orders, such as stopPrice, and childOrderStrategies
    # for one order that sets off another. The table uses accountNumber,
    # orderId, enteredTime, status, quantity, filledQuantity, orderType,
    # price, duration, and the first leg's instruction and symbol. The rest
    # can be had with (schwab-get creds "/trader/v1/orders" ...), giving
    # fromEnteredTime and toEnteredTime.
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
    names = account_names(credentials_path, who)
    rows = []
    for order in orders or []:
        leg = (order.get("orderLegCollection") or [{}])[0]
        rows.append((account_name(names, order.get("accountNumber", "")), number(order.get("orderId")), order.get("enteredTime", ""),
                     order.get("status", ""), leg.get("instruction", ""), leg.get("instrument", {}).get("symbol", ""),
                     number(order.get("quantity")), number(order.get("filledQuantity")),
                     order.get("orderType", ""), number(order.get("price")), order.get("duration", "")))
    return table_from_tuples(rows, ["account", "order-id", "entered", "status", "instruction", "symbol", "quantity",
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


OPTION_SYMBOL = re.compile(r"^([A-Z][A-Z0-9.]{0,5}) *(\d{6})([CP])(\d{8})$")


def option_symbol_parts(symbol, who, what):
    """An option's symbol -- the stock's, padded with spaces to 6 characters;
    the expiration as YYMMDD; C or P; the strike times 1000, in 8 digits --
    as (stock, expiration, C or P, strike, the symbol as Schwab wants it)."""
    match = OPTION_SYMBOL.match(str(symbol).strip().upper())
    if not match:
        raise LispError('%s: %s must be an option\'s symbol, such as "SPY   261218C00700000" (the stock\'s, '
                        'padded with spaces to 6 characters; the expiration as YYMMDD; C or P; the strike times '
                        '1000 in 8 digits), not %s' % (who, what, to_display(symbol)))
    stock, expiration, kind, strike = match.groups()
    return stock, expiration, kind, int(strike) / 1000, stock.ljust(6) + expiration + kind + strike


def to_display(value):
    return value if isinstance(value, str) else repr(value)


def schwab_spread_order(buy_symbol, sell_symbol, quantity, net_debit, *options):
    """(schwab-spread-order buy-symbol sell-symbol quantity net-debit
    [:duration d]) -- an order, as a hash table in Schwab's form, to open a
    vertical spread: buy one option and sell another of the same stock,
    expiration, and type, for a net debit, a limit on what is paid in all, a
    share. quantity is how many spreads (contracts of each). It sends nothing:
    give it to schwab-preview-order or schwab-place-order. For calls, the one
    bought has the lower strike; for puts, the higher -- the other way round
    would be a credit spread, which is not made here. :duration is DAY (the
    default), GOOD_TILL_CANCEL, or FILL_OR_KILL. The net debit is rounded to a
    cent."""
    who = "schwab-spread-order"
    options = keyword_options(options, ["duration"], who)
    duration = str(options.get("duration", "DAY")).upper()
    if duration not in DURATIONS:
        raise LispError("%s: :duration is one of %s" % (who, ", ".join(DURATIONS)))
    bought = option_symbol_parts(buy_symbol, who, "the option to buy")
    sold = option_symbol_parts(sell_symbol, who, "the option to sell")
    if bought[:3] != sold[:3]:
        raise LispError("%s: the two options must be of the same stock, expiration, and type (calls or puts): "
                        "%s and %s are not" % (who, bought[4], sold[4]))
    if bought[3] == sold[3]:
        raise LispError("%s: the two options have the same strike" % who)
    if (bought[3] < sold[3]) != (bought[2] == "C"):
        raise LispError("%s: buying the %s at %g and selling the %s at %g would be a credit spread: for a debit "
                        "spread, a call bought has the lower strike, and a put the higher"
                        % (who, "call" if bought[2] == "C" else "put", bought[3],
                           "call" if bought[2] == "C" else "put", sold[3]))
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise LispError("%s: the quantity is a whole number of spreads, 1 or more" % who)
    if not isinstance(net_debit, (int, float)) or isinstance(net_debit, bool) or round(net_debit, 2) <= 0:
        raise LispError("%s: the net debit must be a number above 0 (to the cent)" % who)
    leg = lambda instruction, parts: {"instruction": instruction, "quantity": quantity,
                                      "instrument": {"symbol": parts[4], "assetType": "OPTION"}}
    return json_to_lisp({"session": "NORMAL", "duration": duration, "orderType": "NET_DEBIT",
                         "complexOrderStrategyType": "VERTICAL", "price": round(float(net_debit), 2),
                         "orderStrategyType": "SINGLE",
                         "orderLegCollection": [leg("BUY_TO_OPEN", bought), leg("SELL_TO_OPEN", sold)]})


STRATEGIES = ["VERTICAL", "BUTTERFLY", "IRON_CONDOR", "STRADDLE", "STRANGLE"]
OPENING = {"BUY_TO_OPEN": 1, "SELL_TO_OPEN": -1}          # an option bought, or sold: +1 or -1


def parse_leg(leg, who):
    """A leg given as a list (instruction symbol quantity) as a dict: its instruction, side (+1 to buy, -1 to
    sell), quantity, and the parts of the option's symbol."""
    items = pairs_to_list(leg) if isinstance(leg, Pair) else None
    if items is None or len(items) != 3:
        raise LispError("%s: a leg is a list of three things: (instruction symbol quantity), such as "
                        '("BUY_TO_OPEN" "SPY   261120C00700000" 1)' % who)
    instruction = str(items[0]).upper()
    if instruction not in OPENING:
        raise LispError("%s: a leg's instruction is BUY_TO_OPEN or SELL_TO_OPEN (this opens new positions), not %s"
                        % (who, to_display(items[0])))
    quantity = items[2]
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise LispError("%s: a leg's quantity is a whole number of contracts, 1 or more" % who)
    stock, expiration, kind, strike, text = option_symbol_parts(items[1], who, "a leg's option")
    return {"instruction": instruction, "side": OPENING[instruction], "quantity": quantity, "stock": stock,
            "expiration": expiration, "kind": kind, "strike": round(strike * 1000), "symbol": text}


def check_strategy(strategy, legs, who):
    """Whether the legs have the shape of the strategy -- the strikes, sides, and quantities that Schwab's
    complexOrderStrategyType of that name means -- or an error that says what's wrong."""
    def wrong(why):
        raise LispError("%s: %s legs %s" % (who, strategy, why))
    counts = {"VERTICAL": 2, "BUTTERFLY": 3, "IRON_CONDOR": 4, "STRADDLE": 2, "STRANGLE": 2}
    if len(legs) != counts[strategy]:
        wrong("need %d options, not %d" % (counts[strategy], len(legs)))
    kinds = [leg["kind"] for leg in legs]
    ordered = sorted(legs, key=lambda leg: (leg["strike"], 0 if leg["kind"] == "P" else 1))
    sides = [leg["side"] for leg in ordered]
    quantities = [leg["quantity"] for leg in ordered]
    strikes = [leg["strike"] for leg in ordered]
    if strategy in ("VERTICAL", "BUTTERFLY") and len(set(kinds)) != 1:
        wrong("are all calls or all puts")
    if strategy == "VERTICAL":
        if strikes[0] == strikes[1]:
            wrong("need different strikes")
        if sides[0] == sides[1]:
            wrong("buy one option and sell the other")
        if quantities[0] != quantities[1]:
            wrong("need the same quantity of each")
    elif strategy == "BUTTERFLY":
        if len(set(strikes)) != 3 or strikes[1] - strikes[0] != strikes[2] - strikes[1]:
            wrong("need three strikes equally far apart")
        if not (sides[0] == sides[2] == -sides[1]):
            wrong("buy the outer two and sell the middle one (or sell the outer and buy the middle)")
        if quantities[1] != 2 * quantities[0] or quantities[2] != quantities[0]:
            wrong("are in the quantities 1, 2, 1: the middle option twice")
    elif strategy == "IRON_CONDOR":
        if sorted(kinds) != ["C", "C", "P", "P"] or [leg["kind"] for leg in ordered] != ["P", "P", "C", "C"]:
            wrong("are two puts below two calls (the puts' strikes no higher than the calls')")
        if not (strikes[0] < strikes[1] <= strikes[2] < strikes[3]):
            wrong("need four strikes in order, the middle two the same or higher than one another")
        if strikes[1] - strikes[0] != strikes[3] - strikes[2]:
            wrong("need wings of the same width (a different width is an unbalanced condor)")
        if not (sides[0] == sides[3] == -sides[1] == -sides[2]):
            wrong("buy the outer two and sell the inner two (or the other way round)")
        if len(set(quantities)) != 1:
            wrong("need the same quantity of each")
    else:                                                       # STRADDLE or STRANGLE
        if sorted(kinds) != ["C", "P"]:
            wrong("are a call and a put")
        call = next(leg for leg in legs if leg["kind"] == "C")
        put = next(leg for leg in legs if leg["kind"] == "P")
        if strategy == "STRADDLE" and call["strike"] != put["strike"]:
            wrong("need the same strike for the call and the put (with different strikes it is a strangle)")
        if strategy == "STRANGLE" and not put["strike"] < call["strike"]:
            wrong("need the put's strike below the call's")
        if call["side"] != put["side"]:
            wrong("both buy, or both sell")
        if call["quantity"] != put["quantity"]:
            wrong("need the same quantity of each")


def schwab_multi_leg_order(strategy, legs, price, *options):
    """(schwab-multi-leg-order strategy legs price [:credit #t :duration d]) -- an order, as a hash table
    in Schwab's form, to open a spread of several options as one order. strategy is VERTICAL, BUTTERFLY,
    IRON_CONDOR, STRADDLE, or STRANGLE, and the legs must have its shape (a vertical: two options of one
    type, one bought and the other sold; a butterfly: three of one type, equally far apart, bought, sold twice,
    bought; an iron condor: two puts below two calls, with wings the same width; a straddle: a call and a put at
    one strike; a strangle: a put below a call). legs is a list of (instruction symbol quantity): the
    instruction BUY_TO_OPEN or SELL_TO_OPEN, the option's symbol, and how many contracts. price is a limit on
    the net debit a share (what is paid in all), or with :credit #t on the net credit (what is got): above 0,
    rounded to a cent. It sends nothing: give it to schwab-preview-order or schwab-place-order. :duration is
    DAY (the default), GOOD_TILL_CANCEL, or FILL_OR_KILL."""
    who = "schwab-multi-leg-order"
    options = keyword_options(options, ["credit", "duration"], who)
    duration = str(options.get("duration", "DAY")).upper()
    if duration not in DURATIONS:
        raise LispError("%s: :duration is one of %s" % (who, ", ".join(DURATIONS)))
    strategy = str(strategy).upper()
    if strategy not in STRATEGIES:
        raise LispError("%s: the strategy is one of %s, not %s" % (who, ", ".join(STRATEGIES), to_display(strategy)))
    if not (isinstance(legs, Pair) or legs is NIL):
        raise LispError("%s: legs is a list of (instruction symbol quantity)" % who)
    parsed = [parse_leg(leg, who) for leg in pairs_to_list(legs)]
    if len({(leg["stock"], leg["expiration"]) for leg in parsed}) > 1:
        raise LispError("%s: the options must all be of the same stock and expiration" % who)
    if len({leg["symbol"] for leg in parsed}) < len(parsed):
        raise LispError("%s: two legs are the same option" % who)
    check_strategy(strategy, parsed, who)
    credit = is_true(options.get("credit", False))
    word = "credit" if credit else "debit"
    if not isinstance(price, (int, float)) or isinstance(price, bool) or round(price, 2) <= 0:
        raise LispError("%s: the net %s must be a number above 0 (to the cent)" % (who, word))
    leg_json = [{"instruction": leg["instruction"], "quantity": leg["quantity"],
                 "instrument": {"symbol": leg["symbol"], "assetType": "OPTION"}} for leg in parsed]
    return json_to_lisp({"session": "NORMAL", "duration": duration,
                         "orderType": "NET_CREDIT" if credit else "NET_DEBIT",
                         "complexOrderStrategyType": strategy, "price": round(float(price), 2),
                         "orderStrategyType": "SINGLE", "orderLegCollection": leg_json})


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
    order, for real, in the account (its name, its number, or its last few
    digits). Nothing is sent without :confirm #t. Returns the order's ID.
    (The app can place at most 10 orders a day.)"""
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
    "schwab-option-chain": schwab_option_chain,
    "schwab-order": schwab_order,
    "schwab-spread-order": schwab_spread_order,
    "schwab-multi-leg-order": schwab_multi_leg_order,
    "schwab-preview-order": schwab_preview_order,
    "schwab-place-order": schwab_place_order,
    "schwab-cancel-order": schwab_cancel_order,
}
