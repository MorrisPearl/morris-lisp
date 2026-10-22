; prepayment_speed.lsp
; ====================
; How fast a pool of mortgages prepays, as one value that can change with time, and the cash flows of pieces of collateral at that speed.
;
; A speed has a type, which says what the number means, and the number for each month. The types are PSA (150 is 150% of the standard
; curve, which rises to 6 CPR over 30 months of loan age; see prepayment_model.lsp), CPR (the annual rate of prepayment, in percent: 6
; is 6 CPR), SMM (the share of what is left that prepays in a month, in percent: 0.5 is a half a percent a month) and MODEL (a share, in percent, of
; what a deal's prepayment model says, which looks at rates: 105 is 105% of it; see model-speed-smms in deal_paths.lsp, which a deal works it out with). The number is a
; single one, for every month, or a few linear pieces, each (from to months): the speed goes in a straight line from `from` to `to`, and is
; `to` in the last of the months, so that the piece after it, or the speed that holds after the last piece, starts from there.
; The months are those from the first payment, the same for every piece of collateral.
;
;   (prepayment-speed 'psa 150)                          ; 150 PSA, always
;   (prepayment-speed 'cpr '((5 5 12) (5 20 24)))        ; 5 CPR for a year, then to 20 CPR over two years, and 20 CPR after that
;   (prepayment-speed 'psa '((0 100 30)))                ; 0 PSA in month 0 to 100 PSA in month 30, and 100 after: a ramp
;
; A piece of collateral is a collateral-piece (make-collateral-piece :balance 100000000 :wac 6.5 :coupon 6.0 :wam 360 :age 0), or, as a shorthand, the list (balance wac coupon wam [age])
; of its first slots: the balance now, the weighted average coupon of the loans (the wac, which
; the borrowers pay and which pays the loans off) and the pass-through coupon (which the investors in the pool are paid), both in percent
; (the pass-through coupon is the wac less the fees that are taken out, so it is no more), the weighted average maturity, the months
; that are left (so that a pool of 30-year loans that have gone for a year is 348), and the age, the months the loans have gone, which is what
; the PSA curve is a rise with (0 if left out). (project-pieces pieces speed) adds up the cash flows of all of them: what is paid to the
; investors is the interest at the pass-through coupon, and the principal is what the loans at their wac pay.
;
; The other slots of a piece say what its loans and its borrowers are like, for a prepayment model to look at (see collateral-characteristics).
; Each is '() if it is not known, and the cash flows at a speed do not use them.

(require "prepayment_model.lsp")

(defstruct speed-curve type pieces)                  ; (made by prepayment-speed: pieces is a list of (from to months), months '() for "from here on")

(define speed-types '(psa cpr smm model))

(define (model-speed? curve)
  "Whether the speed is a share of a prepayment model (its type is model), which has no prepayments of its own: a deal works them out (see deal-project-pieces)."
  (eq? (speed-curve-type curve) 'model))

(define (speed-piece-of piece)
  "A piece of a speed as (from to months), with the months '() for a piece that goes on for ever. An error that says what is wrong with it."
  (unless (and (list? piece) (<= 2 (length piece) 3) (every number? (filter (lambda (x) (not (null? x))) piece)))
    (error (format "a piece of a speed is (from to months), or (from to) for the rest of the time, not {}" piece)))
  (let ((from (car piece))
        (to (cadr piece))
        (months (if (= (length piece) 3) (caddr piece) '())))
    (when (or (< from 0) (< to 0))
      (error (format "a speed cannot be below 0, as in {}" piece)))
    (unless (null? months)
      (unless (and (integer? months) (> months 0))
        (error (format "the months of a piece of a speed are a whole number above 0, not {}" months))))
    (when (and (null? months) (not (= from to)))
      (error (format "a piece of a speed that goes on for ever is one speed: ({} {}) goes from {} to {} with no months to do it in" from to from to)))
    (list from to months)))

(define (prepayment-speed type spec)
  "A speed: the type, psa, cpr, smm or model, and the number for each month, which is one number, or a list of pieces, each (from to months) (see the
top of the file). A piece with no months, (from to), is for the rest of the time, and so must be the last, and have the same speed at both ends."
  (unless (member type speed-types)
    (error (format "the type of a speed is psa, cpr, smm or model, not {}" type)))
  (let ((pieces (map speed-piece-of (if (number? spec) (list (list spec spec)) spec))))
    (when (null? pieces)
      (error "a speed has a number, or a list of pieces"))
    (dolist (piece (butlast pieces))
      (when (null? (caddr piece))
        (error (format "a piece of a speed with no months, {}, is for the rest of the time, so it is the last" (list (car piece) (cadr piece))))))
    (make-speed-curve :type type :pieces pieces)))

(define (describe-speed curve)
  "The speed in words, as \"PSA 150\" or \"CPR: 5 for 12 months, then from 5 to 20 over 24 months, then 20 from then on\"."
  (let* ((pieces (speed-curve-pieces curve))
         (name (string-upcase (format "{}" (speed-curve-type curve)))))
    (if (and (null? (cdr pieces)) (null? (caddr (car pieces))))
        (format "{} {}" name (cadr (car pieces)))
        (format "{}: {}" name
                (string-join (map (lambda (piece)
                                    (cond ((null? (caddr piece)) (format "{} from then on" (cadr piece)))
                                          ((= (car piece) (cadr piece)) (format "{} for {} months" (cadr piece) (caddr piece)))
                                          (else (format "from {} to {} over {} months" (car piece) (cadr piece) (caddr piece)))))
                                  pieces)
                             ", then ")))))

(define (speed-in-month pieces month start)
  "The speed in the month (1, 2, ...) of the pieces, the first of which begins after `start` months: a piece goes from its `from` to its
`to` in a straight line, is at its `to` in its last month, and the speed holds at the last `to` after the last piece."
  (let* ((piece (car pieces))
         (from (car piece))
         (to (cadr piece))
         (length (caddr piece)))
    (cond ((null? length) (+ 0.0 to))
          ((<= month (+ start length)) (+ from (* (- to from) (/ (- month start) (+ 0.0 length)))))
          ((null? (cdr pieces)) (+ 0.0 to))
          (else (speed-in-month (cdr pieces) month (+ start length))))))

(define (speed-values curve months)
  "The speed in each of the months, 1 to the months, as a vector, in the units of the type."
  (let ((speeds (make-vector months 0.0)))
    (loop for month from 1 to months
          do (vector-set! speeds (- month 1) (speed-in-month (speed-curve-pieces curve) month 0)))
    speeds))

(define (speed-smms curve age months)
  "The single monthly mortality, a decimal, in each of the months, 1 to months, of loans that are `age` months old when the first of
them begins: a vector. A PSA speed is a multiple of the PSA curve at the age that the loans have in the month. A speed of a model has none of its own."
  (when (model-speed? curve)
    (error (format "{} is a share of a prepayment model, which looks at rates: a deal works out what it prepays (see deal-project-pieces), not a speed alone"
                   (describe-speed curve))))
  (let ((speeds (speed-values curve months))
        (smms (make-vector months 0.0))
        (type (speed-curve-type curve)))
    (loop for t from 0 below months
          do (vector-set! smms t
                          (cond ((eq? type 'psa) (smm-from-cpr (cpr (+ age t) (vector-ref speeds t))))
                                ((eq? type 'cpr) (smm-from-cpr (min 0.99 (/ (vector-ref speeds t) 100.0))))
                                (else (min 1.0 (/ (vector-ref speeds t) 100.0))))))
    smms))

(define (project-pool balance wac coupon months smms &key (mdrs '()) (severities '()) (lag 0))
  "The cash flows of a pool of level-pay mortgages that prepays by the single monthly mortality of each month, and, if it is given mdrs, defaults: (principal interest
balance gross-interest loss), each a vector, a month each, but the balance, which is one longer. balance is what is owed now, wac the annual rate of the loans in percent,
which they are paid off at, and gross-interest is the interest that they pay; coupon is the annual pass-through rate in percent, and interest what is paid to the investors
at it. months is the months that are left, and smms a vector with a decimal for each of them: the share of what is left after the scheduled payment that prepays.

Defaults. mdrs is a vector with a decimal for each month: the share of the loans still being paid at its start that default (the monthly default rate). The loans that
default stop paying, and are sold lag months later: what the sale brings back, (1 - severity) of their balance, the severity being that of the month they defaulted in
(severities, a vector), is paid as principal, and the rest is lost. Until the sale their interest is paid to the investors (the servicer advances it, and is paid back
from the sale, which the severity takes in), so the interest is the coupon of all that is owed. The cash flows go on for lag months after the last month."
  (let* ((length (if (null? mdrs) months (+ months lag)))
         (monthly-wac (/ wac 1200.0))
         (monthly-coupon (/ coupon 1200.0))
         (principal (make-vector length 0.0))
         (interest (make-vector length 0.0))
         (gross (make-vector length 0.0))
         (loss (make-vector length 0.0))
         (balances (make-vector (+ length 1) 0.0))
         (paying balance))                                      ; (the balance of the loans that are still being paid)
    (vector-set! balances 0 balance)
    (loop for t from 0 below length
          do (let* ((defaulted (if (or (null? mdrs) (>= t months)) 0.0 (* paying (vector-ref mdrs t))))
                    (owed (- paying defaulted))
                    (interest-due (* owed monthly-wac))
                    (scheduled (if (>= t months) 0.0 (min owed (- (payment monthly-wac (- months t) owed) interest-due))))
                    (prepaid (if (>= t months) 0.0 (* (vector-ref smms t) (- owed scheduled))))
                    (paid (min owed (+ scheduled prepaid))))
               (when (> defaulted 0.0)                          ; (the sale, lag months on)
                 (vector-update! principal (+ t lag) + (* defaulted (- 1.0 (vector-ref severities t))))
                 (vector-update! loss (+ t lag) + (* defaulted (vector-ref severities t))))
               (vector-set! gross t interest-due)
               (vector-set! interest t (* (vector-ref balances t) monthly-coupon))
               (vector-update! principal t + paid)
               (set! paying (- owed paid))
               (vector-set! balances (+ t 1) (- (vector-ref balances t) (vector-ref principal t) (vector-ref loss t)))))
    (list principal interest balances gross loss)))

(defstruct collateral-piece balance wac coupon wam (age 0)
  (loan-size '()) (credit-score '()) (ltv '()) (sato '()) (burnout '())
  (investor-share '()) (second-home-share '()) (cash-out-share '()) (refinance-share '())
  (dti '()) (one-borrower-share '()) (mi-percent '()))
; what is known of a piece of collateral, a pool of loans: the balance now, the wac and the pass-through coupon in percent, the wam, the months that are left, and the
; age, the months that the loans have gone; and what its loans are like, each '() if it is not known (see collateral-characteristics). Each is an average over the loans,
; weighted by their balances, as an agency's pool says it:
;   loan-size          the balance of a loan now, in dollars (smaller loans refinance less: the costs are much the same, and the saving is less)
;   credit-score       the borrowers' credit score when the loans were made
;   ltv                the loan-to-value now, percent, after what has been paid and what home prices have done (a borrower with little equity cannot refinance)
;   sato               the spread at origination: the wac less the survey rate of new mortgages when the loans were made, percent (a borrower who paid more than the
;                      market, most often for weaker credit, refinances less)
;   burnout            the months the loans have already had a reason to refinance and did not (an incentive above 0.75 percent, after their first year)
;   investor-share     the share of the balance (0 to 1) on investment properties
;   second-home-share  the share on second homes
;   cash-out-share     the share that was a cash-out refinance
;   refinance-share    the share that was a refinance without cash out
;   dti                the borrowers' debt-to-income when the loans were made, percent (a default model looks at it)
;   one-borrower-share the share of the balance with one borrower, not two or more (one income, which a default model looks at)
;   mi-percent         the mortgage insurance, the percent of a loss that it pays (a severity model looks at it)

(define collateral-characteristics
  (list (list "loan size" collateral-piece-loan-size collateral-piece-loan-size-set!)
        (list "credit score" collateral-piece-credit-score collateral-piece-credit-score-set!)
        (list "ltv" collateral-piece-ltv collateral-piece-ltv-set!)
        (list "sato" collateral-piece-sato collateral-piece-sato-set!)
        (list "burnout" collateral-piece-burnout collateral-piece-burnout-set!)
        (list "investor share" collateral-piece-investor-share collateral-piece-investor-share-set!)
        (list "second home share" collateral-piece-second-home-share collateral-piece-second-home-share-set!)
        (list "cash-out share" collateral-piece-cash-out-share collateral-piece-cash-out-share-set!)
        (list "refinance share" collateral-piece-refinance-share collateral-piece-refinance-share-set!)
        (list "dti" collateral-piece-dti collateral-piece-dti-set!)
        (list "one borrower share" collateral-piece-one-borrower-share collateral-piece-one-borrower-share-set!)
        (list "mi percent" collateral-piece-mi-percent collateral-piece-mi-percent-set!)))
; the slots of a collateral-piece that say what its loans are like: (the column of a table of collateral that has it, the accessor, the setter)

(define (missing-number? x)
  "Whether x is nan, the number that a table has where a value is missing (it is the one number that is not equal to itself)."
  (and (number? x) (not (= x x))))

(define (collateral-piece-of x)
  "A piece of collateral: x if it is one, or one made from a list (balance wac coupon wam [age]) of numbers (the age is 0 if it is left out). An error that says what is wrong
if it is neither."
  (cond ((collateral-piece? x) x)
        ((and (list? x) (<= 4 (length x) 5) (every number? x))
         (make-collateral-piece :balance (car x) :wac (cadr x) :coupon (caddr x) :wam (cadddr x) :age (if (= (length x) 5) (list-ref x 4) 0)))
        (else (error (format "a piece of collateral is (balance wac coupon wam [age]), numbers, not {}" x)))))

(define (collateral-piece-check piece)
  "An error unless the piece (a collateral-piece, or a list of (balance wac coupon wam [age])) is one that can be projected."
  (let* ((piece (collateral-piece-of piece))
         (wac (collateral-piece-wac piece))
         (coupon (collateral-piece-coupon piece))
         (wam (collateral-piece-wam piece))
         (age (collateral-piece-age piece)))
    (when (< wac 0)
      (error (format "the wac of a piece of collateral is in percent, from 0, not {}" wac)))
    (when (< coupon 0)
      (error (format "the pass-through coupon of a piece of collateral is in percent, from 0, not {}" coupon)))
    (when (> coupon wac)
      (error (format "the pass-through coupon of a piece of collateral, {}, is above its wac, {}: it is the wac less the fees that are taken out" coupon wac)))
    (unless (and (integer? wam) (> wam 0))
      (error (format "the wam of a piece of collateral is the months that are left, a whole number above 0, not {}" wam)))
    (unless (and (integer? age) (>= age 0))
      (error (format "the age of a piece of collateral is the months that have gone, a whole number from 0, not {}" age)))
    (collateral-characteristics-check piece)))

(define (collateral-characteristics-check piece)
  "An error unless what the piece says about its loans (see collateral-piece), where it says anything, makes sense."
  (let ((known (lambda (x) (not (null? x))))
        (check (lambda (name value ok? meaning)
                 (unless (null? value)
                   (unless (and (number? value) (ok? value))
                     (error (format "the {} of a piece of collateral is {}, not {}" name meaning value)))))))
    (check "loan size" (collateral-piece-loan-size piece) (lambda (x) (> x 0)) "the balance of a loan, in dollars, above 0")
    (check "credit score" (collateral-piece-credit-score piece) (lambda (x) (<= 300 x 850)) "from 300 to 850")
    (check "ltv" (collateral-piece-ltv piece) (lambda (x) (> x 0)) "the loan-to-value in percent, above 0")
    (check "sato" (collateral-piece-sato piece) (lambda (x) #t) "a number, in percent")
    (check "burnout" (collateral-piece-burnout piece) (lambda (x) (>= x 0)) "a number of months, from 0")
    (check "dti" (collateral-piece-dti piece) (lambda (x) (<= 0 x 100)) "the debt-to-income in percent, from 0 to 100")
    (check "one borrower share" (collateral-piece-one-borrower-share piece) (lambda (x) (<= 0 x 1)) "a share of the balance, from 0 to 1")
    (check "mi percent" (collateral-piece-mi-percent piece) (lambda (x) (<= 0 x 100)) "the percent of a loss that mortgage insurance pays, from 0 to 100")
    (dolist (share (list (list "investor share" (collateral-piece-investor-share piece))
                         (list "second home share" (collateral-piece-second-home-share piece))
                         (list "cash-out share" (collateral-piece-cash-out-share piece))
                         (list "refinance share" (collateral-piece-refinance-share piece))))
      (check (car share) (cadr share) (lambda (x) (<= 0 x 1)) "a share of the balance, from 0 to 1"))
    (let ((occupancy (filter known (list (collateral-piece-investor-share piece) (collateral-piece-second-home-share piece))))
          (purpose (filter known (list (collateral-piece-cash-out-share piece) (collateral-piece-refinance-share piece)))))
      (when (> (apply + occupancy) 1)
        (error (format "the investor share and the second home share of a piece of collateral are {} together: they are parts of one balance, so no more than 1" (apply + occupancy))))
      (when (> (apply + purpose) 1)
        (error (format "the cash-out share and the refinance share of a piece of collateral are {} together: they are parts of one balance, so no more than 1" (apply + purpose)))))))

(define (collateral-pieces-in-use pieces)
  "The pieces, as collateral-pieces, that have a balance: one with none is an empty row, and is left out. An error unless the others can be projected, and there is one.
The pieces can be collateral-pieces, or lists of (balance wac coupon wam [age])."
  (let* ((all (map collateral-piece-of pieces))
         (used (filter (lambda (piece) (not (= (collateral-piece-balance piece) 0))) all)))
    (dolist (piece used)
      (collateral-piece-check piece)
      (when (< (collateral-piece-balance piece) 0)
        (error (format "the balance of a piece of collateral is from 0, not {}" (collateral-piece-balance piece)))))
    (when (null? used)
      (error "there is no collateral: a piece of collateral is (balance wac coupon wam [age])"))
    used))

(define (smms-from-cprs cprs months)
  "The single monthly mortality, a decimal, of each of the first months of a vector of annual prepayment rates in percent (a CPR of 6 is 6): the rate for the months of a piece
of collateral that a prepayment model gives."
  (when (< (vector-length cprs) months)
    (error (format "the prepayment rates are for {} months, and the piece of collateral has {}" (vector-length cprs) months)))
  (- 1.0 (expt (- 1.0 (vector-clip (/ (vector-take cprs months) 100.0) 0.0 0.99)) (/ 1.0 12.0))))

(define (project-pieces-with pieces smms-of &key (defaults-of '()) (lag 0))
  "The cash flows of all the pieces of collateral added together: (principal interest balance gross-interest loss), each a vector, as project-pool gives, as long as the
longest piece. (smms-of piece) gives the single monthly mortality, a decimal, of each of the months of a piece, as a vector: how fast it prepays. If defaults-of is given,
(defaults-of piece) gives (mdrs severities), how many of the loans of each month default and what is lost (see project-pool), and the defaulted loans are sold lag months
later. One with no balance is left out."
  (let* ((used (collateral-pieces-in-use pieces))
         (months (+ (apply max (map collateral-piece-wam used)) (if (null? defaults-of) 0 lag)))
         (principal (make-vector months 0.0))
         (interest (make-vector months 0.0))
         (gross (make-vector months 0.0))
         (loss (make-vector months 0.0))
         (balances (make-vector (+ months 1) 0.0)))
    (dolist (piece used)
      (let* ((wam (collateral-piece-wam piece))
             (defaults (if (null? defaults-of) '() (defaults-of piece)))
             (flows (if (null? defaults)
                        (project-pool (collateral-piece-balance piece) (collateral-piece-wac piece) (collateral-piece-coupon piece) wam (smms-of piece))
                        (project-pool (collateral-piece-balance piece) (collateral-piece-wac piece) (collateral-piece-coupon piece) wam (smms-of piece)
                                      :mdrs (car defaults) :severities (cadr defaults) :lag lag)))
             (length (vector-length (car flows))))
        (loop for t from 0 below length
              do (begin (vector-update! principal t + (vector-ref (car flows) t))
                        (vector-update! interest t + (vector-ref (cadr flows) t))
                        (vector-update! gross t + (vector-ref (cadddr flows) t))
                        (vector-update! loss t + (vector-ref (list-ref flows 4) t))))
        (loop for t from 0 to length
              do (vector-update! balances t + (vector-ref (caddr flows) t)))))
    (list principal interest balances gross loss)))

(define (project-pieces pieces curve)
  "The cash flows of all the pieces of collateral at the speed (a speed-curve), added together: (principal interest balance gross-interest loss), each a vector, as project-pool
gives, as long as the longest piece. A piece is a collateral-piece, or a list (balance wac coupon wam [age]); one with no balance is left out."
  (project-pieces-with pieces
                       (lambda (piece) (speed-smms curve (collateral-piece-age piece) (collateral-piece-wam piece)))))

(define (pool-coupons interest balances)
  "The rate of interest of the pool in each month, a decimal for the year: twelve times the interest over the balance at the start
of the month, or 0 in a month with no balance. It is what a pool of pieces with different coupons pays, as one, month by month (of the
interest that is paid to the investors, the pass-through rate, or of the interest that the loans pay, the wac)."
  (let ((rates (make-vector (vector-length interest) 0.0)))
    (loop for t from 0 below (vector-length interest)
          do (unless (= (vector-ref balances t) 0.0)
               (vector-set! rates t (/ (* 12.0 (vector-ref interest t)) (vector-ref balances t)))))
    rates))
