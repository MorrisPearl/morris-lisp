; bea_example.lsp
;
; The national and regional accounts from the Bureau of Economic Analysis:
; GDP and its parts, personal income and saving, the PCE price index, and
; income and GDP for every state and county. See "BEA data" in the
; reference manual.
;
; It needs your credentials file, with a "bea_api_key" entry; creds is set
; to its path in init.lsp. Run it from the examples directory:
;   python3 ../lisp_interpreter.py bea_example.lsp

; --- 1. The headline numbers ------------------------------------------------------
; bea-series takes short names (bea-names lists them). Monthly and
; quarterly series line up by date, NaN where one has no value.
(define latest (bea-series creds '("real-gdp-growth" "core-pce-price-index" "personal-saving-rate")
                           :start-year 2024))
(display "The last six months:\n")
(display-table (table-slice latest (- (table-row-count latest) 6)))

; --- 2. What made GDP grow ----------------------------------------------------------
; Any NIPA table, by its name: T10102 is the contributions to the percent
; change in real GDP. Lines 2, 7, 15, and 22 are its parts: spending by
; people, by businesses (investment), by the rest of the world less what
; we buy from it (net exports), and by governments. They add up to GDP's
; growth (line 1). bea-nipa-lines lists a table's lines.
(define parts (bea-nipa creds "T10102" :lines '(1 2 7 15 22) :start-year 2023))
(define dates (table-column parts "date"))
(define (part line-name) (table-column parts line-name))
(plot-chart (list (list "consumers" dates (part "Personal consumption expenditures") :bars #t)
                  (list "investment" dates (part "Gross private domestic investment") :bars #t)
                  (list "net exports" dates (part "Net exports of goods and services") :bars #t)
                  (list "government" dates (part "Government consumption expenditures and gross investment")
                        :bars #t)
                  (list "GDP growth" dates (part "Gross domestic product") :symbol "diamond" :color "black"))
            :bars "stacked" :title "Contributions to real GDP growth" :y-label "percentage points"
            :legend "upper left")

; --- 3. Inflation and saving, in panels ---------------------------------------------------
; Year-over-year core PCE inflation, worked out from the monthly index.
(define monthly (bea-series creds '("core-pce-price-index" "personal-saving-rate") :start-year 2018))
(define months (table-row-count monthly))
(define (from-month-13 name) (vector-slice (table-column monthly name) 12))
(define (a-year-before name) (vector-slice (table-column monthly name) 0 (- months 12)))
(define core-inflation (- (/ (from-month-13 "core-pce-price-index") (a-year-before "core-pce-price-index")) 1))
(define later-dates (from-month-13 "date"))
(plot-panels (list (list (list (list "core PCE inflation" later-dates core-inflation))
                         :y-format "{:.0%}" :y-lines (list (list 0.02 "the Fed's 2% goal")))
                   (list (list (list "saving rate" later-dates (/ (from-month-13 "personal-saving-rate") 100)
                                     :fill #t :line #t))
                         :y-format "{:.0%}"))
             :title "Prices and saving" :legend #f
             :shade (list (list (date 2020 2 1) (date 2020 4 30) "recession")))

; --- 4. The states ------------------------------------------------------------------
; bea-regional: a statistic of a regional table for each place -- here
; per capita personal income (table SAINC1, line 3) for every state, the
; last five years. bea-regional-lines lists a table's statistics. "STATE"
; gives the US (fips 00000) and the BEA's eight regions (91000 to 98000)
; too; the states' codes are from 01000 to 56000.
(define income (bea-regional creds "SAINC1" 3 "STATE"))
(define last-year (car (reverse (table-column-names (table-drop-columns income '("unit"))))))
(define (a-state? fips) (and (string<? "00000" fips) (string<? fips "60000")))
(define states (table-filter income (vector-map (lambda (fips) (if (a-state? fips) 1 0))
                                                (table-column income "fips"))))
(define richest (table-head (table-sort states last-year #t) 15))
(display (format "\nPer capita personal income, {}, the 15 highest:\n" last-year))
(display-table richest (list (list last-year ",")))
(plot-chart (list (list "per capita income" (table-column richest "name") (table-column richest last-year)
                        :bars #t :labels #t))
            :horizontal #t :legend #f :y-format "${:,.0f}"
            :title (format "Per capita personal income, {}" last-year))
