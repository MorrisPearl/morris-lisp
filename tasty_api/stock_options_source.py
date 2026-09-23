"""
stock_options_source.py
=========================
tastytrade data source for a single stock's (or ETF's) listed equity
options: the full chain via `get_option_chain`, filtered to the N
strikes nearest the underlying's price per expiration, real bid/ask/
last/volume/open-interest via the one-shot `get_market_data_by_type`
REST call, and implied volatility + delta via the same streamed-Greeks
approach `tastytrade_source.py` uses for futures options (IV isn't in
the REST market-data snapshot for equity options either -- only the
DXLink Greeks stream publishes it).

Reuses make_session/load_credentials/CredentialsError/_maybe_await/
_pick_price from tastytrade_source.py so there's one place that knows
how to authenticate and pick a representative price.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from tastytrade_source import (
    TASTYTRADE_AVAILABLE, CredentialsError, make_session, _maybe_await, _pick_price,
)

try:
    from tastytrade import DXLinkStreamer
    from tastytrade.dxfeed import Greeks
    from tastytrade.instruments import get_option_chain
    from tastytrade.market_data import get_market_data_by_type
except ImportError:
    pass


COLUMNS = [
    "Symbol", "Type", "Strike", "Expiration Date", "Days to Expiration",
    "Underlying Price", "Bid", "Ask", "Mid", "Last Price",
    "Implied Volatility", "Delta", "Volume", "Open Interest",
]


def _option_type_label(option_type) -> str:
    val = getattr(option_type, "value", option_type)
    return "Call" if str(val).upper().startswith("C") else "Put"


class TastytradeStockOptionsFetchWorker(QThread):
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, credentials_path: str, ticker: str, max_expirations: int = 6,
                 max_strikes_per_expiration: int = 20, greeks_timeout: float = 25.0, parent=None):
        super().__init__(parent)
        self.credentials_path = credentials_path
        self.ticker = ticker.strip().upper()
        self.max_expirations = max_expirations
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
        if not self.ticker:
            self.failed.emit("Enter a ticker symbol first.")
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
                "'tastytrade' SDK may have changed its data model since this "
                "app was written -- or the ticker may not have listed options."
            )

    async def _fetch_async(self) -> pd.DataFrame:
        self.progress.emit("Authenticating with tastytrade...")
        session = make_session(self.credentials_path)

        self.progress.emit(f"Fetching option chain for {self.ticker}...")
        chain = await _maybe_await(get_option_chain(session, self.ticker))
        if not chain:
            self.progress.emit(f"No listed options found for {self.ticker}.")
            return pd.DataFrame(columns=COLUMNS)

        if self._cancel:
            return pd.DataFrame(columns=COLUMNS)

        today = dt.date.today()
        kept_expirations = sorted(e for e in chain if e >= today)[: self.max_expirations]
        candidate_options = [opt for e in kept_expirations for opt in chain[e]]
        if not candidate_options:
            self.progress.emit("No upcoming expirations found.")
            return pd.DataFrame(columns=COLUMNS)

        self.progress.emit(f"Fetching {self.ticker} underlying price...")
        underlying_md = await _maybe_await(get_market_data_by_type(session, equities=[self.ticker]))
        underlying_price = _pick_price(underlying_md[0]) if underlying_md else None

        # --- filter to N nearest strikes per expiration ---
        grouped: dict = {}
        for opt in candidate_options:
            grouped.setdefault(opt.expiration_date, []).append(opt)

        filtered_options = []
        for _exp, opts in grouped.items():
            if underlying_price is not None:
                opts_sorted = sorted(opts, key=lambda o: abs(float(o.strike_price) - underlying_price))
                filtered_options.extend(opts_sorted[: self.max_strikes_per_expiration * 2])
            else:
                filtered_options.extend(opts[: self.max_strikes_per_expiration * 2])

        if self._cancel:
            return pd.DataFrame(columns=COLUMNS)

        # --- bid/ask/last/volume/OI (one-shot REST, chunked) ---
        option_symbols = [o.symbol for o in filtered_options if o.symbol]
        self.progress.emit(f"Fetching quotes for {len(option_symbols)} option contract(s)...")
        option_md = []
        for i in range(0, len(option_symbols), 100):
            chunk = option_symbols[i:i + 100]
            option_md.extend(await _maybe_await(get_market_data_by_type(session, options=chunk)))
        md_by_symbol = {md.symbol: md for md in option_md}

        if self._cancel:
            return pd.DataFrame(columns=COLUMNS)

        # --- implied volatility + delta via streamed Greeks ---
        streamer_symbols = [s for s in (o.streamer_symbol for o in filtered_options) if s]
        self.progress.emit(
            f"Streaming implied volatility for {len(streamer_symbols)} contract(s) "
            f"(up to {self.greeks_timeout:.0f}s)..."
        )
        greeks_by_symbol = await self._collect_greeks(session, streamer_symbols)

        rows = []
        for opt in filtered_options:
            md = md_by_symbol.get(opt.symbol)
            greeks = greeks_by_symbol.get(opt.streamer_symbol)
            bid = float(md.bid) if md is not None and md.bid is not None else None
            ask = float(md.ask) if md is not None and md.ask is not None else None
            mid = (bid + ask) / 2 if bid is not None and ask is not None else None
            iv = greeks.volatility if greeks is not None else None
            delta = greeks.delta if greeks is not None else None

            rows.append({
                "Symbol": opt.symbol,
                "Type": _option_type_label(opt.option_type),
                "Strike": float(opt.strike_price),
                "Expiration Date": opt.expiration_date.isoformat(),
                "Days to Expiration": (opt.expiration_date - today).days,
                "Underlying Price": underlying_price,
                "Bid": bid,
                "Ask": ask,
                "Mid": mid,
                "Last Price": _pick_price(md) if md is not None else None,
                "Implied Volatility": float(iv) if iv is not None else None,
                "Delta": float(delta) if delta is not None else None,
                "Volume": getattr(md, "volume", None) if md is not None else None,
                "Open Interest": getattr(md, "open_interest", None) if md is not None else None,
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
                f"{len(streamer_symbols)} (illiquid strikes may not publish greeks; "
                "outside market hours the stream may not publish at all -- Last "
                "Price/Bid/Ask still come from the REST snapshot)."
            )
        except Exception as e:
            self.progress.emit(
                f"Implied volatility stream error ({e}). Continuing without IV for "
                "this refresh."
            )
        return collected
