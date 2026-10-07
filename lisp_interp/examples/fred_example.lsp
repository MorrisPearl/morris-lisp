; fred_example.lsp
;
; Economic data from FRED, the Federal Reserve Bank of St. Louis.
; fred-table downloads one series or several, by ID, as a table with a row
; for each date -- see "FRED" in the reference manual. It needs a free FRED
; API key (https://fred.stlouisfed.org/docs/api/api_key.html), as the
; "fred_api_key" entry of the credentials file. creds is set to its path in
; init.lsp. Run it from the examples directory:
;   python3 ../lisp_interpreter.py fred_example.lsp

; --- 1. A whole series: US GDP, quarterly ------------------------------------
(define gdp (fred-table creds "GDP"))
(define gdp-dates (table-column gdp "date"))
(display (format "GDP: {} quarterly observations, from {} to {}\n"
                 (table-row-count gdp) (vector-ref gdp-dates 0) (vector-ref gdp-dates (- (table-row-count gdp) 1))))
(display-table (table-tail gdp 4) '(("GDP" ",.1f")))

; --- 2. A range of dates: the unemployment rate in 2020 -----------------------
; The dates can be dates or "YYYY-MM-DD" text.
(display "\nThe unemployment rate in 2020, %:\n")
(display-table (fred-table creds "UNRATE" :start-date (date 2020 1 1) :end-date "2020-12-31") :max-rows #f)

; --- 3. Several series at once, lined up -----------------------------------------
; A daily series (the 10-year Treasury), a weekly one (the 30-year mortgage
; rate), and a monthly one (fed funds): one table, a row for each date any
; of them has, then the monthly averages of each.
(define rates (fred-table creds '("DGS10" "MORTGAGE30US" "FEDFUNDS") :start-date "2025-01-01"))
(display (format "\n{} dates since the start of 2025; by month:\n" (table-row-count rates)))
(display-table (series-monthly rates) '(("month" hide) ("DGS10" ".2f") ("MORTGAGE30US" ".2f") ("FEDFUNDS" ".2f")))
