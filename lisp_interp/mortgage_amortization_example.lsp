; mortgage_amortization_example.lsp
;
; A corrected, working version of a hand-drafted example: builds a
; monthly mortgage amortization table (balance/principal/interest) using
; column_engine.lsp's defstruct-based column engine, with prepayments
; (prepayment_model.lsp's PSA-style CPR curve) folded into the collateral
; cashflows. Run it with:
;   python3 lisp_interpreter.py mortgage_amortization_example.lsp
; or from the GUI/REPL:
;   (load "mortgage_amortization_example.lsp")
;

(load "column_engine.lsp")
(load "prepayment_model.lsp")

(define mortgage_interest_rate 6.00)               ; annual, percent
(define periodic_mortgage_interest_rate (/ mortgage_interest_rate 1200.0))
(define mortgage_term 360)                         ; months
(define mortgage_initial_balance 100000.0)

(define d_factor (pow (+ periodic_mortgage_interest_rate 1.0) mortgage_term))
(define mortgage_monthly_payment
  (* mortgage_initial_balance
     (/ (* periodic_mortgage_interest_rate d_factor) (- d_factor 1.0))))

; Prepayment speed, as a percentage of "100% PSA" -- see
; prepayment_model.lsp. 0 turns prepayments off entirely (collateral
; amortizes exactly on its original schedule, same as before this file
; had a prepayment_model.lsp column at all); try 150-300 to see how much
; faster (and shorter) the collateral's life gets.
(define psa_speed 150)

; The collateral's own P&I cashflow, WITH prepayments -- standard MBS
; waterfall order per period: interest, then SCHEDULED principal (off the
; ORIGINAL fixed payment -- never recalculated, same as before), then
; prepayment (SMM applied to whatever balance remains after scheduled
; principal), then the period's total principal and ending balance.
; `after` is left to default to the previous defcolumn (see
; column_engine.lsp) throughout, except the first column here, which
; roots the chain explicitly.

(defcolumn wala_column
  :name "wala"
  :after ()
  :initial_value 0
  :value_calculation current-row
  :visible #f)                      ; loan age in months -- bookkeeping only

(defcolumn interest_column
  :name "coll_interest"
  :initial_value 0
  :value_calculation (* (lag coll_balance 1) periodic_mortgage_interest_rate))

(defcolumn scheduled_principal_column
  :name "sched_principal"
  :initial_value 0
  :value_calculation (max 0 (min (- mortgage_monthly_payment coll_interest)
                                  (lag coll_balance 1)))
  :visible #f)                      ; scheduled-only paydown -- bookkeeping only

(defcolumn smm_column
  :name "smm"
  :initial_value 0.0
  :value_calculation (smm-from-cpr (cpr wala psa_speed)))

(defcolumn prepayment_column
  :name "prepayment"
  :initial_value 0
  :value_calculation (* smm (- (lag coll_balance 1) sched_principal)))

(defcolumn principal_column
  :name "coll_principal"
  :initial_value 0
  :value_calculation (min (lag coll_balance 1) (+ sched_principal prepayment)))

(defcolumn balance_column
  :name "coll_balance"
  :initial_value mortgage_initial_balance
  :value_calculation (max 0 (- (lag coll_balance 1) coll_principal)))

; We are going to model a simple A,B,C,Z deal!

(defcolumn cash
    :value_calculation (+ coll_interest coll_principal)
    )

(defcolumn int_a
    :value_calculation (min cash (* (lag bal_a 1) periodic_mortgage_interest_rate))
    )

(defcolumn cash
    :value_calculation (- cash int_a)
    )

(defcolumn int_b
    :value_calculation (min cash (* (lag bal_b 1) periodic_mortgage_interest_rate))
    )

(defcolumn cash
    :value_calculation (- cash int_b)
    )

(defcolumn int_c
    :value_calculation (min cash (* (lag bal_c 1) periodic_mortgage_interest_rate))
    )

(defcolumn cash
    :value_calculation (- cash int_c)
    )

; Z bond (accrual/accretion bond): while any of A, B, or C still has a
; balance outstanding ("lockout"), Z receives NO cash INTEREST at all --
; its stated coupon just ACCRETES onto its own balance instead (like a
; zero-coupon bond). Since that accrued amount is simply never taken out
; of the shared cash pool in the first place (int_z is 0), it's
; automatically left there for A/B/C's principal claims below -- which
; is the whole point of a Z bond: it accelerates the senior tranches'
; paydown, with no separate "redirect" bookkeeping needed (see int_z's
; comment). Once A, B, and C are fully retired, Z starts receiving cash
; interest like an ordinary bond instead.
;
; Z's PRINCIPAL claim (prin_z, below) is deliberately left unconditional
; -- min(what it's owed, whatever cash A/B/C didn't claim) -- rather than
; gated by the same lockout flag: ordinarily that's 0 while locked out,
; since A/B/C's own claims absorb the whole pool, but if A/B/C happen to
; retire in THIS SAME period with cash still left over, this lets Z pick
; it up immediately instead of it being stranded (silently lost, since
; nothing else claims it and cash doesn't carry over between periods) --
; a real gap an earlier version of this file had. bal_z's formula
; (further down) is unconditional the same way, for the same reason.

; 1/0, not #t/#f -- a column's series is a vector, and vectors only hold
; numbers or dates (see check_vector_elements() in lisp_interpreter.py).
(defcolumn z_locked_out
    :initial_value 1
    :value_calculation (if (or (> (lag bal_a 1) 0) (> (lag bal_b 1) 0) (> (lag bal_c 1) 0)) 1 0)
    :visible #f)

(defcolumn z_accrual
    :initial_value 0
    :value_calculation (* (lag bal_z 1) periodic_mortgage_interest_rate))

; The one genuinely either/or choice a real deal's payment rules make:
; cash interest, or accretion. (Explicitly adding z_accrual back into
; cash here, on top of this already leaving it unclaimed, would DOUBLE
; COUNT it -- there's deliberately no such step.)
(defcolumn int_z
    :value_calculation (if (> z_locked_out 0) 0 (min cash z_accrual))
    )

(defcolumn cash
    :value_calculation (- cash int_z)
    )

(defcolumn prin_a
    :value_calculation (min (lag bal_a 1) cash)
    )

(defcolumn cash
    :value_calculation (- cash prin_a)
    )

(defcolumn bal_a
    :initial_value 25000
    :value_calculation (- (lag bal_a 1) prin_a)
    )

(defcolumn prin_b
    :value_calculation (min (lag bal_b 1) cash)
    )

(defcolumn cash
    :value_calculation (- cash prin_b)
    )

(defcolumn bal_b
    :initial_value 25000
    :value_calculation (- (lag bal_b 1) prin_b)
    )

(defcolumn prin_c
    :value_calculation (min (lag bal_c 1) cash)
    )

(defcolumn cash
    :value_calculation (- cash prin_c)
    )

(defcolumn bal_c
    :initial_value 25000
    :value_calculation (- (lag bal_c 1) prin_c)
    )

(defcolumn prin_z
    :value_calculation (min (lag bal_z 1) cash)
    )

(defcolumn cash
    :value_calculation (- cash prin_z)
    )

; Grows by whatever part of this period's accrual wasn't paid in cash
; (all of it during lockout, none of it once unlocked), shrinks by
; whatever principal it received (0, ordinarily, during lockout) --
; correct in every case without needing to branch on z_locked_out here.
(defcolumn bal_z
    :initial_value 25000
    :value_calculation (max 0 (- (+ (lag bal_z 1) (- z_accrual int_z)) prin_z))
    )

(calculate-all *columns* (+ mortgage_term 1))
