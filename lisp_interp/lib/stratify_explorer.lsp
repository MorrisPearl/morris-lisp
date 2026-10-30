; stratify_explorer.lsp
;
; A form, in a notebook, for choosing how to stratify a table: a section for each column, which opens when it is
; clicked (an "accordion"), where you choose
;
;   how the column is stratified: not at all, one bucket for each value, the top n values, n buckets of the same
;   count or the same weight, one for each year, or between breakpoints you type;
;
;   how it is summarized in the tables of the other columns: by as many functions as you like (an average and a
;   weighted average, say, or the min, the average and the max, or the 10th, 50th and 90th percentiles), each with
;   the heading of its column in the tables -- a button adds another, and a x on each takes it away; and
;
;   the format each summary is shown in (",.2f", ".3%", ...).
;
; It starts from what stratify-plan suggests. Above the sections are the weight column (for the weighted functions,
; and for equal-weight buckets), and two buttons: Make the tables, which runs stratify-all with what is chosen and
; shows each table (and a chart of it, if Charts is ticked), and Show the code, which shows the stratify-all call that
; makes the same tables, to copy into a cell or a program.
;
; Usage, in a notebook:
;   (define explorer (stratify-explorer loans :weight "balance" :name "loans"))
;   explorer                                 ; the form: the value of a cell shows it
;   (stratify-explorer-plan explorer)        ; what is chosen, as (bys summaries formats), for stratify-all
;   (stratify-explorer-weight explorer)      ; the weight column chosen, or '()
;   (stratify-explorer-tables explorer)      ; the tables, as Make the tables makes them

(require "widgets.lsp")

(defstruct stratify-explorer--column
  name kind how count breakpoints
  usual-format      ; the format that suits its numbers, which a new summary gets
  planned           ; the summaries stratify-plan suggests, (function heading format), that the form begins with
  (summaries '())   ; a list of stratify-explorer--summary, in order
  rows)             ; the box the summaries' rows are in

(defstruct stratify-explorer--summary
  function percentile heading format (automatic "")   ; automatic: the heading the form wrote, to replace if it changes
  row)              ; the row of its widgets, with the x that takes it away

(defstruct stratify-explorer--state
  table name columns weight charts chart-column output (accordion '()))

(define stratify-explorer-ways '("hide" "each" "top" "equal-count" "equal-weight" "year" "breakpoints"))

(define stratify-explorer-functions
  '("(none)" "mean" "weighted-mean" "median" "weighted-median" "sum" "min" "max" "stdev" "percentile"
    "weighted-percentile" "mode" "weighted-mode" "representative" "first" "last"))

(define stratify-explorer--no-weight "(none)")
(define stratify-explorer--first-summary "(first summary)")   ; the chart's line is the tables' first summary, as plot-stratification's is

; ---------------------------------------------------------------------------
; 1. From the plan to the form's values, and back
; ---------------------------------------------------------------------------

(define (stratify-explorer--way how)
  "The form's way of stratifying (one of stratify-explorer-ways), its n, and its breakpoints as text, from a by's how:
each, (top 5), (4.0 5.0 6.0), ..."
  (cond ((symbol? how) (list (symbol->string how) 5 ""))
        ((and (pair? how) (symbol? (car how))) (list (symbol->string (car how)) (cadr how) ""))
        (else (list "breakpoints" 5 (string-join (map (lambda (x) (if (date? x) (date->string x) (number->string x))) how) " ")))))

(define (stratify-explorer--breakpoints column)
  "The breakpoints typed in a column's box, as a list of numbers, or of dates for a column of dates, or an error that
says what is wrong with them."
  (let* ((text (widget-get (stratify-explorer--column-breakpoints column) "value"))
         (words (filter (lambda (word) (> (string-length word) 0)) (regex-split "[,\\s]+" text)))
         (value-of (lambda (word)
                     (if (equal? (stratify-explorer--column-kind column) "date")
                         (string->date word)
                         (if (regex-match "^[-+]?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][-+]?[0-9]+)?$" word)
                             (string->number word)
                             (error (format "{}: the breakpoints are numbers, and {} is not one"
                                            (stratify-explorer--column-name column) word)))))))
    (when (null? words)
      (error (format "{}: type the breakpoints, such as 4.0 5.0 6.0" (stratify-explorer--column-name column))))
    (map value-of words)))

(define (stratify-explorer--how column)
  "How the form says to stratify the column, as stratify takes it: hide, each, year, (top 5), (4.0 5.0), ..."
  (let ((way (widget-get (stratify-explorer--column-how column) "value"))
        (count (widget-get (stratify-explorer--column-count column) "value")))
    (cond ((member way '("hide" "each" "year")) (string->symbol way))
          ((equal? way "breakpoints") (stratify-explorer--breakpoints column))
          (else (list (string->symbol way) count)))))

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
; 2. The widgets of a column's section
; ---------------------------------------------------------------------------

(define (stratify-explorer--layout width)
  (make-widget "Layout" :width width))

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

(define (stratify-explorer--summary-widgets column-name function heading format-text usual-format)
  "The widgets of one summary of a column: its function, the percentile (for the percentile functions), its heading,
and its format. usual-format is the format that suits the column's numbers, which a summary gets when its function is
chosen, if its format is empty."
  (let* ((choice (make-widget "Dropdown" :options stratify-explorer-functions :value function
                              :layout (stratify-explorer--layout "190px")))
         (percentile (make-widget "FloatText" :value 10 :description "p" :layout (stratify-explorer--layout "120px")))
         (heading-box (make-widget "Text" :value heading :placeholder "heading" :layout (stratify-explorer--layout "200px")))
         (format-box (make-widget "Text" :value format-text :placeholder ",.2f" :layout (stratify-explorer--layout "110px")))
         (summary (make-stratify-explorer--summary :function choice :percentile percentile :heading heading-box
                                                   :format format-box :automatic heading
                                                   :row (widget-row choice percentile heading-box format-box)))
         (suggest (lambda ()
                    ; a new function gets a new heading, unless the user has typed one of their own
                    (let ((typed (widget-get heading-box "value")))
                      (when (or (equal? typed "") (equal? typed (stratify-explorer--summary-automatic summary)))
                        (let ((chosen (widget-get choice "value")))
                          (let ((suggested (if (equal? chosen "(none)")
                                               ""
                                               (stratify-explorer--suggested-heading column-name chosen
                                                                                     (widget-get percentile "value")))))
                            (stratify-explorer--summary-automatic-set! summary suggested)
                            (widget-set! heading-box "value" suggested)))))
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

(define (stratify-explorer--show-rows column)
  "Put the column's summaries' rows in its box, in order."
  (widget-set! (stratify-explorer--column-rows column) "children"
               (map stratify-explorer--summary-row (stratify-explorer--column-summaries column))))

(define (stratify-explorer--add-summary state column function heading format-text)
  "Add a summary to the column, at the end -- its function, heading and format, as text -- with a x that takes it away,
and show it."
  (let* ((summary (stratify-explorer--summary-widgets (stratify-explorer--column-name column) function heading format-text
                                                      (stratify-explorer--column-usual-format column)))
         (remove (make-widget "Button" :description "x" :tooltip "take this summary away"
                              :layout (stratify-explorer--layout "36px")))
         (row (stratify-explorer--summary-row summary)))
    (widget-set! row "children" (append (widget-get row "children") (list remove)))
    (widget-on-change (stratify-explorer--summary-function summary) "value"
                      (lambda (chosen) (stratify-explorer--changed state)))
    (widget-on-change (stratify-explorer--summary-heading summary) "value"
                      (lambda (heading) (stratify-explorer--offer-chart-columns state)))
    (widget-on-click remove
                     (lambda ()
                       (stratify-explorer--column-summaries-set!
                         column (filter (lambda (other) (not (eq? other summary))) (stratify-explorer--column-summaries column)))
                       (stratify-explorer--show-rows column)
                       (stratify-explorer--changed state))
                     :output (stratify-explorer--state-output state))
    (stratify-explorer--column-summaries-set! column (append (stratify-explorer--column-summaries column) (list summary)))
    (stratify-explorer--show-rows column)
    (stratify-explorer--changed state)
    summary))

(define (stratify-explorer--section state column profile row)
  "The widgets in a column's section of the accordion, as one box: a line about the column, how it is stratified, and
its summaries, with a button that adds another. It begins with the summaries the plan suggests, or one that is none."
  (let* ((count (stratify-explorer--column-count column))
         (breakpoints (stratify-explorer--column-breakpoints column))
         (add (widget-button "+ add a summary" (lambda () (stratify-explorer--add-summary state column "(none)" "" ""))
                             :output (stratify-explorer--state-output state)))
         (show-fields (lambda (way)
                        (widget-visible count (if (member way '("top" "equal-count" "equal-weight")) #t #f))
                        (widget-visible breakpoints (equal? way "breakpoints")))))
    (stratify-explorer--column-rows-set! column (widget-column))
    (dolist (planned (if (null? (stratify-explorer--column-planned column))
                         (list (list "(none)" "" ""))
                         (stratify-explorer--column-planned column)))
      (apply stratify-explorer--add-summary state column planned))
    (show-fields (widget-get (stratify-explorer--column-how column) "value"))
    (widget-on-change (stratify-explorer--column-how column) "value" show-fields)
    (widget-column (make-widget "HTML" :value (stratify-explorer--profile-line profile row))
                   (make-widget "HTML" :value "<b>Stratify by this column</b>")
                   (widget-row (stratify-explorer--column-how column) count breakpoints)
                   (make-widget "HTML" :value "<b>Summarize it in the other tables</b> (function, heading, format)")
                   (stratify-explorer--column-rows column)
                   add)))

(define (stratify-explorer--title column)
  "A column's title in the accordion: its name, how it is stratified, and how it is summarized."
  (let* ((way (widget-get (stratify-explorer--column-how column) "value"))
         (count (widget-get (stratify-explorer--column-count column) "value"))
         (by (cond ((member way '("top" "equal-count" "equal-weight")) (format "{} {}" way count))
                   ((equal? way "breakpoints") (format "at {}" (widget-get (stratify-explorer--column-breakpoints column) "value")))
                   (else way)))
         (functions (filter (lambda (name) (not (equal? name "(none)")))
                            (map (lambda (summary) (widget-get (stratify-explorer--summary-function summary) "value"))
                                 (stratify-explorer--column-summaries column)))))
    (format "{}: {}{}" (stratify-explorer--column-name column) by
            (if (null? functions) "" (format "; {}" (string-join functions ", "))))))

; ---------------------------------------------------------------------------
; 3. The form
; ---------------------------------------------------------------------------

(define (stratify-explorer--usual-format name kind plan-summaries plan-formats)
  "The format that suits a column's numbers: the one stratify-plan gave its average, or '' for a column that isn't
numbers (or that the plan hid)."
  (let ((found (and (pair? plan-summaries) (> (length (car plan-summaries)) 2)
                    (assoc (caddr (car plan-summaries)) plan-formats))))
    (cond (found (cadr found))
          ((member kind '("integer" "float")) ",.2f")
          (else ""))))

(define (stratify-explorer--column-of name kind plan-by plan-summaries plan-formats)
  "The widgets of one column, with what the plan says for it to begin with. Its summaries are added when its section is
made (stratify-explorer--section)."
  (destructuring-bind (way count breakpoint-text) (stratify-explorer--way (if (pair? plan-by) (cadr plan-by) 'hide))
    (make-stratify-explorer--column
      :name name :kind kind
      :how (make-widget "Dropdown" :options stratify-explorer-ways :value way :layout (stratify-explorer--layout "150px"))
      :count (make-widget "IntText" :value count :description "n" :layout (stratify-explorer--layout "120px"))
      :breakpoints (make-widget "Text" :value breakpoint-text :placeholder "4.0 5.0 6.0"
                                :layout (stratify-explorer--layout "260px"))
      :usual-format (stratify-explorer--usual-format name kind plan-summaries plan-formats)
      :planned (map (lambda (planned)
                      (let* ((function (cadr planned))
                             (heading (if (> (length planned) 2) (caddr planned) ""))
                             (found (assoc heading plan-formats)))
                        (list (if (pair? function) (symbol->string (car function)) (symbol->string function))
                              heading (if found (cadr found) ""))))
                    plan-summaries))))

(define (stratify-explorer table &key (weight '()) (name "table"))
  "A form for choosing how to stratify the table: a section for each column -- how it is stratified, and the ways it is
summarized in the other tables (as many as you add), with their headings and formats -- which starts from what stratify-plan
suggests (with :weight, the weight column, if there is one). Above them are the weight column, a box to tick for
charts, and buttons: Make the tables, which runs stratify-all and shows the tables (and charts) under the form, and Show
the code, which shows the call that makes them, with :name (\"table\") for the table. It is a widget: the value of a cell
shows it. stratify-explorer-plan reads what is chosen."
  (let* ((plan (if (null? weight) (stratify-plan table) (stratify-plan table :weight weight)))
         (profile (table-profile table))
         (names (table-column-names table))
         (numeric (filter (lambda (column) (member (vector-ref (table-column profile "kind")
                                                               (vector-ref (vector-positions (table-column profile "column") (vector column)) 0))
                                                   '("integer" "float")))
                          names))
         (columns (map (lambda (column)
                         (stratify-explorer--column-of
                           column
                           (vector-ref (table-column profile "kind") (vector-ref (vector-positions (table-column profile "column") (vector column)) 0))
                           (assoc column (first plan))
                           (filter (lambda (summary) (equal? (car summary) column)) (second plan))
                           (third plan)))
                       names))
         (output (widget-output))
         (weight-choice (make-widget "Dropdown" :options (cons stratify-explorer--no-weight numeric)
                                     :value (if (null? weight) stratify-explorer--no-weight weight)
                                     :description "weight"))
         (charts (make-widget "Checkbox" :value #f :description "Charts"))
         (chart-column (make-widget "Dropdown" :options (list stratify-explorer--first-summary)
                                    :value stratify-explorer--first-summary :description "chart line"))
         (state (make-stratify-explorer--state :table table :name name :columns columns :weight weight-choice
                                               :charts charts :chart-column chart-column :output output))
         (accordion (make-widget "Accordion"
                                 :children (loop for column in columns for row from 0
                                                 collect (stratify-explorer--section state column profile row))))
         (retitle (lambda (value) (stratify-explorer--changed state)))
         (form (widget-column
                 (widget-row weight-choice chart-column charts
                             (widget-button "Make the tables"
                                            (lambda () (widget-clear output) (stratify-explorer--make-tables state #t))
                                            :output output :button-style "primary")
                             (widget-button "Show the code"
                                            (lambda () (widget-clear output) (display (stratify-explorer-code-of state)))
                                            :output output))
                 accordion
                 output)))
    (stratify-explorer--state-accordion-set! state accordion)
    (dolist (column columns)
      (widget-on-change (stratify-explorer--column-how column) "value" retitle)
      (widget-on-change (stratify-explorer--column-count column) "value" retitle)
      (widget-on-change (stratify-explorer--column-breakpoints column) "value" retitle))
    (stratify-explorer--changed state)
    (widget-set-tag! form state)
    form))

; ---------------------------------------------------------------------------
; 4. What is chosen, and the tables
; ---------------------------------------------------------------------------

(define (stratify-explorer--state-of explorer who)
  (let ((state (widget-tag explorer)))
    (unless (stratify-explorer--state? state)
      (error (format "{}: that is not a form that stratify-explorer made" who)))
    state))

(define (stratify-explorer--weight-of state)
  (let ((chosen (widget-get (stratify-explorer--state-weight state) "value")))
    (if (equal? chosen stratify-explorer--no-weight) '() chosen)))

(define (stratify-explorer--plan-of state)
  "What the form says, as (bys summaries formats), the arguments of stratify-all and display-table. A function or a
way that needs a weight, without one, is an error that says which column."
  (let* ((weight (stratify-explorer--weight-of state))
         (bys '())
         (summaries '())
         (formats '()))
    (dolist (column (stratify-explorer--state-columns state))
      (let ((name (stratify-explorer--column-name column))
            (how (stratify-explorer--how column)))
        (when (and (null? weight) (pair? how) (eq? (car how) 'equal-weight))
          (error (format "{}: equal-weight buckets need a weight column: choose one above" name)))
        (unless (eq? how 'hide)
          (push (list name how) bys))
        (dolist (summary (stratify-explorer--column-summaries column))
          (let ((function (stratify-explorer--function summary))
                (heading (widget-get (stratify-explorer--summary-heading summary) "value"))
                (format-text (widget-get (stratify-explorer--summary-format summary) "value")))
            (unless (null? function)
              (when (and (null? weight) (string-starts-with? (symbol->string (if (pair? function) (car function) function)) "weighted"))
                (error (format "{}: {} needs a weight column: choose one above" name
                               (if (pair? function) (car function) function))))
              (let ((heading (if (equal? heading "")
                                 (stratify-explorer--suggested-heading name (symbol->string (if (pair? function) (car function) function))
                                                                       (if (pair? function) (cadr function) 0))
                                 heading)))
                (push (list name function heading) summaries)
                (unless (equal? format-text "")
                  (push (list heading format-text) formats))))))))
    (list (reverse bys) (reverse summaries)
          (append '(("count" ",d") ("percent" ".1%"))
                  (if (null? weight) '() (list (list (format "total_{}" weight) ",.0f")))
                  (reverse formats)))))

(define (stratify-explorer-plan explorer)
  "What the form made by stratify-explorer says now, as (bys summaries formats): the arguments of stratify-all (with the
weight of stratify-explorer-weight) and the formats of display-table."
  (stratify-explorer--plan-of (stratify-explorer--state-of explorer "stratify-explorer-plan")))

(define (stratify-explorer-weight explorer)
  "The weight column the form says, or '() for none."
  (stratify-explorer--weight-of (stratify-explorer--state-of explorer "stratify-explorer-weight")))

(define (stratify-explorer--tables-of state)
  (destructuring-bind (bys summaries formats) (stratify-explorer--plan-of state)
    (let ((weight (stratify-explorer--weight-of state)))
      (if (null? weight)
          (stratify-all (stratify-explorer--state-table state) bys summaries)
          (stratify-all (stratify-explorer--state-table state) bys summaries :weight weight)))))

(define (stratify-explorer-tables explorer)
  "The stratification tables that the form says to make, as a list, as Make the tables makes them."
  (stratify-explorer--tables-of (stratify-explorer--state-of explorer "stratify-explorer-tables")))

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

(define (stratify-explorer--changed state)
  "Something on the form has changed: say what is chosen in the sections' titles, and offer the summaries there are as
the chart's line. (While the sections are being made there is no accordion yet, and nothing to do.)"
  (let ((accordion (stratify-explorer--state-accordion state)))
    (unless (null? accordion)
      (widget-set! accordion "titles" (map stratify-explorer--title (stratify-explorer--state-columns state)))
      (stratify-explorer--offer-chart-columns state))))

(define (stratify-explorer--offer-chart-columns state)
  "Make the choices of the chart's line the summaries the form has now: the first summary, as plot-stratification's own
line is, and each heading. The one chosen stays chosen if it is still there."
  (let* ((choice (stratify-explorer--state-chart-column state))
         (chosen (widget-get choice "value"))
         (options (cons stratify-explorer--first-summary (stratify-explorer--summary-headings state))))
    (unless (equal? (widget-get choice "options") options)
      (widget-set! choice "options" options)
      (widget-set! choice "value" (if (member chosen options) chosen stratify-explorer--first-summary)))))

(define (stratify-explorer--chart-column-of state)
  "The heading of the summary the charts' line is of, or '() for the first summary."
  (let ((chosen (widget-get (stratify-explorer--state-chart-column state) "value")))
    (if (equal? chosen stratify-explorer--first-summary) '() chosen)))

(define (stratify-explorer-chart-column explorer)
  "The heading of the summary the form's charts draw as a line, or '() for the first summary."
  (stratify-explorer--chart-column-of (stratify-explorer--state-of explorer "stratify-explorer-chart-column")))

(define (stratify-explorer--make-tables state show?)
  "Make the tables the form says, and show each (and its chart, if Charts is ticked)."
  (let ((formats (third (stratify-explorer--plan-of state)))
        (tables (stratify-explorer--tables-of state)))
    (when (null? tables)
      (display "Every column is hidden: choose how to stratify one of them.\n"))
    (dolist (table tables)
      (display-table table formats)
      (when (widget-get (stratify-explorer--state-charts state) "value")
        (let ((line (stratify-explorer--chart-column-of state)))
          (if (null? line)
              (plot-stratification table :formats formats)
              (plot-stratification table :formats formats :column line))))
      (newline))
    tables))

(define (stratify-explorer-code-of state)
  "The code that makes the tables the form says, as text (and their charts, if Charts is ticked)."
  (destructuring-bind (bys summaries formats) (stratify-explorer--plan-of state)
    (let* ((weight (stratify-explorer--weight-of state))
           (line (stratify-explorer--chart-column-of state))
           (quoted (lambda (items) (string-join (map (lambda (item) (format "{}" item)) items) "\n      "))))
      (format "(define strats\n  (stratify-all {}\n    '({})\n    '({}){}))\n(define formats\n  '({}))\n(dolist (table strats)\n  (display-table table formats){})\n"
              (stratify-explorer--state-name state) (quoted bys) (quoted summaries)
              (if (null? weight) "" (format "\n    :weight \"{}\"" weight))
              (quoted formats)
              (cond ((not (widget-get (stratify-explorer--state-charts state) "value")) "")
                    ((null? line) "\n  (plot-stratification table :formats formats)")
                    (else (format "\n  (plot-stratification table :formats formats :column \"{}\")" line)))))))

(define (stratify-explorer-code explorer)
  "The code that makes the tables the form says, as text: a stratify-all call, and display-table for each table."
  (stratify-explorer-code-of (stratify-explorer--state-of explorer "stratify-explorer-code")))
