; freddie_prepayment.lsp
; ======================
; A prepayment model fitted to Freddie Mac's loans, from the database that load_freddie_data/build_freddie_sample.py makes (see the README there). The model
; is a logistic regression with hinges (spline-logistic) of the single monthly mortality (smm): the share of a loan's scheduled balance that it prepaid in a month,
; 1 for a loan paid off, weighted by that balance, so that over a pool it is the pool's smm. It can be fitted two ways, on the same predictors:
;
;   loan by loan     every month of every loan (the table loan_months)
;   by groups        the months of loans that are alike put together (the table groups, made by build_groups.py): each group's smm, and the averages of its loans
;
; and either can be tried on loans that it was not fitted to, month by month, as the CPR of all of them together.
;
;   (define conn (sqlite-open "/Users/morris/freddie_data/freddie_loans.db"))
;   (define fit-loans (freddie-loan-months conn "sample_bucket < 80 AND period < '2019-01-01'"))
;   (define by-loan (fit-prepayment-model fit-loans))
;   (display (model-report by-loan))
;   (define test-loans (freddie-loan-months conn "sample_bucket >= 80"))
;   (plot-cpr-by-month (list (list "loan by loan" by-loan test-loans)))

(defstruct prepayment-data periods smm weights predictors)
; what a model is fitted to or tried on: a row for each month of a loan, or each group, with its month (a date), its smm, its weight (the scheduled balance) and its
; predictors, a list of (name . vector), in the order of prepayment-predictors

(define prepayment-predictors
  (list (list "incentive_bp" "incentive * 100" "incentive * 100" '(-100 0 50 100 150 200 300))
        (list "loan_age" "loan_age" "loan_age" '(6 12 24 36 60 120))
        (list "loan_size_k" "start_upb / 1000" "loan_size / 1000" '(100 200 300 500))
        (list "credit_score" "credit_score" "credit_score" '(680 740))
        (list "current_ltv" "current_ltv" "current_ltv" '(60 80 100))
        (list "sato" "sato" "sato" 0)
        (list "burnout" "burnout" "burnout" '(12))
        (list "investor" "occupancy = 'I'" "investor" 0)
        (list "second_home" "occupancy = 'S'" "second_home" 0)
        (list "cash_out" "purpose = 'C'" "cash_out" 0)
        (list "refinance" "purpose IN ('N', 'R')" "refinance" 0)
        (list "winter" "calendar_month IN (1, 2)" "calendar_month IN (1, 2)" 0)
        (list "summer" "calendar_month IN (5, 6, 7, 8)" "calendar_month IN (5, 6, 7, 8)" 0)))
; the predictors: (name, what it is in the table loan_months, what it is in the table groups, its knots, or 0 for a straight line). The incentive is in basis
; points, the loan's rate over the survey rate; the age in months; the loan size the balance in thousands of dollars; the ltv in percent, now; the sato the rate
; over the survey rate when the loan was made, in percent; the burnout the months that the loan had a reason to refinance and did not; investor, second_home, cash_out
; and refinance are 1 or 0 for a loan, and the share of the balance for a group; winter is January and February, summer May to August.

(define freddie-loan-months-rows
  "COALESCE(months_delinquent, 99) < 4 AND scheduled_upb > 0 AND incentive IS NOT NULL AND credit_score IS NOT NULL AND current_ltv IS NOT NULL AND sato IS NOT NULL")
; the months of loans that a model is for: not four or more months delinquent (those are bought out of an agency's pools), with a balance, and with every predictor

(define freddie-groups-rows "credit_score IS NOT NULL AND current_ltv IS NOT NULL AND sato IS NOT NULL")
; the groups that have every predictor (build_groups.py has already left out what freddie-loan-months-rows leaves out)

(define (prepayment-data-from conn table weight-sql rows where predictor-sql)
  "The prepayment-data of the rows of the table that are rows and where (SQL conditions), with the predictors that predictor-sql (cadr or caddr) gives of each."
  (let* ((condition (format "({}) AND ({})" rows where))
         (count (vector-ref (cdr (car (sqlite-query conn (format "SELECT COUNT(*) AS n FROM {} WHERE {}" table condition)))) 0))
         (columns (sqlite-query conn
                                (format "SELECT period, smm, {} AS weight, {} FROM {} WHERE {}"
                                        weight-sql
                                        (string-join (map (lambda (predictor) (format "{} AS {}" (predictor-sql predictor) (car predictor))) prepayment-predictors) ", ")
                                        table condition)
                                (apply string-append "." (map (lambda (column) "F") (cons "smm" (cons "weight" prepayment-predictors))))
                                (max count 1))))
    (make-prepayment-data :periods (cdr (first columns)) :smm (cdr (second columns)) :weights (cdr (third columns)) :predictors (cdddr columns))))

(define (freddie-loan-months conn where)
  "The prepayment-data of the months of loans in the table loan_months that are where (an SQL condition, such as \"sample_bucket < 80\"): a row for each."
  (prepayment-data-from conn "loan_months" "scheduled_upb" freddie-loan-months-rows where cadr))

(define (freddie-groups conn where)
  "The prepayment-data of the groups in the table groups that are where (an SQL condition, such as \"part = 'fit'\"): a row for each group, its predictors the averages of its loans."
  (prepayment-data-from conn "groups" "balance" freddie-groups-rows where caddr))

(define (knots-within knots values)
  "The knots that have values on both sides of them, from the 1st to the 99th percentile (0, for a straight line, if none have): a hinge at a knot with
nothing beyond it is a column of zeros, and one with only a few rows beyond it can be made as steep as it likes to fit them, so neither can be fitted. The
averages of groups of loans are closer together than the loans are, so a knot that the loans are on both sides of can be beyond the groups."
  (let* ((low (vector-quantile values 0.01))
         (high (vector-quantile values 0.99))
         (inside (if (list? knots) (filter (lambda (knot) (< low knot high)) knots) '())))
    (if (null? inside) 0 inside)))

(define (fit-prepayment-model data)
  "A model of the smm, fitted to the prepayment-data: a spline-logistic of the smm on the predictors, with their knots (those with data on both sides: see knots-within), each row
weighted by its scheduled balance."
  (spline-logistic (prepayment-data-predictors data)
                   (prepayment-data-smm data)
                   (map (lambda (predictor column) (knots-within (cadddr predictor) (cdr column))) prepayment-predictors (prepayment-data-predictors data))
                   (prepayment-data-weights data)))

(define (predicted-smm model data)
  "What the model says the smm of each row of the prepayment-data is: a vector."
  (- (prepayment-data-smm data) (model-residuals model (prepayment-data-predictors data) (prepayment-data-smm data))))

(define (cpr-of-smm smm)
  "The CPR, the annual rate of prepayment in percent, of a single monthly mortality (a number or a vector)."
  (* 100.0 (- 1.0 (expt (- 1.0 smm) 12))))

(define (prepayment-cpr-by-month model data)
  "A table, a row for each month: the CPR of all the rows of the prepayment-data of the month together (their smms, weighted by their balances), and what the model says it is."
  (let* ((months (table-group-by (make-table "month" (prepayment-data-periods data)
                                             "weight" (prepayment-data-weights data)
                                             "smm" (prepayment-data-smm data)
                                             "predicted" (predicted-smm model data))
                                 "month"
                                 (list (list "smm" 'weighted-mean "smm" "weight")
                                       (list "predicted" 'weighted-mean "predicted" "weight")))))
    (make-table "month" (table-column months "month")
                "actual CPR" (cpr-of-smm (table-column months "smm"))
                "predicted CPR" (cpr-of-smm (table-column months "predicted")))))

(define (prepayment-cpr-misses comparisons split)
  "A table of how far, on average over the months, each comparison's model is from the CPR of its data, before the split (a date) and from it on, in CPR: the misses
of a model on loans it was not fitted to, in the time that it was fitted to and after it. Each comparison is (name model data)."
  (let* ((misses (map (lambda (comparison)
                        (let ((months (prepayment-cpr-by-month (cadr comparison) (caddr comparison))))
                          (list (table-column months "month")
                                (abs (- (table-column months "predicted CPR") (table-column months "actual CPR"))))))
                      comparisons))
         (average-miss (lambda (miss in-time?)
                         (let ((chosen (in-time? (car miss))))
                           (/ (vector-sum (* (cadr miss) chosen)) (vector-sum chosen))))))
    (make-table "model" (list->vector (map car comparisons))
                (format "before {}" split) (list->vector (map (lambda (miss) (average-miss miss (lambda (months) (< months split)))) misses))
                (format "from {} on" split) (list->vector (map (lambda (miss) (average-miss miss (lambda (months) (>= months split)))) misses)))))

(define (plot-cpr-by-month comparisons &key (title "CPR by month: what the loans did, and what the models said"))
  "A chart of the CPR month by month of the data of the first of the comparisons, and what each comparison's model says it was. Each comparison is (name model data)."
  (let* ((tables (map (lambda (comparison) (prepayment-cpr-by-month (cadr comparison) (caddr comparison))) comparisons))
         (first-table (car tables)))
    (plot-chart (cons (list "actual" (table-column first-table "month") (table-column first-table "actual CPR") :color "black")
                      (map (lambda (comparison table) (list (car comparison) (table-column table "month") (table-column table "predicted CPR")))
                           comparisons tables))
                :title title :y-label "CPR, percent")))

(define typical-prepayment-loan
  '(("loan_age" 36) ("loan_size_k" 250) ("credit_score" 750) ("current_ltv" 70) ("sato" 0) ("burnout" 0)
    ("investor" 0) ("second_home" 0) ("cash_out" 0) ("refinance" 0) ("winter" 0) ("summer" 0)))
; a loan to draw the S-curve of a model for: three years old, $250,000, a credit score of 750, 70% loan-to-value, a purchase, of a primary home, in the spring or fall

(define (prepayment-s-curve model &key (loan typical-prepayment-loan))
  "A table of the CPR that the model says the loan (a list of (predictor value)) prepays at, for each incentive from -200 to 400 basis points, in steps of 25."
  (let ((incentives (list->vector (loop for bp from -200 to 400 by 25 collect bp))))
    (make-table "incentive_bp" incentives
                "CPR" (vector-map (lambda (bp)
                                    (cpr-of-smm (model-predict model (map (lambda (predictor)
                                                                            (if (equal? (car predictor) "incentive_bp") bp (cadr (assoc (car predictor) loan))))
                                                                          prepayment-predictors))))
                                  incentives))))

(define (plot-prepayment-s-curves models &key (loan typical-prepayment-loan))
  "A chart of the S-curve of each model (a list of (name model)): the CPR of the loan, against the incentive."
  (plot-chart (map (lambda (named)
                     (let ((curve (prepayment-s-curve (cadr named) :loan loan)))
                       (list (car named) (table-column curve "incentive_bp") (table-column curve "CPR"))))
                   models)
              :title "The CPR of a typical loan, against its incentive" :x-label "incentive, basis points" :y-label "CPR, percent"))
