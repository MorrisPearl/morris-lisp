"""The data sources, each against a stand-in for its web API (the tests never use the
network): SEC, FDIC, Census, BLS, BEA, Schwab, tastytrade, FRED, Alpha Vantage, and
downloads from any web API.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import urllib.error

import lisp_google
import lisp_rates
import lisp_schwab


class TestOptionChainTable(LispTestCase):
    """tastytrade-option-chain's rows become a table (no network needed to
    test that part), and examples/option_chain_example.lsp runs on one."""

    @staticmethod
    def rows():
        def row(symbol, kind, strike, expiration, days, price, iv, volume, oi):
            S = lisp_core.LispString
            bid, ask = round(price - 0.05, 2), round(price + 0.05, 2)
            return [S(symbol), S(kind), strike, S(expiration), days, None, S("SPY"), 655.0,
                    bid, ask, price, price, iv, None, None, volume, oi]
        return [
            row("SPY C660 OCT", "Call", 660.0, "2025-10-17", 19, 9.10, 0.18, 1200, 5000),
            row("SPY C660 NOV", "Call", 660.0, "2025-10-31", 33, 12.40, 0.19, 800, 2500),
            row("SPY C670 NOV", "Call", 670.0, "2025-10-31", 33, 7.25, 0.17, 400, 90),
            row("SPY C670 DEC", "Call", 670.0, "2025-11-21", 54, 10.05, None, 150, 300),
            row("SPY P650 NOV", "Put", 650.0, "2025-10-31", 33, 6.80, 0.23, 950, 4100),
            row("SPY P640 DEC", "Put", 640.0, "2025-11-21", 54, 0.95, 0.26, 70, 800),
            row("SPY P650 DEC", "Put", 650.0, "2025-11-21", 54, 9.30, 0.22, 300, None),
        ]

    def test_the_rows_become_a_table_with_named_columns(self):
        self.env[lisp_core.Symbol("chain")] = lisp_tastytrade.option_chain_table(self.rows())
        self.assertShows("(table-column-names chain)",
                         '("symbol" "type" "strike" "expiration-date" "days-to-expiration" "delivery-month" '
                         '"underlying" "underlying-price" "bid" "ask" "mid" "last-price" "implied-volatility" '
                         '"delta" "vega" "volume" "open-interest")')
        self.assertShows("(table-row-count chain)", "7")
        self.assertShows('(table-column chain "expiration-date")',
                         "#(2025-10-17 2025-10-31 2025-10-31 2025-11-21 2025-10-31 2025-11-21 2025-11-21)")
        self.assertShows('(vector-ref (table-column chain "implied-volatility") 3)', "nan")

    def test_an_empty_chain_is_a_table_with_no_rows(self):
        self.env[lisp_core.Symbol("chain")] = lisp_tastytrade.option_chain_table([])
        self.assertShows("(table-row-count chain)", "0")

    def test_the_option_chain_example_runs(self):
        chain = lisp_tastytrade.option_chain_table(self.rows())
        self.env[lisp_core.Symbol("tastytrade-option-chain")] = lambda *args: chain
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("no-credentials-needed.json")
        lisp_core.run_file(os.path.join(EXAMPLES, "option_chain_example.lsp"), self.env)
        out = self.printed()
        self.assertIn("SPY: 7 options", out)
        # part 2: the calls with 20-60 days and open interest of at least 100, cheapest per day first
        part2 = out.split("cheapest per day first:\n")[1].split("\n\n")[0]
        self.assertEqual([line.split("  ")[0] for line in part2.splitlines()[2:]],
                         ["SPY C670 DEC", "SPY C660 NOV"])
        # part 3: the puts over 20% volatility and $1
        self.assertIn("Puts with implied volatility over 20% and a price over $1: 2", out)
        self.assertIn("  SPY P650 NOV expires 2025-10-31: 6.75 bid, 6.85 ask, at 23.0% volatility", out)
        # part 4: by expiration
        self.assertIn("2025-10-31             3       19.7%          6,690", out)


class FakeTastytrade:
    """A stand-in for tastytrade's API, for testing lisp_tastytrade without
    the network: a session whose requests are answered from `answers`, a
    function (path, params) -> (HTTP status, JSON body). It keeps every
    request it's asked, as (path, params)."""

    class Response:
        def __init__(self, status, body):
            self.status_code = status
            self.body = body

        def json(self):
            if isinstance(self.body, str):
                raise ValueError("not JSON")
            return self.body

    def __init__(self, answers):
        self.answers = answers
        self.requests = []
        fake = self

        class Client:
            async def get(self, path, params=None):
                fake.requests.append((path, dict(params or {})))
                return FakeTastytrade.Response(*fake.answers(path, dict(params or {})))

        class Session:
            _client = Client()

            async def refresh(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def serialize(self):
                return "{}"
        self.session = Session()

    def __enter__(self):
        self.credentials = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.credentials.write('{"client_secret": "x", "refresh_token": "y"}')
        self.credentials.close()
        self.patch = mock.patch.object(lisp_tastytrade, "_tasty_session", lambda path: self.session)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        os.unlink(self.credentials.name)


class TestSecFinancials(LispTestCase):
    """lisp_sec, on a made-up company's facts -- no network. XYZ Corp's fiscal
    year is the calendar year. It reported revenue as Revenues for 2022 and
    as RevenueFromContractWithCustomerExcludingAssessedTax for 2023; restated
    2022's net income in its 2023 10-K; and gave its operating cash flow
    and capital spending, as most companies do, only for the year to date."""

    @staticmethod
    def fact(start, end, value, form, filed, fy, fp, accn):
        if value >= 1000:
            value = int(value)                  # the SEC gives whole dollars as integers
        f = {"end": end, "val": value, "form": form, "filed": filed, "fy": fy, "fp": fp, "accn": accn}
        if start:
            f["start"] = start
        return f

    def company_facts(self):
        F = self.fact
        k22 = ("10-K", "2023-02-15", 2022, "FY", "k22")
        k23 = ("10-K", "2024-02-15", 2023, "FY", "k23")
        q1, q2, q3 = (("10-Q", "2023-05-01", 2023, "Q1", "q1"), ("10-Q", "2023-08-01", 2023, "Q2", "q2"),
                      ("10-Q", "2023-11-01", 2023, "Q3", "q3"))
        usd = lambda *facts: {"label": "", "units": {"USD": list(facts)}}
        per_share = lambda *facts: {"label": "", "units": {"USD/shares": list(facts)}}
        return {"cik": 1234, "entityName": "XYZ Corp", "facts": {"us-gaap": {
            "Revenues": usd(F("2022-01-01", "2022-12-31", 100e6, *k22)),
            "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
                F("2023-01-01", "2023-03-31", 25e6, *q1), F("2023-04-01", "2023-06-30", 30e6, *q2),
                F("2023-07-01", "2023-09-30", 32e6, *q3), F("2023-01-01", "2023-09-30", 87e6, *q3),
                F("2023-01-01", "2023-12-31", 120e6, *k23)),
            "CostOfRevenue": usd(F("2023-01-01", "2023-12-31", 70e6, *k23)),
            "NetIncomeLoss": usd(F("2022-01-01", "2022-12-31", 10e6, *k22),
                                 F("2022-01-01", "2022-12-31", 11e6, *k23),        # restated
                                 F("2023-01-01", "2023-12-31", 15e6, *k23)),
            "EarningsPerShareDiluted": per_share(
                F("2023-01-01", "2023-03-31", 0.5, *q1), F("2023-04-01", "2023-06-30", 0.6, *q2),
                F("2023-07-01", "2023-09-30", 0.7, *q3), F("2023-01-01", "2023-12-31", 2.4, *k23)),
            "NetCashProvidedByUsedInOperatingActivities": usd(
                F("2023-01-01", "2023-03-31", 10e6, *q1), F("2023-01-01", "2023-06-30", 22e6, *q2),
                F("2023-01-01", "2023-09-30", 35e6, *q3), F("2023-01-01", "2023-12-31", 50e6, *k23)),
            "PaymentsToAcquirePropertyPlantAndEquipment": usd(
                F("2023-01-01", "2023-03-31", 2e6, *q1), F("2023-01-01", "2023-06-30", 5e6, *q2),
                F("2023-01-01", "2023-09-30", 9e6, *q3), F("2023-01-01", "2023-12-31", 12e6, *k23)),
            "Assets": usd(F(None, "2022-12-31", 500e6, *k22), F(None, "2023-03-31", 510e6, *q1),
                          F(None, "2023-06-30", 520e6, *q2), F(None, "2023-09-30", 540e6, *q3),
                          F(None, "2023-12-31", 560e6, *k23)),
            "LiabilitiesAndStockholdersEquity": usd(F(None, "2023-12-31", 560e6, *k23)),
            "StockholdersEquity": usd(F(None, "2023-12-31", 200e6, *k23)),
        }}}

    TICKERS = {"0": {"cik_str": 1234, "ticker": "XYZ", "title": "XYZ Corp"},
               "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}}

    def setUp(self):
        super().setUp()
        import lisp_sec
        self.lisp_sec = lisp_sec
        lisp_sec._parsed_facts.clear()
        self.addCleanup(lisp_sec._parsed_facts.clear)
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"sec_user_agent": "Test Person test@example.com"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        facts = self.company_facts()
        self.downloads = []
        self.real_sec_download = lisp_sec.sec_download

        def fake_download(url, credentials_path, who):
            self.downloads.append(url)
            if url == lisp_sec.TICKERS_URL:
                return self.TICKERS
            if url == lisp_sec.COMPANY_FACTS_URL % 1234:
                return facts
            raise lisp_core.LispError("%s: %s returned HTTP 404 Not Found" % (who, url))
        patcher = mock.patch.object(lisp_sec, "sec_download", fake_download)
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_annual_income_statement(self):
        self.run_lisp('(define t (sec-income-statement creds "XYZ" :in-millions #f))')
        self.assertShows("(table-column-names t)", '("item" "2023-12-31" "2022-12-31" "unit" "source")')
        items = self.column("t", "item")
        row = lambda label: {name: self.column("t", name)[items.index(label)] for name in ("2023-12-31", "2022-12-31")}
        self.assertEqual(row("Revenue"), {"2023-12-31": 120e6, "2022-12-31": 100e6})      # a concept for each year
        self.assertEqual(row("Net income"), {"2023-12-31": 15e6, "2022-12-31": 11e6})     # the restated 2022
        self.assertEqual(row("Gross profit")["2023-12-31"], 50e6)                       # worked out
        self.assertIn("revenue - cost-of-revenue", self.column("t", "source")[items.index("Gross profit")])
        self.assertNotIn("Interest expense", items)                                     # a line with no values
        # in millions, unless :in-millions is #f -- but never a per-share amount
        self.run_lisp('(define m (sec-income-statement creds "XYZ"))')
        self.assertEqual(self.column("m", "2023-12-31")[:2], [120.0, 70.0])

    def test_quarters_from_year_to_date_figures(self):
        self.run_lisp('(define f (sec-financials creds "XYZ" :period "quarterly" :count 4))')
        self.assertShows('(table-column f "fiscal-period")', '#("Q1" "Q2" "Q3" "Q4")')
        self.assertEqual(self.column("f", "revenue"), [25e6, 30e6, 32e6, 33e6])        # Q4: 120 less 87
        self.assertEqual(self.column("f", "operating-cash-flow"), [10e6, 12e6, 13e6, 15e6])
        self.assertEqual(self.column("f", "free-cash-flow"), [8e6, 9e6, 9e6, 12e6])
        eps = self.column("f", "eps-diluted")
        for found, expected in zip(eps[:3], [0.5, 0.6, 0.7]):
            self.assertAlmostEqual(found, expected, places=6)
        self.assertTrue(math.isnan(eps[3]))       # no fourth-quarter EPS: an average isn't a difference

    def test_balance_sheet_and_worked_out_liabilities(self):
        self.run_lisp('(define b (sec-balance-sheet creds "XYZ" :in-millions #f))')
        items = self.column("b", "item")
        self.assertEqual(self.column("b", "2023-12-31")[items.index("Total liabilities")], 360e6)
        self.assertEqual(self.column("b", "2022-12-31")[items.index("Total assets")], 500e6)
        self.run_lisp('(define q (sec-balance-sheet creds "XYZ" :period "quarterly"))')
        self.assertShows("(table-column-names q)",
                         '("item" "2023-12-31" "2023-09-30" "2023-06-30" "2023-03-31" "unit" "source")')

    def test_sec_financials_has_a_row_per_period(self):
        self.run_lisp('(define f (sec-financials creds "XYZ"))')
        self.assertShows('(table-column f "period-end")', "#(2022-12-31 2023-12-31)")
        self.assertShows('(table-column f "fiscal-year")', "#(2022 2023)")
        # period-end, fiscal-year, fiscal-period, and a column for each line item
        self.assertShows('(length (table-column-names f))', str(3 + len(self.lisp_sec.LINE_ITEMS)))

    def test_facts_concepts_and_company(self):
        self.run_lisp('(define facts (sec-facts creds "XYZ" "NetIncomeLoss"))')
        self.assertShows('(table-column facts "value")', "#(10000000 11000000 15000000)")
        self.assertShows('(table-column facts "filed")', "#(2023-02-15 2024-02-15 2024-02-15)")
        self.assertShows('(table-row-count (sec-concepts creds "XYZ"))', "10")
        self.assertShows('(hash-table-ref (sec-company creds 1234) "name")', '"XYZ Corp"')
        self.assertLispError('(sec-facts creds "XYZ" "Goodwill")', "the company has never reported Goodwill")

    def test_tickers(self):
        self.assertEqual(self.lisp_sec.company_cik(self.credentials, lisp_core.LispString("brk.b"), "t"), 1067983)
        self.assertEqual(self.lisp_sec.company_cik(self.credentials, lisp_core.LispString("0000001234"), "t"), 1234)
        self.assertLispError('(sec-income-statement creds "NOPE")', "the SEC has no company with the ticker NOPE")
        self.assertLispError('(sec-income-statement creds 999)', "the SEC has no XBRL financial data for CIK 999")

    def test_options_and_quarters_for_a_company_with_only_annual_reports(self):
        self.assertLispError('(sec-income-statement creds "XYZ" :period "monthly")', ':period is "annual" or "quarterly"')
        self.assertLispError('(sec-income-statement creds "XYZ" :periods 3)', ":periods isn't an option")
        facts = self.company_facts()
        for entry in facts["facts"]["us-gaap"].values():
            entry["units"] = {u: [f for f in fs if f["form"] == "10-K"] for u, fs in entry["units"].items()}
        self.lisp_sec._parsed_facts[1234] = (time.time(), facts)
        self.assertLispError('(sec-income-statement creds "XYZ" :period "quarterly")',
                             "the SEC has no quarterly reports (10-Qs) for this company")

    def test_the_contact_goes_in_the_user_agent(self):
        sent = []

        def fake_http_download(url, cache_hours, headers, who, shown_url=None):
            sent.append(dict((str(p.car), str(p.cdr)) for p in lisp_core.pairs_to_list(headers)))
            return json.dumps(self.TICKERS).encode()
        with mock.patch.object(lisp_http, "download", fake_http_download):
            self.assertEqual(self.real_sec_download(self.lisp_sec.TICKERS_URL, self.credentials, "t"), self.TICKERS)
        self.assertEqual(sent, [{"User-Agent": "Test Person test@example.com"}])
        with open(self.credentials, "w") as f:
            json.dump({"fred_api_key": "x"}, f)
        with self.assertRaises(lisp_core.LispError) as caught:
            self.lisp_sec.user_agent(self.credentials, "sec-facts")
        self.assertIn('the credentials file has no "sec_user_agent" entry', str(caught.exception))


class TestFdic(LispTestCase):
    """lisp_fdic, with the FDIC's API played by a fake -- no network. Bank
    1234's Call Reports give interest income (in thousands) only for the
    year to date, as they do; net income both ways (NETINC, NETINCQ)."""

    QUARTERS = [   # REPDTE, INTINC (year to date), NETINC (ytd), NETINCQ, ASSET, ROA (ytd), ROAQ
        ("20231231", 400, 100, 30, 10000, 1.0, 1.2),
        ("20240331", 110, 25, 25, 10200, 0.98, 0.98),
        ("20240630", 230, 55, 30, 10400, 1.05, 1.12),
        ("20240930", 350, 80, 25, 10500, 1.02, 0.95),
        ("20241231", 480, 110, 30, 10800, 1.03, 1.1),
    ]
    BANKS = [{"CERT": 1234, "NAME": "First Test Bank", "CITY": "Springfield", "STALP": "IL", "ASSET": 10800,
              "ACTIVE": 1, "NAMEHCR": "TEST BANCORP", "REPDTE": "12/31/2024"},
             {"CERT": 5678, "NAME": "First Test Bank West", "CITY": "Boise", "STALP": "ID", "ASSET": 900,
              "ACTIVE": 1, "NAMEHCR": "", "REPDTE": "12/31/2024"},
             {"CERT": 9999, "NAME": "First Test Savings", "CITY": "Gary", "STALP": "IN", "ASSET": 50,
              "ACTIVE": 0, "NAMEHCR": "", "REPDTE": "03/31/2010"}]

    def setUp(self):
        super().setUp()
        import lisp_fdic
        self.lisp_fdic = lisp_fdic
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"fdic_api_key": "secret-key-123"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_fdic_request = lisp_fdic.fdic_request

        def fake_request(credentials_path, dataset, params, who):
            self.requests.append((dataset, dict(params)))
            if dataset == "financials":
                records = [{"REPDTE": d, "NAME": "First Test Bank", "INTINC": i, "NETINC": n, "NETINCQ": nq,
                            "ASSET": a, "ROA": r, "ROAQ": rq}
                           for d, i, n, nq, a, r, rq in reversed(self.QUARTERS)]        # newest first
            elif dataset == "institutions":
                words = params.get("search", "").split(":", 1)[-1].lower()
                records = [b for b in self.BANKS if words in b["NAME"].lower()]
            else:
                records = [{"ID": i, "N": i * 10} for i in range(1234)]
            offset, limit = int(params.get("offset", 0)), int(params.get("limit", 10))
            return {"meta": {"total": len(records)}, "data": [{"data": r} for r in records[offset:offset + limit]]}
        patcher = mock.patch.object(lisp_fdic, "fdic_request", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def assertClose(self, found, expected):
        """Decimals, as vectors store them (in 32 bits: 0.98 is 0.9800000190734863)."""
        self.assertEqual(len(found), len(expected))
        for f, e in zip(found, expected):
            self.assertAlmostEqual(f, e, places=5)

    def test_quarters_from_year_to_date_figures(self):
        self.run_lisp('(define f (fdic-financials creds 1234 :count 4))')
        self.assertShows('(table-column f "report-date")', "#(2024-03-31 2024-06-30 2024-09-30 2024-12-31)")
        self.assertEqual(self.column("f", "interest-income"), [110000, 120000, 120000, 130000])   # in dollars
        self.assertEqual(self.column("f", "net-income"), [25000, 30000, 25000, 30000])            # NETINCQ
        self.assertClose(self.column("f", "return-on-assets"), [0.98, 1.12, 0.95, 1.1])           # ROAQ
        self.assertEqual(self.column("f", "total-assets"), [10200000, 10400000, 10500000, 10800000])

    def test_years(self):
        self.run_lisp('(define f (fdic-financials creds 1234 :period "annual"))')
        self.assertShows('(table-column f "report-date")', "#(2023-12-31 2024-12-31)")
        self.assertEqual(self.column("f", "interest-income"), [400000, 480000])     # the whole year
        self.assertEqual(self.column("f", "net-income"), [100000, 110000])
        self.assertClose(self.column("f", "return-on-assets"), [1.0, 1.03])         # ROA, not ROAQ

    def test_reports_laid_out_as_statements(self):
        self.run_lisp('(define i (fdic-income-statement creds 1234 :count 2))')
        self.assertShows("(table-column-names i)", '("item" "2024-12-31" "2024-09-30" "unit" "field")')
        items = self.column("i", "item")
        self.assertClose([self.column("i", "2024-12-31")[items.index("Interest income")]], [0.13])   # in millions
        self.assertEqual(self.column("i", "field")[items.index("Net income")], "NETINCQ")
        self.run_lisp('(define r (fdic-ratios creds 1234 :period "annual" :count 1))')
        items = self.column("r", "item")
        self.assertClose([self.column("r", "2024-12-31")[items.index("Return on assets")]], [1.03])
        self.assertEqual(self.column("r", "unit")[items.index("Return on assets")], "percent")
        self.run_lisp('(define b (fdic-balance-sheet creds 1234 :count 1 :in-millions #f))')
        items = self.column("b", "item")
        self.assertEqual(self.column("b", "2024-12-31")[items.index("Total assets")], 10800000)

    def test_banks_by_name(self):
        self.run_lisp('(define found (fdic-find-bank creds "first test"))')
        self.assertEqual(self.column("found", "cert"), [1234, 5678, 9999])
        self.assertShows('(table-column found "last-report")', "#(2024-12-31 2024-12-31 2010-03-31)")
        self.assertEqual(self.lisp_fdic.bank_cert(self.credentials, lisp_core.LispString("first test bank"), "t"), 1234)
        self.assertEqual(self.lisp_fdic.bank_cert(self.credentials, lisp_core.LispString("first test bank west"), "t"), 5678)
        self.assertLispError('(fdic-ratios creds "First Test")',
                             "2 banks have names like First Test -- give the certificate number of one")
        self.assertLispError('(fdic-ratios creds "Savings")', "no bank open now has a name like Savings")

    def test_fdic_get_reads_every_page(self):
        self.run_lisp('(define t (fdic-get creds "failures" (list (cons "fields" "ID,N"))))')
        self.assertShows("(table-row-count t)", "1234")
        self.assertEqual([params["offset"] for _, params in self.requests], [0])      # 10,000 a page
        del self.requests[:]
        self.run_lisp('(define t (fdic-get creds "failures"))')                         # every field: 500 a page
        self.assertEqual([params["offset"] for _, params in self.requests], [0, 500, 1000])
        self.run_lisp('(define t (fdic-get creds "failures" (list (cons "limit" "3"))))')
        self.assertShows("(table-row-count t)", "3")
        self.assertLispError('(fdic-get creds "banks")', "there's no dataset banks")

    def test_what_the_fields_mean(self):
        if importlib.util.find_spec("yaml") is None:
            self.skipTest("the yaml package isn't installed")
        definitions = ("properties:\n  data:\n    properties:\n"
                       "      ASSET:\n        title: Total assets\n        description: All assets.\n"
                       "      DEPUNA:\n        title: Uninsured deposits\n        description: >-\n"
                       "          Deposits over the\n          insured limit.\n")
        with mock.patch.object(lisp_http, "download", lambda *args: definitions.encode()):
            self.run_lisp('(define all (fdic-fields creds "financials"))'
                          '(define some (fdic-fields creds "financials" "uninsured"))')
        self.assertShows('(table-column all "field")', '#("ASSET" "DEPUNA")')
        self.assertShows('(table-column some "description")', '#("Deposits over the insured limit.")')

    def test_the_api_key_is_sent_but_never_shown(self):
        seen = []

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            seen.append((url, shown_url))
            raise lisp_core.LispError("%s: %s returned HTTP 500" % (who, shown_url))
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_fdic_request(self.credentials, "financials", {"filters": "CERT:1"}, "fdic-get")
        self.assertIn("api_key=secret-key-123", seen[0][0])
        self.assertNotIn("secret-key-123", seen[0][1])
        self.assertNotIn("secret-key-123", str(caught.exception))


class TestCensus(LispTestCase):
    """lisp_census, with the Census's API played by a fake -- no network.
    The fake has ACS data for 2024 and earlier, for two counties in New
    York; a variable it isn't told about is "10" everywhere."""

    COUNTIES = {
        "001": {"NAME": "Albany County, New York", "B01003_001E": "5000", "B19013_001E": "85333",
                "B17001_002E": "150", "B17001_001E": "1000",
                "B15003_022E": "100", "B15003_023E": "50", "B15003_024E": "20", "B15003_025E": "30",
                "B15003_001E": "800", "B01002_001E": "40.5"},
        "061": {"NAME": "New York County, New York", "B01003_001E": "1600000", "B19013_001E": "-666666666",
                "B17001_002E": "0", "B17001_001E": "0", "B01002_001E": "38.9"},
    }

    def setUp(self):
        super().setUp()
        import lisp_census
        self.lisp_census = lisp_census
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"us_census_api_key": "census-key-456"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_census_download = lisp_census.census_download

        def fake_download(credentials_path, url, params, cache_hours, who):
            self.requests.append((url, dict(params)))
            if url.endswith("/geography.json"):
                if int(url.split("/data/")[1].split("/")[0]) > 2024:
                    raise lisp_core.LispError("%s: %s returned HTTP 404" % (who, url))
                return {"fips": [{"name": "state"}, {"name": "county", "requires": ["state"], "wildcard": ["state"]}]}
            if url.endswith("/variables.json"):
                return {"variables": {
                    "for": {"label": "Census API FIPS 'for' clause"},
                    "B19013_001E": {"label": "Estimate!!Median household income", "concept": "Median Household Income",
                                    "group": "B19013", "predicateType": "int"},
                    "B01003_001E": {"label": "Estimate!!Total", "concept": "Total Population",
                                    "group": "B01003", "predicateType": "int"}}}
            if url == lisp_census.CATALOG_URL:
                return {"dataset": [
                    {"title": "ACS 5-Year", "c_vintage": 2024, "description": "The ACS.",
                     "distribution": [{"accessURL": "http://api.census.gov/data/2024/acs/acs5"}]},
                    {"title": "ACS 5-Year", "c_vintage": 2023, "description": "The ACS.",
                     "distribution": [{"accessURL": "http://api.census.gov/data/2023/acs/acs5"}]},
                    {"title": "Housing starts", "description": "Construction.",
                     "distribution": [{"accessURL": "http://api.census.gov/data/timeseries/eits/resconst"}]}]}
            wanted = params["for"].split(":")[1]
            variables = params["get"].split(",")
            rows = [variables + ["state", "county"]]
            for code, values in self.COUNTIES.items():
                if wanted in ("*", code):
                    rows.append([values.get(v, "10") for v in variables] + ["36", code])
            return rows if len(rows) > 1 else []
        for patcher in (mock.patch.object(lisp_census, "census_download", fake_download),
                        mock.patch.dict(lisp_census._latest_years, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_numbers_are_numbers_and_codes_keep_their_zeros(self):
        self.run_lisp('(define t (census-get creds "acs/acs5" (list "NAME" "B19013_001E") "county:*"'
                      ' :within "state:36"))')
        self.assertShows("(table-column-names t)", '("NAME" "B19013_001E" "state" "county")')
        self.assertShows('(table-column t "county")', '#("001" "061")')
        self.assertShows('(table-column t "state")', '#("36" "36")')
        income = self.column("t", "B19013_001E")
        self.assertEqual(income[0], 85333)
        self.assertTrue(math.isnan(income[1]))         # -666666666: the Census has no number for it
        url, params = self.requests[-1]
        self.assertTrue(url.endswith("/data/2024/acs/acs5"))     # the latest year there's data for
        self.assertEqual((params["for"], params["in"]), ("county:*", "state:36"))

    def test_predicates_come_back_as_text(self):
        def fake_download(credentials_path, url, params, cache_hours, who):
            return [["EMP", "NAICS2017", "time", "state"], ["1200", "52", "2024", "36"], ["900", "00", "2024", "36"]]
        with mock.patch.object(self.lisp_census, "census_download", fake_download):
            self.run_lisp('(define t (census-get creds "2023/cbp" "EMP" "state:36"'
                          '                      :predicates (list (cons "NAICS2017" "52") (cons "time" "2024"))))')
        self.assertShows('(table-column t "NAICS2017")', '#("52" "00")')     # codes, as they were given
        self.assertEqual(self.column("t", "EMP"), [1200, 900])
        self.assertEqual(self.column("t", "time"), [2024, 2024])               # time isn't a code

    def test_a_year_or_a_full_path(self):
        self.run_lisp('(census-get creds "acs/acs5" "NAME" "county:001" :within "state:36" :year 2019)')
        self.assertTrue(self.requests[-1][0].endswith("/data/2019/acs/acs5"))
        self.run_lisp('(census-get creds "2020/acs/acs5" "NAME" "county:001" :within "state:36")')
        self.assertTrue(self.requests[-1][0].endswith("/data/2020/acs/acs5"))
        self.assertLispError('(census-get creds "acs/acs5" "NAME" "county:999" :within "state:36" :year 2019)',
                             "the Census found nothing for that")

    def test_profile(self):
        self.run_lisp('(define p (census-profile creds "county:*" :within "state:36"))')
        self.assertShows('(table-column p "name")', '#("Albany County, New York" "New York County, New York")')
        self.assertShows('(table-column p "county")', '#("001" "061")')
        self.assertEqual(self.column("p", "population"), [5000, 1600000])
        poverty = self.column("p", "poverty-rate")
        self.assertAlmostEqual(poverty[0], 15.0, places=5)     # 150 of 1,000
        self.assertTrue(math.isnan(poverty[1]))                # 0 of 0
        self.assertAlmostEqual(self.column("p", "bachelors-degree-or-higher")[0], 25.0, places=5)  # 200 of 800
        self.assertAlmostEqual(self.column("p", "median-age")[0], 40.5, places=5)
        self.assertTrue(math.isnan(self.column("p", "median-household-income")[1]))

    def test_variables_places_and_datasets(self):
        self.run_lisp('(define v (census-variables creds "acs/acs5" "household income"))')
        self.assertShows('(table-column v "name")', '#("B19013_001E")')
        self.assertShows('(table-column v "label")', '#("Estimate - Median household income")')
        self.run_lisp('(define v (census-variables creds "acs/acs5" :year 2022))')
        self.assertShows('(table-column v "name")', '#("B01003_001E" "B19013_001E")')     # not "for"
        self.assertTrue(self.requests[-1][0].endswith("/data/2022/acs/acs5/variables.json"))
        self.run_lisp('(define g (census-geographies creds "acs/acs5"))')
        self.assertShows('(table-column g "within")', '#("" "state")')
        self.run_lisp('(define d (census-datasets creds))')
        self.assertShows('(table-column d "dataset")', '#("acs/acs5" "acs/acs5" "timeseries/eits/resconst")')
        self.assertShows('(table-column (census-datasets creds "housing") "title")', '#("Housing starts")')

    def test_places_named_by_within(self):
        self.assertEqual(self.lisp_census.place_names(["tract:*", "state:36 county:061"]), {"tract", "state", "county"})
        self.assertEqual(self.lisp_census.place_names(["zip code tabulation area:10027"]),
                         {"zip code tabulation area"})

    def test_the_api_key_is_sent_but_never_shown(self):
        seen = []

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            seen.append((url, shown_url))
            raise lisp_core.LispError("%s: %s returned HTTP 400" % (who, shown_url))
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_census_download(self.credentials, self.lisp_census.API_URL + "2024/acs/acs5",
                                          {"get": "NAME", "for": "state:*"}, 1, "census-get")
        self.assertIn("key=census-key-456", seen[0][0])
        self.assertNotIn("census-key-456", seen[0][1])
        self.assertNotIn("census-key-456", str(caught.exception))


class TestBls(LispTestCase):
    """lisp_bls, with the BLS's API played by a fake -- no network. Its CPI
    is monthly, 100 + (year - 2020) + month / 100, with March 2021
    missing ("-"); productivity is quarterly; both have annual averages."""

    def setUp(self):
        super().setUp()
        import lisp_bls
        self.lisp_bls = lisp_bls
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"bureau_of_labor_statistics_api_key": "bls-key-789"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_bls_request = lisp_bls.bls_request

        def fake_request(credentials_path, series_ids, start_year, end_year, who, catalog=False, annual=False):
            self.requests.append((list(series_ids), start_year, end_year))
            answer = []
            for series_id in series_ids:
                data = []
                for year in range(start_year, end_year + 1):
                    if series_id == "PRS85006092":
                        periods = ["Q01", "Q02", "Q03", "Q04"] + (["Q05"] if annual else [])
                    else:
                        periods = ["M%02d" % m for m in range(1, 13)] + (["M13"] if annual else [])
                    for period in periods:
                        value = "%.2f" % (100 + (year - 2020) + int(period[1:]) / 100)
                        if (year, period) == (2021, "M03"):
                            value = "-"
                        data.append({"year": str(year), "period": period, "value": value})
                catalog_data = {"series_title": "Title of " + series_id} if catalog and series_id[:3] != "JTS" else None
                answer.append({"seriesID": series_id, "data": data, "catalog": catalog_data})
            return answer
        patcher = mock.patch.object(lisp_bls, "bls_request", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_months_and_quarters_line_up_by_date(self):
        self.run_lisp('(define t (bls-series creds (list "cpi" "productivity" "lns14000000")'
                      ' :start-year 2021 :end-year 2021))')
        self.assertShows("(table-column-names t)", '("date" "cpi" "productivity" "LNS14000000")')
        self.assertShows('(vector-ref (table-column t "date") 0)', "2021-01-01")
        self.assertShows("(table-row-count t)", "12")
        cpi = self.column("t", "cpi")
        self.assertAlmostEqual(cpi[0], 101.01, places=4)
        self.assertTrue(math.isnan(cpi[2]))                          # March: "-"
        productivity = self.column("t", "productivity")
        self.assertAlmostEqual(productivity[3], 101.02, places=4)    # April 1: the second quarter
        self.assertTrue(math.isnan(productivity[1]))                 # nothing for February
        self.assertEqual(self.requests, [(["CUSR0000SA0", "LNS14000000", "PRS85006092"], 2021, 2021)])

    def test_annual_averages(self):
        self.run_lisp('(define t (bls-series creds (list "cpi" "productivity") :start-year 2020'
                      ' :end-year 2021 :annual #t))')
        self.assertShows('(table-column t "date")', "#(2020-01-01 2021-01-01)")
        self.assertAlmostEqual(self.column("t", "cpi")[1], 101.13, places=4)          # M13
        self.assertAlmostEqual(self.column("t", "productivity")[0], 100.05, places=4)  # Q05

    def test_requests_of_at_most_50_series_and_20_years(self):
        ids = ["CUUR0000SA0%02d" % i for i in range(60)]
        self.env[lisp_core.Symbol("ids")] = lisp_core.list_to_pairs([lisp_core.LispString(i) for i in ids])
        self.run_lisp('(define t (bls-series creds ids :start-year 1990 :end-year 2025))')
        self.assertEqual([(len(s), a, b) for s, a, b in self.requests],
                         [(50, 1990, 2009), (50, 2010, 2025), (10, 1990, 2009), (10, 2010, 2025)])
        self.assertShows("(table-row-count t)", str(36 * 12))
        import lisp_data_common
        first, last = lisp_data_common.year_range({}, "t")
        self.assertEqual(last - first, 9)                                     # the last 10 years

    def test_local_area(self):
        self.run_lisp('(define t (bls-local-area creds "36" :start-year 2021 :end-year 2021))')
        self.assertShows("(table-column-names t)",
                         '("date" "labor-force" "employed" "unemployed" "unemployment-rate")')
        self.assertEqual(self.requests[-1][0], ["LASST360000000000003", "LASST360000000000004",
                                                "LASST360000000000005", "LASST360000000000006"])
        self.run_lisp('(bls-local-area creds "36061" :start-year 2021 :end-year 2021)')
        self.assertIn("LAUCN360610000000003", self.requests[-1][0])      # counties: not seasonally adjusted
        self.run_lisp('(bls-local-area creds 6 :start-year 2021 :end-year 2021)')
        self.assertIn("LASST060000000000003", self.requests[-1][0])
        self.assertLispError('(bls-local-area creds "NY")', "isn't a state's FIPS code")

    def test_local_area_for_several_places(self):
        self.run_lisp('(define t (bls-local-area creds (list "36" "36061" 6 "36") :start-year 2021 :end-year 2021))')
        self.assertShows("(table-column-names t)",
                         '("fips" "date" "labor-force" "employed" "unemployed" "unemployment-rate")')
        self.assertEqual(self.column("t", "fips"), ["36"] * 12 + ["36061"] * 12 + ["06"] * 12)   # each place once
        self.assertEqual(len(self.requests), 1)                              # 12 series: one request
        del self.requests[:]
        counties = lisp_core.list_to_pairs([lisp_core.LispString("36%03d" % (2 * i + 1)) for i in range(13)])
        self.env[lisp_core.Symbol("counties")] = counties
        self.run_lisp('(bls-local-area creds counties :start-year 2021 :end-year 2021)')
        self.assertEqual([len(ids) for ids, _, _ in self.requests], [50, 2])   # 52 series: two requests

    def test_names_and_info(self):
        self.assertShows('(vector-ref (table-column (bls-names) "name") 0)', '"cpi"')
        self.run_lisp('(define i (bls-series-info creds (list "cpi" "job-openings")))')
        self.assertShows('(table-column i "series-id")', '#("CUSR0000SA0" "JTS000000000000000JOL")')
        titles = self.column("i", "title")
        self.assertEqual(titles[0], "Title of CUSR0000SA0")
        self.assertTrue(titles[1].startswith("Job openings"))      # the BLS gives no title: bls-names's description
        self.assertLispError('(bls-series creds "not a series!")', "isn't a series ID or one of the short names")

    def test_the_api_key_is_sent_but_never_shown(self):
        sent = []

        def fake_download(url, cache_hours, headers, who, shown_url=None, body=None):
            sent.append(body)
            return json.dumps({"status": "REQUEST_NOT_PROCESSED",
                               "message": ["The key bls-key-789 has reached its daily limit."]}).encode()
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_bls_request(self.credentials, ["CUSR0000SA0"], 2020, 2021, "bls-series")
        self.assertEqual(json.loads(sent[0])["registrationkey"], "bls-key-789")
        self.assertNotIn("bls-key-789", str(caught.exception))
        self.assertIn("daily limit", str(caught.exception))

    def test_a_series_the_bls_does_not_have(self):
        def fake_download(url, cache_hours, headers, who, shown_url=None, body=None):
            return json.dumps({"status": "REQUEST_SUCCEEDED", "message": ["Invalid Series for Series XYZ1"],
                               "Results": {"series": [{"seriesID": "XYZ1", "data": []}]}}).encode()
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_bls_request(self.credentials, ["XYZ1"], 2020, 2021, "bls-series")
        self.assertIn("the BLS has no such series: XYZ1", str(caught.exception))


class TestDataCommon(unittest.TestCase):
    """lisp_data_common: what the data modules share."""

    def credentials_file(self, text):
        path = os.path.join(tempfile.mkdtemp(), "credentials.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_reading_the_credentials_file(self):
        import lisp_data_common as common
        path = self.credentials_file('{"bea_api_key": " abc ", "empty": ""}')
        self.assertEqual(common.credential(path, "bea_api_key", "t"), "abc")          # spaces trimmed
        self.assertIsNone(common.credential(path, "fdic_api_key", "t"))             # optional: None
        self.assertIsNone(common.credential(path, "empty", "t"))
        with self.assertRaises(lisp_core.LispError) as caught:
            common.credential(path, "sec_user_agent", "t", "the SEC asks for a name")
        self.assertIn('the credentials file has no "sec_user_agent" entry -- the SEC asks for a name',
                      str(caught.exception))
        for text, message in (("{not json", "isn't valid JSON"), ("[1, 2]", "must hold a JSON object")):
            with self.assertRaises(lisp_core.LispError) as caught:
                common.credential(self.credentials_file(text), "x", "t")
            self.assertIn(message, str(caught.exception))
        with self.assertRaises(lisp_core.LispError) as caught:
            common.credential("/no/such/file.json", "x", "t")
        self.assertIn("couldn't open the credentials file", str(caught.exception))

    def test_dated_tables_and_records(self):
        import lisp_data_common as common
        table = common.dated_table([("a", {datetime.date(2024, 2, 1): 2.0, datetime.date(2024, 1, 1): 1.0}),
                                    ("b", {datetime.date(2024, 2, 1): 5.0})])
        columns = dict((p.car, p.cdr.items.tolist()) for p in lisp_core.pairs_to_list(table))
        self.assertEqual([str(d.date) for d in columns["date"]], ["2024-01-01", "2024-02-01"])
        self.assertTrue(math.isnan(columns["b"][0]))
        table = common.records_table([{"n": 1, "ok": True, "x": {"y": 2}}, {"n": 2, "s": "t"}])
        columns = dict((p.car, p.cdr.items.tolist()) for p in lisp_core.pairs_to_list(table))
        self.assertEqual((columns["n"], columns["ok"][0], columns["x"][0], columns["s"][1]), ([1, 2], 1, '{"y": 2}', "t"))


class TestBea(LispTestCase):
    """lisp_bea, with the BEA's API played by a fake -- no network. Its NIPA
    tables: T10101 (quarterly and annual), whose lines 3 and 17 are both
    "Goods"; T10105 (in millions); T20600 (monthly only) and T20100
    (quarterly and annual), with the saving rate on line 35. A value is
    year + its period's number / 100 (2025Q2 is 2025.02)."""

    TABLES = {   # table -> (frequencies, [(line, description, UNIT_MULT)])
        "T10101": ("QA", [(1, "Gross domestic product", "0"), (3, "Goods", "0"), (17, "Goods", "0")]),
        "T10105": ("QA", [(1, "Gross domestic product", "6")]),
        "T20600": ("M", [(1, "Personal income", "6"), (35, "Personal saving rate", "0")]),
        "T20100": ("QA", [(1, "Personal income", "6"), (35, "Personal saving rate", "0")]),
    }

    def setUp(self):
        super().setUp()
        import lisp_bea
        self.lisp_bea = lisp_bea
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"bea_api_key": "bea-key-321"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_bea_request = lisp_bea.bea_request
        patcher = mock.patch.object(lisp_bea, "bea_request", self.fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_request(self, credentials_path, params, cache_hours, who):
        self.requests.append(dict(params))
        method = params["method"]
        if method == "GetData" and params["DataSetName"] == "NIPA":
            frequencies, lines = self.TABLES.get(params["TableName"], ("", []))
            if params["Frequency"] not in frequencies:
                raise lisp_core.LispError("%s: the BEA says: Data for this table and frequency are not "
                                          "currently available." % who)
            periods = {"A": [""], "Q": ["Q1", "Q2", "Q3", "Q4"], "M": ["M%02d" % m for m in range(1, 13)]}
            data = []
            for year in params["Year"].split(","):
                for number, period in enumerate(periods[params["Frequency"]], 1):
                    for line, description, multiplier in lines:
                        value = "{:,.2f}".format(int(year) + number / 100) if (year, period) != ("2024", "Q3") else "(NA)"
                        data.append({"LineNumber": str(line), "LineDescription": description, "SeriesCode": "S%d" % line,
                                     "TimePeriod": year + period, "CL_UNIT": "Level", "UNIT_MULT": multiplier,
                                     "DataValue": value})
            return {"Data": data}
        if method == "GetData" and params["DataSetName"] == "Regional":
            places = [("36000", "New York"), ("02000", "Alaska *")]
            years = ["2023", "2024"] if params["Year"] == "LAST5" else params["Year"].split(",")
            return {"Data": [{"GeoFips": fips, "GeoName": name, "TimePeriod": year, "CL_UNIT": "Dollars",
                              "DataValue": "{:,}".format(int(year) * 10 + i)}
                             for i, (fips, name) in enumerate(places) for year in years]}
        if method == "GetParameterValuesFiltered":
            return {"ParamValue": [{"Key": "1", "Desc": "[SAINC1] Personal income"},
                                   {"Key": "3", "Desc": "[SAINC1] Per capita personal income"}]}
        if method == "GetParameterValues":
            return {"ParamValue": [{"TableName": "T10101", "Description": "Table 1.1.1. Real GDP"},
                                   {"TableName": "T20600", "Description": "Table 2.6. Personal Income, Monthly"}]}
        if method == "GetDataSetList":
            return {"Dataset": [{"DatasetName": "NIPA", "DatasetDescription": "Standard NIPA tables"}]}
        if method == "GetParameterList":
            return {"Parameter": [{"ParameterName": "Year", "ParameterDescription": "Years",
                                   "ParameterIsRequiredFlag": "1", "MultipleAcceptedFlag": "1", "AllValue": "X"}]}
        raise AssertionError("no fake for %r" % params)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_a_nipa_table(self):
        self.run_lisp('(define t (bea-nipa creds "T10101" :start-year 2024 :end-year 2025))')
        self.assertShows("(table-column-names t)", '("date" "Gross domestic product" "Goods (line 3)" "Goods (line 17)")')
        self.assertShows('(vector-ref (table-column t "date") 1)', "2024-04-01")         # quarterly first
        gdp = self.column("t", "Gross domestic product")
        self.assertAlmostEqual(gdp[0], 2024.01, places=2)
        self.assertTrue(math.isnan(gdp[2]))                                            # "(NA)"
        self.assertEqual(self.requests[-1]["Year"], "2024,2025")
        self.run_lisp('(define t (bea-nipa creds "T10105" :lines 1 :frequency "A" :start-year 2025 :end-year 2025))')
        self.assertAlmostEqual(self.column("t", "Gross domestic product")[0], 2.02501, places=4)   # millions -> billions
        self.run_lisp('(define t (bea-nipa creds "T20600" :lines (list 35) :start-year 2025 :end-year 2025))')
        self.assertEqual([r["Frequency"] for r in self.requests[-2:]], ["Q", "M"])     # no quarters: months
        self.assertShows("(table-row-count t)", "12")                                   # monthly, the only kind
        self.assertLispError('(bea-nipa creds "T10101" :lines (list 2))', "table T10101 has no line 2")

    def test_short_names(self):
        self.run_lisp('(define t (bea-series creds (list "real-gdp-growth" "personal-saving-rate")'
                      ' :start-year 2025 :end-year 2025))')
        self.assertShows("(table-column-names t)", '("date" "real-gdp-growth" "personal-saving-rate")')
        self.assertShows("(table-row-count t)", "12")                      # quarters fall on months
        self.assertTrue(math.isnan(self.column("t", "real-gdp-growth")[1]))   # nothing for February
        self.run_lisp('(define t (bea-series creds "personal-saving-rate" :frequency "A" :start-year 2025 :end-year 2025))')
        self.assertEqual(self.requests[-1]["TableName"], "T20100")         # its annual table
        self.assertLispError('(bea-series creds "gdp" :frequency "M")', "gdp isn't published monthly")
        self.assertLispError('(bea-series creds "gnp")', "there's no series named gnp")
        self.assertShows('(vector-ref (table-column (bea-names) "name") 0)', '"gdp"')

    def test_regional(self):
        self.run_lisp('(define t (bea-regional creds "SAINC1" 3 (list "36" "02")))')
        self.assertShows("(table-column-names t)", '("fips" "name" "2023" "2024" "unit")')
        self.assertShows('(table-column t "name")', '#("New York" "Alaska")')     # the footnote's * is gone
        self.assertEqual(self.column("t", "2024"), [20240, 20241])
        self.assertEqual((self.requests[-1]["GeoFips"], self.requests[-1]["Year"]), ("36000,02000", "LAST5"))
        self.run_lisp('(bea-regional creds "CAINC1" 3 "ny" :start-year 2020 :end-year 2021)')
        self.assertEqual((self.requests[-1]["GeoFips"], self.requests[-1]["Year"]), ("NY", "2020,2021"))
        self.assertShows('(table-column (bea-regional-lines creds "SAINC1") "line")', "#(1 3)")

    def test_finding_things(self):
        self.assertShows('(table-column (bea-datasets creds) "name")', '#("NIPA")')
        self.assertShows('(table-column (bea-parameters creds "NIPA") "required")', "#(#t)")
        self.assertShows('(table-column (bea-parameter-values creds "NIPA" "TableName" "monthly") "value")',
                         '#("T20600")')
        self.run_lisp('(define t (bea-get creds "NIPA" (list (cons "TableName" "T10105") (cons "Frequency" "A")'
                      '                                 (cons "Year" "2025"))))')
        self.assertAlmostEqual(self.column("t", "DataValue")[0], 2025.01, places=2)   # as the BEA sends it

    def test_the_api_key_is_sent_but_never_shown(self):
        seen = []

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            seen.append((url, shown_url))
            return json.dumps({"BEAAPI": {"Request": {"RequestParam": [{"ParameterName": "USERID",
                                                                        "ParameterValue": "bea-key-321"}]},
                                          "Error": {"APIErrorDescription": "Error retrieving NIPA data.",
                                                    "ErrorDetail": {"Description": "Invalid TableName for bea-key-321"}}}}).encode()
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_bea_request(self.credentials, {"method": "GetData"}, 1, "bea-nipa")
        self.assertIn("UserID=bea-key-321", seen[0][0])
        self.assertNotIn("bea-key-321", seen[0][1])
        self.assertIn("Invalid TableName", str(caught.exception))
        self.assertNotIn("bea-key-321", str(caught.exception))


class TestSchwab(LispTestCase):
    """lisp_schwab, with Schwab played by a fake -- no network, no sign-in
    window. The two made-up accounts end 1111 and 2222; the first is named
    "Brokerage", and the second has no name."""

    ACCOUNTS = [{"accountNumber": "10001111", "hashValue": "HASH1"}, {"accountNumber": "20002222", "hashValue": "HASH2"}]
    POSITIONS = {"10001111": [{"longQuantity": 100.0, "shortQuantity": 0.0, "averagePrice": 150.0, "marketValue": 23000.0,
                               "longOpenProfitLoss": 8000.0, "currentDayProfitLoss": 120.0,
                               "instrument": {"symbol": "AAPL", "description": "APPLE INC", "assetType": "EQUITY",
                                              "cusip": "037833100"}}],
                 "20002222": [{"longQuantity": 0.0, "shortQuantity": 5.0, "averagePrice": 2.5, "marketValue": -700.0,
                               "shortOpenProfitLoss": -450.0, "currentDayProfitLoss": -20.0,
                               "instrument": {"symbol": "SPY   261218C00700000", "description": "SPY CALL",
                                              "assetType": "OPTION"}}]}

    TRANSACTIONS = [
        {"activityId": 2, "type": "TRADE", "tradeDate": "2026-10-02T13:30:00+0000", "description": "BUY TRADE",
         "netAmount": -2300.65,
         "transferItems": [{"instrument": {"assetType": "CURRENCY", "symbol": "CURRENCY_USD"}, "amount": 0.65,
                            "cost": -0.65, "feeType": "COMMISSION"},
                           {"instrument": {"assetType": "EQUITY", "symbol": "AAPL"}, "amount": 10.0, "price": 230.0,
                            "cost": -2300.0, "positionEffect": "OPENING"}]},
        {"activityId": 1, "type": "ACH_RECEIPT", "time": "2026-10-01T15:00:00+0000", "description": "DEPOSIT",
         "netAmount": 5000.0, "transferItems": [{"instrument": {"assetType": "CURRENCY"}, "amount": 5000.0}]}]

    def setUp(self):
        super().setUp()
        import lisp_schwab
        self.lisp_schwab = lisp_schwab
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.credentials = os.path.join(folder, "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"Schwab_Client_ID": "app-key", "Schwab_Client_Secret": "app-secret"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.chain_answer = None            # what the fake sends for a request for a chain
        patcher = mock.patch.object(lisp_schwab, "schwab_request", self.fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_request(self, method, url, who, headers, body=None):
        self.requests.append((method, url, headers, body))
        path = url.split("?")[0].replace(self.lisp_schwab.API_URL, "")
        if path == "/v1/oauth/token":
            return 200, {}, {"access_token": "access-%d" % len(self.requests), "refresh_token": "refresh-1",
                             "expires_in": 1800}
        if path == "/trader/v1/accounts/accountNumbers":
            return 200, {}, self.ACCOUNTS
        if path == "/trader/v1/userPreference":
            return 200, {}, {"accounts": [{"accountNumber": "10001111", "nickName": "Brokerage"},
                                          {"accountNumber": "20002222", "nickName": ""}]}
        if path == "/trader/v1/orders":
            return 200, {}, [{"accountNumber": 10001111, "orderId": 555, "status": "FILLED", "quantity": 10.0,
                              "orderLegCollection": [{"instruction": "BUY", "instrument": {"symbol": "AAPL"}}]}]
        if path == "/trader/v1/accounts":
            return 200, {}, [{"securitiesAccount": {"accountNumber": a["accountNumber"], "type": "MARGIN",
                                                    "currentBalances": {"liquidationValue": 1000.0, "cashBalance": 50.0},
                                                    "positions": self.POSITIONS[a["accountNumber"]]}}
                             for a in self.ACCOUNTS]
        if path == "/trader/v1/accounts/HASH2":
            return 200, {}, {"securitiesAccount": {"accountNumber": "20002222", "positions": self.POSITIONS["20002222"]}}
        if path == "/trader/v1/accounts/HASH1":
            return 200, {}, {"securitiesAccount": {"accountNumber": "10001111", "positions": self.POSITIONS["10001111"]}}
        if path == "/trader/v1/accounts/HASH1/transactions":
            return 200, {}, self.TRANSACTIONS
        if path == "/trader/v1/accounts/HASH2/transactions":
            return 200, {}, [{"activityId": 3, "type": "DIVIDEND_OR_INTEREST", "tradeDate": "2026-10-15T00:00:00+0000",
                              "description": "ORDINARY DIVIDEND", "netAmount": 12.5,
                              "transferItems": [{"instrument": {"assetType": "CURRENCY", "symbol": "CURRENCY_USD"},
                                                 "amount": 12.5}]}]
        if path == "/trader/v1/accounts/HASH1/orders/555":
            return 200, {}, {"orderId": 555, "status": "FILLED"}
        if path == "/marketdata/v1/quotes":
            return 200, {}, {"AAPL": {"quote": {"bidPrice": 229.9, "askPrice": 230.1, "lastPrice": 230.0},
                                      "reference": {"description": "Apple Inc"}}}
        if path == "/marketdata/v1/chains":
            return 200, {}, self.chain_answer
        if path == "/marketdata/v1/pricehistory":
            return 200, {}, {"candles": [{"datetime": 1704175200000, "open": 1, "high": 2, "low": 0.5, "close": 1.5,
                                          "volume": 100}]}           # 2024-01-02, 06:00 UTC
        if path == "/trader/v1/accounts/HASH1/orders" and method == "POST":
            return 201, {"Location": self.lisp_schwab.API_URL + "/trader/v1/accounts/HASH1/orders/98765"}, None
        if method == "DELETE":
            return 200, {}, None
        raise AssertionError("no fake for %s %s" % (method, url))

    def sign_in(self):
        with mock.patch.object(self.lisp_schwab, "has_web_engine", lambda: True), \
                mock.patch.object(self.lisp_schwab, "login_in_window",
                                  lambda url, callback: "https://127.0.0.1/?code=C0DE%40&session=s"):
            self.run_lisp("(schwab-login creds)")

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_signing_in(self):
        self.assertLispError("(schwab-accounts creds)", "not signed in to Schwab -- sign in with (schwab-login creds)")
        self.sign_in()
        method, url, headers, body = self.requests[0]
        self.assertEqual((method, url), ("POST", self.lisp_schwab.TOKEN_URL))
        self.assertEqual(headers["Authorization"], "Basic " + base64.b64encode(b"app-key:app-secret").decode())
        self.assertIn("code=C0DE%40", body.decode())                         # the code, decoded and sent back
        self.assertIn("redirect_uri=https%3A%2F%2F127.0.0.1", body.decode())
        path = self.lisp_schwab.token_file(self.credentials)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")        # readable only by you
        self.run_lisp("(schwab-accounts creds)")
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer access-1")

    def test_tokens_are_renewed_and_run_out(self):
        self.sign_in()
        tokens = self.lisp_schwab.load_tokens(self.credentials, "t")
        self.lisp_schwab.save_tokens(self.credentials, dict(tokens, access_expires=0))      # 30 minutes later
        sent = len(self.requests)
        self.run_lisp("(schwab-accounts creds)")
        renewal = self.requests[sent]                      # renewed first, then asked
        self.assertIn("grant_type=refresh_token", renewal[3].decode())
        self.assertNotEqual(self.requests[-1][2]["Authorization"], "Bearer access-1")
        tokens = self.lisp_schwab.load_tokens(self.credentials, "t")
        self.lisp_schwab.save_tokens(self.credentials, dict(tokens, access_expires=0, refresh_expires=0))  # a week later
        self.assertLispError("(schwab-accounts creds)", "the Schwab sign-in has run out")

    def test_transactions(self):
        self.sign_in()
        self.run_lisp("(define t (schwab-transactions creds))")
        self.assertShows('(table-column t "account")', '#("Brokerage" "Brokerage" "...2222")')     # by name
        self.assertShows('(table-column t "type")', '#("ACH_RECEIPT" "TRADE" "DIVIDEND_OR_INTEREST")')  # oldest first
        self.assertShows('(table-column t "symbol")', '#("" "AAPL" "")')
        self.assertEqual(self.column("t", "quantity")[1], 10.0)
        self.assertEqual(self.column("t", "price")[1], 230.0)
        self.assertEqual(self.column("t", "amount"), [5000.0, -2300.65, 12.5])
        self.assertEqual(self.column("t", "fees")[1], -0.65)
        self.assertShows('(vector-ref (table-column t "date") 0)', "2026-10-01")

    def test_transactions_ask_for_what_is_wanted(self):
        self.sign_in()
        self.run_lisp('(schwab-transactions creds :account "brokerage" :days 90 :type "dividend_or_interest" :symbol "AAPL")')
        url = self.requests[-1][1]
        self.assertIn("/trader/v1/accounts/HASH1/transactions?", url)
        self.assertIn("types=DIVIDEND_OR_INTEREST", url)
        self.assertIn("symbol=AAPL", url)
        self.assertNotIn("HASH2", " ".join(r[1] for r in self.requests))
        self.assertLispError('(schwab-transactions creds :type "BUYS")', "isn't one of Schwab's kinds of transaction")
        self.assertLispError("(schwab-transactions creds :days 0)", ":days")

    def test_schwab_get_names_an_account_by_its_name(self):
        self.sign_in()
        self.assertEqual(self.run_lisp('(hash-table-ref (schwab-get creds "/trader/v1/accounts/{account}/orders/555" '
                                       ':account "Brokerage") "status")'), "FILLED")
        self.run_lisp('(schwab-get creds "/trader/v1/accounts/{account}/transactions" \'(("types" . "TRADE")) :account "2222")')
        self.assertIn("/trader/v1/accounts/HASH2/transactions?types=TRADE", self.requests[-1][1])
        self.assertLispError('(schwab-get creds "/trader/v1/accounts/{account}/orders/555")', "say which account")
        self.assertLispError('(schwab-get creds "/trader/v1/userPreference" :account "IRA")', "has none")

    def test_accounts_and_positions(self):
        self.sign_in()
        self.run_lisp("(define a (schwab-accounts creds))")
        self.assertShows('(table-column a "account")', '#("Brokerage" "...2222")')     # names, not numbers
        self.assertEqual(self.column("a", "value"), [1000.0, 1000.0])
        self.run_lisp("(define p (schwab-positions creds))")
        self.assertShows('(table-column p "symbol")', '#("AAPL" "SPY   261218C00700000")')
        self.assertEqual(self.column("p", "quantity"), [100.0, -5.0])          # short: negative
        self.assertEqual(self.column("p", "unrealized-gain"), [8000.0, -450.0])
        self.run_lisp('(define p (schwab-positions creds :account "2222"))')      # by its last digits
        self.assertShows('(table-column p "account")', '#("...2222")')
        self.assertShows('(table-column (schwab-positions creds) "account")', '#("Brokerage" "...2222")')
        self.assertShows('(table-column (schwab-positions creds :account "brokerage") "symbol")',
                         '#("AAPL")')                                                 # by its name
        self.assertLispError('(schwab-positions creds :account "9999")',
                             "no account matches '9999' -- the accounts are Brokerage, ...2222")

    def test_quotes_and_prices(self):
        self.sign_in()
        self.run_lisp('(define q (schwab-quotes creds (list "AAPL" "NOPE")))')
        self.assertAlmostEqual(self.column("q", "bid")[0], 229.9, places=4)
        self.assertTrue(math.isnan(self.column("q", "bid")[1]))                   # unknown: NaN
        self.assertIn("symbols=AAPL%2CNOPE", self.requests[-1][1])
        self.run_lisp('(define h (schwab-price-history creds "AAPL" :start-date "2024-01-01"))')
        self.assertShows('(table-column h "date")', "#(2024-01-02)")
        self.assertIn("startDate=1704067200000", self.requests[-1][1])

    def test_orders(self):
        self.sign_in()
        self.run_lisp("(define listed (schwab-orders creds))")
        self.assertShows('(table-column listed "account")', '#("Brokerage")')     # its number is a number here
        self.assertShows('(table-column listed "symbol")', '#("AAPL")')
        self.run_lisp('(define o (schwab-order "buy" "aapl" 10 :type "LIMIT" :price 150))')
        order = self.lisp_schwab.lisp_to_json(self.run_lisp("o"))
        self.assertEqual(order["orderLegCollection"][0], {"instruction": "BUY", "quantity": 10,
                                                          "instrument": {"symbol": "AAPL", "assetType": "EQUITY"}})
        self.assertEqual((order["orderType"], order["price"], order["duration"]), ("LIMIT", 150, "DAY"))
        self.assertLispError('(schwab-order "BUY" "AAPL" 10 :type "LIMIT")', "a LIMIT order needs :price")
        self.assertLispError('(schwab-order "BUY_TO_OPEN" "AAPL" 1)', "an equity order's instruction is one of")
        sent = len(self.requests)
        self.assertLispError('(schwab-place-order creds "1111" o)', "nothing was sent")
        self.assertEqual(len(self.requests), sent)                             # not one request
        self.assertShows('(schwab-place-order creds "1111" o :confirm #t)', "98765")
        method, url, headers, body = self.requests[-1]
        self.assertEqual((method, json.loads(body)), ("POST", order))
        self.assertShows('(schwab-cancel-order creds "Brokerage" 98765)', "#t")
        self.assertEqual(self.requests[-1][:2], ("DELETE", self.lisp_schwab.API_URL + "/trader/v1/accounts/HASH1/orders/98765"))


    # -- the option chain ---------------------------------------------------------------------------

    @staticmethod
    def contract(kind, strike, bid, ask, expiration="261120", **more):
        """An option as Schwab's chain has it."""
        symbol = "XYZ   %s%s%08d" % (expiration, kind[0], strike * 1000)
        return dict({"putCall": kind.upper(), "symbol": symbol, "description": "XYZ option", "bid": bid, "ask": ask,
                     "last": bid, "mark": (bid + ask) / 2, "totalVolume": 12, "openInterest": 340, "volatility": 21.5,
                     "delta": 0.4, "vega": 0.1, "strikePrice": float(strike), "daysToExpiration": 35}, **more)

    def a_chain(self):
        c = self.contract
        return {"symbol": "XYZ", "status": "SUCCESS", "underlyingPrice": 101.25, "underlying": {"mark": 101.2},
                "callExpDateMap": {
                    "2026-12-18:63": {"100.0": [c("Call", 100, 4.0, 4.2, "261218", daysToExpiration=63)]},
                    "2026-11-20:35": {"105.0": [c("Call", 105, 1.0, 1.2)], "100.0": [c("Call", 100, 3.1, 3.3)]}},
                "putExpDateMap": {
                    "2026-11-20:35": {"100.0": [c("Put", 100, 1.5, 1.7, volatility=-999, delta=-999)]}}}

    def test_the_option_chain_is_a_table_like_tastytrades(self):
        import lisp_tastytrade
        import urllib.parse
        self.sign_in()
        self.chain_answer = self.a_chain()
        self.run_lisp('(define chain (schwab-option-chain creds "xyz" :expiration (date 2026 11 20) :type "all" :strikes 3))')
        method, url, headers, body = self.requests[-1]
        query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        self.assertEqual(urllib.parse.urlparse(url).path, "/marketdata/v1/chains")
        self.assertEqual(query, {"symbol": "XYZ", "contractType": "ALL", "strategy": "SINGLE", "includeUnderlyingQuote": "true",
                                 "fromDate": "2026-11-20", "toDate": "2026-11-20", "strikeCount": "3"})
        self.assertEqual([str(n) for n in lisp_core.pairs_to_list(self.run_lisp("(table-column-names chain)"))],
                         lisp_tastytrade.OPTION_CHAIN_COLUMNS)
        # by expiration, then strike, calls before puts
        self.assertShows('(table-column chain "symbol")',
                         '#("XYZ   261120C00100000" "XYZ   261120P00100000" "XYZ   261120C00105000" "XYZ   261218C00100000")')
        self.assertShows('(table-column chain "type")', '#("Call" "Put" "Call" "Call")')
        self.assertShows('(table-column chain "strike")', "#(100.0 100.0 105.0 100.0)")
        self.assertShows('(table-column chain "expiration-date")', "#(2026-11-20 2026-11-20 2026-11-20 2026-12-18)")
        self.assertShows('(table-column chain "days-to-expiration")', "#(35 35 35 63)")
        self.assertShows('(table-column chain "underlying")', '#("XYZ" "XYZ" "XYZ" "XYZ")')
        self.assertShows('(table-column chain "underlying-price")', "#(101.25 101.25 101.25 101.25)")
        self.assertShows('(table-column chain "bid")', "#(3.1 1.5 1.0 4.0)")
        self.assertShows('(table-column chain "ask")', "#(3.3 1.7 1.2 4.2)")
        self.assertShows('(table-column chain "mid")', "#(3.2 1.6 1.1 4.1)")
        self.assertShows('(table-column chain "volume")', "#(12 12 12 12)")
        self.assertShows('(table-column chain "open-interest")', "#(340 340 340 340)")
        self.assertShows('(table-column chain "delivery-month")', "#(() () () ())")
        # volatility is in percent in Schwab's answer, and -999 means it has none
        self.assertShows('(table-column chain "implied-volatility")', "#(0.215 nan 0.215 0.215)")
        self.assertShows('(table-column chain "delta")', "#(0.4 nan 0.4 0.4)")
        # no :expiration, :type, or :strikes: none is asked for
        self.run_lisp('(schwab-option-chain creds "XYZ")')
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.requests[-1][1]).query)
        self.assertEqual(sorted(query), ["contractType", "includeUnderlyingQuote", "strategy", "symbol"])
        self.assertEqual(query["contractType"], ["ALL"])
        self.run_lisp('(schwab-option-chain creds "XYZ" :expiration "2026-11-20" :type "call")')
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.requests[-1][1]).query)
        self.assertEqual((query["contractType"], query["fromDate"]), (["CALL"], ["2026-11-20"]))

    def test_the_option_chain_copes_with_other_forms_of_the_answer(self):
        self.sign_in()
        answer = self.a_chain()
        del answer["underlyingPrice"]                               # the price from the underlying's quote
        for by_strike in answer["callExpDateMap"].values():
            for contracts in by_strike.values():
                for contract in contracts:
                    contract["bidPrice"], contract["askPrice"] = contract.pop("bid"), contract.pop("ask")   # other names
                    contract.pop("strikePrice")                                                              # the key's strike
        self.chain_answer = answer
        self.run_lisp('(define chain (schwab-option-chain creds "XYZ" :type "CALL"))')
        self.assertShows('(table-column chain "underlying-price")', "#(101.2 101.2 101.2 101.2)")
        self.assertShows('(table-column chain "bid")', "#(3.1 1.5 1.0 4.0)")
        self.assertShows('(table-column chain "strike")', "#(100.0 100.0 105.0 100.0)")
        self.chain_answer = {"symbol": "XYZ", "status": "SUCCESS", "callExpDateMap": {}, "putExpDateMap": {}}
        self.assertShows('(table-row-count (schwab-option-chain creds "XYZ"))', "0")          # no options: an empty table
        self.assertShows('(length (table-column-names (schwab-option-chain creds "XYZ")))', "17")

    def test_the_option_chain_says_what_is_wrong(self):
        self.sign_in()
        self.chain_answer = dict(self.a_chain(), status="FAILED")
        self.assertLispError('(schwab-option-chain creds "XYZ")', "Schwab says the chain's status is FAILED")
        self.chain_answer = None
        self.assertLispError('(schwab-option-chain creds "XYZ")', "Schwab sent no chain")
        self.chain_answer = dict(self.a_chain(), isChainTruncated=True)
        self.assertLispError('(schwab-option-chain creds "XYZ")', "Schwab cut the chain short")
        self.chain_answer = dict(self.a_chain(), isChainTruncated=False, numberOfContracts=4)
        self.assertShows('(table-row-count (schwab-option-chain creds "XYZ"))', "4")
        self.chain_answer = self.a_chain()
        del self.chain_answer["callExpDateMap"]["2026-12-18:63"]["100.0"][0]["symbol"]
        self.assertLispError('(schwab-option-chain creds "XYZ")', "an option with no symbol")
        self.assertLispError('(schwab-option-chain creds "XYZ" :type "BOTH")', ':type is "CALL", "PUT", or "ALL"')
        self.assertLispError('(schwab-option-chain creds "XYZ" :strikes 0)', ":strikes must be a whole number")
        self.assertLispError('(schwab-option-chain creds "XYZ" :expiration "soon")', ":expiration must be a date")
        self.assertLispError('(schwab-option-chain creds "XYZ" :expirations 1)', "isn't an option")

    # -- an order for a spread ----------------------------------------------------------------------

    def test_a_spread_order_buys_one_option_and_sells_the_other_for_a_net_debit(self):
        self.run_lisp('(define o (schwab-spread-order "XYZ   261120C00100000" "xyz261120c00105000" 2 2.104))')
        order = self.lisp_schwab.lisp_to_json(self.run_lisp("o"))
        self.assertEqual(order, {
            "session": "NORMAL", "duration": "DAY", "orderType": "NET_DEBIT", "complexOrderStrategyType": "VERTICAL",
            "price": 2.1, "orderStrategyType": "SINGLE",
            "orderLegCollection": [
                {"instruction": "BUY_TO_OPEN", "quantity": 2, "instrument": {"symbol": "XYZ   261120C00100000", "assetType": "OPTION"}},
                {"instruction": "SELL_TO_OPEN", "quantity": 2, "instrument": {"symbol": "XYZ   261120C00105000", "assetType": "OPTION"}}]})
        # the symbol is made what Schwab wants: padded to 6 characters (here, with the stock's name 4 long)
        self.run_lisp('(define p (schwab-spread-order "BRKB261120P00110000" "BRKB  261120P00100000" 1 3 :duration "good_till_cancel"))')
        order = self.lisp_schwab.lisp_to_json(self.run_lisp("p"))
        self.assertEqual([leg["instrument"]["symbol"] for leg in order["orderLegCollection"]],
                         ["BRKB  261120P00110000", "BRKB  261120P00100000"])         # puts: the higher strike is bought
        self.assertEqual((order["duration"], order["price"]), ("GOOD_TILL_CANCEL", 3.0))
        # it sends nothing, and can be placed by schwab-place-order as any order
        self.sign_in()
        sent = len(self.requests)
        self.run_lisp('(schwab-spread-order "XYZ   261120C00100000" "XYZ   261120C00105000" 1 2.1)')
        self.assertEqual(len(self.requests), sent)

    def test_a_spread_order_that_is_not_a_debit_spread_is_refused(self):
        buy, sell = "XYZ   261120C00100000", "XYZ   261120C00105000"
        for call, fragment in [
                ('(schwab-spread-order "%s" "%s" 1 2.1)' % (sell, buy), "would be a credit spread"),
                ('(schwab-spread-order "XYZ   261120P00100000" "XYZ   261120P00105000" 1 2.1)', "would be a credit spread"),
                ('(schwab-spread-order "%s" "XYZ   261218C00105000" 1 2.1)' % buy, "same stock, expiration, and type"),
                ('(schwab-spread-order "%s" "XYZ   261120P00105000" 1 2.1)' % buy, "same stock, expiration, and type"),
                ('(schwab-spread-order "%s" "ABC   261120C00105000" 1 2.1)' % buy, "same stock, expiration, and type"),
                ('(schwab-spread-order "%s" "%s" 1 2.1)' % (buy, buy), "the same strike"),
                ('(schwab-spread-order "%s" "%s" 0 2.1)' % (buy, sell), "whole number of spreads"),
                ('(schwab-spread-order "%s" "%s" 1.5 2.1)' % (buy, sell), "whole number of spreads"),
                ('(schwab-spread-order "%s" "%s" 1 0)' % (buy, sell), "net debit must be a number above 0"),
                ('(schwab-spread-order "%s" "%s" 1 0.004)' % (buy, sell), "net debit must be a number above 0"),
                ('(schwab-spread-order "%s" "%s" 1 -1)' % (buy, sell), "net debit must be a number above 0"),
                ('(schwab-spread-order "%s" "%s" 1 "2")' % (buy, sell), "net debit must be a number above 0"),
                ('(schwab-spread-order "XYZ" "%s" 1 2.1)' % sell, "the option to buy must be an option's symbol"),
                ('(schwab-spread-order "%s" "XYZ 261120C105" 1 2.1)' % buy, "the option to sell must be an option's symbol"),
                ('(schwab-spread-order "%s" "%s" 1 2.1 :duration "forever")' % (buy, sell), ":duration is one of"),
                ('(schwab-spread-order "%s" "%s" 1 2.1 :limit 2)' % (buy, sell), "isn't an option")]:
            with self.subTest(call=call):
                self.assertLispError(call, fragment)

    # -- an order for any of the usual spreads ------------------------------------------------------

    @staticmethod
    def lisp_legs(*legs):
        """The legs, (instruction, option, quantity) with the options as "C100" or "P95" of XYZ on 2026-11-20, as Lisp source."""
        symbol = lambda option: "XYZ   261120%s%08d" % (option[0], round(float(option[1:]) * 1000))
        return "(list %s)" % " ".join('(list "%s" "%s" %d)' % (instruction, symbol(option), quantity)
                                      for instruction, option, quantity in legs)

    def multi_leg(self, strategy, legs, price, options=""):
        return self.lisp_schwab.lisp_to_json(
            self.run_lisp('(schwab-multi-leg-order "%s" %s %s %s)' % (strategy, self.lisp_legs(*legs), price, options)))

    def test_a_multi_leg_order_for_each_strategy_has_its_legs_and_its_price(self):
        buy, sell = "BUY_TO_OPEN", "SELL_TO_OPEN"
        for strategy, legs, price, options, order_type in [
                ("VERTICAL", [(buy, "P100", 2), (sell, "P105", 2)], 1.234, "", "NET_DEBIT"),
                ("VERTICAL", [(sell, "C100", 1), (buy, "C105", 1)], 1.5, ":credit #t", "NET_CREDIT"),
                ("BUTTERFLY", [(buy, "C100", 3), (sell, "C105", 6), (buy, "C110", 3)], 1.3, "", "NET_DEBIT"),
                ("BUTTERFLY", [(sell, "P100", 1), (buy, "P105", 2), (sell, "P110", 1)], 1.3, ":credit #t", "NET_CREDIT"),
                ("IRON_CONDOR", [(buy, "P95", 2), (sell, "P100", 2), (sell, "C110", 2), (buy, "C115", 2)], 2.8, ":credit #t", "NET_CREDIT"),
                ("IRON_CONDOR", [(buy, "P95", 1), (sell, "P100", 1), (sell, "C100", 1), (buy, "C105", 1)], 3.6, ":credit #t", "NET_CREDIT"),
                ("IRON_CONDOR", [(sell, "P95", 1), (buy, "P100", 1), (buy, "C110", 1), (sell, "C115", 1)], 2.8, "", "NET_DEBIT"),
                ("STRADDLE", [(buy, "C100", 1), (buy, "P100", 1)], 7.8, "", "NET_DEBIT"),
                ("STRADDLE", [(sell, "P100", 4), (sell, "C100", 4)], 7.8, ":credit #t", "NET_CREDIT"),
                ("STRANGLE", [(buy, "P95", 1), (buy, "C105", 1)], 3.8, ":duration \"good_till_cancel\"", "NET_DEBIT"),
                ("STRANGLE", [(sell, "C105", 2), (sell, "P95", 2)], 3.8, ":credit #t :duration \"fill_or_kill\"", "NET_CREDIT")]:
            with self.subTest(strategy=strategy, legs=legs):
                order = self.multi_leg(strategy, legs, price, options)
                self.assertEqual(order["complexOrderStrategyType"], strategy)
                self.assertEqual(order["orderType"], order_type)
                self.assertEqual(order["price"], round(price, 2))
                self.assertEqual(order["session"], "NORMAL")
                self.assertEqual(order["orderStrategyType"], "SINGLE")
                self.assertEqual(order["duration"], {"": "DAY", ":duration \"good_till_cancel\"": "GOOD_TILL_CANCEL",
                                                     ":credit #t :duration \"fill_or_kill\"": "FILL_OR_KILL"}.get(options, "DAY"))
                self.assertEqual([(leg["instruction"], leg["quantity"], leg["instrument"]["symbol"]) for leg in order["orderLegCollection"]],
                                 [(instruction, quantity, "XYZ   261120%s%08d" % (option[0], round(float(option[1:]) * 1000)))
                                  for instruction, option, quantity in legs])
                self.assertTrue(all(leg["instrument"]["assetType"] == "OPTION" for leg in order["orderLegCollection"]))

    def test_the_legs_may_be_in_any_order_and_the_names_in_any_case(self):
        """The shape is checked from the strikes, not from the order the legs are listed in; the order given is kept."""
        order = self.multi_leg("butterfly", [("buy_to_open", "C110", 1), ("sell_to_open", "C105", 2), ("buy_to_open", "C100", 1)], 1.3)
        self.assertEqual(order["complexOrderStrategyType"], "BUTTERFLY")
        self.assertEqual([leg["instrument"]["symbol"][-8:] for leg in order["orderLegCollection"]], ["00110000", "00105000", "00100000"])
        self.assertEqual(self.multi_leg("iron_condor", [("BUY_TO_OPEN", "C115", 1), ("SELL_TO_OPEN", "P100", 1), ("BUY_TO_OPEN", "P95", 1),
                                                         ("SELL_TO_OPEN", "C110", 1)], 2.8, ":credit #t")["price"], 2.8)

    def test_a_multi_leg_order_sends_nothing(self):
        self.sign_in()
        sent = len(self.requests)
        self.multi_leg("STRADDLE", [("BUY_TO_OPEN", "C100", 1), ("BUY_TO_OPEN", "P100", 1)], 7.8)
        self.assertEqual(len(self.requests), sent)

    def test_a_multi_leg_order_that_has_not_the_shape_of_its_strategy_is_refused(self):
        buy, sell = "BUY_TO_OPEN", "SELL_TO_OPEN"
        condor = [(buy, "P95", 1), (sell, "P100", 1), (sell, "C110", 1), (buy, "C115", 1)]
        for strategy, legs, fragment in [
                ("VERTICAL", [(buy, "C100", 1)], "VERTICAL legs need 2 options, not 1"),
                ("VERTICAL", [(buy, "C100", 1), (sell, "C105", 1), (sell, "C110", 1)], "VERTICAL legs need 2 options, not 3"),
                ("VERTICAL", [(buy, "C100", 1), (sell, "P105", 1)], "are all calls or all puts"),
                ("VERTICAL", [(buy, "C100", 1), (buy, "C105", 1)], "buy one option and sell the other"),
                ("VERTICAL", [(buy, "C100", 1), (sell, "C105", 2)], "the same quantity of each"),
                ("BUTTERFLY", [(buy, "C100", 1), (sell, "C105", 2)], "BUTTERFLY legs need 3 options, not 2"),
                ("BUTTERFLY", [(buy, "C100", 1), (sell, "P105", 2), (buy, "C110", 1)], "are all calls or all puts"),
                ("BUTTERFLY", [(buy, "C100", 1), (sell, "C106", 2), (buy, "C110", 1)], "three strikes equally far apart"),
                ("BUTTERFLY", [(buy, "C100", 1), (buy, "C105", 2), (buy, "C110", 1)], "buy the outer two and sell the middle one"),
                ("BUTTERFLY", [(buy, "C100", 1), (sell, "C105", 1), (buy, "C110", 1)], "the quantities 1, 2, 1"),
                ("BUTTERFLY", [(buy, "C100", 1), (sell, "C105", 2), (buy, "C110", 2)], "the quantities 1, 2, 1"),
                ("IRON_CONDOR", condor[:3], "IRON_CONDOR legs need 4 options, not 3"),
                ("IRON_CONDOR", [(buy, "C95", 1), (sell, "C100", 1), (sell, "C110", 1), (buy, "C115", 1)], "two puts below two calls"),
                ("IRON_CONDOR", [(buy, "C95", 1), (sell, "P100", 1), (sell, "C110", 1), (buy, "P115", 1)], "two puts below two calls"),
                ("IRON_CONDOR", [(buy, "P95", 1), (sell, "P112", 1), (sell, "C110", 1), (buy, "C115", 1)], "two puts below two calls"),
                ("IRON_CONDOR", [(buy, "P95", 1), (sell, "P100", 1), (sell, "C110", 1), (buy, "C116", 1)], "wings of the same width"),
                ("IRON_CONDOR", [(buy, "P95", 1), (buy, "P100", 1), (sell, "C110", 1), (sell, "C115", 1)], "buy the outer two and sell the inner two"),
                ("IRON_CONDOR", [(buy, "P95", 2), (sell, "P100", 1), (sell, "C110", 1), (buy, "C115", 2)], "the same quantity of each"),
                ("STRADDLE", [(buy, "C100", 1), (buy, "C100", 1)], "two legs are the same option"),
                ("STRADDLE", [(buy, "C100", 1), (buy, "C105", 1)], "are a call and a put"),
                ("STRADDLE", [(buy, "C100", 1), (buy, "P95", 1)], "the same strike for the call and the put"),
                ("STRADDLE", [(buy, "C100", 1), (sell, "P100", 1)], "both buy, or both sell"),
                ("STRADDLE", [(buy, "C100", 1), (buy, "P100", 2)], "the same quantity of each"),
                ("STRANGLE", [(buy, "C95", 1), (buy, "P100", 1)], "the put's strike below the call's"),
                ("STRANGLE", [(buy, "C100", 1), (buy, "P100", 1)], "the put's strike below the call's"),
                ("STRANGLE", [(buy, "P95", 1), (sell, "C105", 1)], "both buy, or both sell"),
                ("STRANGLE", [(buy, "P95", 1), (buy, "C105", 3)], "the same quantity of each"),
                ("COLLAR", [(buy, "P95", 1), (buy, "C105", 1)], "the strategy is one of VERTICAL, BUTTERFLY, IRON_CONDOR, STRADDLE, STRANGLE, not COLLAR"),
                ("VERTICAL", [("BUY_TO_CLOSE", "C100", 1), (sell, "C105", 1)], "BUY_TO_OPEN or SELL_TO_OPEN"),
                ("VERTICAL", [(buy, "C100", 0), (sell, "C105", 0)], "whole number of contracts, 1 or more"),
                ("VERTICAL", [(buy, "C100", 1), (sell, "C105", 1)], "")]:
            with self.subTest(strategy=strategy, legs=legs):
                call = '(schwab-multi-leg-order "%s" %s 1.5)' % (strategy, self.lisp_legs(*legs))
                if fragment:
                    self.assertLispError(call, fragment)
                else:
                    self.run_lisp(call)                                   # (the control: this one is good)

    def test_a_multi_leg_order_that_has_not_its_legs_from_one_stock_and_day_or_a_good_price_is_refused(self):
        legs = self.lisp_legs(("BUY_TO_OPEN", "C100", 1), ("SELL_TO_OPEN", "C105", 1))
        other_day = '(list (list "BUY_TO_OPEN" "XYZ   261120C00100000" 1) (list "SELL_TO_OPEN" "XYZ   261218C00105000" 1))'
        other_stock = '(list (list "BUY_TO_OPEN" "XYZ   261120C00100000" 1) (list "SELL_TO_OPEN" "ABC   261120C00105000" 1))'
        for call, fragment in [
                ('(schwab-multi-leg-order "VERTICAL" %s 1.5)' % other_day, "the same stock and expiration"),
                ('(schwab-multi-leg-order "VERTICAL" %s 1.5)' % other_stock, "the same stock and expiration"),
                ('(schwab-multi-leg-order "VERTICAL" %s 0)' % legs, "net debit must be a number above 0"),
                ('(schwab-multi-leg-order "VERTICAL" %s 0.004)' % legs, "net debit must be a number above 0"),
                ('(schwab-multi-leg-order "VERTICAL" %s -1 :credit #t)' % legs, "net credit must be a number above 0"),
                ('(schwab-multi-leg-order "VERTICAL" %s "1.5")' % legs, "net debit must be a number above 0"),
                ('(schwab-multi-leg-order "VERTICAL" %s 1.5 :duration "forever")' % legs, ":duration is one of"),
                ('(schwab-multi-leg-order "VERTICAL" %s 1.5 :limit 2)' % legs, "isn't an option"),
                ('(schwab-multi-leg-order "VERTICAL" 5 1.5)', "legs is a list of (instruction symbol quantity)"),
                ('(schwab-multi-leg-order "VERTICAL" (list (list "BUY_TO_OPEN" "XYZ   261120C00100000")) 1.5)', "a leg is a list of three things"),
                ('(schwab-multi-leg-order "VERTICAL" (list (list "BUY_TO_OPEN" "XYZ" 1) (list "SELL_TO_OPEN" "XYZ   261120C00105000" 1)) 1.5)',
                 "a leg's option must be an option's symbol")]:
            with self.subTest(call=call):
                self.assertLispError(call, fragment)


class TestTastytrade(LispTestCase):
    """lisp_tastytrade, with tastytrade's API played by FakeTastytrade."""

    def run_with_api(self, src, answers):
        with FakeTastytrade(answers) as api:
            self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(api.credentials.name)
            result = self.run_lisp(src)
        self.api = api
        return result

    def test_get_returns_the_data_with_decimal_text_made_numbers(self):
        def answers(path, params):
            return 200, {"data": {"symbol": "SPY", "bid": "765.53", "cusip": "78462F103", "id": "27854",
                                  "is-etf": True, "open-interest": 10095, "dividend": None,
                                  "items": [{"strike-price": "375.0"}]}}
        data = self.run_with_api('(tastytrade-get creds "/instruments/equities/SPY")', answers)
        self.env[lisp_core.Symbol("data")] = data
        self.assertShows('(hash-table-ref data "bid")', "765.53")
        self.assertShows('(hash-table-ref data "cusip")', '"78462F103"')       # text without a decimal point stays text
        self.assertShows('(hash-table-ref data "id")', '"27854"')
        self.assertShows('(hash-table-ref data "is-etf")', "#t")
        self.assertShows('(hash-table-ref data "open-interest")', "10095")
        self.assertShows('(hash-table-ref data "dividend")', "()")
        self.assertShows('(hash-table-ref (car (hash-table-ref data "items")) "strike-price")', "375.0")

    def test_the_path_and_parameters(self):
        answers = lambda path, params: (200, {"data": {}})
        self.run_with_api('(tastytrade-get creds (list "option-chains" "BRK/B"))', answers)
        self.assertEqual(self.api.requests, [("/option-chains/BRK%2FB", {})])
        self.run_with_api("""(tastytrade-get creds "market-data/by-type"
                               (list (cons "equity" (list "SPY" "QQQ")) (cons "index" "SPX")
                                     (cons "from" (date 2026 1 2)) (cons "all" #t)))""", answers)
        self.assertEqual(self.api.requests, [("/market-data/by-type", {"equity": ["SPY", "QQQ"], "index": "SPX",
                                                                       "from": "2026-01-02", "all": "true"})])

    def test_an_answer_in_pages_is_put_together(self):
        def answers(path, params):
            page = int(params.get("page-offset", 0))
            return 200, {"data": {"items": [{"n": page * 2}, {"n": page * 2 + 1}]},
                         "pagination": {"page-offset": page, "total-pages": 3}}
        data = self.run_with_api('(tastytrade-get creds "/transactions")', answers)
        self.env[lisp_core.Symbol("data")] = data
        self.assertShows('(map (lambda (item) (hash-table-ref item "n")) (hash-table-ref data "items"))',
                         "(0 1 2 3 4 5)")
        self.assertEqual(len(self.api.requests), 3)
        data = self.run_with_api('(tastytrade-get creds "/transactions" (list (cons "page-offset" 1)))', answers)
        self.env[lisp_core.Symbol("data")] = data
        self.assertShows('(map (lambda (item) (hash-table-ref item "n")) (hash-table-ref data "items"))', "(2 3)")

    def test_errors_say_what_tastytrade_said(self):
        refused = lambda path, params: (403, {"error": {"message": "Token has insufficient scopes for this request"}})
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_with_api('(tastytrade-get creds "/instruments/equity-options")', refused)
        self.assertEqual(str(caught.exception),
                         "tastytrade-get: HTTP 403: Token has insufficient scopes for this request "
                         "(asking for /instruments/equity-options)")
        missing = lambda path, params: (404, "<html>404 Not Found</html>")
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_with_api('(tastytrade-get creds "/no-such-thing")', missing)
        self.assertIn("HTTP 404: there's no such request -- check the path", str(caught.exception))

    def test_get_table(self):
        items = lambda path, params: (200, {"data": {"items": [{"symbol": "SPY", "iv-rank": "0.35"},
                                                               {"symbol": "QQQ", "iv-rank": "0.47"}]}})
        self.env[lisp_core.Symbol("t")] = self.run_with_api('(tastytrade-get-table creds "/market-metrics")', items)
        self.assertShows("t", '(("symbol" . #("SPY" "QQQ")) ("iv-rank" . #(0.35 0.47)))')
        one = lambda path, params: (200, {"data": {"symbol": "SPY", "is-etf": True}})
        self.env[lisp_core.Symbol("t")] = self.run_with_api('(tastytrade-get-table creds "/instruments/equities/SPY")', one)
        self.assertShows("t", '(("symbol" . #("SPY")) ("is-etf" . #(1)))')

    def test_the_kind_of_instrument_a_symbol_names(self):
        kinds = {symbol: lisp_tastytrade._instrument_type(symbol) for symbol in
                 ["SPY", "BRK/B", "SPX", "SPY   261218C00700000", "/CLZ6", "./CLX6 LO1X6 261117P60", "BTC/USD"]}
        self.assertEqual(kinds, {"SPY": "equity", "BRK/B": "equity", "SPX": "equity",
                                 "SPY   261218C00700000": "equity-option", "/CLZ6": "future",
                                 "./CLX6 LO1X6 261117P60": "future-option", "BTC/USD": "cryptocurrency"})

    def test_quotes(self):
        def answers(path, params):
            return 200, {"data": {"items": [
                {"symbol": "SPY", "instrument-type": "Equity", "bid": "765.53", "ask": "765.54", "mid": "765.535"},
                {"symbol": "SPY   261218C00700000", "instrument-type": "Equity Option", "bid": "73.4",
                 "ask": "76.98", "volatility": "0.2616", "delta": "0.787", "open-interest": 10095}]}}
        self.env[lisp_core.Symbol("q")] = self.run_with_api(
            '(tastytrade-quotes creds (list "SPY   261218C00700000" "NOSUCH" "SPY"))', answers)
        self.assertEqual(self.api.requests, [("/market-data/by-type", {
            "equity-option": ["SPY   261218C00700000"], "equity": ["NOSUCH", "SPY"]})])
        self.assertShows('(table-column q "symbol")', '#("SPY   261218C00700000" "NOSUCH" "SPY")')
        self.assertShows('(table-column q "bid")', "#(73.4 nan 765.53)")
        self.assertShows('(table-column q "implied-volatility")', "#(0.2616 nan nan)")
        self.assertShows('(table-column q "open-interest")', "#(10095.0 nan nan)")
        self.assertShows("(car (table-column-names q))", '"symbol"')

    def test_quotes_ask_for_100_symbols_at_a_time(self):
        answers = lambda path, params: (200, {"data": {"items": []}})
        self.run_with_api('(tastytrade-quotes creds (loop for i from 0 below 250 collect (format "S{}" i)))', answers)
        self.assertEqual([len(params["equity"]) for _path, params in self.api.requests], [100, 100, 50])

    def test_option_chain(self):
        def option(strike, kind, expiration):
            occ = "SPY   %s%s%08d" % (expiration[2:].replace("-", ""), kind, strike * 1000)
            return {"symbol": occ, "option-type": kind,
                    "strike-price": "%s.0" % strike, "expiration-date": expiration,
                    "days-to-expiration": 30, "underlying-symbol": "SPY"}
        chain = [option(strike, kind, expiration) for strike in (90, 95, 100, 105, 110)
                 for kind in ("P", "C") for expiration in ("2099-01-16", "2099-02-20", "2199-01-16")]

        def answers(path, params):
            if path == "/option-chains/SPY":
                return 200, {"data": {"items": chain}}
            if params.get("equity") == ["SPY"]:
                return 200, {"data": {"items": [{"symbol": "SPY", "bid": "101.0", "ask": "102.0", "mid": "101.5"}]}}
            return 200, {"data": {"items": [{"symbol": s, "bid": "1.0", "ask": "1.2", "mid": "1.1",
                                             "volatility": "0.2", "delta": "0.5"}
                                            for s in params["equity-option"]]}}
        with mock.patch.object(lisp_tastytrade.datetime, "date", wraps=datetime.date) as fake_date:
            fake_date.today.return_value = datetime.date(2098, 12, 1)
            self.env[lisp_core.Symbol("chain")] = self.run_with_api('(tastytrade-option-chain creds "SPY" 3 2)', answers)
        # the 2 strikes nearest 101.5 (100 and 105), calls and puts, for the two
        # expirations within 3 months, in order
        self.assertShows('(table-column chain "symbol")',
                         '#("SPY   990116C00100000" "SPY   990116P00100000" "SPY   990116C00105000" '
                         '"SPY   990116P00105000" "SPY   990220C00100000" "SPY   990220P00100000" '
                         '"SPY   990220C00105000" "SPY   990220P00105000")')
        self.assertShows('(table-column chain "type")', '#("Call" "Put" "Call" "Put" "Call" "Put" "Call" "Put")')
        self.assertShows('(vector-ref (table-column chain "underlying-price") 0)', "101.5")
        self.assertShows('(vector-ref (table-column chain "ask") 0)', "1.2")
        self.assertShows('(vector-ref (table-column chain "implied-volatility") 0)', "0.2")

    def test_test_connection_names_the_accounts(self):
        answers = lambda path, params: (200, {"data": {"items": [{"account": {"account-number": "5WT0001"}},
                                                                 {"account": {"account-number": "5WT0002"}}]}})
        self.assertEqual(self.run_with_api("(tastytrade-test-connection creds)", answers),
                         "Connected successfully. Account(s): 5WT0001, 5WT0002.")


class TestHttp(LispTestCase):
    """lisp_http.py, against a small web server on this machine -- the test
    suite never touches the internet."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            hits = []

            def do_GET(self):
                Handler.hits.append(self.path)
                if self.path.startswith("/data.json"):
                    body, kind = b'{"rates": [{"date": "2024-01-02", "rate": 5.3}], "ok": true, "none": null}', "json"
                elif self.path.startswith("/data.csv"):
                    body, kind = b"date,rate\n01/02/2024,5.3\n01/03/2024,5.31\n", "csv"
                elif self.path.startswith("/pipes.csv"):
                    body, kind = b"date|rate\n01/02/2024|5.3\n01/03/2024|5.31\n", "csv"
                elif self.path.startswith("/notes.csv"):
                    body, kind = b'"A note, with a comma."\n\nDate,rate\n2024-01-02,5.3\n2024-01-03,NA\n', "csv"
                elif self.path.startswith("/fred?") and "series_id=NOPE" in self.path:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error_code":400,"error_message":"Bad Request.  The series does not exist."}')
                    return
                elif self.path.startswith("/alpha?") and "symbol=NOPE" in self.path:
                    body, kind = (b'{"Information": "Thank you for using Alpha Vantage! The limit for KEY123 is 25 requests a day."}'), "json"
                elif self.path.startswith("/alpha?") and "symbol=NONE" in self.path:
                    body, kind = b'{"symbol": "NONE", "data": []}', "json"
                elif self.path.startswith("/alpha?"):
                    body, kind = (b'{"symbol": "X", "data": ['
                                  b'{"ex_dividend_date": "2024-03-15", "declaration_date": "2024-02-01",'
                                  b' "record_date": "2024-03-16", "payment_date": "2024-04-01", "amount": "0.25"},'
                                  b'{"ex_dividend_date": "2023-12-14", "declaration_date": "None",'
                                  b' "record_date": "None", "payment_date": "None", "amount": "0.2"}]}'), "json"
                elif self.path == "/broken" or (self.path == "/flaky" and Handler.hits.count("/flaky") == 1):
                    self.send_response(503)                 # the server's own trouble (the first time, for /flaky)
                    self.end_headers()
                    self.wfile.write(b"try again later")
                    return
                elif self.path == "/flaky":
                    body, kind = b'{"ok": true}', "json"
                elif self.path.startswith("/fred?"):
                    body, kind = (b'{"observations": [{"date": "2024-01-01", "value": "5.33"},'
                                  b' {"date": "2024-02-01", "value": "."},'
                                  b' {"date": "2024-03-01", "value": "5.31"}]}'), "json"
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"no such thing")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/" + kind)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.handler = Handler
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        super().setUp()
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache, True)
        for patcher in (mock.patch.dict(os.environ, {"LISP_HTTP_CACHE": cache}),
                        mock.patch.object(lisp_http, "RETRY_SECONDS", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.handler.hits.clear()

    def test_json_becomes_hash_tables_and_lists(self):
        self.run_lisp('(define r (http-get-json "%s/data.json"))' % self.base)
        self.assertShows('(hash-table-ref r "ok")', "#t")
        self.assertShows('(hash-table-ref r "none")', "()")
        self.assertShows('(hash-table-ref (car (hash-table-ref r "rates")) "rate")', "5.3")

    def test_csv_becomes_a_table(self):
        self.assertShows('(table-column (http-get-csv "%s/data.csv") "date")' % self.base,
                         "#(2024-01-02 2024-01-03)")

    def test_a_list_of_names_names_the_columns(self):
        self.assertShows('(http-get-csv "%s/data.csv" (list "day" "pct") 0 \'() :skip 1)' % self.base,
                         '(("day" . #(2024-01-02 2024-01-03)) ("pct" . #(5.3 5.31)))')
        self.assertLispError('(http-get-csv "%s/data.csv" (list "a" "a") 0 \'() :skip 1)' % self.base, "http-get-csv: the column names must differ")

    def test_another_separator(self):
        self.assertShows('(http-get-csv "%s/pipes.csv" :separator "|")' % self.base, '(("date" . #(2024-01-02 2024-01-03)) ("rate" . #(5.3 5.31)))')
        self.assertShows('(http-get-csv "%s/pipes.csv")' % self.base, '(("date|rate" . #("01/02/2024|5.3" "01/03/2024|5.31")))')
        self.assertLispError('(http-get-csv "%s/pipes.csv" :separator "ab")' % self.base, "http-get-csv: :separator is the one character")

    def test_csv_text_columns(self):
        self.assertShows('(table-column (http-get-csv "%s/data.csv" #t 0 \'() :text "date") "date")' % self.base,
                         '#("01/02/2024" "01/03/2024")')                   # as written, not as dates
        self.assertShows('(table-column (http-get-csv "%s/data.csv" :text (list "date")) "date")' % self.base,
                         '#("01/02/2024" "01/03/2024")')
        self.assertLispError('(http-get-csv "%s/data.csv" :text "nope")' % self.base,
                             "http-get-csv: :text names nope, which isn't a column of")

    def test_csv_notes_above_the_header_and_missing_values(self):
        self.assertShows('(http-get-csv "%s/notes.csv" :skip "Date" :missing "NA")' % self.base,
                         '(("Date" . #(2024-01-02 2024-01-03)) ("rate" . #(5.3 nan)))')
        self.assertShows('(http-get-csv "%s/notes.csv" #t 0 \'() :skip 2 :missing (list "NA"))' % self.base,
                         '(("Date" . #(2024-01-02 2024-01-03)) ("rate" . #(5.3 nan)))')
        self.assertLispError('(http-get-csv "%s/notes.csv" :skip "Day")' % self.base, "http-get-csv: no row of")

    def test_text_and_errors(self):
        self.assertIn("rates", self.show('(http-get-text "%s/data.json")' % self.base))
        self.assertLispError('(http-get-text "%s/missing")' % self.base, "HTTP 404")

    def test_cache_is_used_only_when_asked_for(self):
        url = "%s/data.json" % self.base
        self.run_lisp('(http-get-text "%s") (http-get-text "%s")' % (url, url))
        self.assertEqual(len(self.handler.hits), 2)             # no cache-hours: downloads each time
        self.run_lisp('(http-get-text "%s" 1) (http-get-text "%s" 1)' % (url, url))
        self.assertEqual(len(self.handler.hits), 3)             # the second call read the cache
        self.assertShows("(http-clear-cache)", "1")
        self.run_lisp('(http-get-text "%s" 1)' % url)
        self.assertEqual(len(self.handler.hits), 4)

    def test_a_failure_that_may_pass_is_tried_once_more(self):
        self.assertShows('(hash-table-ref (http-get-json "%s/flaky") "ok")' % self.base, "#t")
        self.assertEqual(self.handler.hits, ["/flaky", "/flaky"])           # 503, then fine
        self.handler.hits.clear()
        self.assertLispError('(http-get-text "%s/broken")' % self.base, "HTTP 503")
        self.assertEqual(len(self.handler.hits), 2)
        self.handler.hits.clear()
        self.assertLispError('(http-get-text "%s/missing")' % self.base, "HTTP 404")
        self.assertEqual(len(self.handler.hits), 1)                         # a 404 won't pass: no second try

    def test_a_site_that_cannot_answer_is_a_network_error_and_a_missing_page_is_not(self):
        offline = '(catch-error (http-get-text "%s") (m) :only (network) (list "offline" m))'
        self.assertShows(offline % (self.base + "/broken") + " ", '("offline" "http-get-text: %s/broken returned HTTP 503 '
                         'Service Unavailable -- try again later")' % self.base)
        self.assertLispError(offline % (self.base + "/missing"), "HTTP 404")              # (no such page: not a network error)
        import socket
        with socket.socket() as unused:                 # a port that nothing listens on: the site can't be reached
            unused.bind(("127.0.0.1", 0))
            port = unused.getsockname()[1]
        self.assertEqual(self.run_lisp(offline % ("http://127.0.0.1:%d/x" % port)).car, "offline")

    def test_the_statuses_that_say_a_site_cannot_answer_now(self):
        self.assertEqual([status for status in (200, 400, 401, 403, 404, 408, 429, 500, 502, 503, 504) if lisp_http.unavailable(status)],
                         [408, 429, 500, 502, 503, 504])

    def test_old_downloads_are_deleted(self):
        cache = os.environ["LISP_HTTP_CACHE"]
        now = time.time()
        for file_name, days in (("old", 40), ("recent", 10)):
            with open(os.path.join(cache, file_name), "w") as f:
                f.write("saved")
            os.utime(os.path.join(cache, file_name), (now - days * 24 * 3600,) * 2)
        self.run_lisp('(http-get-text "%s/data.json" 1)' % self.base)           # saving one cleans up
        remaining = os.listdir(cache)
        self.assertNotIn("old", remaining)
        self.assertIn("recent", remaining)
        self.assertEqual(len(remaining), 2)                                  # recent, and the new download

    def test_url_building(self):
        self.assertShows('(http-url "https://x.org/a" (list (cons "q" "a b&c") (cons "n" 5)))',
                         '"https://x.org/a?q=a+b%26c&n=5"')
        self.assertShows('(http-url "https://x.org/a?k=1" (list (cons "n" 5)))', '"https://x.org/a?k=1&n=5"')




    def test_fred_table_lines_series_up_by_date(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "credentials.json"), "w") as f:
            json.dump({"fred_api_key": "KEY123"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(folder, "credentials.json"))
        with mock.patch.object(lisp_fred, "FRED_URL", self.base + "/fred"):
            self.run_lisp('(define t (fred-table creds (list "SOFR" "DGS10") :start-date (date 2024 1 1)))')
            self.run_lisp('(fred-table creds (list "SOFR" "DGS10") :start-date (date 2024 1 1))')
            self.assertLispError('(fred-table creds "NOPE")', "fred-table: ")
        self.assertShows("(table-column-names t)", '("date" "SOFR" "DGS10")')
        self.assertShows('(table-column t "date")', "#(2024-01-01 2024-03-01)")      # FRED's "." is left out
        self.assertShows('(table-column t "DGS10")', "#(5.33 5.31)")
        fred_hits = [hit for hit in self.handler.hits if hit.startswith("/fred")]
        self.assertEqual(len(fred_hits), 3)                     # two series, then kept; then NOPE
        self.assertIn("observation_start=2024-01-01", fred_hits[0])

    def test_a_fred_error_says_what_fred_said_without_the_api_key(self):
        self.use_credentials({"fred_api_key": "KEY123"})
        with mock.patch.object(lisp_fred, "FRED_URL", self.base + "/fred"):
            with self.assertRaises(lisp_core.LispError) as cm:
                self.run_lisp('(fred-table creds "NOPE")')
        self.assertIn("The series does not exist", str(cm.exception))
        self.assertNotIn("KEY123", str(cm.exception))

    def use_credentials(self, entries):
        """creds, in the Lisp environment, is a credentials file with these entries."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "credentials.json"), "w") as f:
            json.dump(entries, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(folder, "credentials.json"))

    def test_alpha_vantage_dividends_are_a_table_oldest_first(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            self.run_lisp('(define d (alpha-vantage-dividends creds "BRK/B"))')
        self.assertShows("(table-column-names d)",
                         '("ex-date" "declaration-date" "record-date" "payment-date" "amount")')
        self.assertShows('(table-column d "ex-date")', "#(2023-12-14 2024-03-15)")
        self.assertShows('(table-column d "declaration-date")', "#(() 2024-02-01)")      # "None" is missing
        self.assertShows('(table-column d "payment-date")', "#(() 2024-04-01)")
        self.assertShows('(table-column d "amount")', "#(0.2 0.25)")
        hit = [hit for hit in self.handler.hits if hit.startswith("/alpha")][0]
        self.assertIn("function=DIVIDENDS", hit)
        self.assertIn("symbol=BRK-B", hit)                      # as Alpha Vantage writes a share class
        self.assertIn("apikey=KEY123", hit)

    def test_a_stock_with_no_dividends_has_a_table_with_no_rows(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            self.run_lisp('(define d (alpha-vantage-dividends creds "NONE"))')
        self.assertShows("(table-row-count d)", "0")
        self.assertShows("(length (table-column-names d))", "5")

    def test_alpha_vantage_says_why_without_the_api_key_and_a_problem_is_not_kept(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            for _ in range(2):
                with self.assertRaises(lisp_core.LispError) as cm:
                    self.run_lisp('(alpha-vantage-dividends creds "NOPE")')
                self.assertIn("Alpha Vantage says: Thank you for using Alpha Vantage! The limit for", str(cm.exception))
                self.assertNotIn("KEY123", str(cm.exception))
        self.assertEqual(len([hit for hit in self.handler.hits if hit.startswith("/alpha")]), 2)   # not cached

    def test_good_dividends_are_kept_for_a_while(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            self.run_lisp('(alpha-vantage-dividends creds "X") (alpha-vantage-dividends creds "X")')
        self.assertEqual(len([hit for hit in self.handler.hits if hit.startswith("/alpha")]), 1)

    def test_alpha_vantage_needs_its_key_in_the_credentials_file(self):
        self.use_credentials({"fred_api_key": "x"})
        self.assertLispError('(alpha-vantage-dividends creds "X")', 'no "alpha_vantage_api_key" entry')


class TestSecFilings(LispTestCase):
    """sec-filings, sec-filing-text, text-tone, and lib/filing_tone.lsp, with
    the SEC played by a fake (lisp_http.fetch is replaced) and a few words
    standing in for the Loughran-McDonald word lists -- no network."""

    SUBMISSIONS = {"cik": "1234", "name": "XYZ Corp", "filings": {
        "recent": {"accessionNumber": ["0000001234-24-000002", "0000001234-24-000001", "0000001234-23-000009"],
                   "filingDate": ["2024-11-01", "2024-08-01", "2023-11-03"],
                   "reportDate": ["2024-09-30", "", "2023-09-30"],
                   "form": ["10-K", "8-K", "10-K"],
                   "items": ["", "2.02,9.01", ""],
                   "primaryDocument": ["xyz-2024.htm", "xyz-8k.htm", "xyz-2023.htm"],
                   "primaryDocDescription": ["10-K", "8-K", "10-K"]},
        "files": [{"name": "CIK0000001234-submissions-001.json"}]}}
    OLDER = {"accessionNumber": ["0000001234-99-000001"], "filingDate": ["1999-12-01"], "reportDate": ["1999-09-30"],
             "form": ["10-K"], "items": [""], "primaryDocument": [""], "primaryDocDescription": [""]}

    # A 10-K: hidden XBRL tags, a table of contents, then the items
    TEN_K = """<html><body>
        <div style="display:none"><ix:header><ix:hidden>Hidden Tag Words</ix:hidden></ix:header></div>
        <p>Table of Contents</p>
        <table><tr><td>Item 1A.</td><td>Risk Factors</td><td>9</td></tr>
               <tr><td>Item 7.</td><td>Management&#8217;s Discussion and Analysis</td><td>20</td></tr></table>
        <p>Item 1A. Risk Factors</p>
        <p>Our results may decline. An adverse
           ruling in litigation could cause a loss.</p>
        <p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
        <p>Item 7. Management&#8217;s Discussion and Analysis</p>
        <p>Sales were strong and margins improved, but growth was not strong.</p>
        <p>Item 7A. Quantitative and Qualitative Disclosures</p><p>Rates.</p>
        </body></html>"""
    EIGHT_K = "<html><body><p>Results were strong.</p></body></html>"

    WORD_LISTS = ("Word,Seq_num,Negative,Positive,Uncertainty,Litigious,Constraining,Source\n"
                  "ADVERSE,1,2009,0,0,0,0,x\nLOSS,2,2009,0,0,0,0,x\nDECLINE,3,2009,0,0,0,0,x\n"
                  "LITIGATION,4,2009,0,0,2009,0,x\nMAY,5,0,0,2009,0,0,x\nSTRONG,6,0,2009,0,0,0,x\n"
                  "IMPROVED,7,0,2009,0,0,0,x\nGROWTH,8,0,-2020,0,0,0,x\nRULING,9,0,0,0,2009,0,x\n")

    def setUp(self):
        super().setUp()
        import lisp_sec
        import lisp_sec_filings
        self.lisp_sec_filings = lisp_sec_filings
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.credentials = os.path.join(folder, "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"sec_user_agent": "Test Person test@example.com"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.word_lists = os.path.join(folder, "Loughran-McDonald_MasterDictionary_1993-2025.csv")
        with open(self.word_lists, "w") as f:
            f.write(self.WORD_LISTS)
        self.env[lisp_core.Symbol("lists")] = lisp_core.LispString(self.word_lists)

        archives = "https://www.sec.gov/Archives/edgar/data/1234/"
        self.pages = pages = {lisp_sec_filings.SUBMISSIONS_URL % 1234: json.dumps(self.SUBMISSIONS),
                 lisp_sec_filings.OLDER_SUBMISSIONS_URL % "CIK0000001234-submissions-001.json": json.dumps(self.OLDER),
                 archives + "000000123424000002/xyz-2024.htm": self.TEN_K,
                 archives + "000000123423000009/xyz-2023.htm": "<html><body><p>Item 7. Management's Discussion</p>"
                                                               "<p>Sales may decline.</p></body></html>",
                 archives + "000000123424000001/xyz-8k.htm": self.EIGHT_K,
                 archives + "000000123499000001/0000001234-99-000001.txt": "ITEM 1. BUSINESS\nXYZ makes things.\n"}
        self.fetched = []

        def fake_fetch(request, name, shown_url, last_try):
            self.fetched.append((request.full_url, request.get_header("User-agent")))
            if request.full_url not in pages:
                raise lisp_core.LispError("%s: %s returned HTTP 404 Not Found" % (name, shown_url))
            return pages[request.full_url].encode()

        tickers = {"0": {"cik_str": 1234, "ticker": "XYZ", "title": "XYZ Corp"}}
        for patcher in (mock.patch.dict(os.environ, {"LISP_HTTP_CACHE": folder + "/cache"}),
                        mock.patch.object(lisp_http, "fetch", fake_fetch),
                        mock.patch.object(lisp_sec, "sec_download", lambda url, creds, who: tickers),
                        mock.patch.dict(lisp_sec_filings._word_lists, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def text(self, src):
        """The text a Lisp expression gives."""
        return str(self.run_lisp(src))

    def test_the_filings_are_a_table_oldest_first(self):
        self.run_lisp('(define f (sec-filings creds "XYZ"))')
        self.assertShows("(table-column-names f)",
                         '("filing-date" "report-date" "form" "items" "description" "accession" "url")')
        self.assertShows('(table-column f "filing-date")', "#(1999-12-01 2023-11-03 2024-08-01 2024-11-01)")
        self.assertShows('(table-column f "report-date")', "#(1999-09-30 2023-09-30 () 2024-09-30)")
        self.assertEqual(self.text('(vector-ref (table-column f "items") 2)'), "2.02,9.01")
        self.assertEqual(self.text('(vector-ref (table-column f "url") 3)'),
                         "https://www.sec.gov/Archives/edgar/data/1234/000000123424000002/xyz-2024.htm")
        self.assertEqual(self.text('(vector-ref (table-column f "url") 0)'),   # no main document: the whole filing, as text
                         "https://www.sec.gov/Archives/edgar/data/1234/000000123499000001/0000001234-99-000001.txt")
        self.assertTrue(all(agent == "Test Person test@example.com" for _, agent in self.fetched))

    def test_forms_and_count_pick_filings(self):
        self.assertShows('(table-column (sec-filings creds "XYZ" :forms "10-k") "filing-date")',
                         "#(1999-12-01 2023-11-03 2024-11-01)")
        self.assertShows('(table-column (sec-filings creds 1234 :forms \'("10-K" "8-K") :count 2) "form")',
                         "#(8-K 10-K)")
        self.assertShows('(table-row-count (sec-filings creds "XYZ" :count 0))', "0")

    def test_the_text_leaves_out_the_tags_and_keeps_paragraphs(self):
        url = '"https://www.sec.gov/Archives/edgar/data/1234/000000123424000002/xyz-2024.htm"'
        self.run_lisp("(define t (sec-filing-text creds %s))" % url)
        text = str(self.run_lisp("t"))
        self.assertNotIn("Hidden Tag Words", text)
        self.assertIn("\nItem 1A. Risk Factors\nOur results may decline. An adverse ruling in litigation could cause a loss.\n",
                      text)
        self.assertIn("Item 7. Management’s Discussion and Analysis 20", text)     # a row of a table is a line

    def test_a_section_is_its_longest_stretch_not_the_table_of_contents(self):
        url = '"https://www.sec.gov/Archives/edgar/data/1234/000000123424000002/xyz-2024.htm"'
        self.assertEqual(self.text('(sec-filing-text creds %s :section "risk-factors")' % url),
                         "Item 1A. Risk Factors\nOur results may decline. An adverse ruling in litigation could cause a loss.")
        self.assertEqual(self.text('(sec-filing-text creds %s :section "management-discussion")' % url),
                         "Item 7. Management’s Discussion and Analysis\n"
                         "Sales were strong and margins improved, but growth was not strong.")
        self.assertLispError('(sec-filing-text creds %s :section "business")' % url, "there's no section business")

    def test_a_heading_is_the_section_only_if_its_own_title_says_so(self):
        # A 10-Q's Part II has another Item 2, whose next lines happen to say "management"
        text = ("Part I\nItem 2.\nManagement's Discussion and Analysis\nSales grew.\nItem 3. Market Risk\nRates.\n"
                "Part II\nItem 2. Unregistered Sales of Equity Securities\nManagement bought back many, many, many "
                "shares in the quarter, more than ever before, as the board had said it would.\nItem 6. Exhibits\n")
        self.assertEqual(self.lisp_sec_filings.section_text(text, "management-discussion", "t"),
                         "Item 2.\nManagement's Discussion and Analysis\nSales grew.")

    def test_a_missing_section_is_an_error_of_its_own_kind(self):
        url = '"https://www.sec.gov/Archives/edgar/data/1234/000000123424000001/xyz-8k.htm"'
        self.assertEqual(self.text('(catch-error (sec-filing-text creds %s :section "risk-factors") (m) :only (no-section) m)'
                                   % url),
                         'sec-filing-text: the filing has no "risk-factors" section that I could find '
                         '(10-Ks have had one since 2005)')

    def test_text_tone_counts_the_words_on_each_list(self):
        self.run_lisp('(define tone (text-tone "Our results may decline. An adverse ruling in litigation could '
                      'cause a loss." :word-lists lists))')
        self.assertShows('(hash-table-ref tone "words")', "13")
        self.assertAlmostEqual(self.run_lisp('(hash-table-ref tone "negative")'), 100 * 4 / 13)   # decline adverse litigation loss
        self.assertAlmostEqual(self.run_lisp('(hash-table-ref tone "uncertainty")'), 100 * 1 / 13)
        self.assertAlmostEqual(self.run_lisp('(hash-table-ref tone "litigious")'), 100 * 2 / 13)  # ruling, litigation
        self.assertAlmostEqual(self.run_lisp('(hash-table-ref tone "net-tone")'), -100 * 4 / 13)

    def test_a_positive_word_after_not_and_a_word_taken_off_a_list_are_not_counted(self):
        # strong, improved: positive; "growth" was taken off the list; "not strong" isn't positive
        self.run_lisp('(define tone (text-tone "Sales were STRONG and margins improved, but growth was not strong."'
                      ' :word-lists lists))')
        self.assertAlmostEqual(self.run_lisp('(hash-table-ref tone "positive")'), 100 * 2 / 11)
        self.assertShows('(hash-table-ref (text-tone "" :word-lists lists) "negative")', "nan")

    def test_text_tone_finds_the_word_lists_in_downloads_or_says_where_to_get_them(self):
        with mock.patch.object(self.lisp_sec_filings, "WORD_LISTS_FOLDERS", [os.path.dirname(self.word_lists)]):
            self.assertShows('(hash-table-ref (text-tone "a loss") "negative")', "50.0")
        with mock.patch.object(self.lisp_sec_filings, "WORD_LISTS_FOLDERS", [os.path.join(self.word_lists, "nowhere")]):
            self.assertLispError('(text-tone "a loss")', "download Loughran-McDonald_MasterDictionary_1993-2025.csv")
        not_lists = os.path.join(os.path.dirname(self.word_lists), "other.csv")
        with open(not_lists, "w") as f:
            f.write("Word,Negative\nLOSS,2009\n")
        self.assertLispError('(text-tone "a loss" :word-lists "%s")' % not_lists, "it has no positive column")

    # A section of a few hundred words, with none on the word lists
    FILLER = " ".join(["Revenue grew in each region over the year."] * 30)

    def add_filing(self, name, text, exhibit_13=None):
        """A filing of the fake SEC's, in the folder of accession 0000001234-25-000001: the
        document name with text (plain text, not HTML), and its index page -- with an
        Exhibit 13, if it's given; its url."""
        folder = "https://www.sec.gov/Archives/edgar/data/1234/000000123425000001/"
        self.pages[folder + name] = text
        rows = '<tr><td>1</td><td>10-K</td><td><a href="/Archives/edgar/data/1234/000000123425000001/%s">%s</a></td>' \
               '<td>10-K</td></tr>' % (name, name)
        if exhibit_13 is not None:
            self.pages[folder + "annual.htm"] = exhibit_13
            rows += ('<tr><td>2</td><td>EXHIBIT 13</td><td><a href="/Archives/edgar/data/1234/000000123425000001/'
                     'annual.htm">annual.htm</a> iXBRL</td><td>EX-13</td></tr>')
        self.pages[folder + "0000001234-25-000001-index.htm"] = "<html><table>%s</table></html>" % rows
        return folder + name

    def section(self, url, section):
        return self.text('(catch-error (sec-filing-text creds "%s" :section "%s") (m) :only (no-section) m)'
                         % (url, section))

    def test_a_section_in_the_annual_report_filed_as_exhibit_13_is_read_from_it(self):
        ten_k = ("Item 1A. Risk Factors\nInformation in response to this Item 1A can be found in the 2025 Annual Report "
                 "to Shareholders under \u201cFinancial Review \u2013 Risk Factors.\u201d\nItem 1B. Comments\nNone.\n"
                 "Item 7. Management\u2019s Discussion and Analysis\nInformation in response to this Item 7 can be found "
                 "in the 2025 Annual Report to Shareholders under \u201cFinancial Review.\u201d\nItem 8. Statements\n")
        annual = ("<html><body><p>Financial Review</p><p>3</p><p>Risk Factors</p><p>40</p><p>Controls and Procedures</p>"
                  "<p>Financial Review</p><p>Overview</p><p>%s</p><p>Consolidated balance sheets and cash flows analysis</p>"
                  "<p>%s</p><p>Risk Factors</p><p>We may see losses. %s</p><p>Controls and Procedures</p><p>Fine.</p>"
                  "</body></html>") % (self.FILLER, self.FILLER, self.FILLER)
        url = self.add_filing("xyz-10k.htm", ten_k, exhibit_13=annual)
        review = self.section(url, "management-discussion")
        self.assertTrue(review.startswith("Financial Review\nOverview\nRevenue grew"))     # not the table of contents
        self.assertIn("Consolidated balance sheets and cash flows analysis", review)     # a heading of its own
        self.assertNotIn("We may see losses", review)
        risks = self.section(url, "risk-factors")
        self.assertTrue(risks.startswith("Risk Factors\nWe may see losses."))
        self.assertTrue(risks.endswith("each region over the year."))

    def test_a_section_later_in_the_same_document_with_its_title_on_each_page_is_read_from_there(self):
        ten_k = ("Item 7. Management\u2019s Discussion and Analysis\nReference is made to the section entitled "
                 "\u201cManagement\u2019s Discussion and Analysis\u201d in the Financial Section of this report.\n"
                 "Item 8. Statements\nSee the Financial Section.\nFinancial Section\n"
                 "MANAGEMENT\u2019S DISCUSSION AND ANALYSIS\nPage one. %s\n"
                 "MANAGEMENT\u2019S DISCUSSION AND ANALYSIS\nPage two. %s\n"
                 "MANAGEMENT\u2019S REPORT ON INTERNAL CONTROL OVER FINANCIAL REPORTING\nControls are good.\n"
                 % (self.FILLER, self.FILLER))
        url = self.add_filing("xyz-10k.htm", ten_k)
        found = self.section(url, "management-discussion")
        self.assertTrue(found.startswith("MANAGEMENT\u2019S DISCUSSION AND ANALYSIS\nPage one."))
        self.assertIn("Page two.", found)
        self.assertNotIn("Controls are good", found)

    def test_a_list_of_pages_is_followed_to_the_title_in_its_parentheses(self):
        ten_q = ("Item 2. Management\u2019s Discussion and Analysis (Financial Review)\nOverview\n3\nRisk Factors\n52\n"
                 "Item 3. Market Risk\nSee the Financial Review.\n"
                 "Financial Review\nOverview\n%s\nRisk Factors\nSee the 10-K.\n" % self.FILLER)
        url = self.add_filing("xyz-10q.htm", ten_q)
        self.assertTrue(self.section(url, "management-discussion").startswith("Financial Review\nOverview\nRevenue grew"))

    def test_a_pointer_to_another_filing_or_a_short_answer_stays_as_it_is(self):
        ten_q = ("Item 1A. Risk Factors\nConsider the factors in Part I, \u201cItem 1A. Risk Factors\u201d in our Annual "
                 "Report on Form 10-K for the year ended December 31, 2025.\nItem 2. Sales\nNone.\n"
                 "Risk Factors\n%s\nControls and Procedures\nFine.\n" % self.FILLER)
        url = self.add_filing("xyz-10q.htm", ten_q)
        self.assertTrue(self.section(url, "risk-factors").startswith("Item 1A. Risk Factors\nConsider the factors"))
        # "Not applicable": the only other "Risk Factors" is a line of the table of contents
        ten_k = ("Contents\nRisk Factors\n4\nControls and Procedures\n9\n"
                 "Item 1A. Risk Factors\nNot applicable to a smaller reporting company.\nItem 2. Properties\nNone.\n")
        url = self.add_filing("xyz-10k.htm", ten_k)
        self.assertEqual(self.section(url, "risk-factors"),
                         "Item 1A. Risk Factors\nNot applicable to a smaller reporting company.")

    def test_filing_tone_scores_each_filing(self):
        lisp_core.run_file(os.path.join(LIB, "filing_tone.lsp"), self.env)
        self.run_lisp('(define tones (filing-tone creds "XYZ" :section "management-discussion" :word-lists lists))')
        self.assertShows("(table-column-names tones)",
                         '("filing-date" "report-date" "form" "words" "negative" "positive" "uncertainty" '
                         '"litigious" "constraining" "net-tone" "url")')
        self.assertShows('(table-column tones "filing-date")', "#(1999-12-01 2023-11-03 2024-11-01)")
        self.assertShows('(table-column tones "words")', "#(0 6 16)")     # the 1999 filing has no MD&A: no words
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column tones "negative") 1)'), 100 / 6)  # decline
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column tones "positive") 2)'), 100 * 2 / 16)
        self.run_lisp('(define all (filing-tone creds "XYZ" :forms "8-K" :word-lists lists))')   # all of each filing
        self.assertShows('(table-column all "words")', "#(3)")
        self.run_lisp("(show-filing-tone tones)")
        self.assertIn("2024-11-01", self.printed())


class TestGoogleSheets(LispTestCase):
    """lisp_google, with Google played by a fake -- no network, and no browser: a thread plays it, going to the
    address the sign-in would send it to."""

    def setUp(self):
        super().setUp()
        import lisp_google
        self.google = lisp_google
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.credentials = os.path.join(folder, "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"google_client_id": "app-id", "google_client_secret": "app-secret"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []                  # (method, url, headers, the body as JSON or form text)
        self.token_answer = {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        patcher = mock.patch.object(lisp_google, "google_request", self.fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_request(self, method, url, who, headers, body=None):
        if url == self.google.TOKEN_URL:
            self.requests.append((method, url, headers, body.decode()))
            if isinstance(self.token_answer, Exception):
                raise self.token_answer
            return self.token_answer
        self.requests.append((method, url, headers, json.loads(body)))
        if url == self.google.SHEETS_URL:
            return {"spreadsheetId": "ID1", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/ID1/edit",
                    "sheets": [{"properties": {"sheetId": 100 + i}} for i in range(len(self.requests[-1][3]["sheets"]))]}
        if self.fail_on and self.fail_on in url:
            raise lisp_core.LispError("google-sheet: Google says (HTTP 500): oops")
        return {}

    fail_on = None

    def sign_in(self, code="C0DE", state=None, error=None):
        """(google-login creds), with a thread that plays the browser: it goes to the address the sign-in
        is waiting at, with the code (or an error, or another state), as Google would send it."""
        import threading
        import urllib.parse
        import urllib.request
        opened = []

        def browser(url):
            opened.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            answer = {"error": error} if error else {"code": code, "state": state or query["state"][0]}
            address = query["redirect_uri"][0] + "/?" + urllib.parse.urlencode(answer)
            threading.Thread(target=lambda: urllib.request.urlopen(address).read()).start()

        with mock.patch.object(self.google, "open_browser", browser):
            try:
                return self.run_lisp("(google-login creds)")
            finally:
                self.opened = opened[0]

    def save_a_sign_in(self, access_expires=None):
        self.google.save_tokens(self.credentials, {"access_token": "access-1", "refresh_token": "refresh-1",
                                                   "access_expires": time.time() + 3000 if access_expires is None
                                                   else access_expires})

    def sheet_calls(self):
        return [r for r in self.requests if r[1] != self.google.TOKEN_URL]

    # --- signing in -----------------------------------------------------------------------------------------

    def test_signing_in(self):
        import hashlib
        import urllib.parse
        self.assertLispError("(google-sheet creds \"T\" '() (make-table \"a\" #(1)))",
                             "not signed in to Google -- sign in with (google-login creds)")
        self.assertTrue(self.sign_in())
        asked = urllib.parse.urlparse(self.opened)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(asked.query).items()}
        self.assertEqual(asked.netloc, "accounts.google.com")
        self.assertEqual((query["client_id"], query["scope"], query["response_type"]),
                         ("app-id", "https://www.googleapis.com/auth/drive.file", "code"))
        self.assertEqual((query["access_type"], query["code_challenge_method"]), ("offline", "S256"))
        self.assertTrue(query["redirect_uri"].startswith("http://127.0.0.1:"))
        method, url, headers, body = self.requests[0]
        sent = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        self.assertEqual((method, url), ("POST", self.google.TOKEN_URL))
        self.assertEqual((sent["code"], sent["client_secret"], sent["grant_type"]), ("C0DE", "app-secret", "authorization_code"))
        self.assertEqual(sent["redirect_uri"], query["redirect_uri"])
        # the code can only be traded by whoever knew the verifier whose hash was sent
        import base64
        digest = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).decode().rstrip("=")
        self.assertEqual(digest, query["code_challenge"])
        path = self.google.token_file(self.credentials)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")             # readable only by you
        self.assertEqual(self.google.load_tokens(self.credentials, "t")["refresh_token"], "refresh-1")

    def test_sign_in_that_goes_wrong(self):
        with self.assertRaises(lisp_core.LispError) as caught:
            self.sign_in(error="access_denied")
        self.assertIn("Google says: access_denied", str(caught.exception))
        with self.assertRaises(lisp_core.LispError) as caught:
            self.sign_in(state="not-the-one-we-sent")
        self.assertIn("wasn't the one asked for", str(caught.exception))
        self.token_answer = {"access_token": "a", "expires_in": 3600}                # (no refresh token)
        with self.assertRaises(lisp_core.LispError) as caught:
            self.sign_in()
        self.assertIn("didn't send a refresh token", str(caught.exception))
        self.assertFalse(os.path.exists(self.google.token_file(self.credentials)))
        with open(self.credentials, "w") as f:
            json.dump({"google_client_id": "app-id"}, f)
        self.assertLispError("(google-login creds)", 'no "google_client_secret" entry')

    def test_the_sign_in_gives_up_waiting(self):
        with mock.patch.object(self.google, "SIGN_IN_WAIT_SECONDS", 0), \
                mock.patch.object(self.google, "open_browser", lambda url: None):
            self.assertLispError("(google-login creds)", "no sign-in within 0 minutes")

    def test_tokens_are_renewed(self):
        self.save_a_sign_in(access_expires=0)                                         # an hour later
        self.token_answer = {"access_token": "access-2", "expires_in": 3600}
        self.run_lisp("(google-sheet creds \"T\" '() (make-table \"a\" #(1)))")
        renewal = self.requests[0]
        self.assertIn("grant_type=refresh_token", renewal[3])
        self.assertIn("refresh_token=refresh-1", renewal[3])
        self.assertEqual(self.sheet_calls()[0][2]["Authorization"], "Bearer access-2")
        self.assertEqual(self.google.load_tokens(self.credentials, "t")["refresh_token"], "refresh-1")
        self.save_a_sign_in(access_expires=0)
        self.token_answer = lisp_core.LispError("google-sheet: Google says (HTTP 400): invalid_grant")
        self.assertLispError("(google-sheet creds \"T\" '() (make-table \"a\" #(1)))",
                             "invalid_grant -- sign in again with (google-login creds)")

    # --- the sheet ------------------------------------------------------------------------------------------

    def test_a_tab_for_each_table(self):
        self.save_a_sign_in()
        self.run_lisp("""(define loans (make-table "id" (vector "a" "b" "c") "balance" #(125000 98000.5 250000)
                                                  "rate" #(0.0625 0.0575 0.07) "note" (vector "=1+1" "" "x")))
                         (define small (make-table "state" (vector "NY" "PA") "count" #(2 5)))
                         (define url (google-sheet creds "My loans"
                                       '(("balance" ",.2f") ("rate" ".3%") ("note") ("count" ",d"))
                                       loans small))""")
        self.assertShows("url", '"https://docs.google.com/spreadsheets/d/ID1/edit"')
        create, values, formatting = self.sheet_calls()
        self.assertEqual(create[2]["Authorization"], "Bearer access-1")
        self.assertEqual(create[3]["properties"]["title"], "My loans")
        self.assertEqual([s["properties"]["title"] for s in create[3]["sheets"]], ["id", "state"])    # a tab's first column
        self.assertEqual(create[3]["sheets"][0]["properties"]["gridProperties"],
                         {"rowCount": 4, "columnCount": 3, "frozenRowCount": 1})                   # (note is left out)
        self.assertEqual(values[1], self.google.SHEETS_URL + "/ID1/values:batchUpdate")
        body = values[3]
        self.assertEqual(body["valueInputOption"], "RAW")                    # so "=1+1" is text, not a formula
        self.assertEqual(body["data"][0], {"range": "'id'!A1", "values": [
            ["id", "balance", "rate"], ["a", 125000, 0.0625], ["b", 98000.5, 0.0575], ["c", 250000, 0.07]]})
        self.assertEqual(body["data"][1], {"range": "'state'!A1", "values": [["state", "count"], ["NY", 2], ["PA", 5]]})
        self.assertEqual(formatting[1], self.google.SHEETS_URL + "/ID1:batchUpdate")
        requests = formatting[3]["requests"]
        number_formats = [(r["repeatCell"]["range"]["sheetId"], r["repeatCell"]["range"]["startColumnIndex"],
                           r["repeatCell"]["cell"]["userEnteredFormat"]["numberFormat"])
                          for r in requests
                          if "numberFormat" in r.get("repeatCell", {}).get("cell", {}).get("userEnteredFormat", {})]
        self.assertEqual(number_formats, [(100, 1, {"type": "NUMBER", "pattern": "#,##0.00"}),
                                          (100, 2, {"type": "PERCENT", "pattern": "0.000%"}),
                                          (101, 1, {"type": "NUMBER", "pattern": "#,##0"})])
        bold = [r["repeatCell"]["range"]["sheetId"] for r in requests
                if "repeatCell" in r and "textFormat" in r["repeatCell"]["cell"]["userEnteredFormat"]]
        self.assertEqual(bold, [100, 101])
        self.assertEqual([r["autoResizeDimensions"]["dimensions"]["endIndex"] for r in requests
                          if "autoResizeDimensions" in r], [3, 2])
        self.assertNotIn("access-1", json.dumps([r[3] for r in self.sheet_calls()]))          # (only in the headers)

    def test_stratify_all_goes_straight_in(self):
        self.save_a_sign_in()
        self.run_lisp("""(define pools (make-table "fico" #(610 650 690 730 770 810) "state" (vector "NY" "NY" "PA" "PA" "NY" "PA")
                                                    "balance" #(10 20 30 40 50 60) "cpr" #(0.1 0.2 0.1 0.3 0.2 0.1)))
                         (define strata (stratify-all pools '(("fico" (equal-count 2)) ("state" each))
                                                      '(("cpr" weighted-mean)) :weight "balance"))
                         (apply google-sheet creds "Strata" '(("percent" ".1%")) strata)""")
        create, values, formatting = self.sheet_calls()
        self.assertEqual([s["properties"]["title"] for s in create[3]["sheets"]], ["fico", "state"])
        self.assertEqual(values[3]["data"][1]["values"][0][:2], ["state", "count"])
        self.assertEqual(values[3]["data"][1]["values"][-1][0], "total")

    def test_values_of_every_kind(self):
        self.use_single_precision()           # (the share column is float32: 0.1 must come out as 0.1)
        self.save_a_sign_in()
        self.env[lisp_core.Symbol("t")] = lisp_core.list_to_pairs([
            lisp_core.Pair(lisp_core.LispString("when"), lisp_core.LispVector([lisp_core.LispDate(2024, 1, 2),
                                                                                 lisp_core.LispDate(1899, 12, 30), None])),
            lisp_core.Pair(lisp_core.LispString("share"), lisp_vector_math.to_vector(
                np.array([0.1, float("nan"), float("inf")], dtype=np.float32))),
            lisp_core.Pair(lisp_core.LispString("count"), lisp_vector_math.to_vector(np.array([1, 2, 3]))),
            lisp_core.Pair(lisp_core.LispString("what"), lisp_core.LispVector(["=SUM(A1)", "it's", "+1"]))])
        self.run_lisp("(google-sheet creds \"T\" '((\"share\" \".2f\")) t)")
        create, values, formatting = self.sheet_calls()
        self.assertEqual(values[3]["data"][0]["values"][1:],
                         [[45293, 0.1, 1, "=SUM(A1)"], [0, "", 2, "it's"], ["", "", 3, "+1"]])    # 0.1, not 0.10000000149
        formats = {r["repeatCell"]["range"]["startColumnIndex"]: r["repeatCell"]["cell"]["userEnteredFormat"]["numberFormat"]
                   for r in formatting[3]["requests"]
                   if "numberFormat" in r.get("repeatCell", {}).get("cell", {}).get("userEnteredFormat", {})}
        self.assertEqual(formats, {0: {"type": "DATE", "pattern": "yyyy-mm-dd"},          # (a date, whatever the format)
                                   1: {"type": "NUMBER", "pattern": "0.00"}})

    def test_names_of_tabs(self):
        self.save_a_sign_in()
        self.run_lisp("""(define a (make-table "Sales" #(1) "x" #(2)))
                         (define b (make-table "sales" #(1)))
                         (define c (make-table "O'Brien" #(1)))
                         (define empty-one (make-table "n" (vector)))
                         (google-sheet creds "T" '() a b c empty-one)
                         (google-sheet creds "T" '() a b :names '("First" "Second"))""")
        first, second = [call for call in self.sheet_calls() if call[1] == self.google.SHEETS_URL]
        self.assertEqual([s["properties"]["title"] for s in first[3]["sheets"]], ["Sales", "sales 2", "O'Brien", "n"])
        self.assertEqual([s["properties"]["title"] for s in second[3]["sheets"]], ["First", "Second"])
        ranges = [d["range"] for call in self.sheet_calls() if "values:batchUpdate" in call[1] for d in call[3]["data"]]
        self.assertIn("'O''Brien'!A1", ranges)                                    # a quote in a name, doubled
        self.assertEqual(first[3]["sheets"][3]["properties"]["gridProperties"]["rowCount"], 2)     # (a table with no rows)
        self.assertLispError("(google-sheet creds \"T\" '() a b :names '(\"One\"))", ":names has 1 names, for 2 tables")
        self.assertLispError("(google-sheet creds \"T\" '() a b :names '(\"One\" \"one\"))", "must be different")
        self.assertLispError("(google-sheet creds \"T\" '() a :wide #t)", ":wide isn't an option")

    def test_formats_and_what_they_leave_out(self):
        self.save_a_sign_in()
        self.run_lisp("""(define t (make-table "id" (vector "a") "x" #(1.5) "y" #(2.5) "z" #(3.5)))""")
        self.run_lisp("""(google-sheet creds "T" '(("id" hide) ("y") ("z" ".1f")) t)""")
        values = [call for call in self.sheet_calls() if "values:batchUpdate" in call[1]][0][3]
        self.assertEqual(values["data"][0]["values"], [["x", "z"], [1.5, 3.5]])
        self.assertEqual(self.sheet_calls()[0][3]["sheets"][0]["properties"]["title"], "id")   # (still named for its first column)
        self.assertLispError("""(google-sheet creds "T" '(("id") ("x") ("y") ("z")) t)""", "every column")

    def test_number_formats(self):
        number_format = self.google.number_format
        for spec, expected in ((",.2f", ("NUMBER", "#,##0.00")), (".0f", ("NUMBER", "0")), ("f", ("NUMBER", "0.000000")),
                               (".3%", ("PERCENT", "0.000%")), (",.1%", ("PERCENT", "#,##0.0%")), (".0%", ("PERCENT", "0%")),
                               ("d", ("NUMBER", "0")), (",d", ("NUMBER", "#,##0")), (",", ("NUMBER", "#,##0")),
                               ("05d", ("NUMBER", "00000")), ("+.2f", ("NUMBER", "+0.00;-0.00")),
                               (">12.2f", ("NUMBER", "0.00")), ("12,.2f", ("NUMBER", "#,##0.00")),
                               (".2e", ("SCIENTIFIC", "0.00E+00")), ("n", ("NUMBER", "0"))):
            with self.subTest(spec=spec):
                self.assertEqual(number_format(spec, "c"), expected)
        for spec in (">12", "", "<20", "^8", "s", "10s", ".5s"):
            with self.subTest(spec=spec):
                self.assertIsNone(number_format(spec, "c"))                      # only the layout of text
        for spec in ("g", ".3g", "x", "b", "#x", "_d", "c", "o"):
            with self.subTest(spec=spec):
                with self.assertRaises(lisp_core.LispError) as caught:
                    number_format(spec, "c")
                self.assertIn("no spreadsheet equivalent", str(caught.exception))
        for spec, fragment in ((".2", "needs a type"), (".2d", "is a whole number"), ("zz", "isn't a format spec")):
            with self.subTest(spec=spec):
                with self.assertRaises(lisp_core.LispError) as caught:
                    number_format(spec, "c")
                self.assertIn(fragment, str(caught.exception))

    def test_mistakes_before_anything_is_made(self):
        self.save_a_sign_in()
        self.run_lisp("""(define t (make-table "name" (vector "a" "b") "x" #(1 2)))""")
        self.assertLispError("""(google-sheet creds "T" '(("name" ",.2f")) t)""", 'column name: the format ",.2f" is for numbers')
        self.assertLispError("""(google-sheet creds "T" '(("x" "g")) t)""", "column x: the format \"g\" has no spreadsheet")
        self.assertLispError("""(google-sheet creds "T" '())""", "at least one table")
        self.assertLispError("""(google-sheet creds "" '() t)""", "the title must be a string")
        self.assertLispError("""(google-sheet creds "T" 5 t)""", "the formats must be a list")
        self.assertLispError("""(google-sheet creds "T" '("x") t)""", "each format must be (name spec)")
        self.assertLispError("""(google-sheet creds "T" '() 5)""", "not a table")
        self.assertEqual(self.requests, [])                                       # nothing was sent to Google

    def test_a_failure_part_way_says_where_the_spreadsheet_is(self):
        self.save_a_sign_in()
        self.fail_on = "values:batchUpdate"
        self.assertLispError("""(google-sheet creds "T" '() (make-table "a" #(1)))""",
                             "oops -- the spreadsheet was made, at https://docs.google.com/spreadsheets/d/ID1/edit, but isn't finished")

    def test_google_s_errors_are_read(self):
        message = self.google.google_message
        self.assertEqual(message('{"error": {"code": 403, "message": "The caller does not have permission", '
                                 '"status": "PERMISSION_DENIED"}}'), "The caller does not have permission")
        self.assertEqual(message('{"error": "invalid_grant", "error_description": "Token has been revoked."}'),
                         "invalid_grant: Token has been revoked.")
        self.assertEqual(message("<html>Bad   gateway</html>"), "<html>Bad gateway</html>")

    def test_a_long_table_is_sent_in_pieces(self):
        pieces = self.google.requests_of_ranges
        tab = lambda rows, columns: (["h"] * columns, [[1] * rows] * columns, [None] * columns)
        with mock.patch.object(self.google, "CELLS_PER_REQUEST", 100):
            sent = pieces(["big", "small"], [tab(79, 2), tab(3, 2)])          # 80 rows of 2 cells, then 4 rows of 2
        self.assertEqual([[(d["range"], len(d["values"])) for d in request] for request in sent],
                         [[("'big'!A1", 50)], [("'big'!A51", 30), ("'small'!A1", 4)]])
        for request in sent:
            self.assertLessEqual(sum(len(d["values"]) * 2 for d in request), 100)


if __name__ == "__main__":
    unittest.main()


class TestNetworkErrorsOfTheOtherServices(LispTestCase):
    """Google, Schwab and tastytrade make their own requests: a site that can't be reached, or can't answer now, is a network error
    (see NETWORK in lisp_core.py) there too, and another problem is not. No request leaves this machine."""

    def http_error(self, status):
        return urllib.error.HTTPError("https://example.com", status, "status %d" % status, {}, io.BytesIO(b'{"error": "x"}'))

    def kinds(self, request):
        """The kind of error that request() raises for no connection, for HTTP 503, and for HTTP 401, when urlopen raises them."""
        found = []
        for failure in (urllib.error.URLError("no route to host"), self.http_error(503), self.http_error(401)):
            with mock.patch("urllib.request.urlopen", side_effect=failure):
                with self.assertRaises(lisp_core.LispError) as raised:
                    request()
            found.append(raised.exception.kind)
        return found

    def test_google_and_schwab(self):
        self.assertEqual(self.kinds(lambda: lisp_google.google_request("GET", "https://example.com", "google-sheet", {})),
                         ["network", "network", None])
        self.assertEqual(self.kinds(lambda: lisp_schwab.schwab_request("GET", "https://example.com", "schwab-quotes", {})),
                         ["network", "network", None])

    def test_tastytrade(self):
        def cannot_connect(coroutine):
            coroutine.close()                           # (it is never run)
            raise lisp_tastytrade.NETWORK_FAILURES[-1]("connection refused")
        with mock.patch.object(lisp_tastytrade, "_run_async", cannot_connect):
            with self.assertRaises(lisp_core.LispError) as raised:
                lisp_tastytrade._with_session("credentials.json", lambda session: None)
        self.assertEqual((str(raised.exception), raised.exception.kind), ("tastytrade: couldn't reach tastytrade: connection refused", "network"))

    def test_sofr_calibration_data(self):
        with mock.patch.object(lisp_rates, "_SOFR_MARKET_DATA_AVAILABLE", True), \
                mock.patch.object(lisp_rates, "_fetch_sofr_calibration_data", side_effect=TimeoutError("timed out"), create=True):
            self.assertShows('(catch-error (sofr-calibration-data "credentials.json" 4 2 2) (m) :only (network) m)',
                             '"sofr-calibration-data: couldn\'t reach tastytrade: timed out"')
