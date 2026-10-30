; yield_curve_example.lsp
;
; Today's US Treasury yield curve from two free sources: the Treasury's own
; par yield curve, and the Federal Reserve's smooth fitted curve (Gurkaynak,
; Sack, and Wright). From each, the zero rates, and the forward rates that a
; model of interest rates starts from: see "Yield curves" in
; lisp_paths_manual.md. No API key is needed; it downloads from the Treasury's and the Fed's
; sites. Run it from the examples directory:
;   python3 ../lisp_interpreter.py yield_curve_example.lsp
; It saves two charts, yield_curve_zero.png and yield_curve_forward.png.

; --- The Treasury's par curve, this year so far, and the zero curve of its latest day ---
(define treasury (treasury-par-curve))
(define zeros (treasury-zero-curve treasury))
(define latest (vector-max (table-column treasury "date")))
(display (format "The Treasury's par yield curve of {}: {} days this year.\n" latest (table-row-count treasury)))
(display-table (table-where treasury "date" latest)
               (cons '("date" hide) (map (lambda (name) (list name ".2%")) (cdr (table-column-names treasury)))))

; --- The Fed's curve, and the zero curve of its latest day, by the month ---
(define fed (gsw-curve :start-date (date (date-year latest) 1 1)))
(define fed-zeros (gsw-zero-curve fed))
(display (format "\nThe Fed's curve, to {}: its 10-year zero rate is {:.2%}; the Treasury's, from its par yields, {:.2%}.\n"
                 (vector-max (table-column fed "date")) (vector-ref (table-column fed-zeros "zero") 119)
                 (interpolate 10 (table-column zeros "years") (table-column zeros "zero"))))

(plot-chart (list (list "Treasury par yield" (table-column zeros "years") (table-column zeros "par") :symbol #t)
                  (list "Treasury zero rate" (table-column zeros "years") (table-column zeros "zero"))
                  (list "Fed zero rate" (table-column fed-zeros "years") (table-column fed-zeros "zero")))
            :title "Zero rates and par yields" :x-label "years" :y-label "rate, as a decimal")
(save-chart "yield_curve_zero.png")

; --- Forward rates: one month, a year at a time to 30 years ------------------
; The Treasury's, from a few dozen par yields, are rougher than the Fed's.
(define treasury-forwards (curve-forward-rates zeros))
(define fed-forwards (curve-forward-rates fed-zeros))
(plot-chart (list (list "Treasury" (/ (table-column treasury-forwards "months") 12.0) (table-column treasury-forwards "forward"))
                  (list "Fed" (/ (table-column fed-forwards "months") 12.0) (table-column fed-forwards "forward")))
            :title "One-month forward rates" :x-label "years ahead" :y-label "rate for a year, as a decimal")
(save-chart "yield_curve_forward.png")
