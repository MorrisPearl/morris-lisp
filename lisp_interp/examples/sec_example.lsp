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
; millions; the source column says which concepts the numbers came from.
(display (format "{}\n\n" (hash-table-ref (sec-company creds "AAPL") "name")))
(display "Income statement:\n")
(display-table (table-drop-columns (sec-income-statement creds "AAPL") '("source")))
(display "\nBalance sheet:\n")
(display-table (table-drop-columns (sec-balance-sheet creds "AAPL") '("source")))
(display "\nCash flow statement:\n")
(display-table (table-drop-columns (sec-cash-flow-statement creds "AAPL") '("source")))

; --- 2. Quarters --------------------------------------------------------------
; A fourth quarter, which has no 10-Q, is the year less the first three.
(display "\nMicrosoft's last 6 quarters:\n")
(display-table (table-drop-columns (sec-income-statement creds "MSFT" :period "quarterly" :count 6)
                                   '("source")))

; --- 3. Working with the numbers ------------------------------------------------
; sec-financials has every line item, a row per period, in dollars: ready
; for the table and vector functions. Here, margins and returns for three
; companies over five years.
(define (ratios ticker)
  (let* ((f (sec-financials creds ticker))
         (column (lambda (name) (table-column f name))))
    (make-table "company" (make-vector (table-row-count f) ticker)
                "year-end" (column "period-end")
                "revenue ($bn)" (/ (column "revenue") 1e9)
                "gross margin" (/ (column "gross-profit") (column "revenue"))
                "net margin" (/ (column "net-income") (column "revenue"))
                "return on equity" (/ (column "net-income") (column "stockholders-equity"))
                "free cash flow ($bn)" (/ (column "free-cash-flow") 1e9))))

(display "\nMargins and returns:\n")
(display-table (table-append (ratios "AAPL") (ratios "MSFT") (ratios "KO"))
               '(("revenue ($bn)" ",.1f") ("gross margin" ".1%") ("net margin" ".1%")
                 ("return on equity" ".1%") ("free cash flow ($bn)" ",.1f")))

; --- 4. Every value of one concept --------------------------------------------
; sec-concepts lists everything a company has tagged; sec-facts gives every
; value it has reported for one -- each period, in each filing.
(define eps (sec-facts creds "KO" "EarningsPerShareDiluted"))
(define annual-eps
  (table-filter eps (vector-and (= (table-column eps "form") "10-K")
                                (> (days-between (table-column eps "start") (table-column eps "end")) 300))))
(display (format "\nCoca-Cola has reported diluted EPS {} times, {} of them for a whole year in a 10-K;\n"
                 (table-row-count eps) (table-row-count annual-eps)))
(display "the last few -- each year is reported again, for comparison, in the next two 10-Ks:\n")
(display-table (table-select (table-slice annual-eps (- (table-row-count annual-eps) 6))
                             '("start" "end" "value" "form" "filed")))
