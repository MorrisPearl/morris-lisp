"""Loans by type from the FDIC (lisp_fdic.py: a holding company's banks, the LoanBook, fdic-loan-losses) and the bank
model's Credit Losses and FDIC Call Reports tabs (lisp_financial_credit.py), with a fake FDIC -- no network.

The fake FDIC has a holding company, ABC BCORP, with two banks (the second half the first's size), each filing a Call
Report every quarter since 1999: every type of loan grows 2% a year, and loses its own rate a year of the loans at the
end of the year before (three times as much in 2009); a quarter's year-to-date charge-offs are that quarter's share of
the year's. The latest report is June 30, 2026, so a period is the 12 months to June 30.
"""

from support import *  # noqa: F401,F403 -- the interpreter's modules, mock, and LispTestCase

import datetime
import lisp_fdic
import lisp_financial_credit as credit
import lisp_financial_model as fm
import lisp_google
import lisp_sec
from sheet_formulas import Sheets
from test_financial_bank_insurer import ModelTestCase, bank_facts, YEARS
from test_financial_model import set_input


# a type's loans in 2000, in thousands of dollars, and its loss rate in an ordinary year
BASE_LOANS = {"LNRERES": 400000, "LNREMULT": 60000, "LNRECONS": 30000, "LNRENRES": 150000, "LNREAG": 5000,
              "LNCI": 200000, "LNCRCD": 50000, "LNAUTO": 40000, "LNCONOTH": 20000, "LNAG": 8000, "LNOTHER": 30000,
              "LS": 7000}
LOSS_RATES = {"LNRERES": 0.002, "LNREMULT": 0.001, "LNRECONS": 0.004, "LNRENRES": 0.003, "LNREAG": 0.0,
              "LNCI": 0.005, "LNCRCD": 0.04, "LNAUTO": 0.008, "LNCONOTH": 0.012, "LNAG": 0.003, "LNOTHER": 0.002,
              "LS": 0.001}
EVERYTHING_ELSE = 25000                 # (loans of no type, in 2000; they lose nothing)
CRISIS = {2009: 3.0}
NAME_OF = {t[2]: t for t in lisp_fdic.LOAN_TYPES}
LATEST = "20260630"


def quarter_ends():
    dates = []
    for year in range(1999, 2027):
        for month_day in ("0331", "0630", "0930", "1231"):
            date = "%d%s" % (year, month_day)
            if date <= LATEST:
                dates.append(date)
    return dates


def loans_at(field, date, scale):
    """A type's loans (thousands) at the end of a quarter: 2% more a year, from 2000."""
    years = int(date[:4]) - 2000 + (int(date[4:6]) / 12)
    return BASE_LOANS[field] * scale * 1.02 ** years


def year_losses(field, year, scale):
    """A type's net charge-offs in a calendar year: its rate (more in a crisis) times the loans at the end of the year before."""
    return LOSS_RATES[field] * CRISIS.get(year, 1.0) * loans_at(field, "%d1231" % (year - 1), scale)


def report(date, scale):
    """One Call Report, as the FDIC's API gives it (thousands of dollars)."""
    quarter = int(date[4:6]) // 3
    record = {"REPDTE": date, "NAME": "ABC Bank"}
    total_loans = total_losses = total_noncurrent = 0.0
    for field, kind in NAME_OF.items():
        _, _, balance_field, charge_off_field, noncurrent_field, _ = kind
        balance = loans_at(field, date, scale)
        to_date = year_losses(field, int(date[:4]), scale) * quarter / 4
        record[balance_field], record[charge_off_field], record[noncurrent_field] = balance, to_date, 0.01 * balance
        total_loans += balance
        total_losses += to_date
        total_noncurrent += 0.01 * balance
    record["LNLSGR"] = total_loans + EVERYTHING_ELSE * scale
    record["NTLNLS"] = total_losses
    record["NCLNLS"] = total_noncurrent
    record["RBCT1"] = 130000.0 * scale          # (tier 1 and total capital in every report, as the FDIC has them)
    record["RBC"] = 150000.0 * scale
    if date >= "20150331":                     # (common equity tier 1 since 2015)
        record["RBCT1C"] = 120000.0 * scale
        record["RWAJ"] = 1000000.0 * scale
    # funding, securities, the allowance, and commercial real estate (see the FUNDING... constants)
    record["ASSET"] = ASSETS_TO_LOANS * record["LNLSGR"]
    record["DEP"] = DEPOSITS_TO_LOANS * record["LNLSGR"]
    record["DEPNIDOM"] = NONINTEREST_SHARE * record["DEP"]
    record["DEPUNINS"] = UNINSURED_SHARE * record["DEP"]
    record["BRO"] = BROKERED_SHARE * record["DEP"]
    record["OTHBFHLB"] = HOME_LOAN_BANK_SHARE * record["ASSET"]
    record["SCAA"], record["SCAF"] = 200000.0 * scale, 200000.0 * scale * (1 + AVAILABLE_FOR_SALE_GAIN)
    record["SCHA"], record["SCHF"] = 100000.0 * scale, 100000.0 * scale * (1 + HELD_TO_MATURITY_GAIN)
    record["LNATRES"] = ALLOWANCE_SHARE * record["LNLSGR"]
    if date >= "20070331":
        record["LNRENROT"] = NOT_OWNER_OCCUPIED * record["LNRENRES"]
        record["LNCOMRE"] = 10000.0 * scale
    return record


ASSETS_TO_LOANS, DEPOSITS_TO_LOANS = 1.5, 1.2
NONINTEREST_SHARE, UNINSURED_SHARE, BROKERED_SHARE, HOME_LOAN_BANK_SHARE = 0.25, 0.6, 0.05, 0.02
AVAILABLE_FOR_SALE_GAIN, HELD_TO_MATURITY_GAIN = -0.10, -0.15        # (what the securities are worth, over their cost, less 1)
ALLOWANCE_SHARE = 0.012
NOT_OWNER_OCCUPIED = 0.6                # (of the nonfarm nonresidential loans)


INSTITUTIONS = [
    {"CERT": 1, "NAME": "ABC Bank, National Association", "NAMEHCR": "ABC BCORP", "RSSDHCR": 99, "ASSET": 2000000},
    {"CERT": 2, "NAME": "ABC Bank West", "NAMEHCR": "ABC BCORP", "RSSDHCR": 99, "ASSET": 1000000},
    {"CERT": 3, "NAME": "ABC Bank of Smalltown", "NAMEHCR": "A.B.C. BANCORP", "RSSDHCR": 7, "ASSET": 5000},
    {"CERT": 4, "NAME": "Zed Bancorporation, N.A.", "NAMEHCR": None, "RSSDHCR": None, "ASSET": 800000},
    {"CERT": 5, "NAME": "Other Bank", "NAMEHCR": "OTHER HOLDINGS INC", "RSSDHCR": 5, "ASSET": 900000},
]
SCALE = {1: 1.0, 2: 0.5, 3: 0.001, 4: 0.4, 5: 0.3}


def fake_records(credentials_path, dataset, params, who):
    """lisp_fdic.fdic_records, from the fake FDIC."""
    if dataset == "institutions":
        return [dict(bank) for bank in INSTITUTIONS]
    cert = int(params["filters"].split(":")[1])
    if cert not in SCALE:
        return []
    return [report(date, SCALE[cert]) for date in reversed(quarter_ends())]


class FakeFdic(LispTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(lisp_fdic, "fdic_records", fake_records)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def book(self):
        return lisp_fdic.loan_book("creds.json", [(1, "ABC Bank"), (2, "ABC Bank West")], "test")


# ---------------------------------------------------------------------------
# Names, and a holding company's banks
# ---------------------------------------------------------------------------

class TestNames(unittest.TestCase):

    def test_the_secs_names_and_the_fdics_are_the_same_once_their_words_are(self):
        for sec, fdic in (("US BANCORP \\DE\\", "U S BCORP"), ("WELLS FARGO & COMPANY/MN", "WELLS FARGO&COMPANY"),
                          ("HUNTINGTON BANCSHARES INC /MD/", "HUNTINGTON BANCSHARES INC"),
                          ("SCHWAB CHARLES CORP", "CHARLES SCHWAB CORP THE"), ("FNB CORP/PA/", "F N B CORP"),
                          ("ZIONS BANCORPORATION, NATIONAL ASSOCIATION /UT/", "Zions Bancorporation, N.A."),
                          ("PNC FINANCIAL SERVICES GROUP, INC.", "PNC FINL SERVICES GROUP INC"),
                          ("KEYCORP /NEW/", "KEYCORP"), ("M&T BANK CORP", "M&T BANK CORP"),
                          ("JPMorgan Chase & Co.", "JPMORGAN CHASE&CO")):
            self.assertEqual(lisp_fdic.name_key(sec), lisp_fdic.name_key(fdic), sec)

    def test_different_companies_have_different_keys(self):
        for first, second in (("FIFTH THIRD BANCORP", "FIRST HORIZON CORP"), ("CITIZENS FINANCIAL GROUP", "CITIGROUP INC"),
                              ("BANK OF AMERICA CORP", "BANK OF HAWAII CORP")):
            self.assertNotEqual(lisp_fdic.name_key(first), lisp_fdic.name_key(second))


class TestBanksOfACompany(FakeFdic):

    def test_a_holding_companys_banks_largest_first_and_the_larger_of_two_holding_companies_with_one_name(self):
        # (A.B.C. BANCORP's key is ABC BCORP's too, but it is much smaller)
        self.assertEqual(lisp_fdic.banks_of_company("creds.json", "ABC BANCORP /DE/", "test"),
                         [(1, "ABC Bank, National Association"), (2, "ABC Bank West")])

    def test_a_bank_with_no_holding_company_by_its_own_name(self):
        self.assertEqual(lisp_fdic.banks_of_company("creds.json", "ZED BANCORPORATION, NATIONAL ASSOCIATION /UT/", "test"),
                         [(4, "Zed Bancorporation, N.A.")])

    def test_nothing_for_a_company_the_fdic_does_not_know(self):
        self.assertEqual(lisp_fdic.banks_of_company("creds.json", "NOBODY FINANCIAL CORP", "test"), [])

    def test_banks_can_be_given_by_certificate_number_or_a_list_of_them(self):
        self.assertEqual(lisp_fdic.banks_given("creds.json", 5, "test"), [(5, "certificate 5")])
        two = lisp_core.list_to_pairs([1, 2])
        self.assertEqual([cert for cert, _ in lisp_fdic.banks_given("creds.json", two, "test")], [1, 2])


# ---------------------------------------------------------------------------
# The loan book
# ---------------------------------------------------------------------------

class TestTheLoanBook(FakeFdic):

    def setUp(self):
        super().setUp()
        self.loans = self.book()

    def test_the_periods_are_the_12_months_to_the_latest_reports_day_each_year(self):
        self.assertEqual(self.loans.latest, LATEST)
        self.assertEqual(self.loans.period_ends[0], "20000630")
        self.assertEqual(self.loans.period_ends[-1], LATEST)
        self.assertEqual(len(self.loans.period_ends), 27)
        self.assertEqual(self.loans.bank_names(), "ABC Bank (1); ABC Bank (2)")

    def test_the_banks_are_added_up_in_dollars(self):
        self.assertAlmostEqual(self.loans.balance("commercial", LATEST), loans_at("LNCI", LATEST, 1.5) * 1000, delta=1e-3)
        self.assertAlmostEqual(self.loans.noncurrent("credit-cards", LATEST), 0.01 * loans_at("LNCRCD", LATEST, 1.5) * 1000,
                               delta=1e-3)

    def test_12_months_of_charge_offs_are_this_years_to_date_and_the_rest_of_last_years(self):
        expected = (year_losses("LNCRCD", 2026, 1.5) / 2 + year_losses("LNCRCD", 2025, 1.5) / 2) * 1000
        self.assertAlmostEqual(self.loans.charge_offs("credit-cards", LATEST), expected, delta=1e-3)
        self.assertAlmostEqual(self.loans.charge_offs("credit-cards", "20251231"), year_losses("LNCRCD", 2025, 1.5) * 1000,
                               delta=1e-3)

    def test_everything_else_is_what_the_types_leave_of_all_loans(self):
        self.assertAlmostEqual(self.loans.balance("everything-else", LATEST), EVERYTHING_ELSE * 1.5 * 1000, delta=1e-3)
        self.assertAlmostEqual(self.loans.charge_offs("everything-else", LATEST), 0, places=3)

    def test_a_loss_rate_is_the_charge_offs_over_the_loans_a_year_before(self):
        rates = self.loans.loss_rates("credit-cards")
        self.assertEqual(len(rates), 26)
        expected = (year_losses("LNCRCD", 2026, 1) + year_losses("LNCRCD", 2025, 1)) / 2 / loans_at("LNCRCD", "20250630", 1)
        self.assertAlmostEqual(rates[-1], expected)
        worst = max(rates)
        self.assertGreater(worst, 2 * rates[-1])                       # (the 12 months to June 2009 and 2010 have half the crisis each)

    def test_the_capital_is_there_since_2015(self):
        self.assertEqual(self.loans.capital(LATEST), (180000.0 * 1000, 1500000.0 * 1000))
        self.assertEqual(self.loans.capital("20100630"), (None, None))


class TestYearsLeftOut(unittest.TestCase):
    """A year in which a type's loans more than doubled (a purchase), or in which it was under 1% of all loans, has no loss rate."""

    def setUp(self):
        def report(total, commercial, commercial_lost, cards, cards_lost):
            return {"LNLSGR": total, "LNCI": commercial, "NTCI": commercial_lost, "LNCRCD": cards, "NTCRCD": cards_lost}
        self.book = lisp_fdic.LoanBook([(1, "A bank")], {
            "20231231": report(1000.0, 400.0, 0.0, 5.0, 0.0),
            "20241231": report(1100.0, 420.0, 4.0, 60.0, 2.0),           # (cards were 0.5% of the loans at the start)
            "20251231": report(1600.0, 900.0, 90.0, 70.0, 3.5),          # (commercial loans more than doubled)
        })

    def test_the_rates_left_out(self):
        self.assertEqual(self.book.loss_rates("commercial"), [4.0 / 400.0, None])
        self.assertEqual(self.book.loss_rates("credit-cards"), [None, 3.5 / 60.0])

    def test_the_sheets_formulas_leave_out_the_same(self):
        model = fm.build_model(bank_facts(), "ABC", "annual", 3, 3, "test", None, "bank",
                               find_loan_book=lambda name: (self.book, ""))
        tab = credit.FdicTab(self.book, model)
        sheets = Sheets([tab.sheet()])
        for key, expected in (("commercial", [4.0 / 400.0, ""]), ("credit-cards", ["", 3.5 / 60.0])):
            row = tab.row_of[("rates", key)]
            found = [sheets.value(credit.FDIC_TAB, row - 1, column) for column in (2, 3)]
            self.assertEqual([round(v, 12) if isinstance(v, float) else v for v in found],
                             [round(v, 12) if isinstance(v, float) else v for v in expected], key)


class TestFdicLoanLosses(FakeFdic):

    def test_the_table_has_a_row_for_each_type_and_all_loans(self):
        table = self.run_lisp('(fdic-loan-losses creds "ABC BANCORP")')
        types = [str(x) for x in self.run_lisp('(table-column (fdic-loan-losses creds "ABC BANCORP") "type")').items]
        self.assertEqual(len(types), len(lisp_fdic.LOAN_TYPES) + 2)
        self.assertEqual(types[-1], "All loans")
        shares = self.run_lisp('(table-column (fdic-loan-losses creds 1) "share")').items.tolist()
        self.assertAlmostEqual(shares[-1], 1.0)
        self.assertAlmostEqual(sum(shares[:-1]), 1.0)
        self.assertIsNotNone(table)

    def test_a_types_losses_last_year_and_its_worst(self):
        row = self.run_lisp('(table-column (fdic-loan-losses creds 1) "losses-last-year")').items.tolist()
        cards = next(n for n, t in enumerate(lisp_fdic.LOAN_TYPES) if t[0] == "credit-cards")
        expected = (year_losses("LNCRCD", 2026, 1) + year_losses("LNCRCD", 2025, 1)) / 2 / loans_at("LNCRCD", "20250630", 1)
        self.assertAlmostEqual(row[cards], expected)
        worst = self.run_lisp('(table-column (fdic-loan-losses creds 1) "losses-worst-year")').items.tolist()
        self.assertGreater(worst[cards], 0.05)


# ---------------------------------------------------------------------------
# The bank model with the FDIC's loans
# ---------------------------------------------------------------------------

def build_with_loans(book, period="annual", history=3, forecast=4, facts=None):
    return fm.build_model(facts or bank_facts(), "ABC", period, history, forecast, "test", None, "bank",
                          find_loan_book=lambda name: (book, ""))


class TestTheCreditTabs(ModelTestCase):

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(lisp_fdic, "fdic_records", fake_records)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.book = lisp_fdic.loan_book("creds.json", [(1, "ABC Bank"), (2, "ABC Bank West")], "test")
        self.use(build_with_loans(self.book))
        self.tabs = self.model.sheets()
        self.credit = next(tab for tab in self.tabs if tab["name"] == credit.CREDIT)

    def choose(self, scenario):
        row = next(n for n, cells in enumerate(self.credit["cells"]) if cells[0] and str(cells[0][0]).startswith("Scenario in"))
        self.sheets.cells[credit.CREDIT][(row, 1)] = scenario
        self.sheets.worked_out.clear()

    def named(self, name):
        tab, address = self.sheets.names[name]
        return self.sheets.at(tab, address)

    def test_the_tabs_come_after_the_cash_flow_and_before_the_notes(self):
        self.assertEqual([tab["name"] for tab in self.tabs],
                         ["Assumptions", "Income Statement", "Balance Sheet", "Cash Flow", "Valuation", "Sensitivity",
                          "Distributions", "Sensitivity Macro", "Credit Losses", "FDIC Call Reports", "Notes"])

    def test_every_formula_on_every_tab_works_out_in_every_scenario(self):
        for scenario in credit.SCENARIOS:
            self.choose(scenario)
            for tab in self.tabs:
                for (row, column) in list(self.sheets.cells[tab["name"]]):
                    self.sheets.value(tab["name"], row, column)
            self.assertBalances(7)

    def test_the_fdic_tab_has_the_banks_loans_and_the_rates_are_formulas_of_them(self):
        fdic = credit.FdicTab(self.book, self.model)
        cards = fdic.row_of[("rates", "credit-cards")]
        last = len(self.book.period_ends)
        formula = self.sheets.cells[credit.FDIC_TAB][(cards - 1, last)]
        self.assertTrue(formula.startswith("=IF(") and "IFERROR(" in formula, formula)
        self.assertAlmostEqual(self.sheets.value(credit.FDIC_TAB, cards - 1, last), self.book.loss_rates("credit-cards")[-1])
        loans = fdic.row_of[("loans", "total")]
        self.assertAlmostEqual(self.sheets.value(credit.FDIC_TAB, loans - 1, last), self.book.balance("total", LATEST) / 1e6)

    def test_the_period_ends_reach_google_as_dates(self):
        fdic = credit.FdicTab(self.book, self.model).sheet()
        header = fdic["cells"][3]
        self.assertEqual(header[0][0], "12 months to")
        for (value, styles), end in zip(header[1:], self.book.period_ends):
            cell = lisp_google.api_cell(value, styles)
            day = lisp_google.SHEETS_EPOCH + datetime.timedelta(days=cell["userEnteredValue"]["numberValue"])
            self.assertEqual(day, lisp_fdic.report_date(end).date)
            self.assertEqual(cell["userEnteredFormat"]["numberFormat"]["type"], "DATE")

    def fdic_value(self, section, key, period=None):
        fdic = credit.FdicTab(self.book, self.model)
        period = len(self.book.period_ends) - 1 if period is None else period
        return self.sheets.at(credit.FDIC_TAB, fdic.address(section, key, period))

    def test_the_funding_ratios_are_formulas_of_the_call_reports(self):
        self.assertAlmostEqual(self.fdic_value("funding", "uninsured-share"), UNINSURED_SHARE)
        self.assertAlmostEqual(self.fdic_value("funding", "noninterest-share"), NONINTEREST_SHARE)
        self.assertAlmostEqual(self.fdic_value("funding", "brokered-share"), BROKERED_SHARE)
        self.assertAlmostEqual(self.fdic_value("funding", "home-loan-bank-share"), HOME_LOAN_BANK_SHARE)
        self.assertAlmostEqual(self.fdic_value("funding", "loans-to-deposits"), 1 / DEPOSITS_TO_LOANS)
        self.assertAlmostEqual(self.fdic_value("funding", "deposits"), self.book.reported("deposits", LATEST) / 1e6)

    def test_the_securities_losses_and_the_capital_ratio_counting_them(self):
        scale = 1.5                                         # (banks 1 and 2)
        available, held = 200 * scale * AVAILABLE_FOR_SALE_GAIN, 100 * scale * HELD_TO_MATURITY_GAIN
        capital, risk_weighted = 120 * scale, 1000 * scale
        self.assertAlmostEqual(self.fdic_value("securities", "available-for-sale-gain"), available)
        self.assertAlmostEqual(self.fdic_value("securities", "held-to-maturity-gain"), held)
        self.assertAlmostEqual(self.fdic_value("securities", "gain-to-capital"), (available + held) / capital)
        self.assertAlmostEqual(self.fdic_value("securities", "ratio-with-held-to-maturity"), (capital + held) / risk_weighted)
        self.assertAlmostEqual(self.fdic_value("securities", "ratio-with-all"), (capital + held + available) / risk_weighted)

    def test_the_allowance_and_its_coverage_of_the_noncurrent_loans(self):
        self.assertAlmostEqual(self.fdic_value("allowance", "to-loans"), ALLOWANCE_SHARE)
        noncurrent = self.book.noncurrent("total", LATEST)
        self.assertAlmostEqual(self.fdic_value("allowance", "to-noncurrent"),
                               ALLOWANCE_SHARE * self.book.balance("total", LATEST) / noncurrent)

    def test_commercial_real_estate_as_the_guidance_counts_it(self):
        b = lambda key: self.book.balance(key, LATEST)
        real_estate = (b("construction") + b("multifamily") + NOT_OWNER_OCCUPIED * b("commercial-real-estate")
                       + 10000 * 1000 * 1.5)
        total_capital = 150 * 1.5 * 1e6
        self.assertAlmostEqual(self.fdic_value("real-estate", "total"), real_estate / 1e6)
        self.assertAlmostEqual(self.fdic_value("real-estate", "to-capital"), real_estate / total_capital)
        self.assertAlmostEqual(self.fdic_value("real-estate", "construction-to-capital"), b("construction") / total_capital)
        three_years_before = self.book.period_ends[-4]
        before = (self.book.balance("construction", three_years_before) + self.book.balance("multifamily", three_years_before)
                  + NOT_OWNER_OCCUPIED * self.book.balance("commercial-real-estate", three_years_before) + 10000 * 1000 * 1.5)
        self.assertAlmostEqual(self.fdic_value("real-estate", "growth"), real_estate / before - 1)

    def test_commercial_real_estate_is_empty_before_the_call_report_said_who_occupies_it(self):
        year_2006 = self.book.period_ends.index("20060630")
        self.assertEqual(self.fdic_value("real-estate", "total", year_2006), "")
        self.assertEqual(self.fdic_value("real-estate", "to-capital", year_2006), "")      # (not 0%, as Sheets would say)
        self.assertEqual(self.fdic_value("real-estate", "growth", self.book.period_ends.index("20090630")), "")

    def warning_signs(self):
        """{measure: (the banks' value, the guide, past it?)} of the Credit Losses tab's last table."""
        cells = self.credit["cells"]
        start = next(r for r, row in enumerate(cells) if row[0] and str(row[0][0]).startswith("Concentration, reserves"))
        signs = {}
        for r in range(start + 2, start + 2 + len(credit.CreditTab.WARNING_SIGNS)):
            signs[cells[r][0][0]] = tuple(self.sheets.value(credit.CREDIT, r, c) for c in (1, 2, 3))
        return signs

    def test_the_warning_signs_flag_what_is_past_its_guide(self):
        signs = self.warning_signs()
        self.assertEqual(len(signs), len(credit.CreditTab.WARNING_SIGNS))
        value, guide, flag = signs["Uninsured deposits, % of deposits"]
        self.assertAlmostEqual(value, UNINSURED_SHARE)
        self.assertEqual((guide, flag), (0.5, "Yes"))
        value, guide, flag = signs["Commercial real estate, % of total risk-based capital"]
        self.assertAlmostEqual(value, self.fdic_value("real-estate", "to-capital"))
        self.assertEqual(flag, "" if value <= 3 else "Yes")
        self.assertEqual(signs["Brokered deposits, % of deposits"][2], "")
        self.assertEqual(signs["Deposits that pay no interest, % of deposits"][1:], (0, 0))      # (no guide)

    def test_the_base_loss_rate_is_the_average_of_the_last_five_years_weighted_by_todays_loans(self):
        total = self.book.balance("total", LATEST)
        expected = 0.0
        for key in self.book.keys:
            recent = [rate for rate in self.book.loss_rates(key)[-5:] if rate is not None]
            average = max(sum(recent) / len(recent), 0) if recent else 0.0
            expected += self.book.balance(key, LATEST) / total * average
        self.assertAlmostEqual(self.named("base_loss_rate"), expected, places=9)

    def test_a_worse_scenario_has_more_defaults_and_less_recovered(self):
        base, adverse, severe = (self.named(name) for name in ("base_loss_rate", "adverse_loss_rate", "severe_loss_rate"))
        self.assertLess(base, adverse)
        self.assertLess(adverse, severe)
        cards = 0.04
        self.assertGreater(severe, 2 * base)
        self.assertLess(severe, 10 * cards)

    def test_the_forecasts_charge_offs_follow_the_scenario_for_the_periods_of_stress_then_the_base(self):
        base = self.named("base_loss_rate")
        for i in range(3, 7):
            self.assertAlmostEqual(self.v("Assumptions", "charge-off-rate", i), base)
        self.choose("Severe")
        severe = self.named("severe_loss_rate")
        self.assertEqual([round(self.v("Assumptions", "charge-off-rate", i), 12) for i in range(3, 7)],
                         [round(severe, 12)] * 2 + [round(base, 12)] * 2)
        self.assertAlmostEqual(self.named("chosen_loss_rate"), severe)

    def test_a_worse_scenario_costs_its_extra_charge_offs_after_tax_in_net_income(self):
        base_income = self.v("Income Statement", "net-income", 3)
        base_charge_offs = self.v("Income Statement", "net-charge-offs", 3)
        self.choose("Adverse")
        extra = self.v("Income Statement", "net-charge-offs", 3) - base_charge_offs
        self.assertGreater(extra, 0)
        tax = self.v("Assumptions", "tax-rate", 3)
        self.assertAlmostEqual(base_income - self.v("Income Statement", "net-income", 3), extra * (1 - tax), places=6)
        self.assertAlmostEqual(self.v("Income Statement", "provision", 3),
                               self.v("Income Statement", "net-charge-offs", 3) + self.v("Balance Sheet", "allowance", 3)
                               - self.v("Balance Sheet", "allowance", 2))

    def test_the_capital_ratio_is_the_banks_then_grows_with_the_equity_and_the_loans(self):
        for i, year in enumerate(YEARS):
            self.assertAlmostEqual(self.v("Balance Sheet", "capital-ratio", i), 0.12)
        last = len(YEARS) - 1
        for i in range(3, 7):
            equity_growth = self.v("Balance Sheet", "equity", i) - self.v("Balance Sheet", "equity", last)
            loans_growth = self.v("Balance Sheet", "loans", i) / self.v("Balance Sheet", "loans", last)
            expected = (180000 / 1000 + equity_growth) / (1500000 / 1000 * loans_growth)
            self.assertAlmostEqual(self.v("Balance Sheet", "capital-ratio", i), expected)
        # (the made-up bank pays out more than it earns, which a year of losses would stop: no payouts, to compare)
        for key in ("dividend-payout", "buyback-payout"):
            set_input(self.sheets, self.model, "Assumptions", key, 3, 0.0)
        base_ratio = self.v("Balance Sheet", "capital-ratio", 4)
        self.choose("Severe")
        self.assertLess(self.v("Balance Sheet", "capital-ratio", 4), base_ratio)

    def test_the_table_of_what_each_scenario_costs(self):
        rows = self.credit["cells"]
        start = next(n for n, cells in enumerate(rows) if cells[0] and str(cells[0][0]).startswith("What each scenario costs"))
        labels = [rows[n][0][0] for n in range(start + 2, start + 7)]
        self.assertEqual(labels[0], "Losses a year, % of loans")
        total_loans = self.book.balance("total", LATEST) / 1e6
        severe = self.named("severe_loss_rate")
        losses = self.sheets.value(credit.CREDIT, start + 3, 3)
        self.assertAlmostEqual(losses, severe * total_loans * 2)
        extra = self.sheets.value(credit.CREDIT, start + 4, 3)
        tax = self.named("tax_rate")
        self.assertAlmostEqual(extra, (losses - self.sheets.value(credit.CREDIT, start + 3, 1)) * (1 - tax))
        self.assertAlmostEqual(self.sheets.value(credit.CREDIT, start + 6, 3), (180 - extra) / 1500)

    def test_the_scenario_is_a_drop_down_and_the_cells_have_names(self):
        self.assertEqual(self.credit["validations"][0]["choices"], ["Base", "Adverse", "Severe"])
        self.assertEqual({name for name, _ in self.credit["names"]}, set(credit.NAMES))

    def test_the_notes_say_where_the_data_came_from_and_what_is_left_out(self):
        notes = "\n".join(cells[0][0] for cells in self.tabs[-1]["cells"] if cells and cells[0])
        self.assertIn("Credit losses by type of loan (the Credit Losses and FDIC Call Reports tabs)", notes)
        self.assertIn("ABC Bank (1); ABC Bank (2)", notes)
        self.assertIn("The allowance stays the percentage of loans assumed", notes)
        self.assertNotIn("which the SEC's facts do not give (the FDIC", notes)

    def test_a_typed_scenario_rate_flows_through(self):
        # (a default rate on commercial real estate typed over, in the severe scenario)
        self.choose("Severe")
        before = self.named("severe_loss_rate")
        table = next(n for n, cells in enumerate(self.credit["cells"]) if cells[0] and cells[0][0] == "Loan type")
        row = next(n for n in range(table, table + 20) if self.credit["cells"][n][0][0].startswith("Commercial real estate"))
        self.sheets.cells[credit.CREDIT][(row, credit.COLUMN_OF["severe-default"])] = 0.5
        self.sheets.worked_out.clear()
        share = self.sheets.value(credit.CREDIT, row, credit.COLUMN_OF["share"])
        recovery = self.sheets.value(credit.CREDIT, row, credit.COLUMN_OF["severe-recovery"])
        self.assertGreater(self.named("severe_loss_rate"), before)
        self.assertAlmostEqual(self.v("Assumptions", "charge-off-rate", 3), self.named("severe_loss_rate"))
        self.assertGreater(share * 0.5 * (1 - recovery), 0)


class TestWithoutTheFdic(ModelTestCase):

    def test_a_bank_without_a_loan_book_is_as_before(self):
        self.use(fm.build_model(bank_facts(), "ABC", "annual", 3, 3, "test", None, "bank"))
        names = [tab["name"] for tab in self.model.sheets()]
        self.assertNotIn(credit.CREDIT, names)
        self.assertNotIn("capital-ratio", self.model.layouts["Balance Sheet"].row_of)
        self.assertFalse(str(self.model.sheets()[0]["cells"][self.model.layouts["Assumptions"].row_of["charge-off-rate"] - 1][4][0]).startswith("=IF("))


class TestQuarterlyWithTheFdic(ModelTestCase):

    def test_quarters_have_eight_periods_of_stress_and_everything_works_out(self):
        with mock.patch.object(lisp_fdic, "fdic_records", fake_records):
            book = lisp_fdic.loan_book("creds.json", [(1, "ABC Bank")], "test")
        self.use(build_with_loans(book, "quarterly", 6, 8, bank_facts(quarterly=True)))
        self.assertEqual(self.sheets.at(*self.sheets.names["stress_periods"]), 8)
        for tab in self.model.sheets():
            for (row, column) in list(self.sheets.cells[tab["name"]]):
                self.sheets.value(tab["name"], row, column)


class TestTheBuiltin(LispTestCase):
    """(three-statement-model creds "ABC" :fdic ...) with a made-up bank, a fake FDIC, and a fake Google."""

    def setUp(self):
        super().setUp()
        self.written = []
        self.requests = []
        self.facts = bank_facts()
        self.facts = dict(self.facts)

        def records(credentials_path, dataset, params, who):
            self.requests.append((dataset, params.get("filters")))
            return fake_records(credentials_path, dataset, params, who)
        for patcher in (mock.patch.object(lisp_sec, "company_facts", lambda creds, company, who: self.facts),
                        mock.patch.object(fm, "company_industry", lambda creds, company, who: (6021, "National Commercial Banks")),
                        mock.patch.object(lisp_fdic, "fdic_records", records),
                        mock.patch.object(fm, "fed_funds_finder", lambda who: lambda periods: ([0.01] * len(periods), "")),
                        mock.patch.object(lisp_google, "google_workbook",
                                          lambda creds, title, sheets: self.written.append((title, sheets)) or "https://sheet")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("creds.json")

    def tab_names(self):
        return [tab["name"] for tab in self.written[-1][1]]

    def notes(self):
        return "\n".join(cells[0][0] for cells in self.written[-1][1][-1]["cells"] if cells and cells[0])

    def test_a_bank_has_the_federal_funds_rate_and_the_valuation_tab(self):
        self.facts["entityName"] = "ABC BANCORP"
        self.run_lisp('(three-statement-model creds "ABC")')
        self.assertIn("Valuation", self.tab_names())
        assumptions = next(tab for tab in self.written[-1][1] if tab["name"] == "Assumptions")
        labels = [cells[0][0] for cells in assumptions["cells"] if cells and cells[0]]
        self.assertIn("Federal funds rate (the average over the period; in the forecast, what you expect)", labels)

    def test_the_banks_are_found_by_the_companys_name(self):
        self.facts["entityName"] = "ABC BANCORP"
        self.run_lisp('(three-statement-model creds "ABC")')
        self.assertIn("Credit Losses", self.tab_names())
        self.assertEqual(sorted(f for d, f in self.requests if d == "financials"), ["CERT:1", "CERT:2"])

    def test_a_company_the_fdic_does_not_know_has_a_note_instead(self):
        self.facts["entityName"] = "NOBODY FINANCIAL CORP"
        self.run_lisp('(three-statement-model creds "ABC")')
        self.assertNotIn("Credit Losses", self.tab_names())
        self.assertIn("No FDIC data: the FDIC has no bank open now whose holding company (or itself) is called "
                      "NOBODY FINANCIAL CORP", self.notes())

    def test_banks_given_by_certificate_number(self):
        self.run_lisp("(three-statement-model creds \"ABC\" :fdic '(5))")
        self.assertIn("Credit Losses", self.tab_names())
        self.assertEqual([f for d, f in self.requests if d == "financials"], ["CERT:5"])

    def test_no_fdic_and_no_requests_with_fdic_false(self):
        self.run_lisp('(three-statement-model creds "ABC" :fdic #f)')
        self.assertNotIn("Credit Losses", self.tab_names())
        self.assertEqual(self.requests, [])

    def test_an_fdic_that_cannot_be_reached_is_a_note_when_looking_by_name(self):
        def broken(*arguments):
            raise lisp_core.LispError("fdic: the network is down")
        with mock.patch.object(lisp_fdic, "fdic_records", broken):
            self.run_lisp('(three-statement-model creds "ABC")')
        self.assertIn("No FDIC data: fdic: the network is down", self.notes())


if __name__ == "__main__":
    unittest.main()
