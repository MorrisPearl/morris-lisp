; trade_scenario_example.lsp
;
; A scenario -- a stock, or a future, at a price on a date -- and every way of trading on it with options: every
; position of nineteen kinds (spreads, butterflies, condors, single options, positions with shares, and calendar
; spreads), of every expiration on or after the date, valued on the date and ranked by the profit if you are right,
; for the money it commits. lib/trade_scenario.lsp does the work, and says how.
;
; Give it the stock or the future's code, the price, and the date:
;   python3 ../lisp_interpreter.py trade_scenario_example.lsp CL 70 2026-12-01
;   python3 ../lisp_interpreter.py trade_scenario_example.lsp AAPL 380 2026-12-18
; Run it from the examples directory. It needs a tastytrade account (creds, in init.lsp); the quotes are live while
; the market is open, and the last close's when it isn't. It sends no order.

(define arguments (command-line-arguments))
(when (< (length arguments) 3)
  (error "Give the stock or the future's code, the price, and the date, such as: CL 70 2026-12-01"))

(define scenario (trade-scenario creds (first arguments) (string->number (second arguments)) (string->date (third arguments))))
(show-trade-scenario scenario)
