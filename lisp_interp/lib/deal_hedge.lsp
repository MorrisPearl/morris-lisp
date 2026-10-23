; deal_hedge.lsp
; ==============
; Hedging a tranche of a deal: the Treasuries of the deal's Treasury curve and the collateral, each with its effective duration and effective convexity, and the
; positions in two of them that make the duration and the convexity of the tranche and the hedge together nothing.
;
;   (deal-run-paths! deal)                          ; the tranche's effective duration and convexity are of the paths of rates
;   (deal-set-price! deal "A" 101.0)
;   (display-table (treasury-measures deal))        ; a par Treasury at each maturity of the curve: its effective duration and convexity
;   (display-table (deal-hedge deal "A"))           ; the tranche, what to buy and sell to hedge it, and what is left: nothing
;
; THE TREASURIES. A Treasury is a par bond at each maturity of the deal's Treasury curve: its coupon is the curve's par yield there, paid every six months (a bill, of less
; than six months, pays all at the end), so that it is worth 100. It is valued off the deal's zero curve (deal-zero-curve), and again with the zero rates all moved up and
; down by the shift that the paths of rates were moved by (25 basis points), as the tranche is, so that its effective duration and effective convexity are the same measures
; as the tranche's (see effective-duration and effective-convexity in deal_paths.lsp). A Treasury has a convexity above 0; a tranche of mortgages that the borrowers can pay
; off early has one below 0.
;
; THE HEDGE. The tranche's market value (its money, M) times its effective duration (D) is its dollar duration, how much it loses for a rise of one in rates; M times its
; effective convexity (C) is its dollar convexity. A hedge is positions in instruments, h_i dollars of market value in each (below 0 for one that is sold), that make the
; dollar duration and the dollar convexity of the tranche and the hedge together 0:
;
;   M D + h_1 D_1 + h_2 D_2 = 0            M C + h_1 C_1 + h_2 C_2 = 0
;
; Two instruments are enough to make both 0. Of every pair of the instruments, the hedge is the one that does it with the least in all, |h_1| + |h_2|: a hedge is a cost
; to keep, and a big long and a big short that cancel are a bet on the difference between them. (deal-hedge-pairs deal name) shows every pair. The instruments are the
; Treasuries and the collateral of the deal, if it has been priced, with the paths run: it is the instrument that is most like the tranche.

(require "deal_pricing.lsp")

(defstruct hedge-instrument name price duration convexity)
; something to hedge with, or to be hedged: its name, its price (per 100 of face), its effective duration (years) and its effective convexity (years squared)

; ---------------------------------------------------------------------------
; The Treasuries
; ---------------------------------------------------------------------------

(define (treasury-cash-flows years coupon)
  "The cash flows of a Treasury of 100 face that matures in this many years, with this coupon (percent a year), as a list of (years amount): a coupon of half of it every six
months back from the maturity, and the face at the end; or, for a bill, of less than six months, the face and its interest at the end."
  (if (< years 0.5)
      (list (list years (* 100.0 (+ 1.0 (* (/ coupon 100.0) years)))))
      (let loop ((time years) (flows '()))
        (if (<= time 1e-9)
            flows
            (loop (- time 0.5) (cons (list time (+ (/ coupon 2.0) (if (= time years) 100.0 0.0))) flows))))))

(define (treasury-value zeros years coupon shift)
  "What a Treasury of 100 face, of this many years and coupon (percent), is worth on the zero curve (a table that par-curve-zeros makes) with every zero rate moved by the shift
(a decimal): each cash flow discounted by exp(-(zero + shift) x its years), the zero rate at its years being on a straight line between those of the curve."
  (let ((curve-years (table-column zeros "years"))
        (curve-zeros (table-column zeros "zero")))
    (apply + (map (lambda (flow)
                    (let ((time (car flow)))
                      (* (cadr flow) (exp (- (* (+ (interpolate time curve-years curve-zeros) shift) time))))))
                  (treasury-cash-flows years coupon)))))

(define (deal-shift deal)
  "The shift of the curve that the deal's effective durations and convexities are of: that of the paths of rates that were run, or 25 basis points."
  (if (null? (deal-path-sets deal)) 0.0025 (path-sets-shift (deal-path-sets deal))))

(define (deal-treasuries deal)
  "A Treasury at each maturity of the deal's Treasury curve, a par bond whose coupon is the curve's par yield there (see the top of the file), as a list of hedge-instruments:
its name (\"10y Treasury\"), its price (100, on the curve), and its effective duration and convexity, of the zero rates moved up and down by the deal's shift."
  (let ((zeros (deal-zero-curve deal))
        (shift (deal-shift deal)))
    (map (lambda (point)
           (let* ((years (car point))
                  (coupon (cadr point))
                  (down (treasury-value zeros years coupon (- shift)))
                  (value (treasury-value zeros years coupon 0.0))
                  (up (treasury-value zeros years coupon shift)))
             (make-hedge-instrument :name (format "{}y Treasury" (if (= years (round years)) (round years) years))
                                    :price value
                                    :duration (effective-duration down value up shift)
                                    :convexity (effective-convexity down value up shift))))
         (deal-treasury-curve deal))))

(define (treasury-measures deal)
  "A table with a row for each Treasury of the deal's curve (see deal-treasuries): its name, its years, its coupon (the par yield, percent), its price, and its effective
duration (years) and effective convexity (years squared)."
  (let ((treasuries (deal-treasuries deal))
        (points (deal-treasury-curve deal)))
    (make-table "instrument" (list->vector (map hedge-instrument-name treasuries))
                "years" (list->vector (map car points))
                "coupon" (list->vector (map cadr points))
                "price" (list->vector (map hedge-instrument-price treasuries))
                "effective duration" (list->vector (map hedge-instrument-duration treasuries))
                "effective convexity" (list->vector (map hedge-instrument-convexity treasuries)))))

; ---------------------------------------------------------------------------
; The hedge
; ---------------------------------------------------------------------------

(define (priced-on-paths? node)
  "Whether the node has an effective duration and convexity: it has been priced, and the paths of rates run."
  (number? (node-effective-convexity node)))

(define (node-instrument deal name)
  "The tranche (or the collateral) called name as a hedge-instrument: its price is its money per 100 of its balance."
  (let ((node (get-node deal name)))
    (make-hedge-instrument :name name
                           :price (* 100.0 (/ (node-money node) (vector-ref (node-balance node) 0)))
                           :duration (node-effective-duration node)
                           :convexity (node-effective-convexity node))))

(define (hedge-instruments deal tranche)
  "What the tranche can be hedged with, a list of hedge-instruments: the Treasuries (see deal-treasuries), and the collateral, if it has been priced (with the paths of rates
run), and is not the tranche itself."
  (let ((root (deal-root deal)))
    (if (and (not (equal? root tranche)) (priced-on-paths? (get-node deal root)))
        (append (deal-treasuries deal) (list (node-instrument deal root)))
        (deal-treasuries deal))))

(define (hedge-of-pair money tranche first second)
  "The market values (h1 h2) in two hedge-instruments, first and second, that make the dollar duration and the dollar convexity of this money of the tranche (a hedge-instrument)
and them together 0; or '() if the two cannot (their durations and convexities are in the same proportion)."
  (let* ((duration (hedge-instrument-duration tranche)) (convexity (hedge-instrument-convexity tranche))
         (d1 (hedge-instrument-duration first)) (c1 (hedge-instrument-convexity first))
         (d2 (hedge-instrument-duration second)) (c2 (hedge-instrument-convexity second))
         (determinant (- (* d1 c2) (* d2 c1))))
    (if (< (abs determinant) 1e-9)
        '()
        (list (/ (* money (- (* convexity d2) (* duration c2))) determinant)
              (/ (* money (- (* duration c1) (* convexity d1))) determinant)))))

(define (tranche-to-hedge deal name)
  "The tranche called name as a hedge-instrument: an error that says what to do if it has no effective duration and convexity."
  (unless (priced-on-paths? (get-node deal name))
    (error (format "{} has no effective duration and convexity to hedge: they are of the paths of rates, so price it, and run them, (deal-run-paths! deal)" name)))
  (node-instrument deal name))

(define (pairs-of items)
  "Every pair of the items, each once, as a list of (a b), in the order of the items: (pairs-of '(x y z)) is ((x y) (x z) (y z))."
  (if (null? items)
      '()
      (append (map (lambda (other) (list (car items) other)) (cdr items))
              (pairs-of (cdr items)))))

(define (deal-hedge-pairs deal name)
  "A table of every pair of the instruments that the tranche called name can be hedged with (see hedge-instruments), and the market values in each that hedge it (below 0
for one that is sold), the pair with the least in all first: the columns first, second, first value, second value, and gross (the two, without their signs, added up)."
  (let* ((tranche (tranche-to-hedge deal name))
         (money (node-money (get-node deal name)))
         (hedge-row (lambda (pair)
                      (let ((values (hedge-of-pair money tranche (car pair) (cadr pair))))
                        (if (null? values)
                            '()
                            (list (hedge-instrument-name (car pair)) (hedge-instrument-name (cadr pair))
                                  (car values) (cadr values) (+ (abs (car values)) (abs (cadr values))))))))
         (rows (sort (filter (lambda (row) (not (null? row))) (map hedge-row (pairs-of (hedge-instruments deal name))))
                     (lambda (row) (list-ref row 4)))))
    (when (null? rows)
      (error (format "there are not two instruments to hedge {} with: the deal's Treasury curve needs two points, or the collateral a price" name)))
    (make-table "first" (list->vector (map car rows))
                "second" (list->vector (map cadr rows))
                "first value" (list->vector (map caddr rows))
                "second value" (list->vector (map cadddr rows))
                "gross" (list->vector (map (lambda (row) (list-ref row 4)) rows)))))

(define (deal-hedge deal name)
  "The hedge of the tranche called name: of the pairs of the instruments it can be hedged with (the Treasuries of the deal's curve, and the collateral, if it has been priced),
the one that makes its dollar duration and dollar convexity, and theirs, together 0 with the least in all (see the top of the file). A table with a row for the tranche, a row for
each of the two instruments, and a row net, of them all together, with the columns position, market value (below 0 for what is sold), face (per the price), effective duration,
effective convexity, dollar duration (the market value times the effective duration: what it loses for a rise of one in rates) and dollar convexity (times the convexity). The
net dollar duration and dollar convexity are 0."
  (let* ((tranche (tranche-to-hedge deal name))
         (best (table-row (deal-hedge-pairs deal name) 0))
         (instruments (hedge-instruments deal name))
         (named (lambda (instrument-name) (find-if (lambda (instrument) (equal? (hedge-instrument-name instrument) instrument-name)) instruments)))
         (row-of (lambda (instrument value)
                   (let ((duration (hedge-instrument-duration instrument))
                         (convexity (hedge-instrument-convexity instrument)))
                     (list (hedge-instrument-name instrument) value (* 100.0 (/ value (hedge-instrument-price instrument)))
                           duration convexity (* value duration) (* value convexity)))))
         (rows (list (row-of tranche (node-money (get-node deal name)))
                     (row-of (named (row-ref best "first")) (row-ref best "first value"))
                     (row-of (named (row-ref best "second")) (row-ref best "second value"))))
         (column (lambda (k) (map (lambda (row) (list-ref row k)) rows))))
    (make-table "position" (list->vector (append (column 0) (list "net")))
                "market value" (list->vector (append (column 1) (list (apply + (column 1)))))
                "face" (list->vector (append (column 2) (list nan)))
                "effective duration" (list->vector (append (column 3) (list nan)))
                "effective convexity" (list->vector (append (column 4) (list nan)))
                "dollar duration" (list->vector (append (column 5) (list (apply + (column 5)))))
                "dollar convexity" (list->vector (append (column 6) (list (apply + (column 6))))))))
