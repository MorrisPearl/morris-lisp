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
; Pages can say "page X of Y" ({{page}} and {{pages}}), the templates can say running totals (:running), and a break can
; repeat its header on the pages its group goes over (:repeat-header). (write-report-html table path spec) writes the same
; report as a web page, a page of it at a time, with a bar at the bottom to go through the pages.
;
; HOW IT WORKS. The table is sorted by the break columns (and :detail-order), then written
; in one pass, a row at a time. The summaries of every group (all the aggregations of
; table-group-by: sum, count, mean, weighted-mean, min, max, ...) are worked out first, a
; level at a time, by table-group-by on the whole table, so a group's header can show its
; totals as well as its footer can. The rest, for each row: has a group ended (a footer for
; each level that has) or begun (a header for each); does the row fit on the page; and the
; row's template. Output is written to the file a thousand lines at a time, so a report
; of any length is written without holding it.

(require "template.lsp")

(defstruct report-break field header footer (new-page #f) (restart-page-numbers #f) (repeat-header #f))

(defstruct report-spec
  report-header report-footer
  page-header page-footer (page-lines #f) (page-separator "")
  detail breaks summaries running variables detail-order (presorted #f)
  (markdown #f) formats)

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
    (for-each
      (lambda (entry)
        (unless (and (pair? entry) (string? (car entry)) (pair? (cdr entry)) (member (cadr entry) '(sum count)))
          (error "write-report: a running total is (name sum column [scope]) or (name count [scope]), such as (\"so-far\" sum \"balance\"), not" entry))
        (let ((rest (cddr entry)))
          (when (eq? (cadr entry) 'sum)
            (unless (and (pair? rest) (member (car rest) columns))
              (error (format "write-report: the running total {} needs a column of the table: {}" (car entry) (string-join columns " "))))
            (set! rest (cdr rest)))
          (unless (or (null? rest) (and (pair? rest) (null? (cdr rest)) (or (eq? (car rest) 'page) (member (car rest) (map report-break-field (report-spec-breaks spec))))))
            (error (format "write-report: the scope of the running total {} is page or the column of a break, not {}" (car entry) rest)))))
      (report-spec-running spec))
    (let ((page-lines (report-spec-page-lines spec)))
      (unless (or (null? page-lines) (eq? page-lines #f) (and (integer? page-lines) (> page-lines 2)))
        (error "write-report: :page-lines is a whole number of lines above 2, or '() for no pages, not" page-lines)))
    (if (report-spec-markdown spec)
        (begin
          (when (report--given? (report-spec-detail spec))
            (error "write-report: a :markdown report writes its rows as a table, so it has no :detail template; :formats lays out the columns"))
          (when (or (report--given? (report-spec-page-lines spec)) (report--given? (report-spec-page-header spec))
                    (report--given? (report-spec-page-footer spec)))
            (error "write-report: a :markdown report has no pages, so no :page-lines, :page-header or :page-footer"))
          ; try the formats on a row now, so that a mistake in them is found before any of the file is written
          (when (> (table-row-count table) 0)
            (table-markdown (table-slice table 0 1) (report-spec-formats spec))))
        (when (report--given? (report-spec-formats spec))
          (error "write-report: :formats lays out the columns of a :markdown report, which this is not")))))

; ---------------------------------------------------------------------------
; The report
; ---------------------------------------------------------------------------

(define (report--run table spec emit end-page)
  "Writes the report of the table, as the spec says, a block of lines at a time by calling (emit text) with each (without
its last newline), and (end-page) at the end of each page. Returns the number of pages. A report that says {{pages}} is
laid out twice: the first time to count them."
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
  (define markdown (report-spec-markdown spec))
  (define formats (report-spec-formats spec))
  (define sort-columns (append fields (report-spec-detail-order spec)))
  (define data (if (or (report-spec-presorted spec) (null? sort-columns)) table (table-sort table sort-columns)))
  (define rows (table-row-count data))
  (define column-names (map string->symbol (table-column-names data)))

  ; the running totals: (name function column-or-#f level), the level being 0 for the whole report, a break's place, or -1 for a page
  (define running
    (map (lambda (entry)
           (let* ((function (cadr entry))
                  (rest (cddr entry))
                  (column (if (eq? function 'sum) (table-column data (car rest)) #f))
                  (scope (if (eq? function 'sum) (cdr rest) rest)))
             (list (string->symbol (car entry)) function column
                   (cond ((null? scope) 0)
                         ((eq? (car scope) 'page) -1)
                         (else (+ 1 (position (car scope) fields)))))))
         (report-spec-running spec)))
  (define running-names (map car running))

  ; the templates, parsed once, each with the names it may use
  (define (up-to level) (report--take field-names level))
  (define everywhere (append variable-names running-names '(page pages)))
  (define detail-nodes (report--parse "detail" (report-spec-detail spec) (append column-names everywhere '(row-number))))
  (define header-nodes
    (loop for break in breaks for level from 1
          collect (report--parse (format "header of the break on {}" (report-break-field break)) (report-break-header break)
                                 (append (up-to level) summary-names everywhere '(continued)))))
  (define footer-nodes
    (loop for break in breaks for level from 1
          collect (report--parse (format "footer of the break on {}" (report-break-field break)) (report-break-footer break)
                                 (append (up-to level) summary-names everywhere))))
  (define report-header-nodes (report--parse "report header" (report-spec-report-header spec) (append summary-names everywhere)))
  (define report-footer-nodes (report--parse "report footer" (report-spec-report-footer spec) (append summary-names everywhere)))
  (define page-header-nodes (report--parse "page header" (report-spec-page-header spec) (append field-names everywhere)))
  (define page-footer-nodes (report--parse "page footer" (report-spec-page-footer spec) (append field-names summary-names everywhere)))
  (define all-nodes (append (list detail-nodes report-header-nodes report-footer-nodes page-header-nodes page-footer-nodes)
                            header-nodes footer-nodes))
  (define uses-pages
    (not (null? (filter (lambda (nodes) (and nodes (member 'pages (report--template-names nodes)))) all-nodes))))

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
                     ((member name running-names)
                      (let ((entry (position name running-names)))
                        (lambda (place) (format-value (+ (list-ref running-values entry) (running-contribution (list-ref running entry) place)) spec))))
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
        (render detail-nodes (append (list (list 'row-number (+ place 1)))
                                     (map (lambda (entry value) (list (car entry) (+ value (running-contribution entry place))))
                                          running running-values)
                                     (report--bindings detail-pairs place)))))
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

  ; the state of the writing (set again at the start of each pass)
  (define page 1)
  (define pages 0)
  (define line-count 0)
  (define header-lines 0)
  (define rows-written 0)
  (define page-first-row 0)
  (define group-indexes '())
  (define current-keys '())
  (define content-keys '())
  (define running-values '())
  (define repeat-through 0)                ; the headers of this many outer levels are repeated, if a page ends now
  (define sequence 0)                      ; which run of page numbers (a break that restarts them makes a new one)
  (define page-totals '())                 ; the last page number of each run, as the first pass finds them
  (define known-totals #f)                 ; the same, in the second
  (define table-start #f)                  ; in a markdown report, where the rows of the table being written begin, or #f
  (define sink emit)
  (define finish-page end-page)
  (define (pages-in-run) (if known-totals (list-ref known-totals sequence) 0))
  (define (running-bindings) (map (lambda (entry value) (list (car entry) value)) running running-values))
  (define (base-bindings) (append (list (list 'page page) (list 'pages (pages-in-run))) (running-bindings) variables))
  (define (running-contribution entry place)
    "What the row at this place adds to a running total."
    (if (eq? (cadr entry) 'count)
        1
        (let ((value (vector-ref (caddr entry) place))) (if (= value value) value 0))))
  (define (reset-running level-test)
    (set! running-values (map (lambda (entry value) (if (level-test (cadddr entry)) 0 value)) running running-values)))
  (define (add-running place)
    (unless (null? running)
      (set! running-values (map (lambda (entry value) (+ value (running-contribution entry place))) running running-values))))

  (define (key-bindings keys) (map (lambda (name key) (list name key)) field-names keys))
  (define (render nodes extra) (template-render nodes (append extra (base-bindings))))
  (define (emit-text text lines)
    (sink text)
    (set! line-count (+ line-count lines)))

  ; pages
  (define (repeated-headers)
    "The headers of the groups that go on over a page break, as one text, or #f."
    (let ((texts (loop for l from 1 to repeat-through
                       when (and (report-break-repeat-header (list-ref breaks (- l 1))) (list-ref header-nodes (- l 1)))
                         collect (render (list-ref header-nodes (- l 1)) (cons (list 'continued #t) (group-bindings l))))))
      (if (null? texts) #f (string-join texts "\n"))))
  (define (start-page)
    (set! pages (+ pages 1))
    (set! line-count 0)
    (set! page-first-row rows-written)
    (reset-running (lambda (level) (< level 0)))
    (when page-header-nodes
      (let ((header (render page-header-nodes (key-bindings current-keys))))
        (emit-text header (report--lines header))))
    (let ((repeated (repeated-headers)))
      (when repeated (emit-text repeated (report--lines repeated))))
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
      (finish-page)))
  (define (page-break restart)
    "Ends the page and starts the next, unless nothing is on the page but its header. Returns whether it did."
    (and (> line-count header-lines)
         (begin (close-page)
                (when restart
                  (set! page-totals (append page-totals (list page)))
                  (set! sequence (+ sequence 1)))
                (set! page (if restart 1 (+ page 1)))
                (start-page)
                #t)))
  (define (room-for lines)
    "Makes room for this many lines on the page, by ending it if need be. Returns whether it did."
    (and page-lines (> (+ line-count lines footer-height) page-lines)
         (page-break #f)))
  (define (flush-table)
    "Writes the table of the rows since it began, if one has."
    (when table-start
      (emit-text (table-markdown (table-slice data table-start rows-written) formats) (+ 2 (- rows-written table-start)))
      (set! table-start #f)))
  (define (end-table)
    "Ends the table being written, if there is one: markdown needs a blank line after it."
    (when table-start
      (flush-table)
      (emit-text "" 1)))
  (define (add-table-row place)
    "A row of the table: the first row of a table begins it, after a blank line (markdown needs one before it too)."
    (unless table-start
      (when (> line-count 0) (emit-text "" 1))
      (set! table-start place)))
  (define (write-block render-text)
    "Writes the text that (render-text) gives, unless it gives #f. It is written again if the page ends to make room
for it: what it says may be the page's number."
    (let ((text (render-text)))
      (when text
        (end-table)
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
                         collect (render (list-ref header-nodes (- l 1)) (cons (list 'continued #f) (group-bindings l))))))
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
    (set! repeat-through (- level 1))
    (reset-running (lambda (running-level) (and (> running-level 0) (>= running-level level))))
    (let ((new-page-breaks (filter (lambda (break) break)
                                   (loop for l from level to depth collect (report-break-new-page (list-ref breaks (- l 1)))))))
      (unless (null? new-page-breaks)
        (end-table)
        (page-break (not (null? (filter (lambda (l) (report-break-restart-page-numbers (list-ref breaks (- l 1))))
                                        (iota-from level depth)))))))
    (let ((headers (headers-from level)))
      (when headers
        (end-table)
        (when (room-for (+ (report--lines headers) detail-height))
          (set! headers (headers-from level)))
        (emit-text headers (report--lines headers))
        (set! content-keys current-keys))))

  (define (iota-from low high) (loop for l from low to high collect l))

  ; the report: one pass, or two if it says how many pages there are
  (define (write-all)
    (set! page 1)
    (set! pages 0)
    (set! line-count 0)
    (set! header-lines 0)
    (set! rows-written 0)
    (set! page-first-row 0)
    (set! group-indexes (loop for level from 1 to depth collect -1))
    (set! current-keys (loop for level from 1 to depth collect '()))
    (set! content-keys current-keys)
    (set! running-values (map (lambda (entry) 0) running))
    (set! repeat-through 0)
    (set! sequence 0)
    (set! page-totals '())
    (when (> rows 0) (set! current-keys (row-keys 0)))
    (start-page)
    (when report-header-nodes (write-block (lambda () (render report-header-nodes grand-bindings))))
    (loop for place from 0 below rows
          do (begin
               (let ((change (if (= place 0) 1 (vector-ref change-levels (- place 1)))))
                 (when (<= change depth)
                   (when (> place 0)
                     (set! repeat-through (- change 1))          ; the groups outside those that end go on
                     (write-block (lambda () (footers-from change))))
                   (begin-groups change place)))
               (when detail-nodes
                 (set! repeat-through depth)
                 (write-block (lambda () (render-detail place))))
               (when markdown
                 (add-table-row place))
               (add-running place)
               (set! rows-written (+ place 1))))
    (when (and (> rows 0) (> depth 0))
      (set! repeat-through 0)
      (write-block (lambda () (footers-from 1))))
    (when report-footer-nodes
      (set! repeat-through 0)
      (write-block (lambda () (render report-footer-nodes grand-bindings))))
    (flush-table)
    (close-page)
    (set! page-totals (append page-totals (list page))))

  (when uses-pages
    (set! sink (lambda (text) #f))
    (set! finish-page (lambda () #f))
    (write-all)
    (set! known-totals page-totals)
    (set! sink emit)
    (set! finish-page end-page))
  (write-all)
  pages)

; ---------------------------------------------------------------------------
; The two ways to have it
; ---------------------------------------------------------------------------

(define (report--text-end spec emit)
  "What ends a page of a text report: the page separator, if there is one."
  (let ((separator (report-spec-page-separator spec)))
    (lambda () (when (> (string-length separator) 0) (emit separator)))))

(define (report-text table spec)
  "The report of the table, as the spec says, as one string. For a short report: write-report writes a file, a
thousand lines at a time, and takes a table of any size."
  (report--check-spec table spec)
  (let* ((lines '())
         (emit (lambda (text) (set! lines (cons text lines)))))
    (report--run table spec emit (report--text-end spec emit))
    (string-append (string-join (reverse lines) "\n") "\n")))

(define (report--write-file path chunk body)
  "Calls (body put), where (put text) adds the text and a newline to the file at path, replacing what was there: chunk
texts at a time, so that a long report is not held. Gives back what body does."
  (write-text-file path "" #f)
  (let* ((lines '())
         (count 0)
         (flush (lambda ()
                  (when (> count 0)
                    (write-text-file path (string-append (string-join (reverse lines) "\n") "\n") #t))
                  (set! lines '())
                  (set! count 0)))
         (put (lambda (text)
                (set! lines (cons text lines))
                (set! count (+ count 1))
                (when (>= count chunk) (flush))))
         (result (body put)))
    (flush)
    result))

(define (write-report table path spec)
  "Writes the report of the table, as the spec says (see make-report-spec), to the text file at path, replacing
what was there. Returns the number of pages (1, if the spec has no :page-lines)."
  (report--check-spec table spec)
  (report--write-file path 1000 (lambda (put) (report--run table spec put (report--text-end spec put)))))

; ---------------------------------------------------------------------------
; The report as a web page
; ---------------------------------------------------------------------------

(define (report--escape text)
  "The text as HTML text: with &, < and > as the HTML that shows them."
  (string-replace (string-replace (string-replace text "&" "&amp;") "<" "&lt;") ">" "&gt;"))

(define report--html-top
  (string-append
    "<!DOCTYPE html>\n<html lang='en'>\n<head>\n<meta charset='utf-8'>\n"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
    "<script>document.documentElement.className = 'js';</script>\n"
    "<style>\n"
    ":root { --bg: #ffffff; --fg: #1b1b1b; --bar: #f1f1f1; --line: #c9c9c9; }\n"
    "@media (prefers-color-scheme: dark) { :root { --bg: #16181d; --fg: #e6e6e6; --bar: #23262d; --line: #3a3f4b; } }\n"
    "body { margin: 0; background: var(--bg); color: var(--fg); }\n"
    "main { padding: 16px 16px 84px; overflow-x: auto; }\n"
    "pre { font: 14px/1.35 ui-monospace, Menlo, Consolas, monospace; margin: 0 0 24px; }\n"
    ".js .page { display: none; }\n"
    ".js .page.current { display: block; }\n"
    "nav { display: none; position: fixed; left: 0; right: 0; bottom: 0; gap: 8px; align-items: center;\n"
    "      justify-content: center; flex-wrap: wrap; padding: 10px; background: var(--bar); border-top: 1px solid var(--line); }\n"
    ".js nav { display: flex; }\n"
    "button, input { font: inherit; padding: 6px 12px; border: 1px solid var(--line); border-radius: 6px;\n"
    "                background: var(--bg); color: var(--fg); }\n"
    "button { cursor: pointer; }\n"
    "button:disabled { opacity: 0.4; cursor: default; }\n"
    "input { width: 4.5em; text-align: center; padding: 5px; }\n"
    "@media print { nav { display: none !important; } .js .page { display: block; page-break-after: always; } }\n"
    "</style>\n"))

(define report--html-bottom
  (string-append
    "</main>\n<nav>\n"
    "<button id='first'>&laquo; First</button><button id='previous'>&lsaquo; Previous</button>\n"
    "<span>Page <input id='number' type='number' min='1' aria-label='Page number'> of <span id='total'></span></span>\n"
    "<button id='next'>Next &rsaquo;</button><button id='last'>Last &raquo;</button>\n"
    "</nav>\n<script>\n"
    "(function () {\n"
    "  var pages = document.querySelectorAll('.page');\n"
    "  var total = pages.length;\n"
    "  if (total === 0) { return; }\n"
    "  var current = 0;\n"
    "  var box = document.getElementById('number');\n"
    "  var buttons = { first: document.getElementById('first'), previous: document.getElementById('previous'),\n"
    "                  next: document.getElementById('next'), last: document.getElementById('last') };\n"
    "  document.getElementById('total').textContent = total;\n"
    "  box.max = total;\n"
    "  function show(n) {\n"
    "    n = Math.max(0, Math.min(total - 1, n));\n"
    "    pages[current].classList.remove('current');\n"
    "    current = n;\n"
    "    pages[current].classList.add('current');\n"
    "    box.value = n + 1;\n"
    "    buttons.first.disabled = buttons.previous.disabled = (n === 0);\n"
    "    buttons.next.disabled = buttons.last.disabled = (n === total - 1);\n"
    "    history.replaceState(null, '', '#p' + (n + 1));\n"
    "    window.scrollTo(0, 0);\n"
    "  }\n"
    "  buttons.first.onclick = function () { show(0); };\n"
    "  buttons.previous.onclick = function () { show(current - 1); };\n"
    "  buttons.next.onclick = function () { show(current + 1); };\n"
    "  buttons.last.onclick = function () { show(total - 1); };\n"
    "  box.onchange = function () { show(parseInt(box.value, 10) - 1); };\n"
    "  document.addEventListener('keydown', function (event) {\n"
    "    if (event.target === box) { return; }\n"
    "    if (event.key === 'ArrowRight' || event.key === 'PageDown') { show(current + 1); }\n"
    "    else if (event.key === 'ArrowLeft' || event.key === 'PageUp') { show(current - 1); }\n"
    "    else if (event.key === 'Home') { show(0); }\n"
    "    else if (event.key === 'End') { show(total - 1); }\n"
    "  });\n"
    "  var wanted = /^#p([0-9]+)$/.exec(location.hash);\n"
    "  show(wanted ? parseInt(wanted[1], 10) - 1 : 0);\n"
    "})();\n"
    "</script>\n</body>\n</html>"))

(define (write-report-html table path spec &key (title "Report"))
  "Writes the report of the table, as the spec says, to the web page at path, replacing what was there: a page of it
shown at a time, with a bar at the bottom to go on to the next page or back to the one before, to the first or the last, or to
a page by its number (the arrow keys work too). The pages are those of the report: the spec's :page-lines (50, if it
has none), with its headers and footers; and a page separator is not written. Without JavaScript the page shows them all,
one after another. Returns the number of pages. :title (\"Report\") is the title of the web page."
  (report--check-spec table spec)
  (when (report-spec-markdown spec)
    (error "write-report-html: a :markdown report is Markdown text, for write-report (and a notebook's display-markdown)"))
  (let ((spec (if (report-spec-page-lines spec)
                  spec
                  (let ((copy (copy-report-spec spec)))
                    (report-spec-page-lines-set! copy 50)
                    copy))))
    (report--write-file
      path 10                                  ; (a page is a text of sixty lines or so)
      (lambda (put)
        (put report--html-top)
        (put (string-append "<title>" (report--escape title) "</title>\n</head>\n<body>\n<main>"))
        (let ((page-lines '())
              (number 0))
          (let ((pages (report--run table spec
                                    (lambda (text) (set! page-lines (cons text page-lines)))
                                    (lambda ()
                                      (set! number (+ number 1))
                                      (put (string-append "<section class='page' id='p" (number->string number) "'><pre>"
                                                          (report--escape (string-join (reverse page-lines) "\n"))
                                                          "</pre></section>"))
                                      (set! page-lines '())))))
            (put report--html-bottom)
            pages))))))
