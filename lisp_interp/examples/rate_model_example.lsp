; rate_model_example.lsp
;
; Fit the interest-rate model to real option prices, then simulate a few paths of rates with it.
;
; Two kinds of option say how much rates move: options on SOFR futures (the short rate) and options on the
; 10-year Treasury note future (the long end). The model's three numbers -- how fast the short rate follows the
; long-run level (a), and the volatility of each (sigma1, sigma2) -- are found for which the model's prices of both
; are nearest the market's. Paths are then drawn from the fitted model. They start where the market is today: the
; 10-year yield of day one is today's. See lisp_paths_manual.md (rate_paths_example.lsp takes the paths apart). Needs a tastytrade account (creds, in init.lsp), and downloads the Treasury's yield curve.
; Read-only. Run it from the examples directory:
;   python3 ../lisp_interpreter.py rate_model_example.lsp
; It saves a chart, rate_model_paths.png.

; --- Market data: the Treasury's forward curve, SOFR futures and their options, and 10-year note options ---
(define treasury (curve-forward-rates (treasury-zero-curve (treasury-par-curve))))
(define sofr-data (sofr-calibration-data creds 40 8 3))              ; SOFR futures (car) and options on them (cdr)
(define note-rows (note-option-rows (tastytrade-option-chain creds "ZN" 12 12) :min-days 20 :max-days 120))

; --- Calibrate: one model that prices both kinds of option ---
(define fit (calibrate-rate-model treasury (cdr sofr-data) note-rows))
(define (fitted name) (cdr (assoc name fit)))
(display (format "a = {:.2f}, sigma1 = {:.4f}, sigma2 = {:.4f}. The model's volatilities are {:.0%} from the SOFR options' and {:.0%} from the notes'.\n"
                 (fitted 'a) (fitted 'sigma1) (fitted 'sigma2) (fitted 'sofr-error) (fitted 'note-error)))

; --- Paths: 200 of them, 5 years, a month at a time ---
(define paths (simulate-rate-paths treasury (fitted 'sigma1) (fitted 'sigma2) 5 200 :a (fitted 'a) :seed 1))
(define years (first paths))
(define short-rates (second paths))
(define ten-year-yields (third paths))
(define (at-the-end rates) (map (lambda (path) (vector-ref path 60)) rates))
(display (format "The 10-year yield starts at {:.2%} and ends 5 years on between {:.2%} and {:.2%}, on average {:.2%}.\n"
                 (vector-ref (first ten-year-yields) 0)
                 (apply min (at-the-end ten-year-yields)) (apply max (at-the-end ten-year-yields))
                 (/ (apply + (at-the-end ten-year-yields)) 200)))

; --- A look at the first eight ---
(define (first-eight rates) (loop for path in rates for number from 1 to 8 collect (list "path" years path)))
(plot-panels (list (list (first-eight ten-year-yields) :title "10-year yield" :y-format "{:.1%}")
                   (list (first-eight short-rates) :title "short rate" :y-format "{:.1%}"))
             :x-label "years from today" :legend #f)
(save-chart "rate_model_paths.png")
