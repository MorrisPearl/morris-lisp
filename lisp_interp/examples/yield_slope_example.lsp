; yield_slope_example.lsp
;
; The slope of the Treasury curve -- the 10-year zero yield less the 3-month -- and what it is made of:
; the rates the market expects, the term premium and convexity (term-premium-decomposition, the New York
; Fed's model), and, since 1999, real yields and inflation compensation (tips-curve). See "What the slope of
; the curve is made of" in lisp_paths_manual.md. No API key is needed: it downloads the Fed's two curves.
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py yield_slope_example.lsp
; It saves two charts, yield_slope_pieces.png and yield_slope_inflation.png.

(define parts (term-premium-decomposition (gsw-curve)))          ; fitted to every month since 1961
(define slope (yield-slope-decomposition parts :long 10 :short 0.25))
(define latest (table-tail slope 1))
(display (format "On {}, the 10-year less the 3-month is {:.2%}: expected rates {:.2%}, term premium {:.2%}, convexity {:.2%}, and {:.2%} the model doesn't fit.\n"
                 (vector-ref (table-column latest "date") 0) (vector-ref (table-column latest "slope") 0)
                 (vector-ref (table-column latest "expected") 0) (vector-ref (table-column latest "term-premium") 0)
                 (vector-ref (table-column latest "convexity") 0) (vector-ref (table-column latest "error") 0)))

; The chart starts in 1972: in the 1960s the Fed's curve has few short Treasuries to fit, and its 3-month
; rate jumps around from month to month.
(define since-1972 (table-filter slope (>= (table-column slope "date") (date 1972 1 1))))
(define dates (table-column since-1972 "date"))
(plot-chart (list (list "slope" dates (table-column since-1972 "slope"))
                  (list "expected rates" dates (table-column since-1972 "expected"))
                  (list "term premium" dates (table-column since-1972 "term-premium")))
            :title "The 10-year less the 3-month Treasury yield, in pieces" :y-label "as a decimal")
(save-chart "yield_slope_pieces.png")

; --- Since 1999: the 10-year less the 2-year, as real yields and inflation compensation ---
(define inflation (yield-slope-inflation (tips-curve :start-date (date 2004 1 1)) :long 10 :short 2))
(plot-chart (list (list "slope" (table-column inflation "date") (table-column inflation "slope"))
                  (list "real yields" (table-column inflation "date") (table-column inflation "real"))
                  (list "inflation compensation" (table-column inflation "date") (table-column inflation "inflation")))
            :title "The 10-year less the 2-year: real yields and inflation" :y-label "as a decimal")
(save-chart "yield_slope_inflation.png")
