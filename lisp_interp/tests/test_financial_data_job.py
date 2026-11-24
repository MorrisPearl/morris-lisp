"""The job that keeps the database of market history up to date: financial-data-behind (which sources are behind the last day they could have),
financial-data-update-if-behind (update only then, and only once a day), and examples/update_financial_data.lsp, the script the Mac runs. The update
itself is replaced by a Lisp stand-in, so nothing here touches the network."""

import datetime
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_calendar

# A stand-in for financial-data-update: it counts its calls, and either writes the rows in update-rows (a list of (date instrument)) or fails.
STAND_IN = """
(define update-calls 0)
(define update-rows '())
(define update-fails #f)
(define (financial-data-update creds db &key (start-date '()) (end-date '()))
  (set! update-calls (+ update-calls 1))
  (if update-fails (error "no network"))
  (with-sqlite (conn db)
    (for-each (lambda (row)
                (if (string=? (cadr row) "tba")
                    (sqlite-execute conn "INSERT INTO tba_prices VALUES (?)" (list (car row)))
                    (sqlite-execute conn "INSERT INTO time_series VALUES (?, ?, '', 1.0)" (list (car row) (cadr row)))))
              update-rows))
  '())
"""


def make_database(path, tba_day=None, treasury_day=None, sofr_day=None, mortgage_day=None):
    """A database with one row for each source, on the day given (a source with no day has no rows)."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE tba_prices (date TEXT)")
    connection.execute("CREATE TABLE time_series (date TEXT, instrument TEXT, term TEXT, value REAL)")
    if tba_day:
        connection.execute("INSERT INTO tba_prices VALUES (?)", (tba_day,))
    for instrument, day in (("treasury-par", treasury_day), ("sofr", sofr_day), ("freddie-mac-mortgage-rate", mortgage_day)):
        if day:
            connection.execute("INSERT INTO time_series VALUES (?, ?, '', 1.0)", (day, instrument))
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

    def behind(self, day):
        """The names of the sources that are behind on day (YYYY-MM-DD)."""
        return self.show('(map car (financial-data-behind db (string->date "%s")))' % day)

    def runs(self):
        connection = sqlite3.connect(self.database)
        try:
            return connection.execute("SELECT day, behind, result FROM update_runs ORDER BY rowid").fetchall()
        finally:
            connection.close()


class TestWhatIsBehind(FinancialDataJobTestCase):

    def test_an_empty_database_is_behind_in_everything(self):
        make_database(self.database)
        self.assertEqual(self.show('(financial-data-behind db (date 2026 11 24))'),
                         '(("TBA prices (FINRA)" () 2026-11-23) ("Treasury par yields" () 2026-11-23) ("SOFR (New York Fed)" () 2026-11-23) '
                         '("Freddie Mac mortgage rates" () 2026-11-17))')

    def test_a_database_with_no_tables_yet_is_behind_in_everything(self):
        self.assertEqual(self.show('(length (financial-data-behind db (date 2026 11 24)))'), "4")

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
        self.assertEqual(self.show('(financial-data-behind db (date 2026 11 24))'), '(("SOFR (New York Fed)" 2026-11-20 2026-11-23))')

    def test_the_weekly_mortgage_rate_may_be_a_week_old(self):
        make_database(self.database, "2026-12-02", "2026-12-02", "2026-12-02", "2026-11-25")   # Freddie Mac came out a day early, for Thanksgiving
        self.assertEqual(self.behind("2026-12-02"), "()")
        self.assertEqual(self.behind("2026-12-03"), '("Freddie Mac mortgage rates")')

    def test_a_day_later_than_due_is_fine(self):
        make_database(self.database, "2026-11-24", "2026-11-24", "2026-11-24", "2026-11-24")
        self.assertEqual(self.behind("2026-11-24"), "()")


class TestUpdatingOnlyWhenBehind(FinancialDataJobTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp(STAND_IN)
        self.run_lisp("(define (today) (date 2026 11 24))")        # the library asks (today) for the day

    def run_job(self, options=""):
        return self.show("(financial-data-update-if-behind creds db %s)" % options)

    def calls(self):
        return self.show("update-calls")

    def test_up_to_date_does_nothing(self):
        make_database(self.database, "2026-11-23", "2026-11-23", "2026-11-23", "2026-11-19")
        self.assertEqual(self.run_job(), "up-to-date")
        self.assertEqual(self.calls(), "0")
        self.assertIn("The financial data is up to date.", self.printed())

    def test_behind_updates_and_notes_the_run(self):
        make_database(self.database, "2026-11-20", "2026-11-20", "2026-11-20", "2026-11-19")
        self.run_lisp("""(set! update-rows '(("2026-11-23" "tba") ("2026-11-23" "treasury-par") ("2026-11-23" "sofr")))""")
        self.assertEqual(self.run_job(), "updated")
        self.assertEqual(self.calls(), "1")
        self.assertEqual(self.runs(), [("2026-11-24", "TBA prices (FINRA), Treasury par yields, SOFR (New York Fed)", "done")])
        self.assertIn("TBA prices (FINRA): last day 2026-11-20, could have 2026-11-23", self.printed())
        self.assertNotIn("Still behind", self.printed())
        self.assertEqual(self.run_job(), "up-to-date")                     # and the next time, it is up to date
        self.assertEqual(self.calls(), "1")

    def test_still_behind_after_an_update_is_not_tried_again_that_day(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")   # FINRA has not published (say)
        self.assertEqual(self.run_job(), "updated")
        self.assertIn("Still behind", self.printed())
        self.assertEqual(self.run_job(), "already-updated-today")
        self.assertEqual(self.calls(), "1")
        self.run_lisp("(define (today) (date 2026 11 25))")                 # but the next day it is
        self.assertEqual(self.run_job(), "updated")
        self.assertEqual(self.calls(), "2")

    def test_force_updates_again_the_same_day(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_job()
        self.assertEqual(self.run_job(":force #t"), "updated")
        self.assertEqual(self.calls(), "2")

    def test_a_failed_update_is_tried_again_and_noted(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_lisp("(set! update-fails #t)")
        self.assertEqual(self.run_job(":tries 3 :wait-seconds 0"), "failed")
        self.assertEqual(self.calls(), "3")
        self.assertEqual(self.runs(), [("2026-11-24", "TBA prices (FINRA)", "failed: no network")])
        self.assertIn("The update failed: no network", self.printed())

    def test_a_failed_update_does_not_stop_the_next_try_that_day(self):
        make_database(self.database, "2026-11-20", "2026-11-23", "2026-11-23", "2026-11-19")
        self.run_lisp("(set! update-fails #t)")
        self.run_job()
        self.run_lisp("(set! update-fails #f)")
        self.assertEqual(self.run_job(), "updated")
        self.assertEqual([run[2] for run in self.runs()], ["failed: no network", "done"])


class TestTheScript(unittest.TestCase):
    """examples/update_financial_data.lsp, run as the Mac runs it: a new interpreter, today's date."""

    def test_an_up_to_date_database_is_left_alone_quickly(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        database = os.path.join(folder, "financial_data.db")
        due = lisp_calendar.trading_days_after(datetime.date.today(), -1).isoformat()
        make_database(database, due, due, due, datetime.date.today().isoformat())
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
