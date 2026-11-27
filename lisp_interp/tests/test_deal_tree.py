"""The deal tree (lib/deal_tree.lsp and lisp_deal_tree.py): a window that draws a deal as a tree, with a menu on each tranche and a pop-up
for a split. First the Lisp functions the window calls, without a window; then the window itself, which is drawn by Qt off the screen
(QT_QPA_PLATFORM=offscreen), clicked and filled in the way a person does it: the menu's actions are triggered, the fields typed into and
the buttons clicked. Qt's event loop is not run (deal-tree would wait in it for the window to be closed); the pop-ups are shown instead of
waiting, and the question before taking a split away is answered by the test."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # (before Qt is imported: the windows are drawn off the screen)

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

try:
    from PyQt6 import QtWidgets
except ImportError:
    QtWidgets = None

import lisp_deal_tree
import lisp_widgets

SEQUENTIAL = '(list (cons "tranches" "A 60000000\nB") (cons "accretion" "") (cons "losses" "reverse"))'


class TreeFunctionsTest(LispTestCase):
    """The Lisp functions that deal-tree gives the window: what they say about the deal, and what they do to it."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(require "deal_tree.lsp") (define deal %s) (define forms (standard-split-forms))'
                      % psa_deal("demo", 100000000.0, 6.5, psa=150))

    def value(self, src):
        """What the Lisp gives back, as Python values (lists, strings, numbers), as the window gets them."""
        return lisp_widgets.to_python(self.run_lisp(src))

    def test_the_nodes_are_the_tree_depth_first_with_their_parents_balances_splits_and_kinds(self):
        self.run_lisp('(deal-sequential! deal "POOL" (list (list "A" 60000000) (list "Z" 40000000 (quote z))))'
                      '(deal-io-po! deal "A" "A-IO" "A-PO")')
        self.assertEqual(self.value('(deal-tree--nodes deal)'),
                         [["POOL", "", 100000000.0, "sequential", ""],
                          ["A", "POOL", 60000000.0, "IO and PO", ""],
                          ["A-IO", "A", 60000000.0, "", "notional"],
                          ["A-PO", "A", 60000000.0, "", ""],
                          ["Z", "POOL", 40000000.0, "", "Z"]])

    def test_a_form_asks_for_its_fields_with_the_defaults_for_the_tranche(self):
        heading, help_text, fields = self.value('(deal-tree--asking forms deal "PAC" "POOL")')
        self.assertEqual(heading, "Divide POOL, which has a balance of 100,000,000.00, by a PAC and companion split")
        self.assertIn("schedule", help_text)
        self.assertEqual(fields, [["pac", "text", "PAC", "POOL-PAC"],
                                  ["companion", "text", "Companion", "POOL-COMP"],
                                  ["low", "number", "Low speed (PSA)", 100],
                                  ["high", "number", "High speed (PSA)", 300],
                                  ["losses", "dropdown", "Losses", "reverse", ["reverse", "forward", "pro-rata"]]])

    def test_a_form_for_a_divided_tranche_has_what_its_split_has(self):
        self.run_lisp('(deal-tree--apply! forms deal "Sequential" "POOL" %s)' % SEQUENTIAL)
        heading, help_text, fields = self.value('(deal-tree--asking forms deal "Sequential" "POOL")')
        self.assertEqual(heading, "Change the sequential split of POOL, which has a balance of 100,000,000.00")
        self.assertEqual(fields[0], ["tranches", "textarea", "Tranches", "A 60000000.0\nB 40000000.0"])
        self.assertEqual(self.value('(deal-tree--title-of-split forms deal "POOL")'), "Sequential")

    def test_the_sizes_are_worked_out_without_changing_the_deal(self):
        heading, columns, rows = self.value('(deal-tree--sizes forms deal "Sequential" "POOL" %s)' % SEQUENTIAL)
        self.assertEqual(heading, "POOL (100,000,000.00) divided by a sequential split into:")
        self.assertEqual(columns, ["tranche", "balance", "share of its parent", "average life"])
        self.assertEqual([row[:3] for row in rows], [["A", 60000000.0, 0.6], ["B", 40000000.0, 0.4]])
        self.assertLess(rows[0][3], rows[1][3])                    # (A is paid first, so its average life is shorter)
        self.assertEqual(len(self.value('(deal-tree--nodes deal)')), 1)

    def test_applying_divides_the_tranche_and_says_so(self):
        message = self.value('(deal-tree--apply! forms deal "Sequential" "POOL" %s)' % SEQUENTIAL)
        self.assertEqual(message, "Added A, B under POOL, by a sequential split.")
        self.assertEqual([node[0] for node in self.value('(deal-tree--nodes deal)')], ["POOL", "A", "B"])

    def test_applying_to_a_divided_tranche_changes_its_split(self):
        self.run_lisp('(deal-tree--apply! forms deal "Sequential" "POOL" %s)' % SEQUENTIAL)
        message = self.value('(deal-tree--apply! forms deal "Pro rata" "POOL" '
                             '(list (cons "tranches" "A 50000000\nB") (cons "losses" "pro-rata")))')
        self.assertTrue(message.startswith("Changed the split of POOL: it is a pro rata split into A, B"))
        self.assertEqual(self.value('(deal-tree--nodes deal)')[1], ["A", "POOL", 50000000.0, "", ""])

    def test_deleting_takes_away_the_split_and_everything_under_it(self):
        self.run_lisp('(deal-tree--apply! forms deal "Sequential" "POOL" %s)' % SEQUENTIAL)
        self.run_lisp('(deal-sequential! deal "A" (list (list "A1" 30000000) (list "A2" 30000000)))')
        self.assertEqual(self.value('(deal-tree--delete! deal "POOL")'), "Took away the split of POOL, and A, A1, A2, B. POOL is not divided.")
        self.assertEqual(len(self.value('(deal-tree--nodes deal)')), 1)

    def test_what_is_wrong_with_the_answers_is_an_error(self):
        with self.assertRaisesRegex(lisp_core.LispError, "only the last tranche can leave out its balance"):
            self.run_lisp('(deal-tree--sizes forms deal "Sequential" "POOL" '
                          '(list (cons "tranches" "A\nB") (cons "accretion" "") (cons "losses" "reverse")))')
        with self.assertRaisesRegex(lisp_core.LispError, "no kind of split called Diagonal"):
            self.run_lisp('(deal-tree--asking forms deal "Diagonal" "POOL")')


@unittest.skipIf(QtWidgets is None, "PyQt6 is needed")
class TreeWindowTest(LispTestCase):
    """The window, drawn off the screen, and clicked as a person does."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(require "deal_tree.lsp") (define deal %s)' % psa_deal("demo", 100000000.0, 6.5, psa=150))
        self.open_window()

    def open_window(self):
        """Opens the window of the deal, without waiting in Qt's event loop for it to be closed."""
        with mock.patch.object(QtWidgets.QApplication, "exec", lambda application: 0):
            self.window = self.run_lisp('(deal-tree deal)')
        self.addCleanup(self.window.close)

    # -- doing what the user does ----------------------------------------------

    def node(self, name):
        """The node called name, as the window has it: (name parent balance split-label kind)."""
        return next(node for node in self.window.nodes if node[0] == name)

    def menu_texts(self, name):
        """What the menu of the tranche called name says, line by line, and whether each line can be chosen."""
        return [(action.text().strip(), action.isEnabled()) for action in self.window.node_menu(self.node(name)).actions()]

    def choose(self, name, text):
        """Clicks the tranche called name and chooses the line of its menu that starts with text: the pop-up it opens is shown, not waited
        for, and is returned (None if it opens none)."""
        action = next(action for action in self.window.node_menu(self.node(name)).actions() if action.text().strip().startswith(text))
        before = set(self.window.findChildren(QtWidgets.QDialog))
        with mock.patch.object(QtWidgets.QDialog, "exec", lambda dialog: dialog.show()):
            action.trigger()
        opened = set(self.window.findChildren(QtWidgets.QDialog)) - before
        return opened.pop() if opened else None

    def button(self, dialog, text):
        return next(button for button in dialog.findChildren(QtWidgets.QPushButton) if button.text() == text)

    def visible_labels(self, dialog):
        return [label.text() for label in dialog.findChildren(QtWidgets.QLabel) if label.isVisible()]

    def sizes_shown(self, dialog):
        """The table of sizes in the pop-up, as rows of text."""
        table = dialog.findChildren(QtWidgets.QTableWidget)[0]
        return [[table.item(row, column).text() for column in range(table.columnCount())] for row in range(table.rowCount())]

    def boxes(self):
        """The boxes drawn, by the name of the tranche."""
        return {item.node[0]: item for item in self.window.scene.items() if hasattr(item, "node")}

    def divide_pool(self):
        """Divides POOL into A (60 million) and B (the rest) by a sequential split, through the menu and the pop-up."""
        dialog = self.choose("POOL", "Sequential")
        dialog.findChildren(QtWidgets.QPlainTextEdit)[0].setPlainText("A 60,000,000\nB")
        self.button(dialog, "Calculate the sizes").click()
        self.button(dialog, "Add the tranches to the deal").click()

    # -- the tests -------------------------------------------------------------

    def test_the_window_draws_a_box_for_each_tranche(self):
        self.assertEqual(self.window.windowTitle(), "Deal tree: demo")
        self.assertEqual(set(self.boxes()), {"POOL"})
        self.divide_pool()
        self.assertEqual(set(self.boxes()), {"POOL", "A", "B"})

    def test_the_tree_is_laid_out_with_the_children_to_the_right_and_a_parent_between_its_first_and_last_child(self):
        nodes = [["POOL", "", 1, "sequential", ""], ["A", "POOL", 1, "pro rata", ""], ["A1", "A", 1, "", ""], ["A2", "A", 1, "", ""],
                 ["B", "POOL", 1, "", ""]]
        self.assertEqual(lisp_deal_tree.tree_layout(nodes), {"A1": (2, 0), "A2": (2, 1), "A": (1, 0.5), "B": (1, 2), "POOL": (0, 1.25)})

    def test_the_menu_of_a_tranche_that_is_not_divided_lists_the_kinds_of_split(self):
        self.assertEqual(self.menu_texts("POOL"), [("Divide POOL by:", False), ("Sequential...", True), ("Average life...", True),
                                                   ("Pro rata...", True), ("PAC...", True), ("Floater/inverse...", True),
                                                   ("Premium/discount...", True), ("IO/PO...", True)])

    def test_the_menu_of_a_divided_tranche_offers_to_change_or_take_away_its_split(self):
        self.divide_pool()
        self.assertEqual(self.menu_texts("POOL"), [("Change the sequential split of POOL...", True),
                                                   ("Take away the split of POOL, and everything under it...", True)])

    def test_a_tranche_without_a_balance_cannot_be_divided(self):
        self.run_lisp('(define empty (new-deal "empty"))')
        with mock.patch.object(QtWidgets.QApplication, "exec", lambda application: 0):
            self.window = self.run_lisp('(deal-tree empty)')
        self.addCleanup(self.window.close)
        self.assertEqual(self.menu_texts("POOL"), [("POOL has no balance, so it cannot be divided: the collateral is entered first", False)])

    def test_the_pop_up_has_the_fields_of_the_kind_of_split(self):
        dialog = self.choose("POOL", "PAC")
        self.assertIn("Divide POOL, which has a balance of 100,000,000.00, by a PAC and companion split", self.visible_labels(dialog)[0])
        self.assertEqual([edit.text() for edit in dialog.findChildren(QtWidgets.QLineEdit) if edit.isVisible()],
                         ["POOL-PAC", "POOL-COMP", "100", "300"])
        self.assertEqual(dialog.findChildren(QtWidgets.QComboBox)[0].currentText(), "reverse")

    def test_the_tranches_can_be_added_only_after_their_sizes_are_calculated(self):
        dialog = self.choose("POOL", "Sequential")
        add = self.button(dialog, "Add the tranches to the deal")
        dialog.findChildren(QtWidgets.QPlainTextEdit)[0].setPlainText("A 60000000\nB")
        self.assertFalse(add.isEnabled())
        self.button(dialog, "Calculate the sizes").click()
        self.assertTrue(add.isEnabled())
        self.assertEqual([row[:3] for row in self.sizes_shown(dialog)], [["A", "60,000,000.00", "60.00%"], ["B", "40,000,000.00", "40.00%"]])
        self.assertEqual(len(self.window.nodes), 1)                    # (calculating changes nothing)
        dialog.findChildren(QtWidgets.QPlainTextEdit)[0].setPlainText("A 50000000\nB")
        self.assertFalse(add.isEnabled())                              # (the sizes shown are not those of the fields any more)
        self.assertIn("The fields have changed: calculate the sizes again.", self.visible_labels(dialog))
        self.button(dialog, "Calculate the sizes").click()
        add.click()
        self.assertFalse(dialog.isVisible())
        self.assertEqual([(node[0], node[2]) for node in self.window.nodes], [("POOL", 100000000.0), ("A", 50000000.0), ("B", 50000000.0)])
        self.assertEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "A")) 0)'), 50000000.0)
        self.assertEqual(self.window.statusBar().currentMessage(),
                         "Added A, B under POOL, by a sequential split. Click a tranche to divide it, or to change its split.")

    def test_what_is_wrong_is_said_in_the_pop_up(self):
        dialog = self.choose("POOL", "Floater/inverse")
        dialog.findChildren(QtWidgets.QLineEdit)[2].setText("nine")
        self.button(dialog, "Calculate the sizes").click()
        self.assertIn("nine is not a number, for Cap %", self.visible_labels(dialog))
        dialog = self.choose("POOL", "Sequential")
        self.button(dialog, "Calculate the sizes").click()             # (the default names have no balances)
        self.assertIn("POOL1 has no balance: only the last tranche can leave out its balance, and have what is left", self.visible_labels(dialog))
        self.assertFalse(self.button(dialog, "Add the tranches to the deal").isEnabled())

    def test_a_split_is_changed_in_the_pop_up_filled_in_as_it_is(self):
        self.divide_pool()
        dialog = self.choose("POOL", "Change the sequential split")
        text = dialog.findChildren(QtWidgets.QPlainTextEdit)[0]
        self.assertEqual(text.toPlainText(), "A 60000000.0\nB 40000000.0")
        text.setPlainText("A 70000000\nB")
        self.button(dialog, "Calculate the sizes").click()
        self.assertEqual(self.sizes_shown(dialog)[0][:3], ["A", "60,000,000.00", "70,000,000.00"])        # (tranche, was, balance)
        self.button(dialog, "Change the split").click()
        self.assertEqual(self.node("B")[2], 30000000.0)

    def test_a_split_is_taken_away_when_the_answer_is_yes(self):
        self.divide_pool()
        with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.No) as question:
            self.choose("POOL", "Take away")
        self.assertIn("Take away the split of POOL, and the 2 tranches under it: A, B? That cannot be undone.", question.call_args[0])
        self.assertEqual(len(self.window.nodes), 3)
        with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes):
            self.choose("POOL", "Take away")
        self.assertEqual(len(self.window.nodes), 1)
        self.assertEqual(self.window.statusBar().currentMessage(), "Took away the split of POOL, and A, B. POOL is not divided.")

    def test_a_change_made_to_the_deal_elsewhere_is_drawn(self):
        self.run_lisp('(deal-sequential! deal "POOL" (list (list "X" 10000000) (list "Y" 90000000)))')
        self.assertEqual(set(self.boxes()), {"POOL", "X", "Y"})
        self.window.close()
        self.run_lisp('(deal-delete-split! deal "POOL")')                 # (a closed window is not drawn again)
        self.assertEqual(set(self.boxes()), {"POOL", "X", "Y"})


if __name__ == "__main__":
    unittest.main()
