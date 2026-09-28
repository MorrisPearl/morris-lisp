; ---------------------------------------------------------------------
; Debugging aids example: verbose call tracing and Lisp stack traces.
;
;   (verbose n)   0 off | 1 procedure names | 2 + arguments and return
;                 values | 3 + macro expansions.  Returns the PREVIOUS
;                 level, so you can restore it.
;   (backtrace)   print the chain of procedure calls in progress right now.
;
; Trace lines go wherever display output goes. You can also trace a whole
; script from the command line:  python3 lisp_interpreter.py -vv script.lsp
; And when an error escapes a script, the interpreter reports the chain of
; calls that led to it (see the last section for how to see that here).
; ---------------------------------------------------------------------

(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))

; --- 1. level 1: which procedures run, by name, indented by call depth ---

(display "--- level 1 ---") (newline)
(verbose 1)
(fact 3)
(verbose 0)

; --- 2. level 2: arguments going in, values coming out ---

(display "--- level 2 ---") (newline)
(verbose 2)
(fact 3)
(verbose 0)

; --- 3. tail calls: a call in tail position REPLACES its caller's frame
;        (that is what makes it constant-space), so it is marked >> and
;        sits at the caller's depth; the return line counts what it replaced ---

(define (count-down n) (if (= n 0) 'done (count-down (- n 1))))

(display "--- tail calls ---") (newline)
(verbose 2)
(count-down 3)
(verbose 0)

; --- 4. level 3 also shows every macro expansion (unless is one of the
;        standard macros, from macros_init.lsp) ---

(display "--- level 3 ---") (newline)
(verbose 3)
(unless #f 'ran)
(verbose 0)

; --- 5. save and restore the level, e.g. to trace just one suspicious call ---

(define (square x) (* x x))

(display "--- trace one call only ---") (newline)
(define old (verbose 2))
(square 7)
(verbose old)
(square 8)                    ; not traced

; --- 6. callbacks run by map/filter are traced like any other call ---

(display "--- a callback ---") (newline)
(verbose 1)
(map square (list 1 2))
(verbose 0)

; --- 7. (backtrace): where am I, right now? ---

(define (c) (backtrace) 0)
(define (b) (list (c)))
(define (a) (list (b)))

(display "--- backtrace ---") (newline)
(a)

; --- 8. what an uncaught error's report looks like. An error that escapes
;        a script ends it (exit status 1) and prints the chain of calls
;        that led to it, to stderr. Uncomment the last line below and run
;        this file to see it. Note `helper` isn't listed: it tail-called
;        `middle`, so its frame was replaced -- the "+1 tail call" note
;        accounts for it.
;
;   Lisp traceback (most recent call last):
;     (outer 5)
;     (middle 5)  [+1 tail call]
;     (inner 5)
;   Error: car: not a pair: 5

(define (inner x) (car x))
(define (middle x) (+ 1 (inner x)))
(define (helper x) (middle x))
(define (outer x) (list (helper x)))

(display "--- the error, caught ---") (newline)
(display (catch-error (outer 5) (e) (string-append "caught: " e)))
(newline)

; (outer 5)
