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

; --- A PAC and its companion ---
; The PAC is as big as the pool pays at both of two speeds (month by month the least of the two, added up), and is paid on the
; schedule of that least: it is paid its schedule first, then the companion is paid what is over, then the PAC the rest. At
; any speed between the two the PAC is paid exactly on schedule, and the companion takes up the difference.
(define (build-pac psa)
  (let* ((pool (collateral-from-psa "POOL" 250000000 6.25 :term 360 :psa psa))
         (deal (start-deal (format "PAC {}/{}" 100 300) pool)))
    (deal-pac! deal "POOL" "PAC" "COMP" 100 300)         ; the two speeds: 100% and 300% PSA
    (deal-run! deal)
    deal))

(define (pac-balance-at deal month) (vector-ref (node-balance (get-node deal "PAC")) month))
(define (pac-schedule-at deal month) (vector-ref (pac-split-schedule (node-split (get-node deal "POOL"))) month))

(define pac-deal (build-pac 100))
(display (format "\nThe PAC is {:,.0f} of the pool's 250,000,000, and the companion {:,.0f}.\n"
                 (pac-balance-at pac-deal 0) (vector-ref (node-balance (get-node pac-deal "COMP")) 0)))
(display "                         at month 60, the PAC owes\n")
(display "Speed (PSA)  companion paid off    by schedule     in fact\n")
(dolist (psa '(50 100 200 300 600))
  (let ((deal (build-pac psa)))
    (display (format "{:>10}  {:>17}  {:>13,.0f}  {:>11,.0f}\n" psa (month-paid-off deal "COMP")
                     (pac-schedule-at deal 60) (pac-balance-at deal 60)))))
