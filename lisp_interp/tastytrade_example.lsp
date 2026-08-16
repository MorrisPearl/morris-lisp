; ---------------------------------------------------------------------
; tastytrade example: retrieve and print real broker data (futures curve
; and futures-option chain) via the tastytrade-* functions. Needs the
; `tastytrade` package (pip install tastytrade), a tastytrade account,
; and a local credentials JSON file -- see tasty_api/README.md for the
; one-time OAuth setup. The same credentials file works for tasty_api
; and this interpreter.
;
; Exercises all four tastytrade-* builtins.
; ---------------------------------------------------------------------

(define creds "tastytrade_credentials.json")   ; edit to your credentials file's path

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
(display "  (symbol type strike expiration delivery-month underlying price iv volume oi)") (newline)
(print-each chain)
(newline)

; --- 5. tastytrade-option-chain, with implied volatility (include-iv? =
;        #t, the default): kept to a small chain (1 month, 3 strikes) so
;        the Greeks stream finishes quickly ---
(define chain-iv (tastytrade-option-chain creds "CL" 1 3 #t 20.0))
(display "CL option chain, with IV (") (display (length chain-iv)) (display " contracts):") (newline)
(print-each chain-iv)
(newline)
