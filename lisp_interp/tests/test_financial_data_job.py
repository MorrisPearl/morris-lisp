"""The job that keeps the database of market history up to date: financial-data-behind (which sources are behind the last day they could have: the
market data and the stocks' weekly and monthly prices), financial-data-update-if-behind (run only the updates that are behind, and each only once a day),
and examples/update_financial_data.lsp, the script the Mac runs. The updates themselves are replaced by Lisp stand-ins, so nothing here touches the
network."""

import datetime
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_calendar

# Stand-ins for the updates: each counts its calls, and either fails or writes what it is told to. The market update writes the rows in market-rows
# (a list of (date instrument)); the stock update notes, for every stock, that it was asked for the period in weekly-period or monthly-period.
STAND_IN = """
(define market-calls 0)
(define stock-calls '())
(define market-rows '())
(define weekly-period '())
(define monthly-period '())
(define market-fails #f)
(define stocks-fail #f)
(define (financial-data-update creds db &key (start-date '()) (end-date '()))
  (set! market-calls (+ market-calls 1))
  (if market-fails (error "no network"))
  (with-sqlite (conn db)
    (for-each (lambda (row)
                (if (string=? (cadr row) "tba")
                    (sqlite-execute conn "INSERT INTO tba_prices VALUES (?)" (list (car row)))
                    (sqlite-execute conn "INSERT INTO time_series VALUES (?, ?, '', 1.0)" (list (car row) (cadr row)))))
              market-rows))
  '())
(define (stock-prices-update creds db &key (frequency "weekly") (years '()) (end-date '()))
  (set! stock-calls (append stock-calls (list frequency)))
  (if stocks-fail (error "schwab-login: the sign-in has run out"))
  (let ((period (if (equal? frequency "weekly") weekly-period monthly-period)))
    (if (not (null? period))
        (with-sqlite (conn db)
          (sqlite-execute conn (string-append "UPDATE " frequency "_prices_asked SET last_period = ?") (list period)))))
  '())
"""


ALWAYS_CURRENT = "2099-01-05"     # a period far in the future, for the tests that are about other sources than the stock prices


def make_database(path, tba_day=None, treasury_day=None, sofr_day=None, mortgage_day=None, weekly_period=ALWAYS_CURRENT,
                  monthly_period=ALWAYS_CURRENT, stocks=("AAA", "BBB", "CCC.TO")):
    """A database with one row for each market source, on the day given (a source with no day has no rows), and the stocks, each asked for through
    the weekly and monthly periods given (with no period, not asked for at all). The Canadian stock (.TO) is never asked for."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE tba_prices (date TEXT)")
    connection.execute("CREATE TABLE time_series (date TEXT, instrument TEXT, term TEXT, value REAL)")
    if tba_day:
        connection.execute("INSERT INTO tba_prices VALUES (?)", (tba_day,))
    for instrument, day in (("treasury-par", treasury_day), ("sofr", sofr_day), ("freddie-mac-mortgage-rate", mortgage_day)):
        if day:
            connection.execute("INSERT INTO time_series VALUES (?, ?, '', 1.0)", (day, instrument))
    connection.execute("CREATE TABLE ticker_industry (ticker TEXT, industry TEXT)")
    for ticker in stocks:
        connection.execute("INSERT INTO ticker_industry VALUES (?, 'Things')", (ticker,))
    for frequency, period in (("weekly", weekly_period), ("monthly", monthly_period)):
        connection.execute("CREATE TABLE %s_prices_asked (ticker TEXT PRIMARY KEY, last_period TEXT, periods INTEGER, note TEXT)" % frequency)
        if period:
            for ticker in stocks:
                if not ticker.endswith(".TO"):
                    connection.execute("INSERT INTO %s_prices_asked VALUES (?, ?, 10, '')" % frequency, (ticker, period))
    connection.commit()
    connection.close()


class FinancialDataJobTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.database = os.path.join(self.folder, "financial_data.db")
        self.env[lisp_core.Symbol("db")] = lisp_core.LispString(self.database)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(self.folder, "credentials.json"))
        self.run_lisp('(load "financial_data.lsp")')
        self.run_lisp('(load "industry_returns.lsp")')     # (now, so that the stand-ins below are not replaced when it would be loaded)

    def behind(self, day):
        """The names of the sources that are behind on day (YYYY-MM-DD)."""
        return self.show('(map car (financial-data-behind db (string->date "%s")))' % day)

    def runs(self):
        connection = sqlite3.connect(self.database)
        try:
            return connection.execute("SELECT day, update_name, behind, result FROM update_runs ORDER BY rowid").fetchall()
        finally:
            connection.close()


class TestWhatIsBehind(FinancialDataJobTestCase):

    def test_an_empty_database_is_behind_in_everything(self):
        make_database(self.database, weekly_period=None, monthly_period=None)
        self.assertEqual(self.show('(financial-data-behind db (date 2026 11 24))'),
                         '(("TBA prices (FINRA)" () 2026-11-23 market) ("Treasury par yields" () 2026-11-23 market) '
                         '("SOFR (New York Fed)" () 2026-11-23 market) ("Freddie Mac mortgage rates" () 2026-11-17 market) '
                         '("Stock prices, weekly (Schwab)" () 2026-11-16 weekly-stock-prices) '
                         '("Stock prices, monthly (Schwab)" () 2026-10-01 monthly-stock-prices))')

    def test_a_database_with_no_tables_yet_is_behind_in_everything(self):
        self.assertEqual(self.show('(length (financial-data-behind db (date 2026 11 24)))'), "6")

    def test_up_to_date_when_each_daily_source_has_the_trading_day_before_today(self):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-23", "2026-11-19")
        self.assertEqual(self.behind("2026-11-24"), "()")

    def test_today_itself_is_not_needed(self):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-23", "2026-11-19")
        self.assertEqual(self.behind("2026-11-24"), "()")
        self.assertEqual(self.behind("2026-11-25"), '("TBA prices (FINRA)" "Treasury par yields" "SOFR (New York Fed)")')

    def test_on_monday_friday_is_enough(self):
        make_database(self.database, "2026-11-20", "2026-11-20", "2026-11-20", "2026-11-19")
        self.assertEqual(self.behind("2026-11-23"), "()")
        self.assertEqual(self.behind("2026-11-24"), '("TBA prices (FINRA)" "Treasury par yields" "SOFR (New York Fed)")')

    def test_a_market_holiday_is_skipped(self):
        # Thanksgiving, Thursday 2026-11-26: on the Friday after it, Wednesday is the last day there could be
        make_database(self.database, "2026-11-25", "2026-11-25", "2026-11-25", "2026-11-25")
        self.assertEqual(self.behind("2026-11-27"), "()")

    def test_one_source_behind_is_named_alone(self):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-20", "2026-11-19")
        self.assertEqual(self.show('(financial-data-behind db (date 2026 11 24))'), '(("SOFR (New York Fed)" 2026-11-20 2026-11-23 market))')

    def test_the_weekly_mortgage_rate_may_be_a_week_old(self):
        make_database(self.database, "2026-12-02", "2026-12-02", "2026-12-02", "2026-11-25")   # Freddie Mac came out a day early, for Thanksgiving
        self.assertEqual(self.behind("2026-12-02"), "()")
        self.assertEqual(self.behind("2026-12-03"), '("Freddie Mac mortgage rates")')

    def test_a_day_later_than_due_is_fine(self):
        make_database(self.database, "2026-11-24", "2026-11-24", "2026-11-24", "2026-11-24")
        self.assertEqual(self.behind("2026-11-24"), "()")


class TestWhetherTheStockPricesAreBehind(FinancialDataJobTestCase):
    """A week is named by its Monday and a month by its first day; the last whole one before today's is the one there could be."""

    def market_current(self, **periods):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-23", "2026-11-19", **periods)

    def test_up_to_date_with_last_week_and_last_month(self):
        self.market_current(weekly_period="2026-11-16", monthly_period="2026-10-01")
        self.assertEqual(self.behind("2026-11-24"), "()")

    def test_a_new_week_needs_the_week_just_ended(self):
        self.market_current(weekly_period="2026-11-09", monthly_period="2026-10-01")
        self.assertEqual(self.show('(financial-data-behind db (date 2026 11 24))'),
                         '(("Stock prices, weekly (Schwab)" 2026-11-09 2026-11-16 weekly-stock-prices))')

    def test_sunday_still_belongs_to_the_week_before(self):
        make_database(self.database, "2026-11-20", "2026-11-20", "2026-11-20", "2026-11-19", weekly_period="2026-11-09", monthly_period="2026-10-01")
        self.assertEqual(self.behind("2026-11-22"), "()")          # the week of 11-16 is not over until Sunday is
        self.assertEqual(self.behind("2026-11-23"), '("Stock prices, weekly (Schwab)")')

    def test_a_new_month_needs_the_month_just_ended(self):
        make_database(self.database, "2026-11-30", "2026-11-30", "2026-11-30", "2026-11-26", weekly_period="2026-11-23", monthly_period="2026-10-01")
        self.assertEqual(self.behind("2026-12-01"), '("Stock prices, monthly (Schwab)")')

    def test_a_run_that_stopped_part_way_is_behind(self):
        self.market_current(weekly_period="2026-11-16", monthly_period="2026-10-01")
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE weekly_prices_asked SET last_period = '2026-11-09' WHERE ticker = 'BBB'")
        connection.commit()
        connection.close()
        self.assertEqual(self.show('(map cadr (financial-data-behind db (date 2026 11 24)))'), "(2026-11-09)")

    def test_a_stock_never_asked_for_is_behind(self):
        self.market_current(weekly_period="2026-11-16", monthly_period="2026-10-01")
        connection = sqlite3.connect(self.database)
        connection.execute("INSERT INTO ticker_industry VALUES ('DDD', 'Things')")
        connection.commit()
        connection.close()
        self.assertEqual(self.show('(financial-data-behind db (date 2026 11 24))'),
                         '(("Stock prices, weekly (Schwab)" () 2026-11-16 weekly-stock-prices) '
                         '("Stock prices, monthly (Schwab)" () 2026-10-01 monthly-stock-prices))')

    def test_canadian_stocks_are_not_waited_for(self):
        self.market_current(weekly_period="2026-11-16", monthly_period="2026-10-01", stocks=("AAA", "CCC.TO", "DDD.TO"))
        self.assertEqual(self.behind("2026-11-24"), "()")


class TestUpdatingOnlyWhenBehind(FinancialDataJobTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp(STAND_IN)
        self.run_lisp("(define (today) (date 2026 11 24))")        # the library asks (today) for the day

    def run_job(self, options=""):
        return self.show("(financial-data-update-if-behind creds db %s)" % options)

    def market_calls(self):
        return self.show("market-calls")

    def stock_calls(self):
        return self.show("stock-calls")

    def market_behind(self, **periods):
        """The TBA prices, Treasury yields and SOFR are a day behind on 2026-11-24, and the stock prices are as given (up to date unless they say)."""
        make_database(self.database, "2026-11-20", "2026-11-20", "2026-11-20", "2026-11-19", **periods)

    def test_up_to_date_does_nothing(self):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-23", "2026-11-19", weekly_period="2026-11-16", monthly_period="2026-10-01")
        self.assertEqual(self.run_job(), "up-to-date")
        self.assertEqual(self.market_calls(), "0")
        self.assertEqual(self.stock_calls(), "()")
        self.assertIn("The financial data is up to date.", self.printed())

    def test_behind_updates_and_notes_the_run(self):
        self.market_behind()
        self.run_lisp("""(set! market-rows '(("2026-11-23" "tba") ("2026-11-23" "treasury-par") ("2026-11-23" "sofr")))""")
        self.assertEqual(self.run_job(), "((market updated))")
        self.assertEqual(self.market_calls(), "1")
        self.assertEqual(self.stock_calls(), "()")                              # the stock prices were not behind
        self.assertEqual(self.runs(), [("2026-11-24", "market", "TBA prices (FINRA), Treasury par yields, SOFR (New York Fed)", "done")])
        self.assertIn("TBA prices (FINRA): last day 2026-11-20, could have 2026-11-23", self.printed())
        self.assertNotIn("Still behind", self.printed())
        self.assertEqual(self.run_job(), "up-to-date")                         # and the next time, it is up to date
        self.assertEqual(self.market_calls(), "1")

    def test_only_the_stock_prices_that_are_behind_are_updated(self):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-23", "2026-11-19", weekly_period="2026-11-09", monthly_period="2026-10-01")
        self.run_lisp('(set! weekly-period "2026-11-16")')
        self.assertEqual(self.run_job(), "((weekly-stock-prices updated))")
        self.assertEqual(self.stock_calls(), '("weekly")')
        self.assertEqual(self.market_calls(), "0")
        self.assertEqual(self.run_job(), "up-to-date")

    def test_everything_behind_runs_each_update_in_turn(self):
        self.market_behind(weekly_period="2026-11-09", monthly_period="2026-09-01")
        self.assertEqual(self.run_job(), "((market updated) (weekly-stock-prices updated) (monthly-stock-prices updated))")
        self.assertEqual(self.stock_calls(), '("weekly" "monthly")')
        self.assertEqual([run[1] for run in self.runs()], ["market", "weekly-stock-prices", "monthly-stock-prices"])

    def test_a_failed_stock_update_does_not_stop_the_market_update(self):
        self.market_behind(weekly_period="2026-11-09")
        self.run_lisp("(set! stocks-fail #t)")
        self.assertEqual(self.run_job(), "((market updated) (weekly-stock-prices failed))")
        self.assertEqual(self.runs()[1], ("2026-11-24", "weekly-stock-prices", "Stock prices, weekly (Schwab)",
                                          "failed: schwab-login: the sign-in has run out"))
        self.assertIn("Still behind", self.printed())

    def test_still_behind_after_an_update_is_not_tried_again_that_day(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")   # FINRA has not published (say)
        self.assertEqual(self.run_job(), "((market updated))")
        self.assertIn("Still behind", self.printed())
        self.assertEqual(self.run_job(), "((market already-updated-today))")
        self.assertEqual(self.market_calls(), "1")
        self.run_lisp("(define (today) (date 2026 11 25))")                 # but the next day it is
        self.assertEqual(self.run_job(), "((market updated))")
        self.assertEqual(self.market_calls(), "2")

    def test_one_update_done_today_does_not_hold_back_another(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_job()                                                       # the market data: done, but FINRA is still behind
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE weekly_prices_asked SET last_period = '2026-11-09'")   # (a new week's prices are wanted, say)
        connection.commit()
        connection.close()
        self.run_lisp('(set! weekly-period "2026-11-16")')
        self.assertEqual(self.run_job(), "((market already-updated-today) (weekly-stock-prices updated))")

    def test_force_updates_again_the_same_day(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_job()
        self.assertEqual(self.run_job(":force #t"), "((market updated))")
        self.assertEqual(self.market_calls(), "2")

    def test_a_failed_update_is_tried_again_and_noted(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_lisp("(set! market-fails #t)")
        self.assertEqual(self.run_job(":tries 3 :wait-seconds 0"), "((market failed))")
        self.assertEqual(self.market_calls(), "3")
        self.assertEqual(self.runs(), [("2026-11-24", "market", "TBA prices (FINRA)", "failed: no network")])
        self.assertIn("The update failed: no network", self.printed())

    def test_a_failed_update_does_not_stop_the_next_try_that_day(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_lisp("(set! market-fails #t)")
        self.run_job()
        self.run_lisp("(set! market-fails #f)")
        self.assertEqual(self.run_job(), "((market updated))")
        self.assertEqual([run[3] for run in self.runs()], ["failed: no network", "done"])


class TestTheScript(unittest.TestCase):
    """examples/update_financial_data.lsp, run as the Mac runs it: a new interpreter, today's date."""

    def test_an_up_to_date_database_is_left_alone_quickly(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        database = os.path.join(folder, "financial_data.db")
        due = lisp_calendar.trading_days_after(datetime.date.today(), -1).isoformat()
        today = datetime.date.today()
        this_week = today - datetime.timedelta(days=today.weekday())
        last_week = (this_week - datetime.timedelta(days=7)).isoformat()
        last_month = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1).isoformat()
        make_database(database, due, due, due, today.isoformat(), weekly_period=last_week, monthly_period=last_month)
        init_file = os.path.join(folder, "init.lsp")
        with open(init_file, "w") as f:
            f.write('(define creds "%s")\n' % os.path.join(folder, "credentials.json"))
        started = time.time()
        result = subprocess.run([sys.executable, INTERPRETER, os.path.join(EXAMPLES, "update_financial_data.lsp"), database],
                                capture_output=True, text=True, timeout=120, env=dict(os.environ, LISP_INIT_FILE=init_file))
        seconds = time.time() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The financial data is up to date.", result.stdout)
        self.assertLess(seconds, 10)            # about a second and a half on a Mac; the limit is loose for a busy machine
        connection = sqlite3.connect(database)
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        connection.close()
        self.assertNotIn("update_runs", tables)  # nothing was written


if __name__ == "__main__":
    unittest.main()
