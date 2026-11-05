; industry_returns.lsp
; ====================
; Do a stock's industry tell you how its price moved? Three functions to find out, from the table ticker_industry (ticker, industry) in the database:
;
;   (stock-returns-update creds "financial_data.db")    each stock's return over the last year, from Schwab, kept in the table stock_returns
;   (industry-returns "financial_data.db")              each industry's return, weighted by market capitalization
;   (industry-variation "financial_data.db")            how much stocks differ within an industry, against how much industries differ from each other
;
; A stock's return over a year is what its price gained, plus the dividend, as a fraction of the price it started at:
;
;     return = (end price - start price + dividend) / start price
;
; The prices are the closing prices of the first and last days Schwab has in the year. The dividend is Schwab's dividendAmount, which is the dividend the
; stock pays in a year at its current rate. It is not a list of what was paid in the last twelve months (Schwab's price history does not say that), so for a
; company that has changed its dividend, or began or stopped paying one, it is an approximation. Schwab's marketCap, which the industries are weighted by,
; is today's.
;
; stock_returns has a row for each stock in ticker_industry: ticker, year_end (the day the year was asked to end on), start_date and end_date (the first and
; last days Schwab had prices for), start_price, end_price, dividend, market_cap, return, and note. A stock Schwab has no prices for (a delisted one, or a
; ticker spelled differently) has a note saying so and no return. The function saves each stock as it goes, and on another call skips the stocks it already
; has for the same year_end, so a call that was stopped, or that ran into a sign-in that had run out, picks up where it left off. Schwab allows about two requests a second; with 4,800 stocks a full run takes more than an hour.

(define stock-returns-batch 400)         ; how many stocks to ask Schwab for the market cap and dividend of in one request
(define stock-returns-pause 0.6)         ; seconds between requests for prices
(define stock-returns-retry-pause 30)    ; seconds to wait after Schwab says it has had too many requests

(define (stock-returns--create conn)
  "Makes the table of returns, with a row for each ticker, if the database doesn't have it yet."
  (sqlite-execute conn
    "CREATE TABLE IF NOT EXISTS stock_returns (ticker TEXT PRIMARY KEY, year_end TEXT, start_date TEXT, end_date TEXT, start_price REAL, end_price REAL,
                                               dividend REAL, market_cap REAL, return REAL, note TEXT)"))

(define (stock-returns--join-with-commas words)
  (reduce (lambda (so-far word) (string-append so-far "," word)) (cdr words) (car words)))

(define (stock-returns--ask-schwab thing)
  "Calls thing (a function of no arguments that asks Schwab), and if Schwab says there have been too many requests, waits and calls it again, up to
three times."
  (let loop ((tries-left 3))
    (let ((answer (catch-error (list (thing)) (message)
                    (if (and (> tries-left 1) (string-search message "HTTP 429"))
                        'too-many-requests
                        (error message)))))
      (if (eq? answer 'too-many-requests)
          (begin (sleep stock-returns-retry-pause) (loop (- tries-left 1)))
          (car answer)))))

(define (stock-returns--first count items)
  "The first count of the items."
  (if (or (= count 0) (null? items)) '() (cons (car items) (stock-returns--first (- count 1) (cdr items)))))

(define (stock-returns--fundamentals creds tickers)
  "Schwab's market cap and annual dividend for the tickers (as many as stock-returns-batch at once), as a hash table from ticker to (market-cap dividend).
A ticker Schwab doesn't know is not in it."
  (let ((answer (stock-returns--ask-schwab
                  (lambda () (schwab-get creds "/marketdata/v1/instruments"
                                         (list (cons "symbol" (stock-returns--join-with-commas tickers)) (cons "projection" "fundamental"))))))
        (found (make-hash-table)))
    (for-each (lambda (instrument)
                (let ((facts (hash-table-ref instrument "fundamental")))
                  (if facts
                      (hash-table-set! found (hash-table-ref instrument "symbol")
                                       (list (hash-table-ref facts "marketCap" 0.0) (hash-table-ref facts "dividendAmount" 0.0))))))
              (hash-table-ref answer "instruments" '()))
    found))

(define (stock-returns--prices creds ticker start-date end-date)
  "The first and last closing prices of the ticker in the dates, as (start-date start-price end-date end-price), or a string saying why there are none."
  (catch-error
    (let ((prices (stock-returns--ask-schwab
                    (lambda () (schwab-price-history creds ticker :start-date start-date :end-date end-date)))))
      (let ((dates (table-column prices "date")) (closes (table-column prices "close")))
        (list (vector-ref dates 0) (vector-ref closes 0)
              (vector-ref dates (- (vector-length dates) 1)) (vector-ref closes (- (vector-length closes) 1)))))
    (message) (if (string-search message "has no prices") "Schwab has no prices for it" message)))

(define (stock-returns--save conn ticker year-end prices facts)
  "Replaces the ticker's row in stock_returns. prices is what stock-returns--prices gave, facts is (market-cap dividend) or #f."
  (let* ((have-prices (list? prices))
         (market-cap (if facts (car facts) '()))
         (dividend (if facts (cadr facts) 0.0))
         (start-price (if have-prices (cadr prices) '()))
         (end-price (if have-prices (cadddr prices) '()))
         (note (cond ((not have-prices) prices) ((not facts) "Schwab has no market cap or dividend for it") (else ""))))
    (sqlite-execute conn "DELETE FROM stock_returns WHERE ticker = ?" (list ticker))
    (sqlite-execute conn "INSERT INTO stock_returns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
      (list ticker (date->string year-end)
            (if have-prices (date->string (car prices)) '())
            (if have-prices (date->string (caddr prices)) '())
            start-price end-price dividend market-cap
            (if have-prices (/ (+ (- end-price start-price) dividend) start-price) '())
            note))))

(define (stock-returns--wanted conn end-date)
  "The tickers of ticker_industry that stock_returns doesn't have yet for a year ending at end-date, in order."
  (vector->list
    (table-column
      (sqlite-query conn
        (string-append "SELECT ticker FROM ticker_industry
                         WHERE ticker NOT IN (SELECT ticker FROM stock_returns WHERE year_end = '" (date->string end-date) "')
                         ORDER BY ticker"))
      "ticker")))

(define (stock-returns--do-batch creds conn tickers start-date end-date)
  (let ((fundamentals (stock-returns--fundamentals creds tickers)))
    (for-each (lambda (ticker)
                (stock-returns--save conn ticker end-date (stock-returns--prices creds ticker start-date end-date)
                                     (hash-table-ref fundamentals ticker #f))
                (sleep stock-returns-pause))
              tickers)))

(define (stock-returns-update creds db-path &key (end-date '()))
  "Gets the last year's return of every stock in ticker_industry from Schwab and keeps it in the table stock_returns of the database at db-path (see the
top of industry_returns.lsp). The year ends at :end-date (today). Skips the stocks already there, and returns a table of how many have a return and how many
have none, with the reasons."
  (with-sqlite (conn db-path)
    (stock-returns--create conn)
    (let* ((end (if (null? end-date) (today) (if (string? end-date) (string->date end-date) end-date)))
           (start (date-add-years end -1))
           (wanted (stock-returns--wanted conn end)))
      (display (length wanted)) (display " stocks to get") (newline)
      (let loop ((remaining wanted))
        (if (pair? remaining)
            (let* ((count (min stock-returns-batch (length remaining)))
                   (batch (stock-returns--first count remaining)))
              (stock-returns--do-batch creds conn batch start end)
              (display (+ (- (length wanted) (length remaining)) count)) (display " done") (newline)
              (loop (list-tail remaining count)))))
      (stock-returns--summarize conn))))

(define (stock-returns--summarize conn)
  (sqlite-query conn
    "SELECT CASE WHEN return IS NULL THEN note ELSE 'has a return' END AS what, COUNT(*) AS stocks FROM stock_returns GROUP BY what ORDER BY stocks DESC"))

; ---------------------------------------------------------------------------------------------------------------------------------------------------------
; Industries
; ---------------------------------------------------------------------------------------------------------------------------------------------------------

(define (industry-returns--stocks conn)
  "The stocks with a return and a market cap: ticker, industry, return and market_cap."
  (sqlite-query conn
    "SELECT r.ticker AS ticker, i.industry AS industry, r.return AS return, r.market_cap AS market_cap
       FROM stock_returns r JOIN ticker_industry i ON i.ticker = r.ticker
      WHERE r.return IS NOT NULL AND r.market_cap > 0"))

(define (industry-returns db-path)
  "A table of each industry's return over the last year: the stocks in it, their market cap, the return of all of them together (each stock weighted by its
market cap), the plain average of their returns, and the standard deviation of their returns (how far apart the stocks in it are). Largest industry first."
  (with-sqlite (conn db-path)
    (table-sort
      (table-group-by (industry-returns--stocks conn) "industry"
        '(("stocks" count "ticker")
          ("market-cap" sum "market_cap")
          ("weighted-return" weighted-mean "return" "market_cap")
          ("average-return" mean "return")
          ("stdev-of-returns" stdev "return")))
      "market-cap" #t)))

(define (industry-variation--measures stocks return-column weight-column)
  "How the stocks' returns split into the part industries explain and the part they don't, weighting each stock by the weight column, as a list of
(name . value). A stock's return differs from the average of all stocks' by (how far its industry's average is from that) plus (how far it is from its own
industry's average); the squares of the two add up, weighted, to the square of the total."
  (let* ((weights (table-column stocks weight-column))
         (returns (table-column stocks return-column))
         (total-weight (vector-sum weights))
         (all-average (/ (vector-sum (vector-mul weights returns)) total-weight))
         (industry-averages (table-group-by stocks "industry" (list (list "industry-average" 'weighted-mean return-column weight-column))))
         (with-averages (table-join stocks industry-averages "industry"))
         (own-industry (table-column with-averages "industry-average"))
         (total-squares (vector-sum (vector-mul weights (vector-pow (vector-sub returns all-average) 2))))
         (within-squares (vector-sum (vector-mul weights (vector-pow (vector-sub returns own-industry) 2))))
         (between-squares (- total-squares within-squares)))
    (list (cons "stdev-of-all-returns" (sqrt (/ total-squares total-weight)))
          (cons "stdev-within-industries" (sqrt (/ within-squares total-weight)))
          (cons "stdev-between-industries" (sqrt (/ between-squares total-weight)))
          (cons "share-explained-by-industry" (/ between-squares total-squares)))))

(define (industry-returns--with-ranks stocks)
  "The stocks with a column, return-rank, of where each return stands among all of them, from near 0 for the lowest to 1 for the highest."
  (table-add-columns stocks
    (list (cons "return-rank" (vector-div (vector-rank (table-column stocks "return")) (table-row-count stocks))))))

(define (industry-variation db-path)
  "How well do the industries separate returns? A table of measures, with a column for each way of weighting the stocks:
  equal-weights         every stock counts the same
  market-cap-weights    each stock counts in proportion to its market cap
  return-ranks          every stock counts the same, but each return is replaced by its rank among all of them, from 0 to 1, so that a few stocks that went
                        up tenfold, or lost nearly everything, do not decide the answer (the stdevs are then in ranks, and a spread over all of 0 to 1 is 0.29)
The measures:
  stdev-of-all-returns         how far a stock's return is from the average of all of them, typically
  stdev-within-industries      how far it is from the average of its own industry, typically
  stdev-between-industries     how far its industry's average is from the average of all, typically
  share-explained-by-industry  between-industries variation as a share of the total (R-squared: 0 if industry tells you nothing, 1 if all stocks in an industry
                               had the same return)
  share-by-chance              what that share would be if the stocks were put in industries at random, which is not 0 because an industry of a few
                               stocks has an average that moves with them (the number of industries less 1, over the number of stocks less 1);
                               for equal weights only
  stocks, industries           how many of each
A share well above share-by-chance means the industries are separating returns; the stdev-within against the stdev-between shows by how much."
  (with-sqlite (conn db-path)
    (let* ((stocks (table-add-columns (industry-returns--with-ranks (industry-returns--stocks conn)) (list (cons "equal" 1.0))))
           (stock-count (table-row-count stocks))
           (industry-count (length (vector->list (table-column (table-group-by stocks "industry" '(("n" count "ticker"))) "industry"))))
           (equal-weighted (industry-variation--measures stocks "return" "equal"))
           (by-market-cap (industry-variation--measures stocks "return" "market_cap"))
           (by-rank (industry-variation--measures stocks "return-rank" "equal"))
           (chance (/ (- industry-count 1.0) (- stock-count 1.0)))
           (extra (list (cons "share-by-chance" chance) (cons "stocks" stock-count) (cons "industries" industry-count))))
      (make-table "measure" (list->vector (append (map car equal-weighted) (map car extra)))
                  "equal-weights" (list->vector (append (map cdr equal-weighted) (map cdr extra)))
                  "market-cap-weights" (list->vector (append (map cdr by-market-cap) (list nan stock-count industry-count)))
                  "return-ranks" (list->vector (append (map cdr by-rank) (list chance stock-count industry-count)))))))
