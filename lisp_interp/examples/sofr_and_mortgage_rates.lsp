; sofr_and_mortgage_rates.lsp
;
; Can the 30-year mortgage rate be told from SOFR, the overnight rate that floating-rate loans
; follow? SOFR's whole history comes from the New York Fed (nyfed-rates, no key needed), and
; Freddie Mac's weekly survey of mortgage rates and the 10-year Treasury yield from FRED
; (fred-table, which needs the "fred_api_key" entry of the credentials file; creds is set in
; init.lsp). Run it from the examples directory:
;   python3 ../lisp_interpreter.py sofr_and_mortgage_rates.lsp
;
; The answer: the two move together over the years (both were near zero in 2021 and high in
; 2023), but from week to week a mortgage rate follows the 10-year yield, and SOFR adds
; nothing once that is known.

; --- The rates on each week's survey date ----------------------------------------------------
; SOFR (daily) and the 10-year (daily) on the date of each mortgage survey (weekly): the latest
; value on or before it, since the survey's date can be a holiday.
(define sofr (nyfed-rates "SOFR"))
(define fred (fred-table creds '("MORTGAGE30US" "DGS10") :start-date (vector-ref (table-column sofr "date") 0)))
(define daily (table-sort (table-join fred sofr '("date") "left") '("date")))
(define daily (table-add-columns daily (list (cons "SOFR" (vector-fill-forward (table-column daily "SOFR")))
                                             (cons "DGS10" (vector-fill-forward (table-column daily "DGS10"))))))
(define weekly (table-filter daily (vector= (vector-nan? (table-column daily "MORTGAGE30US")) 0)))
(define mortgage (table-column weekly "MORTGAGE30US"))
(define sofr-rate (table-column weekly "SOFR"))
(define ten-year (table-column weekly "DGS10"))
(display (format "{} weeks, from {} to {}\n\n" (table-row-count weekly)
                 (vector-ref (table-column weekly "date") 0) (vector-ref (table-column weekly "date") (- (table-row-count weekly) 1))))

; --- The levels: both look good, because both rates rose and fell together -----------------------
(display "The mortgage rate from SOFR:\n")
(display (model-report (linear-regression (list (cons "SOFR" sofr-rate)) mortgage)))
(display "\n\nThe mortgage rate from the 10-year Treasury yield:\n")
(display (model-report (linear-regression (list (cons "DGS10" ten-year)) mortgage)))

; --- The changes: what moves a mortgage rate from one month to the next ---------------------------
; Changes over 4 weeks, taking every 4th week so that no two changes share a week.
(define every-4th (vector= (vector-map (lambda (i) (mod i 4)) (vector-range (table-row-count weekly))) 0))
(define (changes v) (vector-drop (vector-diff (vector-select v every-4th) 1) 1))
(display "\n\nThe 4-week change in the mortgage rate, from the changes in SOFR and the 10-year:\n")
(display (model-report (linear-regression (list (cons "SOFR change" (changes sofr-rate))
                                                (cons "10-year change" (changes ten-year)))
                                          (changes mortgage))))

; --- By year: the mortgage rate's spread over each ----------------------------------------------
(define by-year (table-add-columns weekly (list (cons "year" (vector-map date-year (table-column weekly "date")))
                                                (cons "over-10-year" (- mortgage ten-year))
                                                (cons "over-SOFR" (- mortgage sofr-rate)))))
(display "\n\nAverages by year, %:\n")
(display-table (table-group-by by-year '("year")
                               '(("mortgage" mean "MORTGAGE30US") ("SOFR" mean "SOFR") ("10-year" mean "DGS10")
                                 ("over-10-year" mean "over-10-year") ("over-SOFR" mean "over-SOFR")))
               '(("year" "d") ("mortgage" ".2f") ("SOFR" ".2f") ("10-year" ".2f") ("over-10-year" ".2f") ("over-SOFR" ".2f")))
