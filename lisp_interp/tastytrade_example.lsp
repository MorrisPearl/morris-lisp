; ---------------------------------------------------------------------
; tastytrade example: retrieve and print real broker data (futures curve,
; futures/equity option chains, and rich/cheap curve analysis) via the
; tastytrade-* functions -- the full functionality of the tasty_api/
; desktop app, as plain builtins. Needs the `tastytrade` package
; (pip install tastytrade), a tastytrade account, and a local
; credentials JSON file -- see tasty_api/README.md for the one-time
; OAuth setup. The same credentials file works for tasty_api and this
; interpreter.
;
; Exercises all seven tastytrade-* builtins.
; ---------------------------------------------------------------------

; A small helper to print a Lisp list, one item per line -- this Lisp
; has no built-in loop construct, so iteration is just ordinary
; recursion.
(define (print-each lst)
  (if (null? lst)
      #t
      (begin
        (display "  ") (display (car lst)) (newline)
        (print-each (cdr lst)))))

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

; --- 4. tastytrade-option-chain, fast path (include-iv? = #f): CL
;        options over the next 2 delivery months, 5 strikes nearest the
;        money per expiration -- skipping the Greeks stream, so this
;        returns quickly ---
(define chain (tastytrade-option-chain creds "CL" 2 5 #f))
(display "CL option chain, no IV (") (display (length chain)) (display " contracts):") (newline)
(display "  (symbol type strike expiration days-to-expiration delivery-month underlying price iv volume oi)") (newline)
(print-each chain)
(newline)

; --- 5. tastytrade-option-chain, with implied volatility (include-iv? =
;        #t, the default): kept to a small chain (1 month, 3 strikes) so
;        the Greeks stream finishes quickly ---
(define chain-iv (tastytrade-option-chain creds "CL" 1 3 #t 20.0))
(display "CL option chain, with IV (") (display (length chain-iv)) (display " contracts):") (newline)
(print-each chain-iv)
(newline)

; --- 6. tastytrade-option-chain on an equity: any symbol that isn't a
;        futures root ("/..." or a known short code like "CL") is
;        fetched as an equity option chain automatically, no separate
;        function or symbol translation needed. For equities,
;        delivery-month is always '() (there's no separate delivery
;        month the way there is for a futures option) and underlying
;        is just the equity symbol itself; n-months limits results to
;        expirations within that many months from today. ---
(define aapl-chain (tastytrade-option-chain creds "AAPL" 2 5 #f))
(display "AAPL option chain, no IV (") (display (length aapl-chain)) (display " contracts):") (newline)
(print-each aapl-chain)
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
