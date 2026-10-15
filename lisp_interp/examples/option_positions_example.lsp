; option_positions_example.lsp
;
; Which kind of position is best, if you expect a stock to be at a certain
; price when its options expire? For each of seventeen kinds -- a call, a put,
; a spread, a butterfly, a condor, a straddle, a covered call, a collar, ... --
; it finds the best position that can be made of the stock's options that
; expire on one day, and ranks the kinds by the profit at the price you
; expect, as a share of the most you can lose. Owning the stock is one of the
; kinds, so you can see what the options do for you, and what they cost.
; lib/option_positions.lsp does the work, and says how.
;
; Give it the stock, the expiration day, and the price you expect:
;   python3 ../lisp_interpreter.py option_positions_example.lsp SPY 2026-11-20 765
; Run it from the examples directory, while the market is open, when the bids
; and asks are live. It needs a Schwab sign-in ((schwab-login creds); it lasts
; a week): creds is set to the credentials file's path in init.lsp.
;
; It shows the ranking and sends no order. To look closer at one kind, and go
; on to trade the best of it, in a notebook or at the console:
;   (load "option_positions.lsp")
;   (define comparison (option-positions creds "SPY" (date 2026 11 20) 765))
;   (define search (position-comparison-search comparison 'covered-call))
;   (show-option-spreads search)                       ; the best few covered calls
;   (define orders (option-position-orders search))    ; the shares, then the call: sends nothing
;   (show-spread-order orders)                         ; the orders, in words
;   (dolist (order orders) (schwab-preview-order creds "your account" order))    ; places nothing

(load "option_positions.lsp")

(define arguments (command-line-arguments))
(when (< (length arguments) 3)
  (error "Give the stock, the expiration day, and the price you expect, such as: SPY 2026-11-20 765"))

(show-option-positions (option-positions creds (first arguments) (string->date (second arguments))
                                         (string->number (third arguments))))
