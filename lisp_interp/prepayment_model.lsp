; prepayment_model.lsp
;
; A simple, standard PSA-style (Public Securities Association) mortgage
; prepayment model: a "seasoning ramp" -- CPR (Conditional Prepayment
; Rate, annualized) rises linearly from 0% at loan age (WALA) 0 to 6% at
; WALA 30 months, then holds flat at 6% -- scaled by a psa-speed
; multiplier (100 = standard "100% PSA"; 200 = twice as fast; 0 = no
; prepayments at all), the market-standard way to quote a prepayment
; assumption. Optionally bumped up by a simple refinancing-incentive
; term: the further a borrower's rate is above the CURRENT market rate,
; the faster prepayments run.
;
; This is NOT fit to data -- see prepayment_demo.lsp for a regression-
; based CPR model instead, fit to synthetic_mbs_pools.csv. This is the
; textbook PSA curve, with a handful of tunable globals, meant to be
; simple to reason about and adjust -- change the globals below, or
; redefine psa-base-cpr/incentive-bump-cpr outright, to try a different
; shape.
;
; Usage (see mortgage_amortization_example.lsp for a worked example):
;   (smm-from-cpr (cpr wala psa_speed))                     -- pure aging
;   (smm-from-cpr (cpr wala psa_speed :incentive_points x)) -- + refi bump

; --- 1. base seasoning ramp (100% PSA) -----------------------------------

(define psa-ramp-months 30)          ; months to reach full seasoning
(define psa-ultimate-cpr 0.06)       ; CPR (decimal) once fully seasoned

; wala: months since origination (0, 1, 2, ...).
(define (psa-base-cpr wala)
  (* psa-ultimate-cpr (/ (min wala psa-ramp-months) psa-ramp-months)))

; --- 2. optional refinancing-incentive bump ------------------------------

; How much extra ANNUALIZED CPR to add per percentage point of positive
; rate incentive (the borrower's own coupon minus the current market
; rate, in points -- e.g. 1.5 for a 1.5-point incentive), and the most it
; can ever add. Deliberately simple/tunable, not fit to data -- a real
; refi-incentive curve is S-shaped (see prepayment_demo.lsp's
; spline-regression fit for that), this is a flat-rate approximation of
; the same idea.
(define incentive-cpr-per-point 0.02)   ; +2 CPR per 1.00 point of incentive
(define incentive-cpr-cap 0.30)         ; never add more than +30 CPR

(define (incentive-bump-cpr incentive_points)
  (min incentive-cpr-cap
       (* incentive-cpr-per-point (max 0 incentive_points))))

; --- 3. combined CPR / SMM ------------------------------------------------

(define (cpr wala psa_speed &key (incentive_points 0))
  (min 0.99 (+ (* (psa-base-cpr wala) (/ psa_speed 100.0))
               (incentive-bump-cpr incentive_points))))

; CPR (annualized) -> SMM (Single Monthly Mortality: the fraction of the
; balance REMAINING after scheduled principal that prepays this month):
;   SMM = 1 - (1 - CPR)^(1/12)
(define (smm-from-cpr cpr_value)
  (- 1.0 (expt (- 1.0 cpr_value) (/ 1.0 12.0))))
