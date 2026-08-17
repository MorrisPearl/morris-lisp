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

--- What "a few options" means here ---
SOFR futures options are American-style, expire monthly, and are listed
on many strikes. To keep this simple and match "use a FEW exchange traded
options" from the brief, this fetches only the options on ONE nearby
quarterly SR3 contract (whichever near-dated quarter actually has a
listed option chain -- the currently-accruing front quarter often
doesn't), at its nearest expiration, at the `n_strikes` strikes closest
to that future's current price (both call and put at each strike).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tasty_api"))

import tastytrade_source as tt  # noqa: E402  (path must be set up first)

try:
    from tastytrade.instruments import Future, get_future_option_chain
    from tastytrade.market_data import get_market_data_by_type
except ImportError:
    pass  # tt.TASTYTRADE_AVAILABLE guards all use below

DEFAULT_CREDENTIALS_PATH = str(Path.home() / "credentials.json")

SR3_ROOT = "/SR3"
DAYS_PER_MONTH = 365.2425 / 12.0


def _months_between(d1: dt.date, d2: dt.date) -> float:
    """Signed number of months from d1 to d2 (fractional)."""
    return (d2 - d1).days / DAYS_PER_MONTH


def _option_type_str(option_type) -> str:
    val = getattr(option_type, "value", option_type)
    return "call" if str(val).upper().startswith("C") else "put"


def _calibration_price(md):
    """Pick a market price suited to CALIBRATION, as opposed to display:
    prefer a live mark/mid quote over a possibly-stale last-trade print.
    Calibration needs prices that are mutually consistent with each other
    at a single point in time (e.g. respecting put-call parity across a
    strike) far more than it needs trade-history accuracy -- unlike
    tastytrade_source._pick_price() (used for display in the tasty_api
    viewer), which prefers close/last first and only falls back to
    mark/mid when no trade has happened. For a thinly-traded short-dated
    future option, 'last' can be a stale print from well before the
    current bid/ask and materially violate parity against a same-strike
    call/put pulled seconds apart -- 'mark' does not have that problem."""
    mark = getattr(md, "mark", None)
    if mark is not None:
        try:
            return float(mark)
        except (TypeError, ValueError):
            pass
    bid, ask = getattr(md, "bid", None), getattr(md, "ask", None)
    if bid is not None and ask is not None:
        try:
            return (float(bid) + float(ask)) / 2.0
        except (TypeError, ValueError):
            pass
    return tt._pick_price(md)


async def _fetch_async(credentials_path: str, n_futures: int, n_underlyings: int,
                        n_strikes: int, today: dt.date):
    session = tt.make_session(credentials_path)

    # --- 1. All listed SR3 futures contracts (used for both the curve and
    #        to find each option's underlying quarter's settlement date) ---
    all_futures = await tt._maybe_await(Future.get(session, product_codes=["SR3"]))
    all_futures = [f for f in all_futures if getattr(f, "expiration_date", None) is not None]
    all_futures.sort(key=lambda f: f.expiration_date)

    curve_futures = all_futures[:n_futures]
    future_symbols = [f.symbol for f in curve_futures]
    futures_md = await tt._maybe_await(get_market_data_by_type(session, futures=future_symbols))
    price_by_symbol = {md.symbol: _calibration_price(md) for md in futures_md}

    # SR3 accrual quarters run IMM-date to IMM-date (3rd Wednesday to 3rd
    # Wednesday), NOT calendar-month to calendar-month, so each quarter's
    # start is chained to the PREVIOUS contract's own settlement date
    # (its expiration_date) rather than approximated from the delivery
    # month's first-of-month date -- using the first-of-month approximation
    # for every contract independently can round two adjacent quarters'
    # starts to the same month and make them silently overlap. The only
    # place the first-of-month approximation is still used is to decide
    # whether the very FRONT contract has already begun accruing.
    curve = []
    prior_end_months = None
    for f in curve_futures:
        price = price_by_symbol.get(f.symbol)
        if price is None:
            continue
        end_months = round(_months_between(today, f.expiration_date))
        if prior_end_months is None:
            delivery_start = tt.parse_delivery_month(f.symbol, reference_date=today)
            already_started = delivery_start is not None and delivery_start <= today
            start_months = 0 if already_started else max(
                round(_months_between(today, delivery_start)), 0)
        else:
            start_months = prior_end_months
        if end_months <= start_months:
            end_months = start_months + 1
        curve.append({
            'symbol': f.symbol,
            'price': price,
            'rate': (100.0 - price) / 100.0,
            'start_months': start_months,
            'end_months': end_months,
            'expiration_date': f.expiration_date,
        })
        prior_end_months = end_months
    curve.sort(key=lambda q: q['start_months'])

    if not curve:
        raise RuntimeError(
            "No SR3 futures with a usable price were returned -- check "
            "market hours / connectivity and try again."
        )

    # --- 2. Option chain: pick the n_underlyings nearest curve quarters
    #        that actually have a listed option chain, and on EACH one
    #        keep its nearest expiration's n_strikes strikes closest to
    #        that future's current price.
    #
    #        Spanning more than one underlying quarter matters here, not
    #        just for more data points: sigma1 (short-rate factor) and
    #        sigma2 (mean-reversion-level factor) are both roughly
    #        "noise added to the short rate," and over a SINGLE short
    #        horizon their effects on the option payoff are close to
    #        collinear (see _sofr_futures_price_from_state()'s blend
    #        weights), so calibrating against options that all share one
    #        expiry leaves the two parameters poorly identified -- the
    #        grid search can land on a corner solution (e.g. sigma1 ~ 0)
    #        that fits that one expiry fine but isn't a meaningful split
    #        of the two vols. Using near- and far-dated expiries together
    #        gives the search two different mean-reversion-decay weightings
    #        to separate them by. ---
    chain = await tt._maybe_await(get_future_option_chain(session, SR3_ROOT))
    all_opts = [o for opts in chain.values() for o in opts]
    opts_by_underlying: dict = {}
    for o in all_opts:
        opts_by_underlying.setdefault(o.underlying_symbol, []).append(o)

    targets = [q for q in curve if q['symbol'] in opts_by_underlying][:n_underlyings]
    if not targets:
        raise RuntimeError(
            "None of the fetched SR3 futures contract months have a "
            "listed option chain -- try increasing n_futures."
        )

    selected = []  # list of (FutureOption, target_quarter_dict)
    for target in targets:
        target_opts = opts_by_underlying[target['symbol']]
        nearest_exp = min(o.expiration_date for o in target_opts)
        near_opts = [o for o in target_opts if o.expiration_date == nearest_exp]

        ref_price = target['price']
        strikes_sorted = sorted({float(o.strike_price) for o in near_opts},
                                 key=lambda k: abs(k - ref_price))
        kept_strikes = set(strikes_sorted[:n_strikes])
        selected.extend(
            (o, target) for o in near_opts if float(o.strike_price) in kept_strikes
        )

    option_symbols = [o.symbol for o, _ in selected]
    options_md = await tt._maybe_await(
        get_market_data_by_type(session, future_options=option_symbols))
    price_by_option_symbol = {md.symbol: _calibration_price(md) for md in options_md}

    options = []
    for o, target in selected:
        market_price = price_by_option_symbol.get(o.symbol)
        # Skip anything with no usable quote at all -- these would just
        # inject noise into the calibration's squared-error objective.
        if market_price is None or market_price <= 0:
            continue
        expiry_months = max(round(_months_between(today, o.expiration_date)), 1)
        options.append({
            'type': _option_type_str(o.option_type),
            'strike': float(o.strike_price),
            'expiry_months': expiry_months,
            'quarter_start_months': target['start_months'],
            'quarter_end_months': target['end_months'],
            'market_price': market_price,
            'symbol': o.symbol,
            'underlying_symbol': o.underlying_symbol,
            'underlying_price': target['price'],
        })

    if not options:
        raise RuntimeError(
            f"Found {len(selected)} near-the-money option contracts across "
            f"{[t['symbol'] for t in targets]} but none had a usable "
            "market price -- try again during market hours."
        )

    return curve, options


def fetch_sofr_calibration_data(credentials_path: str | None = None,
                                 n_futures: int = 8, n_underlyings: int = 2,
                                 n_strikes: int = 2,
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
                      the curve (8 quarters ~= 2 years of real
                      market-implied forward rates; the curve is
                      extrapolated flat beyond that -- see
                      bootstrap_sofr_curve()'s SIMPLIFICATIONS).
    n_underlyings -- how many of the nearest curve quarters (that have a
                      listed option chain) to draw calibration options
                      from. Deliberately > 1: sigma1 and sigma2 are poorly
                      identified from a single expiry alone (see the
                      comment above the option-selection loop), so this
                      spans near- and farther-dated expiries on purpose.
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
    return asyncio.run(
        _fetch_async(credentials_path, n_futures, n_underlyings, n_strikes, today))
