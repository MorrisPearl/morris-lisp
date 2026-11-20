"""The Quality and Risk tab of a three-statement model (lisp_financial_quality.py): a made-up company, no network.
sheet_formulas.py works out the formulas, and the tests check them against the measures worked out here in Python
from the model's own statements."""

import copy

from support import *  # noqa: F401,F403 -- the interpreter's modules, mock, and LispTestCase

import lisp_financial_model as fm
import lisp_financial_quality as quality
from test_financial_bank_insurer import ModelTestCase, bank_facts, build as build_kind, insurer_facts
from test_financial_model import build, made_up_facts

RETAINED_SHARE = 0.6                    # (the made-up company's retained earnings: this share of its equity)


def with_retained_earnings(facts):
    """The facts, with retained earnings reported at the end of each year."""
    facts = copy.deepcopy(facts)
    taxonomy = facts["facts"]["us-gaap"]
    equity = taxonomy["StockholdersEquity"]["units"]["USD"]
    taxonomy["RetainedEarningsAccumulatedDeficit"] = {"label": "", "units": {"USD": [
        dict(fact, val=fact["val"] * RETAINED_SHARE) for fact in equity]}}
    return facts


class QualityTestCase(ModelTestCase):

    def q(self, key, i):
        return self.v(fm.QUALITY, key, i)


class TestTheTab(QualityTestCase):

    def setUp(self):
        super().setUp()
        self.use(fm.build_model(with_retained_earnings(made_up_facts()), "ABC", "annual", 3, 3, "test", None))

    def test_it_comes_after_the_cash_flow_and_every_formula_works(self):
        names = [tab["name"] for tab in self.model.sheets()]
        self.assertEqual(names[names.index("Cash Flow") + 1], "Quality and Risk")
        for (row, column) in list(self.sheets.cells[fm.QUALITY]):
            self.sheets.value(fm.QUALITY, row, column)

    def test_debt_and_interest(self):
        for i in (1, 2, 4):
            ebitda = (self.v("Income Statement", "operating-income", i) + self.v("Cash Flow", "depreciation", i)
                      + self.v("Cash Flow", "amortization", i))
            debt = self.v("Balance Sheet", "current-debt", i) + self.v("Balance Sheet", "long-term-debt", i)
            net_debt = debt - self.v("Balance Sheet", "cash", i) - self.v("Balance Sheet", "short-term-investments", i)
            self.assertAlmostEqual(self.q("ebitda", i), ebitda)
            self.assertAlmostEqual(self.q("net-debt", i), net_debt)
            self.assertAlmostEqual(self.q("net-debt-to-ebitda", i), net_debt / ebitda)
            self.assertAlmostEqual(self.q("interest-coverage", i), self.v("Income Statement", "operating-income", i)
                                   / self.v("Income Statement", "interest-expense", i))
            self.assertAlmostEqual(self.q("debt-to-equity", i), debt / self.v("Balance Sheet", "equity", i))
            self.assertAlmostEqual(self.q("current-ratio", i), self.v("Balance Sheet", "current-assets", i)
                                   / self.v("Balance Sheet", "current-liabilities", i))

    def test_quality_of_earnings(self):
        for i in (1, 2, 4):
            net_income = self.v("Income Statement", "net-income", i)
            self.assertAlmostEqual(self.q("cash-conversion", i), self.v("Cash Flow", "free-cash-flow", i) / net_income)
            assets = (self.v("Balance Sheet", "total-assets", i - 1) + self.v("Balance Sheet", "total-assets", i)) / 2
            self.assertAlmostEqual(self.q("accruals-ratio", i),
                                   (net_income - self.v("Cash Flow", "operating-cash-flow", i)) / assets)
            self.assertAlmostEqual(self.q("stock-compensation-share", i),
                                   self.v("Cash Flow", "stock-compensation", i) / self.v("Income Statement", "revenue", i))
            self.assertAlmostEqual(self.q("share-change", i), self.v("Income Statement", "shares", i)
                                   / self.v("Income Statement", "shares", i - 1) - 1)
            self.assertAlmostEqual(self.q("cash-conversion-cycle", i), self.v("Assumptions", "receivable-days", i)
                                   + self.v("Assumptions", "inventory-days", i) - self.v("Assumptions", "payable-days", i))
            self.assertAlmostEqual(self.q("incremental-margin", i), (
                self.v("Income Statement", "operating-income", i) - self.v("Income Statement", "operating-income", i - 1)) / (
                self.v("Income Statement", "revenue", i) - self.v("Income Statement", "revenue", i - 1)))

    def test_the_altman_score_weighs_its_four_ratios(self):
        for i in (0, 2, 3, 5):
            assets = self.v("Balance Sheet", "total-assets", i)
            ratios = {
                "working-capital": (self.v("Balance Sheet", "current-assets", i)
                                    - self.v("Balance Sheet", "current-liabilities", i)) / assets,
                "retained": self.q("retained-earnings", i) / assets,
                "operating-income": self.v("Income Statement", "operating-income", i) / assets,
                "equity": self.v("Balance Sheet", "equity", i) / self.v("Balance Sheet", "total-liabilities", i),
            }
            z = sum(quality.ALTMAN_WEIGHTS[key] * ratio for key, ratio in ratios.items())
            self.assertAlmostEqual(self.q("altman-z", i), z)
            zone = "safe" if z > quality.ALTMAN_SAFE else "distress" if z < quality.ALTMAN_DISTRESS else "grey"
            self.assertEqual(self.q("altman-zone", i), zone)

    def test_retained_earnings_are_as_reported_then_grow_by_net_income_less_payouts(self):
        reported = 0.6 * (350 + 40 * 2)                       # (the made-up equity of 2023)
        self.assertAlmostEqual(self.q("retained-earnings", 2), reported)
        for i in (3, 4):
            self.assertAlmostEqual(self.q("retained-earnings", i), self.q("retained-earnings", i - 1)
                                   + self.v("Income Statement", "net-income", i) + self.v("Cash Flow", "dividends", i)
                                   + self.v("Cash Flow", "repurchases", i))

    def test_the_f_score_is_its_nine_tests_added_up(self):
        def ratio(tab_a, key_a, tab_b, key_b, i):
            return self.v(tab_a, key_a, i) / self.v(tab_b, key_b, i)
        for i in (1, 2, 4):
            before = i - 1
            roa = lambda j: ratio("Income Statement", "net-income", "Balance Sheet", "total-assets", j)
            leverage = lambda j: ratio("Balance Sheet", "long-term-debt", "Balance Sheet", "total-assets", j)
            liquidity = lambda j: ratio("Balance Sheet", "current-assets", "Balance Sheet", "current-liabilities", j)
            margin = lambda j: ratio("Income Statement", "gross-profit", "Income Statement", "revenue", j)
            turnover = lambda j: ratio("Income Statement", "revenue", "Balance Sheet", "total-assets", j)
            expected = {
                "f-profitable": self.v("Income Statement", "net-income", i) > 0,
                "f-cash": self.v("Cash Flow", "operating-cash-flow", i) > 0,
                "f-return": roa(i) > roa(before),
                "f-accruals": self.v("Cash Flow", "operating-cash-flow", i) > self.v("Income Statement", "net-income", i),
                "f-leverage": leverage(i) <= leverage(before),
                "f-liquidity": liquidity(i) > liquidity(before),
                "f-shares": self.v("Income Statement", "shares", i) <= self.v("Income Statement", "shares", before),
                "f-margin": margin(i) > margin(before),
                "f-turnover": turnover(i) > turnover(before),
            }
            for key, passed in expected.items():
                self.assertEqual(self.q(key, i), 1 if passed else 0, "%s in period %d" % (key, i))
            self.assertEqual(self.q("f-score", i), sum(expected.values()))

    def test_the_first_period_has_no_tests_against_a_year_before(self):
        row = self.model.layouts[fm.QUALITY].row_of["f-score"]
        self.assertNotIn((row - 1, 1), self.sheets.cells[fm.QUALITY])

    def test_the_notes_explain_it(self):
        self.assertIn("The Quality and Risk tab", self.model.sources_for_notes())


class TestWhereThereIsNoScore(QualityTestCase):

    def test_without_retained_earnings_the_tab_says_there_is_no_altman_score(self):
        self.use(build())
        lines = self.model.layouts[fm.QUALITY].lines
        header = next(line for line in lines if line is not None and line.key == "altman-header")
        self.assertIn("none, because the company does not report its retained earnings", header.label)
        self.assertNotIn("altman-z", self.model.layouts[fm.QUALITY].row_of)

    def test_a_bank_and_an_insurer_have_no_such_tab(self):
        for facts, kind in ((bank_facts(), "bank"), (insurer_facts(), "insurer")):
            names = [tab["name"] for tab in build_kind(facts, kind).sheets()]
            self.assertNotIn("Quality and Risk", names, kind)

    def test_quarters_compare_with_the_same_quarter_a_year_before(self):
        self.use(build(period="quarterly", history=6, forecast=4))
        lag = self.model.lag
        self.assertEqual(lag, 4)
        first = min(i for i in range(self.model.count) if (self.model.layouts[fm.QUALITY].row_of["f-score"] - 1, i + 1)
                    in self.sheets.cells[fm.QUALITY])
        self.assertEqual(first, lag)
        self.assertAlmostEqual(self.q("share-change", 5), self.v("Income Statement", "shares", 5)
                               / self.v("Income Statement", "shares", 1) - 1)
