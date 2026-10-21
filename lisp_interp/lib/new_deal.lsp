; new_deal.lsp
; ============
; Starts a new deal in a Jupyter notebook: the collateral, as a grid to type into, and the speed that it prepays at, and then the deal builder
; (see deal_builder.lsp) to divide it into tranches.
;
;   (define start (new-deal "Demo 2026-1" (date 2026 11 25) :variable 'deal))
;   start
;
; The first thing shown is a grid of the collateral, a row for each piece: the balance, the wac (the weighted average coupon, in percent),
; the wam (the months that are left) and the age (the months the loans have gone, 0 for new loans), which is what a PSA speed rises with. A
; row with no balance is left out. Under it is the pricing speed: a type (PSA, CPR or SMM) and a grid of pieces, each from, to and months, which
; is a speed that goes in a straight line from one to the other, and is `to` in the last of the months (see prepayment_speed.lsp); the months of the
; last piece are 0 for "from here on", and one row with both speeds the same is a single speed. **Show the cash flows** adds up the cash flows
; of the pieces and shows them, year by year; **Create the deal** makes the deal, with the collateral that they add up to, and puts the deal builder
; in the place of the grid.
;
; The deal is the value of (new-deal-deal start), and, with :variable 'deal, of the variable deal as soon as it is made.

(require "deal_builder.lsp")

(defstruct new-deal-gui name first-payment collateral-name variable forms pieces-grid speed-grid speed-type setup messages page (deal '()))
; the name of the deal, the date of the first payment, the name of the collateral, the variable to put the deal in ('() for none), the forms of the
; builder, the grids and the choice of type, the widgets that are put away when the deal is made, the place for what is shown, the widget
; that holds it all, and the deal when it is made

; ---------------------------------------------------------------------------
; What is typed
; ---------------------------------------------------------------------------

(define (new-deal-empty-pieces rows)
  "The table of the collateral with that many rows with nothing in them."
  (make-table "balance" (make-vector rows 0.0)
              "wac" (make-vector rows 0.0)
              "wam" (make-vector rows 0)
              "age" (make-vector rows 0)))

(define (new-deal-empty-speed rows)
  "The table of the pieces of the speed: the first is 100 for ever, and the others have nothing in them."
  (let ((from (make-vector rows 0.0))
        (to (make-vector rows 0.0)))
    (vector-set! from 0 100.0)
    (vector-set! to 0 100.0)
    (make-table "from" from "to" to "months" (make-vector rows 0))))

(define (grid-column-widths widths)
  "A hash table of column name to width in pixels, for a grid made with :column-widths: widths is a list of (name pixels)."
  (let ((table (make-hash-table)))
    (dolist (width widths)
      (hash-table-set! table (car width) (cadr width)))
    table))

(define (new-deal-pieces gui)
  "The pieces of collateral in the grid, as a list of (balance wac wam age): a row with no balance is left out."
  (let* ((table (grid-table (new-deal-gui-pieces-grid gui)))
         (balances (table-column table "balance"))
         (wacs (table-column table "wac"))
         (wams (table-column table "wam"))
         (ages (table-column table "age")))
    (loop for i from 0 below (vector-length balances)
          when (> (vector-ref balances i) 0.0)
          collect (list (vector-ref balances i) (vector-ref wacs i) (vector-ref wams i) (vector-ref ages i)))))

(define (new-deal-speed gui)
  "The speed that is typed: the type that is chosen, and the pieces in the grid. The first row is always a piece; of the others, one with
nothing in it is left out. A piece with 0 months is for the rest of the time."
  (let* ((table (grid-table (new-deal-gui-speed-grid gui)))
         (froms (table-column table "from"))
         (tos (table-column table "to"))
         (months (table-column table "months"))
         (pieces (loop for i from 0 below (vector-length froms)
                       when (or (= i 0) (not (and (= (vector-ref froms i) 0.0) (= (vector-ref tos i) 0.0) (= (vector-ref months i) 0))))
                       collect (if (= (vector-ref months i) 0)
                                   (list (vector-ref froms i) (vector-ref tos i))
                                   (list (vector-ref froms i) (vector-ref tos i) (vector-ref months i))))))
    (prepayment-speed (string->symbol (string-downcase (widget-get (new-deal-gui-speed-type gui) "value"))) pieces)))

; ---------------------------------------------------------------------------
; The buttons
; ---------------------------------------------------------------------------

(define (new-deal-years-rows months)
  "The months to show the cash flows of: the first, and the last of each year, and the last month."
  (let ((rows (append (list 1) (loop for month from 12 to months by 12 collect month))))
    (if (member months rows) rows (append rows (list months)))))

(define (show-collateral-flows pieces curve first-payment)
  "Shows the cash flows of the pieces of collateral at the speed, added up: the totals, and a row for the first month and the end of each year."
  (let* ((flows (project-pieces pieces curve))
         (principal (car flows))
         (interest (cadr flows))
         (balances (caddr flows))
         (months (vector-length principal))
         (speeds (speed-values curve months))
         (rows (new-deal-years-rows months))
         (used (collateral-pieces-in-use pieces))
         (total (apply + (map car used))))
    (display (format "{} pieces, {:,.2f}, with a wac of {:.4f}% and a wam of {} months, paying for {} months; its average life is {:.2f} years at {}.\n"
                     (length used) total (/ (apply + (map (lambda (piece) (* (car piece) (cadr piece))) used)) total)
                     (apply max (map caddr used)) months (average-life principal) (describe-speed curve)))
    (display-table (make-table "month" (list->vector rows)
                               "payment date" (list->vector (map (lambda (month) (date-add-months first-payment (- month 1))) rows))
                               "balance" (list->vector (map (lambda (month) (vector-ref balances (- month 1))) rows))
                               "principal" (list->vector (map (lambda (month) (vector-ref principal (- month 1))) rows))
                               "interest" (list->vector (map (lambda (month) (vector-ref interest (- month 1))) rows))
                               "speed" (list->vector (map (lambda (month) (vector-ref speeds (- month 1))) rows))
                               "coupon" (list->vector (map (lambda (month) (let ((balance (vector-ref balances (- month 1)))) (if (= balance 0.0) 0.0 (* 100.0 (/ (* 12.0 (vector-ref interest (- month 1))) balance))))) rows)))
                   '(("balance" ",.2f") ("principal" ",.2f") ("interest" ",.2f") ("speed" ".2f") ("coupon" ".4f")) :max-rows #f)))

(define (new-deal-show gui)
  "The button that shows the cash flows of the collateral that is typed, at the speed that is typed."
  (show-collateral-flows (new-deal-pieces gui) (new-deal-speed gui) (new-deal-gui-first-payment gui)))

(define (new-deal-create gui)
  "The button that makes the deal: its collateral is the pieces, added up at the speed, and the deal builder takes the place of the grids."
  (let* ((pieces (new-deal-pieces gui))
         (curve (new-deal-speed gui))
         (collateral (collateral-from-pieces (new-deal-gui-collateral-name gui) pieces curve))
         (deal (start-deal (new-deal-gui-name gui) collateral :first-payment (new-deal-gui-first-payment gui))))
    (new-deal-gui-deal-set! gui deal)
    (unless (null? (new-deal-gui-variable gui))
      (eval (list 'define (new-deal-gui-variable gui) (list 'quote deal))))
    (widget-visible (new-deal-gui-setup gui) #f)
    (widget-set! (new-deal-gui-page gui) "children"
                 (list (make-widget "HTML"
                                    :value (format "<b>{}</b>: {:,.2f} of collateral in {} piece{}, paying for {} months from {}. Click a tranche to divide it.{}"
                                                   (new-deal-gui-name gui) (deal-size deal) (length pieces) (if (= (length pieces) 1) "" "s")
                                                   (deal-periods deal) (new-deal-gui-first-payment gui)
                                                   (if (null? (new-deal-gui-variable gui)) "" (format " The deal is the value of <code>{}</code>." (new-deal-gui-variable gui)))))
                       (deal-builder deal :forms (new-deal-gui-forms gui))))))

; ---------------------------------------------------------------------------
; The page
; ---------------------------------------------------------------------------

(define (new-deal name first-payment &key (rows 8) (variable '()) (collateral-name "POOL") (forms (standard-split-forms)))
  "A page to start a deal: a grid for the pieces of collateral (:rows of them, to begin with), the pricing speed, and the buttons that show the cash
flows and make the deal. first-payment is the date of the first payment, which is month 1. :variable is a name, 'deal, that the deal is made the value
of when it is created. The deal builder is for the forms (see deal-builder). Returns the widget, which a cell of a notebook shows; the deal is
(new-deal-deal widget)."
  (unless (date? first-payment)
    (error (format "new-deal: the first payment is a date, such as (date 2026 11 25), not {}" first-payment)))
  (let* ((messages (widget-output))
         (pieces-grid (table-grid (new-deal-empty-pieces rows) :editable #t
                                  :column-widths (grid-column-widths '(("balance" 140) ("wac" 80) ("wam" 80) ("age" 80)))))
         (speed-grid (table-grid (new-deal-empty-speed 4) :editable #t
                                 :column-widths (grid-column-widths '(("from" 80) ("to" 80) ("months" 80)))))
         (speed-type (widget-dropdown (list "PSA" "CPR" "SMM") :value "PSA" :description "Speed is"))
         (gui (make-new-deal-gui :name name :first-payment first-payment :collateral-name collateral-name :variable variable :forms forms
                                 :pieces-grid pieces-grid :speed-grid speed-grid :speed-type speed-type :messages messages))
         (setup (widget-column
                  (make-widget "HTML" :value "<b>Collateral</b>: a row for each piece, with its balance, its wac (the weighted average coupon, in percent), its wam (the months that are left) and its age (the months the loans have gone, 0 if new). A row with no balance is left out. Double-click a cell to change it.")
                  pieces-grid
                  (make-widget "HTML" :value "<b>Pricing speed</b>: the type, and a row for each piece of the speed: it goes in a straight line from <i>from</i> to <i>to</i>, and is <i>to</i> in the last of its <i>months</i>; the last piece has 0 months, for the rest of the time. One row with the same speed twice is a single speed.")
                  speed-type
                  speed-grid
                  (widget-row (deal-gui-button "Show the cash flows" "" (lambda () (new-deal-show gui)) messages)
                              (deal-gui-button "Create the deal" "primary" (lambda () (new-deal-create gui)) messages))))
         (page (widget-column (make-widget "HTML" :value (format "<b>{}</b>: the first payment is {}" name first-payment))
                              setup
                              messages)))
    (new-deal-gui-setup-set! gui setup)
    (new-deal-gui-page-set! gui page)
    (widget-set-tag! page gui)
    page))

(define (new-deal-deal page)
  "The deal that the page made, or '() if the button has not been pressed."
  (let ((gui (widget-tag page)))
    (unless (new-deal-gui? gui)
      (error "new-deal-deal: expected the widget that new-deal made"))
    (new-deal-gui-deal gui)))
