; ---------------------------------------------------------------------
; FRED example: retrieve and print economic data series from the Federal
; Reserve Bank of St. Louis (FRED). Needs a free API key -- get one at
; https://fred.stlouisfed.org/docs/api/api_key.html, then either:
;   - add it to your tastytrade credentials JSON file as "fred_api_key"
;     (see tasty_api/README.md) and pass that file's path below, as
;     shown -- the same file both APIs' credentials can live in, or
;   - pass a literal key string instead ("abc123...") , or
;   - set the FRED_API_KEY environment variable and delete the arg below.
;
; Exercises fred-series (the only FRED builtin) across its full argument
; range: series + key alone, and both accepted forms of an optional
; start-date/end-date range (LispDate values, and "YYYY-MM-DD" strings).
; ---------------------------------------------------------------------

(define api-key "/Users/morris/credentials.json")

; A small helper to print a (dates . values) series returned by
; fred-series, one observation per line -- this Lisp has no built-in
; loop construct, so iteration is just ordinary recursion.
(define (print-series dates values i n)
  (if (< i n)
      (begin
        (display "  ") (display (vector-ref dates i))
        (display "  ") (display (vector-ref values i))
        (newline)
        (print-series dates values (+ i 1) n))
      #t))

; --- 1. fetch a full series: US Real Gross Domestic Product ("GDP") ---
(define gdp (fred-series "GDP" api-key))
(define gdp-dates (car gdp))
(define gdp-values (cdr gdp))          ; NOT (car (cdr gdp)) -- (cdr gdp) IS
                                        ; the values vector already; fred-series
                                        ; returns a cons pair, not a 2-element list
(define gdp-n (vector-length gdp-values))   ; vector-length, not length -- these
                                             ; are vectors, not Lisp lists
(display "GDP: ") (display gdp-n) (display " quarterly observations") (newline)
(display "  first:  ") (display (vector-ref gdp-dates 0))
(display "  ") (display (vector-ref gdp-values 0)) (newline)
(display "  latest: ") (display (vector-ref gdp-dates (- gdp-n 1)))
(display "  ") (display (vector-ref gdp-values (- gdp-n 1))) (newline)
(newline)

; --- 2. a second series, restricted to a date range with an explicit
;        start-date/end-date, given as `date` values ---
(define unrate (fred-series "UNRATE" api-key (date 2020 1 1) (date 2020 12 31)))
(display "UNRATE, 2020 (civilian unemployment rate, %):") (newline)
(print-series (car unrate) (cdr unrate) 0 (vector-length (car unrate)))
(newline)

; --- 3. a third series, with the date range given as "YYYY-MM-DD"
;        strings instead -- both forms work interchangeably ---
(define fedfunds (fred-series "FEDFUNDS" api-key "2023-01-01" "2023-12-31"))
(display "FEDFUNDS, 2023 (effective federal funds rate, %):") (newline)
(print-series (car fedfunds) (cdr fedfunds) 0 (vector-length (car fedfunds)))
(newline)
