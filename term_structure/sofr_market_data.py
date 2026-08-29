"""
sofr_market_data.py
====================
Fetches real, exchange-traded CME 3-Month SOFR (SR3) futures prices and a
handful of near-the-money option quotes on those futures, via the
tastytrade broker API, and shapes them into the plain-number dicts that
term_structure_model.bootstrap_sofr_curve() / price_sofr_future_option_mc()
expect.

This module is the ONLY place in the SOFR pipeline that talks to
tastytrade -- term_structure_model.py stays free of any network/broker
dependency, so it can be tested and reused without a live connection.

Reuses the session/auth plumbing already written for the CME futures
options viewer in ../tasty_api/tastytrade_source.py (same credentials
file format, same make_session()/parse_delivery_month() helpers) rather
than duplicating it.

--- Credentials ---
Defaults to ~/credentials.json (same file the tasty_api app defaults to
in main.py's CredentialsBar) -- pass credentials_path explicitly to use a
different file. See ../tasty_api/README.md for how to obtain a
client_secret + refresh_token.

--- "As far out as they go" ---
fetch_sofr_calibration_data()'s n_futures defaults to 40, comfortably
above the ~20 quarterly SR3 contracts CME actually lists at any time (a
~5 year strip) -- so by default this uses every contract tastytrade
returns, not an arbitrary near-term subset. bootstrap_sofr_curve() (in
term_structure_model.py) still has to extrapolate flat past the last one
to fill out the model's full 30-year grid; there is no market information
further out than the last listed contract.

--- Spreading calibration options across the curve ---
sigma1 (the fast-moving short-rate factor) and sigma2 (the slower
mean-reversion-level factor) are hard to tell apart from options
clustered at similar expiries -- both blend together into "how uncertain
is the near-term rate". Options on CONTRACTS FURTHER OUT ON THE CURVE
give sigma2 more room to show up on its own. So rather than just grabbing
the n_underlyings nearest contract months with a listed option chain,
this spreads its picks evenly across every curve quarter that has one
(see the n_underlyings docstring below).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tasty_api"))
import tastytrade_source as tt  # noqa: E402

try:
    from tastytrade.instruments import Future, get_future_option_chain  # noqa: E402
    from tastytrade.market_data import get_market_data_by_type  # noqa: E402
except ImportError:
    pass  # tt.TASTYTRADE_AVAILABLE below covers this; nothing here is called if it's False.

DEFAULT_CREDENTIALS_PATH = str(Path.home() / "credentials.json")
SR3_ROOT = "/SR3"
DAYS_PER_MONTH = 30.436875  # 365.2425 / 12 -- average Gregorian month length


def _months_between(d1: dt.date, d2: dt.date) -> float:
    """Signed number of months from d1 to d2 (fractional)."""
    return (d2 - d1).days / DAYS_PER_MONTH


def _option_type_str(option_type) -> str:
    val = getattr(option_type, "value", option_type)
    return "call" if str(val).upper().startswith("C") else "put"


def _calibration_price(md):
    """
    Pick a market price suited to CALIBRATION, as opposed to display: only
    trust a price backed by real market evidence -- a two-sided bid/ask
    quote (preferred: calibration needs prices that are mutually
    consistent with each other at a single point in time, e.g. respecting
    put-call parity across a strike, far more than it needs trade-history
    accuracy) or an actual trade print (last/close) -- and return None
    otherwise, so the caller skips the contract.

    This deliberately does NOT fall back to tastytrade's bare 'mark' field
    the way tastytrade_source._pick_price() does (that function is for
    DISPLAY in the tasty_api viewer, where a rough number beats a blank
    cell). Found by testing against real SR3 quotes: several far-dated,
    essentially untraded strikes came back with bid=ask=last=close=None
    but a lone 'mark' of ~25-28 points on a ~96 future -- wildly larger
    than any sane premium at those strikes (a handful of points
    in-the-money should be worth single digits, not 27) -- clearly a
    theoretical value with no real market behind it. A bad calibration
    price actively corrupts the fitted (sigma1, sigma2); it's better to
    use one fewer option than a wrong one.
    """
    bid, ask = getattr(md, "bid", None), getattr(md, "ask", None)
    if bid is not None and ask is not None:
        try:
            return (float(bid) + float(ask)) / 2.0
        except (TypeError, ValueError):
            pass
    for attr in ("close", "last"):
        val = getattr(md, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _run_async(coro):
    """Run an asyncio coroutine to completion and return its result --
    works whether or not the calling thread already has its OWN running
    event loop. With no loop already running (a plain script, or via
    lisp_interpreter.py's console REPL/GUI/batch mode), this is exactly
    asyncio.run(coro). With one already running -- e.g. lisp_interpreter.
    py's Jupyter integration (lisp_jupyter.py), where ipykernel runs one
    continuously -- asyncio.run() would raise "asyncio.run() cannot be
    called from a running event loop", so this runs the coroutine to
    completion on a SEPARATE thread with its own fresh event loop
    instead, and blocks the calling thread until it's done. Either way,
    fetch_sofr_calibration_data() just returns a plain value,
    synchronously -- no awaiting, no nest_asyncio monkeypatching needed.
    See the identical helper in lisp_interp/lisp_interpreter.py."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _fetch_async(credentials_path: str, n_futures: int, n_underlyings: int,
                        n_strikes: int, today: dt.date):
    session = tt.make_session(credentials_path)

    # --- SOFR futures curve --------------------------------------------
    all_futures = await tt._maybe_await(Future.get(session, product_codes=["SR3"]))
    all_futures = [f for f in all_futures if getattr(f, "expiration_date", None) is not None]
    all_futures.sort(key=lambda f: f.expiration_date)

    curve_futures = all_futures[:n_futures]
    future_symbols = [f.symbol for f in curve_futures]
    futures_md = await tt._maybe_await(get_market_data_by_type(session, futures=future_symbols))
    price_by_symbol = {md.symbol: _calibration_price(md) for md in futures_md}

    curve = []
    prior_end_months = None
    for f in curve_futures:
        price = price_by_symbol.get(f.symbol)
        if price is None:
            continue
        end_months = round(_months_between(today, f.expiration_date))
        if prior_end_months is None:
            # Front contract: its accrual quarter may have already begun
            # (SR3's reference quarter runs from the PRIOR IMM date to
            # this one, so "today" often falls inside it) -- in that case
            # the quarter covers today through the contract's own
            # expiration, i.e. starts at month 0, not some point in the
            # past.
            delivery_start = tt.parse_delivery_month(f.symbol, reference_date=today)
            already_started = delivery_start is not None and delivery_start <= today
            start_months = 0 if already_started else max(round(_months_between(today, delivery_start)), 0)
        else:
            start_months = prior_end_months
        if end_months <= start_months:
            end_months = start_months + 1
        curve.append({
            "symbol": f.symbol,
            "price": price,
            "rate": (100.0 - price) / 100.0,
            "start_months": start_months,
            "end_months": end_months,
            "expiration_date": f.expiration_date,
        })
        prior_end_months = end_months
    curve.sort(key=lambda q: q["start_months"])

    if not curve:
        raise RuntimeError(
            "No SR3 futures with a usable price were returned -- check market hours / connectivity and try again.")

    # --- calibration options, spread across the curve -------------------
    chain = await tt._maybe_await(get_future_option_chain(session, SR3_ROOT))  # Dict[expiry, List[FutureOption]]
    all_opts = [o for opts in chain.values() for o in opts]

    opts_by_underlying = {}
    for o in all_opts:
        opts_by_underlying.setdefault(o.underlying_symbol, []).append(o)

    usable = [q for q in curve if q["symbol"] in opts_by_underlying]
    if not usable:
        raise RuntimeError(
            "None of the fetched SR3 futures contract months have a listed option chain -- try increasing n_futures.")

    # Evenly-spaced picks across every curve quarter that has a listed
    # option chain -- not just the nearest n_underlyings -- so
    # calibrate_volatilities() sees both near- and far-dated expiries and
    # can separately identify sigma1 from sigma2 (see the module
    # docstring).
    n_pick = min(n_underlyings, len(usable))
    pick_positions = np.linspace(0, len(usable) - 1, n_pick)
    pick_indices = sorted({int(round(p)) for p in pick_positions})
    targets = [usable[i] for i in pick_indices]

    selected = []
    for target in targets:
        target_opts = opts_by_underlying[target["symbol"]]
        nearest_exp = min(o.expiration_date for o in target_opts)
        near_opts = [o for o in target_opts if o.expiration_date == nearest_exp]

        ref_price = target["price"]
        strikes_sorted = sorted({float(o.strike_price) for o in near_opts},
                                 key=lambda k: abs(k - ref_price))
        kept_strikes = set(strikes_sorted[:n_strikes])
        selected.extend((o, target) for o in near_opts if float(o.strike_price) in kept_strikes)

    option_symbols = [o.symbol for o, _ in selected]
    options_md = []
    for i in range(0, len(option_symbols), 100):
        chunk = option_symbols[i:i + 100]
        options_md.extend(await tt._maybe_await(get_market_data_by_type(session, future_options=chunk)))
    price_by_option_symbol = {md.symbol: _calibration_price(md) for md in options_md}

    options = []
    for o, target in selected:
        market_price = price_by_option_symbol.get(o.symbol)
        if market_price is None or market_price <= 0:
            continue
        expiry_months = max(round(_months_between(today, o.expiration_date)), 1)
        options.append({
            "type": _option_type_str(o.option_type),
            "strike": float(o.strike_price),
            "expiry_months": expiry_months,
            "quarter_start_months": target["start_months"],
            "quarter_end_months": target["end_months"],
            "market_price": market_price,
            "symbol": o.symbol,
            "underlying_symbol": o.underlying_symbol,
            "underlying_price": target["price"],
        })

    if not options:
        raise RuntimeError(
            f"Found {len(selected)} near-the-money option contracts across "
            f"{[t['symbol'] for t in targets]} but none had a usable market price -- try again during market hours.")

    return curve, options


def fetch_sofr_calibration_data(credentials_path: str | None = None, n_futures: int = 40,
                                 n_underlyings: int = 10, n_strikes: int = 3,
                                 today: dt.date | None = None):
    """
    Fetch everything needed to bootstrap a SOFR curve and calibrate the
    two-factor model to real SOFR futures options, in one tastytrade
    session.

    Returns (curve_futures, options):
        curve_futures -- list of dicts (see bootstrap_sofr_curve()'s
                          docstring for the required keys), one per SR3
                          contract month, sorted by start_months. Ready to
                          pass straight to
                          term_structure_model.bootstrap_sofr_curve().
        options       -- list of dicts (see price_sofr_future_option_mc()'s
                          docstring), up to n_underlyings*n_strikes*2
                          near-the-money call/put pairs spread across
                          n_underlyings different quarterly contracts (and
                          therefore different expiries). Ready to pass
                          straight to term_structure_model.calibrate_
                          volatilities(..., price_fn=price_sofr_future_option_mc).

    n_futures     -- how many upcoming SR3 quarterly contracts to use for
                      the curve. Defaults to 40 -- comfortably more than
                      CME actually lists at once (~20, a ~5 year strip) --
                      so by default this uses every contract available,
                      not an arbitrary near-term subset. The curve is
                      extrapolated flat beyond the last one -- see
                      bootstrap_sofr_curve()'s SIMPLIFICATIONS.
    n_underlyings -- how many of the curve quarters that have a listed
                      option chain to draw calibration options from,
                      spaced as evenly as possible across ALL of them
                      (not just the nearest few). sigma1 and sigma2 are
                      poorly identified from options clustered at similar
                      expiries alone (see the module docstring), so this
                      spans near- and far-dated expiries on purpose.
    n_strikes     -- how many distinct near-the-money strikes to use per
                      underlying (both the call and put at each strike are
                      kept when available, so total options is up to
                      2 * n_strikes * n_underlyings).
    """
    if not tt.TASTYTRADE_AVAILABLE:
        raise tt.CredentialsError(
            "The 'tastytrade' package is not installed.\n"
            "Install it with:  pip install tastytrade"
        )
    credentials_path = credentials_path or DEFAULT_CREDENTIALS_PATH
    today = today or dt.date.today()
    return _run_async(_fetch_async(credentials_path, n_futures, n_underlyings, n_strikes, today))
