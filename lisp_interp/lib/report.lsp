; report.lsp
; ==========
; Turns a table, possibly a large one, into a text report with control breaks: the rows
; are in groups (by state, then by zip code within it; or by client), and each group has
; a header before its rows and a footer after them, with the group's totals. The report has
; a header and a footer of its own, with the grand totals, and, if you ask for pages, a
; header and footer for every page, with the page number. What each of these says, and
; what is in each row, is written as a template, with {{name}} where a value goes:
; the templates of template.lsp, so {{balance:>14,.2f}} lays a value out as format does,
; and {{#each}} and {{#if}} work.
;
;   (load "report.lsp")
;
;   (define spec
;     (make-report-spec
;       :page-lines 60
;       :page-header "Mortgages                                  page {{page}}"
;       :detail      "{{loan-id:<10}} {{zip:<6}} {{balance:>14,.2f}}"
;       :summaries   (list (list "loans" 'count) (list "total" 'sum "balance"))
;       :breaks      (list (make-report-break :field "state" :header "State {{state}}"
;                                             :footer "  {{state}}: {{loans}} loans {{total:>14,.2f}}")
;                          (make-report-break :field "zip" :footer "  {{zip}}: {{total:>14,.2f}}"))
;       :report-footer "All: {{loans}} loans {{total:>14,.2f}}"))
;
;   (write-report loans "loans.txt" spec)     ; the report, in a file
;   (report-text loans spec)                  ; or as a string, for a short one
;
; See "Reports with control breaks" in the library manual for everything the spec can say.
;
; HOW IT WORKS. The table is sorted by the break columns (and :detail-order), then written
; in one pass, a row at a time. The summaries of every group (all the aggregations of
; table-group-by: sum, count, mean, weighted-mean, min, max, ...) are worked out first, a
; level at a time, by table-group-by on the whole table, so a group's header can show its
; totals as well as its footer can. The rest, for each row: has a group ended (a footer for
; each level that has) or begun (a header for each); does the row fit on the page; and the
; row's template. Output is written to the file a thousand lines at a time, so a report
; of any length is written without holding it.

(load "template.lsp")

(defstruct report-break field header footer (new-page #f) (restart-page-numbers #f))

(defstruct report-spec
  report-header report-footer
  page-header page-footer (page-lines #f) (page-separator "")
  detail breaks summaries variables detail-order (presorted #f))

; ---------------------------------------------------------------------------
; Small pieces
; ---------------------------------------------------------------------------

(define (report--has-missing? column)
  "Whether a column of numbers has a missing value (a column of text or dates has none)."
  (catch-error (> (vector-sum (vector-nan? column)) 0) (e) #f))

(define (report--lines text)
  "How many lines the text takes."
  (length (string-split text "\n")))

(define (report--take items count)
  (loop for item in items for place from 1 to count collect item))

(define (report--replace-nth items place value)
  (loop for item in items for at from 0 collect (if (= at place) value item)))

(define (report--template-names nodes)
  "The names a parsed template (see template-parse) takes from its bindings: not those a {{#each}} makes itself."
  (append-map
    (lambda (node)
      (let ((kind (car node)))
        (cond ((eq? kind 'var) (list (cadr node)))
              ((eq? kind 'each)
               (append (list (list-ref node 2))
                       (if (null? (list-ref node 3)) '() (list (list-ref node 3)))
                       (filter (lambda (name) (not (eq? name (cadr node))))
                               (report--template-names (list-ref node 4)))))
              ((eq? kind 'if)
               (append (list (cadr node)) (report--template-names (list-ref node 2)) (report--template-names (list-ref node 3))))
              (else '()))))
    nodes))

(define (report--parse where template allowed)
  "The parsed template, or #f if there is none. A template names only what is allowed where it is used."
  (cond ((not (report--given? template)) #f)
        ((string? template)
         (let* ((nodes (template-parse template))
                (unknown (filter (lambda (name) (not (member name allowed))) (report--template-names nodes))))
           (unless (null? unknown)
             (error (format "write-report: the {} uses {{{{{}}}}}, which is not a name there: its names are {}"
                            where (car unknown) (string-join (map symbol->string allowed) " "))))
           nodes))
        (else (error (format "write-report: the {} must be a string (a template) or '(), not {}" where template)))))

(define (report--given? template)
  "A template is given if it is not '() (and not #f)."
  (not (or (null? template) (eq? template #f))))

(define (report--pairs table)
  "The columns of a table, as a list of (name-symbol . vector)."
  (loop for name in (table-column-names table)
        collect (cons (string->symbol name) (table-column table name))))

(define (report--bindings pairs place)
  "The (name value) bindings of one row, at this place, of those columns."
  (map (lambda (pair) (list (car pair) (vector-ref (cdr pair) place))) pairs))

(define (report--empty-bindings summaries)
  "Bindings for a group that has no rows: 0 for counts and totals, and a missing number for the rest."
  (map (lambda (summary)
         (list (string->symbol (car summary)) (if (member (cadr summary) '(count sum)) 0 nan)))
       summaries))

; ---------------------------------------------------------------------------
; The checks of the spec
; ---------------------------------------------------------------------------

(define (report--check-spec table spec)
  (unless (table? table)
    (error "write-report: the first argument must be a table, not" table))
  (unless (report-spec? spec)
    (error "write-report: the report spec must be made by make-report-spec, not" spec))
  (let ((columns (table-column-names table)))
    (for-each
      (lambda (break)
        (unless (report-break? break)
          (error "write-report: :breaks is a list of make-report-break values, not" break))
        (unless (string? (report-break-field break))
          (error "write-report: a break needs the name of the column to break on: (make-report-break :field \"state\" ...)"))
        (unless (member (report-break-field break) columns)
          (error (format "write-report: a break is on the column {}, and the table has {}"
                         (report-break-field break) (string-join columns " "))))
        (when (report--has-missing? (table-column table (report-break-field break)))
          (error (format "write-report: the column {}, which a break is on, has missing values: which group would they be?"
                         (report-break-field break)))))
      (report-spec-breaks spec))
    (for-each
      (lambda (name)
        (unless (member name columns)
          (error (format "write-report: :detail-order names the column {}, and the table has {}"
                         name (string-join columns " ")))))
      (report-spec-detail-order spec))
    (for-each
      (lambda (summary)
        (unless (and (pair? summary) (string? (car summary)) (symbol? (cadr summary)))
          (error "write-report: a summary is (name function column), as table-group-by has them, such as (\"total\" sum \"balance\"), not" summary)))
      (report-spec-summaries spec))
    (let ((page-lines (report-spec-page-lines spec)))
      (unless (or (null? page-lines) (eq? page-lines #f) (and (integer? page-lines) (> page-lines 2)))
        (error "write-report: :page-lines is a whole number of lines above 2, or '() for no pages, not" page-lines)))))

; ---------------------------------------------------------------------------
; The report
; ---------------------------------------------------------------------------

(define (report--run table spec emit)
  "Writes the report of the table, as the spec says, a line at a time by calling (emit text) with each line (without its
newline). Returns the number of pages."
  (report--check-spec table spec)
  (define breaks (report-spec-breaks spec))
  (define depth (length breaks))
  (define fields (map report-break-field breaks))
  (define field-names (map string->symbol fields))
  (define summaries (report-spec-summaries spec))
  (define summary-names (map (lambda (summary) (string->symbol (car summary))) summaries))
  (define variables (report-spec-variables spec))
  (define variable-names (map car variables))
  (define page-lines (if (null? (report-spec-page-lines spec)) #f (report-spec-page-lines spec)))
  (define separator (report-spec-page-separator spec))
  (define sort-columns (append fields (report-spec-detail-order spec)))
  (define data (if (or (report-spec-presorted spec) (null? sort-columns)) table (table-sort table sort-columns)))
  (define rows (table-row-count data))
  (define column-names (map string->symbol (table-column-names data)))

  ; the templates, parsed once, each with the names it may use
  (define (up-to level) (report--take field-names level))
  (define detail-nodes (report--parse "detail" (report-spec-detail spec) (append column-names variable-names '(page row-number))))
  (define header-nodes
    (loop for break in breaks for level from 1
          collect (report--parse (format "header of the break on {}" (report-break-field break)) (report-break-header break)
                                 (append (up-to level) summary-names variable-names '(page)))))
  (define footer-nodes
    (loop for break in breaks for level from 1
          collect (report--parse (format "footer of the break on {}" (report-break-field break)) (report-break-footer break)
                                 (append (up-to level) summary-names variable-names '(page)))))
  (define report-header-nodes (report--parse "report header" (report-spec-report-header spec) (append summary-names variable-names '(page))))
  (define report-footer-nodes (report--parse "report footer" (report-spec-report-footer spec) (append summary-names variable-names '(page))))
  (define page-header-nodes (report--parse "page header" (report-spec-page-header spec) (append field-names variable-names '(page))))
  (define page-footer-nodes (report--parse "page footer" (report-spec-page-footer spec) (append field-names summary-names variable-names '(page))))

  ; what the details use, and the lines the templates take
  (define detail-names (if detail-nodes (report--template-names detail-nodes) '()))
  (define detail-pairs
    (loop for name in column-names
          when (member name detail-names) collect (cons name (table-column data (symbol->string name)))))
  (define detail-height (if (report--given? (report-spec-detail spec)) (report--lines (report-spec-detail spec)) 0))
  ; A detail template of only text and {{name}}s (the usual) is turned into a list of text and of functions of the row's
  ; place, which is a good deal faster than template-render, and what a million rows come to.
  (define (piece node)
    (let ((kind (car node)))
      (cond ((eq? kind 'text) (cadr node))
            ((eq? kind 'var)
             (let ((name (cadr node)) (spec (caddr node)))
               (cond ((eq? name 'page) (lambda (place) (format-value page spec)))
                     ((eq? name 'row-number) (lambda (place) (format-value (+ place 1) spec)))
                     ((assoc name variables) (let ((value (cadr (assoc name variables)))) (lambda (place) (format-value value spec))))
                     (else (let ((column (cdr (assoc name detail-pairs))))
                             (lambda (place) (format-value (vector-ref column place) spec)))))))
            (else #f))))
  (define detail-pieces
    (and detail-nodes
         (let ((pieces (map piece detail-nodes)))
           (and (not (member #f pieces)) pieces))))
  (define (render-detail place)
    (if detail-pieces
        (apply string-append (map (lambda (piece) (if (string? piece) piece (piece place))) detail-pieces))
        (render detail-nodes (append (list (list 'row-number (+ place 1))) (report--bindings detail-pairs place)))))
  (define footer-height (if (report--given? (report-spec-page-footer spec)) (report--lines (report-spec-page-footer spec)) 0))
  (define page-footer-uses-summaries
    (and page-footer-nodes (not (null? (filter (lambda (name) (member name summary-names)) (report--template-names page-footer-nodes))))))

  ; the summaries: of the whole report, and of the groups of each level
  (define with-one (table-add-column data "report--all" (make-vector rows 1)))
  (define (summarize-all part)
    (if (= (table-row-count part) 0)
        (report--empty-bindings summaries)
        (report--bindings (report--pairs (table-group-by part '("report--all") summaries)) 0)))
  (define grand-bindings (summarize-all with-one))
  (define level-pairs
    (loop for level from 1 to depth
          collect (report--pairs (table-group-by data (report--take fields level) summaries))))
  (define key-columns (map (lambda (field) (table-column data field)) fields))

  ; the state of the writing
  (define page 1)
  (define pages 0)
  (define line-count 0)
  (define header-lines 0)
  (define rows-written 0)
  (define page-first-row 0)
  (define group-indexes (loop for level from 1 to depth collect -1))
  (define current-keys (loop for level from 1 to depth collect '()))
  (define content-keys current-keys)
  (define buffered '())
  (define base-bindings (lambda () (cons (list 'page page) variables)))

  (define (key-bindings keys) (map (lambda (name key) (list name key)) field-names keys))
  (define (render nodes extra) (template-render nodes (append extra (base-bindings))))
  (define (emit-text text lines)
    (emit text)
    (set! line-count (+ line-count lines)))

  ; pages
  (define (start-page)
    (set! pages (+ pages 1))
    (set! line-count 0)
    (set! page-first-row rows-written)
    (when page-header-nodes
      (let ((header (render page-header-nodes (key-bindings current-keys))))
        (emit-text header (report--lines header))))
    (set! header-lines line-count))
  (define (page-summaries)
    (if (and page-footer-uses-summaries (> rows-written page-first-row))
        (summarize-all (table-slice with-one page-first-row rows-written))
        (report--empty-bindings summaries)))
  (define (close-page)
    (let* ((footer (if page-footer-nodes
                       (render page-footer-nodes (append (page-summaries) (key-bindings content-keys)))
                       #f))
           (fill (if page-lines (- page-lines line-count footer-height) 0)))
      (loop repeat (max 0 fill) do (emit-text "" 1))
      (when footer (emit-text footer (report--lines footer)))
      (when (> (string-length separator) 0) (emit separator))))
  (define (page-break restart)
    "Ends the page and starts the next, unless nothing is on the page but its header. Returns whether it did."
    (and (> line-count header-lines)
         (begin (close-page)
                (set! page (if restart 1 (+ page 1)))
                (start-page)
                #t)))
  (define (room-for lines)
    "Makes room for this many lines on the page, by ending it if need be. Returns whether it did."
    (and page-lines (> (+ line-count lines footer-height) page-lines)
         (page-break #f)))
  (define (write-block render-text)
    "Writes the text that (render-text) gives, unless it gives #f. It is written again if the page ends to make room
for it: what it says may be the page's number."
    (let ((text (render-text)))
      (when text
        (let ((lines (report--lines text)))
          (when (room-for lines)
            (set! text (render-text))
            (set! lines (report--lines text)))
          (emit-text text lines)
          (set! content-keys current-keys)))))

  ; groups
  (define (group-bindings level)
    (report--bindings (list-ref level-pairs (- level 1)) (list-ref group-indexes (- level 1))))
  (define (footers-from level)
    "The footers of the groups ending, from the innermost up to this level, as one text, or #f."
    (let ((texts (loop for l from depth downto level
                       when (list-ref footer-nodes (- l 1))
                         collect (render (list-ref footer-nodes (- l 1)) (group-bindings l)))))
      (if (null? texts) #f (string-join texts "\n"))))
  (define (headers-from level)
    (let ((texts (loop for l from level to depth
                       when (list-ref header-nodes (- l 1))
                         collect (render (list-ref header-nodes (- l 1)) (group-bindings l)))))
      (if (null? texts) #f (string-join texts "\n"))))
  ; for each row after the first, the outermost level at which its group differs from the row before's (or more than
  ; depth, if it does not): worked out a level at a time, on whole columns
  (define change-levels
    (let ((levels (make-vector (max 0 (- rows 1)) (+ depth 1))))
      (when (> rows 1)
        (loop for level from depth downto 1
              do (let* ((column (list-ref key-columns (- level 1)))
                        (differs (- 1 (= (vector-drop column 1) (vector-take column (- rows 1))))))
                   (set! levels (+ (* differs level) (* (- 1 differs) levels))))))
      levels))
  (define (row-keys place) (map (lambda (column) (vector-ref column place)) key-columns))

  (define (begin-groups level place)
    "Rows of new groups from this level in begin at this place: moves on to them, and writes their headers."
    (loop for l from level to depth
          do (begin
               (set! group-indexes (report--replace-nth group-indexes (- l 1) (+ 1 (list-ref group-indexes (- l 1)))))
               (let ((summary-keys (report--bindings (list-ref level-pairs (- l 1)) (list-ref group-indexes (- l 1)))))
                 (unless (equal? (cadr (assoc (list-ref field-names (- l 1)) summary-keys))
                                 (vector-ref (list-ref key-columns (- l 1)) place))
                   (error "write-report: the groups of the summaries are not in the order of the rows")))))
    (set! current-keys (row-keys place))
    (let ((new-page-breaks (filter (lambda (break) break)
                                   (loop for l from level to depth collect (report-break-new-page (list-ref breaks (- l 1)))))))
      (unless (null? new-page-breaks)
        (page-break (not (null? (filter (lambda (l) (report-break-restart-page-numbers (list-ref breaks (- l 1))))
                                        (iota-from level depth)))))))
    (let ((headers (headers-from level)))
      (when headers
        (when (room-for (+ (report--lines headers) detail-height))
          (set! headers (headers-from level)))
        (emit-text headers (report--lines headers))
        (set! content-keys current-keys))))

  (define (iota-from low high) (loop for l from low to high collect l))

  ; the report
  (when (> rows 0) (set! current-keys (row-keys 0)))
  (start-page)
  (when report-header-nodes (write-block (lambda () (render report-header-nodes grand-bindings))))
  (loop for place from 0 below rows
        do (begin
             (let ((change (if (= place 0) 1 (vector-ref change-levels (- place 1)))))
               (when (<= change depth)
                 (when (> place 0)
                   (write-block (lambda () (footers-from change))))
                 (begin-groups change place)))
             (when detail-nodes
               (write-block (lambda () (render-detail place))))
             (set! rows-written (+ place 1))))
  (when (and (> rows 0) (> depth 0))
    (write-block (lambda () (footers-from 1))))
  (when report-footer-nodes (write-block (lambda () (render report-footer-nodes grand-bindings))))
  (close-page)
  pages)

; ---------------------------------------------------------------------------
; The two ways to have it
; ---------------------------------------------------------------------------

(define (report-text table spec)
  "The report of the table, as the spec says, as one string. For a short report: write-report writes a file, a
thousand lines at a time, and takes a table of any size."
  (let ((lines '()))
    (report--run table spec (lambda (text) (set! lines (cons text lines))))
    (string-append (string-join (reverse lines) "\n") "\n")))

(define (write-report table path spec)
  "Writes the report of the table, as the spec says (see make-report-spec), to the text file at path, replacing
what was there. Returns the number of pages (1, if the spec has no :page-lines)."
  (write-text-file path "" #f)
  (let* ((lines '())
         (count 0)
         (flush (lambda ()
                  (when (> count 0)
                    (write-text-file path (string-append (string-join (reverse lines) "\n") "\n") #t))
                  (set! lines '())
                  (set! count 0))))
    (let ((pages (report--run table spec
                              (lambda (text)
                                (set! lines (cons text lines))
                                (set! count (+ count 1))
                                (when (>= count 1000) (flush))))))
      (flush)
      pages)))
