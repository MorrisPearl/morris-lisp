; finra_database.lsp
; ==================
; A SQLite database of the prices that agency TBAs traded at each day, from FINRA, and the function that brings it up to date.
;
;   (finra-tba-update creds "finra_tba.db")
;
; The first time, it makes the database and fills it with ten years of history (FINRA's TBA prices start in January 2017, so that is what there is). After
; that, each call asks FINRA only for what the database lacks, from a week before its last day (FINRA corrects a day's prices now and then) to today, so it
; takes seconds. Run it as often as you like; a day's prices come the next morning, and there are none for weekends and holidays.
;
; The database has one table, tba_prices, with a row for each day, product (SINGLE FAMILY 30Y or 15Y), agency, settlement month and coupon that had trades:
;
;   date, product, agency        FINRA's, as finra-tba-prices has them (agency is FNMA and FHLMC to 2019, FNMA/UMBS in 2019, UMBS since, and GNMA)
;   settlement                   FINRA's name for it: "November Settlement"
;   settlement_month             the first day of that month, as a date (the month is the next one on or after the report date)
;   coupon                       FINRA's bucket, as text: "4", "4.5", ..., and "<= 3.5" and "> 6" at the ends (FINRA moves the ends with the market)
;   coupon_rate                  the number in it (an end bucket gives its limit)
;   average_price ... trades     the statistics FINRA gives, named for what they are (see finra-tba--statistics below); prices are per 100 of face
;
; Query it as you would any SQLite file:
;
;   (with-sqlite (conn "finra_tba.db")
;     (sqlite-query conn "SELECT date, weighted_average_price FROM tba_prices
;                         WHERE agency = 'UMBS' AND product = 'SINGLE FAMILY 30Y' AND coupon = '5.5' AND settlement_month = '2026-11-01'
;                         ORDER BY date"))
;
; Rows with no trades are not kept. FINRA sends a row for every coupon every day, with zeros where nothing traded.

(define finra-database-years 10)   ; how far back the first run goes

(define finra-tba--table "tba_prices")

; FINRA's name for each statistic, and the column that holds it
(define finra-tba--statistics
  '(("average price" . "average_price")
    ("weighted avg. price" . "weighted_average_price")
    ("avg. price bottom 5 trades" . "bottom_5_average_price")
    ("2nd quartile price" . "quartile_2_price")
    ("3rd quartile price" . "quartile_3_price")
    ("4th quartile price" . "quartile_4_price")
    ("avg. price top 5 trades" . "top_5_average_price")
    ("standard deviation" . "standard_deviation")
    ("volume of trades (000's)" . "volume_thousands")
    ("number of trades" . "trades")))

(define finra-tba--months '("january" "february" "march" "april" "may" "june" "july" "august" "september" "october" "november" "december"))

(define (finra-tba--create-table conn)
  "Makes the table, with the day, product, agency, settlement and coupon as its key, if the database doesn't have it yet."
  (sqlite-execute conn
    (string-append "CREATE TABLE IF NOT EXISTS " finra-tba--table " (
       date TEXT, product TEXT, agency TEXT, settlement TEXT, settlement_month TEXT, coupon TEXT, coupon_rate REAL,
       average_price REAL, weighted_average_price REAL, bottom_5_average_price REAL, quartile_2_price REAL, quartile_3_price REAL,
       quartile_4_price REAL, top_5_average_price REAL, standard_deviation REAL, volume_thousands REAL, trades REAL,
       PRIMARY KEY (date, product, agency, settlement, coupon))")))

(define (finra-tba--settlement-month text report-date)
  "The first day of the month that a settlement (\"November Settlement\") is in, for a report date: the month, in the report date's year, or in the next
year if the month has already gone by in this one (a December report date of a January settlement)."
  (let ((found (position (string-downcase (car (string-split text " "))) finra-tba--months)))
    (if found
        (let ((month (+ found 1)))
          (date (+ (date-year report-date) (if (< month (date-month report-date)) 1 0)) month 1))
        (error "finra-tba-update: FINRA's settlement" text "doesn't begin with a month"))))

(define (finra-tba--coupon-number text)
  "The number in a coupon bucket: 3.5 in \"<= 3.5\", 6 in \"> 6\", 5.5 in \"5.5\"."
  (string->number (string-trim (string-replace (string-replace text "<=" "") ">" ""))))

(define (finra-tba--database-columns prices)
  "FINRA's table of prices, with the columns the database has: settlement_month and coupon_rate added, the statistics renamed, and the rows with no
trades taken out."
  (let* ((dates (vector->list (table-column prices "date")))
         (settlements (vector->list (table-column prices "settlement")))
         (coupons (vector->list (table-column prices "coupon")))
         (with-months (table-add-columns prices
                        (list (cons "settlement_month" (list->vector (map finra-tba--settlement-month settlements dates)))
                              (cons "coupon_rate" (list->vector (map finra-tba--coupon-number coupons))))))
         (traded (table-filter with-months (vector> (table-column with-months "number of trades") 0)))
         (named (reduce (lambda (t pair) (table-rename-column t (car pair) (cdr pair))) finra-tba--statistics traded)))
    (table-select named (append '("date" "product" "agency" "settlement" "settlement_month" "coupon" "coupon_rate")
                                (map cdr finra-tba--statistics)))))

(define (finra-tba--no-prices? message)
  "Is this FINRA's answer that it has no prices for the dates (a holiday week, or before its history starts)?"
  (string-search message "has no prices"))

(define (finra-tba--update-range conn creds from to)
  "Replaces the database's rows from the day from to the day to with FINRA's. Returns how many rows are there now."
  (let ((prices (catch-error (finra-tba-prices creds :start-date from :end-date to) (message)
                  (if (finra-tba--no-prices? message) '() (error message)))))
    (if (null? prices)
        0
        (let ((rows (finra-tba--database-columns prices)))
          (sqlite-execute conn (string-append "DELETE FROM " finra-tba--table " WHERE date >= ? AND date <= ?")
                          (list (date->string from) (date->string to)))
          (sqlite-write-table conn finra-tba--table rows 'append)))))

(define (finra-tba--months-between from to)
  "The months from the day from to the day to, as a list of (first-day . last-day), the first and last of them cut at from and to."
  (let loop ((start from) (months '()))
    (if (> start to)
        (reverse months)
        (let ((end (min (date-end-of-month start) to)))
          (loop (date-add-days end 1) (cons (cons start end) months))))))

(define (finra-tba-update creds db-path &key (start-date '()) (end-date '()))
  "Brings the database at db-path up to date with FINRA's TBA prices, and returns a table of what it has now: the rows and the days for each agency.
It makes the database if there isn't one, and asks FINRA, a month at a time, for the days from :start-date (a week before the last day it has, or ten years ago
if it is empty) to :end-date (today)."
  (with-sqlite (conn db-path)
    (finra-tba--create-table conn)
    (let* ((last (vector-ref (cdr (car (sqlite-query conn (string-append "SELECT MAX(date) AS last FROM " finra-tba--table)))) 0))
           (today (today))
           (to (if (null? end-date) today (if (string? end-date) (string->date end-date) end-date)))
           (from (cond ((not (null? start-date)) (if (string? start-date) (string->date start-date) start-date))
                       ((date? last) (date-add-days last -7))
                       (else (date-add-years today (- finra-database-years))))))
      (for-each (lambda (month)
                  (display "FINRA TBA prices, ") (display (car month)) (display " to ") (display (cdr month)) (newline)
                  (finra-tba--update-range conn creds (car month) (cdr month)))
                (finra-tba--months-between from to))
      (finra-tba--summarize conn))))

(define (finra-tba--summarize conn)
  (sqlite-query conn
    (string-append "SELECT agency, product, COUNT(*) AS rows, MIN(date) AS first_day, MAX(date) AS last_day FROM " finra-tba--table
                   " GROUP BY agency, product ORDER BY agency, product")))

(define (finra-tba-summary db-path)
  "A table of what the database at db-path has: for each agency and product, its rows, its first day and its last."
  (with-sqlite (conn db-path)
    (finra-tba--summarize conn)))
