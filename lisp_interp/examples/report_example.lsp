; report_example.lsp
;
; Two reports with control breaks, written to text files by lib/report.lsp, from made-up data (so it needs nothing):
;   1. a report of mortgages, with subtotals for each zip code, for each state, and a grand total, on pages;
;   2. a letter to each client, listing the client's transactions, with a total.
; The spec of a report is a value that holds its templates: what a page, a group and a row say, and which columns the
; groups are of. See "Reports with control breaks" in the library manual. Run it from the examples directory:
;   python3 ../lisp_interpreter.py report_example.lsp
; It writes mortgage_report.txt and client_letters.txt, and shows them.

(load "report.lsp")

; --- 1. Mortgages: by state, and by zip code within it ---
(define n 30)
(define numbers (vector-range n))
(define mortgages
  (make-table "loan-id" (+ 1000 numbers)
              "state"   (list->vector (map (lambda (i) (list-ref '("NY" "CA" "TX") (remainder i 3))) (iota n)))
              "zip"     (list->vector (map (lambda (i) (list-ref '("10001" "10002" "90001" "90210" "73301") (remainder (* i 7) 5))) (iota n)))
              "balance" (* 1000 (+ 150 (* 3 (vector-range n))))
              "rate"    (+ 5.5 (* 0.05 numbers))))

(define mortgage-report
  (make-report-spec
    :page-lines 26
    :page-header "MORTGAGE REPORT                                  page {{page}}\n--------------------------------------------------"
    :page-footer "(this page: {{loans}} loans, {{total:,.0f}})"
    :detail "{{loan-id:<6}} {{zip:<7}} {{balance:>12,.0f}} {{rate:>6.2f}}%"
    :summaries (list (list "loans" 'count) (list "total" 'sum "balance") (list "wac" 'weighted-mean "rate" "balance"))
    :breaks (list (make-report-break :field "state"
                                     :header "\nSTATE {{state}}"
                                     :footer "  {{state}}: {{loans}} loans {{total:>13,.0f}} at {{wac:.3f}}%")
                  (make-report-break :field "zip"
                                     :footer "    zip {{zip}}: {{loans}} loans {{total:>13,.0f}}"))
    :report-footer "\nALL STATES: {{loans}} loans {{total:>13,.0f}} at {{wac:.3f}}%"))

(display (format "{} pages written to mortgage_report.txt\n\n" (write-report mortgages "mortgage_report.txt" mortgage-report)))
(display (read-text-file "mortgage_report.txt"))

; --- 2. Letters: one to each client, on a page of its own ---
(define transactions
  (make-table "client" (vector "Zed Co" "Amy Lee" "Zed Co" "Amy Lee" "Amy Lee" "Bo Park" "Zed Co" "Bo Park")
              "date"   (vector "2026-03-05" "2026-03-02" "2026-03-01" "2026-03-09" "2026-03-01" "2026-03-12" "2026-03-20" "2026-03-30")
              "what"   (vector "rent" "coffee" "books" "food" "gas" "tickets" "gift" "dinner")
              "amount" (vector 1200.0 4.5 30.0 20.0 40.0 85.0 5.25 61.2)))

(define letters
  (make-report-spec
    :variables (list (list 'month "March 2026"))
    :page-lines 24
    :page-header "ACME BANK                           Statement for {{client}}"
    :page-footer "page {{page}}"
    :detail "  {{date}}  {{what:<10}} {{amount:>10,.2f}}"
    :detail-order '("date")
    :summaries (list (list "count" 'count) (list "total" 'sum "amount"))
    :breaks (list (make-report-break :field "client" :new-page #t :restart-page-numbers #t
                                     :header "\nDear {{client}},\n\nYour {{count}} transactions in {{month}}:\n"
                                     :footer "  --------------------------\n  Total       {{total:>14,.2f}}\n\nThank you for banking with us."))))

(write-report transactions "client_letters.txt" letters)
(display "\n")
(display (read-text-file "client_letters.txt"))
