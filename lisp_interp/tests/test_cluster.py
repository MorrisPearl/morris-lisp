"""table-cluster: a column that says which group of alike rows each row is in."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class TestTableCluster(LispTestCase):
    def setUp(self):
        super().setUp()
        # Two clear groups: three small loans at low rates (rows 0-2) and four large loans at high rates (rows 3-6).
        self.run_lisp("""
          (define loans
            (make-table "balance" #(100000 110000 105000 900000 950000 920000 940000)
                        "rate"    #(3.0 3.1 2.9 7.0 7.2 6.9 7.1)
                        "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL")))""")

    def test_alike_rows_share_a_cluster_and_the_largest_group_is_1(self):
        self.assertEqual(self.show('(table-column (table-cluster loans (list "balance" "rate") 2) "cluster")'),
                         "#(2 2 2 1 1 1 1)")

    def test_the_other_columns_are_kept_and_the_new_one_is_last(self):
        self.assertEqual(self.show('(table-column-names (table-cluster loans "rate" 2))'),
                         '("balance" "rate" "state" "cluster")')

    def test_name_says_what_the_column_is_called(self):
        self.assertEqual(self.show('(table-column-names (table-cluster loans "rate" 2 :name "bucket"))'),
                         '("balance" "rate" "state" "bucket")')

    def test_the_same_seed_gives_the_same_groups(self):
        self.run_lisp('(define a (table-cluster loans (list "balance" "rate") 3 :seed 7))')
        self.run_lisp('(define b (table-cluster loans (list "balance" "rate") 3 :seed 7))')
        self.assertEqual(self.show('(table-column a "cluster")'), self.show('(table-column b "cluster")'))

    def test_one_group_holds_every_row(self):
        self.assertEqual(self.show('(table-column (table-cluster loans "rate" 1) "cluster")'), "#(1 1 1 1 1 1 1)")

    def test_a_row_with_a_missing_value_is_in_no_group(self):
        self.run_lisp('(define gap (make-table "x" #(1 1.1 nan 9 9.1)))')
        self.assertEqual(self.show('(table-column (table-cluster gap "x" 2) "cluster")'), "#(1.0 1.0 nan 2.0 2.0)")   # two rows each: the group of the earlier row is 1

    def test_columns_are_scaled_unless_told_not_to(self):
        # The balances differ by up to 300 and the rates by 8. Compared as they are, the balances decide: rows 0 and 2 (1000, 1100)
        # against 1 and 3 (1200, 1300). Scaled, each column counts as much as the other, and the rate separates rows 0 and 1 from 2 and 3.
        self.run_lisp('(define t (make-table "balance" #(1000 1200 1100 1300) "rate" #(1 1 9 9)))')
        self.assertEqual(self.show('(table-column (table-cluster t (list "balance" "rate") 2) "cluster")'), "#(1 1 2 2)")
        self.assertEqual(self.show('(table-column (table-cluster t (list "balance" "rate") 2 :scale #f) "cluster")'), "#(1 2 1 2)")

    def test_mistakes_are_explained(self):
        self.assertRaisesRegex(Exception, "no column named", self.run_lisp, '(table-cluster loans "nope" 2)')
        self.assertRaisesRegex(Exception, "whole number of 1 or more", self.run_lisp, '(table-cluster loans "rate" 0)')
        self.assertRaisesRegex(Exception, "only 7 rows", self.run_lisp, '(table-cluster loans "rate" 8)')
