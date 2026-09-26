; debugging_example.lsp
;
; Stopping a program to see what it's doing: break, a debug hook,
; conditional breakpoints, and break-on-error. See "Debugging" in
; lisp_interpreter_reference.md.
;
; Everything here works without the console's debug REPL, because the hook
; does the looking around and prints what it finds. That means it works the
; same in a script, in Jupyter, and in the GUI. (The manual has a session
; showing the debug REPL itself.)
;
; Run it from this directory:
;   python3 lisp_interpreter.py debugging_example.lsp

; The level monthly payment that pays off a loan. It has a bug: for a loan
; with no interest the formula divides by zero.
(define (monthly-rate annual-percent)
  (/ annual-percent 1200))

(define (level-payment balance annual-percent months)
  (let ((r (monthly-rate annual-percent)))
    (/ (* balance r) (- 1 (expt (+ 1 r) (- months))))))

(define (round-cents x)
  (/ (round (* x 100)) 100))

; --- 1. A hook that logs each call, and lets the program carry on ----------
; The hook is called at every stop, in place of opening the debug REPL. It's
; given why the program stopped (kind), which procedure (name), and the
; arguments. If it just returns, the program goes on.

(define (log-call kind name args)
  (display (format "   called: {} {}\n" name args)))

(set-debug-hook! log-call)
(break level-payment)
(break monthly-rate)

(display "1. Every call to level-payment and monthly-rate is logged:") (newline)
(display (format "   payment = {}\n\n" (round-cents (level-payment 200000 6.0 360))))

; --- 2. A conditional breakpoint -----------------------------------------
; Stop only for loans over $500,000. The condition is an expression evaluated
; in the procedure's scope, so it can use the parameters by name.

(unbreak)
(break level-payment '(> balance 500000))
(display "2. Only the large loan is logged. The breakpoints are ")
(display (breakpoints)) (newline)
(level-payment 200000 6.0 360)
(level-payment 800000 6.0 360)
(newline)

; --- 3. break-on-error: look at the variables where an error happened -----
; With break-on-error on, an error that nothing handles stops the program
; where it happened. This hook prints the variables there, then leaves the
; computation with throw, back to the catch below.

(unbreak)
(set-debug-hook!
  (lambda (kind name args)
    (if (eq? kind 'error)
        (begin
          (display (format "   stopped by an error: {}\n" name))
          (display (format "   variables there: {}\n" (locals)))
          (throw 'gave-up 'no-payment)))))
(break-on-error #t)

(display "3. A loan with no interest:") (newline)
(define result (catch 'gave-up (level-payment 100000 0 360)))
(display (format "   result = {}\n" result))
(break-on-error #f)
(set-debug-hook! '())
