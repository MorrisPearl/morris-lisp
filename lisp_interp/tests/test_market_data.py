"""What the market says about a company, from outside its financial statements: its price and what analysts expect
(alpha-vantage-price, alpha-vantage-estimates), how much of it is sold short (finra-short-interest), and what its
insiders buy and sell (sec-insider-trades). Each source's answers are faked -- no network."""

import json
import os
import shutil
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, mock, and LispTestCase

import lisp_alpha_vantage
import lisp_finra
import lisp_sec_insiders


class MarketDataTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "credentials.json")
        with open(path, "w") as f:
            json.dump({"alpha_vantage_api_key": "KEY123", "sec_user_agent": "Test test@example.com"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(path)
        self.requests = []

    def answering(self, module, answer):
        """Fake the module's downloads: each request is recorded (url, body), and answered by answer(url, body)."""
        def download(url, cache_hours, headers, who, shown_url=None, body=None, check=None, wait=None):
            self.requests.append((url, body))
            data = answer(url, body)
            if check:
                check(data)
            return data
        patcher = mock.patch.object(module.lisp_http, "download", download)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestAlphaVantage(MarketDataTestCase):

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(lisp_alpha_vantage, "wait_a_moment", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_price_is_a_number(self):
        self.answering(lisp_alpha_vantage, lambda url, body: json.dumps(
            {"Global Quote": {"01. symbol": "ABC", "05. price": "123.4500"}}).encode())
        self.assertShows('(alpha-vantage-price creds "ABC")', "123.45")
        self.assertIn("function=GLOBAL_QUOTE", self.requests[0][0])

    def test_no_price_is_an_error_without_the_key(self):
        self.answering(lisp_alpha_vantage, lambda url, body: json.dumps({"Global Quote": {}}).encode())
        with self.assertRaises(lisp_core.LispError) as cm:
            self.run_lisp('(alpha-vantage-price creds "NOPE")')
        self.assertIn("Alpha Vantage says", str(cm.exception))
        self.assertNotIn("KEY123", str(cm.exception))

    def test_the_estimates_are_a_table_with_their_revisions(self):
        estimates = [
            {"date": "2027-09-30", "horizon": "fiscal year", "eps_estimate_average": "11.0",
             "eps_estimate_average_30_days_ago": "10.0", "eps_estimate_revision_up_trailing_30_days": "3",
             "eps_estimate_revision_down_trailing_30_days": None, "revenue_estimate_average": "500000000000"},
            {"date": "2026-12-31", "horizon": "fiscal quarter", "eps_estimate_average": "2.0",
             "eps_estimate_average_30_days_ago": "2.5", "revenue_estimate_average": "120000000000"},
        ]
        self.answering(lisp_alpha_vantage, lambda url, body: json.dumps({"symbol": "ABC", "estimates": estimates}).encode())
        self.run_lisp('(define e (alpha-vantage-estimates creds "ABC"))')
        self.assertShows('(table-column e "period-end")', "#(2026-12-31 2027-09-30)")         # (oldest first)
        self.assertShows('(table-column e "eps")', "#(2.0 11.0)")
        revisions = self.run_lisp('(table-column e "eps-revision-30-days")').items.tolist()
        self.assertAlmostEqual(revisions[0], 2.0 / 2.5 - 1)
        self.assertAlmostEqual(revisions[1], 11.0 / 10.0 - 1)
        self.assertShows('(table-column e "revenue")', "#(120000.0 500000.0)")               # (millions)
        self.assertIn("function=EARNINGS_ESTIMATES", self.requests[0][0])


class TestShortInterest(MarketDataTestCase):

    def test_a_row_for_each_date_oldest_first(self):
        records = [
            {"settlementDate": "2026-10-30", "currentShortPositionQuantity": 1200, "changePercent": 20.0,
             "averageDailyVolumeQuantity": 300, "daysToCoverQuantity": 4.0},
            {"settlementDate": "2026-10-15", "currentShortPositionQuantity": 1000, "changePercent": -5.0,
             "averageDailyVolumeQuantity": 250, "daysToCoverQuantity": 4.0},
        ]
        self.answering(lisp_finra, lambda url, body: json.dumps(records).encode())
        self.run_lisp('(define s (finra-short-interest "abc" :months 6))')
        self.assertShows('(table-column s "date")', "#(2026-10-15 2026-10-30)")
        self.assertShows('(table-column s "short-shares")', "#(1000.0 1200.0)")
        self.assertShows('(table-column s "change")', "#(-0.05 0.2)")
        self.assertShows('(table-column s "days-to-cover")', "#(4.0 4.0)")
        url, body = self.requests[0]
        request = json.loads(body)
        self.assertEqual(request["compareFilters"][0]["fieldValue"], "ABC")
        self.assertEqual(request["dateRangeFilters"][0]["fieldName"], "settlementDate")

    def test_none_is_an_error_that_says_so(self):
        self.answering(lisp_finra, lambda url, body: b"[]")
        self.assertLispError('(finra-short-interest "ZZZZ")', "FINRA has no short interest for ZZZZ")


FORM_4 = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer>
      <officerTitle>Chief  Financial Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>%s</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-02</value></transactionDate>
      <transactionCoding><transactionCode>%s</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>%s</value></transactionShares>
        <transactionPricePerShare><value>50.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>%s</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>9000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


class TestInsiderTrades(MarketDataTestCase):

    def setUp(self):
        super().setUp()
        submissions = {"filings": {"recent": {
            "form": ["4", "10-Q", "4"], "filingDate": ["2026-11-04", "2026-11-01", "2026-10-20"],
            "reportDate": ["", "", ""], "accessionNumber": ["0001-26-000002", "0001-26-000001", "0001-26-000000"],
            "primaryDocument": ["xslF345X06/form4.xml", "q3.htm", "xslF345X05/form4.xml"]}}}
        forms = {"000126000002": FORM_4 % ("false", "P", "1000", "A"), "000126000000": FORM_4 % ("true", "S", "400", "D")}
        self.fetched = []

        def download(url, credentials_path, cache_hours, who):
            self.fetched.append(url)
            return next(text for accession, text in forms.items() if accession in url).encode()
        for patcher in (mock.patch.object(lisp_sec_insiders, "company_cik", lambda creds, company, who: 1234),
                        mock.patch.object(lisp_sec_insiders, "sec_json", lambda url, creds, who: submissions),
                        mock.patch.object(lisp_sec_insiders, "sec_download", download)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_each_trade_with_its_sign_value_and_role(self):
        self.run_lisp('(define t (sec-insider-trades creds "ABC"))')
        self.assertShows('(table-column t "filing-date")', "#(2026-10-20 2026-11-04)")
        self.assertShows('(table-column t "code")', '#(S P)')
        self.assertShows('(table-column t "what")', '#(sold bought)')
        self.assertShows('(table-column t "shares")', "#(-400.0 1000.0)")          # (disposed of: below 0)
        self.assertShows('(table-column t "value")', "#(-20000.0 50000.0)")
        self.assertShows('(table-column t "planned")', "#(#t #f)")
        self.assertShows('(vector-ref (table-column t "role") 0)', 'Chief Financial Officer, director')
        self.assertTrue(all("/xslF345" not in url for url in self.fetched))      # (the XML, not the page made of it)

    def test_count_keeps_the_latest(self):
        self.run_lisp('(define t (sec-insider-trades creds "ABC" :count 1))')
        self.assertShows('(table-column t "code")', '#(P)')
        self.assertLispError('(sec-insider-trades creds "ABC" :count 0)', ":count is a whole number of Form 4s")
