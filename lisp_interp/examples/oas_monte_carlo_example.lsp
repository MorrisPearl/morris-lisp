; oas_monte_carlo_example.lsp
;
; Worked, end-to-end example of oas_monte_carlo.lsp's pipeline:
;   1. a curve of forward rates, from par yields.
;   2. (illustrated, not run against live data here -- see
;      oas_monte_carlo.lsp's annualized-realized-vol docstring) a
;      historical-vol cross-check for the sigma1/sigma2 used below.
;   3. simulate Monte Carlo short-rate / mortgage-rate paths off that
;      curve (simulate-mortgage-rate-paths).
;   4. generate one pass-through mortgage cashflow vector per path.
;   5. solve for the OAS that reproduces an assumed market price.
;
; All the curve numbers below are ILLUSTRATIVE (made up, in the same spirit as
; term_structure_model.py's own __main__ demo) -- replace with real data (the
; Treasury's own curve: treasury-par-curve; sigma1/sigma2 from options:
; calibrate-rate-model, see oas_monte_carlo_live_example.lsp; a real MBS
; market price) for an actual analysis. sigma1/sigma2 here are simply assumed,
; not fit to option prices, to keep this example runnable with no network
; access and no credentials file.
;
; Run it from the examples directory with:
;   python3 ../lisp_interpreter.py oas_monte_carlo_example.lsp

(load "oas_monte_carlo.lsp")
(load "yield_curves.lsp")

; --- 1. curve: from par yields to a month-by-month forward curve ---------

; The same illustrative Treasury par curve term_structure_model.py's own
; __main__ demo uses (maturities in years, yields as decimals).
(define zeros (par-curve-zeros (vector 0.25 0.5 1 2 5 10 30)
                               (vector 0.043 0.041 0.039 0.038 0.040 0.043 0.046)))
(define forward-rates (table-column (curve-forward-rates zeros) "forward"))

(display "Forward rate at month 1: ")
(display (vector-ref forward-rates 0)) (newline)
(display "Forward rate at month 60: ")
(display (vector-ref forward-rates 59)) (newline)
(display "Forward rate at month 360 (the long end): ")
(display (vector-ref forward-rates 359)) (newline)

; --- 2. historical-vol cross-check (illustrated, not fetched here) -------

; See oas_monte_carlo.lsp's annualized-realized-vol docstring for how to
; run this for real against FRED's "DFF" and "DGS10". Here we just
; assume sigma1/sigma2 outright, since this example has no network
; access.
(define sigma1 0.010)    ; short-rate factor vol, decimal annualized
(define sigma2 0.006)    ; mean-reversion-level factor vol, decimal annualized

; --- 3. simulate Monte Carlo mortgage-rate paths --------------------------

(define n-paths 200)          ; kept small so this example runs quickly
(define horizon-years 30)
(define mortgage-spread 0.020)  ; 200bp over the model's 10-year par yield

(define sim (simulate-mortgage-rate-paths
              forward-rates sigma1 sigma2 horizon-years n-paths
              mortgage-spread :seed 42))
(define short-rate-paths (second sim))
(define mortgage-paths (fourth sim))

(display "Simulated ") (display n-paths) (display " paths over ")
(display horizon-years) (display " years.") (newline)

; --- 4. per-path mortgage cashflows ---------------------------------------

(define initial-balance 300000.0)
(define note-rate-percent 6.00)     ; the loan's own fixed coupon, in percent points
(define n-months 360)
(define psa-speed 100)

; One cashflow vector per path -- prepayment speed on each path responds
; to that path's own simulated mortgage rate (mortgage-paths[i]).
(define path-cashflows
  (mortgage-cashflows-per-path initial-balance note-rate-percent n-months psa-speed mortgage-paths))

(display "Generated ") (display (length path-cashflows))
(display " per-path cashflow vectors, ") (display n-months) (display " months each.") (newline)

; --- 5. solve for the OAS matching an assumed market price ---------------

; An assumed market price (per 100 face, so scale the pass-through
; cashflows down by initial-balance/100 first) -- replace with a real
; observed MBS price for an actual analysis.
(define price-scale (/ 100.0 initial-balance))
(define scaled-path-cashflows (map (lambda (cf) (vector-mul cf price-scale)) path-cashflows))

(define assumed-market-price 98.50)   ; per 100 face

; scaled-path-cashflows[i] is paired against short-rate-paths[i] (same
; path order simulate-mortgage-rate-paths returned them in) --
; oas-model-price/oas-solve accept a LIST of per-path cashflow vectors
; for exactly this case (see oas_monte_carlo.lsp).
(define model-price-at-0-oas (oas-model-price scaled-path-cashflows short-rate-paths 0.0))
(define solved-oas (oas-solve scaled-path-cashflows short-rate-paths assumed-market-price))

(display "Model price at 0 OAS: ") (display model-price-at-0-oas) (newline)
(display "Assumed market price: ") (display assumed-market-price) (newline)
(display "Solved OAS (decimal): ") (display solved-oas) (newline)
(display "Solved OAS (bp): ") (display (* solved-oas 10000)) (newline)
