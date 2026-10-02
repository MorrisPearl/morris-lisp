; vol_smile.lsp
;
; A model of implied volatility, fit to an option chain, to find the
; options whose prices are out of line with the others -- which might be
; trading opportunities.
;
; For each option:
;   T = the time to expiration, in years (days / 365)
;   F = the underlying's forward price for that time: its price now, less
;       the present value of any dividends before expiration, divided by
;       the discount factor e^(-r T), for a fixed interest rate r
;   K = log(strike / F): how far the strike is from the forward
;   Y = T * (implied volatility)^2: the option's total implied variance
;
; The implied volatilities are worked out here, from the option's bid, its
; ask, and the middle of the two, with Black's formula on the forward F.
; tastytrade's own implied volatilities come from its own forward, which
; can differ enough to make every call look rich and every put cheap; and
; the volatilities at the bid and the ask say how wide the spread really
; is, in the units the model works in.
;
; Only liquid options are used: some traded today, some open interest, a
; bid, and a spread -- the volatility at the ask less that at the bid --
; no wider than max-vol-spread. By default, only the out-of-the-money
; ones, too (calls with strikes above the forward, puts below): they're
; the more traded, and an in-the-money put's price has early exercise in
; it, which Black's formula leaves out.
;
; Then Y is fit by least absolute deviation (lad-regression, so a few
; options far out of line don't pull the fit toward them) to some of the
; terms T, sqrt(T), K, K*sqrt(T), and K^2 -- for each expiration
; separately, or for all of them at once. Within one expiration, T and
; sqrt(T) are the same for every option, so they're part of the
; intercept, and K*sqrt(T) is K times a number, so the fit for one
; expiration is a parabola in K:
;   Y = a + b K + c K^2
; Fit to all the expirations at once, all five terms can be used.
;
; An option whose implied volatility is far from the fit's is out of line.
; If the fit's volatility is below the volatility at the option's bid, the
; option could be sold for more than the model says it's worth: "rich". If
; it's above the volatility at the ask, bought for less: "cheap".
;
; Usage:
;   (load "vol_smile.lsp")
;   (define chain (tastytrade-option-chain creds "BRK/B" 4 25))
;   (define fit (fit-vol-smiles chain :rate 0.045))
;   (show-vol-smiles fit)
;   (plot-vol-smile fit (date 2026 11 20))

(define smile-terms '("T" "sqrt(T)" "K" "K*sqrt(T)" "K^2"))

; ---------------------------------------------------------------------------
; Black's formula, and implied volatility from it
; ---------------------------------------------------------------------------
; These work on vectors -- one element per option -- so a whole chain is
; priced at once. call? is a vector of 1 for each call and 0 for each put.

(define (normal-cdf x)
  (* 0.5 (+ 1.0 (erf (/ x (sqrt 2.0))))))

(define (black-price call? forward strike T discount vol)
  "The price of a European option by Black's formula:
discount * (F N(d1) - K N(d2)) for a call, discount * (K N(-d2) - F N(-d1))
for a put, with d1 = log(F/K) / (vol sqrt(T)) + vol sqrt(T) / 2 and
d2 = d1 - vol sqrt(T)."
  (let* ((spread (* vol (sqrt T)))
         (d1 (+ (/ (log (/ forward strike)) spread) (/ spread 2)))
         (d2 (- d1 spread))
         (call-price (* discount (- (* forward (normal-cdf d1)) (* strike (normal-cdf d2)))))
         (put-price (* discount (- (* strike (normal-cdf (- d2))) (* forward (normal-cdf (- d1)))))))
    (vector-where call? call-price put-price)))

(define (black-implied-vol call? price forward strike T discount)
  "The volatility at which Black's formula gives price, for each option,
found by bisection: start with the range 0.1% to 500%, and halve it 50
times, each time keeping the half the answer is in -- the price rises with
volatility, so the answer is below the middle if the middle's price is too
high. NaN where no volatility gives the price (it's below what the option
is worth at expiration, say), or the price is missing."
  (let ((low (make-vector (vector-length price) 0.001))
        (high (make-vector (vector-length price) 5.0)))
    (loop repeat 50
          do (let* ((middle (/ (+ low high) 2))
                    (too-high (> (black-price call? forward strike T discount middle) price)))
               (set! high (vector-where too-high middle high))
               (set! low (vector-where too-high low middle))))
    (let ((answer (/ (+ low high) 2)))
      ; An answer at either end of the range means no volatility fits.
      (vector-where (vector-and (> answer 0.0011) (< answer 4.999)) answer nan))))

; ---------------------------------------------------------------------------
; T, F, K, and Y for each option
; ---------------------------------------------------------------------------

(define (dividends-present-value expirations rate dividends)
  "For each expiration date, the present value of the dividends paid
before it. dividends is a list of (ex-dividend-date amount)."
  (let ((total (make-vector (vector-length expirations) 0.0)))
    (dolist (dividend dividends)
      (let* ((ex-date (first dividend))
             (amount (second dividend))
             (years (/ (days-between (today) ex-date) 365)))
        (when (> years 0)
          (set! total (+ total (* (>= expirations ex-date) amount (exp (* (- rate) years))))))))
    total))

(define (with-smile-columns chain rate dividends)
  "The chain with each option's T, discount factor, forward, K, implied
volatilities at the bid, mid, and ask, and Y added as columns."
  (let* ((column (lambda (name) (table-column chain name)))
         (T (/ (column "days-to-expiration") 365))
         (discount (exp (* (- rate) T)))
         (forward (/ (- (column "underlying-price")
                        (dividends-present-value (column "expiration-date") rate dividends))
                     discount))
         (strike (column "strike"))
         (call? (= (column "type") "Call"))
         (iv (lambda (price) (black-implied-vol call? price forward strike T discount)))
         (iv-mid (iv (column "mid"))))
    (make-table-from-columns
      chain
      (list (cons "T" T)
            (cons "discount" discount)
            (cons "forward" forward)
            (cons "K" (log (/ strike forward)))
            (cons "iv-bid" (iv (column "bid")))
            (cons "iv-mid" iv-mid)
            (cons "iv-ask" (iv (column "ask")))
            (cons "Y" (* T iv-mid iv-mid))))))

(define (make-table-from-columns table columns)
  "table with each (name . vector) in columns added."
  (dolist (column columns)
    (set! table (table-add-column table (car column) (cdr column))))
  table)

(define (liquid-options options max-vol-spread out-of-the-money-only)
  "The options worth fitting to: traded today, with open interest, a bid,
and a spread no wider than max-vol-spread in volatility; and, if
out-of-the-money-only, only calls with K >= 0 and puts with K <= 0."
  (let* ((column (lambda (name) (table-column options name)))
         (call? (= (column "type") "Call"))
         (liquid (vector-and (> (column "volume") 0)
                             (> (column "open-interest") 0)
                             (> (column "bid") 0)
                             (> (column "T") 0)
                             (<= (- (column "iv-ask") (column "iv-bid")) max-vol-spread)))
         (out-of-the-money (vector-or (vector-and call? (>= (column "K") 0))
                                      (vector-and (vector-not call?) (<= (column "K") 0)))))
    (table-filter options (if out-of-the-money-only
                              (vector-and liquid out-of-the-money)
                              liquid))))

; ---------------------------------------------------------------------------
; The fit
; ---------------------------------------------------------------------------

(define (smile-term options name)
  "The values of one of the model's terms, for each option."
  (let ((T (table-column options "T"))
        (K (table-column options "K")))
    (cond ((string=? name "T") T)
          ((string=? name "sqrt(T)") (sqrt T))
          ((string=? name "K") K)
          ((string=? name "K*sqrt(T)") (* K (sqrt T)))
          ((string=? name "K^2") (* K K))
          (else (error "fit-vol-smiles: there's no term" name "-- the terms are" smile-terms)))))

(define (smile-predictors options terms)
  (map (lambda (name) (cons name (smile-term options name))) terms))

(define (fit-smile options terms)
  "The least-absolute-deviation fit of Y to the terms, for these options."
  (lad-regression (smile-predictors options terms) (cons "Y" (table-column options "Y"))))

(define (with-fit options model terms)
  "The options with what the model says about each added as columns:
  fitted-iv     the model's implied volatility for the option
  iv-residual   iv-mid less fitted-iv: positive if the option is priced
                above the model, negative if below
  model-price   the option's price at the model's volatility
  signal        \"rich\" if the bid is above model-price, \"cheap\" if the
                ask is below it, \"\" otherwise
  edge          how far: the bid less model-price, or model-price less the
                ask (0 for neither)"
  (let* ((column (lambda (name) (table-column options name)))
         (Y (column "Y"))
         (fitted-Y (- Y (model-residuals model (smile-predictors options terms) Y)))
         (fitted-iv (sqrt (/ (max fitted-Y 0) (column "T"))))
         (model-price (black-price (= (column "type") "Call") (column "forward") (column "strike")
                                   (column "T") (column "discount") fitted-iv))
         (rich (> (column "bid") model-price))
         (cheap (< (column "ask") model-price)))
    (make-table-from-columns
      options
      (list (cons "fitted-iv" fitted-iv)
            (cons "iv-residual" (- (column "iv-mid") fitted-iv))
            (cons "model-price" model-price)
            (cons "signal" (vector-where rich "rich" (vector-where cheap "cheap" "")))
            (cons "edge" (vector-where rich (- (column "bid") model-price)
                                       (vector-where cheap (- model-price (column "ask")) 0.0)))))))

(define (parity-forward options)
  "The forward price that put-call parity implies: at the strike nearest
the forward with both a call and a put that have bids, the strike plus
(the call's mid less the put's mid) / the discount factor. If it's far
from the forward the rate (and dividends) give, the rate is off, and
the calls will tend to look rich and the puts cheap, or the other way
around. NaN if there's no such strike."
  (let ((put-mids (make-hash-table))
        (best #f)
        (best-distance #f))
    (dolist (row (table-rows options))
      (when (and (string=? (row-ref row "type") "Put") (> (row-ref row "bid") 0))
        (hash-table-set! put-mids (row-ref row "strike") (row-ref row "mid"))))
    (dolist (row (table-rows options))
      (let ((strike (row-ref row "strike"))
            (distance (abs (row-ref row "K"))))
        (when (and (string=? (row-ref row "type") "Call") (> (row-ref row "bid") 0)
                   (hash-table-has? put-mids strike)
                   (or (not best-distance) (< distance best-distance)))
          (set! best-distance distance)
          (set! best (+ strike (/ (- (row-ref row "mid") (hash-table-ref put-mids strike))
                                  (row-ref row "discount")))))))
    (or best nan)))

(define (expiration-summary all-options fitted model terms)
  "One row of the summary, for one expiration: its date, days to
expiration, forward, the forward put-call parity implies (from all its
options, liquid or not), how many options were fit, the fit's volatility
at the forward (K = 0), and the fit's coefficients. fitted is the options
that were fit -- or that would have been: model is #f if there were too
few of them."
  (let* ((T (vector-ref (table-column all-options "T") 0))
         (at-the-forward (map (lambda (name) (cond ((string=? name "T") T)
                                                   ((string=? name "sqrt(T)") (sqrt T))
                                                   (else 0)))
                              terms)))
    (append
      (list (vector-ref (table-column all-options "expiration-date") 0)
            (vector-ref (table-column all-options "days-to-expiration") 0)
            (vector-ref (table-column all-options "forward") 0)
            (parity-forward all-options)
            (table-row-count fitted))
      (if model
          (append (list (sqrt (/ (max (model-predict model at-the-forward) 0) T))
                        (model-intercept model))
                  (vector->list (model-coefficients model)))
          (loop repeat (+ 2 (length terms)) collect nan)))))     ; atm-vol, intercept, terms

(defstruct vol-smile-fit
  options          ; a table: the options fit to, with what the model says about each
  expirations      ; a table: one row per expiration -- the fit's coefficients and more
  models)          ; a list of (expiration-date . model), for model-report

(define (fit-vol-smiles chain &key (rate 0.04) (dividends '()) (max-vol-spread 0.02)
                                   (out-of-the-money-only #t) (by-expiration #t) (terms '()))
  "Fit the volatility model to an option chain, as tastytrade-option-chain
returns it. rate is the interest rate, 0.045 for 4.5%; dividends a list
of (ex-dividend-date amount); max-vol-spread the widest spread, in
volatility, an option can have and be used (0.02: 2 points). by-expiration
#t fits each expiration separately, with the terms (\"K\" \"K^2\") unless
others are given; #f fits all the expirations at once, with all five
terms unless others are given. An expiration with fewer than twice as many
options as the fit has coefficients isn't fit."
  (let* ((terms (cond ((not (null? terms)) terms)
                      (by-expiration '("K" "K^2"))
                      (else smile-terms)))
         (all-options (with-smile-columns chain rate dividends))
         (options (liquid-options all-options max-vol-spread out-of-the-money-only))
         (enough (* 2 (+ 1 (length terms))))
         (expirations (sort (vector->list (vector-unique (table-column all-options "expiration-date")))))
         (shared-model (if (or by-expiration (< (table-row-count options) enough))
                           #f
                           (fit-smile options terms)))
         (fitted '())
         (summary '())
         (models '()))
    (dolist (expiration expirations)
      (let* ((group (table-filter options (= (table-column options "expiration-date") expiration)))
             (model (cond ((= (table-row-count group) 0) #f)
                          ((not by-expiration) shared-model)
                          ((< (table-row-count group) enough) #f)
                          (else (fit-smile group terms)))))
        (when model
          (set! group (with-fit group model terms))
          (set! fitted (cons group fitted))
          (set! models (cons (cons expiration model) models)))
        (set! summary (cons (expiration-summary (table-filter all-options (= (table-column all-options "expiration-date")
                                                                             expiration))
                                                group model terms)
                            summary))))
    (make-vol-smile-fit
      :options (if (null? fitted) (table-head options 0) (apply table-append (reverse fitted)))
      :expirations (table-from-rows (reverse summary)
                                    (append '("expiration-date" "days" "forward" "parity-forward"
                                              "options" "atm-vol" "intercept")
                                            terms))
      :models (reverse models))))

; ---------------------------------------------------------------------------
; Showing the results
; ---------------------------------------------------------------------------

(define vol-smile-formats
  '(("forward" ",.2f") ("parity-forward" ",.2f") ("atm-vol" ".2%") ("strike" ",.2f")
    ("bid" ",.2f") ("ask" ",.2f") ("iv-bid" ".2%") ("iv-mid" ".2%") ("iv-ask" ".2%")
    ("fitted-iv" ".2%") ("iv-residual" "+.2%") ("model-price" ",.3f") ("edge" ",.3f")
    ("K" "+.4f") ("intercept" ".6f") ("T" ".6f") ("sqrt(T)" ".6f") ("K*sqrt(T)" ".6f") ("K^2" ".6f")))

(define (show-vol-smiles fit &key (count 10))
  "Show the fit for each expiration, the count options furthest out of
line, and every option whose bid is above the model's price or whose ask
is below it."
  (let* ((options (vol-smile-fit-options fit))
         (columns '("symbol" "type" "expiration-date" "strike" "bid" "ask" "iv-bid" "iv-mid" "iv-ask"
                    "fitted-iv" "iv-residual" "model-price" "signal" "edge"))
         (out-of-line (table-add-column options "distance" (abs (table-column options "iv-residual")))))
    (display (string-append "The fit for each expiration (atm-vol is its volatility at the forward; "
                            "parity-forward, the forward that put-call parity implies):\n"))
    (display-table (vol-smile-fit-expirations fit) vol-smile-formats)
    (display (format "\nThe {} options furthest from the fit (iv-residual is iv-mid less fitted-iv):\n" count))
    (display-table (table-select (table-head (table-sort out-of-line "distance" #t) count) columns)
                   vol-smile-formats)
    (display "\nOptions whose bid is above the model's price (rich) or ask below it (cheap):\n")
    (display-table (table-select (table-sort (table-filter options (vector-not (= (table-column options "signal") "")))
                                             "edge" #t)
                                 columns)
                   vol-smile-formats)))

(define (plot-vol-smile fit expiration)
  "A chart of one expiration's implied volatilities against strike: at the
bid, at the ask, and the fit's."
  (let ((options (table-sort (table-filter (vol-smile-fit-options fit)
                                           (= (table-column (vol-smile-fit-options fit) "expiration-date")
                                              expiration))
                             "strike")))
    (when (= (table-row-count options) 0)
      (error "plot-vol-smile: no options were fit for" expiration))
    (plot-xy-full (table-column options "strike")
                  (list (table-column options "iv-bid") (table-column options "iv-ask")
                        (table-column options "fitted-iv"))
                  (list "IV at bid" "IV at ask" "fit")
                  #f
                  (format "Implied volatility, {} expiration" expiration)
                  #f)))
