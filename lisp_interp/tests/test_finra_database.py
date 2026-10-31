"""lib/finra_database.lsp: the SQLite database of FINRA's TBA prices, and finra-tba-update, which brings it up to date.
FINRA's API is played by a fake, as in TestFinra, that sends the records whose report date is in the range asked for."""

import datetime
import json
import os
import shutil
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class FinraDatabaseTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        import lisp_finra
        lisp_finra._tokens.clear()
        self.addCleanup(lisp_finra._tokens.clear)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.credentials = os.path.join(self.folder, "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"finra_client_id": "client-1", "finra_client_secret": "secret-123"}, f)
        self.database = os.path.join(self.folder, "tba.db")
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.env[lisp_core.Symbol("db")] = lisp_core.LispString(self.database)
        self.records = []           # what FINRA has
        self.asked = []             # the (start, end) of each request for prices
        patcher = mock.patch.object(lisp_http, "download", self.fake_download)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run_lisp('(load "finra_database.lsp")')

    def fake_download(self, url, cache_hours, headers, who, shown_url=None, body=None):
        if url == lisp_finra_token_url():
            return json.dumps({"access_token": "token", "expires_in": 43170}).encode()
        request = json.loads(body)
        dates = request["dateRangeFilters"][0]
        self.asked.append((dates["startDate"], dates["endDate"]))
        found = [r for r in self.records if dates["startDate"] <= r["reportDate"] <= dates["endDate"]]
        return json.dumps(found[request["offset"]:request["offset"] + request["limit"]]).encode()

    def add_day(self, date, price, trades=10, coupon="5.5", settlement="November Settlement", agency="UMBS"):
        """FINRA's records for one coupon on one day: a record for each statistic."""
        statistics = {"AVERAGE PRICE": price, "WEIGHTED AVG. PRICE": price + 0.1, "AVG. PRICE BOTTOM 5 TRADES": price - 1,
                      "2ND QUARTILE PRICE": price, "3RD QUARTILE PRICE": price + 0.2, "4TH QUARTILE PRICE": price + 0.4,
                      "AVG. PRICE TOP 5 TRADES": price + 1, "STANDARD DEVIATION": 0.3, "VOLUME OF TRADES (000'S)": trades * 1000.0,
                      "NUMBER OF TRADES": trades}
        for statistic, value in statistics.items():
            self.records.append({"reportDate": date, "pricingTableName": "AGENCY PASS-THRU (TBA, STIP, $ ROLLS) - SINGLE FAMILY 30Y",
                                 "agencyCode": agency, "settlementCode": settlement, "couponRateCode": coupon,
                                 "categoryCode": statistic, "valueAmount": str(value)})

    def update(self, options=""):
        return self.run_lisp("(finra-tba-update creds db %s)" % options)

    def column(self, sql, name):
        """The text of a column of the answer to a query of the database."""
        return '(with-sqlite (conn db) (table-column (sqlite-query conn "%s") "%s"))' % (sql, name)


def lisp_finra_token_url():
    import lisp_finra
    return lisp_finra.TOKEN_URL


class TestFinraDatabase(FinraDatabaseTestCase):

    def test_the_first_run_makes_the_database_with_a_row_for_each_coupon_and_day(self):
        self.add_day("2026-10-27", 100.0, coupon="5.5")
        self.add_day("2026-10-27", 98.0, coupon="<= 3.5")
        self.add_day("2026-10-28", 100.5, coupon="5.5")
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        self.assertShows('(table-column (finra-tba-summary db) "rows")', "#(3)")
        self.assertShows('(table-column (finra-tba-summary db) "last_day")', "#(2026-10-28)")
        self.assertShows('(table-column-names (finra-tba-summary db))', '("agency" "product" "rows" "first_day" "last_day")')
        self.assertShows(self.column("SELECT coupon_rate FROM tba_prices ORDER BY date, coupon_rate", "coupon_rate"), "#(3.5 5.5 5.5)")

    def test_the_statistics_are_named_for_what_they_are(self):
        self.add_day("2026-10-27", 100.0, trades=7)
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        names = '(with-sqlite (conn db) (table-column-names (sqlite-query conn "SELECT * FROM tba_prices")))'
        self.assertShows(names, '("date" "product" "agency" "settlement" "settlement_month" "coupon" "coupon_rate" "average_price" '
                                '"weighted_average_price" "bottom_5_average_price" "quartile_2_price" "quartile_3_price" '
                                '"quartile_4_price" "top_5_average_price" "standard_deviation" "volume_thousands" "trades")')
        self.assertShows('(with-sqlite (conn db) (map (lambda (c) (vector-ref (cdr c) 0)) (sqlite-query conn "SELECT average_price, '
                         'weighted_average_price, bottom_5_average_price, top_5_average_price, volume_thousands, trades FROM tba_prices")))',
                         "(100.0 100.1 99.0 101.0 7000.0 7.0)")

    def test_days_with_no_trades_are_not_kept(self):
        self.add_day("2026-10-27", 0.0, trades=0)
        self.add_day("2026-10-27", 100.0, trades=3, coupon="6")
        self.update(':start-date "2026-10-01" :end-date "2026-10-30"')
        self.assertShows(self.column("SELECT coupon FROM tba_prices", "coupon"), '#("6")')

    def test_the_settlement_month_is_the_next_one_on_or_after_the_report_date(self):
        self.add_day("2026-12-15", 100.0, settlement="December Settlement")
        self.add_day("2026-12-15", 100.0, settlement="January Settlement", coupon="6")
        self.update(':start-date "2026-12-01" :end-date "2026-12-31"')
        self.assertShows(self.column("SELECT settlement_month FROM tba_prices ORDER BY coupon", "settlement_month"), "#(2026-12-01 2027-01-01)")

    def test_a_settlement_that_is_not_a_month_is_an_error_and_nothing_is_written(self):
        self.add_day("2026-12-15", 100.0, settlement="Smarch Settlement")
        self.assertLispError('(finra-tba-update creds db :start-date "2026-12-01" :end-date "2026-12-31")', "doesn't begin with a month")
        self.assertShows("(table-row-count (finra-tba-summary db))", "0")

    def test_running_again_asks_only_from_a_week_before_the_last_day_and_changes_nothing_that_has_not_changed(self):
        self.add_day("2026-10-20", 99.0)
        self.add_day("2026-10-27", 100.0)
        self.update(':start-date "2026-10-01" :end-date "2026-10-28"')
        self.asked.clear()
        self.update(':end-date "2026-10-28"')
        self.assertEqual(self.asked, [("2026-10-20", "2026-10-28")])
        self.assertShows('(table-column (finra-tba-summary db) "rows")', "#(2)")

    def test_a_corrected_price_replaces_the_old_one_and_a_new_day_is_added(self):
        self.add_day("2026-10-27", 100.0)
        self.update(':start-date "2026-10-01" :end-date "2026-10-28"')
        self.records.clear()
        self.add_day("2026-10-27", 100.25)       # FINRA corrected it
        self.add_day("2026-10-29", 101.0)
        self.update(':end-date "2026-10-30"')
        self.assertShows(self.column("SELECT average_price FROM tba_prices ORDER BY date", "average_price"), "#(100.25 101.0)")

    def test_it_asks_a_month_at_a_time_and_skips_the_months_without_prices(self):
        self.add_day("2026-08-14", 100.0, settlement="September Settlement")
        self.add_day("2026-10-14", 100.0)
        self.update(':start-date "2026-08-10" :end-date "2026-10-20"')
        self.assertEqual(self.asked, [("2026-08-10", "2026-08-31"), ("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-20")])
        self.assertShows('(table-column (finra-tba-summary db) "rows")', "#(2)")

    def test_a_new_database_starts_ten_years_ago(self):
        self.update()
        today = datetime.date.today()
        self.assertEqual(self.asked[0][0][:8], "%d-%02d-" % (today.year - 10, today.month))
        self.assertEqual(self.asked[-1][1], today.isoformat())
        self.assertShows('(table-row-count (finra-tba-summary db))', "0")

    def test_other_errors_from_finra_are_not_hidden(self):
        with mock.patch.object(lisp_http, "download", side_effect=lisp_core.LispError("finra: it is down")):
            self.assertLispError('(finra-tba-update creds db :start-date "2026-10-01" :end-date "2026-10-30")', "it is down")

    def test_the_functions_are_there_when_the_autoloads_are_loaded(self):
        self.run_lisp('(load "autoloads.lsp")')
        self.add_day("2026-10-27", 100.0)
        self.assertShows('(table-row-count (finra-tba-update creds db :start-date "2026-10-01" :end-date "2026-10-30"))', "1")
