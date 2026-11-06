; macro_models.lsp
; ================
; Small models of the US economy, solved and estimated by Dynare (dynare-run): what happens to GDP, inflation, wages and the Fed's rate,
; quarter by quarter, after a surprise such as a jump in the price of oil. doc/lisp_macro_models_manual.md explains them.
;
;   (oil-model)                                       the oil model with its parameters as chosen by hand (calibrated)
;   (oil-model :parameters '((wage_rigidity . 0.9)))  ... with some of them changed: a scenario
;   (oil-model-estimate creds)                        its parameters estimated from US data, 1985 to 2008 (some minutes)
;   (oil-model :from estimate :parameters '(...))     a scenario that starts from the estimated parameters
;   (oil-shock-responses result :rise 10)             a table: what happens when the price of oil rises 10%
;   (plot-oil-shock result :rise 10)                  the same as charts; or several results, labeled, to compare them
;   (show-oil-estimates estimate)                     what the data say about each parameter
;
; The model itself is in dynare/oil_model.inc, with oil_irfs.mod (responses, for given parameters) and oil_estimate.mod (estimation).

; The model's shocks: Dynare's name, the parameter that holds its typical size in oil_irfs.mod, and what it is.
(define oil-model-shocks
  '(("oil_price_shock"    "oil_price_shock_size"    "oil price")
    ("productivity_shock" "productivity_shock_size" "productivity")
    ("demand_shock"       "demand_shock_size"       "demand")
    ("fed_shock"          "fed_shock_size"          "Fed rate (monetary policy)")
    ("cost_push_shock"    "cost_push_shock_size"    "cost-push (firms' markups)")
    ("wage_shock"         "wage_shock_size"         "wages (workers' bargaining power)")))

; The variables shown: the model's name, the name shown, and what to multiply by. Inflation and the Fed's rate are per quarter in the
; model, and shown per year (times 4), as they are reported; the others are percent differences from normal.
(define oil-model-variables
  '(("gdp"                "GDP"                1)
    ("consumption"        "consumption"        1)
    ("hours"              "hours"              1)
    ("real_wage"          "real wage"          1)
    ("headline_inflation" "headline inflation" 4)
    ("core_inflation"     "core inflation"     4)
    ("fed_rate"           "Fed rate"           4)
    ("real_oil_price"     "real oil price"     1)))

; What each parameter is, for show-oil-estimates.
(define oil-model-parameter-descriptions
  '(("price_stickiness"                "chance a firm can't change its price in a quarter")
    ("wage_rigidity"                   "real wage rigidity (0: wages adjust at once)")
    ("risk_aversion"                   "dislike of uneven consumption")
    ("labor_dislike"                   "how fast the wish not to work grows with hours")
    ("fed_inflation_response"          "Fed: rate rise for a point of inflation")
    ("fed_gdp_response"                "Fed: rate rise for a percent of GDP above normal")
    ("fed_smoothing"                   "Fed: how slowly it moves its rate")
    ("core_weight"                     "Fed: weight on core inflation (rest: headline)")
    ("productivity_persistence"        "how long a productivity change lasts")
    ("demand_persistence"              "how long a demand change lasts")
    ("oil_price_persistence"           "how long an oil price change lasts")
    ("stderr oil_price_shock"          "typical oil price surprise, percent")
    ("stderr productivity_shock"       "typical productivity surprise, percent")
    ("stderr demand_shock"             "typical demand surprise")
    ("stderr fed_shock"                "typical Fed rate surprise, points a quarter")
    ("stderr cost_push_shock"          "typical cost-push surprise")
    ("stderr wage_shock"               "typical wage surprise, percent")
    ("stderr headline_inflation_data"  "headline inflation's measurement error")))

; ---------------------------------------------------------------------------
; Running the model
; ---------------------------------------------------------------------------

(define (oil-model &key (parameters '()) (from '()) (quarters 20))
  "The oil model's responses to each kind of surprise, for quarters quarters, as dynare-run returns them. Its parameters are as
dynare/oil_model.inc chooses them, or, given :from, an estimate (from oil-model-estimate), as the estimate found them (their posterior
means); then :parameters, a list ((name . value) ...), changes any of them: '((wage_rigidity . 0.9) (core_weight . 1))."
  (dynare-run "oil_irfs.mod"
              :parameters (append (if (null? from) '() (oil-model-estimated-parameters from)) parameters)
              :macros (list (cons 'quarters quarters))))

(define (oil-model-estimated-parameters estimate)
  "The parameters an estimate found, as a list ((name . value) ...) that oil-model's :parameters takes: each one's posterior mean (or
its mode, if the estimate made no draws). A shock's size (\"stderr oil_price_shock\") becomes its parameter in oil_irfs.mod (oil_price_shock_size); the
measurement error is left out, since it is not part of the economy."
  (macro-models--estimated-parameters estimate oil-model-shocks))

(define (macro-models--estimated-parameters estimate shocks)
  "oil-model-estimated-parameters for any model: shocks is its list of (shock-name size-parameter description)."
  (let* ((estimates (hash-table-ref estimate "estimates"))
         (names (table-column estimates "name"))
         (means (table-column estimates "mean"))
         (modes (table-column estimates "mode"))
         (no-mean (vector-nan? means)))
    (loop for k from 0 below (vector-length names)
          for name = (vector-ref names k)
          for value = (if (= (vector-ref no-mean k) 1) (vector-ref modes k) (vector-ref means k))
          for shock = (find-if (lambda (entry) (equal? name (string-append "stderr " (first entry)))) shocks)
          when shock collect (cons (second shock) value)
          when (and (not shock) (not (string-starts-with? name "stderr "))) collect (cons name value))))

(define (oil-model-data creds &key (start (date 1985 1 1)) (end (date 2008 7 1)))
  "The data the oil model is estimated on, from FRED, by the quarter from start to end (the quarters' first days): GDP growth (GDPC1),
real wage growth (COMPRNFB, real compensation an hour), core and headline inflation (PCEPILFE, PCEPI), the federal funds rate (FEDFUNDS)
and the change in the real price of oil (WTISPLC, less core inflation), each in percent a quarter, less its average over these quarters
-- the model explains the ups and downs, not the averages. The default ends before the Fed's rate reached zero at the end of 2008,
which the model's Fed rule can't capture."
  (let* ((fred (fred-table creds '("GDPC1" "PCEPILFE" "PCEPI" "FEDFUNDS" "WTISPLC" "COMPRNFB") :frequency "quarterly"
                           :start-date (date-add-months start -3) :end-date end))
         (core (macro-models--growth (table-column fred "PCEPILFE")))
         (all (make-table "date"     (table-column fred "date")
                          "gdp_growth_data"   (macro-models--growth (table-column fred "GDPC1"))
                          "real_wage_growth_data"   (macro-models--growth (table-column fred "COMPRNFB"))
                          "core_inflation_data" core
                          "headline_inflation_data" (macro-models--growth (table-column fred "PCEPI"))
                          "fed_rate_data"    (vector-div (table-column fred "FEDFUNDS") 4)
                          "real_oil_price_change_data"   (vector-sub (macro-models--growth (table-column fred "WTISPLC")) core)))
         (complete (table-filter all (vector-and (vector-not (vector-nan? (table-column all "gdp_growth_data")))
                                                 (vector-not (vector-nan? (table-column all "real_wage_growth_data")))))))
    (cons (car complete)
          (map (lambda (column) (cons (car column) (vector-sub (cdr column) (vector-mean (cdr column))))) (cdr complete)))))

(define (macro-models--growth v)
  "The growth of a series from one quarter to the next, in percent (the change in its log, times 100); NaN for the first."
  (vector-mul (vector-diff (vector-log v)) 100))

(define (oil-model-estimate creds &key (start (date 1985 1 1)) (end (date 2008 7 1)) (data '()) (draws 20000) (quarters 20)
                            (echo #f))
  "The oil model's parameters estimated from US data, start to end (oil-model-data), or from the table :data: dynare-run's result for
dynare/oil_estimate.mod, with its \"estimates\" (show-oil-estimates shows them) and its \"responses\", with bands. Each of the two chains
makes draws draws; 20000 takes some minutes, and a few thousand are enough for a first look. :echo #t shows what Dynare prints as it works."
  (let ((data (if (null? data) (oil-model-data creds :start start :end end) data)))
    (display (format "Estimating the oil model on {} quarters, {} to {}, with {} draws in each of two chains; this takes some minutes."
                     (table-row-count data) (vector-ref (table-column data "date") 0)
                     (vector-ref (table-column data "date") (- (table-row-count data) 1)) draws))
    (newline)
    (dynare-run "oil_estimate.mod" :data (cdr data) :echo echo
                :macros (list (cons 'draws draws) (cons 'quarters quarters)))))

; ---------------------------------------------------------------------------
; Showing results
; ---------------------------------------------------------------------------

(define (oil-model-responses result shock)
  "How the economy responds to one typical surprise of a kind (\"demand_shock\", one of oil-model-shocks), as a table: a quarter column, then
GDP, consumption, hours and the real wage (percent from normal), headline and core inflation and the Fed's rate (percentage points a
year from normal) and the real price of oil; with a \"low\" and a \"high\" column for each, the 90% band, after an estimation."
  (macro-models--responses result shock 1 oil-model-variables))

(define (oil-shock-responses result &key (rise 10))
  "How the economy responds when the real price of oil rises rise percent in the first quarter, as oil-model-responses shows it. The
model is linear, so a rise twice as large has responses twice as large. (After an estimation, the bands are scaled by the same number,
which leaves out how unsure the estimate is of the typical size of an oil surprise.)"
  (let* ((oil (table-column (hash-table-ref (hash-table-ref result "responses") "oil_price_shock") "real_oil_price")))
    (macro-models--responses result "oil_price_shock" (/ rise (vector-ref oil 0)) oil-model-variables)))

(define (macro-models--responses result shock scale variables)
  (let* ((responses (hash-table-ref result "responses"))
         (table (if (hash-table-has? responses shock)
                    (hash-table-ref responses shock)
                    (error (format "the result has no responses to {}; it has {}" shock (hash-table-keys responses)))))
         (names (map car table)))
    (cons (assoc "quarter" table)
          (apply append
                 (map (lambda (variable)
                        (let ((factor (* scale (third variable))))
                          (map (lambda (suffix)
                                 (cons (string-append (second variable) suffix)
                                       (vector-mul (table-column table (string-append (first variable) suffix)) factor)))
                               (filter (lambda (suffix) (member (string-append (first variable) suffix) names)) '("" " low" " high")))))
                      variables)))))

(define (plot-oil-shock results &key (rise 10) (title '()))
  "Charts of what happens when the real price of oil rises rise percent: GDP, consumption, headline and core inflation, the Fed's rate
and the real wage, a panel each, with the 90% band of an estimate. results is one result (of oil-model or oil-model-estimate), or a list of
(label result), to compare them: the same shock under different parameters, say, or estimated on different years."
  (macro-models--plot results (lambda (result) (oil-shock-responses result :rise rise))
                      '(("GDP" "percent") ("consumption" "percent") ("headline inflation" "points a year")
                        ("core inflation" "points a year") ("Fed rate" "points a year") ("real wage" "percent"))
                      (if (null? title) (format "After a {}% rise in the real price of oil" rise) title)
                      "quarters (1 is the quarter of the rise)"))

(define (macro-models--plot results responses panels title x-label)
  "The charts of plot-oil-shock and plot-stock-crash: results as they take it, responses a function from a result to its table of
responses, panels a list of (variable's name, label for the axis)."
  (let* ((labeled (if (hash-table? results) (list (list "model" results)) results))
         (tables (map (lambda (entry) (responses (second entry))) labeled))
         (colors (loop for k from 0 below (length labeled) collect (format "C{}" (mod k 10)))))
    (plot-panels
     (map (lambda (panel)
            (let ((name (first panel)))
              (list (apply append (map (lambda (entry table color)
                                         (macro-models--panel-series (first entry) table name color))
                                       labeled tables colors))
                    :title name :y-label (second panel) :y-lines (list 0)
                    :legend (if (and (eq? panel (first panels)) (> (length labeled) 1)) "best" #f))))
          panels)
     :title title
     :x-label x-label)))

(define (macro-models--panel-series label table name color)
  "The series for one result in a panel of macro-models--plot: its 90% band, if it has one, shaded, then its line."
  (let* ((quarters (table-column table "quarter"))
         (line (list label quarters (table-column table name) :color color :line-width 2)))
    (if (member (string-append name " low") (map car table))
        (list (list (format "{} 90% band" label) quarters (table-column table (string-append name " low"))
                    :fill (table-column table (string-append name " high")) :color color)
              line)
        (list line))))

(define (show-oil-estimates estimate)
  "A table of what an estimate found: for each parameter, what it is, what was believed before the data (the prior's mean), the
posterior mean (the estimate) and its 90% interval (the data say it is between low and high, with a 90% chance)."
  (macro-models--show-estimates estimate oil-model-parameter-descriptions))

(define (macro-models--show-estimates estimate descriptions)
  (let* ((estimates (hash-table-ref estimate "estimates"))
         (names (table-column estimates "name")))
    (display-table
     (make-table "parameter" names
                 "what it is" (vector-map (lambda (name) (let ((found (assoc name descriptions)))
                                                           (if found (second found) "")))
                                          names)
                 "prior mean" (vector-round (table-column estimates "prior mean") 3)
                 "estimate" (vector-round (table-column estimates "mean") 3)
                 "low" (vector-round (table-column estimates "low") 3)
                 "high" (vector-round (table-column estimates "high") 3)))))

; ===========================================================================
; The stock-market crash model (dynare/crash_model.inc): a financial accelerator
; ===========================================================================
;
;   (crash-model)                                     the model with its parameters as chosen by hand
;   (crash-model :parameters '((nu . 0)))             ... with some changed: nu = 0 is an economy without the accelerator
;   (crash-model-estimate creds)                      its parameters estimated from US data, 1985 to 2008 (some minutes)
;   (crash-model :from estimate :parameters '(...))   a scenario that starts from the estimated parameters
;   (stock-crash-responses result :fall 20)           a table: what happens when firms' net worth (the stock market) falls 20%
;   (plot-stock-crash result :fall 20)                the same as charts; or several results, labeled, to compare them
;   (show-crash-estimates estimate)                   what the data say about each parameter
;
; The model's files are dynare/crash_model.inc, crash_irfs.mod (responses) and crash_estimate.mod (estimation).

(define crash-model-shocks
  '(("net_worth_shock"    "net_worth_shock_size"    "net worth (the stock market)")
    ("lender_fear_shock"  "lender_fear_shock_size"  "lenders' fears (the credit spread)")
    ("demand_shock"       "demand_shock_size"       "demand")
    ("productivity_shock" "productivity_shock_size" "productivity")
    ("fed_shock"          "fed_shock_size"          "Fed rate (monetary policy)")
    ("cost_push_shock"    "cost_push_shock_size"    "cost-push (firms' markups)")))

; As oil-model-variables: Dynare's name, the name shown, and what to multiply by. Inflation, the Fed's rate and the credit spread are per
; quarter in the model, and shown per year (times 4).
(define crash-model-variables
  '(("gdp"           "GDP"              1)
    ("consumption"   "consumption"      1)
    ("investment"    "investment"       1)
    ("hours"         "hours"            1)
    ("real_wage"     "real wage"        1)
    ("inflation"     "inflation"        4)
    ("fed_rate"      "Fed rate"         4)
    ("net_worth"     "net worth"        1)
    ("capital_price" "price of capital" 1)
    ("credit_spread" "credit spread"    4)))

(define crash-model-parameter-descriptions
  '(("price_stickiness"          "chance a firm can't change its price in a quarter")
    ("risk_aversion"             "dislike of uneven consumption")
    ("labor_dislike"             "how fast the wish not to work grows with hours")
    ("capital_price_response"    "how fast the price of capital rises with investment")
    ("accelerator"               "the accelerator: rise in the spread for 1% more borrowing")
    ("wealth_effect"             "how much spending rises with the shares households own")
    ("fed_inflation_response"    "Fed: rate rise for a point of inflation")
    ("fed_gdp_response"          "Fed: rate rise for a percent of GDP above normal")
    ("fed_smoothing"             "Fed: how slowly it moves its rate")
    ("productivity_persistence"  "how long a productivity change lasts")
    ("demand_persistence"        "how long a demand change lasts")
    ("lender_fear_persistence"   "how long lenders' fears last")
    ("stderr net_worth_shock"    "typical surprise to net worth, percent")
    ("stderr lender_fear_shock"  "typical surprise to the spread, points a quarter")
    ("stderr demand_shock"       "typical demand surprise")
    ("stderr productivity_shock" "typical productivity surprise, percent")
    ("stderr fed_shock"          "typical Fed rate surprise, points a quarter")
    ("stderr cost_push_shock"    "typical cost-push surprise")
    ("stderr credit_spread_data" "the spread's measurement error")))

(define (crash-model &key (parameters '()) (from '()) (quarters 20))
  "The crash model's responses to each kind of surprise, for quarters quarters, as dynare-run returns them. Its parameters are as
dynare/crash_model.inc chooses them, or, given :from, an estimate (from crash-model-estimate), as the estimate found them (their
posterior means); then :parameters, a list ((name . value) ...), changes any of them: '((accelerator . 0)) is an economy with no accelerator."
  (dynare-run "crash_irfs.mod"
              :parameters (append (if (null? from) '() (macro-models--estimated-parameters from crash-model-shocks)) parameters)
              :macros (list (cons 'quarters quarters))))

(define (crash-model-data creds &key (start (date 1985 1 1)) (end (date 2008 7 1)))
  "The data the crash model is estimated on, from FRED, by the quarter from start to end (the quarters' first days): the growth of
consumption (PCECC96) and investment (GPDIC1), core inflation (PCEPILFE), the federal funds rate (FEDFUNDS) and the spread of
Moody's Baa corporate bond yield over the 10-year Treasury (BAA10YM), each in percent a quarter (the spread, a rate a year, divided by 4),
less its average over these quarters. The default ends before the Fed's rate reached zero at the end of 2008, which the model's Fed rule
can't capture."
  (let* ((fred (fred-table creds '("PCECC96" "GPDIC1" "PCEPILFE" "FEDFUNDS" "BAA10YM") :frequency "quarterly"
                           :start-date (date-add-months start -3) :end-date end))
         (all (make-table "date"                    (table-column fred "date")
                          "consumption_growth_data"   (macro-models--growth (table-column fred "PCECC96"))
                          "investment_growth_data"    (macro-models--growth (table-column fred "GPDIC1"))
                          "inflation_data"            (macro-models--growth (table-column fred "PCEPILFE"))
                          "fed_rate_data"             (vector-div (table-column fred "FEDFUNDS") 4)
                          "credit_spread_data"        (vector-div (table-column fred "BAA10YM") 4)))
         (complete (table-filter all (vector-and (vector-not (vector-nan? (table-column all "consumption_growth_data")))
                                                 (vector-not (vector-nan? (table-column all "credit_spread_data")))))))
    (cons (car complete)
          (map (lambda (column) (cons (car column) (vector-sub (cdr column) (vector-mean (cdr column))))) (cdr complete)))))

(define (crash-model-estimate creds &key (start (date 1985 1 1)) (end (date 2008 7 1)) (data '()) (draws 4000) (quarters 20)
                              (echo #f))
  "The crash model's parameters estimated from US data, start to end (crash-model-data), or from the table :data: dynare-run's result
for dynare/crash_estimate.mod, with its \"estimates\" (show-crash-estimates shows them) and its \"responses\", with bands. Each of the two
chains makes draws draws; the default, 4000, takes about a quarter of an hour, and 1000 is enough for a first look. :echo #t shows what Dynare prints."
  (let ((data (if (null? data) (crash-model-data creds :start start :end end) data)))
    (display (format "Estimating the crash model on {} quarters, {} to {}, with {} draws in each of two chains; this takes about a quarter of an hour."
                     (table-row-count data) (vector-ref (table-column data "date") 0)
                     (vector-ref (table-column data "date") (- (table-row-count data) 1)) draws))
    (newline)
    (dynare-run "crash_estimate.mod" :data (cdr data) :echo echo
                :macros (list (cons 'draws draws) (cons 'quarters quarters)))))

(define (crash-model-responses result shock)
  "How the economy responds to one typical surprise of a kind (\"net_worth_shock\", one of crash-model-shocks), as a table: a quarter column, then
GDP, consumption, investment, hours, the real wage, net worth and the price of capital (percent from normal), inflation, the Fed's rate
and the credit spread (percentage points a year from normal); with a \"low\" and a \"high\" column for each, the 90% band, after an
estimation."
  (macro-models--responses result shock 1 crash-model-variables))

(define (stock-crash-responses result &key (fall 20))
  "How the economy responds when the stock market falls: a surprise to firms' net worth big enough that net worth is fall percent below
normal in the first quarter (it falls further, or recovers, after that), as crash-model-responses shows it. The model is linear, so a
fall twice as large has responses twice as large. (After an estimation, the bands are scaled by the same number.)"
  (let* ((net-worth (table-column (hash-table-ref (hash-table-ref result "responses") "net_worth_shock") "net_worth")))
    (macro-models--responses result "net_worth_shock" (/ (- fall) (vector-ref net-worth 0)) crash-model-variables)))

(define (plot-stock-crash results &key (fall 20) (title '()))
  "Charts of what happens when firms' net worth (the stock market) falls fall percent: GDP, consumption, investment, inflation, the Fed's
rate, the credit spread and net worth itself, a panel each, with the 90% band of an estimate. results is one result (of crash-model or
crash-model-estimate), or a list of (label result), to compare them: the same crash with and without the accelerator, say."
  (macro-models--plot results (lambda (result) (stock-crash-responses result :fall fall))
                      '(("GDP" "percent") ("consumption" "percent") ("investment" "percent") ("inflation" "points a year")
                        ("Fed rate" "points a year") ("credit spread" "points a year") ("net worth" "percent"))
                      (if (null? title) (format "After a {}% fall in the stock market (firms' net worth)" fall) title)
                      "quarters (1 is the quarter of the fall)"))

(define (show-crash-estimates estimate)
  "A table of what an estimate found: for each parameter, what it is, what was believed before the data (the prior's mean), the
posterior mean (the estimate) and its 90% interval (the data say it is between low and high, with a 90% chance)."
  (macro-models--show-estimates estimate crash-model-parameter-descriptions))

; ===========================================================================
; The stock-market crash with four kinds of households (dynare/types_model.inc)
; ===========================================================================
;
;   (wealth-by-type creds)                          the Fed's wealth shares of the four groups: their net worth and their stocks
;   (types-model)                                   the model with its parameters as chosen by hand
;   (types-model :wealth (wealth-by-type creds))    ... with the groups' stock holdings as the Fed's latest data show them
;   (types-model :parameters '((hand_to_mouth_bottom50 . 0)))   ... with some changed
;   (types-model-responses result "fed_shock")    the same for one typical surprise of any kind (the crash model's six)
;   (types-crash-responses result :fall 20)         a table: what happens to the economy and to each group when firms' net worth falls 20%
;   (types-crash-losses result :fall 20)            a table: how much each group's income and spending fall
;   (plot-types-crash result :fall 20)              the same as charts
;
; The model's files are dynare/types_model.inc and types_irfs.mod. It is the crash model with the households split in four, by wealth;
; the section "Four kinds of households" of lisp_macro_models_manual.md explains it.

; Each group: the name used in the model's variables and parameters, how it is shown, and the FRED series for its share of the nation's net
; worth and of its corporate equities and mutual fund shares (the Fed's Distributional Financial Accounts).
(define household-types
  '(("bottom50" "bottom 50%"        "WFRBSB50215" "WFRBSB50203")
    ("next40"   "next 40% (50-90)"  "WFRBSN40188" "WFRBSN40176")
    ("next9"    "next 9% (90-99)"   "WFRBSN09161" "WFRBSN09149")
    ("top1"     "top 1%"            "WFRBST01134" "WFRBST01122")))

(define (wealth-by-type creds)
  "The Federal Reserve's Distributional Financial Accounts for the latest quarter they have: a table with a row for each of the four groups
of households (the bottom 50% by wealth, the next 40%, the next 9% and the top 1%) and the share of the nation's net worth (\"net worth
share\") and of its corporate equities and mutual fund shares (\"stock share\") that the group holds, as fractions that add to 1."
  (let* ((series (apply append (map (lambda (group) (list (third group) (fourth group))) household-types)))
         (fred (fred-table creds series :frequency "quarterly" :start-date (date-add-months (today) -12)))
         (complete (table-filter fred (apply vector-and (map (lambda (id) (vector-not (vector-nan? (table-column fred id)))) series))))
         (last (- (table-row-count complete) 1)))
    (display (format "The Fed's Distributional Financial Accounts, quarter of {}" (vector-ref (table-column complete "date") last)))
    (newline)
    (let ((shares (lambda (position)
                    (let ((fractions (map (lambda (group) (/ (vector-ref (table-column complete (position group)) last) 100)) household-types)))
                      (list->vector (map (lambda (fraction) (/ fraction (apply + fractions))) fractions))))))
      (make-table "group" (list->vector (map second household-types))
                  "net worth share" (shares third)
                  "stock share" (shares fourth)))))

(define (types-model &key (parameters '()) (wealth '()) (quarters 20))
  "The four-household model's responses to each kind of surprise, for quarters quarters, as dynare-run returns them. Its parameters are as
dynare/types_model.inc chooses them; :wealth, a table from wealth-by-type, replaces the stock shares with the Fed's latest; then
:parameters, a list ((name . value) ...), changes any of them: '((hand_to_mouth_bottom50 . 0)) is an economy where the bottom half plan ahead."
  (dynare-run "types_irfs.mod"
              :parameters (append (if (null? wealth)
                                      '()
                                      (map (lambda (group share) (cons (string-append "stock_share_" (first group)) share))
                                           household-types (vector->list (table-column wealth "stock share"))))
                                  parameters)
              :macros (list (cons 'quarters quarters))))

; As crash-model-variables, with the income and the spending of each group.
(define types-model-variables
  (append '(("gdp"           "GDP"            1)
            ("consumption"   "consumption"    1)
            ("investment"    "investment"     1)
            ("hours"         "hours"          1)
            ("inflation"     "inflation"      4)
            ("fed_rate"      "Fed rate"       4)
            ("net_worth"     "net worth"      1)
            ("credit_spread" "credit spread"  4)
            ("wealth_tax"           "wealth tax"            1)
            ("wealth_tax_revenue"   "tax revenue"           1)
            ("top1_wealth_lost"     "top 1% wealth lost"    1)
            ("government_purchases" "government purchases"  1)
            ("ai_investment"        "AI investment"         1)
            ("ai_stocks"            "AI stocks"             1)
            ("ai_productivity"      "AI productivity"       1))
          (map (lambda (group) (list (string-append "income_" (first group)) (string-append "income: " (second group)) 1))
               household-types)
          (map (lambda (group) (list (string-append "consumption_" (first group)) (string-append "spending: " (second group)) 1))
               household-types)))

(define (types-model-responses result shock)
  "How the economy and each group of households respond to one typical surprise of a kind (\"fed_shock\", one of crash-model-shocks), as
a table with the columns of types-crash-responses."
  (macro-models--responses result shock 1 types-model-variables))

(define (types-crash-responses result &key (fall 20))
  "How the economy and each group of households respond when the stock market falls: a surprise to firms' net worth big enough that net
worth is fall percent below normal in the first quarter, as a table: a quarter column, then GDP, consumption, investment, hours (percent
from normal), inflation, the Fed's rate and the credit spread (points a year from normal), net worth, and the income and the spending of
each group (percent from that group's normal). The model is linear, so a fall twice as large has responses twice as large."
  (let* ((net-worth (table-column (hash-table-ref (hash-table-ref result "responses") "net_worth_shock") "net_worth")))
    (macro-models--responses result "net_worth_shock" (/ (- fall) (vector-ref net-worth 0)) types-model-variables)))

(define (types-crash-losses result &key (fall 20) (quarters 8))
  "How much each group of households loses in a stock market fall of fall percent: a row for each group, with its income and its spending
(percent from normal) in the first quarter, its spending at the worst, and its spending on average over the first quarters quarters."
  (let* ((responses (types-crash-responses result :fall fall))
         (spending (lambda (group) (table-column responses (string-append "spending: " (second group)))))
         (income (lambda (group) (table-column responses (string-append "income: " (second group)))))
         (rounded (lambda (f) (vector-round (list->vector (map f household-types)) 2))))
    (make-table "group" (list->vector (map second household-types))
                "income, first quarter" (rounded (lambda (group) (vector-ref (income group) 0)))
                "spending, first quarter" (rounded (lambda (group) (vector-ref (spending group) 0)))
                "spending, worst" (rounded (lambda (group) (vector-min (spending group))))
                (format "spending, average of {} quarters" quarters)
                (rounded (lambda (group) (vector-mean (vector-slice (spending group) 0 quarters)))))))

(define (plot-types-crash result &key (fall 20) (title '()))
  "Charts of what happens to the economy and to each group of households when firms' net worth (the stock market) falls fall percent: the
spending and the income of each group, GDP, the Fed's rate, the credit spread and net worth, a panel each."
  (macro-models--plot-groups (types-crash-responses result :fall fall)
                             '(("GDP" "percent") ("Fed rate" "points a year") ("credit spread" "points a year") ("net worth" "percent"))
                             (if (null? title) (format "After a {}% fall in the stock market, by group of households" fall) title)
                             "quarters (1 is the quarter of the fall)"))

(define (macro-models--plot-groups responses panels title x-label)
  "Charts of a table of types-model responses: a panel of the four groups' spending and one of their income, then a panel for each of
panels, a list of (the variable's name in the table, label for the axis)."
  (let ((quarters (table-column responses "quarter")))
    (let ((groups (lambda (kind)
                    (loop for group in household-types
                          for k from 0
                          collect (list (second group) quarters (table-column responses (string-append kind ": " (second group)))
                                        :color (format "C{}" k) :line-width 2)))))
      (plot-panels
       (append (list (list (groups "spending") :title "spending by group" :y-label "percent" :y-lines (list 0) :legend "best")
                     (list (groups "income") :title "income by group" :y-label "percent" :y-lines (list 0)))
               (map (lambda (panel)
                      (list (list (list (first panel) quarters (table-column responses (first panel)) :color "C0" :line-width 2))
                            :title (first panel) :y-label (second panel) :y-lines (list 0)))
                    panels))
       :title title
       :x-label x-label))))

; ===========================================================================
; A wealth tax on the top 1% (dynare/types_model.inc)
; ===========================================================================
;
;   (define tax (types-model :quarters 40))                       the model, with the assumptions of types_model.inc
;   (wealth-tax-responses tax :rate 1)                            a table: what a tax of 1% of the top 1%'s wealth a year does
;   (plot-wealth-tax tax :rate 1)                                 the same as charts
;   (compare-wealth-taxes (list (list "no avoidance" a) ...))     a table: the same tax under different assumptions, side by side
;
; The assumptions are parameters (tax_avoidance, wealth_rebuilding, wealth_spending_top1, tax_from_firm_equity, revenue_to_...), changed as
; any are: (types-model :quarters 40 :parameters '((tax_avoidance . 0.5))). The section "A wealth tax on the top 1%" of the manual explains them.

(define (wealth-tax-responses result &key (rate 1))
  "What happens when the wealth tax on the top 1% is rate percent of its wealth a year, as a table with the columns of types-crash-responses
(plus \"wealth tax\", \"tax revenue\" and \"government purchases\", percent of GDP, and \"top 1% wealth lost\", percent of its wealth). The tax
is rate in the first quarter and fades slowly after that (wealth_tax_persistence). Run types-model with :quarters 40, or more, to see ten years."
  (let* ((tax (table-column (hash-table-ref (hash-table-ref result "responses") "wealth_tax_shock") "wealth_tax")))
    (macro-models--responses result "wealth_tax_shock" (/ rate (vector-ref tax 0)) types-model-variables)))

(define (plot-wealth-tax result &key (rate 1) (title '()))
  "Charts of what a wealth tax on the top 1% of rate percent of its wealth a year does: the spending and the income of each group, GDP,
investment, what the tax collects (percent of GDP) and how much poorer it makes the top 1%, a panel each."
  (macro-models--plot-groups (wealth-tax-responses result :rate rate)
                             '(("GDP" "percent") ("investment" "percent") ("tax revenue" "percent of GDP") ("top 1% wealth lost" "percent"))
                             (if (null? title) (format "A wealth tax of {}% a year on the top 1%" rate) title)
                             "quarters (1 is the quarter the tax starts)"))

(define (compare-wealth-taxes results &key (rate 1) (quarters '(4 20 40)))
  "The same wealth tax under different assumptions, side by side: results is a list of (label result), each from types-model. A row for each
result and each of the quarters quarters after the tax starts (4, 20 and 40 are one, five and ten years): GDP, investment, consumption, the
spending of the bottom 50% and of the top 1% (percent from normal), and what the tax collects (percent of GDP)."
  (let* ((rows (apply append (map (lambda (entry)
                                    (let ((table (wealth-tax-responses (second entry) :rate rate)))
                                      (map (lambda (quarter) (list (first entry) quarter table)) quarters)))
                                  results)))
         (column (lambda (name) (vector-round (list->vector (map (lambda (row) (vector-ref (table-column (third row) name) (- (second row) 1))) rows)) 2))))
    (make-table "assumptions" (list->vector (map first rows))
                "quarter" (list->vector (map second rows))
                "GDP" (column "GDP")
                "investment" (column "investment")
                "consumption" (column "consumption")
                "spending: bottom 50%" (column "spending: bottom 50%")
                "spending: top 1%" (column "spending: top 1%")
                "tax revenue" (column "tax revenue"))))

; ===========================================================================
; A shock to the AI companies (dynare/types_model.inc)
; ===========================================================================
;
;   (ai-bust-scenarios)                                   the three scenarios: a moratorium, a solvency crisis, demand more elastic than thought
;   (define busts (ai-bust-models))                       the model run for each of them: a list of (label result)
;   (ai-bust-responses (second (first busts)))            a table: what happens, quarter by quarter, in one scenario
;   (compare-ai-busts busts)                              a table: the scenarios side by side, after one, two and five years
;   (compare-ai-busts (ai-bust-parts (second (second (ai-bust-scenarios)))))   a table: one scenario, and each of its parts alone
;   (plot-ai-busts busts)                                 charts: the scenarios side by side
;   (plot-ai-bust (second (first busts)))                 charts: one scenario, with each group of households
;   (ai-investment-data creds)                            the data on the boom: investment in computers, from the BEA (FRED)
;
; Each scenario is a list of the ai_ parameters of types_model.inc; any of them can be changed, and any other parameter of the model, as
; types-model's :parameters changes them. The section "A shock to the AI companies" of the manual explains the parameters and the scenarios.

(define (ai-bust-scenarios)
  "The three scenarios, as a list of (label parameters): the parameters are the ai_ parameters of dynare/types_model.inc that make each
scenario what it is (the others keep their values there). Every number is an assumption, said in the manual's section \"A shock to the AI
companies\":
  moratorium          no new data centers: AI investment falls 0.75% of GDP, slowly (projects underway are finished, and some of the
                      investment goes abroad); AI shares fall 15%; lenders don't mind.
  solvency crisis     an AI company can't pay for the chips and the leases it committed to: AI investment falls 1% of GDP, fast; AI
                      shares fall 40%; the credit spread rises 1 point a year (losses at private-credit funds and their lenders).
  elastic demand      AI is sold near its cost, because buyers switch to whatever is cheapest: AI investment falls 0.5% of GDP; AI
                      shares fall 35%; the spread rises a quarter point; the firms that use AI get 0.2% more productive, as it is cheaper."
  (list (list "moratorium"
              '((ai_investment_cut . 0.75) (ai_investment_delay . 0.8) (ai_stock_fall . 15) (ai_credit_stress . 0)
                (ai_productivity_gain . 0)))
        (list "solvency crisis"
              '((ai_investment_cut . 1.0) (ai_investment_delay . 0.5) (ai_stock_fall . 40) (ai_credit_stress . 1.0)
                (ai_productivity_gain . 0)))
        (list "elastic demand"
              '((ai_investment_cut . 0.5) (ai_investment_delay . 0.7) (ai_stock_fall . 35) (ai_credit_stress . 0.25)
                (ai_productivity_gain . 0.2)))))

(define (ai-bust-models &key (scenarios (ai-bust-scenarios)) (parameters '()) (quarters 20))
  "The four-household model run for each scenario: a list of (label result), for compare-ai-busts and plot-ai-busts. scenarios is a list of
(label parameters), as ai-bust-scenarios gives it; :parameters, a list ((name . value) ...), changes any parameter in every scenario:
'((ai_domestic_share . 0.3)) is a world where more of the AI investment is imported."
  (map (lambda (scenario)
         (list (first scenario) (types-model :parameters (append (second scenario) parameters) :quarters quarters)))
       scenarios))

(define (ai-bust-parts scenario-parameters &key (parameters '()) (quarters 20))
  "One scenario, and each of its parts alone, as a list of (label result) for compare-ai-busts and plot-ai-busts: \"all\", then
\"investment only\" (the fall in AI investment, nothing else), \"stocks only\" (the fall in AI shares), \"credit only\" (lenders' fears)
and \"productivity only\" (cheaper AI for other firms), leaving out a part the scenario doesn't have. scenario-parameters is the second of
an entry of ai-bust-scenarios. The model is linear, so the parts add up to all of it: the table says which part does what."
  (let* ((size (lambda (name) (cdr (assoc name scenario-parameters))))
         (zero '((ai_investment_cut . 0) (ai_stock_fall . 0) (ai_credit_stress . 0) (ai_productivity_gain . 0)))
         (only (lambda (name) (append scenario-parameters zero (list (cons name (size name))))))
         (parts (filter (lambda (part) (not (= (size (second part)) 0)))
                        '(("investment only" ai_investment_cut) ("stocks only" ai_stock_fall)
                          ("credit only" ai_credit_stress) ("productivity only" ai_productivity_gain)))))
    (ai-bust-models :scenarios (cons (list "all" scenario-parameters)
                                     (map (lambda (part) (list (first part) (only (second part)))) parts))
                    :parameters parameters :quarters quarters)))

(define (ai-bust-responses result)
  "What happens, quarter by quarter, after the AI bust of a result of types-model (ai-bust-models makes them): a table with the columns of
types-crash-responses, and \"AI investment\" (percent of GDP from normal), \"AI stocks\" and \"AI productivity\" (percent)."
  (macro-models--responses result "ai_shock" 1 types-model-variables))

(define (compare-ai-busts results &key (quarters '(1 4 8 20)))
  "Scenarios side by side: results is a list of (label result), as ai-bust-models makes it. A row for each scenario and each of the quarters
quarters after the bust starts (4, 8 and 20 are one, two and five years): GDP, consumption, the economy's own investment (not the AI
companies'), the spending of the bottom 50% and of the top 1% (percent from normal), the Fed's rate and the credit spread (points a year),
and AI investment (percent of GDP). The last row of a scenario's GDP column, compared with its AI investment, says how much of the bust the
rest of the economy makes up."
  (let* ((rows (apply append (map (lambda (entry)
                                    (let ((table (ai-bust-responses (second entry))))
                                      (map (lambda (quarter) (list (first entry) quarter table)) quarters)))
                                  results)))
         (column (lambda (name) (vector-round (list->vector (map (lambda (row) (vector-ref (table-column (third row) name) (- (second row) 1))) rows)) 2))))
    (make-table "scenario" (list->vector (map first rows))
                "quarter" (list->vector (map second rows))
                "GDP" (column "GDP")
                "consumption" (column "consumption")
                "other investment" (column "investment")
                "spending: bottom 50%" (column "spending: bottom 50%")
                "spending: top 1%" (column "spending: top 1%")
                "Fed rate" (column "Fed rate")
                "credit spread" (column "credit spread")
                "AI investment" (column "AI investment"))))

(define (plot-ai-busts results &key (title "After a shock to the AI companies"))
  "Charts of scenarios side by side, results a list of (label result) as ai-bust-models makes it: GDP, consumption, the economy's own
investment, the Fed's rate, the credit spread and AI investment, a panel each."
  (macro-models--plot results ai-bust-responses
                      '(("GDP" "percent") ("consumption" "percent") ("investment" "percent") ("Fed rate" "points a year")
                        ("credit spread" "points a year") ("AI investment" "percent of GDP"))
                      title
                      "quarters (1 is the quarter the bust starts)"))

(define (plot-ai-bust result &key (title "After a shock to the AI companies, by group of households"))
  "Charts of one scenario (a result of types-model, as ai-bust-models makes them): the spending and the income of each group of households,
GDP, the Fed's rate, the economy's own investment and AI investment, a panel each."
  (macro-models--plot-groups (ai-bust-responses result)
                             '(("GDP" "percent") ("Fed rate" "points a year") ("investment" "percent") ("AI investment" "percent of GDP"))
                             title
                             "quarters (1 is the quarter the bust starts)"))

(define (ai-investment-data creds &key (start (date 2019 1 1)))
  "The data on the AI boom, from the BEA's national accounts (through FRED), by the quarter from start: GDP and business investment in
computers and peripheral equipment (B935RC1Q027SBEA), in billions of dollars a year, and that investment as a percent of GDP. Servers for data
centers are most of it now; before the boom it was about half a percent of GDP. (Data-center buildings, power and software are in other
series, and much of the equipment is imported: see the manual.)"
  (let* ((fred (fred-table creds '("GDP" "B935RC1Q027SBEA") :frequency "quarterly" :start-date start))
         (computers (table-column fred "B935RC1Q027SBEA")))
    (make-table "date" (table-column fred "date")
                "GDP" (table-column fred "GDP")
                "computer investment" computers
                "percent of GDP" (vector-round (vector-mul (vector-div computers (table-column fred "GDP")) 100) 2))))
