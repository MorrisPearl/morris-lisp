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
; Two things can be asked for. :match-volatility #t multiplies the paths'
; volatility by the one number that brings the paths' values into line with
; the market's prices overall (the middle iv-residual becomes 0), so that
; the options that are out of line are those out of line with the market's
; general level of volatility, and not with the history's. And
; :expected-return, the underlying's expected annual return, makes a second
; set of paths, the same ones but for that growth, and adds what each option
; is worth if the underlying does earn that, and whether that favors buying
; or selling it. That is an expected value: it is not adjusted for risk, and
; a call is expected to earn more than the interest rate whenever the
; underlying is.
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
; expiration.) :volatility #t helps with the next few days: the paths start
; at today's volatility, as a volatility model (volatility-model) fitted to
; the history estimates it, and go back toward the history's, as the model
; says, instead of being as wild as the history is on average from the
; start. And an option on a stock can be
; exercised early, which the paths' values leave out, so by default only
; the out-of-the-money options are used, as in vol_smile.lsp. Or, with
; :early-exercise #t, what the right to exercise early is worth (from a
; binomial tree, american-price, at the option's own implied volatility)
; is taken off its bid and ask before they are compared with the paths'
; European values, and added to the value after: then an in-the-money
; option can be checked too.
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

(define (option-check--tree-dividends schedule start-date)
  "A dividend schedule (as dividend-schedule makes it) as the table of time,
in years from start-date, and amount that american-price takes; '() for
none."
  (if (null? schedule)
      '()
      (make-table "time" (/ (days-between start-date (table-column schedule "ex-date")) 365.0)
                  "amount" (table-column schedule "amount"))))

(define (option-check--without-early-exercise options schedule start-date rate)
  "The options as if they could be exercised only when they expire: what
the right to exercise early is worth, the American price less the European
one, both by binomial tree (american-price, 100 steps) at the option's own
implied volatility, is in a column early-exercise, and is taken off the
bid, ask, and mid; then the implied volatilities are found again."
  (with-columns (type underlying-price strike T iv-mid bid ask mid) options
    (let* ((dividends (option-check--tree-dividends schedule start-date))
           (premium (- (american-price type underlying-price strike T rate iv-mid :dividends dividends :steps 100)
                       (american-price type underlying-price strike T rate iv-mid :dividends dividends :steps 100
                                       :early-exercise #f))))
      (with-smile-columns (make-table-from-columns options (list (cons "early-exercise" premium)
                                                                 (cons "bid" (- bid premium))
                                                                 (cons "ask" (- ask premium))
                                                                 (cons "mid" (- mid premium))))
                          rate schedule start-date))))

(define (option-check--with-early-exercise checked)
  "The checked options with the right to exercise early added back: to the
bid and ask, which are then the market's again, to model-price, which is
then the paths' value of the option that can be exercised early, and to
expected-value, if there is one."
  (let* ((premium (table-column checked "early-exercise"))
         (prices (list (cons "bid" (+ (table-column checked "bid") premium))
                       (cons "ask" (+ (table-column checked "ask") premium))
                       (cons "model-price" (+ (table-column checked "model-price") premium)))))
    (make-table-from-columns checked
                             (if (member "expected-value" (table-column-names checked))
                                 (cons (cons "expected-value" (+ (table-column checked "expected-value") premium)) prices)
                                 prices))))

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

(define (option-check--payoffs options returns schedule annual-return scale paths block-size seed
                              model start-volatility)
  "What each option pays on average at its expiration (option-payoffs), over
simulated paths of the underlying's price as long as the longest option has.
The returns are adjusted to grow at annual-return, with their volatility
multiplied by scale; the schedule's dividends come off the price. With
model, a volatility model ('() for none), the paths' volatility starts at
the model's today's (times scale), or at start-volatility, if it isn't '()."
  (let* ((horizon (vector-max (table-column options "trading-days")))
         (start-price (vector-ref (table-column options "underlying-price") 0))
         (adjusted (adjust-returns returns annual-return :volatility-scale scale))
         (simulated (map (lambda (i) (bootstrap-path adjusted start-price horizon block-size
                                                       :seed (+ seed i) :dividends schedule
                                                       :volatility model :start-volatility start-volatility))
                         (iota paths))))
    (option-payoffs simulated (table-column options "trading-days") (table-column options "strike")
                    (= (table-column options "type") "Call"))))

(define option-check-columns
  '("symbol" "type" "expiration-date" "days-to-expiration" "strike" "bid" "ask" "iv-bid" "iv-mid" "iv-ask"
    "model-price" "standard-error" "paths-paid" "model-iv" "iv-residual" "iv-vs-expiration" "signal" "edge"))

(define option-check-expected-columns '("expected-value" "favors" "expected-profit"))

(define (option-check--typical-by-expiration options)
  "For each option, the middle (median) iv-residual of the options that
expire the same day."
  (let ((typical (make-hash-table))
        (expirations (table-column options "expiration-date")))
    (dolist (expiration (vector->list (vector-unique expirations)))
      (hash-table-set! typical expiration
                       (vector-median (table-column (table-where options "expiration-date" expiration) "iv-residual"))))
    (list->vector (map (lambda (expiration) (hash-table-ref typical expiration)) (vector->list expirations)))))

(define (option-check--expected real-payoffs discount bid ask standard-errors)
  "The columns about what each option is worth if the underlying earns its
expected return, as (name . vector) pairs; none if real-payoffs, what the
options pay on average over paths with that return, is '(). expected-value
is the present value of that, at the interest rate; favors, \"buying\" if it is
above the ask (by standard-errors of its error) and \"selling\" if below the
bid; and expected-profit how far."
  (if (null? real-payoffs)
      '()
      (let* ((expected-value (* discount (table-column real-payoffs "payoff")))
             (expected-error (* discount (table-column real-payoffs "payoff-error")))
             (buy (> (- expected-value (* standard-errors expected-error)) ask))
             (sell (< (+ expected-value (* standard-errors expected-error)) bid)))
        (list (cons "expected-value" expected-value)
              (cons "favors" (vector-where buy "buying" (vector-where sell "selling" "")))
              (cons "expected-profit" (vector-where buy (- expected-value ask)
                                                    (vector-where sell (- bid expected-value) 0.0)))))))

(define (option-check--compare options payoffs real-payoffs min-paths-paid standard-errors)
  "The options with what the paths say about each added as columns, as
check-option-chain says, the ones the paths say too little about left out,
and the rest in order of how far out of line they are. payoffs is what the
options pay on average (option-payoffs) over paths that grow at the interest
rate, and real-payoffs the same over paths with the underlying's expected
return, or '() for no expected return."
  (let ((with-payoffs (make-table-from-columns options payoffs))
        (columns (append option-check-columns
                         (if (member "early-exercise" (table-column-names options)) '("early-exercise") '())
                         (if (null? real-payoffs) '() option-check-expected-columns))))
    (with-columns (payoff payoff-error paths-paid type forward strike T discount bid ask iv-mid) with-payoffs
      (let* ((model-price (* discount payoff))
             (standard-error (* discount payoff-error))
             (model-iv (black-implied-vol (= type "Call") model-price forward strike T discount))
             (rich (> bid (+ model-price (* standard-errors standard-error))))
             (cheap (< ask (- model-price (* standard-errors standard-error))))
             (compared (make-table-from-columns
                         with-payoffs
                         (append (list (cons "model-price" model-price)
                                       (cons "standard-error" standard-error)
                                       (cons "model-iv" model-iv)
                                       (cons "iv-residual" (- iv-mid model-iv))
                                       (cons "signal" (vector-where rich "rich" (vector-where cheap "cheap" "")))
                                       (cons "edge" (vector-where rich (- bid model-price)
                                                                  (vector-where cheap (- model-price ask) 0.0))))
                                 (option-check--expected real-payoffs discount bid ask standard-errors))))
             (enough (table-filter compared (vector-and (>= paths-paid min-paths-paid)
                                                        (vector-not (vector-nan? (table-column compared "iv-residual")))))))
        (if (= (table-row-count enough) 0)
            (table-select (table-add-column enough "iv-vs-expiration" nan) columns)
            (let ((with-typical (table-add-column enough "iv-vs-expiration"
                                                  (- (table-column enough "iv-residual")
                                                     (option-check--typical-by-expiration enough)))))
              (table-select (table-sort (table-add-column with-typical "distance"
                                                          (abs (table-column with-typical "iv-residual")))
                                        "distance" #t)
                            columns)))))))

(define (option-check--fit-scale compared-at scale tries)
  "The number to multiply the history's volatility by, to bring the paths'
values into line with the market's prices overall: try scale, and if the
middle ratio of the options' iv-mid to their model-iv isn't within 0.2% of
1, multiply scale by it (an option's model-iv is about in proportion to the
volatility of the paths) and try again, up to tries times. compared-at is a
procedure from a scale to the options compared (option-check--compare)."
  (let ((compared (compared-at scale)))
    (when (= (table-row-count compared) 0)
      (error "check-option-chain: there is no option to match the volatility with"))
    (let ((ratio (vector-median (/ (table-column compared "iv-mid") (table-column compared "model-iv")))))
      (cond ((< (abs (- ratio 1)) 0.002) scale)
            ((= tries 1) (* scale ratio))
            (else (option-check--fit-scale compared-at (* scale ratio) (- tries 1)))))))

(define (check-option-chain chain returns &key (start-date (today)) (start-price '()) (rate 0.04) (dividends '())
                                               (paths 5000) (block-size 10) (seed 1) (max-vol-spread 0.02)
                                               (out-of-the-money-only #t) (min-paths-paid 50) (standard-errors 2)
                                               (forward-tolerance 0.002) (expected-return '())
                                               (match-volatility #f) (early-exercise #f)
                                               (volatility #f) (start-volatility '()))
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
fraction of it: 0.002 is 0.2%. match-volatility #t multiplies the paths'
volatility by the number that makes the middle iv-residual 0 (adds the
column volatility-scale, which has it). expected-return is the underlying's
expected annual return, dividends included, 0.08 for 8%: with it, the
columns expected-value, favors, and expected-profit are added.
early-exercise #t takes what the right to exercise early is worth off the
options' prices before comparing them with the paths' European values, and
adds it to the values after (the column early-exercise has it): for
checking in-the-money options too (out-of-the-money-only #f). The
implied volatilities are then of the prices without it. volatility #t
fits a volatility model to the returns (volatility-model), or volatility
can be one (one row, for the returns' log-return column); then the paths'
volatility starts at the model's today's, or at start-volatility, for a
year, if that's given, and goes back toward the history's, and the
columns start-volatility and long-run-volatility have those two.

The result is a table, the options furthest out of line first, with these
columns added to the chain's own: model-price, the value from the paths;
standard-error, its error from there being only so many paths; paths-paid;
model-iv, the volatility of that price; iv-residual, iv-mid less model-iv;
iv-vs-expiration, iv-residual less the middle one of the options that expire
the same day; signal, \"rich\" if the bid is above model-price, \"cheap\" if the ask is
below it, \"\" if neither; and edge, how far: the bid less model-price, or
model-price less the ask (0 for neither). With expected-return: expected-value,
the present value of what the option pays on average if the underlying earns
that (with the same volatility), at the interest rate; favors, \"buying\" if
that is above the ask by standard-errors of its error, \"selling\" if it is below the bid
by that, \"\" if neither; and expected-profit, how far: expected-value less
the ask, or the bid less expected-value (0 for neither). These are expected
values: they are not adjusted for risk."
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
           (as-quoted (with-smile-columns ahead rate schedule start-date))
           (all-options (if early-exercise
                            (option-check--without-early-exercise as-quoted schedule start-date rate)
                            as-quoted))
           (options (liquid-options all-options max-vol-spread out-of-the-money-only)))
      (option-check--require-fitting-prices all-options forward-tolerance)
      (when (= (table-row-count options) 0)
        (error "check-option-chain: no option is liquid enough to check -- see max-vol-spread"))
      (let* ((risk-neutral (- (exp rate) 1))
             (model (cond ((eq? volatility #t) (volatility-model returns))
                          ((or (not volatility) (null? volatility)) '())
                          (else volatility)))
             (payoffs-at (lambda (annual-return scale)
                           (option-check--payoffs options returns schedule annual-return scale paths block-size seed
                                                  model start-volatility)))
             (compared-at (lambda (scale)
                            (option-check--compare options (payoffs-at risk-neutral scale) '()
                                                   min-paths-paid standard-errors)))
             (scale (if match-volatility (option-check--fit-scale compared-at 1.0 5) 1.0))
             (real-payoffs (if (null? expected-return) '() (payoffs-at expected-return scale)))
             (compared (option-check--compare options (payoffs-at risk-neutral scale) real-payoffs
                                              min-paths-paid standard-errors))
             (checked (if early-exercise (option-check--with-early-exercise compared) compared))
             (scaled (if match-volatility (table-add-column checked "volatility-scale" scale) checked)))
        (if (null? model)
            scaled
            (let ((start (if (null? start-volatility)
                             (* scale (vector-ref (table-column model "next-day-volatility") 0))
                             start-volatility))
                  (long-run (* scale (vector-ref (table-column model "long-run-volatility") 0))))
              (table-add-column (table-add-column scaled "start-volatility" start) "long-run-volatility" long-run)))))))

(define (check-option-prices creds symbol &key (months 3) (strikes 15) (start-date (today)) (start-price '())
                                               (rate 0.04) (paths 5000) (block-size 10) (seed 1)
                                               (max-vol-spread 0.02) (out-of-the-money-only #t)
                                               (min-paths-paid 50) (standard-errors 2) (forward-tolerance 0.002)
                                               (expected-return '()) (match-volatility #f) (early-exercise #f)
                                               (volatility #f) (start-volatility '()))
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
                        :forward-tolerance forward-tolerance :expected-return expected-return
                        :match-volatility match-volatility :early-exercise early-exercise
                        :volatility volatility :start-volatility start-volatility)))

; ---------------------------------------------------------------------------
; Showing the results
; ---------------------------------------------------------------------------

(define option-check-formats
  '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f") ("iv-bid" ".1%") ("iv-mid" ".1%") ("iv-ask" ".1%")
    ("model-price" ",.3f") ("standard-error" ",.3f") ("paths-paid" ",.0f") ("model-iv" ".1%")
    ("iv-residual" "+.1%") ("iv-vs-expiration" "+.1%") ("median-iv-residual" "+.1%") ("edge" ",.3f")
    ("expected-value" ",.3f") ("expected-profit" ",.3f") ("volatility-scale" ".3f") ("early-exercise" ",.3f")
    ("start-volatility" ".1%") ("long-run-volatility" ".1%")))

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
whose ask is below it; and, if there is an expected return, the count
options whose expected profit is greatest."
  (let* ((matched (member "volatility-scale" (table-column-names checked)))
         (scale (if matched (vector-ref (table-column checked "volatility-scale") 0) 1.0))
         (modeled (member "start-volatility" (table-column-names checked)))
         (start (if modeled (vector-ref (table-column checked "start-volatility") 0) 0.0))
         (long-run (if modeled (vector-ref (table-column checked "long-run-volatility") 0) 0.0))
         (checked (if matched (table-drop-columns checked "volatility-scale") checked))       ; (said here instead)
         (checked (if modeled (table-drop-columns checked '("start-volatility" "long-run-volatility")) checked))
         (columns (table-column-names checked))
         (by-expiration (table-add-column checked "distance" (abs (table-column checked "iv-vs-expiration")))))
    (when matched
      (display (format "The paths' volatility was multiplied by {:.3f}, to match the market's overall level.\n" scale)))
    (when modeled
      (display (format (string-append "The paths' volatility started at {:.1%} and went back toward {:.1%}, "
                                      "as the volatility model says.\n")
                       start long-run)))
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
                   option-check-formats)
    (when (member "expected-profit" columns)
      (display (format "\nThe {} options with the most expected profit if the underlying earns its expected return,\n" count))
      (display "buying at the ask or selling at the bid (an expected value: not adjusted for risk):\n")
      (display-table (table-head (table-sort checked "expected-profit" #t) count) option-check-formats))))
