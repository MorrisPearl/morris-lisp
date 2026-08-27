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
;     under) resolves to that column's value at the CURRENT row (rebound
;     as an ordinary global variable once that column's been calculated
;     for this row -- see calculate-all's compute-row)
;   - (lag NAME n) resolves to that column's value n rows back, by
;     looking NAME up in the column registry directly (not through the
;     bare-name binding above, which only ever holds the CURRENT row's
;     value) -- see the `lag` macro and find-column
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

(define (register-column c)
  (set! *columns* (append *columns* (list c)))
  c)

; (defcolumn var-name :name "balance" :initial_value ... :after ...
;    :value_calculation (- ...))
; -- like make-column, but value_calculation is auto-quoted (it's a
; per-row FORMULA, not a value to compute right away -- forgetting this
; quote, since make-column is an ordinary function and would otherwise
; evaluate it immediately, is an easy mistake), and the result is both
; define'd as var-name and automatically registered.
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
       (define ,var-name (make-column ,@rewritten))
       (register-column ,var-name))))

; name: a symbol, e.g. 'balance -- matched against each registered
; column's declared (string) `name` slot.
(define (find-column name)
  (define (search lst)
    (cond
      ((null? lst) (error "lag/find-column: no column named" name))
      ((equal? (column-name (car lst)) (symbol->string name)) (car lst))
      (#t (search (cdr lst)))))
  (search *columns*))

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
; fills row 0 from `initial_value`, then for each row 1..n-1, in
; topological order, evaluates each column's value_calculation and
; records it -- both into that column's series vector (for `lag` to
; find) and as a plain global variable bound to the column's declared
; name (for a same-row, later-ordered column's bare-name reference).
; Finally displays every visible column via display-columns.
(define (calculate-all columns n)
  (define ordered (topo-sort columns))
  (dolist (c ordered)
    (column-series-set! c (make-vector n 0)))
  (dolist (c ordered)
    (vector-set! (column-series c) 0 (column-initial_value c)))
  (define (compute-row j)
    (if (< j n)
        (begin
          (eval (list 'define 'current-row j))
          (dolist (c ordered)
            (let ((v (eval (column-value_calculation c))))
              (vector-set! (column-series c) j v)
              (eval (list 'define (string->symbol (column-name c)) v))))
          (compute-row (+ j 1)))
        '()))
  (compute-row 1)
  (display-columns
   (map (lambda (c) (cons (column-name c) (column-series c)))
        (filter column-visible ordered)))
  ordered)
