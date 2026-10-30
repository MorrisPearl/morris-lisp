; stratify_explorer.lsp
;
; A form, in a notebook, for choosing how to stratify a table: a section for each column, which opens when it is
; clicked (an "accordion"), where you choose
;
;   how the column is stratified: not at all, one bucket for each value, the top n values, n buckets of the same
;   count or the same weight, one for each year, or between breakpoints you type;
;
;   what else its table is split by: as many other columns as you like ("and by"), each bucketed as its own section
;   says or in a way of its own -- a table of state, and by rate within each state, and by year within that;
;
;   how it is summarized in the tables of the other columns: by as many functions as you like (an average and a
;   weighted average, say, or the min, the average and the max, or the 10th, 50th and 90th percentiles), each with
;   the heading of its column in the tables and the format it is shown in -- a button adds another, and a x on each
;   takes it away.
;
; It starts from what stratify-plan suggests. Above the sections are the weight column (for the weighted functions,
; and for equal-weight buckets); the summary the charts draw as a line; boxes to tick for charts, for the total row,
; and for showing the tables as grids that sort; the rows to use (conditions on the columns, as many as you like, all
; of which a row must meet); buttons that make the tables and show the code that makes them; and buttons that write
; the tables to CSV files, a Google Sheet, or a report in Markdown. Each section has a button that makes its table
; alone. What is chosen can be saved to a file, and a new form started from it.
;
; Usage, in a notebook:
;   (define explorer (stratify-explorer loans :weight "balance" :name "loans"))
;   explorer                                 ; the form: the value of a cell shows it
;   (stratify-explorer-save explorer "loans_strats.lsp")                 ; what is chosen, to a file
;   (stratify-explorer loans :name "loans" :plan "loans_strats.lsp")     ; a form that starts from it
;   (stratify-explorer-plan explorer)        ; what is chosen, as (bys summaries formats), for stratify-all
;   (stratify-explorer-tables explorer)      ; the tables, as Make the tables makes them

(require "widgets.lsp")

(defstruct stratify-explorer--column
  name kind how count breakpoints
  usual-format      ; the format that suits its numbers, which a new summary gets
  planned           ; the summaries stratify-plan suggests, (function percentile heading format), that it begins with
  (summaries '())   ; a list of stratify-explorer--summary, in order
  rows              ; the box the summaries' rows are in
  (splits '())      ; a list of stratify-explorer--split: the other columns its table is split by, in order
  split-rows)       ; the box their rows are in

(defstruct stratify-explorer--summary
  function percentile heading format (automatic "")   ; automatic: the heading the form wrote, to replace if it changes
  row)              ; the row of its widgets, with the x that takes it away

(defstruct stratify-explorer--split
  column how count breakpoints row)       ; another column a table is split by, and how it is bucketed

(defstruct stratify-explorer--condition
  column test value row)                  ; a condition the rows to use must meet

(defstruct stratify-explorer--state
  table name columns weight charts chart-column total grids
  (conditions '()) condition-rows warning export-name output (accordion '()))

(define stratify-explorer-ways '("hide" "each" "top" "equal-count" "equal-weight" "year" "breakpoints"))
(define stratify-explorer--as-its-section "(as in its section)")

(define stratify-explorer-functions
  '("(none)" "mean" "weighted-mean" "median" "weighted-median" "sum" "min" "max" "stdev" "percentile"
    "weighted-percentile" "mode" "weighted-mode" "representative" "first" "last"))

(define stratify-explorer-tests '("=" "not =" "<" "<=" ">" ">=" "one of" "missing" "not missing"))

(define stratify-explorer--no-weight "(none)")
(define stratify-explorer--first-summary "(first summary)")   ; the chart's line is the tables' first summary, as plot-stratification's is

; ---------------------------------------------------------------------------
; 1. From the widgets to what stratify takes
; ---------------------------------------------------------------------------

(define (stratify-explorer--way how)
  "The form's way of stratifying (one of stratify-explorer-ways), its n, and its breakpoints as text, from a by's how:
each, (top 5), (4.0 5.0 6.0), ..."
  (cond ((symbol? how) (list (symbol->string how) 5 ""))
        ((and (pair? how) (symbol? (car how))) (list (symbol->string (car how)) (cadr how) ""))
        (else (list "breakpoints" 5 (string-join (map (lambda (x) (if (date? x) (date->string x) (number->string x))) how) " ")))))

(define (stratify-explorer--number-text? word)
  (if (regex-match "^[-+]?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][-+]?[0-9]+)?$" word) #t #f))

(define (stratify-explorer--breakpoints name kind text)
  "The breakpoints typed for a column (its name and kind, and the text typed), as a list of numbers, or of dates for a
column of dates, or an error that says what is wrong with them."
  (let ((words (filter (lambda (word) (> (string-length word) 0)) (regex-split "[,\\s]+" text))))
    (when (null? words)
      (error (format "{}: type the breakpoints, such as 4.0 5.0 6.0" name)))
    (map (lambda (word)
           (cond ((equal? kind "date") (string->date word))
                 ((stratify-explorer--number-text? word) (string->number word))
                 (else (error (format "{}: the breakpoints are numbers, and {} is not one" name word)))))
         words)))

(define (stratify-explorer--how-of name kind way count text)
  "A way of stratifying, from the form's choices for it, as stratify takes it: hide, each, year, (top 5), (4.0 5.0), ..."
  (cond ((member way '("hide" "each" "year")) (string->symbol way))
        ((equal? way "breakpoints") (stratify-explorer--breakpoints name kind text))
        (else (list (string->symbol way) count))))

(define (stratify-explorer--how column)
  "How the column's section says to stratify it."
  (stratify-explorer--how-of (stratify-explorer--column-name column) (stratify-explorer--column-kind column)
                             (widget-get (stratify-explorer--column-how column) "value")
                             (widget-get (stratify-explorer--column-count column) "value")
                             (widget-get (stratify-explorer--column-breakpoints column) "value")))

(define (stratify-explorer--find-column state name)
  "The column of the form with this name."
  (let ((found (filter (lambda (column) (equal? (stratify-explorer--column-name column) name))
                       (stratify-explorer--state-columns state))))
    (if (null? found) (error "stratify-explorer: the table has no column" name) (car found))))

(define (stratify-explorer--how-of-split state column split)
  "How a split says its column is bucketed: as in that column's own section, or a way of its own."
  (let* ((name (widget-get (stratify-explorer--split-column split) "value"))
         (other (stratify-explorer--find-column state name))
         (way (widget-get (stratify-explorer--split-how split) "value")))
    (if (equal? way stratify-explorer--as-its-section)
        (let ((how (stratify-explorer--how other)))
          (when (eq? how 'hide)
            (error (format "{}: it is split by {}, which its own section hides: choose how to split by it"
                           (stratify-explorer--column-name column) name)))
          how)
        (stratify-explorer--how-of name (stratify-explorer--column-kind other) way
                                   (widget-get (stratify-explorer--split-count split) "value")
                                   (widget-get (stratify-explorer--split-breakpoints split) "value")))))

(define (stratify-explorer--by state column)
  "What the column's table is stratified by, as stratify takes it -- (column how), or, if it is split by other columns
too, a list of (column how) -- or '() if its section hides it."
  (let ((how (stratify-explorer--how column))
        (splits (stratify-explorer--column-splits column)))
    (cond ((eq? how 'hide) '())
          ((null? splits) (list (stratify-explorer--column-name column) how))
          (else (cons (list (stratify-explorer--column-name column) how)
                      (map (lambda (split)
                             (list (widget-get (stratify-explorer--split-column split) "value")
                                   (stratify-explorer--how-of-split state column split)))
                           splits))))))

(define (stratify-explorer--function summary)
  "The summary's function as stratify takes it -- weighted-mean, or (percentile 10) -- or '() for none."
  (let ((chosen (widget-get (stratify-explorer--summary-function summary) "value")))
    (cond ((equal? chosen "(none)") '())
          ((member chosen '("percentile" "weighted-percentile"))
           (list (string->symbol chosen) (widget-get (stratify-explorer--summary-percentile summary) "value")))
          (else (string->symbol chosen)))))

(define (stratify-explorer--suggested-heading column-name chosen percentile)
  "A heading for a summary that hasn't one: mean rate, wavg rate, rate p10, sum balance, ..."
  (cond ((equal? chosen "mean") (format "mean {}" column-name))
        ((equal? chosen "weighted-mean") (format "wavg {}" column-name))
        ((equal? chosen "median") (format "median {}" column-name))
        ((equal? chosen "weighted-median") (format "wmedian {}" column-name))
        ((equal? chosen "percentile") (format "{} p{}" column-name (number->string percentile)))
        ((equal? chosen "weighted-percentile") (format "{} wp{}" column-name (number->string percentile)))
        (else (format "{} {}" chosen column-name))))

; ---------------------------------------------------------------------------
; 2. The rows to use
; ---------------------------------------------------------------------------

(define (stratify-explorer--value-of-condition state condition)
  "The value a condition compares with, as an expression: a number for a column of numbers, a date for one of dates,
text otherwise; a list of them, for one of. An error if a number or a date is not one."
  (let* ((name (widget-get (stratify-explorer--condition-column condition) "value"))
         (kind (stratify-explorer--column-kind (stratify-explorer--find-column state name)))
         (text (widget-get (stratify-explorer--condition-value condition) "value"))
         (value-of (lambda (word)
                     (cond ((member kind '("integer" "float"))
                            (if (stratify-explorer--number-text? word)
                                (string->number word)
                                (error (format "the rows to use: {} is a column of numbers, and {} is not one" name word))))
                           ((equal? kind "date")
                            (let ((day (string->date word)))
                              (list 'date (date-year day) (date-month day) (date-day day))))
                           (else word)))))
    (if (equal? (widget-get (stratify-explorer--condition-test condition) "value") "one of")
        (map value-of (filter (lambda (word) (> (string-length word) 0)) (map string-trim (string-split text ","))))
        (value-of (string-trim text)))))

(define (stratify-explorer--condition-expression state condition table)
  "A condition as an expression of a mask of the rows that meet it: (> (table-column table \"balance\") 0), with table
the expression of the table."
  (let* ((name (widget-get (stratify-explorer--condition-column condition) "value"))
         (kind (stratify-explorer--column-kind (stratify-explorer--find-column state name)))
         (column (list 'table-column table name))
         (test (widget-get (stratify-explorer--condition-test condition) "value"))
         (missing (if (member kind '("integer" "float" "date" "mixed"))
                      (list 'vector-nan? column)
                      (list '= column ""))))
    (cond ((equal? test "missing") missing)
          ((equal? test "not missing") (list 'vector-not missing))
          ((equal? test "one of")
           (let ((values (stratify-explorer--value-of-condition state condition)))
             (when (null? values)
               (error (format "the rows to use: type what {} is one of, with commas between them" name)))
             (if (null? (cdr values))
                 (list '= column (car values))
                 (cons 'vector-or (map (lambda (value) (list '= column value)) values)))))
          ((equal? test "not =") (list 'vector-not (list '= column (stratify-explorer--value-of-condition state condition))))
          (else (list (string->symbol test) column (stratify-explorer--value-of-condition state condition))))))

(define (stratify-explorer--filled-in? condition)
  "Whether a condition says something yet: it is missing or not missing, or a value has been typed for it. One that
hasn't is passed over."
  (or (member (widget-get (stratify-explorer--condition-test condition) "value") '("missing" "not missing"))
      (> (string-length (string-trim (widget-get (stratify-explorer--condition-value condition) "value"))) 0)))

(define (stratify-explorer--filter-expression state table)
  "An expression of the mask of the rows that meet every condition, with table the expression of the table; '() if
there are none."
  (let ((masks (map (lambda (condition) (stratify-explorer--condition-expression state condition table))
                    (filter stratify-explorer--filled-in? (stratify-explorer--state-conditions state)))))
    (cond ((null? masks) '())
          ((null? (cdr masks)) (car masks))
          (else (cons 'vector-and masks)))))

(define (stratify-explorer--rows state)
  "The rows of the table that the conditions say to use: the table, filtered."
  (let ((mask (stratify-explorer--filter-expression state 'stratify-explorer--table)))
    (if (null? mask)
        (stratify-explorer--state-table state)
        (table-filter (stratify-explorer--state-table state)
                      (eval (list 'let (list (list 'stratify-explorer--table (list 'quote (stratify-explorer--state-table state))))
                                  mask))))))

; ---------------------------------------------------------------------------
; 3. The widgets
; ---------------------------------------------------------------------------

(define (stratify-explorer--layout width)
  (make-widget "Layout" :width width))

(define (stratify-explorer--button label action output &key (style ""))
  "A button as wide as its label that calls (action), with what it displays in output; an error is shown there as its
message alone (the form's widgets would make a traceback too long to read)."
  (let ((button (widget-button label
                               (lambda ()
                                 (catch-error (action) (message)
                                   (display (format "{}\n" message))))
                               :output output :button-style style)))
    (widget-set! button "layout" (make-widget "Layout" :width "auto" :align-self "flex-start"))   ; (not stretched across a column)
    button))

(define (stratify-explorer--x tooltip)
  "A small button that takes a row away."
  (make-widget "Button" :description "x" :tooltip tooltip :layout (stratify-explorer--layout "36px")))

(define (stratify-explorer--profile-line profile row)
  "A line about the column, from table-profile's row for it: its kind, how many values are distinct and missing, and
its range."
  (let* ((cell (lambda (name) (vector-ref (table-column profile name) row)))
         (kind (cell "kind")))
    (format "<i>{}; {:,} distinct, {:,} missing{}</i>" kind (cell "distinct") (cell "missing")
            (cond ((member kind '("integer" "float"))
                   (if (= (cell "min") (cell "min")) (format "; from {:,} to {:,}" (cell "min") (cell "max")) ""))
                  ((> (string-length (cell "range")) 0) (format "; {}" (cell "range")))
                  (else "")))))

(define (stratify-explorer--way-widgets ways way count text)
  "The widgets of a way of bucketing: the way, its n (shown for the ways that have one), and its breakpoints (shown for
breakpoints), as a list."
  (let* ((choice (make-widget "Dropdown" :options ways :value way :layout (stratify-explorer--layout "170px")))
         (n (make-widget "IntText" :value count :description "n" :layout (stratify-explorer--layout "120px")))
         (breakpoints (make-widget "Text" :value text :placeholder "4.0 5.0 6.0" :layout (stratify-explorer--layout "260px")))
         (show (lambda (chosen)
                 (widget-visible n (if (member chosen '("top" "equal-count" "equal-weight")) #t #f))
                 (widget-visible breakpoints (equal? chosen "breakpoints")))))
    (show way)
    (widget-on-change choice "value" show)
    (list choice n breakpoints)))

(define (stratify-explorer--summary-widgets column-name function percentile-value heading format-text usual-format)
  "The widgets of one summary of a column: its function, the percentile (for the percentile functions), its heading,
and its format. usual-format is the format that suits the column's numbers, which a summary gets when its function is
chosen, if its format is empty."
  (let* ((choice (make-widget "Dropdown" :options stratify-explorer-functions :value function
                              :layout (stratify-explorer--layout "190px")))
         (percentile (make-widget "FloatText" :value percentile-value :description "p" :layout (stratify-explorer--layout "120px")))
         (heading-box (make-widget "Text" :value heading :placeholder "heading" :layout (stratify-explorer--layout "200px")))
         (format-box (make-widget "Text" :value format-text :placeholder ",.2f" :layout (stratify-explorer--layout "110px")))
         (summary (make-stratify-explorer--summary :function choice :percentile percentile :heading heading-box
                                                   :format format-box :automatic heading
                                                   :row (widget-row choice percentile heading-box format-box)))
         (suggest (lambda ()
                    ; a new function gets a new heading, unless the user has typed one of their own
                    (let ((typed (widget-get heading-box "value")))
                      (when (or (equal? typed "") (equal? typed (stratify-explorer--summary-automatic summary)))
                        (let* ((chosen (widget-get choice "value"))
                               (suggested (if (equal? chosen "(none)")
                                              ""
                                              (stratify-explorer--suggested-heading column-name chosen
                                                                                    (widget-get percentile "value")))))
                          (stratify-explorer--summary-automatic-set! summary suggested)
                          (widget-set! heading-box "value" suggested))))
                    (when (and (equal? (widget-get format-box "value") "")
                               (not (equal? (widget-get choice "value") "(none)")))
                      (widget-set! format-box "value" usual-format)))))
    (widget-visible percentile (string-contains? function "percentile"))
    (widget-on-change choice "value"
                      (lambda (chosen)
                        (widget-visible percentile (string-contains? chosen "percentile"))
                        (suggest)))
    (widget-on-change percentile "value" (lambda (p) (suggest)))
    summary))

(define (stratify-explorer--show-rows box items row-of)
  "Put the rows of the items in the box, in order."
  (widget-set! box "children" (map row-of items)))

(define (stratify-explorer--add-summary state column function percentile heading format-text)
  "Add a summary to the column, at the end -- its function, percentile, heading and format -- with a x that takes it
away, and show it."
  (let* ((summary (stratify-explorer--summary-widgets (stratify-explorer--column-name column) function percentile heading
                                                      format-text (stratify-explorer--column-usual-format column)))
         (remove (stratify-explorer--x "take this summary away"))
         (row (stratify-explorer--summary-row summary))
         (show (lambda () (stratify-explorer--show-rows (stratify-explorer--column-rows column)
                                                        (stratify-explorer--column-summaries column)
                                                        stratify-explorer--summary-row))))
    (widget-set! row "children" (append (widget-get row "children") (list remove)))
    (widget-on-change (stratify-explorer--summary-function summary) "value" (lambda (chosen) (stratify-explorer--changed state)))
    (widget-on-change (stratify-explorer--summary-heading summary) "value" (lambda (heading) (stratify-explorer--changed state)))
    (widget-on-click remove
                     (lambda ()
                       (stratify-explorer--column-summaries-set!
                         column (filter (lambda (other) (not (eq? other summary))) (stratify-explorer--column-summaries column)))
                       (show)
                       (stratify-explorer--changed state))
                     :output (stratify-explorer--state-output state))
    (stratify-explorer--column-summaries-set! column (append (stratify-explorer--column-summaries column) (list summary)))
    (show)
    (stratify-explorer--changed state)
    summary))

(define (stratify-explorer--add-split state column other way count text)
  "Split the column's table by another column too, at the end -- the other column's name, and how it is bucketed --
with a x that takes it away, and show it."
  (let* ((others (filter (lambda (name) (not (equal? name (stratify-explorer--column-name column))))
                         (map stratify-explorer--column-name (stratify-explorer--state-columns state))))
         (choice (make-widget "Dropdown" :options others :value (if (member other others) other (car others))
                              :layout (stratify-explorer--layout "220px")))
         (way-widgets (stratify-explorer--way-widgets (cons stratify-explorer--as-its-section stratify-explorer-ways)
                                                      way count text))
         (remove (stratify-explorer--x "don't split by this column"))
         (split (make-stratify-explorer--split :column choice :how (first way-widgets) :count (second way-widgets)
                                               :breakpoints (third way-widgets)
                                               :row (apply widget-row (append (list (make-widget "HTML" :value "and by") choice)
                                                                              way-widgets (list remove)))))
         (show (lambda () (stratify-explorer--show-rows (stratify-explorer--column-split-rows column)
                                                        (stratify-explorer--column-splits column)
                                                        stratify-explorer--split-row))))
    (dolist (widget (list choice (first way-widgets) (second way-widgets) (third way-widgets)))
      (widget-on-change widget "value" (lambda (value) (stratify-explorer--changed state))))
    (widget-on-click remove
                     (lambda ()
                       (stratify-explorer--column-splits-set!
                         column (filter (lambda (other) (not (eq? other split))) (stratify-explorer--column-splits column)))
                       (show)
                       (stratify-explorer--changed state))
                     :output (stratify-explorer--state-output state))
    (stratify-explorer--column-splits-set! column (append (stratify-explorer--column-splits column) (list split)))
    (show)
    (stratify-explorer--changed state)
    split))

(define (stratify-explorer--add-condition state column test value)
  "Add a condition on the rows to use -- a column, a test, and the value it is tested against -- with a x that takes
it away, and show it."
  (let* ((names (map stratify-explorer--column-name (stratify-explorer--state-columns state)))
         (choice (make-widget "Dropdown" :options names :value (if (member column names) column (car names))
                              :layout (stratify-explorer--layout "220px")))
         (test-choice (make-widget "Dropdown" :options stratify-explorer-tests :value test
                                   :layout (stratify-explorer--layout "120px")))
         (value-box (make-widget "Text" :value value :placeholder "a value; for one of, values with commas between"
                                 :layout (stratify-explorer--layout "320px")))
         (remove (stratify-explorer--x "take this condition away"))
         (condition (make-stratify-explorer--condition :column choice :test test-choice :value value-box
                                                       :row (widget-row choice test-choice value-box remove)))
         (show (lambda () (stratify-explorer--show-rows (stratify-explorer--state-condition-rows state)
                                                        (stratify-explorer--state-conditions state)
                                                        stratify-explorer--condition-row)))
         (show-value (lambda (chosen) (widget-visible value-box (not (member chosen '("missing" "not missing")))))))
    (show-value test)
    (widget-on-change test-choice "value" show-value)
    (widget-on-click remove
                     (lambda ()
                       (stratify-explorer--state-conditions-set!
                         state (filter (lambda (other) (not (eq? other condition))) (stratify-explorer--state-conditions state)))
                       (show))
                     :output (stratify-explorer--state-output state))
    (stratify-explorer--state-conditions-set! state (append (stratify-explorer--state-conditions state) (list condition)))
    (show)
    condition))

(define (stratify-explorer--section state column profile row)
  "The widgets in a column's section of the accordion, as one box: a line about the column; how it is stratified, and
what else its table is split by; its summaries; and a button that makes its table alone."
  (let ((way-widgets (list (stratify-explorer--column-how column) (stratify-explorer--column-count column)
                           (stratify-explorer--column-breakpoints column)))
        (output (stratify-explorer--state-output state)))
    (stratify-explorer--column-rows-set! column (widget-column))
    (stratify-explorer--column-split-rows-set! column (widget-column))
    (dolist (planned (if (null? (stratify-explorer--column-planned column))
                         (list (list "(none)" 10 "" ""))
                         (stratify-explorer--column-planned column)))
      (apply stratify-explorer--add-summary state column planned))
    (widget-column
      (make-widget "HTML" :value (stratify-explorer--profile-line profile row))
      (make-widget "HTML" :value "<b>Stratify by this column</b>")
      (apply widget-row way-widgets)
      (stratify-explorer--column-split-rows column)
      (stratify-explorer--button "+ and by another column"
                                 (lambda () (stratify-explorer--add-split state column "" stratify-explorer--as-its-section 5 ""))
                                 output)
      (make-widget "HTML" :value "<b>Summarize it in the other tables</b> (function, heading, format)")
      (stratify-explorer--column-rows column)
      (stratify-explorer--button "+ add a summary" (lambda () (stratify-explorer--add-summary state column "(none)" 10 "" ""))
                                 output)
      (stratify-explorer--button "Make this table"
                                 (lambda () (widget-clear output) (stratify-explorer--make-tables state (list column)))
                                 output :style "info"))))

(define (stratify-explorer--title state column)
  "A column's title in the accordion: its name, how it is stratified, what else it is split by, and how it is
summarized."
  (let* ((way (widget-get (stratify-explorer--column-how column) "value"))
         (count (widget-get (stratify-explorer--column-count column) "value"))
         (by (cond ((member way '("top" "equal-count" "equal-weight")) (format "{} {}" way count))
                   ((equal? way "breakpoints") (format "at {}" (widget-get (stratify-explorer--column-breakpoints column) "value")))
                   (else way)))
         (splits (map (lambda (split) (widget-get (stratify-explorer--split-column split) "value"))
                      (stratify-explorer--column-splits column)))
         (functions (filter (lambda (name) (not (equal? name "(none)")))
                            (map (lambda (summary) (widget-get (stratify-explorer--summary-function summary) "value"))
                                 (stratify-explorer--column-summaries column)))))
    (format "{}: {}{}{}" (stratify-explorer--column-name column) by
            (if (or (null? splits) (equal? way "hide")) "" (format ", and by {}" (string-join splits ", ")))
            (if (null? functions) "" (format "; {}" (string-join functions ", "))))))

(define (stratify-explorer--usual-format name kind plan-summaries plan-formats)
  "The format that suits a column's numbers: the one stratify-plan gave its average, or ',.2f' for numbers it didn't
summarize, or '' for a column that isn't numbers."
  (let ((found (and (pair? plan-summaries) (> (length (car plan-summaries)) 2)
                    (assoc (caddr (car plan-summaries)) plan-formats))))
    (cond (found (cadr found))
          ((member kind '("integer" "float")) ",.2f")
          (else ""))))

(define (stratify-explorer--column-of name kind plan-by plan-summaries plan-formats)
  "The widgets of one column, with what the plan says for it to begin with. Its summaries are added when its section is
made (stratify-explorer--section)."
  (destructuring-bind (way count breakpoint-text) (stratify-explorer--way (if (pair? plan-by) (cadr plan-by) 'hide))
    (let ((way-widgets (stratify-explorer--way-widgets stratify-explorer-ways way count breakpoint-text)))
      (make-stratify-explorer--column
        :name name :kind kind
        :how (first way-widgets) :count (second way-widgets) :breakpoints (third way-widgets)
        :usual-format (stratify-explorer--usual-format name kind plan-summaries plan-formats)
        :planned (map (lambda (planned)
                        (let* ((function (cadr planned))
                               (heading (if (> (length planned) 2) (caddr planned) ""))
                               (found (assoc heading plan-formats)))
                          (list (if (pair? function) (symbol->string (car function)) (symbol->string function))
                                (if (pair? function) (cadr function) 10)
                                heading (if found (cadr found) ""))))
                      plan-summaries)))))

; ---------------------------------------------------------------------------
; 4. The form
; ---------------------------------------------------------------------------

(define (stratify-explorer table &key (weight '()) (name "table") (plan '()))
  "A form for choosing how to stratify the table: a section for each column -- how it is stratified, what else its
table is split by, and the ways it is summarized in the other tables, with their headings and formats -- which starts
from what stratify-plan suggests (with :weight, the weight column, if there is one), or from :plan, what a form had
chosen: a file stratify-explorer-save wrote, or stratify-explorer-settings' list. Above the sections are the weight
column, the charts' line, boxes for charts, the total row and grids, the rows to use, and buttons that make the tables,
show the code that makes them (with :name, \"table\", for the table), and write them out. It is a widget: the value of
a cell shows it. stratify-explorer-plan reads what is chosen."
  (let* ((stratify-plan-of (if (null? weight) (stratify-plan table) (stratify-plan table :weight weight)))
         (profile (table-profile table))
         (names (table-column-names table))
         (kind-of (lambda (column)
                    (vector-ref (table-column profile "kind") (vector-ref (vector-positions (table-column profile "column") (vector column)) 0))))
         (numeric (filter (lambda (column) (member (kind-of column) '("integer" "float"))) names))
         (columns (map (lambda (column)
                         (stratify-explorer--column-of column (kind-of column)
                                                       (assoc column (first stratify-plan-of))
                                                       (filter (lambda (summary) (equal? (car summary) column)) (second stratify-plan-of))
                                                       (third stratify-plan-of)))
                       names))
         (output (widget-output))
         (state (make-stratify-explorer--state
                  :table table :name name :columns columns
                  :weight (make-widget "Dropdown" :options (cons stratify-explorer--no-weight numeric)
                                       :value (if (null? weight) stratify-explorer--no-weight weight) :description "weight")
                  :chart-column (make-widget "Dropdown" :options (list stratify-explorer--first-summary)
                                             :value stratify-explorer--first-summary :description "chart line")
                  :charts (make-widget "Checkbox" :value #f :description "charts")
                  :total (make-widget "Checkbox" :value #t :description "total row")
                  :grids (make-widget "Checkbox" :value #f :description "grids (that sort)")
                  :condition-rows (widget-column)
                  :warning (make-widget "HTML" :value "")
                  :export-name (make-widget "Text" :value (format "{} strata" name) :description "name"
                                            :layout (stratify-explorer--layout "300px"))
                  :output output))
         (accordion (make-widget "Accordion"
                                 :children (loop for column in columns for row from 0
                                                 collect (stratify-explorer--section state column profile row))))
         (button (lambda (label action style)
                   (stratify-explorer--button label (lambda () (widget-clear output) (action)) output :style style)))
         (form (widget-column
                 (widget-row (stratify-explorer--state-weight state) (stratify-explorer--state-chart-column state)
                             (stratify-explorer--state-charts state) (stratify-explorer--state-total state)
                             (stratify-explorer--state-grids state))
                 (make-widget "HTML" :value "<b>The rows to use</b> (a row must meet every condition; none: every row)")
                 (stratify-explorer--state-condition-rows state)
                 (stratify-explorer--button "+ add a condition"
                                            (lambda () (stratify-explorer--add-condition state (car names) "=" "")) output)
                 (widget-row (button "Make the tables"
                                     (lambda () (stratify-explorer--make-tables state (stratify-explorer--state-columns state)))
                                     "primary")
                             (button "Show the code" (lambda () (display (stratify-explorer-code-of state))) ""))
                 (widget-row (stratify-explorer--state-export-name state)
                             (button "Write CSV files" (lambda () (stratify-explorer--write-csv-files state)) "")
                             (button "Write a Google Sheet" (lambda () (stratify-explorer--write-google-sheet state)) "")
                             (button "Write a report" (lambda () (stratify-explorer--write-report state)) ""))
                 (stratify-explorer--state-warning state)
                 accordion
                 output)))
    (stratify-explorer--state-accordion-set! state accordion)
    (dolist (column columns)
      (dolist (widget (list (stratify-explorer--column-how column) (stratify-explorer--column-count column)
                            (stratify-explorer--column-breakpoints column)))
        (widget-on-change widget "value" (lambda (value) (stratify-explorer--changed state)))))
    (unless (null? plan)
      (stratify-explorer--apply-settings state (if (string? plan) (read-from-string (read-text-file plan)) plan)))
    (stratify-explorer--changed state)
    (widget-set-tag! form state)
    form))

; ---------------------------------------------------------------------------
; 5. Keeping the form up to date
; ---------------------------------------------------------------------------

(define (stratify-explorer--summary-headings state)
  "The headings of the summaries the form has now, in order: the columns that the tables have besides their counts."
  (apply append
         (map (lambda (column)
                (map (lambda (summary) (widget-get (stratify-explorer--summary-heading summary) "value"))
                     (filter (lambda (summary)
                               (and (not (equal? (widget-get (stratify-explorer--summary-function summary) "value") "(none)"))
                                    (not (equal? (widget-get (stratify-explorer--summary-heading summary) "value") ""))))
                             (stratify-explorer--column-summaries column))))
              (stratify-explorer--state-columns state))))

(define (stratify-explorer--repeated items)
  "The items that are in the list more than once, each once, in the order they first come."
  (let ((seen '()) (twice '()))
    (dolist (item items)
      (if (member item seen)
          (unless (member item twice) (push item twice))
          (push item seen)))
    (reverse twice)))

(define (stratify-explorer--changed state)
  "Something on the form has changed: say what is chosen in the sections' titles, offer the summaries there are as the
chart's line, and warn of two summaries with one heading. (While the sections are being made there is no accordion
yet, and nothing to do.)"
  (let ((accordion (stratify-explorer--state-accordion state)))
    (unless (null? accordion)
      (widget-set! accordion "titles" (map (lambda (column) (stratify-explorer--title state column))
                                           (stratify-explorer--state-columns state)))
      (stratify-explorer--offer-chart-columns state)
      (let ((repeated (stratify-explorer--repeated (stratify-explorer--summary-headings state))))
        (widget-set! (stratify-explorer--state-warning state) "value"
                     (if (null? repeated)
                         ""
                         (format "<span style=\"color:#b00020\">Two summaries have the heading {}: give one a heading of its own.</span>"
                                 (string-join (map (lambda (heading) (format "\"{}\"" heading)) repeated) ", "))))))))

(define (stratify-explorer--offer-chart-columns state)
  "Make the choices of the chart's line the summaries the form has now: the first summary, as plot-stratification's own
line is, and each heading. The one chosen stays chosen if it is still there."
  (let* ((choice (stratify-explorer--state-chart-column state))
         (chosen (widget-get choice "value"))
         (options (cons stratify-explorer--first-summary (stratify-explorer--repeated-out (stratify-explorer--summary-headings state)))))
    (unless (equal? (widget-get choice "options") options)
      (widget-set! choice "options" options)
      (widget-set! choice "value" (if (member chosen options) chosen stratify-explorer--first-summary)))))

(define (stratify-explorer--repeated-out items)
  "The list with each item once, in the order they first come."
  (let ((seen '()))
    (dolist (item items)
      (unless (member item seen) (push item seen)))
    (reverse seen)))

; ---------------------------------------------------------------------------
; 6. What is chosen, and the tables
; ---------------------------------------------------------------------------

(define (stratify-explorer--state-of explorer who)
  (let ((state (widget-tag explorer)))
    (unless (stratify-explorer--state? state)
      (error (format "{}: that is not a form that stratify-explorer made" who)))
    state))

(define (stratify-explorer--weight-of state)
  (let ((chosen (widget-get (stratify-explorer--state-weight state) "value")))
    (if (equal? chosen stratify-explorer--no-weight) '() chosen)))

(define (stratify-explorer--plan-of state columns)
  "What the form says for these of its columns, as (bys summaries formats), the arguments of stratify-all and
display-table. The summaries are all the form's: they are columns of every table. A function or a way that needs a
weight, without one, is an error that says which column."
  (let* ((weight (stratify-explorer--weight-of state))
         (summaries '())
         (formats '())
         (bys (filter (lambda (by) (not (null? by))) (map (lambda (column) (stratify-explorer--by state column)) columns))))
    (when (null? weight)
      (dolist (by bys)
        (dolist (one (if (pair? (car by)) by (list by)))
          (when (and (pair? (cadr one)) (eq? (car (cadr one)) 'equal-weight))
            (error (format "{}: equal-weight buckets need a weight column: choose one above" (car one)))))))
    (dolist (column (stratify-explorer--state-columns state))
      (let ((name (stratify-explorer--column-name column)))
        (dolist (summary (stratify-explorer--column-summaries column))
          (let ((function (stratify-explorer--function summary))
                (heading (widget-get (stratify-explorer--summary-heading summary) "value"))
                (format-text (widget-get (stratify-explorer--summary-format summary) "value")))
            (unless (null? function)
              (let ((function-name (symbol->string (if (pair? function) (car function) function))))
                (when (and (null? weight) (string-starts-with? function-name "weighted"))
                  (error (format "{}: {} needs a weight column: choose one above" name function-name)))
                (let ((heading (if (equal? heading "")
                                   (stratify-explorer--suggested-heading name function-name (if (pair? function) (cadr function) 0))
                                   heading)))
                  (push (list name function heading) summaries)
                  (unless (equal? format-text "")
                    (push (list heading format-text) formats)))))))))
    (list bys (reverse summaries)
          (append '(("count" ",d") ("percent" ".1%"))
                  (if (null? weight) '() (list (list (format "total_{}" weight) ",.0f")))
                  (reverse formats)))))

(define (stratify-explorer-plan explorer)
  "What the form made by stratify-explorer says now, as (bys summaries formats): the arguments of stratify-all (with the
weight of stratify-explorer-weight) and the formats of display-table."
  (let ((state (stratify-explorer--state-of explorer "stratify-explorer-plan")))
    (stratify-explorer--plan-of state (stratify-explorer--state-columns state))))

(define (stratify-explorer-weight explorer)
  "The weight column the form says, or '() for none."
  (stratify-explorer--weight-of (stratify-explorer--state-of explorer "stratify-explorer-weight")))

(define (stratify-explorer-rows explorer)
  "The rows of the table that the form's conditions say to use."
  (stratify-explorer--rows (stratify-explorer--state-of explorer "stratify-explorer-rows")))

(define (stratify-explorer--total? state)
  (widget-get (stratify-explorer--state-total state) "value"))

(define (stratify-explorer--tables-of state columns)
  "The tables of these of the form's columns, as the form says."
  (destructuring-bind (bys summaries formats) (stratify-explorer--plan-of state columns)
    (let ((weight (stratify-explorer--weight-of state))
          (rows (stratify-explorer--rows state))
          (total (stratify-explorer--total? state)))
      (when (= (table-row-count rows) 0)
        (error "No row meets the conditions of the rows to use"))
      (if (null? weight)
          (stratify-all rows bys summaries :total total)
          (stratify-all rows bys summaries :weight weight :total total)))))

(define (stratify-explorer-tables explorer)
  "The stratification tables that the form says to make, as a list, as Make the tables makes them."
  (let ((state (stratify-explorer--state-of explorer "stratify-explorer-tables")))
    (stratify-explorer--tables-of state (stratify-explorer--state-columns state))))

(define (stratify-explorer--chart-column-of state)
  "The heading of the summary the charts' line is of, or '() for the first summary."
  (let ((chosen (widget-get (stratify-explorer--state-chart-column state) "value")))
    (if (equal? chosen stratify-explorer--first-summary) '() chosen)))

(define (stratify-explorer-chart-column explorer)
  "The heading of the summary the form's charts draw as a line, or '() for the first summary."
  (stratify-explorer--chart-column-of (stratify-explorer--state-of explorer "stratify-explorer-chart-column")))

(define (stratify-explorer--make-tables state columns)
  "Make the tables of these columns that the form says, and show each: as a table, or as a grid that sorts (if grids
is ticked), and its chart (if charts is ticked)."
  (let ((formats (third (stratify-explorer--plan-of state columns)))
        (tables (stratify-explorer--tables-of state columns))
        (line (stratify-explorer--chart-column-of state))
        (rows (table-row-count (stratify-explorer--rows state)))
        (all (table-row-count (stratify-explorer--state-table state))))
    (cond ((null? tables) (display "It is hidden: choose how to stratify it.\n"))
          ((< rows all) (display (format "{:,} of the {:,} rows meet the conditions.\n" rows all))))
    (dolist (table tables)
      (if (widget-get (stratify-explorer--state-grids state) "value")
          (display-widget (table-grid table :editable #f))
          (display-table table formats))
      (when (widget-get (stratify-explorer--state-charts state) "value")
        (if (null? line)
            (plot-stratification table :formats formats)
            (plot-stratification table :formats formats :column line)))
      (newline))
    tables))

(define (stratify-explorer-code-of state)
  "The code that makes the tables the form says, as text: the rows to use, the stratify-all call, and display-table for
each table (and its chart, if charts is ticked)."
  (destructuring-bind (bys summaries formats) (stratify-explorer--plan-of state (stratify-explorer--state-columns state))
    (let* ((weight (stratify-explorer--weight-of state))
           (name (stratify-explorer--state-name state))
           (mask (stratify-explorer--filter-expression state (string->symbol name)))
           (line (stratify-explorer--chart-column-of state))
           (quoted (lambda (items indent) (string-join (map (lambda (item) (format "{}" item)) items) (string-append "\n" indent))))
           (mask-text (cond ((null? mask) "")
                            ((member (car mask) '(vector-and))
                             (format "(vector-and {})" (quoted (cdr mask) "                ")))
                            (else (format "{}" mask)))))
      (format "{}(define strats\n  (stratify-all {}\n    '({})\n    '({}){}{}))\n(define formats\n  '({}))\n(dolist (table strats)\n  (display-table table formats){})\n"
              (if (null? mask) "" (format "(define rows\n  (table-filter {}\n    {}))\n" name mask-text))
              (if (null? mask) name "rows")
              (quoted bys "      ") (quoted summaries "      ")
              (if (null? weight) "" (format "\n    :weight \"{}\"" weight))
              (if (stratify-explorer--total? state) "" "\n    :total #f")
              (quoted formats "    ")
              (cond ((not (widget-get (stratify-explorer--state-charts state) "value")) "")
                    ((null? line) "\n  (plot-stratification table :formats formats)")
                    (else (format "\n  (plot-stratification table :formats formats :column \"{}\")" line)))))))

(define (stratify-explorer-code explorer)
  "The code that makes the tables the form says, as text: the rows to use, a stratify-all call, and display-table for
each table."
  (stratify-explorer-code-of (stratify-explorer--state-of explorer "stratify-explorer-code")))

; ---------------------------------------------------------------------------
; 7. Writing the tables out
; ---------------------------------------------------------------------------

(define (stratify-explorer--export-name state)
  (let ((name (string-trim (widget-get (stratify-explorer--state-export-name state) "value"))))
    (if (equal? name "") (format "{} strata" (stratify-explorer--state-name state)) name)))

(define (stratify-explorer--file-name text)
  "Text made fit for a file's name: what isn't a letter, a digit, a dot or a hyphen becomes _."
  (regex-replace "[^A-Za-z0-9.\\-]+" text "_"))

(define (stratify-explorer--write-csv-files state)
  "Write each table to a CSV file of its own, named for the export name and the table's first column, and say which."
  (let ((tables (stratify-explorer--tables-of state (stratify-explorer--state-columns state)))
        (base (stratify-explorer--file-name (stratify-explorer--export-name state))))
    (dolist (table tables)
      (let ((path (format "{}-{}.csv" base (stratify-explorer--file-name (string-join (map car (stratify-explorer--by-columns table)) "-")))))
        (write-columns-csv path table)
        (display (format "Wrote {}\n" path))))
    tables))

(define (stratify-explorer--by-columns table)
  "The columns a stratification table is of: those before its count, as (name . vector)."
  (let loop ((columns table) (found '()))
    (if (or (null? columns) (equal? (car (car columns)) "count"))
        (reverse found)
        (loop (cdr columns) (cons (car columns) found)))))

(define (stratify-explorer--write-google-sheet state)
  "Write the tables to a new Google Sheet, a tab for each, called by the export name, with the tables' formats, and say
where it is. It needs creds, the credentials file's path (from init.lsp), and a Google sign-in (google-login)."
  (let* ((columns (stratify-explorer--state-columns state))
         (formats (third (stratify-explorer--plan-of state columns)))
         (tables (stratify-explorer--tables-of state columns))
         (address (apply google-sheet (append (list creds (stratify-explorer--export-name state) formats) tables))))
    (display (format "Wrote {}\n" address))
    address))

(define (stratify-explorer--report-text state)
  "The tables as a report in Markdown: a title, the rows used, and a heading and a table for each."
  (let* ((columns (stratify-explorer--state-columns state))
         (formats (third (stratify-explorer--plan-of state columns)))
         (tables (stratify-explorer--tables-of state columns))
         (mask (stratify-explorer--filter-expression state (string->symbol (stratify-explorer--state-name state))))
         (weight (stratify-explorer--weight-of state)))
    (apply string-append
           (format "# {}\n\n{:,} rows of {}{}{}.\n\n" (stratify-explorer--export-name state)
                   (table-row-count (stratify-explorer--rows state)) (stratify-explorer--state-name state)
                   (if (null? mask) "" (format ", those that meet `{}`" mask))
                   (if (null? weight) "" (format "; weighted by {}" weight)))
           (map (lambda (table)
                  (format "## By {}\n\n{}\n\n" (string-join (map car (stratify-explorer--by-columns table)) ", and by ")
                          (table-markdown table formats)))
                tables))))

(define (stratify-explorer--write-report state)
  "Write the tables to a report in Markdown, named by the export name, and say where."
  (let ((path (format "{}.md" (stratify-explorer--file-name (stratify-explorer--export-name state)))))
    (write-text-file path (stratify-explorer--report-text state))
    (display (format "Wrote {}\n" path))
    path))

; ---------------------------------------------------------------------------
; 8. Saving what is chosen, and starting from it
; ---------------------------------------------------------------------------

(define (stratify-explorer--settings-of state)
  "Everything the form says, as a list that read-from-string reads back: see stratify-explorer-settings."
  (let ((value (lambda (widget) (widget-get widget "value"))))
    (list (list "weight" (value (stratify-explorer--state-weight state)))
          (list "chart-line" (value (stratify-explorer--state-chart-column state)))
          (list "charts" (value (stratify-explorer--state-charts state)))
          (list "total" (value (stratify-explorer--state-total state)))
          (list "grids" (value (stratify-explorer--state-grids state)))
          (list "export" (value (stratify-explorer--state-export-name state)))
          (list "conditions"
                (map (lambda (condition)
                       (list (value (stratify-explorer--condition-column condition))
                             (value (stratify-explorer--condition-test condition))
                             (value (stratify-explorer--condition-value condition))))
                     (stratify-explorer--state-conditions state)))
          (list "columns"
                (map (lambda (column)
                       (list (stratify-explorer--column-name column)
                             (value (stratify-explorer--column-how column))
                             (value (stratify-explorer--column-count column))
                             (value (stratify-explorer--column-breakpoints column))
                             (map (lambda (split)
                                    (list (value (stratify-explorer--split-column split)) (value (stratify-explorer--split-how split))
                                          (value (stratify-explorer--split-count split)) (value (stratify-explorer--split-breakpoints split))))
                                  (stratify-explorer--column-splits column))
                             (map (lambda (summary)
                                    (list (value (stratify-explorer--summary-function summary))
                                          (value (stratify-explorer--summary-percentile summary))
                                          (value (stratify-explorer--summary-heading summary))
                                          (value (stratify-explorer--summary-format summary))))
                                  (stratify-explorer--column-summaries column))))
                     (stratify-explorer--state-columns state))))))

(define (stratify-explorer-settings explorer)
  "Everything the form says, as a list: the weight, the charts' line, the boxes ticked, the export name, the conditions
on the rows, and for each column how it is stratified, what else it is split by, and its summaries. :plan of
stratify-explorer takes it, to start a form from it."
  (stratify-explorer--settings-of (stratify-explorer--state-of explorer "stratify-explorer-settings")))

(define (stratify-explorer-save explorer path)
  "Write what the form says to the file at path, for :plan of stratify-explorer to start a form from, another day."
  (write-text-file path (format "{}\n" (stratify-explorer-settings explorer)))
  path)

(define (stratify-explorer--setting settings name default)
  (let ((found (assoc name settings)))
    (if found (cadr found) default)))

(define (stratify-explorer--apply-settings state settings)
  "Make the form say what the settings say (see stratify-explorer-settings). A column that the table hasn't, and a
choice that is no longer there, are passed over."
  (let ((set-if-there (lambda (dropdown value)            ; (a choice that is no longer there is passed over)
                        (when (member value (widget-get dropdown "options"))
                          (widget-set! dropdown "value" value))))
        (names (map stratify-explorer--column-name (stratify-explorer--state-columns state))))
    (set-if-there (stratify-explorer--state-weight state) (stratify-explorer--setting settings "weight" stratify-explorer--no-weight))
    (widget-set! (stratify-explorer--state-charts state) "value" (stratify-explorer--setting settings "charts" #f))
    (widget-set! (stratify-explorer--state-total state) "value" (stratify-explorer--setting settings "total" #t))
    (widget-set! (stratify-explorer--state-grids state) "value" (stratify-explorer--setting settings "grids" #f))
    (widget-set! (stratify-explorer--state-export-name state) "value"
                 (stratify-explorer--setting settings "export" (widget-get (stratify-explorer--state-export-name state) "value")))
    (stratify-explorer--state-conditions-set! state '())
    (dolist (condition (stratify-explorer--setting settings "conditions" '()))
      (when (member (first condition) names)
        (apply stratify-explorer--add-condition state condition)))
    (dolist (saved (stratify-explorer--setting settings "columns" '()))
      (when (member (first saved) names)
        (destructuring-bind (name way count text splits summaries) saved
          (let ((column (stratify-explorer--find-column state name)))
            (widget-set! (stratify-explorer--column-how column) "value" way)
            (widget-set! (stratify-explorer--column-count column) "value" count)
            (widget-set! (stratify-explorer--column-breakpoints column) "value" text)
            (stratify-explorer--column-splits-set! column '())
            (dolist (split splits)
              (when (member (first split) names)
                (apply stratify-explorer--add-split state column split)))
            (stratify-explorer--column-summaries-set! column '())
            (dolist (summary summaries)
              (apply stratify-explorer--add-summary state column summary))
            (stratify-explorer--show-rows (stratify-explorer--column-rows column) (stratify-explorer--column-summaries column)
                                          stratify-explorer--summary-row)
            (stratify-explorer--show-rows (stratify-explorer--column-split-rows column) (stratify-explorer--column-splits column)
                                          stratify-explorer--split-row)))))
    (stratify-explorer--show-rows (stratify-explorer--state-condition-rows state) (stratify-explorer--state-conditions state)
                                  stratify-explorer--condition-row)
    (stratify-explorer--changed state)
    (set-if-there (stratify-explorer--state-chart-column state) (stratify-explorer--setting settings "chart-line" stratify-explorer--first-summary))))
