; option_spreads.lsp
;
; Option spreads: of a stock's options that expire on one day, which
; combination of calls and puts is best, if you expect the stock to be at a
; certain price on that day? Ten kinds of spread are ranked here -- the
; vertical spreads (bull call, bear call, bull put, bear put), butterflies
; (of calls or of puts), the iron condor and the iron butterfly, and the long
; straddle and long strangle -- each of them the same way. (call_spreads.lsp
; has a long explanation of the simplest, the bull call spread, with an
; example worked out by hand: read that first if spreads are new to you.)
;
; What a spread is. An option is a right to buy the stock (a call) or to sell
; it (a put) at its strike on the expiration day. On that day a call is worth
; the stock's price less the strike, or nothing if that's less; a put, the
; strike less the stock's price, or nothing. A spread is several options,
; some bought and some sold, which together are worth more or less as the
; stock ends higher or lower. Each kind is a pattern of legs, listed from
; the lowest strike to the highest (+ is bought, - sold):
;
;   bull call spread    +call K1, -call K2       worth more as the stock rises, up to K2
;   bear call spread    -call K1, +call K2       worth less as it rises: kept if it ends below K1
;   bull put spread     +put K1,  -put K2        kept if the stock ends above K2
;   bear put spread     -put K1,  +put K2        worth more as the stock falls, down to K1
;   call butterfly      +call K1, -2 call K2, +call K3     worth most with the stock at K2
;   put butterfly       +put K1,  -2 put K2,  +put K3      (the same shape, made of puts)
;   iron condor         +put K1, -put K2, -call K3, +call K4      kept if it ends between K2 and K3
;   iron butterfly      the iron condor with K2 = K3             worth most with the stock at K2
;   long straddle       +call K, +put K          worth more the farther the stock ends from K
;   long strangle       +put K1, +call K2        the same, with a gap between the strikes
;
; In a butterfly the strikes are equally far apart (K2 - K1 = K3 - K2), and in
; the iron condor and the iron butterfly the two wings are the same width
; (K2 - K1 = K4 - K3). The shorts -- a short straddle or strangle, say -- are
; left out because they can lose without limit.
;
; What it costs, and what it can lose. What you pay for a spread is its cost,
; or net debit: what you pay for the options you buy, less what you get for
; those you sell. If that is negative you are paid, and it is a credit. What a
; spread is worth on the expiration day, with the stock at S, is the sum of
; its legs' worths (each of them bought or sold, and a butterfly's middle
; option twice), and the profit is that less the cost. A spread's worth
; changes direction only at its strikes, so its best and worst cases are at its
; strikes (or with the stock at 0, or, for a straddle or strangle, at as high
; a price as you like). So for each spread the most it can lose, the most it
; can make, and the prices where it breaks even are found from its profit at
; each of its strikes and at 0. The ratio this file ranks the spreads by is
; the same for all of them:
;
;     the profit at S  /  the most you can lose.
;
; Prices. You buy at the ask and sell at the bid (:prices 'bid-ask, the
; default). With :prices 'mid it is the middle of each's bid and ask, which is
; what you'd get if you could trade in the middle. Be careful with 'mid: thin
; options have wide, ragged quotes, and their middles can make a spread look
; far cheaper than it can be traded. A higher :min-open-interest guards
; against these. The prices are for one share; an option contract is for 100
; (option-contract-size).
;
; Which options count. Each must have a bid and an ask above 0, and open
; interest of at least :min-open-interest (1) and volume of at least
; :min-volume (1: the option has traded at least once today). Volume counts
; today's trades, so it is 0 for every option before the market opens: give
; :min-volume 0 then. A spread with no most to lose (from quotes that don't
; agree: a credit as big as the spread's width, say -- or a tenth of a cent
; short of it, which is the rounding of the numbers) is left out, as is one
; that can lose less than :min-risk (0). Spreads that can lose almost nothing
; have huge ratios if the stock gets where they pay, and almost no chance of
; doing it: :min-risk leaves them out. :max-width (in dollars) leaves out the
; spreads whose strikes are farther apart than that (a wing, for a butterfly or
; a condor), which also makes the search of a big chain quicker.
;
; What the ratio leaves out. It says how much you'd make, per dollar you could
; lose, if the stock is at the price you expect. It doesn't say how likely
; that is (the price you expect is one price, and the stock can end anywhere),
; and it ignores commissions, margin (a spread with a sold option needs
; some of your money held, and your broker's approval), and that an option
; you sold can be exercised before expiration. A butterfly or a condor ranked
; first for a price you expect to the penny is the most fragile of all.
;
; Usage:
;   (load "option_spreads.lsp")
;   (option-spread-kinds)                         ; a table of the kinds
;   (define search (option-spreads creds "SPY" 'iron-condor (date 2026 11 20) 765))   ; live quotes, from Schwab
;   (show-option-spreads search)                  ; the best, and the next few
;   (spread-search-spreads search)                ; the table of all of them, best first
;   (define order (option-spread-order search))   ; an order for the best one: nothing is sent
;   (show-spread-order order)                     ; what it would do, in words
;   (schwab-preview-order creds "Brokerage" order)  ; what Schwab makes of it: nothing is placed
;   (schwab-place-order creds "Brokerage" order :confirm #t)   ; this places it, for real
;
; Or, for a chain you have already, from Schwab or tastytrade:
;   (option-spreads-for-chain chain 'bull-put (date 2026 11 20) 765)

(defstruct spread-search
  kind              ; which kind of spread: bull-call, iron-condor, ... (see option-spread-kinds)
  stock             ; the stock's symbol
  stock-price       ; its price when the chain was got
  expiration        ; the day the options expire
  expected-price    ; the stock's price that day, as expected
  prices            ; bid-ask or mid: the prices the spreads cost at
  spreads)          ; a table: a row for each spread, the best first

(define option-contract-size 100)         ; shares in an option contract
(define option-spreads--least-risk 0.001)  ; a share's most to lose below this is nothing: a tenth of a cent

; ---------------------------------------------------------------------------
; 1. The kinds
; ---------------------------------------------------------------------------
; A kind is its legs, lowest strike first: the type of option (call or put)
; and how many are bought (a minus sign: sold). The shape says how the strikes
; of a spread of this kind are found, in section 3; the strategy is the name
; Schwab gives it in an order.

(defstruct spread-kind
  name legs shape strategy label text)

(define spread-kinds
  (list
    (make-spread-kind
      :name 'bull-call :label "bull call spread" :legs '((call 1) (call -1)) :shape 'vertical :strategy "VERTICAL"
      :text "Buy the call with the lower strike, sell the one with the higher. A bet on a rise, for a debit, which is the most it can lose; the most it can make is the strikes' difference less the debit, with the stock at the higher strike or more.")
    (make-spread-kind
      :name 'bear-call :label "bear call spread" :legs '((call -1) (call 1)) :shape 'vertical :strategy "VERTICAL"
      :text "Sell the call with the lower strike, buy the one with the higher. A bet that the stock won't rise, for a credit, which is the most it can make, with the stock at the lower strike or less; the most it can lose is the strikes' difference less the credit.")
    (make-spread-kind
      :name 'bull-put :label "bull put spread" :legs '((put 1) (put -1)) :shape 'vertical :strategy "VERTICAL"
      :text "Buy the put with the lower strike, sell the one with the higher. A bet that the stock won't fall, for a credit, which is the most it can make, with the stock at the higher strike or more; the most it can lose is the strikes' difference less the credit.")
    (make-spread-kind
      :name 'bear-put :label "bear put spread" :legs '((put -1) (put 1)) :shape 'vertical :strategy "VERTICAL"
      :text "Sell the put with the lower strike, buy the one with the higher. A bet on a fall, for a debit, which is the most it can lose; the most it can make is the strikes' difference less the debit, with the stock at the lower strike or less.")
    (make-spread-kind
      :name 'call-butterfly :label "call butterfly" :legs '((call 1) (call -2) (call 1)) :shape 'butterfly :strategy "BUTTERFLY"
      :text "Buy a call at a low strike, sell two at the middle strike, and buy one at a high strike as far above the middle as the low one is below. A bet that the stock ends near the middle strike, for a small debit, which is the most it can lose; the most it can make is the distance between strikes less the debit, with the stock at the middle strike.")
    (make-spread-kind
      :name 'put-butterfly :label "put butterfly" :legs '((put 1) (put -2) (put 1)) :shape 'butterfly :strategy "BUTTERFLY"
      :text "The same as the call butterfly, made of puts: the same shape of profit, and nearly the same cost.")
    (make-spread-kind
      :name 'iron-condor :label "iron condor" :legs '((put 1) (put -1) (call -1) (call 1)) :shape 'condor :strategy "IRON_CONDOR"
      :text "Sell a put and a call, and buy a put below and a call above them to limit the risk, the two wings the same width. A bet that the stock ends between the two sold strikes, for a credit, which is the most it can make; the most it can lose is a wing's width less the credit.")
    (make-spread-kind
      :name 'iron-butterfly :label "iron butterfly" :legs '((put 1) (put -1) (call -1) (call 1)) :shape 'iron-butterfly :strategy "IRON_CONDOR"
      :text "An iron condor whose sold put and call have the same strike. A bet that the stock ends near that strike, for a bigger credit than the condor's, which is the most it can make, at that strike exactly; the most it can lose is a wing's width less the credit.")
    (make-spread-kind
      :name 'long-straddle :label "long straddle" :legs '((call 1) (put 1)) :shape 'straddle :strategy "STRADDLE"
      :text "Buy a call and a put with the same strike. A bet on a big move either way, for a debit, which is the most it can lose, with the stock at the strike; there is no limit to what it can make on a rise.")
    (make-spread-kind
      :name 'long-strangle :label "long strangle" :legs '((put 1) (call 1)) :shape 'strangle :strategy "STRANGLE"
      :text "Buy a put and a call with different strikes, the put's the lower. A bet on a big move either way, for a smaller debit than the straddle's, which is the most it can lose, with the stock between the strikes; there is no limit to what it can make on a rise.")))

(define (option-spreads--kind name)
  "The spread-kind with this name, or an error that lists the names."
  (let ((found (filter (lambda (kind) (eq? (spread-kind-name kind) name)) spread-kinds)))
    (if (null? found)
        (error (format "option-spreads: {} isn't a kind of spread; the kinds are {}" name
                       (string-join (map (lambda (kind) (symbol->string (spread-kind-name kind))) spread-kinds) ", ")))
        (car found))))

(define (option-spreads--leg-type leg) (first leg))
(define (option-spreads--leg-quantity leg) (second leg))

(define (option-spreads--words-for-legs legs)
  "The legs in a few words: buy a call, sell a call."
  (string-join (map (lambda (leg) (format "{} {}{}"
                                          (if (> (option-spreads--leg-quantity leg) 0) "buy" "sell")
                                          (if (= (abs (option-spreads--leg-quantity leg)) 1)
                                              ""
                                              (format "{} " (abs (option-spreads--leg-quantity leg))))
                                          (option-spreads--leg-type leg)))
                    legs)
               ", "))

(define (option-spread-kinds)
  "The kinds of spread, as a table with a row for each: its name (the symbol to give option-spreads), a
label, its legs from the lowest strike up, the name Schwab gives it, and what it is for."
  (make-table "kind" (list->vector (map (lambda (kind) (symbol->string (spread-kind-name kind))) spread-kinds))
              "label" (list->vector (map spread-kind-label spread-kinds))
              "legs" (list->vector (map (lambda (kind) (option-spreads--words-for-legs (spread-kind-legs kind))) spread-kinds))
              "schwab" (list->vector (map spread-kind-strategy spread-kinds))
              "about" (list->vector (map spread-kind-text spread-kinds))))

; ---------------------------------------------------------------------------
; 2. The options that count
; ---------------------------------------------------------------------------

(define (option-spreads--market-open?)
  "Whether the stock market is open now: from 9:30 to 4:00, New York time, on
a trading day. (This takes the computer's clock to be on New York time.)"
  (let* ((now (current-time))
         (minutes (+ (* 60 (list-ref now 3)) (list-ref now 4))))      ; since midnight
    (and (trading-day? (today)) (>= minutes (+ (* 9 60) 30)) (< minutes (* 16 60)))))

(define (option-spreads--day expiration)
  "A date, from a date or YYYY-MM-DD text."
  (if (string? expiration) (string->date expiration) expiration))

(define (option-spreads--no-options chain type day)
  "The error for a chain with no options of this type (Call or Put) expiring on day."
  (let ((days (vector-unique (table-column (table-filter chain (= (table-column chain "type") type))
                                           "expiration-date")))
        (word (string-downcase type)))
    (error (format "option-spreads: the chain has no {}s expiring on {}; its {}s expire on {}"
                   word (date->string day) word
                   (if (= (vector-length days) 0)
                       "no day at all"
                       (string-join (map date->string (vector->list days)) ", "))))))

(define (option-spreads--quoted chain type day prices min-open-interest min-volume)
  "The chain's options of this type (Call or Put) that expire on day and count: they have a bid and an ask,
open interest, and volume. A table in order of strike, with, besides the chain's columns, buy and sell (the
prices to buy and to sell at) and key (the strike in cents, a whole number, to find a strike by)."
  (let* ((options (table-filter chain (vector-and (= (table-column chain "type") type)
                                                  (= (table-column chain "expiration-date") day)))))
    (when (= (table-row-count options) 0)
      (option-spreads--no-options chain type day))
    (let ((quoted (table-sort
                    (table-filter options (vector-and (> (table-column options "bid") 0)
                                                      (> (table-column options "ask") 0)
                                                      (>= (vector-fill-nan (table-column options "open-interest") 0)
                                                          min-open-interest)
                                                      (>= (vector-fill-nan (table-column options "volume") 0)
                                                          min-volume)))
                    "strike")))
      (table-add-column
        (table-add-column
          (table-add-column quoted "buy" (table-column quoted (if (eq? prices 'mid) "mid" "ask")))
          "sell" (table-column quoted (if (eq? prices 'mid) "mid" "bid")))
        "key" (vector-round (* (table-column quoted "strike") 100))))))

; ---------------------------------------------------------------------------
; 3. The strikes of the spreads
; ---------------------------------------------------------------------------
; Every strike is a whole number of cents, so that strikes can be told to be
; equal, or to be a wing's width apart, exactly. Each function here gives a
; list of vectors, one for each leg of the kind: the strikes of that leg in
; every spread that might be made. (Whether there is an option at each strike
; is found out in section 4.) The vector-grid of two numbers gives every pair of
; positions, and a mask of them keeps the pairs that make a spread.

(define (option-spreads--within width max-width)
  "A mask of the widths (vectors, in cents) that are no more than max-width dollars, or all, if there's none."
  (if (null? max-width)
      (>= width 0)
      (<= width (round (* 100 max-width)))))

(define (option-spreads--join pieces like)
  "The vectors in the list joined end to end -- or an empty vector, as long as like is 0, if the list is empty."
  (apply vector-append (cons (vector-take like 0) pieces)))

(define (option-spreads--pairs-up keys)
  "Every pair of the strikes in the vector, the lower first: two vectors."
  (let* ((grid (vector-grid (vector-length keys) (vector-length keys)))
         (keep (< (first grid) (second grid))))
    (list (vector-gather keys (vector-select (first grid) keep))
          (vector-gather keys (vector-select (second grid) keep)))))

(define (option-spreads--vertical-strikes keys max-width)
  "A vertical spread has two strikes: each pair."
  (let* ((pairs (option-spreads--pairs-up keys))
         (keep (option-spreads--within (- (second pairs) (first pairs)) max-width)))
    (list (vector-select (first pairs) keep) (vector-select (second pairs) keep))))

(define (option-spreads--butterfly-strikes keys max-width)
  "A butterfly has three strikes, equally far apart: each pair is the middle and the highest, and the lowest
is as far below the middle as the highest is above."
  (let* ((pairs (option-spreads--pairs-up keys))
         (middle (first pairs))
         (high (second pairs))
         (keep (option-spreads--within (- high middle) max-width)))
    (list (vector-select (- (* 2 middle) high) keep) (vector-select middle keep) (vector-select high keep))))

(define (option-spreads--condor-strikes put-keys call-keys max-width touching?)
  "A condor has four strikes: the puts' lower and higher, the calls' lower and higher, with wings of the
same width. The two in the middle are each pair of a put's and a call's strike with the put's the lower
(or, for an iron butterfly, touching?, the same); a wing as wide as the strikes of the puts are apart, for each
width that comes up, makes the outer strikes -- which may or may not be there."
  (let* ((grid (vector-grid (vector-length put-keys) (vector-length call-keys)))
         (put-middle (vector-gather put-keys (first grid)))
         (call-middle (vector-gather call-keys (second grid)))
         (keep (if touching? (= put-middle call-middle) (< put-middle call-middle)))
         (put-middle (vector-select put-middle keep))
         (call-middle (vector-select call-middle keep))
         (gaps (option-spreads--pairs-up put-keys))
         (widths (vector-unique (let ((all (- (second gaps) (first gaps))))
                                  (vector-select all (option-spreads--within all max-width)))))
         (found (list '() '() '() '())))
    (dolist (width (vector->list widths))
      (let* ((put-low (- put-middle width))
             (call-high (+ call-middle width))
             (there (vector-and (>= (vector-positions put-keys put-low) 0)
                                (>= (vector-positions call-keys call-high) 0))))
        (set! found (map (lambda (pieces strikes) (cons (vector-select strikes there) pieces))
                         found (list put-low put-middle call-middle call-high)))))
    (map (lambda (pieces) (option-spreads--join (reverse pieces) put-keys)) found)))

(define (option-spreads--straddle-strikes put-keys call-keys)
  "A straddle has one strike, a call's and a put's: each strike the puts and calls both have."
  (let ((both (vector-select call-keys (>= (vector-positions put-keys call-keys) 0))))
    (list both both)))

(define (option-spreads--strangle-strikes put-keys call-keys max-width)
  "A strangle has a put's strike, and a higher call's: each such pair."
  (let* ((grid (vector-grid (vector-length put-keys) (vector-length call-keys)))
         (put-strike (vector-gather put-keys (first grid)))
         (call-strike (vector-gather call-keys (second grid)))
         (keep (vector-and (< put-strike call-strike) (option-spreads--within (- call-strike put-strike) max-width))))
    (list (vector-select put-strike keep) (vector-select call-strike keep))))

(define (option-spreads--strikes kind put-keys call-keys max-width)
  "The strikes of every spread of the kind that might be made, as a list of vectors, one for each leg."
  (let ((own-keys (if (eq? (option-spreads--leg-type (first (spread-kind-legs kind))) 'call) call-keys put-keys)))
    (case (spread-kind-shape kind)
      ((vertical) (option-spreads--vertical-strikes own-keys max-width))
      ((butterfly) (option-spreads--butterfly-strikes own-keys max-width))
      ((condor) (option-spreads--condor-strikes put-keys call-keys max-width #f))
      ((iron-butterfly) (option-spreads--condor-strikes put-keys call-keys max-width #t))
      ((straddle) (option-spreads--straddle-strikes put-keys call-keys))
      ((strangle) (option-spreads--strangle-strikes put-keys call-keys max-width))
      (else (error "option-spreads: not a shape of spread:" (spread-kind-shape kind))))))

; ---------------------------------------------------------------------------
; 4. What each spread is worth, risks, and ratio
; ---------------------------------------------------------------------------

(define (option-spreads--worth legs strikes price)
  "What the legs are worth, together, on the expiration day with the stock at price (a number, or a vector with
a price for each spread). strikes is a list of vectors, the strikes of each leg."
  (let ((total 0))
    (loop for leg in legs
          for strike in strikes
          do (set! total (+ total (* (option-spreads--leg-quantity leg)
                                     (if (eq? (option-spreads--leg-type leg) 'call)
                                         (vector-clip (- price strike) 0 1e12)
                                         (vector-clip (- strike price) 0 1e12))))))
    total))

(define (option-spreads--lowest vectors)
  "The least of each spread's numbers, over the list of vectors."
  (let ((least (car vectors)))
    (dolist (v (cdr vectors))
      (set! least (vector-where (< v least) v least)))
    least))

(define (option-spreads--highest vectors)
  (let ((most (car vectors)))
    (dolist (v (cdr vectors))
      (set! most (vector-where (> v most) v most)))
    most))

(define (option-spreads--earlier a b)
  "The less of two vectors, where one is missing the other."
  (vector-where (vector-nan? a) b (vector-where (vector-nan? b) a (vector-where (< a b) a b))))

(define (option-spreads--later a b)
  (vector-where (vector-nan? a) b (vector-where (vector-nan? b) a (vector-where (> a b) a b))))

(define (option-spreads--breakeven-roots strikes profits slope)
  "The prices where each spread breaks even, as a list of vectors, nan where it doesn't. The profit is a line
between one strike and the next -- and from 0 to the lowest, and from the highest up, at the slope of the calls
bought less sold -- so it crosses 0 between two points that have profits of opposite sign, at a price that is
a proportion of the way along. profits is a list of vectors: the profit at 0, then at each strike."
  (let ((points (cons 0 strikes))
        (roots '()))
    (loop for place from 0 below (length strikes)
          do (let* ((from (list-ref points place))
                    (to (list-ref points (+ place 1)))
                    (profit-from (list-ref profits place))
                    (profit-to (list-ref profits (+ place 1)))
                    (crosses (vector-or (vector-and (< profit-from 0) (>= profit-to 0))
                                        (vector-and (> profit-from 0) (<= profit-to 0)))))
               (push (vector-where crosses
                                   (+ from (* (- to from) (vector-div (- profit-from) (- profit-to profit-from))))
                                   nan)
                     roots)))
    (when (> slope 0)                       ; above the highest strike, the profit goes on rising
      (let ((top (option-spreads--last strikes))
            (profit-top (option-spreads--last profits)))
        (push (vector-where (< profit-top 0) (- top (vector-div profit-top slope)) nan) roots)))
    roots))

(define (option-spreads--last items)
  (car (last items)))

(define (option-spreads--analysis kind strikes cost expected-price)
  "What a set of spreads of a kind -- their strikes, a list of vectors, and their costs -- is worth at
expected-price and in the worst and best cases, as a list of vectors:
worth, profit, max-loss, max-profit (nan: no limit), breakeven-1, breakeven-2 (nan: none)."
  (let* ((legs (spread-kind-legs kind))
         (slope (apply + (map option-spreads--leg-quantity       ; the calls bought less sold: the profit's slope at the top
                              (filter (lambda (leg) (eq? (option-spreads--leg-type leg) 'call)) legs))))
         (check (when (< slope 0)
                  (error "option-spreads: this kind of spread can lose without limit:" (spread-kind-name kind))))
         (worth (option-spreads--worth legs strikes expected-price))
         (profits (cons (- (option-spreads--worth legs strikes 0) cost)
                        (map (lambda (strike) (- (option-spreads--worth legs strikes strike) cost)) strikes)))
         (roots (option-spreads--breakeven-roots strikes profits slope))
         (first-root (option-spreads--fold option-spreads--earlier roots))
         (last-root (option-spreads--fold option-spreads--later roots)))
    (list worth
          (- worth cost)
          (- (option-spreads--lowest profits))
          (if (> slope 0) (make-vector (vector-length cost) nan) (option-spreads--highest profits))
          first-root
          (vector-where (vector= first-root last-root) nan last-root))))

(define (option-spreads--fold f vectors)
  (let ((result (car vectors)))
    (dolist (v (cdr vectors))
      (set! result (f result v)))
    result))

; ---------------------------------------------------------------------------
; 5. Finding the spreads
; ---------------------------------------------------------------------------

(define (option-spreads--column-of-leg quoted positions column)
  "The values of a column of the options at these positions in the table."
  (vector-gather (table-column quoted column) positions))

(define (option-spreads--root-of symbol)
  "The root of an option's symbol: the stock's, or the name of a kind of its options (SPXW for SPX's weeklies), without
the padding spaces. (An option's symbol is the root padded to 6 characters, the expiration as YYMMDD, C or P, and the
strike times 1000 in 8 digits.)"
  (string-trim (regex-replace "\\d{6}[CP]\\d{8}$" symbol "")))

(define (option-spreads--with-root table)
  (if (= (table-row-count table) 0)
      (table-add-column table "root" (table-column table "symbol"))
      (table-add-column table "root" (vector-map option-spreads--root-of (table-column table "symbol")))))

(define (option-spreads--of-root kind calls puts expected-price min-risk max-width)
  "The spreads of the kind that can be made of these calls and puts, which are of one root, as the columns of a
table, not in order: see option-spreads-for-chain."
  (let* ((legs (spread-kind-legs kind))
         (empty-keys (vector-take (vector-range 1) 0))
         (call-keys (if (null? calls) empty-keys (table-column calls "key")))
         (put-keys (if (null? puts) empty-keys (table-column puts "key")))
         (leg-keys (option-spreads--strikes kind put-keys call-keys max-width))
         (tables (map (lambda (leg) (if (eq? (option-spreads--leg-type leg) 'call) calls puts)) legs))
         (found (map (lambda (table keys) (vector-positions (table-column table "key") keys)) tables leg-keys))
         (there (apply vector-and (map (lambda (positions) (>= positions 0)) found)))
         (positions (map (lambda (positions) (vector-select positions there)) found))
         (symbols (map (lambda (table at) (option-spreads--column-of-leg table at "symbol")) tables positions))
         (strikes (map (lambda (table at) (option-spreads--column-of-leg table at "strike")) tables positions))
         (leg-prices (map (lambda (leg table at)
                            (option-spreads--column-of-leg table at (if (> (option-spreads--leg-quantity leg) 0) "buy" "sell")))
                          legs tables positions))
         (cost (apply + (map (lambda (leg price) (* (option-spreads--leg-quantity leg) price)) legs leg-prices))))
    (destructuring-bind (worth profit max-loss max-profit breakeven-1 breakeven-2)
        (option-spreads--analysis kind strikes cost expected-price)
      (let* ((keep (vector-and (> max-loss option-spreads--least-risk) (>= max-loss min-risk)))
             (pick (lambda (v) (vector-select v keep)))
             (chosen-loss (pick max-loss)))
        (append
          (loop for symbol in symbols for place from 1 collect (cons (format "symbol-{}" place) (pick symbol)))
          (loop for strike in strikes for place from 1 collect (cons (format "strike-{}" place) (pick strike)))
          (loop for price in leg-prices for place from 1 collect (cons (format "price-{}" place) (pick price)))
          (list (cons "cost" (pick cost))
                (cons "max-loss" chosen-loss)
                (cons "max-profit" (pick max-profit))
                (cons "worth" (pick worth))
                (cons "profit" (pick profit))
                (cons "ratio" (/ (pick profit) chosen-loss))
                (cons "breakeven-1" (pick breakeven-1))
                (cons "breakeven-2" (pick breakeven-2))))))))

(define (option-spreads-for-chain chain kind-name expiration expected-price
                                  &key (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-risk 0)
                                  (max-width '()))
  "Every spread of the kind (bull-call, bear-call, bull-put, bear-put, call-butterfly, put-butterfly, iron-condor,
iron-butterfly, long-straddle, or long-strangle: see option-spread-kinds) that can be made of the chain's options
expiring on expiration (a date, or YYYY-MM-DD text), as a spread-search (see the top of this file): its table of
spreads has a row for each, the best first -- the one with the highest profit, if the stock is at expected-price
on expiration day, as a share of the most that can be lost. chain is a table as tastytrade-option-chain or
schwab-option-chain makes. All the options of a spread are of one root (the stock's own options, or its weeklies,
or its minis: some stocks and indexes have several of the same strike and expiration, which are not the same
contract). The columns of the table, for a spread of n options (its legs, lowest strike first):
  symbol-1 ... symbol-n    the options (the kind's legs say which are bought and which sold)
  strike-1 ... strike-n    their strikes
  price-1 ... price-n      the price of each for a share: the ask for one bought, the bid for one sold
  cost                     what the spread costs in all, for a share; negative, if it pays you (a credit)
  max-loss                 the most that can be lost, for a share
  max-profit               the most that can be made; missing if there's no limit
  worth                    what the spread is worth at expected-price on the day
  profit                   worth less cost
  ratio                    profit as a share of max-loss: 1.5 is 150%
  breakeven-1, breakeven-2 the stock's prices at which the spread breaks even: the lower, and the higher if there
                           are two; missing, if there is none (a spread that cannot make a profit has none)
:prices is bid-ask (pay the ask, get the bid) or mid; the others limit which options count and which spreads are
kept: see the top of this file."
  (unless (or (eq? prices 'bid-ask) (eq? prices 'mid))
    (error "option-spreads: :prices is 'bid-ask or 'mid, not" prices))
  (let* ((kind (option-spreads--kind kind-name))
         (legs (spread-kind-legs kind))
         (day (option-spreads--day expiration))
         (needs (lambda (type) (some (lambda (leg) (eq? (option-spreads--leg-type leg) type)) legs)))
         (calls (if (needs 'call)
                    (option-spreads--with-root (option-spreads--quoted chain "Call" day prices min-open-interest min-volume))
                    '()))
         (puts (if (needs 'put)
                   (option-spreads--with-root (option-spreads--quoted chain "Put" day prices min-open-interest min-volume))
                   '()))
         (roots-found (vector-unique (vector-append (if (null? calls) (vector "") (table-column calls "root"))
                                                    (if (null? puts) (vector "") (table-column puts "root")))))
         ; (with no options at all there is one search, of none, which finds the table with no rows)
         (roots (if (= (vector-length roots-found) 0) (vector "") roots-found))
         (of-root (lambda (table root)
                    (if (null? table) table (table-filter table (= (table-column table "root") root)))))
         (tables (map (lambda (root)
                        (option-spreads--of-root kind (of-root calls root) (of-root puts root)
                                                 expected-price min-risk max-width))
                      (vector->list roots))))
    (make-spread-search
      :kind kind-name
      :stock (vector-ref (table-column chain "underlying") 0)
      :stock-price (vector-ref (table-column chain "underlying-price") 0)
      :expiration day
      :expected-price expected-price
      :prices prices
      :spreads (table-sort (apply table-append tables) "ratio" #t))))

(define (option-spreads creds symbol kind-name expiration expected-price
                        &key (prices 'bid-ask) (min-open-interest 1) (min-volume 1) (min-risk 0) (max-width '()))
  "Get the stock's options expiring on expiration (a date, or YYYY-MM-DD text) from Schwab -- the calls, or the
puts, or both, as the kind of spread needs -- the bids and asks are live while the market is open, and say so if it
is closed -- and rank the spreads of the kind: see option-spreads-for-chain, which takes the options you
have, and gives the result."
  (let* ((kind (option-spreads--kind kind-name))
         (types (map option-spreads--leg-type (spread-kind-legs kind)))
         (contracts (cond ((and (member 'call types) (member 'put types)) "ALL")
                          ((member 'call types) "CALL")
                          (else "PUT"))))
    (unless (option-spreads--market-open?)
      (display "The market is closed now: the bids and asks are from its last close.\n\n"))
    (option-spreads-for-chain (schwab-option-chain creds symbol :expiration (option-spreads--day expiration) :type contracts)
                              kind-name expiration expected-price
                              :prices prices :min-open-interest min-open-interest :min-volume min-volume
                              :min-risk min-risk :max-width max-width)))

; ---------------------------------------------------------------------------
; 6. The order
; ---------------------------------------------------------------------------

(define (option-spread-order search &key (row 0) (contracts 1) (price '()) (strategy '()))
  "An order for one of the spreads of a spread-search -- the best, unless :row (0 is the best, 1 the next, ...)
says -- as a hash table, in Schwab's form: buy the options the kind buys and sell those it sells, :contracts times
each (a butterfly's middle option twice that), as one order, with a limit on the net debit -- or, for a spread that
pays you, the net credit -- of :price a share (the spread's cost, or credit, unless it is given). It sends nothing:
schwab-preview-order says what Schwab makes of it, and schwab-place-order :confirm #t places it. The order opens new
positions, and lasts the day. :strategy is the name Schwab gives the kind of order (VERTICAL, BUTTERFLY,
IRON_CONDOR, STRADDLE, or STRANGLE: the kind's, unless you give another, if Schwab doesn't like it).

At the cost, if the prices are bid-ask, the order is likely to fill at once: it pays what is asked for the options
bought and takes what is bid for those sold. A better :price (lower, for a debit; higher, for a credit) may fill at
a better price, or not fill. Selling options needs your broker's approval, and some of your money held."
  (let* ((kind (option-spreads--kind (spread-search-kind search)))
         (spreads (spread-search-spreads search))
         (legs (spread-kind-legs kind)))
    (when (>= row (table-row-count spreads))
      (error (format "option-spread-order: there is no row {}: the search found {} spreads" row
                     (table-row-count spreads))))
    (unless (and (integer? contracts) (>= contracts 1))
      (error "option-spread-order: :contracts is a whole number of spreads, 1 or more"))
    (let* ((cost (vector-ref (table-column spreads "cost") row))
           (credit? (< cost 0)))
      (schwab-multi-leg-order
        (if (null? strategy) (spread-kind-strategy kind) strategy)
        (loop for leg in legs
              for place from 1
              collect (list (if (> (option-spreads--leg-quantity leg) 0) "BUY_TO_OPEN" "SELL_TO_OPEN")
                            (vector-ref (table-column spreads (format "symbol-{}" place)) row)
                            (* contracts (abs (option-spreads--leg-quantity leg)))))
        (if (null? price) (abs cost) price)
        :credit credit?))))

(define (option-spreads--plural noun count)
  (cond ((= count 1) noun)
        ((string-ends-with? noun "y") (string-append (substring noun 0 (- (string-length noun) 1)) "ies"))
        (else (string-append noun "s"))))

(define (show-spread-order order)
  "Say in words what a spread order -- as option-spread-order, call-spread-order, or schwab-multi-leg-order
or schwab-spread-order makes it -- would do, to read before previewing or placing it: what it buys and sells,
and the most it would pay, or the least it would get. Nothing is sent."
  (let* ((legs (hash-table-ref order "orderLegCollection"))
         (contracts (apply min (map (lambda (leg) (hash-table-ref leg "quantity")) legs)))
         (price (hash-table-ref order "price"))
         (credit? (equal? (hash-table-ref order "orderType") "NET_CREDIT"))
         (noun (let ((strategy (hash-table-ref order "complexOrderStrategyType" "")))
                 (cond ((equal? strategy "VERTICAL") "spread")
                       ((equal? strategy "BUTTERFLY") "butterfly")
                       ((equal? strategy "IRON_CONDOR") "iron condor")
                       ((equal? strategy "STRADDLE") "straddle")
                       ((equal? strategy "STRANGLE") "strangle")
                       (else "spread")))))
    (display (format "This order has not been sent. If it were: a {} order to open {} {}, with a limit on the net {} of {:,.2f} a share ({:,.2f} for each, {:,.2f} in all, at {}):\n"
                     (string-downcase (hash-table-ref order "duration")) contracts (option-spreads--plural noun contracts)
                     (if credit? "credit" "debit") price (* option-contract-size price) (* option-contract-size price contracts)
                     (if credit? "least" "most")))
    (dolist (leg legs)
      (display (format "  {:<13} {} x {}\n" (hash-table-ref leg "instruction") (hash-table-ref leg "quantity")
                       (hash-table-ref (hash-table-ref leg "instrument") "symbol"))))))

; ---------------------------------------------------------------------------
; 7. Showing them
; ---------------------------------------------------------------------------

(define (option-spreads--leg-in-words search legs row place)
  "One leg of the spread in the row: buy 1 100.00 call at 6.20."
  (let* ((spreads (spread-search-spreads search))
         (leg (list-ref legs (- place 1)))
         (quantity (abs (option-spreads--leg-quantity leg))))
    (format "{} {} {:,.2f} {}{} at {:,.2f}"
            (if (> (option-spreads--leg-quantity leg) 0) "buy" "sell") quantity
            (vector-ref (table-column spreads (format "strike-{}" place)) row)
            (option-spreads--leg-type leg) (if (= quantity 1) "" "s")
            (vector-ref (table-column spreads (format "price-{}" place)) row))))

(define (option-spreads--best-in-words search)
  "A paragraph about the best spread: what to buy and sell, what it costs, and what it makes."
  (let* ((kind (option-spreads--kind (spread-search-kind search)))
         (legs (spread-kind-legs kind))
         (spreads (spread-search-spreads search))
         (stock (spread-search-stock search))
         (size option-contract-size)
         (cost (vector-ref (table-column spreads "cost") 0))
         (loss (vector-ref (table-column spreads "max-loss") 0))
         (gain (vector-ref (table-column spreads "max-profit") 0))
         (profit (vector-ref (table-column spreads "profit") 0))
         (low (vector-ref (table-column spreads "breakeven-1") 0))
         (high (vector-ref (table-column spreads "breakeven-2") 0)))
    (string-append
      (format "The best: {}.\n"
              (string-join (loop for place from 1 to (length legs)
                                 collect (option-spreads--leg-in-words search legs 0 place))
                           ", "))
      (if (< cost 0)
          (format "  It pays you {:,.2f} a share: {:,.2f} for one contract of each option. The most you can lose is {:,.2f} a share ({:,.2f}).\n"
                  (- cost) (* size (- cost)) loss (* size loss))
          (format "  It costs {:,.2f} a share: {:,.2f} for one contract of each option. The most you can lose is {:,.2f} a share ({:,.2f}).\n"
                  cost (* size cost) loss (* size loss)))
      (format "  With {} at {:,.2f} on {}, it is worth {:,.2f} a share, a profit of {:,.2f} ({:,.2f}): {:.0%} of the most you can lose.\n"
              stock (spread-search-expected-price search) (date->string (spread-search-expiration search))
              (vector-ref (table-column spreads "worth") 0) profit (* size profit)
              (vector-ref (table-column spreads "ratio") 0))
      (if (= gain gain)
          (format "  The most it can make is {:,.2f} a share ({:,.2f}). " gain (* size gain))
          "  There is no limit to what it can make. ")
      (cond ((and (= low low) (= high high))
             (format "It breaks even with {} at {:,.2f} and at {:,.2f}." stock low high))
            ((= low low) (format "It breaks even with {} at {:,.2f}." stock low))
            (else "It makes a profit with the stock at any price.")))))

(define (show-option-spreads search &key (count 10))
  "Show what option-spreads found: the best spread in words, and a table of it and the next count best."
  (let* ((kind (option-spreads--kind (spread-search-kind search)))
         (legs (spread-kind-legs kind))
         (spreads (spread-search-spreads search))
         (rows (table-row-count spreads)))
    (display (format "{} is at {:,.2f}. {} expiring {}, if it is at {:,.2f} then; bought and sold at the {} prices. {} {}.\n\n"
                     (spread-search-stock search) (spread-search-stock-price search)
                     (option-spreads--capitalized (option-spreads--plural (spread-kind-label kind) 2))
                     (date->string (spread-search-expiration search)) (spread-search-expected-price search)
                     (if (eq? (spread-search-prices search) 'mid) "middle" "ask and bid") rows
                     (if (= rows 1) "spread" "spreads")))
    (cond
      ((= rows 0)
       (display "No such spread can be made: the options need a bid and an ask, open interest, volume today, and a most that can be lost above 0.\n(Volume counts today's trades, and is 0 before the market opens: give :min-volume 0 then.)\n"))
      (else
        (display (option-spreads--best-in-words search))
        (display (format "\n\nThe best {}, by the ratio of profit to the most that can be lost (prices are for a share):\n"
                         (min count rows)))
        (display-table (table-head spreads count)
                       (append
                         (loop for place from 1 to (length legs) collect (list (format "symbol-{}" place)))
                         (loop for place from 1 to (length legs) collect (list (format "strike-{}" place) ",.2f"))
                         (loop for place from 1 to (length legs) collect (list (format "price-{}" place) ",.2f"))
                         '(("cost" ",.2f") ("max-loss" ",.2f") ("max-profit" ",.2f") ("worth" ",.2f") ("profit" ",.2f")
                           ("ratio" ".0%") ("breakeven-1" ",.2f") ("breakeven-2" ",.2f"))))
        (display "\nTo trade the best one: option-spread-order sends nothing, the preview asks Schwab what it makes of\nthe order and places nothing, and only the last line places it:\n")
        (display "  (define order (option-spread-order search :contracts 1))\n")
        (display "  (show-spread-order order)                               ; the order, in words\n")
        (display "  (schwab-preview-order creds \"your account\" order)     ; what Schwab makes of it; nothing is placed\n")
        (display "  (schwab-place-order creds \"your account\" order :confirm #t)     ; places it, for real\n")))))

(define (option-spreads--capitalized text)
  (string-append (string-upcase (substring text 0 1)) (substring text 1)))
