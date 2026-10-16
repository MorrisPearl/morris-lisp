; oas_monte_carlo_live_example.lsp
;
; The same pipeline as oas_monte_carlo_example.lsp, but against REAL
; market data instead of made-up illustrative numbers:
;   - the Treasury's par yield curve, from the Treasury (treasury-par-curve),
;     which the paths of rates start on;
;   - SOFR futures and options on them, and options on the 10-year note
;     future, from tastytrade, to calibrate the two-factor model's a,
;     sigma1 and sigma2 (sofr-calibrate-jointly: see rate_model_example.lsp);
;   - a historical-volatility cross-check for the fitted sigma1/sigma2
;     (annualized-realized-vol), computed from real FRED daily-rate
;     history (DFF for the short-rate factor, DGS10 for the slower
;     mean-reversion-level factor);
;   - the mortgage note rate driving simple-mortgage-cashflows, fetched
;     from FRED's MORTGAGE30US (the weekly Freddie Mac Primary Mortgage
;     Market Survey average) instead of an assumed number, and the spread
;     of mortgage rates over the 10-year yield that it implies.
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
; Generating one cashflow vector per Monte Carlo path in pure Lisp takes a
; while (see oas_monte_carlo.lsp's header comment for why that part isn't done
; through column_engine.lsp), so n-scenario-paths, below, is turned down: turn
; it back up for a more careful run once you've confirmed everything works.
; Writes a report to oas_monte_carlo_live_report.txt (and prints the same report
; to the console) with every market data point and assumption this run used.
;
; Run it from the examples directory with:
;   python3 ../lisp_interpreter.py oas_monte_carlo_live_example.lsp

(load "oas_monte_carlo.lsp")
(load "yield_curves.lsp")
(load "note_options.lsp")

(define (latest table column)
  ; the date and value of a FRED table's latest value in column, as (date value)
  (let ((known (table-filter table (vector-not (vector-nan? (table-column table column))))))
    (list (vector-ref (table-column known "date") (- (table-row-count known) 1))
          (vector-ref (table-column known column) (- (table-row-count known) 1)))))

; --- 1. the Treasury's curve: the paths of rates start on it -------------

(display "Fetching the Treasury's par yield curve...") (newline)
(define par-curve (treasury-par-curve))
(define treasury-day (vector-max (table-column par-curve "date")))
(define treasury-forwards (table-column (curve-forward-rates (treasury-zero-curve par-curve)) "forward"))
(define (par-yield years) (sofr-par-yield treasury-forwards years))
(display "  as of ") (display treasury-day) (display ": 2y=") (display (par-yield 2))
(display " 5y=") (display (par-yield 5)) (display " 10y=") (display (par-yield 10))
(display " 30y=") (display (par-yield 30)) (newline)

; --- 2. fetch the SOFR futures curve and options, and the 10-year note options ---

(display "Fetching SOFR futures, SOFR options and 10-year note options from tastytrade...") (newline)
(define calibration-data (sofr-calibration-data creds 40 8 3))
(define curve-futures-rows (car calibration-data))
(define sofr-option-rows (cdr calibration-data))
(define sofr-forward-rates (cdr (sofr-bootstrap-curve curve-futures-rows)))
(define note-rows (note-option-rows (tastytrade-option-chain creds "ZN" 12 12) :min-days 20 :max-days 120))

; How many months of sofr-forward-rates are the REAL (non-extrapolated)
; part of the curve -- the last SR3 contract's end_months. curve-futures-
; rows is (symbol start_months end_months rate); end_months is field 2.
(define real-months (apply max (map third curve-futures-rows)))

(display "  ") (display (length curve-futures-rows)) (display " SOFR futures contracts, ")
(display (length sofr-option-rows)) (display " SOFR options, ")
(display (length note-rows)) (display " options on the 10-year note future") (newline)

; --- 3. calibrate (a, sigma1, sigma2) against both kinds of option ------

(display "Calibrating against the option prices...") (newline)
(define fit (sofr-calibrate-jointly sofr-forward-rates treasury-forwards sofr-option-rows note-rows real-months))
(define (fitted name) (cdr (assoc name fit)))
(define fitted-a (fitted 'a))
(define fitted-sigma1 (fitted 'sigma1))
(define fitted-sigma2 (fitted 'sigma2))
(define fitted-error (fitted 'error))
(display "  a=") (display fitted-a)
(display "  sigma1=") (display fitted-sigma1) (display "  sigma2=") (display fitted-sigma2)
(display "  error=") (display fitted-error) (newline)

; --- 4. historical-vol cross-check for fitted sigma1/sigma2 -------------

(display "Fetching historical rate history from FRED for a vol cross-check...") (newline)
(define dff (table-column (fred-table creds "DFF") "DFF"))         ; the daily effective fed funds rate, %
(define dgs10 (table-column (fred-table creds "DGS10") "DGS10"))   ; the 10-year Treasury's, %
(define vol-window-days 504)                                       ; ~2 years of business days

(define (recent-decimal-values percents n)
  ; the last n values, as decimals
  (vector-mul (vector-drop percents (max 0 (- (vector-length percents) n))) 0.01))

(define dff-recent (recent-decimal-values dff vol-window-days))
(define dgs10-recent (recent-decimal-values dgs10 vol-window-days))

(define historical-vol-short (annualized-realized-vol dff-recent 252))
(define historical-vol-level (annualized-realized-vol dgs10-recent 252))

(display "  historical short-rate vol (DFF, ~2y daily): ") (display historical-vol-short)
(display "  vs. fitted sigma1: ") (display fitted-sigma1) (newline)
(display "  historical level vol (DGS10, ~2y daily): ") (display historical-vol-level)
(display "  vs. fitted sigma2: ") (display fitted-sigma2) (newline)

; --- 5. fetch the current market mortgage rate from FRED -----------------

(display "Fetching the current 30-year mortgage rate from FRED...") (newline)
(define mortgage30us (fred-table creds "MORTGAGE30US"))
(define note-rate-percent (second (latest mortgage30us "MORTGAGE30US")))   ; already in percent points
(display "  MORTGAGE30US: ") (display note-rate-percent) (display "%  (as of ")
(display (first (latest mortgage30us "MORTGAGE30US"))) (display ")") (newline)

; The spread of mortgage rates over the 10-year yield: today's mortgage rate less the curve's 10-year par yield.
; A paths' mortgage rate is that yield plus this spread, so that it starts at today's mortgage rate.
(define mortgage-spread (- (/ note-rate-percent 100.0) (par-yield 10)))
(display "  over the curve's 10-year yield: ") (display mortgage-spread) (newline)

; --- 6. simulate Monte Carlo mortgage-rate paths off the fitted model ---

(define n-scenario-paths 100)   ; turned down for a quicker first run --
                                 ; see this file's header comment
(define horizon-years 30)

(display "Simulating ") (display n-scenario-paths) (display " mortgage-rate paths over ")
(display horizon-years) (display " years...") (newline)
(define sim (sofr-simulate-mortgage-rate-paths
              treasury-forwards fitted-sigma1 fitted-sigma2 horizon-years n-scenario-paths
              mortgage-spread :seed 42 :a fitted-a))
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
(define scaled-path-cashflows (map (lambda (cf) (vector-mul cf price-scale)) path-cashflows))

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

  (display "Treasury par yield curve (Treasury, as of ") (display treasury-day) (display "):") (newline)
  (display "  2y=") (display (par-yield 2)) (display "  5y=") (display (par-yield 5))
  (display "  10y=") (display (par-yield 10)) (display "  30y=") (display (par-yield 30)) (newline)
  (display "  forward rate, month 1:   ") (display (vector-ref treasury-forwards 0)) (newline)
  (display "  forward rate, month 60:  ") (display (vector-ref treasury-forwards 59)) (newline)
  (display "  forward rate, month 120: ") (display (vector-ref treasury-forwards 119)) (newline)
  (display "  forward rate, month 360: ") (display (vector-ref treasury-forwards 359)) (newline) (newline)

  (display "SOFR futures curve and options (tastytrade):") (newline)
  (display "  ") (display (length curve-futures-rows)) (display " contracts, real curve out to month ")
  (display real-months) (display "; ") (display (length sofr-option-rows)) (display " SOFR futures options") (newline)
  (display "10-year note future options (tastytrade): ") (display (length note-rows)) (display " options") (newline) (newline)

  (display "Calibrated two-factor model parameters (fit against the options above):") (newline)
  (display "  a (mean-reversion speed)        = ") (display fitted-a) (newline)
  (display "  sigma1 (short-rate factor vol)  = ") (display fitted-sigma1) (newline)
  (display "  sigma2 (level factor vol)       = ") (display fitted-sigma2) (newline)
  (display "  error (relative volatility)     = ") (display fitted-error) (newline) (newline)

  (display "Historical-volatility cross-check (FRED, last ") (display vol-window-days)
  (display " business days):") (newline)
  (display "  DFF-implied annualized short-rate vol = ") (display historical-vol-short)
  (display "   (fitted sigma1 = ") (display fitted-sigma1) (display ")") (newline)
  (display "  DGS10-implied annualized level vol    = ") (display historical-vol-level)
  (display "   (fitted sigma2 = ") (display fitted-sigma2) (display ")") (newline) (newline)

  (display "Current 30-year mortgage rate (FRED MORTGAGE30US, as of ")
  (display (first (latest mortgage30us "MORTGAGE30US"))) (display "): ")
  (display note-rate-percent) (display "%") (newline)
  (display "  its spread over the curve's 10-year par yield: ") (display mortgage-spread) (newline) (newline)

  (display "--- ASSUMPTIONS (not fetched) ---") (newline) (newline)

  (display "Loan: initial balance $") (display initial-balance)
  (display ", ") (display n-months) (display "-month term, ")
  (display psa-speed) (display "% PSA prepayment speed") (newline)
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
