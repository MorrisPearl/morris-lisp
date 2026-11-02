; macro_models.lsp
; ================
; Small models of the US economy, solved and estimated by Dynare (dynare-run): what happens to GDP, inflation, wages and the Fed's rate,
; quarter by quarter, after a surprise such as a jump in the price of oil. doc/lisp_macro_models_manual.md explains them.
;
;   (oil-model)                                       the oil model with its parameters as chosen by hand (calibrated)
;   (oil-model :parameters '((gamma . 0.9)))          ... with some of them changed: a scenario
;   (oil-model-estimate creds)                        its parameters estimated from US data, 1985 to 2008 (some minutes)
;   (oil-model :from estimate :parameters '(...))     a scenario that starts from the estimated parameters
;   (oil-shock-responses result :rise 10)             a table: what happens when the price of oil rises 10%
;   (plot-oil-shock result :rise 10)                  the same as charts; or several results, labeled, to compare them
;   (show-oil-estimates estimate)                     what the data say about each parameter
;
; The model itself is in dynare/oil_model.inc, with oil_irfs.mod (responses, for given parameters) and oil_estimate.mod (estimation).

; The model's shocks: Dynare's name, the parameter that holds its typical size in oil_irfs.mod, and what it is.
(define oil-model-shocks
  '(("e_oil" "sigma_oil" "oil price")
    ("e_a"   "sigma_a"   "productivity")
    ("e_z"   "sigma_z"   "demand")
    ("e_i"   "sigma_i"   "Fed rate (monetary policy)")
    ("e_p"   "sigma_p"   "cost-push (firms' markups)")
    ("e_w"   "sigma_w"   "wages (workers' bargaining power)")))

; The variables shown: the model's name, the name shown, and what to multiply by. Inflation and the Fed's rate are per quarter in the
; model, and shown per year (times 4), as they are reported; the others are percent differences from normal.
(define oil-model-variables
  '(("y"    "GDP"                1)
    ("c"    "consumption"        1)
    ("n"    "hours"              1)
    ("w"    "real wage"          1)
    ("pi_c" "headline inflation" 4)
    ("pi_q" "core inflation"     4)
    ("i"    "Fed rate"           4)
    ("s"    "real oil price"     1)))

; What each parameter is, for show-oil-estimates.
(define oil-model-parameter-descriptions
  '(("theta"       "chance a firm can't change its price in a quarter")
    ("gamma"       "real wage rigidity (0: wages adjust at once)")
    ("sigma"       "dislike of uneven consumption")
    ("phi"         "how fast the wish not to work grows with hours")
    ("phi_pi"      "Fed: rate rise for a point of inflation")
    ("phi_y"       "Fed: rate rise for a percent of GDP above normal")
    ("rho_i"       "Fed: how slowly it moves its rate")
    ("core_weight" "Fed: weight on core inflation (rest: headline)")
    ("rho_a"       "how long a productivity change lasts")
    ("rho_z"       "how long a demand change lasts")
    ("rho_s"       "how long an oil price change lasts")
    ("stderr e_oil"    "typical oil price surprise, percent")
    ("stderr e_a"      "typical productivity surprise, percent")
    ("stderr e_z"      "typical demand surprise")
    ("stderr e_i"      "typical Fed rate surprise, points a quarter")
    ("stderr e_p"      "typical cost-push surprise")
    ("stderr e_w"      "typical wage surprise, percent")
    ("stderr pi_c_obs" "headline inflation's measurement error")))

; ---------------------------------------------------------------------------
; Running the model
; ---------------------------------------------------------------------------

(define (oil-model &key (parameters '()) (from '()) (quarters 20))
  "The oil model's responses to each kind of surprise, for quarters quarters, as dynare-run returns them. Its parameters are as
dynare/oil_model.inc chooses them, or, given :from, an estimate (from oil-model-estimate), as the estimate found them (their posterior
means); then :parameters, a list ((name . value) ...), changes any of them: '((gamma . 0.9) (core_weight . 1))."
  (dynare-run "oil_irfs.mod"
              :parameters (append (if (null? from) '() (oil-model-estimated-parameters from)) parameters)
              :macros (list (cons 'quarters quarters))))

(define (oil-model-estimated-parameters estimate)
  "The parameters an estimate found, as a list ((name . value) ...) that oil-model's :parameters takes: each one's posterior mean (or
its mode, if the estimate made no draws). A shock's size (\"stderr e_oil\") becomes its parameter in oil_irfs.mod (sigma_oil); the
measurement error is left out, since it is not part of the economy."
  (let* ((estimates (hash-table-ref estimate "estimates"))
         (names (table-column estimates "name"))
         (means (table-column estimates "mean"))
         (modes (table-column estimates "mode"))
         (no-mean (vector-nan? means)))
    (loop for k from 0 below (vector-length names)
          for name = (vector-ref names k)
          for value = (if (= (vector-ref no-mean k) 1) (vector-ref modes k) (vector-ref means k))
          for shock = (find-if (lambda (entry) (equal? name (string-append "stderr " (first entry)))) oil-model-shocks)
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
                          "dy_obs"   (macro-models--growth (table-column fred "GDPC1"))
                          "dw_obs"   (macro-models--growth (table-column fred "COMPRNFB"))
                          "pi_q_obs" core
                          "pi_c_obs" (macro-models--growth (table-column fred "PCEPI"))
                          "i_obs"    (vector-div (table-column fred "FEDFUNDS") 4)
                          "ds_obs"   (vector-sub (macro-models--growth (table-column fred "WTISPLC")) core)))
         (complete (table-filter all (vector-and (vector-not (vector-nan? (table-column all "dy_obs")))
                                                 (vector-not (vector-nan? (table-column all "dw_obs")))))))
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
  "How the economy responds to one typical surprise of a kind (\"e_z\", one of oil-model-shocks), as a table: a quarter column, then
GDP, consumption, hours and the real wage (percent from normal), headline and core inflation and the Fed's rate (percentage points a
year from normal) and the real price of oil; with a \"low\" and a \"high\" column for each, the 90% band, after an estimation."
  (macro-models--responses result shock 1))

(define (oil-shock-responses result &key (rise 10))
  "How the economy responds when the real price of oil rises rise percent in the first quarter, as oil-model-responses shows it. The
model is linear, so a rise twice as large has responses twice as large. (After an estimation, the bands are scaled by the same number,
which leaves out how unsure the estimate is of the typical size of an oil surprise.)"
  (let* ((oil (table-column (hash-table-ref (hash-table-ref result "responses") "e_oil") "s")))
    (macro-models--responses result "e_oil" (/ rise (vector-ref oil 0)))))

(define (macro-models--responses result shock scale)
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
                      oil-model-variables)))))

(define (plot-oil-shock results &key (rise 10) (title '()))
  "Charts of what happens when the real price of oil rises rise percent: GDP, consumption, headline and core inflation, the Fed's rate
and the real wage, a panel each, with the 90% band of an estimate. results is one result (of oil-model or oil-model-estimate), or a list of
(label result), to compare them: the same shock under different parameters, say, or estimated on different years."
  (let* ((labeled (if (hash-table? results) (list (list "model" results)) results))
         (tables (map (lambda (entry) (oil-shock-responses (second entry) :rise rise)) labeled))
         (colors (loop for k from 0 below (length labeled) collect (format "C{}" (mod k 10))))
         (panels '(("GDP" "percent") ("consumption" "percent") ("headline inflation" "points a year") ("core inflation" "points a year")
                   ("Fed rate" "points a year") ("real wage" "percent"))))
    (plot-panels
     (map (lambda (panel)
            (let ((name (first panel)))
              (list (apply append (map (lambda (entry table color)
                                         (macro-models--panel-series (first entry) table name color))
                                       labeled tables colors))
                    :title name :y-label (second panel) :y-lines (list 0)
                    :legend (if (and (eq? panel (first panels)) (> (length labeled) 1)) "best" #f))))
          panels)
     :title (if (null? title) (format "After a {}% rise in the real price of oil" rise) title)
     :x-label "quarters (1 is the quarter of the rise)")))

(define (macro-models--panel-series label table name color)
  "The series for one result in a panel of plot-oil-shock: its 90% band, if it has one, shaded, then its line."
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
  (let* ((estimates (hash-table-ref estimate "estimates"))
         (names (table-column estimates "name")))
    (display-table
     (make-table "parameter" names
                 "what it is" (vector-map (lambda (name) (let ((found (assoc name oil-model-parameter-descriptions)))
                                                           (if found (second found) "")))
                                          names)
                 "prior mean" (vector-round (table-column estimates "prior mean") 3)
                 "estimate" (vector-round (table-column estimates "mean") 3)
                 "low" (vector-round (table-column estimates "low") 3)
                 "high" (vector-round (table-column estimates "high") 3)))))
