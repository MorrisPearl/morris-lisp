"""lib/financial_data.lsp: the time_series table of the database of market history, the sources that fill it, the current coupon worked out from the TBA
prices, and reading series back. The sources (the Treasury, FRED, the New York Fed, FINRA) are replaced by Lisp stand-ins that give small tables."""

import datetime
import os
import shutil
import sqlite3
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

# Stand-ins for the sources, defined after the library is loaded so that they are what it calls.
SOURCES = """
(define source-calls '())
(define (note-call name from to) (set! source-calls (append source-calls (list (list name (date->string from) (date->string to))))))
(define (finra-tba-update creds db &key (start-date '()) (end-date '())) '())
(define (treasury-par-curve &key start-date end-date)
  (note-call "treasury" start-date end-date)
  (make-table "date" (vector (date 2026 10 27) (date 2026 10 28))
              "1m" #(0.0410 0.0409) "1.5m" #(nan 0.0413) "2m" #(0.0417 0.0416) "3m" #(0.0426 0.0425) "4m" #(nan nan) "6m" #(0.0436 0.0435)
              "1y" #(0.0451 0.0452) "2y" #(0.0479 0.0481) "3y" #(0.0486 0.0489) "5y" #(0.0494 0.0495) "7y" #(0.0502 0.0503)
              "10y" #(0.0512 0.0513) "20y" #(0.0547 0.0547) "30y" #(0.0542 0.0542)))
(define (fred-table creds ids &key start-date end-date cache-hours)
  (note-call "fred" start-date end-date)
  (make-table "date" (vector (date 2026 10 22) (date 2026 10 29)) "MORTGAGE30US" #(7.1 7.24) "MORTGAGE15US" #(6.4 nan)))
(define (nyfed-rates names &key start-date end-date cache-hours)
  (note-call "nyfed" start-date end-date)
  (make-table "date" (vector (date 2026 10 27) (date 2026 10 28))
              "SOFR" #(3.95 3.94) "SOFR-30" #(3.89 3.90) "SOFR-90" #(3.91 3.92) "SOFR-180" #(3.93 3.94) "SOFR-INDEX" #(1.2645 1.2646)))
"""

# FINRA's TBA prices for two days: (date, coupon, settlement month, weighted price, trades)
TBA_ROWS = [
    # 10-27: June is the month being traded; par is between 5.0 and 5.5
    ("2026-10-27", "<= 3.5", "2026-12-01", 88.0, 90), ("2026-10-27", "5", "2026-12-01", 99.0, 500), ("2026-10-27", "5.5", "2026-12-01", 100.5, 400),
    ("2026-10-27", "5", "2027-01-01", 95.0, 3), ("2026-10-27", "5.5", "2027-01-01", 96.0, 2),     # a month with few trades: not used
    # 10-28: par is beyond 5.5, in the "> 5.5" bucket: the line through 5 and 5.5 is carried on to 100
    ("2026-10-28", "5", "2026-12-01", 98.0, 500), ("2026-10-28", "5.5", "2026-12-01", 99.5, 400), ("2026-10-28", "> 5.5", "2026-12-01", 101.0, 90),
    # 10-29: par is beyond 5.5, but the bucket above is under 100 too, so there is no knowing
    ("2026-10-29", "5", "2026-12-01", 97.0, 500), ("2026-10-29", "5.5", "2026-12-01", 98.5, 400), ("2026-10-29", "> 5.5", "2026-12-01", 99.4, 90),
    # 10-30: par is a long way beyond the last coupon: more than half a point
    ("2026-10-30", "5", "2026-12-01", 90.0, 500), ("2026-10-30", "5.5", "2026-12-01", 91.0, 400), ("2026-10-30", "> 5.5", "2026-12-01", 101.0, 90),
]


class FinancialDataTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.database = os.path.join(self.folder, "financial_data.db")
        self.env[lisp_core.Symbol("db")] = lisp_core.LispString(self.database)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(self.folder, "credentials.json"))
        self.run_lisp('(load "financial_data.lsp")')
        self.run_lisp(SOURCES)

    def make_tba_prices(self, agency="UMBS", product="SINGLE FAMILY 30Y", rows=TBA_ROWS):
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE tba_prices (date TEXT, product TEXT, agency TEXT, settlement TEXT, settlement_month TEXT, coupon TEXT, "
                           "coupon_rate REAL, weighted_average_price REAL, trades REAL)")
        for date, coupon, month, price, trades in rows:
            rate = float(coupon.strip("<=> "))
            connection.execute("INSERT INTO tba_prices VALUES (?, ?, ?, '', ?, ?, ?, ?, ?)", (date, product, agency, month, coupon, rate, price, trades))
        connection.commit()
        connection.close()

    def stored(self, sql):
        connection = sqlite3.connect(self.database)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()

    def update(self, options=""):
        return self.run_lisp("(financial-data-update creds db %s)" % options)

    def calls(self):
        return self.run_lisp("source-calls")


class TestTimeSeries(FinancialDataTestCase):

    def setUp(self):
        super().setUp()
        self.make_tba_prices(rows=[])           # finra-tba-update, which makes the table, is a stand-in here

    def test_each_source_makes_rows_for_each_term_and_day_in_percent(self):
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        treasury = dict(((d, t), v) for d, t, v in self.stored("SELECT date, term, value FROM time_series WHERE instrument = 'treasury-par'"))
        self.assertAlmostEqual(treasury[("2026-10-27", "10Y")], 5.12)             # the Treasury's 0.0512, as a percent
        self.assertAlmostEqual(treasury[("2026-10-28", "1.5M")], 4.13)
        self.assertNotIn(("2026-10-27", "1.5M"), treasury)                       # no value that day: no row
        self.assertEqual(sorted({t for _, t in treasury}), sorted(["1M", "1.5M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]))
        self.assertEqual(self.stored("SELECT date, term, value FROM time_series WHERE instrument = 'freddie-mac-mortgage-rate' ORDER BY date, term"),
                         [("2026-10-22", "15Y", 6.4), ("2026-10-22", "30Y", 7.1), ("2026-10-29", "30Y", 7.24)])
        self.assertEqual(self.stored("SELECT value FROM time_series WHERE instrument = 'sofr' AND term = 'ON' ORDER BY date"), [(3.95,), (3.94,)])
        self.assertEqual(self.stored("SELECT term, value FROM time_series WHERE instrument = 'sofr-average' AND date = '2026-10-27' ORDER BY term"),
                         [("180D", 3.93), ("30D", 3.89), ("90D", 3.91)])
        self.assertEqual(self.stored("SELECT term, value FROM time_series WHERE instrument = 'sofr-index' AND date = '2026-10-27'"), [("", 1.2645)])

    def test_the_summary_has_a_row_for_each_instrument_and_term(self):
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        self.assertShows('(vector-ref (table-column (financial-data-summary db) "instrument") 0)', '"freddie-mac-mortgage-rate"')
        self.assertEqual(self.run_lisp('(table-row-count (financial-data-summary db))'), 20)

    def test_a_first_run_asks_for_ten_years_and_a_later_one_from_two_weeks_before_the_last_day(self):
        self.update(':end-date "2026-10-30"')
        self.assertShows('(map car source-calls)', '("treasury" "fred" "nyfed")')
        self.assertEqual(self.run_lisp('(substring (cadr (car source-calls)) 0 4)'), str(datetime.date.today().year - 10))
        self.run_lisp("(set! source-calls '())")
        self.update(':end-date "2026-10-30"')
        self.assertShows('source-calls', '(("treasury" "2026-10-14" "2026-10-30") ("fred" "2026-10-15" "2026-10-30") ("nyfed" "2026-10-14" "2026-10-30"))')

    def test_running_again_replaces_the_days_it_asks_for_and_leaves_the_others(self):
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        connection = sqlite3.connect(self.database)
        connection.execute("INSERT INTO time_series VALUES ('2026-09-01', 'sofr', 'ON', 3.0)")
        connection.commit()
        connection.close()
        self.run_lisp('''(define (nyfed-rates names &key start-date end-date cache-hours)
                           (make-table "date" (vector (date 2026 10 28) (date 2026 10 29)) "SOFR" #(3.50 3.60) "SOFR-30" #(3.9 3.9)
                                       "SOFR-90" #(3.9 3.9) "SOFR-180" #(3.9 3.9) "SOFR-INDEX" #(1.3 1.3)))''')
        self.update(':end-date "2026-10-30"')
        self.assertEqual(self.stored("SELECT date, value FROM time_series WHERE instrument = 'sofr' ORDER BY date"),
                         [("2026-09-01", 3.0), ("2026-10-28", 3.5), ("2026-10-29", 3.6)])
        # the 1st of September is before the two weeks, and is left; the 27th is in them, and is replaced by what the source gives, which is not it

    def test_the_key_is_date_instrument_and_term(self):
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        self.assertEqual(self.stored("SELECT COUNT(*) FROM time_series"), [(len(self.stored("SELECT DISTINCT date, instrument, term FROM time_series")),)])


class TestReadingSeries(FinancialDataTestCase):

    def setUp(self):
        super().setUp()
        self.make_tba_prices(rows=[])
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')

    def test_a_series_is_a_table_of_date_and_value(self):
        self.assertShows('(with-sqlite (conn db) (time-series conn "treasury-par" "10Y"))',
                         '(("date" . #(2026-10-27 2026-10-28)) ("value" . #(5.12 5.13)))')
        self.assertShows('(with-sqlite (conn db) (table-column (time-series conn "sofr-index") "value"))', "#(1.2645 1.2646)")

    def test_several_series_side_by_side_with_nan_where_a_day_has_none(self):
        self.assertShows('''(with-sqlite (conn db)
                              (time-series-table conn '(("treasury-par" "10Y") ("freddie-mac-mortgage-rate" "30Y") ("nothing" "here"))))''',
                         '(("date" . #(2026-10-22 2026-10-27 2026-10-28 2026-10-29)) '
                         '("treasury-par 10Y" . #(nan 5.12 5.13 nan)) ("freddie-mac-mortgage-rate 30Y" . #(7.1 nan nan 7.24)) ("nothing here" . #(nan nan nan nan)))')


class TestCurrentCoupon(FinancialDataTestCase):

    def coupons(self):
        return self.stored("SELECT date, instrument, term, value FROM time_series WHERE instrument LIKE 'current-coupon-%' ORDER BY date")

    def test_par_between_two_coupons_is_found_by_the_line_between_them(self):
        self.make_tba_prices()
        self.update(':start-date "2026-10-01" :end-date "2026-10-31"')
        day = self.coupons()[0]
        self.assertEqual(day[:3], ("2026-10-27", "current-coupon-UMBS", "30Y"))
        self.assertAlmostEqual(day[3], 5.0 + (100 - 99.0) / (100.5 - 99.0) * 0.5)        # 5.333; the month with 5 trades is not the one used

    def test_par_just_beyond_the_last_coupon_is_found_by_carrying_the_line_on(self):
        self.make_tba_prices()
        self.update(':start-date "2026-10-01" :end-date "2026-10-31"')
        day = [c for c in self.coupons() if c[0] == "2026-10-28"][0]
        self.assertAlmostEqual(day[3], 5.5 + (100 - 99.5) / (99.5 - 98.0) * 0.5)         # 5.667

    def test_there_is_none_when_the_bucket_beyond_is_under_par_or_par_is_far_out(self):
        self.make_tba_prices()
        self.update(':start-date "2026-10-01" :end-date "2026-10-31"')
        self.assertEqual([c[0] for c in self.coupons()], ["2026-10-27", "2026-10-28"])    # not the 29th, and not the 30th

    def test_the_series_is_for_each_agency_and_term(self):
        self.make_tba_prices(agency="FNMA/UMBS", product="SINGLE FAMILY 15Y")
        self.update(':start-date "2026-10-01" :end-date "2026-10-31"')
        self.assertEqual(self.coupons()[0][1:3], ("current-coupon-FNMA-UMBS", "15Y"))

    def test_a_price_of_exactly_par_is_that_coupon(self):
        self.make_tba_prices(rows=[("2026-10-27", "5", "2026-12-01", 99.0, 5), ("2026-10-27", "5.5", "2026-12-01", 100.0, 5)])
        self.update(':start-date "2026-10-01" :end-date "2026-10-31"')
        self.assertAlmostEqual(self.coupons()[0][3], 5.5)
