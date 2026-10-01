; ---------------------------------------------------------------------
; tastytrade example: retrieve and print real broker data (quotes, a
; futures curve, futures/equity option chains, market metrics, and
; rich/cheap curve analysis) via the tastytrade-* functions. Needs the
; `tastytrade` package (pip install tastytrade), a tastytrade account, and
; a local credentials JSON file -- see tasty_api/README.md for the
; one-time OAuth setup. The same credentials file works for tasty_api and
; this interpreter. creds is set to its path in init.lsp.
;
; Exercises all ten tastytrade-* builtins.
; ---------------------------------------------------------------------

; A small helper to print a Lisp list, one item per line.
(define (print-each lst)
  (dolist (item lst)
    (display "  ") (display item) (newline)))

; --- 1. tastytrade-products: which product codes are supported ---
(display "Supported products:") (newline)
(print-each (tastytrade-products))
(newline)

; --- 2. tastytrade-test-connection: confirm the credentials work before
;        spending time on real data fetches ---
(display "Connection test: ") (display (tastytrade-test-connection creds)) (newline)
(newline)

; --- 3. tastytrade-futures-curve: WTI Crude Oil (CL) futures term
;        structure, next 6 contract months ---
(define curve (tastytrade-futures-curve creds "CL" 6))
(define curve-dates (car curve))
(define curve-prices (cdr curve))

(define (print-curve dates prices i n)
  (if (< i n)
      (begin
        (display "  ") (display (vector-ref dates i))
        (display "  ") (display (vector-ref prices i))
        (newline)
        (print-curve dates prices (+ i 1) n))
      #t))

(display "CL futures curve (") (display (vector-length curve-dates)) (display " months):") (newline)
(print-curve curve-dates curve-prices 0 (vector-length curve-dates))
(newline)

; --- 4. tastytrade-option-chain: CL options over the next 2 delivery
;        months, 5 strikes nearest the money per expiration, with bids,
;        asks, implied volatility, and delta ---
(define chain (tastytrade-option-chain creds "CL" 2 5))
(display "CL option chain (") (display (table-row-count chain)) (display " contracts):") (newline)
(define chain-formats '(("strike" ",.2f") ("underlying-price" ",.2f") ("bid" ",.2f") ("ask" ",.2f")
                        ("mid" ",.3f") ("last-price" ",.2f") ("implied-volatility" ".1%")
                        ("delta" ".3f") ("volume" ",.0f") ("open-interest" ",.0f")))
(display-table chain chain-formats)
(newline)

; The chain is a table, so whole columns can be used at once -- here, the
; calls only -- or it can be looked at one option at a time, as rows:
(define calls (table-filter chain (= (table-column chain "type") "Call")))
(dolist (option (table-rows calls))
  (with-struct option
    (display (format "  {} strike {:,.2f}, {} days\n" symbol strike days-to-expiration))))
(newline)

; --- 5. tastytrade-quotes: the current bid and ask (and more) for any
;        symbols at all -- a stock, an index, an equity option (in OCC's
;        form: the root padded to six characters, YYMMDD, C or P, and the
;        strike times 1000), a future, and the first CL option in the
;        chain above ---
(define quotes (tastytrade-quotes creds (list "SPY" "SPX" "SPY   261218C00700000" "/CLZ6"
                                              (vector-ref (table-column chain "symbol") 0))))
(display "Quotes:") (newline)
(display-table (table-select quotes '("symbol" "instrument-type" "bid" "ask" "mid" "last"
                                      "implied-volatility" "delta"))
               '(("implied-volatility" ".1%") ("delta" ".3f")))
(newline)

; --- 6. tastytrade-option-chain on an equity: any symbol that isn't a
;        futures root ("/..." or a known short code like "CL") is
;        fetched as an equity option chain automatically, no separate
;        function or symbol translation needed. For equities,
;        delivery-month is always '() (there's no separate delivery
;        month the way there is for a futures option) and underlying
;        is just the equity symbol itself; n-months limits results to
;        expirations within that many months from today. ---
(define aapl-chain (tastytrade-option-chain creds "AAPL" 2 5))
(display "AAPL option chain (") (display (table-row-count aapl-chain)) (display " contracts):") (newline)
(display-table aapl-chain chain-formats)
(newline)

; --- 7. tastytrade-curve-fit: per-contract rich/cheap vs. a fitted
;        curve. Fetch the curve ROWS once (unlike plain
;        tastytrade-futures-curve, these also carry the futures symbol
;        and days-to-delivery that the analysis needs); tastytrade-curve-fit
;        itself does no networking, so re-running it with a different
;        threshold is instant. ---
(define curve-rows (tastytrade-futures-curve-rows creds "CL" 8))
(define fit (tastytrade-curve-fit curve-rows 0.75))
(display "CL curve-fit rich/cheap (threshold 0.75%):") (newline)
(display "  (delivery-month symbol days-to-delivery price fitted-price rich-cheap-pct signal)") (newline)
(print-each fit)
(newline)

; --- 8. tastytrade-leg-carry: pairwise (adjacent contract month)
;        implied cost-of-carry decomposition -- also pure, no
;        networking, reusing curve-rows from step 7. See the big
;        methodology comment at the top of tasty_api/relative_value.py
;        for what these numbers mean and their limits (the storage-cost/
;        convenience-yield split is only literal for a storable physical
;        commodity like CL; for financial futures read it as
;        illustrative, not a real estimate). ---
(define legs (tastytrade-leg-carry curve-rows 4.25 3.0 1.0))
(display "CL implied carry by leg (funding rate 4.25%, storage cost 3.0%):") (newline)
(display "  (near-month far-month near-price far-price days-between carry-rate-pct net-storage-pct convenience-yield-pct signal)") (newline)
(print-each legs)
(newline)

; --- 9. tastytrade-get and tastytrade-get-table: anything else the API
;        offers -- the list is at
;        https://developer.tastytrade.com/open-api-spec/ . Here, market
;        metrics (implied volatility rank, liquidity) for two ETFs, as a
;        table; and one instrument's description, as Lisp data (a hash
;        table). A symbol with a / in it goes in a list of path parts,
;        which are encoded for it. ---
(define metrics (tastytrade-get-table creds "/market-metrics" '(("symbols" . "SPY,QQQ"))))
(display "Market metrics:") (newline)
(display-table (table-select metrics '("symbol" "implied-volatility-index" "implied-volatility-index-rank"
                                       "liquidity-rating"))
               '(("implied-volatility-index" ".1%") ("implied-volatility-index-rank" ".1%")))
(define brk (tastytrade-get creds (list "instruments" "equities" "BRK/B")))
(display (format "BRK/B is {}\n" (hash-table-ref brk "description")))
