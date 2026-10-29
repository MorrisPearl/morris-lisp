; filing_tone_example.lsp
;
; The tone of what a company writes in its 10-Ks: how negative, positive,
; and uncertain the words of its risk factors are, year by year, by the
; Loughran-McDonald word lists -- see "SEC filings: what companies write"
; in the library manual. The work is in lib/filing_tone.lsp.
;
; It needs a credentials file with a "sec_user_agent" entry (creds is set
; to its path in init.lsp), and the word lists file in morris_lisp/data or
; your Downloads folder. Run it from the examples directory, with a ticker
; if you like (Apple's, unless you give one):
;   python3 ../lisp_interpreter.py filing_tone_example.lsp MSFT

(destructuring-bind (&optional (ticker "AAPL")) (command-line-arguments)
  (let ((tones (filing-tone creds ticker :section "risk-factors" :count 15)))
    (display (format "The risk factors of {}'s last 15 10-Ks: the percent of their words on each list\n\n" ticker))
    (show-filing-tone tones)
    (plot-filing-tone tones :title (format "{}'s risk factors" ticker))))
