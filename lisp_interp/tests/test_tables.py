"""Tables: building, filtering, joining, rows, displaying them, stratification, CSV files,
SQLite, and saving variables.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class TestTables(LispTestCase):
    """lisp_tables.py: tables are lists of (name . vector) columns."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define loans (make-table "id"      (vector "a" "a" "b" "b" "c")
                                    "month"   #(1 2 1 2 1)
                                    "state"   (vector "CA" "CA" "NY" "NY" "CA")
                                    "balance" #(100 90 200 195 50)
                                    "rate"    (vector 6.0 6.0 4.5 nan 7.25)))""")
        self.run_lisp("(define (same-ignoring-case? a b) (string=? (string-downcase a) (string-downcase b)))")

    def test_looking_at_a_table(self):
        self.assertShows("(table-column-names loans)", '("id" "month" "state" "balance" "rate")')
        self.assertShows('(table-column loans "balance")', "#(100 90 200 195 50)")
        self.assertShows("(table-row-count loans)", "5")
        self.assertShows('(row-ref (table-row loans 2) "state")', '"NY"')
        self.assertShows('(table-column (table-head loans 2) "id")', '#("a" "a")')
        self.assertShows('(table-column (table-slice loans 3) "id")', '#("b" "c")')
        self.assertShows('(table-column (table-tail loans 2) "id")', '#("b" "c")')
        self.assertShows('(table-column (table-tail loans) "id")', '#("a" "a" "b" "b" "c")')     # fewer than 10
        self.assertShows('(table-row-count (table-tail loans 0))', "0")

    def test_with_columns(self):
        self.assertShows("(with-columns (balance rate) loans (vector-weighted-mean rate balance))",
                         "5.4602272727272725")              # the missing rate is skipped
        self.assertShows('(with-columns ((amount "balance") id) loans (list (vector-ref id 2) (vector-sum amount)))',
                         '("b" 635)')
        self.assertShows('(with-columns (SP500) (make-table "SP500" #(1 2)) SP500)', "#(1 2)")      # case kept
        self.run_lisp('(define prices (make-table "date" (vector (date 2024 1 2) (date 2024 1 3)) "close" #(100 104)))')
        self.assertShows('(with-columns ((day "date") close) prices (vector-select close (>= day (date 2024 1 3))))',
                         "#(104)")                          # renamed, so the date function still works
        self.run_lisp("(define made 0)")
        self.run_lisp("(define (get-loans) (set! made (+ made 1)) loans)")
        self.assertShows("(with-columns (id month balance) (get-loans) (set! made (+ made 10)) (vector-sum month))", "7")
        self.assertShows("made", "11")                      # the table expression ran once; every body form ran
        self.assertLispError("(with-columns (balance) loans balance) balance", "unbound")   # local to the body
        self.assertLispError("(with-columns (balanse) loans balanse)", "no column named 'balanse' (the columns are:")
        self.assertLispError("(with-columns ((amount balance)) loans amount)",
                             'each column must be a name, or (variable "column"), not (amount balance)')
        self.assertLispError("(with-columns balance loans balance)", "expected (with-columns (column...) table body...)")
        self.assertIsInstance(self.env[lisp_core.Symbol("with-columns")], lisp_core.Macro)

    def test_drawdowns(self):
        self.run_lisp("(define dd-dates (vector (date 2020 1 1) (date 2020 1 2) (date 2020 1 3) (date 2020 1 4)"
                      " (date 2020 1 5) (date 2020 1 6) (date 2020 1 7) (date 2020 1 8)))")
        self.run_lisp("(define dd (vector-drawdowns dd-dates #(100 95 85 88 80 101 120 100) 10))")
        self.assertShows("(table-row-count dd)", "2")
        self.assertShows('(table-column dd "peak")', "#(100.0 120.0)")
        self.assertShows('(table-column dd "below-date")', "#(2020-01-03 2020-01-08)")
        self.assertShows('(table-column dd "trough-date")', "#(2020-01-05 2020-01-08)")
        self.assertShows('(table-column dd "trough")', "#(80.0 100.0)")
        self.assertAlmostEqual(float(self.run_lisp('(vector-ref (table-column dd "drop-pct") 1)')), 100 / 6, places=4)
        self.assertShows('(table-column dd "recovery-date")', "#(2020-01-06 ())")     # the second hasn't recovered
        self.assertShows("(table-row-count (vector-drawdowns dd-dates #(100 95 85 88 80 101 120 100) 25))", "0")
        self.assertShows("(table-row-count (vector-drawdowns #(1 2 3) #(100 nan 85) 10))", "1")   # NaN skipped
        self.assertLispError("(vector-drawdowns #(1 2) #(1 2 3) 10)", "dates has 2 elements but values has 3")
        self.assertLispError("(vector-drawdowns #(1 2) #(100 -5) 10)", "must be above 0")

    def test_where_with_key_and_test(self):
        self.assertShows('(table-column (table-where loans "state" "ny" :key string-downcase) "balance")', "#(200 195)")
        self.assertShows('(table-column (table-where loans "id" (list "A" "C") :key string-downcase) "balance")',
                         "#(100 90 50)")
        self.assertShows('(table-column (table-where loans "state" "ny" :test same-ignoring-case?) "balance")',
                         "#(200 195)")
        self.assertShows('(table-column (table-where loans "rate" 6 :key floor) "id")', '#("a" "a")')   # a missing rate matches nothing
        # the test is given the value, then the cell
        self.assertShows('(table-column (table-where loans "balance" 150 :test (lambda (value cell) (> cell value))) "id")',
                         '#("b" "b")')
        # and what the key made of each, with both given
        self.assertShows('(table-column (table-where loans "state" "Nevada" :key (lambda (s) (substring s 0 1))'
                         ' :test string=?) "balance")', "#(200 195)")
        self.assertLispError('(table-where loans "state" "NY" :test 5)', ":test must be a procedure of two values")
        self.assertLispError('(table-where loans "state" "NY" :key "downcase")', ":key must be a procedure of one value")
        self.assertLispError('(table-where loans "state" "NY" :tset string=?)', ":tset isn't an option -- the options are :key, :test")
        self.assertLispError('(table-where loans "state" "NY" :key (lambda (s) (list s)))', ":key must return a number, string, or date")
        # the key is applied once to each distinct value, not once to each row
        self.run_lisp("(define calls 0)")
        self.run_lisp("(define (counting-downcase s) (set! calls (+ calls 1)) (string-downcase s))")
        self.run_lisp('(table-where loans "state" "ny" :key counting-downcase)')
        self.assertShows("calls", "3")                      # "ny", and the column's two distinct values, CA and NY

    def test_rows_where_a_column_holds_a_value(self):
        self.assertShows('(table-column (table-where loans "state" "NY") "balance")', "#(200 195)")
        self.assertShows('(table-column (table-where loans "id" (list "a" "c")) "balance")', "#(100 90 50)")
        self.assertShows('(table-column (table-where loans "rate" 7.25) "id")', '#("c")')          # a decimal
        self.assertShows('(table-row-count (table-where loans "state" "TX"))', "0")
        self.assertShows('(= (table-column loans "state") "CA")', "#(1 1 0 0 1)")           # text, element by element
        self.assertShows("(table? loans)", "#t")
        self.assertShows("(table? (list 1))", "#f")
        self.assertLispError('(table-column loans "nope")', "no column named")
        self.assertLispError("(table-row loans 99)", "table-row: there's no row 99 -- the table has 5 rows")
        self.assertLispError('(make-table "a" #(1 2) "b" #(1))', "different lengths")

    def test_choosing_and_changing_columns(self):
        self.assertShows('(table-column-names (table-select loans (list "rate" "id")))', '("rate" "id")')
        self.assertShows('(table-column-names (table-drop-columns loans (list "rate" "id")))',
                         '("month" "state" "balance")')
        self.assertShows('(table-column (table-add-column loans "one" 1) "one")', "#(1 1 1 1 1)")
        self.assertShows('(table-column-names (table-add-column loans "month" #(9 9 9 9 9)))',
                         '("id" "month" "state" "balance" "rate")')
        self.assertLispError('(table-add-column loans "x" #(1 2))', "5 rows")
        self.assertShows('(table-column-names (table-rename-column loans "id" "loan"))',
                         '("loan" "month" "state" "balance" "rate")')

    def test_filter_and_sort(self):
        self.assertShows('(table-column (table-filter loans (vector> (table-column loans "balance") 95)) "id")',
                         '#("a" "b" "b")')
        self.assertShows('(table-column (table-sort loans "balance" #t) "balance")', "#(200 195 100 90 50)")
        self.assertShows('(table-column (table-sort loans (list "state" "balance")) "balance")',
                         "#(50 90 100 195 200)")
        self.assertShows('(table-column (table-sort loans "rate") "rate")', "#(4.5 6.0 6.0 7.25 nan)")
        self.assertLispError("(table-filter loans #(1 0))", "mask has 2")

    def test_append(self):
        self.assertShows('(table-column (table-append (table-head loans 1) (table-slice loans 4)) "id")',
                         '#("a" "c")')
        self.assertLispError('(table-append loans (make-table "x" #(1)))', "different columns")

    def test_group_by(self):
        self.run_lisp("""
          (define g (table-group-by loans "state"
                       (list (list "n" 'count) (list "upb" 'sum "balance")
                             (list "wac" 'weighted-mean "rate" "balance")
                             (list "avg" "mean" "rate") (list "lo" 'min "balance")
                             (list "last_id" 'last "id") (list "med" 'median "balance"))))""")
        self.assertShows('(table-column g "state")', '#("CA" "NY")')
        self.assertShows('(table-column g "n")', "#(3 2)")
        self.assertShows('(table-column g "upb")', "#(240 395)")
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column g "wac") 1)'), 4.5)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column g "wac") 0)'),
                               (100 * 6 + 90 * 6 + 50 * 7.25) / 240, places=5)
        self.assertShows('(table-column g "avg")', "#(6.4166665 4.5)")
        self.assertShows('(table-column g "lo")', "#(50 195)")
        self.assertShows('(table-column g "last_id")', '#("c" "b")')
        self.assertShows('(table-column g "med")', "#(90.0 197.5)")
        self.assertShows('(table-column (table-group-by loans (list "state" "month") (list (list "n" (quote count)))) "n")',
                         "#(2 1 1 1)")
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'bogus \"rate\")))",
                             "table-group-by: bogus isn't a summary")
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'weighted-mode \"rate\")))",
                             "table-group-by: weighted-mode needs a weight column")

    def test_group_by_the_other_statistics(self):
        self.assertShows("(table-group-by loans \"state\" (list (list \"id\" 'representative \"id\")"
                         " (list \"most\" 'weighted-mode \"id\" \"balance\")"
                         " (list \"wm\" 'weighted-median \"balance\" \"balance\")"
                         " (list \"p90\" '(percentile 90) \"balance\")))",
                         '(("state" . #("CA" "NY")) ("id" . #("a" "b")) ("most" . #("a" "b"))'
                         ' ("wm" . #(90.0 200.0)) ("p90" . #(98.0 199.5)))')
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'weighted-mean \"rate\")))", "weight column")

    def test_group_by_with_key_and_test(self):
        self.run_lisp('(define names (make-table "name" (vector "b" "A" "a" "B" "c") "v" #(1 2 3 4 5)))')
        aggregations = ('(list (list "total" (quote sum) "v") (list "first" (quote first) "v")'
                        ' (list "last" (quote last) "v"))')
        # :key -- rows whose keyed values are equal share a group, which shows the keyed value;
        # each group's rows stay in the table's order (so "B" comes after "b" in the table, but is the last)
        self.assertShows('(table-group-by names "name" %s :key string-downcase)' % aggregations,
                         '(("name" . #("a" "b" "c")) ("total" . #(5 5 5)) ("first" . #(2 1 5)) ("last" . #(3 4 5)))')
        # :test -- a group shows its first key value in sorted order
        self.assertShows('(table-group-by names "name" %s :test same-ignoring-case?)' % aggregations,
                         '(("name" . #("A" "B" "c")) ("total" . #(5 5 5)) ("first" . #(2 1 5)) ("last" . #(3 4 5)))')
        # with several key columns, every one must match
        self.run_lisp('(define two-keys (make-table "name" (vector "A" "a" "A" "b") "m" #(1 1 2 1)))')
        self.assertShows('(table-column (table-group-by two-keys (list "name" "m") (list (list "n" (quote count)))'
                         ' :test (lambda (a b) (if (string? a) (same-ignoring-case? a b) (= a b)))) "n")', "#(2 1 1)")
        self.assertShows('(table-column (table-group-by (table-head names 0) "name" (list (list "n" (quote count)))'
                         ' :test same-ignoring-case?) "n")', "#()")
        self.assertLispError('(table-group-by names "name" %s :test 5)' % aggregations, ":test must be a procedure")

    def test_join(self):
        self.run_lisp('(define rates (make-table "month" #(1 2) "mkt" #(6.5 6.25) "rate" #(1 2)))')
        self.assertShows('(table-column (table-join loans rates "month") "mkt")', "#(6.5 6.25 6.5 6.25 6.5)")
        self.assertShows('(table-column (table-join loans rates "month") "rate_right")', "#(1 2 1 2 1)")
        self.run_lisp('(define few (make-table "month" #(2) "mkt" #(6.25)))')
        self.assertShows('(table-row-count (table-join loans few "month"))', "2")
        self.assertShows('(table-column (table-join loans few "month" (quote left)) "mkt")',
                         "#(nan 6.25 nan 6.25 nan)")
        # a left row matching two right rows appears twice, in left order
        self.run_lisp('(define two (make-table "k" (vector "x" "x") "v" #(10 20)))')
        self.assertShows('(table-column (table-join (make-table "k" (vector "x" "y")) two "k" (quote left)) "v")',
                         "#(10.0 20.0 nan)")
        self.assertShows('(table-column (table-join (make-table "k" (vector "y")) two "k") "v")', "#()")
        self.assertLispError('(table-join loans rates "month" (quote outer))', "how must be")

    def test_join_with_key(self):
        self.run_lisp("""
          (define holdings (make-table "name" (vector "Apple Inc." "BROWN-FORMAN CORP" "Microsoft" "Tesla")
                                       "weight" #(7.25 0.5 5.8 1.2)))
          (define industries (make-table "name" (vector "APPLE INC" "brown forman corp" "microsoft" "Nvidia")
                                         "industry" (vector "Tech" "Beverages" "Tech" "Chips")))
          (define (plain s) (string-downcase (regex-replace "[.,]" (regex-replace "-" s " ") "")))""")
        self.assertShows('(table-column (table-join holdings industries "name") "industry")', "#()")
        self.assertShows('(table-column (table-join holdings industries "name" :key string-downcase) "industry")',
                         '#("Tech")')                       # only Microsoft differs from its twin in just its case
        self.assertShows('(table-column (table-join holdings industries "name" :key plain) "industry")',
                         '#("Tech" "Beverages" "Tech")')
        self.assertShows('(table-column (table-join holdings industries "name" :key plain) "name")',
                         '#("Apple Inc." "BROWN-FORMAN CORP" "Microsoft")')    # the left table's own key values
        self.assertShows("(table-column (table-join holdings industries \"name\" 'left :key plain) \"industry\")",
                         '#("Tech" "Beverages" "Tech" ())')
        # numbers, with a key that makes them match
        self.assertShows('(table-column (table-join (make-table "x" #(1 2 3)) (make-table "x" #(11 12 20) "j" #(7 8 9)) "x"'
                         ' :key (lambda (n) (mod n 10))) "j")', "#(7 8)")
        # with several key columns, every one must match
        self.run_lisp('(define a (make-table "k" (vector "x" "x" "y") "m" #(1 2 1) "n" #(1 2 3)))')
        self.run_lisp('(define b (make-table "k" (vector "X" "X" "Y") "m" #(1 2 2) "v" #(10 20 30)))')
        self.assertShows('(table-column (table-join a b (list "k" "m") :key (lambda (x) (if (string? x) (string-downcase x) x))) "v")',
                         "#(10 20)")
        self.assertLispError('(table-join holdings industries "name" :key 5)', ":key must be a procedure of one value")
        self.assertLispError('(table-join holdings industries "name" :key list)', ":key must return a number, string, or date")

    def test_join_with_test(self):
        self.run_lisp('(define left (make-table "k" (vector "x" "X" "y" "z") "n" #(1 2 3 4)))')
        self.run_lisp('(define right (make-table "k" (vector "X" "x" "Y") "v" #(10 20 30)))')
        # each left row gets the right rows that match it, in the left table's order and then the right's
        self.assertShows('(table-column (table-join left right "k" :test same-ignoring-case?) "v")', "#(10 20 10 20 30)")
        self.assertShows('(table-column (table-join left right "k" :test same-ignoring-case?) "k")', '#("x" "x" "X" "X" "y")')
        self.assertShows("(table-column (table-join left right \"k\" 'left :test same-ignoring-case?) \"v\")",
                         "#(10.0 20.0 10.0 20.0 30.0 nan)")
        # the test is given the left value, then the right
        self.assertShows('(table-column (table-join (make-table "k" #(1 5)) (make-table "k" #(3 4) "v" #(30 40)) "k"'
                         ' :test (lambda (left right) (< left right))) "v")', "#(30 40)")
        # numbers that are close; a decimal such as 4.01 reaches the test as 4.01
        self.assertShows('(table-column (table-join (make-table "x" (vector 4.01 5.5)) (make-table "x" (vector 4.0 5.49) "j" #(7 8))'
                         ' "x" :test (lambda (a b) (< (abs (- a b)) 0.05))) "j")', "#(7 8)")
        # with several key columns, every one must match
        self.run_lisp('(define a (make-table "k" (vector "x" "x" "y") "m" #(1 2 1) "n" #(1 2 3)))')
        self.run_lisp('(define b (make-table "k" (vector "X" "X" "Y") "m" #(1 2 2) "v" #(10 20 30)))')
        self.assertShows('(table-column (table-join a b (list "k" "m") :test (lambda (p q) (if (string? p) (same-ignoring-case? p q) (= p q)))) "v")',
                         "#(10 20)")
        # after :key, the test is given what the key made
        self.assertShows('(table-column (table-join (make-table "k" (vector "Ab" "cD")) (make-table "k" (vector "AB " "cd") "v" #(1 2))'
                         ' "k" :key string-downcase :test (lambda (a b) (string-starts-with? b a))) "v")', "#(1 2)")
        # no rows on one side
        self.assertShows('(table-row-count (table-join (table-head left 0) right "k" :test same-ignoring-case?))', "0")
        self.assertShows('(table-row-count (table-join left (table-head right 0) "k" :test same-ignoring-case?))', "0")
        self.assertShows("(table-column (table-join left (table-head right 0) \"k\" 'left :test same-ignoring-case?) \"v\")",
                         "#(nan nan nan nan)")
        self.assertLispError('(table-join left right "k" :test 5)', ":test must be a procedure of two values")
        self.assertLispError('(table-join left right "k" :test)', "after the first arguments come :name value pairs")
        self.assertLispError("(table-join left right \"k\" 'outer :test same-ignoring-case?)", "how must be")

    def test_join_with_test_applies_it_to_distinct_key_values(self):
        # loans has 2 distinct months and so does rates: 2 x 2 = 4 calls, not 5 x 2 = 10
        self.run_lisp('(define rates (make-table "month" #(1 2) "mkt" #(6.5 6.25)))')
        self.run_lisp("(define calls 0)")
        self.run_lisp("(define (counting-equal a b) (set! calls (+ calls 1)) (= a b))")
        self.assertShows('(table-column (table-join loans rates "month" :test counting-equal) "mkt")', "#(6.5 6.25 6.5 6.25 6.5)")
        self.assertShows("calls", "4")

    def test_a_missing_key_never_reaches_key_or_test(self):
        # the missing ones would make string-downcase and same-ignoring-case? fail; a missing key matches only another
        self.run_lisp("""
          (define with-missing (table-join (make-table "n" #(1 2 3)) (make-table "n" #(1 3) "k" (vector "x" "y")) "n" (quote left)))
          (define other-missing (table-join (make-table "m" #(1 2)) (make-table "m" #(1) "k" (vector "X")) "m" (quote left)))""")
        self.assertShows('(table-column with-missing "k")', '#("x" () "y")')
        self.assertShows('(table-column (table-join with-missing other-missing "k" (quote left) :key string-downcase) "m")',
                         "#(1.0 2.0 nan)")
        self.assertShows('(table-column (table-join with-missing other-missing "k" (quote left) :test same-ignoring-case?) "m")',
                         "#(1.0 2.0 nan)")
        self.assertShows('(table-column (table-where with-missing "k" "X" :key string-downcase) "n")', "#(1)")
        self.assertShows('(table-column (table-group-by with-missing "k" (list (list "rows" (quote count))) :key string-upcase) "k")',
                         '#("X" "Y" ())')

    def test_describe(self):
        self.run_lisp("(define d (table-describe loans))")
        self.assertShows('(table-column d "column")', '#("month" "balance" "rate")')
        self.assertShows('(table-column d "count")', "#(5 5 4)")
        self.assertShows('(table-column d "max")', "#(2.0 200.0 7.25)")


class TestTableRows(LispTestCase):
    """A table seen a row at a time: table-rows, table-row, row-ref, and
    table-from-rows."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""(define t (make-table "id" (vector "a" "b" "c")
                                             "balance" #(100 90 200)
                                             "rate" (vector 6.0 nan 7.5)))""")

    def test_table_rows_gives_one_row_per_table_row(self):
        self.assertShows("(length (table-rows t))", "3")
        self.assertShows("(car (table-rows t))", '#S(row :id "a" :balance 100 :rate 6.0)')

    def test_a_row_is_a_struct(self):
        self.assertShows("(struct? (table-row t 0))", "#t")
        self.assertShows("(struct-ref (table-row t 0) 'balance)", "100")

    def test_row_ref_takes_a_string_or_a_symbol(self):
        self.assertShows('(row-ref (table-row t 1) "id")', '"b"')
        self.assertShows("(row-ref (table-row t 1) 'balance)", "90")
        self.assertShows('(row-ref (table-row t 1) "rate")', "nan")         # a missing value
        self.assertLispError('(row-ref (table-row t 1) "nope")',
                             "row-ref: the row has no column nope -- its columns are id, balance, rate")
        self.assertLispError('(row-ref 5 "id")', "row-ref: not a row: 5")

    def test_with_struct_makes_each_column_a_variable(self):
        self.assertShows("(with-struct (table-row t 2) (list id (* balance 2)))", '("c" 400)')

    def test_filtering_rows_with_a_predicate(self):
        self.run_lisp("(define big (filter (lambda (r) (with-struct r (> balance 95))) (table-rows t)))")
        self.assertShows("(map (lambda (r) (row-ref r 'id)) big)", '("a" "c")')

    def test_table_row_checks_the_row_number(self):
        self.assertLispError("(table-row t 3)", "table-row: there's no row 3 -- the table has 3 rows")
        self.assertLispError("(table-row t 1.5)", "there's no row 1.5")

    def test_rows_back_into_a_table(self):
        self.assertShows("(table-from-rows (table-rows t))",
                         '(("id" . #("a" "b" "c")) ("balance" . #(100 90 200)) ("rate" . #(6.0 nan 7.5)))')
        self.assertShows("(table-from-rows (table-rows t) '(\"balance\" \"id\"))",
                         '(("balance" . #(100 90 200)) ("id" . #("a" "b" "c")))')

    def test_a_table_from_lists(self):
        self.assertShows("""(table-from-rows (list (list "x" 1 "2024-01-31") (list "y" '() "2024-02-29"))
                                             (list "name" "n" "day"))""",
                         '(("name" . #("x" "y")) ("n" . #(1.0 nan)) ("day" . #(2024-01-31 2024-02-29)))')

    def test_hash_tables_such_as_json_objects_become_rows(self):
        self.run_lisp("""
          (define a (make-hash-table))
          (hash-table-set! a "symbol" "SPY")
          (hash-table-set! a "bid" 765.5)
          (hash-table-set! a "is-etf" #t)
          (hash-table-set! a "tags" (list 1 2))           ; a list: left out
          (define b (make-hash-table))
          (hash-table-set! b "symbol" "BRK/B")
          (hash-table-set! b "is-etf" #f)
          (hash-table-set! b "listed" "1996-05-09")""")
        self.assertShows("(table-from-rows (list a b))",
                         '(("symbol" . #("SPY" "BRK/B")) ("bid" . #(765.5 nan)) ("is-etf" . #(1 0)) '
                         '("listed" . #(() 1996-05-09)))')
        self.assertShows('(table-from-rows (list a b) (list "bid" "symbol"))',
                         '(("bid" . #(765.5 nan)) ("symbol" . #("SPY" "BRK/B")))')
        self.assertLispError("(table-from-rows (list a 5))", "every row must be")

    def test_table_from_rows_errors(self):
        self.assertLispError("(table-from-rows (list (list 1 2)))", "give the column names")
        self.assertLispError("(table-from-rows (list (list 1 2)) (list \"a\"))",
                             "the row (1 2) has 2 values, but there are 1 column names")
        self.assertLispError("(table-from-rows (list (list #t)) (list \"a\"))",
                             "a table holds numbers, strings, and dates, not #t (in column a)")
        self.assertLispError("(table-from-rows (list 5) (list \"a\"))", "a row must be a row")

    def test_no_rows(self):
        self.assertShows("(table-from-rows '() (list \"a\"))", '(("a" . #()))')
        self.assertShows("(table-rows (table-filter t (> (table-column t \"balance\") 1000)))", "()")


class TestDisplayHtml(LispTestCase):
    """display-html: HTML in a notebook, the plain text anywhere else."""

    def test_the_console_gets_the_plain_text(self):
        self.run_lisp('(display-html "<b>bold</b>" "bold")')
        self.assertEqual(self.printed(), "bold\n")

    def test_without_plain_text_the_console_gets_the_html(self):
        self.run_lisp('(display-html "<b>bold</b>")')
        self.assertEqual(self.printed(), "<b>bold</b>\n")

    def test_a_notebook_gets_the_html(self):
        shown = []
        env = lisp_builtins.make_global_env(output=self.out.append, html=shown.append)
        self.run_lisp('(display-html "<b>bold</b>" "bold")', env)
        self.assertEqual(shown, ["<b>bold</b>"])
        self.assertEqual(self.printed(), "")

    def test_the_notebook_callback_shows_it_as_html(self):
        try:
            import lisp_jupyter
            from IPython.display import HTML
        except ImportError:
            self.skipTest("IPython is not installed")
        with mock.patch.object(lisp_jupyter, "_ipy_display") as fake_display:
            lisp_jupyter._notebook_html("<b>bold</b>")
        shown = fake_display.call_args[0][0]
        self.assertIsInstance(shown, HTML)
        self.assertEqual(shown.data, "<b>bold</b>")

    def test_it_needs_strings(self):
        self.assertLispError("(display-html 5)", "display-html: expected a string for html, got 5")


class TestDisplayTable(LispTestCase):
    """display-table: a table, or a list of rows, with each column's numbers
    laid out by a format spec."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""(define t (make-table "symbol" (vector "SPY C" "SPY|P")
                                             "strike" #(450 455)
                                             "iv" (vector 0.2345 nan)
                                             "volume" #(12345 67)))""")

    def test_the_console_table(self):
        self.run_lisp("(display-table t '((\"strike\" \",.2f\") (\"iv\" \".1%\") (\"volume\" \",\")))")
        self.assertEqual(self.printed(),
                         "symbol  strike     iv  volume\n"
                         "------  ------  -----  ------\n"
                         "SPY C   450.00  23.4%  12,345\n"
                         "SPY|P   455.00             67\n")

    def test_without_formats_numbers_are_shown_as_display_shows_them(self):
        self.run_lisp("(display-table t)")
        self.assertIn("SPY C      450  0.2345   12345", self.printed())

    def test_a_format_may_be_written_as_a_dotted_pair(self):
        self.run_lisp("(display-table t '((\"strike\" . \",.1f\")))")
        self.assertIn("450.0", self.printed())

    def test_a_format_for_a_column_the_table_lacks_is_not_used(self):
        self.run_lisp("(display-table (table-select t \"symbol\") '((\"strike\" \",.2f\")))")
        self.assertEqual(self.printed(), "symbol\n------\nSPY C\nSPY|P\n")

    def test_a_list_of_rows(self):
        self.run_lisp("(display-table (table-rows t) '((\"strike\" \",.2f\")))")
        self.assertIn("SPY C   450.00", self.printed())

    def test_an_empty_table(self):
        self.run_lisp("(display-table '())")
        self.assertEqual(self.printed(), "(an empty table)\n")

    def test_errors(self):
        self.assertLispError("(display-table 5)", "display-table: not a table")
        self.assertLispError("(display-table t '(5))", "each format must be (name spec)")
        self.assertLispError("(display-table t '((\"symbol\" \".2f\")))", "display-table: column symbol: format:")
        self.assertLispError("(display-table t :max-rows -1)", ":max-rows must be a whole number, 0 or more, or #f")
        self.assertLispError("(display-table t :rows 5)", ":rows isn't an option -- the options are :max-rows")

    def test_a_long_table_shows_its_first_rows_and_says_so(self):
        self.run_lisp("(display-table t :max-rows 1)")
        self.assertEqual(self.printed(), "symbol  strike      iv  volume\n"
                                         "------  ------  ------  ------\n"
                                         "SPY C      450  0.2345   12345\n"
                                         "(the first 1 of 2 rows -- :max-rows shows more)\n")

    def test_twenty_rows_unless_max_rows_says_otherwise(self):
        self.run_lisp('(define long (make-table "n" (list->vector (iota 25))))')
        self.run_lisp("(display-table long)")
        self.assertTrue(self.printed().endswith("19\n(the first 20 of 25 rows -- :max-rows shows more)\n"))
        self.out.clear()
        self.run_lisp('(display-table long \'(("n" ",")) :max-rows #f)')         # after formats; #f: every row
        self.assertTrue(self.printed().endswith("\n23\n24\n"), self.printed())
        self.out.clear()
        self.run_lisp("(display-table long :max-rows 0)")
        self.assertEqual(self.printed(), "n\n-\n(the first 0 of 25 rows -- :max-rows shows more)\n")

    def test_a_hidden_column_is_left_out(self):
        self.run_lisp("(display-table t '((\"strike\" hide) (\"iv\" \"hide\") (\"volume\" \",\")))")
        self.assertEqual(self.printed(), "symbol  volume\n------  ------\nSPY C   12,345\nSPY|P       67\n")
        self.out.clear()
        self.run_lisp("(display-table t '((\"symbol\" hide) (\"strike\" hide) (\"iv\" hide) (\"volume\" hide)))")
        self.assertEqual(self.printed(), "(every column is hidden)\n")
        self.assertShows('(table-column-names t)', '("symbol" "strike" "iv" "volume")')      # the table is unchanged

    def test_what_the_table_callback_receives(self):
        shown = []
        env = lisp_builtins.make_global_env(output=self.out.append, table=shown.append)
        self.run_lisp("(display-table (make-table \"id\" (vector \"a\") \"n\" #(1.5)) '((\"n\" \".2f\")))",
                      env=env)
        self.assertEqual(shown, [[("id", ["a"], "left"), ("n", ["1.50"], "right")]])

    def test_the_markdown_a_notebook_shows(self):
        columns = [("id", ["a", "b|c"], "left"), ("n", ["1.50", ""], "right")]
        self.assertEqual(lisp_builtins.markdown_table(columns),
                         "| id | n |\n|:---|---:|\n| a | 1.50 |\n| b\\|c |  |")

    def test_markdown_characters_in_a_table_are_shown_as_they_are(self):
        """In a notebook, a pair of $ makes a formula -- "revenue ($bn)" and
        "free cash flow ($bn)" in one row turned the text between them into
        one and broke the table -- and * and _ make emphasis. Each is
        backslashed, which Markdown shows as the character itself."""
        columns = [("revenue ($bn)", ["K*sqrt(T)_x"], "left"), ("free cash flow ($bn)", ["<1> `a` ~b~"], "left")]
        self.assertEqual(lisp_builtins.markdown_table(columns).splitlines()[0],
                         "| revenue (\\$bn) | free cash flow (\\$bn) |")
        self.assertEqual(lisp_builtins.markdown_table(columns).splitlines()[2],
                         "| K\\*sqrt(T)\\_x | \\<1\\> \\`a\\` \\~b\\~ |")


class TestSaveVariables(LispTestCase):
    """save-variables and load-variables: variables saved in a JSON file,
    and defined again from it -- here, in a new environment, as in a later
    session."""

    VALUES = """
      (defstruct point x y)
      (define n 42)
      (define rate 0.0625)
      (define missing nan)
      (define big -inf)
      (define name "Pool \\"A\\" \u2014 2024")
      (define flags (list #t #f '()))
      (define sym 'balance)
      (define key :max-rows)
      (define day (date 2024 1 2))
      (define nested (list 1 (list 2 3) (vector 4 5) "six"))
      (define dotted (cons 'a 1))
      (define improper (cons 1 (cons 2 3)))
      (define v-float (vector 1.5 nan 0.1))
      (define v-int #(1 2 300))
      (define v-bits #(1 0 1))
      (define v-text (vector-lag (vector "a" "b" "c")))
      (define v-dates (vector (date 2024 1 2) (date 2024 2 1)))
      (define loans (make-table "id" (vector "a" "b") "balance" #(100.5 90) "start" (vector (date 2020 1 1) (date 2021 6 30))))
      (define pairs (list (cons 'a #(1 2)) (cons 'b #(3 4))))     ; symbols, so not a table
      (define h (make-hash-table))
      (hash-table-set! h "CA" 1)
      (hash-table-set! h 'NY (list 1 2))
      (hash-table-set! h (date 2024 1 1) "new year")
      (define p (make-point :x 1 :y (vector 2 3)))
      (define rows (table-rows loans))"""
    NAMES = ("n rate missing big name flags sym key day nested dotted improper v-float v-int v-bits v-text "
             "v-dates loans pairs h p rows")

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.path = os.path.join(folder, "work.json")
        self.env[lisp_core.Symbol("path")] = lisp_core.LispString(self.path)
        self.later = lisp_builtins.make_global_env(output=self.out.append)       # a later session
        self.later[lisp_core.Symbol("path")] = lisp_core.LispString(self.path)

    def test_every_kind_of_data_comes_back_as_it_was(self):
        self.run_lisp(self.VALUES)
        self.assertShows("(save-variables path %s)" % self.NAMES, "(%s)" % self.NAMES)
        self.run_lisp("(defstruct point x y)", env=self.later)
        names = self.run_lisp("(load-variables path)", env=self.later)
        self.assertEqual(lisp_core.to_string(names), "(%s)" % self.NAMES)
        for name in self.NAMES.split():
            symbol = lisp_core.Symbol(name)
            self.assertEqual(lisp_core.to_string(self.later[symbol]), lisp_core.to_string(self.env[symbol]), name)
        for name in ("v-float", "v-int", "v-bits", "v-text", "v-dates"):            # stored the same way
            symbol = lisp_core.Symbol(name)
            self.assertEqual(self.later[symbol].items.dtype, self.env[symbol].items.dtype, name)
        self.assertEqual(self.later[lisp_core.Symbol("v-float")].items[2], np.float32(0.1))
        self.assertEqual(self.run_lisp("(list (hash-table-ref h 'NY) (hash-table-ref h (date 2024 1 1)) (point? p)"
                                       " (point-x p) (row-ref (cadr rows) \"start\") (table? loans) (table? pairs))",
                                       env=self.later),
                         self.run_lisp("(list (hash-table-ref h 'NY) (hash-table-ref h (date 2024 1 1)) (point? p)"
                                       " (point-x p) (row-ref (cadr rows) \"start\") (table? loans) (table? pairs))"))

    def test_the_file_is_plain_json(self):
        self.run_lisp(self.VALUES)
        self.run_lisp("(save-variables path missing big sym day loans p)")
        def refuse(constant):
            raise AssertionError("not plain JSON: " + constant)
        with open(self.path, encoding="utf-8") as f:
            document = json.load(f, parse_constant=refuse)
        self.assertEqual((document["format"], document["version"]), ("morris-lisp variables", 1))
        self.assertEqual(document["variables"], {
            "missing": None, "big": {"number": "-inf"}, "sym": {"symbol": "balance"}, "day": {"date": "2024-01-02"},
            "loans": {"table": [["id", ["a", "b"]], ["balance", [100.5, 90.0]],
                                ["start", [{"date": "2020-01-01"}, {"date": "2021-06-30"}]]]},
            "p": {"struct": "point", "slots": {"x": 1, "y": {"vector": [2, 3]}}}})

    def test_load_variables_defines_them_at_the_top_level(self):
        self.run_lisp("(define rate 0.05) (save-variables path rate)")
        self.run_lisp("(define (restore) (load-variables path)) (restore)", env=self.later)
        self.assertShows("rate", "0.05")
        self.assertEqual(self.later[lisp_core.Symbol("rate")], 0.05)

    def test_models_predict_and_report_the_same(self):
        self.run_lisp("""
          (define x (cons "income" #(10 20 30 40 50 60 70 80)))
          (define kind (cons "kind" (vector "own" "rent" "own" "rent" "own" "rent" "own" "rent")))
          (define y (cons "spend" #(9 15 33 38 52 58 74 77)))
          (define linear (linear-regression (list x) y))
          (define lad (lad-regression (list x) y))
          (define logistic (logistic-regression (list x) (cons "default" #(0 0 1 0 1 0 1 1))))
          (define spline (spline-regression (list x kind) y (list 1 'categorical)))
          (define lad-spline (spline-lad (list x kind) y (list 1 'categorical)))
          (define between (logistic-regression (list x) y :floor 5 :ceiling 80))
          (define spline-between (spline-logistic (list x kind) y (list 1 'categorical) :floor 5 :ceiling 80))""")
        self.run_lisp("(save-variables path linear lad logistic spline lad-spline between spline-between)")
        self.run_lisp("(load-variables path)", env=self.later)
        for model in ("linear", "lad", "logistic", "between"):
            for src in ("(model-predict %s (list 45))" % model, "(model-report %s)" % model):
                self.assertEqual(self.run_lisp(src, env=self.later), self.run_lisp(src), src)
        for model in ("spline", "lad-spline", "spline-between"):
            for src in ('(model-predict %s (list 45 "rent"))' % model, "(model-report %s)" % model,
                        "(model-kind %s)" % model):
                self.assertEqual(self.run_lisp(src, env=self.later), self.run_lisp(src), src)
        self.assertIn("kind: categorical -- categories own, rent (baseline own)", self.run_lisp("(model-report spline)"))

    def test_what_cant_be_saved(self):
        self.run_lisp("(define rate 0.05) (save-variables path rate)")
        self.run_lisp("(define (f x) x) (define stuff (list 1 f))")
        self.assertLispError("(save-variables path rate stuff)",
                             "save-variables: can't save stuff: it is or holds #<procedure f>, which isn't data")
        self.run_lisp("(load-variables path)", env=self.later)                   # the earlier file, as it was
        self.assertEqual(self.later[lisp_core.Symbol("rate")], 0.05)
        self.assertLispError("(save-variables path (+ 1 2))", "save-variables: expected the names of variables, not (+ 1 2)")
        self.assertLispError("(save-variables path)",
                             "expected (save-variables path name... [:leave-out-procedures #t]), with at least one name")
        self.assertLispError("(save-variables path nowhere)", "unbound")

    def test_a_structs_procedures_can_be_left_out_and_come_back_as_their_defaults(self):
        tranche = "(defstruct tranche (children ()) (money 0.0) (f (lambda (x) (* x 3))))"
        self.run_lisp(tranche)
        self.run_lisp("(define senior (make-tranche :money 100.0 :children (list (make-tranche :money 40.0))))")
        self.assertLispError("(save-variables path senior)",
                             "can't save senior: it is or holds a tranche whose f slot holds #<procedure>, which "
                             "isn't data -- to leave a struct's procedures out of the file, give save-variables "
                             ":leave-out-procedures #t")
        self.assertShows("(save-variables path senior :leave-out-procedures #t)", "(senior)")
        with open(self.path, encoding="utf-8") as f:
            saved = json.load(f)["variables"]["senior"]
        self.assertEqual(saved["slots"], {"children": [{"struct": "tranche", "slots": {"children": [], "money": 40.0}}],
                                          "money": 100.0})
        self.run_lisp(tranche, env=self.later)
        self.run_lisp("(load-variables path)", env=self.later)
        self.assertEqual(lisp_core.to_string(self.run_lisp(
            "(list (tranche-money senior) ((tranche-f senior) 2) ((tranche-f (car (tranche-children senior))) 5))",
            env=self.later)), "(100.0 6 15)")

    def test_a_slot_the_file_doesnt_have_gets_its_default_as_make_gives_it(self):
        self.run_lisp("(defstruct loan balance) (define big (make-loan :balance 200000)) (save-variables path big)")
        self.run_lisp("(defstruct loan balance (fee (* balance 0.01)))", env=self.later)   # a slot gained since
        self.run_lisp("(load-variables path)", env=self.later)
        self.assertEqual(self.run_lisp("(loan-fee big)", env=self.later), 2000.0)        # from the saved balance

    def test_leaving_out_procedures_is_only_for_a_structs_slots(self):
        self.run_lisp("(define (f x) x) (define h (make-hash-table)) (hash-table-set! h 'rule f)")
        self.assertLispError("(save-variables path f :leave-out-procedures #t)", "can't save f: it is or holds #<procedure f>")
        self.assertLispError("(save-variables path h :leave-out-procedures #t)", "can't save h: it is or holds #<procedure f>")
        self.assertLispError("(save-variables path h :skip #t)", ":skip isn't an option -- the options are :leave-out-procedures")
        self.assertLispError("(save-variables path :leave-out-procedures #t)", "with at least one name")

    def test_what_cant_be_loaded(self):
        self.run_lisp(self.VALUES)
        self.run_lisp("(save-variables path rate p)")
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_lisp("(load-variables path)", env=self.later)
        self.assertIn("load-variables: can't load p: there's no point struct type -- define it with defstruct first",
                      str(caught.exception))
        self.assertNotIn(lisp_core.Symbol("rate"), self.later)                     # nothing defined
        self.run_lisp("(defstruct point x)", env=self.later)                         # it has lost its y slot
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_lisp("(load-variables path)", env=self.later)
        self.assertIn("can't load p: the saved point has slots a point doesn't have now: y", str(caught.exception))
        with open(self.path, "w") as f:
            f.write('{"rate": 0.05}')
        self.assertLispError("(load-variables path)", "isn't a file save-variables wrote")
        with open(self.path, "w") as f:
            f.write("not JSON")
        self.assertLispError("(load-variables path)", "isn't a JSON file")
        self.assertLispError('(load-variables "/no/such/file.json")', "couldn't read /no/such/file.json")


class TestStratify(LispTestCase):
    """lisp_stratify.py: stratify and stratify-all."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define loans
            (make-table "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 nan)
                        "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000)
                        "age"     #(12 24 36 6 48 60 3 72 18 30)
                        "ltv"     #(80 75 90 60 95 70 85 65 78 88)
                        "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA")
                        "first"   (vector (date 2019 3 1) (date 2020 5 1) (date 2021 1 1) (date 2019 7 1)
                                          (date 2022 2 1) (date 2018 9 1) (date 2023 4 1) (date 2020 8 1)
                                          (date 2021 6 1) (date 2022 11 1))))
          (define summaries '(("rate" weighted-mean "WAC") ("age" weighted-mean "WALA")))""")

    def strat(self, by, extra=':weight "balance"'):
        return "(stratify loans '%s summaries %s)" % (by, extra)

    def column(self, by, name, extra=':weight "balance"'):
        return self.show('(table-column %s "%s")' % (self.strat(by, extra), name))

    def test_breakpoints(self):
        by = '("rate" (4.0 5.0 6.0 7.0))'
        self.assertEqual(self.column(by, "rate"),
                         '#("under 4.0" "4.0 to 5.0" "5.0 to 6.0" "6.0 to 7.0" "7.0 and over" "missing" "total")')
        self.assertEqual(self.column(by, "count"), "#(2 1 2 2 2 1 10)")
        self.assertEqual(self.column(by, "total balance"),
                         "#(310000.0 250000.0 475000.0 215000.0 460000.0 50000.0 1760000.0)")
        self.assertEqual(self.show("(table-column-names %s)" % self.strat(by)),
                         '("rate" "count" "total balance" "percent" "WAC" "WALA")')
        wac = self.run_lisp('(vector-ref (table-column %s "WAC") 0)' % self.strat(by))
        self.assertAlmostEqual(wac, (3.25 * 100000 + 3.99 * 210000) / 310000, places=5)
        percent = self.run_lisp('(vector-ref (table-column %s "percent") 0)' % self.strat(by))
        self.assertAlmostEqual(percent, 310000 / 1760000)

    def test_a_row_is_in_the_bucket_its_value_starts(self):
        self.run_lisp("(define t (make-table \"x\" #(4.0 5.0) \"w\" #(1 1)))")
        self.assertShows("(table-column (stratify t '(\"x\" (4.0 5.0)) '() :total #f) \"x\")",
                         '#("4.0 to 5.0" "5.0 and over")')

    def test_equal_count(self):
        by = '("age" (equal-count 3))'
        self.assertEqual(self.column(by, "age"), '#("3 to 12" "18 to 36" "48 to 72" "total")')
        self.assertEqual(self.column(by, "count"), "#(3 4 3 10)")

    def test_equal_weight(self):
        by = '("ltv" (equal-weight 3))'
        self.assertEqual(self.column(by, "ltv"), '#("60 to 70" "75 to 80" "85 to 95" "total")')
        self.assertEqual(self.column(by, "total balance"), "#(450000.0 560000.0 750000.0 1760000.0)")

    def test_equal_buckets_keep_equal_values_together(self):
        self.run_lisp("(define t (make-table \"x\" #(1 2 2 2 2 2 3 4) \"w\" #(1 1 1 1 1 1 1 1)))")
        self.assertShows("(table-column (stratify t '(\"x\" (equal-count 4)) '()) \"x\")",
                         '#("1 to 1" "2 to 2" "3 to 4" "total")')

    def test_top_and_each(self):
        self.assertEqual(self.column('("state" (top 2))', "state"), '#("CA" "FL" "other" "total")')
        self.assertShows("(table-column (stratify loans '(\"state\" (top 2)) '()) \"state\")",
                         '#("CA" "NY" "other" "total")')                     # by rows, without a weight
        self.assertEqual(self.column('("state" each)', "state"), '#("CA" "FL" "NY" "TX" "WA" "total")')
        self.assertEqual(self.column('("rate" (top 2))', "rate"), '#(7.0 5.75 "other" "missing" "total")')

    def test_year_and_date_breakpoints(self):
        self.assertEqual(self.column('("first" year)', "first"),
                         '#(2018 2019 2020 2021 2022 2023 "total")')
        self.assertShows("(table-column (stratify loans (list \"first\" (list (date 2020 1 1) (date 2022 1 1)))"
                         " summaries :weight \"balance\") \"first\")",
                         '#("under 2020-01-01" "2020-01-01 to 2022-01-01" "2022-01-01 and over" "total")')
        self.assertLispError(self.strat('("rate" year)'), "stratify: bucketing rate by year needs a column of dates")

    def test_several_columns_at_once(self):
        by = '(("state" (top 2)) ("rate" (5.0)))'
        self.assertEqual(self.column(by, "state"), '#("CA" "CA" "FL" "other" "other" "other" "total")')
        self.assertEqual(self.column(by, "rate"),
                         '#("under 5.0" "5.0 and over" "5.0 and over" "under 5.0" "5.0 and over" "missing" "")')
        self.assertEqual(self.column(by, "count"), "#(2 2 1 1 3 1 10)")

    def test_without_a_weight(self):
        self.assertEqual(self.show("(table-column-names (stratify loans '(\"state\" each) '((\"age\" mean))))"),
                         '("state" "count" "percent" "age (mean)")')
        self.assertLispError("(stratify loans '(\"state\" each) summaries)", "a weighted-mean needs a weight")
        self.assertLispError("(stratify loans '(\"ltv\" (equal-weight 3)) '())", "equal-weight buckets need a weight")

    def test_no_total_row(self):
        self.assertEqual(self.column('("state" (top 2))', "count", ':weight "balance" :total #f'), "#(4 1 5)")

    def test_totals_are_kept_in_full_precision(self):
        self.run_lisp("(define t (make-table \"x\" #(1 2) \"w\" (vector 16777216.0 1.0)))")
        self.assertShows("(table-column (stratify t '(\"x\" each) '((\"w\" sum)) :weight \"w\") \"total w\")",
                         "#(16777216.0 1.0 16777217.0)")      # 32-bit storage would round the total to ...216
        self.assertShows("(table-column (stratify t '(\"x\" each) '((\"w\" sum)) :weight \"w\") \"w (sum)\")",
                         "#(16777216.0 1.0 16777217.0)")

    def test_stratifying_by_the_weight_column(self):
        self.assertEqual(self.column('("balance" (100000 200000))', "balance"),
                         '#("under 100000" "100000 to 200000" "200000 and over" "total")')

    def test_representative_and_mode_for_columns_that_cannot_be_averaged(self):
        by = '("rate" (5.0))'
        summaries = "'((\"state\" representative) (\"state\" mode \"most loans\") (\"state\" weighted-mode \"most balance\"))"
        table = "(stratify loans '%s %s :weight \"balance\")" % (by, summaries)
        self.assertShows('(table-column %s "state (representative)")' % table, '#("CA" "CA" "WA" "CA")')
        self.assertShows('(table-column %s "most loans")' % table, '#("CA" "CA" "WA" "CA")')
        self.assertShows('(table-column %s "most balance")' % table, '#("CA" "FL" "WA" "CA")')

    def test_medians_and_percentiles(self):
        self.run_lisp("(define t (make-table \"x\" #(1 1 1 2) \"fico\" #(700 720 730 640)"
                      " \"w\" #(100 250 210 50)))")
        table = ("(stratify t '(\"x\" each) '((\"fico\" median) (\"fico\" weighted-median)"
                 " (\"fico\" (percentile 10)) (\"fico\" (weighted-percentile 90))) :weight \"w\")")
        self.assertShows('(table-column-names %s)' % table,
                         '("x" "count" "total w" "percent" "fico (median)" "fico (weighted-median)"'
                         ' "fico (percentile 10)" "fico (weighted-percentile 90)")')
        self.assertShows('(table-column %s "fico (median)")' % table, "#(720.0 640.0 710.0)")
        self.assertShows('(table-column %s "fico (weighted-median)")' % table, "#(720.0 640.0 720.0)")
        self.assertShows('(table-column %s "fico (percentile 10)")' % table, "#(704.0 640.0 658.0)")
        self.assertShows('(table-column %s "fico (weighted-percentile 90)")' % table, "#(730.0 640.0 730.0)")

    def test_bad_percentiles(self):
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" (percentile 120))))",
                             "a percentile is written (percentile p) or (weighted-percentile p)")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" percentile)))",
                             "say which percentile, e.g. (percentile 90)")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" weighted-median)))",
                             "a weighted-median needs a weight")

    def test_stratify_all(self):
        tables = self.run_lisp("(stratify-all loans '((\"state\" (top 2)) (\"age\" (equal-count 3))) "
                               "summaries :weight \"balance\")")
        names = [lisp_core.to_string(lisp_core.pairs_to_list(t)[0].car) for t in lisp_core.pairs_to_list(tables)]
        self.assertEqual(names, ['"state"', '"age"'])

    def test_errors(self):
        self.assertLispError(self.strat('("rate" (between 1 2))'), "stratify: can't bucket rate by (between 1 2)")
        self.assertLispError(self.strat('("nope" each)'), "no column named")
        self.assertLispError(self.strat('("rate")'), "each way of bucketing is (column how)")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" average)))",
                             "stratify: average isn't a summary")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" mean \"count\")))",
                             "two columns would both be called count")
        self.assertLispError("(stratify loans '(\"rate\" each) '() :weigth \"balance\")", ":weigth isn't an option")


class TestCsvFiles(LispTestCase):
    """lisp_csv.py: load-csv reads a table, write-columns-csv writes one."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_columns_become_numbers_dates_or_strings(self):
        path = self.write("a.csv", "id,when,us_date,amount,count\n"
                                   "x,2024-01-31,01/31/2024,1.5,3\n"
                                   "y,,02/29/2024,,4\n")
        self.run_lisp('(define t (load-csv "%s"))' % path)
        self.assertShows('(table-column t "id")', '#("x" "y")')
        self.assertShows('(table-column t "when")', "#(2024-01-31 ())")
        self.assertShows('(table-column t "us_date")', "#(2024-01-31 2024-02-29)")
        self.assertShows('(table-column t "amount")', "#(1.5 nan)")
        self.assertShows('(table-column t "count")', "#(3 4)")

    def test_no_header_and_short_rows(self):
        path = self.write("b.csv", "1,2\n3\n")
        self.assertShows('(load-csv "%s" #f)' % path, '(("Column1" . #(1 3)) ("Column2" . #(2.0 nan)))')
        self.assertLispError('(load-csv "%s")' % self.write("c.csv", "a\n1,2\n"), "only 1 columns")

    def test_write_then_read_back(self):
        path = os.path.join(self.dir, "out.csv")
        self.run_lisp('''(write-columns-csv "%s" (make-table "id" (vector "a" "b")
                                                  "x" (vector 1.5 nan)
                                                  "d" (vector (date 2024 1 1) (date 2024 2 1))))''' % path)
        with open(path) as f:
            self.assertEqual(f.read().splitlines(), ["id,x,d", "a,1.5,2024-01-01", "b,,2024-02-01"])
        self.assertShows('(load-csv "%s")' % path,
                         '(("id" . #("a" "b")) ("x" . #(1.5 nan)) ("d" . #(2024-01-01 2024-02-01)))')


class TestSqlite(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define conn (sqlite-open ":memory:"))
          (sqlite-execute conn "CREATE TABLE t (id INTEGER, name TEXT, amount REAL)")
          (sqlite-execute conn "INSERT INTO t VALUES (1, 'ann', 10.5)")
          (sqlite-execute conn "INSERT INTO t VALUES (2, 'bob', 20.0)")
          (sqlite-execute conn "INSERT INTO t VALUES (3, 'cy', 30.25)")""")

    def tearDown(self):
        self.run_lisp("(sqlite-close conn)")

    def test_query_returns_column_wise_name_vector_pairs(self):
        self.assertShows('(sqlite-query conn "SELECT id, name FROM t ORDER BY id")',
                         '(("id" . #(1 2 3)) ("name" . #("ann" "bob" "cy")))')

    def test_query_with_bound_parameters(self):
        self.assertShows("(sqlite-query conn \"SELECT name FROM t WHERE id = ?\" '() '() (list 2))",
                         '(("name" . #("bob")))')

    def test_execute_with_bound_parameters_then_read_back(self):
        self.run_lisp('(sqlite-execute conn "INSERT INTO t VALUES (?, ?, ?)" (list 4 "dee" 1.5))')
        self.assertShows("(vector-sum (cdr (car (sqlite-query conn \"SELECT id FROM t\"))))", "10")

    def test_fetch_row_steps_through_a_result_then_returns_empty(self):
        self.run_lisp('(define cur (sqlite-execute conn "SELECT id FROM t ORDER BY id"))')
        self.assertShows("(list (sqlite-fetch-row cur) (sqlite-fetch-row cur) (sqlite-fetch-row cur) (sqlite-fetch-row cur))",
                         "((1) (2) (3) ())")

    def test_null_in_a_text_column_is_the_empty_list(self):
        self.run_lisp('(sqlite-execute conn "INSERT INTO t VALUES (9, NULL, 1.0)")')
        self.assertShows('(vector-ref (cdr (car (sqlite-query conn "SELECT name FROM t WHERE id = 9"))) 0)', "()")

    def test_dtype_hints_force_vector_types(self):
        cols = self.run_lisp('(sqlite-query conn "SELECT id, amount FROM t ORDER BY id" "IF" 10)')
        self.assertEqual(cols.car.cdr.items.dtype, lisp_core.LispVector.INT_DTYPE)
        self.assertEqual(cols.cdr.car.cdr.items.dtype, lisp_core.LispVector.FLOAT_DTYPE)

    def test_max_rows_bound_is_enforced(self):
        self.assertLispError('(sqlite-query conn "SELECT id FROM t" "I" 2)')

    def test_predicates(self):
        self.assertShows("(sqlite-connection? conn)", "#t")
        self.assertShows("(sqlite-connection? 5)", "#f")
        self.assertShows('(sqlite-cursor? (sqlite-execute conn "SELECT 1"))', "#t")

    def test_sql_errors_are_lisp_errors(self):
        self.assertLispError('(sqlite-query conn "SELECT nope FROM missing")', "sqlite")

    def test_a_non_connection_is_rejected(self):
        self.assertLispError('(sqlite-query 5 "SELECT 1")', "sqlite connection")

    def test_a_hostile_value_is_data_not_sql_when_bound(self):
        self.run_lisp("""(sqlite-execute conn "INSERT INTO t VALUES (?, ?, ?)"
                          (list 7 "x'); DROP TABLE t; --" 0.0))""")
        # the table still exists, and the hostile text was stored verbatim
        self.assertShows("(vector-length (cdr (car (sqlite-query conn \"SELECT id FROM t\"))))", "4")
        self.assertShows("(vector-ref (cdr (car (sqlite-query conn \"SELECT name FROM t WHERE id = 7\"))) 0)",
                         '"x\'); DROP TABLE t; --"')

    def test_null_in_a_numeric_column_is_nan(self):
        self.run_lisp('(sqlite-execute conn "INSERT INTO t VALUES (9, NULL, NULL)")')
        self.assertShows('(cdr (car (sqlite-query conn "SELECT amount FROM t ORDER BY id")))',
                         "#(10.5 20.0 30.25 nan)")

    def test_write_table_round_trip(self):
        self.run_lisp("""
          (define tbl (make-table "id" (vector "a" "b") "x" (vector 1.5 nan)
                                  "d" (vector (date 2024 1 1) (date 2024 2 1)) "odd \\"name\\"" #(1 2)))""")
        self.assertShows('(sqlite-write-table conn "w" tbl)', "2")
        self.assertShows('(sqlite-query conn "SELECT id, x, d FROM w")',
                         '(("id" . #("a" "b")) ("x" . #(1.5 nan)) ("d" . #(2024-01-01 2024-02-01)))')
        names = self.run_lisp('(table-column-names (sqlite-query conn "SELECT * FROM w"))')
        self.assertEqual(lisp_core.pairs_to_list(names)[-1], 'odd "name"')     # quoted safely

    def test_write_table_modes(self):
        self.run_lisp('(define tbl (make-table "n" #(1 2)))')
        self.run_lisp('(sqlite-write-table conn "w" tbl)')
        self.assertLispError('(sqlite-write-table conn "w" tbl)', "already exists")
        self.run_lisp('(sqlite-write-table conn "w" tbl (quote append))')
        self.assertShows('(cdr (car (sqlite-query conn "SELECT count(*) AS n FROM w")))', "#(4)")
        self.run_lisp('(sqlite-write-table conn "w" (make-table "n" #(9)) (quote replace))')
        self.assertShows('(cdr (car (sqlite-query conn "SELECT n FROM w")))', "#(9)")

    def test_a_failed_write_changes_nothing(self):
        self.run_lisp('(sqlite-write-table conn "w" (make-table "n" #(1)))')
        self.assertLispError('(sqlite-write-table conn "w" (make-table "other" #(5)) (quote append))',
                             "no column named other")
        self.assertShows('(cdr (car (sqlite-query conn "SELECT count(*) AS n FROM w")))', "#(1)")


if __name__ == "__main__":
    unittest.main()
