; option_methods.lsp
;
; Three ways to value an option, on the options actually listed on a stock,
; next to the market's bids and asks:
;
;   Black-Scholes    a formula (bsm-price), for returns that are normally
;                    distributed, with a volatility that doesn't change
;   a binomial tree  the same model, made of up and down steps
;                    (american-price), which also allows for exercising
;                    the option early, as the listed options can be
;   Monte Carlo      paths of the price copied from the stock's own
;                    history, a day at a time (bootstrap-path), and what
;                    each option pays on them, discounted and averaged
;                    (option-payoffs)
;
; All three use the history's volatility (the daily log returns' spread,
; for a year of 252 trading days), count time in trading days, and grow the
; price at the interest rate (see "What risk-neutral means" in the reference
; manual). The formula and the tree are the same model, so they agree, but
; for the tree's having only so many steps and its allowing for early
; exercise -- worth little for these options, which are all out of the
; money. The paths are another model, with the history's own returns in
; place of the normal distribution. Those have fat tails: more days of big
; moves than a normal distribution would have, and more quiet days too, for
; the same volatility. So over a few days or weeks the paths value options
; near the money lower than the formula does, and options far out of the
; money higher; over longer times, many days add up to something closer to
; normal, and the two come closer together.
;
; The market agrees with none of them exactly: its volatility is the one it
; expects, not the history's (market-vol is the volatility of each
; option's price, by the formula), and it is different for each strike.
;
; Each method also gives the chance that each option ends in the money: the
; formula's (N(d2) for a call, N(-d2) for a put), the tree's (the chances of
; its last step's prices that are in the money, added up), and how many of
; the paths do. These are chances in models that grow the price at the
; interest rate, not at what the stock is expected to earn ("risk-neutral").
; The tree's last step has only 201 prices, a few percent apart, so its
; chance jumps as the strike passes each of them, and can be a few points
; from the formula's, though its price is close to the formula's: an
; option's payoff changes smoothly with the price at expiration, but whether
; it is in the money doesn't.
;
; A stock's dividends are taken off its price on their ex-dates: the last
; year's are supposed to go on, as dividend-schedule has it. The formula
; takes their present value off today's price; the tree does the same
; (escrowed dividends); and the paths' price drops by each one when it
; comes.
;
; The options compared are the liquid ones out of the money: traded today,
; with open interest and a bid, a bid-ask spread no wider than
; max-vol-spread in volatility, and calls struck at or above today's price
; and puts at or below it. Time to expiration is in trading days, not
; counting today: before the market opens, each option has one more.
;
; Usage:
;   (load "option_methods.lsp")
;   (define compared (option-methods creds "BRK/B"))       ; while the market is open
;   (show-option-methods compared)
;   (option-values-options compared)        ; the table itself, to filter, sort, or chart
;   (show-option-methods (option-methods creds "KO" :months 6 :rate 0.045))

(defstruct option-values
  symbol           ; the stock's
  price            ; the stock's price, which the options are valued at
  volatility       ; the history's, for a year
  rate             ; the interest rate
  paths            ; how many paths
  options)         ; a table: a row for each option, with what each method says of it

; ---------------------------------------------------------------------------
; The options to value
; ---------------------------------------------------------------------------

(define (option-methods--market-open?)
  "Whether the stock market is open now: from 9:30 to 4:00, New York time, on
a trading day. (This takes the computer's clock to be on New York time.)"
  (let* ((now (current-time))
         (minutes (+ (* 60 (list-ref now 3)) (list-ref now 4))))      ; since midnight
    (and (trading-day? (today)) (>= minutes (+ (* 9 60) 30)) (< minutes (* 16 60)))))

(define (option-methods--trading-days start-date expirations)
  "The trading days after start-date, up to each expiration, as a vector."
  (list->vector (map (lambda (expiration) (trading-days-between start-date expiration)) (vector->list expirations))))

(define (option-methods--dividends-present-value schedule rate days)
  "The present value, at the interest rate, of the schedule's dividends in the next `days` trading days."
  (let ((paid (table-filter schedule (<= (table-column schedule "day") days))))
    (vector-sum (* (table-column paid "amount") (exp (- (* rate (/ (table-column paid "day") 252.0))))))))

(define (option-methods--add-columns table columns)
  "The table with each (name . vector) of columns added to it."
  (if (null? columns)
      table
      (option-methods--add-columns (table-add-column table (car (car columns)) (cdr (car columns))) (cdr columns))))

(define (option-methods--with-market-vols options spot schedule rate)
  "The options, with columns added: years (to expiration, in years of 252
trading days), ex-dividend-price (today's price, less the present value of
the dividends before the option expires: the price the formula starts
from), and the volatility of each option's bid, ask, and mid, by the
formula (iv-bid, iv-ask, and market-vol)."
  (with-columns (days type strike bid ask mid) options
    (let* ((years (/ days 252.0))
           (ex-dividend (- spot (list->vector (map (lambda (d) (option-methods--dividends-present-value schedule rate d))
                                                   (vector->list days)))))
           (vol-of (lambda (price) (implied-vol price type ex-dividend strike years rate))))
      (option-methods--add-columns options (list (cons "years" years)
                                                 (cons "ex-dividend-price" ex-dividend)
                                                 (cons "iv-bid" (vol-of bid))
                                                 (cons "iv-ask" (vol-of ask))
                                                 (cons "market-vol" (vol-of mid)))))))

(define (option-methods--liquid options spot max-vol-spread)
  "The options worth comparing: traded today, with open interest and a bid,
a bid-ask spread no wider than max-vol-spread, and out of the money --
calls struck at or above today's price, and puts at or below it."
  (with-columns (type strike volume open-interest bid iv-bid iv-ask) options
    (let ((calls (= type "Call")))
      (table-filter options (vector-and (> volume 0)
                                        (> open-interest 0)
                                        (> bid 0)
                                        (<= (- iv-ask iv-bid) max-vol-spread)
                                        (vector-or (vector-and calls (>= strike spot))
                                                   (vector-and (vector-not calls) (<= strike spot))))))))

; ---------------------------------------------------------------------------
; Each method's values
; ---------------------------------------------------------------------------

(define (option-methods--values options returns spot volatility schedule rate path-count seed)
  "The table of what each method says of each option (see option-methods-for-chain)."
  (with-columns (expiration-date type strike days years ex-dividend-price bid ask market-vol) options
    (let* (; the tree, with the dividends' times in years of trading days, as years is
           (tree-dividends (if (= (table-row-count schedule) 0)
                               '()
                               (make-table "time" (/ (table-column schedule "day") 252.0)
                                           "amount" (table-column schedule "amount"))))
           ; the paths: as long as the longest option, copied a day at a time from the
           ; history, grown at the interest rate, with the dividends taken off on their days
           (fair-returns (adjust-returns returns (- (exp rate) 1)))
           (paths (map (lambda (i) (bootstrap-path fair-returns spot (vector-max days) 1
                                                   :seed (+ seed i) :dividends schedule))
                       (iota path-count)))
           (paid (option-payoffs paths days strike (= type "Call")))
           (discount (exp (- (* rate years)))))
      (make-table "expiration-date" expiration-date
                  "type" type
                  "strike" strike
                  "days" days
                  "bid" bid
                  "ask" ask
                  "black-scholes" (bsm-price type ex-dividend-price strike years rate volatility)
                  "tree" (american-price type spot strike years rate volatility :dividends tree-dividends)
                  "monte-carlo" (* discount (table-column paid "payoff"))
                  "mc-error" (* discount (table-column paid "payoff-error"))
                  "market-vol" market-vol
                  "bs-probability" (bsm-probability-in-the-money type ex-dividend-price strike years rate volatility)
                  "tree-probability" (binomial-probability-in-the-money type spot strike years rate volatility
                                                                        :dividends tree-dividends)
                  "paths-in-the-money" (table-column paid "paths-paid")
                  "paths-probability" (/ (table-column paid "paths-paid") path-count)))))

(define (option-methods-for-chain chain returns &key (symbol "") (dividends '()) (start-date (today)) (rate 0.04)
                                                (max-vol-spread 0.02) (paths 20000) (seed 1000))
  "Value the liquid options of a chain three ways -- Black-Scholes, a
binomial tree, and Monte Carlo paths of the stock's history -- as an
option-values struct, which show-option-methods shows. chain is a table as
tastytrade-option-chain makes; returns the stock's table of returns, as
daily-returns makes it, with its dividends in it if it pays any; dividends
the stock's actual dividends, as alpha-vantage-dividends makes them, of
which the last year's are supposed to go on, or '() for none; start-date
the date of the chain's prices; rate the interest rate, 0.04 for 4%;
max-vol-spread the widest bid-ask spread an option can have and be
compared, in volatility (0.02: 2 points); paths how many paths, with seeds
from seed on. The struct's options table has a row for each option:
expiration-date, type, strike, days (trading days to expiration), bid,
ask, black-scholes, tree, monte-carlo (each method's value), mc-error (the
paths' standard error), market-vol (the volatility of the option's mid, by
the formula), bs-probability, tree-probability (each one's chance that the
option ends in the money), paths-in-the-money (how many of the paths it
does on), and paths-probability (what share of them)."
  (let* ((spot (vector-ref (table-column chain "underlying-price") 0))
         (log-returns (table-column returns "log-return"))
         (moves (- log-returns (vector-mean log-returns)))
         (volatility (sqrt (* 252 (vector-mean (* moves moves)))))      ; as the paths have it
         (dated (table-add-column chain "days" (option-methods--trading-days start-date
                                                                           (table-column chain "expiration-date"))))
         (ahead (table-filter dated (> (table-column dated "days") 0)))      ; not one that expires today
         (schedule (if (null? dividends)
                       (make-table "ex-date" (vector) "day" (vector) "amount" (vector))
                       (dividend-schedule dividends start-date (vector-max (table-column ahead "days"))
                                          :repeat-last-year #t)))
         (options (option-methods--liquid (option-methods--with-market-vols ahead spot schedule rate)
                                          spot max-vol-spread)))
    (when (= (table-row-count options) 0)
      (error (format "option-methods: no option of {} is liquid enough to compare (see max-vol-spread)" symbol)))
    (make-option-values :symbol symbol :price spot :volatility volatility :rate rate :paths paths
                        :options (option-methods--values options returns spot volatility schedule rate paths seed))))

(define (option-methods creds symbol &key (months 3) (strikes 10) (rate 0.04) (max-vol-spread 0.02) (paths 20000)
                                          (seed 1000))
  "Get a stock's option chain (from tastytrade: months ahead, with the
strikes nearest the price in each expiration), its prices (from Schwab),
and its dividends (from Alpha Vantage), and value its liquid options three
ways: see option-methods-for-chain, which takes the other options, and
gives the result. Says so if the market is closed, when the bids and asks
are the last close's."
  (unless (option-methods--market-open?)
    (display "The market is closed now: the bids and asks are from its last close.\n\n"))
  (let* ((chain (tastytrade-option-chain creds symbol months strikes))
         (dividends (alpha-vantage-dividends creds symbol))
         (returns (daily-returns (schwab-price-history creds symbol) :dividends dividends)))
    (option-methods-for-chain chain returns :symbol symbol :dividends dividends :rate rate
                              :max-vol-spread max-vol-spread :paths paths :seed seed)))

; ---------------------------------------------------------------------------
; Showing them
; ---------------------------------------------------------------------------

(define (option-methods-summary compared)
  "A table with a row for each method: how many of the options its value
is between the bid and the ask for, below the bid for (the market prices
the option higher), and above the ask for (lower)."
  (let* ((options (option-values-options compared))
         (bids (table-column options "bid"))
         (asks (table-column options "ask"))
         (row (lambda (method)
                (let ((values (table-column options method)))
                  (list method
                        (vector-sum (vector-and (>= values bids) (<= values asks)))
                        (vector-sum (< values bids))
                        (vector-sum (> values asks)))))))
    (table-from-rows (map row '("black-scholes" "tree" "monte-carlo"))
                     '("method" "between-bid-and-ask" "below-the-bid" "above-the-ask"))))

(define (show-option-methods compared)
  "Show what option-methods found: each option's value by each method, next
to its bid and ask; the chance that each ends in the money, by each method;
and how often each method's value is between the bid and the ask."
  (let* ((options (option-values-options compared))
         (rows (table-row-count options))
         (the-option '("expiration-date" "type" "strike" "days")))
    (display (format "{} at {:,.2f}. Its volatility over the last ten years: {:.1%}. An interest rate of {:.0%}.\n"
                     (option-values-symbol compared) (option-values-price compared)
                     (option-values-volatility compared) (option-values-rate compared)))
    (display (format "{} options, valued from {:,} paths; days are trading days to expiration.\n\n"
                     rows (option-values-paths compared)))
    (display-table (table-select options (append the-option '("bid" "ask" "black-scholes" "tree" "monte-carlo"
                                                              "mc-error" "market-vol")))
                   '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f") ("black-scholes" ",.2f") ("tree" ",.2f")
                     ("monte-carlo" ",.2f") ("mc-error" ",.2f") ("market-vol" ".1%"))
                   :max-rows rows)
    (display "\nThe chance that each ends in the money, by each method (growing at the interest rate):\n")
    (display-table (table-select options (append the-option '("bs-probability" "tree-probability"
                                                              "paths-in-the-money" "paths-probability")))
                   '(("strike" ",.2f") ("bs-probability" ".1%") ("tree-probability" ".1%")
                     ("paths-in-the-money" ",d") ("paths-probability" ".1%"))
                   :max-rows rows)
    (display (format "\nThe market's volatility, the middle of the options': {:.1%}.\n"
                     (vector-median (table-column options "market-vol"))))
    (display-table (option-methods-summary compared))))
