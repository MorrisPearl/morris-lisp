; stratify_example.lsp
;
; Stratification tables: a big table of loans, cut up into many small
; tables, each with a row per bucket of one column (coupons from 3.0 to 5.0,
; 5.0 to 6.0, ...; ten buckets of loan age; one row per state) and, in each
; row, the loans' count, total balance, share of the pool, and
; balance-weighted averages. See "Stratification tables" in
; lisp_library_reference.md.
;
; The pool here is 5,000 made-up loans, so it runs anywhere. To use real
; data, load the table from SQLite instead, e.g.
;
;   (define loans
;     (with-sqlite (conn "/Users/morris/freddie_data/freddie_sample.db")
;       (sqlite-query conn "SELECT current_actual_upb AS balance, current_interest_rate AS rate,
;                                  loan_age AS age, estimated_ltv AS ltv, orig_dti AS dti
;                           FROM loan_performance
;                           WHERE monthly_reporting_period = '2020-01-01'")))
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py stratify_example.lsp

; --- A made-up pool of loans -------------------------------------------------
(random-seed 1)
(define n 5000)
(define (make-column value) (list->vector (loop repeat n collect (value))))
(define states '("CA" "TX" "FL" "NY" "IL" "WA" "AZ" "NC" "GA" "CO"))

(define loans
  (make-table
    "balance"   (make-column (lambda () (round (random-float 40000 800000))))
    "rate"      (make-column (lambda () (/ (round (* 8 (random-float 2.75 8.25))) 8.0)))   ; eighths
    "age"       (make-column (lambda () (random-int 0 120)))
    "ltv"       (make-column (lambda () (round (random-float 40 97))))
    "fico"      (make-column (lambda () (random-int 600 820)))
    "state"     (make-column (lambda () (list-ref states (random-int 0 (- (length states) 1)))))
    "first-pay" (make-column (lambda () (date-add-months (date 2016 1 1) (random-int 0 107))))))

; --- What each small table shows -----------------------------------------------
; Every table has the bucket, the count of loans, their total balance
; ("total balance", since the weight is the balance column), and its share of
; the pool ("percent"); then these, each averaged by balance.
(define summaries
  '(("rate" weighted-mean "WAC")
    ("age"  weighted-mean "WALA")
    ("ltv"  weighted-mean "LTV")
    ("fico" weighted-mean "FICO")))

; How to show the numbers (see display-table).
(define formats
  '(("total balance" ",.0f") ("percent" ".1%") ("WAC" ".3f") ("WALA" ".1f") ("LTV" ".1f") ("FICO" ".0f")))

; --- The tables ----------------------------------------------------------------
(define tables
  (stratify-all loans
    '(("rate"      (3.0 4.0 5.0 6.0 7.0 8.0))     ; coupon ranges
      ("balance"   (100000 200000 300000 400000 500000 600000 700000))
      ("age"       (equal-count 5))              ; five buckets, 1,000 loans each
      ("ltv"       (equal-weight 4))             ; four buckets, a quarter of the balance each
      ("state"     (top 5))                      ; the five biggest states, then the rest
      ("first-pay" year)                         ; by year of first payment
      (("state" (top 3)) ("rate" (5.0 7.0))))    ; two columns at once
    summaries
    :weight "balance"))

(dolist (table tables)
  (display-table table formats)
  (newline))

; A single table, made on its own:
(display-table (stratify loans '("fico" (660 700 740 780)) summaries :weight "balance") formats)
