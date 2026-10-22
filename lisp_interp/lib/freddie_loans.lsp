; freddie_loans.lsp
; =================
; What the models of Freddie Mac's loans share: freddie_prepayment.lsp (how fast loans prepay) and freddie_default.lsp (how many default, and what is lost).
; Each is fitted to the rows of the database that load_freddie_data/build_freddie_sample.py makes (see the README there): a row for each month of each loan,
; or for each group of loans that are alike.
;
; Most of the models are of a MONTHLY RATE: the share of a loan's balance that something happened to in a month (that it prepaid: the smm; that defaulted:
; the mdr), a spline-logistic of it, with each row weighted by the balance, so that over a pool it is the pool's rate. Twelve months of a monthly rate are
; the annual rate (annual-rate): the CPR of an smm, the CDR of an mdr. The severity of a loss is modeled the same way, by a spline-regression.
;
; A model is tried on loans that it was not fitted to (a sample_bucket of 80 or more), period by period: what they did, all of them together, and what the
; model said they would (outcomes-by-period, rate-by-month, plot-rate-by-month, rate-misses).

(defstruct predictor name sql group-sql knots)
; something a model looks at: its name, what it is in SQL, in the table loan_months and in the table groups ('() if it is not in that table), and its knots
; (a list, or 0 for a straight line)

(defstruct loan-data periods outcomes weights predictors)
; what a model is fitted to or tried on: a row for each month of a loan, or each group, or each loss: its period (a date), its outcome (a monthly rate, or a
; severity), its weight (a balance) and its predictors, a list of (name . vector), in the order of the model's predictors

(define (loan-data-from conn table outcome-sql weight-sql where predictors predictor-sql &key (period-sql "period"))
  "The loan-data of the rows of the table that are where (an SQL condition): the outcome and the weight that outcome-sql and weight-sql give of each, its period
(period-sql), and the predictors, each what predictor-sql (predictor-sql or predictor-group-sql) gives of it."
  (let* ((count (vector-ref (cdr (car (sqlite-query conn (format "SELECT COUNT(*) AS n FROM {} WHERE {}" table where)))) 0))
         (columns (sqlite-query conn
                                (format "SELECT {} AS period, {} AS outcome, {} AS weight, {} FROM {} WHERE {}"
                                        period-sql outcome-sql weight-sql
                                        (string-join (map (lambda (predictor) (format "{} AS {}" (predictor-sql predictor) (predictor-name predictor))) predictors) ", ")
                                        table where)
                                (apply string-append "." (map (lambda (column) "F") (cons "outcome" (cons "weight" predictors))))
                                (max count 1))))
    (make-loan-data :periods (cdr (first columns)) :outcomes (cdr (second columns)) :weights (cdr (third columns)) :predictors (cdddr columns))))

(define (knots-within knots values)
  "The knots that have values on both sides of them, from the 1st to the 99th percentile (0, for a straight line, if none have): a hinge at a knot with
nothing beyond it is a column of zeros, and one with only a few rows beyond it can be made as steep as it likes to fit them, so neither can be fitted. The
averages of groups of loans are closer together than the loans are, so a knot that the loans are on both sides of can be beyond the groups."
  (let* ((low (vector-quantile values 0.01))
         (high (vector-quantile values 0.99))
         (inside (if (list? knots) (filter (lambda (knot) (< low knot high)) knots) '())))
    (if (null? inside) 0 inside)))

(define (data-knots data predictors)
  "The knots of each of the predictors that the data has on both sides (see knots-within)."
  (map (lambda (predictor column) (knots-within (predictor-knots predictor) (cdr column))) predictors (loan-data-predictors data)))

(define (fit-rate-model data predictors)
  "A model of a monthly rate, fitted to the loan-data: a spline-logistic of the outcome on the predictors, with their knots, each row weighted by its weight."
  (spline-logistic (loan-data-predictors data) (loan-data-outcomes data) (data-knots data predictors) (loan-data-weights data)))

(define (predicted-outcomes model data)
  "What the model says the outcome of each row of the loan-data is: a vector."
  (- (loan-data-outcomes data) (model-residuals model (loan-data-predictors data) (loan-data-outcomes data))))

(define (model-predictions model columns)
  "What the model says of each row of the columns, a list of (name . vector) in the order of its predictors: a vector. (The residuals of rows whose outcomes are 0 are
the predictions, less than 0.)"
  (let ((zeros (make-vector (vector-length (cdr (car columns))) 0.0)))
    (- zeros (model-residuals model columns zeros))))

(define (annual-rate monthly)
  "The annual rate in percent (a CPR, or a CDR) of a monthly rate (a decimal, or a vector of them): what is left after twelve months of it, taken from all of it."
  (* 100.0 (- 1.0 (expt (- 1.0 monthly) 12))))

(define (outcomes-by-period model data)
  "A table, a row for each period: the outcome of all the rows of the loan-data of the period together (their outcomes, weighted by their weights), and what the model
says it is: the columns period, actual and predicted."
  (let ((periods (table-group-by (make-table "period" (loan-data-periods data)
                                             "weight" (loan-data-weights data)
                                             "actual" (loan-data-outcomes data)
                                             "predicted" (predicted-outcomes model data))
                                 "period"
                                 (list (list "actual" 'weighted-mean "actual" "weight")
                                       (list "predicted" 'weighted-mean "predicted" "weight")))))
    (make-table "period" (table-column periods "period")
                "actual" (table-column periods "actual")
                "predicted" (table-column periods "predicted"))))

(define (rate-by-month model data label)
  "A table, a row for each month: the annual rate (label, CPR or CDR) of all the rows of the loan-data of the month together, and what the model says it is."
  (let ((months (outcomes-by-period model data)))
    (make-table "month" (table-column months "period")
                (format "actual {}" label) (annual-rate (table-column months "actual"))
                (format "predicted {}" label) (annual-rate (table-column months "predicted")))))

(define (rate-misses comparisons split label)
  "A table of how far, on average over the months, each comparison's model is from the annual rate (label) of its data, before the split (a date) and from it on: the
misses of a model on loans it was not fitted to, in the time that it was fitted to and after it. Each comparison is (name model data)."
  (let* ((misses (map (lambda (comparison)
                        (let ((months (rate-by-month (cadr comparison) (caddr comparison) label)))
                          (list (table-column months "month")
                                (abs (- (table-column months (format "predicted {}" label)) (table-column months (format "actual {}" label)))))))
                      comparisons))
         (average-miss (lambda (miss in-time?)
                         (let ((chosen (in-time? (car miss))))
                           (/ (vector-sum (* (cadr miss) chosen)) (vector-sum chosen))))))
    (make-table "model" (list->vector (map car comparisons))
                (format "before {}" split) (list->vector (map (lambda (miss) (average-miss miss (lambda (months) (< months split)))) misses))
                (format "from {} on" split) (list->vector (map (lambda (miss) (average-miss miss (lambda (months) (>= months split)))) misses)))))

(define (plot-rate-by-month comparisons label &key (title (format "{} by month: what the loans did, and what the models said" label)))
  "A chart of the annual rate (label) month by month of the data of the first of the comparisons, and what each comparison's model says it was. Each comparison is
(name model data)."
  (let* ((tables (map (lambda (comparison) (rate-by-month (cadr comparison) (caddr comparison) label)) comparisons))
         (first-table (car tables)))
    (plot-chart (cons (list "actual" (table-column first-table "month") (table-column first-table (format "actual {}" label)) :color "black")
                      (map (lambda (comparison table) (list (car comparison) (table-column table "month") (table-column table (format "predicted {}" label))))
                           comparisons tables))
                :title title :y-label (format "{}, percent" label))))

(define (model-curve model predictors loan name values)
  "What the model says of the loan (a list of (predictor value)) as one of its predictors, name, takes each of the values (a vector), the others staying as the
loan has them: a vector."
  (vector-map (lambda (value)
                (model-predict model (map (lambda (predictor)
                                            (if (equal? (predictor-name predictor) name) value (cadr (assoc (predictor-name predictor) loan))))
                                          predictors)))
              values))
