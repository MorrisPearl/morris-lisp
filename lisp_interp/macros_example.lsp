; ---------------------------------------------------------------------
; Macro example: defmacro + quasiquote/unquote/unquote-splicing.
;
; A macro's arguments are the caller's UNEVALUATED source expressions --
; not values -- so a macro can do things a plain function never can: skip
; evaluating an argument, evaluate it more than once, or mutate the
; caller's own variables. quasiquote (`) is the natural way to build the
; replacement code, with , splicing in one value and ,@ splicing in the
; elements of a list.
; ---------------------------------------------------------------------

; --- 1. my-unless: can't be a function -- a function would always evaluate
;        `then`, even when test is true and it shouldn't run at all.
;        (The standard unless, in macros_init.lsp, is the same idea with
;        any number of body forms; this one is named my-unless so it
;        doesn't replace it.) ---

(defmacro my-unless (test then)
  `(if (not ,test) ,then '()))

(display "(my-unless (> 1 2) 'shown) -> ") (display (my-unless (> 1 2) 'shown)) (newline)
(display "(my-unless (> 2 1) 'shown) -> ") (display (my-unless (> 2 1) 'shown)) (newline)

; A function couldn't skip evaluating its argument -- proof: `then` here
; would error if it ever actually ran, since the call it contains isn't
; defined. Since test is #t here, `then` is never reached.
(display "my-unless never touches the untaken branch: ")
(display (my-unless #t (boom-undefined-if-this-ever-runs)))
(newline)

; --- 2. swap!: can't be a function either -- a function only ever sees
;        the VALUES of its arguments, never the variables themselves, so
;        it has nothing to set! ---

(defmacro swap! (a b)
  `(let ((tmp ,a))
     (set! ,a ,b)
     (set! ,b tmp)))

(define p 1)
(define q 2)
(display "before swap!: p=") (display p) (display " q=") (display q) (newline)
(swap! p q)
(display "after swap!:  p=") (display p) (display " q=") (display q) (newline)

; --- 3. my-and: expands to nested `if`s -- short-circuits, and works for
;        any number... well, this one's fixed-arity (2), like every
;        macro/procedure in this interpreter, but the same idea extends ---

(defmacro my-and2 (a b)
  `(if ,a ,b #f))

(define ran-b '())
(display "short-circuit: ")
(display (my-and2 #f (begin (set! ran-b #t) #t)))
(display "  (b evaluated? ") (display ran-b) (display ")") (newline)

; --- 4. unquote-splicing: splice the ELEMENTS of a list into a template,
;        not the list itself -- quasiquote works standalone too, it isn't
;        only for macro bodies (this just builds and displays the CODE,
;        as data; there's no `eval` builtin in this interpreter to run it) ---

(define extra-args (list 10 20 30))
(display "`(+ 1 2 ,@extra-args) builds -> ")
(display `(+ 1 2 ,@extra-args))
(newline)

; --- 5. a macro-defined loop -- proof that a macro's expansion, when it's
;        a tail call, gets the SAME constant-stack-space handling any
;        other tail call does (see the module docstring / reference.md).
;        It's called my-while so it doesn't replace the standard while in
;        macros_init.lsp, which uses gensym for its loop name instead of
;        the fixed %loop here -- see "What goes wrong without gensym" in
;        lisp_interpreter_reference.md for why that matters ---

(defmacro my-while (test body)
  `(let ()
     (define (%loop)
       (if ,test
           (begin ,body (%loop))
           '()))
     (%loop)))

(define i 0)
(define total 0)
(my-while (< i 200000)
  (begin (set! total (+ total i)) (set! i (+ i 1))))
(display "my-while summed 0..199999 -> ") (display total) (newline)

(define a '(b c d e))
(my-while (not (null? a))
  (begin
   (define n '(1 2 3))
   (my-while (not (null? n))
     (begin
      (print (cons (car a) (car n)))
      (set! n (cdr n))
      )
     )
   (set! a (cdr a))
   )
  )
