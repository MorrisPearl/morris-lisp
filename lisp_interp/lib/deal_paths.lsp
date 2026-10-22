; deal_paths.lsp
; ==============
; The option-adjusted spread (OAS) and the effective duration of the tranches of a deal. A deal is run on many paths of interest rates, each a possible future (see
; "Interest rate paths" in the library manual); on each path the collateral prepays as a model says it does there, so the cash flows of every tranche differ from path to
; path, and the value of a tranche is the average, over the paths, of what its cash flows are worth when each is discounted along its own path.
;
;   (deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))
;   (deal-run-paths! deal :paths 200)                  ; takes a while: a run of the deal for each path, and for each of the two shifts of the curve
;   (deal-set-price! deal "A" 100.5)                   ; its oas and its effective duration are worked out with the yield and the rest (see deal_pricing.lsp)
;   (deal-set-oas! deal "B" 90)                        ; or the price of B is, from an OAS of 90 basis points
;
; THE PARTS (each a slot of the deal, which the user can replace).
;
;   the rate model     a, sigma1 and sigma2 (and b), the numbers that make the paths: see "How to generate paths" in the library manual. The paths start on the Treasury curve of
;                      the deal, and spread out. (rate-model, with the values of the manual to begin with: they are to be worked out from market data.)
;   the prepayment model   a function (model piece path): the annual prepayment rate, in percent (a CPR of 6 is 6), for each month of the collateral-piece (a vector with as many
;                      as its wam, month 1 being the first payment), given the rate-path, the short rate and the 10-year yield, each a vector with a rate (a decimal) for each month
;                      from the start, and the date of the first payment. What a model looks at is its own affair: the piece says what the loans are (their wac, age and so on).
;                      A pricing speed of the model (prepayment-speed 'model 105) is 105% of it, on each path; the cash flows at the pricing speed are what it says if rates follow
;                      the forward curve (deal-forward-path). It is the one fitted to Freddie Mac's loans (freddie-prepayment-model, told the deal's home-price-growth and
;                      mortgage-spread), unless the deal is given another. A pricing speed of another type (PSA, CPR, SMM) does not look at rates: the paths prepay at it
;                      (static-prepayment-model).
;   the index function  a function of the path of short rates that gives the path of the index that a floating tranche is of: a vector with a number (a decimal) for each month.
;                      To begin with it is the identity: the index is the short rate.
;
; THE SPREAD. The OAS of a tranche is the one spread, a constant added to the short rate of every month of every path, that makes the average value of its cash flows the money
; that the buyer pays (its price and its accrued interest). A month's cash flow is discounted by 1 / (1 + (short rate + oas) / 12) for each month on the path up to it, as
; in oas_monte_carlo.lsp, but the first payment is the part of a month away that it is from the closing date, as in the yield of deal_pricing.lsp. It is in basis points.
; The paths start on the curve, so their average discount factor is the curve's, and an OAS of 0 is a price on the Treasury curve (what the borrowers' option to prepay
; is worth is taken out of the spread: the more it is worth, the lower the OAS of a price).
;
; THE EFFECTIVE DURATION. The curve is moved up and down by a shift (25 basis points), the paths are made again on the moved curves from the same random numbers, the
; collateral is prepaid by the model on them, and the deal run; the value of the tranche at its OAS, which stays as it was, is worked out on each of the three sets of paths.
; The effective duration is the proportion that the money falls by, for a rise of one in rates: (down - up) / (2 x shift x money).

(require "deal.lsp")
(require "yield_curves.lsp")
(require "solver.lsp")
(require "freddie_prepayment.lsp")
(require "freddie_default.lsp")

(defstruct rate-model (a 2.75) (b 0.15) (sigma1 0.019) (sigma2 0.012))
; the numbers of the two-factor model of the paths (see simulate-rate-paths): how fast the short rate follows the level, and the level follows its mean, and the sizes of the shocks

(defstruct rate-path short-rates long-yields (first-payment '()))
; a path of rates that a prepayment model is given: the short rate, and the 10-year par yield, at the start of each month from today, as vectors of decimals, and the
; date of the first payment, month 1 ('() if the deal has none), for a model that looks at the seasons

(defstruct path-run rates flows)
; the paths that were run on one curve: rates is a list of vectors, the short rate on each path; flows is a hash table of the name of a tranche to a list, a vector for each
; path, of what the tranche is paid each month

(defstruct path-sets paths shift seed base up down (cache (make-hash-table)))
; what deal-run-paths! made: how many paths, the shift of the curve, and the seed, and the path-runs on the curve, on it moved up by the shift, and on it moved down.
; cache has what was worked out of them (an OAS, an effective duration), by the tranche and the money

; ---------------------------------------------------------------------------
; What the paths are made with
; ---------------------------------------------------------------------------

(define (static-prepayment-model speed)
  "A prepayment model that does not look at the rates: the collateral prepays at the speed (see prepayment-speed), whatever they are. Its answer is the rate, in percent,
that the speed is for each month of the piece."
  (lambda (piece path)
    (let ((smms (speed-smms speed (collateral-piece-age piece) (collateral-piece-wam piece))))
      (* 100.0 (- 1.0 (expt (- 1.0 smms) 12.0))))))

(define (model-at-speed model speed)
  "The prepayment model, as a share of it that the speed of the model (prepayment-speed 'model ...) says, in each month: 105 is 105% of the rates it gives (no more than 99)."
  (lambda (piece path)
    (vector-clip (* (model piece path) (/ (speed-values speed (collateral-piece-wam piece)) 100.0)) 0.0 99.0)))

(define (deal-base-prepayment-model deal)
  "The deal's prepayment model: the one it was given (deal-set-prepayment-model!), or the one fitted to Freddie Mac's loans, told the deal's growth of home prices and
mortgage spread."
  (if (null? (deal-prepayment-model deal))
      (freddie-prepayment-model :home-price-growth (deal-home-price-growth deal) :mortgage-spread (deal-mortgage-spread deal))
      (deal-prepayment-model deal)))

(define (deal-prepayment-model-in-use deal)
  "The prepayment model that the paths are prepaid by: if the pricing speed of the deal is of the model, the deal's prepayment model at that speed (see model-at-speed);
otherwise one that prepays at the pricing speed, whatever the rates."
  (let ((speed (deal-pricing-speed deal)))
    (if (model-speed? speed)
        (model-at-speed (deal-base-prepayment-model deal) speed)
        (static-prepayment-model speed))))

(define (deal-forward-path deal months)
  "The path of rates that the forward curve of the deal's Treasury curve is (one with no randomness: the curve itself, read forward), at least months long: what rates
are if they do what the market expects. An error if the deal has no curve."
  (when (null? (deal-treasury-curve deal))
    (error "a speed of the prepayment model, or loans that default as the default model says, needs a Treasury curve, which the rates the models look at are read forward from: give the deal one, (deal-set-treasury-curve! deal '((2 4.1) (10 4.5))), or in (info deal)"))
  (let ((paths (simulate-rate-paths (deal-forward-curve deal) 0.0 0.0 (max 1 (ceiling (/ months 12.0))) 2)))
    (make-rate-path :short-rates (car (cadr paths)) :long-yields (car (caddr paths)) :first-payment (deal-first-payment deal))))

(define (deal-piece-defaults deal piece path)
  "The defaults of the piece on the path of rates, as project-pool takes them: (mdrs severities). The monthly default rate is the deal's share (deal-defaults) of what the
default model fitted to Freddie Mac's loans says, and the severity is what the severity model says of the loans that default each month, sold liquidation-lag months later;
both are told the deal's growth of home prices and mortgage spread."
  (let* ((settings (list :home-price-growth (deal-home-price-growth deal) :mortgage-spread (deal-mortgage-spread deal)))
         (cdrs (vector-clip (* ((apply freddie-default-model settings) piece path) (/ (deal-defaults deal) 100.0)) 0.0 99.0))
         (severities ((apply freddie-severity-model :lag (deal-liquidation-lag deal) settings) piece path)))
    (list (smms-from-cprs cdrs (collateral-piece-wam piece)) severities)))

(define (deal-defaults-of deal path-of)
  "What project-pieces-with is to be given as defaults-of: '() if the deal's loans do not default (deal-defaults is 0), and otherwise a function of a piece, the defaults
of the piece on its path of rates, (path-of piece)."
  (if (= (deal-defaults deal) 0)
      '()
      (lambda (piece) (deal-piece-defaults deal piece (path-of piece)))))

(define (model-speed-smms deal speed piece)
  "The single monthly mortality, a decimal, of each month of the piece at a speed of the prepayment model: what the deal's prepayment model says it is if rates follow the
forward curve, times the share that the speed says."
  (let ((months (collateral-piece-wam piece)))
    (smms-from-cprs ((model-at-speed (deal-base-prepayment-model deal) speed) piece (deal-forward-path deal months)) months)))

(define (deal-rate-model-in-use deal)
  "The rate model of the deal, or, if it has none, one with the numbers of the library manual."
  (if (null? (deal-rate-model deal)) (make-rate-model) (deal-rate-model deal)))

(define (deal-index-of-short-rates deal short-rates)
  "The index that the floating tranches of the deal are of, for a path of short rates: what the index function of the deal makes of it (the short rates, if it has none)."
  (if (null? (deal-index-function deal))
      short-rates
      ((deal-index-function deal) short-rates)))

(define (deal-forward-curve deal)
  "The monthly forward rates, a vector of 360 decimals, of the Treasury curve of the deal, which the paths of rates start on: the zero curve that its par yields give, and its forward
rates (see par-curve-zeros and curve-forward-rates). An error if it has no curve."
  (let ((points (deal-treasury-curve deal)))
    (when (null? points)
      (error "the deal has no Treasury curve, which the paths of rates start on: give it one, (deal-set-treasury-curve! deal '((2 4.1) (3 4.2))), or in (info deal)"))
    (table-column (curve-forward-rates (par-curve-zeros (list->vector (map car points))
                                                         (list->vector (map (lambda (point) (/ (cadr point) 100.0)) points))))
                  "forward")))

; ---------------------------------------------------------------------------
; The deal on a path
; ---------------------------------------------------------------------------

(define (path-collateral-flows deal pieces model path)
  "The cash flows of the collateral on a path: each piece prepays as the model says it does on the path, and, if the deal's loans default, defaults as the default model
says it does there. (principal interest balance loss), as long as the deal."
  (deal-pad-flows deal (project-pieces-with pieces
                                            (lambda (piece) (smms-from-cprs (model piece path) (collateral-piece-wam piece)))
                                            :defaults-of (deal-defaults-of deal (lambda (piece) path))
                                            :lag (deal-liquidation-lag deal))))

(define (path-tranche-flows deal collateral-flows index names)
  "What each of the tranches called names is paid in each month, a vector for each, when the collateral pays the cash flows, and the floating coupons are of the index (a vector
with a number for each month): the principal and the interest, from a run of a copy of the deal."
  (let ((run (deal-run-copy deal collateral-flows #t index)))
    (map (lambda (name)
           (let ((node (get-node run name)))
             (+ (node-principal node) (node-interest node))))
         names)))

(define (run-path-set deal forwards n-paths seed label)
  "A path-run: n-paths paths made on the forward rates, from the seed, the collateral prepaid by the prepayment model on each, and the deal run on each. It says how far it has
got, as label."
  (let* ((model (deal-prepayment-model-in-use deal))
         (rates (deal-rate-model-in-use deal))
         (years (max 1 (ceiling (/ (deal-periods deal) 12.0))))
         (simulated (simulate-rate-paths forwards (rate-model-sigma1 rates) (rate-model-sigma2 rates) years n-paths
                                         :a (rate-model-a rates) :b (rate-model-b rates) :seed seed))
         (short-paths (cadr simulated))
         (long-paths (caddr simulated))
         (count (length short-paths))
         (every (max 1 (quotient count 10)))
         (pieces (deal-pieces deal))
         (names (deal-tree-names deal (deal-root deal)))
         (collected (make-hash-table)))
    (dolist (name names)
      (hash-table-set! collected name '()))
    (loop for short in short-paths
          for long in long-paths
          for number from 1
          do (let* ((path (make-rate-path :short-rates short :long-yields long :first-payment (deal-first-payment deal)))
                    (flows (path-tranche-flows deal (path-collateral-flows deal pieces model path) (deal-index-of-short-rates deal short) names)))
               (for-each (lambda (name flow) (hash-table-set! collected name (cons flow (hash-table-ref collected name)))) names flows)
               (when (or (= (remainder number every) 0) (= number count))
                 (display (format "{}: {} of {} paths\n" label number count)))))
    (dolist (name names)
      (hash-table-set! collected name (reverse (hash-table-ref collected name))))
    (make-path-run :rates short-paths :flows collected)))

; ---------------------------------------------------------------------------
; What the tranches are worth on the paths
; ---------------------------------------------------------------------------

(define (path-run-money run name oas fraction)
  "What the tranche called name is worth on the paths of the run: the average, over the paths, of its cash flows discounted along each at the short rates and the oas (a
decimal), the first payment being fraction of a month from the start."
  (let ((values (path-present-values (hash-table-ref (path-run-flows run) name) (path-run-rates run) oas fraction)))
    (/ (vector-sum values) (vector-length values))))

(define (path-sets-cached sets key compute)
  "What (compute) gives, which is kept in the sets under the key, so that it is worked out once."
  (let ((found (hash-table-ref (path-sets-cache sets) key)))
    (or found
        (let ((value (compute)))
          (hash-table-set! (path-sets-cache sets) key value)
          value))))

(define (path-sets-oas sets name money fraction)
  "The OAS, a decimal, of the tranche called name that is paid for with this money: the spread at which it is worth that on the paths. An error if there is none, between -100% and 500%."
  (path-sets-cached sets (format "oas {} {}" name money)
    (lambda ()
      (let ((excess (lambda (oas) (- (path-run-money (path-sets-base sets) name oas fraction) money))))
        (unless (and (> (excess -1.0) 0.0) (< (excess 5.0) 0.0))
          (error (format "no OAS, from -10000 to 50000 basis points, makes {} worth {:,.2f} on the paths" name money)))
        (ridders excess -1.0 5.0 :tolerance 1e-13)))))

(define (path-sets-effective-duration sets name oas fraction)
  "The effective duration of the tranche called name at this OAS (a decimal), in years: the proportion that its value falls by for a rise of one in rates, from its value on the
paths on the curve moved down and moved up, at the same OAS."
  (path-sets-cached sets (format "duration {} {}" name oas)
    (lambda ()
      (/ (- (path-run-money (path-sets-down sets) name oas fraction) (path-run-money (path-sets-up sets) name oas fraction))
         (* 2.0 (path-sets-shift sets) (path-run-money (path-sets-base sets) name oas fraction))))))
