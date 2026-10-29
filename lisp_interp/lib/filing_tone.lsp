; filing_tone.lsp
;
; The tone of what a company writes in its filings with the SEC, filing by
; filing: how negative, positive, uncertain, litigious, and constraining
; its words are, by the Loughran-McDonald word lists (see text-tone, in
; "SEC filings: what companies write" in the library manual).
;
; filing-tone downloads each filing (sec-filings, sec-filing-text) -- all
; of it, or one section -- and scores it (text-tone). A 10-K's tone moves
; slowly; what tells you something is a change from one year to the next,
; or one company next to others in its business, more than its level.
;
;   (define apple (filing-tone creds "AAPL" :section "risk-factors"))
;   (show-filing-tone apple)
;   (plot-filing-tone apple)

(define filing-tone-measures '("words" "negative" "positive" "uncertainty" "litigious" "constraining" "net-tone"))

(define (filing-tone creds company &key (forms "10-K") section count word-lists)
  "The tone of a company's filings: a table with a row for each filing, oldest first, of its filing-date,
report-date, and form, then text-tone's measures of its words -- words, and the percent of them that are
negative, positive, uncertainty, litigious, and constraining, and net-tone (positive less negative) -- and its
url. :forms is a form or a list of them (\"10-K\" unless it says); :count keeps just the most recent that many;
:section is \"risk-factors\" or \"management-discussion\", for just that section of each 10-K or 10-Q (a filing
without it has 0 words, and NaN for the rest); :word-lists is the word lists file, if text-tone can't find it.
Each filing is downloaded once and kept for a week."
  (let* ((filings (sec-filings creds company :forms forms :count count))
         (tones (map (lambda (url) (filing-tone--of-url creds url section word-lists))
                     (vector->list (table-column filings "url"))))
         (tone-table (table-from-rows tones filing-tone-measures)))
    (table-add-columns (table-select filings '("filing-date" "report-date" "form"))
                       (append (map (lambda (measure) (cons measure (table-column tone-table measure)))
                                    filing-tone-measures)
                               (list (cons "url" (table-column filings "url")))))))

(define (filing-tone--of-url creds url section word-lists)
  "text-tone's measures of one filing, or of its section; the measures of no words if it has no such section."
  (text-tone (catch-error (sec-filing-text creds url :section section) (message) :only (no-section) "")
             :word-lists word-lists))

(define (show-filing-tone tones)
  "A filing-tone table, as a table of text, with each percent to two decimal places."
  (display-table tones '(("words" ",d") ("negative" ".2f") ("positive" ".2f") ("uncertainty" ".2f")
                         ("litigious" ".2f") ("constraining" ".2f") ("net-tone" ".2f") ("url" hide))
                 :max-rows #f))

(define (plot-filing-tone tones &key (measures '("negative" "positive" "uncertainty")) title)
  "A chart of a filing-tone table's measures, filing by filing: the percent of the words that are negative,
positive, and uncertain, unless :measures names others."
  (plot-chart (map (lambda (measure) (list measure (table-column tones "filing-date") (table-column tones measure)))
                   measures)
              :title (or title "The tone of the filings") :y-label "percent of the words"))
