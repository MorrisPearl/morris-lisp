; oas_monte_carlo.lsp
;
; Option-Adjusted Spread (OAS), computed the standard way: simulate many
; interest-rate paths (term_structure_model.py's two-factor model, via
; sofr-simulate-rate-paths / sofr-simulate-mortgage-rate-paths), discount
; a security's cashflows along each path using that path's own rates
; PLUS a trial spread, average the discounted values across paths to get
; a model price, then solve (by bisection) for whichever spread makes
; that model price match the security's actual market price. The
; resulting spread is the OAS -- the extra yield the security offers
; over the risk-free curve once the value of its embedded rate-optionality
; (here: prepayment risk) has been stripped out.
;
; This is the same discounting convention term_structure_model.py's own
; price_callable_bond_mc() uses for a callable bond, generalized here to
; an arbitrary cashflow vector (so it works for a mortgage pool too) and
; extended to SOLVE for the OAS instead of taking it as an input --
; price_callable_bond_mc()'s docstring explicitly flags that direction as
; unimplemented; oas-solve, below, is that missing piece, done in Lisp
; rather than added to the Python model.
;
; Three independent pieces, usable on their own:
;   1. annualized-realized-vol -- a historical-data cross-check for the
;      sigma1/sigma2 volatilities sofr-calibrate-model fits, or for a
;      quick sanity check when you don't have SOFR futures options handy
;      at all.
;   2. path-present-value / oas-model-price / oas-solve -- the generic
;      Monte Carlo OAS engine (works on ANY monthly cashflow vector, not
;      just mortgages).
;   3. simple-mortgage-cashflows -- a fast, direct (not column_engine.lsp
;      -based) per-path cashflow generator for a single fixed-rate,
;      prepaying mortgage, reusing prepayment_model.lsp's CPR/SMM. Kept
;      OUT of column_engine.lsp deliberately: an OAS run needs one
;      cashflow vector per Monte Carlo path (hundreds to thousands), and
;      column_engine.lsp's registry/topological-sort/global-rebinding
;      machinery -- built for readability on a SINGLE calculated table --
;      would make that needlessly slow. This does NOT touch
;      mortgage_amortization_example.lsp or tranche.lsp -- those are a
;      richer, single-path CMO/tranche waterfall; this is a narrower,
;      many-paths-fast pricer for one pass-through cashflow stream.
;
; See oas_monte_carlo_example.lsp for a worked end-to-end run (curve
; extension -> historical-vol cross-check -> path simulation -> cashflow
; generation -> OAS solve).

(load "prepayment_model.lsp")

; --- 1. historical-volatility cross-check --------------------------------

; (annualized-realized-vol rate-levels periods-per-year) -> a decimal
; annualized volatility, in the SAME units as sofr-calibrate-model's
; fitted sigma1/sigma2 -- both are the standard deviation, per
; sqrt(year), of ABSOLUTE (not log, not percentage) changes in a short
; rate, since that's the diffusion term's own units in
; term_structure_model.py's SDE (dr = a*(theta-r)*dt + sigma1*sqrt(dt)*dW,
; sigma1 multiplying an ABSOLUTE rate change). So this deliberately does
; NOT take log-differences (the usual choice for a price series) --
; interest rates can sit near zero or go negative, where log-differences
; break down, and the model being cross-checked isn't diffusing in log-
; rate space anyway.
;
; rate-levels: a vector of a rate observed at evenly-spaced times (e.g.
;     monthly), as DECIMALS (0.045, not 4.5).
; periods-per-year: how many observations per year rate-levels has (12
;     for monthly data, 252 for daily, 4 for quarterly, ...).
;
; WORKED EXAMPLE (not run automatically here -- needs a FRED API key; see
; fred_example.lsp): a rough real-world cross-check for sofr-calibrate-
; model's sigma1 (the short-rate factor, which moves fastest) is FRED's
; DFF (the daily effective fed funds rate, a long history); a rough cross
; check for sigma2 (the slower mean-reversion-LEVEL factor) is FRED's
; DGS10 (the 10-year Treasury yield, a proxy for where the "long-run
; level" the short rate reverts to has itself been drifting). Neither is
; a rigorous substitute for calibrating against real SOFR futures option
; prices (sofr-calibrate-model) -- these are single free-standing rate
; series, not the two-factor model's own latent state -- but they're a
; fast, no-options-data-needed sanity check that a fitted sigma1/sigma2
; is at least the right ORDER OF MAGNITUDE:
;   (define dff (fred-series "DFF" api-key))
;   (define dff-annual-vol (annualized-realized-vol (cdr dff) 252))
(define (annualized-realized-vol rate_levels periods_per_year)
  (define n (vector-length rate_levels))
  (define diffs (vector-sub (vector-drop rate_levels 1) (vector-take rate_levels (- n 1))))
  (define count (vector-length diffs))
  (define mean_diff (/ (vector-sum diffs) count))
  (define centered (vector-map (lambda (d) (- d mean_diff)) diffs))
  (define sum_sq (vector-sum (vector-map (lambda (d) (* d d)) centered)))
  (define sample_variance (/ sum_sq (- count 1)))   ; n-1: sample (not population) variance
  (* (sqrt sample_variance) (sqrt periods_per_year)))

; --- 2. Monte Carlo OAS engine --------------------------------------------

; (path-present-value cashflows short-rate-path oas) -> a number.
; cashflows: a vector, one entry per month, months 1..N (index 0 is
;     month 1's cashflow).
; short-rate-path: a vector of at least N simulated short rates -- one
;     Monte Carlo PATH from sofr-simulate-rate-paths'/sofr-simulate-
;     mortgage-rate-paths' short-rate-paths list (index k is the rate
;     prevailing at the START of month k+1 -- the same start-of-period
;     convention term_structure_model.py's price_callable_bond_mc() uses
;     via r_paths[:, :-1]).
; oas: a constant DECIMAL spread (e.g. 0.005 for 50bp) added to every
;     month's discount rate before discounting -- exactly
;     price_callable_bond_mc()'s `oas` argument.
;
; Discounts month m's cashflow by DF(0,m) = the product of monthly
; factors 1/(1+(rate+oas)/12) over rate-path indices 0..m-1 -- the same
; cum_df[:, m-1] convention price_callable_bond_mc() uses, so oas-solve
; below reproduces exactly what that function would report if you fed it
; the OAS this solves for.
(define (path-present-value cashflows short_rate_path oas)
  (define n (vector-length cashflows))
  (define (step m cum_df pv)
    (if (> m n)
        pv
        (let* ((rate (vector-ref short_rate_path (- m 1)))
               (monthly_factor (/ 1.0 (+ 1.0 (/ (+ rate oas) 12.0))))
               (new_cum_df (* cum_df monthly_factor))
               (cf (vector-ref cashflows (- m 1))))
          (step (+ m 1) new_cum_df (+ pv (* cf new_cum_df))))))
  (step 1 1.0 0.0))

; (oas-model-price cashflows rate-paths oas) -> a number -- the Monte
; Carlo model price: path-present-value averaged across every path in
; rate-paths (a Lisp LIST of vectors, e.g. sofr-simulate-rate-paths'
; short-rate-paths return value, or one path per scenario you built
; yourself).
;
; cashflows may be EITHER a single vector (used, unchanged, against every
; path -- right for an ordinary fixed-coupon bond, whose cashflow dates
; and amounts don't depend on the rate scenario) OR a Lisp LIST of
; vectors, one per path in the SAME order as rate-paths (right for a
; prepaying mortgage, whose cashflows themselves depend on that path's
; own rate incentive -- see simple-mortgage-cashflows /
; mortgage-cashflows-per-path, below).
(define (oas-model-price cashflows rate_paths oas)
  (define prices (oas--present-values cashflows rate_paths oas))
  (/ (reduce + prices 0.0) (length prices)))

(define (oas--present-values cashflows rate_paths oas)
  (if (vector? cashflows)
      (map (lambda (path) (path-present-value cashflows path oas)) rate_paths)
      (oas--present-values-paired cashflows rate_paths oas)))

(define (oas--present-values-paired cashflow_list rate_path_list oas)
  (if (or (null? cashflow_list) (null? rate_path_list))
      '()
      (cons (path-present-value (car cashflow_list) (car rate_path_list) oas)
            (oas--present-values-paired (cdr cashflow_list) (cdr rate_path_list) oas))))

; (oas-solve cashflows rate-paths target-price [&key oas_lo oas_hi
;  tolerance max_iter]) -> a decimal spread -- bisects for the OAS whose
; oas-model-price matches target-price (the security's actual market
; price), since oas-model-price is monotonically DECREASING in oas (a
; wider spread means a bigger discount rate means a lower price, for any
; ordinary positive cashflow stream).
;
; target-price: the security's real market price (same face/scale as
;     cashflows -- e.g. per 100 face, matching price_callable_bond_mc's
;     convention, if cashflows was built that way).
; oas_lo / oas_hi: the search bracket, decimals -- defaults -0.05/0.20
;     (-500bp to +2000bp) comfortably covers ordinary MBS/corporate
;     spreads; widen if target-price is very far from par.
; tolerance: stop once the model price is within this of target-price
;     (same units as target-price, e.g. 0.01 for a cent per 100 face).
; max_iter: hard cap on bisection steps, in case the bracket doesn't
;     actually contain a root (see the error raised below).
;
; Raises a LispError up front if target-price isn't between
; oas-model-price at oas_lo and at oas_hi -- a silent wrong answer from a
; bisection outside its bracket is worse than an early, clear failure.
(define (oas-solve cashflows rate_paths target_price
                    &key (oas_lo -0.05) (oas_hi 0.20) (tolerance 0.01) (max_iter 60))
  (define price_at_lo (oas-model-price cashflows rate_paths oas_lo))
  (define price_at_hi (oas-model-price cashflows rate_paths oas_hi))
  (if (or (< price_at_lo price_at_hi) (> target_price price_at_lo) (< target_price price_at_hi))
      (error "oas-solve: target-price" target_price
             "is not bracketed by oas-model-price at oas_lo/oas_hi --"
             "price(oas_lo)=" price_at_lo "price(oas_hi)=" price_at_hi
             "-- widen oas_lo/oas_hi"))
  (define (bisect lo hi iter)
    (if (>= iter max_iter)
        (/ (+ lo hi) 2.0)
        (let* ((mid (/ (+ lo hi) 2.0))
               (price (oas-model-price cashflows rate_paths mid)))
          (if (< (abs (- price target_price)) tolerance)
              mid
              (if (> price target_price)
                  (bisect mid hi (+ iter 1))    ; price too high -> raise oas
                  (bisect lo mid (+ iter 1))))))) ; price too low -> lower oas
  (bisect oas_lo oas_hi 0))

; --- 3. a fast, direct mortgage cashflow generator ------------------------

; (simple-mortgage-cashflows initial-balance note-rate-percent n-months
;  psa-speed market-rate-path) -> a vector of length n-months, one total
; cashflow (interest + scheduled principal + prepayment) per month.
;
; A standard fixed-rate, level-pay, PSA-prepaying pass-through: the
; ORIGINAL fixed payment (computed once, from the full n-months term) is
; never recomputed, so prepayments shrink the balance faster than
; scheduled but don't change the payment amount -- exactly
; mortgage_amortization_example.lsp's own convention, just computed
; directly here (one vector-set! per month) instead of through
; column_engine.lsp's per-row registry machinery, since an OAS run needs
; this generated once per Monte Carlo path.
;
; initial-balance: loan balance at month 0.
; note-rate-percent: the loan's fixed coupon, in PERCENT POINTS (e.g.
;     6.00) -- matches prepayment_model.lsp's incentive_points units.
; n-months: the amortization term AND the number of cashflows generated
;     -- this function does not support a loan term different from the
;     simulation horizon; truncate/extend market-rate-path to the term
;     you want first.
; psa-speed: fed straight through to prepayment_model.lsp's `cpr` as its
;     psa_speed argument (100 = standard 100% PSA).
; market-rate-path: a DECIMAL rate vector (e.g. one row of sofr-simulate-
;     mortgage-rate-paths' mortgage-paths, or ten-year-paths/underlying-
;     paths) of length >= n-months, index k = the market rate prevailing
;     at the START of month k+1 -- multiplied by 100 here before being
;     compared to note-rate-percent, since the two are in different unit
;     conventions upstream (term_structure_model.py works in decimals
;     throughout; prepayment_model.lsp's incentive_points is in percent
;     points) and mixing them un-converted would silently understate the
;     refinancing incentive by a factor of 100.
;
; WALA (loan age, in months) at month j's calculation is (j - 1) -- the
; loan is 0 months seasoned when its first payment (month 1) is
; calculated, matching prepayment_model.lsp's psa-base-cpr ramping up
; from WALA 0.
(define (simple-mortgage-cashflows initial_balance note_rate_percent n_months psa_speed market_rate_path)
  (define periodic_rate (/ note_rate_percent 1200.0))
  (define d_factor (pow (+ periodic_rate 1.0) n_months))
  (define payment (* initial_balance (/ (* periodic_rate d_factor) (- d_factor 1.0))))
  (define cashflows (make-vector n_months))
  (define (step balance j)
    (if (> j n_months)
        cashflows
        (let* ((wala (- j 1))
               (market_rate_percent (* 100.0 (vector-ref market_rate_path wala)))
               (incentive (- note_rate_percent market_rate_percent))
               (cpr_value (cpr wala psa_speed :incentive_points incentive))
               (smm (smm-from-cpr cpr_value))
               (interest (* balance periodic_rate))
               (scheduled_principal (min balance (- payment interest)))
               (prepayment (* smm (- balance scheduled_principal)))
               (total_principal (min balance (+ scheduled_principal prepayment)))
               (cashflow (+ interest total_principal))
               (new_balance (- balance total_principal)))
          (vector-set! cashflows (- j 1) cashflow)
          (step new_balance (+ j 1)))))
  (step initial_balance 1))

; (mortgage-cashflows-per-path initial-balance note-rate-percent n-months
;  psa-speed market-rate-paths) -> a Lisp LIST of cashflow vectors, one
; per entry in market-rate-paths, in the SAME order -- runs simple-
; mortgage-cashflows once per path, so each path's prepayment speed
; responds to that path's own simulated rate incentive. Feed straight
; into oas-model-price/oas-solve as `cashflows`, paired against the SAME
; rate-paths list market-rate-paths came from (see oas_monte_carlo_
; example.lsp): market-rate-paths would typically be sofr-simulate-
; mortgage-rate-paths' mortgage-paths, and the matching rate-paths
; argument to oas-model-price/oas-solve its short-rate-paths -- same
; list, same path order, so entry i lines up in both.
(define (mortgage-cashflows-per-path initial_balance note_rate_percent n_months psa_speed market_rate_paths)
  (if (null? market_rate_paths)
      '()
      (cons (simple-mortgage-cashflows initial_balance note_rate_percent n_months psa_speed
                                        (car market_rate_paths))
            (mortgage-cashflows-per-path initial_balance note_rate_percent n_months psa_speed
                                          (cdr market_rate_paths)))))
