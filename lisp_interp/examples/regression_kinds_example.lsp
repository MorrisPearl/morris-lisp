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
; levels the data flattens out at, by eye, in place of 0 and 1. A second
; chart has a band (spline-quantile), a smooth spline, and a logistic curve
; whose floor and ceiling are fit to the data; and a table compares how
; well each model fits the data with how well it predicts data it wasn't
; fit to (cross-validate).
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
; It saves the charts in regression_kinds.png and regression_more.png; in a
; notebook or the GUI, they're drawn too.
;
; The plain logistic curve can't flatten out at 0.48, as the data does: its
; curve goes from 0 to 1. With a floor of 0.03 and a ceiling of 0.48, it
; has the data's shape, and follows it closely: a probability that can't go
; below 0.03 or above 0.48 makes a month far from the curve cost the fit
; only so much. The spline-logistic, freer to bend, is still pulled at its
; ends.

; --- The data ------------------------------------------------------------------
(random-seed 7)                                          ; the same made-up data every time
(define incentive (- (/ (vector-range 41) 8.0) 2))      ; -2 to 3 points, every 1/8
(define (s-curve x) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- x 1)))))))
(define noise (list->vector (map (lambda (i) (* 0.05 (- (random-float) 0.5))) (iota 41))))
(define prepaid (+ (vector-map s-curve incentive) noise))
(vector-set! prepaid 4 0.55)                             ; a pool sold off, at -1.5 points
(vector-set! prepaid 36 0.02)                            ; a month the data was wrong, at 2.5 points

; --- The models ------------------------------------------------------------------
; Each is a procedure that fits one kind of model to x and y, so that it can
; be fit to all the data, and cross-validated (below).
(define knots 3)
(define fits
  (list (cons "linear-regression" (lambda (x y) (linear-regression x y)))
        (cons "lad-regression" (lambda (x y) (lad-regression x y)))
        (cons "logistic-regression" (lambda (x y) (logistic-regression x y)))
        (cons "spline-regression" (lambda (x y) (spline-regression x y knots)))
        (cons "spline-lad" (lambda (x y) (spline-lad x y knots)))
        (cons "spline-logistic" (lambda (x y) (spline-logistic x y knots)))
        (cons "logistic-regression, floor 0.03 and ceiling 0.48"
              (lambda (x y) (logistic-regression x y :floor 0.03 :ceiling 0.48)))
        (cons "spline-logistic, floor 0.03 and ceiling 0.48"
              (lambda (x y) (spline-logistic x y knots :floor 0.03 :ceiling 0.48)))))
(define (fit-all entries) (map (lambda (entry) (cons (car entry) ((cdr entry) incentive prepaid))) entries))
(define models (fit-all fits))

; --- One chart each, the same points, and each model's curve ------------------------
(define grid (- (/ (vector-range 201) 40.0) 2))         ; -2 to 3 points, finely
(define (curve model) (vector-map (lambda (x) (model-predict model x)) grid))
(define the-data (list "data" incentive prepaid :symbol "circle" :symbol-size 4))
(define (panel entry)
  (list (list the-data (list (model-kind (cdr entry)) grid (curve (cdr entry)) :line #t))
        :title (car entry) :y-label "share prepaid" :y-min -0.1 :y-max 0.7))
(plot-panels (map panel models)
             :title "Six kinds of regression on the same data, and two with a floor and ceiling"
             :x-label "rate incentive (percentage points)" :legend #f :height 21)
(save-chart "regression_kinds.png")

; --- More: a band, a smooth curve, and a fitted floor and ceiling --------------------
;   spline-quantile at 0.25, 0.5, and 0.75: the curves a quarter, half,
;     and three quarters of the points are below -- a band around the data.
;     (Not the 10th and 90th percentiles: with about 10 points in each of
;     the spline's pieces, those would be set by the single lowest or
;     highest point of a piece -- here, the months out of line. A
;     percentile far from the middle needs many points.)
;   spline-lad with :smooth #t and 5 knots: cubic pieces that join with no
;     corners, and a straight line beyond the first and last knots
;   logistic-regression with :floor 'fit :ceiling 'fit: the floor and the
;     ceiling the data says, in place of ones chosen by eye. The two months
;     out of line pull them in (to about 0.06 and 0.42): a share of 0.55
;     where the curve is near its floor is evidence of a higher floor. That
;     is this model's way of taking such points in -- the floor is how
;     often a point like that turns up -- and why, with few points, a floor
;     and ceiling known from outside the data can be better.
(define quantiles (map (lambda (q) (cons q (spline-quantile incentive prepaid q knots))) '(0.25 0.5 0.75)))
(define more-fits
  (list (cons "spline-lad, smooth, 5 knots" (lambda (x y) (spline-lad x y 5 '() :smooth #t)))
        (cons "logistic-regression, floor and ceiling fitted"
              (lambda (x y) (logistic-regression x y :floor 'fit :ceiling 'fit)))))
(define more-models (fit-all more-fits))
(define fitted (cdr (second more-models)))
(plot-panels
  (list (list (cons the-data (map (lambda (entry) (list (format "{:.0%}" (car entry)) grid (curve (cdr entry)) :line #t))
                                  quantiles))
              :title "spline-quantile: the 25th, 50th, and 75th percentiles" :y-label "share prepaid"
              :y-min -0.1 :y-max 0.7 :legend "upper left")
        (panel (first more-models))
        (panel (cons (format "logistic-regression, floor and ceiling fitted: {:.3f} and {:.3f}"
                             (model-floor fitted) (model-ceiling fitted))
                     fitted)))
  :title "A band, a smooth curve, and a fitted floor and ceiling"
  :x-label "rate incentive (percentage points)" :height 10)
(save-chart "regression_more.png")

; --- How well each predicts --------------------------------------------------------
; On the data it was fit to, a model that bends more always fits better. On
; data it wasn't fit to, it may not: cross-validate fits each model to four
; fifths of the points and predicts the other fifth, five times over. The
; two months out of line count for a lot in the root mean squared errors,
; since they're squared; the mean absolute errors show the ordinary months.
; Here the logistic curve with a floor and ceiling of 0.03 and 0.48 -- the
; shape the data was made with -- predicts best, and spline-lad, which
; doesn't know the shape, next.
(define (overall measure table) (vector-ref (table-column table measure) (- (table-row-count table) 1)))
(define (how-well entry)
  (let* ((model ((cdr entry) incentive prepaid))
         (residuals (model-residuals model incentive prepaid))
         (crossed (cross-validate (cdr entry) incentive prepaid)))
    (list (car entry)
          (sqrt (vector-mean (* residuals residuals))) (overall "rmse" crossed)
          (vector-mean (vector-map abs residuals)) (overall "mae" crossed))))
(display "\nHow well each fits the data, and predicts data it wasn't fit to (cross-validated):\n")
(display-table
  (table-from-rows (map how-well (append fits more-fits))
                   '("model" "rmse" "cross-validated-rmse" "mae" "cross-validated-mae"))
  '(("rmse" ".4f") ("cross-validated-rmse" ".4f") ("mae" ".4f") ("cross-validated-mae" ".4f")))
