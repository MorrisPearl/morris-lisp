; stratify_plot.lsp
;
; A chart of a stratification table (see "Stratification tables" in lisp_library_reference.md): a bar for each bucket's
; share of the whole, and a line over the bars for what the buckets average -- so that a change from bucket to bucket,
; such as a rate that rises with the loans' age, is seen at once, where a table has to be read.
;
; Usage:
;   (plot-stratification table)                              ; the first summary is the line
;   (plot-stratification table :column "avg ltv")            ; another column of the table is the line
;   (plot-stratification table :formats formats)             ; the same formats as display-table's
;
;   (destructuring-bind (bys summaries formats) (stratify-plan loans :weight "balance")
;     (dolist (table (stratify-all loans bys summaries :weight "balance"))
;       (plot-stratification table :formats formats)))        ; a chart for each table of a first look

; The columns of a stratification table that say which bucket a row is in: those before "count".
(define (strata-bucket-names table)
  (let walk ((names (table-column-names table)) (found '()))
    (if (equal? (car names) "count")
        (reverse found)
        (walk (cdr names) (cons (car names) found)))))

; The columns after "percent": the summaries.
(define (strata-summary-names table)
  (cdr (member "percent" (table-column-names table))))

; Each row's bucket as text: with several columns, their buckets with a / between.
(define (strata-labels table bucket-names rows)
  (let ((columns (map (lambda (name) (table-column table name)) bucket-names)))
    (list->vector
      (loop for row from 0 below rows
            collect (string-join (map (lambda (column) (to-string (vector-ref column row))) columns) " / ")))))

; The format that a list of formats gives a column, as display-table takes them: a spec, or #f for none.
(define (strata-format formats name)
  (let ((entry (assoc name formats)))
    (if entry (cadr entry) #f)))

(define (plot-stratification table &key (formats '()) (column #f))
  (let* ((bucket-names (strata-bucket-names table))
         (all-rows (table-row-count table))
         (rows (if (equal? (to-string (vector-ref (table-column table (car bucket-names)) (- all-rows 1))) "total")
                   (- all-rows 1)                       ; not the last row, which is the whole table
                   all-rows))
         (labels (strata-labels table bucket-names rows))
         (shares (vector-slice (table-column table "percent") 0 rows))
         (summaries (strata-summary-names table))
         (line-name (cond (column column)
                          ((null? summaries) #f)
                          (else (car summaries))))
         (bars (list "share" labels shares :bars #t :color "lightsteelblue"))
         (line (and line-name
                    (list line-name labels (vector-slice (table-column table line-name) 0 rows)
                          :line #t :symbol #t :secondary #t :color "firebrick"))))
    (plot-chart (if line (list bars line) (list bars))
                :title (string-join bucket-names " / ")
                :y-label "share of the whole"
                :y-format (or (strata-format formats "percent") ".1%")
                :secondary-label line-name
                :secondary-format (and line-name (strata-format formats line-name))
                :legend "upper left")))
