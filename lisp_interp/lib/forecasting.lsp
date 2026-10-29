; forecasting.lsp
;
; Tools for forecasting questions of the kind asked on Good Judgment Open
; (gjopen.com) and the prediction markets: "Will X happen before a date?",
; and "In which of these ranges will the number be?". See
; lisp_forecasting_manual.md.
;
; RANGES. A question about a number -- the CPI, the unemployment rate, the
; S&P 500 at the end of the year -- offers ranges of it, called bins. The
; bins are given here by their edges: edges (2.0 2.5 3.0) make four bins,
; below 2.0, from 2.0 to 2.5, from 2.5 to 3.0, and 3.0 or more. Each of the
; ...-bins functions answers with a list of four chances, one for each bin,
; that add up to 1, worked out from a distribution of the number:
;
;   normal-bins       a forecast and how far off such forecasts usually are
;   lognormal-bins    a price today and its volatility, as an option prices it
;   empirical-bins    a forecast and a list of how far off past forecasts were
;   call-price-bins   the prices of call options at several strikes
;   bin-probabilities any distribution, given as a function
;
; "BEFORE A DATE". If a thing has a 30% chance of happening in the next six
; months, and nothing changes but the calendar, it has less of a chance in
; the three months that are left after three quiet months: about 16%.
; probability-remaining works that out, and decay-schedule makes the table
; of what to forecast each week.
;
; COMBINING AND SCORING. combine-forecasts averages forecasts made different
; ways, extremize makes a forecast bolder, brier-score and
; ordered-brier-score score one the way Good Judgment Open does, and
; calibration-table checks a record of past forecasts.
;
; Usage:
;   (lognormal-bins '(6000 6500 7000) 6700 0.16 0.25)    ; the S&P 500 in 3 months
;   (bin-table '(6000 6500 7000) (lognormal-bins '(6000 6500 7000) 6700 0.16 0.25))
;   (probability-remaining 0.30 182 91)                  ; => 0.163...
;   (brier-score '(0.7 0.2 0.1) 0)                       ; => 0.14

; ---------------------------------------------------------------------------
; 1. The chance of each bin
; ---------------------------------------------------------------------------

(define (bin-probabilities edges cdf)
  "The chance of each bin that the edges make, from the distribution's cdf: (cdf x) is the chance that the number
is below x. There is one more bin than there are edges: below the first edge, between each two, and at or above
the last."
  (let ((below (append (list 0) (map cdf edges) (list 1))))  ; the chance of being below each edge, and the ends
    (let loop ((rest below) (chances '()))
      (if (null? (cdr rest))
          (reverse chances)
          (loop (cdr rest) (cons (max 0 (- (cadr rest) (car rest))) chances))))))

(define (normal-bins edges mean stdev)
  "The chance of each bin if the number is normally distributed: a forecast (mean) that is off by stdev, as a
rule. For a figure such as the CPI: the consensus forecast, and the standard deviation of past surprises."
  (bin-probabilities edges (lambda (x) (normal-cdf (/ (- x mean) stdev)))))

(define (lognormal-bins edges price volatility years &key (rate 0))
  "The chance of each bin for a price years from now, if it moves as option prices assume it does: lognormally,
with the given volatility (0.16 for 16% a year), and expected to grow at rate (an interest rate less a dividend
yield; 0 is near enough for a few months). The volatility to use is the implied volatility of options that expire
near the date the question is decided."
  (let ((forward (* price (exp (* rate years))))
        (spread (* volatility (sqrt years))))
    (bin-probabilities edges
                       (lambda (x) (normal-cdf (/ (+ (log (/ x forward)) (/ (* spread spread) 2)) spread))))))

(define (empirical-bins edges center errors)
  "The chance of each bin if the number is center plus one of the past errors, each as likely as the others: the
errors are how far the actual numbers were from the forecasts before them (actual minus forecast), so their
spread and lopsidedness are used just as they were, with no normal curve assumed."
  (let ((outcomes (map (lambda (e) (+ center e)) errors))
        (n (length errors)))
    (bin-probabilities edges
                       (lambda (x) (/ (length (filter (lambda (y) (< y x)) outcomes)) n)))))

(define (forecasting--slope-at x xs ys)
  "The slope of the line through the points (xs, ys) at x: each slope between two points is put at the point
halfway between them, and the slopes at those halfway points are joined by straight lines."
  (let* ((n (length xs))
         (middles (map (lambda (i) (/ (+ (list-ref xs i) (list-ref xs (+ i 1))) 2)) (iota (- n 1))))
         (slopes (map (lambda (i) (/ (- (list-ref ys (+ i 1)) (list-ref ys i))
                                     (- (list-ref xs (+ i 1)) (list-ref xs i))))
                      (iota (- n 1)))))
    (interpolate x (list->vector middles) (list->vector slopes))))

(define (call-price-bins edges strikes call-prices &key (discount 1))
  "The chance of each bin for a price on the day options expire, from the prices of calls on it at several
strikes (rising), as the market sees it. A call at strike K pays the amount the price ends above K, so as K rises
by a dollar the call loses a dollar times the chance that the price ends above K: the chance is the slope of the
call prices, less the discount for the time until they are paid (discount, such as 0.99 for 1% interest). Use
the middle of the bid and ask, and strikes close together around the edges."
  (bin-probabilities edges
                     (lambda (x)
                       (let ((above (- (/ (forecasting--slope-at x strikes call-prices) discount))))
                         (- 1 (min 1 (max 0 above)))))))

(define (forecasting--number-text x)
  "A number as short text: 2.5, 6000, and 0.25 rather than 0.2500."
  (if (= x (round x)) (number->string (round x)) (number->string x)))

(define (bin-table edges chances)
  "The bins and their chances as a table, for looking at: a label for each bin, and its chance in percent."
  (let* ((texts (map forecasting--number-text edges))
         (n (length edges))
         (labels (map (lambda (i)
                        (cond ((= i 0) (string-append "below " (list-ref texts 0)))
                              ((= i n) (string-append (list-ref texts (- n 1)) " or more"))
                              (else (string-append (list-ref texts (- i 1)) " to " (list-ref texts i)))))
                      (iota (+ n 1)))))
    (make-table "bin" (list->vector labels)
                "percent" (list->vector (map (lambda (p) (/ (round (* p 1000)) 10)) chances)))))

; ---------------------------------------------------------------------------
; 2. "Will it happen before the date?"
; ---------------------------------------------------------------------------

(define (probability-remaining chance days-total days-left)
  "The chance that a thing happens in the days-left days still to go, if it had the given chance of happening
in all days-total days and is as likely on any day as on any other. A 30% chance over 182 days is a 16% chance
over the last 91 of them: (probability-remaining 0.3 182 91)."
  (- 1 (expt (- 1 chance) (/ days-left days-total))))

(define (decay-schedule chance start-date end-date &key (every 7))
  "What to forecast each week (or every so many days) from start-date until end-date, if the thing has the given
chance of happening in that time, and it hasn't happened yet: a table of the date, the days left, and the chance
in percent. Forecast it on each date while nothing else changes."
  (let* ((days-total (days-between start-date end-date))
         (offsets (filter (lambda (d) (< d days-total)) (map (lambda (i) (* i every)) (iota (+ 1 (quotient days-total every)))))))
    (make-table "date" (list->vector (map (lambda (d) (date-add-days start-date d)) offsets))
                "days left" (list->vector (map (lambda (d) (- days-total d)) offsets))
                "percent" (list->vector (map (lambda (d)
                                               (/ (round (* 1000 (probability-remaining chance days-total (- days-total d)))) 10))
                                             offsets)))))

; ---------------------------------------------------------------------------
; 3. Combining forecasts
; ---------------------------------------------------------------------------

(define (combine-forecasts forecasts &key (weights '()))
  "The average of several forecasts of the same question, each a list of chances, one for each answer: weighted
by weights, if given, which need not add up to 1. Forecasts made different ways -- from a base rate, from a
market, from a model -- are each wrong in their own ways, and their average is usually better than any one."
  (let* ((weights (if (null? weights) (map (lambda (f) 1) forecasts) weights))
         (total (apply + weights)))
    (apply map
           (lambda chances (/ (apply + (map * weights chances)) total))
           forecasts)))

(define (extremize chances power)
  "The forecast made bolder (power above 1) or more timid (power below 1): each chance is raised to the power,
and then they are scaled to add up to 1 again. An average of forecasts by people who each know part of the
story is usually too timid; a power of 1.5 to 2.5 is the usual correction. Of two answers, (extremize '(0.7 0.3)
2) makes 0.7 into 0.84."
  (let* ((raised (map (lambda (p) (expt p power)) chances))
         (total (apply + raised)))
    (map (lambda (p) (/ p total)) raised)))

; ---------------------------------------------------------------------------
; 4. Scoring
; ---------------------------------------------------------------------------

(define (brier-score chances outcome)
  "The Brier score of a forecast: chances has one for each answer, and outcome is the number of the answer that
happened (0 for the first). It is the sum, over the answers, of the square of how far each chance was from what
happened (1 for the answer that did, 0 for the others): 0 is perfect, 2 is as wrong as can be, and a forecast
of 50% on a yes-or-no question scores 0.5. Lower is better."
  (apply + (map (lambda (p i) (let ((miss (- p (if (= i outcome) 1 0)))) (* miss miss)))
                chances
                (iota (length chances)))))

(define (ordered-brier-score chances outcome)
  "The Brier score for answers that are bins in order, as Good Judgment Open scores them: at each place between
two bins, the bins are split into those below and those above, and the forecast is scored as the yes-or-no
question of which side the number is on; the score is the average of those. A forecast that puts its chance in
the bin next to the right one scores better than one that puts it far away, as the plain Brier score doesn't."
  (let ((n (length chances)))
    (/ (apply + (map (lambda (cut)
                       (let ((below (apply + (map (lambda (i) (list-ref chances i)) (iota cut)))))
                         (brier-score (list below (- 1 below)) (if (< outcome cut) 0 1))))
                     (cdr (iota n))))
       (- n 1))))

(define (calibration-table chances outcomes &key (bins 10))
  "How well calibrated a record of yes-or-no forecasts is: chances are the chances given for yes, and outcomes are
1 where it happened and 0 where it didn't. The forecasts are put in bins by their chance (0 to 10%, 10 to 20%,
...), and for each bin with any forecasts the table has the number of them, their average chance in percent, and
the percent that happened. Well calibrated, the last two are close."
  (let ((rows '()))
    (do ((b 0 (+ b 1)))
        ((= b bins))
      (let* ((low (/ b bins))
             (high (/ (+ b 1) bins))
             (in-bin (filter (lambda (i)
                               (let ((p (list-ref chances i)))
                                 (and (>= p low) (or (< p high) (= b (- bins 1))))))
                             (iota (length chances))))
             (n (length in-bin)))
        (if (> n 0)
            (set! rows (cons (list (string-append (forecasting--number-text (* 100 low)) " to "
                                                  (forecasting--number-text (* 100 high)) "%")
                                   n
                                   (/ (round (* 1000 (/ (apply + (map (lambda (i) (list-ref chances i)) in-bin)) n))) 10)
                                   (/ (round (* 1000 (/ (apply + (map (lambda (i) (list-ref outcomes i)) in-bin)) n))) 10))
                             rows)))))
    (table-from-rows (reverse rows) (list "forecast" "count" "average forecast" "percent happened"))))
