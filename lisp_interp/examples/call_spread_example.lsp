; call_spread_example.lsp
;
; Which call spread is best, if you expect a stock to be at a certain price
; when its options expire? Of the stock's calls that expire on one day, it
; buys the one with the lower strike and sells the one with the higher, and
; ranks every pair by the profit at the price you expect, as a share of the
; most you can lose (what the pair costs). lib/call_spreads.lsp does the
; work, and says how.
;
; Give it the stock, the expiration day, and the price you expect:
;   python3 ../lisp_interpreter.py call_spread_example.lsp SPY 2026-11-20 765
; Run it from the examples directory, while the market is open, when the bids
; and asks are live. It needs a Schwab sign-in ((schwab-login creds); it lasts
; a week): creds is set to the credentials file's path in init.lsp.
;
; It shows the best spreads and sends no order. To go on to trade the best,
; in a notebook or at the console:
;   (load "call_spreads.lsp")
;   (define search (call-spreads creds "SPY" (date 2026 11 20) 765))
;   (define order (call-spread-order search :contracts 1))   ; sends nothing
;   (schwab-preview-order creds "your account" order)         ; what Schwab makes of it; places nothing
;   (schwab-place-order creds "your account" order :confirm #t)   ; places it, for real

(load "call_spreads.lsp")

(define arguments (command-line-arguments))
(when (< (length arguments) 3)
  (error "Give the stock, the expiration day, and the price you expect, such as: SPY 2026-11-20 765"))

(show-call-spreads (call-spreads creds (first arguments) (string->date (second arguments))
                                 (string->number (third arguments))))
