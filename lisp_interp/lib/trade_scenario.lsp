; trade_scenario.lsp
;
; A scenario -- "crude oil will be at 75 on December 1", "Apple will be at 380 on January 15" -- and every way of
; trading on it with options: which position makes the most, for what it risks, if the scenario comes to pass?
;
; option_spreads.lsp and option_positions.lsp answer that for one expiration day: the price you expect is the
; underlying's price on the day the options expire, and every position is worth, that day, what its options are
; worth when they expire. A scenario's date need not be an expiration day. This file searches every expiration on
; or after it, and values each position on the scenario's date:
;
;   An option that expires on the date is worth what it pays then: a call the price less the strike, or nothing;
;   a put the strike less the price, or nothing.
;
;   An option that expires later still has time to run, and is worth more than that: what the Black-Scholes formula
;   says (Black's, for a future's option), with the time it has left after the date, at the volatility that its
;   own price implies today. Keeping each option's volatility as it is today is the assumption ("sticky strike");
;   a big move usually changes volatilities too, and this leaves that out.
;
; The positions are the seventeen kinds of option_spreads.lsp, made of options of one expiration, and two more
; that only a date before an expiration makes worth looking at: the calendar spreads, which sell an option that
; expires on or after the date and buy the same strike's option that expires later (a call calendar, of calls; a
; put calendar, of puts). On the date the near option is worth little and the far one still has its time: the
; spread does best if the price is near the strike then.
;
; For each position, on the scenario's date:
;
;   profit         what it is worth then, at the price expected, less what it costs today: if you are right
;   max-loss       the most it can lose then, at any price: if you are wrong. For a position that expires on the
;                  date this is exact (the profit is straight lines between the strikes); for one that expires
;                  later it is the worst of the profits at 300 prices from 0 to three times the higher of today's
;                  price and the price expected, so it is close, not exact
;   if-unchanged   the profit if the price on the date is today's: if nothing happens. Options that expire later
;                  have lost some of their time value by then
;   roi            the profit as a share of the money committed: what a position that costs you (a debit) costs,
;                  and for one that pays you (a credit), the most it can lose, which is about what your broker
;                  holds back as margin (a cash-secured put's is the cash for the shares). Shares are paid for in
;                  full (a future's are not: only margin is put up for one, so its roi here is low)
;   ratio          the profit as a share of the most it can lose, as option_spreads.lsp ranks them
;   breakeven-1, -2  the prices on the date at which it breaks even
;
; Futures. A future's options are on several futures, a delivery month each, with prices of their own: crude oil's
; options that expire in November are on the December future, December's on January's, and so on. The scenario's
; price is the price of one of them, the *reference* -- the future of the options that expire first on or after the
; date, unless :underlying says another -- and each of the others is taken to keep its difference from it, as it is
; today: if December is at 61 and January at 61.5, crude at 75 is December at 75 and January at 75.5.
;
; What is left out, as in option_spreads.lsp: commissions; that the options would be sold on the date at their bids,
; not their values (the cost is at today's asks and bids, the worth at the formula's middle); that an option you
; sold can be exercised early; dividends, apart from what today's prices already say; and how likely the scenario is.
; A position ranked first for a price you expect to the penny can be very fragile: look at max-loss and
; if-unchanged, and at the next few rows.
;
; Usage:
;   (define scenario (trade-scenario creds "CL" 75.0 (date 2026 12 1)))     ; fetches crude oil's options, ranks
;   (show-trade-scenario scenario)                                            ; the best, and the best of each kind
;   (trade-scenario-trades scenario)                                          ; the table of every position
;   (trade-scenario creds "AAPL" 380.0 (date 2027 1 15) :kinds '(bull-call long-call call-calendar))
;
; Or, for a chain you have already (from tastytrade-option-chain):
;   (trade-scenario-for-chain chain 75.0 (date 2026 12 1) :contract-size 1000 :unit "barrel")

(require "option_spreads.lsp")

(defstruct trade-scenario
  symbol            ; the reference underlying: the stock, or the future whose price the scenario is of
  today-price       ; its price today
  price             ; its price on the date, in the scenario
  date              ; the scenario's date
  rate              ; the interest rate, continuously compounded, that the formula discounts at
  prices            ; bid-ask or mid: the prices the options are bought and sold at today
  (contract-size option-contract-size)   ; how many of the underlying's units a contract covers: 100 shares, 1,000 barrels
  (unit "share")    ; what one is called: the prices and profits are for one
  underlyings       ; a table of the underlyings: underlying, today (its price), scenario (its price on the date)
  strikes           ; (lowest highest): the strikes of the options searched
  trades)           ; a table: a row for each position, the best first

(define trade-scenario--leg-slots 4)          ; the most options a position has (an iron condor's four)
(define trade-scenario--grid-points 300)      ; the prices that a later-expiring position's worst case is looked for at

(define trade-scenario-calendar-kinds '(call-calendar put-calendar))

; How many of a future's units its option covers, and what to call one: the dollars of a contract are the price
; times the first. (Corn's, soybeans' and wheat's prices are in cents, so theirs is the dollars of a cent.) Check the
; exchange's specification for the contract you trade.
(define trade-scenario-futures-units
  '(("ES" 50 "point") ("MES" 5 "point") ("NQ" 20 "point") ("MNQ" 2 "point") ("YM" 5 "point") ("RTY" 50 "point")
    ("M2K" 5 "point") ("ZT" 2000 "point") ("ZF" 1000 "point") ("ZN" 1000 "point") ("TN" 1000 "point")
    ("ZB" 1000 "point") ("UB" 1000 "point") ("SR3" 2500 "point")
    ("CL" 1000 "barrel") ("MCL" 100 "barrel") ("BZ" 1000 "barrel") ("NG" 10000 "MMBtu") ("RB" 42000 "gallon")
    ("HO" 42000 "gallon") ("GC" 100 "ounce") ("MGC" 10 "ounce") ("SI" 5000 "ounce") ("HG" 25000 "pound")
    ("PL" 50 "ounce") ("ZC" 50 "bushel") ("ZS" 50 "bushel") ("ZW" 50 "bushel") ("LE" 400 "pound") ("HE" 400 "pound")
    ("6E" 125000 "euro") ("6J" 12500000 "yen") ("6B" 62500 "pound sterling") ("6C" 100000 "Canadian dollar")
    ("6A" 100000 "Australian dollar") ("6S" 125000 "Swiss franc") ("BTC" 5 "bitcoin") ("ETH" 50 "ether")))

; ---------------------------------------------------------------------------
; 1. Each option's volatility, from its price
; ---------------------------------------------------------------------------

(define (trade-scenario--futures? chain)
  "Whether the chain is a future's options: their symbols start with ./, as tastytrade writes them."
  (string-starts-with? (vector-ref (table-column chain "symbol") 0) "./"))

(define (trade-scenario--with-days chain today)
  "The chain with a days-to-expiration column, the days from today to each option's expiration, if it has none (as
schwab-option-chain's has not), and an implied-volatility column of nan, if it has none."
  (let* ((with-days (if (assoc "days-to-expiration" chain)
                        chain
                        (table-add-column chain "days-to-expiration" (days-between today (table-column chain "expiration-date"))))))
    (if (assoc "implied-volatility" with-days)
        with-days
        (table-add-column with-days "implied-volatility" (* nan (table-column with-days "strike"))))))

(define (trade-scenario--volatilities chain rate futures?)
  "A hash table from each option's symbol to its volatility: the one at which the Black-Scholes formula (Black's, for
a future's option, which is the formula with a dividend yield of the rate) gives the middle of its bid and ask today,
or tastytrade's implied volatility where none does. (tastytrade works its own out another way, which doesn't give its
prices back: see vol_smile.lsp.)"
  (let ((found (make-hash-table)))
    (dolist (type '("Call" "Put"))
      (let ((options (table-filter chain (= (table-column chain "type") type))))
        (when (> (table-row-count options) 0)
          (let* ((years (vector-clip (/ (table-column options "days-to-expiration") 365.0) (/ 1 365.0) 100))
                 (implied (implied-vol (table-column options "mid") (string-downcase type)
                                       (table-column options "underlying-price") (table-column options "strike")
                                       years rate :dividend-yield (if futures? rate 0)))
                 (volatility (vector-where (vector-nan? implied) (table-column options "implied-volatility") implied)))
            (loop for symbol in (vector->list (table-column options "symbol"))
                  for vol in (vector->list volatility)
                  do (hash-table-set! found symbol vol))))))
    found))

; ---------------------------------------------------------------------------
; 2. What a set of positions is worth on the date
; ---------------------------------------------------------------------------
; A batch is positions of one kind, one underlying and the same expirations, as vectors: one position for each
; element. Each leg is the type of option (call or put), how many are bought (a minus sign: sold), the years it has
; left after the date (0: it expires then), and vectors of its strikes, volatilities, symbols, prices today, and
; expiration dates (as text).

(defstruct trade-scenario--batch
  kind expires underlying shares legs cost exact)    ; exact: '(), or (max-loss breakeven-1 breakeven-2) at expiration

(defstruct trade-scenario--leg
  type quantity years strikes vols symbols prices expiration)

(define (trade-scenario--leg-worth leg price rate futures?)
  "What one of the leg's options is worth on the date, with the underlying at price, for each position."
  (let ((type (trade-scenario--leg-type leg))
        (strikes (trade-scenario--leg-strikes leg)))
    (if (<= (trade-scenario--leg-years leg) 0)
        (if (eq? type 'call) (vector-clip (- price strikes) 0 1e12) (vector-clip (- strikes price) 0 1e12))
        (bsm-price (symbol->string type) price strikes (trade-scenario--leg-years leg) rate
                   (trade-scenario--leg-vols leg) :dividend-yield (if futures? rate 0)))))

(define (trade-scenario--worth batch price rate futures?)
  "What each position of the batch is worth on the date, with the underlying at price: its shares, and its options,
those bought counted plus and those sold minus."
  (let ((total (+ (* 0 (trade-scenario--batch-cost batch)) (* (trade-scenario--batch-shares batch) price))))
    (dolist (leg (trade-scenario--batch-legs batch))
      (set! total (+ total (* (trade-scenario--leg-quantity leg) (trade-scenario--leg-worth leg price rate futures?)))))
    total))

(define (trade-scenario--on-a-grid batch high rate futures?)
  "The most each position can lose on the date, and the prices where it breaks even (the lowest and the highest), from
its profits at trade-scenario--grid-points prices from 0 to high: (max-loss breakeven-1 breakeven-2), vectors, nan
where there is no breakeven. Between two prices the profit is taken to be a straight line."
  (let* ((cost (trade-scenario--batch-cost batch))
         (step (/ high trade-scenario--grid-points))
         (before (- (trade-scenario--worth batch 0.000001 rate futures?) cost))
         (lowest before)
         (first-root (* nan cost))
         (last-root (* nan cost)))
    (loop for point from 1 to trade-scenario--grid-points
          do (let* ((price (* point step))
                    (profit (- (trade-scenario--worth batch price rate futures?) cost))
                    (crosses (vector-or (vector-and (< before 0) (>= profit 0)) (vector-and (> before 0) (<= profit 0))))
                    (root (+ (- price step) (* step (vector-div (- before) (- profit before))))))
               (set! lowest (vector-where (< profit lowest) profit lowest))
               (set! first-root (vector-where (vector-and crosses (vector-nan? first-root)) root first-root))
               (set! last-root (vector-where crosses root last-root))
               (set! before profit)))
    (list (- lowest) first-root (vector-where (= first-root last-root) nan last-root))))

; ---------------------------------------------------------------------------
; 3. The batches: positions of one expiration, and calendars
; ---------------------------------------------------------------------------

(define (trade-scenario--years-after day expiration)
  (/ (days-between day expiration) 365.0))

(define (trade-scenario--from-search search day volatilities)
  "The positions of a spread-search, as a batch. Those that expire on the date have their exact most to lose and
breakevens from the search."
  (let* ((kind (option-spreads--kind (spread-search-kind search)))
         (spreads (spread-search-spreads search))
         (expiration (spread-search-expiration search))
         (years (trade-scenario--years-after day expiration))
         (column (lambda (name place) (table-column spreads (format "{}-{}" name place)))))
    (make-trade-scenario--batch
      :kind (spread-search-kind search)
      :expires (date->string expiration)
      :underlying (spread-search-stock search)
      :shares (spread-kind-shares kind)
      :cost (table-column spreads "cost")
      :exact (if (<= years 0)
                 (list (table-column spreads "max-loss") (table-column spreads "breakeven-1") (table-column spreads "breakeven-2"))
                 '())
      :legs (loop for leg in (spread-kind-legs kind)
                  for place from 1
                  collect (make-trade-scenario--leg
                            :type (option-spreads--leg-type leg) :quantity (option-spreads--leg-quantity leg) :years years
                            :strikes (column "strike" place)
                            :vols (vector-map (lambda (symbol) (hash-table-ref volatilities symbol nan)) (column "symbol" place))
                            :symbols (column "symbol" place) :prices (column "price" place)
                            :expiration (date->string expiration))))))

(define (trade-scenario--calendars chain kind-name day near far prices min-open-interest min-volume volatilities)
  "The calendar spreads of the kind (call-calendar or put-calendar) that sell an option expiring on near and buy the
same strike's expiring on far, as a batch: one for each strike that both have quoted."
  (let* ((type (if (eq? kind-name 'call-calendar) "Call" "Put"))
         (near-options (option-spreads--quoted chain type near prices min-open-interest min-volume))
         (far-options (option-spreads--quoted chain type far prices min-open-interest min-volume))
         (at (vector-positions (table-column far-options "key") (table-column near-options "key")))
         (there (>= at 0))
         (far-at (vector-select at there))
         (near-column (lambda (name) (vector-select (table-column near-options name) there)))
         (far-column (lambda (name) (vector-gather (table-column far-options name) far-at)))
         (leg (lambda (quantity expiration column)
                (make-trade-scenario--leg
                  :type (if (eq? kind-name 'call-calendar) 'call 'put) :quantity quantity
                  :years (trade-scenario--years-after day expiration)
                  :strikes (column "strike")
                  :vols (vector-map (lambda (symbol) (hash-table-ref volatilities symbol nan)) (column "symbol"))
                  :symbols (column "symbol")
                  :prices (column (if (> quantity 0) "buy" "sell"))
                  :expiration (date->string expiration)))))
    (make-trade-scenario--batch
      :kind kind-name
      :expires (format "{} & {}" (date->string near) (date->string far))
      :underlying (vector-ref (table-column chain "underlying") 0)
      :shares 0
      :cost (- (far-column "buy") (near-column "sell"))
      :exact '()
      :legs (list (leg -1 near near-column) (leg 1 far far-column)))))

(define (trade-scenario--has? chain type day)
  (> (table-row-count (table-filter chain (vector-and (= (table-column chain "type") type)
                                                      (= (table-column chain "expiration-date") day))))
     0))

(define (trade-scenario--possible? kind chain day)
  "Whether the chain's options on one underlying have the types the kind needs, expiring on day."
  (every (lambda (leg) (trade-scenario--has? chain (if (eq? (option-spreads--leg-type leg) 'call) "Call" "Put") day))
         (spread-kind-legs kind)))

; ---------------------------------------------------------------------------
; 4. A batch's rows
; ---------------------------------------------------------------------------

(define (trade-scenario--rows batch expected today-price high rate futures? min-risk)
  "The batch's positions as a table of the scenario's columns (see trade-scenario-for-chain), those that can be valued
and can lose something."
  (let* ((cost (trade-scenario--batch-cost batch))
         (count (vector-length cost))
         (worth (trade-scenario--worth batch expected rate futures?))
         (unchanged (- (trade-scenario--worth batch today-price rate futures?) cost))
         (risks (if (null? (trade-scenario--batch-exact batch))
                    (trade-scenario--on-a-grid batch high rate futures?)
                    (trade-scenario--batch-exact batch)))
         (max-loss (first risks))
         (profit (- worth cost))
         (committed (vector-where (> cost 0) cost max-loss))
         (keep (vector-and (vector-not (vector-nan? worth)) (> max-loss option-spreads--least-risk) (>= max-loss min-risk)))
         (pick (lambda (v) (vector-select v keep)))
         (kept (vector-sum keep))
         (text (lambda (value) (make-vector kept value)))
         (legs (trade-scenario--batch-legs batch))
         (slot (lambda (place get missing)
                 (if (<= place (length legs)) (pick (get (list-ref legs (- place 1)))) (text missing)))))
    (append
      (list (cons "kind" (text (symbol->string (trade-scenario--batch-kind batch))))
            (cons "expires" (text (trade-scenario--batch-expires batch)))
            (cons "underlying" (text (trade-scenario--batch-underlying batch)))
            (cons "shares" (text (trade-scenario--batch-shares batch))))
      (apply append
             (loop for place from 1 to trade-scenario--leg-slots
                   collect (list (cons (format "type-{}" place)
                                       (slot place (lambda (leg) (make-vector count (symbol->string (trade-scenario--leg-type leg)))) ""))
                                 (cons (format "quantity-{}" place)
                                       (slot place (lambda (leg) (make-vector count (trade-scenario--leg-quantity leg))) 0))
                                 (cons (format "expiration-{}" place)
                                       (slot place (lambda (leg) (make-vector count (trade-scenario--leg-expiration leg))) ""))
                                 (cons (format "symbol-{}" place) (slot place trade-scenario--leg-symbols ""))
                                 (cons (format "strike-{}" place) (slot place trade-scenario--leg-strikes nan))
                                 (cons (format "price-{}" place) (slot place trade-scenario--leg-prices nan)))))
      (list (cons "cost" (pick cost))
            (cons "max-loss" (pick max-loss))
            (cons "worth" (pick worth))
            (cons "profit" (pick profit))
            (cons "roi" (pick (vector-div profit committed)))
            (cons "ratio" (pick (vector-div profit max-loss)))
            (cons "if-unchanged" (pick unchanged))
            (cons "breakeven-1" (pick (second risks)))
            (cons "breakeven-2" (pick (third risks)))))))

(define (trade-scenario--stock-row underlying today-price expected)
  "Owning the underlying from today to the date, as a row, to compare the rest with: it costs today's price, is worth
the price expected, and can lose all it costs."
  (let ((batch (make-trade-scenario--batch :kind 'long-stock :expires "" :underlying underlying :shares 1
                                           :legs '() :cost (vector today-price)
                                           :exact (list (vector today-price) (vector today-price) (vector nan)))))
    (trade-scenario--rows batch expected today-price (* 3 expected) 0.0 #f 0)))

; ---------------------------------------------------------------------------
; 5. The scenario
; ---------------------------------------------------------------------------

(define (trade-scenario--underlyings chain reference expected)
  "A table of the chain's underlyings: underlying, today (its price), and scenario (its price on the date: the
expected price for the reference, and for each of the others, the expected price plus its difference from the
reference today)."
  (let* ((names (vector-unique (table-column chain "underlying")))
         (price-of (lambda (name) (vector-ref (table-column (table-filter chain (= (table-column chain "underlying") name))
                                                            "underlying-price")
                                              0)))
         (today-prices (vector-map price-of names))
         (reference-price (price-of reference)))
    (make-table "underlying" names "today" today-prices "scenario" (+ expected (- today-prices reference-price)))))

(define (trade-scenario--reference chain day underlying)
  "The underlying whose price the scenario is of: :underlying, or the one of the options that expire first on or after
the date (of those, the one first in the chain)."
  (if (not (null? underlying))
      (begin
        (unless (> (vector-length (vector-positions (table-column chain "underlying") (vector underlying))) 0)
          (error "trade-scenario: the chain has no options on" underlying))
        underlying)
      (let* ((later (table-filter chain (>= (table-column chain "expiration-date") day)))
             (first-day (vector-min (table-column later "expiration-date"))))
        (vector-ref (table-column (table-filter later (= (table-column later "expiration-date") first-day)) "underlying") 0))))

(define (trade-scenario-for-chain chain price day
                                  &key (kinds '()) (prices 'bid-ask) (min-open-interest 1) (min-volume 0) (min-risk 0)
                                  (max-width '()) (underlying '()) (rate 0.04) (rank-by 'roi) (today (today))
                                  (contract-size option-contract-size) (unit "share"))
  "Every position of the kinds that can be made of the chain's options expiring on or after day (a date, or
YYYY-MM-DD text), valued on day if the underlying is at price then, ranked: a trade-scenario (see the top of this
file). chain is a table as tastytrade-option-chain makes. The kinds are all of option-spread-kinds' and the call and
put calendars, unless :kinds is a list of the names of the ones you want. The table of trades has a row for each
position, the best first by :rank-by (roi, the default, ratio, or profit), with the columns:
  kind, expires (the expiration, or the two of a calendar), underlying, shares (1 if it buys the underlying)
  type-1 .. type-4, quantity-1 .., expiration-1 .., symbol-1 .., strike-1 .., price-1 ..
                 its options, lowest strike first (empty, past its last): call or put, how many bought (minus:
                 sold), when it expires, its symbol and strike, and the price paid (the ask) or got (the bid) today
  cost           what it costs today, for one unit, with its shares; negative, if it pays you
  max-loss       the most it can lose on the date, at any price
  worth, profit  what it is worth on the date at the price expected, and that less the cost
  roi            profit over the money committed: the cost, or for a credit, max-loss
  ratio          profit over max-loss
  if-unchanged   the profit on the date if the price then is today's
  breakeven-1, breakeven-2   the prices on the date where it breaks even
:rate is the interest rate, continuously compounded (0.04), which the Black-Scholes formula discounts at. :today is
the day of the chain's prices, for a chain without days-to-expiration (as schwab-option-chain's). For a
future's options, :underlying names the future the scenario's price is of (see the top of this file), and
:contract-size and :unit say how many of its units a contract covers and what to call one. The others are those of
option-spreads-for-chain; :min-volume is 0 here, since a scenario is often looked at with the market closed."
  (unless (member rank-by '(roi ratio profit))
    (error "trade-scenario: :rank-by is roi, ratio, or profit, not" rank-by))
  (option-spreads--check-units contract-size unit "trade-scenario")
  (let* ((day (option-spreads--day day))
         (names (if (null? kinds) (append (map spread-kind-name spread-kinds) trade-scenario-calendar-kinds) kinds))
         (check (dolist (name names)
                  (unless (member name trade-scenario-calendar-kinds) (option-spreads--kind name))))
         (later (trade-scenario--with-days (table-filter chain (>= (table-column chain "expiration-date") day)) today))
         (check-later (when (= (table-row-count later) 0)
                        (error (format "trade-scenario: the chain has no options expiring on or after {}" (date->string day)))))
         (futures? (trade-scenario--futures? chain))
         (reference (trade-scenario--reference chain day underlying))
         (underlyings (trade-scenario--underlyings later reference price))
         (volatilities (trade-scenario--volatilities later rate futures?))
         (option-kinds (filter (lambda (name) (not (or (member name trade-scenario-calendar-kinds) (eq? name 'long-stock))))
                               names))
         (tables '()))
    (dolist (name (vector->list (table-column underlyings "underlying")))
      (let* ((on (table-filter later (= (table-column later "underlying") name)))
             (row (vector-ref (vector-positions (table-column underlyings "underlying") (vector name)) 0))
             (today-price (vector-ref (table-column underlyings "today") row))
             (expected (vector-ref (table-column underlyings "scenario") row))
             (high (* 3 (max expected today-price)))
             (days (sort (vector->list (vector-unique (table-column on "expiration-date")))))
             (add (lambda (batch)
                    (when (> (vector-length (trade-scenario--batch-cost batch)) 0)
                      (push (trade-scenario--rows batch expected today-price high rate futures? min-risk) tables)))))
        (when (> (table-row-count on) 0)
          (dolist (expiration days)
            (dolist (name option-kinds)
              (when (trade-scenario--possible? (option-spreads--kind name) on expiration)
                (add (trade-scenario--from-search
                       (option-spreads-for-chain on name expiration expected :prices prices
                                                 :min-open-interest min-open-interest :min-volume min-volume
                                                 :min-risk min-risk :max-width max-width
                                                 :contract-size contract-size :unit unit)
                       day volatilities)))))
          (dolist (name (filter (lambda (name) (member name trade-scenario-calendar-kinds)) names))
            (loop for near in days
                  do (dolist (far (filter (lambda (other) (> other near)) days))
                       (when (and (trade-scenario--has? on (if (eq? name 'call-calendar) "Call" "Put") near)
                                  (trade-scenario--has? on (if (eq? name 'call-calendar) "Call" "Put") far))
                         (add (trade-scenario--calendars on name day near far prices min-open-interest min-volume
                                                         volatilities)))))))))
    (when (member 'long-stock names)
      (let ((row (vector-ref (vector-positions (table-column underlyings "underlying") (vector reference)) 0)))
        (push (trade-scenario--stock-row reference (vector-ref (table-column underlyings "today") row) price) tables)))
    (make-trade-scenario
      :symbol reference
      :today-price (vector-ref (table-column underlyings "today")
                               (vector-ref (vector-positions (table-column underlyings "underlying") (vector reference)) 0))
      :price price :date day :rate rate :prices prices :contract-size contract-size :unit unit
      :underlyings underlyings
      :strikes (list (vector-min (table-column later "strike")) (vector-max (table-column later "strike")))
      :trades (if (null? tables)
                  (error "trade-scenario: no position can be made of the chain's options: they need a bid and an ask, and open interest")
                  (table-sort (apply table-append tables) (symbol->string rank-by) #t)))))

(define (trade-scenario--units symbol)
  "The contract size and unit of a future's options, by its code (CL, or /CL), from trade-scenario-futures-units, or
'() for a stock."
  (let ((found (assoc (if (string-starts-with? symbol "/") (substring symbol 1 (string-length symbol)) symbol)
                      trade-scenario-futures-units)))
    (if found (cdr found) '())))

(define (trade-scenario creds symbol price day
                        &key (kinds '()) (prices 'bid-ask) (min-open-interest 1) (min-volume 0) (min-risk 0)
                        (max-width '()) (underlying '()) (rate '()) (rank-by 'roi) (strikes 40) (months '())
                        (contract-size '()) (unit '()))
  "Fetch the options of symbol -- a stock (\"AAPL\") or a future's code from (tastytrade-products) (\"CL\") -- from
tastytrade, and rank every position that could be traded on the scenario that it is at price on day: see
trade-scenario-for-chain. :strikes (40) is how many strikes nearest today's price to keep of each expiration; give
more for a scenario far from today's price (show-trade-scenario says when the price is beyond the strikes there are). :months is how many months of expirations (of a stock's) or delivery
months (of a future's) to get: three more than the months to the date, unless it is given. :rate is the interest
rate, from the Treasury's curve to the date, unless it is given. A future's :contract-size and :unit are from
trade-scenario-futures-units, unless they are given; a stock's are 100 and share."
  (let* ((day (option-spreads--day day))
         (units (trade-scenario--units symbol))
         (months (if (null? months) (+ 3 (max 0 (months-between (today) day))) months))
         (rate (if (null? rate)
                   (let ((years (max (/ 1 12.0) (/ (days-between (today) day) 365.0))))
                     (/ (- (log (curve-discount-factors (curve-forward-rates (treasury-zero-curve (treasury-par-curve)))
                                                        years)))
                        years))
                   rate)))
    (unless (market-open?)
      (display "The market is closed now: the bids and asks are from its last close.\n\n"))
    (trade-scenario-for-chain (tastytrade-option-chain creds symbol months strikes) price day
                              :kinds kinds :prices prices :min-open-interest min-open-interest :min-volume min-volume
                              :min-risk min-risk :max-width max-width :underlying underlying :rate rate :rank-by rank-by
                              :contract-size (cond ((not (null? contract-size)) contract-size)
                                                   ((null? units) option-contract-size)
                                                   (else (first units)))
                              :unit (cond ((not (null? unit)) unit) ((null? units) "share") (else (second units))))))

; ---------------------------------------------------------------------------
; 6. Showing it
; ---------------------------------------------------------------------------

(define (trade-scenario-position-in-words scenario row)
  "The position in a row of the scenario's trades, in words: buy 1 70.00 call, sell 1 75.00 call -- with the
expirations of a calendar's options, and the underlying it buys, if it does."
  (let* ((trades (trade-scenario-trades scenario))
         (cell (lambda (name) (vector-ref (table-column trades name) row)))
         (calendar? (string-contains? (cell "expires") "&")))
    (string-join
      (append (if (> (cell "shares") 0)
                  (list (format "buy {}" (if (= (trade-scenario-contract-size scenario) option-contract-size)
                                             (format "{} shares" option-contract-size)
                                             (cell "underlying"))))
                  '())
              (loop for place from 1 to trade-scenario--leg-slots
                    when (not (equal? (cell (format "type-{}" place)) ""))
                    collect (let ((quantity (cell (format "quantity-{}" place))))
                              (format "{} {} {:,.2f} {}{}{}" (if (> quantity 0) "buy" "sell") (abs quantity)
                                      (cell (format "strike-{}" place)) (cell (format "type-{}" place))
                                      (if (> (abs quantity) 1) "s" "")
                                      (if calendar? (format " ({})" (cell (format "expiration-{}" place))) "")))))
      ", ")))

(define (trade-scenario--shown scenario rows)
  "A table of these rows of the trades, to show: the kind, when it expires, the position in words, and its numbers."
  (let ((trades (trade-scenario-trades scenario)))
    (make-table "kind" (vector-gather (table-column trades "kind") rows)
                "expires" (vector-gather (table-column trades "expires") rows)
                "position" (vector-map (lambda (row) (trade-scenario-position-in-words scenario row)) rows)
                "cost" (vector-gather (table-column trades "cost") rows)
                "max-loss" (vector-gather (table-column trades "max-loss") rows)
                "profit" (vector-gather (table-column trades "profit") rows)
                "roi" (vector-gather (table-column trades "roi") rows)
                "ratio" (vector-gather (table-column trades "ratio") rows)
                "if-unchanged" (vector-gather (table-column trades "if-unchanged") rows)
                "breakeven-1" (vector-gather (table-column trades "breakeven-1") rows)
                "breakeven-2" (vector-gather (table-column trades "breakeven-2") rows))))

(define (trade-scenario-best-of-each-kind scenario)
  "A table of the best position of each kind (by the scenario's ranking), the best first, as show-trade-scenario shows."
  (let* ((kinds (table-column (trade-scenario-trades scenario) "kind"))
         (firsts (vector-map (lambda (kind) (vector-ref (vector-positions kinds (vector kind)) 0)) (vector-unique kinds))))
    (trade-scenario--shown scenario (sort firsts))))

(define (show-trade-scenario scenario &key (count 15))
  "Show a trade-scenario: what the scenario is, the best count positions, and the best of each kind."
  (let* ((trades (trade-scenario-trades scenario))
         (underlyings (trade-scenario-underlyings scenario))
         (size (trade-scenario-contract-size scenario))
         (formats '(("cost" ",.2f") ("max-loss" ",.2f") ("profit" ",.2f") ("roi" ".0%") ("ratio" ".0%")
                    ("if-unchanged" ",.2f") ("breakeven-1" ",.2f") ("breakeven-2" ",.2f"))))
    (display (format "The scenario: {} at {:,.2f} on {} (it is at {:,.2f} now). {} positions, from options expiring on {} or later; bought and sold today at the {} prices, valued on {} with an interest rate of {:.2%}.\n"
                     (trade-scenario-symbol scenario) (trade-scenario-price scenario) (date->string (trade-scenario-date scenario))
                     (trade-scenario-today-price scenario) (table-row-count trades) (date->string (trade-scenario-date scenario))
                     (if (eq? (trade-scenario-prices scenario) 'mid) "middle" "ask and bid")
                     (date->string (trade-scenario-date scenario)) (trade-scenario-rate scenario)))
    (when (> (table-row-count underlyings) 1)
      (display "Each future is taken to keep its difference from the first:\n")
      (display-table underlyings '(("today" ",.2f") ("scenario" ",.2f"))))
    (let ((lowest (first (trade-scenario-strikes scenario)))
          (highest (second (trade-scenario-strikes scenario))))
      (when (or (< (trade-scenario-price scenario) lowest) (> (trade-scenario-price scenario) highest))
        (display (format "The strikes of the options go from {:,.2f} to {:,.2f}, and the scenario's price is beyond them: there are better positions with strikes nearer it. Ask for more strikes (trade-scenario's :strikes, or tastytrade-option-chain's last argument).\n"
                         lowest highest))))
    (display (format "The amounts are for {} (a contract is {:,} {}: multiply by {:,} for a contract's dollars).\n\n"
                     (option-spreads--a (trade-scenario-unit scenario)) size
                     (option-spreads--plural (trade-scenario-unit scenario) size) size))
    (display (format "The best {}:\n" (min count (table-row-count trades))))
    (display-table (trade-scenario--shown scenario (vector-range (min count (table-row-count trades)))) formats)
    (display "\nThe best of each kind:\n")
    (display-table (trade-scenario-best-of-each-kind scenario) formats)))
