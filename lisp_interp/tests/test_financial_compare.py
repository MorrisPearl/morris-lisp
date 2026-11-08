"""compare-companies (lisp_financial_compare.py): made-up companies of one kind, the SEC and Google faked -- no
network. sheet_formulas.py works out the formulas of the sheets as Google would."""

import copy

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_financial_compare as fc
import lisp_financial_model as fm
import lisp_google
import lisp_sec
from sheet_formulas import Sheets
from test_financial_bank_insurer import bank_facts, insurer_facts
from test_financial_model import made_up_facts


def scaled(facts, factor, name, overrides=None, unit=None):
    """A copy of the facts with every amount (not shares) times `factor`, and some concepts times their own factor
    as well (overrides: concept -> factor), under another name; in another currency if `unit`."""
    facts = copy.deepcopy(facts)
    facts["entityName"] = name
    for concept, data in facts["facts"]["us-gaap"].items():
        if "USD" not in data["units"]:
            continue
        for fact in data["units"]["USD"]:
            fact["val"] = fact["val"] * factor * (overrides or {}).get(concept, 1.0)
        if unit:
            data["units"][unit] = data["units"].pop("USD")
    return facts


class CompareTestCase(LispTestCase):
    """compare-companies with these companies' facts and industries; the sheets it made are in self.written."""

    companies = {}                               # ticker -> (facts, (industry code, description))

    def setUp(self):
        super().setUp()
        self.written = []
        self.companies = {}
        for patcher in (mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: self.companies[str(company)][0]),
                        mock.patch.object(fm, "company_industry", lambda creds, company, who: self.companies[str(company)][1]),
                        mock.patch.object(lisp_google, "google_workbook",
                                          lambda creds, title, sheets: self.written.append((title, sheets)) or "https://sheet")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def add(self, ticker, facts, industry=(3571, "Electronic Computers")):
        self.companies[ticker] = (facts, industry)

    def compare(self, tickers, options=""):
        text = "(compare-companies creds '(%s) %s)" % (" ".join('"%s"' % t for t in tickers), options)
        return self.run_lisp(text)

    def worked(self):
        """The tabs made, as {name: cells}, and a calculator over them."""
        title, tabs = self.written[-1]
        return title, {tab["name"]: tab["cells"] for tab in tabs}, Sheets(tabs)

    def row(self, cells, label):
        """The index of the row with this label in column A."""
        for i, row in enumerate(cells):
            if row and row[0] and row[0][0] == label:
                return i
        raise AssertionError("no row called %s" % label)

    def number(self, sheets, tab, cells, label, column):
        return sheets.value(tab, self.row(cells[tab], label), column)


class TestSideBySide(CompareTestCase):

    def setUp(self):
        super().setUp()
        base = made_up_facts()
        self.add("AAA", scaled(base, 1.0, "Alpha Inc."))
        self.add("BBB", scaled(base, 10.0, "Beta Corp."))
        self.add("CCC", scaled(base, 3.0, "Gamma Ltd.", {"SellingGeneralAndAdministrativeExpense": 2.0}))

    def test_a_column_for_each_company_with_the_same_rows_and_the_amounts_in_millions(self):
        self.compare(["AAA", "BBB", "CCC"])
        title, tabs, sheets = self.worked()
        self.assertEqual(list(tabs), ["Comparison", "Notes"])
        cells = tabs["Comparison"]
        self.assertEqual([c[0] for c in cells[2][1:4]], ["Alpha Inc. (AAA)", "Beta Corp. (BBB)", "Gamma Ltd. (CCC)"])
        self.assertEqual([c[0] for c in cells[4][1:4]], ["FY2023, USD"] * 3)
        self.assertEqual(cells[3][1][0], datetime.date(2023, 12, 31))
        row = self.row(cells, "Revenue")
        for j, expected in zip((1, 2, 3), (1210.0, 12100.0, 3630.0)):
            self.assertAlmostEqual(cells[row][j][0], expected)
        self.assertEqual(len({len(r) for r in cells}), 1)                        # every row is as wide as the header
        self.assertEqual(title, "AAA, BBB, CCC compared (annual)")

    def test_a_number_is_blue_data_and_a_ratio_is_a_formula_that_works_out_the_same_for_a_company_of_any_size(self):
        self.compare(["AAA", "BBB", "CCC"])
        _, tabs, sheets = self.worked()
        cells = tabs["Comparison"]
        self.assertIn("data", cells[self.row(cells, "Revenue")][1][1])
        gross = self.row(cells, "Gross margin")
        self.assertTrue(cells[gross][1][0].startswith("=IFERROR("))
        self.assertEqual([round(sheets.value("Comparison", gross, j), 6) for j in (1, 2, 3)], [0.4, 0.4, 0.4])
        operating = self.row(cells, "Operating margin")
        for j in (2, 3):                                  # (a company of any size: the same margin)
            self.assertAlmostEqual(sheets.value("Comparison", operating, 1), sheets.value("Comparison", operating, j))

    def test_the_median_of_the_ratios_is_the_middle_company(self):
        self.compare(["AAA", "BBB", "CCC"])
        _, tabs, sheets = self.worked()
        cells = tabs["Comparison"]
        row = self.row(cells, "Operating margin")
        values = sorted(sheets.value("Comparison", row, j) for j in (1, 2, 3))
        self.assertAlmostEqual(sheets.value("Comparison", row, 4), values[1])
        self.assertEqual(cells[2][4][0], "Median")
        self.assertIsNone(cells[self.row(cells, "Revenue")][4])                  # (no median of amounts of different sizes)

    def test_without_a_basis_the_balance_sheet_balances_in_every_column(self):
        self.compare(["AAA", "BBB", "CCC"])
        _, tabs, sheets = self.worked()
        for j in (1, 2, 3):
            assets = self.number(sheets, "Comparison", tabs, "Total assets", j)
            liabilities = self.number(sheets, "Comparison", tabs, "Total liabilities", j)
            equity = self.number(sheets, "Comparison", tabs, "Stockholders' equity (with minority interests)", j)
            self.assertAlmostEqual(assets, liabilities + equity)

    def test_the_cash_flow_subtotals_are_the_companys(self):
        self.compare(["AAA"] + ["BBB"])
        _, tabs, sheets = self.worked()
        net_income = (200 * 1.21 - 12 - 40 * 1.21)
        self.assertAlmostEqual(self.number(sheets, "Comparison", tabs, "Cash from operations", 1), net_income + 40 * 1.21 + 15 * 1.21 - 25)
        self.assertAlmostEqual(self.number(sheets, "Comparison", tabs, "Cash from investing", 1), -60 * 1.21 - 15)
        self.assertAlmostEqual(self.number(sheets, "Comparison", tabs, "Cash from financing", 1), -85)

    def number(self, sheets, tab, tabs, label, column):
        return sheets.value(tab, self.row(tabs[tab], label), column)


class TestAsAPercentage(CompareTestCase):

    def setUp(self):
        super().setUp()
        base = made_up_facts()
        self.add("AAA", scaled(base, 1.0, "Alpha Inc."))
        self.add("BBB", scaled(base, 10.0, "Beta Corp."))
        self.add("CCC", scaled(base, 3.0, "Gamma Ltd.", {"SellingGeneralAndAdministrativeExpense": 2.0}))

    def figures(self, label, column, tab="Comparison"):
        _, tabs, sheets = self.worked()
        return sheets.value(tab, self.row(tabs[tab], label), column)

    def test_as_a_percentage_of_revenue_the_companies_of_any_size_are_the_same(self):
        self.compare(["AAA", "BBB", "CCC"], ':basis "revenue"')
        _, tabs, _ = self.worked()
        self.assertEqual(list(tabs), ["Comparison", "As reported", "Notes"])
        for j in (1, 2):
            self.assertAlmostEqual(self.figures("Revenue", j), 1.0)
            self.assertAlmostEqual(self.figures("Cost of revenue", j), 0.6)
            self.assertAlmostEqual(self.figures("Net income", j), (200 * 1.21 - 12 - 40 * 1.21) / 1210)
        self.assertAlmostEqual(self.figures("Selling, general and administrative", 3), 2 * 120 * 1.21 / 1210)
        self.assertAlmostEqual(self.figures("Selling, general and administrative", 4), 120 * 1.21 / 1210)       # (the median)

    def test_the_comparison_is_formulas_over_the_numbers_as_reported(self):
        self.compare(["AAA", "BBB"], ':basis "revenue"')
        _, tabs, _ = self.worked()
        row = self.row(tabs["Comparison"], "Cost of revenue")
        reported_row = self.row(tabs["As reported"], "Cost of revenue")
        self.assertEqual(tabs["Comparison"][row][1][0], "=IFERROR('As reported'!B%d/'As reported'!B$%d,\"\")"
                         % (reported_row + 1, self.row(tabs["As reported"], "Revenue") + 1))
        self.assertAlmostEqual(tabs["As reported"][reported_row][2][0], 7260.0)
        self.assertIn("percent", tabs["Comparison"][row][1][1])
        self.assertIn("data", tabs["As reported"][reported_row][2][1])

    def test_as_a_percentage_of_the_balance_sheet(self):
        self.compare(["AAA", "BBB", "CCC"], ':basis "assets"')
        assets = 1000 * 1.21 / 1.21                     # (placeholder, replaced below)
        total = self.figures("Total assets", 1)
        self.assertAlmostEqual(total, 1.0)
        self.assertAlmostEqual(self.figures("Total assets", 3), 1.0)
        reported = self.figures("Total assets", 1, "As reported")
        self.assertAlmostEqual(self.figures("Receivables", 2), 120 * 1.21 / reported)
        self.assertAlmostEqual(self.figures("Stockholders' equity (with minority interests)", 1), (350 + 80) / reported)

    def test_shares_and_earnings_per_share_are_not_scaled(self):
        self.compare(["AAA", "BBB"], ':basis "revenue"')
        self.assertAlmostEqual(self.figures("Diluted shares, millions", 1), 98.0)
        self.assertAlmostEqual(self.figures("Earnings per share, diluted", 1), (200 * 1.21 - 12 - 40 * 1.21) / 98)

    def test_the_ratios_are_the_same_with_or_without_a_basis(self):
        self.compare(["AAA", "CCC"], ':basis "revenue"')
        with_basis = (self.figures("Return on equity (a year's net income / equity)", 2),
                      self.figures("Current assets / current liabilities", 1))
        self.compare(["AAA", "CCC"])
        without = (self.figures("Return on equity (a year's net income / equity)", 2),
                   self.figures("Current assets / current liabilities", 1))
        self.assertEqual(with_basis, without)

    def test_the_notes_say_what_was_done(self):
        self.compare(["AAA", "BBB"], ':basis "revenue"')
        _, tabs, _ = self.worked()
        notes = "\n".join(row[0][0] for row in tabs["Notes"] if row and row[0])
        self.assertIn("Comparison is each amount divided by the company's revenue", notes)
        self.assertIn("Alpha Inc. (AAA): Electronic Computers, FY2023 ending 2023-12-31, in USD", notes)


class TestBanksAndInsurers(CompareTestCase):

    def test_banks_have_a_banks_rows_and_the_top_line_is_net_revenue(self):
        self.add("B1", scaled(bank_facts(), 1.0, "First Bank"), (6021, "National Commercial Banks"))
        self.add("B2", scaled(bank_facts(), 4.0, "Second Bank", {"NoninterestExpense": 1.5}), (6022, "State Commercial Banks"))
        self.compare(["B1", "B2"], ':basis "revenue"')
        _, tabs, sheets = self.worked()
        cells = tabs["Comparison"]
        self.assertEqual(sheets.value("Comparison", self.row(cells, "Net revenue (net interest income plus noninterest income)"), 1), 1.0)
        nii = self.row(cells, "Net interest income")
        self.assertAlmostEqual(sheets.value("Comparison", nii, 1), 68 / (68 + 48))
        efficiency = self.row(cells, "Efficiency ratio (noninterest expense / net revenue)")
        self.assertAlmostEqual(sheets.value("Comparison", efficiency, 1), 80 / 116)
        self.assertAlmostEqual(sheets.value("Comparison", efficiency, 2), 1.5 * 80 / 116)

    def test_banks_balance_sheet_as_a_percentage_of_assets(self):
        self.add("B1", scaled(bank_facts(), 1.0, "First Bank"), (6021, "National Commercial Banks"))
        self.add("B2", scaled(bank_facts(), 4.0, "Second Bank"), (6022, "State Commercial Banks"))
        self.compare(["B1", "B2"], ':basis "assets"')
        _, tabs, sheets = self.worked()
        cells = tabs["Comparison"]
        deposits = sheets.value("Comparison", self.row(cells, "Deposits"), 1)
        self.assertAlmostEqual(deposits, 1740 / sheets.value("As reported", self.row(tabs["As reported"], "Total assets"), 1))
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Loans / deposits"), 2), 1200 / 1740)

    def test_insurers_have_an_insurers_rows(self):
        self.add("I1", scaled(insurer_facts(), 1.0, "First Mutual"), (6331, "Fire, Marine & Casualty Insurance"))
        self.add("I2", scaled(insurer_facts(), 2.0, "Second Mutual", {"PolicyholderBenefitsAndClaimsIncurredNet": 1.2}),
                 (6331, "Fire, Marine & Casualty Insurance"))
        self.compare(["I1", "I2"], ':basis "revenue"')
        _, tabs, sheets = self.worked()
        cells = tabs["Comparison"]
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Combined ratio (under 100% is an underwriting profit)"), 1), 0.95)
        # (more losses and the same profit: the other expenses are what is left, so the combined ratio is the same)
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Loss ratio (losses / premiums earned)"), 2), 0.65 * 1.2)
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Combined ratio (under 100% is an underwriting profit)"), 2), 0.95)
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Total revenues"), 2), 1.0)
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Premiums earned"), 1),
                               1200 / (1200 + 96 + 5 + 20))

    def test_companies_of_different_kinds_are_an_error_unless_compared_as_ordinary_companies(self):
        self.add("B1", bank_facts(), (6021, "National Commercial Banks"))
        self.add("I1", insurer_facts(), (6331, "Fire, Marine & Casualty Insurance"))
        self.assertLispError("(compare-companies creds '(\"B1\" \"I1\"))", "not all of one kind (B1: bank, I1: insurer)")
        self.compare(["B1", "I1"], ':kind "general" :basis "assets"')
        _, tabs, _ = self.worked()
        self.assertIn("Gross profit", [row[0][0] for row in tabs["Comparison"] if row and row[0]])


class TestWhatCannotBeCompared(CompareTestCase):

    def test_a_company_without_the_lines_of_its_kind_is_named_with_what_to_do(self):
        self.add("B1", bank_facts(), (6021, "National Commercial Banks"))
        self.add("B2", made_up_facts(), (6021, "National Commercial Banks"))               # (a "bank" without a bank's lines)
        self.assertLispError("(compare-companies creds '(\"B1\" \"B2\"))", "B2: a model of a bank needs")
        self.assertLispError("(compare-companies creds '(\"B1\" \"B2\"))", 'with :kind "general"')

    def test_different_currencies_cannot_be_compared_as_they_are(self):
        base = made_up_facts()
        self.add("AAA", scaled(base, 1.0, "Alpha Inc."))
        self.add("EUR", scaled(base, 2.0, "Euro SA", unit="EUR"))
        self.assertLispError("(compare-companies creds '(\"AAA\" \"EUR\"))", "different currencies (EUR, USD)")
        self.compare(["AAA", "EUR"], ':basis "revenue"')
        _, tabs, _ = self.worked()
        self.assertEqual(tabs["Comparison"][4][2][0], "FY2023, EUR")

    def test_bad_arguments_are_errors(self):
        base = made_up_facts()
        self.add("AAA", scaled(base, 1.0, "Alpha Inc."))
        self.add("BBB", scaled(base, 2.0, "Beta Corp."))
        self.assertLispError("(compare-companies creds '(\"AAA\"))", "at least two companies")
        self.assertLispError("(compare-companies creds '(\"AAA\" \"aaa\"))", "given twice")
        self.assertLispError("(compare-companies creds '(\"AAA\" \"BBB\") :basis \"size\")", ':basis is "none", "revenue", or "assets"')
        self.assertLispError("(compare-companies creds '(\"AAA\" \"BBB\") :period \"daily\")", ':period is "annual" or "quarterly"')
        self.assertLispError("(compare-companies creds '(\"AAA\" \"BBB\") :kind \"airline\")", ':kind is "auto"')
        self.assertLispError("(compare-companies creds '(\"AAA\" \"BBB\") :years 3)", ":years isn't an option")
        self.assertLispError("(compare-companies creds 5)", "must be a string or a list of strings")


class TestQuarterly(CompareTestCase):

    def test_the_latest_quarter_with_a_years_flows_in_the_ratios(self):
        base = made_up_facts(quarterly=True)
        self.add("AAA", scaled(base, 1.0, "Alpha Inc."))
        self.add("BBB", scaled(base, 5.0, "Beta Corp."))
        self.compare(["AAA", "BBB"], ':period "quarterly"')
        title, tabs, sheets = self.worked()
        cells = tabs["Comparison"]
        self.assertEqual(cells[4][1][0], "Q4 FY2023, USD")
        self.assertEqual(sheets.value("Comparison", self.row(cells, "Days in the period"), 1), 92.0)       # Oct 1 - Dec 31
        net_income = 0.28 * (200 * 1.21 - 12 - 40 * 1.21)
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Net income"), 1), net_income)
        assets = sheets.value("Comparison", self.row(cells, "Total assets"), 1)
        self.assertAlmostEqual(sheets.value("Comparison", self.row(cells, "Return on assets (a year's net income / assets)"), 1),
                               net_income * 365 / 92 / assets)
        self.assertIn("(a quarter's times 365 over its days)", "\n".join(row[0][0] for row in tabs["Notes"] if row and row[0]))
