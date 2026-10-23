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
; than six months, pays all at the end), so that it is worth 100. It is valued off the zero curve that the par yields give (par-curve-zeros), and again with the zero rates
; all moved up and down by the shift that the paths of rates were moved by (25 basis points), as the tranche is: its effective duration is (down - up) / (2 x shift x value),
; and its effective convexity (down + up - 2 x value) / (value x shift^2), the same measures as the tranche's. A Treasury has a convexity above 0; a tranche of mortgages that
; the borrowers can pay off early has one below 0.
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

(define (deal-zero-curve deal)
  "The zero curve of the deal's Treasury curve, as par-curve-zeros makes it: a table of years, par, discount and zero (a continuously compounded rate). An error if the deal has
no curve."
  (let ((points (deal-treasury-curve deal)))
    (when (null? points)
      (error "the deal has no Treasury curve, which the Treasuries are of: give it one, (deal-set-treasury-curve! deal '((2 4.1) (10 4.5))), or in (info deal)"))
    (par-curve-zeros (list->vector (map car points)) (list->vector (map (lambda (point) (/ (cadr point) 100.0)) points)))))

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

(define (treasury-measures deal)
  "A table with a row for each Treasury, a par bond at each maturity of the deal's Treasury curve (see the top of the file): its name (\"10y Treasury\"), its years, its coupon
(the par yield, percent), its price (100, on the curve), and its effective duration (years) and effective convexity (years squared), of the zero rates moved up and down by the
shift that the paths of rates were moved by."
  (let* ((zeros (deal-zero-curve deal))
         (shift (deal-shift deal))
         (points (deal-treasury-curve deal))
         (measure (lambda (point)
                    (let* ((years (car point))
                           (coupon (cadr point))
                           (value (treasury-value zeros years coupon 0.0))
                           (down (treasury-value zeros years coupon (- shift)))
                           (up (treasury-value zeros years coupon shift)))
                      (list (format "{}y Treasury" (if (= years (round years)) (round years) years))
                            years coupon value
                            (/ (- down up) (* 2.0 shift value))
                            (/ (+ down up (* -2.0 value)) (* value shift shift))))))
         (rows (map measure points)))
    (make-table "instrument" (list->vector (map car rows))
                "years" (list->vector (map cadr rows))
                "coupon" (list->vector (map caddr rows))
                "price" (list->vector (map cadddr rows))
                "effective duration" (list->vector (map (lambda (row) (list-ref row 4)) rows))
                "effective convexity" (list->vector (map (lambda (row) (list-ref row 5)) rows)))))

(define (hedge-instruments deal tranche)
  "What the tranche can be hedged with, as a list of (name price effective-duration effective-convexity): the Treasuries (see treasury-measures), and the collateral, if it has
been priced (with the paths of rates run), and is not the tranche itself. The price of the collateral is its money per 100 of its balance."
  (let* ((treasuries (treasury-measures deal))
         (root (get-node deal (deal-root deal)))
         (collateral (if (and (not (equal? (deal-root deal) tranche)) (number? (node-effective-convexity root)))
                         (list (list (deal-root deal) (* 100.0 (/ (node-money root) (vector-ref (node-balance root) 0)))
                                     (node-effective-duration root) (node-effective-convexity root)))
                         '())))
    (append (map list
                 (vector->list (table-column treasuries "instrument"))
                 (vector->list (table-column treasuries "price"))
                 (vector->list (table-column treasuries "effective duration"))
                 (vector->list (table-column treasuries "effective convexity")))
            collateral)))

(define (tranche-measures deal name)
  "The money, effective duration and effective convexity of the tranche called name, as a list: an error that says what to do if it has not got them."
  (let ((node (get-node deal name)))
    (unless (number? (node-effective-convexity node))
      (error (format "{} has no effective duration and convexity to hedge: they are of the paths of rates, so price it, and run them, (deal-run-paths! deal)" name)))
    (list (node-money node) (node-effective-duration node) (node-effective-convexity node))))

(define (hedge-of-pair money duration convexity first second)
  "The market values (h1 h2) in two instruments, each (name price duration convexity), that make the dollar duration and the dollar convexity of a position of this money,
duration and convexity, and them, together 0; or '() if the two cannot (their durations and convexities are in the same proportion)."
  (let* ((d1 (caddr first)) (c1 (cadddr first))
         (d2 (caddr second)) (c2 (cadddr second))
         (determinant (- (* d1 c2) (* d2 c1))))
    (if (< (abs determinant) 1e-9)
        '()
        (list (/ (* money (- (* convexity d2) (* duration c2))) determinant)
              (/ (* money (- (* duration c1) (* convexity d1))) determinant)))))

(define (deal-hedge-pairs deal name)
  "A table of every pair of the instruments that the tranche called name can be hedged with (see hedge-instruments), and the market values in each that hedge it (below 0
for one that is sold), the pair with the least in all first: the columns first, second, first value, second value, and gross (the two, without their signs, added up)."
  (let* ((measures (tranche-measures deal name))
         (instruments (hedge-instruments deal name))
         (pairs (let loop ((rest instruments) (found '()))
                  (if (null? rest)
                      (reverse found)
                      (loop (cdr rest)
                            (append (reverse (filter (lambda (pair) (not (null? (caddr pair))))
                                                     (map (lambda (other) (list (car rest) other (apply hedge-of-pair (append measures (list (car rest) other)))))
                                                          (cdr rest))))
                                    found)))))
         (rows (sort (map (lambda (pair)
                            (let ((values (caddr pair)))
                              (list (car (car pair)) (car (cadr pair)) (car values) (cadr values) (+ (abs (car values)) (abs (cadr values))))))
                          pairs)
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
  (let* ((measures (tranche-measures deal name))
         (money (car measures))
         (node (get-node deal name))
         (best (table-row (deal-hedge-pairs deal name) 0))
         (instruments (hedge-instruments deal name))
         (instrument (lambda (instrument-name) (assoc instrument-name instruments)))
         (row-of (lambda (position value price duration convexity)
                   (list position value (* 100.0 (/ value price)) duration convexity (* value duration) (* value convexity))))
         (rows (list (row-of name money (* 100.0 (/ money (vector-ref (node-balance node) 0))) (cadr measures) (caddr measures))
                     (let ((first (instrument (row-ref best "first"))))
                       (row-of (car first) (row-ref best "first value") (cadr first) (caddr first) (cadddr first)))
                     (let ((second (instrument (row-ref best "second"))))
                       (row-of (car second) (row-ref best "second value") (cadr second) (caddr second) (cadddr second)))))
         (column (lambda (k) (map (lambda (row) (list-ref row k)) rows)))
         (net-value (apply + (column 1))))
    (make-table "position" (list->vector (append (column 0) (list "net")))
                "market value" (list->vector (append (column 1) (list net-value)))
                "face" (list->vector (append (column 2) (list nan)))
                "effective duration" (list->vector (append (column 3) (list nan)))
                "effective convexity" (list->vector (append (column 4) (list nan)))
                "dollar duration" (list->vector (append (column 5) (list (apply + (column 5)))))
                "dollar convexity" (list->vector (append (column 6) (list (apply + (column 6))))))))
