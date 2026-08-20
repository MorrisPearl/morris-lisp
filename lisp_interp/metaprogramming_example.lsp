; ---------------------------------------------------------------------
; Metaprogramming example: variadic functions/macros, eval, apply,
; gensym, load, and output redirection.
; ---------------------------------------------------------------------

; --- 1. variadic functions: (a b . rest), or a bare symbol for "collect
;        everything, no fixed params at all" ---

(define (describe-args a b . rest)
  (list 'fixed (list a b) 'rest rest))
(display "variadic function, fixed + rest: ")
(display (describe-args 1 2 3 4 5))
(newline)

(define sum-all (lambda nums (apply + nums)))
(display "variadic function, bare-symbol params: (sum-all 1 2 3 4) -> ")
(display (sum-all 1 2 3 4))
(newline)

; --- 2. variadic macros: my-or, short-circuiting across any number of
;        expressions, built by recursively expanding itself ---

(defmacro my-or (. exprs)
  (if (null? exprs)
      #f
      `(let ((t ,(car exprs)))
         (if t t (my-or ,@(cdr exprs))))))
(display "variadic macro: (my-or #f #f 3 4) -> ")
(display (my-or #f #f 3 4))
(newline)

; --- 3. apply, now supporting leading arguments before the final list
;        (the standard Scheme/CL signature, not just (apply f list)) ---

(display "apply with leading args: (apply + 1 2 (list 3 4 5)) -> ")
(display (apply + 1 2 (list 3 4 5)))
(newline)

; --- 4. eval: run a piece of Lisp code built as data ---

(define code (list '+ 1 2 (list '* 3 4)))
(display "eval on constructed code ") (display code) (display " -> ")
(display (eval code))
(newline)

; --- 5. gensym: hygienic names for hand-written macros ---

(display "two gensyms, never equal: ")
(display (gensym)) (display " vs ") (display (gensym "tmp"))
(display "  (distinct? ") (display (not (equal? (gensym) (gensym)))) (display ")")
(newline)

; --- 6. load: read and evaluate another file's forms into THIS
;        environment -- write one with redirect-output, just to keep
;        this example self-contained, then load it back ---

(redirect-output "/tmp/lisp_load_demo.lsp")
(display "(define value-from-loaded-file 12345)")
(newline)
(reset-output)

(load "/tmp/lisp_load_demo.lsp")
(display "after (load ...): value-from-loaded-file -> ")
(display value-from-loaded-file)
(newline)

; --- 7. redirect-output on its own: send some output to a file instead
;        of the console, then switch back ---

(redirect-output "/tmp/lisp_redirect_demo.txt")
(display "this line went to /tmp/lisp_redirect_demo.txt, not the console")
(newline)
(reset-output)
(display "back on the console -- check /tmp/lisp_redirect_demo.txt to see the redirected line")
(newline)
