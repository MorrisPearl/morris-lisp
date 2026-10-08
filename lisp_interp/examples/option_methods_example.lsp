; option_methods_example.lsp
;
; Three ways to value an option, side by side, on an investment that pays
; no dividends (Berkshire Hathaway, BRK/A):
;
;   Black-Scholes    a formula (bsm-price), for returns that are normally
;                    distributed, with a volatility that doesn't change
;   a binomial tree  the same model, made of up and down steps
;                    (american-price, with :early-exercise #f: the
;                    option can only be exercised when it expires)
;   Monte Carlo      paths of the price copied from its own history, a day
;                    at a time (bootstrap-path), and what the option pays on
;                    each of them, discounted and averaged (option-payoffs)
;
; The formula and the tree are the same model, so they agree, but for the
; tree's having only so many steps. The paths are another model: the
; history's own returns, fat tails and all, in place of the normal
; distribution. So they agree with the formula at the money, and over a
; year, when many days add up to something close to normal -- but not for
; an option a month away and well out of the money, which the fat tails
; make worth more. The last column says how far apart the paths' value and
; the formula's are, in standard errors of the paths' value: within about 2,
; and the difference could be only that there are so many paths.
;
; To make the three comparable, everything else is the same for all of
; them: the volatility is the history's (the daily log returns' spread, for
; a year of 252 trading days), time is counted in trading days, and the
; paths grow at the interest rate, as the formula and the tree suppose
; (see "What risk-neutral means" in the reference manual).
;
; It needs a Schwab sign-in for the prices ((schwab-login creds); it lasts
; a week). creds is set to its path in init.lsp. It takes a few seconds.
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py option_methods_example.lsp

(define prices (schwab-price-history creds "BRK/A"))        ; ten years, as Schwab gives them
(define history (daily-returns prices))
(define spot (vector-ref (table-column prices "close") (- (table-row-count prices) 1)))
(define rate 0.04)

; The history's volatility, as the paths have it: the log returns' spread
; about their average, for a year of 252 trading days.
(define moves (- (table-column history "log-return") (vector-mean (table-column history "log-return"))))
(define volatility (sqrt (* 252 (vector-mean (* moves moves)))))

; 20,000 paths of a year of trading days, each copied a day at a time from
; the history (blocks of 1 day), grown at the interest rate.
(define returns (adjust-returns history (- (exp rate) 1)))
(define paths (map (lambda (i) (bootstrap-path returns spot 252 1 :seed (+ 1000 i))) (iota 20000)))

; The options: a name, call or put, the strike as a fraction of today's
; price, and the trading days to expiration.
(define options '(("1 year, call at the money"  "call" 1.0 252)
                  ("1 year, put 20% below"      "put"  0.8 252)
                  ("1 month, call at the money" "call" 1.0 21)
                  ("1 month, put 10% below"     "put"  0.9 21)))
(define types (map second options))
(define strikes (* spot (list->vector (map third options))))
(define days (list->vector (map fourth options)))
(define years (/ days 252.0))

; What each option pays on the paths, on average, discounted at the
; interest rate (all four from the same paths, at once).
(define paid (option-payoffs paths days strikes (list->vector (map (lambda (type) (if (equal? type "call") 1 0)) types))))
(define discount (exp (- (* rate years))))
(define monte-carlo (* discount (table-column paid "payoff")))
(define standard-error (* discount (table-column paid "payoff-error")))

(define black-scholes
  (list->vector (map (lambda (type strike T) (bsm-price type spot strike T rate volatility))
                     types (vector->list strikes) (vector->list years))))
(define tree
  (list->vector (map (lambda (type strike T) (american-price type spot strike T rate volatility
                                                             :steps 200 :early-exercise #f))
                     types (vector->list strikes) (vector->list years))))

(define compared
  (make-table "option" (list->vector (map first options))
              "black-scholes" black-scholes
              "tree" tree
              "monte-carlo" monte-carlo
              "standard-error" standard-error
              "standard-errors-apart" (/ (- monte-carlo black-scholes) standard-error)))

(display (format "BRK/A at {:,.0f}; the history's volatility {:.1%}; an interest rate of {:.0%}; {:,} paths\n\n"
                 spot volatility rate (length paths)))
(display-table compared '(("black-scholes" ",.0f") ("tree" ",.0f") ("monte-carlo" ",.0f") ("standard-error" ",.0f")
                          ("standard-errors-apart" "+.1f")))
