; deal_example.lsp
;
; A structured deal as a tree: a pool of mortgages at the root, which pays principal each month, divided by splits into
; tranches, which can be divided again until the bonds at the leaves. The principal goes down the tree month by month; this
; program builds a small one, runs it at two prepayment speeds, and shows when each bond is paid off. See "Structured deals"
; in the library manual. Needs nothing. Run it from the examples directory:
;   python3 ../lisp_interpreter.py deal_example.lsp

(load "deal.lsp")

;   POOL --sequential--> A --sequential--> A1, A2
;                        B --pro-rata----> B1, B2
(define (build-deal psa)
  (let* ((pool (collateral-from-psa "POOL" 250000000 6.25 :term 360 :age 0 :psa psa))
         (deal (start-deal (format "Demo, {}% PSA" psa) pool)))
    (deal-sequential! deal "POOL" '(("A" 150000000) ("B" 100000000)))
    (deal-sequential! deal "A" '(("A1" 60000000) ("A2" 90000000)))
    (deal-pro-rata! deal "B" '(("B1" 30000000) ("B2" 70000000)))
    (deal-run! deal)
    deal))

; the first month in which a bond has nothing left to be paid
(define (month-paid-off deal name)
  (let ((balances (node-balance (get-node deal name))))
    (position-if (lambda (balance) (< balance 0.01)) balances)))

(define (show deal)
  (display (format "{}: the principal adds up in every month: {}\n" (deal-name deal) (deal-check deal)))
  (dolist (name (deal-leaves deal))
    (display (format "  {:<3} is paid off in month {:>3}\n" name (month-paid-off deal name)))))

(define slow (build-deal 100))
(define fast (build-deal 400))
(show slow)
(show fast)

; the principal of the first few months, a column for each node, at the slow speed
(display "\nThe first months of the slow deal, the principal each node is paid:\n")
(display-table (table-head (deal-principal-table slow) 3)
               '(("POOL" ",.0f") ("A" ",.0f") ("B" ",.0f") ("A1" ",.0f") ("A2" ",.0f") ("B1" ",.0f") ("B2" ",.0f")))
