"""The data sources, each against a stand-in for its web API (the tests never use the
network): SEC, FDIC, Census, BLS, BEA, Schwab, tastytrade, FRED, Alpha Vantage, and
downloads from any web API.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


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
        if path == "/marketdata/v1/quotes":
            return 200, {}, {"AAPL": {"quote": {"bidPrice": 229.9, "askPrice": 230.1, "lastPrice": 230.0},
                                      "reference": {"description": "Apple Inc"}}}
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


if __name__ == "__main__":
    unittest.main()
