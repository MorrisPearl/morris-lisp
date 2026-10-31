; financial_data.lsp
; ==================
; A SQLite database of market history, for comparing one thing with another over time, and the function that brings it up to date.
;
;   (financial-data-update creds "financial_data.db")
;
; The first call makes the database and fills it with ten years of history; after that, each call asks only for what is missing, from two weeks before the
; last day it has (a source corrects a number now and then) to today. Run it as often as you like.
;
; The database has two tables.
;
;   tba_prices    what agency TBAs traded at each day (finra_database.lsp describes it)
;   time_series   one number for each day, instrument and term:
;                   date         the day
;                   instrument   what it is: see the list below
;                   term         which one of that instrument, for those that come in terms (a Treasury's maturity: "10Y"); "" for those that don't
;                   value        a rate is in percent, as its source publishes it (4.25 is 4.25%); the index is a number of dollars
;
; The instruments:
;
;   treasury-par                  the Treasury's par yield curve, by maturity: 1M, 1.5M, 2M, 3M, 4M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y
;                                 (a maturity the Treasury did not publish on a day has no row for it; the 1.5M and 4M began in 2022 and 2025)
;   freddie-mac-mortgage-rate     Freddie Mac's weekly survey of the 30- and 15-year fixed mortgage rate: 30Y, 15Y (from FRED)
;   sofr                          the Secured Overnight Financing Rate, from the New York Fed: term "ON" (overnight)
;   sofr-average                  the 30-, 90- and 180-day averages of SOFR: 30D, 90D, 180D
;   sofr-index                    what $1 put in SOFR on April 2, 2018 has grown to
;   current-coupon-<agency>       the coupon at which a TBA is worth 100, worked out from tba_prices (see current-coupon-sql): term 30Y or 15Y;
;                                 the agencies are FNMA and FHLMC until 2019, FNMA-UMBS in 2019, UMBS since, and GNMA
;
; Each source is asked for from its own last day, so one that fails does not stop the others from being brought up to date by the next call.
;
; Read a series with (time-series conn instrument term), or several, side by side by date, with (time-series-table conn '((instrument term) ...)).

(define financial-data-years 10)       ; how far back the first run goes
(define financial-data-margin 14)      ; how many days before the last one a run starts again

(define (time-series--create conn)
  "Makes the table of time series, with the day, instrument and term as its key, if the database does not have it yet."
  (sqlite-execute conn
    "CREATE TABLE IF NOT EXISTS time_series (date TEXT, instrument TEXT, term TEXT, value REAL, PRIMARY KEY (date, instrument, term))")
  (sqlite-execute conn "CREATE INDEX IF NOT EXISTS time_series_by_instrument ON time_series (instrument, term, date)"))

(define (time-series--start conn instrument-pattern start-date)
  "The day to ask a source from, for the instruments that match the pattern (SQL's LIKE): start-date if there is one, or the margin before the last day
the database has for them, or ten years ago if it has none."
  (let ((last (vector-ref (cdr (car (sqlite-query conn "SELECT MAX(date) AS last FROM time_series WHERE instrument LIKE ?" '() '()
                                                   (list instrument-pattern)))) 0)))
    (cond ((not (null? start-date)) start-date)
          ((date? last) (date-add-days last (- financial-data-margin)))
          (else (date-add-years (today) (- financial-data-years))))))

(define (time-series--rows instrument wide columns)
  "The rows of the time_series table (a table of date, instrument, term and value) from a table with a column for each term and a row for each date.
columns is a list of (column term scale): the column of wide, the term to call it, and what to multiply it by to make a percent. Days with no value
are left out."
  (apply table-append
         (map (lambda (column)
                (let* ((values (vector-mul (table-column wide (car column)) (caddr column)))
                       (found (table-filter (make-table "date" (table-column wide "date") "value" values)
                                            (vector= (vector-nan? values) 0))))
                  (table-select (table-add-columns found (list (cons "instrument" instrument) (cons "term" (cadr column))))
                                '("date" "instrument" "term" "value"))))
              columns)))

(define (time-series--replace conn instrument-pattern from rows)
  "Replaces what the database has of the instruments that match the pattern, from the day from on, with the rows. Returns how many rows it wrote."
  (sqlite-execute conn "DELETE FROM time_series WHERE instrument LIKE ? AND date >= ?" (list instrument-pattern (date->string from)))
  (if (> (table-row-count rows) 0)
      (sqlite-write-table conn "time_series" rows 'append)
      0))

(define (time-series--say what from to)
  (display what) (display ", ") (display from) (display " to ") (display to) (newline))

; ---------------------------------------------------------------------------
; The sources
; ---------------------------------------------------------------------------

; The Treasury's heading for each maturity (the name treasury-par-curve gives it), and the term it is stored as.
(define treasury-par-terms
  '(("1m" "1M") ("1.5m" "1.5M") ("2m" "2M") ("3m" "3M") ("4m" "4M") ("6m" "6M") ("1y" "1Y") ("2y" "2Y") ("3y" "3Y") ("5y" "5Y")
    ("7y" "7Y") ("10y" "10Y") ("20y" "20Y") ("30y" "30Y")))

(define (update-treasury conn to start-date)
  (let ((from (time-series--start conn "treasury-par" start-date)))
    (time-series--say "Treasury par yields" from to)
    (time-series--replace conn "treasury-par" from
      (time-series--rows "treasury-par" (treasury-par-curve :start-date from :end-date to)
                         (map (lambda (pair) (list (car pair) (cadr pair) 100)) treasury-par-terms)))))   ; the Treasury's are fractions: 0.0512

(define (update-mortgage-rates conn creds to start-date)
  (let ((from (time-series--start conn "freddie-mac-mortgage-rate" start-date)))
    (time-series--say "Freddie Mac mortgage rates (FRED)" from to)
    (time-series--replace conn "freddie-mac-mortgage-rate" from
      (time-series--rows "freddie-mac-mortgage-rate"
                         (fred-table creds '("MORTGAGE30US" "MORTGAGE15US") :start-date from :end-date to :cache-hours 0)
                         '(("MORTGAGE30US" "30Y" 1) ("MORTGAGE15US" "15Y" 1))))))

(define (update-sofr conn to start-date)
  (let ((from (time-series--start conn "sofr%" start-date)))
    (time-series--say "SOFR (New York Fed)" from to)
    (time-series--replace conn "sofr%" from
      (let ((rates (nyfed-rates '("SOFR" "SOFR-30" "SOFR-90" "SOFR-180" "SOFR-INDEX") :start-date from :end-date to :cache-hours 0)))
        (table-append
          (time-series--rows "sofr" rates '(("SOFR" "ON" 1)))
          (time-series--rows "sofr-average" rates '(("SOFR-30" "30D" 1) ("SOFR-90" "90D" 1) ("SOFR-180" "180D" 1)))
          (time-series--rows "sofr-index" rates '(("SOFR-INDEX" "" 1))))))))

; The current coupon of an agency's TBAs on a day: the coupon at which the price is 100. TBAs trade in coupons half a point apart, so it is on the line
; between the price of the coupon just below par and the one just above. Which settlement month to use: the one with the most trades that day (the
; month being traded; the one that has just settled has hardly any).
;
; FINRA gives the coupons in the middle of the range one by one, and the ones at each end as a bucket ("<= 3.0", "> 5.5"), a price for all the coupons beyond
; it. When par is beyond the last coupon given alone (a price under 100 for 5.5 and over 100 for "> 5.5"), the line through the last two coupons is carried on
; to 100, if that is within half a point of the last. A day where par is further out, or that has no coupon half a point from another, has no current coupon.
(define current-coupon-sql
  "WITH month_trades AS (
     SELECT date, agency, product, settlement_month, SUM(trades) AS total
     FROM tba_prices WHERE date >= ? GROUP BY date, agency, product, settlement_month),
   busiest AS (
     SELECT date, agency, product, settlement_month,
            ROW_NUMBER() OVER (PARTITION BY date, agency, product ORDER BY total DESC, settlement_month) AS place
     FROM month_trades),
   traded AS MATERIALIZED (
     SELECT p.date, p.agency, p.product, p.coupon, p.coupon_rate, p.weighted_average_price AS price
     FROM tba_prices p JOIN busiest b ON p.date = b.date AND p.agency = b.agency AND p.product = b.product
                                      AND p.settlement_month = b.settlement_month AND b.place = 1),
   single AS MATERIALIZED (SELECT * FROM traded WHERE coupon NOT LIKE '<%' AND coupon NOT LIKE '>%'),
   estimates AS (
     -- par between two coupons half a point apart
     SELECT low.date, low.agency, low.product, 1 AS source,
            low.coupon_rate + (100 - low.price) / (high.price - low.price) * 0.5 AS current_coupon
     FROM single low JOIN single high ON low.date = high.date AND low.agency = high.agency AND low.product = high.product
                                      AND high.coupon_rate = low.coupon_rate + 0.5
     WHERE low.price < 100 AND high.price >= 100
     UNION ALL
     -- par beyond the highest coupon, in the bucket above it
     SELECT last.date, last.agency, last.product, 2,
            last.coupon_rate + (100 - last.price) / (last.price - before.price) * 0.5
     FROM single last JOIN single before ON last.date = before.date AND last.agency = before.agency AND last.product = before.product
                                         AND before.coupon_rate = last.coupon_rate - 0.5
          JOIN traded above ON last.date = above.date AND last.agency = above.agency AND last.product = above.product
                            AND above.coupon LIKE '>%' AND above.coupon_rate = last.coupon_rate
     WHERE last.price < 100 AND above.price >= 100 AND (100 - last.price) / (last.price - before.price) <= 1
     UNION ALL
     -- par below the lowest coupon, in the bucket below it
     SELECT first.date, first.agency, first.product, 2,
            first.coupon_rate - (first.price - 100) / (after.price - first.price) * 0.5
     FROM single first JOIN single after ON first.date = after.date AND first.agency = after.agency AND first.product = after.product
                                         AND after.coupon_rate = first.coupon_rate + 0.5
          JOIN traded below ON first.date = below.date AND first.agency = below.agency AND first.product = below.product
                            AND below.coupon LIKE '<%' AND below.coupon_rate = first.coupon_rate - 0.5
     WHERE first.price >= 100 AND below.price < 100 AND (first.price - 100) / (after.price - first.price) <= 1),
   chosen AS (
     SELECT *, ROW_NUMBER() OVER (PARTITION BY date, agency, product ORDER BY source, current_coupon) AS place FROM estimates)
   SELECT date, 'current-coupon-' || REPLACE(agency, '/', '-') AS instrument, SUBSTR(product, -3) AS term, current_coupon AS value
   FROM chosen WHERE place = 1 ORDER BY date, instrument, term")

(define (update-current-coupons conn to start-date)
  (let ((from (time-series--start conn "current-coupon-%" start-date)))
    (time-series--say "Current coupons, from the TBA prices" from to)
    (time-series--replace conn "current-coupon-%" from
      (let ((rows (sqlite-query conn current-coupon-sql '() '() (list (date->string from)))))
        (if (null? rows) (make-table "date" (vector) "instrument" (vector) "term" (vector) "value" (vector)) rows)))))

; ---------------------------------------------------------------------------
; The call
; ---------------------------------------------------------------------------

(define (financial-data--day value fallback)
  "A date, from a date or YYYY-MM-DD text, or the fallback if there is none."
  (cond ((null? value) fallback) ((string? value) (string->date value)) (else value)))

(define (financial-data-update creds db-path &key (start-date '()) (end-date '()))
  "Brings the database at db-path up to date: the TBA prices (finra-tba-update), then each time series from its own last day to :end-date (today), or
from :start-date for all of them (to work out a series again). It makes the database if there is not one. Returns the table that financial-data-summary gives."
  (let ((to (financial-data--day end-date (today)))
        (from (financial-data--day start-date '())))
    (finra-tba-update creds db-path :start-date from :end-date to)
    (with-sqlite (conn db-path)
      (time-series--create conn)
      (update-treasury conn to from)
      (update-mortgage-rates conn creds to from)
      (update-sofr conn to from)
      (update-current-coupons conn to from))
    (financial-data-summary db-path)))

(define (financial-data-summary db-path)
  "A table of what the time_series table has: for each instrument and term, its rows, its first day and its last."
  (with-sqlite (conn db-path)
    (sqlite-query conn
      "SELECT instrument, term, COUNT(*) AS rows, MIN(date) AS first_day, MAX(date) AS last_day FROM time_series GROUP BY instrument, term
       ORDER BY instrument, term")))

(define (time-series conn instrument &optional (term ""))
  "A table of date and value for an instrument and term, oldest first."
  (sqlite-query conn "SELECT date, value FROM time_series WHERE instrument = ? AND term = ? ORDER BY date" '() '() (list instrument term)))

(define (time-series-table conn series)
  "A table with a row for each day that has any of the series, and a column for each, headed by the instrument and term (\"treasury-par 10Y\"), with
nan where a series has no value for the day. series is a list of (instrument term), such as '((\"treasury-par\" \"10Y\") (\"sofr\" \"ON\"))."
  (let* ((names (map (lambda (one) (string-trim (string-append (car one) " " (cadr one)))) series))
         (picks (map (lambda (n) (format "MAX(CASE WHEN instrument = ? AND term = ? THEN value END) AS c{}" n)) (iota (length series))))
         (sql (format "SELECT date, {} FROM time_series WHERE {} GROUP BY date ORDER BY date"
                      (string-join picks ", ")
                      (string-join (map (lambda (one) "(instrument = ? AND term = ?)") series) " OR ")))
         (params (append (apply append series) (apply append series)))
         (found (sqlite-query conn sql (apply string-append "." (map (lambda (one) "F") series)) '() params)))
    (reduce (lambda (t pair) (table-rename-column t (format "c{}" (car pair)) (cdr pair)))
            (map cons (iota (length series)) names)
            found)))
