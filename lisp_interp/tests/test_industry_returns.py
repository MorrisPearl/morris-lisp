"""lib/industry_returns.lsp: each stock's return over a year (price change and dividend, from Schwab), the industries' market-cap-weighted returns, and how
the variation within industries compares with the variation between them. Schwab is replaced by Lisp stand-ins that know a few stocks."""

import os
import shutil
import sqlite3
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

# Stand-ins for Schwab's instruments endpoint and its price history, defined after the library is loaded so that they are what it calls.
# ticker: (market cap, annual dividend, price a year ago, price now); ZZZ is one Schwab has no prices for, and QQQQ is one with prices but no fundamentals.
SCHWAB = """
(define stocks '(("AAA" 100.0 2.0 50.0 52.0) ("BBB" 300.0 0.0 20.0 30.0) ("CCC" 200.0 1.0 10.0 9.0) ("DDD" 200.0 0.0 10.0 11.0) ("ZZZ" 1.0 0.0 1.0 1.0)
                 ("QQQQ" 0.0 0.0 5.0 5.0)))
(define schwab-calls '())
(define (schwab-get creds path params)
  (set! schwab-calls (append schwab-calls (list (cdr (assoc "symbol" params)))))
  (let ((answer (make-hash-table)))
    (hash-table-set! answer "instruments"
      (filter (lambda (x) x)
        (map (lambda (stock)
               (if (and (string-search (cdr (assoc "symbol" params)) (car stock)) (not (equal? (car stock) "QQQQ")))
                   (let ((instrument (make-hash-table)) (facts (make-hash-table)))
                     (hash-table-set! facts "marketCap" (cadr stock))
                     (hash-table-set! facts "dividendAmount" (caddr stock))
                     (hash-table-set! instrument "symbol" (car stock))
                     (hash-table-set! instrument "fundamental" facts)
                     instrument)
                   #f))
             stocks)))
    answer))
(define (schwab-price-history creds ticker &key start-date end-date)
  (let ((stock (assoc ticker stocks)))
    (if (equal? ticker "ZZZ")
        (error "schwab-price-history: Schwab has no prices for ZZZ in those dates")
        (make-table "date" (vector (date 2025 11 5) (date 2025 11 6) (date 2026 11 4))
                    "close" (vector (cadddr stock) 0.0 (car (cddddr stock)))))))
"""

# the industry of each ticker: two industries, with AAA and BBB in one and CCC, DDD, ZZZ and QQQQ in the other
INDUSTRIES = [("AAA", "Banks"), ("BBB", "Banks"), ("CCC", "Oil"), ("DDD", "Oil"), ("ZZZ", "Oil"), ("QQQQ", "Oil")]


class IndustryReturnsTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.database = os.path.join(self.folder, "financial_data.db")
        self.env[lisp_core.Symbol("db")] = lisp_core.LispString(self.database)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(self.folder, "credentials.json"))
        self.make_industries(INDUSTRIES)
        self.run_lisp('(load "industry_returns.lsp")')
        self.run_lisp(SCHWAB)
        self.run_lisp("(define stock-returns-pause 0.0)")

    def make_industries(self, rows):
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE ticker_industry(ticker NUM,industry NUM)")
        connection.executemany("INSERT INTO ticker_industry VALUES (?, ?)", rows)
        connection.commit()
        connection.close()

    def stored(self, sql):
        connection = sqlite3.connect(self.database)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()

    def update(self):
        return self.run_lisp('(stock-returns-update creds db :end-date "2026-11-05")')


class TestStockReturns(IndustryReturnsTestCase):

    def test_a_return_is_the_price_change_and_the_annual_dividend_over_the_starting_price(self):
        self.update()
        self.assertEqual(self.stored("SELECT ticker, start_price, end_price, dividend, market_cap, return FROM stock_returns "
                                     "WHERE return IS NOT NULL ORDER BY ticker"),
                         [("AAA", 50.0, 52.0, 2.0, 100.0, 0.08),         # (52 - 50 + 2) / 50
                          ("BBB", 20.0, 30.0, 0.0, 300.0, 0.5),
                          ("CCC", 10.0, 9.0, 1.0, 200.0, 0.0),            # the dividend makes up the loss
                          ("DDD", 10.0, 11.0, 0.0, 200.0, 0.1),
                          ("QQQQ", 5.0, 5.0, 0.0, None, 0.0)])

    def test_the_first_and_last_days_with_prices_are_kept(self):
        self.update()
        self.assertEqual(self.stored("SELECT year_end, start_date, end_date FROM stock_returns WHERE ticker = 'AAA'"),
                         [("2026-11-05", "2025-11-05", "2026-11-04")])

    def test_a_stock_schwab_has_no_prices_for_is_kept_with_a_note_and_no_return(self):
        self.update()
        self.assertEqual(self.stored("SELECT return, note FROM stock_returns WHERE ticker = 'ZZZ'"),
                         [(None, "Schwab has no prices for it")])

    def test_a_stock_with_prices_but_no_market_cap_has_a_return_and_a_note(self):
        self.update()
        self.assertEqual(self.stored("SELECT market_cap, note FROM stock_returns WHERE ticker = 'QQQQ'"),
                         [(None, "Schwab has no market cap or dividend for it")])

    def test_the_summary_counts_the_stocks_with_a_return_and_the_reasons_for_those_without(self):
        self.assertShows('(table-column (stock-returns-update creds db :end-date "2026-11-05") "stocks")', "#(5 1)")

    def test_market_caps_and_dividends_are_asked_for_in_batches(self):
        self.run_lisp("(define stock-returns-batch 4)")
        self.update()
        self.assertShows("(length schwab-calls)", "2")

    def test_a_second_call_asks_only_for_the_stocks_it_does_not_have(self):
        self.update()
        self.make_new_ticker()
        self.run_lisp("(set! schwab-calls '())")
        self.update()
        self.assertShows("schwab-calls", '("EEE")')

    def make_new_ticker(self):
        connection = sqlite3.connect(self.database)
        connection.execute("INSERT INTO ticker_industry VALUES ('EEE', 'Banks')")
        connection.commit()
        connection.close()
        self.run_lisp('(set! stocks (append stocks (list (list "EEE" 50.0 0.0 1.0 2.0))))')

    def test_a_later_year_end_asks_for_everything_again(self):
        self.update()
        self.run_lisp("(set! schwab-calls '())")
        self.run_lisp('(stock-returns-update creds db :end-date "2026-11-12")')
        self.assertShows("(length schwab-calls)", "1")


class TestIndustryReturns(IndustryReturnsTestCase):

    def test_an_industrys_return_is_weighted_by_market_cap(self):
        self.update()
        # Banks: AAA 0.08 (cap 100) and BBB 0.5 (cap 300): (8 + 150) / 400 = 0.395; the plain average is 0.29
        self.assertShows('(table-column (industry-returns db) "industry")', '#("Banks" "Oil")')
        self.assertShows('(table-column (industry-returns db) "weighted-return")', "#(0.395 0.05)")
        self.assertShows('(table-column (industry-returns db) "average-return")', "#(0.29 0.05)")
        self.assertShows('(table-column (industry-returns db) "stocks")', "#(2 2)")

    def test_a_stock_without_a_return_or_a_market_cap_is_left_out(self):
        self.update()
        self.assertShows('(table-column (industry-returns db) "market-cap")', "#(400.0 400.0)")


class TestIndustryVariation(IndustryReturnsTestCase):

    def make_database(self, rows, stocks):
        """A database of the industries (ticker, industry) and the stocks' returns ((ticker, market cap, return))."""
        os.remove(self.database)
        self.make_industries(rows)
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE stock_returns (ticker TEXT PRIMARY KEY, year_end TEXT, start_date TEXT, end_date TEXT, start_price REAL, "
                           "end_price REAL, dividend REAL, market_cap REAL, return REAL, note TEXT)")
        for ticker, cap, change in stocks:
            connection.execute("INSERT INTO stock_returns VALUES (?, '', '', '', 1, 1, 0, ?, ?, '')", (ticker, cap, change))
        connection.commit()
        connection.close()

    def measure(self, rows, stocks, column):
        """The measures of industry-variation, as a dictionary from name to the value in the column."""
        self.make_database(rows, stocks)
        names = ["stdev-of-all-returns", "stdev-within-industries", "stdev-between-industries", "share-explained-by-industry", "share-by-chance",
                 "stocks", "industries"]
        return {name: self.run_lisp('(let ((t (industry-variation db))) (vector-ref (table-column t "%s") (position "%s" (vector->list (table-column t "measure")))))'
                                    % (column, name)) for name in names}

    def test_industries_that_separate_returns_perfectly_explain_all_the_variation(self):
        rows = [("A", "x"), ("B", "x"), ("C", "y"), ("D", "y")]
        stocks = [("A", 1.0, 0.10), ("B", 3.0, 0.10), ("C", 1.0, 0.30), ("D", 5.0, 0.30)]
        shares = self.measure(rows, stocks, "equal-weights")
        self.assertAlmostEqual(shares["share-explained-by-industry"], 1.0)
        self.assertAlmostEqual(shares["stdev-within-industries"], 0.0)
        self.assertAlmostEqual(shares["stdev-between-industries"], 0.10)       # industries at 0.10 and 0.30: 0.10 either side of 0.20
        self.assertAlmostEqual(shares["stdev-of-all-returns"], 0.10)
        self.assertEqual((shares["stocks"], shares["industries"]), (4.0, 2.0))

    def test_industries_with_the_same_average_explain_nothing(self):
        rows = [("A", "x"), ("B", "x"), ("C", "y"), ("D", "y")]
        stocks = [("A", 1.0, 0.0), ("B", 1.0, 0.4), ("C", 1.0, 0.1), ("D", 1.0, 0.3)]
        shares = self.measure(rows, stocks, "equal-weights")
        self.assertAlmostEqual(shares["share-explained-by-industry"], 0.0)
        self.assertAlmostEqual(shares["stdev-between-industries"], 0.0)
        self.assertAlmostEqual(shares["stdev-within-industries"], shares["stdev-of-all-returns"])

    def test_the_split_adds_up_and_the_chance_share_is_industries_less_one_over_stocks_less_one(self):
        rows = [("A", "x"), ("B", "x"), ("C", "y"), ("D", "y"), ("E", "z")]
        stocks = [("A", 1.0, 0.0), ("B", 1.0, 0.2), ("C", 1.0, 0.5), ("D", 1.0, 0.1), ("E", 1.0, 0.4)]
        shares = self.measure(rows, stocks, "equal-weights")
        self.assertAlmostEqual(shares["stdev-within-industries"] ** 2 + shares["stdev-between-industries"] ** 2, shares["stdev-of-all-returns"] ** 2)
        self.assertAlmostEqual(shares["share-by-chance"], 2.0 / 4.0)

    def test_market_cap_weights_count_the_big_stocks_more(self):
        rows = [("A", "x"), ("B", "x"), ("C", "y"), ("D", "y")]
        stocks = [("A", 1.0, 0.0), ("B", 99.0, 0.2), ("C", 1.0, 0.3), ("D", 99.0, 0.3)]
        equal = self.measure(rows, stocks, "equal-weights")
        weighted = self.measure(rows, stocks, "market-cap-weights")
        # equal: y is 0.3 and x is 0.1, and the within variation is the 0.1 either side of x's average; weighted: B is nearly all of x, so x is almost one value
        self.assertGreater(weighted["share-explained-by-industry"], equal["share-explained-by-industry"])
        self.assertLess(weighted["stdev-within-industries"], equal["stdev-within-industries"])

    def test_ranks_keep_one_huge_return_from_deciding_the_answer(self):
        rows = [("A", "x"), ("B", "x"), ("C", "y"), ("D", "y")]
        stocks = [("A", 1.0, 0.1), ("B", 1.0, 0.2), ("C", 1.0, 0.3), ("D", 1.0, 100.0)]
        # ranks are 1/4 2/4 3/4 1: the industries' averages are 3/8 and 7/8, so between is 4/16 of the total 5/16
        self.assertAlmostEqual(self.measure(rows, stocks, "return-ranks")["share-explained-by-industry"], 0.8)
        # the return of 100 is so far from the others that it is nearly all the variation, and it is within an industry
        self.assertLess(self.measure(rows, stocks, "equal-weights")["share-explained-by-industry"], 0.5)
        self.assertAlmostEqual(self.measure(rows, stocks, "return-ranks")["share-by-chance"], 1.0 / 3.0)

    def test_the_functions_are_there_when_the_autoloads_are_loaded(self):
        self.run_lisp('(load "autoloads.lsp")')
        self.assertShows("(procedure? stock-returns-update)", "#t")
        self.assertShows("(procedure? industry-returns)", "#t")
        self.assertShows("(procedure? industry-variation)", "#t")


# Monthly closes for the principal components: AAA and BBB go up and down with one pattern (bank), CCC and DDD with another (oil), from October 2025
# to November 2026 (November is a month not yet over, which is to be left out). QQQQ is missing a month. ZZZ has no prices, and the Canadian XYZ.TO is not
# to be asked for at all.
BANK = [0.02, -0.03, 0.05, 0.01, -0.02, 0.04, -0.01, 0.03, -0.04, 0.02, 0.01, -0.02, 0.03]
OIL = [-0.01, 0.04, -0.03, 0.02, 0.05, -0.02, 0.01, -0.05, 0.03, 0.02, -0.03, 0.04, 0.01]


def closes(start, returns):
    prices = [start]
    for change in returns:
        prices.append(prices[-1] * (1 + change))
    return prices


MONTHLY = {"AAA": closes(100.0, BANK), "BBB": closes(50.0, [2 * r for r in BANK]),
           "CCC": closes(20.0, OIL), "DDD": closes(10.0, [3 * r for r in OIL]), "QQQQ": closes(5.0, BANK)}

MONTHLY_SCHWAB = """
(define monthly-asked '())
(define (schwab-price-history creds ticker &key start-date end-date frequency)
  (set! monthly-asked (append monthly-asked (list ticker)))
  (let ((closes (assoc ticker monthly-closes)))
    (if (not closes)
        (error (string-append "schwab-price-history: Schwab has no prices for " ticker " in those dates"))
        (let* ((months (map (lambda (i) (date-add-months (date 2025 10 1) i)) (iota (length (cdr closes)))))
               (table (make-table "date" (list->vector months) "close" (list->vector (cdr closes)))))
          (if (equal? ticker "QQQQ")
              (table-filter table (list->vector (map (lambda (day) (if (= (date-month day) 3) 0 1)) months)))     ; no March
              table)))))
"""


class TestMonthlyReturns(IndustryReturnsTestCase):

    def setUp(self):
        super().setUp()
        self.make_industries([("EEE.TO", "Oil")])
        connection = sqlite3.connect(self.database)
        connection.executemany("INSERT INTO ticker_industry VALUES (?, ?)", [("QQQQ", "Banks")])
        connection.commit()
        connection.close()
        alist = " ".join('("%s" %s)' % (ticker, " ".join(repr(p) for p in prices)) for ticker, prices in MONTHLY.items())
        self.run_lisp("(define monthly-closes '(%s))" % alist)
        self.run_lisp(MONTHLY_SCHWAB)

    def make_industries(self, rows):
        if os.path.exists(self.database) and rows != INDUSTRIES:
            connection = sqlite3.connect(self.database)
            connection.executemany("INSERT INTO ticker_industry VALUES (?, ?)", rows)
            connection.commit()
            connection.close()
        else:
            super().make_industries(rows)

    def update(self):
        return self.run_lisp('(monthly-prices-update creds db :years 1 :end-date "2026-11-05")')

    def test_the_whole_months_are_kept_and_the_canadian_stocks_are_not_asked_for(self):
        self.update()
        self.assertEqual(self.stored("SELECT MIN(month), MAX(month), COUNT(*) FROM monthly_prices WHERE ticker = 'AAA'"),
                         [("2025-10-01", "2026-10-01", 13)])
        self.assertShows("(member \"EEE.TO\" monthly-asked)", "#f")

    def test_the_summary_says_which_stocks_have_every_month(self):
        self.assertShows('(table-column (monthly-prices-update creds db :years 1 :end-date "2026-11-05") "what")',
                         '#("every month" "Schwab has no prices for it" "some months")')
        self.assertShows('(table-column (monthly-prices-update creds db :years 1 :end-date "2026-11-05") "stocks")', "#(4 1 1)")

    def test_a_second_call_asks_for_nothing(self):
        self.update()
        self.run_lisp("(set! monthly-asked '())")
        self.update()
        self.assertShows("monthly-asked", "()")

    def test_a_months_return_is_the_change_in_price_and_a_twelfth_of_the_dividend(self):
        self.update()
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE stock_returns (ticker TEXT PRIMARY KEY, year_end TEXT, start_date TEXT, end_date TEXT, start_price REAL, "
                           "end_price REAL, dividend REAL, market_cap REAL, return REAL, note TEXT)")
        connection.execute("INSERT INTO stock_returns VALUES ('AAA', '', '', '', 1, 1, 12.0, 100.0, 0, '')")
        connection.commit()
        connection.close()
        # November 2025: the price goes from 100 to 102 (BANK[0] is 2%), and a month's dividend is 1: (102 - 100 + 1) / 100
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column (monthly-returns db :years 1) "AAA") 0)'), 0.03)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column (monthly-returns db :years 1) "BBB") 0)'), 0.04)

    def test_only_the_stocks_with_every_month_are_in_the_returns(self):
        self.update()
        self.assertShows("(table-column-names (monthly-returns db :years 1))", '("month" "AAA" "BBB" "CCC" "DDD")')
        self.assertShows("(table-row-count (monthly-returns db :years 1))", "12")

    def test_two_patterns_explain_all_of_four_stocks_that_follow_two_patterns(self):
        self.update()
        self.run_lisp("(define components (return-components db :years 1 :count 3))")
        shares = self.run_lisp('(vector->list (table-column (cdr (assoc "variance" components)) "cumulative-share"))')
        self.assertAlmostEqual(shares.cdr.car, 1.0)            # two components explain everything
        self.assertAlmostEqual(shares.cdr.cdr.car, 1.0)
        self.assertShows('(vector-round (table-column (cdr (assoc "stocks" components)) "explained") 6)', "#(1.0 1.0 1.0 1.0)")
        # with 12 months, a component of stocks that moved independently would explain 1/11 of the variation
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column (cdr (assoc "variance" components)) "share-if-unrelated") 0)'), 1 / 11)

    def test_an_error_that_would_happen_for_every_stock_stops_the_run(self):
        self.run_lisp('(define (schwab-price-history creds ticker &key start-date end-date frequency) '
                      '(error "schwab-price-history: the Schwab sign-in has run out -- sign in again with (schwab-login creds)"))')
        self.assertLispError('(monthly-prices-update creds db :years 1 :end-date "2026-11-05")', "sign in again")
        self.assertEqual(self.stored("SELECT COUNT(*) FROM monthly_prices_asked"), [(0,)])

    def test_the_stocks_table_has_each_stocks_industry_and_the_industries_table_averages_them(self):
        self.update()
        components = "(return-components db :years 1 :count 2)"
        self.assertShows('(table-column (cdr (assoc "stocks" %s)) "industry")' % components, '#("Banks" "Banks" "Oil" "Oil")')
        self.assertShows('(table-column-names (cdr (assoc "industries" %s)))' % components, '("industry" "stocks" "pc1" "pc2" "explained")')
        self.assertShows('(table-column-names (cdr (assoc "months" %s)))' % components, '("month" "pc1" "pc2" "market-return")')
