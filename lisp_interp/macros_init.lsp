; macros_init.lsp
; ==============
; The standard macros, written in Lisp. Every new environment loads this
; file first, before anything else (see make_global_env in lisp_builtins.py),
; so these are always available.
;
;   (let ((name value)...) body...)
;   (let* ((name value)...) body...)
;   (dolist (var list [result]) body...)
;   (while test body...)
;   (do ((var init [step])...) (end-test result...) body...)
;   (assert test [message...])
;   (with-sqlite (var path) body...)
;   (with-columns (column...) table body...)
;   (when test body...)
;   (unless test body...)
;   (push item variable), (pop variable), (incf variable [n]), (decf variable [n])
;   (case key-expr ((key...) body...)... [(else body...)])
;   (destructuring-bind pattern expression body...)
;   (lazy-load file name...)
;   (save-variables path name... [:leave-out-procedures #t])
;   (pretty-print-function name), (pretty-print-macro name)
;
; let, let*, and dolist come first, because the other macros use them.
;
; while and do turn into a small local function that calls itself to run
; the next time around the loop. The call is a tail call, and the
; evaluator runs tail calls without growing the stack, so a loop can run
; any number of times. The name of that function comes from gensym, so it
; can't clash with any name in the loop's own code.
;
; HOW THESE MACROS ARE WRITTEN: QUOTE, BACKQUOTE, COMMA, AND COMMA-AT
; ---------------------------------------------------------------------
; A macro is given the code it was called with, NOT evaluated -- as data:
; lists and symbols. It returns new code, which is then evaluated in place
; of the call. So a macro's job is to build a list that is a piece of
; program. Four pieces of syntax make that easy:
;
;   'x      QUOTE. The expression x itself, not evaluated.
;             '(+ 1 2)            ; => (+ 1 2)   a list of three things, not 3
;
;   `x      BACKQUOTE (also called quasiquote). Like quote, a template for
;           a list, except that you can mark places in it to fill in.
;           Anything not marked is copied as it is:
;             (define n 5)
;             `(+ n 1)            ; => (+ n 1)
;
;   ,expr   COMMA (unquote), inside a backquote. Evaluates expr and puts
;           its value in that place:
;             `(+ ,n 1)           ; => (+ 5 1)
;
;   ,@expr  COMMA-AT (unquote-splicing), inside a backquote. Evaluates
;           expr, which must give a list, and puts the list's ELEMENTS in
;           that place, rather than the list itself:
;             (define xs (list 1 2 3))
;             `(+ ,xs)            ; => (+ (1 2 3))
;             `(+ ,@xs)           ; => (+ 1 2 3)
;             `(list 0 ,@xs 4)    ; => (list 0 1 2 3 4)
;
; They're short for ordinary lists: 'x is (quote x), `x is (quasiquote x),
; ,x is (unquote x), and ,@x is (unquote-splicing x).
;
; A worked example: the while macro below, called as
;
;   (while (< i 3) (display i) (set! i (+ i 1)))
;
; Its parameter list is (test . body), so test is the list (< i 3), and
; body -- because of the dot -- is the list of all the remaining forms,
; ((display i) (set! i (+ i 1))). Then (gensym "while-loop") makes a new
; symbol, say %while-loop-1, for loop-name. The template
;
;   `(let ()
;      (define (,loop-name)
;        (if ,test
;            (begin ,@body (,loop-name))
;            '()))
;      (,loop-name))
;
; becomes
;
;   (let ()
;     (define (%while-loop-1)
;       (if (< i 3)
;           (begin (display i) (set! i (+ i 1)) (%while-loop-1))
;           '()))
;     (%while-loop-1))
;
;   - ,test puts the test in place.
;   - ,@body puts the body forms in one after another. With ,body instead,
;     begin would get ONE form, the list ((display i) (set! i (+ i 1))),
;     which would be evaluated as a call -- a mistake.
;   - (,loop-name) is a list holding the generated symbol: a call to the
;     loop function.
;   - '() has no comma, so it's copied as it is. In the expansion it's the
;     value the loop returns when it's done.
;
; A quote followed by a comma, ',x, puts x in place and QUOTES it, so the
; expansion uses x as data instead of evaluating it. assert, below, uses
; this so that its error message can show the test's code:
;
;   (define test '(>= balance 0))
;   `(error "assert:" ,test "is false")    ; => (error "assert:" (>= balance 0) "is false")
;   `(error "assert:" ',test "is false")   ; => (error "assert:" (quote (>= balance 0)) "is false")
;
; With ,test the expansion would evaluate (>= balance 0) and show #f; with
; ',test it shows (>= balance 0).
;
; A macro's code runs at two different times. The code OUTSIDE the
; backquote -- like (gensym "while-loop"), or do's checks of its variable
; list -- runs once, when the macro builds the expansion. The code IN the
; backquote is what runs afterwards, each time the expansion is evaluated.
;
; To see what a macro call becomes, without running it:
;   (macroexpand-1 '(while (< i 3) (display i)))
;   (print-macroexpansion '(assert (>= balance 0)))    ; spread over several lines
; For more, see "Macros" in lisp_interpreter_reference.md, including why
; a macro should name its own variables with gensym ("What goes wrong
; without gensym").

; (let ((name value)...) body...)
; Evaluates each value, then evaluates the body forms in a new scope, with
; each name bound to its value, and returns the last one's value. All the
; values are evaluated before any name is bound, so a value can't use a name
; from the same let (let* can).
;
;   (let ((x 2) (y 3))
;     (* x y))                   ; => 6
;
; expands to a call of a procedure whose parameters are the names:
;
;   ((%scope-lambda (x y) (* x y)) 2 3)
;
; %scope-lambda is lambda, except that the procedure it makes is marked as a
; scope rather than a function, so stack traces and (verbose) leave it out.
(define (let--check-binding binding who)
  "Signal an error unless binding has the form (name value). (Whether name
can be a name is checked by %scope-lambda, as for any procedure.)"
  (if (not (and (pair? binding)
                (pair? (cdr binding))
                (null? (cddr binding))))
      (error who "each binding must be (name value), not" binding)
      '()))

(define (let--check-bindings bindings who)
  "Signal an error unless bindings is a list of (name value)."
  (if (not (list? bindings))
      (error who "expected a list of bindings, ((name value)...), not" bindings)
      (for-each (lambda (binding) (let--check-binding binding who)) bindings)))

(defmacro let (bindings . body)
  (let--check-bindings bindings "let:")
  `((%scope-lambda ,(map car bindings) ,@body)
    ,@(map cadr bindings)))

; (let* ((name value)...) body...)
; Like let, but binds the names one at a time, so each value can use the
; names before it.
;
;   (let* ((x 2)
;          (y (* x 10)))
;     (+ x y))                   ; => 22
;
; expands to one let inside another:
;
;   (let ((x 2))
;     (let* ((y (* x 10)))
;       (+ x y)))
(defmacro let* (bindings . body)
  (let--check-bindings bindings "let*:")
  (if (or (null? bindings) (null? (cdr bindings)))
      `(let ,bindings ,@body)
      `(let (,(car bindings))
         (let* ,(cdr bindings) ,@body))))

; (dolist (var list [result]) body...)
; Evaluates the body forms once for each element of list (a list or a
; vector), with var bound to that element, then returns the value of result
; ('() if there's none; var is '() while it's evaluated).
;
;   (define total 0)
;   (dolist (x '(1 2 3) total)
;     (set! total (+ total x)))  ; => 6
;
; expands to a local function that calls itself for the rest of the list:
;
;   (let ((%dolist-items-3 '(1 2 3)))
;     (define (%dolist-loop-1 %dolist-remaining-2)
;       (if (null? %dolist-remaining-2)
;           (let ((x '())) total)
;           (let ((x (car %dolist-remaining-2)))
;             (set! total (+ total x))
;             (%dolist-loop-1 (cdr %dolist-remaining-2)))))
;     (%dolist-loop-1 (cond ((list? %dolist-items-3) %dolist-items-3)
;                           ((vector? %dolist-items-3) (vector->list %dolist-items-3))
;                           (else (error "dolist: expected a list or a vector, not"
;                                        %dolist-items-3)))))
(defmacro dolist (spec . body)
  (if (not (and (pair? spec)
                (list? spec)
                (or (= (length spec) 2) (= (length spec) 3))))
      (error "dolist: expected (dolist (var list [result]) body...), not" spec)
      '())
  (let ((var (car spec))
        (list-expr (cadr spec))
        (result-expr (if (= (length spec) 3) (caddr spec) ''()))
        (loop-name (gensym "dolist-loop"))
        (remaining (gensym "dolist-remaining"))
        (items (gensym "dolist-items")))
    `(let ((,items ,list-expr))
       (define (,loop-name ,remaining)
         (if (null? ,remaining)
             (let ((,var '())) ,result-expr)
             (let ((,var (car ,remaining)))
               ,@body
               (,loop-name (cdr ,remaining)))))
       (,loop-name (cond ((list? ,items) ,items)
                         ((vector? ,items) (vector->list ,items))
                         (else (error "dolist: expected a list or a vector, not" ,items)))))))

; (while test body...)
; Evaluates test; if it's true, evaluates the body forms and starts again.
; Stops the first time test is false, and returns '().
;
;   (define i 0)
;   (while (< i 3)
;     (display i)
;     (set! i (+ i 1)))          ; prints 012
;
; expands to
;
;   (let ()
;     (define (%while-loop-1)
;       (if (< i 3)
;           (begin (display i) (set! i (+ i 1)) (%while-loop-1))
;           '()))
;     (%while-loop-1))
(defmacro while (test . body)
  (let ((loop-name (gensym "while-loop")))
    `(let ()
       (define (,loop-name)
         (if ,test
             (begin ,@body (,loop-name))
             '()))
       (,loop-name))))

; (do ((var init [step])...) (end-test result...) body...)
; Common Lisp's do loop. Binds each var to its init, then repeats:
;   1. if end-test is true, evaluate the result forms and return the last
;      one's value ('() if there are none);
;   2. otherwise evaluate the body forms, then give each var the value of
;      its step (a var with no step keeps its value), and go back to 1.
; All the steps are computed before any var changes, so each step sees the
; values from the time around the loop just finished.
;
;   (do ((i 0 (+ i 1))
;        (total 0 (+ total i)))
;       ((= i 5) total))         ; => 10  (0 + 1 + 2 + 3 + 4)
;
; expands to
;
;   (let ()
;     (define (%do-loop-2 i total)
;       (if (= i 5)
;           (begin total)
;           (begin (%do-loop-2 (+ i 1) (+ total i)))))
;     (%do-loop-2 0 0))
;
; Passing the new values as arguments to the loop function is what makes
; the steps all use the old values.
(define (do--check-var-spec spec)
  "Signal an error unless spec has the form (var init) or (var init step)."
  (if (not (and (pair? spec)
                (symbol? (car spec))
                (or (= (length spec) 2) (= (length spec) 3))))
      (error "do: each variable must be written (var init) or (var init step), not" spec)
      '()))

(defmacro do (var-specs end-clause . body)
  (dolist (spec var-specs) (do--check-var-spec spec))
  (if (not (pair? end-clause))
      (error "do: the second part must be (end-test result...), not" end-clause)
      '())
  (let* ((loop-name (gensym "do-loop"))
         (vars (map car var-specs))
         (inits (map (lambda (spec) (list-ref spec 1)) var-specs))
         (steps (map (lambda (spec) (if (= (length spec) 3) (list-ref spec 2) (car spec)))
                     var-specs))
         (end-test (car end-clause))
         (results (cdr end-clause))
         (result-form (if (null? results) ''() (cons 'begin results))))
    `(let ()
       (define (,loop-name ,@vars)
         (if ,end-test
             ,result-form
             (begin ,@body (,loop-name ,@steps))))
       (,loop-name ,@inits))))

; (assert test [message...])
; Does nothing if test is true. If it's false, stops with an error naming
; the test -- and, if given, the message, which is any number of values,
; displayed with spaces between them (as `error` does). Returns '().
;
;   (define balance -5)
;   (assert (>= balance 0))
;   ; error: assert: (>= balance 0) is false
;   (assert (>= balance 0) "balance went negative:" balance)
;   ; error: assert: (>= balance 0) is false: balance went negative: -5
;
; It's a macro, not a function, so that it can put the test's source code
; (not just its value, #f) into the message. The message is evaluated only
; if the test fails.
(defmacro assert (test . message)
  (if (null? message)
      `(if ,test '() (error "assert:" ',test "is false"))
      `(if ,test '() (error "assert:" ',test "is false:" ,@message))))

; (with-sqlite (var path) body...)
; Opens the SQLite database at path (creating it if it doesn't exist),
; binds var to the connection, and evaluates the body forms, returning the
; last one's value. The connection is always closed afterwards -- even if
; the body stops with an error or a throw -- so it's never left open.
;
;   (with-sqlite (conn "loans.db")
;     (sqlite-write-table conn "pools" pools 'replace)
;     (sqlite-query conn "SELECT count(*) AS n FROM pools"))
;
; expands to
;
;   (let ((conn (sqlite-open "loans.db")))
;     (unwind-protect
;         (begin (sqlite-write-table conn "pools" pools 'replace)
;                (sqlite-query conn "SELECT count(*) AS n FROM pools"))
;       (sqlite-close conn)))
;
; Each statement is saved to the database as soon as it runs (connections
; are in SQLite's autocommit mode), so there's nothing to commit before the
; connection closes.
(defmacro with-sqlite (spec . body)
  (if (not (and (pair? spec) (symbol? (car spec)) (= (length spec) 2)))
      (error "with-sqlite: expected (with-sqlite (var path) body...), not" spec)
      '())
  (let ((var (car spec))
        (path (list-ref spec 1)))
    `(let ((,var (sqlite-open ,path)))
       (unwind-protect
           (begin ,@body)
         (sqlite-close ,var)))))

; (with-columns (column...) table body...)
; Evaluates table once, then evaluates the body forms with a variable for
; each column listed, bound to that column's vector (as table-column gives
; it), and returns the last one's value -- as Common Lisp's with-slots does
; for an object's slots. Each column is written as
;
;   name                 a variable called name, for the column of the same
;                        name (a name keeps its case: SP500 is the column
;                        "SP500")
;   (variable "column")  a variable called variable, for the column
;                        "column" -- for a column whose name would hide a
;                        function the body calls (such as date), or can't be
;                        a variable (such as "2024", or a name with spaces)
;
;   (with-columns ((day "date") close) prices
;     (vector-select close (>= day (date 2024 1 3))))
;
; expands to (with a gensym name for the table, so it's evaluated only once)
;
;   (let ((%with-columns-table-1 prices))
;     (let ((day (table-column %with-columns-table-1 "date"))
;           (close (table-column %with-columns-table-1 "close")))
;       (vector-select close (>= day (date 2024 1 3)))))
(define (with-columns--binding column table-var)
  "One entry of with-columns' column list -- name, or (variable \"column\")
-- as the let binding it becomes."
  (cond ((symbol? column)
         `(,column (table-column ,table-var ,(symbol->string column))))
        ((and (list? column)
              (= (length column) 2)
              (symbol? (car column))
              (string? (cadr column)))
         `(,(car column) (table-column ,table-var ,(cadr column))))
        (else
         (error "with-columns: each column must be a name, or (variable \"column\"), not" column))))

(defmacro with-columns (columns table . body)
  (if (not (list? columns))
      (error "with-columns: expected (with-columns (column...) table body...), not" columns)
      '())
  (let ((table-var (gensym "with-columns-table")))
    `(let ((,table-var ,table))
       (let ,(map (lambda (column) (with-columns--binding column table-var)) columns)
         ,@body))))

; (when test body...)
; If test is true, evaluates the body forms and returns the last one's
; value; otherwise returns '(). Like an if with no else, but with room for
; several forms.
;
;   (when (> balance 0)
;     (display "paying down ")
;     (set! balance (- balance payment)))
;
; expands to
;
;   (if (> balance 0)
;       (begin (display "paying down ") (set! balance (- balance payment)))
;       '())
(defmacro when (test . body)
  `(if ,test (begin ,@body) '()))

; (unless test body...)
; The opposite of when: if test is false, evaluates the body forms and
; returns the last one's value; otherwise returns '().
;
;   (unless (sqlite-connection? conn)
;     (error "not a connection:" conn))
(defmacro unless (test . body)
  `(if ,test '() (begin ,@body)))

; (push item variable), (pop variable)
; push puts item on the front of the list in variable, and returns the new
; list; pop takes the first item off, and returns it -- as in Common Lisp,
; but only for a variable (there's no setf here).
;
;   (define stack '())
;   (push 1 stack)       ; stack is (1)
;   (push 2 stack)       ; stack is (2 1)
;   (pop stack)          ; => 2, and stack is (1)
(defmacro push (item variable)
  (unless (symbol? variable)
    (error "push: expected a variable to push onto, not" variable))
  `(begin (set! ,variable (cons ,item ,variable)) ,variable))

(defmacro pop (variable)
  (unless (symbol? variable)
    (error "pop: expected a variable to pop from, not" variable))
  (let ((first-item (gensym)))
    `(let ((,first-item (car ,variable)))
       (set! ,variable (cdr ,variable))
       ,first-item)))

; (incf variable [n]), (decf variable [n])
; Add n (1 unless given) to the number in variable, or take it away, and
; return the new value -- as in Common Lisp, but only for a variable.
;
;   (incf count)         ; (set! count (+ count 1))
;   (decf balance 100)   ; (set! balance (- balance 100))
(defmacro incf (variable . n)
  (unless (symbol? variable)
    (error "incf: expected a variable, not" variable))
  `(begin (set! ,variable (+ ,variable ,(if (null? n) 1 (car n)))) ,variable))

(defmacro decf (variable . n)
  (unless (symbol? variable)
    (error "decf: expected a variable, not" variable))
  `(begin (set! ,variable (- ,variable ,(if (null? n) 1 (car n)))) ,variable))

; (case key-expr clause...)
; Evaluates key-expr once, finds the first clause whose keys include its
; value, and evaluates that clause's body forms, returning the last one's
; value. The keys are compared with the value as member compares them
; (with equal?), so they can be symbols, numbers, or strings. They are not
; evaluated: write them as they are, without a quote. Each clause is one of
;
;   ((key1 key2 ...) body...)   several keys
;   (key body...)               a single key
;   (else body...)              used if no other clause matches; it must be
;                               the last clause (otherwise works the same,
;                               as in Common Lisp)
;
; If nothing matches and there's no else clause, case returns '().
;
;   (define (region state)
;     (case state
;       (("CA" "OR" "WA") 'west)
;       (("NY" "NJ" "CT") 'northeast)
;       (else 'other)))
;   (region "OR")              ; => west
;
; expands to (with a gensym name for the key, so key-expr is evaluated
; only once)
;
;   (let ((%case-key-1 state))
;     (cond ((member %case-key-1 '("CA" "OR" "WA")) 'west)
;           ((member %case-key-1 '("NY" "NJ" "CT")) 'northeast)
;           (else 'other)))
(define (case--else-clause? clause)
  "Whether clause is an else (or otherwise) clause."
  (or (eq? (car clause) 'else) (eq? (car clause) 'otherwise)))

(define (case--cond-clause key-var clause last?)
  "One case clause, as the cond clause it becomes. last? says whether it's
the last clause, the only place an else clause is allowed."
  (cond ((not (pair? clause))
         (error "case: each clause must be ((key...) body...), (key body...), or (else body...), not"
                clause))
        ((case--else-clause? clause)
         (if last?
             (cons 'else (cdr clause))
             (error "case: the" (car clause) "clause must be the last one")))
        (else
         (let ((keys (if (list? (car clause)) (car clause) (list (car clause)))))
           (cons `(member ,key-var ',keys) (cdr clause))))))

(define (case--cond-clauses key-var clauses)
  "All the case clauses, as cond clauses."
  (if (null? clauses)
      '()
      (cons (case--cond-clause key-var (car clauses) (null? (cdr clauses)))
            (case--cond-clauses key-var (cdr clauses)))))

(defmacro case (key-expr . clauses)
  (let ((key-var (gensym "case-key")))
    `(let ((,key-var ,key-expr))
       (cond ,@(case--cond-clauses key-var clauses)))))

; (destructuring-bind pattern expression body...)
; Evaluates expression, which gives a list, binds the variables in pattern
; to its parts, and evaluates the body forms with them, as Common Lisp's
; destructuring-bind does. The pattern has the list's shape:
;
;   (destructuring-bind (name (low high) &optional (step 1) &key (label name))
;       '("range" (0 10) 2 :label "R")
;     (list name low high step label))           ; => ("range" 0 10 2 "R")
;
; A pattern can have, in this order:
;   variables      one for each element, or a pattern of its own, for an
;                  element that is a list: (a (b c) d)
;   &optional      then variables for elements that may be missing: x,
;                  (x default), or (x default supplied-p) -- supplied-p is
;                  bound to #t if the element is there and #f if not. The
;                  default is '() unless given, and can use the variables
;                  before it. x can be a pattern: ((low high) '(0 1)).
;   &rest x, or &body x, or a dot: (a b . x)
;                  x is bound to the rest of the list
;   &key           then keyword arguments, from :name value pairs in the
;                  rest of the list: x, (x default), or (x default
;                  supplied-p), for :x. Any other key is an error, unless
;                  &allow-other-keys comes after them.
;   &aux           then more variables, not from the list: x, or (x value)
; and it can start with &whole x, for x to be bound to the whole list.
;
; It is an error if the list has fewer elements than the variables before
; &optional, or more than the pattern has room for (and there's no &rest).
;
; It expands to a let*, with a variable for what's left of the list as it
; goes, and a check wherever the list might not fit. The example above
; becomes (with %list-1, %rest-2, ... from gensym):
;
;   (let* ((%list-1 '("range" (0 10) 2 :label "R"))
;          (%rest-2 %list-1)
;          (name (destructuring--next %rest-2 '(name (low high) ...) %list-1))
;          (%rest-2 (cdr %rest-2))
;          (%part-3 (destructuring--next %rest-2 '(name (low high) ...) %list-1))
;          (%rest-4 %part-3)
;          (low (destructuring--next %rest-4 '(low high) %part-3))
;          (%rest-4 (cdr %rest-4))
;          (high (destructuring--next %rest-4 '(low high) %part-3))
;          (%rest-4 (cdr %rest-4))
;          (%end-5 (destructuring--end %rest-4 '(low high) %part-3))
;          (%rest-2 (cdr %rest-2))
;          (%supplied-6 (pair? %rest-2))
;          (step (if %supplied-6 (car %rest-2) 1))
;          (%rest-2 (if %supplied-6 (cdr %rest-2) %rest-2))
;          (%keys-7 (destructuring--check-keys %rest-2 '(name (low high) ...) %list-1 '("label") #f))
;          (%supplied-8 (destructuring--has-key? %rest-2 "label"))
;          (label (if %supplied-8 (destructuring--key-value %rest-2 "label") name)))
;     (list name low high step label))
;
; (Let* binds a name again by making a new scope inside the last, so
; %rest-2 is a new variable each time, holding less of the list.)

(define destructuring--markers '(&optional &rest &body &key &allow-other-keys &aux &whole))

(define (destructuring--marker? x)
  "Whether x is one of the words that start a part of a pattern, such as &optional."
  (and (symbol? x) (member x destructuring--markers)))

(define (destructuring--error message shape whole)
  (error (string-append "destructuring-bind: " (to-string whole) " doesn't fit the pattern " (to-string shape)
                        ": " message)))

; What the expansion calls, as it takes the list apart:

(define (destructuring--next rest shape whole)
  "The next element of the list: the first of rest, what's left of it."
  (cond ((pair? rest) (car rest))
        ((null? rest) (destructuring--error "it has too few elements" shape whole))
        (else (destructuring--error "it isn't a list" shape whole))))

(define (destructuring--end rest shape whole)
  "Check that nothing is left of the list."
  (unless (null? rest)
    (destructuring--error (if (pair? rest) "it has too many elements" "it isn't a list") shape whole)))

(define (destructuring--key-names rest)
  "The names of the keys in rest, a list of :name value pairs: (\"x\" \"y\") for (:x 1 :y 2);
#f if rest isn't such a list."
  (cond ((null? rest) '())
        ((and (pair? rest) (keyword? (car rest)) (pair? (cdr rest)))
         (let ((more (destructuring--key-names (cddr rest))))
           (and more (cons (substring (symbol->string (car rest)) 1) more))))
        (else #f)))

(define (destructuring--check-keys rest shape whole names allow-other-keys)
  "Check that rest is a list of :name value pairs, with no name that isn't
one of names (unless allow-other-keys)."
  (let ((given (destructuring--key-names rest)))
    (unless given
      (destructuring--error "its keyword arguments must be :name value pairs" shape whole))
    (unless allow-other-keys
      (dolist (name given)
        (unless (member name names)
          (destructuring--error (string-append ":" name " isn't one of the pattern's keys") shape whole))))))

(define (destructuring--has-key? rest name)
  "Whether rest, a list of :name value pairs, has the key :name."
  (and (pair? rest)
       (or (equal? (symbol->string (car rest)) (string-append ":" name))
           (destructuring--has-key? (cddr rest) name))))

(define (destructuring--key-value rest name)
  "The value of the key :name in rest, a list of :name value pairs (the first, if it's there twice)."
  (if (equal? (symbol->string (car rest)) (string-append ":" name))
      (cadr rest)
      (destructuring--key-value (cddr rest) name)))

; What makes the expansion: each returns a list of let* bindings.

(define (destructuring--bindings pattern whole)
  "The bindings for pattern's variables, from the list in the variable whole."
  (let ((rest (gensym "rest")))
    (if (and (pair? pattern) (eq? (car pattern) '&whole))
        (begin
          (unless (pair? (cdr pattern))
            (error "destructuring-bind: expected a variable after &whole in" pattern))
          `(,@(destructuring--variable (cadr pattern) whole)
            (,rest ,whole)
            ,@(destructuring--required (cddr pattern) rest pattern whole)))
        `((,rest ,whole) ,@(destructuring--required pattern rest pattern whole)))))

(define (destructuring--variable target value)
  "The bindings for target -- a variable, or a pattern of its own -- to the value of the code value."
  (cond ((and (symbol? target) (not (keyword? target)) (not (destructuring--marker? target)))
         `((,target ,value)))
        ((pair? target)
         (let ((part (gensym "part")))
           `((,part ,value) ,@(destructuring--bindings target part))))
        (else (error "destructuring-bind: a pattern's variables must be names, not" target))))

(define (destructuring--end-check rest shape whole)
  `((,(gensym "end") (destructuring--end ,rest ',shape ,whole))))

(define (destructuring--required pattern rest shape whole)
  "The bindings for a pattern's variables before any &optional."
  (cond ((null? pattern) (destructuring--end-check rest shape whole))
        ((not (pair? pattern)) (destructuring--variable pattern rest))           ; (a b . more)
        ((eq? (car pattern) '&optional) (destructuring--optional (cdr pattern) rest shape whole))
        ((destructuring--marker? (car pattern)) (destructuring--after-optional pattern rest shape whole))
        (else `(,@(destructuring--variable (car pattern) `(destructuring--next ,rest ',shape ,whole))
                (,rest (cdr ,rest))
                ,@(destructuring--required (cdr pattern) rest shape whole)))))

(define (destructuring--optional pattern rest shape whole)
  "The bindings for the variables after &optional."
  (if (or (not (pair? pattern)) (destructuring--marker? (car pattern)))
      (destructuring--after-optional pattern rest shape whole)
      (let* ((spec (car pattern))                 ; x, or (x [default [supplied-p]]), where x can be a pattern
             (target (if (pair? spec) (car spec) spec))
             (default (if (and (pair? spec) (pair? (cdr spec))) (cadr spec) ''()))
             (supplied (if (and (pair? spec) (pair? (cdr spec)) (pair? (cddr spec))) (caddr spec) (gensym "supplied"))))
        `((,supplied (pair? ,rest))
          ,@(destructuring--variable target `(if ,supplied (car ,rest) ,default))
          (,rest (if ,supplied (cdr ,rest) ,rest))
          ,@(destructuring--optional (cdr pattern) rest shape whole)))))

(define (destructuring--after-optional pattern rest shape whole)
  "The bindings for the rest of a pattern, from &rest, &body, &key, &aux, a dot, or its end."
  (cond ((null? pattern) (destructuring--end-check rest shape whole))
        ((not (pair? pattern)) (destructuring--variable pattern rest))
        ((member (car pattern) '(&rest &body))
         (unless (pair? (cdr pattern))
           (error "destructuring-bind: expected a variable after" (car pattern) "in" shape))
         `(,@(destructuring--variable (cadr pattern) rest)
           ,@(destructuring--after-rest (cddr pattern) rest shape whole)))
        ((eq? (car pattern) '&key) (destructuring--keys (cdr pattern) rest shape whole))
        ((eq? (car pattern) '&aux)
         `(,@(destructuring--end-check rest shape whole) ,@(destructuring--aux (cdr pattern) shape)))
        (else (error "destructuring-bind:" (car pattern) "can't be there in the pattern" shape))))

(define (destructuring--after-rest pattern rest shape whole)
  "The bindings for what comes after &rest x: &key, &aux, or nothing."
  (cond ((null? pattern) '())
        ((eq? (car pattern) '&key) (destructuring--keys (cdr pattern) rest shape whole))
        ((eq? (car pattern) '&aux) (destructuring--aux (cdr pattern) shape))
        (else (error "destructuring-bind:" (car pattern) "can't be there in the pattern" shape))))

(define (destructuring--key-specs pattern)
  "The &key specs at the start of pattern: up to the next marker, or the end."
  (if (or (null? pattern) (destructuring--marker? (car pattern)))
      '()
      (cons (car pattern) (destructuring--key-specs (cdr pattern)))))

(define (destructuring--key spec rest)
  "The bindings for one &key spec: x, (x default), or (x default supplied-p)."
  (let* ((variable (if (pair? spec) (car spec) spec))
         (default (if (and (pair? spec) (pair? (cdr spec))) (cadr spec) ''()))
         (supplied (if (and (pair? spec) (pair? (cdr spec)) (pair? (cddr spec))) (caddr spec) (gensym "supplied")))
         (name (if (and (symbol? variable) (not (keyword? variable))) (symbol->string variable) #f)))
    (unless name
      (error "destructuring-bind: a key's variable must be a name, not" variable))
    `((,supplied (destructuring--has-key? ,rest ,name))
      (,variable (if ,supplied (destructuring--key-value ,rest ,name) ,default)))))

(define (destructuring--keys pattern rest shape whole)
  "The bindings for the variables after &key, then any &aux."
  (let* ((specs (destructuring--key-specs pattern))
         (after (list-tail pattern (length specs)))
         (allow-other-keys (and (pair? after) (eq? (car after) '&allow-other-keys)))
         (after (if allow-other-keys (cdr after) after))
         (names (map (lambda (spec) (symbol->string (if (pair? spec) (car spec) spec))) specs)))
    `((,(gensym "keys") (destructuring--check-keys ,rest ',shape ,whole ',names ,allow-other-keys))
      ,@(apply append (map (lambda (spec) (destructuring--key spec rest)) specs))
      ,@(cond ((null? after) '())
              ((eq? (car after) '&aux) (destructuring--aux (cdr after) shape))
              (else (error "destructuring-bind:" (car after) "can't be there in the pattern" shape))))))

(define (destructuring--aux pattern shape)
  "The bindings for the variables after &aux: x, or (x value)."
  (map (lambda (spec)
         (cond ((pair? spec) (list (car spec) (if (pair? (cdr spec)) (cadr spec) ''())))
               ((destructuring--marker? spec)
                (error "destructuring-bind:" spec "can't be there in the pattern" shape))
               (else (list spec ''()))))
       pattern))

(defmacro destructuring-bind (pattern expression . body)
  (let ((whole (gensym "list")))
    `(let* ((,whole ,expression)
            ,@(destructuring--bindings pattern whole))
       ,@body)))

; (lazy-load file name...)
; Makes each name a function that, the first time it's called, loads file,
; and then calls the function of that name that the file defined, with the
; same arguments, and returns what it does. So a library's functions can be
; called without loading it first, and it isn't loaded until one of them
; is. (Emacs Lisp calls this autoload.) It returns the names.
;
;   (lazy-load "solver.lsp" ridders nelder-mead)
;   (ridders (lambda (x) (- (* x x) 2)) 0 2)     ; loads solver.lsp, then calls ridders
;
; Each name is defined as a stand-in, a "stub", which the file's own
; definition replaces when it's loaded -- the stubs of all the names at
; once, since the file defines them all. A stub looks up its name again
; after the load, so it finds the file's function there:
;
;   (define (ridders . %arguments-2)
;     "Loads solver.lsp, which defines ridders, and calls it."
;     (let ((%stub-1 ridders))
;       (load "solver.lsp")
;       (when (eq? ridders %stub-1)
;         (error "lazy-load:" "solver.lsp" "didn't define" 'ridders))
;       (apply ridders %arguments-2)))
;
; It works for functions, and not for a file's macros or variables: a
; macro is needed before the code that uses it is evaluated, and a
; variable isn't called. lib/autoloads.lsp has the lazy-loads for the
; libraries that come with the interpreter.

(define (lazy-load--stub file name)
  "The definition of the stub for name, which loads file and calls the name's new function."
  (unless (and (symbol? name) (not (keyword? name)))
    (error "lazy-load: expected the names of functions, not" name))
  (let ((stub (gensym "stub"))
        (arguments (gensym "arguments")))
    `(define ,(cons name arguments)               ; (name . arguments): every argument, as a list
       ,(format "Loads {}, which defines {}, and calls it." file name)
       (let ((,stub ,name))
         (load ,file)
         (when (eq? ,name ,stub)
           (error "lazy-load:" ,file "didn't define" ',name))
         (apply ,name ,arguments)))))

(defmacro lazy-load (file . names)
  (when (null? names)
    (error "lazy-load: expected (lazy-load file name...), with at least one name"))
  `(begin
     ,@(map (lambda (name) (lazy-load--stub file name)) names)
     ',names))

; (save-variables path name... [:leave-out-procedures #t])
; Saves each named variable's value -- numbers, strings, lists, vectors,
; tables, dates, hash tables, structs, regression models -- in the JSON
; file at path (replacing the file, if there is one), and returns their
; names. (load-variables path) defines them all again, in this session or
; a later one. With :leave-out-procedures #t, a struct's slots that hold
; procedures are left out of the file, and load-variables gives them their
; defaults. It's a macro so that it sees the variables' names, and not just
; their values:
;
;   (save-variables "work.json" loans rates :leave-out-procedures #t)
;
; expands to
;
;   (%save-variables "work.json" (list (cons 'loans loans) (cons 'rates rates))
;                    :leave-out-procedures #t)
;
; and %save-variables, in lisp_save.py, writes the file.
(define (save-variables--names arguments)
  "The names given to save-variables: its arguments up to the first keyword."
  (if (or (null? arguments) (keyword? (car arguments)))
      '()
      (cons (car arguments) (save-variables--names (cdr arguments)))))

(define (save-variables--options arguments)
  "The options given to save-variables: its arguments from the first keyword on."
  (if (or (null? arguments) (keyword? (car arguments)))
      arguments
      (save-variables--options (cdr arguments))))

(define (save-variables--pair name)
  "One of save-variables' names, as the (name . value) pair it saves."
  (unless (symbol? name)
    (error "save-variables: expected the names of variables, not" name))
  `(cons ',name ,name))

(defmacro save-variables (path . arguments)
  (let ((names (save-variables--names arguments))
        (options (save-variables--options arguments)))
    (when (null? names)
      (error "save-variables: expected (save-variables path name... [:leave-out-procedures #t]),"
             "with at least one name"))
    `(%save-variables ,path (list ,@(map save-variables--pair names)) ,@options)))

; (pretty-print-function name), (pretty-print-macro name)
; Print the definition of the procedure, or macro, called name, spread out
; one element per line (see pretty-print in lisp_interpreter_reference.md).
; They're macros so that you can write the name without a quote:
;
;   (pretty-print-function monthly-payment)
(defmacro pretty-print-function (name)
  `(pretty-print-function-named ',name ,name))

(defmacro pretty-print-macro (name)
  `(pretty-print-macro-named ',name ,name))
