; compare_companies_example.lsp
;
; Companies side by side in a Google Sheet: the latest period of each, a column for every company,
; the same rows for all -- see "Comparing companies" in the library manual.
;
; It needs the credentials file's "sec_user_agent" entry (see sec_example.lsp), and a Google sign-in:
; run (google-login creds) once first. Each call makes a new spreadsheet in your Google Drive, and
; gives its address. Run it from the examples directory:
;   python3 ../lisp_interpreter.py compare_companies_example.lsp

; --- 1. Three consulting and information-services companies, as a percentage of revenue ---
; Of different sizes, so the amounts are not comparable; as a percentage of revenue they are.
(display (compare-companies creds '("ACN" "EFX" "CTSH") :basis "revenue"))

; --- 2. Banks (their rows are a bank's), as a percentage of total assets ---------------
(display (compare-companies creds '("JPM" "BAC" "C" "USB") :basis "assets"))

; --- 3. Property and casualty insurers, the amounts in millions, the latest quarter ---
(display (compare-companies creds '("TRV" "CB" "PGR") :period "quarterly"))
