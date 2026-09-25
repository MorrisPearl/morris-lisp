; macros_init.lsp
; ==============
; The standard macros, written in Lisp. Every new environment loads this
; file first, before init.lsp (see load_init_file in lisp_builtins.py), so
; these are always available.
;
;   (while test body...)
;   (do ((var init [step])...) (end-test result...) body...)
;
; Both turn into a small local function that calls itself to run the next
; time around the loop. The call is a tail call, and the evaluator runs
; tail calls without growing the stack, so a loop can run any number of
; times. The name of that function comes from gensym, so it can't clash
; with any name in the loop's own code.

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
