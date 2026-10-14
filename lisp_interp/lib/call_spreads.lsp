; call_spreads.lsp
;
; Bull call spreads: of a stock's calls that expire on one day, buy the one
; with the lower strike and sell the one with the higher strike. Which pair
; is best, if you expect the stock to be at a certain price on that day?
;
; This is the simplest spread, and the one to read first. The work is done by
; option_spreads.lsp, which ranks nine other kinds of spread besides this one
; (bear call, bull put, bear put, butterflies, iron condors, straddles,
; strangles) the same way: (option-spreads-for-chain chain 'bull-call ...) is
; what call-spreads-for-chain does, with the table's columns named for the
; call bought (long) and the call sold (short) instead of the first and second
; option. Everything below is about this one kind.
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

(load "option_spreads.lsp")

; ---------------------------------------------------------------------------
; Finding the spreads
; ---------------------------------------------------------------------------

(define (call-spreads--classic search)
  "A spread-search of bull call spreads from option_spreads.lsp's, with the columns named for the call
bought and the call sold: option_spreads.lsp's symbol-1 is long-symbol, symbol-2 short-symbol, and so on;
its max-loss, which for this spread is the cost, is left out; and the breakeven is the lower strike plus the cost
(where the spread is worth what it cost; for a spread that costs more than its width, that is above the higher strike
and the spread can never make a profit, and option_spreads.lsp has no breakeven for it)."
  (let ((table (spread-search-spreads search)))
    (make-spread-search
      :kind (spread-search-kind search)
      :stock (spread-search-stock search)
      :stock-price (spread-search-stock-price search)
      :expiration (spread-search-expiration search)
      :expected-price (spread-search-expected-price search)
      :prices (spread-search-prices search)
      :spreads (list (cons "long-symbol" (table-column table "symbol-1"))
                     (cons "short-symbol" (table-column table "symbol-2"))
                     (cons "long-strike" (table-column table "strike-1"))
                     (cons "short-strike" (table-column table "strike-2"))
                     (cons "long-price" (table-column table "price-1"))
                     (cons "short-price" (table-column table "price-2"))
                     (cons "cost" (table-column table "cost"))
                     (cons "worth" (table-column table "worth"))
                     (cons "profit" (table-column table "profit"))
                     (cons "ratio" (table-column table "ratio"))
                     (cons "breakeven" (+ (table-column table "strike-1") (table-column table "cost")))
                     (cons "max-profit" (table-column table "max-profit"))))))

(define (call-spreads-for-chain chain expiration expected-price
                                &key (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-cost 0))
  "Every pair of the chain's calls that expire on expiration (a date, or
YYYY-MM-DD text), bought at the lower strike and sold at the higher, as a
spread-search (see the top of option_spreads.lsp): its table of spreads has a row for
each, the best first -- the one with the highest profit, if the stock is at
expected-price on expiration day, as a share of the most that can be lost.
chain is a table as tastytrade-option-chain or schwab-option-chain makes.
The columns of the table:
  long-symbol, short-symbol    the options bought and sold
  long-strike, short-strike    their strikes
  long-price, short-price      what is paid for one, and got for the other, for a share
  cost                         the net: the most that can be lost, for a share
  worth                        what the spread is worth at expected-price on the day
  profit                       worth less cost
  ratio                        profit as a share of cost: 1.5 is 150%
  breakeven                    the stock's price at which the spread is worth its cost
  max-profit                   the most that can be made: the strikes' difference less cost
:prices is bid-ask (pay the ask, get the bid) or mid; the others limit which
calls count: see the top of this file."
  (call-spreads--classic
    (option-spreads-for-chain chain 'bull-call expiration expected-price
                              :prices prices :min-open-interest min-open-interest :min-volume min-volume
                              :min-risk min-cost)))

(define (call-spreads creds symbol expiration expected-price
                      &key (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-cost 0))
  "Get the stock's calls expiring on expiration (a date, or YYYY-MM-DD text)
from Schwab -- the bids and asks are live while the market is open, and say so
if it is closed -- and rank the call spreads: see call-spreads-for-chain, which
takes the other options, and gives the result."
  (call-spreads--classic
    (option-spreads creds symbol 'bull-call expiration expected-price
                    :prices prices :min-open-interest min-open-interest :min-volume min-volume
                    :min-risk min-cost)))

; ---------------------------------------------------------------------------
; The order
; ---------------------------------------------------------------------------

(define (call-spread-order search &key (row 0) (contracts 1) (price '()))
  "An order for one of the spreads of a spread-search -- the best, unless :row
(0 is the best, 1 the next, ...) says -- as a hash table, in Schwab's form:
buy the call with the lower strike and sell the one with the higher, for
:contracts of each, with a limit on the net debit, a share, of :price (the
spread's cost, unless it is given). It sends nothing: schwab-preview-order says
what Schwab makes of it, and schwab-place-order :confirm #t places it. The order
opens new positions, and lasts the day.

At the cost, if the prices are bid-ask, the order is likely to fill at once:
it pays what is asked for the call bought and takes what is bid for the call
sold. A lower :price may fill at a better price, or not fill."
  (let ((spreads (spread-search-spreads search)))
    (when (>= row (table-row-count spreads))
      (error (format "call-spread-order: there is no row {}: the search found {} spreads" row
                     (table-row-count spreads))))
    (schwab-spread-order (vector-ref (table-column spreads "long-symbol") row)
                         (vector-ref (table-column spreads "short-symbol") row)
                         contracts
                         (if (null? price) (vector-ref (table-column spreads "cost") row) price))))

; ---------------------------------------------------------------------------
; Showing them
; ---------------------------------------------------------------------------

(define (call-spreads--best-in-words search)
  "A paragraph about the best spread: what to buy and sell, what it costs,
and what it makes."
  (let* ((spreads (spread-search-spreads search))
         (stock (spread-search-stock search))
         (size option-contract-size)
         (cost (vector-ref (table-column spreads "cost") 0))
         (profit (vector-ref (table-column spreads "profit") 0))
         (low (vector-ref (table-column spreads "long-strike") 0))
         (high (vector-ref (table-column spreads "short-strike") 0)))
    (string-append
      (format "The best: buy the {:,.2f} call, at {:,.2f}, and sell the {:,.2f} call, at {:,.2f}.\n"
              low (vector-ref (table-column spreads "long-price") 0)
              high (vector-ref (table-column spreads "short-price") 0))
      (format "  It costs {:,.2f} a share ({:,.2f} for a contract of {}). That is the most you can lose, if {} ends at {:,.2f} or less.\n"
              cost (* size cost) size stock low)
      (format "  With {} at {:,.2f} on {}, the spread is worth {:,.2f} a share, a profit of {:,.2f} ({:,.2f} a contract): {:.0%} of the most you can lose.\n"
              stock (spread-search-expected-price search) (date->string (spread-search-expiration search))
              (vector-ref (table-column spreads "worth") 0) profit (* size profit)
              (vector-ref (table-column spreads "ratio") 0))
      (format "  It breaks even with {} at {:,.2f}; the most it can make is {:,.2f} a share, with {} at {:,.2f} or more."
              stock (vector-ref (table-column spreads "breakeven") 0)
              (vector-ref (table-column spreads "max-profit") 0) stock high))))

(define (show-call-spreads search &key (count 10))
  "Show what call-spreads found: the best spread in words, and a table of it
and the next count best."
  (let* ((spreads (spread-search-spreads search))
         (rows (table-row-count spreads)))
    (display (format "{} is at {:,.2f}. Bull call spreads expiring {}, if it is at {:,.2f} then; bought and sold at the {} prices. {} spreads.\n\n"
                     (spread-search-stock search) (spread-search-stock-price search)
                     (date->string (spread-search-expiration search)) (spread-search-expected-price search)
                     (if (eq? (spread-search-prices search) 'mid) "middle" "ask and bid") rows))
    (cond
      ((= rows 0)
       (display "No pair of its calls makes a spread: there are no two with a bid and an ask, open interest, volume today, and a net cost above 0.\n(Volume counts today's trades, and is 0 before the market opens: give :min-volume 0 then.)\n"))
      (else
        (display (call-spreads--best-in-words search))
        (display (format "\n\nThe best {}, by the ratio of profit to the most that can be lost (prices are for a share):\n"
                         (min count rows)))
        (display-table (table-head spreads count)
                       '(("long-symbol") ("short-symbol") ("long-strike" ",.2f") ("short-strike" ",.2f")
                         ("long-price" ",.2f") ("short-price" ",.2f") ("cost" ",.2f") ("worth" ",.2f")
                         ("profit" ",.2f") ("ratio" ".0%") ("breakeven" ",.2f") ("max-profit" ",.2f")))
        (display "\nTo trade the best one: call-spread-order sends nothing, the preview asks Schwab what it makes of\nthe order and places nothing, and only the last line places it:\n")
        (display "  (define order (call-spread-order search :contracts 1))\n")
        (display "  (show-spread-order order)                               ; the order, in words\n")
        (display "  (schwab-preview-order creds \"your account\" order)     ; what Schwab makes of it; nothing is placed\n")
        (display "  (schwab-place-order creds \"your account\" order :confirm #t)     ; places it, for real\n")))))
