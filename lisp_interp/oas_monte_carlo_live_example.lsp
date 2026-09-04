; oas_monte_carlo_live_example.lsp
;
; The same pipeline as oas_monte_carlo_example.lsp, but against REAL
; market data instead of made-up illustrative numbers:
;   - the near-term SOFR curve, and the options used to calibrate the
;     two-factor model's sigma1/sigma2, both fetched from tastytrade
;     (sofr-calibration-data -- the same real-data fetch
;     sofr_monte_carlo_example.lsp uses);
;   - the Treasury par curve used to extend the SOFR curve's long end
;     (sofr-extend-curve-with-treasury), fetched from FRED;
;   - a historical-volatility cross-check for the fitted sigma1/sigma2
;     (annualized-realized-vol), computed from real FRED daily-rate
;     history (DFF for the short-rate factor, DGS10 for the slower
;     mean-reversion-level factor);
;   - the mortgage note rate driving simple-mortgage-cashflows, fetched
;     from FRED's MORTGAGE30US (the weekly Freddie Mac Primary Mortgage
;     Market Survey average) instead of an assumed number.
;
; The ONE number this script cannot fetch anywhere in this codebase is
; the security's own MARKET PRICE -- there's no live TBA/pass-through
; quote source wired up here -- so `assumed-market-price`, below, stays
; an assumption; the report this script writes calls that out
; explicitly, separately from everything that WAS fetched.
;
; Needs the `tastytrade` package, a tastytrade account, and a
; credentials JSON file with BOTH tastytrade fields AND a
; "fred_api_key" entry (see tasty_api/README.md and fred_example.lsp) --
; `creds`, referenced below, comes from init.lsp, which is loaded
; automatically at startup; edit that if your credentials file lives
; somewhere else.
;
; CALIBRATION IS SLOW, and so is generating one cashflow vector per
; Monte Carlo path in pure Lisp (see oas_monte_carlo.lsp's header
; comment for why that part isn't done through column_engine.lsp) --
; calibration-n-paths/n-grid/n-rounds and n-scenario-paths, below, are
; turned down from term_structure_model.py's own defaults so a first run
; finishes in roughly a minute; turn them back up for a more careful
; run once you've confirmed everything works. Writes a report to
; oas_monte_carlo_live_report.txt (and prints the same report to the
; console) with every market data point and assumption this run used.
;
; Run with:
;   python3 lisp_interpreter.py oas_monte_carlo_live_example.lsp

(load "oas_monte_carlo.lsp")

(define (fred-latest-value series) (vector-ref (cdr series) (- (vector-length (cdr series)) 1)))
(define (fred-latest-date series) (vector-ref (car series) (- (vector-length (car series)) 1)))

; --- 1. fetch the SOFR futures curve AND calibration options ------------

(display "Fetching SOFR futures curve and options from tastytrade...") (newline)
(define calibration-data (sofr-calibration-data creds 40 8 3))
(define curve-futures-rows (car calibration-data))
(define options-rows (cdr calibration-data))

(define sofr-curve (sofr-bootstrap-curve curve-futures-rows))
(define sofr-forward-rates (cdr sofr-curve))

; How many months of sofr-forward-rates are the REAL (non-extrapolated)
; part of the curve -- the last SR3 contract's end_months. curve-futures-
; rows is (symbol start_months end_months rate); end_months is field 2.
(define (curve-real-months rows)
  (if (null? (cdr rows))
      (list-ref (car rows) 2)
      (max (list-ref (car rows) 2) (curve-real-months (cdr rows)))))
(define real-months (curve-real-months curve-futures-rows))

(display "  ") (display (length curve-futures-rows)) (display " SOFR futures contracts, ")
(display (length options-rows)) (display " options, real curve out to month ")
(display real-months) (newline)

; --- 2. calibrate (a, theta_bar, sigma1, sigma2) against the options ----

(display "Calibrating against real SOFR futures option prices...") (newline)
(define calibration-n-paths 500)    ; turned down from term_structure_model.py's
(define calibration-n-grid 5)       ; own defaults (2000/7/4) for a quicker
(define calibration-n-rounds 3)     ; first run
(define fit (sofr-calibrate-model sofr-forward-rates options-rows real-months
                                   calibration-n-paths 42
                                   calibration-n-grid calibration-n-rounds))
(define fitted-a (list-ref fit 0))
(define fitted-theta-bar (list-ref fit 1))
(define fitted-sigma1 (list-ref fit 2))
(define fitted-sigma2 (list-ref fit 3))
(define fitted-error (list-ref fit 4))
(display "  a=") (display fitted-a) (display "  theta_bar=") (display fitted-theta-bar)
(display "  sigma1=") (display fitted-sigma1) (display "  sigma2=") (display fitted-sigma2)
(display "  error=") (display fitted-error) (newline)

; --- 3. fetch the Treasury par curve from FRED, extend the SOFR curve --

(display "Fetching Treasury par yields from FRED...") (newline)
(define dgs3mo-series (fred-series "DGS3MO" creds))
(define dgs6mo-series (fred-series "DGS6MO" creds))
(define dgs1-series (fred-series "DGS1" creds))
(define dgs2-series (fred-series "DGS2" creds))
(define dgs5-series (fred-series "DGS5" creds))
(define dgs10-series (fred-series "DGS10" creds))
(define dgs30-series (fred-series "DGS30" creds))

(define yield-3m (/ (fred-latest-value dgs3mo-series) 100.0))
(define yield-6m (/ (fred-latest-value dgs6mo-series) 100.0))
(define yield-1y (/ (fred-latest-value dgs1-series) 100.0))
(define yield-2y (/ (fred-latest-value dgs2-series) 100.0))
(define yield-5y (/ (fred-latest-value dgs5-series) 100.0))
(define yield-10y (/ (fred-latest-value dgs10-series) 100.0))
(define yield-30y (/ (fred-latest-value dgs30-series) 100.0))

(display "  3m=") (display yield-3m) (display " 6m=") (display yield-6m)
(display " 1y=") (display yield-1y) (display " 2y=") (display yield-2y)
(display " 5y=") (display yield-5y) (display " 10y=") (display yield-10y)
(display " 30y=") (display yield-30y) (display "  (as of ")
(display (fred-latest-date dgs10-series)) (display ")") (newline)

(define extended-forward-rates
  (sofr-extend-curve-with-treasury sofr-forward-rates real-months
                                    yield-3m yield-6m yield-1y yield-2y
                                    yield-5y yield-10y yield-30y))

; --- 4. historical-vol cross-check for fitted sigma1/sigma2 -------------

(display "Fetching historical rate history from FRED for a vol cross-check...") (newline)
(define dff-series (fred-series "DFF" creds))     ; daily effective fed funds rate
(define vol-window-days 504)                      ; ~2 years of business days

(define (fred-recent-decimal-values series n)
  (define pct_values (cdr series))
  (define len (vector-length pct_values))
  (vector-scale (vector-drop pct_values (max 0 (- len n))) 0.01))

(define dff-recent (fred-recent-decimal-values dff-series vol-window-days))
(define dgs10-recent (fred-recent-decimal-values dgs10-series vol-window-days))

(define historical-vol-short (annualized-realized-vol dff-recent 252))
(define historical-vol-level (annualized-realized-vol dgs10-recent 252))

(display "  historical short-rate vol (DFF, ~2y daily): ") (display historical-vol-short)
(display "  vs. fitted sigma1: ") (display fitted-sigma1) (newline)
(display "  historical level vol (DGS10, ~2y daily): ") (display historical-vol-level)
(display "  vs. fitted sigma2: ") (display fitted-sigma2) (newline)

; --- 5. fetch the current market mortgage rate from FRED -----------------

(display "Fetching the current 30-year mortgage rate from FRED...") (newline)
(define mortgage30us-series (fred-series "MORTGAGE30US" creds))
(define note-rate-percent (fred-latest-value mortgage30us-series))   ; already in percent points
(display "  MORTGAGE30US: ") (display note-rate-percent) (display "%  (as of ")
(display (fred-latest-date mortgage30us-series)) (display ")") (newline)

; --- 6. simulate Monte Carlo mortgage-rate paths off the fitted model,
;        extended curve --------------------------------------------------

(define n-scenario-paths 100)   ; turned down for a quicker first run --
                                 ; see this file's header comment
(define horizon-years 30)
(define mortgage-spread 0.0175)  ; 175bp -- see term_structure/
                                  ; mortgage_spread.py for a data-driven
                                  ; estimate instead of a guess; not
                                  ; fetched here

(display "Simulating ") (display n-scenario-paths) (display " mortgage-rate paths over ")
(display horizon-years) (display " years...") (newline)
(define sim (sofr-simulate-mortgage-rate-paths
              extended-forward-rates fitted-sigma1 fitted-sigma2 horizon-years n-scenario-paths
              mortgage-spread 42 fitted-a fitted-theta-bar))
(define short-rate-paths (list-ref sim 1))
(define mortgage-paths (list-ref sim 3))

; --- 7. per-path mortgage cashflows, using the REAL fetched note rate ---

(define initial-balance 300000.0)   ; loan size -- not fetched, a modeling choice
(define n-months 360)
(define psa-speed 100)              ; 100% PSA -- not fetched, a modeling choice

(display "Generating per-path mortgage cashflows...") (newline)
(define path-cashflows
  (mortgage-cashflows-per-path initial-balance note-rate-percent n-months psa-speed mortgage-paths))

; --- 8. solve for the OAS matching an ASSUMED market price --------------

; No live TBA/pass-through price source is wired into this codebase, so
; this stays an assumption -- see the report, below, which reports it
; separately from everything that WAS fetched.
(define assumed-market-price 98.50)   ; per 100 face

(define price-scale (/ 100.0 initial-balance))
(define scaled-path-cashflows (map (lambda (cf) (vector-scale cf price-scale)) path-cashflows))

(display "Solving for OAS...") (newline)
(define model-price-at-0-oas (oas-model-price scaled-path-cashflows short-rate-paths 0.0))
(define solved-oas (oas-solve scaled-path-cashflows short-rate-paths assumed-market-price))

; --- 9. the report: every market data point and assumption used ---------

(define (write-report)
  (display "================================================================")
  (newline)
  (display "OAS Monte Carlo report -- live market data") (newline)
  (display "================================================================")
  (newline) (newline)

  (display "--- MARKET DATA (fetched) ---") (newline) (newline)

  (display "SOFR futures curve (tastytrade):") (newline)
  (display "  ") (display (length curve-futures-rows)) (display " contracts, real curve out to month ")
  (display real-months) (newline)
  (display "  1-month forward rate at month 1:   ") (display (vector-ref sofr-forward-rates 0)) (newline)
  (display "  1-month forward rate at month ") (display real-months) (display ": ")
  (display (vector-ref sofr-forward-rates (- real-months 1))) (newline) (newline)

  (display "Calibration options (tastytrade): ") (display (length options-rows))
  (display " SOFR futures options") (newline) (newline)

  (display "Calibrated two-factor model parameters (fit against the options above):") (newline)
  (display "  a (mean-reversion speed)        = ") (display fitted-a) (newline)
  (display "  theta_bar (long-run level)      = ") (display fitted-theta-bar) (newline)
  (display "  sigma1 (short-rate factor vol)  = ") (display fitted-sigma1) (newline)
  (display "  sigma2 (level factor vol)       = ") (display fitted-sigma2) (newline)
  (display "  total squared pricing error     = ") (display fitted-error) (newline) (newline)

  (display "Treasury par yields (FRED, as of ") (display (fred-latest-date dgs10-series))
  (display "):") (newline)
  (display "  3m=") (display yield-3m) (display "  6m=") (display yield-6m)
  (display "  1y=") (display yield-1y) (display "  2y=") (display yield-2y) (newline)
  (display "  5y=") (display yield-5y) (display "  10y=") (display yield-10y)
  (display "  30y=") (display yield-30y) (newline) (newline)

  (display "Extended forward curve (SOFR out to month ") (display real-months)
  (display ", Treasury-shaped beyond that):") (newline)
  (display "  month 12:  ") (display (vector-ref extended-forward-rates 11)) (newline)
  (display "  month 60:  ") (display (vector-ref extended-forward-rates 59)) (newline)
  (display "  month 120: ") (display (vector-ref extended-forward-rates 119)) (newline)
  (display "  month 240: ") (display (vector-ref extended-forward-rates 239)) (newline)
  (display "  month 360: ") (display (vector-ref extended-forward-rates 359)) (newline) (newline)

  (display "Historical-volatility cross-check (FRED, last ") (display vol-window-days)
  (display " business days):") (newline)
  (display "  DFF-implied annualized short-rate vol = ") (display historical-vol-short)
  (display "   (fitted sigma1 = ") (display fitted-sigma1) (display ")") (newline)
  (display "  DGS10-implied annualized level vol    = ") (display historical-vol-level)
  (display "   (fitted sigma2 = ") (display fitted-sigma2) (display ")") (newline) (newline)

  (display "Current 30-year mortgage rate (FRED MORTGAGE30US, as of ")
  (display (fred-latest-date mortgage30us-series)) (display "): ")
  (display note-rate-percent) (display "%") (newline) (newline)

  (display "--- ASSUMPTIONS (not fetched) ---") (newline) (newline)

  (display "Loan: initial balance $") (display initial-balance)
  (display ", ") (display n-months) (display "-month term, ")
  (display psa-speed) (display "% PSA prepayment speed") (newline)
  (display "Mortgage spread over the model's tenor-year proxy rate: ") (display mortgage-spread)
  (display "  (see term_structure/mortgage_spread.py for a data-driven estimate)") (newline)
  (display "Assumed market price (NOT fetched -- no live quote source wired up): ")
  (display assumed-market-price) (display " per 100 face") (newline)
  (display "Monte Carlo scenario paths: ") (display n-scenario-paths)
  (display " over ") (display horizon-years) (display " years, seed 42") (newline) (newline)

  (display "--- RESULT ---") (newline) (newline)

  (display "Model price at 0 OAS:  ") (display model-price-at-0-oas) (newline)
  (display "Assumed market price:  ") (display assumed-market-price) (newline)
  (display "Solved OAS (decimal):  ") (display solved-oas) (newline)
  (display "Solved OAS (bp):       ") (display (* solved-oas 10000)) (newline))

(write-report)

(redirect-output "oas_monte_carlo_live_report.txt")
(write-report)
(reset-output)
(display "Wrote oas_monte_carlo_live_report.txt") (newline)
