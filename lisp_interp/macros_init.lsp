; macros_init.lsp
; ==============
; The standard macros, written in Lisp. Every new environment loads this
; file first, before init.lsp (see load_init_file in lisp_builtins.py), so
; these are always available.
;
;   (while test body...)
;   (do ((var init [step])...) (end-test result...) body...)
;   (assert test [message...])
;   (with-sqlite (var path) body...)
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
