; autoloads.lsp
;
; The functions of the libraries that come with the interpreter (lib/), so
; that they can be called without loading the library first: each is a
; lazy-load (see macros_init.lsp), and the first call of any of a
; library's functions loads it. init.lsp loads this file:
;
;   (load "autoloads.lsp")
;
; Only functions can be lazy-loaded -- not a library's macros or variables
; -- so a library is still loaded by hand for those: column_engine.lsp (its
; defcolumn and lag are macros), template.lsp's template-bindings macro,
; parser.lsp's define-grammar macro,
; and variables such as option-check-formats and vol-smile-formats. When a
; library gets a new function that should be called from outside it, add
; it here; the tests check that each library defines the names listed for
; it.

; Implied volatility smiles (see "Implied volatility smiles" in lisp_library_reference.md)
(lazy-load "vol_smile.lsp"
  fit-vol-smiles show-vol-smiles plot-vol-smile parity-forward
  vol-smile-fit-options vol-smile-fit-expirations vol-smile-fit-models)

; Option prices checked against simulated paths
(lazy-load "option_check.lsp"
  check-option-prices check-option-chain show-option-check option-check-expirations)

; Options valued three ways
(lazy-load "option_methods.lsp"
  option-methods option-methods-for-chain show-option-methods option-methods-summary
  option-values-options option-values-symbol option-values-price option-values-volatility
  option-values-rate option-values-paths)

; Parsers for small languages (see "A parser framework" in lisp_interpreter_reference.md)
(lazy-load "parser.lsp"
  make-grammar grammar-parse grammar-tokens node-builder)

; Option spreads: the best vertical spread, butterfly, iron condor, straddle, or strangle, single option, or
; position with shares, for the price you expect, and the order for it
(lazy-load "option_spreads.lsp"
  option-spreads option-spreads-for-chain option-spread-kinds show-option-spreads option-spread-order
  option-position-orders show-spread-order spread-search-kind spread-search-stock spread-search-stock-price
  spread-search-expiration spread-search-expected-price spread-search-prices spread-search-contract-size
  spread-search-unit spread-search-spreads
  option-profit-curve plot-option-profit option-profit-panel)

; Option positions: the best position of each of those kinds, and owning the stock, ranked together
(lazy-load "option_positions.lsp"
  option-positions option-positions-for-chain show-option-positions plot-option-positions position-comparison-search
  position-comparison-stock position-comparison-stock-price position-comparison-expiration
  position-comparison-expected-price position-comparison-prices position-comparison-contract-size
  position-comparison-unit position-comparison-positions position-comparison-searches)

; Yield curves: the Treasury's par curve and the Fed's fitted curve, zero rates and forward rates
(lazy-load "yield_curves.lsp"
  treasury-par-curve treasury-zero-curve par-curve-zeros curve-forward-rates extend-forward-curve gsw-curve
  gsw-parameters gsw-zero-curve
  svensson-zero-rates svensson-forward-rates)

; Options on the 10-year note future (ZN), as the rows the rate model is fitted to
(lazy-load "note_options.lsp" note-option-rows)

; Call spreads: the best pair of calls to buy and sell (the bull-call kind of the above), and the order for it
(lazy-load "call_spreads.lsp"
  call-spreads call-spreads-for-chain show-call-spreads call-spread-order plot-call-spreads)

; Mortgages: the OAS Monte Carlo, and the prepayment model it uses
(lazy-load "oas_monte_carlo.lsp"
  oas-model-price oas-solve annualized-realized-vol path-present-value
  simple-mortgage-cashflows mortgage-cashflows-per-path)
(lazy-load "prepayment_model.lsp"
  cpr smm-from-cpr psa-base-cpr incentive-bump-cpr)

; Root finding and minimizing
(lazy-load "solver.lsp" ridders nelder-mead)

; Reports with control breaks: a table written as a text report, with a header, footer and totals for each group, and pages
(lazy-load "report.lsp"
  write-report write-report-html report-text make-report-spec report-spec? copy-report-spec make-report-break report-break?
  copy-report-break report-spec-report-header report-spec-report-footer report-spec-page-header
  report-spec-page-footer report-spec-page-lines report-spec-page-separator report-spec-detail report-spec-breaks
  report-spec-summaries report-spec-running report-spec-variables report-spec-detail-order report-spec-presorted report-spec-markdown report-spec-formats
  report-spec-report-header-set! report-spec-report-footer-set! report-spec-page-header-set!
  report-spec-page-footer-set! report-spec-page-lines-set! report-spec-page-separator-set! report-spec-detail-set!
  report-spec-breaks-set! report-spec-summaries-set! report-spec-running-set! report-spec-variables-set! report-spec-detail-order-set!
  report-spec-presorted-set! report-spec-markdown-set! report-spec-formats-set! report-break-field report-break-header report-break-footer report-break-new-page
  report-break-restart-page-numbers report-break-repeat-header report-break-field-set! report-break-header-set! report-break-footer-set!
  report-break-new-page-set! report-break-restart-page-numbers-set! report-break-repeat-header-set!)

; The common widgets of a notebook, one call each (the others are made with make-widget)
(lazy-load "widgets.lsp"
  widget-slider widget-button widget-dropdown widget-checkbox widget-text widget-output widget-column widget-row widget-visible
  widget-actions widget-actions-heading widget-actions-set! widget-actions-answers widget-actions-select
  widget-actions-clear widget-actions-button-label!)

; Prepayment speeds that change with time, and the cash flows of pieces of collateral (see "The collateral" in lisp_cmo_manual.md)
(lazy-load "prepayment_speed.lsp"
  collateral-piece-check collateral-pieces-in-use copy-speed-curve make-speed-curve pool-coupons prepayment-speed
  project-pieces project-pool speed-curve-pieces speed-curve-pieces-set! speed-curve-type speed-curve-type-set!
  speed-curve? speed-in-month speed-piece-of speed-smms speed-values describe-speed piece-age piece-wam)

; Structured deals as a tree: a pool, divided by splits into tranches (see lisp_cmo_manual.md)
(lazy-load "deal.lsp"
  start-deal deal-add-collateral! collateral-from-psa constant-coupon deal-sequential! deal-pro-rata! deal-pac!
  deal-floater-inverse! deal-premium-discount! deal-io-po! deal-add-tranche! deal-add-split! deal-add-node!
  deal-forget-node! get-node deal-run! deal-check deal-principal-table deal-interest-table deal-accrual-table
  deal-loss-table deal-shortfall-table deal-coupon-table deal-balance-table deal-leaves deal-root-of deal-parent-of
  deal-po? deal-tree-names deal-index-at pool-cash-flows node-owed node-remaining pay-child! write-down-child!
  settle-interest! node-interest-owed node-coupon-rate node-interest-due check-all-paid! check-all-written-down!
  walk-principal! walk-interest! walk-losses! deal-principal-at deal-size deal-children-names check-loss-rule
  check-parent-not-z child-tranche collateral-accrual collateral-accrual-set! collateral-age collateral-age-set!
  collateral-balance collateral-balance-set! collateral-coupon collateral-coupon-set! collateral-follows
  collateral-follows-set! collateral-interest collateral-interest-set! collateral-loss collateral-loss-set!
  collateral-name collateral-name-set! collateral-notional-flag collateral-notional-flag-set! collateral-principal
  collateral-principal-set! collateral-psa collateral-psa-set! collateral-rate collateral-rate-set! collateral-share
  collateral-share-set! collateral-shortfall collateral-shortfall-set! collateral-split collateral-split-set!
  collateral-term collateral-term-set! collateral-z-flag collateral-z-flag-set! collateral? copy-collateral copy-deal
  copy-floater-inverse-split copy-io-po-split copy-node copy-pac-split copy-premium-discount-split copy-pro-rata-split
  copy-sequential-split copy-split copy-tranche deal-check-new-children deal-check-total deal-collateral-for
  deal-index deal-index-set! deal-name deal-name-set! deal-names deal-names-set! deal-nodes deal-nodes-set!
  deal-periods deal-periods-set! deal-roots deal-roots-set! deal-run-months! deal-set-index! deal-shortfalls
  deal-shortfalls-set! deal-table-of deal? floater-inverse-sizes floater-inverse-split-cap
  floater-inverse-split-cap-set! floater-inverse-split-children floater-inverse-split-children-set!
  floater-inverse-split-constant floater-inverse-split-constant-set! floater-inverse-split-index-name
  floater-inverse-split-index-name-set! floater-inverse-split-leverage floater-inverse-split-leverage-set!
  floater-inverse-split-loss-rule floater-inverse-split-loss-rule-set! floater-inverse-split-margin
  floater-inverse-split-margin-set! floater-inverse-split? index-rate interest-carried io-po-split-children
  io-po-split-children-set! io-po-split-io-coupon io-po-split-io-coupon-set! io-po-split-loss-rule
  io-po-split-loss-rule-set! io-po-split? make-collateral make-deal make-floater-inverse-split make-io-po-split
  make-node make-pac-split make-premium-discount-split make-pro-rata-split make-sequential-split make-split
  make-tranche node-accrual node-accrual-set! node-balance node-balance-set! node-coupon node-coupon-set! node-follows
  node-follows-set! node-interest node-interest-set! node-loss node-loss-set! node-name node-name-set!
  node-notional-flag node-notional-flag-set! node-principal node-principal-set! node-share node-share-set!
  node-shortfall node-shortfall-set! node-split node-split-set! node-z-flag node-z-flag-set! node? pac-check-arguments
  pac-split-children pac-split-children-set! pac-split-high-psa pac-split-high-psa-set! pac-split-loss-rule
  pac-split-loss-rule-set! pac-split-low-psa pac-split-low-psa-set! pac-split-schedule pac-split-schedule-set!
  pac-split? parent-coupon-rate premium-discount-sizes premium-discount-split-children
  premium-discount-split-children-set! premium-discount-split-discount-coupon
  premium-discount-split-discount-coupon-set! premium-discount-split-loss-rule premium-discount-split-loss-rule-set!
  premium-discount-split-premium-coupon premium-discount-split-premium-coupon-set! premium-discount-split?
  pro-rata-split-children pro-rata-split-children-set! pro-rata-split-loss-rule pro-rata-split-loss-rule-set!
  pro-rata-split? sequential-split-accretion-to sequential-split-accretion-to-set! sequential-split-children
  sequential-split-children-set! sequential-split-loss-rule sequential-split-loss-rule-set! sequential-split?
  split-children split-children-set! split-loss-rule split-loss-rule-set! split? tranche-accrual tranche-accrual-set!
  tranche-balance tranche-balance-set! tranche-coupon tranche-coupon-set! tranche-follows tranche-follows-set!
  tranche-interest tranche-interest-set! tranche-loss tranche-loss-set! tranche-name tranche-name-set!
  tranche-notional-flag tranche-notional-flag-set! tranche-principal tranche-principal-set! tranche-share
  tranche-share-set! tranche-shortfall tranche-shortfall-set! tranche-split tranche-split-set! tranche-z-flag
  tranche-z-flag-set! tranche? copy-split-plan deal-add-plan! deal-outline deal-outline-below deal-outline-entries
  floater-inverse-plan io-po-plan make-split-plan pac-plan premium-discount-plan pro-rata-plan sequential-plan
  split-plan-sizes split-plan-split split-plan-split-set! split-plan-tranches split-plan-tranches-set! split-plan?
  deal-ancestors deal-delete-split! deal-install-plan! deal-replace-split! deal-resize-below! deal-size-split!
  deal-trial-copy deal-trial-of-plan deal-update-tranche! average-life average-life-plan average-life-sizes
  average-life-split-accretion-to average-life-split-accretion-to-set! average-life-split-children
  average-life-split-children-set! average-life-split-lives average-life-split-lives-set! average-life-split-loss-rule
  average-life-split-loss-rule-set! average-life-split? collateral-from-pieces collateral-pieces
  collateral-pieces-set! collateral-speed collateral-speed-set! copy-average-life-split coupon-at coupon-less
  deal-average-life deal-average-life! deal-first-payment deal-first-payment-set! deal-payment-date deal-payment-dates
  deal-principal-now deal-run-copy make-average-life-split range-life solve-for-size collateral-wac
  collateral-wac-set! collateral-table collateral-table-pieces deal-add-view! deal-assign-all-coupons!
  deal-assign-coupons-below! deal-change! deal-changed! deal-closing-date deal-closing-date-set! deal-collateral
  deal-collateral-set! deal-flows-table deal-generate-collateral! deal-install-collateral! deal-pad-flows
  deal-pricing-flows deal-pricing-speed deal-pricing-speed-set! deal-put-collateral-flows! deal-ran deal-ran-set!
  deal-root-pieces deal-set-closing-date! deal-set-collateral! deal-set-first-payment! deal-set-periods!
  deal-set-pricing-speed! deal-speed-for deal-summary-months deal-views deal-views-set! new-deal padded pieces-coupon)

; Building a deal by clicking in a notebook (see "Building a deal by clicking" in lisp_cmo_manual.md)
(lazy-load "deal_builder.lsp"
  copy-deal-gui copy-split-form deal-builder deal-gui-choose! deal-gui-chosen deal-gui-chosen-set! deal-gui-deal
  deal-gui-deal-set! deal-gui-forms deal-gui-forms-set! deal-gui-grid deal-gui-grid-set! deal-gui-messages
  deal-gui-messages-set! deal-gui-names deal-gui-names-set! deal-gui-panel deal-gui-panel-set! deal-gui-parent
  deal-gui-plan deal-gui-refresh! deal-gui-say deal-gui-show-sizes! deal-gui? form-answer form-children
  form-coupon-percent form-line form-losses form-name form-number form-optional-name form-percent-to-decimal
  make-deal-gui make-split-form split-form-defaults split-form-defaults-set! split-form-fields split-form-fields-set!
  split-form-help split-form-help-set! split-form-plan split-form-plan-set! split-form-title split-form-title-set!
  split-form? standard-split-forms deal-gui-apply! deal-gui-ask-whether-to-delete! deal-gui-button
  deal-gui-cancel-button deal-gui-cancel-button-set! deal-gui-confirm-button deal-gui-confirm-button-set!
  deal-gui-delete! deal-gui-delete-button deal-gui-delete-button-set! deal-gui-delete-row deal-gui-delete-row-set!
  deal-gui-form-for deal-gui-keep! deal-gui-offer-to-change! deal-gui-offer-to-divide! deal-gui-put-away!
  deal-gui-show-delete! form-children-text form-decimal-to-percent show-plan-effect split-form-describe
  split-form-describe-set! split-form-label split-form-label-set! without-traceback average-lives-of form-lives
  form-lives-text bonds deal-gui-flows deal-gui-flows-set! deal-gui-show-flows! deal-gui-table show-node-flows)

; Views of a deal in a notebook: its collateral, and its dates and pricing speed (see lisp_cmo_manual.md)
(lazy-load "deal_views.lsp"
  collateral collateral-gui-deal collateral-gui-deal-set! collateral-gui-grid collateral-gui-grid-set!
  collateral-gui-messages collateral-gui-messages-set! collateral-gui-page collateral-gui-page-set!
  collateral-gui-pieces collateral-gui-rows collateral-gui-rows-set! collateral-gui-show collateral-gui-table
  collateral-gui-update collateral-gui? copy-collateral-gui copy-info-gui date-from-text date-to-text
  grid-column-widths info info-gui-closing info-gui-closing-set! info-gui-deal info-gui-deal-set!
  info-gui-first-payment info-gui-first-payment-set! info-gui-messages info-gui-messages-set! info-gui-name
  info-gui-name-set! info-gui-show info-gui-speed-grid info-gui-speed-grid-set! info-gui-speed-type
  info-gui-speed-type-set! info-gui-update info-gui? info-speed-from-grid info-speed-table make-collateral-gui
  make-info-gui show-collateral-flows)

; Templates of text and SQL
(lazy-load "template.lsp"
  template-parse template-render template-render-sql sqlite-query-template sqlite-execute-template)

; A fitted model as a function
(lazy-load "model_utils.lsp" model->function)
