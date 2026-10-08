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

; Mortgages: the OAS Monte Carlo, and the prepayment model it uses
(lazy-load "oas_monte_carlo.lsp"
  oas-model-price oas-solve annualized-realized-vol path-present-value
  simple-mortgage-cashflows mortgage-cashflows-per-path)
(lazy-load "prepayment_model.lsp"
  cpr smm-from-cpr psa-base-cpr incentive-bump-cpr)

; Root finding and minimizing
(lazy-load "solver.lsp" ridders nelder-mead)

; Templates of text and SQL
(lazy-load "template.lsp"
  template-parse template-render template-render-sql sqlite-query-template sqlite-execute-template)

; A fitted model as a function
(lazy-load "model_utils.lsp" model->function)
