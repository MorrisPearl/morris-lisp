"""A first look at a table: table-profile, table-missing, table-outliers, and plot-stratification."""

import math

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class ExploreTestCase(LispTestCase):
    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define t
            (make-table "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 5000000 nan 80000)
                        "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 6.0 nan nan)
                        "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" nan "OR" "NV")
                        "first"   (vector (date 2020 1 1) (date 2020 2 1) (date 2021 1 1) (date 2021 2 1)
                                          (date 2022 1 1) (date 2022 2 1) (date 2023 1 1) (date 2023 2 1)
                                          (date 2024 1 1) nan nan (date 2025 2 1))))""")

    def column(self, table, name):
        return self.show('(table-column %s "%s")' % (table, name))


class TestTableProfile(ExploreTestCase):
    def test_a_row_for_each_column(self):
        self.assertEqual(self.column("(table-profile t)", "column"), '#("balance" "rate" "state" "first")')
        self.assertEqual(self.column("(table-profile t)", "kind"), '#("integer" "float" "text" "date")')
        self.assertEqual(self.column("(table-profile t)", "missing"), "#(1 2 1 2)")
        self.assertEqual(self.column("(table-profile t)", "distinct"), "#(11 10 6 10)")

    def test_integers_are_told_from_other_numbers(self):
        self.run_lisp('''(define n (make-table "whole" #(1 2 3) "fraction" #(1 2.5 3) "gap" #(1 nan 3) "big" #(1e12 2 3)))''')
        self.assertEqual(self.column("(table-profile n)", "kind"), '#("integer" "float" "integer" "integer")')

    def test_numbers_have_their_statistics_and_other_columns_a_range(self):
        profile = "(table-profile t)"
        self.assertEqual(self.run_lisp('(vector-ref (table-column %s "min") 0)' % profile), 60000.0)
        self.assertEqual(self.run_lisp('(vector-ref (table-column %s "median") 1)' % profile), 5.875)
        self.assertTrue(math.isnan(self.run_lisp('(vector-ref (table-column %s "mean") 2)' % profile)))
        self.assertEqual(self.column(profile, "range"), '#("" "" "CA to TX" "2020-01-01 to 2025-02-01")')

    def test_the_most_common_value(self):
        self.assertEqual(self.column("(table-profile t)", "most common"), '#("100000.0" "3.25" "CA" "2020-01-01")')

    def test_an_empty_column(self):
        self.run_lisp('(define e (make-table "x" #(nan nan)))')
        self.assertEqual(self.column("(table-profile e)", "distinct"), "#(0)")
        self.assertEqual(self.column("(table-profile e)", "most common"), '#("")')


class TestTableMissing(ExploreTestCase):
    def test_a_row_for_each_pattern_most_common_first(self):
        self.assertEqual(self.column("(table-missing t)", "missing"),
                         '#("none" "state, first" "balance, rate, first" "rate")')
        self.assertEqual(self.column("(table-missing t)", "rows"), "#(9 1 1 1)")

    def test_the_percents(self):
        percent = self.run_lisp('(vector-ref (table-column (table-missing t) "percent") 0)')
        self.assertAlmostEqual(percent, 0.75)

    def test_a_table_with_nothing_missing(self):
        self.run_lisp('(define whole (make-table "x" #(1 2 3)))')
        self.assertEqual(self.column("(table-missing whole)", "missing"), '#("none")')


class TestTableOutliers(ExploreTestCase):
    def test_the_lowest_and_highest_of_each_number_column(self):
        outliers = "(table-outliers t :count 2)"
        self.assertEqual(self.column(outliers, "column"),
                         '#("balance" "balance" "balance" "balance" "rate" "rate" "rate" "rate")')
        self.assertEqual(self.column(outliers, "side"), '#("low" "low" "high" "high" "low" "low" "high" "high")')
        self.assertEqual(self.column(outliers, "row"), "#(7 11 9 6 0 8 7 6)")
        self.assertEqual(self.run_lisp('(vector-ref (table-column %s "value") 2)' % outliers), 5000000.0)

    def test_how_far_from_the_rest(self):
        spread = self.run_lisp('(vector-ref (table-column (table-outliers t :count 1) "spread") 1)')
        self.assertGreater(spread, 20)                  # 5,000,000 is far from the rest

    def test_a_value_is_not_shown_as_both_low_and_high(self):
        self.run_lisp('(define few (make-table "x" #(1 2 3)))')
        self.assertEqual(self.column("(table-outliers few :count 5)", "row"), "#(0 1 2)")

    def test_count_is_checked(self):
        self.assertLispError("(table-outliers t :count 0)", ":count")


class TestPlotStratification(LispTestCase):
    def setUp(self):
        super().setUp()
        self.specs = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, plot=self.specs.append)
        self.run_lisp('''
          (load "autoloads.lsp")
          (define loans (make-table "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 6.0)
                                    "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000)
                                    "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA")))
          (define by-rate (stratify loans '("rate" (5.0)) '(("rate" weighted-mean "WAC")) :weight "balance"))''')

    def test_bars_for_each_share_and_a_line_for_the_first_summary(self):
        self.run_lisp("(plot-stratification by-rate)")
        bars, line = self.specs[-1]["series"]
        self.assertEqual(bars["x"], ["under 5.0", "5.0 and over"])          # not the total row
        self.assertEqual(len(bars["y"]), 2)
        self.assertAlmostEqual(sum(bars["y"]), 1.0)
        self.assertEqual(line["label"], "WAC")
        self.assertEqual(self.specs[-1]["title"], "rate")

    def test_another_column_can_be_the_line(self):
        self.run_lisp('(plot-stratification by-rate :column "count")')
        self.assertEqual(self.specs[-1]["series"][1]["y"], [3.0, 7.0])

    def test_without_summaries_only_bars(self):
        self.run_lisp('(plot-stratification (stratify loans \'("state" (top 2)) \'() :weight "balance" :total #f))')
        self.assertEqual(len(self.specs[-1]["series"]), 1)
        self.assertEqual(self.specs[-1]["series"][0]["x"], ["CA", "FL", "other"])

    def test_two_columns_are_labelled_with_both_buckets(self):
        self.run_lisp('(plot-stratification (stratify loans \'(("state" (top 1)) ("rate" (5.0))) \'() :weight "balance"))')
        self.assertEqual(self.specs[-1]["series"][0]["x"][0], "CA / under 5.0")
