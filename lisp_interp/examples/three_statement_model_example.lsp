; three_statement_model_example.lsp
;
; A company's income statement, balance sheet, and cash flow statement from the SEC, for the last
; five years and the next five, as a Google Sheet that you change the assumptions of -- see
; "Three-statement models" in the library manual.
;
; It needs the credentials file's "sec_user_agent" entry (see sec_example.lsp), and a Google sign-in:
; run (google-login creds) once first (see "Google Sheets" in the library manual). Each call makes
; a new spreadsheet in your Google Drive, and gives its address. Run it from the examples directory:
;   python3 ../lisp_interpreter.py three_statement_model_example.lsp

; --- 1. Five years reported, five forecast ---------------------------------------
; Revenue by business segment if the company reports them (Apple: its regions), else in total.
(display (three-statement-model creds "AAPL"))

; --- 2. Apple's products instead, a quarter at a time ----------------------------
; 8 quarters reported and 8 forecast; each quarter's revenue grows from the same quarter a year before.
(display (three-statement-model creds "AAPL" :period "quarterly" :segments "product"
                                :title "Apple by quarter and product"))

; --- 3. Total revenue only, ten years forward ---------------------------------------
(display (three-statement-model creds "KO" :forecast 10 :segments #f))
