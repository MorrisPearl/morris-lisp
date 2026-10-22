"""Prices in the grid of the tranches of a deal ((bonds deal), lib/deal_builder.lsp): a price, a yield, a spread or a delay typed in a cell gives the tranche
that, and what is worked out from it is shown in the others; a price can be + or ?; a cleared cell takes the price away; what is typed in a column that is
worked out is put back. The grid is edited and clicked the way the browser does it."""

import unittest

from support import *  # noqa: F401,F403 -- the interpreters modules, numpy, mock, and LispTestCase
from test_deal_views import ViewsCase


class PricingGridCase(ViewsCase):

    def make(self, collateral=None):
        """A deal of 60 months, with the dates that a new issue has and a Treasury curve, divided into A and B, with its bonds view."""
        self.run_lisp('''(define deal (new-deal "Demo 2026-1" :first-payment (date 2026 12 25) :closing-date (date 2026 11 20)
                                                 :collateral '((10000000.0 6.5 6.0 60)) :speed (prepayment-speed 'psa 150)))
                         (deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))''')

    def setUp(self):
        super().setUp()
        self.make()
        self.ui = self.widget("(bonds deal)")
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))''')

    @property
    def grid(self):
        return self.ui.children[0]

    def type_in(self, row, column, text):
        """The user types text in a cell (and the browser says so): what is said under the grid is given back."""
        self.out.clear()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.edit(self.grid, row, column, text)
        return re.sub(r"\x1b\[2K|\r", "", self.printed() + printed.getvalue())        # (without what clearing an Output widget writes where there is no notebook)

    def cell(self, row, column):
        return self.grid.data[column][row]

    def slot(self, name, slot):
        return self.run_lisp('(node-%s (get-node deal "%s"))' % (slot, name))


class TestTheColumns(PricingGridCase):

    def test_the_grid_has_the_columns_of_what_a_price_says_after_the_cash_flows(self):
        self.assertEqual(list(self.grid.data.columns), ["tranche", "balance", "split", "cash flows", "price", "yield", "spread", "oas", "duration",
                                                         "effective duration", "average life", "dv01", "money", "delay"])
        self.assertEqual([name.strip() for name in self.grid.data["tranche"]], ["POOL", "A", "B"])

    def test_the_average_life_and_the_delay_are_there_before_anything_is_priced(self):
        for row in range(3):
            self.assertTrue(float(self.cell(row, "average life")) > 0)
            self.assertEqual(self.cell(row, "delay"), "24")
            for column in ("price", "yield", "spread", "duration", "dv01", "money"):
                self.assertEqual(self.cell(row, column), "")

    def test_the_average_life_of_a_tranche_is_that_of_the_slot(self):
        self.assertEqual(self.cell(1, "average life"), "%.3f" % self.slot("A", "average-life"))


class TestTypingAPrice(PricingGridCase):

    def test_a_price_gives_the_yield_the_spread_the_duration_the_dv01_and_the_money(self):
        self.assertEqual(self.type_in(1, "price", "100.5"), "")
        self.assertEqual(self.slot("A", "price"), 100.5)
        self.assertEqual(self.cell(1, "price"), "100.5000")
        self.assertEqual(self.cell(1, "yield"), "%.4f" % self.slot("A", "yield"))
        self.assertEqual(self.cell(1, "spread"), "%.1f" % self.slot("A", "spread"))
        self.assertEqual(self.cell(1, "duration"), "%.3f" % self.slot("A", "duration"))
        self.assertEqual(self.cell(1, "dv01"), "{:,.2f}".format(self.slot("A", "dv01")))
        self.assertEqual(self.cell(1, "money"), "{:,.2f}".format(self.slot("A", "money")))
        self.assertEqual(self.cell(0, "price"), "")                                  # (the others are as they were)
        self.assertEqual(self.cell(2, "money"), "")

    def test_a_yield_and_a_spread_give_the_price(self):
        self.type_in(1, "yield", "5.25")
        self.assertEqual(self.slot("A", "yield"), 5.25)
        self.assertEqual(self.cell(1, "yield"), "5.2500")
        self.assertEqual(self.cell(1, "price"), "%.4f" % self.slot("A", "price"))
        self.type_in(2, "spread", "120")
        self.assertEqual(self.slot("B", "spread"), 120)
        self.assertEqual(self.cell(2, "spread"), "120.0")
        self.assertEqual(self.cell(2, "price"), "%.4f" % self.slot("B", "price"))
        self.assertShows('(node-priced-by (get-node deal "B"))', "spread")

    def test_plus_and_question_mark_are_prices_that_add_up_the_money(self):
        self.type_in(1, "price", "100.5")
        self.type_in(2, "yield", "6")
        self.type_in(0, "price", "+")
        self.assertAlmostEqual(self.slot("POOL", "money"), self.slot("A", "money") + self.slot("B", "money"), places=4)
        self.assertEqual(self.cell(0, "price"), "%.4f" % self.slot("POOL", "price"))
        self.type_in(0, "price", "101")
        self.type_in(2, "price", "?")
        self.assertAlmostEqual(self.slot("A", "money") + self.slot("B", "money"), self.slot("POOL", "money"), places=4)
        self.assertEqual(self.cell(2, "price"), "%.4f" % self.slot("B", "price"))

    def test_a_cleared_cell_takes_the_price_away(self):
        self.type_in(1, "price", "100.5")
        self.type_in(1, "price", "")
        for column in ("price", "yield", "spread", "duration", "dv01", "money"):
            self.assertEqual(self.cell(1, column), "")
        self.assertShows('(node-priced-by (get-node deal "A"))', "()")
        self.assertTrue(float(self.cell(1, "average life")) > 0)

    def test_the_delay_is_typed_and_changes_the_money(self):
        self.type_in(1, "price", "100.5")
        before = self.slot("A", "money")
        self.assertEqual(self.type_in(1, "delay", "14"), "")
        self.assertEqual(self.cell(1, "delay"), "14")
        self.assertEqual(self.cell(1, "price"), "100.5000")
        self.assertLess(self.slot("A", "money"), before)

    def test_what_is_typed_stays_when_the_deal_changes(self):
        self.type_in(1, "price", "100.5")
        yield_before = self.cell(1, "yield")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 400))")
        self.assertEqual(self.cell(1, "price"), "100.5000")
        self.assertNotEqual(self.cell(1, "yield"), yield_before)
        self.run_lisp('''(deal-sequential! deal "B" '(("B1" 1000000.0) ("B2" 3000000.0)))''')
        self.assertEqual([name.strip() for name in self.grid.data["tranche"]], ["POOL", "A", "B", "B1", "B2"])
        self.assertEqual(self.cell(1, "price"), "100.5000")
        self.assertEqual(self.cell(3, "money"), "")
        self.assertTrue(float(self.cell(3, "average life")) > 0)


class TestTheOasColumns(PricingGridCase):

    def test_they_are_blank_until_the_paths_are_run_and_then_have_the_oas_and_the_effective_duration(self):
        self.type_in(1, "price", "100.5")
        for column in ("oas", "effective duration"):
            self.assertEqual(self.cell(1, column), "")
        self.run_lisp("(deal-run-paths! deal :paths 4)")
        self.assertEqual(self.cell(1, "oas"), "%.1f" % self.slot("A", "oas"))
        self.assertEqual(self.cell(1, "effective duration"), "%.3f" % self.slot("A", "effective-duration"))
        self.assertEqual(self.cell(2, "oas"), "")                                    # (B has no price)

    def test_an_oas_that_is_typed_gives_the_price_and_the_rest(self):
        self.run_lisp("(deal-run-paths! deal :paths 4)")
        self.assertEqual(self.type_in(2, "oas", "80"), "")
        self.assertEqual(self.slot("B", "oas"), 80)
        self.assertEqual(self.cell(2, "oas"), "80.0")
        self.assertEqual(self.cell(2, "price"), "%.4f" % self.slot("B", "price"))
        self.assertEqual(self.cell(2, "yield"), "%.4f" % self.slot("B", "yield"))
        self.assertEqual(self.cell(2, "effective duration"), "%.3f" % self.slot("B", "effective-duration"))
        self.assertShows('(node-priced-by (get-node deal "B"))', "oas")

    def test_an_oas_before_the_paths_are_run_is_said_and_put_back(self):
        said = self.type_in(2, "oas", "80")
        self.assertIn("have not been run", said)
        self.assertEqual(self.cell(2, "oas"), "")

    def test_the_effective_duration_is_worked_out_not_typed(self):
        self.run_lisp("(deal-run-paths! deal :paths 4)")
        self.type_in(1, "price", "100.5")
        said = self.type_in(1, "effective duration", "9")
        self.assertIn("effective duration is worked out, not typed", said)
        self.assertEqual(self.cell(1, "effective duration"), "%.3f" % self.slot("A", "effective-duration"))


class TestWhatIsPutBack(PricingGridCase):

    def test_a_column_that_is_worked_out_is_not_typed_in(self):
        self.type_in(1, "price", "100.5")
        said = self.type_in(1, "duration", "9")
        self.assertIn("duration is worked out, not typed", said)
        self.assertEqual(self.cell(1, "duration"), "%.3f" % self.slot("A", "duration"))

    def test_text_that_is_not_a_number_is_said_and_put_back(self):
        self.type_in(1, "price", "100.5")
        said = self.type_in(1, "price", "lots")
        self.assertIn("lots is not a number, for the price of A", said)
        self.assertEqual(self.cell(1, "price"), "100.5000")
        self.assertEqual(self.slot("A", "price"), 100.5)

    def test_what_the_deal_cannot_do_is_said_and_put_back(self):
        said = self.type_in(1, "spread", "100")
        self.assertEqual(said, "")
        self.run_lisp("(deal-treasury-curve-set! deal '())")
        self.run_lisp("(deal-update-analytics! deal)")
        said = self.type_in(2, "spread", "100")
        self.assertIn("has no Treasury curve", said)
        self.assertEqual(self.cell(2, "spread"), "")
        said = self.type_in(1, "delay", "-3")
        self.assertIn("a whole number of days", said)
        self.assertEqual(self.cell(1, "delay"), "24")

    def test_question_mark_with_nothing_to_take_it_from_is_said(self):
        said = self.type_in(2, "price", "?")
        self.assertIn("POOL has no price yet", said)
        self.assertEqual(self.cell(2, "price"), "")

    def test_clicking_in_the_columns_of_prices_does_not_open_the_panel(self):
        self.click(self.grid, 1, "price")
        self.assertEqual(self.ui.children[2].layout.display, "none")
        self.click(self.grid, 1, "balance")
        self.assertNotEqual(self.ui.children[2].layout.display, "none")


if __name__ == "__main__":
    unittest.main()
