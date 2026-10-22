; deal_views.lsp
; ==============
; Views of a deal in a Jupyter notebook: the collateral, as a grid to type in, and the dates, the pricing speed and the Treasury curve, as a few fields. Each is one
; cell of the notebook, and they can all be shown at once, with the grid of the bonds (see deal_builder.lsp), for the same deal: what is changed
; in one is shown in the others.
;
;   (define deal (new-deal "Demo 2026-1" :first-payment (date 2026 11 25)))
;   (info deal)            ; the name, the dates and the pricing speed
;   (collateral deal)      ; the pieces of collateral: balance, wac, pass-through coupon, wam, age
;   (bonds deal)           ; the tranches, to divide them, and to look at the cash flows of each
;
; A piece of collateral is a row of the grid: the balance, the wac (the weighted average coupon of the loans, in percent, which they are paid off at), the
; pass-through coupon (in percent, what the investors in the pool are paid: the wac less fees), the wam (the months that are left) and the age (the months
; the loans have gone, 0 for new loans), which is what a PSA speed rises with. A row with no balance is left out. **Show the cash flows** adds up the cash
; flows of the pieces, as they are in the grid, at the pricing speed, and shows them year by year; **Update the deal** gives the deal the collateral that is
; in the grid, which works out the cash flows again, and the sizes of the tranches under it. The pricing speed is a type (PSA, CPR, SMM or MODEL) and a grid of
; pieces, each from, to and months, which is a speed that goes in a straight line from one to the other, and is `to` in the last of the months (see
; prepayment_speed.lsp); the last piece has 0 months, for the rest of the time, and one row with the same speed twice is a single speed. MODEL is a share of the
; prepayment model, which is told the growth of home prices and the mortgage spread in the two fields under the speed (see deal_paths.lsp). The Treasury curve is a grid
; of points, the years and the yield in percent, that the spreads of the tranches are over (see deal_pricing.lsp).

(require "deal_builder.lsp")

; ---------------------------------------------------------------------------
; Small helpers
; ---------------------------------------------------------------------------

(define (grid-column-widths widths)
  "A hash table of column name to width in pixels, for a grid made with :column-widths: widths is a list of (name pixels)."
  (let ((table (make-hash-table)))
    (dolist (width widths)
      (hash-table-set! table (car width) (cadr width)))
    table))

(define (date-from-text text what)
  "The date written in a field, YYYY-MM-DD, or '() if it is blank. An error that says which field, if it is not a date."
  (let ((trimmed (string-trim text)))
    (if (equal? trimmed "")
        '()
        (catch-error (string->date trimmed)
          (message)
          (error (format "{} is a date written YYYY-MM-DD, such as 2026-11-25, not \"{}\"" what trimmed))))))

(define (date-to-text date)
  "A date for a field: YYYY-MM-DD, or nothing for no date."
  (if (null? date) "" (format "{}" date)))

(define (show-collateral-flows deal pieces curve)
  "Shows the cash flows of the pieces of collateral at the speed, added up, as the deal works them out (see deal-project-pieces): the totals, and a row for the first
month and the end of each year, with the interest that the investors are paid, and the rate that it is of the balance (the pass-through coupon) beside the rate that the
loans pay (the wac), month by month: they change as the pieces with the higher rates pay off. The dates are from the deal's first payment, if it has one."
  (let* ((first-payment (deal-first-payment deal))
         (flows (deal-project-pieces deal pieces curve))
         (principal (car flows))
         (interest (cadr flows))
         (balances (caddr flows))
         (losses (list-ref flows 4))
         (lost (vector-sum losses))
         (months (vector-length principal))
         (speeds (speed-values curve months))
         (wacs (pool-coupons (cadddr flows) balances))
         (coupons (pool-coupons interest balances))
         (rows (deal-summary-months months))
         (used (collateral-pieces-in-use pieces))
         (total (apply + (map collateral-piece-balance used)))
         (average (lambda (field) (/ (apply + (map (lambda (piece) (* (collateral-piece-balance piece) (field piece))) used)) total)))
         (at (lambda (vector) (list->vector (map (lambda (month) (vector-ref vector (- month 1))) rows)))))
    (display (format "{} pieces, {:,.2f}, with a wac of {:.4f}%, a pass-through coupon of {:.4f}% and a wam of {} months, paying for {} months; its average life is {:.2f} years at {}{}.\n"
                     (length used) total (average collateral-piece-wac) (average collateral-piece-coupon) (apply max (map collateral-piece-wam used)) months (average-life principal)
                     (describe-speed curve)
                     (if (> lost 0.0)
                         (format ", and it loses {:,.2f} ({:.2f}%) when the homes of the loans that default ({}% of the default model) are sold" lost (* 100.0 (/ lost total)) (deal-defaults deal))
                         "")))
    (display-table (apply make-table
                          (append (list "month" (list->vector rows))
                                  (if (null? first-payment)
                                      '()
                                      (list "payment date" (list->vector (map (lambda (month) (date-add-months first-payment (- month 1))) rows))))
                                  (list "balance" (at balances)
                                        "principal" (at principal)
                                        "interest" (at interest)
                                        "speed" (at speeds)
                                        "wac" (at (vector-map (lambda (rate) (* 100.0 rate)) wacs))
                                        "coupon" (at (vector-map (lambda (rate) (* 100.0 rate)) coupons)))
                                  (if (> lost 0.0) (list "loss" (at losses)) '())))
                   '(("balance" ",.2f") ("principal" ",.2f") ("interest" ",.2f") ("speed" ".2f") ("wac" ".4f") ("coupon" ".4f") ("loss" ",.2f")) :max-rows #f)))

; ---------------------------------------------------------------------------
; The collateral
; ---------------------------------------------------------------------------

(defstruct collateral-gui deal grid messages page (rows 8))
; the deal, the grid of the pieces, the place for what is shown, the widget that holds them, and how many rows the grid has at least

(define (collateral-gui-table gui)
  "The table for the grid: the pieces of the collateral of the deal, and rows with nothing in them, so that there are at least as many as the gui is to have."
  (let* ((pieces (collateral-table-pieces (deal-collateral (collateral-gui-deal gui))))
         (blanks (max 3 (- (collateral-gui-rows gui) (length pieces)))))
    (collateral-table (append pieces (loop repeat blanks collect (list 0.0 0.0 0.0 0 0))))))

(define (collateral-gui-pieces gui)
  "The pieces of collateral in the grid: a row with no balance is left out."
  (collateral-table-pieces (grid-table (collateral-gui-grid gui))))

(define (collateral-gui-show gui)
  "The button that shows the cash flows of the collateral in the grid, at the pricing speed of the deal."
  (let ((deal (collateral-gui-deal gui)))
    (show-collateral-flows deal (collateral-gui-pieces gui) (deal-pricing-speed deal))))

(define (collateral-gui-update gui)
  "The button that gives the deal the collateral in the grid: its cash flows are worked out again, and so are the sizes of the tranches under it."
  (let ((deal (collateral-gui-deal gui))
        (pieces (collateral-gui-pieces gui)))
    (deal-set-collateral! deal pieces)
    (widget-clear (collateral-gui-messages gui))
    (widget-capture (collateral-gui-messages gui)
                    (lambda ()
                      (display (format "Updated the collateral of {}: {:,.2f} in {} piece{}, paying for {} months.\n"
                                       (deal-name deal) (deal-size deal) (length pieces) (if (= (length pieces) 1) "" "s") (deal-periods deal)))))))

(define (collateral deal &key (rows 8))
  "A grid of the collateral of the deal, to change it, and buttons to show its cash flows and to give the deal what is typed: see the top of the file. The
:rows is how many rows the grid has at least. Returns the widget, which a cell of a notebook shows. It shows the changes
made to the collateral of the deal elsewhere."
  (let* ((messages (widget-output))
         (gui (make-collateral-gui :deal deal :messages messages :rows rows))
         (grid (table-grid (collateral-gui-table gui) :editable #t
                           :column-widths (grid-column-widths (append '(("balance" 140) ("wac" 80) ("coupon" 80) ("wam" 80) ("age" 80))
                                                                      (map (lambda (characteristic) (list (car characteristic) 120)) collateral-characteristics)))))
         (page (widget-column
                 (make-widget "HTML" :value (format "<b>Collateral</b> of {}: a row for each piece, with its balance, its wac (the weighted average coupon of the loans, in percent), its pass-through coupon (in percent, what the investors are paid: the wac less the fees taken out, so no more than the wac), its wam (the months that are left) and its age (the months the loans have gone, 0 if new). The columns after those say what the loans are like, for a prepayment model: the balance of a loan, the credit score, the loan-to-value now (percent), the sato (the wac less the market rate when the loans were made, percent), the burnout (months with a reason to refinance that went by), and the shares of the balance (0 to 1) on investment properties and second homes, and that were cash-out and other refinances; a blank cell is not known. A row with no balance is left out. Double-click a cell to change it." (deal-name deal)))
                 grid
                 (widget-row (deal-gui-button "Show the cash flows" "" (lambda () (collateral-gui-show gui)) messages)
                             (deal-gui-button "Update the deal" "primary" (lambda () (collateral-gui-update gui)) messages))
                 messages)))
    (collateral-gui-grid-set! gui grid)
    (collateral-gui-page-set! gui page)
    (deal-add-view! deal '(collateral) (lambda () (grid-set-table! (collateral-gui-grid gui) (collateral-gui-table gui))))
    page))

; ---------------------------------------------------------------------------
; The dates and the pricing speed
; ---------------------------------------------------------------------------

(defstruct info-gui deal name closing first-payment speed-type speed-grid home-prices mortgage-spread defaults liquidation-lag curve-grid messages)
; the deal, the fields and the grids (of the pieces of the pricing speed, and of the points of the Treasury curve), and the place for what is shown

(define (info-curve-table points)
  "The table of the points of a Treasury curve, for the grid: years and yield (percent), with rows with nothing in them to make six."
  (let ((blanks (max 0 (- 6 (length points)))))
    (make-table "years" (list->vector (append (map car points) (loop repeat blanks collect 0.0)))
                "yield" (list->vector (append (map cadr points) (loop repeat blanks collect 0.0))))))

(define (info-curve-from-grid table)
  "The points, (years yield), that a table of years and yield says: a row with nothing in it is left out."
  (let ((years (table-column table "years"))
        (yields (table-column table "yield")))
    (loop for i from 0 below (vector-length years)
          unless (and (= (vector-ref years i) 0.0) (= (vector-ref yields i) 0.0))
          collect (list (vector-ref years i) (vector-ref yields i)))))

(define (info-speed-table curve)
  "The table of the pieces of a speed, for the grid: from, to and months (0 for the rest of the time), with rows with nothing in them to make four."
  (let* ((pieces (speed-curve-pieces curve))
         (blanks (max 0 (- 4 (length pieces)))))
    (make-table "from" (list->vector (append (map car pieces) (loop repeat blanks collect 0.0)))
                "to" (list->vector (append (map cadr pieces) (loop repeat blanks collect 0.0)))
                "months" (list->vector (append (map (lambda (piece) (if (null? (caddr piece)) 0 (caddr piece))) pieces)
                                               (loop repeat blanks collect 0))))))

(define (info-speed-from-grid type table)
  "The speed that the type, \"PSA\", \"CPR\", \"SMM\" or \"MODEL\", and a table of pieces, from, to and months, say: the first row is always a piece, and of the others one with
nothing in it is left out; a piece with 0 months is for the rest of the time."
  (let* ((froms (table-column table "from"))
         (tos (table-column table "to"))
         (months (table-column table "months"))
         (pieces (loop for i from 0 below (vector-length froms)
                       when (or (= i 0) (not (and (= (vector-ref froms i) 0.0) (= (vector-ref tos i) 0.0) (= (vector-ref months i) 0))))
                       collect (if (= (vector-ref months i) 0)
                                   (list (vector-ref froms i) (vector-ref tos i))
                                   (list (vector-ref froms i) (vector-ref tos i) (vector-ref months i))))))
    (prepayment-speed (string->symbol (string-downcase type)) pieces)))

(define (info-gui-show gui)
  "Puts what the deal has in the fields."
  (let ((deal (info-gui-deal gui)))
    (widget-set! (info-gui-name gui) "value" (deal-name deal))
    (widget-set! (info-gui-closing gui) "value" (date-to-text (deal-closing-date deal)))
    (widget-set! (info-gui-first-payment gui) "value" (date-to-text (deal-first-payment deal)))
    (widget-set! (info-gui-speed-type gui) "value" (string-upcase (format "{}" (speed-curve-type (deal-pricing-speed deal)))))
    (grid-set-table! (info-gui-speed-grid gui) (info-speed-table (deal-pricing-speed deal)))
    (widget-set! (info-gui-home-prices gui) "value" (+ 0.0 (deal-home-price-growth deal)))
    (widget-set! (info-gui-mortgage-spread gui) "value" (+ 0.0 (deal-mortgage-spread deal)))
    (widget-set! (info-gui-defaults gui) "value" (+ 0.0 (deal-defaults deal)))
    (widget-set! (info-gui-liquidation-lag gui) "value" (deal-liquidation-lag deal))
    (grid-set-table! (info-gui-curve-grid gui) (info-curve-table (deal-treasury-curve deal)))))

(define (info-gui-latest-curve gui)
  "The button that gets the Treasury's most recent par yield curve (latest-treasury-points, which reads the Treasury's own file) and puts it in the grid of the curve: the
deal is given it by the Update button, with what else is typed."
  (let* ((found (latest-treasury-points))
         (points (cadr found)))
    (grid-set-table! (info-gui-curve-grid gui) (info-curve-table points))
    (widget-clear (info-gui-messages gui))
    (widget-capture (info-gui-messages gui)
                    (lambda () (display (format "The Treasury's par yield curve of {}, {} points, is in the grid: Update the deal gives it to {}.\n"
                                                (car found) (length points) (deal-name (info-gui-deal gui))))))))

(define (info-gui-update gui)
  "The button that gives the deal the name, the dates, the pricing speed, what its models are told, its defaults, and the Treasury curve that are typed. A speed of the
model, and defaults, need the curve, so it is given the curve first; otherwise the speed and the defaults are given first, so that the curve can then be taken away.
Nothing is changed if something is wrong."
  (let* ((deal (info-gui-deal gui))
         (closing (date-from-text (widget-get (info-gui-closing gui) "value") "the closing date"))
         (first-payment (date-from-text (widget-get (info-gui-first-payment gui) "value") "the first payment"))
         (name (string-trim (widget-get (info-gui-name gui) "value")))
         (speed (info-speed-from-grid (widget-get (info-gui-speed-type gui) "value") (grid-table (info-gui-speed-grid gui))))
         (home-prices (widget-get (info-gui-home-prices gui) "value"))
         (mortgage-spread (widget-get (info-gui-mortgage-spread gui) "value"))
         (defaults (widget-get (info-gui-defaults gui) "value"))
         (liquidation-lag (widget-get (info-gui-liquidation-lag gui) "value"))
         (curve (info-curve-from-grid (grid-table (info-gui-curve-grid gui))))
         (set-curve (lambda () (if (null? curve) (deal-clear-treasury-curve! deal) (deal-set-treasury-curve! deal curve))))
         (set-model-settings (lambda ()
                               (unless (= home-prices (deal-home-price-growth deal)) (deal-set-home-price-growth! deal home-prices))
                               (unless (= mortgage-spread (deal-mortgage-spread deal)) (deal-set-mortgage-spread! deal mortgage-spread))
                               (unless (= liquidation-lag (deal-liquidation-lag deal)) (deal-set-liquidation-lag! deal liquidation-lag))
                               (unless (= defaults (deal-defaults deal)) (deal-set-defaults! deal defaults)))))
    (when (equal? name "")
      (error "the deal needs a name"))
    (treasury-points (if (null? curve) '((1 0)) curve))                  ; (an error now, before anything is changed, if the curve is wrong)
    (deal-set-closing-date! deal closing)
    (deal-set-first-payment! deal first-payment)
    (deal-name-set! deal name)
    (if (or (model-speed? speed) (> defaults 0))
        (begin (set-curve) (set-model-settings) (deal-set-pricing-speed! deal speed))
        (begin (deal-set-pricing-speed! deal speed) (set-model-settings) (set-curve)))
    (widget-clear (info-gui-messages gui))
    (widget-capture (info-gui-messages gui)
                    (lambda () (display (format "Updated {}: pricing speed {}{}{}{}.\n" name (describe-speed speed)
                                                (if (or (model-speed? speed) (> defaults 0))
                                                    (format " (home prices {}% a year, mortgage rate {}% over the 10-year Treasury)" home-prices mortgage-spread)
                                                    "")
                                                (if (> defaults 0)
                                                    (format ", defaults {}% of the default model, sold {} months later" defaults liquidation-lag)
                                                    "")
                                                (cond ((null? curve) ", no Treasury curve")
                                                      ((= (length curve) 1) ", Treasury curve of 1 point")
                                                      (else (format ", Treasury curve of {} points" (length curve))))))))))

(define (info deal)
  "A few fields for the name of the deal, the date of its closing, the date of its first payment, which is month 1, and its pricing speed, which is what the cash flows
of the collateral are, and what the sizes of tranches that depend on them are worked out at, and a button to give the deal what is typed: see the top of the file.
Returns the widget, which a cell of a notebook shows. It shows the changes made to the deal elsewhere."
  (let* ((messages (widget-output))
         (name (make-widget "Text" :description "Name" :style (widget--style) :layout (make-widget "Layout" :width "28em")))
         (closing (make-widget "Text" :description "Closing date" :placeholder "YYYY-MM-DD" :style (widget--style)))
         (first-payment (make-widget "Text" :description "First payment" :placeholder "YYYY-MM-DD" :style (widget--style)))
         (speed-type (make-widget "Dropdown" :options (list "PSA" "CPR" "SMM" "MODEL") :description "Pricing speed" :style (widget--style)))
         (speed-grid (table-grid (info-speed-table (deal-pricing-speed deal)) :editable #t
                                 :column-widths (grid-column-widths '(("from" 80) ("to" 80) ("months" 80)))))
         (home-prices (make-widget "FloatText" :description "Home prices, % a year" :style (widget--style)))
         (mortgage-spread (make-widget "FloatText" :description "Mortgage rate over the 10-year, %" :style (widget--style)))
         (defaults (make-widget "FloatText" :description "Defaults, % of the model (0: none)" :style (widget--style)))
         (liquidation-lag (make-widget "IntText" :description "Months from a default to the sale" :style (widget--style)))
         (curve-grid (table-grid (info-curve-table (deal-treasury-curve deal)) :editable #t
                                 :column-widths (grid-column-widths '(("years" 80) ("yield" 80)))))
         (gui (make-info-gui :deal deal :name name :closing closing :first-payment first-payment :speed-type speed-type :speed-grid speed-grid
                             :home-prices home-prices :mortgage-spread mortgage-spread :defaults defaults :liquidation-lag liquidation-lag
                             :curve-grid curve-grid :messages messages))
         (page (widget-column
                 (make-widget "HTML" :value "<b>The deal</b>: its name, its dates, and the pricing speed: a type, and a row for each piece of the speed, which goes in a straight line from <i>from</i> to <i>to</i> and is <i>to</i> in the last of its <i>months</i>; the last piece has 0 months, for the rest of the time. One row with the same speed twice is a single speed. MODEL is a share of the prepayment model fitted to Freddie Mac's loans, which looks at rates: 100 is the model, and 105 is 105% of it. It needs the Treasury curve, which the rates are read forward from (and on each path of rates, for the OAS), and is told how much home prices grow, and how far the rate of a new mortgage is above the 10-year Treasury yield. The defaults are a share, in percent, of the default model fitted to Freddie Mac's loans (0 for none): a loan that defaults is sold the months after it that are typed, and what is lost, by the severity model, writes the tranches down. The default model needs the curve too.")
                 name closing first-payment speed-type speed-grid home-prices mortgage-spread defaults liquidation-lag
                 (make-widget "HTML" :value "<b>The Treasury curve</b>, that a spread is over: a row for each point, the years to its maturity and its yield in percent, in any order (a row with nothing in it is left out). The yield at an average life between two points is on the straight line between them. <i>Get the latest curve</i> fills it with the Treasury's most recent par yield curve (from its own website); <i>Update the deal</i> then gives it to the deal.")
                 curve-grid
                 (widget-row (deal-gui-button "Get the latest curve" "" (lambda () (info-gui-latest-curve gui)) messages)
                             (deal-gui-button "Update the deal" "primary" (lambda () (info-gui-update gui)) messages))
                 messages)))
    (info-gui-show gui)
    (deal-add-view! deal '(info) (lambda () (info-gui-show gui)))
    page))
