; sofr_floating_rate_example.lsp
;
; Fetches the current CME 3-Month SOFR (SR3) futures strip via tastytrade,
; bootstraps a 360-month curve of forward rates implied by those futures
; prices (sofr-forward-curve, which reuses term_structure/
; term_structure_model.py's bootstrap_sofr_curve() as-is -- see that
; function's docstring for the full methodology and its documented
; simplifications), and uses the resulting curve to drive a floating-rate
; note's coupon -- built on column_engine.lsp's defstruct-based column
; engine, where each column is a formula of the columns before it.
;
; Needs the `tastytrade` package (pip install tastytrade), a tastytrade
; account, and a credentials JSON file -- see tasty_api/README.md for the
; one-time OAuth setup.
;
; For mortgages, whose prepayments depend on rates, see the deal library
; (lisp_cmo_manual.md): its prepayment model, fitted to Freddie Mac's
; loans, is run on paths of rates that start on a curve like this one.

(load "column_engine.lsp")

; --- 1. fetch the current SR3 strip and bootstrap the forward curve ---
(define sofr-curve-rows (tastytrade-futures-curve-rows creds "SR3" 40))
(define sofr-curve (sofr-forward-curve sofr-curve-rows))
(define sofr-months (car sofr-curve))
(define sofr-forward-rates (cdr sofr-curve))   ; (vector-ref sofr-forward-rates (- month 1))

(display "SOFR forward curve, first 12 months:") (newline)
(display-table (make-table "month" (vector-slice sofr-months 0 12)
                           "sofr_1m" (vector-slice sofr-forward-rates 0 12))
               '(("sofr_1m" ".4f")))
(newline)

; --- 2. a floating-rate note: coupon = SOFR(this period) + a fixed margin.
;     Bullet note (flat balance) for simplicity -- give balance_column a
;     value_calculation that takes out principal each period to make it
;     amortize instead. ---
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

; balance/interest use the `decimals` slot's default (0, a dollar
; amount), and sofr_1m/coupon_rate each specify their own (4, above).
(calculate-all *columns* (+ note_term 1))
(write-csv "sofr_floating_rate_example.csv" *columns*)
(display "Wrote sofr_floating_rate_example.csv") (newline)
