; call_spreads.lsp
;
; Bull call spreads: of a stock's calls that expire on one day, buy the one
; with the lower strike and sell the one with the higher strike. Which pair
; is best, if you expect the stock to be at a certain price on that day?
;
; This is the simplest spread, and the one to read first. The work is done by
; option_spreads.lsp, which ranks sixteen other kinds of position besides this
; one (bear call, bull put, bear put, butterflies, iron condors, straddles,
; strangles, single options, and positions with shares) the same way: the
; functions below are its bull-call kind under names of their own. In the
; table of spreads, symbol-1, strike-1 and price-1 are the call bought, and
; symbol-2, strike-2 and price-2 the call sold. Everything this comment says is
; about this one kind.
;
; What a spread is. A call lets you buy the stock at its strike on the
; expiration day, so at expiration it is worth the stock's price less the
; strike, or nothing, if that's less. Buying the call at the lower strike
; and selling the one at the higher costs less than the first alone, and
; gives up what the stock gains beyond the higher strike. With the strikes
; K1 (bought) and K2 (sold), and the stock at S on the expiration day, the
; pair is worth
;
;     (S - K1, or 0)  -  (S - K2, or 0)
;
; which is 0 for S at or below K1, then rises dollar for dollar with the
; stock, and stops at K2 - K1 for S at or above K2. What you pay for the
; pair is its cost (also called the net debit): the price of the call you
; buy, less the price you get for the one you sell. The most you can lose
; is the cost, if the stock ends at K1 or below and both calls expire
; worthless. At the price you expect, S, the profit is the worth there, less
; the cost; and the ratio this file ranks the pairs by is
;
;     the profit at S  /  the most you can lose.
;
; Prices. You buy at the ask and sell at the bid, so the cost is the ask of
; the call bought less the bid of the call sold (:prices 'bid-ask, the
; default). With :prices 'mid, it is the middle of each's bid and ask, which
; is what you'd get if you could trade in the middle. Be careful with 'mid:
; thin options have wide, ragged quotes, and their middles can make a pair
; look far cheaper than it can be traded. (On SPY, after the close, two deep
; in-the-money calls with open interest of 4 and 8 had middles only 0.38
; apart for strikes a dollar apart, and so made a spread worth 1.00 at
; expiration "cost" 0.38, and the best of all; at their asks and bids it is
; nowhere near. A higher :min-open-interest guards against these.) The prices
; are for one share; an option contract is for 100 (option-contract-size).
;
; Which calls count. Both must have a bid and an ask above 0, and open
; interest of at least :min-open-interest (1; the number of contracts that
; are open) and volume of at least :min-volume (1: the option has traded at
; least once today). Volume counts today's trades, so it is 0 for every option
; before the market opens: give :min-volume 0 then. A pair that would pay
; you to buy it (a cost of 0 or less, from quotes that don't agree) has no
; most you can lose and is left out, as is one that costs less than
; :min-cost (0). Spreads that cost almost nothing have huge ratios if the
; stock gets to the higher strike, and almost no chance of doing it: :min-cost
; leaves them out.
;
; What the ratio leaves out. It says how much you'd make, per dollar you
; could lose, if the stock is at the price you expect. It doesn't say how
; likely that is (the price you expect is one price, and the stock can end
; anywhere), and it ignores commissions, and that the call you sold can be
; exercised before expiration (usually just before an ex-dividend date, if it
; is in the money). The most you can make is the width of the spread less
; the cost, and you make it with the stock at the higher strike or more.
;
; Usage:
;   (load "call_spreads.lsp")
;   (define search (call-spreads creds "SPY" (date 2026 11 20) 765))   ; live quotes, from Schwab
;   (show-call-spreads search)                    ; the best, and the next few
;   (spread-search-spreads search)                ; the table of all of them, best first
;   (define order (call-spread-order search))     ; an order for the best one: nothing is sent
;   (show-spread-order order)                     ; what it would do, in words
;   (schwab-preview-order creds "Brokerage" order)  ; what Schwab makes of it: nothing is placed
;   (schwab-place-order creds "Brokerage" order :confirm #t)   ; this places it, for real
;
; Or, for a chain you have already, from Schwab or tastytrade:
;   (call-spreads-for-chain chain (date 2026 11 20) 765)

(require "option_spreads.lsp")

(define (call-spreads-for-chain chain expiration expected-price
                                &key (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-cost 0)
                                (underlying '()) (contract-size option-contract-size) (unit "share"))
  "Every pair of the chain's calls that expire on expiration (a date, or YYYY-MM-DD text), bought at the lower strike and sold at
the higher, as a spread-search: (option-spreads-for-chain chain 'bull-call ...), whose table of spreads has a row for each, the
best first -- the one with the highest profit, if the stock is at expected-price on expiration day, as a share of the most that
can be lost. :min-cost is its :min-risk; the other options are its own (see the top of this file, and option-spreads-for-chain)."
  (option-spreads-for-chain chain 'bull-call expiration expected-price
                            :prices prices :min-open-interest min-open-interest :min-volume min-volume
                            :min-risk min-cost :underlying underlying :contract-size contract-size :unit unit))

(define (call-spreads creds symbol expiration expected-price
                      &key (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-cost 0))
  "Get the stock's calls expiring on expiration (a date, or YYYY-MM-DD text) from Schwab -- the bids and asks are live while the
market is open, and say so if it is closed -- and rank the call spreads: see call-spreads-for-chain."
  (option-spreads creds symbol 'bull-call expiration expected-price
                  :prices prices :min-open-interest min-open-interest :min-volume min-volume :min-risk min-cost))

(define (show-call-spreads search &key (count 10))
  "Show what call-spreads found: the best spread in words, and a table of it and the next count best (show-option-spreads)."
  (show-option-spreads search :count count))

(define (plot-call-spreads search &key (rows (list 0)) (low '()) (high '()) (points 200))
  "Chart the profit of one of the spreads -- the best, unless :rows (a list of row numbers) says -- on the expiration day, against
the price the stock might have then (plot-option-profit). save-chart saves the chart to a file."
  (plot-option-profit search :rows rows :low low :high high :points points))

(define (call-spread-order search &key (row 0) (contracts 1) (price '()))
  "An order for one of the spreads -- the best, unless :row (0 is the best, 1 the next, ...) says -- as a hash table in Schwab's
form: buy the call with the lower strike and sell the one with the higher, :contracts of each, with a limit on the net debit, a
share, of :price (the spread's cost, unless it is given) (option-spread-order). It sends nothing: schwab-preview-order says what
Schwab makes of it, and schwab-place-order :confirm #t places it."
  (option-spread-order search :row row :contracts contracts :price price))
