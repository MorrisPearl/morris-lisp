; option_methods_example.lsp
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
; A second table has the chance that each option ends in the money, by
; each method: the formula's, the tree's, and how many of the paths do.
;
; A stock's dividends are taken off its price on their ex-dates: the last
; year's are supposed to go on, as dividend-schedule has it. The formula
; takes their present value off today's price; the tree does the same
; (escrowed dividends); and the paths' price drops by each one when it
; comes.
;
; Change `symbol` to look at another stock. It needs a tastytrade sign-in
; (the options), a Schwab sign-in ((schwab-login creds); it lasts a week)
; for the prices, and an Alpha Vantage key for the dividends: creds is set
; to the credentials file's path in init.lsp. Run it while the market is
; open, when the bids and asks are live, from the examples directory:
;   python3 ../lisp_interpreter.py option_methods_example.lsp

(define symbol "BRK/B")
(define rate 0.04)                  ; the interest rate, continuously compounded
(define months 3)                   ; how far ahead to look for expirations
(define strikes-per-expiration 10)  ; the strikes nearest the price, in each expiration
(define max-vol-spread 0.02)        ; the widest bid-ask spread an option may have, in volatility: 2 points
(define path-count 20000)

; --- 1. The options, now --------------------------------------------------------
; The market is open from 9:30 to 4:00, New York time, on a trading day. At
; other times the bids and asks are the last close's, and the stock's price
; may be from later, so the comparison means less. (This takes the
; computer's clock to be on New York time.)
(define (market-open?)
  (let* ((now (current-time))
         (minutes (+ (* 60 (list-ref now 3)) (list-ref now 4))))      ; since midnight
    (and (trading-day? (today)) (>= minutes (+ (* 9 60) 30)) (< minutes (* 16 60)))))
(unless (market-open?)
  (display "The market is closed now: the bids and asks are from its last close.\n\n"))

(define chain (tastytrade-option-chain creds symbol months strikes-per-expiration))
(define spot (vector-ref (table-column chain "underlying-price") 0))
(define start-date (today))

; --- 2. The stock's history ------------------------------------------------------
; Ten years of daily returns, with the dividends in them, and the
; volatility of those returns, as the paths have it: their spread about
; their average, for a year of 252 trading days.
(define dividends (alpha-vantage-dividends creds symbol))
(define history (daily-returns (schwab-price-history creds symbol) :dividends dividends))
(define moves (- (table-column history "log-return") (vector-mean (table-column history "log-return"))))
(define volatility (sqrt (* 252 (vector-mean (* moves moves)))))

; --- 3. The options to value -------------------------------------------------------
; Each option's time to expiration, in trading days and in years of them.
; (Today isn't counted: before the market opens, each option has a trading
; day more than this.)
(define (trading-days-to expirations)
  (list->vector (map (lambda (expiration) (trading-days-between start-date expiration)) (vector->list expirations))))
(define dated (table-add-column chain "days" (trading-days-to (table-column chain "expiration-date"))))
(define ahead (table-filter dated (> (table-column dated "days") 0)))      ; not one that expires today
(define horizon (vector-max (table-column ahead "days")))

; The dividends to come, to the last expiration: a schedule of the trading
; day (1 for tomorrow) and the amount of each.
(define schedule (dividend-schedule dividends start-date horizon :repeat-last-year #t))
(define (dividends-present-value days)
  "The present value, at the interest rate, of the dividends in the next `days` trading days."
  (let ((paid (table-filter schedule (<= (table-column schedule "day") days))))
    (vector-sum (* (table-column paid "amount") (exp (- (* rate (/ (table-column paid "day") 252.0))))))))

(define (add-columns table columns)
  "The table with each (name . vector) of columns added to it."
  (if (null? columns)
      table
      (add-columns (table-add-column table (car (car columns)) (cdr (car columns))) (cdr columns))))

; Each option's price as a volatility, by the formula: of its bid, ask, and
; mid. The price the formula starts from is today's, less the dividends
; that come before the option expires.
(define (with-market-vols options)
  (let* ((T (/ (table-column options "days") 252.0))
         (ex-dividend (- spot (list->vector (map dividends-present-value (vector->list (table-column options "days"))))))
         (vol-of (lambda (price) (implied-vol price (table-column options "type") ex-dividend
                                              (table-column options "strike") T rate))))
    (add-columns options (list (cons "T" T)
                               (cons "ex-dividend-price" ex-dividend)
                               (cons "iv-bid" (vol-of (table-column options "bid")))
                               (cons "iv-ask" (vol-of (table-column options "ask")))
                               (cons "market-vol" (vol-of (table-column options "mid")))))))
(define priced (with-market-vols ahead))

; The options worth comparing: traded today, with open interest and a bid,
; a bid-ask spread no wider than max-vol-spread, and out of the money --
; calls struck at or above today's price, and puts at or below it.
(define calls (= (table-column priced "type") "Call"))
(define strikes (table-column priced "strike"))
(define options
  (table-filter priced (vector-and (> (table-column priced "volume") 0)
                                   (> (table-column priced "open-interest") 0)
                                   (> (table-column priced "bid") 0)
                                   (<= (- (table-column priced "iv-ask") (table-column priced "iv-bid")) max-vol-spread)
                                   (vector-or (vector-and calls (>= strikes spot))
                                              (vector-and (vector-not calls) (<= strikes spot))))))
(when (= (table-row-count options) 0)
  (error (format "There are no options of {} liquid enough to compare (see max-vol-spread)." symbol)))

; --- 4. Each method's values ------------------------------------------------------
(define types (table-column options "type"))
(define option-strikes (table-column options "strike"))
(define option-days (table-column options "days"))
(define T (table-column options "T"))

; The formula, on today's price less the dividends to come before each expires.
(define black-scholes (bsm-price types (table-column options "ex-dividend-price") option-strikes T rate volatility))

; The tree, with the dividends' times in years of trading days, as T is.
(define tree-dividends
  (if (= (table-row-count schedule) 0)
      '()
      (make-table "time" (/ (table-column schedule "day") 252.0) "amount" (table-column schedule "amount"))))
(define tree (american-price types spot option-strikes T rate volatility :dividends tree-dividends))

; The paths: path-count of them, as long as the longest option, copied a day
; at a time from the history, grown at the interest rate, with the
; dividends taken off the price on their days. What each option pays on
; them, on average, discounted.
(define returns (adjust-returns history (- (exp rate) 1)))
(define paths (map (lambda (i) (bootstrap-path returns spot horizon 1 :seed (+ 1000 i) :dividends schedule))
                   (iota path-count)))
(define paid (option-payoffs paths option-days option-strikes (= types "Call")))
(define discount (exp (- (* rate T))))
(define monte-carlo (* discount (table-column paid "payoff")))
(define monte-carlo-error (* discount (table-column paid "payoff-error")))

; The chance each option ends in the money, by each method: the formula's
; (N(d2) for a call, N(-d2) for a put), the tree's (the chances of its last
; step's prices that are in the money, added up), and how many of the paths
; end in the money (option-payoffs' paths-paid: those it pays something
; on), and what share of them. These are chances in models that grow the
; price at the interest rate, not at what the stock is expected to earn
; ("risk-neutral"). The tree's last step has only 201 prices, a few percent
; apart, so its chance jumps as the strike passes each of them, and can be
; a few points from the formula's, though its price is close to the
; formula's: an option's payoff changes smoothly with the price at
; expiration, but whether it is in the money doesn't.
(define black-scholes-chance
  (bsm-probability-in-the-money types (table-column options "ex-dividend-price") option-strikes T rate volatility))
(define tree-chance
  (binomial-probability-in-the-money types spot option-strikes T rate volatility :dividends tree-dividends))
(define paths-in-the-money (table-column paid "paths-paid"))

; --- 5. Side by side --------------------------------------------------------------
(define compared
  (make-table "expiration-date" (table-column options "expiration-date")
              "type" types
              "strike" option-strikes
              "days" option-days
              "bid" (table-column options "bid")
              "ask" (table-column options "ask")
              "black-scholes" black-scholes
              "tree" tree
              "monte-carlo" monte-carlo
              "mc-error" monte-carlo-error
              "market-vol" (table-column options "market-vol")
              "bs-probability" black-scholes-chance
              "tree-probability" tree-chance
              "paths-in-the-money" paths-in-the-money
              "paths-probability" (/ paths-in-the-money path-count)))

(display (format "{} at {:,.2f}. Its volatility over the last ten years: {:.1%}. An interest rate of {:.0%}.\n"
                 symbol spot volatility rate))
(display (format "{} options, valued from {:,} paths; days are trading days to expiration.\n\n"
                 (table-row-count compared) path-count))
(define the-option '("expiration-date" "type" "strike" "days"))
(display-table (table-select compared (append the-option '("bid" "ask" "black-scholes" "tree" "monte-carlo" "mc-error"
                                                           "market-vol")))
               '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f") ("black-scholes" ",.2f") ("tree" ",.2f")
                 ("monte-carlo" ",.2f") ("mc-error" ",.2f") ("market-vol" ".1%"))
               :max-rows (table-row-count compared))

(display "\nThe chance that each ends in the money, by each method (growing at the interest rate):\n")
(display-table (table-select compared (append the-option '("bs-probability" "tree-probability" "paths-in-the-money"
                                                           "paths-probability")))
               '(("strike" ",.2f") ("bs-probability" ".1%") ("tree-probability" ".1%") ("paths-in-the-money" ",d")
                 ("paths-probability" ".1%"))
               :max-rows (table-row-count compared))

; How often each method's value is between the bid and the ask, below the
; bid (the market prices the option higher), or above the ask (lower).
(define (where-the-values-are name values)
  (let ((bids (table-column compared "bid"))
        (asks (table-column compared "ask")))
    (list name
          (vector-sum (vector-and (>= values bids) (<= values asks)))
          (vector-sum (< values bids))
          (vector-sum (> values asks)))))
(display (format "\nThe market's volatility, the middle of the options': {:.1%}.\n"
                 (vector-median (table-column compared "market-vol"))))
(display-table (table-from-rows (list (where-the-values-are "black-scholes" black-scholes)
                                      (where-the-values-are "tree" tree)
                                      (where-the-values-are "monte-carlo" monte-carlo))
                                '("method" "between-bid-and-ask" "below-the-bid" "above-the-ask")))
