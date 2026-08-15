#!/usr/bin/env python3
"""
test_tastytrade_connection.py
==============================
Small standalone script to debug the tastytrade connection/credentials
outside the full GUI app. Run it directly from the command line:

    python test_tastytrade_connection.py [path/to/credentials.json]

If no path is given, it defaults to tastytrade_credentials.json in the
current folder. This exercises the exact same `test_connection()` and
`make_session()` code the GUI's "Test Connection" button uses, and prints
extra diagnostics (installed tastytrade version, and whether it detected
the pre-v12 sync-style API or the v12+ async-only API) that are useful to
share if something still doesn't work.

This only needs `tastytrade` and `pandas` installed — it does NOT import
PyQt6, so it also works in a bare virtualenv if you want to isolate
whether a problem is in the tastytrade SDK layer vs. the GUI/threading
layer.
"""

import sys

try:
    import tastytrade_source as tt
except ImportError as e:
    print(f"Could not import tastytrade_source.py — run this from the app's folder. ({e})")
    sys.exit(1)


def main():
    creds_path = sys.argv[1] if len(sys.argv) > 1 else "tastytrade_credentials.json"

    print(f"tastytrade package available: {tt.TASTYTRADE_AVAILABLE}")
    if tt.TASTYTRADE_AVAILABLE:
        print(f"tastytrade package version:   {tt.TASTYTRADE_VERSION}")
    print(f"Credentials file:              {creds_path}")
    print("-" * 60)

    if not tt.TASTYTRADE_AVAILABLE:
        print("Install it with:  pip install tastytrade")
        sys.exit(1)

    try:
        creds = tt.load_credentials(creds_path)
        print(f"Loaded credentials OK (is_test={creds.get('is_test', False)}).")
    except tt.CredentialsError as e:
        print(f"FAILED to load credentials: {e}")
        sys.exit(1)

    # Shape-only sanity check on the secrets — never prints the actual
    # values, just length + whether the refresh token has the 3-segment
    # dot-separated structure tastytrade's "Invalid JWT" error suggests
    # it expects. This catches truncated/mangled copy-pastes early.
    secret, refresh = creds["client_secret"], creds["refresh_token"]
    print(f"client_secret:  length={len(secret)}")
    print(f"refresh_token:  length={len(refresh)}, looks-like-JWT={tt._looks_like_jwt(refresh)}")
    if not tt._looks_like_jwt(refresh):
        print(
            "  -> refresh_token doesn't look like a 3-segment JWT (header.payload.signature). "
            "This usually means it got truncated or mangled when copied — or the "
            "client_secret and refresh_token values got swapped in the JSON file. "
            "Worth re-copying it directly from a fresh 'Create Grant' before going further."
        )
    print("-" * 60)

    print("Attempting to connect and fetch account list...")
    try:
        message = tt.test_connection(creds_path)
        print(f"SUCCESS: {message}")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        err_text = str(e)
        if "await expression" in err_text:
            print(
                "\nThis means the installed tastytrade SDK's API shape differs "
                "from what this script expects — please share the version printed "
                "above."
            )
        elif "invalid_grant" in err_text or "Invalid JWT" in err_text:
            print(
                "\ntastytrade's OAuth server rejected the refresh_token itself "
                "(not a code bug on this end — the request reached tastytrade and "
                "got a structured error back). Likely causes, roughly in order of "
                "likelihood:\n"
                "  1. The refresh_token got truncated/mangled when copy-pasted into "
                "the JSON file (see the shape check above).\n"
                "  2. client_secret and refresh_token are from two DIFFERENT OAuth "
                "applications — the grant must be created under the same app whose "
                "client_secret you're using.\n"
                "  3. The client secret was regenerated after the grant was created, "
                "invalidating old grants.\n"
                "  4. is_test doesn't match where the grant was actually created "
                "(production vs. the sandbox/cert environment).\n"
                "Easiest fix: go back to My Profile > API > OAuth Applications, hit "
                "'Create Grant' again on the correct application, and paste the "
                "fresh refresh_token in (double-check no leading/trailing spaces or "
                "line breaks got included)."
            )
        sys.exit(1)

    print("\nTrying a small futures-price fetch (CL front month) via the raw SDK call...")
    try:
        import asyncio
        import datetime as _dt

        async def _quick_price_check():
            from tastytrade.market_data import get_market_data_by_type
            session = tt.make_session(creds_path)
            today = _dt.date.today()
            code = tt.MONTH_CODES[today.month]
            symbol = f"/CL{code}{today.year % 10}"
            raw = get_market_data_by_type(session, futures=[symbol])
            data = await tt._maybe_await(raw)
            return symbol, data

        symbol, data = asyncio.run(_quick_price_check())
        if data:
            price = tt._pick_price(data[0])
            print(f"{symbol}: last/close price = {price}")
        else:
            print(f"{symbol}: no data returned (contract may not be listed under this guessed symbol).")
    except Exception as e:
        print(f"Futures price fetch FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
