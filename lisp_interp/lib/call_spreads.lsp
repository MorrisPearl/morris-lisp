; call_spreads.lsp
;
; Bull call spreads: of a stock's calls that expire on one day, buy the one
; with the lower strike and sell the one with the higher strike. Which pair
; is best, if you expect the stock to be at a certain price on that day?
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
; are open) and volume of at least :min-volume (0). A pair that would pay
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

(defstruct spread-search
  stock             ; the stock's symbol
  stock-price       ; its price when the chain was got
  expiration        ; the day the calls expire
  expected-price    ; the stock's price that day, as expected
  prices            ; bid-ask or mid: the prices the spreads cost at
  spreads)          ; a table: a row for each pair of calls that makes a spread, the best first

(define option-contract-size 100)         ; shares in an option contract

; ---------------------------------------------------------------------------
; Finding the spreads
; ---------------------------------------------------------------------------

(define (call-spreads--market-open?)
  "Whether the stock market is open now: from 9:30 to 4:00, New York time, on
a trading day. (This takes the computer's clock to be on New York time.)"
  (let* ((now (current-time))
         (minutes (+ (* 60 (list-ref now 3)) (list-ref now 4))))      ; since midnight
    (and (trading-day? (today)) (>= minutes (+ (* 9 60) 30)) (< minutes (* 16 60)))))

(define (call-spreads--day expiration)
  "A date, from a date or YYYY-MM-DD text."
  (if (string? expiration) (string->date expiration) expiration))

(define (call-spreads--repeat value like)
  "A vector of value, as long as like."
  (vector-map (lambda (x) value) like))

(define (call-spreads--pairs symbols strikes buy sell)
  "The pairs of calls, whose symbols, strikes, and buying and selling prices
are in the vectors, in order of strike: the call bought and the call sold, for
every pair of them, as six vectors: the symbols of the calls bought, and of
those sold, their strikes, and their prices."
  (let ((long-symbols '()) (short-symbols '()) (long-strikes '()) (short-strikes '())
        (long-prices '()) (short-prices '()))
    (loop for i from 0 below (- (vector-length strikes) 1)
          do (let ((later (+ i 1)))                  ; the calls sold are those with higher strikes
               (push (call-spreads--repeat (vector-ref symbols i) (vector-drop strikes later)) long-symbols)
               (push (vector-drop symbols later) short-symbols)
               (push (call-spreads--repeat (vector-ref strikes i) (vector-drop strikes later)) long-strikes)
               (push (vector-drop strikes later) short-strikes)
               (push (call-spreads--repeat (vector-ref buy i) (vector-drop strikes later)) long-prices)
               (push (vector-drop sell later) short-prices)))
    (map (lambda (pieces) (apply vector-append (cons (vector-take strikes 0) (reverse pieces))))
         (list long-symbols short-symbols long-strikes short-strikes long-prices short-prices))))

(define (call-spreads--no-calls chain day)
  "The error for a chain with no calls expiring on day."
  (let ((days (vector-unique (table-column (table-filter chain (= (table-column chain "type") "Call"))
                                           "expiration-date"))))
    (error (format "call-spreads: the chain has no calls expiring on {}; its calls expire on {}"
                   (date->string day)
                   (if (= (vector-length days) 0)
                       "no day at all"
                       (string-join (map date->string (vector->list days)) ", "))))))

(define (call-spreads-for-chain chain expiration expected-price
                                &key (prices 'bid-ask) (min-open-interest 1) (min-volume 0) (min-cost 0))
  "Every pair of the chain's calls that expire on expiration (a date, or
YYYY-MM-DD text), bought at the lower strike and sold at the higher, as a
spread-search (see the top of this file): its table of spreads has a row for
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
  (unless (or (eq? prices 'bid-ask) (eq? prices 'mid))
    (error "call-spreads: :prices is 'bid-ask or 'mid, not" prices))
  (let* ((day (call-spreads--day expiration))
         (calls (table-filter chain (vector-and (= (table-column chain "type") "Call")
                                                (= (table-column chain "expiration-date") day)))))
    (when (= (table-row-count calls) 0)
      (call-spreads--no-calls chain day))
    (let* ((quoted (table-sort
                     (table-filter calls (vector-and (> (table-column calls "bid") 0)
                                                     (> (table-column calls "ask") 0)
                                                     (>= (vector-fill-nan (table-column calls "open-interest") 0)
                                                         min-open-interest)
                                                     (>= (vector-fill-nan (table-column calls "volume") 0)
                                                         min-volume)))
                     "strike"))
           (buy (table-column quoted (if (eq? prices 'mid) "mid" "ask")))
           (sell (table-column quoted (if (eq? prices 'mid) "mid" "bid"))))
      (destructuring-bind (long-symbol short-symbol long-strike short-strike long-price short-price)
          (call-spreads--pairs (table-column quoted "symbol") (table-column quoted "strike") buy sell)
        (let* ((cost (- long-price short-price))
               (worth (- (vector-clip (- expected-price long-strike) 0 1e12)
                         (vector-clip (- expected-price short-strike) 0 1e12)))
               (keep (vector-and (> cost 0) (>= cost min-cost) (> short-strike long-strike)))
               (pick (lambda (v) (vector-select v keep)))
               (kept-cost (pick cost))
               (kept-profit (- (pick worth) kept-cost)))
          (make-spread-search
            :stock (vector-ref (table-column chain "underlying") 0)
            :stock-price (vector-ref (table-column chain "underlying-price") 0)
            :expiration day
            :expected-price expected-price
            :prices prices
            :spreads (table-sort
                       (make-table "long-symbol" (pick long-symbol) "short-symbol" (pick short-symbol)
                                   "long-strike" (pick long-strike) "short-strike" (pick short-strike)
                                   "long-price" (pick long-price) "short-price" (pick short-price)
                                   "cost" kept-cost "worth" (pick worth) "profit" kept-profit
                                   "ratio" (/ kept-profit kept-cost)
                                   "breakeven" (+ (pick long-strike) kept-cost)
                                   "max-profit" (- (pick short-strike) (pick long-strike) kept-cost))
                       "ratio" #t)))))))

(define (call-spreads creds symbol expiration expected-price
                      &key (prices 'bid-ask) (min-open-interest 1) (min-volume 0) (min-cost 0))
  "Get the stock's calls expiring on expiration (a date, or YYYY-MM-DD text)
from Schwab -- the bids and asks are live while the market is open, and say so
if it is closed -- and rank the call spreads: see call-spreads-for-chain, which
takes the other options, and gives the result."
  (unless (call-spreads--market-open?)
    (display "The market is closed now: the bids and asks are from its last close.\n\n"))
  (call-spreads-for-chain (schwab-option-chain creds symbol :expiration (call-spreads--day expiration) :type "CALL")
                          expiration expected-price
                          :prices prices :min-open-interest min-open-interest :min-volume min-volume
                          :min-cost min-cost))

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

(define (show-spread-order order)
  "Say in words what a spread order -- as call-spread-order or
schwab-spread-order makes it -- would do, to read before previewing or placing
it: what it buys and sells, and the most it would pay. Nothing is sent."
  (let* ((legs (hash-table-ref order "orderLegCollection"))
         (contracts (hash-table-ref (first legs) "quantity"))
         (price (hash-table-ref order "price")))
    (display (format "This order has not been sent. If it were: a {} order to open {} spread{}, with a limit on the net debit of {:,.2f} a share ({:,.2f} for each, {:,.2f} in all, at most):\n"
                     (string-downcase (hash-table-ref order "duration")) contracts (if (= contracts 1) "" "s")
                     price (* option-contract-size price) (* option-contract-size price contracts)))
    (dolist (leg legs)
      (display (format "  {:<13} {} x {}\n" (hash-table-ref leg "instruction") (hash-table-ref leg "quantity")
                       (hash-table-ref (hash-table-ref leg "instrument") "symbol"))))))

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
       (display "No pair of its calls makes a spread: there are no two with a bid and an ask, open interest, and a net cost above 0.\n"))
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
