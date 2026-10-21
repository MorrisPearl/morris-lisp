"""Starting a deal in a notebook (lib/new_deal.lsp): the grid for the collateral, the pricing speed, the buttons that show the cash flows and
make the deal, and the deal builder that takes the place of the grids. The grids are edited, and the buttons pressed, the way the browser does it."""

import unittest

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreters modules, numpy, mock, and LispTestCase

try:
    import ipywidgets
except ImportError:
    ipywidgets = None

try:
    import ipydatagrid
except ImportError:
    ipydatagrid = None


@unittest.skipIf(ipywidgets is None or ipydatagrid is None, "ipywidgets and ipydatagrid are needed")
class TestNewDeal(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "new_deal.lsp")')
        self.start()

    def start(self, options=":variable 'deal"):
        self.run_lisp('(define start (new-deal "Demo 2026-1" (date 2026 11 25) %s))' % options)
        self.page = self.env[lisp_core.Symbol("start")]
        self.heading, self.setup, self.messages = self.page.children
        self.pieces_grid = self.setup.children[1]
        self.speed_type = self.setup.children[3]
        self.speed_grid = self.setup.children[4]
        self.show_button, self.create_button = self.setup.children[5].children

    # -- doing what the user does ----------------------------------------------

    @staticmethod
    def edit(grid, row, column, value):
        """Type a value in a cell of a grid, the message the browser sends."""
        grid._DataGrid__handle_custom_msg(None, {"event_type": "cell-changed", "row": row, "column_index": list(grid.data.columns).index(column), "value": value}, [])

    def piece(self, row, balance, wac, wam, age=0):
        for column, value in (("balance", balance), ("wac", wac), ("wam", wam), ("age", age)):
            self.edit(self.pieces_grid, row, column, value)

    def speed_row(self, row, start, end, months):
        for column, value in (("from", start), ("to", end), ("months", months)):
            self.edit(self.speed_grid, row, column, value)

    def press(self, button):
        self.out.clear()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            button.click()
        return self.printed() + printed.getvalue()

    def two_pieces(self):
        self.piece(0, 100000000.0, 6.0, 360)
        self.piece(1, 50000000.0, 7.0, 240, 12)

    # -- the start ----------------------------------------------------------------

    def test_the_page_has_a_grid_of_empty_pieces_and_a_speed_of_100_psa(self):
        self.assertIn("Demo 2026-1", self.heading.value)
        self.assertIn("2026-11-25", self.heading.value)
        self.assertEqual(list(self.pieces_grid.data.columns), ["balance", "wac", "wam", "age"])
        self.assertEqual(len(self.pieces_grid.data), 8)
        self.assertEqual(self.pieces_grid.data["balance"].sum(), 0)
        self.assertEqual(self.speed_type.value, "PSA")
        self.assertEqual(list(self.speed_type.options), ["PSA", "CPR", "SMM"])
        self.assertEqual(list(self.speed_grid.data.columns), ["from", "to", "months"])
        self.assertEqual(list(self.speed_grid.data.iloc[0]), [100.0, 100.0, 0])
        self.assertEqual(self.show_button.description, "Show the cash flows")
        self.assertEqual(self.create_button.description, "Create the deal")
        self.assertShows("(new-deal-deal start)", "()")

    def test_the_number_of_rows_can_be_asked_for(self):
        self.start("")
        self.run_lisp('(define more (new-deal "Demo" (date 2026 11 25) :rows 20))')
        self.assertEqual(len(self.env[lisp_core.Symbol("more")].children[1].children[1].data), 20)

    def test_the_first_payment_is_a_date(self):
        self.assertLispError('(new-deal "Demo" "2026-11-25")', "the first payment is a date")

    # -- showing the cash flows ---------------------------------------------------------

    def test_the_cash_flows_of_the_pieces_are_shown_added_up_year_by_year(self):
        self.two_pieces()
        shown = self.press(self.show_button)
        self.assertIn("2 pieces, 150,000,000.00", shown)
        self.assertIn("a wac of 6.3333%", shown)
        self.assertIn("a wam of 360 months", shown)
        self.assertIn("at PSA 100.0.", shown)
        for text in ("payment date", "2026-11-25", "2027-10-25", "balance", "principal", "interest", "speed", "coupon", "100.00"):
            self.assertIn(text, shown)
        flows = lisp_core.pairs_to_list(self.run_lisp("(project-pieces '((100000000.0 6.0 360) (50000000.0 7.0 240 12)) (prepayment-speed 'psa 100))"))
        life = self.run_lisp("(average-life (car (project-pieces '((100000000.0 6.0 360) (50000000.0 7.0 240 12)) (prepayment-speed 'psa 100))))")
        self.assertIn("average life is %.2f years" % life, shown)
        self.assertIn("{:,.2f}".format(flows[2].items[11]), shown)                       # (the balance at the start of month 12, the last row of the first year)
        self.assertNotIn("rows --", shown)                                               # (every row is shown)

    def test_a_speed_that_changes_is_shown_month_by_month_at_the_ends_of_the_years(self):
        self.two_pieces()
        self.edit(self.speed_grid, 0, "from", 5.0)
        self.edit(self.speed_grid, 0, "to", 5.0)
        self.edit(self.speed_grid, 0, "months", 12)
        self.speed_row(1, 5.0, 20.0, 24)
        self.speed_row(2, 20.0, 20.0, 0)
        self.speed_type.value = "CPR"
        shown = self.press(self.show_button)
        self.assertIn("at CPR: 5.0 for 12 months, then from 5.0 to 20.0 over 24 months, then 20.0 from then on.", shown)
        self.assertRegex(shown, r"\b1\s+2026-11-25\s+[\d,\.]+\s+[\d,\.]+\s+[\d,\.]+\s+5\.00")         # (5 CPR in the first month)
        self.assertRegex(shown, r"\b24\s+2028-10-25\s+[\d,\.]+\s+[\d,\.]+\s+[\d,\.]+\s+12\.50")        # (half way up the ramp: 5 + 15 x 12 / 24)
        self.assertRegex(shown, r"\b36\s+2029-10-25\s+[\d,\.]+\s+[\d,\.]+\s+[\d,\.]+\s+20\.00")

    def test_a_speed_of_nothing_in_the_first_row_is_a_speed_of_0_and_not_a_row_left_out(self):
        self.two_pieces()
        for column in ("from", "to"):
            self.edit(self.speed_grid, 0, column, 0.0)
        shown = self.press(self.show_button)
        self.assertIn("at PSA 0.0.", shown)
        self.assertNotIn("Error", shown)

    def test_the_last_month_is_shown_when_it_is_not_the_end_of_a_year(self):
        self.piece(0, 1000000.0, 6.0, 30)
        shown = self.press(self.show_button)
        for month in ("1 ", "12 ", "24 ", "30 "):
            self.assertRegex(shown, r"\n\s*" + month)
        self.assertIn("2029-04-25", shown)                                 # (month 30)

    def test_a_row_with_no_balance_is_left_out_and_nothing_typed_is_said(self):
        self.assertIn("there is no collateral", self.press(self.show_button))
        self.piece(3, 80000000.0, 5.5, 360)                      # (a row in the middle of the empty ones)
        self.assertIn("1 pieces, 80,000,000.00", self.press(self.show_button))

    def test_what_is_wrong_with_the_collateral_or_the_speed_is_said(self):
        self.piece(0, 100000000.0, -1.0, 360)
        self.assertIn("the wac of a piece of collateral is in percent", self.press(self.show_button))
        self.piece(0, 100000000.0, 6.0, 360)
        self.edit(self.speed_grid, 0, "from", 100.0)
        self.edit(self.speed_grid, 0, "to", 200.0)
        self.assertIn("goes on for ever is one speed", self.press(self.show_button))
        self.assertShows("(new-deal-deal start)", "()")

    def test_a_value_that_is_not_a_whole_number_of_months_is_said_by_the_grid(self):
        self.piece(0, 100000000.0, 6.0, 360)
        self.edit(self.pieces_grid, 0, "wam", 12.5)
        shown = self.press(self.show_button)
        self.assertIn("wam", shown)
        self.assertIn("not a whole number", shown)

    # -- making the deal ----------------------------------------------------------------

    def test_the_deal_is_made_from_the_pieces_at_the_speed(self):
        self.two_pieces()
        self.edit(self.speed_grid, 0, "from", 150.0)
        self.edit(self.speed_grid, 0, "to", 150.0)
        self.press(self.create_button)
        self.assertEqual(self.page.children[0].value, "<b>Demo 2026-1</b>: 150,000,000.00 of collateral in 2 pieces, paying for 360 months from 2026-11-25. Click a tranche to divide it. The deal is the value of <code>deal</code>.")
        self.assertShows("(deal-name deal)", '"Demo 2026-1"')
        self.assertShows("(eq? deal (new-deal-deal start))", "#t")
        self.assertShows("(deal-names deal)", '("POOL")')
        self.assertShows("(deal-first-payment deal)", "2026-11-25")
        self.assertShows('(vector-ref (deal-payment-dates deal) 1)', "2026-12-25")
        self.run_lisp("(define direct (collateral-from-pieces \"POOL\" '((100000000.0 6.0 360) (50000000.0 7.0 240 12)) (prepayment-speed 'psa 150)))")
        np.testing.assert_allclose(self.run_lisp('(node-principal (get-node deal "POOL"))').items, self.run_lisp("(node-principal direct)").items)
        np.testing.assert_allclose(self.run_lisp('(node-interest (get-node deal "POOL"))').items, self.run_lisp("(node-interest direct)").items)
        self.assertShows('(collateral-pieces (get-node deal "POOL"))', "((100000000.0 6.0 360 0) (50000000.0 7.0 240 12))")

    def test_the_speed_that_was_typed_is_the_pricing_speed_of_the_collateral(self):
        self.two_pieces()
        self.edit(self.speed_grid, 0, "from", 5.0)
        self.edit(self.speed_grid, 0, "to", 5.0)
        self.edit(self.speed_grid, 0, "months", 12)
        self.speed_row(1, 5.0, 20.0, 24)
        self.speed_row(2, 20.0, 20.0, 0)
        self.speed_type.value = "SMM"
        self.press(self.create_button)
        self.assertShows('(speed-curve-type (collateral-speed (get-node deal "POOL")))', "smm")
        self.assertShows('(speed-curve-pieces (collateral-speed (get-node deal "POOL")))', "((5.0 5.0 12) (5.0 20.0 24) (20.0 20.0 ()))")

    def test_a_deal_with_no_variable_is_the_value_of_the_widget_only(self):
        self.start("")
        self.two_pieces()
        self.press(self.create_button)
        self.assertNotIn("is the value of", self.page.children[0].value)
        self.assertIn("in 2 pieces", self.page.children[0].value)
        self.assertEqual(type(self.run_lisp("(new-deal-deal start)")).__name__, "LispStruct")
        self.assertLispError("deal", "unbound symbol")

    def test_the_deal_builder_takes_the_place_of_the_grids(self):
        self.two_pieces()
        self.press(self.create_button)
        self.assertEqual(self.setup.layout.display, "none")
        self.assertEqual(len(self.page.children), 2)
        heading, builder = self.page.children
        self.assertIn("Click a tranche to divide it", heading.value)
        grid = builder.children[0]
        self.assertEqual([name.strip() for name in grid.data["tranche"]], ["POOL"])
        self.assertAlmostEqual(grid.data["balance"][0], 150000000.0)

    def test_the_deal_that_was_made_can_be_divided_by_clicking_and_by_average_life(self):
        self.two_pieces()
        self.press(self.create_button)
        builder = self.page.children[1]
        grid, panel = builder.children[0], builder.children[1]
        grid._DataGrid__handle_custom_msg(None, {"event_type": "cell-click", "region": "body", "column": "tranche", "column_index": 0, "row": 0,
                                                 "primary_key_row": 0, "cell_value": "POOL"}, [])
        tabs = panel.children[1]
        page = tabs.children[list(tabs.titles).index("Average life")]
        for widget in page.children[0].children:
            if getattr(widget, "description", None) == "Tranches":
                widget.value = "A1 2\nA2 5\nA3"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            page.children[1].children[1].click()
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-names deal)", '("POOL" "A1" "A2" "A3")')
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A1")'), 2.0, places=8)
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A2")'), 5.0, places=8)
        self.assertShows("(deal-check deal)", "#t")

    def test_what_is_wrong_when_the_deal_is_made_is_said_and_no_deal_is_made(self):
        self.assertIn("there is no collateral", self.press(self.create_button))
        self.assertShows("(new-deal-deal start)", "()")
        self.assertEqual(self.setup.layout.display, None)

    def test_new_deal_deal_wants_the_widget_that_new_deal_made(self):
        self.assertLispError('(new-deal-deal (make-widget "VBox"))', "expected the widget that new-deal made")


if __name__ == "__main__":
    unittest.main()
