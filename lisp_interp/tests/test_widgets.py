"""Widgets for the notebook (lisp_widgets.py, lib/widgets.lsp): making them, reading and changing them, the functions called
when they change, and the grid for editing a table. The grid is tested the way the browser works it: by sending the message
a cell edit makes. A widget works without a notebook, so most of this needs none; the last tests run cells in a real kernel."""

import contextlib
import shutil
import tempfile
import unittest

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase
from test_debugging import start_test_kernel

import lisp_widgets

try:
    import ipywidgets
except ImportError:
    ipywidgets = None

try:
    import ipydatagrid
except ImportError:
    ipydatagrid = None


@unittest.skipIf(ipywidgets is None, "ipywidgets is needed")
class TestWidgets(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "widgets.lsp")')

    def printing(self, src):
        """What the Lisp in src displays."""
        return self.capture(lambda: self.run_lisp(src))

    def test_make_widget_makes_the_ipywidgets_class_with_the_attributes_given(self):
        w = self.run_lisp('(make-widget "IntSlider" :min 0 :max 10 :value 5 :description "n")')
        self.assertIsInstance(w, ipywidgets.IntSlider)
        self.assertEqual((w.min, w.max, w.value, w.description), (0, 10, 5, "n"))

    def test_an_attribute_written_with_hyphens_is_the_one_with_underscores(self):
        w = self.run_lisp('(make-widget "Button" :button-style "danger")')
        self.assertEqual(w.button_style, "danger")

    def test_a_list_is_a_list_a_hash_table_a_dict_and_the_empty_list_an_empty_one_where_none_is_not_allowed(self):
        self.run_lisp('(define a (make-widget "Label")) (define b (make-widget "Label"))')
        box = self.run_lisp('(make-widget "VBox" :children (list a b))')
        self.assertEqual(len(box.children), 2)
        self.assertEqual(self.run_lisp('(make-widget "VBox" :children (list))').children, ())
        self.run_lisp('(define h (make-hash-table)) (hash-table-set! h "description_width" "initial")')
        self.assertEqual(self.run_lisp('(make-widget "IntSlider" :style h)').style.description_width, "initial")

    def test_a_class_or_an_attribute_that_is_not_there_is_an_error_that_suggests_the_nearest(self):
        self.assertLispError('(make-widget "IntSlidr")', "did you mean IntSlider")
        self.assertLispError('(make-widget "IntSlider" :mn 2)', "did you mean min")
        self.assertLispError('(make-widget "IntSlider" :min "x")', "expected an int")
        self.assertLispError('(make-widget "IntSlider" :min)', ":name value pairs")
        self.assertLispError('(make-widget "IntSlider" "min" 2)', "expected a keyword")
        self.assertLispError('(make-widget "Layout" :_dom_classes 2)', "no attribute")

    def test_widget_get_and_widget_set_read_and_change_an_attribute(self):
        self.run_lisp('(define s (make-widget "IntSlider" :value 3))')
        self.assertShows('(widget-get s "value")', "3")
        self.run_lisp('(widget-set! s "value" 8)')
        self.assertShows('(widget-get s "value")', "8")
        self.assertShows('(widget-get (make-widget "Dropdown" :options (list "a" "b")) "options")', '("a" "b")')
        self.assertShows('(widget-get (make-widget "Text") "value")', '""')
        self.assertLispError('(widget-set! s "value" "a")', "expected an int")
        self.assertLispError('(widget-get s "nonsense")', "no attribute")
        self.assertLispError('(widget-get 5 "value")', "expected a widget")

    def test_a_function_is_called_with_the_new_value_when_the_value_changes_by_the_user_or_by_widget_set(self):
        self.run_lisp('(define s (make-widget "IntSlider")) '
                      '(widget-on-change s "value" (lambda (v) (display (format "value {}\\n" v))))')
        self.assertEqual(self.printing('(widget-set! s "value" 4)'), "value 4\n")
        slider = self.env[lisp_core.Symbol("s")]
        self.assertEqual(self.capture(lambda: setattr(slider, "value", 6)), "value 6\n")

    def capture(self, python_function):
        """What the function makes the Lisp display (outside a notebook, an Output widget captures nothing), then what it
        prints as Python: the report of an error in a callback."""
        self.out.clear()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            python_function()
        return self.printed() + printed.getvalue()

    def test_the_context_is_passed_as_the_last_argument_if_one_is_given(self):
        self.run_lisp('(define b (make-widget "Button")) (define s (make-widget "IntSlider"))'
                      '(widget-on-click b (lambda (where) (display (list "clicked" where))) :context "the button")'
                      '(widget-on-change s "value" (lambda (v where) (display (list v where))) :context (list 1 2))')
        self.assertEqual(self.capture(self.env[lisp_core.Symbol("b")].click), '("clicked" "the button")')
        self.assertEqual(self.printing('(widget-set! s "value" 4)'), '(4 (1 2))')

    def test_a_click_calls_the_function(self):
        self.run_lisp('(define b (make-widget "Button")) (widget-on-click b (lambda () (display "clicked")))')
        self.assertEqual(self.capture(self.env[lisp_core.Symbol("b")].click), "clicked")
        self.assertLispError('(widget-on-click (make-widget "IntSlider") (lambda () 1))', "no click")

    def test_an_error_in_the_function_is_reported_and_does_not_stop_the_widget(self):
        self.run_lisp('(define b (make-widget "Button")) (widget-on-click b (lambda () (error "boom")))')
        shown = self.capture(self.env[lisp_core.Symbol("b")].click)
        self.assertIn("Error: boom", shown)

    def test_what_a_function_displays_goes_to_the_output_widget_it_is_given(self):
        entered = []

        class FakeOutput(ipywidgets.Output):
            def __enter__(self):
                entered.append("in")

            def __exit__(self, *details):
                entered.append("out")

        self.env[lisp_core.Symbol("out")] = FakeOutput()
        self.run_lisp('(define b (make-widget "Button")) (widget-on-click b (lambda () (error "boom")) :output out)')
        shown = self.capture(self.env[lisp_core.Symbol("b")].click)
        self.assertEqual(entered, ["in", "out"])
        self.assertIn("Error: boom", shown)
        self.assertLispError('(widget-on-click b (lambda () 1) :output 5)', "Output widget")
        self.assertLispError('(widget-on-click b (lambda () 1) :out out)', "isn't an option")
        self.assertLispError('(widget-on-click b (lambda () 1) :output)', ":name value pairs")

    def test_widget_capture_runs_a_function_inside_the_output_widget_and_widget_clear_empties_it(self):
        self.run_lisp('(define out (make-widget "Output"))')
        self.assertShows('(widget-capture out (lambda () 42))', "42")
        out = self.env[lisp_core.Symbol("out")]
        with mock.patch.object(out, "clear_output") as cleared:
            self.run_lisp("(widget-clear out)")
        cleared.assert_called_once()
        self.assertLispError('(widget-capture 5 (lambda () 1))', "Output widget")

    def test_widget_link_links_the_two_in_the_browser(self):
        self.run_lisp('(define a (make-widget "IntSlider")) (define b (make-widget "IntSlider"))')
        link = self.run_lisp('(widget-link a "value" b "value")')
        self.assertIsInstance(link, ipywidgets.widgets.widget_link.Link)

    def test_widget_close_closes_it(self):
        self.run_lisp('(define s (make-widget "IntSlider")) (widget-close s)')
        self.assertFalse(self.env[lisp_core.Symbol("s")].comm)

    def test_display_widget_hands_the_widget_to_the_environment_and_a_console_cannot_show_one(self):
        self.assertLispError('(display-widget (make-widget "IntSlider"))', "only a Jupyter notebook")
        shown = []
        env = lisp_builtins.make_global_env(widget=shown.append)
        for expr in lisp_core.parse('(display-widget (make-widget "IntSlider"))'):
            lisp_core.seval(expr, env)
        self.assertIsInstance(shown[0], ipywidgets.IntSlider)
        self.assertLispError("(display-widget 5)", "expected a widget")

    # --- lib/widgets.lsp ---

    def test_a_slider_is_of_whole_numbers_if_its_ends_and_step_are(self):
        self.assertIsInstance(self.run_lisp("(widget-slider 1 30 :value 15)"), ipywidgets.IntSlider)
        self.assertIsInstance(self.run_lisp("(widget-slider 0 1.0 :step 0.1)"), ipywidgets.FloatSlider)
        w = self.run_lisp('(widget-slider 1 30 :value 15 :description "years")')
        self.assertEqual((w.min, w.max, w.value, w.description, w.continuous_update), (1, 30, 15, "years", False))
        self.assertEqual(self.run_lisp("(widget-slider 3 9)").value, 3)

    def test_the_widgets_of_the_library_call_their_function_when_they_change(self):
        self.run_lisp('(define s (widget-slider 1 30 :on-change (lambda (v) (display (list "slider" v)))))'
                      '(define d (widget-dropdown (list "a" "b") :on-change (lambda (v) (display (list "drop" v)))))'
                      '(define c (widget-checkbox :on-change (lambda (v) (display (list "check" v)))))'
                      '(define t (widget-text :on-change (lambda (v) (display (list "text" v)))))')
        self.assertEqual(self.printing('(widget-set! s "value" 5)'), '("slider" 5)')
        self.assertEqual(self.printing('(widget-set! d "value" "b")'), '("drop" "b")')
        self.assertEqual(self.printing('(widget-set! c "value" #t)'), '("check" #t)')
        self.assertEqual(self.printing('(widget-set! t "value" "hi")'), '("text" "hi")')

    def test_the_other_widgets_of_the_library(self):
        self.assertEqual(self.run_lisp('(widget-dropdown (list "a" "b") :value "b")').value, "b")
        self.assertEqual(self.run_lisp('(widget-dropdown (list "a" "b"))').value, "a")
        button = self.run_lisp('(widget-button "go" (lambda () (display "went")) :button-style "success")')
        self.assertEqual((button.description, button.button_style), ("go", "success"))
        self.assertEqual(self.capture(button.click), "went")
        self.assertIsInstance(self.run_lisp("(widget-output)"), ipywidgets.Output)
        self.run_lisp("(define s (widget-slider 1 2)) (define d (widget-checkbox))")
        self.assertIsInstance(self.run_lisp("(widget-column s d)"), ipywidgets.VBox)
        self.assertEqual(len(self.run_lisp("(widget-row s d)").children), 2)
        self.assertEqual(self.run_lisp('(widget-text :value "x" :placeholder "p")').placeholder, "p")


@unittest.skipIf(ipydatagrid is None, "ipydatagrid is needed")
class TestTableGrid(LispTestCase):

    TABLE = '''(define t (make-table "id" (vector "a" "b" "c")
                                     "bal" (vector 100.5 200.0 300.25)
                                     "n" #(1 2 3)
                                     "d" (vector (date 2026 1 5) (date 2026 2 6) (date 2026 3 7))))'''

    def setUp(self):
        super().setUp()
        self.run_lisp(self.TABLE)
        self.grid = self.run_lisp("(table-grid t)")
        self.env[lisp_core.Symbol("g")] = self.grid

    def edit(self, row, column_index, value):
        """The message the browser sends when the user types a value into a cell."""
        self.grid._DataGrid__handle_custom_msg(
            None, {"event_type": "cell-changed", "row": row, "column_index": column_index, "value": value}, [])

    def test_the_grid_shows_the_table_and_can_be_edited(self):
        self.assertIsInstance(self.grid, ipydatagrid.DataGrid)
        self.assertTrue(self.grid.editable)
        self.assertEqual(list(self.grid.data.columns), ["id", "bal", "n", "d"])
        self.assertEqual(list(self.grid.data["bal"]), [100.5, 200.0, 300.25])
        self.assertEqual(list(self.grid.data["d"]), ["2026-01-05", "2026-02-06", "2026-03-07"])
        self.assertFalse(self.run_lisp("(table-grid t :editable #f)").editable)

    def test_a_float32_column_shows_the_numbers_as_they_were_written(self):
        self.run_lisp("(define f (make-table \"x\" (vector 0.1 0.2)))")
        self.assertEqual(list(self.run_lisp("(table-grid f)").data["x"]), [0.1, 0.2])

    def test_grid_table_without_edits_is_the_table(self):
        self.assertShows("(equal? (grid-table g) t)", "#t")

    def test_the_edits_are_in_the_table_that_grid_table_gives_and_the_other_cells_are_as_they_were(self):
        self.edit(1, 1, 250.5)
        self.edit(0, 0, "zz")
        self.edit(2, 3, "2026-12-25")
        self.edit(0, 2, 7)
        self.assertShows("(grid-table g)", '(("id" . #("zz" "b" "c")) ("bal" . #(100.5 250.5 300.25)) '
                                           '("n" . #(7 2 3)) ("d" . #(2026-01-05 2026-02-06 2026-12-25)))')
        self.assertShows('(table-column t "bal")', "#(100.5 200.0 300.25)")     # (the table the grid was made from is not changed)

    def test_each_column_keeps_its_type(self):
        self.edit(0, 1, 5.5)
        self.edit(0, 2, 9)
        table = self.run_lisp("(grid-table g)")
        types = {str(p.car): p.cdr.items.dtype for p in lisp_core.pairs_to_list(table)}
        self.assertEqual(str(types["bal"]), "float32")
        self.assertEqual(str(types["n"]), "int32")
        self.assertEqual(str(types["id"]), "object")

    def test_a_missing_value_is_an_empty_cell_and_stays_missing_unless_it_is_edited(self):
        self.run_lisp('(define m (make-table "x" #(1.5 2.5) "s" (vector "a" "b")))')
        grid = self.run_lisp("(table-grid m)")
        self.assertEqual(list(grid.data["x"]), [1.5, 2.5])
        self.env[lisp_core.Symbol("h")] = grid
        grid._DataGrid__handle_custom_msg(None, {"event_type": "cell-changed", "row": 0, "column_index": 0, "value": None}, [])
        self.assertShows('(vector-nan? (table-column (grid-table h) "x"))', "#(1 0)")

    def test_a_value_that_does_not_fit_its_column_is_an_error_that_says_where(self):
        self.edit(0, 1, "lots")
        self.assertLispError("(grid-table g)", "column bal, row 0")
        self.edit(0, 1, 5.5)
        self.edit(1, 2, 2.5)
        self.assertLispError("(grid-table g)", "column n, row 1: 2.5 is not a whole number")
        self.edit(1, 2, 2)
        self.edit(2, 3, "next week")
        self.assertLispError("(grid-table g)", "not a date written YYYY-MM-DD")

    def test_grid_on_edit_is_called_with_the_column_the_row_and_the_value(self):
        self.run_lisp('(grid-on-edit g (lambda (column row value) (display (list column row value))))')
        self.out.clear()
        self.edit(1, 1, 250.5)
        self.edit(2, 3, "2026-12-25")
        self.edit(0, 0, "zz")
        self.assertEqual(self.printed(), '("bal" 1 250.5)("d" 2 2026-12-25)("id" 0 "zz")')

    def test_the_context_of_grid_on_edit_is_the_last_argument_so_one_function_can_tell_the_grids_apart(self):
        self.run_lisp('(define other (table-grid (make-table "k" #(1 2))))')
        other = self.env[lisp_core.Symbol("other")]
        self.run_lisp('(define (heard column row value where) (display (list where column row value)))'
                      '(grid-on-edit g heard :context "loans")(grid-on-edit other heard :context "others")')
        self.out.clear()
        self.edit(1, 1, 250.5)
        other._DataGrid__handle_custom_msg(None, {"event_type": "cell-changed", "row": 0, "column_index": 0, "value": 9}, [])
        self.assertEqual(self.printed(), '("loans" "bal" 1 250.5)("others" "k" 0 9)')

    def click(self, row, column_index, value, primary_key_row=None, region="body"):
        """The message the browser sends when the user clicks a cell."""
        columns = list(self.grid.data.columns)
        self.grid._DataGrid__handle_custom_msg(None, {
            "event_type": "cell-click", "region": region, "column": columns[column_index] if column_index >= 0 else None,
            "column_index": column_index, "row": row, "primary_key_row": row if primary_key_row is None else primary_key_row,
            "cell_value": value}, [])

    def test_grid_on_click_is_called_with_the_column_the_row_and_the_value_of_the_cell_clicked(self):
        self.run_lisp('(grid-on-click g (lambda (column row value) (display (list column row value))))')
        self.out.clear()
        self.click(1, 1, 200.0)
        self.click(2, 0, "c")
        self.click(0, 3, "2026-01-05")
        self.assertEqual(self.printed(), '("bal" 1 200.0)("id" 2 "c")("d" 0 2026-01-05)')

    def test_grid_on_click_says_the_place_in_the_table_when_the_grid_is_sorted_and_ignores_the_headings(self):
        self.run_lisp('(grid-on-click g (lambda (column row value) (display (list column row value))))')
        self.out.clear()
        self.click(0, 1, 300.25, primary_key_row=2)           # (the top row of a grid sorted the other way round)
        self.click(0, 1, None, region="column-header")
        self.click(1, -1, None, region="row-header")
        self.click(0, -1, None, region="corner-header")
        self.assertEqual(self.printed(), '("bal" 2 300.25)')

    def test_grid_on_click_takes_a_context_and_an_output_widget(self):
        self.run_lisp('(grid-on-click g (lambda (column row value where) (display (list where row))) :context "loans")')
        self.out.clear()
        self.click(1, 1, 200.0)
        self.assertEqual(self.printed(), '("loans" 1)')
        self.assertLispError("(grid-on-click g (lambda () 1) :output 5)", "Output widget")
        self.assertLispError("(grid-on-click g (lambda () 1) :where 5)", "isn't an option")
        self.assertLispError("(grid-on-click 5 (lambda () 1))", "made by table-grid")
        self.assertLispError("(grid-on-click g 5)", "expected a function")

    def test_grid_set_table_shows_another_table_and_forgets_the_edits(self):
        self.edit(0, 0, "zz")
        self.run_lisp('(grid-set-table! g (make-table "k" #(1 2) "v" (vector "p" "q")))')
        self.assertEqual(list(self.grid.data.columns), ["k", "v"])
        self.assertShows("(grid-table g)", '(("k" . #(1 2)) ("v" . #("p" "q")))')
        self.edit(1, 1, "z")
        self.assertShows("(grid-table g)", '(("k" . #(1 2)) ("v" . #("p" "z")))')

    def test_other_attributes_of_the_grid_are_given_by_keyword(self):
        grid = self.run_lisp("(table-grid t :base-row-size 40 :auto-fit-columns #t)")
        self.assertEqual(grid.base_row_size, 40)
        self.assertTrue(grid.auto_fit_columns)
        self.assertLispError("(table-grid t :nonsense 1)", "no attribute")

    def test_the_arguments_are_checked(self):
        self.assertLispError("(table-grid 5)", "not a table")
        self.assertLispError("(table-grid '())", "no columns")
        self.assertLispError("(grid-table 5)", "made by table-grid")
        self.assertLispError("(grid-on-edit 5 (lambda () 1))", "made by table-grid")
        self.assertLispError('(grid-set-table! g 5)', "not a table")
        with mock.patch.object(lisp_widgets, "EDIT_ROWS_LIMIT", 2):
            self.assertLispError("(table-grid t)", "more than a grid can carry")


class TestWidgetsInAKernel(unittest.TestCase):
    """Widgets in a real Jupyter kernel, worked as the browser works them: by the messages a click and a change make."""

    @classmethod
    def setUpClass(cls):
        if ipywidgets is None:
            raise unittest.SkipTest("ipywidgets is needed")
        cls.tmp = tempfile.mkdtemp()
        cls.frontend = start_test_kernel(cls.tmp, "lisp-widget-test")

    @classmethod
    def tearDownClass(cls):
        cls.frontend.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.fe = self.frontend
        self.fe.widgets.clear()
        self.fe.outputs.clear()

    def send(self, comm_id, data):
        """Send what the browser sends to a widget, wait for the kernel to be done with it, and return the text it wrote.
        (The browser puts that text in the Output widget that the widget names: what is written is a stream message
        that has the browser's message as its parent.)"""
        message = self.fe.kc.session.msg("comm_msg", {"comm_id": comm_id, "data": data})
        cell = self.fe.Cell(message["header"]["msg_id"])
        self.fe.cells[cell.msg_id] = cell
        self.fe.kc.shell_channel.send(message)
        self.fe.wait_for(lambda: cell.done)
        return "".join(cell.streams)

    def change(self, comm_id, state):
        return self.send(comm_id, {"method": "update", "state": state, "buffer_paths": []})

    def click(self, comm_id):
        return self.send(comm_id, {"method": "custom", "content": {"event": "click"}})

    def test_a_cell_whose_value_is_a_widget_shows_it(self):
        cell = self.fe.run('(make-widget "IntSlider" :description "years")')
        self.assertEqual(cell.errors, [])
        self.assertEqual(cell.results, [])                      # (not the text of an object)
        self.assertIn(("IntSliderModel", "years"), [(w[1], w[2]) for w in self.fe.widgets])

    def test_display_widget_shows_a_widget(self):
        self.fe.run('(display-widget (make-widget "Button" :description "go-now"))')
        self.assertTrue(self.fe.buttons("go-now"))

    def test_a_click_and_a_change_in_the_browser_call_the_lisp_functions_and_their_output_goes_to_the_output_widget(self):
        cell = self.fe.run('''
          (load "widgets.lsp")
          (define out (widget-output))
          (define slider (widget-slider 1 10 :value 2 :description "sl" :continuous-update #t
                          :on-change (lambda (v) (display (format "slider {}\\n" v)))
                          :output out))
          (define bad (widget-button "oops" (lambda () (error "boom")) :output out))
          (define good (widget-button "yes" (lambda () (display "clicked\\n")) :output out))
          (display-widget (widget-column slider good bad out))''')
        self.assertEqual(cell.errors, [])
        fe = self.fe
        fe.process(0.3)
        slider = [w[0] for w in fe.widgets if w[1] == "IntSliderModel"][0]
        self.assertEqual(self.change(slider, {"value": 7}), "slider 7\n")
        self.assertEqual(self.click(fe.buttons("yes")[0]), "clicked\n")
        self.assertIn("Error: boom", self.click(fe.buttons("oops")[0]))
        again = fe.run("(widget-get slider \"value\")")             # (and the kernel is still working)
        self.assertEqual(again.results, ["7"])


if __name__ == "__main__":
    unittest.main()
