; sofr_monte_carlo_example.lsp
;
; End to end: fetch a SOFR futures curve AND a spread of SOFR futures
; OPTIONS via tastytrade (sofr-calibration-data), bootstrap the forward
; curve, CALIBRATE the two-factor model's mean-reversion speed (a) and
; both volatilities (sigma1, sigma2) against those real option prices
; (sofr-calibrate-model), then use the fitted parameters to generate a
; set of Monte Carlo interest-rate paths (sofr-simulate-rate-paths /
; sofr-simulate-mortgage-rate-paths) -- all of it reusing
; term_structure/term_structure_model.py and sofr_market_data.py as-is;
; see those files (and each builtin's own docstring in
; lisp_interpreter.py) for the full methodology and its documented
; simplifications.
;
; Needs the `tastytrade` package (pip install tastytrade), a tastytrade
; account, and a credentials JSON file -- see tasty_api/README.md.
;
; CALIBRATION IS SLOW: sofr-calibrate-model runs a Monte Carlo option
; pricer at every (a, sigma1, sigma2) combination in a shrinking grid
; search -- at the term_structure_model.py module's own defaults
; (n-paths 2000, n-grid 7, n-rounds 4) this took ten to twenty seconds
; against a real SR3 options snapshot when that code was written; it'll
; vary with how many options sofr-calibration-data selected. The
; calibration-n-paths/n-grid/n-rounds below are turned DOWN from those
; defaults for a quicker first run -- turn them back up for a more
; careful fit once you've confirmed everything runs.

(load "column_engine.lsp")
( define creds "/Users/morris/credentials.json" )

; --- 1. fetch the curve AND calibration options in one session ---------
(define calibration-data (sofr-calibration-data creds 40 8 3))
(define curve-futures-rows (car calibration-data))
(define options-rows (cdr calibration-data))

; --- 2. bootstrap the forward curve from the futures leg ----------------
(define sofr-curve (sofr-bootstrap-curve curve-futures-rows))
(define sofr-months (car sofr-curve))
(define sofr-forward-rates (cdr sofr-curve))

; How many months of sofr-forward-rates are the REAL (non-extrapolated)
; part of the curve -- the last SR3 contract's end_months. curve-futures-
; rows is (symbol start_months end_months rate); end_months is field 2.
(define (curve-real-months rows)
  (if (null? (cdr rows))
      (list-ref (car rows) 2)
      (max (list-ref (car rows) 2) (curve-real-months (cdr rows)))))
(define real-months (curve-real-months curve-futures-rows))

; --- 3. calibrate (a, theta_bar, sigma1, sigma2) against the options ----
(display "Calibrating against ") (display (length options-rows)) (display " options...") (newline)
(define calibration-n-paths 500)   ; turned down from the module default
(define calibration-n-grid 5)      ; (2000/7/4) for a quicker first run
(define calibration-n-rounds 3)
(define fit (sofr-calibrate-model sofr-forward-rates options-rows real-months
                                   calibration-n-paths 42
                                   calibration-n-grid calibration-n-rounds))
(define fitted-a (list-ref fit 0))
(define fitted-theta-bar (list-ref fit 1))
(define fitted-sigma1 (list-ref fit 2))
(define fitted-sigma2 (list-ref fit 3))
(define fitted-error (list-ref fit 4))
(display "a=") (display fitted-a)
(display "  theta_bar=") (display fitted-theta-bar)
(display "  sigma1=") (display fitted-sigma1)
(display "  sigma2=") (display fitted-sigma2)
(display "  total squared pricing error=") (display fitted-error)
(newline)

; --- 4. generate a set of Monte Carlo rate paths using the fitted params -
(define simulation-horizon-years 5)
(define n-scenario-paths 20)        ; how many scenarios to generate --
                                     ; independent of calibration-n-paths
                                     ; above (that's option-pricing
                                     ; accuracy during calibration; this
                                     ; is how many scenarios you get out)
(define mortgage-spread 0.0175)     ; 175bp -- see term_structure/
                                     ; mortgage_spread.py for a data-
                                     ; driven estimate instead of a guess

(define sim (sofr-simulate-mortgage-rate-paths
             sofr-forward-rates fitted-sigma1 fitted-sigma2
             simulation-horizon-years n-scenario-paths mortgage-spread
             42 fitted-a fitted-theta-bar))
(define sim-years (list-ref sim 0))
(define short-rate-paths (list-ref sim 1))
(define underlying-paths (list-ref sim 2))
(define mortgage-rate-paths (list-ref sim 3))

; --- 5. look at the results: a chart of a handful of paths, and the full
;     set written to CSV (one column per path -- see write-columns-csv;
;     column_engine.lsp's write-csv wraps this for column structs, but
;     these are plain vectors, so the builtin directly is simpler here) -
(define (numbered-name prefix i) (string-append prefix (number->string i)))
(define (path-columns paths prefix)
  (define (build i remaining)
    (if (null? remaining)
        '()
        (cons (list (numbered-name prefix i) (car remaining) 4)
              (build (+ i 1) (cdr remaining)))))
  (build 0 paths))

(write-columns-csv "sofr_monte_carlo_example.csv"
                    (cons (list "years" sim-years 2)
                          (path-columns mortgage-rate-paths "mortgage_path_")))
(display "Wrote sofr_monte_carlo_example.csv (years + ")
(display n-scenario-paths)
(display " simulated mortgage-rate paths)") (newline)

; Chart the first 5 short-rate paths against the first 5 mortgage-rate
; paths (all n-scenario-paths are in the CSV above; this is just a look).
(define (list-take lst n)
  (if (or (<= n 0) (null? lst))
      '()
      (cons (car lst) (list-take (cdr lst) (- n 1)))))

(plot-xy-full sim-years
              (append (list-take short-rate-paths 5) (list-take mortgage-rate-paths 5))
              (list "short-1" "short-2" "short-3" "short-4" "short-5"
                    "mtg-1" "mtg-2" "mtg-3" "mtg-4" "mtg-5")
              #t
              "Simulated SOFR short-rate and proxy mortgage-rate paths"
              #f)

; USING ONE PATH TO DRIVE MORTGAGE CASHFLOWS: sofr_floating_rate_example.
; lsp and mortgage_amortization_example.lsp both already show how to read
; a precomputed rate vector by row inside a column's value_calculation
; ((vector-ref some-rate-vector current-row), roughly) -- a simulated
; path here is just another such vector. Picking ONE path (e.g.
; (list-ref mortgage-rate-paths 0)) and feeding it into
; mortgage_amortization_example.lsp's rate_incentive_column in place of
; the deterministic sofr-forward-rates-derived market_rate turns that
; whole example into ONE Monte Carlo scenario; looping calculate-all over
; several paths (each with its own *columns*/registry -- see
; column_engine.lsp's caveats about reusing global state across runs) is
; how you'd get a full Monte Carlo DISTRIBUTION of cashflows, not just
; one path's -- left as the natural next step, not built out here.
