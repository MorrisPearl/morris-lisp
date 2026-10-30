"""lib/stratify_explorer.lsp: a form in a notebook for choosing how to stratify a table -- an accordion with a section for
each column, where the user chooses how the column is stratified, up to two ways it is summarized, and their formats --
and the stratify-all call that it comes to. The widgets are worked here as the user works them in the browser: by
changing their values."""

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


@unittest.skipIf(ipywidgets is None, "ipywidgets is needed")
class TestStratifyExplorer(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "stratify_explorer.lsp")')
        self.run_lisp(LOANS)
        self.run_lisp('(define explorer (stratify-explorer loans :weight "balance" :name "loans"))')
        self.form = self.run_lisp("explorer")

    # The parts of the form: a row of the weight, Charts, and the two buttons; the accordion; the output.
    def top(self, place):
        return self.form.children[0].children[place]

    def accordion(self):
        return self.form.children[1]

    def section(self, column):
        names = ["rate", "balance", "age", "state", "opened"]
        return self.accordion().children[names.index(column)]

    def how(self, column):
        return self.section(column).children[2].children[0]

    def count(self, column):
        return self.section(column).children[2].children[1]

    def breakpoints(self, column):
        return self.section(column).children[2].children[2]

    def summary(self, column, place):
        """(function, percentile, heading, format) of a column's summary: place 0 is the first, 1 the second."""
        return self.section(column).children[4 + place].children

    def plan(self):
        bys, summaries, formats = lisp_core.pairs_to_list(self.run_lisp("(stratify-explorer-plan explorer)"))
        return self.show_value(bys), self.show_value(summaries), self.show_value(formats)

    def show_value(self, value):
        return lisp_core.to_display_string(value)

    def test_it_begins_with_what_stratify_plan_suggests(self):
        self.assertIsInstance(self.accordion(), ipywidgets.Accordion)
        self.assertEqual(len(self.accordion().children), 5)
        self.assertEqual(self.top(0).value, "balance")
        plan = self.run_lisp('(stratify-plan loans :weight "balance")')
        bys, summaries, _ = self.plan()
        self.assertEqual(bys, self.show_value(lisp_core.pairs_to_list(plan)[0]))
        self.assertEqual(summaries, self.show_value(lisp_core.pairs_to_list(plan)[1]))
        self.assertEqual(self.how("balance").value, "hide")             # the weight column
        self.assertEqual(self.summary("rate", 0)[0].value, "weighted-mean")
        self.assertEqual(self.summary("rate", 0)[3].value, ".3f")
        self.assertEqual(self.summary("rate", 1)[0].value, "(none)")
        self.assertEqual(list(self.accordion().titles)[:2], ["rate: each; weighted-mean", "balance: hide"])
        self.assertIn("float; 10 distinct, 0 missing; from 3.25 to 7.25", self.section("rate").children[0].value)

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

    def test_a_column_can_be_summarized_two_ways_each_with_its_heading_and_format(self):
        function, percentile, heading, format_box = self.summary("rate", 1)
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

    def test_the_tables_are_stratify_alls_and_the_code_makes_them_again(self):
        self.how("state").value = "top"
        self.count("state").value = 2
        self.summary("rate", 1)[0].value = "mean"
        tables = self.show_value(self.run_lisp("(stratify-explorer-tables explorer)"))
        code = self.run_lisp("(stratify-explorer-code explorer)")
        self.assertTrue(str(code).startswith("(define strats\n  (stratify-all loans\n"), code)
        self.run_lisp(str(code))
        self.assertEqual(self.show_value(self.run_lisp("strats")), tables)
        self.assertEqual(self.run_lisp("(stratify-explorer-weight explorer)"), "balance")
        self.printed()                                          # (what the code displayed)
        self.run_lisp("(stratify-explorer--make-tables (widget-tag explorer) #t)")
        shown = self.printed()
        self.assertIn("state  count  total_balance", shown)
        self.assertIn("mean rate", shown)

    def test_without_a_weight_the_weighted_ways_are_errors_that_say_which_column(self):
        self.top(0).value = "(none)"
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

    def test_breakpoints_that_are_not_numbers_are_an_error(self):
        self.how("rate").value = "breakpoints"
        self.assertLispError("(stratify-explorer-plan explorer)", "rate: type the breakpoints")
        self.breakpoints("rate").value = "4 five"
        self.assertLispError("(stratify-explorer-plan explorer)", "rate: the breakpoints are numbers, and five is not one")

    def test_a_widget_that_is_not_an_explorer_is_an_error(self):
        self.assertLispError('(stratify-explorer-plan (make-widget "Button"))', "not a form that stratify-explorer made")

    def test_the_charts_line_is_chosen_from_the_summaries(self):
        line = self.top(1)
        self.assertEqual(line.description, "chart line")
        self.assertEqual(list(line.options), ["(first summary)", "avg rate", "avg age"])
        function, _, heading, _ = self.summary("rate", 1)
        function.value = "mean"                                        # a new summary is a new choice
        self.assertEqual(list(line.options), ["(first summary)", "avg rate", "mean rate", "avg age"])
        line.value = "mean rate"
        heading.value = "plain rate"                                   # renamed: the old name is gone, and the first is chosen
        self.assertEqual(list(line.options), ["(first summary)", "avg rate", "plain rate", "avg age"])
        self.assertEqual(line.value, "(first summary)")
        self.assertEqual(self.run_lisp("(stratify-explorer-chart-column explorer)"), lisp_core.NIL)
        line.value = "avg age"
        self.assertEqual(self.run_lisp("(stratify-explorer-chart-column explorer)"), "avg age")
        # the charts draw it, and the code says so, when Charts is ticked
        self.top(2).value = True
        self.run_lisp("""(define drawn '())
                         (define (plot-stratification table &key formats column) (set! drawn (cons column drawn)))""")
        self.run_lisp("(stratify-explorer--make-tables (widget-tag explorer) #t)")
        self.assertEqual(self.show_value(self.run_lisp("drawn")), '("avg age" "avg age" "avg age" "avg age")')       # (a chart for each of the four tables)
        code = str(self.run_lisp("(stratify-explorer-code explorer)"))
        self.assertIn('(plot-stratification table :formats formats :column "avg age")', code)
        line.value = "(first summary)"
        self.assertIn("(plot-stratification table :formats formats))", str(self.run_lisp("(stratify-explorer-code explorer)")))
        self.top(2).value = False
        self.assertNotIn("plot-stratification", str(self.run_lisp("(stratify-explorer-code explorer)")))
