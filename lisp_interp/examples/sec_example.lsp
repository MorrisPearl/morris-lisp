; sec_example.lsp
;
; Financial statements from the SEC: the income statement, balance sheet,
; and cash flow statement of any company that files with it, from the
; numbers tagged in its 10-Ks and 10-Qs, put in a standard form -- see
; "SEC financial statements" in the reference manual.
;
; It needs a credentials file with a "sec_user_agent" entry -- a name and
; email address, which the SEC asks every request to carry, such as
; "Jane Smith jane@example.com". creds is set to its path in init.lsp.
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py sec_example.lsp

; --- 1. A company's statements, as it would show them -----------------------
; A row per line item, a column per fiscal year (newest first), amounts in
; millions. The source column, which says which concepts the numbers came
; from, is left out of the display: its format is hide.
(display (format "{}\n\n" (hash-table-ref (sec-company creds "AAPL") "name")))
(display "Income statement:\n")
(display-table (sec-income-statement creds "AAPL") '(("source" hide)))
(display "\nBalance sheet:\n")
(display-table (sec-balance-sheet creds "AAPL") '(("source" hide)))
(display "\nCash flow statement:\n")
(display-table (sec-cash-flow-statement creds "AAPL") '(("source" hide)))

; --- 2. Quarters --------------------------------------------------------------
; A fourth quarter, which has no 10-Q, is the year less the first three.
(display "\nMicrosoft's last 6 quarters:\n")
(display-table (sec-income-statement creds "MSFT" :period "quarterly" :count 6) '(("source" hide)))

; --- 3. Working with the numbers ------------------------------------------------
; sec-financials has every line item, a row per period, in dollars: ready
; for the table and vector functions. Here, margins and returns for three
; companies over five years.
(define (ratios ticker)
  (let ((f (sec-financials creds ticker)))
    (with-columns (period-end revenue gross-profit net-income stockholders-equity free-cash-flow) f
      (make-table "company" (make-vector (table-row-count f) ticker)
                  "year-end" period-end
                  "revenue ($bn)" (/ revenue 1e9)
                  "gross margin" (/ gross-profit revenue)
                  "net margin" (/ net-income revenue)
                  "return on equity" (/ net-income stockholders-equity)
                  "free cash flow ($bn)" (/ free-cash-flow 1e9)))))

(display "\nMargins and returns:\n")
(display-table (table-append (ratios "AAPL") (ratios "MSFT") (ratios "KO"))
               '(("revenue ($bn)" ",.1f") ("gross margin" ".1%") ("net margin" ".1%")
                 ("return on equity" ".1%") ("free cash flow ($bn)" ",.1f")))

; --- 4. Every value of one concept --------------------------------------------
; sec-concepts lists everything a company has tagged; sec-facts gives every
; value it has reported for one -- each period, in each filing.
(define eps (sec-facts creds "KO" "EarningsPerShareDiluted"))
(define annual-eps
  (with-columns (form start end) eps
    (table-filter eps (vector-and (= form "10-K") (> (days-between start end) 300)))))
(display (format "\nCoca-Cola has reported diluted EPS {} times, {} of them for a whole year in a 10-K;\n"
                 (table-row-count eps) (table-row-count annual-eps)))
(display "the last few -- each year is reported again, for comparison, in the next two 10-Ks:\n")
(display-table (table-select (table-tail annual-eps 6) '("start" "end" "value" "form" "filed")))
