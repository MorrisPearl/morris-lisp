; implied_vol.lsp
;
; Implied volatility of a European option under the Black-Scholes-Merton
; model: given an option's market price, find the volatility that makes
; the model's price equal it. There's no closed-form inverse, so this
; uses solver.lsp's Ridders' method on
;     f(vol) = bsm-price(vol) - market price
; over a bracket of plausible volatilities. Price rises monotonically
; with volatility, so there's at most one answer.
;
; Usage:
;   (load "implied_vol.lsp")
;   (implied-vol 10.45 "call" 100 100 1.0 0.05)          ; => ~0.20
;   (implied-vol 10.45 "call" 100 100 1.0 0.05 :dividend_yield 0.01)
;
; Note on American options (e.g. equity options like AAPL): this prices
; them as if European, so for those the result is an approximation --
; fairly close for calls on non-dividend-paying stocks, less so for
; puts and for dividend-paying stocks.

(load "solver.lsp")

; The standard normal cumulative distribution function, N(x).
(define (normal-cdf x)
  (* 0.5 (+ 1.0 (erf (/ x (sqrt 2.0))))))

; #t for "call", #f for "put" (case doesn't matter, so tastytrade's
; "Call"/"Put" work as they are); anything else is an error.
(define (implied-vol--call? type)
  (let ((t (string-downcase type)))
    (cond ((string=? t "call") #t)
          ((string=? t "put") #f)
          (#t (error "option type must be \"call\" or \"put\", got" type)))))

; (bsm-price type spot strike time rate vol [&key dividend_yield]) ->
; the Black-Scholes-Merton price of a European option.
;
; type: "call" or "put".
; spot: current price of the underlying.
; strike: the option's strike price.
; time: time to expiration in YEARS (e.g. 30 days is 30/365.0).
; rate: continuously compounded risk-free interest rate, as a decimal
;     (0.05 for 5%).
; vol: volatility of the underlying, annualized, as a decimal (0.20 for 20%).
; dividend_yield: continuous dividend yield of the underlying, as a
;     decimal -- default 0.
(define (bsm-price type spot strike time rate vol &key (dividend_yield 0.0))
  (let* ((sqrt_t (sqrt time))
         (d1 (/ (+ (log (/ spot strike))
                   (* (+ (- rate dividend_yield) (* 0.5 vol vol)) time))
                (* vol sqrt_t)))
         (d2 (- d1 (* vol sqrt_t)))
         (discounted_spot (* spot (exp (- (* dividend_yield time)))))
         (discounted_strike (* strike (exp (- (* rate time))))))
    (if (implied-vol--call? type)
        (- (* discounted_spot (normal-cdf d1))
           (* discounted_strike (normal-cdf d2)))
        (- (* discounted_strike (normal-cdf (- d2)))
           (* discounted_spot (normal-cdf (- d1)))))))

; (implied-vol price type spot strike time rate
;              [&key dividend_yield vol_lo vol_hi tolerance]) ->
; the annualized volatility, as a decimal (0.20 means 20%).
;
; price: the option's market price. The other arguments are as for
;     bsm-price.
; vol_lo, vol_hi: the range of volatilities searched -- defaults 0.0001
;     (0.01%) to 5.0 (500%).
; tolerance: how precisely the volatility is found -- default 1e-8.
;
; Raises an error if price is outside the range of prices the model can
; produce between vol_lo and vol_hi -- typically a price below the
; option's intrinsic value (which no volatility can explain), or above
; what vol_hi implies. A stale or zero quote will do this.
(define (implied-vol price type spot strike time rate
                     &key (dividend_yield 0.0) (vol_lo 0.0001) (vol_hi 5.0) (tolerance 1e-8))
  (let ((price_at_lo (bsm-price type spot strike time rate vol_lo :dividend_yield dividend_yield))
        (price_at_hi (bsm-price type spot strike time rate vol_hi :dividend_yield dividend_yield)))
    (if (or (< price price_at_lo) (> price price_at_hi))
        (error "implied-vol: price" price "is outside" price_at_lo "to" price_at_hi
               "-- the model prices between vol" vol_lo "and" vol_hi)
        (ridders (lambda (vol)
                   (- (bsm-price type spot strike time rate vol :dividend_yield dividend_yield)
                      price))
                 vol_lo vol_hi :tolerance tolerance))))
