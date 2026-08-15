"""
tastytrade_source.py
=====================
tastytrade data source: real CME futures + futures-options data across
several popular products (see PRODUCTS below) and streamed implied
volatility, using the community `tastytrade` Python SDK
(pip install tastytrade), authenticated via a small local JSON
credentials file. This is the only data source the app uses.

--- Getting credentials (one-time setup) ---
1. Log into tastytrade and go to:
   https://my.tastytrade.com/app.html#/manage/api-access/oauth-applications
2. Create a new OAuth application (check the scopes you want — read-only
   market data access is enough for this app). Add http://localhost:8000
   as a valid redirect/callback URL. Save the CLIENT SECRET it shows you —
   it's only displayed once.
3. On the same page, find your new app > Manage > "Create Grant" to
   generate a REFRESH TOKEN. Save that too.
4. Put both into a JSON file (see tastytrade_credentials.example.json):
       {
         "client_secret": "...",
         "refresh_token": "...",
         "is_test": false
       }
   Refresh tokens don't expire and the SDK auto-renews the short-lived
   session token behind the scenes, so this is a one-time setup.

--- What this module fetches, and how ---
* Real futures-option chains for any product in PRODUCTS, via
  `get_future_option_chain`.
* Last/close prices via the one-shot `get_market_data_by_type` REST call.
* Implied volatility via a short-lived DXLink websocket subscription to
  the `Greeks` event stream — IV/Greeks are NOT exposed by the plain
  REST market-data endpoint, only by the streamer.

Streaming Greeks for every strike across every expiration would be slow
and could hit subscription limits, so each (underlying, expiration) group
is filtered down to the N strikes nearest the underlying's price before
subscribing (configurable; default 15 nearest strikes = up to 30
contracts per expiration, since both the call and put at each strike are
kept).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

try:
    import tastytrade as _tastytrade_pkg
    from tastytrade import Session, DXLinkStreamer
    from tastytrade.dxfeed import Greeks
    from tastytrade.instruments import get_future_option_chain
    from tastytrade.market_data import get_market_data_by_type
    TASTYTRADE_AVAILABLE = True
    TASTYTRADE_VERSION = getattr(_tastytrade_pkg, "__version__", "unknown")
except ImportError:
    TASTYTRADE_AVAILABLE = False
    TASTYTRADE_VERSION = None


async def _maybe_await(value):
    """Compatibility shim: the `tastytrade` SDK went async-only in v12.0.0.
    Older installed versions return plain results (lists, dicts, model
    instances, etc.) directly from calls like `Account.get(session)`
    instead of a coroutine. Calling `await` on a non-awaitable raises
    `TypeError: object <type> can't be used in await expression` — this
    helper detects which behavior is in play at runtime and does the
    right thing either way, so this module works against both API
    generations without needing to know in advance which one is
    installed."""
    if inspect.isawaitable(value):
        return await value
    return value

MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
CODE_TO_MONTH = {v: k for k, v in MONTH_CODES.items()}

# Supported products: code -> (tastytrade root symbol, display label).
# `root` is passed straight to get_future_option_chain()/used to build
# guessed futures symbols for the curve fetch (e.g. "/CL" + month code +
# single-digit year). Adding a new product is just adding a line here —
# everything else (chain parsing, delivery-month grouping, near-the-money
# filtering) is generic.
PRODUCTS = {
    "CL": {"root": "/CL", "label": "CL — WTI Crude Oil"},
    "MCL": {"root": "/MCL", "label": "MCL — Micro WTI Crude Oil"},
    "ES": {"root": "/ES", "label": "ES — E-mini S&P 500"},
    "NQ": {"root": "/NQ", "label": "NQ — E-mini Nasdaq-100"},
    "SR3": {"root": "/SR3", "label": "SR3 — Three-Month SOFR"},
    "ZN": {"root": "/ZN", "label": "ZN — 10-Year T-Note"},
    "ZQ": {"root": "/ZQ", "label": "ZQ — 30-Day Fed Funds"},
}

COLUMNS = [
    "Symbol", "Data Source", "Type", "Strike", "Expiration Date", "Delivery Month",
    "Underlying Future", "Last Price", "Implied Volatility",
    "Volume", "Open Interest",
]


class CredentialsError(Exception):
    pass


def load_credentials(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise CredentialsError(
            f"Credentials file not found: {path}\n"
            "See tastytrade_credentials.example.json for the expected format."
        )
    try:
        with open(p) as f:
            creds = json.load(f)
    except json.JSONDecodeError as e:
        raise CredentialsError(f"Credentials file isn't valid JSON: {e}")

    # Defensively strip whitespace/newlines — a very common copy-paste
    # artifact when pasting a long token out of a browser, and one that
    # produces exactly the kind of "Invalid JWT" error tastytrade returns
    # for a malformed token.
    for key in ("client_secret", "refresh_token"):
        if isinstance(creds.get(key), str):
            creds[key] = creds[key].strip()

    missing = [k for k in ("client_secret", "refresh_token") if not creds.get(k)]
    if missing:
        raise CredentialsError(
            f"Credentials file is missing: {', '.join(missing)}. "
            "See tastytrade_credentials.example.json for the expected format."
        )
    return creds


def _looks_like_jwt(token: str) -> bool:
    """Loose structural check: a JWT is 3 base64url segments joined by
    dots. This does NOT validate signature/contents — it's just a cheap
    way to catch obviously truncated/mangled tokens (e.g. from a bad
    copy-paste) without ever printing the actual secret value."""
    import re
    parts = token.split(".")
    if len(parts) != 3 or any(len(p) == 0 for p in parts):
        return False
    return all(re.fullmatch(r"[A-Za-z0-9_-]+", p) for p in parts)


def make_session(credentials_path: str):
    if not TASTYTRADE_AVAILABLE:
        raise CredentialsError(
            "The 'tastytrade' package is not installed.\n"
            "Install dependencies with:  pip install -r requirements.txt"
        )
    creds = load_credentials(credentials_path)
    return Session(
        creds["client_secret"], creds["refresh_token"],
        is_test=bool(creds.get("is_test", False)),
    )


def parse_delivery_month(underlying_symbol: str, reference_date: dt.date | None = None):
    """Parse a CME futures trading symbol into its delivery month
    (first-of-month date). Returns None if unparseable.

    tastytrade's plain `.symbol` field uses a SINGLE-digit year code
    (e.g. '/CLZ6' = December 2026, '/ESU3' = September 2023) — unlike
    the `.streamer_symbol` field, which uses two digits. Since a single
    digit is ambiguous across decades, this picks whichever decade
    produces a date closest to `reference_date` (defaults to today),
    allowing a small grace period into the past for recently-expired
    contracts still present in a freshly-fetched chain.
    """
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
    if month_code not in CODE_TO_MONTH:
        return None
    month = CODE_TO_MONTH[month_code]

    reference_date = reference_date or dt.date.today()
    if len(year_digits) >= 2:
        year = 2000 + int(year_digits[-2:])
    else:
        last_digit = int(year_digits)
        base_decade = (reference_date.year // 10) * 10
        year = base_decade + last_digit
        past_grace_years = 2
        if year < reference_date.year - past_grace_years:
            year += 10
    try:
        return dt.date(year, month, 1)
    except ValueError:
        return None


def _pick_price(md):
    """Prefer settled/close price; fall back to last trade, then mark/mid."""
    for attr in ("close", "last", "mark", "mid"):
        val = getattr(md, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _option_type_label(option_type) -> str:
    val = getattr(option_type, "value", option_type)
    return "Call" if str(val).upper().startswith("C") else "Put"


class TastytradeOptionsFetchWorker(QThread):
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, credentials_path: str, product: str = "CL", n_months: int = 12,
                 max_strikes_per_expiration: int = 15, greeks_timeout: float = 25.0, parent=None):
        super().__init__(parent)
        assert product in PRODUCTS, f"Unknown product {product!r}"
        self.credentials_path = credentials_path
        self.product = product
        self.n_months = n_months
        self.max_strikes_per_expiration = max_strikes_per_expiration
        self.greeks_timeout = greeks_timeout
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if not TASTYTRADE_AVAILABLE:
            self.failed.emit(
                "The 'tastytrade' package is not installed.\n"
                "Install dependencies with:  pip install -r requirements.txt"
            )
            return
        try:
            df = asyncio.run(self._fetch_async())
            self.finished_ok.emit(df)
        except CredentialsError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(
                f"tastytrade fetch failed: {e}\n\n"
                "If this looks like a missing/renamed attribute, the "
                "'tastytrade' SDK may have changed its data model since "
                "this app was written."
            )

    async def _fetch_async(self) -> pd.DataFrame:
        self.progress.emit("Authenticating with tastytrade...")
        session = make_session(self.credentials_path)

        root = PRODUCTS[self.product]["root"]
        self.progress.emit(f"Fetching {root} futures-option chain...")
        chain = await _maybe_await(get_future_option_chain(session, root))  # Dict[date, List[FutureOption]]

        if self._cancel:
            return pd.DataFrame(columns=COLUMNS)

        today = dt.date.today()
        by_delivery_month: dict = {}
        for exp_date, options in chain.items():
            for opt in options:
                delivery = parse_delivery_month(getattr(opt, "underlying_symbol", "")) \
                    or (exp_date.replace(day=1) if hasattr(exp_date, "replace") else None)
                if delivery is None:
                    continue
                by_delivery_month.setdefault(delivery, []).append(opt)

        kept_months = sorted(m for m in by_delivery_month if m >= today.replace(day=1))[: self.n_months]
        candidate_options = [opt for m in kept_months for opt in by_delivery_month[m]]

        if not candidate_options:
            self.progress.emit("No option contracts found for this product/date range.")
            return pd.DataFrame(columns=COLUMNS)

        # --- underlying futures prices (used to pick near-the-money strikes) ---
        future_symbols = sorted({
            getattr(o, "underlying_symbol", None) for o in candidate_options
        } - {None})
        self.progress.emit(f"Fetching futures prices for {len(future_symbols)} contract month(s)...")
        future_md = await _maybe_await(get_market_data_by_type(session, futures=future_symbols))
        future_price = {md.symbol: _pick_price(md) for md in future_md}

        # --- filter to N nearest strikes per (underlying, expiration) ---
        grouped: dict = {}
        for opt in candidate_options:
            key = (getattr(opt, "underlying_symbol", None), getattr(opt, "expiration_date", None))
            grouped.setdefault(key, []).append(opt)

        filtered_options = []
        for (underlying, _exp), opts in grouped.items():
            ref_price = future_price.get(underlying)
            if ref_price is not None:
                opts_sorted = sorted(
                    opts,
                    key=lambda o: abs(float(getattr(o, "strike_price", 0) or 0) - ref_price),
                )
                filtered_options.extend(opts_sorted[: self.max_strikes_per_expiration * 2])
            else:
                filtered_options.extend(opts[: self.max_strikes_per_expiration * 2])

        if self._cancel:
            return pd.DataFrame(columns=COLUMNS)

        # --- option last/close prices (chunked REST calls) ---
        option_symbols = [s for s in (getattr(o, "symbol", None) for o in filtered_options) if s]
        self.progress.emit(f"Fetching prices for {len(option_symbols)} option contract(s)...")
        option_md = []
        for i in range(0, len(option_symbols), 100):
            chunk = option_symbols[i:i + 100]
            option_md.extend(await _maybe_await(get_market_data_by_type(session, future_options=chunk)))
        option_price = {md.symbol: _pick_price(md) for md in option_md}
        option_volume = {md.symbol: getattr(md, "volume", None) for md in option_md}
        option_oi = {md.symbol: getattr(md, "open_interest", None) for md in option_md}

        if self._cancel:
            return pd.DataFrame(columns=COLUMNS)

        # --- implied volatility via streamed Greeks ---
        streamer_symbols = [s for s in (getattr(o, "streamer_symbol", None) for o in filtered_options) if s]
        self.progress.emit(
            f"Streaming implied volatility for {len(streamer_symbols)} contract(s) "
            f"(up to {self.greeks_timeout:.0f}s)..."
        )
        greeks_by_symbol = await self._collect_greeks(session, streamer_symbols)

        # --- assemble rows ---
        rows = []
        for opt in filtered_options:
            symbol = getattr(opt, "symbol", None)
            streamer_symbol = getattr(opt, "streamer_symbol", None)
            underlying = getattr(opt, "underlying_symbol", None) or ""
            strike = getattr(opt, "strike_price", None)
            exp_date = getattr(opt, "expiration_date", None)
            option_type = getattr(opt, "option_type", None)

            delivery = parse_delivery_month(underlying)
            greeks = greeks_by_symbol.get(streamer_symbol)
            iv = getattr(greeks, "volatility", None) if greeks is not None else None

            rows.append({
                "Symbol": symbol,
                "Data Source": "tastytrade (real chain, streamed IV)",
                "Type": _option_type_label(option_type) if option_type is not None else None,
                "Strike": float(strike) if strike is not None else None,
                "Expiration Date": exp_date.isoformat() if hasattr(exp_date, "isoformat") else exp_date,
                "Delivery Month": delivery.strftime("%b %Y") if delivery else None,
                "Underlying Future": underlying.lstrip("/"),
                "Last Price": option_price.get(symbol),
                "Implied Volatility": float(iv) if iv is not None else None,
                "Volume": option_volume.get(symbol),
                "Open Interest": option_oi.get(symbol),
            })

        df = pd.DataFrame(rows, columns=COLUMNS)
        n_with_iv = int(df["Implied Volatility"].notna().sum()) if not df.empty else 0
        self.progress.emit(f"Done. {len(df)} option contract(s), {n_with_iv} with implied volatility.")
        return df

    async def _collect_greeks(self, session, streamer_symbols: list) -> dict:
        collected: dict = {}
        if not streamer_symbols:
            return collected

        async def _listen():
            async with DXLinkStreamer(session) as streamer:
                await _maybe_await(streamer.subscribe(Greeks, streamer_symbols))
                async for event in streamer.listen(Greeks):
                    collected[event.event_symbol] = event
                    if self._cancel or len(collected) >= len(streamer_symbols):
                        break

        try:
            await asyncio.wait_for(_listen(), timeout=self.greeks_timeout)
        except asyncio.TimeoutError:
            self.progress.emit(
                f"Implied volatility stream timed out — got {len(collected)}/"
                f"{len(streamer_symbols)} (illiquid strikes may not publish greeks)."
            )
        except Exception as e:
            self.progress.emit(
                f"Implied volatility stream error ({e}). Continuing without IV for "
                "this refresh — the installed tastytrade SDK's streaming API may not "
                "match what this app expects."
            )
        return collected


class TastytradeFuturesCurveWorker(QThread):
    """Fetches last price for each upcoming contract month of the
    selected product directly from tastytrade (used by the Relative
    Value tab). Guessed contract-month symbols that don't actually exist
    for a given product (e.g. equity index/rates products that only
    list quarterly months) simply come back with no price and are
    skipped — this is a single bulk REST call, so guessing extra months
    costs effectively nothing."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, credentials_path: str, product: str = "CL", n_months: int = 18, parent=None):
        super().__init__(parent)
        assert product in PRODUCTS, f"Unknown product {product!r}"
        self.credentials_path = credentials_path
        self.product = product
        self.n_months = n_months
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if not TASTYTRADE_AVAILABLE:
            self.failed.emit(
                "The 'tastytrade' package is not installed.\n"
                "Install dependencies with:  pip install -r requirements.txt"
            )
            return
        try:
            df = asyncio.run(self._fetch_async())
            self.finished_ok.emit(df)
        except CredentialsError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"tastytrade fetch failed: {e}")

    async def _fetch_async(self) -> pd.DataFrame:
        self.progress.emit("Authenticating with tastytrade...")
        session = make_session(self.credentials_path)

        root = PRODUCTS[self.product]["root"]
        today = dt.date.today()
        y, m = today.year, today.month
        candidate_symbols, candidate_months = [], []
        for i in range(self.n_months):
            total = (m - 1) + i
            mm = total % 12 + 1
            yyyy = y + total // 12
            code = MONTH_CODES[mm]
            # tastytrade's plain trading symbol uses a single-digit year
            # (e.g. "/CLZ6" for Dec 2026), unlike the streamer symbol.
            candidate_symbols.append(f"{root}{code}{yyyy % 10}")
            candidate_months.append(dt.date(yyyy, mm, 1))

        self.progress.emit(f"Fetching prices for {len(candidate_symbols)} {self.product} contract month(s)...")
        market_data = await _maybe_await(get_market_data_by_type(session, futures=candidate_symbols))
        price_by_symbol = {md.symbol: _pick_price(md) for md in market_data}

        rows = []
        for sym, delivery in zip(candidate_symbols, candidate_months):
            price = price_by_symbol.get(sym)
            if price is None:
                continue
            rows.append({
                "Delivery Month": delivery.strftime("%b %Y"),
                "Futures Symbol": sym.lstrip("/"),
                "Days to Delivery": (delivery - today).days,
                "Last Price": price,
            })

        df = pd.DataFrame(rows)
        self.progress.emit(f"Done. {len(df)} contract month(s) with a price.")
        return df


async def _test_connection_async(credentials_path: str) -> str:
    session = make_session(credentials_path)
    from tastytrade import Account
    raw = Account.get(session)
    api_style = "async (v12+)" if inspect.isawaitable(raw) else "sync (pre-v12)"
    accounts = await _maybe_await(raw)
    version_note = f"tastytrade SDK v{TASTYTRADE_VERSION}, {api_style} API detected."
    if not accounts:
        return f"Connected, but no accounts were found on this login. {version_note}"
    numbers = ", ".join(getattr(a, "account_number", str(a)) for a in accounts)
    return f"Connected successfully. Account(s): {numbers}. {version_note}"


def test_connection(credentials_path: str) -> str:
    """Synchronous wrapper for a quick auth sanity check. Raises on failure."""
    if not TASTYTRADE_AVAILABLE:
        raise CredentialsError(
            "The 'tastytrade' package is not installed.\n"
            "Install dependencies with:  pip install -r requirements.txt"
        )
    return asyncio.run(_test_connection_async(credentials_path))


class TastytradeTestConnectionWorker(QThread):
    """Runs test_connection() off the GUI thread (it does real network I/O)."""

    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, credentials_path: str, parent=None):
        super().__init__(parent)
        self.credentials_path = credentials_path

    def run(self):
        try:
            message = test_connection(self.credentials_path)
            self.succeeded.emit(message)
        except Exception as e:
            self.failed.emit(str(e))
