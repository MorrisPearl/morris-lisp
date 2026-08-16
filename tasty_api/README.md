# CME Futures Options & Relative Value Viewer

A desktop app (PyQt6) with two tabs, backed entirely by real tastytrade
broker data (no free/unofficial scraping involved):

1. **Options** — lists options on CME futures for a selected product, in
   a sortable/filterable table.
2. **Futures Relative Value** — pulls the selected product's futures term
   structure and flags contract months that look rich or cheap, plus a
   calendar-spread breakdown of implied carry.

## Supported products

| Code | Product |
|---|---|
| CL | WTI Crude Oil |
| MCL | Micro WTI Crude Oil |
| ES | E-mini S&P 500 |
| NQ | E-mini Nasdaq-100 |
| SR3 | Three-Month SOFR |
| ZN | 10-Year T-Note |
| ZQ | 30-Day Fed Funds |

Adding another product later is a one-line change in `tastytrade_source.py`
(the `PRODUCTS` dict) — everything else (chain parsing, delivery-month
grouping, near-the-money filtering) is generic and doesn't need to know
about individual products.

## Setting up tastytrade access

The credentials bar at the top of the window (shared by both tabs) points
at a small local JSON file holding your tastytrade API credentials.

**One-time setup:**

1. Log into tastytrade and open
   [OAuth Applications](https://my.tastytrade.com/app.html#/manage/api-access/oauth-applications).
2. Create a new OAuth application. Check the scopes you want (read-only
   market data access is enough for this app), add `http://localhost:8000`
   as a valid redirect/callback URL, and create it. **Save the client
   secret it shows you — it's only displayed once.**
3. On the same page, open your new app's **Manage > Create Grant** to
   generate a **refresh token**. Save that too.
4. Copy `tastytrade_credentials.example.json` to `tastytrade_credentials.json`
   (or any path you like) and fill in both values:
   ```json
   {
     "client_secret": "...",
     "refresh_token": "...",
     "is_test": false
   }
   ```
   Refresh tokens don't expire and the SDK auto-renews the short-lived
   session token behind the scenes, so this is a one-time setup — no
   password is ever stored.

   This app doesn't use it, but this same file can also hold a
   `"fred_api_key"` entry — the `../lisp_interp/lisp_interpreter.py`
   Lisp interpreter's `fred-series` builtin will read it from here, so
   both tastytrade and FRED credentials can live in one file.
5. In the app, point the "tastytrade credentials file" field at that JSON
   file (or leave the default if you named it `tastytrade_credentials.json`
   in the same folder as the app) and click **Test Connection** to confirm
   it works before fetching data.

If "Test Connection" fails, run `python test_tastytrade_connection.py
[path/to/credentials.json]` from the command line — it's a standalone
diagnostic (no GUI) that prints your installed tastytrade SDK version,
does a shape check on your credential strings without ever printing the
actual secrets, and gives a specific troubleshooting checklist for
common OAuth failures like `invalid_grant`.

## Why it's slower than a typical free ticker app

Real bid/ask/last prices come from a one-shot REST call, but implied
volatility is only available from tastytrade's live Greeks stream (a
websocket subscription, one per contract) — there's no snapshot IV field
in their REST market-data endpoint. Subscribing to every strike across
every expiration would be slow and could hit subscription limits, so
each expiration is trimmed to the **N strikes nearest the underlying's
price** first (adjustable via "Max strikes near money" on the Options
tab, default 15 → up to 30 contracts per expiration counting both calls
and puts). The "Greeks stream timeout" caps how long it waits to collect
IV before giving up on stragglers — illiquid strikes may end up with a
blank Implied Volatility if tastytrade hasn't published a recent Greeks
snapshot for them.

## Options tab columns

| Column | Meaning |
|---|---|
| Symbol | The option's real tastytrade/CME contract symbol |
| Data Source | Always "tastytrade (real chain, streamed IV)" |
| Type | Call or Put |
| Strike | Strike price |
| Expiration Date | When the option expires |
| Delivery Month | Delivery month of the **underlying future** |
| Underlying Future | The specific futures contract ticker |
| Last Price | Most recent trade/close price (not real-time) |
| Implied Volatility | Implied volatility of the option, from the Greeks stream |
| Volume / Open Interest | Rough liquidity gauge (may be blank — tastytrade doesn't report open interest for every product) |

## Futures Relative Value tab

| Table | What it shows |
|---|---|
| Per-contract rich/cheap | Fits a smooth curve (polynomial) to ln(price) vs. days-to-delivery across all listed months for the selected product, then flags each contract's deviation from that curve as Rich / Cheap / Fair. This needs no rate assumptions and is generic — it works the same way for a commodity, equity-index, or rates curve. |
| Calendar-spread carry | For each pair of adjacent contract months, computes the **implied annualized carry rate** `c = ln(F2/F1)/(T2−T1)` directly from prices, then — using your editable funding-rate (r) and storage-cost (u) assumptions — backs out an **implied net storage cost** (`c − r`) and **implied convenience yield** (`r + u − c`). |

Rich/Cheap rows are color-highlighted (soft red = Rich, soft green =
Cheap). The funding rate, storage cost, and rich/cheap threshold are all
editable and recompute instantly — no need to refetch data when you tweak
them.

**Storage cost only means something literal for CL/MCL.** For the
financial products (ES, NQ, ZN, SR3, ZQ) there's no physical storage, so
the storage-cost/convenience-yield decomposition doesn't map to anything
real — the underlying *implied carry rate* is still a valid, meaningful
number for all products, but treat the storage/convenience-yield split as
illustrative rather than literal outside of CL/MCL. The per-contract
rich/cheap curve-fit table is the more broadly meaningful of the two views
for the financial products.

### The math, in full

Cost-of-carry for a commodity forward curve:

```
F2 = F1 * exp[(r + u − y) * (T2 − T1)]
```

- `r` = funding/risk-free rate (your input)
- `u` = storage cost (your input — not published anywhere, so this is a
  rough assumption you control)
- `y` = convenience yield (not directly observable)

Rearranged, per adjacent pair of contracts:

```
c  = ln(F2/F1) / (T2−T1)      <- observed from market prices
u−y = c − r                    <- "implied net storage cost", given your r
 y  = r + u − c                <- "implied convenience yield", given your r AND u
```

You cannot separate storage cost from convenience yield using price data
alone — that split fundamentally requires an assumption about one of them
(here, your `u` input). That's a property of the model, not a limitation
of this app specifically.

## Install & run

```bash
pip install -r requirements.txt
python main.py
```

Requires Python 3.10+ and a tastytrade account (see setup above).

## Important limitations

- **Implied volatility can be blank** for strikes that haven't published a
  recent Greeks snapshot within the stream timeout — this is more likely
  for far-dated or deep out-of-the-money strikes.
- The chain includes both standard monthly options and any weekly/serial
  option series a product lists, all grouped under their shared delivery
  month.
- Field names come from the community `tastytrade` Python SDK as
  documented in mid-2026; if tastytrade changes their data model, the
  error message in the status bar will say so explicitly rather than
  silently returning wrong data. `tastytrade_source.py` includes a
  compatibility shim (`_maybe_await`) that works with both the pre-v12
  (sync) and v12+ (async-only) generations of the SDK automatically.
- Only near-the-money strikes are fetched by default (see "Max strikes
  near money") — this is intentionally not the full chain, to keep fetch
  times reasonable given the per-contract streaming cost of IV.
- **Delayed / last-trade data, not real-time** — by design, per the
  original request this was built for.
- **The relative-value model is simplified and single-factor.** Real
  curves have seasonal effects (commodities), dividend/coupon effects
  (equities/rates), and carry isn't usually constant across maturities
  the way this model assumes. Rich/Cheap flags are a starting point for
  further research, not a trading signal by themselves.
- This tool is for research/informational purposes only — it is not
  financial advice, and nothing here should be the sole basis for a
  trading decision. Options and futures trading carries substantial risk.

## Troubleshooting

- "tastytrade not installed": run `pip install -r requirements.txt`.
- "Credentials file not found" / "missing client_secret": double-check
  the path in the credentials bar and that your JSON file matches
  `tastytrade_credentials.example.json`'s format.
- Connection test fails with `invalid_grant`/`Invalid JWT`: run
  `python test_tastytrade_connection.py` for a detailed diagnostic —
  usually a truncated/mangled refresh token, mismatched OAuth
  application, or a regenerated client secret invalidating old grants.
- "object list can't be used in await expression" (or similar):
  version mismatch between the installed SDK and what this app expects —
  should now be handled automatically by the compatibility shim, but if
  you still see it, run `pip install --upgrade tastytrade` and try again.
- Fetch is slow or times out: lower "Months ahead" and/or "Max strikes
  near money", or raise the Greeks stream timeout.
- No data for a product on the Relative Value tab: some products only
  list quarterly contract months (e.g. ES, NQ, ZN) rather than every
  calendar month — guessed symbols for non-existent months are silently
  skipped, this is expected.
