; option_payoffs_example.lsp
;
; What does each kind of option position pay? One chart for each: the price
; the stock has on the expiration day along the bottom, and what the position
; has made or lost then, for a share, up the side -- green where it has made
; money, red where it has lost. The kinds are the seventeen that
; lib/option_spreads.lsp ranks: spreads, butterflies, condors, a straddle and a
; strangle, single options, shares with options, and owning the stock alone.
;
; It needs no network. The stock and its options are made up: a stock at
; 104, and options on it that expire in 30 days, priced by Black-Scholes at a
; volatility of 25%, with a bid and an ask a little either side of the price.
; Then, if you expect the stock to be at 108 on the expiration day, it finds
; the best position of each kind (lib/option_positions.lsp), and shows the
; ranking, and:
;
;   option_payoff_condor.png       one position in detail: the best iron condor
;   option_payoffs_compared.png    the best few of the kinds that are options alone, on one chart
;   option_payoffs_hedged.png      the stock, and what a covered call, a protective put, and a
;                                  collar do to it
;   option_payoffs_verticals.png   the vertical spreads, and the single options, one chart each
;   option_payoffs_butterflies.png the butterflies, the condors, the straddle, and the strangle
;   option_payoffs_shares.png      owning the stock, and the three with shares, each on its own
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py option_payoffs_example.lsp
; In a notebook or the GUI the charts are drawn too. To chart a position of your
; own stock, the examples option_spreads_example.lsp and
; option_positions_example.lsp do it with Schwab's quotes.

(load "option_positions.lsp")

; --- A stock and its options, made up -----------------------------------------------
(define stock-price 104.0)
(define day (date 2026 11 20))
(define years (/ 30 365.0))                                    ; 30 days to expiration
(define interest-rate 0.04)
(define volatility 0.25)
(define strikes (+ 80.0 (* 5 (vector-range 11))))              ; 80 to 130, every 5
(define both (lambda (calls puts) (vector-append calls puts)))

; The name of an option: the stock's (padded to 6 characters), the day as YYMMDD, C or P, and the
; strike times 1000 in 8 digits.
(define (names letter)
  (vector-map (lambda (strike) (format "XYZ   261120{}{:08d}" letter (round (* strike 1000)))) strikes))
(define (constant value) (vector-map (lambda (strike) value) (both strikes strikes)))

; Black-Scholes's price is the middle of the bid and ask. The bid is 2 cents and half a percent less,
; and the ask as much more.
(define (bids prices) (vector-round (vector-clip (- prices (+ 0.02 (* 0.005 prices))) 0.01 1e9) 2))
(define (asks prices) (vector-round (+ prices (+ 0.02 (* 0.005 prices))) 2))
(define call-prices (bsm-price "call" stock-price strikes years interest-rate volatility))
(define put-prices (bsm-price "put" stock-price strikes years interest-rate volatility))

(define chain
  (make-table "symbol" (both (names "C") (names "P"))
              "type" (both (vector-map (lambda (strike) "Call") strikes) (vector-map (lambda (strike) "Put") strikes))
              "strike" (both strikes strikes)
              "expiration-date" (constant day)
              "underlying" (constant "XYZ")
              "underlying-price" (constant stock-price)
              "bid" (both (bids call-prices) (bids put-prices))
              "ask" (both (asks call-prices) (asks put-prices))
              "mid" (vector-round (both call-prices put-prices) 3)
              "volume" (constant 100)
              "open-interest" (constant 500)))

; --- The best of each kind, if the stock is expected at 108 ---------------------------
; :max-width 10 keeps the strikes of a spread, or a strangle, within 10 of one another. Without it the best
; strangle has a put at 80, which is worth nothing, and so is just a call.
(define expected-price 108.0)
(define comparison (option-positions-for-chain chain day expected-price :max-width 10))
(show-option-positions comparison)

; --- One position in detail ---------------------------------------------------------------
; The line bends at the strikes. It is above 0 between the two breakevens (the circles), and the most
; it can make or lose is where it is flat. The diamond is the stock at the price expected.
(plot-option-profit (position-comparison-search comparison 'iron-condor))
(save-chart "option_payoff_condor.png")

; --- The best of several kinds on one chart ------------------------------------------
; By default the options alone, the best few by the ratio: a butterfly is a tent, a condor a tent with a
; flat top; each gains where the stock ends near its middle strikes, and loses everywhere else.
(plot-option-positions comparison)
(save-chart "option_payoffs_compared.png")

; The shares come in a chart of their own, as their profits are bigger: the stock's line goes from
; losing 20 to making 20, and the rest are the same line with something taken off or held back.
; The covered call stops rising at its strike, and the protective put stops falling at its; the collar
; does both.
(plot-option-positions comparison :kinds '(long-stock covered-call protective-put collar))
(save-chart "option_payoffs_hedged.png")

; --- A chart for every kind, in three figures ---------------------------------------
; Each panel is one kind's best position, on the same prices (85 to 140) as the others'.
(define (gallery title kinds filename)
  (plot-panels (map (lambda (kind) (option-profit-panel (position-comparison-search comparison kind) :low 85 :high 140))
                    kinds)
               :title title :x-min 85 :x-max 140 :x-label "price of XYZ on 2026-11-20"
               :y-label "profit, for a share" :height (+ 1 (* 2.6 (length kinds))))
  (save-chart filename))

(gallery "The vertical spreads and the single options"
         '(bull-call bear-call bull-put bear-put long-call long-put cash-secured-put) "option_payoffs_verticals.png")
(gallery "Butterflies, condors, the straddle and the strangle"
         '(call-butterfly put-butterfly iron-condor iron-butterfly long-straddle long-strangle)
         "option_payoffs_butterflies.png")
(gallery "Owning the stock, and with an option or two"
         '(long-stock covered-call protective-put collar) "option_payoffs_shares.png")
