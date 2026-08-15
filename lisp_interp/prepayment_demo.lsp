; ---------------------------------------------------------------------
; End-to-end demo: load a pool-level prepayment dataset, suggest knots,
; fit a spline-logistic model with multiple predictors (one categorical),
; evaluate on held-out data, and chart the fitted curve.
; ---------------------------------------------------------------------

(define d (load-csv "synthetic_mbs_pools.csv"))
(define headers (car d))
(define cols (cdr d))
(display "Columns: ") (display headers) (newline)

(define incentive (list-ref cols 10))   ; rate_incentive_pct
(define wala (list-ref cols 3))         ; wala_months
(define purpose (list-ref cols 8))      ; purpose_refi (0/1)
(define cpr (list-ref cols 11))         ; cpr (target, in [0,1])

(display "n = ") (display (vector-length cpr)) (newline)

; --- suggest knot locations for the refi-incentive S-curve ---
(define suggested (suggest-knots incentive cpr 15 4))
(display "Suggested incentive knots: ") (display suggested) (newline)

; --- train/test split (shuffle then take/drop) ---
(define shuffled (vectors-shuffle (list incentive wala purpose cpr) 7))
(define s-incentive (list-ref shuffled 0))
(define s-wala (list-ref shuffled 1))
(define s-purpose (list-ref shuffled 2))
(define s-cpr (list-ref shuffled 3))

(define n-train (floor (* (vector-length s-cpr) 0.7)))
(define train-incentive (vector-take s-incentive n-train))
(define train-wala (vector-take s-wala n-train))
(define train-purpose (vector-take s-purpose n-train))
(define train-cpr (vector-take s-cpr n-train))
(define test-incentive (vector-drop s-incentive n-train))
(define test-wala (vector-drop s-wala n-train))
(define test-purpose (vector-drop s-purpose n-train))
(define test-cpr (vector-drop s-cpr n-train))

; --- fit: incentive (spline, suggested knots), wala (spline, 3 knots),
;     purpose (categorical), logistic link since CPR is in [0,1] ---
(define m (spline-regression (list train-incentive train-wala train-purpose)
                              train-cpr
                              (list suggested 3 (quote categorical))
                              #t))
(display (model-report m)) (newline)

(display "Held-out evaluation:") (newline)
(display (model-evaluate m (list test-incentive test-wala test-purpose) test-cpr)) (newline)

; --- predicted CPR at a few illustrative incentive levels (WALA=24, purchase pool) ---
(display "Predicted CPR, incentive=-1.0: ") (display (model-predict m (list -1.0 24 0))) (newline)
(display "Predicted CPR, incentive= 0.0: ") (display (model-predict m (list 0.0 24 0))) (newline)
(display "Predicted CPR, incentive= 1.0: ") (display (model-predict m (list 1.0 24 0))) (newline)
(display "Predicted CPR, incentive= 2.0: ") (display (model-predict m (list 2.0 24 0))) (newline)

; --- chart: CPR vs rate incentive, with the fitted regression curve ---
(plot-xy-regression incentive cpr "CPR" "logistic")
(save-chart "prepayment_incentive_curve.png")
(display "Saved prepayment_incentive_curve.png") (newline)
