; industry_returns.lsp
; ====================
; Do a stock's industry tell you how its price moved? Three functions to find out, from the table ticker_industry (ticker, industry) in the database:
;
;   (stock-returns-update creds "financial_data.db")    each stock's return over the last year, from Schwab, kept in the table stock_returns
;   (industry-returns "financial_data.db")              each industry's return, weighted by market capitalization
;   (industry-variation "financial_data.db")            how much stocks differ within an industry, against how much industries differ from each other
;
; and, further down, weekly (or monthly) returns over a few years and their principal components (stock-prices-update, periodic-returns, return-components).
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

(define (stock-returns--why-none message)
  "The note to keep for a stock Schwab gave an error for, from the error's message. An error that will happen for every stock -- the sign-in has run
out, or Schwab can't be reached -- is not kept as a note; it stops the run (which can be started again, and carries on from there)."
  (cond ((string-search message "has no prices") "Schwab has no prices for it")
        ((or (string-search message "schwab-login") (string-search message "couldn't reach")) (error message))
        (else message)))

(define (stock-returns--prices creds ticker start-date end-date)
  "The first and last closing prices of the ticker in the dates, as (start-date start-price end-date end-price), or a string saying why there are none."
  (catch-error
    (let ((prices (stock-returns--ask-schwab
                    (lambda () (schwab-price-history creds ticker :start-date start-date :end-date end-date)))))
      (let ((dates (table-column prices "date")) (closes (table-column prices "close")))
        (list (vector-ref dates 0) (vector-ref closes 0)
              (vector-ref dates (- (vector-length dates) 1)) (vector-ref closes (- (vector-length closes) 1)))))
    (message) (stock-returns--why-none message)))

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

; ---------------------------------------------------------------------------------------------------------------------------------------------------------
; Weekly (or monthly) returns, and the few patterns that explain much of them (principal components)
; ---------------------------------------------------------------------------------------------------------------------------------------------------------
;
;   (stock-prices-update creds "financial_data.db")   each stock's closing price at the end of each week for the last three years, from Schwab
;   (periodic-returns "financial_data.db")            a table with a row for each week and a column of each stock's returns
;   (return-components "financial_data.db")           the principal components of those returns
;
; Each takes :frequency, "weekly" (the default) or "monthly", and :years, how far back (3 for weekly, 2 for monthly). A period is named by its first day: the
; Monday of a week (as Schwab dates its weekly prices), or the first of a month. Only whole periods are used: the last is the one before the period the update
; is run in. The Canadian stocks (tickers ending in .TO) are left out.
;
; A period's return is (its close - the last period's close + the dividends with an ex-date in it) / the last period's close. The dividend is the current one,
; the same number of dollars each time: Schwab's dividendAmount (a year's dividends at the current rate) over dividendFreq (how many payments a year: 4 for
; most, 12 for some, 2 for some foreign companies). The ex-dates (the day the price falls by the dividend) are Schwab's dividendDate (the latest, or the
; next) and the same day of the month every 12 / dividendFreq months before and after it -- which only approximates the real ones, which move about by a
; few days. A stock with a dividend but no ex-date, or with a number of payments a year that doesn't divide a year into whole months, gets its dividend
; spread evenly over the periods (a 52nd a week, a 12th a month).
;
; The tables, for each frequency: weekly_prices (ticker, period, close) and weekly_prices_asked (ticker, last_period, periods, note), a row for each stock
; asked for, so that a run that is stopped picks up where it left off (and monthly_prices and monthly_prices_asked); and stock_dividends (ticker,
; annual_dividend, payments_per_year, ex_date), the dividends as Schwab has them now, which stock-prices-update gets afresh each time (a few requests).

(define stock-prices-default-years '(("weekly" . 3) ("monthly" . 2)))    ; how many years of returns, unless :years says
(define stock-prices-periods-per-year '(("weekly" . 52) ("monthly" . 12)))

(define (stock-prices--check frequency)
  (if (not (assoc frequency stock-prices-default-years))
      (error "stock prices: :frequency is \"weekly\" or \"monthly\", not" frequency)))

(define (stock-prices--years frequency years)
  "The years asked for, or the frequency's usual number."
  (if (null? years) (cdr (assoc frequency stock-prices-default-years)) years))

(define (stock-prices--table frequency) (string-append frequency "_prices"))              ; weekly_prices or monthly_prices
(define (stock-prices--asked-table frequency) (string-append frequency "_prices_asked"))  ; weekly_prices_asked or monthly_prices_asked

(define (stock-prices--create conn frequency)
  (sqlite-execute conn (string-append "CREATE TABLE IF NOT EXISTS " (stock-prices--table frequency)
                                      " (ticker TEXT, period TEXT, close REAL, PRIMARY KEY (ticker, period))"))
  (sqlite-execute conn (string-append "CREATE TABLE IF NOT EXISTS " (stock-prices--asked-table frequency)
                                      " (ticker TEXT PRIMARY KEY, last_period TEXT, periods INTEGER, note TEXT)")))

(define (stock-prices--period-of frequency day)
  "The first day of the period day is in: the Monday of its week, or the first of its month."
  (if (equal? frequency "weekly")
      (date-add-days day (- 1 (date-day-of-week day)))
      (date (date-year day) (date-month day) 1)))

(define (stock-prices--period-sql frequency day-sql)
  "The same, as SQL, of the SQL day-sql: SQLite's 'weekday 1' goes forward to a Monday, so going back six days first finds the one the week starts on."
  (if (equal? frequency "weekly")
      (string-append "date(" day-sql ", '-6 days', 'weekday 1')")
      (string-append "date(" day-sql ", 'start of month')")))

(define (stock-prices--last-period frequency day)
  "The first day of the last whole period before the period of day."
  (let ((this-period (stock-prices--period-of frequency day)))
    (if (equal? frequency "weekly") (date-add-days this-period -7) (date-add-months this-period -1))))

(define (stock-prices--first-period frequency last-period years)
  "The first day of the period whose close comes before the first return: years before the last period."
  (stock-prices--period-of frequency (date-add-years last-period (- years))))

(define (stock-prices--end-of-period frequency first-day)
  (if (equal? frequency "weekly") (date-add-days first-day 6) (date-end-of-month first-day)))

; --- dividends ---

(define (stock-dividends--create conn)
  (sqlite-execute conn "CREATE TABLE IF NOT EXISTS stock_dividends (ticker TEXT PRIMARY KEY, annual_dividend REAL, payments_per_year INTEGER, ex_date TEXT)"))

(define (stock-dividends--batch creds tickers)
  "Schwab's dividend facts for the tickers, as a table of ticker, annual_dividend, payments_per_year and ex_date (\"\" if there is none)."
  (let* ((answer (stock-returns--ask-schwab
                   (lambda () (schwab-get creds "/marketdata/v1/instruments"
                                          (list (cons "symbol" (stock-returns--join-with-commas tickers)) (cons "projection" "fundamental"))))))
         (facts (filter (lambda (f) f)
                        (map (lambda (instrument) (hash-table-ref instrument "fundamental"))
                             (hash-table-ref answer "instruments" '()))))
         (ex-date (lambda (f) (let ((text (hash-table-ref f "dividendDate" "")))
                                (if (>= (string-length text) 10) (substring text 0 10) "")))))
    (make-table "ticker" (list->vector (map (lambda (f) (hash-table-ref f "symbol")) facts))
                "annual_dividend" (list->vector (map (lambda (f) (hash-table-ref f "dividendAmount" 0.0)) facts))
                "payments_per_year" (list->vector (map (lambda (f) (hash-table-ref f "dividendFreq" 0)) facts))
                "ex_date" (list->vector (map ex-date facts)))))

(define (stock-dividends-update creds db-path)
  "Gets Schwab's dividend facts for every stock in ticker_industry but the Canadian ones (a year's dividends at the current rate, how many payments a
year, and the latest or next ex-dividend date) and keeps them in the table stock_dividends, in place of what it had. Asks for stock-returns-batch at a time.
Returns how many stocks it has, and how many of them pay a dividend."
  (with-sqlite (conn db-path)
    (stock-dividends--create conn)
    (let ((tickers (vector->list (table-column (sqlite-query conn "SELECT ticker FROM ticker_industry WHERE ticker NOT LIKE '%.TO' ORDER BY ticker")
                                               "ticker"))))
      (sqlite-execute conn "DELETE FROM stock_dividends")
      (let loop ((remaining tickers))
        (if (pair? remaining)
            (let ((count (min stock-returns-batch (length remaining))))
              (let ((found (stock-dividends--batch creds (stock-returns--first count remaining))))
                (if (> (table-row-count found) 0) (sqlite-write-table conn "stock_dividends" found 'append)))
              (loop (list-tail remaining count)))))
      (sqlite-query conn "SELECT COUNT(*) AS stocks, SUM(annual_dividend > 0) AS paying_dividends FROM stock_dividends"))))

; --- prices ---

(define (stock-prices--wanted conn frequency last-period)
  "The tickers of ticker_industry, but for the Canadian ones, not yet asked for with this last period, in order."
  (vector->list
    (table-column
      (sqlite-query conn (string-append "SELECT ticker FROM ticker_industry
                                          WHERE ticker NOT LIKE '%.TO'
                                            AND ticker NOT IN (SELECT ticker FROM " (stock-prices--asked-table frequency) " WHERE last_period = ?)
                                          ORDER BY ticker")
                    '() '() (list (date->string last-period)))
      "ticker")))

(define (stock-prices--save conn creds frequency ticker first-period last-period)
  "Asks Schwab for the ticker's closes from first-period to the end of last-period, and replaces what the prices table has for it."
  (let* ((prices (catch-error (stock-returns--ask-schwab
                                (lambda () (schwab-price-history creds ticker :frequency frequency
                                                                 :start-date first-period :end-date (stock-prices--end-of-period frequency last-period))))
                   (message) message))
         (whole-periods (if (string? prices) '() (table-filter prices (vector<= (table-column prices "date") last-period))))
         (periods (if (null? whole-periods) 0 (table-row-count whole-periods)))
         (note (cond ((string? prices) (stock-returns--why-none prices))
                     ((= periods 0) "Schwab has no whole periods for it")
                     (else ""))))
    (sqlite-execute conn (string-append "DELETE FROM " (stock-prices--table frequency) " WHERE ticker = ?") (list ticker))
    (if (> periods 0)
        (sqlite-write-table conn (stock-prices--table frequency)
          (table-add-columns (table-select (table-rename-column whole-periods "date" "period") '("period" "close"))
                             (list (cons "ticker" ticker)))
          'append))
    (sqlite-execute conn (string-append "DELETE FROM " (stock-prices--asked-table frequency) " WHERE ticker = ?") (list ticker))
    (sqlite-execute conn (string-append "INSERT INTO " (stock-prices--asked-table frequency) " VALUES (?, ?, ?, ?)")
                    (list ticker (date->string last-period) periods note))))

(define (stock-prices-update creds db-path &key (frequency "weekly") (years '()) (end-date '()))
  "Gets each stock's closes at the end of each week (or, with :frequency \"monthly\", each month) for the last :years (3 for weekly, 2 for monthly) whole
years, before the period of :end-date (today), from Schwab, and keeps them in the table weekly_prices (or monthly_prices) of the database at db-path; first it
brings the dividends up to date (stock-dividends-update). Skips the stocks it already has, so it can be stopped and called again. Returns a table of how many
stocks it has every period for, how many some periods, and how many none, by reason."
  (stock-prices--check frequency)
  (display "dividends: ") (display (stock-dividends-update creds db-path)) (newline)
  (with-sqlite (conn db-path)
    (stock-prices--create conn frequency)
    (let* ((end (if (null? end-date) (today) (if (string? end-date) (string->date end-date) end-date)))
           (last-period (stock-prices--last-period frequency end))
           (first-period (stock-prices--first-period frequency last-period (stock-prices--years frequency years)))
           (wanted (stock-prices--wanted conn frequency last-period)))
      (display (length wanted)) (display " stocks to get") (newline)
      (let loop ((remaining wanted) (done 0))
        (if (pair? remaining)
            (begin
              (stock-prices--save conn creds frequency (car remaining) first-period last-period)
              (sleep stock-returns-pause)
              (if (= (remainder (+ done 1) 400) 0) (begin (display (+ done 1)) (display " done") (newline)))
              (loop (cdr remaining) (+ done 1)))))
      (sqlite-query conn
        (string-append "SELECT CASE WHEN note != '' THEN note WHEN periods = (SELECT MAX(periods) FROM " (stock-prices--asked-table frequency)
                       " WHERE last_period = ?) THEN 'every period' ELSE 'some periods' END AS what, COUNT(*) AS stocks
                         FROM " (stock-prices--asked-table frequency) " WHERE last_period = ? GROUP BY what ORDER BY stocks DESC, what")
        '() '() (list (date->string last-period) (date->string last-period))))))

; --- returns ---

(define (periodic-returns--long conn frequency years)
  "The returns, a row for each stock and period: ticker, period, return and market_cap, for the stocks that have a return in every one of the periods of the
last years the prices table has."
  (stock-returns--create conn)      ; (the market caps come from it; without it, there are none)
  (stock-dividends--create conn)    ; (and the dividends from this)
  (let* ((prices (stock-prices--table frequency))
         (last-period (string->date (date->string (vector-ref (table-column (sqlite-query conn (string-append "SELECT MAX(period) AS last FROM " prices))
                                                                            "last") 0))))
         (first-period (date->string (stock-prices--first-period frequency last-period years)))
         (spread-over (cdr (assoc frequency stock-prices-periods-per-year))))
    (sqlite-query conn
      (string-append
      "WITH RECURSIVE
       -- each stock's ex-dividend dates: Schwab's, and the same day of the month every 12 / payments_per_year months before it, back to the first period,
       -- and after it, up to the last (step is -1 going back and +1 going forward). The months are counted from the first of the month, and the day put
       -- back, but no later than the month's last day: SQLite takes May 31 less 3 months to be March 3.
       ex_months (ticker, month, day_of_month, payment, months_apart, step) AS (
         SELECT ticker, date(ex_date, 'start of month'), CAST(strftime('%d', ex_date) AS INTEGER),
                annual_dividend / payments_per_year, 12 / payments_per_year, step
           FROM stock_dividends, (SELECT -1 AS step UNION ALL SELECT 1)
          WHERE annual_dividend > 0 AND ex_date != '' AND payments_per_year IN (1, 2, 3, 4, 6, 12)
         UNION ALL
         SELECT ticker, date(month, printf('%+d months', step * months_apart)), day_of_month, payment, months_apart, step FROM ex_months
          WHERE (step < 0 AND month >= date(?, 'start of month')) OR (step > 0 AND month <= ?)),
       ex_days AS (
         SELECT DISTINCT ticker, MIN(date(month, printf('+%d days', day_of_month - 1)), date(month, '+1 month', '-1 day')) AS day, payment
           FROM ex_months),     -- (DISTINCT: Schwab's own date is there twice, once for each step)
       paid AS (SELECT ticker, " (stock-prices--period-sql frequency "day") " AS period, SUM(payment) AS dividend FROM ex_days GROUP BY ticker, period),
       -- a stock with a dividend but no ex-date, or an odd number of payments a year: spread evenly over the periods
       spread AS (SELECT ticker, annual_dividend / " (number->string spread-over) ".0 AS dividend FROM stock_dividends
                   WHERE annual_dividend > 0 AND NOT (ex_date != '' AND payments_per_year IN (1, 2, 3, 4, 6, 12))),
       priced AS (
         SELECT p.ticker, p.period, p.close,
                LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.period) AS previous_close,
                COALESCE(paid.dividend, spread.dividend, 0) AS dividend,
                COALESCE(r.market_cap, 0) AS market_cap
           FROM " prices " p
                LEFT JOIN paid ON paid.ticker = p.ticker AND paid.period = p.period
                LEFT JOIN spread ON spread.ticker = p.ticker
                LEFT JOIN stock_returns r ON r.ticker = p.ticker
          WHERE p.period >= ? AND p.period <= ?),
       returns AS (
         SELECT ticker, period, (close - previous_close + dividend) / previous_close AS return, market_cap
           FROM priced WHERE previous_close > 0),
       counts AS (SELECT ticker, COUNT(*) AS periods FROM returns GROUP BY ticker)
       SELECT ticker, period, return, market_cap FROM returns
        WHERE ticker IN (SELECT ticker FROM counts WHERE periods = (SELECT MAX(periods) FROM counts))
        ORDER BY ticker, period")
      '() '() (list first-period (date->string last-period) first-period (date->string last-period)))))

(define (periodic-returns db-path &key (frequency "weekly") (years '()))
  "A table of the stocks' weekly (or, with :frequency \"monthly\", monthly) returns: a period column (the first day of each week or month), and a column for
each stock that has a return in every one of the periods of the last :years (3 for weekly, 2 for monthly), named by its ticker."
  (stock-prices--check frequency)
  (with-sqlite (conn db-path)
    (table-pivot (periodic-returns--long conn frequency (stock-prices--years frequency years)) "period" "ticker" '(sum "return"))))

(define (return-components db-path &key (frequency "weekly") (years '()) (count 5) (standardize #t))
  "The principal components of the stocks' weekly (or, with :frequency \"monthly\", monthly) returns over the last :years (3 for weekly, 2 for monthly): the
:count (5) patterns of moving together that explain the most of how the stocks' returns went up and down. With :standardize #t (the default) each stock's
returns are first put on the same scale, so that the components explain how the stocks move together, not just which stocks move the most. Returns a list of
four tables, by name:
  (\"variance\" . table)    component, variance-share (the share of all the stocks' variation it explains), cumulative-share, share-if-unrelated (what
                           each component would explain if the stocks moved independently: 1 / (periods - 1)), and correlation-with-market (with the
                           market-cap-weighted return of all the stocks)
  (\"stocks\" . table)      ticker, industry, market_cap, pc1 ... (the correlation of the stock's returns with each component, from -1 to 1: how
                           closely it moves with it), and explained (the share of the stock's variation the components explain together: the
                           correlations' squares added up)
  (\"industries\" . table)  industry, stocks, and the average of its stocks' correlations and explained shares; largest first
  (\"periods\" . table)     period, pc1 ... (each component's value that week or month), and market-return
Read one with (cdr (assoc \"stocks\" components))."
  (stock-prices--check frequency)
  (with-sqlite (conn db-path)
    (let* ((long (periodic-returns--long conn frequency (stock-prices--years frequency years)))
           (wide (table-pivot long "period" "ticker" '(sum "return")))
           (periods (table-row-count wide))
           (pca (principal-components wide :count count :standardize standardize))
           (pc-names (map (lambda (i) (string-append "pc" (number->string i))) (iota (min count (- periods 1)) 1)))
           (market (table-group-by long "period" '(("market-return" weighted-mean "return" "market_cap"))))
           (scores (table-join (cdr (assoc "scores" pca)) market "period"))
           (market-returns (table-column scores "market-return"))
           (variance (table-add-columns (cdr (assoc "variance" pca))
                       (list (cons "share-if-unrelated" (/ 1.0 (- periods 1)))
                             (cons "correlation-with-market"
                                   (list->vector (map (lambda (name) (vector-correlation (table-column scores name) market-returns)) pc-names))))))
           (facts (sqlite-query conn "SELECT i.ticker AS ticker, i.industry AS industry, COALESCE(r.market_cap, 0) AS market_cap
                                        FROM ticker_industry i LEFT JOIN stock_returns r ON r.ticker = i.ticker"))
           (explained (table-select (cdr (assoc "loadings" pca)) '("column" "explained")))
           (stocks (table-join (table-join (cdr (assoc "correlations" pca)) explained "column") (table-rename-column facts "ticker" "column") "column"))
           (stocks (table-rename-column stocks "column" "ticker"))
           (stocks (table-select stocks (append '("ticker" "industry" "market_cap") pc-names '("explained"))))
           (industries (table-sort (table-group-by stocks "industry"
                                     (append '(("stocks" count "ticker"))
                                             (map (lambda (name) (list name 'mean name)) pc-names)
                                             '(("explained" mean "explained"))))
                                   "stocks" #t)))
      (list (cons "variance" variance) (cons "stocks" stocks) (cons "industries" industries) (cons "periods" scores)))))
