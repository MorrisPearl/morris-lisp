"""lib/stratify_explorer.lsp: a form in a notebook for choosing how to stratify a table -- an accordion with a section for
each column, where the user chooses how the column is stratified, what else its table is split by, and the ways it is
summarized, with their formats; the rows to use; and buttons that make the tables, show the code, and write them out --
and the stratify-all call it comes to. The widgets are worked here as the user works them in the browser: by changing
their values and clicking their buttons."""

import os
import shutil
import tempfile
import unittest

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

try:
    import ipywidgets
except ImportError:
    ipywidgets = None

LOANS = """(define loans
  (make-table "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 6.0)
              "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000)
              "age"     #(12 24 36 6 48 60 3 72 18 30)
              "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA")
              "opened"  (vector (date 2020 1 5) (date 2021 3 1) (date 2021 7 9) (date 2022 2 2) (date 2022 5 5)
                                (date 2023 1 1) (date 2023 8 8) (date 2024 2 9) (date 2024 6 6) (date 2025 1 2))))"""

NAMES = ["rate", "balance", "age", "state", "opened"]


@unittest.skipIf(ipywidgets is None, "ipywidgets is needed")
class StratifyExplorerTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "stratify_explorer.lsp")')
        self.run_lisp(LOANS)
        self.run_lisp('(define explorer (stratify-explorer loans :weight "balance" :name "loans"))')
        self.form = self.run_lisp("explorer")

    # The widgets, found through the form's own record of them.
    def part(self, name):
        """A widget of the form as a whole: weight, chart-column, charts, total, grids, export-name, warning, accordion,
        condition-rows."""
        return self.run_lisp("(stratify-explorer--state-%s (widget-tag explorer))" % name)

    def of_column(self, column, name):
        return self.run_lisp('(stratify-explorer--column-%s (stratify-explorer--find-column (widget-tag explorer) "%s"))'
                             % (name, column))

    def how(self, column):
        return self.of_column(column, "how")

    def count(self, column):
        return self.of_column(column, "count")

    def breakpoints(self, column):
        return self.of_column(column, "breakpoints")

    def accordion(self):
        return self.part("accordion")

    def section(self, column):
        return self.accordion().children[NAMES.index(column)]

    def summaries(self, column):
        return len(self.of_column(column, "rows").children)

    def summary(self, column, place):
        """(function, percentile, heading, format, x) of a column's summary: place 0 is the first, 1 the second, ..."""
        return self.of_column(column, "rows").children[place].children

    def add(self, column):
        """Click the column's button that adds a summary, and give the new one's widgets."""
        self.section(column).children[7].click()
        return self.summary(column, self.summaries(column) - 1)

    def add_split(self, column, other, way="(as in its section)", count=None, breakpoints=None):
        """Click the column's button that splits it by another column too, and choose the column and how."""
        self.section(column).children[4].click()
        row = self.of_column(column, "split-rows").children[-1].children     # ("and by", column, way, n, breakpoints, x)
        row[1].value = other
        row[2].value = way
        if count is not None:
            row[3].value = count
        if breakpoints is not None:
            row[4].value = breakpoints
        return row

    def add_condition(self, column, test, value=""):
        """Click the button that adds a condition on the rows to use, and fill it in."""
        self.form.children[3].click()
        row = self.part("condition-rows").children[-1].children               # (column, test, value, x)
        row[0].value = column
        row[1].value = test
        row[2].value = value
        return row

    def plan(self):
        bys, summaries, formats = lisp_core.pairs_to_list(self.run_lisp("(stratify-explorer-plan explorer)"))
        return self.text(bys), self.text(summaries), self.text(formats)

    def text(self, value):
        return lisp_core.to_display_string(value)

    def make_all(self):
        self.run_lisp("(stratify-explorer--make-tables (widget-tag explorer) (stratify-explorer--state-columns (widget-tag explorer)))")


class TestTheForm(StratifyExplorerTestCase):

    def test_it_begins_with_what_stratify_plan_suggests(self):
        self.assertIsInstance(self.accordion(), ipywidgets.Accordion)
        self.assertEqual(len(self.accordion().children), 5)
        self.assertEqual(self.part("weight").value, "balance")
        plan = lisp_core.pairs_to_list(self.run_lisp('(stratify-plan loans :weight "balance")'))
        bys, summaries, _ = self.plan()
        self.assertEqual(bys, self.text(plan[0]))
        self.assertEqual(summaries, self.text(plan[1]))
        self.assertEqual(self.how("balance").value, "hide")             # the weight column
        self.assertEqual(self.summary("rate", 0)[0].value, "weighted-mean")
        self.assertEqual(self.summary("rate", 0)[3].value, ".3f")
        self.assertEqual(self.summaries("rate"), 1)                     # the plan's one summary
        self.assertEqual(self.summaries("state"), 1)                    # none planned: one row, of none
        self.assertEqual(self.summary("state", 0)[0].value, "(none)")
        self.assertEqual(list(self.accordion().titles)[:2], ["rate: each; weighted-mean", "balance: hide"])
        self.assertIn("float; 10 distinct, 0 missing; from 3.25 to 7.25", self.section("rate").children[0].value)
        self.assertEqual((self.part("total").value, self.part("grids").value, self.part("charts").value), (True, False, False))
        self.assertEqual(self.part("export-name").value, "loans strata")

    def test_a_column_can_be_stratified_any_of_the_ways(self):
        self.how("rate").value = "breakpoints"
        self.breakpoints("rate").value = "4.0, 5.0 6.0"
        self.how("age").value = "equal-count"
        self.count("age").value = 3
        self.how("state").value = "top"
        self.count("state").value = 2
        self.how("opened").value = "breakpoints"
        self.breakpoints("opened").value = "2022-01-01 2024-01-01"
        self.how("balance").value = "equal-weight"
        bys, _, _ = self.plan()
        self.assertEqual(bys, '(("rate" (4.0 5.0 6.0)) ("balance" (equal-weight 5)) ("age" (equal-count 3)) '
                              '("state" (top 2)) ("opened" (2022-01-01 2024-01-01)))')
        self.assertEqual(self.accordion().titles[0], "rate: at 4.0, 5.0 6.0; weighted-mean")
        self.assertEqual(self.accordion().titles[3], "state: top 2")
        # the n box shows only for the ways that have an n, and the breakpoints only for breakpoints
        self.assertEqual(self.count("state").layout.display, None)
        self.assertEqual(self.breakpoints("state").layout.display, "none")
        self.how("state").value = "each"
        self.assertEqual(self.count("state").layout.display, "none")

    def test_breakpoints_that_are_not_numbers_are_an_error(self):
        self.how("rate").value = "breakpoints"
        self.assertLispError("(stratify-explorer-plan explorer)", "rate: type the breakpoints")
        self.breakpoints("rate").value = "4 five"
        self.assertLispError("(stratify-explorer-plan explorer)", "rate: the breakpoints are numbers, and five is not one")

    def test_a_widget_that_is_not_an_explorer_is_an_error(self):
        self.assertLispError('(stratify-explorer-plan (make-widget "Button"))', "not a form that stratify-explorer made")


class TestSummaries(StratifyExplorerTestCase):

    def test_a_summary_has_its_heading_and_format(self):
        function, percentile, heading, format_box, _ = self.add("rate")
        function.value = "mean"
        self.assertEqual((heading.value, format_box.value), ("mean rate", ".3f"))    # suggested, and the column's format
        function.value = "percentile"
        percentile.value = 90
        self.assertEqual(heading.value, "rate p90.0")
        heading.value = "rate, 90th"                                                 # typed: kept from now on
        format_box.value = ".2f"
        function.value = "weighted-percentile"
        self.assertEqual(heading.value, "rate, 90th")
        _, summaries, formats = self.plan()
        self.assertIn('("rate" weighted-mean "avg rate") ("rate" (weighted-percentile 90.0) "rate, 90th")', summaries)
        self.assertIn('("avg rate" ".3f") ("rate, 90th" ".2f")', formats)
        self.assertTrue(formats.startswith('(("count" ",d") ("percent" ".1%") ("total_balance" ",.0f")'))

    def test_any_number_of_summaries_can_be_added_and_taken_away(self):
        for function, p in (("min", None), ("percentile", 50), ("percentile", 90), ("max", None)):
            row = self.add("age")
            row[0].value = function
            if p is not None:
                row[1].value = p
        self.assertEqual(self.summaries("age"), 5)
        self.assertEqual(self.accordion().titles[2], "age: each; weighted-mean, min, percentile, percentile, max")
        _, summaries, _ = self.plan()
        self.assertIn('("age" weighted-mean "avg age") ("age" min "min age") ("age" (percentile 50.0) "age p50.0") '
                      '("age" (percentile 90.0) "age p90.0") ("age" max "max age")', summaries)
        self.assertIn("age p90.0", list(self.part("chart-column").options))
        self.summary("age", 2)[4].click()                       # the x of the 50th percentile
        self.assertEqual(self.summaries("age"), 4)
        _, summaries, _ = self.plan()
        self.assertNotIn("age p50.0", summaries)
        self.assertNotIn("age p50.0", list(self.part("chart-column").options))
        while self.summaries("age") > 0:
            self.summary("age", 0)[4].click()
        _, summaries, _ = self.plan()
        self.assertNotIn('"age"', summaries)
        self.assertEqual(self.accordion().titles[2], "age: each")

    def test_two_summaries_with_one_heading_are_warned_of_at_once(self):
        self.assertEqual(self.part("warning").value, "")
        function, _, heading, _, _ = self.add("rate")
        function.value = "mean"
        heading.value = "avg rate"
        self.assertIn('Two summaries have the heading "avg rate"', self.part("warning").value)
        self.assertEqual(list(self.part("chart-column").options).count("avg rate"), 1)
        heading.value = "plain rate"
        self.assertEqual(self.part("warning").value, "")

    def test_without_a_weight_the_weighted_ways_are_errors_that_say_which_column(self):
        self.part("weight").value = "(none)"
        self.assertLispError("(stratify-explorer-plan explorer)", "rate: weighted-mean needs a weight column")
        self.summary("rate", 0)[0].value = "mean"
        self.summary("age", 0)[0].value = "median"
        self.how("balance").value = "equal-weight"
        self.assertLispError("(stratify-explorer-plan explorer)", "balance: equal-weight buckets need a weight column")
        self.how("balance").value = "equal-count"
        _, _, formats = self.plan()
        # (choosing another function renamed the heading the plan had given: avg rate is now mean rate)
        self.assertEqual(formats, '(("count" ",d") ("percent" ".1%") ("mean rate" ".3f") ("median age" ",.2f"))')
        self.assertEqual(self.run_lisp("(stratify-explorer-weight explorer)"), lisp_core.NIL)


class TestSplitsAndRows(StratifyExplorerTestCase):

    def test_a_table_can_be_split_by_any_number_of_other_columns(self):
        self.add_split("state", "rate", "breakpoints", breakpoints="5.0")
        self.add_split("state", "opened", "year")
        self.add_split("state", "age")                                      # as in its own section: each
        bys, _, _ = self.plan()
        self.assertIn('(("state" each) ("rate" (5.0)) ("opened" year) ("age" each))', bys)
        self.assertEqual(self.accordion().titles[3], "state: each, and by rate, opened, age")
        tables = lisp_core.pairs_to_list(self.run_lisp("(stratify-explorer-tables explorer)"))
        by_state = [t for t in tables if str(lisp_core.pairs_to_list(t)[0].car) == "state"][0]
        names = [str(column.car) for column in lisp_core.pairs_to_list(by_state)]
        self.assertEqual(names[:5], ["state", "rate", "opened", "age", "count"])
        self.of_column("state", "split-rows").children[1].children[-1].click()      # the x of opened
        bys, _, _ = self.plan()
        self.assertIn('(("state" each) ("rate" (5.0)) ("age" each))', bys)
        # a split as in a section that hides its column is an error that says so
        self.add_split("state", "balance")
        self.assertLispError("(stratify-explorer-plan explorer)", "state: it is split by balance, which its own section hides")

    def test_the_rows_to_use_meet_every_condition(self):
        self.add_condition("balance", ">=", "100000")
        self.add_condition("state", "one of", "CA, NY")
        self.add_condition("opened", "<", "2023-06-01")
        rows = self.run_lisp("(stratify-explorer-rows explorer)")
        self.assertEqual(self.text(lisp_tables.table_columns(rows, "test")[0][1]), "#(3.25 4.5 5.125 6.25)")
        code = str(self.run_lisp("(stratify-explorer-code explorer)"))
        self.assertIn('(define rows\n  (table-filter loans\n    (vector-and (>= (table-column loans "balance") 100000)\n', code)
        self.assertIn('(vector-or (= (table-column loans "state") "CA") (= (table-column loans "state") "NY"))', code)
        self.assertIn('(< (table-column loans "opened") (date 2023 6 1))', code)
        self.assertIn("(stratify-all rows\n", code)
        self.run_lisp(code)
        self.assertEqual(self.text(self.run_lisp("strats")), self.text(self.run_lisp("(stratify-explorer-tables explorer)")))
        self.part("condition-rows").children[0].children[3].click()                 # the x of the balance
        self.assertEqual(len(self.part("condition-rows").children), 2)

    def test_the_tests_of_a_condition(self):
        def states_with(column, test, value=""):
            while self.part("condition-rows").children:
                self.part("condition-rows").children[0].children[3].click()
            self.add_condition(column, test, value)
            return self.text(lisp_tables.table_columns(self.run_lisp("(stratify-explorer-rows explorer)"), "t")[3][1])
        self.assertEqual(states_with("state", "=", "TX"), '#("TX" "TX")')
        self.assertEqual(states_with("state", "not =", "CA"), '#("NY" "TX" "NY" "FL" "TX" "WA")')
        self.assertEqual(states_with("rate", "<=", "4.5"), '#("CA" "NY" "CA")')
        self.assertEqual(states_with("state", "not missing"), self.text(self.run_lisp('(table-column loans "state")')))
        self.assertEqual(states_with("rate", "missing"), "#()")
        self.add_condition("rate", ">", "five")
        self.assertLispError("(stratify-explorer-rows explorer)", "rate is a column of numbers, and five is not one")

    def test_a_condition_no_row_meets_is_said(self):
        self.add_condition("balance", ">", "10000000")
        self.assertLispError("(stratify-explorer-tables explorer)", "No row meets the conditions")


class TestTablesAndCode(StratifyExplorerTestCase):

    def test_the_tables_are_stratify_alls_and_the_code_makes_them_again(self):
        self.how("state").value = "top"
        self.count("state").value = 2
        self.add("rate")[0].value = "mean"
        tables = self.text(self.run_lisp("(stratify-explorer-tables explorer)"))
        code = self.run_lisp("(stratify-explorer-code explorer)")
        self.assertTrue(str(code).startswith("(define strats\n  (stratify-all loans\n"), code)
        self.run_lisp(str(code))
        self.assertEqual(self.text(self.run_lisp("strats")), tables)
        self.printed()
        self.make_all()
        shown = self.printed()
        self.assertIn("state  count  total_balance", shown)
        self.assertIn("mean rate", shown)

    def test_a_sections_button_makes_its_table_alone(self):
        self.run_lisp("""(define shown '())
                         (define (display-table table formats) (set! shown (cons (car (car table)) shown)))""")
        self.section("age").children[8].click()
        self.assertEqual(self.text(self.run_lisp("shown")), '("age")')

    def test_the_total_row_can_be_left_out(self):
        self.part("total").value = False
        table = lisp_core.pairs_to_list(self.run_lisp("(stratify-explorer-tables explorer)"))[0]
        self.assertNotIn("total", self.text(lisp_tables.table_columns(table, "t")[0][1]))
        self.assertIn(":total #f", str(self.run_lisp("(stratify-explorer-code explorer)")))

    def test_the_tables_can_be_grids_that_sort(self):
        self.part("grids").value = True
        self.run_lisp("""(define widgets '())
                         (define (display-widget w) (set! widgets (cons w widgets)))""")
        self.make_all()
        self.assertEqual(len(lisp_core.pairs_to_list(self.run_lisp("widgets"))), 4)

    def test_the_charts_line_is_chosen_from_the_summaries(self):
        line = self.part("chart-column")
        self.assertEqual(list(line.options), ["(first summary)", "avg rate", "avg age"])
        function, _, heading, _, _ = self.add("rate")
        function.value = "mean"
        self.assertEqual(list(line.options), ["(first summary)", "avg rate", "mean rate", "avg age"])
        line.value = "mean rate"
        heading.value = "plain rate"                                   # renamed: the old name is gone, and the first is chosen
        self.assertEqual(line.value, "(first summary)")
        line.value = "avg age"
        self.assertEqual(self.run_lisp("(stratify-explorer-chart-column explorer)"), "avg age")
        self.part("charts").value = True
        self.run_lisp("""(define drawn '())
                         (define (plot-stratification table &key formats column) (set! drawn (cons column drawn)))""")
        self.make_all()
        self.assertEqual(self.text(self.run_lisp("drawn")), '("avg age" "avg age" "avg age" "avg age")')
        code = str(self.run_lisp("(stratify-explorer-code explorer)"))
        self.assertIn('(plot-stratification table :formats formats :column "avg age")', code)
        self.part("charts").value = False
        self.assertNotIn("plot-stratification", str(self.run_lisp("(stratify-explorer-code explorer)")))


class TestWritingAndSaving(StratifyExplorerTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.folder)

    def test_csv_files_a_file_for_each_table(self):
        self.add_split("state", "rate", "breakpoints", breakpoints="5.0")
        self.part("export-name").value = "my loans"
        self.run_lisp("(stratify-explorer--write-csv-files (widget-tag explorer))")
        self.assertEqual(sorted(os.listdir(self.folder)),
                         ["my_loans-age.csv", "my_loans-opened.csv", "my_loans-rate.csv", "my_loans-state-rate.csv"])
        with open(os.path.join(self.folder, "my_loans-state-rate.csv")) as f:
            self.assertTrue(f.readline().startswith("state,rate,count,total_balance,percent"))

    def test_a_google_sheet_with_a_tab_for_each_table(self):
        self.run_lisp("""(define creds "the credentials")
                         (define asked '())
                         (define (google-sheet creds title formats &rest tables)
                           (set! asked (list creds title (length tables)))
                           "https://docs.google.com/spreadsheets/d/abc")""")
        self.printed()
        self.run_lisp("(stratify-explorer--write-google-sheet (widget-tag explorer))")
        self.assertEqual(self.text(self.run_lisp("asked")), '("the credentials" "loans strata" 4)')
        self.assertIn("Wrote https://docs.google.com/spreadsheets/d/abc", self.printed())

    def test_a_report_in_markdown(self):
        self.add_condition("state", "=", "CA")
        self.run_lisp("(stratify-explorer--write-report (widget-tag explorer))")
        with open(os.path.join(self.folder, "loans_strata.md")) as f:
            report = f.read()
        self.assertTrue(report.startswith("# loans strata\n\n4 rows of loans, those that meet "
                                          '`(= (table-column loans "state") "CA")`; weighted by balance.\n\n## By rate\n\n| rate |'),
                        report[:300])
        self.assertIn("\n\n## By age\n\n", report)

    def test_what_is_chosen_is_saved_and_a_form_starts_from_it(self):
        self.how("age").value = "equal-count"
        self.count("age").value = 3
        self.add_split("state", "rate", "breakpoints", breakpoints="5.0")
        self.add("rate")[0].value = "max"
        self.add_condition("balance", ">", "60000")
        self.part("total").value = False
        self.part("charts").value = True
        self.part("chart-column").value = "max rate"
        self.run_lisp('(stratify-explorer-save explorer "saved.lsp")')
        self.run_lisp('(define again (stratify-explorer loans :name "loans" :plan "saved.lsp"))')
        self.assertEqual(self.text(self.run_lisp("(stratify-explorer-settings again)")),
                         self.text(self.run_lisp("(stratify-explorer-settings explorer)")))
        self.assertEqual(str(self.run_lisp("(stratify-explorer-code again)")), str(self.run_lisp("(stratify-explorer-code explorer)")))
        self.assertIn("max rate", str(self.run_lisp("(stratify-explorer-code again)")))
        # from a list, too; and a column the table hasn't is passed over
        self.run_lisp("""(define settings (stratify-explorer-settings explorer))
                         (define fewer (stratify-explorer (table-select loans '("rate" "balance")) :plan settings))""")
        self.assertEqual(self.text(lisp_core.pairs_to_list(self.run_lisp("(stratify-explorer-plan fewer)"))[1]),
                         '(("rate" weighted-mean "avg rate") ("rate" max "max rate"))')


class TestWhatTheButtonsSayWhenSomethingIsWrong(StratifyExplorerTestCase):

    def test_a_condition_not_yet_filled_in_is_passed_over(self):
        self.add_condition("rate", ">", "")
        self.assertEqual(lisp_tables.table_columns(self.run_lisp("(stratify-explorer-rows explorer)"), "t")[0][1].items.size, 10)
        self.assertNotIn("table-filter", str(self.run_lisp("(stratify-explorer-code explorer)")))

    def test_an_error_is_shown_as_its_message_alone(self):
        self.how("rate").value = "breakpoints"
        self.breakpoints("rate").value = "4 five"
        self.printed()
        self.form.children[4].children[0].click()                           # Make the tables
        shown = self.printed()
        self.assertEqual(shown.strip(), "rate: the breakpoints are numbers, and five is not one")


class TestNoWidgetIsClosed(unittest.TestCase if ipywidgets is None else LispTestCase):

    @unittest.skipIf(ipywidgets is None, "ipywidgets is needed")
    def test_making_the_form_closes_no_widget_the_browser_may_still_draw(self):
        """A widget that Python lets go of is closed, and a browser that hasn't drawn it yet then can't draw what holds it
        ("widget model not found"). So making the form, and working it, must let go of none but those taken away."""
        closed = []
        original = ipywidgets.Widget.close

        def close(widget):
            closed.append(type(widget).__name__)
            original(widget)
        with mock.patch.object(ipywidgets.Widget, "close", close):
            self.run_lisp('(load "stratify_explorer.lsp")')
            self.run_lisp(LOANS)
            self.run_lisp('(define explorer (stratify-explorer loans :weight "balance" :name "loans"))')
            import gc
            gc.collect()
            self.assertEqual(closed, [])
            form = self.run_lisp("explorer")
            form.children[3].click()                                      # + add a condition
            self.assertEqual(closed, [])
