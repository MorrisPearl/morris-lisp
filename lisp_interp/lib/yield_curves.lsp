; yield_curves.lsp
;
; The yield curve of US Treasuries, from two free sources, and what can be
; worked out from it: the zero curve and the forward rates that a model of
; interest rates starts from.
;
;   The Treasury's par yield curve (treasury-par-curve). Every business day
;   since 1990, the Treasury publishes the yields of notes and bills at 1
;   month to 30 years (a few more were added, and a few dropped, over the
;   years). It is official, and is out the same day.
;
;   The Federal Reserve's fitted curve (gsw-curve), by Gurkaynak, Sack, and
;   Wright. Every day since 1961, the Fed's staff fits one smooth curve, a
;   Svensson curve of six numbers, to the prices of all the Treasuries, and
;   publishes the six numbers and the zero, par, and forward rates it gives
;   at every maturity from 1 to 30 years. It has the long history, and is
;   smooth; it is a research product, and lags a few days.
;
; THE WORDS. A bond that pays a coupon every six months is a par bond if it
; is worth its face value: its coupon is then its par yield, which is what
; the Treasury publishes, as a rate for a year. A zero-coupon bond pays only
; at its end: for one that pays 1 at t years, what it costs now is its discount
; factor D(t), and the rate it earns, D(t) = exp(-z t), is the zero rate z (here
; the continuously compounded one, as the Fed's). The rate for a period between
; two dates, agreed now, is a forward rate: money kept from t1 to t2 grows by
; D(t1) / D(t2). A zero rate is an average of the forward rates before it.
;
; BOOTSTRAPPING. The par yields are not zero rates, but give them. A par bond
; of 6 months is worth 1 with a coupon at the end: that gives D(0.5). A par bond
; of a year has a coupon at 6 months, which D(0.5) values, and the face and a
; coupon at a year: that gives D(1) -- and so on, a step of 6 months at a time,
; each discount factor found from those before it (par-curve-zeros). The par
; yield at a step the Treasury doesn't publish, as at 4 years, is on a smooth
; curve through the ones it does (interpolate :smooth #t, which never rises
; above or falls below the points it joins): with straight lines between them,
; the forward rates that come out jump where the lines meet.
;
; Usage:
;   (no load is needed: the functions load this file when first used)
;   (define curve (treasury-par-curve))                  ; this year, to date: a row for each day
;   (table-column curve "10y")                           ; the 10-year yield, as 0.0429
;   (define zeros (treasury-zero-curve curve))           ; the latest day's zero curve
;   (define forwards (curve-forward-rates zeros))        ; 360 months of forward rates, for a model
;
;   (define fed (gsw-curve :start-date (date 2026 1 1)))
;   (curve-forward-rates (gsw-zero-curve fed))           ; the same, from the Fed's curve

; ---------------------------------------------------------------------------
; 1. The Treasury's par yield curve
; ---------------------------------------------------------------------------

; The Treasury's columns: its heading, the name here, and the maturity in months.
(define treasury-tenors
  '(("1 Mo" "1m" 1) ("1.5 Month" "1.5m" 1.5) ("2 Mo" "2m" 2) ("3 Mo" "3m" 3) ("4 Mo" "4m" 4) ("6 Mo" "6m" 6)
    ("1 Yr" "1y" 12) ("2 Yr" "2y" 24) ("3 Yr" "3y" 36) ("5 Yr" "5y" 60) ("7 Yr" "7y" 84) ("10 Yr" "10y" 120)
    ("20 Yr" "20y" 240) ("30 Yr" "30y" 360)))

(define (yield-curves--day day fallback)
  "A date, from a date or YYYY-MM-DD text, or the fallback if there is none."
  (cond ((null? day) fallback)
        ((string? day) (string->date day))
        (else day)))

(define (treasury-par-curve--url year)
  (string-append "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                 (number->string year) "/all?type=daily_treasury_yield_curve&field_tdr_date_value="
                 (number->string year) "&page&_format=csv"))

(define (treasury-par-curve--year year cache-hours)
  "One year's file of the Treasury's, as a table: a date column, and a column for each of the treasury-tenors, as a
decimal (0.043, where the Treasury has 4.3), nan where the file has no such maturity: a year's file has only the
maturities the Treasury published then."
  (let* ((file (http-get-csv (treasury-par-curve--url year) #t cache-hours))
         (headings (table-column-names file))
         (days (table-row-count file)))
    (cons (cons "date" (table-column file "Date"))
          (map (lambda (tenor)
                 (cons (second tenor)
                       (if (member (first tenor) headings)
                           (/ (table-column file (first tenor)) 100)
                           (make-vector days nan))))
               treasury-tenors))))

(define (treasury-par-curve &key (start-date '()) (end-date '()) (cache-hours 12))
  "The Treasury's daily par yield curve, as a table, the oldest day first: a date column, and a column for each
maturity -- 1m, 1.5m, 2m, 3m, 4m, 6m, 1y, 2y, 3y, 5y, 7y, 10y, 20y, and 30y -- of the yield as a decimal (0.043 is
4.3%), nan on a day when the Treasury published none for a maturity (it has not always published every one). From
:start-date to :end-date (a date, or YYYY-MM-DD text); by default, the start of the year of the end date to the end
date, today by default: this year so far. The Treasury's curve begins in 1990. Each year is a download, kept for
:cache-hours (12)."
  (let* ((last-day (yield-curves--day end-date (today)))
         (first-day (yield-curves--day start-date (date (date-year last-day) 1 1))))
    (when (> first-day last-day)
      (error "treasury-par-curve: :start-date is after :end-date"))
    (when (< (date-year first-day) 1990)
      (error "treasury-par-curve: the Treasury's curve begins in 1990, not" (date->string first-day)))
    (let* ((years (loop for year from (date-year first-day) to (date-year last-day)
                        collect (treasury-par-curve--year year cache-hours)))
           (all (apply table-append years))
           (dates (table-column all "date")))
      (table-sort (table-filter all (vector-and (>= dates first-day) (<= dates last-day))) "date"))))

(define (latest-treasury-points &key (cache-hours 1))
  "The Treasury's most recent par yield curve, as (day points): the last day of its file that has a yield, and the points, (years yield), of the maturities that it
has one for, the yield in percent, in the form of a Treasury curve of a deal (see deal-set-treasury-curve!). The file is the one that treasury-par-curve reads, kept
for :cache-hours (1). An error if the Treasury has published no yield in the last two weeks."
  (let* ((today-date (today))
         (curve (treasury-par-curve :start-date (date-add-days today-date -14) :end-date today-date :cache-hours cache-hours))
         (days (table-row-count curve)))
    (loop for row from (- days 1) downto 0
          do (let ((points (loop for tenor in treasury-tenors
                                 for yield = (vector-ref (table-column curve (cadr tenor)) row)
                                 when (= yield yield)
                                 collect (list (/ (caddr tenor) 12.0) (* 100.0 yield)))))
               (unless (null? points)
                 (return (list (vector-ref (table-column curve "date") row) points)))))))

; ---------------------------------------------------------------------------
; 2. From par yields to zero rates, and forward rates
; ---------------------------------------------------------------------------

(define (par-curve-zeros years yields)
  "The zero curve that par yields give, as a table. years are the maturities, rising, and yields the par yield
at each, as decimals; a maturity with a yield that is missing (nan) is left out. The table has a row for each
maturity of less than six months, and for every six months to the last maturity, with the columns:
  years     the maturity
  par       the par yield: the one given, or on a smooth curve through the ones given (and flat, beyond them)
  discount  what 1 paid at that maturity is worth now
  zero      the rate it earns: the continuously compounded zero rate, -ln(discount) / years
A bill of less than six months is priced as 1 / (1 + yield * years), as its yield is quoted. From six months on,
the yield is that of a par bond with a coupon every six months, so that bond's price is 1: each discount factor
is (1 less the coupons before it, of half the par yield each, at their discount factors) over (1 plus half the par
yield), for the coupon and face at the end."
  (let* ((present (vector-not (vector-nan? yields)))
         (years (vector-select years present))
         (yields (vector-select yields present)))
    (when (= (vector-length years) 0)
      (error "par-curve-zeros: there is no par yield"))
    (let* ((bill-years (vector-select years (< years 0.5)))
           (bill-discounts (/ 1 (+ 1 (* (vector-select yields (< years 0.5)) bill-years))))
           (periods (max 1 (ceiling (* 2 (vector-max years)))))
           (grid (* 0.5 (+ 1 (vector-range periods))))
           (grid-yields (interpolate grid years yields :smooth #t))
           (grid-discounts '())
           (coupons-worth 0.0))                      ; the discount factors of the coupons before this one, added up
      (loop for step from 0 below periods
            do (let* ((coupon (/ (vector-ref grid-yields step) 2))
                      (discount (/ (- 1 (* coupon coupons-worth)) (+ 1 coupon))))
                 (push discount grid-discounts)
                 (set! coupons-worth (+ coupons-worth discount))))
      (let* ((all-years (vector-append bill-years grid))
             (all-yields (vector-append (vector-select yields (< years 0.5)) grid-yields))
             (all-discounts (vector-append bill-discounts (list->vector (reverse grid-discounts)))))
        (make-table "years" all-years
                    "par" all-yields
                    "discount" all-discounts
                    "zero" (/ (- (log all-discounts)) all-years))))))

(define (curve-forward-rates zero-curve &key (months 360))
  "The one-month forward rates of a zero curve, as a table, for each of :months (360, thirty years): a row for each,
with the columns
  months    1, 2, ... : the forward rate is for the month that ends then
  discount  what 1 paid at the end of that month is worth now
  forward   the rate for that month, as a rate for a year with monthly interest: a month's money grows by
            (1 + forward / 12), so discount[month - 1] / discount[month] = 1 + forward / 12
This table is what a curve of forward rates is everywhere: sofr-forward-curve makes the same one, and the paths of
rates (simulate-rate-paths and the others) take it, or its forward column.
zero-curve is a table with columns years and zero, such as treasury-zero-curve and gsw-zero-curve make: the zero
rate of each month is on a smooth curve through those given (and flat beyond them)."
  (let* ((month-numbers (+ 1 (vector-range months)))
         (years (/ month-numbers 12.0))
         (zeros (interpolate years (table-column zero-curve "years") (table-column zero-curve "zero") :smooth #t))
         (discounts (exp (- (* zeros years))))
         (earlier (vector-append (vector 1.0) (vector-take discounts (- months 1)))))
    (make-table "months" month-numbers
                "discount" discounts
                "forward" (* 12 (- (/ earlier discounts) 1)))))

(define (yield-curves--forwards curve who)
  "The forward rates of a curve, as a vector: the curve's forward column, if it is a table as curve-forward-rates makes,
or the curve itself, if it is a vector of them."
  (cond ((vector? curve) curve)
        ((and (table? curve) (assoc "forward" curve)) (table-column curve "forward"))
        (else (error (format "{}: a curve of forward rates is a table with a forward column, as curve-forward-rates makes, or a vector of the rates" who)))))

(define (forward-rates-table forwards)
  "A vector of monthly forward rates as the table curve-forward-rates makes: months, discount and forward."
  (let ((months (vector-length forwards)))
    (make-table "months" (+ 1 (vector-range months))
                "discount" (exp (vector-cumsum (- (log (+ 1 (/ forwards 12))))))
                "forward" forwards)))

(define (extend-forward-curve forwards real-months longer-forwards &key (blend-months 12))
  "The forward rates of a curve that is only known to real-months -- the SOFR futures' curve, say, which is flat
beyond the last futures contract -- carried on by the forward rates of a longer curve. forwards and longer-forwards
are curves of one-month forward rates, as long as each other: tables as curve-forward-rates and sofr-forward-curve make,
or vectors of the rates. The result is forwards for the first real-months, then a straight-line change over
:blend-months (12) to longer-forwards, so that there is no jump where they meet, and longer-forwards from then on: a
table like curve-forward-rates's if forwards is one, and otherwise a vector."
  (let ((short (yield-curves--forwards forwards "extend-forward-curve"))
        (long (yield-curves--forwards longer-forwards "extend-forward-curve")))
    (unless (= (vector-length short) (vector-length long))
      (error (format "extend-forward-curve: forwards has {} months and longer-forwards {}: they must be as long as each other"
                     (vector-length short) (vector-length long))))
    (unless (and (number? blend-months) (> blend-months 0))
      (error "extend-forward-curve: :blend-months is a number of months above 0, not" blend-months))
    (let* ((weights (vector-clip (/ (- (vector-range (vector-length short)) real-months) (* 1.0 blend-months)) 0 1))
           (both (+ (* (- 1 weights) short) (* weights long))))
      (if (vector? forwards) both (forward-rates-table both)))))

(define (yield-curves--row-on curve day)
  "The last row of the table (as the Treasury's, or the Fed's, oldest day first) that is on or before the day, as a
one-row table; the latest, if there is no day."
  (let* ((dates (table-column curve "date"))
         (found (if (null? day) curve (table-filter curve (<= dates (yield-curves--day day '()))))))
    (when (= (table-row-count found) 0)
      (error (format "yield-curves: the curve has no day on or before {}" (date->string (yield-curves--day day '())))))
    (table-where found "date" (vector-max (table-column found "date")))))

(define (treasury-zero-curve curve &key (date '()))
  "The zero curve of the Treasury's par yield curve on a day, as par-curve-zeros makes it. curve is a table as
treasury-par-curve makes; the day is the last in it that is on or before :date (a date, or YYYY-MM-DD text), the
latest, if none is given."
  (let ((row (yield-curves--row-on curve date)))
    (par-curve-zeros (list->vector (map (lambda (tenor) (/ (third tenor) 12.0)) treasury-tenors))
                     (list->vector (map (lambda (tenor) (vector-ref (table-column row (second tenor)) 0))
                                        treasury-tenors)))))

; ---------------------------------------------------------------------------
; 3. The Federal Reserve's fitted curve
; ---------------------------------------------------------------------------

(define gsw-url "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv")

(define (gsw-curve--name heading)
  "The name here of a column of the Fed's file: BETA0 is beta0, TAU1 tau1; SVENY05 is zero-5, the zero rate at 5
years; SVENPY05 par-5; SVENF05 forward-5, the instantaneous forward rate; and SVEN1F04 year-forward-4, the
rate for the year that starts in 4 years."
  (let ((number-in (lambda (pattern)
                     (let ((found (regex-match pattern heading)))
                       (if found (number->string (string->number (second found))) #f)))))
    (cond ((equal? heading "Date") "date")
          ((regex-match "BETA\\d|TAU\\d" heading) (string-downcase heading))
          ((number-in "SVENY(\\d+)") (string-append "zero-" (number-in "SVENY(\\d+)")))
          ((number-in "SVENPY(\\d+)") (string-append "par-" (number-in "SVENPY(\\d+)")))
          ((number-in "SVENF(\\d+)") (string-append "forward-" (number-in "SVENF(\\d+)")))
          ((number-in "SVEN1F(\\d+)") (string-append "year-forward-" (number-in "SVEN1F(\\d+)")))
          (else heading))))

(define (gsw-curve &key (start-date '()) (end-date '()) (cache-hours 12))
  "The Federal Reserve's fitted Treasury curve (Gurkaynak, Sack, and Wright), as a table, the oldest day first, from
:start-date to :end-date (a date, or YYYY-MM-DD text; all of it, if they are not given: it begins in 1961). The
columns are the date; beta0, beta1, beta2, beta3, tau1, and tau2, which are the six numbers of the Svensson curve
(see svensson-zero-rates; the betas are decimals, the taus years); and, for each whole number of years from 1 to
30, what the curve gives there, as decimals: zero-1 ... zero-30 (the zero rate, continuously compounded), par-1
... par-30 (the par yield, as the Treasury publishes it), and forward-1 ... forward-30 (the instantaneous forward
rate, continuously compounded), and year-forward-1, -4, and -9 (the rate for a year, that starts that many years
ahead). nan where the Fed gives none: the curve did not reach 30 years until the 1980s. It is a research product,
not an official release: it lags by a few days, and can be revised. The file is one download of the whole history
(6 MB), kept for :cache-hours (12)."
  (let* ((file (http-get-csv gsw-url #t cache-hours :skip "Date" :missing "NA"))
         (columns (map (lambda (column)
                         (let ((name (gsw-curve--name (car column))))
                           (cons name (if (or (equal? name "date") (regex-match "tau\\d" name))
                                          (cdr column)
                                          (/ (cdr column) 100)))))
                       file))
         (dates (table-column columns "date"))
         (first-day (yield-curves--day start-date (vector-min dates)))
         (last-day (yield-curves--day end-date (vector-max dates))))
    (table-filter columns (vector-and (>= dates first-day) (<= dates last-day)))))

(define (gsw-parameters curve &key (date '()))
  "The six numbers of the Svensson curve on a day, as a list (beta0 beta1 beta2 beta3 tau1 tau2): from the last day
in the table (as gsw-curve makes it) that is on or before :date, the latest, if none is given."
  (let ((row (yield-curves--row-on curve date)))
    (map (lambda (name) (vector-ref (table-column row name) 0))
         '("beta0" "beta1" "beta2" "beta3" "tau1" "tau2"))))

(define (svensson-zero-rates parameters years)
  "The zero rates of a Svensson curve, at these maturities (a vector, or a number), in years. parameters is the
list (beta0 beta1 beta2 beta3 tau1 tau2), as gsw-parameters gives it. The curve is
  z(t) = beta0 + beta1 s(t / tau1) + beta2 (s(t / tau1) - e^(-t / tau1)) + beta3 (s(t / tau2) - e^(-t / tau2)),
  where s(x) = (1 - e^(-x)) / x;
beta0 is the rate for the longest maturities, beta0 + beta1 the rate for the shortest, and the others add a hump, and
a second one, where the taus say."
  (destructuring-bind (beta0 beta1 beta2 beta3 tau1 tau2) parameters
    (let* ((x1 (/ years tau1))
           (x2 (/ years tau2))
           (decay1 (exp (- x1)))
           (decay2 (exp (- x2)))
           (slope1 (/ (- 1 decay1) x1))
           (slope2 (/ (- 1 decay2) x2)))
      (+ beta0 (* beta1 slope1) (* beta2 (- slope1 decay1)) (* beta3 (- slope2 decay2))))))

(define (svensson-forward-rates parameters years)
  "The instantaneous forward rates of a Svensson curve, at these maturities (a vector, or a number), in years:
  f(t) = beta0 + beta1 e^(-t / tau1) + beta2 (t / tau1) e^(-t / tau1) + beta3 (t / tau2) e^(-t / tau2)
-- the rate for the next instant, t years ahead, which the zero rate averages from now to then. parameters is
as for svensson-zero-rates."
  (destructuring-bind (beta0 beta1 beta2 beta3 tau1 tau2) parameters
    (let* ((x1 (/ years tau1))
           (x2 (/ years tau2)))
      (+ beta0 (* beta1 (exp (- x1))) (* beta2 x1 (exp (- x1))) (* beta3 x2 (exp (- x2)))))))

(define (gsw-zero-curve curve &key (date '()) (months 360))
  "The Fed's zero curve on a day, as a table of years and zero for each month to :months (360), for
curve-forward-rates: svensson-zero-rates of that day's parameters. curve is a table as gsw-curve makes it; the day
is the last in it on or before :date, the latest, if none is given."
  (let ((years (/ (+ 1 (vector-range months)) 12.0)))
    (make-table "years" years
                "zero" (svensson-zero-rates (gsw-parameters curve :date date) years))))
