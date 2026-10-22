; freddie_prepayment.lsp
; ======================
; A prepayment model fitted to Freddie Mac's loans, from the database that load_freddie_data/build_freddie_sample.py makes (see the README there). The model
; is a spline-logistic of the single monthly mortality (smm): the share of a loan's scheduled balance that it prepaid in a month, 1 for a loan paid off, weighted
; by that balance, so that over a pool it is the pool's smm, and its CPR is (annual-rate smm). What it shares with the default model is in freddie_loans.lsp.
; It can be fitted two ways, on the same predictors:
;
;   loan by loan     every month of every loan (the table loan_months)
;   by groups        the months of loans that are alike put together (the table groups, made by build_groups.py): each group's smm, and the averages of its loans
;
; and either can be tried on loans that it was not fitted to, month by month, as the CPR of all of them together.
;
;   (define conn (sqlite-open "/Users/morris/freddie_data/freddie_loans.db"))
;   (define by-loan (fit-prepayment-model (freddie-loan-months conn "sample_bucket < 80 AND period < '2019-01-01'")))
;   (display (model-report by-loan))
;   (define test-loans (freddie-loan-months conn "sample_bucket >= 80"))
;   (plot-rate-by-month (list (list "loan by loan" by-loan test-loans)) "CPR")

(require "freddie_loans.lsp")

(define prepayment-predictors
  (list (make-predictor :name "incentive_bp" :sql "incentive * 100" :group-sql "incentive * 100" :knots '(-100 0 50 100 150 200 300))
        (make-predictor :name "loan_age" :sql "loan_age" :group-sql "loan_age" :knots '(6 12 24 36 60 120))
        (make-predictor :name "loan_size_k" :sql "start_upb / 1000" :group-sql "loan_size / 1000" :knots '(100 200 300 500))
        (make-predictor :name "credit_score" :sql "credit_score" :group-sql "credit_score" :knots '(680 740))
        (make-predictor :name "current_ltv" :sql "current_ltv" :group-sql "current_ltv" :knots '(60 80 100))
        (make-predictor :name "sato" :sql "sato" :group-sql "sato" :knots 0)
        (make-predictor :name "burnout" :sql "burnout" :group-sql "burnout" :knots '(12))
        (make-predictor :name "investor" :sql "occupancy = 'I'" :group-sql "investor" :knots 0)
        (make-predictor :name "second_home" :sql "occupancy = 'S'" :group-sql "second_home" :knots 0)
        (make-predictor :name "cash_out" :sql "purpose = 'C'" :group-sql "cash_out" :knots 0)
        (make-predictor :name "refinance" :sql "purpose IN ('N', 'R')" :group-sql "refinance" :knots 0)
        (make-predictor :name "winter" :sql "calendar_month IN (1, 2)" :group-sql "calendar_month IN (1, 2)" :knots 0)
        (make-predictor :name "summer" :sql "calendar_month IN (5, 6, 7, 8)" :group-sql "calendar_month IN (5, 6, 7, 8)" :knots 0)))
; what the prepayment model looks at. The incentive is in basis points, the loan's rate over the survey rate; the age in months; the loan size the balance in
; thousands of dollars; the ltv in percent, now; the sato the rate over the survey rate when the loan was made, in percent; the burnout the months that the loan had
; a reason to refinance and did not; investor, second_home, cash_out and refinance are 1 or 0 for a loan, and the share of the balance for a group; winter is
; January and February, summer May to August.

(define prepayment-loan-months
  "COALESCE(months_delinquent, 99) < 4 AND scheduled_upb > 0 AND incentive IS NOT NULL AND credit_score IS NOT NULL AND current_ltv IS NOT NULL AND sato IS NOT NULL")
; the months of loans that the prepayment model is for: not four or more months delinquent (those are bought out of an agency's pools), with a balance, and with
; every predictor

(define prepayment-groups "credit_score IS NOT NULL AND current_ltv IS NOT NULL AND sato IS NOT NULL")
; the groups that have every predictor (build_groups.py has already left out the months that prepayment-loan-months leaves out)

(define (freddie-loan-months conn where)
  "The loan-data of the months of loans in the table loan_months that are where (an SQL condition, such as \"sample_bucket < 80\"): a row for each, its outcome its smm,
its weight its scheduled balance."
  (loan-data-from conn "loan_months" "smm" "scheduled_upb" (format "({}) AND ({})" prepayment-loan-months where) prepayment-predictors predictor-sql))

(define (freddie-groups conn where)
  "The loan-data of the groups in the table groups that are where (an SQL condition, such as \"part = 'fit'\"): a row for each group, its predictors the averages of its loans."
  (loan-data-from conn "groups" "smm" "balance" (format "({}) AND ({})" prepayment-groups where) prepayment-predictors predictor-group-sql))

(define (fit-prepayment-model data)
  "A model of the smm, fitted to the loan-data (of loans, or of groups): see fit-rate-model."
  (fit-rate-model data prepayment-predictors))

(define typical-prepayment-loan
  '(("loan_age" 36) ("loan_size_k" 250) ("credit_score" 750) ("current_ltv" 70) ("sato" 0) ("burnout" 0)
    ("investor" 0) ("second_home" 0) ("cash_out" 0) ("refinance" 0) ("winter" 0) ("summer" 0)))
; a loan to draw the S-curve of a model for: three years old, $250,000, a credit score of 750, 70% loan-to-value, a purchase, of a primary home, in the spring or fall

; ---------------------------------------------------------------------------
; The model, for a deal: (model piece path)
; ---------------------------------------------------------------------------

(define freddie-prepayment-fit-file "freddie_prepayment_fit.json")
; the prepayment model fitted to Freddie Mac's loans that comes with the library, in lib/ beside this file: fitted in notebooks/freddie_prepayment_model.ipynb, and
; saved there by save-freddie-prepayment-fit

(define freddie-prepayment-fit-model '())
(define freddie-prepayment-fit-read '())

(define (freddie-prepayment-fit)
  "The prepayment model fitted to Freddie Mac's loans that comes with the library (freddie-prepayment-fit-file), read from its file the first time it is wanted."
  (when (null? freddie-prepayment-fit-read)
    (load-variables freddie-prepayment-fit-file)
    (set! freddie-prepayment-fit-read freddie-prepayment-fit-model))
  freddie-prepayment-fit-read)

(define (save-freddie-prepayment-fit model path)
  "Saves the model (made by fit-prepayment-model) in the file at path, for freddie-prepayment-fit to read: lib/freddie_prepayment_fit.json is the one that the deals use."
  (set! freddie-prepayment-fit-model model)
  (save-variables path freddie-prepayment-fit-model))

(define (prepayment-model-columns piece path &key (home-price-growth 3.0) (mortgage-spread 1.75))
  "What the prepayment model looks at in each month of the piece (a collateral-piece), 1 to its wam, on the path of rates (a rate-path): its predictors
(prepayment-predictors), each a vector with a value for each month, as a list of (name . vector).

  incentive_bp, loan_age, loan_size_k, current_ltv   as the piece goes along the path (see piece-on-path)
  burnout         the piece's burnout, and a month more for each month before this one, after the first year, with an incentive above 75 basis points
  credit_score, sato, investor, second_home, cash_out, refinance    the piece's, the same each month
  winter, summer  1 in January and February, and May to August, from the date of the first payment; with no date, 2/12 and 4/12, an average year

Where the piece does not say what its loans are like, the model takes them to be the loan of unknown-piece."
  (let* ((months (collateral-piece-wam piece))
         (along (piece-on-path piece path home-price-growth mortgage-spread))
         (incentive (cdr (assoc "incentive_bp" along)))
         (age (cdr (assoc "loan_age" along)))
         (constant (lambda (slot accessor) (make-vector months (+ 0.0 (piece-value piece slot accessor)))))
         (in-the-money (* (> incentive 75.0) (> age 12)))
         (burnout (+ (piece-value piece 'burnout collateral-piece-burnout) (- (vector-cumsum in-the-money) in-the-money)))
         (first-payment (rate-path-first-payment path))
         (calendar (if (null? first-payment) '() (calendar-months first-payment months))))
    (list (cons "incentive_bp" incentive)
          (cons "loan_age" age)
          (assoc "loan_size_k" along)
          (cons "credit_score" (constant 'credit-score collateral-piece-credit-score))
          (assoc "current_ltv" along)
          (cons "sato" (constant 'sato collateral-piece-sato))
          (cons "burnout" (+ 0.0 burnout))
          (cons "investor" (constant 'investor-share collateral-piece-investor-share))
          (cons "second_home" (constant 'second-home-share collateral-piece-second-home-share))
          (cons "cash_out" (constant 'cash-out-share collateral-piece-cash-out-share))
          (cons "refinance" (constant 'refinance-share collateral-piece-refinance-share))
          (cons "winter" (if (null? calendar) (make-vector months (/ 2.0 12)) (+ 0.0 (<= calendar 2))))
          (cons "summer" (if (null? calendar) (make-vector months (/ 4.0 12)) (+ 0.0 (* (>= calendar 5) (<= calendar 8))))))))

(define (freddie-prepayment-model &key (home-price-growth 3.0) (mortgage-spread 1.75) (fit '()))
  "A prepayment model for a deal, (model piece path) (see deal_paths.lsp): the model fitted to Freddie Mac's loans (fit, or, if it is '(), the one that comes with the
library: freddie-prepayment-fit), which gives the CPR, in percent, of each month of the piece of collateral on the path of rates, from what it looks at
(prepayment-model-columns). home-price-growth is how much home prices grow, percent a year, and mortgage-spread how far the rate of a new mortgage is above the
10-year Treasury yield, percent."
  (lambda (piece path)
    (annual-rate (model-predictions (if (null? fit) (freddie-prepayment-fit) fit)
                                    (prepayment-model-columns piece path :home-price-growth home-price-growth :mortgage-spread mortgage-spread)))))

(define (prepayment-s-curve model &key (loan typical-prepayment-loan))
  "A table of the CPR that the model says the loan (a list of (predictor value)) prepays at, for each incentive from -200 to 400 basis points, in steps of 25."
  (let ((incentives (list->vector (loop for bp from -200 to 400 by 25 collect bp))))
    (make-table "incentive_bp" incentives
                "CPR" (annual-rate (model-curve model prepayment-predictors loan "incentive_bp" incentives)))))

(define (plot-prepayment-s-curves models &key (loan typical-prepayment-loan))
  "A chart of the S-curve of each model (a list of (name model)): the CPR of the loan, against the incentive."
  (plot-chart (map (lambda (named)
                     (let ((curve (prepayment-s-curve (cadr named) :loan loan)))
                       (list (car named) (table-column curve "incentive_bp") (table-column curve "CPR"))))
                   models)
              :title "The CPR of a typical loan, against its incentive" :x-label "incentive, basis points" :y-label "CPR, percent"))
