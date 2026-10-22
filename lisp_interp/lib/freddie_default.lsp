; freddie_default.lsp
; ===================
; A default model fitted to Freddie Mac's loans, the same sample as the prepayment model (freddie_prepayment.lsp), from the database that
; load_freddie_data/build_freddie_sample.py makes (see the README there). It is in three parts:
;
;   how many default    a spline-logistic of whether a loan defaulted in a month (the monthly default rate, mdr), over the months of the loans that have not
;                       defaulted yet, weighted by their balances, so that over a pool it is the share of the balance that defaults; (annual-rate mdr) is the CDR
;   what is lost        a spline-regression of the severity of the loss of a loan that was sold (a short sale, a third-party sale or an REO sale): the loss over
;                       the balance, weighted by the balance
;   what became of them  default-outcomes: of the loans that defaulted each year, how much was sold at a loss, how much was paid off or sold while paying, how
;                       much is not over yet, and how long it took
;
; A loan defaults in the first month that it is six months delinquent, not in forbearance (most loans that were in 2020 and 2021 were, and caught up), or that the
; home is taken, or that the loan ends in a sale of the home or of the note (see load_freddie_data/loan_months.py). What it shares with the prepayment model is in
; freddie_loans.lsp.
;
;   (define conn (sqlite-open "/Users/morris/freddie_data/freddie_loans.db"))
;   (define defaults (fit-default-model (freddie-default-months conn "sample_bucket < 80 AND period < '2019-01-01'")))
;   (plot-rate-by-month (list (list "model" defaults (freddie-default-months conn "sample_bucket >= 80"))) "CDR")
;   (define severity (fit-severity-model (freddie-liquidations conn "sample_bucket < 80 AND period < '2019-01-01'")))
;   (display-table (default-outcomes conn))

(require "freddie_loans.lsp")

(define default-predictors
  (list (make-predictor :name "credit_score" :sql "credit_score" :knots '(620 680 740))
        (make-predictor :name "current_ltv" :sql "current_ltv" :knots '(60 80 100 120))
        (make-predictor :name "loan_age" :sql "loan_age" :knots '(12 24 48 96))
        (make-predictor :name "dti" :sql "dti" :knots '(36 45))
        (make-predictor :name "sato" :sql "sato" :knots 0)
        (make-predictor :name "incentive_bp" :sql "incentive * 100" :knots '(-100 0 100))
        (make-predictor :name "loan_size_k" :sql "start_upb / 1000" :knots '(100 200 300))
        (make-predictor :name "investor" :sql "occupancy = 'I'" :knots 0)
        (make-predictor :name "second_home" :sql "occupancy = 'S'" :knots 0)
        (make-predictor :name "cash_out" :sql "purpose = 'C'" :knots 0)
        (make-predictor :name "refinance" :sql "purpose IN ('N', 'R')" :knots 0)
        (make-predictor :name "one_borrower" :sql "borrowers = 1" :knots 0)))
; what the default model looks at: the credit score when the loan was made; the loan-to-value now, percent (a borrower who owes more than the home is worth can
; walk away, and cannot sell it to pay the loan); the age in months; the debt-to-income when it was made, percent; the sato, percent (a borrower who paid more than
; the market, most often for weaker credit); the incentive in basis points (a borrower who could save by refinancing and does not may not be able to); the loan
; size in thousands of dollars; and 1 or 0 for an investment property, a second home, a cash-out refinance, another refinance, and a loan with one borrower

(define default-loan-months
  "after_default = 0 AND start_upb > 0 AND credit_score IS NOT NULL AND current_ltv IS NOT NULL AND dti IS NOT NULL AND sato IS NOT NULL AND incentive IS NOT NULL AND borrowers IS NOT NULL")
; the months of loans that the default model is for: those of the loans that have not defaulted yet (the month of the default is one of them), with every predictor

(define (freddie-default-months conn where)
  "The loan-data of the months of loans that have not defaulted yet in the table loan_months that are where (an SQL condition, such as \"sample_bucket < 80\"): a row
for each, its outcome 1 if the loan defaulted that month, its weight its balance at the start of the month."
  (loan-data-from conn "loan_months" "defaulted" "start_upb" (format "({}) AND ({})" default-loan-months where) default-predictors predictor-sql))

(define (fit-default-model data)
  "A model of the monthly default rate, fitted to the loan-data of freddie-default-months: see fit-rate-model."
  (fit-rate-model data default-predictors))

(define typical-default-loan
  '(("credit_score" 720) ("current_ltv" 80) ("loan_age" 36) ("dti" 36) ("sato" 0) ("incentive_bp" 0) ("loan_size_k" 250)
    ("investor" 0) ("second_home" 0) ("cash_out" 0) ("refinance" 0) ("one_borrower" 0)))
; a loan to draw the curves of a default model for: a credit score of 720, 80% loan-to-value, three years old, 36% debt-to-income, $250,000, two borrowers buying a
; home to live in, at the market rate then and now

(define (default-ltv-curves model &key (scores '(640 700 760)) (loan typical-default-loan))
  "A table of the CDR that the model says the loan (a list of (predictor value)) defaults at, for each loan-to-value now from 40 to 160 in steps of 10, a column for each of
the credit scores."
  (let ((ltvs (list->vector (loop for ltv from 40 to 160 by 10 collect ltv))))
    (apply make-table
           (cons "current_ltv"
                 (cons ltvs
                       (apply append
                              (map (lambda (score)
                                     (list (format "CDR, credit score {}" score)
                                           (annual-rate (model-curve model default-predictors
                                                                     (cons (list "credit_score" score) loan) "current_ltv" ltvs))))
                                   scores)))))))

(define (plot-default-ltv-curves model &key (scores '(640 700 760)) (loan typical-default-loan))
  "A chart of default-ltv-curves: the CDR of the loan against its loan-to-value now, a line for each credit score."
  (let ((curves (default-ltv-curves model :scores scores :loan loan)))
    (plot-chart (map (lambda (column) (list (car column) (table-column curves "current_ltv") (cdr column))) (cdr curves))
                :title "The CDR of a typical loan, against its loan-to-value now" :x-label "loan-to-value now, percent" :y-label "CDR, percent")))

; ---------------------------------------------------------------------------
; What is lost
; ---------------------------------------------------------------------------

(define severity-predictors
  (list (make-predictor :name "ltv_at_default" :sql "ltv_at_default" :knots '(60 80 100 120))
        (make-predictor :name "loan_size_k" :sql "removal_upb / 1000" :knots '(100 200))
        (make-predictor :name "mi_percent" :sql "mi_percent" :knots 0)
        (make-predictor :name "months_since_default" :sql "months_since_default" :knots '(12 24 36))
        (make-predictor :name "investor" :sql "occupancy = 'I'" :knots 0)))
; what the severity model looks at: the loan-to-value when the loan defaulted, percent (the less the home is worth, the less the sale brings); the balance, in thousands
; of dollars (the costs are much the same for a small loan, so they are more of it); the mortgage insurance, percent of the loss that it covers; the months from the
; default to the sale (interest goes unpaid, and taxes and upkeep are paid, all that time); and 1 for an investment property

(define liquidations "loss IS NOT NULL AND removal_upb > 0 AND ltv_at_default IS NOT NULL AND mi_percent IS NOT NULL AND months_since_default IS NOT NULL")
; the months of loans that were sold at a loss that Freddie reports, with every predictor

(define (freddie-liquidations conn where)
  "The loan-data of the sales of defaulted loans in the table loan_months that are where (an SQL condition): a row for each, its outcome the severity, its weight the
balance, and its period the first day of the year of the sale."
  (loan-data-from conn "loan_months" "severity" "removal_upb" (format "({}) AND ({})" liquidations where) severity-predictors predictor-sql
                  :period-sql "substr(period, 1, 4) || '-01-01'"))

(define (fit-severity-model data)
  "A model of the severity of a loss, fitted to the loan-data of freddie-liquidations: a spline-regression of the severity on the predictors, each sale weighted by its
balance."
  (spline-regression (loan-data-predictors data) (loan-data-outcomes data) (data-knots data severity-predictors) (loan-data-weights data)))

(define (severity-by-year model data)
  "A table, a row for each year: the severity of all the sales of the loan-data of the year together (their losses over their balances), and what the model says it is,
in percent."
  (let ((years (outcomes-by-period model data)))
    (make-table "year" (table-column years "period")
                "actual severity" (* 100.0 (table-column years "actual"))
                "predicted severity" (* 100.0 (table-column years "predicted")))))

(define typical-liquidation
  '(("ltv_at_default" 90) ("loan_size_k" 200) ("mi_percent" 0) ("months_since_default" 18) ("investor" 0)))
; a sale to draw the curve of a severity model for: 90% loan-to-value at the default, $200,000, no mortgage insurance, sold a year and a half after the default

(define (severity-ltv-curve model &key (liquidation typical-liquidation))
  "A table of the severity, percent, that the model says the sale (a list of (predictor value)) has, for each loan-to-value at the default from 40 to 160 in steps of 10."
  (let ((ltvs (list->vector (loop for ltv from 40 to 160 by 10 collect ltv))))
    (make-table "ltv_at_default" ltvs
                "severity" (* 100.0 (model-curve model severity-predictors liquidation "ltv_at_default" ltvs)))))

; ---------------------------------------------------------------------------
; What became of the loans that defaulted
; ---------------------------------------------------------------------------

(define (default-outcomes conn)
  "A table, a row for each year that loans of the table loan_months defaulted in: how many, their balance when they defaulted, and
what share of it, in percent, was sold at a loss (a short sale, a third-party sale or an REO sale), was sold as a note while it was not being paid, was paid off, was sold
as a note while it was being paid again (most often after a modification), and is not over yet; the severity of the losses, percent of the balance; the months from the
default to the sale; and the losses over all that defaulted, percent: the loss given default, which is less than the severity, as not every default is sold at a loss.
The years near the end are not over: a default that is still going has no loss yet."
  (let ((share (lambda (condition) (format "100.0 * SUM(CASE WHEN {} THEN d.start_upb ELSE 0 END) / SUM(d.start_upb)" condition))))
    (sqlite-query conn
                  (format "SELECT substr(d.period, 1, 4) AS year, COUNT(*) AS defaults, SUM(d.start_upb) AS balance,
                                  {} AS \"sold at a loss\", {} AS \"note sold\", {} AS \"paid off\", {} AS \"sold, paying\", {} AS \"not over\",
                                  100.0 * SUM(x.loss) / SUM(CASE WHEN x.loss IS NOT NULL THEN x.removal_upb END) AS severity,
                                  AVG(CASE WHEN x.loss IS NOT NULL THEN x.months_since_default END) AS \"months to the sale\",
                                  100.0 * SUM(COALESCE(x.loss, 0)) / SUM(d.start_upb) AS \"loss given default\"
                           FROM loan_months d LEFT JOIN loan_months x ON x.loan_id = d.loan_id AND x.exit_code IS NOT NULL
                           WHERE d.defaulted = 1
                           GROUP BY year ORDER BY year"
                          (share "x.exit_code IN ('02', '03', '09')") (share "x.exit_code = '15'") (share "x.exit_code = '01'")
                          (share "x.exit_code = '16'") (share "x.exit_code IS NULL")))))
