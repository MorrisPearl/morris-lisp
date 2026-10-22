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

    def row(self, row):
        """The balance, wac, coupon, wam and age in a row of the grid of collateral: the cells after them say what the loans are like, which is not known here."""
        cells = list(self.grid.data.iloc[row])
        self.assertTrue(all(cell != cell for cell in cells[5:]), "what the loans are like is blank: %s" % cells)
        return cells[:5]

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
        self.assertEqual(list(self.grid.data.columns), ["balance", "wac", "coupon", "wam", "age", "loan size", "credit score", "ltv", "sato", "burnout",
                                                         "investor share", "second home share", "cash-out share", "refinance share"])
        self.assertEqual(len(self.grid.data), 8)
        self.assertEqual(self.row(0), [100000000.0, 6.5, 6.0, 360, 0])
        self.assertEqual(self.row(1), [50000000.0, 7.5, 6.5, 240, 12])
        self.assertEqual(self.row(2), [0.0, 0.0, 0.0, 0, 0])
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
        self.assertShows("(map (lambda (piece) (list (collateral-piece-balance piece) (collateral-piece-wac piece) (collateral-piece-coupon piece) (collateral-piece-wam piece) (collateral-piece-age piece))) (collateral-table-pieces (deal-collateral deal)))", "((90000000.0 6.5 6.0 360 0) (50000000.0 7.5 6.5 240 12) (30000000.0 8.0 7.0 120 6))")
        self.assertEqual(self.row(2), [30000000.0, 8.0, 7.0, 120, 6])

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

    def test_what_the_loans_are_like_is_typed_in_its_columns_and_a_blank_is_not_known(self):
        self.view()
        self.edit(self.grid, 0, "credit score", 760)
        self.edit(self.grid, 0, "investor share", 0.15)
        self.edit(self.grid, 1, "ltv", 62.5)
        self.press(self.update_button)
        self.assertShows("(map collateral-piece-credit-score (deal-pieces deal))", "(760.0 ())")
        self.assertShows("(map collateral-piece-investor-share (deal-pieces deal))", "(0.15 ())")
        self.assertShows("(map collateral-piece-ltv (deal-pieces deal))", "(() 62.5)")
        self.assertEqual(self.grid.data["credit score"][0], 760)
        self.edit(self.grid, 1, "investor share", 1.5)
        self.assertIn("a share of the balance, from 0 to 1", self.press(self.update_button))
        self.assertShows("(map collateral-piece-investor-share (deal-pieces deal))", "(0.15 ())")

    def test_a_change_of_the_collateral_somewhere_else_is_shown(self):
        self.view()
        self.run_lisp("(deal-set-collateral! deal '((7000000.0 6.0 5.5 120)))")
        self.assertEqual(self.row(0), [7000000.0, 6.0, 5.5, 120, 0])
        self.assertEqual(self.row(1), [0.0, 0.0, 0.0, 0, 0])

    def test_a_change_of_the_tranches_is_not_a_reason_to_lose_what_was_typed_and_not_given_to_the_deal(self):
        self.view()
        self.edit(self.grid, 3, "balance", 9000000.0)                          # (typed, not yet given to the deal)
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.assertEqual(self.grid.data["balance"][3], 9000000.0)


class TestTheInfoView(ViewsCase):

    def view(self, collateral=ViewsCase.PIECES):
        self.make(collateral)
        self.page = self.widget("(info deal)")
        (self.heading, self.name, self.closing, self.first_payment, self.speed_type, self.speed_grid, self.home_prices, self.mortgage_spread,
         self.curve_heading, self.curve_grid, self.update_button, self.messages) = self.page.children

    def test_the_fields_have_what_the_deal_has(self):
        self.view()
        self.assertEqual(self.name.value, "Demo 2026-1")
        self.assertEqual(self.closing.value, "2026-11-20")
        self.assertEqual(self.first_payment.value, "2026-11-25")
        self.assertEqual(self.speed_type.value, "PSA")
        self.assertEqual(list(self.speed_type.options), ["PSA", "CPR", "SMM", "MODEL"])
        self.assertEqual((self.home_prices.value, self.mortgage_spread.value), (3.0, 1.75))       # (what the prepayment model is told, to begin with)
        self.assertEqual(list(self.speed_grid.data.columns), ["from", "to", "months"])
        self.assertEqual(len(self.speed_grid.data), 4)
        self.assertEqual(list(self.speed_grid.data.iloc[0]), [100.0, 100.0, 0])                # (the pricing speed is 100 PSA to begin with)

    def test_the_treasury_curve_is_a_grid_of_years_and_yields_with_empty_rows_to_type_in(self):
        self.view()
        self.assertEqual(list(self.curve_grid.data.columns), ["years", "yield"])
        self.assertEqual(len(self.curve_grid.data), 6)
        self.assertEqual(list(self.curve_grid.data.iloc[0]), [0.0, 0.0])
        self.run_lisp("(deal-set-treasury-curve! deal '((2 4.1) (3 4.2)))")                        # (a change made somewhere else is shown)
        self.assertEqual(list(self.curve_grid.data.iloc[0]), [2.0, 4.1])
        self.assertEqual(list(self.curve_grid.data.iloc[1]), [3.0, 4.2])
        self.assertEqual(list(self.curve_grid.data.iloc[2]), [0.0, 0.0])
        self.assertIn("Treasury curve", self.curve_heading.value)

    def test_the_button_gives_the_deal_the_curve_that_is_typed_and_a_blank_one_takes_it_away(self):
        self.view()
        for row, (years, percent) in enumerate(((5, 4.3), (2, 4.1), (10, 4.5))):                    # (in any order)
            self.edit(self.curve_grid, row, "years", years)
            self.edit(self.curve_grid, row, "yield", percent)
        shown = self.press(self.update_button)
        self.assertIn("Treasury curve of 3 points", shown)
        self.assertShows("(deal-treasury-curve deal)", "((2.0 4.1) (5.0 4.3) (10.0 4.5))")
        for row in range(3):
            self.edit(self.curve_grid, row, "years", 0.0)
            self.edit(self.curve_grid, row, "yield", 0.0)
        shown = self.press(self.update_button)
        self.assertIn("no Treasury curve", shown)
        self.assertShows("(deal-treasury-curve deal)", "()")

    def test_a_curve_that_is_wrong_is_said_and_nothing_is_changed(self):
        self.view()
        self.edit(self.curve_grid, 0, "years", 2.0)
        self.edit(self.curve_grid, 0, "yield", 4.0)
        self.edit(self.curve_grid, 1, "years", 2.0)
        self.edit(self.curve_grid, 1, "yield", 4.5)
        self.name.value = "Changed"
        shown = self.press(self.update_button)
        self.assertIn("two yields for 2.0 years", shown)
        self.assertEqual(self.run_lisp("(deal-name deal)"), "Demo 2026-1")
        self.assertShows("(deal-treasury-curve deal)", "()")

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

    def test_what_the_prepayment_model_is_told_is_typed_and_shown(self):
        self.view()
        self.home_prices.value = -2.5
        self.mortgage_spread.value = 2.25
        self.press(self.update_button)
        self.assertShows("(list (deal-home-price-growth deal) (deal-mortgage-spread deal))", "(-2.5 2.25)")
        self.run_lisp("(deal-set-home-price-growth! deal 4.0)")                                    # (a change made somewhere else is shown)
        self.assertEqual(self.home_prices.value, 4.0)
        self.home_prices.value = -150.0
        self.assertIn("above -100", self.press(self.update_button))

    def test_a_speed_of_the_model_needs_the_curve_and_is_given_it_first(self):
        self.view()
        self.speed_type.value = "MODEL"
        self.assertIn("needs a Treasury curve", self.press(self.update_button))
        self.assertShows("(speed-curve-type (deal-pricing-speed deal))", "psa")
        self.run_lisp('''(set! freddie-prepayment-fit-read
                            (spline-logistic (list (cons "incentive_bp" (vector -100.0 0.0 100.0 200.0)) (cons "loan_age" (vector 1.0 2.0 3.0 4.0))
                                                   (cons "loan_size_k" (vector 100.0 200.0 300.0 250.0)) (cons "credit_score" (vector 700.0 720.0 740.0 760.0))
                                                   (cons "current_ltv" (vector 50.0 60.0 70.0 80.0)) (cons "sato" (vector 0.0 0.1 0.2 0.3))
                                                   (cons "burnout" (vector 0.0 1.0 2.0 3.0)) (cons "investor" (vector 0.0 0.0 1.0 0.0))
                                                   (cons "second_home" (vector 0.0 1.0 0.0 0.0)) (cons "cash_out" (vector 1.0 0.0 0.0 0.0))
                                                   (cons "refinance" (vector 0.0 0.0 0.0 1.0)) (cons "winter" (vector 1.0 0.0 0.0 0.0))
                                                   (cons "summer" (vector 0.0 1.0 0.0 0.0)))
                                             (vector 0.01 0.02 0.05 0.2) 0))''')        # (a stand-in for the fitted model: just enough to work)
        for row, (years, percent) in enumerate(((2, 4.1), (10, 4.5))):
            self.edit(self.curve_grid, row, "years", years)
            self.edit(self.curve_grid, row, "yield", percent)
        self.assertEqual(self.speed_type.value, "PSA")                       # (what failed is put back as the deal has it)
        self.speed_type.value = "MODEL"                                       # (and the grid's 100 is 100% of the model)
        shown = self.press(self.update_button)
        self.assertIn("pricing speed MODEL 100", shown)
        self.assertIn("(home prices 3.0% a year, mortgage rate 1.75% over the 10-year Treasury)", shown)
        self.assertShows("(speed-curve-type (deal-pricing-speed deal))", "model")
        self.assertShows("(deal-treasury-curve deal)", "((2.0 4.1) (10.0 4.5))")

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
        self.assertEqual(list(self.grid.data.columns), ["tranche", "balance", "split", "cash flows", "price", "yield", "spread", "oas", "duration", "effective duration", "average life", "dv01", "money", "delay"])
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
        self.update_info = self.info_page.children[10]

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
