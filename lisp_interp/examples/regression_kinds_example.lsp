; regression_kinds_example.lsp
;
; Six kinds of regression on the same made-up data, one chart each:
;
;   linear-regression    a straight line, by least squares
;   lad-regression       a straight line, by least absolute deviation
;   logistic-regression  an S-curve, between 0 and 1
;   spline-regression    a line that bends at knots, by least squares
;   spline-lad           a line that bends at knots, by least absolute deviation
;   spline-logistic      a curve that bends at knots, between 0 and 1
;
; and then the two logistic ones again, with a :floor and :ceiling: the
; levels the data flattens out at, by eye, in place of 0 and 1.
;
; The data: the share of mortgages in a pool that prepaid in a month, by
; how far the rate they pay is above today's rate (the "incentive", in
; percentage points). Prepayments rise in an S: few borrowers refinance
; with no incentive, many with a big one, and then no more. Two months are
; out of line -- a pool sold off, and a month the data was wrong -- to show
; what least squares and least absolute deviation make of them.
;
; The spline models use the same knots: 3 for each, placed at the
; quartiles of the incentive, as spline-regression, spline-lad, and
; spline-logistic all place them, from the predictor alone. They differ
; only in how the bending line is fit.
;
; It needs no network. Run it from the examples directory:
;   python3 ../lisp_interpreter.py regression_kinds_example.lsp
; It saves the charts in regression_kinds.png; in a notebook or the GUI,
; they're drawn too.
;
; The plain logistic curve can't flatten out at 0.48, as the data does: its
; curve goes from 0 to 1. With a floor of 0.03 and a ceiling of 0.48, it
; has the data's shape. But a logistic fit, like a least-squares one, is
; pulled by the months out of line, where spline-lad isn't.

; --- The data ------------------------------------------------------------------
(random-seed 7)                                          ; the same made-up data every time
(define incentive (- (/ (vector-range 41) 8.0) 2))      ; -2 to 3 points, every 1/8
(define (s-curve x) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- x 1)))))))
(define noise (list->vector (map (lambda (i) (* 0.05 (- (random-float) 0.5))) (iota 41))))
(define prepaid (+ (vector-map s-curve incentive) noise))
(vector-set! prepaid 4 0.55)                             ; a pool sold off, at -1.5 points
(vector-set! prepaid 36 0.02)                            ; a month the data was wrong, at 2.5 points

; --- The six models --------------------------------------------------------------
(define knots 3)
(define models
  (list (cons "linear-regression" (linear-regression incentive prepaid))
        (cons "lad-regression" (lad-regression incentive prepaid))
        (cons "logistic-regression" (logistic-regression incentive prepaid))
        (cons "spline-regression" (spline-regression incentive prepaid knots))
        (cons "spline-lad" (spline-lad incentive prepaid knots))
        (cons "spline-logistic" (spline-logistic incentive prepaid knots))
        (cons "logistic-regression, floor 0.03 and ceiling 0.48"
              (logistic-regression incentive prepaid :floor 0.03 :ceiling 0.48))
        (cons "spline-logistic, floor 0.03 and ceiling 0.48"
              (spline-logistic incentive prepaid knots :floor 0.03 :ceiling 0.48))))

; --- One chart each, the same points, and each model's curve ------------------------
(define grid (- (/ (vector-range 201) 40.0) 2))         ; -2 to 3 points, finely
(define (curve model) (vector-map (lambda (x) (model-predict model x)) grid))
(define (panel entry)
  (list (list (list "data" incentive prepaid :symbol "circle" :symbol-size 4)
              (list (model-kind (cdr entry)) grid (curve (cdr entry)) :line #t))
        :title (car entry) :y-label "share prepaid" :y-min -0.1 :y-max 0.7))
(plot-panels (map panel models)
             :title "Six kinds of regression on the same data, and two with a floor and ceiling"
             :x-label "rate incentive (percentage points)" :legend #f :height 21)
(save-chart "regression_kinds.png")

; --- How well each fits, by two measures ---------------------------------------------
; Least squares makes the first column smallest, of the models of its shape;
; least absolute deviation, the second. The two months out of line count
; for a lot in the first, since they're squared.
(define (sum-of f values) (vector-sum (vector-map f values)))
(display-table
  (table-from-rows
    (map (lambda (entry)
           (let ((residuals (model-residuals (cdr entry) incentive prepaid)))
             (list (car entry) (model-kind (cdr entry))
                   (sum-of (lambda (r) (* r r)) residuals)
                   (sum-of abs residuals))))
         models)
    '("model" "kind" "sum-of-squares" "sum-of-absolute-values"))
  '(("sum-of-squares" ".4f") ("sum-of-absolute-values" ".4f")))
