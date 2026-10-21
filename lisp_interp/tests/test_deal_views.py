"""The views of a deal in a notebook (lib/deal_views.lsp, lib/deal_builder.lsp): (collateral deal), (info deal) and (bonds deal), each in a cell of
its own, for the same deal, so that what is changed in one is shown in the others. The grids are edited, clicked, and the buttons pressed, the
way the browser does it."""

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
class ViewsCase(LispTestCase):

    PIECES = "'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.5 240 12))"

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_views.lsp")')

    def make(self, collateral=PIECES):
        self.run_lisp('(define deal (new-deal "Demo 2026-1" :first-payment (date 2026 11 25) :closing-date (date 2026 11 20) %s))'
                      % (":collateral " + collateral if collateral else ""))

    def widget(self, source):
        """Make a view with the Lisp in source, and give it back."""
        return self.run_lisp(source)

    # -- doing what the user does ----------------------------------------------------

    @staticmethod
    def edit(grid, row, column, value):
        grid._DataGrid__handle_custom_msg(None, {"event_type": "cell-changed", "row": row, "column_index": list(grid.data.columns).index(column), "value": value}, [])

    @staticmethod
    def click(grid, row, column):
        columns = list(grid.data.columns)
        grid._DataGrid__handle_custom_msg(None, {"event_type": "cell-click", "region": "body", "column": column, "column_index": columns.index(column),
                                                 "row": row, "primary_key_row": row, "cell_value": None}, [])

    def press(self, button):
        self.out.clear()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            button.click()
        return self.printed() + printed.getvalue()

    def piece(self, grid, row, balance, wac, coupon, wam, age=0):
        for column, value in (("balance", balance), ("wac", wac), ("coupon", coupon), ("wam", wam), ("age", age)):
            self.edit(grid, row, column, value)


class TestTheCollateralView(ViewsCase):

    def view(self, collateral=ViewsCase.PIECES):
        self.make(collateral)
        self.page = self.widget("(collateral deal)")
        self.heading, self.grid, self.buttons, self.messages = self.page.children
        self.show_button, self.update_button = self.buttons.children

    def test_the_grid_has_a_row_for_each_piece_and_empty_ones_to_type_in(self):
        self.view()
        self.assertEqual(list(self.grid.data.columns), ["balance", "wac", "coupon", "wam", "age"])
        self.assertEqual(len(self.grid.data), 8)
        self.assertEqual(list(self.grid.data.iloc[0]), [100000000.0, 6.5, 6.0, 360, 0])
        self.assertEqual(list(self.grid.data.iloc[1]), [50000000.0, 7.5, 6.5, 240, 12])
        self.assertEqual(list(self.grid.data.iloc[2]), [0.0, 0.0, 0.0, 0, 0])
        self.assertIn("Demo 2026-1", self.heading.value)
        self.assertIn("pass-through coupon", self.heading.value)

    def test_a_deal_with_no_collateral_has_a_grid_of_empty_rows(self):
        self.make(collateral=None)
        self.heading, self.grid, self.buttons, self.messages = self.widget("(collateral deal)").children
        self.assertEqual(len(self.grid.data), 8)
        self.assertEqual(self.grid.data["balance"].sum(), 0)

    def test_the_number_of_rows_can_be_asked_for_and_more_are_added_to_a_longer_collateral(self):
        self.make(collateral="'((1.0 6.0 6.0 12) (2.0 6.0 6.0 12) (3.0 6.0 6.0 12) (4.0 6.0 6.0 12) (5.0 6.0 6.0 12) (6.0 6.0 6.0 12) (7.0 6.0 6.0 12) (8.0 6.0 6.0 12) (9.0 6.0 6.0 12))")
        grid = self.widget("(collateral deal)").children[1]
        self.assertEqual(len(grid.data), 12)                                 # (nine pieces, and three to type in)
        self.assertEqual(len(self.widget("(collateral deal :rows 20)").children[1].data), 20)

    def test_a_deal_that_was_started_with_cash_flows_has_no_collateral_data_to_show(self):
        self.run_lisp('(define old (start-deal "Old" (collateral-from-psa "POOL" 1000000.0 6.0 :term 24)))')
        self.assertLispError("(collateral old)", "the deal was started with the cash flows of its collateral")

    def test_the_cash_flows_of_what_is_in_the_grid_are_shown_at_the_pricing_speed_without_changing_the_deal(self):
        self.view()
        self.piece(self.grid, 1, 80000000.0, 7.0, 6.0, 180)                  # (changed in the grid, not in the deal)
        shown = self.press(self.show_button)
        self.assertIn("2 pieces, 180,000,000.00", shown)
        self.assertIn("a wac of 6.7222%, a pass-through coupon of 6.0000%", shown)
        self.assertIn("at PSA 100.", shown)
        for text in ("payment date", "2026-11-25", "balance", "principal", "interest", "speed", "wac", "coupon"):
            self.assertIn(text, shown)
        self.assertShows("(deal-size deal)", "150000000.0")

    def test_a_deal_with_no_first_payment_date_shows_no_dates(self):
        self.run_lisp('(define deal (new-deal "Demo" :collateral %s))' % self.PIECES)
        self.heading, self.grid, self.buttons, self.messages = self.widget("(collateral deal)").children
        shown = self.press(self.buttons.children[0])
        self.assertNotIn("payment date", shown)

    def test_what_is_wrong_with_what_is_in_the_grid_is_said_when_the_cash_flows_are_asked_for(self):
        self.view()
        self.piece(self.grid, 0, 100000000.0, 6.0, 6.5, 360)
        self.assertIn("is above its wac", self.press(self.show_button))
        for row in range(8):
            self.piece(self.grid, row, 0.0, 0.0, 0.0, 0)
        self.assertIn("there is no collateral", self.press(self.show_button))

    def test_the_button_gives_the_deal_the_collateral_in_the_grid(self):
        self.view()
        self.piece(self.grid, 2, 30000000.0, 8.0, 7.0, 120, 6)
        self.piece(self.grid, 0, 90000000.0, 6.5, 6.0, 360)
        shown = self.press(self.update_button)
        self.assertIn("Updated the collateral of Demo 2026-1: 170,000,000.00 in 3 pieces, paying for 360 months.", shown)
        self.assertShows("(deal-size deal)", "170000000.0")
        self.assertShows("(collateral-table-pieces (deal-collateral deal))", "((90000000.0 6.5 6.0 360 0) (50000000.0 7.5 6.5 240 12) (30000000.0 8.0 7.0 120 6))")
        self.assertEqual(list(self.grid.data.iloc[2]), [30000000.0, 8.0, 7.0, 120, 6])

    def test_the_tranches_under_it_are_worked_out_again_by_the_button(self):
        self.view()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-pac! deal "A" "AP" "AC" 100 300)''')
        self.edit(self.grid, 0, "balance", 200000000.0)
        self.press(self.update_button)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "A")) 0)'), 250000000.0 * 0.6, places=3)
        self.assertAlmostEqual(self.run_lisp('(+ (vector-ref (node-balance (get-node deal "AP")) 0) (vector-ref (node-balance (get-node deal "AC")) 0))'),
                               150000000.0, places=3)
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")

    def test_what_is_wrong_when_the_deal_is_given_the_collateral_is_said_and_the_deal_is_not_changed(self):
        self.view()
        self.piece(self.grid, 0, 100000000.0, 6.0, 6.5, 360)
        shown = self.press(self.update_button)
        self.assertIn("Error:", shown)
        self.assertNotIn("traceback", shown)
        self.assertShows("(deal-size deal)", "150000000.0")

    def test_a_change_of_the_collateral_somewhere_else_is_shown(self):
        self.view()
        self.run_lisp("(deal-set-collateral! deal '((7000000.0 6.0 5.5 120)))")
        self.assertEqual(list(self.grid.data.iloc[0]), [7000000.0, 6.0, 5.5, 120, 0])
        self.assertEqual(list(self.grid.data.iloc[1]), [0.0, 0.0, 0.0, 0, 0])

    def test_a_change_of_the_tranches_is_not_a_reason_to_lose_what_was_typed_and_not_given_to_the_deal(self):
        self.view()
        self.edit(self.grid, 3, "balance", 9000000.0)                          # (typed, not yet given to the deal)
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.assertEqual(self.grid.data["balance"][3], 9000000.0)


class TestTheInfoView(ViewsCase):

    def view(self, collateral=ViewsCase.PIECES):
        self.make(collateral)
        self.page = self.widget("(info deal)")
        (self.heading, self.name, self.closing, self.first_payment, self.speed_type, self.speed_grid, self.update_button, self.messages) = self.page.children

    def test_the_fields_have_what_the_deal_has(self):
        self.view()
        self.assertEqual(self.name.value, "Demo 2026-1")
        self.assertEqual(self.closing.value, "2026-11-20")
        self.assertEqual(self.first_payment.value, "2026-11-25")
        self.assertEqual(self.speed_type.value, "PSA")
        self.assertEqual(list(self.speed_type.options), ["PSA", "CPR", "SMM"])
        self.assertEqual(list(self.speed_grid.data.columns), ["from", "to", "months"])
        self.assertEqual(len(self.speed_grid.data), 4)
        self.assertEqual(list(self.speed_grid.data.iloc[0]), [100.0, 100.0, 0])                # (the pricing speed is 100 PSA to begin with)

    def test_a_deal_with_no_dates_has_empty_fields(self):
        self.run_lisp('(define deal (new-deal "Demo"))')
        page = self.widget("(info deal)")
        self.assertEqual(page.children[2].value, "")
        self.assertEqual(page.children[3].value, "")

    def test_the_button_gives_the_deal_what_is_typed(self):
        self.view()
        self.name.value = "Demo 2026-2"
        self.closing.value = "2026-12-01"
        self.first_payment.value = " 2027-01-25 "
        shown = self.press(self.update_button)
        self.assertIn("Updated Demo 2026-2: pricing speed PSA 100.", shown)
        self.assertShows("(deal-name deal)", '"Demo 2026-2"')
        self.assertShows("(deal-closing-date deal)", "2026-12-01")
        self.assertShows("(deal-first-payment deal)", "2027-01-25")

    def test_a_date_left_blank_is_no_date(self):
        self.view()
        self.closing.value = ""
        self.press(self.update_button)
        self.assertShows("(deal-closing-date deal)", "()")

    def test_a_speed_that_changes_is_typed_in_the_grid(self):
        self.view()
        self.speed_type.value = "CPR"
        self.edit(self.speed_grid, 0, "from", 5.0)
        self.edit(self.speed_grid, 0, "to", 5.0)
        self.edit(self.speed_grid, 0, "months", 12)
        self.edit(self.speed_grid, 1, "from", 5.0)
        self.edit(self.speed_grid, 1, "to", 20.0)
        self.edit(self.speed_grid, 1, "months", 24)
        self.edit(self.speed_grid, 2, "from", 20.0)
        self.edit(self.speed_grid, 2, "to", 20.0)
        shown = self.press(self.update_button)
        self.assertIn("pricing speed CPR: 5.0 for 12 months, then from 5.0 to 20.0 over 24 months, then 20.0 from then on", shown)
        self.assertShows("(speed-curve-pieces (deal-pricing-speed deal))", "((5.0 5.0 12) (5.0 20.0 24) (20.0 20.0 ()))")
        np.testing.assert_allclose(np.array(self.run_lisp('(node-principal (get-node deal "POOL"))').items)[:3],
                                   np.array(self.run_lisp("(car (project-pieces %s (prepayment-speed 'cpr 5)))" % self.PIECES).items)[:3])

    def test_the_first_row_of_the_speed_is_always_a_piece_so_a_speed_of_0_can_be_typed(self):
        self.view()
        self.edit(self.speed_grid, 0, "from", 0.0)
        self.edit(self.speed_grid, 0, "to", 0.0)
        self.press(self.update_button)
        self.assertShows("(describe-speed (deal-pricing-speed deal))", '"PSA 0.0"')

    def test_what_is_wrong_is_said_and_nothing_is_changed_not_even_what_was_right(self):
        self.view()
        self.name.value = "Another"
        self.closing.value = "2026-13-45"
        shown = self.press(self.update_button)
        self.assertIn("the closing date is a date written YYYY-MM-DD", shown)
        self.assertShows("(deal-name deal)", '"Demo 2026-1"')
        self.closing.value = "2026-11-20"
        self.name.value = "   "
        self.assertIn("the deal needs a name", self.press(self.update_button))
        self.name.value = "Demo 2026-1"
        self.edit(self.speed_grid, 0, "from", 100.0)
        self.edit(self.speed_grid, 0, "to", 200.0)
        self.assertIn("goes on for ever is one speed", self.press(self.update_button))
        self.assertShows("(describe-speed (deal-pricing-speed deal))", '"PSA 100"')

    def test_a_speed_that_breaks_a_split_below_the_collateral_is_said_and_changes_nothing(self):
        self.view()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-average-life! deal "A" '(("A1" 1.5) ("A2" 2.8) ("A3")))''')
        size = self.run_lisp('(vector-ref (node-balance (get-node deal "A1")) 0)')
        self.edit(self.speed_grid, 0, "from", 1.0)                            # (1 PSA: nothing prepays, and A cannot have a life of 1.5 years in its first bond)
        self.edit(self.speed_grid, 0, "to", 1.0)
        shown = self.press(self.update_button)
        self.assertIn("Error:", shown)
        self.assertEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "A1")) 0)'), size)

    def test_a_change_of_the_dates_or_the_speed_somewhere_else_is_shown(self):
        self.view()
        self.run_lisp("(deal-set-closing-date! deal (date 2027 3 1))")
        self.assertEqual(self.closing.value, "2027-03-01")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'smm '((0.5 0.5 6))))")
        self.assertEqual(self.speed_type.value, "SMM")
        self.assertEqual(list(self.speed_grid.data.iloc[0]), [0.5, 0.5, 6])

    def test_a_deal_with_no_pricing_speed_has_no_info_to_show(self):
        self.run_lisp('(define old (start-deal "Old" (collateral-from-psa "POOL" 1000000.0 6.0 :term 24)))')
        self.assertLispError("(info old)", "the deal has no pricing speed")


class TestTheBondsView(ViewsCase):

    def view(self, collateral=ViewsCase.PIECES):
        self.make(collateral)
        self.ui = self.widget("(bonds deal)")
        self.grid, self.flows, self.panel, self.delete_row, self.messages = self.ui.children

    def divide(self):
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-pac! deal "A" "AP" "AC" 100 300)''')

    def names(self):
        return [name.strip() for name in self.grid.data["tranche"]]

    def test_bonds_is_the_grid_of_the_tranches_with_a_column_to_click_for_the_cash_flows(self):
        self.view()
        self.assertEqual(list(self.grid.data.columns), ["tranche", "balance", "split", "cash flows"])
        self.assertEqual(self.names(), ["POOL"])
        self.assertEqual(list(self.grid.data["cash flows"]), ["view"])
        self.divide()
        self.assertEqual(self.names(), ["POOL", "A", "AP", "AC", "B"])
        self.assertEqual(list(self.grid.data["cash flows"]), ["view"] * 5)
        self.assertEqual(self.widget("(deal-builder deal)").__class__, self.ui.__class__)

    def test_clicking_view_shows_the_cash_flows_of_that_tranche_from_a_run_at_the_pricing_speed(self):
        self.view()
        self.divide()
        self.assertShows("(deal-ran deal)", "#f")
        self.out.clear()
        self.click(self.grid, 1, "cash flows")                                # (A)
        shown = self.printed()
        self.assertIn("A: 90,000,000.00 to begin with, with an average life of", shown)
        self.assertIn("run at PSA 100", shown)
        for text in ("month", "payment date", "2026-11-25", "balance", "principal", "interest", "2027-10-25"):
            self.assertIn(text, shown)
        self.assertShows("(describe-speed (deal-ran deal))", '"PSA 100"')
        np.testing.assert_allclose(self.run_lisp("(vector-ref (node-principal (get-node deal \"A\")) 0)"),
                                   self.run_lisp('(vector-ref (table-column (deal-flows-table deal "A") "principal") 0)'))

    def test_the_average_life_shown_is_that_of_the_tranche_and_an_interest_only_bond_has_none(self):
        self.view()
        self.run_lisp('(deal-io-po! deal "POOL" "IO" "PO")')
        self.out.clear()
        self.click(self.grid, 1, "cash flows")
        self.assertNotIn("average life", self.printed())
        self.out.clear()
        self.click(self.grid, 2, "cash flows")
        self.assertIn("with an average life of", self.printed())

    def test_the_deal_is_not_run_again_if_it_has_been_run_since_it_changed_and_it_is_if_it_has_not(self):
        self.view()
        self.divide()
        self.run_lisp("(deal-run! deal (prepayment-speed 'psa 300))")        # (run by the user, at another speed)
        self.out.clear()
        self.click(self.grid, 2, "cash flows")
        self.assertIn("run at PSA 300", self.printed())
        self.run_lisp('(deal-replace-split! deal "A" (pac-plan "AP" "AC" 100 250))')   # (a change: stale)
        self.assertShows("(deal-ran deal)", "#f")
        self.out.clear()
        self.click(self.grid, 2, "cash flows")
        self.assertIn("run at PSA 100", self.printed())

    def test_a_floater_with_no_index_says_so_in_a_line_and_the_index_the_deal_was_given_is_used(self):
        self.make("'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))")
        self.ui = self.widget("(bonds deal)")
        self.grid, self.flows, self.panel, self.delete_row, self.messages = self.ui.children
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.0975)')
        self.out.clear()
        self.click(self.grid, 1, "cash flows")
        self.assertIn("Error: a bond of this deal has a floating rate: give deal-run! an :index", self.printed())
        self.run_lisp("(deal-run! deal :index 0.04)")
        self.run_lisp("(deal-set-closing-date! deal (date 2026 12 1))")          # (a change: it is run again, with the index it was given)
        self.out.clear()
        self.click(self.grid, 1, "cash flows")
        self.assertIn("F: ", self.printed())
        self.assertShows("(begin (deal-check deal) #t)", "#t")

    def test_a_deal_with_no_collateral_yet_says_where_it_is_entered(self):
        self.make(collateral=None)
        self.ui = self.widget("(bonds deal)")
        self.grid, self.flows, self.panel, self.delete_row, self.messages = self.ui.children
        self.out.clear()
        self.click(self.grid, 0, "cash flows")
        self.assertIn("has no cash flows: the deal has no collateral yet", self.printed())
        self.out.clear()
        self.click(self.grid, 0, "tranche")
        self.assertIn("has no balance, so it cannot be divided yet: the collateral is entered with (collateral deal)", self.printed())
        self.assertEqual(self.panel.layout.display, "none")

    def test_the_cash_flows_of_the_collateral_are_those_of_the_pieces_at_the_pricing_speed(self):
        self.view()
        self.out.clear()
        self.click(self.grid, 0, "cash flows")
        flows = np.array(self.run_lisp("(car (project-pieces %s (prepayment-speed 'psa 100)))" % self.PIECES).items)
        shown = self.printed()
        self.assertIn("POOL: 150,000,000.00 to begin with", shown)
        self.assertIn("{:,.2f}".format(np.array(self.run_lisp("(node-principal (get-node deal \"POOL\"))").items)[0]), shown)


class TestSeveralViewsAtOnce(ViewsCase):
    """The same deal in three cells: a change in any is shown in the others."""

    def setUp(self):
        super().setUp()
        self.make()
        self.collateral_page = self.widget("(collateral deal)")
        self.info_page = self.widget("(info deal)")
        self.bonds_page = self.widget("(bonds deal)")
        self.collateral_grid = self.collateral_page.children[1]
        self.update_collateral = self.collateral_page.children[2].children[1]
        self.bonds_grid = self.bonds_page.children[0]
        self.speed_type = self.info_page.children[4]
        self.speed_grid = self.info_page.children[5]
        self.update_info = self.info_page.children[6]

    def bonds_balances(self):
        return list(self.bonds_grid.data["balance"])

    def test_the_collateral_view_changes_what_the_bonds_view_shows(self):
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.assertEqual(self.bonds_balances(), [150000000.0, 90000000.0, 60000000.0])
        self.edit(self.collateral_grid, 0, "balance", 200000000.0)
        self.press(self.update_collateral)
        self.assertEqual(self.bonds_balances(), [250000000.0, 150000000.0, 100000000.0])

    def test_the_bonds_view_changes_what_the_other_views_see_of_the_deal(self):
        ui = self.bonds_page
        self.click(self.bonds_grid, 0, "tranche")
        tabs = ui.children[2].children[1]
        page = tabs.children[0]
        for widget in page.children[0].children:
            if getattr(widget, "description", None) == "Tranches":
                widget.value = "A 90,000,000\nB"
        with contextlib.redirect_stdout(io.StringIO()):
            page.children[1].children[1].click()
        self.assertShows("(deal-names deal)", '("POOL" "A" "B")')
        self.assertEqual([name.strip() for name in self.bonds_grid.data["tranche"]], ["POOL", "A", "B"])
        self.assertShows("(deal-ran deal)", "#f")

    def test_the_info_view_changes_the_cash_flows_and_so_what_the_bonds_view_sizes(self):
        self.run_lisp('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2")))''')
        before = self.bonds_balances()
        self.speed_type.value = "PSA"
        self.edit(self.speed_grid, 0, "from", 400.0)
        self.edit(self.speed_grid, 0, "to", 400.0)
        self.press(self.update_info)
        after = self.bonds_balances()
        self.assertEqual(after[0], before[0])
        self.assertGreater(after[1], before[1])                                 # (faster: a bond of the same life is bigger)

    def test_a_change_made_in_code_is_shown_in_all_three(self):
        self.run_lisp("(deal-set-collateral! deal '((10000000.0 6.0 5.5 60)))")
        self.assertEqual(self.collateral_grid.data["balance"][0], 10000000.0)
        self.assertEqual(self.bonds_balances(), [10000000.0])
        self.run_lisp("(deal-set-closing-date! deal (date 2027 1 1))")
        self.assertEqual(self.info_page.children[2].value, "2027-01-01")

    def test_a_panel_that_was_open_in_the_bonds_view_is_put_away_when_the_deal_changes_elsewhere(self):
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.click(self.bonds_grid, 1, "tranche")
        self.assertIsNone(self.bonds_page.children[2].layout.display)
        self.edit(self.collateral_grid, 0, "balance", 200000000.0)
        self.press(self.update_collateral)
        self.assertEqual(self.bonds_page.children[2].layout.display, "none")

    def test_the_views_made_in_any_order_work_the_same(self):
        self.run_lisp('(define other (new-deal "Other"))')
        bonds = self.widget("(bonds other)")
        collateral = self.widget("(collateral other)")
        self.run_lisp("(deal-set-collateral! other '((10000000.0 6.0 5.5 60)))")
        self.assertEqual(list(bonds.children[0].data["balance"]), [10000000.0])
        self.assertEqual(collateral.children[1].data["balance"][0], 10000000.0)


if __name__ == "__main__":
    unittest.main()
