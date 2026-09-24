; solver.lsp
;
; Numerical solvers: Ridders' method (root finding, one variable) and
; Nelder-Mead (minimization, several variables; see further down).
;
; Ridders' method: given a function f and
; an interval [a, b] across which f changes sign, finds an x in the
; interval where f(x) = 0 -- no derivative needed, and it converges much
; faster than plain bisection (roughly quadratically) while, like
; bisection, never leaving the bracket, so it can't diverge.
;
; Each step evaluates f at the interval's midpoint xm, then uses the
; three values f(a), f(xm), f(b) to fit an exponential correction that
; puts a new estimate xn very close to the root; the bracket then
; shrinks to whichever two of {a, xm, xn, b} still straddle the root.
;
; Usage:
;   (load "solver.lsp")
;   (ridders (lambda (x) (- (* x x) 2)) 0 2)          ; => 1.41421356...
;   (ridders f 0 2 :tolerance 1e-12 :max_iter 200)

; -1, 0, or 1 according to the sign of x.
(define (ridders--sign x)
  (cond ((> x 0) 1)
        ((< x 0) -1)
        (#t 0)))

; (ridders f a b [&key tolerance max_iter]) -> x with f(x) ~ 0.
;
; f: a function of one number returning a number.
; a, b: the ends of an interval; f(a) and f(b) must have opposite signs
;     (an error is raised if they don't -- the interval isn't known to
;     contain a root). If f is exactly 0 at either end, that end is
;     returned.
; tolerance: stop once the bracket around the root is narrower than
;     this (in x, not in f) -- default 1e-10.
; max_iter: give up (with an error) after this many steps -- default 100.
;     Ridders' method normally needs only a handful.
(define (ridders f a b &key (tolerance 1e-10) (max_iter 100))
  (let* ((fa (f a))
         (fb (f b)))
    (cond ((= fa 0) a)
          ((= fb 0) b)
          ((> (* (ridders--sign fa) (ridders--sign fb)) 0)
           (error "ridders: f(a) and f(b) have the same sign -- no root is bracketed by"
                  a b "f(a)=" fa "f(b)=" fb))
          (#t (ridders--iterate f a fa b fb tolerance max_iter 0)))))

; One step per call; the recursive call at the bottom is a tail call, so
; this loops in constant stack space. (a, fa) and (b, fb) always
; straddle the root: fa and fb have opposite signs.
(define (ridders--iterate f a fa b fb tolerance max_iter iteration)
  (if (>= iteration max_iter)
      (error "ridders: no convergence after" max_iter "iterations; bracket is now" a b)
      (let* ((xm (/ (+ a b) 2.0))
             (fm (f xm))
             ; fa*fb < 0, so this is always a positive number
             (s (sqrt (- (* fm fm) (* fa fb)))))
        (if (= s 0)
            xm
            (let* ((step (/ (* (- xm a) fm) s))
                   ; move from the midpoint toward the side where f is
                   ; closer to zero: toward b if fa > fb, otherwise a
                   (xn (if (> fa fb) (+ xm step) (- xm step)))
                   (fn (f xn)))
              (cond ((= fn 0) xn)
                    ; the root lies between xm and xn
                    ((< (* (ridders--sign fm) (ridders--sign fn)) 0)
                     (ridders--next f xm fm xn fn xn tolerance max_iter iteration))
                    ; the root lies between a and xn
                    ((< (* (ridders--sign fa) (ridders--sign fn)) 0)
                     (ridders--next f a fa xn fn xn tolerance max_iter iteration))
                    ; the root lies between xn and b
                    (#t
                     (ridders--next f xn fn b fb xn tolerance max_iter iteration))))))))

; Given the new bracket (lo, hi): if it's narrower than tolerance, xn is
; the answer; otherwise take another step.
(define (ridders--next f lo flo hi fhi xn tolerance max_iter iteration)
  (if (< (abs (- hi lo)) tolerance)
      xn
      (ridders--iterate f lo flo hi fhi tolerance max_iter (+ iteration 1))))

; ---------------------------------------------------------------------
; Nelder-Mead: minimize a function of several variables, no derivatives.
;
; Keeps a "simplex" -- n+1 points for n variables (a triangle for 2
; variables, a tetrahedron for 3) -- and repeatedly replaces the worst
; point with a better one, found by reflecting it through the centre of
; the others, and stretching (expand) or pulling back (contract) that
; move depending on how it went. If nothing helps, the whole simplex
; shrinks toward its best point. The simplex crawls downhill and
; contracts around a minimum.
;
; It finds a LOCAL minimum, near the starting point; it can be slow or
; stall on badly scaled or very high-dimensional problems. To solve
; f(x) = 0 for several unknowns, minimize the sum of squares of f.
;
; Usage:
;   (load "solver.lsp")
;   (nelder-mead (lambda (p) (+ (expt (- (car p) 1) 2)
;                               (expt (- (car (cdr p)) 2) 2)))
;                (list 0 0))                   ; => ((1.0 2.0) 0.0)
; ---------------------------------------------------------------------

; (nelder-mead f start [&key step tolerance max_iter]) ->
; (list best_point best_value)
;
; f: a function taking ONE argument, a list of numbers (a point), and
;     returning the number to minimize.
; start: a list of numbers, the starting point. Its length is the
;     number of variables.
; step: how far the initial simplex extends from start, as a fraction of
;     each coordinate's size (or an absolute amount for a coordinate
;     that is 0) -- default 0.1. Make it bigger if the minimum may be
;     far away.
; tolerance: stop when the best and worst points of the simplex have
;     values within this of each other -- default 1e-10 -- AND ...
; x_tolerance: ... every point of the simplex is within this of the best
;     point, in every coordinate -- default 1e-8. (Both are needed: two
;     points on opposite sides of a minimum can have equal values while
;     still being far from it.)
; max_iter: give up (with an error) after this many steps -- default 2000.
(define (nelder-mead f start &key (step 0.1) (tolerance 1e-10) (x_tolerance 1e-8) (max_iter 2000))
  (let ((simplex (nm--sort (nm--evaluate f (nm--initial-points start step)))))
    (nm--iterate f simplex tolerance x_tolerance max_iter 0)))

; ---- the algorithm ----------------------------------------------------
; A "vertex" is a pair (value . point). `simplex` is a list of vertices
; sorted best (lowest value) first, worst last.

(define (nm--iterate f simplex tolerance x_tolerance max_iter iteration)
  (let* ((best (car simplex))
         (worst (nm--last simplex))
         (second_worst (list-ref simplex (- (length simplex) 2))))
    (cond ((and (<= (- (car worst) (car best)) tolerance)
                (<= (nm--size simplex) x_tolerance))
           (list (cdr best) (car best)))
          ((>= iteration max_iter)
           (error "nelder-mead: no convergence after" max_iter
                  "iterations; best value so far" (car best)))
          (#t
           (let* ((others (nm--all-but-last simplex))
                  (center (nm--centroid (map cdr others)))
                  (reflected (nm--try f (nm--point-along center (cdr worst) -1.0))))
             (nm--iterate
              f
              (nm--sort
               (cond
                 ; reflection beat the best: try stretching further
                 ((< (car reflected) (car best))
                  (let ((expanded (nm--try f (nm--point-along center (cdr worst) -2.0))))
                    (append others (list (if (< (car expanded) (car reflected))
                                             expanded reflected)))))
                 ; reflection is good enough: keep it
                 ((< (car reflected) (car second_worst))
                  (append others (list reflected)))
                 ; reflection is poor: pull back toward the centre. If
                 ; that fails too, shrink everything toward the best.
                 (#t
                  (let ((contracted
                         (nm--try f (if (< (car reflected) (car worst))
                                        (nm--point-along center (cdr reflected) 0.5)
                                        (nm--point-along center (cdr worst) 0.5)))))
                    (if (< (car contracted) (min (car worst) (car reflected)))
                        (append others (list contracted))
                        (nm--shrink f simplex))))))
              tolerance x_tolerance max_iter (+ iteration 1)))))))

; How spread out the simplex is: the largest difference, in any
; coordinate, between the best point and any other point.
(define (nm--size simplex)
  (let ((best_point (cdr (car simplex))))
    (reduce max
            (map (lambda (vertex)
                   (reduce max (nm--map2 (lambda (a b) (abs (- a b))) best_point (cdr vertex)) 0.0))
                 (cdr simplex))
            0.0)))

; The vertex (value . point) for a point.
(define (nm--try f point)
  (cons (f point) point))

; from + fraction * (toward - from), coordinate by coordinate. Fraction 0
; is `from`, 1 is `toward`, -1 is the mirror image of `toward` through
; `from`, and so on.
(define (nm--point-along from toward fraction)
  (nm--map2 (lambda (a b) (+ a (* fraction (- b a)))) from toward))

; Move every vertex halfway toward the best one (keeping the best).
(define (nm--shrink f simplex)
  (let ((best_point (cdr (car simplex))))
    (cons (car simplex)
          (map (lambda (vertex)
                 (nm--try f (nm--point-along best_point (cdr vertex) 0.5)))
               (cdr simplex)))))

; The average of a list of points.
(define (nm--centroid points)
  (let ((n (length points)))
    (map (lambda (total) (/ total n))
         (reduce (lambda (sum p) (nm--map2 + sum p)) points))))

; start, plus one point per coordinate nudged along that coordinate.
(define (nm--initial-points start step)
  (cons start (nm--nudged start step 0)))

(define (nm--nudged start step i)
  (if (>= i (length start))
      '()
      (cons (nm--nudge-coordinate start i (* step (nm--scale (list-ref start i))))
            (nm--nudged start step (+ i 1)))))

; The size of a coordinate, for scaling a step: itself, or 1 if it's 0.
(define (nm--scale x)
  (if (= x 0) 1.0 x))

; The point with coordinate i increased by delta.
(define (nm--nudge-coordinate point i delta)
  (if (= i 0)
      (cons (+ (car point) delta) (cdr point))
      (cons (car point) (nm--nudge-coordinate (cdr point) (- i 1) delta))))

; ---- small list helpers -----------------------------------------------

(define (nm--evaluate f points)
  (map (lambda (p) (nm--try f p)) points))

; Sort vertices by value, lowest first (insertion sort -- simplexes are tiny).
(define (nm--sort vertices)
  (if (null? vertices)
      '()
      (nm--insert (car vertices) (nm--sort (cdr vertices)))))

(define (nm--insert vertex sorted)
  (cond ((null? sorted) (list vertex))
        ((<= (car vertex) (car (car sorted))) (cons vertex sorted))
        (#t (cons (car sorted) (nm--insert vertex (cdr sorted))))))

; Apply f to corresponding elements of two lists of the same length.
(define (nm--map2 f a b)
  (if (null? a)
      '()
      (cons (f (car a) (car b)) (nm--map2 f (cdr a) (cdr b)))))

(define (nm--last lst)
  (if (null? (cdr lst)) (car lst) (nm--last (cdr lst))))

(define (nm--all-but-last lst)
  (if (null? (cdr lst)) '() (cons (car lst) (nm--all-but-last (cdr lst)))))
