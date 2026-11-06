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


# Closes for the principal components: AAA and BBB go up and down with one pattern (bank), CCC and DDD with another (oil). Monthly, from October 2025 to
# November 2026; weekly, from the week of Monday, October 20, 2025, to the week of November 2, 2026 (in each, the last is a period not yet over, which is to
# be left out). QQQQ is missing a period. ZZZ has no prices, and the Canadian EEE.TO is not to be asked for at all.
BANK = [0.02, -0.03, 0.05, 0.01, -0.02, 0.04, -0.01, 0.03, -0.04, 0.02, 0.01, -0.02, 0.03]
OIL = [-0.01, 0.04, -0.03, 0.02, 0.05, -0.02, 0.01, -0.05, 0.03, 0.02, -0.03, 0.04, 0.01]
WEEKS = 55          # October 20, 2025 to November 2, 2026
WEEKLY_BANK = [0.01 * ((i * 7) % 5 - 2) for i in range(WEEKS - 1)]
WEEKLY_OIL = [0.01 * ((i * 3) % 7 - 3) for i in range(WEEKS - 1)]


def closes(start, returns):
    prices = [start]
    for change in returns:
        prices.append(prices[-1] * (1 + change))
    return prices


MONTHLY = {"AAA": closes(100.0, BANK), "BBB": closes(50.0, [2 * r for r in BANK]),
           "CCC": closes(20.0, OIL), "DDD": closes(10.0, [3 * r for r in OIL]), "QQQQ": closes(5.0, BANK)}
WEEKLY = {"AAA": closes(100.0, WEEKLY_BANK), "BBB": closes(50.0, [2 * r for r in WEEKLY_BANK]),
          "CCC": closes(20.0, WEEKLY_OIL), "DDD": closes(10.0, [3 * r for r in WEEKLY_OIL]), "QQQQ": closes(5.0, WEEKLY_BANK)}

PRICES_SCHWAB = """
(define asked '())
; the stocks that pay dividends: (ticker annual-dividend payments-a-year ex-date), as Schwab's fundamentals have them
(define dividends '())
(define (schwab-get creds path params)
  (let ((answer (make-hash-table)))
    (hash-table-set! answer "instruments"
      (map (lambda (stock)
             (let ((instrument (make-hash-table)) (facts (make-hash-table)))
               (hash-table-set! facts "symbol" (car stock))
               (hash-table-set! facts "dividendAmount" (cadr stock))
               (hash-table-set! facts "dividendFreq" (caddr stock))
               (if (not (equal? (cadddr stock) "")) (hash-table-set! facts "dividendDate" (cadddr stock)))
               (hash-table-set! instrument "symbol" (car stock))
               (hash-table-set! instrument "fundamental" facts)
               instrument))
           (filter (lambda (stock) (string-search (cdr (assoc "symbol" params)) (car stock))) dividends)))
    answer))
(define (schwab-price-history creds ticker &key start-date end-date frequency)
  (set! asked (append asked (list ticker)))
  (let* ((weekly (equal? frequency "weekly"))
         (closes (assoc ticker (if weekly weekly-closes monthly-closes))))
    (if (not closes)
        (error (string-append "schwab-price-history: Schwab has no prices for " ticker " in those dates"))
        (let* ((days (map (lambda (i) (if weekly (date-add-days (date 2025 10 20) (* 7 i)) (date-add-months (date 2025 10 1) i)))
                          (iota (length (cdr closes)))))
               (table (make-table "date" (list->vector days) "close" (list->vector (cdr closes)))))
          (if (equal? ticker "QQQQ")
              (table-filter table (list->vector (map (lambda (day) (if (= (date-month day) 3) 0 1)) days)))     ; nothing in March
              table)))))
"""


class PricesTestCase(IndustryReturnsTestCase):
    """The stocks AAA, BBB, CCC, DDD and QQQQ, with prices, and ZZZ and EEE.TO."""

    def setUp(self):
        super().setUp()
        connection = sqlite3.connect(self.database)
        connection.executemany("INSERT INTO ticker_industry VALUES (?, ?)", [("EEE.TO", "Oil"), ("QQQQ", "Banks")])
        connection.commit()
        connection.close()
        for name, prices in (("monthly-closes", MONTHLY), ("weekly-closes", WEEKLY)):
            alist = " ".join('("%s" %s)' % (ticker, " ".join(repr(p) for p in values)) for ticker, values in prices.items())
            self.run_lisp("(define %s '(%s))" % (name, alist))
        self.run_lisp(PRICES_SCHWAB)

    def return_of(self, ticker, index):
        return self.run_lisp('(vector-ref (table-column (periodic-returns db %s) "%s") %d)' % (self.options, ticker, index))

    def update(self):
        return self.run_lisp('(stock-prices-update creds db %s :end-date "2026-11-05")' % self.options)


class TestMonthlyReturns(PricesTestCase):
    options = ':frequency "monthly" :years 1'

    def test_the_whole_months_are_kept_and_the_canadian_stocks_are_not_asked_for(self):
        self.update()
        self.assertEqual(self.stored("SELECT MIN(period), MAX(period), COUNT(*) FROM monthly_prices WHERE ticker = 'AAA'"),
                         [("2025-10-01", "2026-10-01", 13)])
        self.assertShows("(member \"EEE.TO\" asked)", "#f")

    def test_the_summary_says_which_stocks_have_every_period(self):
        self.assertShows('(table-column %s "what")' % '(stock-prices-update creds db :frequency "monthly" :years 1 :end-date "2026-11-05")',
                         '#("every period" "Schwab has no prices for it" "some periods")')
        self.assertShows('(table-column %s "stocks")' % '(stock-prices-update creds db :frequency "monthly" :years 1 :end-date "2026-11-05")',
                         "#(4 1 1)")

    def test_a_second_call_asks_for_nothing(self):
        self.update()
        self.run_lisp("(set! asked '())")
        self.update()
        self.assertShows("asked", "()")

    def test_a_quarterly_dividend_is_a_quarter_of_the_years_in_each_month_with_an_ex_date(self):
        # AAA pays 4.00 a year, quarterly, and its last ex-date was August 14, 2026: so also in May and February 2026 and November 2025
        self.run_lisp("""(set! dividends '(("AAA" 4.0 4 "2026-08-14 00:00:00.0")))""")
        self.update()
        # November 2025: the price goes from 100 to 102 (BANK[0] is 2%), and the dividend is 1: (102 - 100 + 1) / 100
        self.assertAlmostEqual(self.return_of("AAA", 0), 0.03)
        # December 2025 has no ex-date: the price change alone
        self.assertAlmostEqual(self.return_of("AAA", 1), BANK[1])
        self.assertEqual([i for i in range(12) if abs(self.return_of("AAA", i) - BANK[i]) > 1e-12], [0, 3, 6, 9])   # Nov, Feb, May, Aug

    def test_the_ex_dates_go_forward_from_schwabs_as_well_as_back(self):
        # an ex-date of May 31, 2026, paid twice a year: November 2025 and May 2026 (and May 31 less 6 months is November 30, not December 1)
        self.run_lisp("""(set! dividends '(("AAA" 2.0 2 "2026-05-31 00:00:00.0") ("CCC" 1.2 12 "2025-12-02 00:00:00.0")))""")
        self.update()
        self.assertEqual([i for i in range(12) if abs(self.return_of("AAA", i) - BANK[i]) > 1e-12], [0, 6])
        # CCC pays monthly, and Schwab's ex-date is in December 2025: every month has a dividend of 0.10, before it and after it
        self.assertEqual([i for i in range(12) if abs(self.return_of("CCC", i) - OIL[i]) > 1e-12], list(range(12)))

    def test_a_dividend_without_an_ex_date_is_a_twelfth_every_month(self):
        self.run_lisp("""(set! dividends '(("CCC" 12.0 0 "")))""")
        self.update()
        # November 2025: CCC goes from 20 to 19.8 (OIL[0] is -1%), with a dividend of 1: (19.8 - 20 + 1) / 20
        self.assertAlmostEqual(self.return_of("CCC", 0), 0.04)

    def test_the_dividends_are_kept_and_counted(self):
        self.run_lisp("""(set! dividends '(("AAA" 4.0 4 "2026-08-14 00:00:00.0") ("BBB" 0.0 0 "")))""")
        self.update()
        self.assertEqual(self.stored("SELECT * FROM stock_dividends ORDER BY ticker"), [("AAA", 4.0, 4, "2026-08-14"), ("BBB", 0.0, 0, "")])
        self.assertShows('(table-column (stock-dividends-update creds db) "paying_dividends")', "#(1)")

    def test_only_the_stocks_with_every_period_are_in_the_returns(self):
        self.update()
        self.assertShows('(table-column-names (periodic-returns db %s))' % self.options, '("period" "AAA" "BBB" "CCC" "DDD")')
        self.assertShows('(table-row-count (periodic-returns db %s))' % self.options, "12")

    def test_two_patterns_explain_all_of_four_stocks_that_follow_two_patterns(self):
        self.update()
        self.run_lisp("(define components (return-components db %s :count 3))" % self.options)
        shares = self.run_lisp('(vector->list (table-column (cdr (assoc "components" components)) "cumulative-share"))')
        self.assertAlmostEqual(shares.cdr.car, 1.0)            # two components explain everything
        self.assertAlmostEqual(shares.cdr.cdr.car, 1.0)
        self.assertShows('(vector-round (table-column (cdr (assoc "stocks" components)) "explained") 6)', "#(1.0 1.0 1.0 1.0)")
        # with 12 months, a component of stocks that moved independently would explain 1/11 of the variation
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column (cdr (assoc "components" components)) "share-if-unrelated") 0)'), 1 / 11)

    def test_an_error_that_would_happen_for_every_stock_stops_the_run(self):
        self.run_lisp('(define (schwab-price-history creds ticker &key start-date end-date frequency) '
                      '(error "schwab-price-history: the Schwab sign-in has run out -- sign in again with (schwab-login creds)"))')
        self.assertLispError('(stock-prices-update creds db %s :end-date "2026-11-05")' % self.options, "sign in again")
        self.assertEqual(self.stored("SELECT COUNT(*) FROM monthly_prices_asked"), [(0,)])

    def test_the_stocks_table_has_each_stocks_industry_and_the_industries_table_averages_them(self):
        self.update()
        components = "(return-components db %s :count 2)" % self.options
        self.assertShows('(table-column (cdr (assoc "stocks" %s)) "industry")' % components, '#("Banks" "Banks" "Oil" "Oil")')
        self.assertShows('(table-column-names (cdr (assoc "industries" %s)))' % components, '("industry" "stocks" "pc1" "pc2" "explained")')
        self.assertShows('(table-column-names (cdr (assoc "periods" %s)))' % components, '("period" "pc1" "pc2" "market-return")')


class TestWeeklyReturns(PricesTestCase):
    options = ":years 1"         # weekly is the default

    def test_the_weeks_start_on_mondays_and_the_week_not_yet_over_is_left_out(self):
        self.update()
        # November 5, 2026 is a Thursday: the last whole week is the one of Monday, October 26; a year before it is in the week of October 20, 2025
        self.assertEqual(self.stored("SELECT MIN(period), MAX(period), COUNT(*) FROM weekly_prices WHERE ticker = 'AAA'"),
                         [("2025-10-20", "2026-10-26", 54)])
        self.assertEqual(self.stored("SELECT DISTINCT last_period FROM weekly_prices_asked"), [("2026-10-26",)])

    def test_three_years_is_the_usual_and_monthly_and_weekly_are_kept_apart(self):
        self.run_lisp('(stock-prices-update creds db :end-date "2026-11-05")')
        self.assertEqual(self.stored("SELECT COUNT(*) FROM weekly_prices_asked"), [(6,)])
        self.assertEqual(self.stored("SELECT name FROM sqlite_master WHERE name = 'monthly_prices'"), [])
        self.assertLispError('(stock-prices-update creds db :frequency "daily")', "weekly")

    def test_a_dividend_is_in_the_week_of_each_ex_date(self):
        # AAA pays 4.00 a year, quarterly; Schwab's ex-date is Friday, August 14, 2026, so the others are May 14 (a Thursday), February 14 (a Saturday:
        # the week of Monday the 9th) and November 14, 2025 (a Friday)
        self.run_lisp("""(set! dividends '(("AAA" 4.0 4 "2026-08-14 00:00:00.0")))""")
        self.update()
        periods = self.run_lisp('(vector->list (table-column (periodic-returns db :years 1) "period"))')
        weeks = []
        while periods is not lisp_core.NIL:
            weeks.append(str(periods.car))
            periods = periods.cdr
        with_dividend = [weeks[i] for i in range(len(weeks)) if abs(self.return_of("AAA", i) - WEEKLY_BANK[i]) > 1e-12]
        self.assertEqual(with_dividend, ["2025-11-10", "2026-02-09", "2026-05-11", "2026-08-10"])
        # the week of November 10, 2025 is the third return (the first is the week of October 27): AAA's price change that week, and a dividend of 1
        before, after = WEEKLY["AAA"][2], WEEKLY["AAA"][3]
        self.assertAlmostEqual(self.return_of("AAA", 2), (after - before + 1.0) / before)

    def test_a_dividend_without_an_ex_date_is_a_52nd_every_week(self):
        self.run_lisp("""(set! dividends '(("CCC" 52.0 0 "")))""")
        self.update()
        self.assertAlmostEqual(self.return_of("CCC", 0), (WEEKLY["CCC"][1] - 20.0 + 1.0) / 20.0)

    def test_two_patterns_explain_all_of_four_stocks_that_follow_two_patterns(self):
        self.update()
        self.run_lisp("(define components (return-components db :years 1 :count 3))")
        shares = self.run_lisp('(vector->list (table-column (cdr (assoc "components" components)) "cumulative-share"))')
        self.assertAlmostEqual(shares.cdr.car, 1.0)
        self.assertShows('(table-row-count (cdr (assoc "periods" components)))', "53")
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column (cdr (assoc "components" components)) "share-if-unrelated") 0)'), 1 / 52)

    def test_with_each_industry_following_one_pattern_the_industries_explain_the_components(self):
        self.update()
        self.run_lisp('(define components (return-components db :years 1 :count 2 :rotate "varimax"))')
        described = '(cdr (assoc "components" components))'
        self.assertShows('(table-column %s "component")' % described, '#("pc1" "pc2")')
        self.assertShows('(vector-round (table-column %s "industry-share") 6)' % described, "#(1.0 1.0)")
        self.assertShows('(vector-round (vector-abs (table-column %s "best-industry-correlation")) 6)' % described, "#(1.0 1.0)")
        self.assertShows('(sort (vector->list (table-column %s "best-industry")))' % described, '("Banks" "Oil")')
        # with four stocks and two industries, the share by chance is (2 - 1) / (4 - 1); no industry has the 10 stocks a label needs
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column %s "industry-share-by-chance") 0)' % described), 1 / 3)
        self.assertShows('(table-column %s "label")' % described, '#("" "")')

    def test_each_stocks_most_important_components_then_the_others_then_its_own(self):
        self.update()
        self.run_lisp('(define components (return-components db :years 1 :count 2 :rotate "varimax"))')
        self.run_lisp('(define mine (stock-components components :top 1))')
        self.assertShows('(table-row-count mine)', "12")                  # three rows for each of the four stocks
        self.assertShows('(table-column (table-head mine 3) "component")', '#("%s" "the other components" "its own")'
                         % self.run_lisp('(vector-ref (table-column mine "component") 0)'))
        self.assertShows('(table-column (table-head mine 3) "rank")', "#(1 2 3)")
        # AAA moves exactly with the bank pattern, which a rotated component nearly is (the made-up bank and oil patterns are a little correlated, so
        # not exactly): it explains nearly all of AAA, and the two components together explain all of it, so none of AAA is its own
        self.assertShows('(vector-round (table-column (table-head mine 3) "share") 2)', "#(1.0 0.0 0.0)")
        self.assertShows('(round-to-nearest (vector-ref (table-column mine "correlation") 0) 0.01)', "1.0")
