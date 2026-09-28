; sofr_floating_rate_example.lsp
;
; Fetches the current CME 3-Month SOFR (SR3) futures strip via tastytrade,
; bootstraps a 360-month curve of forward rates implied by those futures
; prices (sofr-forward-curve, which reuses term_structure/
; term_structure_model.py's bootstrap_sofr_curve() as-is -- see that
; function's docstring for the full methodology and its documented
; simplifications), and uses the resulting curve to drive a floating-rate
; note's coupon -- built on column_engine.lsp's defstruct-based column
; engine, the same way mortgage_amortization_example.lsp builds a fixed-
; rate amortization table.
;
; Needs the `tastytrade` package (pip install tastytrade), a tastytrade
; account, and a credentials JSON file -- see tasty_api/README.md for the
; one-time OAuth setup.
;
; USING THIS FOR A MORTGAGE PREPAYMENT MODEL INSTEAD: sofr-forward-rates
; (below) is exactly what you'd feed a prepayment model too -- a
; borrower's "rate incentive" to refinance is (their origination rate -
; the CURRENT market mortgage rate), and the current market mortgage rate
; can be estimated as sofr-forward-rates[period] + a spread (see
; term_structure/mortgage_spread.py, which estimates that spread
; empirically from FRED's MORTGAGE30US series -- fetch it once with
; fetch_current_mortgage_rate() there, or just assume a flat ~150-250bp
; spread over 1-month SOFR as a starting point). Once you have a
; per-period rate_incentive column, prepayment_demo.lsp already shows how
; to fit/use a spline-logistic CPR model from rate incentive (among other
; predictors) -- (model-predict that-model (list rate_incentive-vector
; ...)) gives a per-period prepayment speed, which would multiply into a
; column here the same way `interest`/`principal` do below, reducing
; `balance` by (scheduled principal + prepayment) each period instead of
; just scheduled principal.

(load "column_engine.lsp")

; --- 1. fetch the current SR3 strip and bootstrap the forward curve ---
(define sofr-curve-rows (tastytrade-futures-curve-rows creds "SR3" 40))
(define sofr-curve (sofr-forward-curve sofr-curve-rows))
(define sofr-months (car sofr-curve))
(define sofr-forward-rates (cdr sofr-curve))   ; (vector-ref sofr-forward-rates (- month 1))

(set! *column-number-format* "{:,.4f}")
(display "SOFR forward curve, first 12 months:") (newline)
(display-columns (list (cons "month" (vector-slice sofr-months 0 12))
                        (cons "sofr_1m" (vector-slice sofr-forward-rates 0 12))))
(newline)

; --- 2. a floating-rate note: coupon = SOFR(this period) + a fixed margin.
;     Bullet note (flat balance) for simplicity -- swap balance_column's
;     value_calculation for something like mortgage_amortization_
;     example.lsp's balance formula (referencing coupon_rate instead of a
;     fixed rate) to make it amortize instead. ---
(define note_initial_balance 100000.0)
(define note_term 60)             ; months (5-year FRN, for example)
(define coupon_margin 0.0150)     ; 150bp margin over 1-month SOFR

; sofr_1m: this column's value_calculation doesn't reference any OTHER
; column -- it just reads this period's already-bootstrapped forward
; rate off the vector fetched in step 1 -- but it fits into calculate-all
; exactly the same way any other column does: current-row is always
; bound while a value_calculation runs (see column_engine.lsp), so any
; precomputed series -- fetched, loaded from a file, whatever -- can be
; read off of it one row per period, index-aligned, and referenced by
; bare name (or lag) from other columns just like a calculated one.
(defcolumn sofr_1m_column
  :name "sofr_1m"
  :after ()
  :initial_value (vector-ref sofr-forward-rates 0)
  :value_calculation (vector-ref sofr-forward-rates (- current-row 1))
  :decimals 4)                      ; a rate, not a dollar amount -- see
                                     ; column_engine.lsp's `decimals` slot

(defcolumn coupon_rate_column
  :name "coupon_rate"
  :initial_value (+ (vector-ref sofr-forward-rates 0) coupon_margin)
  :value_calculation (+ sofr_1m coupon_margin)
  :decimals 4)

(defcolumn balance_column
  :name "balance"
  :initial_value note_initial_balance
  :value_calculation (lag balance 1))

(defcolumn interest_column
  :name "interest"
  :initial_value 0
  :value_calculation (* (lag balance 1) (/ coupon_rate 12.0)))

; No need to fiddle with *column-number-format* for this one -- balance/
; interest use the `decimals` slot's default (0, a dollar amount), and
; sofr_1m/coupon_rate each specify their own (4, above).
(calculate-all *columns* (+ note_term 1))
(write-csv "sofr_floating_rate_example.csv" *columns*)
(display "Wrote sofr_floating_rate_example.csv") (newline)
