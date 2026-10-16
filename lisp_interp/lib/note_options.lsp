; note_options.lsp
;
; Options on the 10-year note future (ZN), shaped for the interest-rate model.
;
; The model of interest rates (sofr-calibrate-model) is fitted to SOFR futures
; options, which show how much the SHORT rate moves. A mortgage depends on
; the LONG end, and a 10-year note option says how much that moves. The
; builtins sofr-calibrate-note-options, sofr-calibrate-jointly and
; sofr-note-option-comparison fit and check the model against those options:
; see "Options on the 10-year note future" in lisp_library_reference.md.
; What this file does is the small step before them: the chain of options,
; as tastytrade-option-chain gives it, as the rows they read.
;
; Usage:
;   (define chain (tastytrade-option-chain creds "ZN" 12 12))
;   (define rows (note-option-rows chain))               ; (type strike days futures-price market-price)
;   (define forwards (table-column (curve-forward-rates (treasury-zero-curve (treasury-par-curve))) "forward"))
;   (define fit (sofr-calibrate-note-options forwards rows))
;   (cdr (assoc 'sigma2 fit))                            ; the volatility of the long end, as 0.0134
;   (sofr-note-option-comparison forwards rows 0.01 (cdr (assoc 'sigma2 fit)))   ; the model's prices and the market's

(define (note-option-rows chain &key (day (today)) (min-days 7) (max-days 400))
  "The options of a chain (a table, as tastytrade-option-chain gives it) as rows (type strike days futures-price
market-price) for the note-option builtins: the type \"call\" or \"put\", the strike, the days from :day (today) to the
option's expiry, the price of the future the option is on, and the price of the option, the middle of its bid and ask.
Options with no bid or no ask (no price to speak of), and those with fewer than :min-days (7) or more than :max-days
(400) days to expiry, are left out: an option of a few days is priced on the next few days' news more than on how
the rates move, and its quotes are the thinnest."
  (let ((types (table-column chain "type"))
        (strikes (table-column chain "strike"))
        (expirations (table-column chain "expiration-date"))
        (futures-prices (table-column chain "underlying-price"))
        (bids (table-column chain "bid"))
        (asks (table-column chain "ask")))
    (loop for i from 0 below (table-row-count chain)
          for days = (days-between day (vector-ref expirations i))
          when (and (> (vector-ref bids i) 0) (> (vector-ref asks i) 0) (>= days min-days) (<= days max-days))
            collect (list (string-downcase (vector-ref types i))
                          (vector-ref strikes i)
                          days
                          (vector-ref futures-prices i)
                          (/ (+ (vector-ref bids i) (vector-ref asks i)) 2.0)))))
