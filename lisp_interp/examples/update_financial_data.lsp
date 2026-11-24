; update_financial_data.lsp
; =========================
; Brings the database of market history (the market data, and the stocks' weekly and monthly prices from Schwab) up to date, if it is behind: the job
; the Mac runs when it starts or wakes and once a day (economic_data_guide.md says how to set that up). When the database is up to date it says so and
; stops, in two seconds or so.
;
;   python3 lisp_interpreter.py examples/update_financial_data.lsp                  the database in morris_lisp/data
;   python3 lisp_interpreter.py examples/update_financial_data.lsp path/to/the.db   another one
;   python3 lisp_interpreter.py examples/update_financial_data.lsp --force          update even if it was updated today already
;
; creds is the credentials file that init.lsp names.

(define arguments (command-line-arguments))
(define database
  (let ((paths (filter (lambda (word) (not (string=? word "--force"))) arguments)))
    (if (null? paths) "/Users/morris/morris_lisp/data/financial_data.db" (car paths))))

(financial-data-update-if-behind creds database :force (if (member "--force" arguments) #t #f) :tries 3 :wait-seconds 60)
