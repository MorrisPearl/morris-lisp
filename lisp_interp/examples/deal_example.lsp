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

; --- A second PAC, under the first one's companion ---
; A PAC is sized from what its parent is paid, whether the parent is the collateral or not, so the companion of the first PAC can be
; divided in the same way, for a narrower range of speeds. The deal is run at each of the two speeds, down to the parent, to find
; out what the parent is paid.
(define (build-two-pacs psa)
  (let* ((pool (collateral-from-psa "POOL" 250000000 6.25 :term 360 :psa psa))
         (deal (start-deal "Two PACs" pool)))
    (deal-pac! deal "POOL" "PAC1" "COMP1" 100 300)
    (deal-pac! deal "COMP1" "PAC2" "COMP2" 150 250)
    (deal-run! deal)
    deal))

(define (miss deal pac owner)
  (vector-max (abs (- (node-balance (get-node deal pac)) (pac-split-schedule (node-split (get-node deal owner)))))))

(display "\nTwo PACs: PAC1 is paid on schedule at 100% to 300% PSA, and PAC2, out of the companion, at 150% to 250%.\n")
(display "Speed (PSA)   PAC1 is off its schedule by at most   PAC2 is off its schedule by at most\n")
(dolist (psa '(120 200 280))
  (let ((deal (build-two-pacs psa)))
    (display (format "{:>10}   {:>35,.0f}   {:>35,.0f}\n" psa (miss deal "PAC1" "POOL") (miss deal "PAC2" "COMP1")))))

; --- Interest: a floater and an inverse floater ---
; Each bond has a coupon, a function of the index, and is paid a twelfth of it on its balance each month, before the principal. A
; floater and an inverse floater are sized, from the cap, so that together they pay the coupon of the bond they are divided out of,
; whatever the index is.
(define (build-floating index)
  (let* ((pool (collateral-from-psa "POOL" 250000000 6.25 :term 360 :psa 150))
         (deal (start-deal "Floating" pool)))
    (deal-sequential! deal "POOL" '(("A" 150000000) ("B" 100000000)))
    (deal-floater-inverse! deal "B" "F" "I" :cap 0.09 :margin 0.005 :index-name "SOFR")
    (deal-run! deal :index index)
    deal))

(define (first-month-coupon deal name) (vector-ref (table-column (deal-coupon-table deal) name) 0))
(define (first-balance deal name) (vector-ref (node-balance (get-node deal name)) 0))

(define floating (build-floating 0.03))
(display (format "\nB, {:,.0f} at {:.2%}, is divided into a floater of {:,.0f} (the index plus 0.5%, to 9%) and an inverse floater of {:,.0f}.\n"
                 (first-balance floating "B") (first-month-coupon floating "B") (first-balance floating "F") (first-balance floating "I")))
(display "Index    floater   inverse   the two together\n")
(dolist (index '(0.0 0.03 0.05 0.08 0.12))
  (let* ((deal (build-floating index))
         (floater (first-month-coupon deal "F"))
         (inverse (first-month-coupon deal "I"))
         (together (/ (+ (* floater (first-balance deal "F")) (* inverse (first-balance deal "I"))) (first-balance deal "B"))))
    (display (format "{:>5.2%}  {:>8.3%}  {:>8.3%}  {:>10.3%}   {}\n" index floater inverse together (deal-check deal)))))

; --- More than one piece of collateral ---
; Each piece is the root of a tree of its own.
(define group1 (collateral-from-psa "G1" 100000000 6.0 :term 360 :psa 150))
(define group2 (collateral-from-psa "G2" 50000000 7.0 :term 360 :psa 150))
(define two-groups (start-deal "Two groups" group1))
(deal-add-collateral! two-groups group2)
(deal-sequential! two-groups "G1" '(("S1" 60000000) ("S2" 40000000)))
(deal-pro-rata! two-groups "G2" '(("T1" 20000000) ("T2" 30000000)))
(deal-run! two-groups)
(display (format "\nTwo pieces of collateral, {}; the bonds are {}; the principal and the interest add up: {}\n"
                 (string-join (deal-roots two-groups) " and ") (string-join (deal-leaves two-groups) ", ") (deal-check two-groups)))

; --- A Z bond, and an accretion directed bond ---
; A Z bond is not paid its interest: what it is owed is added to its balance, and paid, as principal, to the bonds ahead of it. That is
; why the interest is worked out before the principal. With :accretion-to, one bond is paid what the Z bond accrues first.
(define (build-z accretion-to)
  (let* ((pool (collateral-from-psa "POOL" 100000000 6.0 :term 360 :psa 150))
         (deal (start-deal "Z" pool)))
    (deal-sequential! deal "POOL" '(("A" 30000000) ("B" 30000000) ("Z" 40000000 z)) :accretion-to accretion-to)
    (deal-run! deal)
    deal))

(define (first-month deal table-of name) (vector-ref (table-column (table-of deal) name) 0))

(define z-deal (build-z '()))
(define adb-deal (build-z "B"))
(display (format "\nIn the first month Z accrues {:,.0f}, which is not paid to it as interest. It is paid, as principal:\n"
                 (first-month z-deal deal-accrual-table "Z")))
(display (format "  to A, in order: A {:,.0f}, B {:,.0f}\n" (first-month z-deal deal-principal-table "A") (first-month z-deal deal-principal-table "B")))
(display (format "  with B directed: A {:,.0f}, B {:,.0f}\n" (first-month adb-deal deal-principal-table "A") (first-month adb-deal deal-principal-table "B")))
(display (format "Z is paid off in month {}, and A in month {}; the principal and the interest add up: {}\n"
                 (month-paid-off z-deal "Z") (month-paid-off z-deal "A") (deal-check z-deal)))

; --- Interest-only and principal-only bonds ---
; An IO has a notional balance that follows the PO's, and is paid the coupon on it; the PO is paid the principal. Either can be divided.
(define strips (start-deal "Strips" (collateral-from-psa "POOL" 100000000 6.0 :term 360 :psa 150)))
(deal-io-po! strips "POOL" "IO" "PO")
(deal-sequential! strips "PO" '(("PO1" 40000000) ("PO2" 60000000)))
(deal-run! strips)
(display (format "\nThe IO's notional balance falls from {:,.0f} to {:,.0f} after a year; its first month's interest is {:,.0f}, and the PO's principal {:,.0f}.\n"
                 (vector-ref (node-balance (get-node strips "IO")) 0) (vector-ref (node-balance (get-node strips "IO")) 12)
                 (first-month strips deal-interest-table "IO") (first-month strips deal-principal-table "PO")))
(display (format "PO1 is paid off in month {}, and PO2 in month {}; the principal and the interest add up: {}\n"
                 (month-paid-off strips "PO1") (month-paid-off strips "PO2") (deal-check strips)))

; --- Losses, and interest shortfalls ---
; A loss is balance written off, with no cash. A sequential split writes down its last bond first; a split made with :losses 'pro-rata
; shares a loss by what each bond has left. Here the B bonds go first, from the bottom up, and then the A bonds share what is left.
; The pool is given by its cash flows (in millions): where they come from does not matter to the deal.
(define (monthly-flows balance coupon principals losses)
  (let ((balances (list balance)))
    (loop for p in principals for l in losses
          do (push (- (car balances) p l) balances))
    (list (list->vector (reverse balances))
          (list->vector (map (lambda (b) (* b (/ coupon 12.0))) (reverse (cdr balances))))
          (list->vector principals)
          (list->vector losses))))

(define (lossy-deal losses-of-a-and-b)
  (let* ((flows (monthly-flows 100.0 0.06 '(20.0 20.0 15.0 10.0 10.0) '(0.0 25.0 0.0 0.0 0.0)))
         (pool (make-collateral :name "POOL" :balance (car flows) :interest (cadr flows) :principal (caddr flows)
                                :loss (cadddr flows) :coupon (constant-coupon 0.06)))
         (deal (start-deal "Losses" pool)))
    (deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)))
    (deal-sequential! deal "A" '(("A1" 50.0) ("A2" 30.0)) :losses losses-of-a-and-b)
    (deal-sequential! deal "B" '(("B1" 15.0) ("B2" 5.0)))
    (deal-run! deal)
    deal))

(define lossy (lossy-deal 'pro-rata))
(define (written-down deal name) (vector-ref (table-column (deal-loss-table deal) name) 1))
(display (format "\nThe pool loses 25 in the second month. B2 is written down by {}, B1 by {}, and the A bonds share the other {}: A1 {}, A2 {}.\n"
                 (written-down lossy "B2") (written-down lossy "B1") (written-down lossy "A") (written-down lossy "A1") (written-down lossy "A2")))
(define lossy-in-order (lossy-deal 'reverse))
(display (format "With the A bonds written down from the bottom up, too, A2 takes all of it: A1 {}, A2 {}. The principal and the interest add up: {}\n"
                 (written-down lossy-in-order "A1") (written-down lossy-in-order "A2") (deal-check lossy-in-order)))

; If the interest the pool pays is less than the bonds are owed, the deal has to be started with :shortfalls #t: the bonds that go without are owed
; what they were not paid, with interest at their coupon, and are paid it when there is cash.
(define short-pool (make-collateral :name "POOL" :balance #(100.0 80.0 60.0 40.0 20.0 0.0) :principal #(20.0 20.0 20.0 20.0 20.0)
                                    :interest #(0.45 0.4 0.35 0.2 0.1) :coupon (constant-coupon 0.06)))
(define short-deal (start-deal "Shortfalls" short-pool :shortfalls #t))
(deal-sequential! short-deal "POOL" '(("S" 80.0) ("J" 20.0)))
(deal-run! short-deal)
(define (month-of deal table-of name month) (vector-ref (table-column (table-of deal) name) month))
(display (format "\nThe pool pays 0.45 of interest in the first month, and the bonds are owed 0.5. S is paid {:.3f}, and J {:.3f}, which is a shortfall of {:.3f}.\n"
                 (month-of short-deal deal-interest-table "S" 0) (month-of short-deal deal-interest-table "J" 0)
                 (month-of short-deal deal-shortfall-table "J" 0)))
(display (format "The pool pays 0.4 in the second month: S is paid its 0.3 and J the other 0.1, of the 0.15025 it is owed (0.1, and the 0.05 carried with a month's interest), so J is short by {:.5f}. The principal and the interest add up: {}\n"
                 (month-of short-deal deal-shortfall-table "J" 1) (deal-check short-deal)))
