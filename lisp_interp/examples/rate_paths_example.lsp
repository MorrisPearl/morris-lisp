; rate_paths_example.lsp
;
; How the paths of the interest-rate model are made, one step at a time. A path is today's forward curve, bent
; by two random numbers (the "factors") that wander from month to month; each month on each path, the bent curve
; gives a short rate and a 10-year yield. This program shows each stage, and what is read from it. See lisp_paths_manual.md.
;
; Needs no key: it downloads the Treasury's yield curve. Run it from the examples directory:
;   python3 ../lisp_interpreter.py rate_paths_example.lsp
; It saves two charts, rate_paths_curve.png and rate_paths_fan.png.

; The model's three numbers: how fast the short rate follows the level (a), and the sizes of the random shocks to the
; short rate (sigma1) and to the level (sigma2). These are what rate_model_example.lsp fitted to option prices on
; 2026-10-15; that program shows how to find them.
(define a 2.75)
(define sigma1 0.019)
(define sigma2 0.012)

; --- 1. Today's curve: the Treasury's forward rates, a month at a time, for thirty years ---
(define zeros (treasury-zero-curve (treasury-par-curve)))
(define forwards (table-column (curve-forward-rates zeros) "forward"))
(display (format "1. Today's curve, as par yields: 2 years {:.2%}, 5 years {:.2%}, 10 years {:.2%}, 30 years {:.2%}.\n"
                 (curve-par-yield forwards 2) (curve-par-yield forwards 5) (curve-par-yield forwards 10) (curve-par-yield forwards 30)))

; --- 2. With no volatility, a path is that curve itself, read forward in time ---
(define no-volatility (simulate-rate-paths forwards 0 0 5 2))
(define curve-short-rate (first (second no-volatility)))
(define curve-yield (first (third no-volatility)))
(display (format "2. With no volatility, every path is the curve: the short rate in 2 years is {:.2%} (the curve's forward rate for that month: {:.2%}),\n"
                 (vector-ref curve-short-rate 24) (vector-ref forwards 24)))
(display (format "   and the 10-year yield then is {:.2%}: the par yield of a 10-year note starting in 2 years, on today's curve ({:.2%}).\n"
                 (vector-ref curve-yield 24) (curve-par-yield forwards 10 :start-months 24)))

; --- 3. The model's two random factors, over 5 years ---
; delta-r: how far the short rate has strayed from the curve's; delta-theta: how far the level (the long end) has.
(define factors (simulate-rate-factors sigma1 sigma2 5 200 :a a :seed 1))
(define delta-r (second factors))
(define delta-theta (third factors))

; The paths, from the same factors (the same seed). Follow one whose 10-year yield after 3 years is among the highest tenth.
(define paths (simulate-rate-paths forwards sigma1 sigma2 5 200 :a a :seed 1))
(define years (first paths))
(define short-rates (second paths))
(define ten-year-yields (third paths))
(define yields-at-3-years (map (lambda (path) (vector-ref path 36)) ten-year-yields))
(define highest-tenth (vector-quantile (list->vector yields-at-3-years) 0.9))
(define distances (map (lambda (yield) (abs (- yield highest-tenth))) yields-at-3-years))
(define followed (position (apply min distances) distances))
(define r-at-3-years (vector-ref (list-ref delta-r followed) 36))
(define theta-at-3-years (vector-ref (list-ref delta-theta followed) 36))
(display (format "3. On path {}, after 3 years the short rate has strayed {:+.2%} from the curve's, and the level {:+.2%}.\n"
                 followed r-at-3-years theta-at-3-years))

; --- 4. The curve on that date: today's curve for the dates from then on, bent by the factors ---
; The short end follows delta-r, the long end delta-theta, and a says how quickly the one gives way to the other.
(define on-date (rate-curve-on-date forwards 36 r-at-3-years theta-at-3-years :a a))
(define months (table-column on-date "months"))
(display (format "4. The curve 3 years from now, as the model has it on path {}: first month {:.2%} (today's curve says {:.2%}), month 10 years out {:.2%} ({:.2%}).\n"
                 followed (vector-ref (table-column on-date "model") 0) (vector-ref (table-column on-date "today") 0)
                 (vector-ref (table-column on-date "model") 119) (vector-ref (table-column on-date "today") 119)))
(plot-chart (list (list "today's curve, for those dates" (/ months 12.0) (table-column on-date "today"))
                  (list (format "path {}, 3 years from now" followed) (/ months 12.0) (table-column on-date "model")))
            :title "The curve 3 years from now: today's, and bent by one path's factors"
            :x-label "years after that date" :y-label "forward rate for a month, as a rate for a year" :y-format "{:.1%}")
(save-chart "rate_paths_curve.png")

; --- 5. What a path reports each month is read from that curve ---
(display (format "5. The short rate on path {} in month 36 is {:.2%}: the first month of that curve, {:.2%}. Its 10-year yield, {:.2%}, is the par yield of that curve.\n"
                 followed (vector-ref (list-ref short-rates followed) 36) (vector-ref (table-column on-date "model") 0)
                 (vector-ref (list-ref ten-year-yields followed) 36)))

; --- 6. Many paths: they spread out, and their average is the curve ---
; The market's discount factor to 5 years, from the curve, next to the average along the 200 paths' short rates.
(define (discount-factor rates) (vector-ref (vector-cumprod (/ 1 (+ 1 (/ (vector-take rates 60) 12)))) 59))
(define (five-year-rate discount) (* 12 (- (expt discount (/ -1 60.0)) 1)))
(define average-discount (/ (apply + (map discount-factor short-rates)) (length short-rates)))
(define ten-year-yields-at-5-years (list->vector (map (lambda (path) (vector-ref path 60)) ten-year-yields)))
(display (format "6. The 5-year rate of the curve is {:.2%}; of the average discount factor along the paths, {:.2%}. The 10-year yield, today {:.2%}, is after 5 years\n"
                 (five-year-rate (discount-factor forwards)) (five-year-rate average-discount) (vector-ref curve-yield 0)))
(display (format "   between {:.2%} and {:.2%} for 80% of the paths (and {:.2%} with no volatility).\n"
                 (vector-quantile ten-year-yields-at-5-years 0.1) (vector-quantile ten-year-yields-at-5-years 0.9) (vector-ref curve-yield 60)))

(define (some-paths rates) (loop for path in rates for number from 1 to 7 collect (list "path" years path :line-width 0.8)))
(define (with-the-curve curve rates)
  (append (list (list "the curve, no volatility" years curve :color "black" :line-width 2.5))
          (some-paths rates)
          (list (list "the path followed" years (list-ref rates followed) :color "red" :line-width 1.8))))
(plot-panels (list (list (with-the-curve curve-yield ten-year-yields) :title "10-year yield" :y-format "{:.1%}")
                   (list (with-the-curve curve-short-rate short-rates) :title "short rate" :y-format "{:.1%}")
                   (list (list (list "delta-r (short rate)" years (list-ref delta-r followed))
                               (list "delta-theta (level)" years (list-ref delta-theta followed)))
                         :title (format "the factors of the path followed (path {})" followed) :y-format "{:+.1%}" :legend "upper left"))
             :x-label "years from today" :legend #f :heights (list 2 2 1.5)
             :title "Seven paths, and the one followed (red), around the curve (black: no volatility)")
(save-chart "rate_paths_fan.png")
