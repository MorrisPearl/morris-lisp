"""The deal tree (lib/deal_tree.lsp and lisp_deal_tree.py): a window that draws a deal as a tree, with a menu on each tranche and a pop-up
for a split. First the Lisp functions the window calls, without a window; then the window itself, which is drawn by Qt off the screen
(QT_QPA_PLATFORM=offscreen), clicked and filled in the way a person does it: the menu's actions are triggered, the fields typed into and
the buttons clicked. Qt's event loop is not run (deal-tree would wait in it for the window to be closed); the pop-ups are shown instead of
waiting, and the question before taking a split away is answered by the test. Last, the kind of split that the CMO manual makes, step by step,
in "Making another kind of split": its blocks are run as they are written, and its form is used in the window's menu and pop-up."""

import os
import re
import shutil
import tempfile
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
        self.run_lisp('(split-form-apply! (split-form-named forms "Sequential") deal "POOL" %s)' % SEQUENTIAL)
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
        message = self.value('(split-form-apply! (split-form-named forms "Sequential") deal "POOL" %s)' % SEQUENTIAL)
        self.assertEqual(message, "Added A, B under POOL, by a sequential split.")
        self.assertEqual([node[0] for node in self.value('(deal-tree--nodes deal)')], ["POOL", "A", "B"])

    def test_applying_to_a_divided_tranche_changes_its_split(self):
        self.run_lisp('(split-form-apply! (split-form-named forms "Sequential") deal "POOL" %s)' % SEQUENTIAL)
        message = self.value('(split-form-apply! (split-form-named forms "Pro rata") deal "POOL" '
                             '(list (cons "tranches" "A 50000000\nB") (cons "losses" "pro-rata")))')
        self.assertTrue(message.startswith("Changed the split of POOL: it is a pro rata split into A, B"))
        self.assertEqual(self.value('(deal-tree--nodes deal)')[1], ["A", "POOL", 50000000.0, "", ""])

    def test_deleting_takes_away_the_split_and_everything_under_it(self):
        self.run_lisp('(split-form-apply! (split-form-named forms "Sequential") deal "POOL" %s)' % SEQUENTIAL)
        self.run_lisp('(deal-sequential! deal "A" (list (list "A1" 30000000) (list "A2" 30000000)))')
        self.assertEqual(self.value('(deal-tree--delete! deal "POOL")'), "Took away the split of POOL, and A, A1, A2, B. POOL is not divided.")
        self.assertEqual(len(self.value('(deal-tree--nodes deal)')), 1)

    def test_what_is_wrong_with_the_answers_is_an_error(self):
        with self.assertRaisesRegex(lisp_core.LispError, "only the last tranche can leave out its balance"):
            self.run_lisp('(deal-tree--sizes forms deal "Sequential" "POOL" '
                          '(list (cons "tranches" "A\nB") (cons "accretion" "") (cons "losses" "reverse")))')
        with self.assertRaisesRegex(lisp_core.LispError, "no kind of split called Diagonal"):
            self.run_lisp('(deal-tree--asking forms deal "Diagonal" "POOL")')


class TreeWindowActions:
    """Doing what the user does, in the window that is self.window."""

    def open_window(self, src='(deal-tree deal)'):
        """Opens the window that src makes, without waiting in Qt's event loop for it to be closed."""
        with mock.patch.object(QtWidgets.QApplication, "exec", lambda application: 0):
            self.window = self.run_lisp(src)
        self.addCleanup(self.window.close)

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

    def line_texts(self, dialog):
        """What is in the pop-up's lines to type in, in order."""
        return [edit.text() for edit in dialog.findChildren(QtWidgets.QLineEdit) if edit.isVisible()]

    def file_menu_item(self, text):
        """The item of the window's File menu that starts with text."""
        file_menu = self.window.menuBar().actions()[0].menu()
        return next(action for action in file_menu.actions() if action.text().startswith(text))


@unittest.skipIf(QtWidgets is None, "PyQt6 is needed")
class TreeWindowTest(TreeWindowActions, LispTestCase):
    """The window, drawn off the screen, and clicked as a person does."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(require "deal_tree.lsp") (define deal %s)' % psa_deal("demo", 100000000.0, 6.5, psa=150))
        self.open_window()

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
        self.assertEqual(self.line_texts(dialog), ["POOL-PAC", "POOL-COMP", "100", "300"])
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

    def test_the_window_is_not_waited_for_when_qt_draws_it_off_the_screen(self):
        """Off the screen (as here, with QT_QPA_PLATFORM=offscreen), no one could close the window, so Qt's event loop is not run: running
        it would wait for ever."""
        with mock.patch.object(QtWidgets.QApplication, "exec") as event_loop, mock.patch("builtins.print") as said:
            other = self.run_lisp("(deal-tree deal)")
        self.addCleanup(other.close)
        event_loop.assert_not_called()
        self.assertIn("off the screen", said.call_args[0][0])

    def test_the_file_menu_saves_the_deal_and_opens_one(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        saved = os.path.join(directory, "demo.deal")
        self.divide_pool()
        with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(saved[:-len(".deal")], "")) as asked:
            self.file_menu_item("Save").trigger()                    # (a name with no ending is given .deal)
        self.assertEqual(asked.call_args[0][2], os.path.join(os.getcwd(), "demo.deal"))        # (the name it suggests is the deal's)
        self.assertTrue(os.path.exists(saved))
        self.assertEqual(self.window.statusBar().currentMessage(), "Saved demo in %s." % saved)
        self.run_lisp('(save-deal (new-deal "Other 2026-2" :collateral (quote ((50000000.0 6.0 5.5 360)))) "%s")'
                      % os.path.join(directory, "other.deal"))
        with mock.patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(os.path.join(directory, "other.deal"), "")) as asked:
            self.file_menu_item("Open").trigger()
        self.assertEqual(asked.call_args[0][2], directory)                                     # (it begins where the deal was saved)
        self.assertEqual(self.window.windowTitle(), "Deal tree: Other 2026-2")
        self.assertEqual(set(self.boxes()), {"POOL"})
        self.assertEqual(self.run_lisp("(deal-name deal)"), "Other 2026-2")                   # (the variable has the deal from the file)
        self.assertEqual(self.window.statusBar().currentMessage(), "Opened Other 2026-2, from %s." % os.path.join(directory, "other.deal"))
        with mock.patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(saved, "")):
            self.file_menu_item("Open").trigger()
        self.assertEqual(set(self.boxes()), {"POOL", "A", "B"})
        self.run_lisp('(deal-sequential! deal "A" (list (list "A1" 30000000) (list "A2" 30000000)))')
        self.assertEqual(set(self.boxes()), {"POOL", "A", "B", "A1", "A2"})                  # (what changes it elsewhere is still drawn)

    def test_what_cannot_be_opened_or_saved_is_said(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        not_a_deal = os.path.join(directory, "notes.txt")
        with open(not_a_deal, "w", encoding="utf-8") as f:
            f.write("(some notes)")
        with mock.patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(not_a_deal, "")), \
                mock.patch.object(QtWidgets.QMessageBox, "warning") as warned:
            self.file_menu_item("Open").trigger()
        self.assertIn("is not a deal saved by save-deal", warned.call_args[0][2])
        self.assertIn("is not a deal saved by save-deal", self.window.statusBar().currentMessage())
        with mock.patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=("", "")) as asked:
            self.file_menu_item("Open").trigger()                     # (the window was closed without choosing a file: nothing happens)
        asked.assert_called_once()
        self.assertEqual(self.run_lisp("(deal-names deal)").car, "POOL")

    def test_the_name_suggested_for_a_file_is_the_deals(self):
        self.assertEqual(lisp_deal_tree.file_name_for("Demo 2026-1"), "Demo 2026-1.deal")
        self.assertEqual(lisp_deal_tree.file_name_for("Deal: A/B"), "Deal_ A_B.deal")

    def test_a_change_made_to_the_deal_elsewhere_is_drawn(self):
        self.run_lisp('(deal-sequential! deal "POOL" (list (list "X" 10000000) (list "Y" 90000000)))')
        self.assertEqual(set(self.boxes()), {"POOL", "X", "Y"})
        self.window.close()
        self.run_lisp('(deal-delete-split! deal "POOL")')                 # (a closed window is not drawn again)
        self.assertEqual(set(self.boxes()), {"POOL", "X", "Y"})


def manual_section_blocks(heading):
    """The ```lisp blocks of the section of the CMO manual under the ## heading (its ### sections are a part of it), in order."""
    with open(CMO_DOC, encoding="utf-8") as f:
        text = f.read()
    section = text.split("\n## %s\n" % heading, 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```lisp\n(.*?)```", section, re.S)


@unittest.skipIf(QtWidgets is None, "PyQt6 is needed")
class ManualsKindOfSplitTest(TreeWindowActions, LispTestCase):
    """The lockout split that "Making another kind of split" in lisp_cmo_manual.md makes, step by step. The section's blocks are run as
    they are written, one after another, as in a notebook (all but the ones that open a window or a widget), and then its form is used in
    the deal tree: its menu, and the pop-up that adds a lockout split and changes it."""

    def setUp(self):
        super().setUp()
        lisp_core.run_file(os.path.join(LIB, "autoloads.lsp"), self.env)     # (as at the console: a library is loaded when it is called)
        blocks = manual_section_blocks("Making another kind of split")
        self.assertGreaterEqual(len(blocks), 4)                              # (a kind that changes one thing, a lockout, its form, the window)
        for block in blocks:
            if "(deal-tree " not in block and "(display-widget" not in block:
                self.run_lisp(block)
        self.run_lisp('(define demo %s)' % psa_deal("demo", 100000000.0, 6.5, psa=150))
        self.open_window('(deal-tree demo :forms (append (standard-split-forms) (list lockout-form)))')

    def lockout(self, balance, months):
        """Chooses Lockout in the menu of POOL and types the balance of the locked-out bond and the months: the pop-up, with the sizes
        calculated."""
        dialog = self.choose("POOL", "Lockout")
        edits = [edit for edit in dialog.findChildren(QtWidgets.QLineEdit) if edit.isVisible()]
        edits[1].setText(balance)
        edits[3].setText(months)
        self.button(dialog, "Calculate the sizes").click()
        return dialog

    def principal(self, deal, name):
        """What the tranche called name of the deal (a Lisp name) was paid in principal, month by month, as a Python list."""
        return lisp_widgets.to_python(self.run_lisp('(vector->list (node-principal (get-node %s "%s")))' % (deal, name)))

    def test_the_manuals_deals_are_paid_as_it_says(self):
        self.assertEqual(self.principal("deal", "NAS"), [0.0, 0.0, 20.0, 20.0, 20.0, 0.0])
        self.assertEqual(self.principal("early", "SUP"), [20.0, 10.0, 0.0, 0.0, 0.0, 0.0])

    def test_the_new_kind_is_at_the_end_of_the_menu(self):
        self.assertEqual(self.menu_texts("POOL")[-2:], [("IO/PO...", True), ("Lockout...", True)])

    def test_its_pop_up_is_made_from_the_form_and_adds_the_two_bonds(self):
        dialog = self.choose("POOL", "Lockout")
        self.assertIn("Divide POOL, which has a balance of 100,000,000.00, by a lockout split", self.visible_labels(dialog)[0])
        self.assertEqual(self.line_texts(dialog), ["POOL-NAS", "50000000", "POOL-SUP", "60"])     # (the defaults: half, and 60 months)
        dialog = self.lockout("40,000,000", "60")
        self.assertEqual([row[:3] for row in self.sizes_shown(dialog)],
                         [["POOL-NAS", "40,000,000.00", "40.00%"], ["POOL-SUP", "60,000,000.00", "60.00%"]])
        self.button(dialog, "Add the tranches to the deal").click()
        self.assertEqual(self.window.statusBar().currentMessage(),
                         "Added POOL-NAS, POOL-SUP under POOL, by a lockout split. Click a tranche to divide it, or to change its split.")
        self.assertEqual(self.node("POOL")[3], "lockout")                    # (the label drawn on the lines of the split)
        self.run_lisp('(deal-run! demo)')
        self.assertIs(self.run_lisp('(deal-check demo)'), True)
        self.assertEqual(self.run_lisp('(vector-ref (node-principal (get-node demo "POOL-NAS")) 59)'), 0.0)      # (the last month locked out)
        self.assertGreater(self.run_lisp('(vector-ref (node-principal (get-node demo "POOL-NAS")) 60)'), 0.0)

    def test_a_lockout_split_is_changed_in_its_pop_up_filled_in_as_it_is(self):
        self.button(self.lockout("40000000", "60"), "Add the tranches to the deal").click()
        self.assertEqual(self.menu_texts("POOL"), [("Change the lockout split of POOL...", True),
                                                   ("Take away the split of POOL, and everything under it...", True)])
        dialog = self.choose("POOL", "Change the lockout split")
        self.assertEqual(self.line_texts(dialog), ["POOL-NAS", "40000000", "POOL-SUP", "60"])     # (what :describe says)
        dialog.findChildren(QtWidgets.QLineEdit)[3].setText("36")
        self.button(dialog, "Calculate the sizes").click()
        self.button(dialog, "Change the split").click()
        self.assertEqual(self.run_lisp('(lockout-split-months (node-split (get-node demo "POOL")))'), 36)

    def test_what_the_form_and_the_kind_refuse_is_said_in_the_pop_up(self):
        dialog = self.lockout("100,000,000", "60")
        self.assertIn("the locked-out bond's balance is more than 0 and less than the 100,000,000.00 that is divided", self.visible_labels(dialog))
        self.assertFalse(self.button(dialog, "Add the tranches to the deal").isEnabled())
        dialog = self.lockout("40,000,000", "-3")
        self.assertIn("a lockout is a whole number of months, 0 or more, not -3", self.visible_labels(dialog))     # (from check-split)
        self.assertEqual(len(self.window.nodes), 1)


if __name__ == "__main__":
    unittest.main()
