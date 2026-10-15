; option_spreads_example.lsp
;
; Which spread is best, if you expect a stock to be at a certain price when
; its options expire? Of the stock's options that expire on one day, it builds
; every spread of one kind -- a vertical spread (bull call, bear call, bull
; put, bear put), a butterfly, an iron condor or iron butterfly, a straddle or
; a strangle -- and ranks them by the profit at the price you expect, as a
; share of the most you can lose. lib/option_spreads.lsp does the work, and
; says how; (option-spread-kinds) lists the kinds.
;
; Give it the stock, the kind of spread, the expiration day, and the price you
; expect:
;   python3 ../lisp_interpreter.py option_spreads_example.lsp SPY iron-condor 2026-11-20 765
; Run it from the examples directory, while the market is open, when the bids
; and asks are live. It needs a Schwab sign-in ((schwab-login creds); it lasts
; a week): creds is set to the credentials file's path in init.lsp.
;
; It shows the best spreads, and two charts of their profit on the expiration
; day (up the side) against the price the stock might have then (along the
; bottom): the best one in detail, in option_spreads_profit.png, and the best
; three on one chart to compare, in option_spreads_compared.png (in a notebook
; or the GUI they are drawn too). It sends no order. To go on to trade the
; best, in a notebook or at the console:
;   (load "option_spreads.lsp")
;   (define search (option-spreads creds "SPY" 'iron-condor (date 2026 11 20) 765))
;   (define order (option-spread-order search :contracts 1))   ; sends nothing
;   (schwab-preview-order creds "your account" order)           ; what Schwab makes of it; places nothing
;   (schwab-place-order creds "your account" order :confirm #t)   ; places it, for real

(load "option_spreads.lsp")

(define arguments (command-line-arguments))
(when (< (length arguments) 4)
  (error "Give the stock, the kind of spread, the expiration day, and the price you expect, such as: SPY iron-condor 2026-11-20 765"))

(define search (option-spreads creds (first arguments) (string->symbol (second arguments))
                              (string->date (third arguments))
                              (string->number (fourth arguments))))
(show-option-spreads search)

(define positions (table-row-count (spread-search-spreads search)))
(when (> positions 0)
  (plot-option-profit search)
  (save-chart "option_spreads_profit.png"))
(when (> positions 1)
  (plot-option-profit search :rows (iota (min positions 3)))
  (save-chart "option_spreads_compared.png"))
