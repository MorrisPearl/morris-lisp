; option_methods_example.lsp
;
; Three ways to value an option -- Black-Scholes, a binomial tree, and Monte
; Carlo paths copied from the stock's own history -- on the options listed
; on a stock, next to the market's bids and asks, and the chance each one
; ends in the money by each. lib/option_methods.lsp does the work, and says
; how.
;
; Give it the stock's symbol after the file's name (BRK/B, if there's none):
;   python3 ../lisp_interpreter.py option_methods_example.lsp KO
; Run it from the examples directory, while the market is open, when the
; bids and asks are live. It needs a tastytrade sign-in (the options), a
; Schwab sign-in ((schwab-login creds); it lasts a week) for the prices,
; and an Alpha Vantage key for the dividends: creds is set to the
; credentials file's path in init.lsp.
;
; In a notebook, or to try other settings, use the library itself:
;   (load "option_methods.lsp")
;   (show-option-methods (option-methods creds "KO" :months 6 :rate 0.045))

(load "option_methods.lsp")

(destructuring-bind (&optional (symbol "BRK/B")) (command-line-arguments)
  (show-option-methods (option-methods creds symbol)))
