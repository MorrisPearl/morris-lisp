; option_chain_example.lsp
;
; Fetching an option chain from tastytrade, picking out the options that
; meet some criteria, and showing them.
;
; tastytrade-option-chain returns a TABLE: one column per field (symbol,
; type, strike, expiration-date, days-to-expiration, delivery-month,
; underlying, underlying-price, bid, ask, mid, last-price,
; implied-volatility, delta, volume, open-interest). So the
; chain can be filtered a whole column at a time (part 2), or looked at one
; option at a time, as rows (part 3). A value tastytrade didn't report is
; missing -- NaN in a column of numbers -- and a comparison with a missing
; value is false, so an option with no open interest, say, never passes a
; test on open interest.
;
; It needs your tastytrade credentials file: creds is set to its path in
; init.lsp. Run it from the examples directory:
;   python3 ../lisp_interpreter.py option_chain_example.lsp
; or in a notebook:
;   (load "option_chain_example.lsp")

; --- 1. Fetch the chain, and show it ---------------------------------------
; SPY options expiring in the next 2 months, the 10 strikes nearest the
; money at each expiration, with their current bids and asks.
(define chain (tastytrade-option-chain creds "SPY" 2 10))

; How to lay out each column's numbers: the same specs format uses.
(define chain-formats
  '(("strike" ",.2f") ("bid" ",.2f") ("ask" ",.2f") ("mid" ",.2f") ("last-price" ",.2f")
    ("implied-volatility" ".1%") ("volume" ",.0f") ("open-interest" ",.0f")))

(display (format "SPY: {} options\n" (table-row-count chain)))
(display-table (table-select chain '("symbol" "type" "strike" "expiration-date"
                                     "bid" "ask" "implied-volatility" "open-interest"))
               chain-formats)
(newline)

; --- 2. Filter whole columns at once ----------------------------------------
; Calls expiring in 20 to 60 days, with at least 100 contracts of open
; interest. Each comparison gives a mask (1 where it's true); vector-and
; keeps the rows where every mask is 1.
(define (column name) (table-column chain name))

(define liquid-calls
  (table-filter chain
                (vector-and (= (column "type") "Call")
                            (<= 20 (column "days-to-expiration") 60)
                            (>= (column "open-interest") 100))))

; A new column, computed from two others: what each day of the option's life
; costs, at the middle of the bid and ask, and the table sorted by it.
(define liquid-calls-per-day
  (table-add-column liquid-calls "price-per-day"
                    (/ (table-column liquid-calls "mid")
                       (table-column liquid-calls "days-to-expiration"))))

(display "Calls, 20 to 60 days, open interest of at least 100, cheapest per day first:\n")
(display-table (table-sort (table-select liquid-calls-per-day
                                         '("symbol" "strike" "days-to-expiration"
                                           "mid" "price-per-day" "open-interest"))
                           "price-per-day")
               (cons '("price-per-day" ".4f") chain-formats))
(newline)

; --- 3. Look at one option at a time ----------------------------------------
; table-rows gives each option as a row; with-struct makes its columns into
; variables, so a test reads like a sentence. filter keeps the rows it's
; true for, and display-table shows a list of rows as a table.
(define (expensive-put? option)
  (with-struct option
    (and (string=? type "Put")
         (> implied-volatility 0.20)
         (> mid 1.0))))

(define expensive-puts (filter expensive-put? (table-rows chain)))
(display (format "Puts with implied volatility over 20% and a price over $1: {}\n"
                 (length expensive-puts)))
(display-table expensive-puts chain-formats)
(newline)

; One line per option, written out with format:
(dolist (option expensive-puts)
  (with-struct option
    (display (format "  {} expires {}: {:.2f} bid, {:.2f} ask, at {:.1%} volatility\n"
                     symbol expiration-date bid ask implied-volatility))))
(newline)

; --- 4. Summarize by expiration ---------------------------------------------
; One row per expiration date: how many options, their average implied
; volatility, and their total open interest.
(display "By expiration:\n")
(display-table (table-group-by chain "expiration-date"
                               '(("options" count)
                                 ("average-iv" mean "implied-volatility")
                                 ("open-interest" sum "open-interest")))
               '(("average-iv" ".1%") ("open-interest" ",.0f")))
