; mortgage_amortization_example.lsp
;
; A corrected, working version of a hand-drafted example: builds a
; monthly mortgage amortization table (balance/principal/interest) using
; column_engine.lsp's defstruct-based column engine. Run it with:
;   python3 lisp_interpreter.py mortgage_amortization_example.lsp
; or from the GUI/REPL:
;   (load "mortgage_amortization_example.lsp")
;
; Fixed, relative to the original sketch this is based on: a stray
; duplicate `define`/missing paren around mortgage_initial_balance, a
; mortgage_initial-balance/mortgage_initial_balance typo, and (the
; important one) value_calculation now always being a per-row FORMULA --
; defcolumn quotes it for you, so it can't accidentally be evaluated once
; up front instead of once per row.

(load "column_engine.lsp")

(define mortgage_interest_rate 6.00)               ; annual, percent
(define periodic_mortgage_interest_rate (/ mortgage_interest_rate 1200.0))
(define mortgage_term 360)                         ; months
(define mortgage_initial_balance 100000.0)

(define d_factor (pow (+ periodic_mortgage_interest_rate 1.0) mortgage_term))
(define mortgage_monthly_payment
  (* mortgage_initial_balance
     (/ (* periodic_mortgage_interest_rate d_factor) (- d_factor 1.0))))

(defcolumn balance_column
  :name "balance"
  :after ()
  :initial_value mortgage_initial_balance
  :value_calculation (- (* (lag balance 1) (+ 1 periodic_mortgage_interest_rate))
                        mortgage_monthly_payment))

(defcolumn principal_column
  :name "principal"
  :after balance_column
  :initial_value 0
  :value_calculation (- (lag balance 1) balance))

(defcolumn interest_column
  :name "interest"
  :after principal_column
  :initial_value 0
  :value_calculation (* (lag balance 1) periodic_mortgage_interest_rate))

(calculate-all *columns* (+ mortgage_term 1))
