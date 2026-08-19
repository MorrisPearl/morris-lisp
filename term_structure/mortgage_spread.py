"""
mortgage_spread.py
===================
Computes an empirical SOFR-to-mortgage spread from real market data, for
term_structure_model.simulate_mortgage_rate_paths()'s mortgage_spread
parameter -- rather than just guessing a flat number like 175bp.

--- Why FRED, not "TBA futures" ---
The original idea was to back out the current mortgage rate from TBA MBS
futures prices. Checked directly against the live tastytrade API: it
doesn't work -- tastytrade lists 74 future products total, and NONE of
them are MBS/TBA/agency-related (no CME MBS future is in tastytrade's
tradable universe; TBA trading itself happens bilaterally between
broker-dealers, not on an exchange tastytrade connects to at all).

FRED's MORTGAGE30US is the best available substitute: a REAL,
weekly-updated, widely-quoted market rate (Freddie Mac's Primary Mortgage
Market Survey -- the standard reference for "the" US 30-year mortgage
rate) rather than something modeled or derived. The repo's
credentials.json already carries a fred_api_key for exactly this purpose
-- see ../lisp_interp/lisp_interpreter.py's fred_series(), which this
mirrors (same REST endpoint, same credentials-file convention).
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path

import sofr_market_data as smd
import term_structure_model as tsm

MORTGAGE30US_SERIES_ID = "MORTGAGE30US"  # Freddie Mac PMMS, 30-year fixed, weekly
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def _fred_api_key_from_file(path: str | Path) -> str:
    with open(path) as f:
        data = json.load(f)
    key = data.get("fred_api_key")
    if not key:
        raise ValueError(f"{path}: no \"fred_api_key\" entry (see ../tasty_api/README.md)")
    return key


def fetch_current_mortgage_rate(credentials_path: str | Path | None = None,
                                 series_id: str = MORTGAGE30US_SERIES_ID) -> tuple[dt.date, float]:
    """
    The most recent observation of a FRED weekly/daily mortgage-rate
    series, as a decimal (e.g. 0.0667 for 6.67%).

    Defaults to MORTGAGE30US -- Freddie Mac's Primary Mortgage Market
    Survey average 30-year fixed rate, published weekly (Thursdays).
    Pass a different series_id for another tenor (e.g. "MORTGAGE15US"
    for 15-year fixed).

    Returns (date, rate) -- date is the FRED observation date, rate is
    the decimal rate.
    """
    credentials_path = str(credentials_path or smd.DEFAULT_CREDENTIALS_PATH)
    api_key = _fred_api_key_from_file(credentials_path)

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5,  # a few, in case the most recent print(s) are "." (not yet reported)
    }
    url = FRED_OBSERVATIONS_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"FRED request failed: {e}")

    if "observations" not in data:
        raise RuntimeError(f"FRED error: {data.get('error_message', 'unknown error')}")

    for obs in data["observations"]:
        if obs["value"] != ".":
            return dt.date.fromisoformat(obs["date"]), float(obs["value"]) / 100.0

    raise RuntimeError(f"No valid observations returned for FRED series {series_id!r}")


def compute_sofr_mortgage_spread(forward_rates, a, theta_bar,
                                  credentials_path: str | Path | None = None,
                                  series_id: str = MORTGAGE30US_SERIES_ID,
                                  tenor_years: float = 10):
    """
    The current mortgage_spread to feed into
    term_structure_model.simulate_mortgage_rate_paths(): today's real
    30-year mortgage rate (from FRED) minus the model's own current
    SOFR-curve-implied ~tenor_years rate.

    forward_rates, a, theta_bar: the (calibrated) SOFR curve and model
        parameters -- same ones you'd pass to simulate_mortgage_rate_paths().
        The model's "current" ~tenor_years rate is
        ten_year_rate_from_state(forward_rates[0], theta_bar, a=a,
        tenor_years=tenor_years) -- i.e. the SAME approximate long-tenor
        rate simulate_mortgage_rate_paths() adds mortgage_spread on top
        of at every future simulated date, just evaluated at today's
        state (r0, theta_bar) instead of a simulated future one.

    Returns (spread, mortgage_rate, model_rate, mortgage_rate_date):
        spread            -- decimal (e.g. 0.025 for 250bp), ready for
                              simulate_mortgage_rate_paths()'s
                              mortgage_spread argument
        mortgage_rate     -- the FRED rate used, decimal
        model_rate        -- the model's current ~tenor_years rate, decimal
        mortgage_rate_date -- the FRED observation's date
    """
    mortgage_rate_date, mortgage_rate = fetch_current_mortgage_rate(credentials_path, series_id)
    model_rate = tsm.ten_year_rate_from_state(forward_rates[0], theta_bar, a=a, tenor_years=tenor_years)
    spread = mortgage_rate - model_rate
    return spread, mortgage_rate, model_rate, mortgage_rate_date
