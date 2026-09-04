; oas_monte_carlo_example.lsp
;
; Worked, end-to-end example of oas_monte_carlo.lsp's pipeline:
;   1. bootstrap a near-term SOFR curve, then extend its long end with a
;      Treasury curve instead of leaving it flat-extrapolated.
;   2. (illustrated, not run against live data here -- see
;      oas_monte_carlo.lsp's annualized-realized-vol docstring) a
;      historical-vol cross-check for the sigma1/sigma2 used below.
;   3. simulate Monte Carlo short-rate / mortgage-rate paths off that
;      extended curve.
;   4. generate one pass-through mortgage cashflow vector per path.
;   5. solve for the OAS that reproduces an assumed market price.
;
; All the curve/option numbers below are ILLUSTRATIVE (made up, in the
; same spirit as term_structure_model.py's own __main__ demo) -- replace
; with real data (sofr-calibration-data + sofr-calibrate-model for
; sigma1/sigma2, a real FRED Treasury curve, a real MBS market price) for
; an actual analysis. sigma1/sigma2 here are simply assumed, not fit to
; option prices, to keep this example runnable with no network access and
; no credentials file.
;
; Run with:
;   python3 lisp_interpreter.py oas_monte_carlo_example.lsp

(load "oas_monte_carlo.lsp")

; --- 1. curve: bootstrap the near term, extend the long end --------------

; A handful of illustrative SR3 quarterly futures rates -- the "real"
; (non-extrapolated) part of the curve, out to 2 years.
(define sofr-futures-rows
  (list (list "F1" 0 3 0.045)
        (list "F2" 3 6 0.044)
        (list "F3" 6 12 0.043)
        (list "F4" 12 18 0.042)
        (list "F5" 18 24 0.041)))
(define curve-real-months 24)

(define curve (sofr-bootstrap-curve sofr-futures-rows))
(define forward-rates (cdr curve))

; The same illustrative Treasury par curve term_structure_model.py's own
; __main__ demo uses, decimals.
(define extended-forward-rates
  (sofr-extend-curve-with-treasury forward-rates curve-real-months
                                    0.043 0.041 0.039 0.038 0.040 0.043 0.046))

(display "Forward rate at month 24 (last real SOFR month): ")
(display (vector-ref extended-forward-rates 23)) (newline)
(display "Forward rate at month 30 (blended toward Treasury shape): ")
(display (vector-ref extended-forward-rates 29)) (newline)
(display "Forward rate at month 360 (Treasury long end, not flat): ")
(display (vector-ref extended-forward-rates 359)) (newline)

; --- 2. historical-vol cross-check (illustrated, not fetched here) -------

; See oas_monte_carlo.lsp's annualized-realized-vol docstring for how to
; run this for real against fred-series "DFF"/"DGS10". Here we just
; assume sigma1/sigma2 outright, since this example has no network
; access.
(define sigma1 0.010)    ; short-rate factor vol, decimal annualized
(define sigma2 0.006)    ; mean-reversion-level factor vol, decimal annualized

; --- 3. simulate Monte Carlo mortgage-rate paths --------------------------

(define n-paths 200)          ; kept small so this example runs quickly
(define horizon-years 30)
(define mortgage-spread 0.020)  ; 200bp over the model's 10-year proxy rate

(define sim (sofr-simulate-mortgage-rate-paths
              extended-forward-rates sigma1 sigma2 horizon-years n-paths
              mortgage-spread 42))
(define short-rate-paths (car (cdr sim)))
(define mortgage-paths (car (cdr (cdr (cdr sim)))))

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
(define scaled-path-cashflows (map (lambda (cf) (vector-scale cf price-scale)) path-cashflows))

(define assumed-market-price 98.50)   ; per 100 face

; scaled-path-cashflows[i] is paired against short-rate-paths[i] (same
; path order sofr-simulate-mortgage-rate-paths returned them in) --
; oas-model-price/oas-solve accept a LIST of per-path cashflow vectors
; for exactly this case (see oas_monte_carlo.lsp).
(define model-price-at-0-oas (oas-model-price scaled-path-cashflows short-rate-paths 0.0))
(define solved-oas (oas-solve scaled-path-cashflows short-rate-paths assumed-market-price))

(display "Model price at 0 OAS: ") (display model-price-at-0-oas) (newline)
(display "Assumed market price: ") (display assumed-market-price) (newline)
(display "Solved OAS (decimal): ") (display solved-oas) (newline)
(display "Solved OAS (bp): ") (display (* solved-oas 10000)) (newline)
