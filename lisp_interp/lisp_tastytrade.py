"""tastytrade (real broker data) for the Lisp interpreter.

One general function reaches everything tastytrade's API can tell you:

  (tastytrade-get credentials-path path [parameters])
      any of the API's GET requests -- market data, instruments, option
      chains, market metrics, accounts, positions, balances, transactions,
      orders, watchlists, ... -- with the answer as Lisp data. The requests
      are listed at https://developer.tastytrade.com/open-api-spec/ .

The others are special cases of it:

  tastytrade-get-table        what a request returns, as a table
  tastytrade-quotes           bid, ask, last, ... for any symbols (and implied
                              volatility and Greeks, for options)
  tastytrade-option-chain     an option chain, with prices, as a table
  tastytrade-futures-curve, tastytrade-futures-curve-rows
                              a futures term structure
  tastytrade-test-connection

plus tastytrade-products. A futures curve's rows are what lisp_futures.py's
futures-curve-fit and futures-leg-carry analyze.

Every request only reads: nothing here places, changes, or cancels an
order.

Logging in uses the community `tastytrade` package (pip install tastytrade,
version 12 or later), a tastytrade account, and a credentials JSON file --
see tasty_api/README.md for the one-time OAuth setup. Each builtin is a
plain synchronous function that runs the package's async calls to
completion itself (see _run_async), so it works from a script, the REPL,
the GUI, or a Jupyter notebook alike.

This module still imports without the tastytrade package installed; the
builtins then raise a clear error when called.
"""

import asyncio
import concurrent.futures
import datetime
import os
import re
import urllib.parse

from lisp_core import (
    LispDate, LispError, LispHashTable, LispString, LispVector, NIL, Pair,
    list_to_pairs, pairs_to_list,
)
from lisp_data_common import read_credentials
from lisp_http import json_to_lisp
from lisp_tables import column_vector, make_table_value, table_from_rows, table_from_tuples
from lisp_time_series import months_later


try:
    from tastytrade import Session as _TTSession
    _TASTYTRADE_AVAILABLE = True
except ImportError:
    _TASTYTRADE_AVAILABLE = False

TASTY_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
TASTY_CODE_TO_MONTH = {v: k for k, v in TASTY_MONTH_CODES.items()}

# Supported products: code -> tastytrade root symbol. Kept in sync with
# tasty_api/tastytrade_source.py's PRODUCTS dict.
TASTY_PRODUCTS = {
"ES":"/ES",
"MES":"/MES",
"NQ":"/NQ",
"MNQ":"/MNQ",
"YM":"/YM",
"MYM":"/MYM",
"RTY":"/RTY",
"M2K":"/M2K",
"ZT":"/ZT",
"ZF":"/ZF",
"ZN":"/ZN",
"ZB":"/ZB",
"SR3":"/SR3",
"2YY":"/2YY",
"5YY":"/5YY",
"10Y":"/10Y",
"30Y":"/30Y",
"TN":"/TN",
"UB":"/UB",
"6E":"/6E",
"M6E":"/M6E",
"6J":"/6J",
"6B":"/6B",
"M6B":"/M6B",
"6C":"/6C",
"MCD":"/MCD",
"6A":"/6A",
"M6A":"/M6A",
"6M":"/6M",
"6S":"/6S",
"CL":"/CL",
"MCL":"/MCL",
"QM":"/QM",
"NG":"/NG",
"MNG":"/MNG",
"QG":"/QG",
"RB":"/RB",
"HO":"/HO",
"BZ":"/BZ",
"GC":"/GC",
"MGC":"/MGC",
"1OZ":"/1OZ",
"HG":"/HG",
"MHG":"/MHG",
"SI":"/SI",
"SIL":"/SIL",
"SIC":"/SIC",
"PL":"/PL",
"PA":"/PA",
"ZC":"/ZC",
"XC":"/XC",
"ZS":"/ZS",
"XK":"/XK",
"ZW":"/ZW",
"XW":"/XW",
"BTC":"/BTC",
"MBT":"/MBT",
"ETH":"/ETH",
"MET":"/MET",
"MXP":"/MXP",
"LE":"/LE",
"HE":"/HE",
"VX":"/VX",
"VXM":"/VXM"
}


# ---------------------------------------------------------------------------
# Logging in, and running the package's async calls
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an asyncio coroutine to completion and return its result, whether
    or not this thread already has a running event loop. Normally that's
    just asyncio.run(coro). But a Jupyter kernel keeps a loop running, and
    asyncio.run() refuses to run inside one, so in that case the coroutine
    runs on a separate thread with its own loop while this one waits.
    term_structure/sofr_market_data.py has the same helper."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _tasty_load_credentials(path):
    """The credentials file's entries, with its client secret and refresh
    token checked for."""
    creds = read_credentials(path, "tastytrade")
    for key in ("client_secret", "refresh_token"):
        if isinstance(creds.get(key), str):
            creds[key] = creds[key].strip()
    missing = [k for k in ("client_secret", "refresh_token") if not creds.get(k)]
    if missing:
        raise LispError("tastytrade: credentials file is missing: %s" % ", ".join(missing))
    return creds


# Logging in -- trading the credentials' refresh token for an access token --
# takes a round trip to tastytrade, and the access token is good for 15
# minutes. So the last session for each credentials file is kept, as the
# text Session.serialize makes, and the next call starts from it; the
# session logs in again by itself once the token runs out. The key is the
# file's path and modification time, so changed credentials are used at once.
_saved_sessions = {}


def _session_key(credentials_path):
    path = os.path.abspath(str(credentials_path))
    if not os.path.exists(path):
        raise LispError("tastytrade: credentials file not found: %s" % path)
    return path, os.path.getmtime(path)


def _tasty_session(credentials_path):
    """A tastytrade Session for the credentials file."""
    if not _TASTYTRADE_AVAILABLE:
        raise LispError(
            "tastytrade: the 'tastytrade' package is not installed (pip install tastytrade)")
    saved = _saved_sessions.get(_session_key(credentials_path))
    if saved is not None:
        return _TTSession.deserialize(saved)
    creds = _tasty_load_credentials(credentials_path)
    return _TTSession(
        creds["client_secret"], creds["refresh_token"],
        is_test=bool(creds.get("is_test", False)))


def _with_session(credentials_path, work):
    """Run work(session) -- an async function making requests -- to
    completion with a session for the credentials, and return its result."""
    async def run():
        session = _tasty_session(credentials_path)
        async with session:                 # closes its connections when done
            result = await work(session)
        _saved_sessions[_session_key(credentials_path)] = session.serialize()
        return result
    return _run_async(run())


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

# tastytrade sends every decimal number as text, with a decimal point:
# "765.53", "10.0". Text like that is made a number; text without a decimal
# point -- an ID, a CUSIP, a zip code -- stays text.
_DECIMAL_TEXT = re.compile(r"-?\d+\.\d+")


def _with_numbers(value):
    """Parsed JSON with its decimal-number text made numbers."""
    if isinstance(value, dict):
        return {k: _with_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_with_numbers(v) for v in value]
    if isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value):
        return float(value)
    return value


def _request_path(path, who):
    """A request's path: a string such as "/market-metrics", or a list of its
    parts, such as ("option-chains" "BRK/B"), each of which is encoded so that
    a / or a space in a symbol can't be mistaken for part of the path."""
    if isinstance(path, Pair):
        return "/" + "/".join(urllib.parse.quote(str(part), safe="") for part in pairs_to_list(path))
    if isinstance(path, str):
        return "/" + str(path).lstrip("/")
    raise LispError("%s: the path must be a string or a list of its parts, not %r" % (who, path))


def _parameter_text(value):
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, LispDate):
        return value.date.isoformat()
    return str(value)


def _request_parameters(parameters, who):
    """The request's parameters, from a list of (name . value) pairs or a hash
    table, as a dict for the request. A value that's a list is sent once for
    each of its items: ("symbol[]" "AAPL" "MSFT") asks about both."""
    if parameters is NIL or parameters is None:
        return {}
    if isinstance(parameters, LispHashTable):
        pairs = list(parameters.table.items())
    else:
        pairs = []
        for entry in pairs_to_list(parameters):
            if not isinstance(entry, Pair):
                raise LispError("%s: parameters must be (name . value) pairs, not %r" % (who, entry))
            pairs.append((entry.car, entry.cdr))
    result = {}
    for name, value in pairs:
        if isinstance(value, Pair):
            result[str(name)] = [_parameter_text(v) for v in pairs_to_list(value)]
        else:
            result[str(name)] = _parameter_text(value)
    return result


def _error_message(response):
    """What tastytrade says went wrong with a request."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        if response.status_code == 404:
            return "HTTP 404: there's no such request -- check the path"
        return "HTTP %d" % response.status_code
    messages = [e.get("message") or e.get("reason") or str(e) for e in (error.get("errors") or [error])]
    return "HTTP %d: %s" % (response.status_code, "; ".join(m for m in messages if m))


async def _api_get(session, path, params=None, who="tastytrade-get"):
    """GET path; the "data" in the JSON answer, with decimal-number text
    made numbers. An answer that comes in pages is put together from all of
    them, unless params asks for one page ("page-offset")."""
    params = dict(params or {})
    all_pages = "page-offset" not in params
    items = []
    await session.refresh()                 # logs in again if the token has run out
    while True:
        response = await session._client.get(path, params=params)
        if response.status_code // 100 != 2:
            raise LispError("%s: %s (asking for %s)" % (who, _error_message(response), path))
        answer = response.json()
        data = answer.get("data")
        pagination = answer.get("pagination")
        if not all_pages or not pagination or not isinstance(data, dict) or "items" not in data:
            return _with_numbers(data)
        items.extend(data["items"])
        if pagination["page-offset"] >= pagination["total-pages"] - 1:
            data["items"] = items
            return _with_numbers(data)
        params["page-offset"] = pagination["page-offset"] + 1


def tastytrade_get_fn(credentials_path, path, parameters=NIL):
    """(tastytrade-get credentials-path path [parameters]) -- the answer to
    any of tastytrade's GET requests, as Lisp data: a JSON object becomes a
    hash table with string keys, an array a list, and decimal numbers (which
    tastytrade sends as text) numbers. `path` is a string such as
    "/market-metrics" or a list of parts such as (list "option-chains"
    "BRK/B"); `parameters` is a list of (name . value) pairs or a hash
    table. Only reads: it can't place an order."""
    request_path = _request_path(path, "tastytrade-get")
    params = _request_parameters(parameters, "tastytrade-get")
    return json_to_lisp(_with_session(credentials_path,
                                      lambda session: _api_get(session, request_path, params)))


def tastytrade_get_table_fn(credentials_path, path, parameters=NIL):
    """(tastytrade-get-table credentials-path path [parameters]) -- the
    same request as tastytrade-get, with what it returns as a table: one row
    for each of the answer's items, or one row if it's a single object (see
    table-from-rows for how a JSON object becomes a row)."""
    data = tastytrade_get_fn(credentials_path, path, parameters)
    if isinstance(data, LispHashTable) and LispString("items") in data.table:
        return table_from_rows(data.table[LispString("items")])
    if isinstance(data, LispHashTable):
        return table_from_rows(list_to_pairs([data]))
    raise LispError("tastytrade-get-table: the answer isn't a JSON object, so it can't be made a table")


# ---------------------------------------------------------------------------
# Quotes: tastytrade's market data for any symbols
# ---------------------------------------------------------------------------

# An equity option's symbol, as OCC writes it: the root (padded with spaces
# to six characters), the expiration as YYMMDD, C or P, and the strike times
# 1000 in eight digits -- "SPY   261218C00700000".
_OCC_OPTION = re.compile(r"[A-Z0-9./]{1,6} *\d{6}[CP]\d{8}")


def _instrument_type(symbol):
    """The kind of instrument a symbol names, as the market-data request
    calls it:
      ./CLX6 LO1X6 261117P60   future-option   (starts with ./)
      /CLZ6                    future          (starts with /)
      SPY   261218C00700000    equity-option   (OCC's form, above)
      BTC/USD                  cryptocurrency  (ends with /USD)
      anything else            equity -- which an index such as SPX can be
                               asked for as, too"""
    if symbol.startswith("./"):
        return "future-option"
    if symbol.startswith("/"):
        return "future"
    if _OCC_OPTION.fullmatch(symbol):
        return "equity-option"
    if symbol.endswith("/USD"):
        return "cryptocurrency"
    return "equity"


async def _market_data(session, symbols, who):
    """tastytrade's market data for the symbols: a dict from symbol to what
    it says about it (a dict). tastytrade takes 100 symbols per request. A
    symbol it doesn't know is left out."""
    found = {}
    for start in range(0, len(symbols), 100):
        params = {}
        for symbol in symbols[start:start + 100]:
            params.setdefault(_instrument_type(symbol), []).append(symbol)
        data = await _api_get(session, "/market-data/by-type", params, who)
        for item in data.get("items", []):
            found[item["symbol"]] = item
    return found


# The quote table's columns, and the market data field each comes from.
QUOTE_COLUMNS = [
    ("symbol", "symbol"), ("instrument-type", "instrument-type"),
    ("bid", "bid"), ("ask", "ask"), ("mid", "mid"), ("mark", "mark"), ("last", "last"),
    ("bid-size", "bid-size"), ("ask-size", "ask-size"), ("volume", "volume"),
    ("open-interest", "open-interest"), ("implied-volatility", "volatility"),
    ("delta", "delta"), ("gamma", "gamma"), ("theta", "theta"), ("vega", "vega"),
    ("prev-close", "prev-close"), ("updated-at", "updated-at"),
]


def _symbol_list(symbols, who):
    """A symbol, or a list or vector of them, as a list of strings."""
    if isinstance(symbols, str):
        return [str(symbols)]
    if isinstance(symbols, LispVector):
        return [str(s) for s in symbols.items.tolist()]
    if isinstance(symbols, Pair):
        return [str(s) for s in pairs_to_list(symbols)]
    raise LispError("%s: expected a symbol or a list of symbols, not %r" % (who, symbols))


def tastytrade_quotes_fn(credentials_path, symbols):
    """(tastytrade-quotes credentials-path symbols) -- tastytrade's current
    market data for each of the symbols (one, or a list): a table with a row
    per symbol, in the order given, and the columns in QUOTE_COLUMNS. Any
    mix of stocks, ETFs, indexes, equity options, futures, futures options,
    and cryptocurrencies (see _instrument_type for how they're told apart).
    Implied volatility and the Greeks are there for options only; a value
    tastytrade doesn't give, or a symbol it doesn't know, is NaN (or '())."""
    symbol_list = _symbol_list(symbols, "tastytrade-quotes")
    found = _with_session(credentials_path,
                          lambda session: _market_data(session, symbol_list, "tastytrade-quotes"))
    rows = [found.get(symbol, {"symbol": symbol}) for symbol in symbol_list]
    return make_table_value([(column, column_vector([_lisp_value(row.get(field)) for row in rows]))
                             for column, field in QUOTE_COLUMNS])


def _lisp_value(value):
    """A value from tastytrade's answer (with numbers already made numbers)
    as a table holds it."""
    if value is None:
        return None
    if isinstance(value, str):
        return LispString(value)
    if value is True or value is False:
        return int(value)
    return value


def _current_price(item):
    """The best guess at a symbol's price now, from its market data: the
    middle of the bid and ask, else the mark, the last trade, or the close."""
    if item is None:
        return None
    for field in ("mid", "mark", "last", "close"):
        value = item.get(field)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _settlement_price(item):
    """A futures contract's price for the curve: the settlement (close) if
    there is one, else the last trade, the mark, or the middle of the bid
    and ask."""
    if item is None:
        return None
    for field in ("close", "last", "mark", "mid"):
        value = item.get(field)
        if isinstance(value, (int, float)):
            return float(value)
    return None


# ---------------------------------------------------------------------------
# Futures curves
# ---------------------------------------------------------------------------

def _tasty_root(product, name):
    root = TASTY_PRODUCTS.get(str(product).upper())
    if root is None:
        raise LispError(
            "%s: unknown product %r (supported: %s)"
            % (name, str(product), ", ".join(TASTY_PRODUCTS)))
    return root


def _tasty_parse_delivery_month(underlying_symbol, reference_date=None):
    """The delivery month (as a first-of-month date) of a CME futures symbol
    such as '/CLZ6', or None if it can't be parsed. See parse_delivery_month
    in tasty_api/tastytrade_source.py for how the one-digit year is read."""
    if not underlying_symbol:
        return None
    sym = underlying_symbol.lstrip("/")
    if len(sym) < 3:
        return None
    year_digits = ""
    i = len(sym) - 1
    while i >= 0 and sym[i].isdigit():
        year_digits = sym[i] + year_digits
        i -= 1
    if not year_digits or i < 0:
        return None
    month_code = sym[i]
    if month_code not in TASTY_CODE_TO_MONTH:
        return None
    month = TASTY_CODE_TO_MONTH[month_code]

    reference_date = reference_date or datetime.date.today()
    if len(year_digits) >= 2:
        year = 2000 + int(year_digits[-2:])
    else:
        last_digit = int(year_digits)
        base_decade = (reference_date.year // 10) * 10
        year = base_decade + last_digit
        if year < reference_date.year - 2:
            year += 10
    try:
        return datetime.date(year, month, 1)
    except ValueError:
        return None


def _futures_curve(credentials_path, product, n_months, who):
    """The upcoming contracts of a futures product with a price: a list of
    (delivery month, symbol without the /, days to delivery, price)."""
    root = _tasty_root(product, who)
    today = datetime.date.today()
    symbols, months = [], []
    for i in range(int(n_months)):
        total = (today.month - 1) + i
        month = total % 12 + 1
        year = today.year + total // 12
        # tastytrade's symbol has a one-digit year: "/CLZ6" for Dec 2026.
        symbols.append("%s%s%d" % (root, TASTY_MONTH_CODES[month], year % 10))
        months.append(datetime.date(year, month, 1))
    found = _with_session(credentials_path, lambda session: _market_data(session, symbols, who))
    rows = []
    for symbol, delivery in zip(symbols, months):
        price = _settlement_price(found.get(symbol))
        if price is not None:
            rows.append((delivery, symbol.lstrip("/"), (delivery - today).days, price))
    return rows


def tastytrade_futures_curve_fn(credentials_path, product, n_months=18):
    """(tastytrade-futures-curve credentials-path product [n-months]) ->
    (cons delivery-dates-vector prices-vector), one entry for each upcoming
    contract month that has a price -- the settlement, else the last trade.
    `product` is a code from (tastytrade-products), e.g. "CL". For the
    contract symbols and days to delivery too, use
    tastytrade-futures-curve-rows; for bids and asks, tastytrade-quotes."""
    rows = _futures_curve(credentials_path, product, n_months, "tastytrade-futures-curve")
    dates = [LispDate(d.year, d.month, d.day) for d, _sym, _dte, _price in rows]
    prices = [price for _d, _sym, _dte, price in rows]
    return Pair(LispVector(dates), LispVector(prices))


def tastytrade_futures_curve_rows_fn(credentials_path, product, n_months=18):
    """(tastytrade-futures-curve-rows credentials-path product [n-months]) ->
    a list of rows (delivery-month futures-symbol days-to-delivery price),
    one per upcoming contract month with a price. This is the input for
    futures-curve-fit and futures-leg-carry, which don't use the network --
    so fetch once, then analyze as often as you like."""
    rows = _futures_curve(credentials_path, product, n_months, "tastytrade-futures-curve-rows")
    return list_to_pairs([
        list_to_pairs([
            LispDate(d.year, d.month, d.day),
            LispString(sym),
            int(dte),
            float(price),
        ])
        for d, sym, dte, price in rows
    ])


# ---------------------------------------------------------------------------
# Analyses of a fetched futures curve (no network)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Option chains
# ---------------------------------------------------------------------------

def _tasty_resolve_symbol(symbol):
    """Classify a symbol for tastytrade-option-chain, returning
    (kind, resolved) with kind "future" or "equity":
      "/CL" (starts with /)           -> ("future", "/CL"), for any futures root
      "CL" (a TASTY_PRODUCTS code)    -> ("future", "/CL")
      anything else, e.g. "AAPL"      -> ("equity", "AAPL")"""
    s = str(symbol).strip()
    if s.startswith("/"):
        return ("future", s)
    upper = s.upper()
    root = TASTY_PRODUCTS.get(upper)
    if root is not None:
        return ("future", root)
    return ("equity", upper)


def _expiration(option):
    return datetime.date.fromisoformat(option["expiration-date"])


def _options_within(kind, options, n_months, today):
    """The options to consider: for futures, those on the next n_months
    delivery months; for equities, those expiring in the next n_months."""
    if kind == "equity":
        cutoff = months_later(today, n_months)
        return [o for o in options if today <= _expiration(o) <= cutoff]
    by_delivery_month = {}
    for option in options:
        delivery = _tasty_parse_delivery_month(option.get("underlying-symbol", ""), today) \
            or _expiration(option).replace(day=1)
        by_delivery_month.setdefault(delivery, []).append(option)
    months = sorted(m for m in by_delivery_month if m >= today.replace(day=1))[:n_months]
    return [o for m in months for o in by_delivery_month[m]]


def _nearest_strikes(options, underlying_price, max_strikes):
    """Of one expiration's options, the max_strikes strikes nearest the
    underlying's price -- calls and puts both, so up to 2 * max_strikes
    options."""
    if underlying_price is not None:
        options = sorted(options, key=lambda o: abs(float(o["strike-price"]) - underlying_price))
    return options[:2 * max_strikes]


async def _option_chain(session, symbol, n_months, max_strikes):
    """The option chain's rows, as option_chain_table takes them."""
    kind, resolved = _tasty_resolve_symbol(symbol)
    if kind == "future":
        path = "/futures-option-chains/" + urllib.parse.quote(resolved.lstrip("/"), safe="")
    else:
        path = "/option-chains/" + urllib.parse.quote(resolved, safe="")
    options = (await _api_get(session, path, None, "tastytrade-option-chain"))["items"]
    today = datetime.date.today()
    options = _options_within(kind, options, n_months, today)

    # The underlyings' prices (for a futures option, its future's), and the
    # strikes nearest them, for each underlying and expiration.
    underlyings = sorted({o["underlying-symbol"] for o in options})
    underlying_data = await _market_data(session, underlyings, "tastytrade-option-chain")
    by_expiration = {}
    for option in options:
        by_expiration.setdefault((option["underlying-symbol"], option["expiration-date"]), []).append(option)
    kept = []
    for (underlying, _expiration_date), group in by_expiration.items():
        kept.extend(_nearest_strikes(group, _current_price(underlying_data.get(underlying)), max_strikes))
    kept.sort(key=lambda o: (o["expiration-date"], o["underlying-symbol"], float(o["strike-price"]), o["option-type"]))

    option_data = await _market_data(session, [o["symbol"] for o in kept], "tastytrade-option-chain")
    return [_option_row(option, kind, option_data.get(option["symbol"], {}),
                        _current_price(underlying_data.get(option["underlying-symbol"])), today)
            for option in kept]


def _option_row(option, kind, data, underlying_price, today):
    """One option's row: its values in OPTION_CHAIN_COLUMNS order."""
    underlying = option["underlying-symbol"]
    delivery = _tasty_parse_delivery_month(underlying, today) if kind == "future" else None
    return [
        _lisp_value(option["symbol"]),
        LispString("Call" if option["option-type"] == "C" else "Put"),
        float(option["strike-price"]),
        _lisp_value(option["expiration-date"]),
        option.get("days-to-expiration"),
        LispDate(delivery.year, delivery.month, delivery.day) if delivery else None,
        LispString(underlying.lstrip("/")),
        underlying_price,
        _lisp_value(data.get("bid")),
        _lisp_value(data.get("ask")),
        _lisp_value(data.get("mid")),
        _lisp_value(data.get("last")),
        _lisp_value(data.get("volatility")),
        _lisp_value(data.get("delta")),
        _lisp_value(data.get("vega")),
        _lisp_value(data.get("volume")),
        _lisp_value(data.get("open-interest")),
    ]


def tastytrade_option_chain_fn(credentials_path, symbol, n_months=12, max_strikes_per_expiration=15):
    """(tastytrade-option-chain credentials-path symbol [n-months
    max-strikes-per-expiration]) -> a table (see lisp_tables.py), one row
    per option, with the columns in OPTION_CHAIN_COLUMNS: symbol, type
    ("Call" or "Put"), strike, expiration-date, days-to-expiration,
    delivery-month, underlying, underlying-price, bid, ask, mid, last-price,
    implied-volatility, delta, vega, volume, and open-interest.

    `symbol` is a futures root such as "/CL", a short code from
    (tastytrade-products) such as "CL", or anything else, e.g. "AAPL", for an
    equity option chain. For futures, n-months is how many delivery months to
    include; for equities, how many months ahead to look for expirations
    (delivery-month is then '()). Each expiration keeps only the
    max-strikes-per-expiration strikes nearest the underlying's price.
    Values tastytrade doesn't report are missing: NaN in a column of
    numbers, '() otherwise."""
    rows = _with_session(credentials_path, lambda session: _option_chain(
        session, symbol, int(n_months), int(max_strikes_per_expiration)))
    return option_chain_table(rows)


# The columns of the table tastytrade-option-chain returns, in the order
# _option_row gives them.
OPTION_CHAIN_COLUMNS = [
    "symbol", "type", "strike", "expiration-date", "days-to-expiration", "delivery-month",
    "underlying", "underlying-price", "bid", "ask", "mid", "last-price", "implied-volatility",
    "delta", "vega", "volume", "open-interest",
]


def option_chain_table(rows):
    """The option chain's rows (as _option_row makes them) as a table, one
    column per field. A value tastytrade didn't report is '() in the row,
    which is NaN in a column of numbers."""
    return table_from_tuples(rows, OPTION_CHAIN_COLUMNS)


# ---------------------------------------------------------------------------
# The rest
# ---------------------------------------------------------------------------

def tastytrade_test_connection_fn(credentials_path):
    """(tastytrade-test-connection credentials-path) -> a status string,
    naming the login's accounts. Raises a LispError if logging in fails."""
    data = _with_session(credentials_path, lambda session: _api_get(
        session, "/customers/me/accounts", None, "tastytrade-test-connection"))
    numbers = [item["account"]["account-number"] for item in data.get("items", [])]
    if not numbers:
        return LispString("Connected, but no accounts were found on this login.")
    return LispString("Connected successfully. Account(s): %s." % ", ".join(numbers))


def tastytrade_products_fn():
    """(tastytrade-products) -> a Lisp list of supported product code strings."""
    return list_to_pairs([LispString(code) for code in TASTY_PRODUCTS])


BUILTINS = {
    "tastytrade-get": tastytrade_get_fn,
    "tastytrade-get-table": tastytrade_get_table_fn,
    "tastytrade-quotes": tastytrade_quotes_fn,
    "tastytrade-test-connection": tastytrade_test_connection_fn,
    "tastytrade-futures-curve": tastytrade_futures_curve_fn,
    "tastytrade-futures-curve-rows": tastytrade_futures_curve_rows_fn,
    "tastytrade-option-chain": tastytrade_option_chain_fn,
    "tastytrade-products": tastytrade_products_fn,
}
