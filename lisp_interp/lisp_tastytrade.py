"""tastytrade (real broker data) for the Lisp interpreter: futures curves,
option chains for futures or equities, and two pure analyses of a fetched
futures curve (tastytrade-curve-fit, tastytrade-leg-carry).

Uses the community `tastytrade` Python package (pip install tastytrade),
a tastytrade account, and a credentials JSON file -- see
tasty_api/README.md for the one-time OAuth setup. Modeled on
tasty_api/tastytrade_source.py, minus the PyQt6 threading: each builtin
here is a plain synchronous function that runs the SDK's async calls to
completion itself (see _run_async), so it works from a script, the REPL,
the GUI, or a Jupyter notebook alike.

This module still imports without the tastytrade package installed; the
builtins then raise a clear error when called.
"""

import asyncio
import calendar
import concurrent.futures
import datetime
import inspect
import json
import os

from lisp_core import (
    LispDate, LispError, LispString, LispVector, NIL, Pair,
    is_true, list_to_pairs, pairs_to_list,
)


try:
    from tastytrade import Session as _TTSession
    from tastytrade.instruments import get_future_option_chain as _tt_get_future_option_chain
    from tastytrade.instruments import get_option_chain as _tt_get_option_chain
    from tastytrade.market_data import get_market_data_by_type as _tt_get_market_data_by_type
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


async def _tasty_maybe_await(value):
    """Compatibility shim: the `tastytrade` SDK went async-only in v12.0.0,
    so older installed versions return plain results directly instead of a
    coroutine. See the identically-named helper in tasty_api/tastytrade_source.py."""
    if inspect.isawaitable(value):
        return await value
    return value


def _run_async(coro):
    """Run an asyncio coroutine to completion and return its result --
    works whether or not the calling thread already has its OWN running
    event loop. With no loop already running (a plain script, the
    console REPL, the GUI), this is exactly asyncio.run(coro). With one
    already running -- e.g. inside a Jupyter/IPython kernel, which runs
    one continuously; found by hitting it directly, calling any
    tastytrade-*/sofr-calibration-data builtin from a notebook cell blew
    up with "asyncio.run() cannot be called from a running event loop"
    -- asyncio.run() would raise exactly that, so this runs the
    coroutine to completion on a SEPARATE thread with its own fresh
    event loop instead, and blocks the calling thread until it's done.
    Either way, every caller of every _tasty_*_async coroutine in this
    file just gets a plain return value back, synchronously -- no
    awaiting, no nest_asyncio monkeypatching needed, no visible
    difference depending on which context it's called from. See the
    identical helper in term_structure/sofr_market_data.py, needed for
    the same reason for fetch_sofr_calibration_data()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _tasty_root(product, name):
    root = TASTY_PRODUCTS.get(str(product).upper())
    if root is None:
        raise LispError(
            "%s: unknown product %r (supported: %s)"
            % (name, str(product), ", ".join(TASTY_PRODUCTS)))
    return root


def _tasty_resolve_symbol(symbol):
    """Classifies a symbol for tastytrade-option-chain and returns
    (kind, resolved) where kind is "future" or "equity":

      - Already starts with "/" (tastytrade's own convention for
        futures) -> ("future", symbol as given). Works for ANY futures
        root, not just ones in TASTY_PRODUCTS -- no translation needed,
        per tastytrade's own convention.
      - A known short code from TASTY_PRODUCTS (e.g. "CL") -> ("future",
        "/CL"), for backward compatibility with existing scripts that
        pass the short code.
      - Anything else (e.g. "AAPL", "SPY") -> ("equity", symbol
        upper-cased), fetched via the equity option-chain endpoint.
    """
    s = str(symbol).strip()
    if s.startswith("/"):
        return ("future", s)
    upper = s.upper()
    root = TASTY_PRODUCTS.get(upper)
    if root is not None:
        return ("future", root)
    return ("equity", upper)


def _tasty_load_credentials(path):
    path = str(path)
    if not os.path.exists(path):
        raise LispError("tastytrade: credentials file not found: %s" % path)
    try:
        with open(path) as f:
            creds = json.load(f)
    except json.JSONDecodeError as e:
        raise LispError("tastytrade: credentials file isn't valid JSON: %s" % e)
    for key in ("client_secret", "refresh_token"):
        if isinstance(creds.get(key), str):
            creds[key] = creds[key].strip()
    missing = [k for k in ("client_secret", "refresh_token") if not creds.get(k)]
    if missing:
        raise LispError("tastytrade: credentials file is missing: %s" % ", ".join(missing))
    return creds


def _tasty_session(credentials_path):
    if not _TASTYTRADE_AVAILABLE:
        raise LispError(
            "tastytrade: the 'tastytrade' package is not installed (pip install tastytrade)")
    creds = _tasty_load_credentials(credentials_path)
    return _TTSession(
        creds["client_secret"], creds["refresh_token"],
        is_test=bool(creds.get("is_test", False)))


def _tasty_pick_price(md):
    """Prefer settled/close price; fall back to last trade, then mark/mid."""
    for attr in ("close", "last", "mark", "mid"):
        val = getattr(md, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _tasty_option_type_label(option_type):
    val = getattr(option_type, "value", option_type)
    return "Call" if str(val).upper().startswith("C") else "Put"


def _tasty_days_to_expiration(opt, exp_date, today):
    """Prefers the SDK's own days_to_expiration field; falls back to
    computing it from the expiration date if that's not populated."""
    dte = getattr(opt, "days_to_expiration", None)
    if dte is not None:
        try:
            return int(dte)
        except (TypeError, ValueError):
            pass
    if hasattr(exp_date, "toordinal") and hasattr(today, "toordinal"):
        return (exp_date - today).days
    return None


def _tasty_parse_delivery_month(underlying_symbol, reference_date=None):
    """Parse a CME futures trading symbol (single-digit year, e.g.
    '/CLZ6') into its delivery month (first-of-month date). Returns None
    if unparseable. See tasty_api/tastytrade_source.py's
    parse_delivery_month for the full rationale."""
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


async def _tasty_test_connection_async(credentials_path):
    session = _tasty_session(credentials_path)
    from tastytrade import Account
    raw = Account.get(session)
    accounts = await _tasty_maybe_await(raw)
    if not accounts:
        return "Connected, but no accounts were found on this login."
    numbers = ", ".join(getattr(a, "account_number", str(a)) for a in accounts)
    return "Connected successfully. Account(s): %s." % numbers


def tastytrade_test_connection_fn(credentials_path):
    """(tastytrade-test-connection credentials-path) -> a status string.
    Raises a LispError on any authentication/connection failure."""
    return LispString(_run_async(_tasty_test_connection_async(credentials_path)))


async def _tasty_futures_curve_async(credentials_path, product, n_months):
    session = _tasty_session(credentials_path)
    root = _tasty_root(product, "tastytrade-futures-curve")

    today = datetime.date.today()
    y, m = today.year, today.month
    candidate_symbols, candidate_months = [], []
    for i in range(int(n_months)):
        total = (m - 1) + i
        mm = total % 12 + 1
        yyyy = y + total // 12
        code = TASTY_MONTH_CODES[mm]
        # tastytrade's plain trading symbol uses a single-digit year
        # (e.g. "/CLZ6" for Dec 2026), unlike the streamer symbol.
        candidate_symbols.append("%s%s%d" % (root, code, yyyy % 10))
        candidate_months.append(datetime.date(yyyy, mm, 1))

    market_data = await _tasty_maybe_await(
        _tt_get_market_data_by_type(session, futures=candidate_symbols))
    price_by_symbol = {md.symbol: _tasty_pick_price(md) for md in market_data}

    rows = []  # (delivery_date, symbol_without_slash, days_to_delivery, price)
    for sym, delivery in zip(candidate_symbols, candidate_months):
        price = price_by_symbol.get(sym)
        if price is None:
            continue
        rows.append((delivery, sym.lstrip("/"), (delivery - today).days, price))
    return rows


def tastytrade_futures_curve_fn(credentials_path, product, n_months=18):
    """(tastytrade-futures-curve credentials-path product [n-months]) ->
    (cons delivery-dates-vector last-prices-vector), one entry per upcoming
    contract month that actually has a price (guessed contract months that
    don't exist for this product -- e.g. non-quarterly months for ES/NQ/ZN
    -- are silently skipped). `product` is one of "CL", "MCL", "ES", "NQ",
    "SR3", "ZN", "ZQ". Feed the result straight into plot-xy,
    linear-regression, spline-regression, etc.
    See also tastytrade-futures-curve-rows, which additionally includes
    each contract's symbol and days-to-delivery -- needed by
    tastytrade-curve-fit and tastytrade-leg-carry."""
    rows = _run_async(_tasty_futures_curve_async(credentials_path, product, int(n_months)))
    dates = [LispDate(d.year, d.month, d.day) for d, _sym, _dte, _price in rows]
    prices = [price for _d, _sym, _dte, price in rows]
    return Pair(LispVector(dates), LispVector(prices))


def tastytrade_futures_curve_rows_fn(credentials_path, product, n_months=18):
    """(tastytrade-futures-curve-rows credentials-path product [n-months])
    -> a Lisp list of rows, each row a 4-element list:
       (delivery-month futures-symbol days-to-delivery last-price)
    one per upcoming contract month that actually has a price (same
    coverage as tastytrade-futures-curve, just with the extra fields
    tastytrade-curve-fit and tastytrade-leg-carry need). Fetch once with
    this, then call either analysis function as many times as you like
    with different rate/threshold assumptions, with no re-fetch needed --
    they're pure functions over the row data, no networking."""
    rows = _run_async(_tasty_futures_curve_async(credentials_path, product, int(n_months)))
    return list_to_pairs([
        list_to_pairs([
            LispDate(d.year, d.month, d.day),
            LispString(sym),
            int(dte),
            float(price),
        ])
        for d, sym, dte, price in rows
    ])


def tasty_row_field(row, index):
    """row is a Python list already extracted via pairs_to_list(); pulls
    field `index` and unwraps a LispDate to a plain datetime.date where
    relevant, otherwise returns the raw value."""
    val = row[index]
    return val.date if isinstance(val, LispDate) else val


def tastytrade_curve_fit_fn(curve_rows, rich_cheap_threshold_pct=0.75, poly_degree=None):
    """(tastytrade-curve-fit curve-rows [rich-cheap-threshold-pct poly-degree])
    -> a Lisp list of rows, each row a 7-element list:
       (delivery-month futures-symbol days-to-delivery last-price
        fitted-price rich-cheap-pct signal)
    `curve-rows` is the output of tastytrade-futures-curve-rows (or
    anything shaped the same way). Fits ln(price) vs. days-to-delivery
    with a low-order polynomial (degree = min(3, n-1) unless
    `poly-degree` is given) across ALL rows, and flags each contract's
    deviation from that fitted curve: `signal` is "Rich" if the contract
    trades more than `rich-cheap-threshold-pct` above the fit, "Cheap" if
    that far below, else "Fair". This is a pure function -- no
    networking -- so it's cheap to re-run with different assumptions.
    Needs at least 3 rows; returns '() if there aren't enough."""
    import numpy as np

    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if len(rows) < 3:
        return NIL

    rows = sorted(rows, key=lambda r: tasty_row_field(r, 2))
    x = np.array([float(tasty_row_field(r, 2)) for r in rows], dtype=float)
    y = np.log(np.array([float(tasty_row_field(r, 3)) for r in rows], dtype=float))

    n = len(rows)
    degree = int(poly_degree) if poly_degree is not None and is_true(poly_degree) else min(3, max(1, n - 1))
    degree = max(1, min(degree, n - 1))

    coeffs = np.polyfit(x, y, degree)
    fitted_price = np.exp(np.polyval(coeffs, x))
    threshold = float(rich_cheap_threshold_pct)

    out_rows = []
    for r, fitted in zip(rows, fitted_price):
        last_price = float(tasty_row_field(r, 3))
        pct = (last_price - fitted) / fitted * 100
        if pct > threshold:
            signal = "Rich"
        elif pct < -threshold:
            signal = "Cheap"
        else:
            signal = "Fair"
        out_rows.append(list_to_pairs([
            r[0], r[1], r[2], r[3],
            float(fitted), float(pct), LispString(signal),
        ]))
    return list_to_pairs(out_rows)


def tastytrade_leg_carry_fn(curve_rows, funding_rate_pct, storage_cost_pct,
                             leg_signal_threshold_pct=1.0):
    """(tastytrade-leg-carry curve-rows funding-rate-pct storage-cost-pct
         [leg-signal-threshold-pct])
    -> a Lisp list of rows, each row a 9-element list:
       (near-month far-month near-price far-price days-between
        implied-carry-rate-pct implied-net-storage-cost-pct
        implied-convenience-yield-pct signal)
    Pairwise (adjacent contract month) implied cost-of-carry decomposition:
    for each pair, c = ln(far-price/near-price)/(days-between/365) is the
    OBSERVED implied annualized carry rate; given your `funding-rate-pct`
    (r) and `storage-cost-pct` (u) assumptions, net storage cost = c - r
    and convenience yield = r + u - c. `signal` flags a leg whose carry
    rate deviates from the MEDIAN carry rate across all legs by more than
    `leg-signal-threshold-pct` (percentage points), in either direction.
    `storage-cost-pct`/convenience-yield are only literally meaningful for
    a storable physical commodity (e.g. CL) -- for financial futures
    (ES, NQ, ZN, SR3...) there's no real storage, so read those two
    fields as an illustrative decomposition of implied carry, not an
    actual estimate; the carry rate itself is still meaningful either
    way. `curve-rows` is the output of tastytrade-futures-curve-rows.
    Pure function -- no networking. Needs at least 2 rows; returns '()
    if there aren't enough, or if no adjacent pair has positive spacing."""
    import numpy as np

    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if len(rows) < 2:
        return NIL

    rows = sorted(rows, key=lambda r: tasty_row_field(r, 2))
    r = float(funding_rate_pct) / 100.0
    u = float(storage_cost_pct) / 100.0

    legs = []
    carries = []
    for i in range(len(rows) - 1):
        near, far = rows[i], rows[i + 1]
        near_days = float(tasty_row_field(near, 2))
        far_days = float(tasty_row_field(far, 2))
        days_between = far_days - near_days
        if days_between <= 0:
            continue
        near_price = float(tasty_row_field(near, 3))
        far_price = float(tasty_row_field(far, 3))
        dt_years = days_between / 365.0
        c = np.log(far_price / near_price) / dt_years
        net_storage = c - r
        convenience_yield = r + u - c
        carries.append(c)
        legs.append((near, far, near_price, far_price, days_between, c, net_storage, convenience_yield))

    if not legs:
        return NIL

    median_carry = float(np.median(carries))
    threshold = float(leg_signal_threshold_pct)

    out_rows = []
    for near, far, near_price, far_price, days_between, c, net_storage, convenience_yield in legs:
        pct_diff = (c - median_carry) * 100
        if pct_diff > threshold:
            signal = "Far month rich / near cheap"
        elif pct_diff < -threshold:
            signal = "Far month cheap / near rich"
        else:
            signal = "Fair"
        out_rows.append(list_to_pairs([
            near[0], far[0], near_price, far_price, int(days_between),
            float(c * 100), float(net_storage * 100), float(convenience_yield * 100),
            LispString(signal),
        ]))
    return list_to_pairs(out_rows)

async def _tasty_collect_greeks(session, streamer_symbols, timeout):
    from tastytrade import DXLinkStreamer
    from tastytrade.dxfeed import Greeks
    collected = {}
    if not streamer_symbols:
        return collected

    async def _listen():
        async with DXLinkStreamer(session) as streamer:
            await _tasty_maybe_await(streamer.subscribe(Greeks, streamer_symbols))
            async for event in streamer.listen(Greeks):
                collected[event.event_symbol] = event
                if len(collected) >= len(streamer_symbols):
                    break

    try:
        await asyncio.wait_for(_listen(), timeout=timeout)
    except asyncio.TimeoutError:
        pass  # illiquid strikes may simply never publish greeks in time
    except Exception:
        pass  # streaming API mismatch/hiccup -- return whatever we got
    return collected


async def _tasty_price_and_iv_for_options(session, opts, price_kwarg, include_iv, greeks_timeout):
    """Shared tail end of both the futures- and equity-option fetches:
    looks up last/close price, volume, and open interest via one-shot
    REST calls (chunked at 100 symbols), then optionally streams implied
    volatility via Greeks. `price_kwarg` is "future_options" or
    "options", matching get_market_data_by_type's parameter names for
    each instrument type."""
    option_symbols = [s for s in (getattr(o, "symbol", None) for o in opts) if s]
    option_md = []
    for i in range(0, len(option_symbols), 100):
        chunk = option_symbols[i:i + 100]
        option_md.extend(await _tasty_maybe_await(
            _tt_get_market_data_by_type(session, **{price_kwarg: chunk})))
    option_price = {md.symbol: _tasty_pick_price(md) for md in option_md}
    option_volume = {md.symbol: getattr(md, "volume", None) for md in option_md}
    option_oi = {md.symbol: getattr(md, "open_interest", None) for md in option_md}

    greeks_by_symbol = {}
    if include_iv:
        streamer_symbols = [s for s in (getattr(o, "streamer_symbol", None) for o in opts) if s]
        greeks_by_symbol = await _tasty_collect_greeks(session, streamer_symbols, float(greeks_timeout))

    return option_price, option_volume, option_oi, greeks_by_symbol


def _tasty_option_row(opt, today, option_price, option_volume, option_oi, greeks_by_symbol,
                       delivery=None, underlying_label=None):
    symbol = getattr(opt, "symbol", None)
    streamer_symbol = getattr(opt, "streamer_symbol", None)
    strike = getattr(opt, "strike_price", None)
    exp_date = getattr(opt, "expiration_date", None)
    option_type = getattr(opt, "option_type", None)
    dte = _tasty_days_to_expiration(opt, exp_date, today)

    greeks = greeks_by_symbol.get(streamer_symbol)
    iv = getattr(greeks, "volatility", None) if greeks is not None else None
    price = option_price.get(symbol)
    volume = option_volume.get(symbol)
    oi = option_oi.get(symbol)

    return [
        LispString(symbol) if symbol else NIL,
        LispString(_tasty_option_type_label(option_type)) if option_type is not None else NIL,
        float(strike) if strike is not None else NIL,
        LispString(exp_date.isoformat()) if hasattr(exp_date, "isoformat") else NIL,
        int(dte) if dte is not None else NIL,
        LispDate(delivery.year, delivery.month, delivery.day) if delivery else NIL,
        LispString(underlying_label) if underlying_label else NIL,
        float(price) if price is not None else NIL,
        float(iv) if iv is not None else NIL,
        int(volume) if volume is not None else NIL,
        int(oi) if oi is not None else NIL,
    ]


async def _tasty_future_option_chain_async(session, root, n_months,
                                            max_strikes_per_expiration, include_iv, greeks_timeout):
    chain = await _tasty_maybe_await(_tt_get_future_option_chain(session, root))

    today = datetime.date.today()
    by_delivery_month = {}
    for exp_date, options in chain.items():
        for opt in options:
            delivery = _tasty_parse_delivery_month(getattr(opt, "underlying_symbol", ""), today) \
                or (exp_date.replace(day=1) if hasattr(exp_date, "replace") else None)
            if delivery is None:
                continue
            by_delivery_month.setdefault(delivery, []).append(opt)

    kept_months = sorted(mo for mo in by_delivery_month if mo >= today.replace(day=1))[:int(n_months)]
    candidate_options = [opt for mo in kept_months for opt in by_delivery_month[mo]]
    if not candidate_options:
        return []

    future_symbols = sorted({
        getattr(o, "underlying_symbol", None) for o in candidate_options
    } - {None})
    future_md = await _tasty_maybe_await(
        _tt_get_market_data_by_type(session, futures=future_symbols))
    future_price = {md.symbol: _tasty_pick_price(md) for md in future_md}

    grouped = {}
    for opt in candidate_options:
        key = (getattr(opt, "underlying_symbol", None), getattr(opt, "expiration_date", None))
        grouped.setdefault(key, []).append(opt)

    max_strikes_per_expiration = int(max_strikes_per_expiration)
    filtered_options = []
    for (underlying, _exp), opts in grouped.items():
        ref_price = future_price.get(underlying)
        if ref_price is not None:
            opts_sorted = sorted(
                opts, key=lambda o: abs(float(getattr(o, "strike_price", 0) or 0) - ref_price))
            filtered_options.extend(opts_sorted[: max_strikes_per_expiration * 2])
        else:
            filtered_options.extend(opts[: max_strikes_per_expiration * 2])

    option_price, option_volume, option_oi, greeks_by_symbol = await _tasty_price_and_iv_for_options(
        session, filtered_options, "future_options", include_iv, greeks_timeout)

    rows = []
    for opt in filtered_options:
        underlying = getattr(opt, "underlying_symbol", None) or ""
        delivery = _tasty_parse_delivery_month(underlying, today)
        rows.append(_tasty_option_row(
            opt, today, option_price, option_volume, option_oi, greeks_by_symbol,
            delivery=delivery, underlying_label=underlying.lstrip("/")))
    return rows


async def _tasty_equity_option_chain_async(session, symbol, n_months,
                                            max_strikes_per_expiration, include_iv, greeks_timeout):
    chain = await _tasty_maybe_await(_tt_get_option_chain(session, symbol))

    today = datetime.date.today()
    cutoff = _tasty_add_months(today, int(n_months))
    candidate_options = [
        opt for exp_date, options in chain.items()
        if exp_date is not None and today <= exp_date <= cutoff
        for opt in options
    ]
    if not candidate_options:
        return []

    equity_md = await _tasty_maybe_await(
        _tt_get_market_data_by_type(session, equities=[symbol]))
    ref_price = _tasty_pick_price(equity_md[0]) if equity_md else None

    grouped = {}
    for opt in candidate_options:
        grouped.setdefault(getattr(opt, "expiration_date", None), []).append(opt)

    max_strikes_per_expiration = int(max_strikes_per_expiration)
    filtered_options = []
    for _exp, opts in grouped.items():
        if ref_price is not None:
            opts_sorted = sorted(
                opts, key=lambda o: abs(float(getattr(o, "strike_price", 0) or 0) - ref_price))
            filtered_options.extend(opts_sorted[: max_strikes_per_expiration * 2])
        else:
            filtered_options.extend(opts[: max_strikes_per_expiration * 2])

    option_price, option_volume, option_oi, greeks_by_symbol = await _tasty_price_and_iv_for_options(
        session, filtered_options, "options", include_iv, greeks_timeout)

    return [
        _tasty_option_row(opt, today, option_price, option_volume, option_oi, greeks_by_symbol,
                          delivery=None, underlying_label=symbol)
        for opt in filtered_options
    ]


def _tasty_add_months(d, n):
    """d shifted forward by n months, clamped to the last valid day of
    the target month (e.g. Jan 31 + 1 month -> Feb 28/29, not Mar 3)."""
    month0 = d.month - 1 + int(n)
    year = d.year + month0 // 12
    month = month0 % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


async def _tasty_option_chain_async(credentials_path, symbol, n_months,
                                     max_strikes_per_expiration, include_iv, greeks_timeout):
    session = _tasty_session(credentials_path)
    kind, resolved = _tasty_resolve_symbol(symbol)
    if kind == "future":
        return await _tasty_future_option_chain_async(
            session, resolved, n_months, max_strikes_per_expiration, include_iv, greeks_timeout)
    else:
        return await _tasty_equity_option_chain_async(
            session, resolved, n_months, max_strikes_per_expiration, include_iv, greeks_timeout)


def tastytrade_option_chain_fn(credentials_path, symbol, n_months=12,
                                max_strikes_per_expiration=15, include_iv=True,
                                greeks_timeout=25.0):
    """(tastytrade-option-chain credentials-path symbol
         [n-months max-strikes-per-expiration include-iv? greeks-timeout])
    -> a Lisp list of rows, each row an 11-element list:
       (symbol type strike expiration-date days-to-expiration delivery-month
        underlying last-price implied-volatility volume open-interest)

    `symbol` can be:
      - A futures root starting with "/" (tastytrade's own convention,
        e.g. "/CL", "/ES") -- works for any futures product, not just
        ones with a curated short code.
      - A known short code from tastytrade-products (e.g. "CL"), kept
        for backward compatibility -- translated to "/CL" automatically.
      - Any other symbol (e.g. "AAPL", "SPY") -> fetched as an EQUITY
        option chain. No translation needed or done.

    `type` is the string "Call" or "Put". `delivery-month` and
    `underlying` are futures-specific: for equities, `delivery-month` is
    always '() and `underlying` is just the equity symbol itself. For
    equities, `n-months` limits results to expirations within that many
    months from today (there's no separate "delivery month" for an
    equity option the way there is for a futures option, so this is the
    closest equivalent). Missing values (e.g. no recent Greeks snapshot
    for implied-volatility) come back as '() (the empty list). Each
    expiration is trimmed to the `max-strikes-per-expiration` strikes
    nearest the underlying's price, since implied volatility comes from
    a live per-contract Greeks stream (`include-iv?` defaults to #t;
    pass #f to skip the stream entirely and fetch much faster).
    `greeks-timeout` (seconds) caps how long that stream is awaited."""
    rows = _run_async(_tasty_option_chain_async(
        credentials_path, symbol, int(n_months), int(max_strikes_per_expiration),
        is_true(include_iv), float(greeks_timeout)))
    return list_to_pairs([list_to_pairs(row) for row in rows])


def tastytrade_products_fn():
    """(tastytrade-products) -> a Lisp list of supported product code strings."""
    return list_to_pairs([LispString(code) for code in TASTY_PRODUCTS])


BUILTINS = {
    "tastytrade-test-connection": tastytrade_test_connection_fn,
    "tastytrade-futures-curve": tastytrade_futures_curve_fn,
    "tastytrade-futures-curve-rows": tastytrade_futures_curve_rows_fn,
    "tastytrade-option-chain": tastytrade_option_chain_fn,
    "tastytrade-curve-fit": tastytrade_curve_fit_fn,
    "tastytrade-leg-carry": tastytrade_leg_carry_fn,
    "tastytrade-products": tastytrade_products_fn,
}
