; deal_example.lsp
;
; A structured deal as a tree: a pool of mortgages at the root, which pays principal each month, divided by splits into
; tranches, which can be divided again until the bonds at the leaves. The principal goes down the tree month by month; this
; program builds a small one, runs it at two prepayment speeds, and shows when each bond is paid off. The pool is data, a table
; of pieces of collateral (balance, wac, pass-through coupon, wam), and its cash flows are worked out at a prepayment speed.
; See the CMO manual (lisp_cmo_manual.md). Needs nothing. Run it from the examples directory:
;   python3 ../lisp_interpreter.py deal_example.lsp

(load "deal.lsp")

; one pool of 250 million at 6.25%, passed through at the same rate, with 360 months to run, that prepays at this speed
(define (new-pool-deal name psa)
  (new-deal name :collateral '((250000000 6.25 6.25 360)) :speed (prepayment-speed 'psa psa)))

;   POOL --sequential--> A --sequential--> A1, A2
;                        B --pro-rata----> B1, B2
(define (build-deal psa)
  (let ((deal (new-pool-deal (format "Demo, {}% PSA" psa) psa)))
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
  (let ((deal (new-pool-deal (format "PAC {}/{}" 100 300) psa)))
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
  (let ((deal (new-pool-deal "Two PACs" psa)))
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
  (let ((deal (new-pool-deal "Floating" 150)))
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

; --- Pieces of collateral with different coupons ---
; The pool is the sum of its pieces, each projected at the speed on its own: here 100 million at 6.0% (the loans pay 6.5%) and 50 million, 12
; months old, at 7.0%. The pool's coupon is the rate that the interest it pays is of its balance, which falls as the piece with the higher coupon is
; paid off. A deal is run at the speed it is given, and the pieces' cash flows are worked out again each time.
(define pieces-deal (new-deal "Pieces" :collateral '((100000000 6.5 6.0 360) (50000000 7.5 7.0 240 12)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! pieces-deal "POOL" '(("S1" 90000000) ("S2" 60000000)))
(define (pool-coupon-in-month deal month) (vector-ref (node-coupon (get-node deal "POOL")) month))
(deal-run! pieces-deal)
(display (format "\nTwo pieces of collateral, {:,.0f} in all, for {} months; the pool's coupon is {:.3%} in the first month and {:.3%} in month 200; the bonds are {}; the principal and the interest add up: {}\n"
                 (first-balance pieces-deal "POOL") (deal-periods pieces-deal) (pool-coupon-in-month pieces-deal 0) (pool-coupon-in-month pieces-deal 199)
                 (string-join (deal-leaves pieces-deal) ", ") (deal-check pieces-deal)))
(define (first-principal deal) (vector-ref (node-principal (get-node deal "POOL")) 0))
(define principal-at-150 (first-principal pieces-deal))
(deal-run! pieces-deal (prepayment-speed 'psa 400))
(display (format "At 400% PSA the pool pays {:,.0f} of principal in the first month, instead of {:,.0f} at 150%; the bonds still add up: {}\n"
                 (first-principal pieces-deal) principal-at-150 (deal-check pieces-deal)))

; --- A Z bond, and an accretion directed bond ---
; A Z bond is not paid its interest: what it is owed is added to its balance, and paid, as principal, to the bonds ahead of it. That is
; why the interest is worked out before the principal. With :accretion-to, one bond is paid what the Z bond accrues first.
(define (build-z accretion-to)
  (let ((deal (new-deal "Z" :collateral '((100000000 6.0 6.0 360)) :speed (prepayment-speed 'psa 150))))
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
(define strips (new-deal "Strips" :collateral '((100000000 6.0 6.0 360)) :speed (prepayment-speed 'psa 150)))
(deal-io-po! strips "POOL" "IO" "PO")
(deal-sequential! strips "PO" '(("PO1" 40000000) ("PO2" 60000000)))
(deal-run! strips)
(display (format "\nThe IO's notional balance falls from {:,.0f} to {:,.0f} after a year; its first month's interest is {:,.0f}, and the PO's principal {:,.0f}.\n"
                 (vector-ref (node-balance (get-node strips "IO")) 0) (vector-ref (node-balance (get-node strips "IO")) 12)
                 (first-month strips deal-interest-table "IO") (first-month strips deal-principal-table "PO")))
(display (format "PO1 is paid off in month {}, and PO2 in month {}; the principal and the interest add up: {}\n"
                 (month-paid-off strips "PO1") (month-paid-off strips "PO2") (deal-check strips)))
