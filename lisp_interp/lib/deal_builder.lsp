; deal_builder.lsp
; ================
; Builds a deal by clicking, in a Jupyter notebook. A deal begins as the collateral alone, its cash flows, and is divided into
; tranches one split at a time:
;
;   (define deal (new-deal "Demo 2026-1" :first-payment (date 2026 11 25)
;                            :collateral '((100000000 6.5 6.0 360) (50000000 7.5 6.5 240 12))))
;   (bonds deal)
;
; The last line shows a grid with a row for each tranche of the deal (to begin with, one: the collateral). Click a tranche, and a
; panel opens under the grid with a tab (or an accordion section, with :style "accordion") for each kind of split that can divide
; it, and the fields that kind needs: the names and balances of the children of a sequential split, the two speeds of a PAC, the cap
; of a floater. Fill in a tab, and there are two buttons: one calculates the sizes of the tranches and shows them, and the other adds
; the tranches to the deal. The new tranches appear in the grid under the one that was divided, so that the rows are the tree of the
; deal, depth first (see deal-outline). Beside the split is a column, cash flows: click view in it, and the cash flows of that tranche are shown under the
; grid, year by year, from a run of the deal at the pricing speed (the deal is run first, if it has changed since the last run). (bonds deal) is the name
; for this view of a deal, with (collateral deal) and (info deal) (see deal_views.lsp): they can be shown at the same time, in different cells, and each
; shows what is changed in the others.
;
; Beside it is a chart of the balance of each tranche, month by month: a little area chart in the cell, all of them on one scale (that of the biggest balance, over the
; months of the longest tranche), so that a small tranche is a small chart and a short one a short one.
;
; Beyond the cash flows are the columns of what a price says about a tranche (see deal_pricing.lsp): price, yield, spread, oas, duration, effective duration, average life,
; dv01, money and delay (the oas and the effective duration are of the paths of rates, and are blank until they are run: see deal_paths.lsp). Type in one of price, yield, spread and oas, in the cell of a tranche (double-click it, or click it and type; a + or ? is typed after the double-click), and the others are worked out; a price can be +, which
; makes the money of the tranche that of its children, or ?, which makes the money of the tranche and its siblings that of their parent. Clear a cell to take the
; price away. The delay, in days, is typed too. The other columns are worked out: what is typed in them is put back.
;
; Click a tranche that has been divided, and the panel shows its split, with the fields as they were filled in. Change them, and
; the buttons calculate and make the change: the tranches of the split are worked out again, and so are those under them, to the
; leaves (see deal-replace-split!). A button under the panel takes the split away, with every tranche under it, after asking.
;
; Each tab is a split-form: the title of the tab, the label that the splits of its kind have (see split-label), a line that explains it,
; its fields (see widget-actions), the values to put in the fields when a tranche is chosen, a function that says what is in the fields
; for a split that is in the deal, and a function that makes a split-plan (see deal.lsp) from the answers. The forms are those of
; (standard-split-forms), one for each kind of split of deal.lsp; a form of your own, for a kind of split of your own, is added
; with :forms:
;
;   (deal-builder deal :forms (append (standard-split-forms) (list my-form)))

(require "deal.lsp")
(require "deal_pricing.lsp")
(require "widgets.lsp")

(defstruct split-form title label help fields defaults describe plan)
; title: the name of the tab; label: what split-label says of the splits that it makes; help: a line of HTML above the fields; fields:
; widget-actions fields, (name kind label default [options]); defaults: (defaults parent) is a list of (field-name . value) to put in the
; fields when the parent is chosen; describe: (describe deal split) is the list of (field-name . value) that makes the split, which is
; in the deal, or '() if there is no way to say (the fields keep their defaults); plan: (plan parent answers) is the split-plan for
; dividing the parent as the answers say, answers a list of (field-name . value), or an error that says what is wrong.

(defstruct deal-gui deal forms grid flows panel messages delete-row delete-button confirm-button cancel-button (chosen '()) (names '()))
; the deal being built, the split-forms, the widgets (the grid, the place under it for the cash flows of a tranche, the panel, ...), the name of
; the tranche chosen ('() if none), and the names of the tranches in the rows of the grid

; ---------------------------------------------------------------------------
; Reading what was typed
; ---------------------------------------------------------------------------

(define (form-answer answers name)
  "What is in the field called name."
  (cdr (assoc name answers)))

(define (form-name answers field what)
  "The name typed in a field, which is not blank."
  (let ((text (string-trim (form-answer answers field))))
    (when (equal? text "")
      (error (format "give the name of {}" what)))
    text))

(define (form-optional-name answers field)
  "The name typed in a field, or '() if it is blank."
  (let ((text (string-trim (form-answer answers field))))
    (if (equal? text "") '() text)))

(define (form-number text what)
  "The number written in text, which can have commas in it (60,000,000), or an error that says what it was to be."
  (let ((number (catch-error (string->number (string-replace text "," "")) (message) #f)))
    (unless number
      (error (format "{} is not a number, for {}" text what)))
    number))

(define (form-percent-to-decimal percent)
  "A rate that was typed in percent, as a decimal: 8.5 is 0.085."
  (/ percent 100.0))

(define (form-decimal-to-percent decimal)
  "A rate that is a decimal, in percent for a field: 0.085 is 8.5 (to six places, so that 7% is not 7.000000000000001)."
  (/ (round (* decimal 1e8)) 1e6))

(define (form-losses answers)
  "The loss rule that was chosen, as the symbol that the plans take."
  (string->symbol (form-answer answers "losses")))

(define (form-line line)
  "A line that describes a child, \"A1 60000000\" or \"Z 10000000 z\" for a Z bond, as (name balance z): the balance is #f if the line
leaves it out (\"A2\"), and z is #t for a Z bond."
  (let* ((words (string-split line))
         (is-z (lambda (word) (equal? (string-downcase word) "z")))
         (others (filter (lambda (word) (not (is-z word))) (cdr words))))
    (when (> (length others) 1)
      (error (format "a line is a name, a balance, and z if it is a Z bond, not \"{}\"" line)))
    (list (car words)
          (if (null? others) #f (form-number (car others) (format "the balance of {}" (car words))))
          (some is-z (cdr words)))))

(define (form-children text parent)
  "The children written in text, one to a line, as the list that sequential-plan takes, (name balance) or (name balance z). The last
line can leave its balance out: that child is what is left of the parent's."
  (let* ((lines (filter (lambda (line) (not (null? (string-split line)))) (string-split text "\n")))
         (entries (map form-line lines)))
    (when (null? entries)
      (error "write the tranches, one to a line: a name and a balance"))
    (let ((left-out (filter (lambda (entry) (not (cadr entry))) entries)))
      (unless (or (null? left-out) (and (= (length left-out) 1) (eq? (car left-out) (car (last entries)))))
        (error (format "{} has no balance: only the last tranche can leave out its balance, and have what is left" (car (car left-out))))))
    (let ((left (- (vector-ref (node-balance parent) 0) (apply + (map (lambda (entry) (if (cadr entry) (cadr entry) 0.0)) entries)))))
      (when (and (not (cadr (car (last entries)))) (<= left 0.0))
        (error (format "nothing is left of {} for {}" (node-name parent) (car (car (last entries))))))
      (map (lambda (entry)
             (let ((balance (if (cadr entry) (cadr entry) left)))
               (if (caddr entry) (list (car entry) balance 'z) (list (car entry) balance))))
           entries))))

(define (form-children-text deal split)
  "The children of the split written as form-children reads them: one to a line, with its balance, and z for a Z bond."
  (string-join (map (lambda (name)
                      (let ((node (get-node deal name)))
                        (format "{} {}{}" name (vector-ref (node-balance node) 0) (if (node-z-flag node) " z" ""))))
                    (split-children split))
               "\n"))

(define (form-lives text)
  "The children written in text, one to a line, as the list that average-life-plan takes: (name years), or (name) for the one that has no
average life, and is what is left."
  (let ((lines (filter (lambda (line) (not (null? (string-split line)))) (string-split text "\n"))))
    (when (null? lines)
      (error "write the tranches, one to a line: a name and the average life it is to have, in years, and for one of them no life"))
    (map (lambda (line)
           (let ((words (string-split line)))
             (when (> (length words) 2)
               (error (format "a line is a name and the average life, in years, not \"{}\"" line)))
             (if (= (length words) 1)
                 (list (car words))
                 (list (car words) (form-number (cadr words) (format "the average life of {}" (car words)))))))
         lines)))

(define (form-lives-text deal split)
  "The children of the split written as form-lives reads them: a name and its life, or only the name for the one that has none."
  (string-join (map (lambda (name life) (if (null? life) name (format "{} {}" name life)))
                    (split-children split) (average-life-split-lives split))
               "\n"))

(define (form-coupon-percent parent)
  "The coupon of the parent, in percent, or 0 if it has none: for the values to start the fields with."
  (if (null? (node-coupon parent)) 0.0 (* 100.0 (coupon-at (node-coupon parent) 0.0 0))))

; ---------------------------------------------------------------------------
; The forms
; ---------------------------------------------------------------------------

(define form-loss-rules (list "reverse" "forward" "pro-rata"))

(define (standard-split-forms)
  "The tabs of the panel of deal-builder, a split-form for each kind of split of deal.lsp."
  (list
    (make-split-form
      :title "Sequential"
      :label "sequential"
      :help "One tranche to a line: its name and its balance, and z after the balance if it is a Z bond. The last can leave out its balance, and be what is left. They are paid in order."
      :fields (list (list "tranches" 'textarea "Tranches" "")
                    (list "accretion" 'text "Accretion directed to" "")
                    (list "losses" 'dropdown "Losses" "reverse" form-loss-rules))
      :defaults (lambda (parent) (list (cons "tranches" (format "{}1\n{}2" (node-name parent) (node-name parent)))))
      :describe (lambda (deal split)
                  (list (cons "tranches" (form-children-text deal split))
                        (cons "accretion" (if (null? (sequential-split-accretion-to split)) "" (sequential-split-accretion-to split)))
                        (cons "losses" (format "{}" (split-loss-rule split)))))
      :plan (lambda (parent answers)
              (sequential-plan (form-children (form-answer answers "tranches") parent)
                               :accretion-to (form-optional-name answers "accretion")
                               :losses (form-losses answers))))
    (make-split-form
      :title "Average life"
      :label "sequential by average life"
      :help "One tranche to a line: its name and the average life, in years, that it is to have. One tranche, anywhere in the list, has no life: it is what is left. They are paid in order, and are made the sizes that have the lives, at the pricing speed."
      :fields (list (list "tranches" 'textarea "Tranches" "")
                    (list "losses" 'dropdown "Losses" "reverse" form-loss-rules))
      :defaults (lambda (parent) (list (cons "tranches" (format "{}1 2\n{}2 5\n{}3" (node-name parent) (node-name parent) (node-name parent)))))
      :describe (lambda (deal split)
                  (list (cons "tranches" (form-lives-text deal split))
                        (cons "losses" (format "{}" (split-loss-rule split)))))
      :plan (lambda (parent answers)
              (average-life-plan (form-lives (form-answer answers "tranches"))
                                 :losses (form-losses answers))))
    (make-split-form
      :title "Pro rata"
      :label "pro rata"
      :help "One tranche to a line: its name and its balance. The last can leave out its balance, and be what is left. They are paid in proportion to what each is owed."
      :fields (list (list "tranches" 'textarea "Tranches" "")
                    (list "losses" 'dropdown "Losses" "pro-rata" form-loss-rules))
      :defaults (lambda (parent) (list (cons "tranches" (format "{}1\n{}2" (node-name parent) (node-name parent)))))
      :describe (lambda (deal split)
                  (list (cons "tranches" (form-children-text deal split))
                        (cons "losses" (format "{}" (split-loss-rule split)))))
      :plan (lambda (parent answers)
              (pro-rata-plan (form-children (form-answer answers "tranches") parent)
                             :losses (form-losses answers))))
    (make-split-form
      :title "PAC"
      :label "PAC and companion"
      :help "A PAC is paid on a schedule, if the collateral prepays at any speed from the low one to the high one, and its companion is paid what is over. The sizes are worked out from the two speeds."
      :fields (list (list "pac" 'text "PAC" "")
                    (list "companion" 'text "Companion" "")
                    (list "low" 'number "Low speed (PSA)" 100)
                    (list "high" 'number "High speed (PSA)" 300)
                    (list "losses" 'dropdown "Losses" "reverse" form-loss-rules))
      :defaults (lambda (parent) (list (cons "pac" (format "{}-PAC" (node-name parent)))
                                       (cons "companion" (format "{}-COMP" (node-name parent)))))
      :describe (lambda (deal split)
                  (list (cons "pac" (car (split-children split)))
                        (cons "companion" (cadr (split-children split)))
                        (cons "low" (pac-split-low-psa split))
                        (cons "high" (pac-split-high-psa split))
                        (cons "losses" (format "{}" (split-loss-rule split)))))
      :plan (lambda (parent answers)
              (pac-plan (form-name answers "pac" "the PAC") (form-name answers "companion" "the companion")
                        (form-answer answers "low") (form-answer answers "high")
                        :losses (form-losses answers))))
    (make-split-form
      :title "Floater/inverse"
      :label "floater and inverse floater"
      :help "The floater pays the index plus the margin, up to the cap, and the inverse floater pays what makes the two together pay the parent's coupon. The sizes are worked out from the cap."
      :fields (list (list "floater" 'text "Floater" "")
                    (list "inverse" 'text "Inverse floater" "")
                    (list "cap" 'number "Cap %" 9.0)
                    (list "margin" 'number "Margin %" 0.5))
      :defaults (lambda (parent) (list (cons "floater" (format "{}-F" (node-name parent)))
                                       (cons "inverse" (format "{}-I" (node-name parent)))
                                       (cons "cap" (+ 3.0 (form-coupon-percent parent)))))
      :describe (lambda (deal split)
                  (list (cons "floater" (car (split-children split)))
                        (cons "inverse" (cadr (split-children split)))
                        (cons "cap" (form-decimal-to-percent (floater-inverse-split-cap split)))
                        (cons "margin" (form-decimal-to-percent (floater-inverse-split-margin split)))))
      :plan (lambda (parent answers)
              (floater-inverse-plan (form-name answers "floater" "the floater") (form-name answers "inverse" "the inverse floater")
                                    :cap (form-percent-to-decimal (form-answer answers "cap"))
                                    :margin (form-percent-to-decimal (form-answer answers "margin")))))
    (make-split-form
      :title "Premium/discount"
      :label "premium and discount"
      :help "The premium bond has a coupon above the parent's, and the discount bond one below it. The sizes are worked out so that, together, they pay the parent's coupon."
      :fields (list (list "premium" 'text "Premium bond" "")
                    (list "discount" 'text "Discount bond" "")
                    (list "premium-coupon" 'number "Premium coupon %" 8.0)
                    (list "discount-coupon" 'number "Discount coupon %" 4.0))
      :defaults (lambda (parent) (list (cons "premium" (format "{}-P" (node-name parent)))
                                       (cons "discount" (format "{}-D" (node-name parent)))
                                       (cons "premium-coupon" (+ 1.0 (form-coupon-percent parent)))
                                       (cons "discount-coupon" (- (form-coupon-percent parent) 1.0))))
      :describe (lambda (deal split)
                  (list (cons "premium" (car (split-children split)))
                        (cons "discount" (cadr (split-children split)))
                        (cons "premium-coupon" (form-decimal-to-percent (premium-discount-split-premium-coupon split)))
                        (cons "discount-coupon" (form-decimal-to-percent (premium-discount-split-discount-coupon split)))))
      :plan (lambda (parent answers)
              (premium-discount-plan (form-name answers "premium" "the premium bond") (form-name answers "discount" "the discount bond")
                                     :premium-coupon (form-percent-to-decimal (form-answer answers "premium-coupon"))
                                     :discount-coupon (form-percent-to-decimal (form-answer answers "discount-coupon")))))
    (make-split-form
      :title "IO/PO"
      :label "IO and PO"
      :help "Both are as big as the parent. The PO is paid all of its principal, and the IO is paid its interest, on a notional balance that follows the PO's."
      :fields (list (list "io" 'text "IO" "")
                    (list "po" 'text "PO" "")
                    (list "io-coupon" 'text "IO coupon % (blank for the parent's)" ""))
      :defaults (lambda (parent) (list (cons "io" (format "{}-IO" (node-name parent)))
                                       (cons "po" (format "{}-PO" (node-name parent)))))
      :describe (lambda (deal split)
                  (list (cons "io" (car (split-children split)))
                        (cons "po" (cadr (split-children split)))
                        (cons "io-coupon" (if (null? (io-po-split-io-coupon split))
                                              ""
                                              (format "{}" (form-decimal-to-percent (io-po-split-io-coupon split)))))))
      :plan (lambda (parent answers)
              (io-po-plan (form-name answers "io" "the IO") (form-name answers "po" "the PO")
                          :io-coupon (let ((text (string-trim (form-answer answers "io-coupon"))))
                                       (if (equal? text "")
                                           '()
                                           (form-percent-to-decimal (form-number text "the coupon of the IO")))))))))

; ---------------------------------------------------------------------------
; What the clicks and the buttons do
; ---------------------------------------------------------------------------

(define (without-traceback thunk)
  "Calls (thunk). If it raises an error, displays what is wrong, as a line, without the traceback that a callback would show: the user
who clicked a button has typed something that cannot be used, and the message says what."
  (catch-error (thunk)
    (message)
    (display (format "Error: {}\n" message))))

(define (deal-gui-say gui text)
  "Shows a line under the panel."
  (widget-capture (deal-gui-messages gui) (lambda () (display text))))

(define priced-columns '("price" "yield" "spread" "oas" "duration" "effective duration" "average life" "dv01" "money" "delay"))
(define typed-columns '("price" "yield" "spread" "oas" "delay"))
(define chart-column "balance chart")
(define chart-width 130)

(define (priced-column-texts deal names)
  "The columns of what a price says about each of the tranches called names, as text (blank for what a tranche has not got), as a table: so that a price can be typed
as + or ?, and a cell cleared."
  (let ((texts (lambda (slot spec)
                 (list->vector (map (lambda (name) (let ((value (slot (get-node deal name)))) (if (null? value) "" (format spec value)))) names)))))
    (make-table "price" (texts node-price "{:.4f}")
                "yield" (texts node-yield "{:.4f}")
                "spread" (texts node-spread "{:.1f}")
                "oas" (texts node-oas "{:.1f}")
                "duration" (texts node-duration "{:.3f}")
                "effective duration" (texts node-effective-duration "{:.3f}")
                "average life" (texts node-average-life "{:.3f}")
                "dv01" (texts node-dv01 "{:,.2f}")
                "money" (texts node-money "{:,.2f}")
                "delay" (texts node-delay "{}"))))

(define (balance-charts deal names)
  "A little chart of the balance of each of the tranches called names, month by month, as the HTML of an svg, for a column of the grid: from the deal run at its pricing speed
(see deal-pricing-run), all on one scale, that of the biggest balance, over the months of the longest, so that a small tranche is a small chart and a short one a short one. They
are blank if the deal has no collateral yet, or has a floating tranche and no index to run it with."
  (if (or (= (deal-periods deal) 0) (deal-floating-without-index deal))
      (list->vector (map (lambda (name) "") names))
      (let ((run (deal-pricing-run deal)))
        (sparklines (map (lambda (name) (node-balance (get-node run name))) names) :width (- chart-width 10) :height 16))))

(define (deal-gui-table gui)
  "The table for the grid: the outline of the deal, with a column beside the split to click to see the cash flows of a tranche, a chart of the balance of each, and the
columns of what a price says about each (see deal_pricing.lsp)."
  (let* ((deal (deal-gui-deal gui))
         (names (map car (deal-outline-entries deal))))
    (append (deal-outline deal)
            (list (cons "cash flows" (list->vector (map (lambda (name) "view") names)))
                  (cons chart-column (balance-charts deal names)))
            (priced-column-texts deal names))))

(define (deal-gui-update-prices! gui)
  "Works out the slots that a price gives, of every tranche, again (the deal may have changed), and says what could not be."
  (dolist (problem (deal-update-analytics! (deal-gui-deal gui)))
    (deal-gui-say gui (format "{}\n" problem))))

(define (deal-gui-refresh! gui)
  "Shows the tranches of the deal as they are now, and puts away what was being done to one of them: the deal has changed."
  (deal-gui-names-set! gui (map car (deal-outline-entries (deal-gui-deal gui))))
  (deal-gui-update-prices! gui)
  (grid-set-table! (deal-gui-grid gui) (deal-gui-table gui))
  (widget-clear (deal-gui-flows gui))
  (deal-gui-put-away! gui))

(define (deal-gui-type-number text what)
  "The number typed in a cell, for what it is of."
  (form-number (string-trim text) what))

(define (deal-gui-typed! gui column row text)
  "The user typed text in a cell of the grid, in column, in the row of a tranche. A price (a number, or + or ?), a yield, a spread or a delay is given to the tranche, and what is
worked out from it is shown; a cleared cell takes the price away. What is typed in any other column is put back, with what is wrong said."
  (let* ((deal (deal-gui-deal gui))
         (name (list-ref (deal-gui-names gui) row))
         (word (string-trim text))
         (done #f))
    (widget-clear (deal-gui-messages gui))
    (without-traceback
      (lambda ()
        (cond ((not (member column typed-columns))
               (error (format "{} is worked out, not typed: type a price, a yield, a spread, an oas or a delay" column)))
              ((equal? column "delay")
               (deal-set-delay! deal name (deal-gui-type-number word (format "the delay of {}" name))))
              ((equal? word "")
               (deal-clear-price! deal name))
              ((equal? column "price")
               (deal-set-price! deal name (if (member word '("+" "?")) word (deal-gui-type-number word (format "the price of {}" name)))))
              ((equal? column "yield")
               (deal-set-yield! deal name (deal-gui-type-number word (format "the yield of {}" name))))
              ((equal? column "oas")
               (deal-set-oas! deal name (deal-gui-type-number word (format "the oas of {}" name))))
              (else
               (deal-set-spread! deal name (deal-gui-type-number word (format "the spread of {}" name)))))
        (set! done #t)))
    (unless done                                        ; (the cell has what was typed in it, which is not what the deal has)
      (deal-gui-refresh! gui))))

(define (show-node-flows deal name)
  "Shows the cash flows of the tranche called name, from the last run of the deal: what it is, its average life, and a table with a row for the first month and
the end of each year."
  (let* ((node (get-node deal name))
         (principal (node-principal node)))
    (cond ((= (deal-periods deal) 0)
           (display (format "{} has no cash flows: the deal has no collateral yet. It is entered with (collateral deal).\n" name)))
          (else
           (display (format "{}: {:,.2f} to begin with{}, {}.\n" name (vector-ref (node-balance node) 0)
                            (if (> (vector-sum principal) 0.0) (format ", with an average life of {:.2f} years" (average-life principal)) "")
                            (if (speed-curve? (deal-ran deal)) (format "run at {}" (describe-speed (deal-ran deal))) "run")))
           (display-table (deal-flows-table deal name :months (deal-summary-months (deal-periods deal)))
                          '(("balance" ",.2f") ("principal" ",.2f") ("interest" ",.2f") ("accrual" ",.2f") ("loss" ",.2f") ("shortfall" ",.2f"))
                          :max-rows #f)))))

(define (deal-gui-show-flows! gui row)
  "The user clicked view for a tranche: its cash flows are shown under the grid. The deal is run first, at the pricing speed, if it has changed since the last run."
  (let ((deal (deal-gui-deal gui))
        (name (list-ref (deal-gui-names gui) row)))
    (widget-clear (deal-gui-flows gui))
    (unless (deal-ran deal)
      (deal-run! deal :index (deal-index deal)))
    (widget-capture (deal-gui-flows gui) (lambda () (show-node-flows deal name)))))

(define (deal-gui-show-delete! gui asking)
  "Shows the row under the panel with the button that takes away the split (asking is button) or the two that ask whether to (sure),
or none of them if asking is the empty list."
  (widget-visible (deal-gui-delete-row gui) (not (null? asking)))
  (widget-visible (deal-gui-delete-button gui) (eq? asking 'button))
  (widget-visible (deal-gui-confirm-button gui) (eq? asking 'sure))
  (widget-visible (deal-gui-cancel-button gui) (eq? asking 'sure)))

(define (deal-gui-form-for gui split)
  "The form of the tab for splits of the kind that split is, or #f if there is none."
  (find-if (lambda (form) (equal? (split-form-label form) (split-label split))) (deal-gui-forms gui)))

(define (deal-gui-put-away! gui)
  "Nothing is chosen: the panel and the button that takes away a split are put away."
  (deal-gui-chosen-set! gui '())
  (widget-visible (deal-gui-panel gui) #f)
  (deal-gui-show-delete! gui '()))

(define (deal-gui-offer-to-divide! gui node)
  "The chosen tranche is not divided: the panel has the defaults of each tab, to divide it."
  (let ((panel (deal-gui-panel gui)))
    (deal-gui-show-delete! gui '())
    (if (= (vector-ref (node-balance node) 0) 0.0)
        (begin (widget-visible panel #f)
               (deal-gui-say gui (format "{} has no balance, so it cannot be divided yet: the collateral is entered with (collateral deal).\n" (node-name node))))
        (begin
          (widget-actions-heading panel (format "Divide <b>{}</b>, which has a balance of {:,.2f}, by:" (node-name node) (vector-ref (node-balance node) 0)))
          (widget-actions-button-label! panel 1 "Add the tranches to the deal")
          (dolist (form (deal-gui-forms gui))
            (dolist (default ((split-form-defaults form) node))
              (widget-actions-set! panel (split-form-title form) (car default) (cdr default))))
          (widget-visible panel #t)))))

(define (deal-gui-offer-to-change! gui node)
  "The chosen tranche is divided: the panel shows its split, to change, and the button to take the split away."
  (let* ((panel (deal-gui-panel gui))
         (split (node-split node))
         (form (deal-gui-form-for gui split)))
    (deal-gui-show-delete! gui 'button)
    (cond (form
           (widget-actions-heading panel (format "<b>{}</b> is divided by a {} split into {}. Change it:"
                                                 (node-name node) (split-label split) (string-join (split-children split) ", ")))
           (widget-actions-button-label! panel 1 "Change the split")
           (unless (null? (split-form-describe form))
             (dolist (field ((split-form-describe form) (deal-gui-deal gui) split))
               (widget-actions-set! panel (split-form-title form) (car field) (cdr field))))
           (widget-actions-select panel (split-form-title form))
           (widget-visible panel #t))
          (else
           (widget-visible panel #f)
           (deal-gui-say gui (format "{} is divided by a {} split, which no tab of the panel is for, so it cannot be changed here, only taken away.\n"
                                     (node-name node) (split-label split)))))))

(define (deal-gui-choose! gui row)
  "The user clicked row of the grid: the tranche in it is chosen, to divide, or to change the split of."
  (let* ((name (list-ref (deal-gui-names gui) row))
         (node (get-node (deal-gui-deal gui) name)))
    (widget-clear (deal-gui-messages gui))
    (widget-actions-clear (deal-gui-panel gui))
    (deal-gui-chosen-set! gui name)
    (if (null? (node-split node))
        (deal-gui-offer-to-divide! gui node)
        (deal-gui-offer-to-change! gui node))))

(define (deal-gui-parent gui)
  "The node that was chosen."
  (when (null? (deal-gui-chosen gui))
    (error "click a tranche first, to say which one is to be divided"))
  (get-node (deal-gui-deal gui) (deal-gui-chosen gui)))

(define (deal-gui-plan gui title answers)
  "The plan for dividing the chosen tranche as the answers on the tab called title say."
  (let ((form (find-if (lambda (form) (equal? (split-form-title form) title)) (deal-gui-forms gui))))
    ((split-form-plan form) (deal-gui-parent gui) answers)))

(define (average-lives-of trial names)
  "The average life, in years, of each of the nodes of the trial deal, a list: found by running a copy of the deal, at the pricing speed.
nan for a node that is paid no principal, such as an interest-only bond."
  (let ((run (deal-run-copy trial (deal-pricing-flows trial) #t)))
    (map (lambda (name)
           (let ((principal (node-principal (get-node run name))))
             (if (> (vector-sum principal) 0.0) (average-life principal) nan)))
         names)))

(define (show-plan-effect deal trial parent-name)
  "Shows what the nodes below the parent are in the trial deal, which has a plan applied to it: their balances, and what each is of its
own parent's, their average lives, and what they are in the deal itself (a node that is new has no balance there)."
  (let* ((entries (cdr (deal-outline-below trial parent-name 0)))
         (names (map car entries))
         (balance-in (lambda (a-deal name) (vector-ref (node-balance (get-node a-deal name)) 0)))
         (was (map (lambda (name) (if (hash-table-ref (deal-nodes deal) name) (balance-in deal name) nan)) names))
         (share (map (lambda (name) (let ((parent (balance-in trial (node-name (deal-parent-of trial name)))))
                                      (if (= parent 0.0) 0.0 (/ (balance-in trial name) parent))))
                     names))
         (indented (map (lambda (entry) (string-append (format-value "" (format ">{}" (* 2 (- (cdr entry) 1)))) (car entry))) entries))
         (columns (append (list "tranche" (list->vector indented))
                          (if (some (lambda (value) (= value value)) was) (list "was" (list->vector was)) '())      ; (a node that is new has no balance, nan, which is not equal to itself)
                          (list "balance" (list->vector (map (lambda (name) (balance-in trial name)) names))
                                "share of its parent" (list->vector share)
                                "average life" (list->vector (average-lives-of trial names))))))
    (display (format "{} ({:,.2f}) divided by a {} split into:\n" parent-name (balance-in trial parent-name)
                     (split-label (node-split (get-node trial parent-name)))))
    (display-table (apply make-table columns) '(("was" ",.2f") ("balance" ",.2f") ("share of its parent" ".2%") ("average life" ".2f")))))

(define (deal-gui-show-sizes! gui title answers)
  "The button that shows the sizes: the plan is tried on a copy of the deal, so that what is wrong with it is said, and what the tranches
below the chosen one would be is shown."
  (let* ((parent (deal-gui-parent gui))
         (trial (deal-trial-of-plan (deal-gui-deal gui) (node-name parent) (deal-gui-plan gui title answers))))
    (show-plan-effect (deal-gui-deal gui) trial (node-name parent))))

(define (deal-gui-apply! gui title answers)
  "The button that adds the tranches to the deal, or changes the split: the grid shows them, and the panel is put away."
  (let* ((parent (deal-gui-parent gui))
         (plan (deal-gui-plan gui title answers))
         (adding (null? (node-split parent)))
         (children (string-join (split-children (split-plan-split plan)) ", ")))
    (if adding
        (deal-add-plan! (deal-gui-deal gui) (node-name parent) plan)
        (deal-replace-split! (deal-gui-deal gui) (node-name parent) plan))
    (deal-gui-say gui (if adding
                          (format "Added {} under {}, by a {} split. Click a tranche to divide it, or to change its split.\n"
                                  children (node-name parent) (split-label (split-plan-split plan)))
                          (format "Changed the split of {}: it is a {} split into {}, and what is under them is worked out again. Click a tranche to divide it, or to change its split.\n"
                                  (node-name parent) (split-label (split-plan-split plan)) children)))))

(define (deal-gui-ask-whether-to-delete! gui)
  "The button that takes away the split: says what would go, and asks."
  (let* ((parent (deal-gui-parent gui))
         (below (cdr (deal-tree-names (deal-gui-deal gui) (node-name parent)))))
    (deal-gui-say gui (format "Take away the split of {}, and {}, {}? That cannot be undone.\n"
                              (node-name parent)
                              (if (= (length below) 1) "the tranche under it" (format "the {} tranches under it" (length below)))
                              (string-join below ", ")))
    (deal-gui-show-delete! gui 'sure)))

(define (deal-gui-delete! gui)
  "The button that confirms: takes away the split and everything under it."
  (let* ((parent (deal-gui-parent gui))
         (gone (deal-delete-split! (deal-gui-deal gui) (node-name parent))))
    (widget-clear (deal-gui-messages gui))
    (deal-gui-say gui (format "Took away the split of {}, and {}. {} is not divided.\n" (node-name parent) (string-join gone ", ") (node-name parent)))))

(define (deal-gui-keep! gui)
  "The button that says not to take the split away."
  (widget-clear (deal-gui-messages gui))
  (deal-gui-show-delete! gui 'button)
  (deal-gui-say gui "Kept.\n"))

; ---------------------------------------------------------------------------
; The builder
; ---------------------------------------------------------------------------

(define (deal-gui-button label style function messages)
  "A button as wide as its label, which calls the function, whose errors it shows without a traceback, with what it displays under the panel."
  (let ((button (widget-button label (lambda () (without-traceback function)) :output messages :button-style style)))
    (widget-set! (widget-get button "layout") "width" "auto")
    button))

(define (deal-builder deal &key (forms (standard-split-forms)) (style "tabs"))
  "A grid of the tranches of the deal, to click one and divide it, or to change its split or take it away, and the panel to say how, and a column beside the
split to click to see the cash flows of a tranche: see the top of the file. :style is \"tabs\" or \"accordion\", for the panel. Returns the widget, which a cell
of a notebook shows; the deal is the one given, and is changed as tranches are added. It shows the changes made to the deal elsewhere, which another view
of it can make at the same time."
  (let* ((messages (widget-output))
         (flows (widget-output))
         (gui (make-deal-gui :deal deal :forms forms :messages messages :flows flows :names (map car (deal-outline-entries deal))))
         (priced (deal-gui-update-prices! gui))
         (grid (table-grid (deal-gui-table gui) :editable #t :selection-mode "cell"
                           :renderers (list (list chart-column (html-renderer :width chart-width)))))
         (panel (widget-actions (map (lambda (form) (append (list (split-form-title form) (split-form-help form)) (split-form-fields form)))
                                     forms)
                                :style style
                                :buttons (list (cons "Calculate the sizes"
                                                     (lambda (title answers) (without-traceback (lambda () (deal-gui-show-sizes! gui title answers)))))
                                               (cons "Add the tranches to the deal"
                                                     (lambda (title answers) (without-traceback (lambda () (deal-gui-apply! gui title answers))))))))
         (delete-button (deal-gui-button "Take away this split, and all under it" "danger" (lambda () (deal-gui-ask-whether-to-delete! gui)) messages))
         (confirm-button (deal-gui-button "Yes, take them away" "danger" (lambda () (deal-gui-delete! gui)) messages))
         (cancel-button (deal-gui-button "No, keep them" "" (lambda () (deal-gui-keep! gui)) messages))
         (delete-row (widget-row delete-button confirm-button cancel-button)))
    (deal-gui-grid-set! gui grid)
    (deal-gui-panel-set! gui panel)
    (deal-gui-delete-row-set! gui delete-row)
    (deal-gui-delete-button-set! gui delete-button)
    (deal-gui-confirm-button-set! gui confirm-button)
    (deal-gui-cancel-button-set! gui cancel-button)
    (grid-on-click grid
                   (lambda (column row value)
                     (without-traceback (lambda () (cond ((equal? column "cash flows") (deal-gui-show-flows! gui row))
                                                         ((or (member column priced-columns) (equal? column chart-column)) '())
                                                         (else (deal-gui-choose! gui row))))))
                   :output messages)
    (grid-on-edit grid (lambda (column row value) (deal-gui-typed! gui column row value)) :output messages)
    (deal-gui-put-away! gui)
    (deal-add-view! deal '(tranches prices) (lambda () (deal-gui-refresh! gui)))
    (widget-column grid flows panel delete-row messages)))

(define (bonds deal &key (forms (standard-split-forms)) (style "tabs"))
  "The grid of the tranches of the deal, to divide them, and to see their cash flows: see deal-builder, which this is."
  (deal-builder deal :forms forms :style style))
