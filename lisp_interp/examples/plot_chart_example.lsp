; plot_chart_example.lsp
;
; plot-chart: several series on one chart, each with its own X values, drawn
; as symbols, lines, or bars (grouped or stacked). See "plot-chart" in the
; reference manual. The data here is made up, so it needs no network.
;
; In Jupyter or the GUI each chart is drawn; at the console each prints a
; summary (save-chart writes the last one to a file). Run it from the
; examples directory:
;   python3 ../lisp_interpreter.py plot_chart_example.lsp

; --- Some dates: 24 months and 8 quarters ---------------------------------
(define (month-start i) (date (+ 2024 (quotient i 12)) (+ 1 (remainder i 12)) 1))
(define (quarter-start i) (date (+ 2024 (quotient i 4)) (+ 1 (* 3 (remainder i 4))) 1))
(define months (list->vector (map month-start (iota 24))))
(define quarters (list->vector (map quarter-start (iota 8))))

(define rate (vector-map (lambda (i) (- 4.5 (* 0.03 i))) (list->vector (iota 24))))
(define gdp-growth #(2.1 -0.5 1.5 3.0 2.2 1.1 -1.0 2.5))
(define productivity #(1.0 0.5 -0.8 1.2 0.9 1.5 0.7 -0.4))

; --- 1. Monthly and quarterly on one date axis ------------------------------
; The quarters' bars sit under the months they start in.
(plot-chart (list (list "unemployment rate" months rate :line #t :symbol "circle" :symbol-size 4)
                  (list "GDP growth" quarters gdp-growth :bars #t)
                  (list "productivity" quarters productivity :bars #t))
            :title "A monthly line over grouped quarterly bars" :y-label "percent")

; --- 2. Stacked bars, with their total ------------------------------------------
(plot-chart (list (list "GDP growth" quarters gdp-growth :bars #t)
                  (list "productivity" quarters productivity :bars #t)
                  (list "total" quarters (+ gdp-growth productivity)
                        :line "dashed" :symbol "diamond" :color "black"))
            :title "Stacked: up from 0 for gains, down for losses" :bars "stacked" :legend "upper left")

; --- 3. Categories ------------------------------------------------------------------
; Text X values are categories, in the order they first appear. A series
; can have just some of them.
(define states #("New York" "Texas" "California" "Florida" "Ohio" "Maine" "Utah" "Iowa"))
(plot-chart (list (list "2023" states #(5.0 6.0 7.0 4.0 3.0 2.0 3.0 2.0) :bars #t)
                  (list "2024" states #(5.5 6.1 6.5 4.4 3.3 2.1 3.5 2.2) :bars #t)
                  (list "target" #("Texas" "Ohio") #(6.5 4.0) :symbol "star" :symbol-size 14))
            :title "Grouped bars by state" :y-label "growth, percent")

; --- 4. A scatter plot and a line, on numbers ---------------------------------------
(define x #(1 2 3 4 5 6 7 8))
(define y #(2.3 2.9 4.2 4.8 6.1 6.4 8.2 8.5))
(define model (linear-regression x y))
(define x-ends #(1 8))
(plot-chart (list (list "data" x y :symbol #t)
                  (list "fitted line" x-ends (vector-map (lambda (v) (model-predict model v)) x-ends)))
            :x-label "x" :y-label "y" :title "Points and a fitted line")
