; column_engine.lsp
;
; A small example library, built entirely on top of defstruct and &key
; keyword arguments (see lisp_interpreter.py), for modeling row-by-row
; calculated series -- e.g. a mortgage amortization table, or more
; generally the cashflows of a structured transaction (CMO tranches and
; the like). This is ordinary Lisp code, not interpreter internals: read
; it, and change it, freely -- it's meant to communicate an approach, not
; be the only way to do this.
;
; The idea: define a `column` for each series you want (a balance, a
; principal paydown, an interest accrual, ...) with make-column/defcolumn,
; register it, then call calculate-all with how many rows (periods) to
; compute. Each column's value_calculation is a QUOTED formula, evaluated
; once per row, in which:
;   - a bare column NAME (its declared `name` slot -- e.g. `balance` --
;     not necessarily the same as whatever Lisp variable it's define'd
;     under) resolves to that column's value at the CURRENT row if it's
;     already been calculated this row (in topological order), or
;     otherwise its PREVIOUS row's value -- every column's name is bound
;     to SOMETHING before any value_calculation runs, so column B can
;     depend on column A's fresh current-row value, while column A can
;     depend on column B's previous-row value, with neither needing exact
;     `after` bookkeeping to avoid an unbound-variable error. See
;     calculate-all's two-pass compute-row, below.
;   - (lag NAME n) resolves to that column's value n rows back, always
;     precisely (never a same-row value), by reading NAME's series vector
;     directly through the column registry -- see the `lag` macro and
;     find-column
;
; CAVEAT: because a column's declared name becomes a real global variable
; while calculating, a column named e.g. "list" would shadow the builtin
; of that name. Not fixed here, just flagged -- pick column names that
; don't collide with builtins you use in the same formulas.

(defstruct column
  name                  ; string: the display/reference name, e.g. "balance"
  initial_value         ; row-0 value -- an ordinary value, evaluated once,
                         ; when make-column/defcolumn is called
  value_calculation     ; a QUOTED expression, evaluated once per row --
                         ; see defcolumn, which quotes this slot for you
  after                 ; () (a root column), a single column, or a list
                         ; of columns that must be calculated first
  (series ())           ; filled in by calculate-all: an N-element vector
  (visible #t))         ; #f = calculated but not shown by display-columns

(define *columns* '())

; The column most recently defined by defcolumn -- defcolumn's default
; `after`, so a plain sequence of defcolumn calls chains together in
; declaration order without having to spell out :after every time; only
; branch/merge points need an explicit :after.
(define *last-column* '())

(define (register-column c)
  (set! *columns* (append *columns* (list c)))
  c)

; (defcolumn var-name :name "balance" :initial_value ... :after ...
;    :value_calculation (- ...))
; -- like make-column, but:
;   - value_calculation is auto-quoted (it's a per-row FORMULA, not a
;     value to compute right away -- forgetting this quote, since
;     make-column is an ordinary function and would otherwise evaluate it
;     immediately, is an easy mistake)
;   - :name defaults to var-name itself (as a string), :after defaults to
;     *last-column* (the previously defcolumn'd column), and
;     :initial_value defaults to 0.0 -- supplying any of them explicitly
;     overrides the default, same as any other keyword argument
;   - the result is both define'd as var-name and automatically
;     registered (updating *last-column*)
(defmacro defcolumn (var-name . plist)
  (define (quote-value-calc items)
    (cond
      ((null? items) '())
      ((eq? (car items) :value_calculation)
       (cons (car items)
             (cons (list 'quote (car (cdr items)))
                   (quote-value-calc (cdr (cdr items))))))
      (#t (cons (car items)
                (cons (car (cdr items))
                      (quote-value-calc (cdr (cdr items))))))))
  (let ((rewritten (quote-value-calc plist)))
    `(begin
       (define ,var-name
         (make-column :name ,(symbol->string var-name)
                      :after *last-column*
                      :initial_value 0.0
                      ,@rewritten))
       (register-column ,var-name)
       (set! *last-column* ,var-name))))

; Bound by calculate-all while a column's value_calculation is running --
; current-row to the row index, current-column to the column struct
; itself -- so `lag`/find-column can resolve name reuse relative to
; "where" the currently-running formula is (see find-column, below).
(define current-row '())
(define current-column '())

(define (position-of item lst i)
  (cond
    ((null? lst) -1)
    ((eq? (car lst) item) i)
    (#t (position-of item (cdr lst) (+ i 1)))))

; name: a symbol, e.g. 'balance -- matched against each registered
; column's declared (string) `name` slot. The usual case is exactly one
; match, returned directly -- REGARDLESS of registration order, so a
; column can freely (lag ...) a column defined LATER in the script (e.g.
; one waterfall stage depending on a lagged value of a later stage).
;
; If the SAME name was registered more than once (e.g. re-using
; "cash-remaining" at each stage of a waterfall), resolves to the most
; recent one AT OR BEFORE current-column (bound by calculate-all while a
; formula runs) -- so an earlier stage's reference and a later stage's
; each pick up whichever prior use of that name is nearest to where THEY
; are, not always the same, final one. Falls back to the last (most
; recently registered) match when current-column isn't set, or is
; positioned before every match.
(define (find-column name)
  (define target (symbol->string name))
  (define (collect lst i)
    (cond
      ((null? lst) '())
      ((equal? (column-name (car lst)) target)
       (cons (cons i (car lst)) (collect (cdr lst) (+ i 1))))
      (#t (collect (cdr lst) (+ i 1)))))
  (define matches (collect *columns* 0))
  (cond
    ((null? matches) (error "lag/find-column: no column named" name))
    ((null? (cdr matches)) (cdr (car matches)))
    (#t
     (let ((cur-pos (if (null? current-column) -1 (position-of current-column *columns* 0)))
           (last-match (cdr (car (reverse matches)))))
       (define (scan remaining best)
         (cond
           ((null? remaining) best)
           ((<= (car (car remaining)) cur-pos) (scan (cdr remaining) (cdr (car remaining))))
           (#t best)))
       (scan matches last-match)))))

(defmacro lag (name n)
  `(vector-ref (column-series (find-column ',name)) (- current-row ,n)))

; Normalize a column's `after` slot into a list of prerequisite columns:
; () stays (), a single column becomes a one-element list, and a list
; (for a column that depends on more than one other -- useful once you're
; past a simple chain, e.g. modeling a CMO tranche) passes through as-is.
(define (normalize-after a)
  (cond
    ((null? a) '())
    ((column? a) (list a))
    (#t a)))

(define (contains? item lst)
  (cond
    ((null? lst) #f)
    ((eq? (car lst) item) #t)
    (#t (contains? item (cdr lst)))))

(define (all-satisfied? prereqs done)
  (cond
    ((null? prereqs) #t)
    ((contains? (car prereqs) done) (all-satisfied? (cdr prereqs) done))
    (#t #f)))

; Kahn's algorithm: repeatedly pull out every column whose `after`
; prerequisites are already in `done`, until every column has been
; placed (or nothing is ready, which means a cycle or a typo'd `after`).
(define (topo-sort columns)
  (define (visit remaining done)
    (cond
      ((null? remaining) done)
      (#t
       (let ((ready (filter (lambda (c) (all-satisfied? (normalize-after (column-after c)) done))
                             remaining)))
         (if (null? ready)
             (error "calculate-all: circular or missing `after` dependency")
             (visit (filter (lambda (c) (not (contains? c ready))) remaining)
                    (append done ready)))))))
  (visit columns '()))

; (calculate-all columns n) -- columns: a list of column structs (e.g.
; *columns*); n: how many rows (periods) to compute, including row 0.
; Orders the columns by `after`, pre-allocates each one's `series`,
; fills row 0 from `initial_value`, then for each row 1..n-1:
;   pass 1 -- binds EVERY column's bare name to its PREVIOUS row's value
;             (a plain global variable, via eval+define since the name
;             is only known at runtime -- see bind-name), so every
;             formula about to run in pass 2 already has a defined value
;             to see for ANY other column, before any of THIS row's
;             values exist yet;
;   pass 2 -- in topological order, evaluates each column's
;             value_calculation (current-column bound to it throughout,
;             for find-column/lag), records the result into its series
;             vector, and overwrites its pass-1 binding with that fresh
;             value -- so a LATER column (this row, in topological order)
;             sees the current-row value instead of pass 1's carry-
;             forward, while an EARLIER one (or one reached via `lag`)
;             still only ever saw the previous row's.
; Finally displays every visible column via display-columns.
(define (calculate-all columns n)
  (define ordered (topo-sort columns))
  (dolist (c ordered)
    (column-series-set! c (make-vector n 0)))
  (dolist (c ordered)
    (vector-set! (column-series c) 0 (column-initial_value c)))
  (define (bind-name c value)
    (eval (list 'define (string->symbol (column-name c)) value)))
  (define (compute-row j)
    (if (< j n)
        (begin
          (set! current-row j)
          (dolist (c ordered)
            (bind-name c (vector-ref (column-series c) (- j 1))))
          (dolist (c ordered)
            (set! current-column c)
            (let ((v (eval (column-value_calculation c))))
              (vector-set! (column-series c) j v)
              (bind-name c v)))
          (compute-row (+ j 1)))
        '()))
  (compute-row 1)
  (set! current-column '())
  (display-columns
   (map (lambda (c) (cons (column-name c) (column-series c)))
        (filter column-visible ordered)))
  ordered)
