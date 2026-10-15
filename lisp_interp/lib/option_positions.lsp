; option_positions.lsp
;
; Which kind of position is best? option_spreads.lsp ranks the positions of
; one kind -- the bull call spreads, say, or the covered calls -- by the profit
; at the price you expect for the stock on one day, as a share of the most you
; can lose. This file takes the best position of every kind, and ranks those
; by the same ratio, so you can see the kinds side by side: seventeen of them,
; from a bull call spread to a collar, and among them the simplest of all,
; owning the stock (long-stock), which the others can be compared with. The
; best of a kind is not the same thing as the kind being a good idea: read the
; last paragraph of option_spreads.lsp's header, about what the ratio leaves
; out.
;
; What the ratio compares, and what it doesn't. The ratio is the profit at
; the price you expect over the most that can be lost, so it says what you'd
; make for each dollar you could lose -- not for each dollar you have to put
; up. They can differ a lot: a credit spread needs your broker to hold its
; most to lose, a cash-secured put needs the whole strike in cash, and a long
; call needs only its price. And the ratio is for the one price you expect: a
; long call, a straddle, and the stock itself make more the higher the stock
; goes, where a butterfly or a condor make nothing beyond a narrow range.
;
; Usage:
;   (load "option_positions.lsp")
;   (define comparison (option-positions creds "SPY" (date 2026 11 20) 765))   ; live quotes, from Schwab
;   (show-option-positions comparison)                      ; the best of each kind, ranked
;   (define search (position-comparison-search comparison 'covered-call))   ; all the covered calls
;   (show-option-spreads search)                            ; the best few of them
;   (define orders (option-position-orders search))         ; the orders for the best: nothing is sent
;
; Or, for a chain you have already, from Schwab or tastytrade:
;   (option-positions-for-chain chain (date 2026 11 20) 765)

(load "option_spreads.lsp")

(defstruct position-comparison
  stock             ; the stock's symbol
  stock-price       ; the price its shares are bought at
  expiration        ; the day the options expire
  expected-price    ; the stock's price that day, as expected
  prices            ; bid-ask or mid: the prices the options are bought and sold at
  positions         ; a table: a row for the best position of each kind, the best first
  searches)         ; a list of (kind . spread-search): all the positions of each kind that has one

(define (option-positions--possible? kind chain day)
  "Whether the chain has the options that the kind needs, expiring on day: the calls, and the puts."
  (let ((has? (lambda (type)
                (> (table-row-count (table-filter chain (vector-and (= (table-column chain "type") type)
                                                                    (= (table-column chain "expiration-date") day))))
                   0))))
    (every (lambda (leg)
             (has? (if (eq? (option-spreads--leg-type leg) 'call) "Call" "Put")))
           (spread-kind-legs kind))))

(define (option-positions--best searches column)
  "The vector of the best position's value in the column, for each search."
  (list->vector (map (lambda (pair) (vector-ref (table-column (spread-search-spreads (cdr pair)) column) 0)) searches)))

(define (option-positions--table searches)
  "A table with a row for the best position of each search: its kind, the position in words, and its numbers (as
option-spreads-for-chain gives them), the best first."
  (table-sort
    (make-table "kind" (list->vector (map (lambda (pair) (symbol->string (car pair))) searches))
                "position" (list->vector (map (lambda (pair) (option-spreads--position-in-words (cdr pair) 0 #f)) searches))
                "cost" (option-positions--best searches "cost")
                "max-loss" (option-positions--best searches "max-loss")
                "max-profit" (option-positions--best searches "max-profit")
                "worth" (option-positions--best searches "worth")
                "profit" (option-positions--best searches "profit")
                "ratio" (option-positions--best searches "ratio")
                "breakeven-1" (option-positions--best searches "breakeven-1")
                "breakeven-2" (option-positions--best searches "breakeven-2"))
    "ratio" #t))

(define (option-positions-for-chain chain expiration expected-price
                                    &key (kinds '()) (prices 'bid-ask) (min-open-interest 1) (min-volume 1)
                                    (min-risk 0) (max-width '()) (stock-price '()))
  "The best position of each kind that can be made of the chain's options expiring on expiration (a date, or
YYYY-MM-DD text), ranked: a position-comparison, whose table of positions has a row for each kind, the one with the
highest profit if the stock is at expected-price that day, as a share of the most that can be lost, first. The kinds
are all of those option-spread-kinds lists, with the long stock among them, unless :kinds is a list of the names of
the ones you want. A kind that needs puts, or calls, that the chain has none of on that day, and a kind of which no
position can be made, are left out. The other options are those of option-spreads-for-chain, which does the
searches. The columns of the table:
  kind                     the name of the kind
  position                 what it buys and sells, in words
  cost, max-loss, max-profit, worth, profit, ratio, breakeven-1, breakeven-2
                           as in option-spreads-for-chain, for a share"
  (let* ((day (option-spreads--day expiration))
         (names (if (null? kinds) (map spread-kind-name spread-kinds) kinds))
         (possible (filter (lambda (name) (option-positions--possible? (option-spreads--kind name) chain day)) names))
         (searches (filter (lambda (pair) (> (table-row-count (spread-search-spreads (cdr pair))) 0))
                           (map (lambda (name)
                                  (cons name (option-spreads-for-chain chain name day expected-price
                                                                       :prices prices :min-open-interest min-open-interest
                                                                       :min-volume min-volume :min-risk min-risk
                                                                       :max-width max-width :stock-price stock-price)))
                                possible))))
    (make-position-comparison
      :stock (vector-ref (table-column chain "underlying") 0)
      :stock-price (if (null? stock-price) (vector-ref (table-column chain "underlying-price") 0) stock-price)
      :expiration day
      :expected-price expected-price
      :prices prices
      :positions (option-positions--table searches)
      :searches searches)))

(define (option-positions creds symbol expiration expected-price
                          &key (kinds '()) (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-risk 0)
                          (max-width '()) (stock-price '()))
  "Get the stock's options expiring on expiration (a date, or YYYY-MM-DD text) from Schwab -- the calls and the
puts, or only those the :kinds need -- the bids and asks are live while the market is open, and say so if it is
closed -- and rank the best position of each kind: see option-positions-for-chain, which takes the options you
have, and gives the result."
  (let ((contracts (option-spreads--contracts-needed
                     (map option-spreads--kind (if (null? kinds) (map spread-kind-name spread-kinds) kinds)))))
    (unless (option-spreads--market-open?)
      (display "The market is closed now: the bids and asks are from its last close.\n\n"))
    (option-positions-for-chain (schwab-option-chain creds symbol :expiration (option-spreads--day expiration) :type contracts)
                                expiration expected-price
                                :kinds kinds :prices prices :min-open-interest min-open-interest
                                :min-volume min-volume :min-risk min-risk :max-width max-width
                                :stock-price stock-price)))

(define (position-comparison-search comparison kind-name)
  "All the positions of one kind in the comparison, as a spread-search -- the best first -- to show with
show-option-spreads, or to make orders from with option-spread-order or option-position-orders."
  (let ((found (assoc kind-name (position-comparison-searches comparison))))
    (if found
        (cdr found)
        (error (format "position-comparison-search: the comparison has no {}; it has {}" kind-name
                       (string-join (map (lambda (pair) (symbol->string (car pair))) (position-comparison-searches comparison))
                                    ", "))))))

(define (show-option-positions comparison &key (count 20))
  "Show a position-comparison: the best position of each kind, ranked, in a table of the first count, and where
owning the stock comes among them."
  (let* ((positions (position-comparison-positions comparison))
         (rows (table-row-count positions))
         (stock-row (if (= rows 0)
                        -1
                        (vector-ref (vector-positions (table-column positions "kind") (vector "long-stock")) 0))))
    (display (format "{} is at {:,.2f}. The best position of each kind expiring {}, if it is at {:,.2f} then; options bought and sold at the {} prices, shares at {:,.2f}. {} {}.\n\n"
                     (position-comparison-stock comparison) (position-comparison-stock-price comparison)
                     (date->string (position-comparison-expiration comparison)) (position-comparison-expected-price comparison)
                     (if (eq? (position-comparison-prices comparison) 'mid) "middle" "ask and bid")
                     (position-comparison-stock-price comparison)
                     rows (if (= rows 1) "position" "positions")))
    (cond
      ((= rows 0)
       (display "No position can be made: the options need a bid and an ask, open interest, volume today, and a most that can be lost above 0.\n(Volume counts today's trades, and is 0 before the market opens: give :min-volume 0 then.)\n"))
      (else
        (display "Ranked by the ratio of profit to the most that can be lost (prices are for a share):\n")
        (display-table (table-head positions count)
                       '(("cost" ",.2f") ("max-loss" ",.2f") ("max-profit" ",.2f") ("worth")      ; (worth is left out)
                         ("profit" ",.2f") ("ratio" ".1%") ("breakeven-1" ",.2f") ("breakeven-2" ",.2f")))
        (display (format "\n{}"
                         (if (>= stock-row 0)
                             (format "Owning the stock (long-stock) is number {} of {}, with a ratio of {:.1%}: {} of the positions make more for each dollar they could lose, with {} at {:,.2f} on {}.\n"
                                     (+ stock-row 1) rows (vector-ref (table-column positions "ratio") stock-row) stock-row
                                     (position-comparison-stock comparison) (position-comparison-expected-price comparison)
                                     (date->string (position-comparison-expiration comparison)))
                             "Owning the stock is not among them.\n")))
        (display "\nFor the best few of one kind, and an order for it:\n")
        (display "  (define search (position-comparison-search comparison 'covered-call))\n")
        (display "  (show-option-spreads search)\n")))))
