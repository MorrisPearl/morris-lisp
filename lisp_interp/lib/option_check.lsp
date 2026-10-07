; option_check.lsp
;
; An option chain's prices, checked against what simulated paths of the
; underlying's price say the options are worth -- to find the ones whose
; prices are furthest out of line.
;
; The paths come from the underlying's own history, by block bootstrap
; (daily-returns, adjust-returns, bootstrap-path), grown at the interest
; rate, with its dividends taken off the price on the dates they're
; expected (dividend-schedule, from the last year's). Every option in the
; chain is valued from the same paths: its payoff on the day it expires,
; discounted and averaged (option-payoffs). So the options' values are
; consistent with one another, and a difference between two of them is not
; noise in the paths.
;
; Then, as in vol_smile.lsp, from which the volatility and the forward come:
;   iv-mid       the implied volatility of the option's price (its mid)
;   model-iv     the implied volatility of its value from the paths
;   iv-residual  iv-mid less model-iv: positive if the option is priced
;                above the paths' value, negative if below
;   iv-vs-expiration  iv-residual less the middle (median) iv-residual of
;                the options that expire the same day
; and "rich" if the bid is above the paths' value (by more than the paths'
; own noise), "cheap" if the ask is below it. The options are sorted by how
; far iv-residual is from 0.
;
; The options' prices and the underlying's must be from the same moment. If
; the market is closed, the options' prices are the last close's, but the
; underlying's price can be one from after hours, and then calls look rich
; and puts cheap, or the other way around: all of them out of line, which
; says nothing about them. So the check first sees that the forward the
; underlying's price gives agrees with the one that put-call parity gives,
; for the first expiration, and stops if it doesn't (see forward-tolerance).
;
; What the paths know is the history, and nothing else: the volatility
; the market expects can be well above or below what the history had, and
; then most of the options come out rich, or most cheap -- by more, the
; sooner they expire, since the history says least about the next few days.
; (show-option-check says what the middle iv-residual of each expiration is;
; and iv-vs-expiration is what is left of an option's iv-residual after
; that, for finding the options that are out of line with the rest of their
; expiration.) And an option on a stock can be
; exercised early, which the paths' values leave out, so by default only
; the out-of-the-money options are used, as in vol_smile.lsp.
;
; Usage:
;   (load "option_check.lsp")
;   (define checked (check-option-prices creds "SPY" :rate 0.04))
;   (show-option-check checked)

(load "vol_smile.lsp")

(define (option-check--trading-days chain start-date)
  "For each option, the number of trading days after start-date, up to its
expiration."
  (list->vector (map (lambda (expiration) (trading-days-between start-date expiration))
                     (vector->list (table-column chain "expiration-date")))))

(define (option-check--dividend-list schedule)
  "A dividend schedule (as dividend-schedule makes it) as the list of
(ex-dividend-date amount) that with-smile-columns takes."
  (if (null? schedule)
      '()
      (map list (vector->list (table-column schedule "ex-date")) (vector->list (table-column schedule "amount")))))

(define (option-check--require-fitting-prices options tolerance)
  "Stop with an error if the underlying's price doesn't fit the options'
prices: if, for the first expiration, the forward that put-call parity gives
(parity-forward) is further from the forward the underlying's price gives
than tolerance of it."
  (let* ((first-expiration (table-where options "trading-days" (vector-min (table-column options "trading-days"))))
         (forward (vector-ref (table-column first-expiration "forward") 0))
         (discount (vector-ref (table-column first-expiration "discount") 0))
         (price (vector-ref (table-column first-expiration "underlying-price") 0))
         (parity (parity-forward first-expiration)))
    (when (> (abs (/ (- parity forward) forward)) tolerance)    ; (false if there is no parity forward: NaN)
      (error (format (string-append "check-option-chain: the options' prices don't fit the underlying's price of {:,.2f}: "
                                    "put-call parity in the options that expire {} says that its forward is {:,.2f}, "
                                    "and the price says {:,.2f}. The market may be closed, with the options' prices from "
                                    "its last close. If the underlying was at about {:,.2f} when they were made, give "
                                    "that as :start-price (and :start-date, if it was before today); or see "
                                    ":forward-tolerance, if the rate or the dividends are what's off.")
                     price (vector-ref (table-column first-expiration "expiration-date") 0) parity forward
                     (+ price (* (- parity forward) discount)))))))

(define (option-check--paths options returns schedule rate paths block-size seed)
  "A list of simulated paths of the underlying's price, as many days long as
the longest option has. The returns are adjusted to grow at the interest
rate; the schedule's dividends come off the price."
  (let ((horizon (vector-max (table-column options "trading-days")))
        (start-price (vector-ref (table-column options "underlying-price") 0))
        (fair-returns (adjust-returns returns (- (exp rate) 1))))
    (map (lambda (i) (bootstrap-path fair-returns start-price horizon block-size
                                     :seed (+ seed i) :dividends schedule))
         (iota paths))))

(define option-check-columns
  '("symbol" "type" "expiration-date" "days-to-expiration" "strike" "bid" "ask" "iv-bid" "iv-mid" "iv-ask"
    "model-price" "standard-error" "paths-paid" "model-iv" "iv-residual" "iv-vs-expiration" "signal" "edge"))

(define (option-check--typical-by-expiration options)
  "For each option, the middle (median) iv-residual of the options that
expire the same day."
  (let ((typical (make-hash-table))
        (expirations (table-column options "expiration-date")))
    (dolist (expiration (vector->list (vector-unique expirations)))
      (hash-table-set! typical expiration
                       (vector-median (table-column (table-where options "expiration-date" expiration) "iv-residual"))))
    (list->vector (map (lambda (expiration) (hash-table-ref typical expiration)) (vector->list expirations)))))

(define (option-check--compare options simulated min-paths-paid standard-errors)
  "The options with what the paths say about each added as columns, as
check-option-chain says, the ones the paths say too little about left out,
and the rest in order of how far out of line they are."
  (let* ((payoffs (option-payoffs simulated (table-column options "trading-days") (table-column options "strike")
                                  (= (table-column options "type") "Call")))
         (with-payoffs (make-table-from-columns options payoffs)))
    (with-columns (payoff payoff-error paths-paid type forward strike T discount bid ask iv-mid) with-payoffs
      (let* ((model-price (* discount payoff))
             (standard-error (* discount payoff-error))
             (model-iv (black-implied-vol (= type "Call") model-price forward strike T discount))
             (rich (> bid (+ model-price (* standard-errors standard-error))))
             (cheap (< ask (- model-price (* standard-errors standard-error))))
             (compared (make-table-from-columns
                         with-payoffs
                         (list (cons "model-price" model-price)
                               (cons "standard-error" standard-error)
                               (cons "model-iv" model-iv)
                               (cons "iv-residual" (- iv-mid model-iv))
                               (cons "signal" (vector-where rich "rich" (vector-where cheap "cheap" "")))
                               (cons "edge" (vector-where rich (- bid model-price)
                                                          (vector-where cheap (- model-price ask) 0.0))))))
             (enough (table-filter compared (vector-and (>= paths-paid min-paths-paid)
                                                        (vector-not (vector-nan? (table-column compared "iv-residual")))))))
        (if (= (table-row-count enough) 0)
            (table-select (table-add-column enough "iv-vs-expiration" nan) option-check-columns)
            (let ((with-typical (table-add-column enough "iv-vs-expiration"
                                                  (- (table-column enough "iv-residual")
                                                     (option-check--typical-by-expiration enough)))))
              (table-select (table-sort (table-add-column with-typical "distance"
                                                          (abs (table-column with-typical "iv-residual")))
                                        "distance" #t)
                            option-check-columns)))))))

(define (check-option-chain chain returns &key (start-date (today)) (start-price '()) (rate 0.04) (dividends '())
                                               (paths 5000) (block-size 10) (seed 1) (max-vol-spread 0.02)
                                               (out-of-the-money-only #t) (min-paths-paid 50) (standard-errors 2)
                                               (forward-tolerance 0.002))
  "Check an option chain's prices against values from simulated paths.
chain is a table as tastytrade-option-chain makes; returns is the
underlying's table of returns, as daily-returns makes it (with its
dividends, if it pays any); start-date is the date of the chain's prices,
and start-price the underlying's price then, which the chain's
underlying-price is unless it's given (the time to each expiration is
counted from start-date, not from the chain's days-to-expiration); rate is the interest rate, 0.04 for
4%; dividends is the table of the
underlying's actual dividends, as alpha-vantage-dividends makes it, whose
last year is supposed to go on, or '() for none; paths is how many paths,
each made of blocks of block-size days, with seeds from seed on;
max-vol-spread is the widest spread, in volatility, an option can have and
be used (0.02: 2 points); out-of-the-money-only #t uses only calls with
strikes at or above the forward and puts at or below it; an option the
paths pay on fewer than min-paths-paid of is left out, because the paths
say too little about it; and a bid has to be above the value, or an ask
below it, by standard-errors of the paths' own error to count as rich or
cheap. forward-tolerance is how far the forward from put-call parity may be
from the one the underlying's price gives, in the first expiration, as a
fraction of it: 0.002 is 0.2%.

The result is a table, the options furthest out of line first, with these
columns added to the chain's own: model-price, the value from the paths;
standard-error, its error from there being only so many paths; paths-paid;
model-iv, the volatility of that price; iv-residual, iv-mid less model-iv;
iv-vs-expiration, iv-residual less the middle one of the options that expire
the same day; signal, \"rich\" if the bid is above model-price, \"cheap\" if the ask is
below it, \"\" if neither; and edge, how far: the bid less model-price, or
model-price less the ask (0 for neither)."
  (let* ((priced (if (null? start-price) chain (table-add-column chain "underlying-price" start-price)))
         (calendar-days (days-between start-date (table-column priced "expiration-date")))
         (trading-days (option-check--trading-days priced start-date))
         (ahead (table-filter (table-add-column (table-add-column priced "days-to-expiration" calendar-days)
                                                "trading-days" trading-days)
                              (> trading-days 0))))
    (when (= (table-row-count ahead) 0)
      (error "check-option-chain: there is no option that expires after" start-date))
    (let* ((last-day (vector-max (table-column ahead "trading-days")))
           (schedule (if (null? dividends)
                         '()
                         (dividend-schedule dividends start-date last-day :repeat-last-year #t)))
           (all-options (with-smile-columns ahead rate (option-check--dividend-list schedule)))
           (options (liquid-options all-options max-vol-spread out-of-the-money-only)))
      (option-check--require-fitting-prices all-options forward-tolerance)
      (when (= (table-row-count options) 0)
        (error "check-option-chain: no option is liquid enough to check -- see max-vol-spread"))
      (option-check--compare options
                             (option-check--paths options returns schedule rate paths block-size seed)
                             min-paths-paid standard-errors))))

(define (check-option-prices creds symbol &key (months 3) (strikes 15) (start-date (today)) (start-price '())
                                               (rate 0.04) (paths 5000) (block-size 10) (seed 1)
                                               (max-vol-spread 0.02) (out-of-the-money-only #t)
                                               (min-paths-paid 50) (standard-errors 2) (forward-tolerance 0.002))
  "Get an underlying's option chain (from tastytrade; months ahead, with
the strikes nearest the price), its prices (from Schwab) and dividends
(from Alpha Vantage), make paths, value every option from them, and check
the chain's prices against the values: see check-option-chain, which
takes the other arguments, and gives the result."
  (let* ((chain (tastytrade-option-chain creds symbol months strikes))
         (dividends (alpha-vantage-dividends creds symbol))
         (returns (daily-returns (schwab-price-history creds symbol) :dividends dividends)))
    (check-option-chain chain returns :start-date start-date :start-price start-price :rate rate
                        :dividends dividends :paths paths :block-size block-size :seed seed
                        :max-vol-spread max-vol-spread :out-of-the-money-only out-of-the-money-only
                        :min-paths-paid min-paths-paid :standard-errors standard-errors
                        :forward-tolerance forward-tolerance)))

; ---------------------------------------------------------------------------
; Showing the results
; ---------------------------------------------------------------------------

(define option-check-formats
  '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f") ("iv-bid" ".1%") ("iv-mid" ".1%") ("iv-ask" ".1%")
    ("model-price" ",.3f") ("standard-error" ",.3f") ("paths-paid" ",.0f") ("model-iv" ".1%")
    ("iv-residual" "+.1%") ("iv-vs-expiration" "+.1%") ("median-iv-residual" "+.1%") ("edge" ",.3f")))

(define (option-check-expirations checked)
  "A table with a row for each expiration: how many options were checked,
the middle iv-residual of them, and how many are rich and cheap."
  (let ((rows '()))
    (dolist (expiration (sort (vector->list (vector-unique (table-column checked "expiration-date")))))
      (let ((group (table-where checked "expiration-date" expiration)))
        (push (list expiration
                    (vector-ref (table-column group "days-to-expiration") 0)
                    (table-row-count group)
                    (vector-median (table-column group "iv-residual"))
                    (table-row-count (table-where group "signal" "rich"))
                    (table-row-count (table-where group "signal" "cheap")))
              rows)))
    (table-from-rows (reverse rows) '("expiration-date" "days-to-expiration" "options" "median-iv-residual" "rich" "cheap"))))

(define (show-option-check checked &key (count 10))
  "Show the middle iv-residual of each expiration, the count options
furthest from the paths' values, the count furthest from their expiration's
middle iv-residual, and every option whose bid is above the paths' value or
whose ask is below it."
  (let ((columns (table-column-names checked))
        (by-expiration (table-add-column checked "distance" (abs (table-column checked "iv-vs-expiration")))))
    (display (format "{} options. The middle iv-residual, the market's volatility less the paths', in each expiration:\n"
                     (table-row-count checked)))
    (display-table (option-check-expirations checked) option-check-formats)
    (display (format "\nThe {} options furthest from the paths' values (iv-residual is iv-mid less model-iv):\n" count))
    (display-table (table-head checked count) option-check-formats)
    (display (format "\nThe {} furthest from the middle iv-residual of their expiration (iv-vs-expiration):\n" count))
    (display-table (table-select (table-head (table-sort by-expiration "distance" #t) count) columns)
                   option-check-formats)
    (display "\nOptions whose bid is above the paths' value (rich) or ask below it (cheap):\n")
    (display-table (table-sort (table-filter checked (vector-not (= (table-column checked "signal") ""))) "edge" #t)
                   option-check-formats)))
