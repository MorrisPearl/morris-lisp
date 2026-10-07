; investment_paths_example.lsp
;
; Simulating an investment's future prices from its own past: copy blocks of
; consecutive days from its history, end to end, until there's a year of
; them -- see "Simulating investment prices" in the reference manual.
;
; It needs a Schwab sign-in for the prices ((schwab-login creds); it lasts
; a week), and an "alpha_vantage_api_key" entry in the credentials file for
; the dividends. creds is set to its path in init.lsp.
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py investment_paths_example.lsp

; --- 1. Dividends are part of an investment's return -------------------------
; Schwab's prices aren't adjusted for dividends, so on the day an investment
; goes ex-dividend its price drops, and the return from the prices alone is
; low by what it pays. Alpha Vantage has the dividends themselves.
(define spy-prices (schwab-price-history creds "SPY"))
(define spy-dividends (alpha-vantage-dividends creds "SPY"))
(define (average-yearly-return returns)      ; log returns, 252 trading days a year
  (* 252 (vector-mean (table-column returns "log-return"))))
(display (format "SPY, from its prices alone:   {:.2%} a year\n"
                 (average-yearly-return (daily-returns spy-prices))))
(display (format "SPY, with its dividends:      {:.2%} a year\n"
                 (average-yearly-return (daily-returns spy-prices :dividends spy-dividends))))

; --- 2. Berkshire Hathaway, which pays none ----------------------------------------
; The ten years of prices Schwab gives, as a table of daily log returns.
(define prices (schwab-price-history creds "BRK/A"))
(define history (daily-returns prices))
(define volatility (* (sqrt 252) (vector-stdev (table-column history "log-return"))))   ; a year's
(display (format "\nBRK/A: {} daily returns, {:.1%} a year on average, volatility {:.1%} a year\n"
                 (table-row-count history)
                 (average-yearly-return history)
                 volatility))

; Take that average out, and put in the return we expect: 8% a year.
(define returns (adjust-returns history 0.08))

; --- 3. A thousand paths ---------------------------------------------------------------
; Each path starts at today's price and goes 252 trading days, in blocks of
; 10 days. A different seed for each path makes each one different, and the
; whole run the same every time.
(define start-price (vector-ref (table-column prices "close") (- (table-row-count prices) 1)))
(define (one-path i) (bootstrap-path returns start-price 252 10 :seed (+ 1000 i)))
(define paths (map one-path (iota 1000)))

; Where the paths end up, as the change from today's price.
(define year-returns
  (vector-sub (vector-div (list->vector (map (lambda (path) (vector-ref path 251)) paths)) start-price) 1))
(display (format "\nBRK/A today: {:,.2f}\nAfter a year, of 1000 paths:\n" start-price))
(dolist (fraction '(0.05 0.25 0.5 0.75 0.95))
  (display (format "  {:>4.0%} of the paths ended below {:>+7.1%}\n" fraction (vector-quantile year-returns fraction))))
(display (format "  the average path ended {:+.1%}; {:.0%} of the paths lost money\n"
                 (vector-mean year-returns) (vector-mean (> 0 year-returns))))
(plot-histogram year-returns :bins 30 :x-format "{:+.0%}" :title "BRK/A, a year from now"
                :x-label "change from today's price")

; --- 4. An option ----------------------------------------------------------------
; What is a one-year call on it, struck at today's price, worth? Each path
; pays the final price less the strike, or nothing; option-value discounts
; those payments and averages them. For that to be a fair value, though, the
; paths must grow at the interest rate -- 4% here, continuously compounded --
; and not at the 8% we expect, so the returns are adjusted to e^0.04 - 1.
; (Blocks of one day, so that the volatility is the history's, and the value
; can be compared with Black-Scholes. Longer blocks keep what the history did
; over several days, which for BRK/A is lower volatility, and a cheaper call.)
(load "implied_vol.lsp")
(define rate 0.04)
(define fair-returns (adjust-returns history (- (exp rate) 1)))
(define fair-paths
  (map (lambda (i) (bootstrap-path fair-returns start-price 252 1 :seed (+ 1000 i))) (iota 5000)))
(define (call-pays path) (max 0 (- (vector-ref path 251) start-price)))
(define call (option-value fair-paths call-pays rate 1.0))
(display (format "\nA one-year call on BRK/A, struck at today's price:\n  from 5000 paths: {:,.0f} +/- {:,.0f}\n  Black-Scholes, with the history's volatility: {:,.0f}\n"
                 (first call) (second call)
                 (bsm-price "call" start-price start-price 1.0 rate volatility)))

; --- 5. An option on an investment that pays dividends ----------------------------
; SPY pays a dividend every three months. Its returns are total returns, with
; the dividends in them, as in section 1; and the schedule takes each dividend
; off the price on its ex-date, in every path. Here the schedule supposes that
; the last year's dividends go on, on the same dates and in the same amounts,
; as far as the path goes: three months of trading days, 63 of them. The days
; are counted with the NYSE's calendar. An option that ended before the next
; ex-date wouldn't have a dividend taken off.
(define spy-days 63)
(define spy-last-date (vector-ref (table-column spy-prices "date") (- (table-row-count spy-prices) 1)))
(define spy-start-price (vector-ref (table-column spy-prices "close") (- (table-row-count spy-prices) 1)))
(define spy-returns (adjust-returns (daily-returns spy-prices :dividends spy-dividends) (- (exp rate) 1)))
(define spy-schedule (dividend-schedule spy-dividends spy-last-date spy-days :repeat-last-year #t))
(display (format "\nSPY's dividends in the next {} trading days, after {}:\n" spy-days spy-last-date))
(display-table spy-schedule)

(define (spy-call-value schedule)           ; a call struck at today's price, with this schedule
  (let ((paths (map (lambda (i) (bootstrap-path spy-returns spy-start-price spy-days 1
                                                :seed (+ 1000 i) :dividends schedule))
                    (iota 5000))))
    (option-value paths (lambda (path) (max 0 (- (vector-ref path (- spy-days 1)) spy-start-price)))
                  rate (/ spy-days 252.0))))
(define with-dividends (spy-call-value spy-schedule))
(define without-dividends (spy-call-value '()))
(display (format "A 3-month SPY call at {:,.2f}: {:.2f} +/- {:.2f} with the dividends, {:.2f} +/- {:.2f} without\n"
                 spy-start-price (first with-dividends) (second with-dividends)
                 (first without-dividends) (second without-dividends)))
