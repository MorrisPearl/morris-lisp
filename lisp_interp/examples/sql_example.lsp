; sql_example.lsp
;
; The SQL interpreter in sql.lsp at work: a small database made with SQL
; statements, then questions asked of a table that was loaded from a CSV file
; (32,460 rows of pool-months), and the answers used as ordinary tables.
;
; Run it from the examples directory (it takes a few seconds):
;   python3 ../lisp_interpreter.py sql_example.lsp
; To type SQL yourself, (load "sql.lsp"), then (sql-repl).

(load "sql.lsp")

(define (ask text)
  "Shows the SQL, then its result."
  (display (format "> {}\n" text))
  (show-sql text)
  (newline))

; ---------------------------------------------------------------------------
; A database made with SQL
; ---------------------------------------------------------------------------

(display "Making two tables, and putting some rows in them:\n\n")
(ask "CREATE TABLE states (state TEXT, region TEXT)")
(ask "INSERT INTO states VALUES ('CA', 'West'), ('WA', 'West'), ('NY', 'Northeast'), ('TX', 'South'), ('FL', 'South'), ('AK', 'West')")
(ask "CREATE TABLE loans (loan_id INTEGER, state TEXT, balance REAL, rate REAL, fico INTEGER)")
(ask "INSERT INTO loans VALUES
        (1, 'CA', 400000, 6.25, 760), (2, 'CA', 250000, 6.50, 690), (3, 'NY', 300000, 6.00, 720),
        (4, 'TX', 180000, 7.00, 640), (5, 'TX', 220000, 6.75, 705), (6, 'FL', 310000, 6.50, NULL),
        (7, 'WA', 500000, 5.75, 790), (8, 'NY', 150000, 7.25, 610), (9, 'CA', 275000, 6.00, 745)")

(display "Which loans are big? And which have a low FICO score, or none at all?\n\n")
(ask "SELECT loan_id, state, balance, fico FROM loans WHERE balance >= 275000 ORDER BY balance DESC")
(ask "SELECT loan_id, state, fico FROM loans WHERE fico < 700 OR fico IS NULL ORDER BY loan_id")

(display "Totals by region -- the loans joined to the states they are in:\n\n")
(ask "SELECT s.region, COUNT(*) AS loans, SUM(l.balance) AS upb,
             SUM(l.balance * l.rate) / SUM(l.balance) AS wac, MIN(l.fico) AS lowest_fico
      FROM loans l JOIN states s ON l.state = s.state
      GROUP BY s.region
      ORDER BY upb DESC")

(display "A state with no loans shows up in a LEFT JOIN, with nothing for the loans:\n\n")
(ask "SELECT s.state, COUNT(l.loan_id) AS loans, SUM(l.balance) AS upb
      FROM states s LEFT JOIN loans l ON s.state = l.state
      GROUP BY s.state
      HAVING COUNT(l.loan_id) < 2
      ORDER BY s.state")

(display "Changing the data:\n\n")
(ask "UPDATE loans SET rate = rate - 0.25 WHERE state = 'TX'")
(ask "DELETE FROM loans WHERE fico IS NULL")
(ask "SELECT state, COUNT(*) AS loans, AVG(rate) AS avg_rate FROM loans GROUP BY state ORDER BY avg_rate")

(display "A mistake is an error that says what is wrong:\n\n")
(display (format "  {}\n\n"
                 (catch-error (sql "SELECT state, SUM(balance) FROM loans")
                              (message) message)))

; ---------------------------------------------------------------------------
; A table from a file
; ---------------------------------------------------------------------------
; Any table can be given a name for SQL to use: here the table load-csv makes.

(define pools (load-csv "synthetic_mbs_pools.csv"))
(sql-register-table! "pools" pools)

(display "Prepayment speeds (cpr) of 32,460 pool-months, by the pool's average FICO score, to the nearest 50:\n\n")
(ask "SELECT round(avg_fico / 50) * 50 AS fico, COUNT(*) AS months, AVG(cpr) AS avg_cpr
      FROM pools
      GROUP BY round(avg_fico / 50) * 50
      ORDER BY fico")

(display "The fastest pools when the rate to refinance was well below the pool's rate, in 2020 or after:\n\n")
(ask "SELECT pool_id, COUNT(*) AS months, AVG(cpr) AS avg_cpr, MAX(cpr) AS fastest
      FROM pools
      WHERE rate_incentive_pct > 1 AND obs_date >= date('2020-01-01')
      GROUP BY pool_id
      HAVING COUNT(*) >= 5
      ORDER BY avg_cpr DESC
      LIMIT 5")

; ---------------------------------------------------------------------------
; The answers are tables
; ---------------------------------------------------------------------------
; What (sql ...) returns is a table like any other, for the interpreter's
; other functions -- and a table you give a name to can be asked about again.

(define by-fico
  (sql "SELECT round(avg_fico / 50) * 50 AS fico, AVG(cpr) AS avg_cpr FROM pools GROUP BY round(avg_fico / 50) * 50"))

(display (format "The averages, rounded to four places, with vector-round: {}\n"
                 (vector-round (table-column by-fico "avg_cpr") 4)))
(display "The same table sorted by table-sort, slowest first:\n\n")
(display-table (table-sort by-fico "avg_cpr"))

(newline)
(sql-register-table! "by_fico" by-fico)
(ask "SELECT fico, avg_cpr FROM by_fico WHERE avg_cpr > 0.16 ORDER BY fico DESC")

(display "And the loans table, as changed above, is a table too:\n\n")
(display-table (sql-table "loans"))
