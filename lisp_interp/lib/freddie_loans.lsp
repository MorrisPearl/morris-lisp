; freddie_loans.lsp
; =================
; What the models of Freddie Mac's loans share: freddie_prepayment.lsp (how fast loans prepay) and freddie_default.lsp (how many default, and what is lost).
; Each is fitted to the rows of the database that load_freddie_data/build_freddie_sample.py makes (see the README there): a row for each month of each loan,
; or for each group of loans that are alike.
;
; Most of the models are of a MONTHLY RATE: the share of a loan's balance that something happened to in a month (that it prepaid: the smm; that defaulted:
; the mdr), a spline-logistic of it, with each row weighted by the balance, so that over a pool it is the pool's rate. Twelve months of a monthly rate are
; the annual rate (annual-rate, in prepayment_speed.lsp): the CPR of an smm, the CDR of an mdr. The severity of a loss is modeled the same way, by a spline-regression.
;
; A model is tried on loans that it was not fitted to (a sample_bucket of 80 or more), period by period: what they did, all of them together, and what the
; model said they would (outcomes-by-period, rate-by-month, plot-rate-by-month, rate-misses).

(require "prepayment_speed.lsp")

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
    (make-loan-data :periods (cdr (car columns)) :outcomes (cdr (cadr columns)) :weights (cdr (caddr columns)) :predictors (cdddr columns))))

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

; ---------------------------------------------------------------------------
; A piece of collateral along a path of rates, for a model of a deal
; ---------------------------------------------------------------------------

(define unknown-piece
  '((loan-size 250000) (credit-score 750) (ltv 70) (sato 0) (burnout 0) (investor-share 0) (second-home-share 0) (cash-out-share 0) (refinance-share 0)
    (dti 36) (one-borrower-share 0.5) (mi-percent 0)))
; what the models take a piece of collateral to be like where it does not say (its slot is '()): $250,000 loans, a credit score of 750, 70% loan-to-value, 36%
; debt-to-income, purchases of homes to live in, half of them by one borrower, with no mortgage insurance

(define (piece-value piece slot accessor)
  "The slot of the piece (a collateral-piece), or what unknown-piece says it is if the piece does not say."
  (let ((value (accessor piece)))
    (if (null? value) (cadr (assoc slot unknown-piece)) value)))

(define (scheduled-balance-left wac wam month-numbers)
  "The share of a loan's balance that is left at the start of each of the months (a vector of their numbers, 1 for the first payment), if it pays as scheduled: a
level-payment loan at the wac (percent) with wam payments to go. After k payments it is ((1 + r)^wam - (1 + r)^k) / ((1 + r)^wam - 1) of what it is now, r being the
monthly rate."
  (let ((growth (+ 1.0 (/ wac 1200.0)))
        (paid (- month-numbers 1.0)))
    (if (= wac 0)
        (- 1.0 (/ paid wam))
        (/ (- (expt growth wam) (expt growth paid)) (- (expt growth wam) 1.0)))))

(define (calendar-months first-payment months)
  "The month of the year, 1 to 12, of each month from the first payment: a vector."
  (+ 1 (remainder (+ (- (date-month first-payment) 1) (vector-range 0 months)) 12)))

(define (piece-on-path piece path home-price-growth mortgage-spread)
  "What changes month by month, for each month of the piece (a collateral-piece), 1 to its wam, on the path of rates (a rate-path), as a list of (name . vector):

  incentive_bp    the wac less the rate of a new mortgage at the start of the month, in basis points: the 10-year yield of the path, plus the mortgage spread (percent)
  loan_age        the piece's age, and a month more each month
  loan_size_k     the piece's loan size, in thousands, as it is paid down by its scheduled payments (a loan that prepays is gone; the others are smaller)
  current_ltv     the piece's loan-to-value, as the scheduled payments pay it down and home prices grow (home-price-growth, percent a year)"
  (let* ((months (collateral-piece-wam piece))
         (month-numbers (vector-range 1 (+ months 1)))
         (long-yields (rate-path-long-yields path)))
    (when (< (vector-length long-yields) months)
      (error (format "the path of rates has {} months, and the piece of collateral {}" (vector-length long-yields) months)))
    (let ((mortgage-rates (+ (* 100.0 (vector-take long-yields months)) mortgage-spread))
          (left (scheduled-balance-left (collateral-piece-wac piece) months month-numbers))
          (home-prices (expt (+ 1.0 (/ home-price-growth 100.0)) (/ (- month-numbers 1) 12.0))))
      (list (cons "incentive_bp" (* 100.0 (- (collateral-piece-wac piece) mortgage-rates)))
            (cons "loan_age" (+ 0.0 (collateral-piece-age piece) month-numbers))
            (cons "loan_size_k" (* (/ (piece-value piece 'loan-size collateral-piece-loan-size) 1000.0) left))
            (cons "current_ltv" (/ (* (piece-value piece 'ltv collateral-piece-ltv) left) home-prices))))))

