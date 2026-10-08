; plot_chart_example.lsp
;
; plot-chart: several series on one chart, each with its own X values, drawn
; as symbols, lines, or bars (grouped or stacked). See "plot-chart" in the
; language manual. The data here is made up, so it needs no network.
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

; --- 5. Two scales -----------------------------------------------------------------
; Revenue in dollars and the margin as a fraction: the margin goes on the
; secondary axis (on the right), with its own scale. Each axis can have its
; own limits and about how many ticks it shows, at round numbers.
(define years #(2019 2020 2021 2022 2023 2024))
(plot-chart (list (list "revenue" years #(120000 135000 128000 150000 162000 171000) :bars #t)
                  (list "margin" years #(0.12 0.14 0.11 0.15 0.16 0.18) :symbol #t :line #t :secondary #t))
            :title "Revenue and margin" :y-label "dollars" :secondary-label "margin"
            :y-min 100000 :y-ticks 4 :secondary-ticks '(0.10 0.15 0.20) :legend "upper left")

; --- 6. On its side, for many bars --------------------------------------------------
; :horizontal #t: the X values down the side (the first at the top), the bars
; across. A chart of many categories is made tall enough for every label.
(define cities #("Phoenix" "Dallas" "Houston" "Atlanta" "Denver" "Seattle" "Boston" "Miami"
                 "Chicago" "Portland" "Austin" "Tampa" "Nashville" "Charlotte" "Detroit" "Raleigh"))
(define growth #(2.6 2.4 2.2 2.0 1.9 1.7 1.5 1.4 1.2 1.1 3.1 2.8 2.7 2.5 0.3 2.9))
(plot-chart (list (list "population growth" cities growth :bars #t))
            :horizontal #t :title "Population growth, percent" :legend #f)

; --- 7. A log scale -------------------------------------------------------------------
; Something that grows 7% a year is a straight line on a log scale.
(define year-numbers (list->vector (iota 40 1985)))
(define value (vector-map (lambda (year) (* 100 (expt 1.07 (- year 1985)))) year-numbers))
(plot-chart (list (list "7% a year" year-numbers value))
            :y-log #t :title "Steady growth, on a log scale" :y-label "value")

; --- 8. Marking a chart: shading, reference lines, a note ----------------------------
(define quarters-2019 (list->vector (map (lambda (i) (date (+ 2019 (quotient i 4)) (+ 1 (* 3 (remainder i 4))) 1))
                                         (iota 20))))
(define jobless #(3.8 3.6 3.6 3.6 3.8 13.0 8.8 6.8 6.2 5.9 5.1 4.2 3.8 3.6 3.6 3.6 3.5 3.6 3.7 3.8))
(plot-chart (list (list "unemployment" quarters-2019 (/ jobless 100) :fill #t :line #t))
            :title "Shading, a reference line, and a note" :legend #f :y-format "{:.0%}"
            :shade (list (list (date 2020 2 1) (date 2020 4 30) "recession"))
            :y-lines (list (list 0.04 "4%"))
            :notes (list (list (date 2020 4 1) 0.13 "the pandemic")))

; --- 9. A band, and values printed on the chart -------------------------------------------
(define fitted #(2.0 3.1 4.0 5.2 5.9 7.1))
(plot-chart (list (list "range" #(1 2 3 4 5 6) (- fitted 0.8) :fill (+ fitted 0.8) :color "gray")
                  (list "estimate" #(1 2 3 4 5 6) fitted :symbol #t :line #t :labels #t))
            :title "A fitted line with a band" :legend "upper left")
(plot-chart (list (list "product" #("Q1" "Q2" "Q3" "Q4") #(120000 135000 128000 150000) :bars #t :labels #t)
                  (list "service" #("Q1" "Q2" "Q3" "Q4") #(40000 52000 61000 70000) :bars #t :labels #t))
            :bars "stacked" :y-format "${:,.0f}" :title "Revenue, labeled" :legend "upper left")

; --- 10. A histogram ---------------------------------------------------------------------
; Made-up daily returns: the sum of a few random numbers is roughly bell-shaped.
(define (made-up-return i) (* 0.01 (- (+ (random-float) (random-float) (random-float) (random-float)) 2)))
(define returns (list->vector (map made-up-return (iota 1000))))
(plot-histogram returns :bins 25 :x-format "{:.1%}" :title "1,000 made-up daily returns"
                :x-lines (list (list 0 "0")))

; --- 11. Panels sharing an X axis -----------------------------------------------------------
(define days (list->vector (iota 60)))
(define price (vector-map (lambda (d) (+ 100 (* 0.3 d) (* 3 (random-float)))) days))
(define volume (vector-map (lambda (d) (+ 1000 (* 500 (random-float)))) days))
(plot-panels (list (list (list (list "price" days price :line #t)) :y-label "dollars" :title "Price")
                   (list (list (list "volume" days volume :bars #t :color "gray")) :y-label "shares"))
             :heights (list 3 1) :legend #f :x-label "trading day" :title "A price over its volume")
