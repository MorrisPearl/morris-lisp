; deal_save.lsp
; =============
; Saves a deal in a file, and makes it again from the file:
;
;   (save-deal deal "demo.deal")
;   (define deal (load-deal "demo.deal"))
;
; What is saved is what the deal is made from, as data: its name, dates and settings, its collateral (the table of its pieces), its
; pricing speed and Treasury curve, each split with the tranches that it divides its parent into, and the price, yield, spread or OAS
; that each tranche was given, and its delay. The rest is worked out again from those when the deal is loaded, by the functions that
; worked it out when the deal was built: the cash flows of the collateral, the sizes that a split works out (a PAC's, a floater's), and
; the coupons of the tranches.
;
; Functions are not saved as their text. A function's text is its code, but not the values that the code refers to: the coupon of a
; tranche at 6%, (constant-coupon 0.06), prints as (lambda (index) rate), and rate is 0.06 only where the function was made: read back
; and called, it is the error "unbound symbol: rate". A builtin has no text at all (#<builtin car>). So the functions of a deal are made
; again, by the code that made them, from data that can be saved. The two that a person can give a deal, a prepayment model and an index
; function (see deal_pricing.lsp), are not saved, and save-deal says so.
;
; The file is a deal-file struct, written as it prints, #S(deal-file :name "Demo" ...), with a slot to a line. load-deal reads it with
; read-from-string, which reads data and runs nothing, so a file can only describe a deal, not do anything else. A split is written as the
; struct that it is, #S(sequential-split :children ("A" "B") ...), so a kind of split of your own is saved too, and is loaded once its
; defstruct and methods have been loaded.

(require "deal.lsp")
(require "deal_pricing.lsp")
(require "deal_paths.lsp")              ; (the rate-model struct, which a deal may have)

(define deal-save-format-version 1)     ; (written in the file, so that a later way of saving can tell an earlier file; not called
                                        ; deal-file-version, which is the accessor of the version slot of a deal-file)

(defstruct deal-file version name first-payment closing-date collateral-name shortfalls pricing-speed treasury-curve home-price-growth
  mortgage-spread defaults liquidation-lag rate-model index collateral other-tranches splits prices names)
; version: deal-save-format-version when it was saved. The dates are text, "2026-11-25", or '() (a date is written 2026-11-25, which reads back as
; a symbol). collateral: the table of the pieces of collateral. other-tranches: the tranches that no split pays (that have not been given a
; parent), as the arguments of deal-add-tranche!, (name balance :z z :notional notional :follows follows). splits: (parent tranches split)
; for each split, the parents in the order of the tree, each before the ones under it, which is the order they are added in again; tranches
; are the arguments of deal-add-tranche! for the children, as a split-plan has them. prices: (name :priced-by kind :value value :delay days)
; for each node, kind one of price, yield, spread and oas, or '() if it was not given one. names: the names of the nodes in the order they were
; added, which deal-names, deal-leaves and the tables of cash flows keep (the splits are added again in the order of the tree, which may not be it).

(define deal-save--one-to-a-line '(collateral other-tranches splits prices))   ; (the slots whose elements are written a line each)

; ---------------------------------------------------------------------------
; Saving
; ---------------------------------------------------------------------------

(define (deal-save--date-text date)
  "A date as the text \"2026-11-25\", or '() for none."
  (if (null? date) '() (date->string date)))

(define (deal-save--tranche-arguments deal name)
  "The arguments of deal-add-tranche! that make the tranche called name again as it is: (name balance :z z :notional notional :follows follows)."
  (let ((node (get-node deal name)))
    (list name (vector-ref (node-balance node) 0) :z (node-z-flag node) :notional (node-notional-flag node) :follows (node-follows node))))

(define (deal-save--tops deal)
  "The names of the nodes that no split pays, in the order they were added: the collateral first, and then any tranche that has not been given a parent."
  (let ((children (deal--children-names deal)))
    (filter (lambda (name) (not (member name children))) (deal-names deal))))

(define (deal-save--splits deal)
  "Each split of the deal, as (parent tranches split): the parents in the order of their trees, each before the ones under it."
  (append-map (lambda (name)
                (let ((split (node-split (get-node deal name))))
                  (if (null? split)
                      '()
                      (list (list name (map (lambda (child) (deal-save--tranche-arguments deal child)) (split-children split)) split)))))
              (append-map (lambda (top) (deal--tree-names deal top)) (deal-save--tops deal))))

(define (deal-save--price-entry deal name)
  "What the node called name was given, for its price: (name :priced-by kind :value value :delay days)."
  (let ((node (get-node deal name)))
    (list name :priced-by (node-priced-by node) :value (deal-pricing--priced-by-value node) :delay (node-delay node))))

(define (deal-save--slots deal)
  "The slots of the deal-file that the deal is saved as, a list of (slot-name . value), in the order of the defstruct."
  (list (cons 'version deal-save-format-version)
        (cons 'name (deal-name deal))
        (cons 'first-payment (deal-save--date-text (deal-first-payment deal)))
        (cons 'closing-date (deal-save--date-text (deal-closing-date deal)))
        (cons 'collateral-name (deal-root deal))
        (cons 'shortfalls (deal-shortfalls deal))
        (cons 'pricing-speed (deal-pricing-speed deal))
        (cons 'treasury-curve (deal-treasury-curve deal))
        (cons 'home-price-growth (deal-home-price-growth deal))
        (cons 'mortgage-spread (deal-mortgage-spread deal))
        (cons 'defaults (deal-defaults deal))
        (cons 'liquidation-lag (deal-liquidation-lag deal))
        (cons 'rate-model (deal-rate-model deal))
        (cons 'index (deal-index deal))
        (cons 'collateral (deal-collateral deal))
        (cons 'other-tranches (map (lambda (name) (deal-save--tranche-arguments deal name))
                                   (filter (lambda (name) (not (equal? name (deal-root deal)))) (deal-save--tops deal))))
        (cons 'splits (deal-save--splits deal))
        (cons 'prices (map (lambda (name) (deal-save--price-entry deal name)) (deal-names deal)))
        (cons 'names (deal-names deal))))

(define (deal-save--slot-text slot)
  "A slot of the deal-file as the lines of the file: :name value, or, for a long list, :name and then an element to a line."
  (let ((name (car slot))
        (value (cdr slot)))
    (if (and (member name deal-save--one-to-a-line) (pair? value))
        (format "\n :{}\n ({})" name (string-join (map write-to-string value) "\n  "))
        (format "\n :{} {}" name (write-to-string value)))))

(define (deal-save--text deal slots)
  "The text of the file: a line that says what it is, and the deal-file, #S(deal-file ...), with a slot to a line."
  (string-append (format "; The deal {}, saved by save-deal. (load-deal \"the name of this file\") makes it again.\n"
                         (write-to-string (deal-name deal)))
                 "#S(deal-file"
                 (apply string-append (map deal-save--slot-text slots))
                 ")\n"))

(define (deal-save--check-reads-back text slots)
  "An error if a slot of the text does not read back as the value it was written from: a function, a hash table or anything else that is
written #<...> is not data, and is not saved."
  (let ((read-back (read-from-string text)))
    (dolist (slot slots)
      (let ((written (write-to-string (cdr slot))))
        (when (or (string-contains? written "#<")
                  (not (equal? written (write-to-string (struct-ref read-back (car slot))))))
          (error (format "save-deal: the {} of the deal is not data that can be written and read back (a function, say): {}"
                         (car slot) (if (> (string-length written) 200) (string-append (substring written 0 200) " ...") written))))))))

(define (deal-save--check-has-pieces deal)
  "An error if the collateral of the deal has a balance but no pieces: its cash flows were given to it, and there is nothing to work them out from again."
  (when (and (null? (deal-pieces deal))
             (> (vector-ref (node-balance (get-node deal (deal-root deal))) 0) 0.0))
    (error (format "save-deal: the collateral of {} was given its cash flows, not pieces of collateral (see deal-set-collateral!): what is saved is the pieces that the cash flows are worked out from"
                   (deal-name deal)))))

(define (save-deal deal path)
  "Saves the deal in the file at path, as data that load-deal makes it again from: its name, dates and settings, its collateral, its pricing speed and
Treasury curve, its splits and their tranches, and the price, yield, spread or OAS that each tranche was given, and its delay. The cash flows, the sizes
that splits work out and the coupons are worked out again when it is loaded. A prepayment model or an index function that the deal was given is a
function, which is not saved (save-deal says so): give it to the loaded deal again. The file is text, #S(deal-file ...), that a person can read.
Returns path.

  (save-deal deal \"demo.deal\")"
  (deal-save--check-has-pieces deal)
  (let* ((slots (deal-save--slots deal))
         (text (deal-save--text deal slots)))
    (deal-save--check-reads-back text slots)
    (write-text-file path text)
    (unless (null? (deal-prepayment-model deal))
      (display "save-deal: the deal's prepayment model is a function, which is not saved: give it to the loaded deal again, with deal-set-prepayment-model!\n"))
    (unless (null? (deal-index-function deal))
      (display "save-deal: the deal's index function is a function, which is not saved: give it to the loaded deal again, with deal-set-index-function!\n"))
    path))

; ---------------------------------------------------------------------------
; Loading
; ---------------------------------------------------------------------------

(define (deal-save--option entry key)
  "The value after key in entry, a list such as (\"A\" :priced-by price :value 101.5 :delay 24), or '() if key is not in it."
  (let ((found (member key (cdr entry))))
    (if (and found (pair? (cdr found))) (cadr found) '())))

(define (deal-save--date text)
  "The date that the text \"2026-11-25\" is, or '() for '()."
  (if (null? text) '() (string->date text)))

(define (deal-save--read path)
  "The deal-file in the file at path, or an error that says what is wrong with it."
  (let ((saved (catch-error (read-from-string (read-text-file path))
                 (message)
                 (error (format "load-deal: {} cannot be read as a saved deal: {}" path message)))))
    (unless (deal-file? saved)
      (error (format "load-deal: {} is not a deal saved by save-deal: it is not a #S(deal-file ...)" path)))
    (unless (equal? (deal-file-version saved) deal-save-format-version)
      (error (format "load-deal: {} was saved in version {} of the way deals are saved, and this is version {}" path (deal-file-version saved) deal-save-format-version)))
    saved))

(define (deal-save--give-prices! deal entries)
  "Gives each node the price, yield, spread or OAS that it was given, and its delay, and works out the rest of its slots (see deal-update-analytics!).
A tranche priced by its OAS keeps it, and is priced when the paths of rates are run (see deal-run-paths!)."
  (let ((priced #f))
    (dolist (entry entries)
      (let ((node (get-node deal (car entry)))
            (kind (deal-save--option entry :priced-by))
            (value (deal-save--option entry :value)))
        (node-delay-set! node (deal-save--option entry :delay))
        (unless (null? kind)
          (node-priced-by-set! node kind)
          (cond ((eq? kind 'price) (node-price-set! node value))
                ((eq? kind 'yield) (node-yield-set! node value))
                ((eq? kind 'spread) (node-spread-set! node value))
                ((eq? kind 'oas) (node-oas-set! node value))
                (else (error (format "load-deal: {} was priced by {}, which is not price, yield, spread or oas" (car entry) kind))))
          (set! priced #t))))
    (when priced
      (deal-pricing--track-prices! deal)
      (deal-update-analytics! deal))))

(define (deal-save--check-sizes deal saved)
  "An error if a tranche of the deal that was made from the file does not have the balance that the file says it had: a split that works out its
sizes worked them out to something else, from the collateral and the settings that were saved."
  (dolist (entry (deal-file-splits saved))
    (dolist (tranche (cadr entry))
      (let ((made (vector-ref (node-balance (get-node deal (car tranche))) 0)))
        (when (> (abs (- made (cadr tranche))) (* deal-tolerance (deal-size deal)))
          (error (format "load-deal: the file gives {} a balance of {:,.2f}, and the deal made from it gives it {:,.2f}" (car tranche) (cadr tranche) made)))))))

(define (deal-save--put-in-order! deal names)
  "Makes the names of the deal's nodes be in the order of names, the order they were added in when the deal was saved, if they are the same names."
  (unless (equal? (sort names) (sort (deal-names deal)))
    (error (format "load-deal: the file names the nodes {}, and the deal made from it has {}" names (deal-names deal))))
  (deal-names-set! deal names))

(define (load-deal path)
  "The deal saved in the file at path by save-deal, made again: its collateral and settings are given to a new deal, its splits are added in the order
of the tree (so the cash flows, the sizes that splits work out and the coupons are worked out as they were when it was built), and its tranches are
given the prices, yields, spreads, OASs and delays that they had. An error if the file is not one that save-deal wrote, if it has a kind of split
that is not defined (load the file that defines it first), or if a tranche does not come out the size that it was. The file is read as data, and
nothing in it is run.

  (define deal (load-deal \"demo.deal\"))"
  (let* ((saved (deal-save--read path))
         (deal (new-deal (deal-file-name saved)
                         :speed (deal-file-pricing-speed saved)
                         :first-payment (deal-save--date (deal-file-first-payment saved))
                         :closing-date (deal-save--date (deal-file-closing-date saved))
                         :treasury-curve (deal-file-treasury-curve saved)
                         :collateral-name (deal-file-collateral-name saved)
                         :shortfalls (deal-file-shortfalls saved))))
    (deal-set-home-price-growth! deal (deal-file-home-price-growth saved))
    (deal-set-mortgage-spread! deal (deal-file-mortgage-spread saved))
    (deal-set-defaults! deal (deal-file-defaults saved))
    (deal-set-liquidation-lag! deal (deal-file-liquidation-lag saved))
    (unless (null? (deal-file-rate-model saved))
      (deal-set-rate-model! deal (deal-file-rate-model saved)))
    (unless (null? (deal-file-collateral saved))
      (deal-set-collateral! deal (deal-file-collateral saved)))
    (dolist (tranche (deal-file-other-tranches saved))
      (apply deal-add-tranche! deal tranche))
    (dolist (entry (deal-file-splits saved))
      (deal-add-plan! deal (car entry) (make-split-plan :tranches (cadr entry) :split (caddr entry))))
    (deal-save--check-sizes deal saved)
    (deal-save--put-in-order! deal (deal-file-names saved))
    (deal-index-set! deal (deal-file-index saved))
    (deal-save--give-prices! deal (deal-file-prices saved))
    deal))
