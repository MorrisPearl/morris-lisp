; vol_smile_example.lsp
;
; Fitting the implied volatility model in lib/vol_smile.lsp to an option
; chain from tastytrade, to see which options are out of line with the
; rest -- which might be trading opportunities. See vol_smile.lsp for the
; model: for each option, T (years to expiration), F (the forward), K =
; log(strike / F), and Y = T * implied volatility^2, and a least absolute
; deviation fit of Y to K and K^2 for each expiration.
;
; It needs your tastytrade credentials file: creds is set to its path in
; init.lsp. Run it from the examples directory:
;   python3 ../lisp_interpreter.py vol_smile_example.lsp
; or in a notebook, where the chart is drawn too:
;   (load "vol_smile_example.lsp")

(load "vol_smile.lsp")

; --- 1. The chain -----------------------------------------------------------
; BRK/B, which pays no dividend: its options over the next 4 months, the 25
; strikes nearest the money at each expiration.
(define chain (tastytrade-option-chain creds "BRK/B" 4 25))
(display (format "BRK/B: {} options\n\n" (table-row-count chain)))

; --- 2. Fit each expiration's smile -----------------------------------------
; The interest rate sets each expiration's forward. If the forward is far
; from parity-forward -- the forward the calls' and puts' prices imply --
; the rate is off. Options with a spread wider than 2 volatility points are
; left out, as are in-the-money ones.
(define fit (fit-vol-smiles chain :rate 0.045 :max-vol-spread 0.02))
(show-vol-smiles fit :count 10)
(newline)

; --- 3. One fit for all the expirations at once ------------------------------
; With all five terms -- T, sqrt(T), K, K*sqrt(T), and K^2 -- a single
; surface across the expirations. It bends less to each expiration than
; fitting them one at a time, so it can also show an expiration that's out
; of line with the others.
(define surface (fit-vol-smiles chain :rate 0.045 :by-expiration #f))
(display (model-report (cdar (vol-smile-fit-models surface))))
(newline)
(display "\nUnder the single fit, the options furthest from it:\n")
(define surface-options (vol-smile-fit-options surface))
(display-table (table-select (table-head (table-sort (table-add-column surface-options "distance"
                                                                      (abs (table-column surface-options "iv-residual")))
                                                    "distance" #t)
                                         10)
                             '("symbol" "expiration-date" "strike" "iv-bid" "iv-mid" "iv-ask" "fitted-iv"
                               "iv-residual" "signal" "edge"))
               vol-smile-formats)

; --- 4. A chart of the first expiration that was fit -------------------------
(plot-vol-smile fit (caar (vol-smile-fit-models fit)))
