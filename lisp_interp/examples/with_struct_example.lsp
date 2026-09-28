; ---------------------------------------------------------------------
; with-struct example: bind ALL of a struct's slots as variables at once.
;
;   (with-struct struct-expr body...)
;
; struct-expr is evaluated once and can be an instance of ANY defstruct
; type. Every slot name of that instance is then bound to the slot's value
; -- exactly as `let` would bind it, in a fresh scope -- and body... runs
; there, returning its last value. It saves writing (loan-rate ln),
; (loan-months ln), ... over and over when a body uses several slots.
;
; (It's a special form rather than a defmacro macro because WHICH names to
; bind depends on the struct's runtime value -- a defmacro transformer only
; ever sees the unevaluated source, e.g. the symbol `ln`, never the struct
; it will hold. See "with-struct" in lisp_interpreter_reference.md.)
; ---------------------------------------------------------------------

; --- 1. the basic idea: accessors vs. with-struct ---

(defstruct point x y (label "origin"))
(define p (make-point :x 3 :y 4))

(display "with accessors:     ")
(display (sqrt (+ (* (point-x p) (point-x p)) (* (point-y p) (point-y p)))))
(newline)

(display "with with-struct:   ")
(display (with-struct p (sqrt (+ (* x x) (* y y)))))
(newline)

; Every slot is bound, including ones with defaults you never supplied:
(display "label slot too:     ")
(display (with-struct p label))
(newline)

; --- 2. works on any kind of struct -- the same form, different types ---

(defstruct loan balance rate months)
(defstruct tranche name (coupon 0.05) (factor 1.0))

; standard level-payment mortgage formula, all three slots used as plain
; variables
(define (monthly-payment ln)
  (with-struct ln
    (let ((r (/ rate 12.0)))
      (/ (* balance r) (- 1.0 (expt (+ 1.0 r) (- months)))))))

(define ln (make-loan :balance 300000.0 :rate 0.06 :months 360))
(display "30yr 6% $300k payment: ") (display (round (* 100 (monthly-payment ln))))
(display " cents/month") (newline)

(define t1 (make-tranche :name "A1" :coupon 0.045))
(display "tranche summary:     ")
(display (with-struct t1 (list name coupon factor)))
(newline)

; --- 3. inheritance: an included struct's inherited slots are bound too ---

(defstruct (point-3d (:include point)) z)
(define c (make-point-3d :x 1 :y 2 :z 3))
(display "point-3d slots:      ")
(display (with-struct c (list x y z label)))
(newline)

; --- 4. it's `let`: a snapshot, in its own scope ---

; slot names shadow same-named outer variables inside the body only
(define x 100)
(display "shadows outer x:     ")
(display (with-struct p x))
(display ", outer x still ")
(display x)
(newline)

; ...while everything else in scope stays visible
(define scale 10)
(display "outer vars visible:  ")
(display (with-struct p (* scale (+ x y))))
(newline)

; The variables are COPIES of the slot values at entry, like let -- so
; set! on one changes only the local variable, not the struct. To change
; the struct itself, use its setter (or struct-set!) as usual:
(with-struct p (set! y 0))
(display "after (set! y 0):    y slot is still ") (display (point-y p)) (newline)

(with-struct p (point-y-set! p 0))
(display "after point-y-set!:  y slot is now   ") (display (point-y p)) (newline)

; --- 5. nesting, and closures over the bound slots ---

(defstruct rate-curve base)
(define shifted
  (with-struct (make-rate-curve :base 0.03)
    (lambda (bp) (+ base (/ bp 10000.0)))))
(display "closure over slot:   ") (display (shifted 25)) (newline)

(display "nested (inner wins): ")
(display (with-struct (make-loan :balance 1 :rate 2 :months 3)
           (with-struct (make-tranche :name "B" :coupon 9)
             (list balance rate months name coupon))))
(newline)

; --- 6. the body is in tail position: constant control-stack space ---

(defstruct counter n limit)
(define (count-up c)
  (with-struct c
    (if (>= n limit)
        n
        (count-up (make-counter :n (+ n 1) :limit limit)))))
(display "300000 tail calls -> ")
(display (count-up (make-counter :n 0 :limit 300000)))
(newline)

; --- 7. errors ---

(display "non-struct arg:      ")
(display (catch-error (with-struct 42 x) (e) e))
(newline)
