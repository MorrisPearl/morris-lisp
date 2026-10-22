; deal_pricing.lsp
; ================
; What a price says about a tranche of a deal, and what a yield or a spread says about its price. A tranche has these slots (see deal.lsp):
;
;   price         what the buyer pays for each 100 of its balance, without the accrued interest
;   yield         what the buyer earns, in percent a year: the bond equivalent yield of the cash flows that the tranche is paid
;   spread        the yield over the Treasury curve at the average life of the tranche, in basis points
;   duration      the modified duration, in years
;   average-life  the average life, in years
;   dv01          how much the money falls if the yield rises by a basis point, and nothing else is changed
;   money         what the buyer pays, in all: the balance times the price over 100, and the accrued interest
;   delay         the days from the end of the accrual period of its interest to the day it is paid (24 to begin with)
;
; The user gives one of price, yield or spread, and the rest are worked out from it (see deal-set-price! and the others): they are of the cash flows that the
; tranche is paid when the deal is run at its pricing speed, as of the closing date of the deal, which is when the buyer pays and the bond is delivered.
; (deal-update-analytics! deal) works them out again, after the deal has changed: from the one that was given.
;
;   (define deal (new-deal "Demo 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
;                          :collateral '((100000000 6.5 6.0 360))))
;   (deal-sequential! deal "POOL" '(("A" 60000000) ("B" 40000000)))
;   (deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))        ; years and percent: the curve that the spreads are to
;   (deal-set-price! deal "A" 100.5)                  ; the yield, the spread, the duration, the dv01 and the money of A are worked out
;   (deal-set-spread! deal "B" 120)                   ; B is to be 120 basis points over the Treasury curve at its average life: its price is worked out
;   (deal-set-price! deal "POOL" "+")                 ; the price of POOL that makes its money what its children, A and B, have between them
;   (display-table (deal-pricing-table deal))
;
; THE CALCULATIONS.
;
; The accrued interest is what the balance has earned at the coupon since the accrual period began, by the 30/360 day count (every month is 30 days, and a year
; 360): balance x coupon x days / 360. The accrual period that ends a delay before the first payment date is the one that the closing date is in, and
; began a month before it ended. (A closing date after that end is an error: the first payment is not for a buyer then.)
;
; The yield is a bond equivalent yield: the cash flows, the principal and the interest that the tranche is paid each month, on its payment dates, are discounted
; by (1 + yield / 200) to the power of minus a sixth for each month from the closing date, the months being counted by the 30/360 day count (a payment is a
; whole number of months after the one before it), and what they are worth, added up, is the money. The yield that is given is the one that the cash flows are
; discounted at; the yield of a price is the one that makes them worth the money. The duration is how much the money falls, in the proportion, for a rise of
; one in the yield (the modified duration), and the dv01 is how much the money falls when the yield is a basis point higher.
;
; The spread is the yield less the yield of the Treasury curve at the average life of the tranche, which is found by a straight line between the points of
; the curve on either side of it (and is that of the nearest point, beyond the ends of the curve). A tranche that is paid no principal has no average life,
; and no spread.
;
; A price can be given as "+", which is the price that makes the money of the tranche what the money of its children add up to, or "?", which is the price
; that makes the money of the tranche and of the tranches that are paid by the same split (its siblings) what the money of their parent is.

(require "deal.lsp")
(require "solver.lsp")

; ---------------------------------------------------------------------------
; Dates
; ---------------------------------------------------------------------------

(define (days-360 from to)
  "The days from one date to another by the 30/360 count (the bond basis: every month is 30 days, and the 31st counts as the 30th)."
  (let* ((day-from (min 30 (date-day from)))
         (day-to (if (and (= (date-day to) 31) (= day-from 30)) 30 (date-day to))))
    (+ (* 360 (- (date-year to) (date-year from)))
       (* 30 (- (date-month to) (date-month from)))
       (- day-to day-from))))

(define (deal-settlement deal)
  "The date that a buyer pays on, and from when the cash flows are worth something: the closing date of the deal."
  (when (null? (deal-closing-date deal))
    (error "the deal has no closing date, which a price is as of: give it one, (deal-set-closing-date! deal (date 2026 11 20)), or in (info deal)"))
  (deal-payment-date deal 1)                      ; (an error that says so, if there is no first payment date)
  (deal-closing-date deal))

(define (accrual-end deal node)
  "The end of the first accrual period of the node: its delay, in days, before the first payment date."
  (date-add-days (deal-payment-date deal 1) (- (node-delay node))))

(define (accrued-interest deal node)
  "The interest that has accrued on the node's balance at the closing date of the deal: the balance times the coupon of the first month, for the days from the start of
the accrual period to the closing date, by the 30/360 count over 360. Nothing has accrued if the period has not begun."
  (let* ((closing (deal-settlement deal))
         (end (accrual-end deal node))
         (start (date-add-months end -1)))
    (when (> (days-360 end closing) 0)
      (error (format "the closing date, {}, is after the end of the first accrual period of {}, {} (the first payment is {}, and its delay {} days)"
                     closing (node-name node) end (deal-payment-date deal 1) (node-delay node))))
    (* (vector-ref (node-balance node) 0) (node-coupon-rate deal node 0) (/ (max 0 (days-360 start closing)) 360.0))))

(define (months-from-settlement deal payments)
  "A vector with a number for each of the payments: the months from the closing date to the payment date, by the 30/360 count, which is not a whole number for the first,
and a month more for each one after it."
  (let ((first-month (/ (days-360 (deal-settlement deal) (deal-payment-date deal 1)) 30.0))
        (months (make-vector payments 0.0)))
    (loop for t from 0 below payments
          do (vector-set! months t (+ first-month t)))
    months))

; ---------------------------------------------------------------------------
; Yield, money, duration
; ---------------------------------------------------------------------------

(define (monthly-factor yield)
  "What a dollar is worth a month later, at the yield (percent, bond equivalent): (1 + yield / 200) to the minus a sixth."
  (expt (+ 1.0 (/ yield 200.0)) (/ -1.0 6.0)))

(define (present-value flows months yield)
  "What the cash flows (a vector) are worth at the yield, when each is the months (a vector) from the closing date."
  (vector-sum (* flows (expt (monthly-factor yield) months))))

(define (modified-duration flows months yield)
  "How much the value of the cash flows falls, in proportion, for a rise of one (100 percentage points) in the yield, in years."
  (/ (vector-sum (* flows (/ months 12.0) (expt (monthly-factor yield) months)))
     (* (present-value flows months yield) (+ 1.0 (/ yield 200.0)))))

(define (yield-of-money flows months money)
  "The yield, in percent, at which the cash flows are worth the money: found by Ridders' method between -100 and 1000 percent. An error if there is none."
  (when (<= money 0.0)
    (error (format "the money is {:,.2f}: it has to be more than 0 to have a yield" money)))
  (let ((excess (lambda (yield) (- (present-value flows months yield) money))))
    (unless (and (> (excess -100.0) 0.0) (< (excess 1000.0) 0.0))
      (error (format "no yield, from -100% to 1000%, makes the cash flows worth {:,.2f}: they add up to {:,.2f}" money (vector-sum flows))))
    (ridders excess -100.0 1000.0 :tolerance 1e-12)))

; ---------------------------------------------------------------------------
; The Treasury curve, and the spread to it
; ---------------------------------------------------------------------------

(define (treasury-points curve)
  "The points of a Treasury curve, a list of (years yield), by the years: the curve is a list of (years yield), or a table with the columns years and yield. The yields are in
percent. An error that says what is wrong with it."
  (let ((points (if (and (table? curve) (not (null? curve)))
                    (begin
                      (dolist (name '("years" "yield"))
                        (unless (assoc name curve)
                          (error (format "a Treasury curve has the columns years and yield: this table has no column {}" name))))
                      (map list (vector->list (table-column curve "years")) (vector->list (table-column curve "yield"))))
                    curve)))
    (unless (and (list? points) (pair? points)
                 (every (lambda (point) (and (list? point) (= (length point) 2) (every number? point) (> (car point) 0))) points))
      (error (format "a Treasury curve is a list of (years yield), the years above 0 and the yield in percent, not {}" curve)))
    (let ((sorted (sort points car)))
      (dolist (years (map car sorted))
        (when (> (length (filter (lambda (other) (= other years)) (map car sorted))) 1)
          (error (format "a Treasury curve has two yields for {} years" years))))
      sorted)))

(define (deal-set-treasury-curve! deal curve)
  "Gives the deal the Treasury curve that spreads are to: a list of (years yield), such as '((2 4.1) (3 4.2)), or a table with the columns years and yield. The yields are
in percent. The spreads of the tranches are worked out again (the ones that were given stay as they were, and so do the prices of those that were given a price, whose spreads
change)."
  (deal-treasury-curve-set! deal (treasury-points curve))
  (deal-update-analytics! deal)
  (deal-refresh-views! deal 'prices 'info)
  (deal-treasury-curve deal))

(define (deal-clear-treasury-curve! deal)
  "Takes the Treasury curve away from the deal: there is no spread to work out, and a tranche that was priced by a spread has nothing to take it over."
  (deal-treasury-curve-set! deal '())
  (deal-update-analytics! deal)
  (deal-refresh-views! deal 'prices 'info))

(define (interpolate-points points years)
  "The yield at this many years, by a straight line between the two points that it is between, or the yield of the nearest point, beyond the ends."
  (let ((lower (car points)))
    (cond ((<= years (car lower)) (cadr lower))
          ((null? (cdr points)) (cadr lower))
          (else (let ((upper (cadr points)))
                  (if (<= years (car upper))
                      (+ (cadr lower) (* (- (cadr upper) (cadr lower)) (/ (- years (car lower)) (- (car upper) (car lower)))))
                      (interpolate-points (cdr points) years)))))))

(define (treasury-yield deal years)
  "The yield of the Treasury curve of the deal at this many years, in percent."
  (when (null? (deal-treasury-curve deal))
    (error "the deal has no Treasury curve, which a spread is to: give it one, (deal-set-treasury-curve! deal '((2 4.1) (3 4.2))), or in (info deal)"))
  (interpolate-points (deal-treasury-curve deal) years))

; ---------------------------------------------------------------------------
; What a tranche is paid, and what it is worth
; ---------------------------------------------------------------------------

(define (node-floats? node)
  "Whether the coupon of the node depends on the index."
  (let ((coupon (node-coupon node)))
    (and (not (null? coupon)) (not (vector? coupon)) (not (= (coupon 0.0) (coupon 0.05))))))

(define (deal-floating-without-index deal)
  "The name of a tranche of the deal that has a floating coupon, if the deal was never run with an index (so there is none to price it at), and otherwise #f."
  (and (null? (deal-index deal))
       (find-if (lambda (name) (node-floats? (get-node deal name))) (deal-tree-names deal (deal-root deal)))))

(define (deal-pricing-run deal)
  "A copy of the deal, run at its pricing speed, and at the index that it was last run with: what the tranches are paid, to price them from. It is kept, until the deal
changes. An error if it has no collateral, or a tranche floats and it has no index."
  (when (= (deal-periods deal) 0)
    (error "the deal has no collateral, so nothing is paid to be priced: give it some, (deal-set-collateral! deal '((100000000 6.5 6.0 360))), or in (collateral deal)"))
  (let ((floater (deal-floating-without-index deal)))
    (when floater
      (error (format "{} floats, and the deal has no index to price it at: run it with one first, (deal-run! deal :index 0.04)" floater))))
  (when (null? (deal-priced-run deal))                    ; (it is kept until the deal changes: the prices do not change what is paid)
    (deal-priced-run-set! deal (deal-run-copy deal (deal-pricing-flows deal) #t)))
  (deal-priced-run deal))

(define (tranche-cash-flows run name)
  "What the tranche called name is paid each month in the run of the deal, as a vector: its principal and its interest."
  (let ((node (get-node run name)))
    (+ (node-principal node) (node-interest node))))

(define (tranche-average-life run name)
  "The average life of the tranche called name in the run, in years, or '() if it is paid no principal."
  (let ((principal (node-principal (get-node run name))))
    (if (> (vector-sum principal) 0.0) (average-life principal) '())))

(define (analyze-tranche deal run name priced-by value)
  "What the tranche called name is, priced by one of price, yield and spread (the symbol priced-by) that is value: a list (price yield spread duration average-life dv01
money). With '() for priced-by, only the average life is worked out. The price is per 100 of balance, the yield in percent, the spread in basis points. Nothing is changed."
  (let ((node (get-node deal name))
        (life (tranche-average-life run name)))
    (if (null? priced-by)
        (list '() '() '() '() life '() '())
        (let ((balance (vector-ref (node-balance node) 0))
              (flows (tranche-cash-flows run name))
              (accrued (accrued-interest deal node)))
          (when (<= balance 0.0)
            (error (format "{} has no balance, so it has no price" name)))
          (when (and (eq? priced-by 'spread) (null? life))
            (error (format "{} is paid no principal, so it has no average life to take a spread at" name)))
          (let* ((months (months-from-settlement deal (vector-length flows)))
                 (money-of (lambda (price) (+ (* balance (/ price 100.0)) accrued)))
                 (yield (cond ((eq? priced-by 'price) (yield-of-money flows months (money-of value)))
                              ((eq? priced-by 'yield) value)
                              (else (+ (treasury-yield deal life) (/ value 100.0)))))
                 (money (if (eq? priced-by 'price) (money-of value) (present-value flows months yield)))
                 (price (if (eq? priced-by 'price) value (* 100.0 (/ (- money accrued) balance))))
                 (spread (cond ((eq? priced-by 'spread) value)
                               ((or (null? life) (null? (deal-treasury-curve deal))) '())
                               (else (* 100.0 (- yield (treasury-yield deal life)))))))
            (list price yield spread (modified-duration flows months yield) life
                  (- (present-value flows months yield) (present-value flows months (+ yield 0.01)))
                  money))))))

(define (analytics-assign! node result)
  "Puts the list that analyze-tranche gives, (price yield spread duration average-life dv01 money), in the slots of the node."
  (node-price-set! node (list-ref result 0))
  (node-yield-set! node (list-ref result 1))
  (node-spread-set! node (list-ref result 2))
  (node-duration-set! node (list-ref result 3))
  (node-average-life-set! node (list-ref result 4))
  (node-dv01-set! node (list-ref result 5))
  (node-money-set! node (list-ref result 6)))

(define (deal-track-prices! deal)
  "Makes the deal work the slots of its tranches out again whenever it changes (its collateral, its tranches, its pricing speed, its dates, its index): a view of the deal,
which is made once. It is made when a tranche is first priced."
  (unless (deal-tracks-prices deal)
    (deal-tracks-prices-set! deal #t)
    (deal-add-view! deal '(collateral tranches info index) (lambda () (deal-update-analytics! deal)))))

(define (priced-by-value node)
  "The one of price, yield and spread that the node was priced by: what was given."
  (let ((kind (node-priced-by node)))
    (cond ((eq? kind 'price) (node-price node))
          ((eq? kind 'yield) (node-yield node))
          ((eq? kind 'spread) (node-spread node))
          (else '()))))

(define (deal-update-analytics! deal)
  "Works out the slots of every tranche of the deal again, from the one of price, yield and spread that it was given (see the top of the file), and the average life of every
tranche: for after the deal has changed. A tranche that cannot be worked out (it has no Treasury curve to take a spread at, say) has its slots cleared, and a message of
what is wrong. Returns the list of messages, which is empty if all is well. A deal with no collateral has nothing to work out."
  (cond ((= (deal-periods deal) 0) '())
        ((deal-floating-without-index deal)
         (list (format "{} floats, and the deal has no index to price it at: run it with one first, (deal-run! deal :index 0.04)" (deal-floating-without-index deal))))
        (else
         (let ((run (deal-pricing-run deal))
               (problems '()))
           (dolist (name (deal-tree-names deal (deal-root deal)))
             (let ((node (get-node deal name)))
               (catch-error (analytics-assign! node (analyze-tranche deal run name (node-priced-by node) (priced-by-value node)))
                 (message)
                 (begin
                   (analytics-assign! node (analyze-tranche deal run name '() '()))
                   (set! problems (append problems (list (format "{}: {}" name message))))))))
           problems))))

; ---------------------------------------------------------------------------
; Giving a price, a yield or a spread
; ---------------------------------------------------------------------------

(define (priced-money deal name)
  "The money of the tranche called name, which is an error if it has not been priced."
  (let ((money (node-money (get-node deal name))))
    (when (null? money)
      (error (format "{} has no price yet, which the sums of money of its tranches need" name)))
    money))

(define (money-of-children deal name)
  "The money of the children of the tranche called name, added up."
  (let ((split (node-split (get-node deal name))))
    (when (null? split)
      (error (format "{} is not divided, so \"+\" has no tranches under it to add up" name)))
    (apply + (map (lambda (child) (priced-money deal child)) (split-children split)))))

(define (money-left-for deal name)
  "The money of the parent of the tranche called name, less that of its siblings (the other children of the parent's split)."
  (let ((parent (deal-parent-of deal name)))
    (unless parent
      (error (format "{} is the collateral: it has no parent, so \"?\" has nothing to take its money from" name)))
    (- (priced-money deal (node-name parent))
       (apply + (map (lambda (sibling) (priced-money deal sibling))
                     (filter (lambda (child) (not (equal? child name))) (split-children (node-split parent))))))))

(define (price-for-money deal name money)
  "The price, per 100 of balance, that the tranche called name has when the buyer pays this money in all."
  (let ((node (get-node deal name)))
    (when (<= (vector-ref (node-balance node) 0) 0.0)
      (error (format "{} has no balance, so it has no price" name)))
    (* 100.0 (/ (- money (accrued-interest deal node)) (vector-ref (node-balance node) 0)))))

(define (check-priceable deal name)
  "An error unless the tranche called name is in the tree of the deal."
  (unless (deal-in-tree? deal name)
    (error (format "{} is not in a tree of the deal: it has not been given a parent" name))))

(define (deal-price-tranche! deal name priced-by value)
  "Gives the tranche called name the price, yield or spread (priced-by, a symbol) that is value, and works out the rest of its slots. Nothing is changed if something is wrong.
The value of a price can also be the symbol + or ?, for the price that the money of its children, or of its parent less its siblings, says: see the top of the file."
  (check-priceable deal name)
  (let ((relation (cond ((member value '(+ "+")) '+) ((member value '(? "?")) '?) (else #f))))
    (when relation
      (let ((problems (deal-update-analytics! deal)))
        (unless (null? problems)
          (error (format "the other tranches are not all priced: {}" (car problems))))))
    (let* ((run (deal-pricing-run deal))
           (node (get-node deal name))
           (price (cond ((eq? relation '+) (price-for-money deal name (money-of-children deal name)))
                        ((eq? relation '?) (price-for-money deal name (money-left-for deal name)))
                        (else value)))
           (kind (if relation 'price priced-by)))
      (unless (number? price)
        (error (format "a {} is a number, not {}" priced-by value)))
      (analytics-assign! node (analyze-tranche deal run name kind price))
      (node-priced-by-set! node kind)
      (deal-track-prices! deal)
      (deal-refresh-views! deal 'prices)
      node)))

(define (deal-set-price! deal name price)
  "Gives the tranche called name a price (per 100 of balance, such as 101.5), and works out its yield, spread, duration, dv01 and money. The price can be \"+\", which is
the price that makes the money of the tranche what its children's add up to, or \"?\", the price that makes its money and its siblings' what its parent's is."
  (deal-price-tranche! deal name 'price price))

(define (deal-set-yield! deal name yield)
  "Gives the tranche called name a yield (in percent, such as 4.25), and works out its price, spread, duration, dv01 and money."
  (deal-price-tranche! deal name 'yield yield))

(define (deal-set-spread! deal name spread)
  "Gives the tranche called name a spread (in basis points, over the Treasury curve of the deal at its average life), and works out its yield, price, duration, dv01 and money."
  (deal-price-tranche! deal name 'spread spread))

(define (deal-clear-price! deal name)
  "Takes away the price of the tranche called name: it has no yield, spread, duration, dv01 or money (its average life stays)."
  (check-priceable deal name)
  (let ((node (get-node deal name)))
    (node-priced-by-set! node '())
    (dolist (clear (list node-price-set! node-yield-set! node-spread-set! node-duration-set! node-dv01-set! node-money-set!))
      (clear node '()))
    (deal-refresh-views! deal 'prices)
    node))

(define (deal-set-delay! deal name days)
  "Gives the tranche called name a delay: the days from the end of the accrual period of its interest to the payment date, which is 24 to begin with. It changes the
accrued interest, and so the money and the price, whichever of them was given."
  (unless (and (integer? days) (>= days 0))
    (error (format "the delay is a whole number of days, from 0, not {}" days)))
  (let ((node (get-node deal name))
        (was (node-delay (get-node deal name))))
    (node-delay-set! node days)
    (let ((problems (deal-update-analytics! deal)))
      (unless (null? problems)                            ; (the delay is not what the deal can be priced with: it stays as it was)
        (node-delay-set! node was)
        (deal-update-analytics! deal)
        (error (car problems))))
    (deal-refresh-views! deal 'prices)
    node))

; ---------------------------------------------------------------------------
; Looking at it
; ---------------------------------------------------------------------------

(define (deal-pricing-table deal)
  "A table of the slots that a price gives, a row for each tranche, each below its parent (as deal-outline has them): the tranche, its balance, the price, the yield (percent),
the spread (basis points), the duration and the average life (years), the dv01, the money and the delay (days). nan where it has none. The slots are as they were last
worked out (see deal-update-analytics!)."
  (let* ((names (map car (deal-outline-entries deal)))
         (slot-of (lambda (slot) (list->vector (map (lambda (name) (let ((value (slot (get-node deal name)))) (if (null? value) nan value))) names)))))
    (make-table "tranche" (list->vector names)
                "balance" (list->vector (map (lambda (name) (vector-ref (node-balance (get-node deal name)) 0)) names))
                "price" (slot-of node-price)
                "yield" (slot-of node-yield)
                "spread" (slot-of node-spread)
                "duration" (slot-of node-duration)
                "average life" (slot-of node-average-life)
                "dv01" (slot-of node-dv01)
                "money" (slot-of node-money)
                "delay" (list->vector (map (lambda (name) (node-delay (get-node deal name))) names)))))
