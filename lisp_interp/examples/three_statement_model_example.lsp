; three_statement_model_example.lsp
;
; A company's income statement, balance sheet, and cash flow statement from the SEC, for the last
; five years and the next five, as a Google Sheet that you change the assumptions of -- see
; "Three-statement models" in the library manual. Ordinary companies, banks, and property and
; casualty insurers, and asset managers each get the lines and assumptions that fit them.
;
; It needs the credentials file's "sec_user_agent" entry (see sec_example.lsp), and a Google sign-in:
; run (google-login creds) once first (see "Google Sheets" in the library manual). Each call makes
; a new spreadsheet in your Google Drive, and gives its address. Run it from the examples directory:
;   python3 ../lisp_interpreter.py three_statement_model_example.lsp

; --- 1. Five years reported, five forecast ---------------------------------------
; Revenue by business segment if the company reports them (Apple: its regions), else in total.
(print (three-statement-model creds "AAPL"))

; --- 2. Apple's products instead, a quarter at a time ----------------------------
; 8 quarters reported and 8 forecast; each quarter's revenue grows from the same quarter a year before.
(print (three-statement-model creds "AAPL" :period "quarterly" :segments "product"
                                :title "Apple by quarter and product"))

; --- 3. Total revenue only, ten years forward ---------------------------------------
(print (three-statement-model creds "KO" :forecast 10 :segments #f))

; --- 4. A bank: its balance sheet and the interest rates on it drive the forecast ----
; The SEC's industry code tells the program that JPMorgan is a bank, so the sheet has loans,
; deposits, interest rates, credit losses, and the efficiency ratio instead of revenue growth.
(print (three-statement-model creds "JPM"))

; --- 5. A property and casualty insurer: premiums, loss and expense ratios, and the float ---
(print (three-statement-model creds "TRV" :period "quarterly"))

; --- 6. An asset manager: revenue is a fee on assets under management ---------------
; The SEC's data has no AUM, so give it: billions at the end of each year, oldest first, the last
; being the latest annual report's. (These are placeholders -- type the figures from the 10-K.)
(print (three-statement-model creds "TROW" :aum (list 1688 1275 1480 1610 1750)))

; --- 7. The kind can be chosen. Berkshire Hathaway, with its insurance, railroad, utilities, and ---
; manufacturing in one set of statements, is modeled as an ordinary company (the Notes tab says why).
(print (three-statement-model creds "BRK-B"))

; --- 8. What is the company worth? The DCF tab ---------------------------------------
; Every ordinary company's and asset manager's sheet has a DCF tab: the forecast free cash flow discounted
; at a rate built from the risk-free rate, beta, and risk premium (placeholders -- type your own), a terminal
; value, and a value per share, with a table of other discount and growth rates. :price (today's share price)
; weights the debt and equity by their market values and shows the value against the price. A bank or an
; insurer has no DCF tab. In the sheet, set the "method" cell to 1 for a company still growing fast at the end of the forecast.
(print (three-statement-model creds "KO" :segments #f :price 70 :title "Coca-Cola, with a DCF"))
