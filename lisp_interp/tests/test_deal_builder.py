"""The deal builder (lib/deal_builder.lsp): a grid of the tranches of a deal, and a panel to divide the one that was clicked.
The grid is clicked, the fields filled in and the buttons pressed the way the browser does it: by sending the message a click
makes, setting the value of the field widgets, and clicking the buttons. A widget works without a notebook, so none is needed;
what the buttons display goes to the test's output."""

import unittest

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

try:
    import ipywidgets
except ImportError:
    ipywidgets = None

try:
    import ipydatagrid
except ImportError:
    ipydatagrid = None


@unittest.skipIf(ipywidgets is None or ipydatagrid is None, "ipywidgets and ipydatagrid are needed")
class BuilderCase(LispTestCase):
    """A deal, its builder, and the helpers that click and fill in and press as the user does."""

    POOL = '(collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :psa 150)'

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_builder.lsp")')
        self.start("deal")

    @property
    def grid(self):
        """The grid in the column of the builder: a new one each time the tranches change."""
        return self.ui.children[0]

    def use(self, ui):
        """The clicks and the buttons that follow are those of this builder."""
        self.ui = ui
        self.flows, self.panel, self.delete_row, self.messages = ui.children[1:]
        self.tabs = self.panel.children[1]

    def start(self, name, options=""):
        """Make a deal called name, in the Lisp variable of that name, and its builder; the clicks and the buttons that follow are its."""
        self.deal_name = name
        self.run_lisp('(define %s (start-deal "%s" %s)) (define %s-ui (deal-builder %s %s))' % (name, name, self.POOL, name, name, options))
        self.use(self.env[lisp_core.Symbol(name + "-ui")])

    # -- doing what the user does ----------------------------------------------

    def click(self, row, column_index=0):
        """Click a cell of the grid, with the message the browser sends."""
        columns = list(self.grid.data.columns)
        self.grid._DataGrid__handle_custom_msg(None, {
            "event_type": "cell-click", "region": "body", "column": columns[column_index], "column_index": column_index,
            "row": row, "primary_key_row": row, "cell_value": None}, [])

    def page(self, title):
        return self.tabs.children[list(self.tabs.titles).index(title)]

    def field(self, title, label):
        """The widget of a field on a tab, which is found by its label."""
        for widget in self.page(title).children[0].children:
            if getattr(widget, "description", None) == label:
                return widget
        self.fail("no field %s on the tab %s" % (label, title))

    def fill(self, title, values):
        """Put values in fields of a tab: a dict of label to value."""
        for label, value in values.items():
            self.field(title, label).value = value

    def press(self, title, button):
        """Press 'Calculate the sizes' (0) or 'Add the tranches to the deal' (1) on a tab; return what is shown."""
        self.out.clear()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.page(title).children[1].children[button].click()
        return self.printed() + printed.getvalue()

    def calculate(self, title):
        return self.press(title, 0)

    def add(self, title):
        return self.press(title, 1)

    def push(self, button):
        """Click a button that is not on the tabs (the ones that take a split away); return what is shown."""
        self.out.clear()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            button.click()
        return self.printed() + printed.getvalue()

    def delete_button(self):
        return self.delete_row.children[0]

    def confirm_button(self):
        return self.delete_row.children[1]

    def cancel_button(self):
        return self.delete_row.children[2]

    def shown_buttons(self):
        """Which of the three buttons under the panel are there to be clicked."""
        if self.delete_row.layout.display == "none":
            return []
        return [name for name, button in (("delete", self.delete_button()), ("confirm", self.confirm_button()), ("cancel", self.cancel_button()))
                if button.layout.display != "none"]

    def selected_tab(self):
        return self.tabs.titles[self.tabs.selected_index]

    # -- looking at what happened ------------------------------------------------

    def rows(self):
        """The names in the grid, with the indentation that shows how deep they are."""
        return list(self.grid.data["tranche"])

    def names(self):
        return [name.strip() for name in self.rows()]

    def hidden(self):
        return self.panel.layout.display == "none"

    def balance(self, name):
        return self.run_lisp('(vector-ref (node-balance (get-node %s "%s")) 0)' % (self.deal_name, name))



@unittest.skipIf(ipywidgets is None or ipydatagrid is None, "ipywidgets and ipydatagrid are needed")
class TestDealBuilder(BuilderCase):

    # -- the start ----------------------------------------------------------------

    def test_a_new_deal_is_a_grid_with_one_row_the_collateral_and_a_panel_that_is_put_away(self):
        self.assertEqual(list(self.grid.data.columns), ["tranche", "balance", "split", "cash flows"])
        self.assertEqual(self.names(), ["POOL"])
        self.assertEqual(self.grid.data["balance"][0], 100000000.0)
        self.assertTrue(self.hidden())
        self.assertEqual(list(self.tabs.titles), ["Sequential", "Average life", "Pro rata", "PAC", "Floater/inverse", "Premium/discount", "IO/PO"])
        self.assertEqual(self.messages.__class__.__name__, "Output")

    def test_a_tranche_clicked_is_the_parent_of_the_split_and_the_fields_start_with_names_made_from_it(self):
        self.click(0)
        self.assertFalse(self.hidden())
        self.assertEqual(self.panel.children[0].value, "Divide <b>POOL</b>, which has a balance of 100,000,000.00, by:")
        self.assertEqual(self.field("Sequential", "Tranches").value, "POOL1\nPOOL2")
        self.assertEqual(self.field("Average life", "Tranches").value, "POOL1 2\nPOOL2 5\nPOOL3")
        self.assertEqual(self.field("PAC", "PAC").value, "POOL-PAC")
        self.assertEqual(self.field("PAC", "Companion").value, "POOL-COMP")
        self.assertEqual(self.field("Floater/inverse", "Floater").value, "POOL-F")
        self.assertEqual(self.field("Floater/inverse", "Cap %").value, 9.5)             # (3 above the 6.5 of the collateral)
        self.assertEqual(self.field("Premium/discount", "Premium coupon %").value, 7.5)
        self.assertEqual(self.field("Premium/discount", "Discount coupon %").value, 5.5)
        self.assertEqual(self.field("IO/PO", "PO").value, "POOL-PO")

    def test_an_accordion_instead_of_tabs_can_be_asked_for(self):
        self.run_lisp('(define accordion-ui (deal-builder deal :style "accordion"))')
        panel = self.env[lisp_core.Symbol("accordion-ui")].children[2]               # (under the grid, and the place for cash flows)
        self.assertIsInstance(panel.children[1], ipywidgets.Accordion)
        self.assertEqual(len(panel.children[1].children), 7)

    # -- a sequential split ----------------------------------------------------------

    def test_the_sizes_are_shown_without_adding_anything(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 60,000,000\nB"})
        shown = self.calculate("Sequential")
        self.assertIn("POOL (100,000,000.00) divided by a sequential split into:", shown)
        self.assertIn("60,000,000.00", shown)
        self.assertIn("40,000,000.00", shown)
        self.assertIn("60.00%", shown)
        self.assertEqual(self.names(), ["POOL"])
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_the_tranches_are_added_under_the_one_that_was_divided(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 60000000\nB 40000000"})
        shown = self.add("Sequential")
        self.assertIn("Added A, B under POOL, by a sequential split.", shown)
        self.assertEqual(self.rows(), ["POOL", "  A", "  B"])
        self.assertEqual(list(self.grid.data["balance"]), [100000000.0, 60000000.0, 40000000.0])
        self.assertEqual(list(self.grid.data["split"]), ["sequential", "", ""])
        self.assertShows("(deal-names deal)", '("POOL" "A" "B")')
        self.assertShows("(split-children (node-split (get-node deal \"POOL\")))", '("A" "B")')
        self.assertTrue(self.hidden())

    def test_the_grid_is_the_tree_of_the_deal_depth_first_as_tranches_are_added_at_any_depth(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 60000000\nB"})
        self.add("Sequential")
        self.click(1)                                                   # (A)
        self.assertEqual(self.panel.children[0].value, "Divide <b>A</b>, which has a balance of 60,000,000.00, by:")
        self.fill("Floater/inverse", {"Cap %": 9.0})
        self.add("Floater/inverse")
        self.assertEqual(self.rows(), ["POOL", "  A", "    A-F", "    A-I", "  B"])        # (under A, before B)
        self.click(4)                                                   # (B, which is now in the fifth row)
        self.fill("Pro rata", {"Tranches": "B1 10000000\nB2"})
        self.add("Pro rata")
        self.assertEqual(self.rows(), ["POOL", "  A", "    A-F", "    A-I", "  B", "    B1", "    B2"])
        self.assertEqual(list(self.grid.data["split"]), ["sequential", "floater and inverse floater", "", "", "pro rata", "", ""])
        self.assertAlmostEqual(self.balance("B2"), 30000000.0)
        self.assertAlmostEqual(self.balance("A-F") + self.balance("A-I"), 60000000.0)
        self.assertShows("(begin (deal-run! deal :index 0.04) (deal-check deal))", "#t")

    def test_a_grid_that_is_as_tall_as_its_rows_grows_with_them(self):
        self.assertEqual(self.grid.layout.height, "60px")
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 60000000\nB"})
        self.add("Sequential")
        self.assertEqual(self.grid.layout.height, "100px")

    def test_a_click_on_any_cell_of_a_row_chooses_the_tranche(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 60000000\nB"})
        self.add("Sequential")
        self.click(2, column_index=1)                                   # (the balance of B)
        self.assertIn("<b>B</b>", self.panel.children[0].value)

    def test_the_tranches_can_have_commas_blank_lines_and_a_z_bond(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "\nA 50,000,000\n\n Z 10,000,000  z \nB\n"})
        shown = self.calculate("Sequential")
        self.assertIn("10.00%", shown)
        self.add("Sequential")
        self.assertEqual(self.names(), ["POOL", "A", "Z", "B"])
        self.assertShows('(node-z-flag (get-node deal "Z"))', "#t")
        self.assertShows('(node-z-flag (get-node deal "A"))', "#f")
        self.assertAlmostEqual(self.balance("B"), 40000000.0)

    def test_a_z_bond_can_leave_out_its_balance_and_be_what_is_left(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 90000000\nZ z"})
        self.add("Sequential")
        self.assertAlmostEqual(self.balance("Z"), 10000000.0)
        self.assertShows('(node-z-flag (get-node deal "Z"))', "#t")

    def test_the_accretion_directed_bond_and_the_loss_rule_are_passed_on(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 50000000\nZ 10000000 z\nB", "Accretion directed to": "B", "Losses": "forward"})
        self.add("Sequential")
        self.assertShows('(sequential-split-accretion-to (node-split (get-node deal "POOL")))', '"B"')
        self.assertShows('(split-loss-rule (node-split (get-node deal "POOL")))', "forward")

    def test_what_is_wrong_with_the_tranches_is_said_and_nothing_is_added(self):
        self.click(0)
        for tranches, message in (("A 60000000\nB 30000000", "add up to 90000000.0, and POOL has 100000000.0"),
                                  ("A\nB 40000000", "A has no balance: only the last tranche can leave out its balance"),
                                  ("A 100000000\nB", "nothing is left of POOL for B"),
                                  ("A sixty\nB", "sixty is not a number, for the balance of A"),
                                  ("A 1 2\nB", "a line is a name, a balance, and z if it is a Z bond"),
                                  ("  \n", "write the tranches, one to a line")):
            with self.subTest(tranches=tranches):
                self.fill("Sequential", {"Tranches": tranches})
                shown = self.add("Sequential")
                self.assertIn("Error: ", shown)
                self.assertIn(message, shown)
                self.assertNotIn("traceback", shown)                              # (it is the user's mistake, not a bug to be traced)
                self.assertEqual(self.names(), ["POOL"])
                self.assertShows("(deal-names deal)", '("POOL")')
                self.assertFalse(self.hidden())                                  # (so it can be put right)

    def test_a_name_that_is_in_the_deal_already_is_an_error_that_leaves_the_deal_as_it_was(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "POOL 60000000\nB"})
        self.assertIn("the deal already has a node called POOL", self.add("Sequential"))
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_button_pressed_before_a_tranche_is_clicked_asks_for_one(self):
        self.assertIn("click a tranche first", self.calculate("Sequential"))
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 60000000\nB"})
        self.add("Sequential")
        self.assertIn("click a tranche first", self.add("Sequential"))             # (the tranche was divided: another is to be clicked)
        self.assertEqual(self.names(), ["POOL", "A", "B"])

    # -- the other kinds of split --------------------------------------------------------

    def test_the_sizes_shown_have_the_average_life_of_each_tranche(self):
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 30,000,000\nB"})
        shown = self.calculate("Sequential")
        self.assertIn("average life", shown)
        self.assertRegex(shown, r"A\s+30,000,000.00\s+30.00%\s+\d+\.\d\d")

    def test_an_interest_only_bond_has_no_average_life_in_the_sizes_shown(self):
        self.click(0)
        shown = self.calculate("IO/PO")
        self.assertNotIn("Error", shown)
        io_row = next(line for line in shown.splitlines() if line.startswith("POOL-IO"))
        po_row = next(line for line in shown.splitlines() if line.startswith("POOL-PO"))
        self.assertRegex(po_row, r"\d+\.\d\d\s*$")                         # (the PO has one)
        self.assertNotRegex(io_row, r"\d+\.\d\d\s*$")                      # (the IO is paid no principal, and has none)

    def test_an_average_life_split_is_sized_from_the_lives_and_the_tranche_that_has_none_is_what_is_left(self):
        self.click(0)
        self.fill("Average life", {"Tranches": "A1 2\nA2 5\nA3"})
        shown = self.calculate("Average life")
        self.assertIn("divided by a sequential by average life split into:", shown)
        for text in ("2.00", "5.00", "average life"):
            self.assertIn(text, shown)
        self.assertEqual(self.names(), ["POOL"])                                  # (only looked at)
        self.assertIn("Added A1, A2, A3 under POOL, by a sequential by average life split", self.add("Average life"))
        self.assertEqual(self.names(), ["POOL", "A1", "A2", "A3"])
        self.assertAlmostEqual(self.balance("A1") + self.balance("A2") + self.balance("A3"), 100000000.0, places=3)
        self.run_lisp("(deal-run! deal)")
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A1")'), 2.0, places=8)
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A2")'), 5.0, places=8)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_tranche_with_no_life_can_be_anywhere_in_the_list(self):
        self.click(0)
        self.fill("Average life", {"Tranches": "A1 1.5\nA2\nA3 12"})
        self.add("Average life")
        self.run_lisp("(deal-run! deal)")
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A1")'), 1.5, places=8)
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A3")'), 12.0, places=8)

    def test_what_is_wrong_with_the_lives_is_said(self):
        self.click(0)
        for tranches, message in (("A1 2\nA2 5", "all but one of its children"),
                                  ("A1\nA2", "all but one of its children"),
                                  ("A1 two\nA2", "two is not a number, for the average life of A1"),
                                  ("A1 2 3\nA2", "a line is a name and the average life"),
                                  ("A1 40\nA2", "A1 cannot have an average life of 40 years"),
                                  ("  \n", "write the tranches, one to a line")):
            with self.subTest(tranches=tranches):
                self.fill("Average life", {"Tranches": tranches})
                self.assertIn(message, self.calculate("Average life"))
                self.assertIn(message, self.add("Average life"))
                self.assertEqual(self.names(), ["POOL"])

    def test_a_pro_rata_split_pays_in_proportion_and_has_its_own_loss_rule(self):
        self.click(0)
        self.fill("Pro rata", {"Tranches": "A 70000000\nB"})
        self.assertIn("70.00%", self.calculate("Pro rata"))
        self.add("Pro rata")
        self.assertShows('(split-loss-rule (node-split (get-node deal "POOL")))', "pro-rata")
        self.assertShows('(pro-rata-split? (node-split (get-node deal "POOL")))', "#t")

    def test_a_pac_is_sized_from_the_two_speeds_as_deal_pac_does(self):
        self.run_lisp('''(define other (start-deal "Other" %s))
                         (deal-pac! other "POOL" "P" "C" 90 250)''' % self.POOL)
        self.click(0)
        self.fill("PAC", {"PAC": "P", "Companion": "C", "Low speed (PSA)": 90, "High speed (PSA)": 250})
        shown = self.calculate("PAC")
        self.assertIn("divided by a PAC and companion split into:", shown)
        self.assertEqual(self.names(), ["POOL"])                                   # (only looked at)
        self.add("PAC")
        self.assertEqual(self.names(), ["POOL", "P", "C"])
        pac = self.run_lisp('(vector-ref (node-balance (get-node other "P")) 0)')
        self.assertAlmostEqual(self.balance("P"), pac, places=4)
        self.assertAlmostEqual(self.balance("P") + self.balance("C"), 100000000.0, places=4)
        np.testing.assert_allclose(self.run_lisp('(pac-split-schedule (node-split (get-node deal "POOL")))').items,
                                   self.run_lisp('(pac-split-schedule (node-split (get-node other "POOL")))').items)
        self.assertShows("(begin (deal-run! deal) (deal-check deal))", "#t")

    def test_a_pac_needs_names_and_two_speeds_that_go_up(self):
        self.click(0)
        self.fill("PAC", {"PAC": "  "})
        self.assertIn("give the name of the PAC", self.add("PAC"))
        self.fill("PAC", {"PAC": "P", "Companion": ""})
        self.assertIn("give the name of the companion", self.add("PAC"))
        self.fill("PAC", {"Companion": "C", "Low speed (PSA)": 300, "High speed (PSA)": 100})
        self.assertIn("speeds must be from the lower to the higher", self.add("PAC"))
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_floater_and_inverse_floater_are_sized_from_the_cap(self):
        self.run_lisp('''(define other (start-deal "Other" %s))
                         (deal-floater-inverse! other "POOL" "F" "I" :cap 0.09 :margin 0.005)''' % self.POOL)
        self.click(0)
        self.fill("Floater/inverse", {"Floater": "F", "Inverse floater": "I", "Cap %": 9.0, "Margin %": 0.5})
        self.assertIn("divided by a floater and inverse floater split into:", self.calculate("Floater/inverse"))
        self.add("Floater/inverse")
        self.assertAlmostEqual(self.balance("F"), self.run_lisp('(vector-ref (node-balance (get-node other "F")) 0)'))
        self.assertAlmostEqual(self.balance("F"), 100000000.0 * 0.065 / 0.09)
        self.assertShows('(floater-inverse-split-margin (node-split (get-node deal "POOL")))', "0.005")
        self.assertShows("(begin (deal-run! deal :index 0.03) (deal-check deal))", "#t")

    def test_a_cap_below_the_coupon_is_an_error(self):
        self.click(0)
        self.fill("Floater/inverse", {"Cap %": 5.0})
        self.assertIn("must be above the coupon", self.calculate("Floater/inverse"))
        self.assertIn("must be above the coupon", self.add("Floater/inverse"))
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_premium_and_a_discount_bond_are_sized_so_they_pay_the_coupon_together(self):
        self.click(0)
        self.fill("Premium/discount", {"Premium coupon %": 8.5, "Discount coupon %": 4.5})
        self.add("Premium/discount")
        self.assertAlmostEqual(self.balance("POOL-P"), 50000000.0)                 # (6.5 is half way from 4.5 to 8.5)
        self.assertAlmostEqual(self.balance("POOL-D"), 50000000.0)
        self.assertShows('((node-coupon (get-node deal "POOL-P")) 0.0)', "0.085")

    def test_an_io_and_a_po_are_both_as_big_as_the_parent_and_the_io_coupon_may_be_left_blank_or_given(self):
        self.click(0)
        self.add("IO/PO")
        self.assertEqual(self.names(), ["POOL", "POOL-IO", "POOL-PO"])
        self.assertAlmostEqual(self.balance("POOL-IO"), 100000000.0)
        self.assertShows('(io-po-split-io-coupon (node-split (get-node deal "POOL")))', "()")
        self.start("second")
        self.click(0)
        self.fill("IO/PO", {"IO coupon % (blank for the parent's)": "2.5"})
        self.add("IO/PO")
        self.assertShows('(io-po-split-io-coupon (node-split (get-node second "POOL")))', "0.025")
        self.assertShows("(begin (deal-run! second) (deal-check second))", "#t")

    def test_an_io_coupon_that_is_not_a_number_is_an_error(self):
        self.click(0)
        self.fill("IO/PO", {"IO coupon % (blank for the parent's)": "lots"})
        self.assertIn("lots is not a number, for the coupon of the IO", self.add("IO/PO"))
        self.assertShows("(deal-names deal)", '("POOL")')

    # -- deals with more than one collateral, and forms of your own ------------------------------

    def test_every_collateral_is_a_row_with_the_tranches_under_it(self):
        self.run_lisp('''(deal-add-collateral! deal (collateral-from-psa "POOL2" 50000000.0 5.5 :term 360 :psa 100))
                         (define two (deal-builder deal))''')
        self.use(self.env[lisp_core.Symbol("two")])
        self.assertEqual(self.names(), ["POOL", "POOL2"])
        self.click(1)
        self.assertIn("<b>POOL2</b>", self.panel.children[0].value)
        self.fill("Sequential", {"Tranches": "X 20000000\nY"})
        self.add("Sequential")
        self.assertEqual(self.rows(), ["POOL", "POOL2", "  X", "  Y"])

    def test_forms_of_your_own_replace_the_standard_ones(self):
        self.run_lisp('''
          (define halves
            (make-split-form
              :title "Halves"
              :label "sequential"
              :help "Two tranches of half each."
              :fields (list (list "first" 'text "First" "") (list "second" 'text "Second" ""))
              :defaults (lambda (parent) (list (cons "first" (string-append (node-name parent) "-1"))
                                               (cons "second" (string-append (node-name parent) "-2"))))
              :plan (lambda (parent answers)
                      (let ((half (/ (vector-ref (node-balance parent) 0) 2.0)))
                        (sequential-plan (list (list (cdr (assoc "first" answers)) half) (list (cdr (assoc "second" answers)) half)))))))
          (define own (deal-builder deal :forms (list halves)))''')
        self.use(self.env[lisp_core.Symbol("own")])
        self.assertEqual(list(self.tabs.titles), ["Halves"])
        self.click(0)
        self.assertEqual(self.field("Halves", "First").value, "POOL-1")
        self.add("Halves")
        self.assertShows("(deal-names deal)", '("POOL" "POOL-1" "POOL-2")')
        self.assertAlmostEqual(self.balance("POOL-2"), 50000000.0)


@unittest.skipIf(ipywidgets is None or ipydatagrid is None, "ipywidgets and ipydatagrid are needed")
class TestChangingAndTakingAwayInTheBuilder(BuilderCase):
    """A tranche that is divided is clicked: its split is in the panel, to change, and there is a button to take it away."""

    SIGNATURE = '''
      (define (signature deal)
        (map (lambda (name)
               (let ((node (get-node deal name)))
                 (list name (round (* 100 (vector-ref (node-balance node) 0)))
                       (if (null? (node-coupon node)) '() (list (round (* 1e9 ((node-coupon node) 0.02))) (round (* 1e9 ((node-coupon node) 0.07)))))
                       (if (null? (node-split node)) '() (list (split-label (node-split node)) (split-children (node-split node))))
                       (round (* 1e9 (node-share node))) (node-notional-flag node) (node-z-flag node))))
             (deal-names deal)))
      (define (run-and-check deal) (deal-run! deal :index 0.04) (deal-check deal))'''

    DEMO = '''
      (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
      (deal-floater-inverse! deal "A" "AF" "AI" :cap 0.095)
      (deal-pac! deal "AF" "AP" "AC" 100 300)'''

    def setUp(self):
        super().setUp()
        self.run_lisp(self.SIGNATURE)

    def signature(self, deal="deal"):
        return self.show("(signature %s)" % deal)

    def make_demo(self):
        """The deal that the builder is for already has the demo splits: the builder shows them."""
        self.run_lisp(self.DEMO)
        self.start_over()

    def start_over(self):
        """A builder for the deal as it is now."""
        self.run_lisp("(define deal-ui (deal-builder deal))")
        self.use(self.env[lisp_core.Symbol("deal-ui")])

    # -- a tranche that is divided --------------------------------------------------

    def test_a_tranche_that_is_divided_shows_its_split_in_the_panel_with_its_inputs(self):
        self.make_demo()
        self.assertEqual(self.rows(), ["POOL", "  A", "    AF", "      AP", "      AC", "    AI", "  B"])
        self.click(1)                                                       # (A)
        self.assertFalse(self.hidden())
        self.assertEqual(self.panel.children[0].value,
                         "<b>A</b> is divided by a floater and inverse floater split into AF, AI. Change it:")
        self.assertEqual(self.selected_tab(), "Floater/inverse")
        self.assertEqual(self.field("Floater/inverse", "Floater").value, "AF")
        self.assertEqual(self.field("Floater/inverse", "Inverse floater").value, "AI")
        self.assertEqual(self.field("Floater/inverse", "Cap %").value, 9.5)
        self.assertEqual(self.field("Floater/inverse", "Margin %").value, 0.0)
        self.assertEqual([b.description for b in self.page("Floater/inverse").children[1].children], ["Calculate the sizes", "Change the split"])
        self.assertEqual(self.shown_buttons(), ["delete"])

    def test_a_tranche_that_is_not_divided_has_the_buttons_for_adding_and_no_button_to_take_away(self):
        self.make_demo()
        self.click(1)
        self.click(6)                                                       # (B, which is not divided)
        self.assertEqual([b.description for b in self.page("Sequential").children[1].children], ["Calculate the sizes", "Add the tranches to the deal"])
        self.assertEqual(self.shown_buttons(), [])
        self.assertEqual(self.panel.children[0].value, "Divide <b>B</b>, which has a balance of 40,000,000.00, by:")

    def test_the_split_of_each_kind_is_as_it_was_made_and_changing_nothing_changes_nothing(self):
        self.run_lisp("""
          (deal-sequential! deal "POOL" '(("L" 40000000.0) ("S" 10000000.0) ("R" 10000000.0) ("C" 20000000.0) ("F" 10000000.0) ("D" 5000000.0) ("O" 5000000.0)))
          (deal-average-life! deal "L" '(("L1" 1.0) ("L2") ("L3" 5.0)))
          (deal-sequential! deal "S" '(("S1" 2500000.0) ("S2" 2500000.0) ("SZ" 5000000.0 z)) :accretion-to "S1" :losses 'forward)
          (deal-pro-rata! deal "R" '(("R1" 6000000.0) ("R2" 4000000.0)))
          (deal-pac! deal "C" "C1" "C2" 90 250 :losses 'pro-rata)
          (deal-floater-inverse! deal "F" "F1" "F2" :cap 0.092 :margin 0.0075)
          (deal-premium-discount! deal "D" "D1" "D2" :premium-coupon 0.07 :discount-coupon 0.0525)
          (deal-io-po! deal "O" "O1" "O2" :io-coupon 0.02)""")
        self.start_over()
        expected = {
            "S": ("Sequential", {"Tranches": "S1 2500000.0\nS2 2500000.0\nSZ 5000000.0 z", "Accretion directed to": "S1", "Losses": "forward"}),
            "L": ("Average life", {"Tranches": "L1 1.0\nL2\nL3 5.0", "Losses": "reverse"}),
            "R": ("Pro rata", {"Tranches": "R1 6000000.0\nR2 4000000.0", "Losses": "pro-rata"}),
            "C": ("PAC", {"PAC": "C1", "Companion": "C2", "Low speed (PSA)": 90, "High speed (PSA)": 250, "Losses": "pro-rata"}),
            "F": ("Floater/inverse", {"Floater": "F1", "Inverse floater": "F2", "Cap %": 9.2, "Margin %": 0.75}),
            "D": ("Premium/discount", {"Premium bond": "D1", "Discount bond": "D2", "Premium coupon %": 7.0, "Discount coupon %": 5.25}),
            "O": ("IO/PO", {"IO": "O1", "PO": "O2", "IO coupon % (blank for the parent's)": "2.0"}),
        }
        before = self.signature()
        for name, (title, fields) in expected.items():
            with self.subTest(parent=name):
                self.click(self.names().index(name))
                self.assertEqual(self.selected_tab(), title)
                for label, value in fields.items():
                    self.assertEqual(self.field(title, label).value, value, label)
                shown = self.press(title, 1)
                self.assertIn("Changed the split of %s" % name, shown)
                self.assertNotIn("Error", shown)
                self.assertEqual(self.signature(), before)
        self.assertShows("(run-and-check deal)", "#t")

    # -- changing it -------------------------------------------------------------------

    def test_the_sizes_of_a_change_show_what_is_under_the_split_as_it_was_and_as_it_would_be(self):
        self.make_demo()
        self.click(1)
        self.fill("Floater/inverse", {"Cap %": 10.0})
        before = self.signature()
        shown = self.calculate("Floater/inverse")
        self.assertIn("A (60,000,000.00) divided by a floater and inverse floater split into:", shown)
        for text in ("was", "AF", "AP", "AC", "AI", "41,052,631.58", "39,000,000.00", "21,000,000.00"):
            self.assertIn(text, shown)
        self.assertEqual(self.signature(), before)                          # (only looked at)

    def test_pressing_change_works_out_the_tranches_under_it_again_and_shows_them(self):
        self.make_demo()
        self.click(1)
        self.fill("Floater/inverse", {"Cap %": 10.0})
        shown = self.press("Floater/inverse", 1)
        self.assertIn("Changed the split of A: it is a floater and inverse floater split into AF, AI, and what is under them is worked out again.", shown)
        self.assertEqual(self.rows(), ["POOL", "  A", "    AF", "      AP", "      AC", "    AI", "  B"])
        self.assertEqual(self.grid.data["balance"][2], 39000000.0)
        self.run_lisp('''(define direct (start-deal "Direct" %s))
                         (deal-sequential! direct "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-floater-inverse! direct "A" "AF" "AI" :cap 0.10)
                         (deal-pac! direct "AF" "AP" "AC" 100 300)''' % self.POOL)
        self.assertEqual(self.signature("deal"), self.signature("direct"))
        self.assertTrue(self.hidden())
        self.assertEqual(self.shown_buttons(), [])

    def test_a_change_that_is_wrong_is_said_and_changes_nothing_and_the_panel_stays(self):
        self.make_demo()
        self.click(1)
        before = self.signature()
        self.fill("Floater/inverse", {"Cap %": 5.0})
        for button in (0, 1):
            shown = self.press("Floater/inverse", button)
            self.assertIn("Error: the cap of the floater, 0.05, must be above the coupon", shown)
            self.assertNotIn("traceback", shown)
        self.assertEqual(self.signature(), before)
        self.assertFalse(self.hidden())
        self.assertEqual(self.shown_buttons(), ["delete"])

    def test_a_change_that_would_leave_out_a_tranche_that_is_divided_is_said(self):
        self.make_demo()
        self.click(0)
        before = self.signature()
        self.fill("Sequential", {"Tranches": "B 100000000"})
        self.assertIn("A is divided, so it cannot be left out: take away its split first", self.press("Sequential", 1))
        self.assertEqual(self.signature(), before)

    def test_a_split_can_be_changed_to_one_of_another_kind(self):
        self.make_demo()
        self.click(0)
        self.fill("Pro rata", {"Tranches": "A 60000000\nB"})
        self.assertIn("Changed the split of POOL: it is a pro rata split into A, B", self.press("Pro rata", 1))
        self.assertShows('(split-label (node-split (get-node deal "POOL")))', '"pro rata"')
        self.assertEqual(self.names(), ["POOL", "A", "AF", "AP", "AC", "AI", "B"])
        self.assertShows("(run-and-check deal)", "#t")

    def test_a_tranche_can_be_added_to_a_split_by_changing_it(self):
        self.make_demo()
        self.click(0)
        self.fill("Sequential", {"Tranches": "A 50000000\nB 30000000\nC"})
        self.press("Sequential", 1)
        self.assertEqual(self.names(), ["POOL", "A", "AF", "AP", "AC", "AI", "B", "C"])
        self.assertEqual(self.grid.data["balance"][7], 20000000.0)
        self.assertAlmostEqual(self.grid.data["balance"][2], 50000000.0 * 0.065 / 0.095, places=2)       # (to the cent)
        self.assertShows("(run-and-check deal)", "#t")

    def test_a_split_that_no_tab_is_for_can_only_be_taken_away(self):
        self.run_lisp('''(deal-io-po! deal "POOL" "IO" "PO")
                         (define only-sequential (deal-builder deal :forms (list (car (standard-split-forms)))))''')
        self.use(self.env[lisp_core.Symbol("only-sequential")])
        self.click(0)
        self.assertTrue(self.hidden())
        self.assertEqual(self.shown_buttons(), ["delete"])
        self.assertIn("POOL is divided by a IO and PO split, which no tab of the panel is for", self.printed())

    def test_a_form_that_does_not_say_what_is_in_its_fields_leaves_them_as_they_were(self):
        self.run_lisp('''
          (define bare
            (make-split-form :title "Bare" :label "sequential" :help "No describe."
                             :fields (list (list "tranches" 'textarea "Tranches" ""))
                             :defaults (lambda (parent) (list (cons "tranches" "X1\\nX2")))
                             :plan (lambda (parent answers) (sequential-plan (list (list "X1" 40000000.0) (list "X2" 60000000.0))))))
          (define own (deal-builder deal :forms (list bare)))''')
        self.use(self.env[lisp_core.Symbol("own")])
        self.click(0)
        self.press("Bare", 1)
        self.click(0)                                                       # (divided now: the fields are not described, so they are as they were)
        self.assertEqual(self.field("Bare", "Tranches").value, "X1\nX2")
        self.assertEqual(self.shown_buttons(), ["delete"])

    # -- taking a split away ---------------------------------------------------------------

    def test_the_button_says_what_would_be_taken_away_and_asks(self):
        self.make_demo()
        self.click(1)
        shown = self.push(self.delete_button())
        self.assertIn("Take away the split of A, and the 4 tranches under it, AF, AP, AC, AI? That cannot be undone.", shown)
        self.assertEqual(self.shown_buttons(), ["confirm", "cancel"])
        self.assertEqual(self.names(), ["POOL", "A", "AF", "AP", "AC", "AI", "B"])          # (nothing has gone yet)

    def test_a_split_with_one_tranche_under_it_says_the_tranche(self):
        self.run_lisp('(deal-sequential! deal "POOL" (list (list "ONLY" 100000000.0)))')
        self.start_over()
        self.click(0)
        self.assertIn("and the tranche under it, ONLY?", self.push(self.delete_button()))

    def test_yes_takes_the_split_and_everything_under_it_away(self):
        self.make_demo()
        self.click(1)
        self.push(self.delete_button())
        shown = self.push(self.confirm_button())
        self.assertIn("Took away the split of A, and AF, AP, AC, AI. A is not divided.", shown)
        self.assertEqual(self.rows(), ["POOL", "  A", "  B"])
        self.assertShows("(deal-names deal)", '("POOL" "A" "B")')
        self.assertTrue(self.hidden())
        self.assertEqual(self.shown_buttons(), [])
        self.assertEqual(self.grid.layout.height, "100px")
        self.assertShows("(run-and-check deal)", "#t")
        self.click(1)                                                       # (A can be divided again)
        self.assertEqual(self.panel.children[0].value, "Divide <b>A</b>, which has a balance of 60,000,000.00, by:")
        self.fill("Pro rata", {"Tranches": "A1 20000000\nA2"})
        self.add("Pro rata")
        self.assertEqual(self.names(), ["POOL", "A", "A1", "A2", "B"])

    def test_no_keeps_it(self):
        self.make_demo()
        self.click(1)
        before = self.signature()
        self.push(self.delete_button())
        self.assertIn("Kept.", self.push(self.cancel_button()))
        self.assertEqual(self.shown_buttons(), ["delete"])
        self.assertEqual(self.signature(), before)
        self.assertFalse(self.hidden())

    def test_clicking_another_tranche_forgets_the_question(self):
        self.make_demo()
        self.click(1)
        self.push(self.delete_button())
        self.click(2)                                                       # (AF, which is divided too)
        self.assertEqual(self.shown_buttons(), ["delete"])
        self.assertIn("<b>AF</b> is divided by a PAC and companion split", self.panel.children[0].value)
        self.push(self.delete_button())
        self.click(6)                                                       # (B, which is not)
        self.assertEqual(self.shown_buttons(), [])

    def test_what_is_taken_away_is_what_the_chosen_tranche_has_under_it_when_it_is_at_the_top(self):
        self.make_demo()
        self.click(0)
        self.push(self.delete_button())
        self.assertIn("the 6 tranches under it, A, AF, AP, AC, AI, B", self.printed())
        self.push(self.confirm_button())
        self.assertEqual(self.rows(), ["POOL"])


if __name__ == "__main__":
    unittest.main()
