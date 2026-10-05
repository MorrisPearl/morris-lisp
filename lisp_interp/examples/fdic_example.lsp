; fdic_example.lsp
;
; Bank financial data from the FDIC: every insured bank's quarterly Call
; Report -- balance sheet, income, loans, deposits, capital -- and the
; ratios the FDIC works out from them, back to 1984. See "FDIC bank data"
; in the reference manual.
;
; It needs your credentials file, with an "fdic_api_key" entry; creds is
; set to its path in init.lsp. Run it from the examples directory:
;   python3 ../lisp_interpreter.py fdic_example.lsp

; --- 1. Finding a bank ----------------------------------------------------------
; A bank is its FDIC certificate number. fdic-find-bank looks them up by
; name -- including closed banks and former names.
(display "Banks with names like \"Silicon Valley\":\n")
(display-table (fdic-find-bank creds "silicon valley")
               '(("total-assets" ",.0f")))

; --- 2. A bank's reports, as it would show them ----------------------------------
; Quarters, newest first, amounts in millions; :period "annual" for year ends.
; The field column (the FDIC's name for each item) is left out of the
; display: its format is hide. The balance sheet has more than 20 lines,
; so :max-rows #f shows all of them.
(display "\nWells Fargo Bank -- balance sheet:\n")
(display-table (fdic-balance-sheet creds 3511 :count 4) '(("field" hide)) :max-rows #f)
(display "\nIncome, each quarter:\n")
(display-table (fdic-income-statement creds 3511 :count 4) '(("field" hide)))
(display "\nRatios (in percent), each year:\n")
(display-table (fdic-ratios creds 3511 :period "annual" :count 5) '(("field" hide)))

; --- 3. Working with the numbers ---------------------------------------------------
; fdic-financials has every item, a row per quarter, in dollars. Silicon
; Valley Bank's last two years before it failed in March 2023: the share of
; its deposits that were uninsured, and how its securities compared with
; its equity.
(define svb (fdic-financials creds 24735 :count 8))
(display "\nSilicon Valley Bank, its last eight quarters:\n")
(with-columns (report-date total-deposits uninsured-deposits securities equity return-on-assets) svb
  (display-table (make-table "quarter" report-date
                             "deposits ($bn)" (/ total-deposits 1e9)
                             "uninsured" (/ uninsured-deposits total-deposits)
                             "securities ($bn)" (/ securities 1e9)
                             "securities / equity" (/ securities equity)
                             "return on assets" (/ return-on-assets 100))
                 '(("deposits ($bn)" ",.1f") ("uninsured" ".0%") ("securities ($bn)" ",.1f")
                   ("securities / equity" ".1f") ("return on assets" ".2%"))))

; --- 4. Anything else the FDIC has ---------------------------------------------------
; fdic-get reads any of its datasets; fdic-fields says what the fields mean.
; Here, the banks that have failed since the start of 2023 (amounts in
; thousands, as the FDIC gives them).
(define failures
  (fdic-get creds "failures"
            '(("filters" . "FAILDATE:[2023-01-01 TO *]")
              ("fields" . "NAME,CITY,PSTALP,FAILDATE,QBFASSET,COST")
              ("sort_by" . "FAILDATE")
              ("sort_order" . "DESC"))))
(display (format "\n{} banks have failed since the start of 2023; the largest:\n" (table-row-count failures)))
(display-table (table-head (table-sort (table-select failures '("NAME" "CITY" "PSTALP" "FAILDATE" "QBFASSET" "COST"))
                                       "QBFASSET" #t)
                           5)
               '(("QBFASSET" ",.0f") ("COST" ",.0f")))
