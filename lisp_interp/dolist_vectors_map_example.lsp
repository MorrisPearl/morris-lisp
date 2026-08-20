; ---------------------------------------------------------------------
; dolist / vectors-map / tail-call example.
;
; Demonstrates three additions to the interpreter:
;   1. `dolist` -- Common-Lisp-style "loop over a list for side effects"
;   2. `vectors-map` -- vector-map generalized to several input vectors
;   3. that ordinary tail-recursive Lisp functions -- and dolist itself,
;      which desugars into one -- run in CONSTANT control-stack space,
;      not space proportional to how many iterations they do
; ---------------------------------------------------------------------

; --- 1. dolist: side-effecting iteration --------------------------------

(display "dolist: summing a list") (newline)
(define total 0)
(dolist (x (list 1 2 3 4 5)) (set! total (+ total x)))
(display "  total = ") (display total) (newline)

(display "dolist: printing with a result-expr") (newline)
(display "  ")
(dolist (name (list "SOFR" "SR3" "ZQ") "done printing")
  (display name) (display " "))
(newline)

; --- 2. vectors-map: apply a procedure across several vectors at once ---

(newline)
(display "vectors-map: elementwise combination of three same-length vectors") (newline)
(define prices #(100 101 99))
(define rates #(0.04 0.041 0.039))
(define spreads #(0.01 0.012 0.009))
(display "  ")
(display (vectors-map (lambda (p r s) (* p (+ r s))) (list prices rates spreads)))
(newline)

(display "vectors-map: mismatched lengths, stop at the shortest (default)") (newline)
(display "  ")
(display (vectors-map + (list #(1 2 3 4 5) #(10 20 30))))
(newline)

(display "vectors-map: mismatched lengths, pad the short one with a default") (newline)
(display "  ")
(display (vectors-map + (list #(1 2 3 4 5) #(10 20 30)) 0))
(newline)

; --- 3. tail calls run in constant stack space --------------------------

(newline)
(display "tail recursion: counting down from 1,000,000 (no stack growth)") (newline)
(define (count-down n acc)
  (if (= n 0) acc (count-down (- n 1) (+ acc 1))))
(display "  count-down 1,000,000 -> ") (display (count-down 1000000 0)) (newline)

(display "dolist over a 300,000-element list (also tail-recursive under the hood)") (newline)
(define (make-range n acc)
  (if (= n 0) acc (make-range (- n 1) (cons n acc))))
(define visited 0)
(dolist (x (make-range 300000 '())) (set! visited (+ visited 1)))
(display "  elements visited -> ") (display visited) (newline)
