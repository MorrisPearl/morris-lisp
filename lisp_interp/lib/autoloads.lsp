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
  widget-slider widget-button widget-dropdown widget-checkbox widget-text widget-output widget-column widget-row)

; Templates of text and SQL
(lazy-load "template.lsp"
  template-parse template-render template-render-sql sqlite-query-template sqlite-execute-template)

; A fitted model as a function
(lazy-load "model_utils.lsp" model->function)
