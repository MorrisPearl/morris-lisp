; note_option_example.lsp
;
; Fitting the interest-rate model to options on the 10-year Treasury note future (ZN).
;
; The model of rates is fitted to SOFR futures options elsewhere (sofr_monte_carlo_example.lsp); those show how
; much the SHORT rate moves. A mortgage follows the LONG end, and options on the 10-year note future say how much
; that moves. Here the model's prices of the options are set beside the market's, and the volatility of the long
; end (sigma2) is found for which they are nearest. See "Fitting the model to options on the 10-year note future"
; in the library manual.
;
; Needs a tastytrade account (creds, in init.lsp) for the options, and downloads the Treasury's yield curve. Read-only:
; nothing is placed. Run it from the examples directory:
;   python3 ../lisp_interpreter.py note_option_example.lsp
; It saves a chart, note_option_smile.png.

(load "yield_curves.lsp")
(load "note_options.lsp")

; --- The curve the paths are centered on: the Treasury's forward rates, 360 months ---
(define forwards (table-column (curve-forward-rates (treasury-zero-curve (treasury-par-curve))) "forward"))

; --- The options: calls and puts on the next dozen expirations, and the rows the model reads ---
; Only those between 20 and 120 days out: the nearer ones are priced on the next few days' news.
(define chain (tastytrade-option-chain creds "ZN" 12 12))
(define rows (note-option-rows chain :min-days 20 :max-days 120))
(display (format "{} options on the 10-year note future, {} to {} days from expiry.\n" (length rows)
                 (apply min (map third rows)) (apply max (map third rows))))

; --- The fit: the long end's volatility, sigma2, for which the model's prices are nearest the market's ---
(define fit (sofr-calibrate-note-options forwards rows))
(define sigma2 (cdr (assoc 'sigma2 fit)))
(display (format "sigma2 = {:.4f} a year; the model's volatilities are {:.1%} from the market's, root mean square.\n"
                 sigma2 (cdr (assoc 'error fit))))

; --- The model's prices beside the market's ---
(define comparison (sofr-note-option-comparison forwards rows (cdr (assoc 'sigma1 fit)) sigma2))
(display (format "A yield volatility of {:.0f} basis points a year (the market's: {:.0f}), for a note of {:.1f} years' duration.\n"
                 (vector-mean (table-column comparison "model-yield-vol"))
                 (vector-mean (table-column comparison "market-yield-vol"))
                 (vector-mean (table-column comparison "duration"))))
(define nearest (table-where comparison "days" (vector-min (table-column comparison "days"))))
(display (format "\nThe options {} days from expiry:\n" (vector-ref (table-column nearest "days") 0)))
(display-table (table-select (table-sort nearest "strike") '("type" "strike" "market-price" "model-price" "market-vol" "model-vol" "error"))
               '(("strike" ".2f") ("market-price" ".4f") ("model-price" ".4f") ("market-vol" ".3f") ("model-vol" ".3f")
                 ("error" "+.1%"))
               :max-rows 30)

; --- The smile: the volatility each option's price implies, by strike, for the options out of the money (the puts
; below the future's price, the calls above it: they are the ones that trade most, and their prices are the cleanest).
; The model has one volatility; the market's is higher for the strikes away from the money, and more for the low
; strikes, the options that pay if rates rise a long way.
(define puts (table-where nearest "type" "put"))
(define calls (table-where nearest "type" "call"))
(define out-of-the-money
  (table-sort (table-append (table-filter puts (< (table-column puts "strike") (table-column puts "futures-price")))
                            (table-filter calls (>= (table-column calls "strike") (table-column calls "futures-price"))))
              "strike"))
(plot-chart (list (list "market" (table-column out-of-the-money "strike") (table-column out-of-the-money "market-vol") :symbol #t)
                  (list "model" (table-column out-of-the-money "strike") (table-column out-of-the-money "model-vol")))
            :title (format "10-year note options {} days from expiry" (vector-ref (table-column nearest "days") 0))
            :x-label "strike" :y-label "volatility, in points a year")
(save-chart "note_option_smile.png")
