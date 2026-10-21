"""lib/deal.lsp, the interest: coupons, paying interest before principal, a floater and an inverse floater, a premium and a discount
bond, and a deal of collateral with pieces of different coupons. The small deals are worked out by hand."""

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make
from test_deal import DealTestCase


class InterestTestCase(DealTestCase):

    def a_deal(self, coupon=0.12, months=4, amount=30.0):
        """A deal, called deal, of collateral that pays this principal for this many months, and the interest on its balance at the coupon."""
        self.run_lisp(level_pool(amount, months, coupon))

    def interest(self, name):
        return self.vector('(node-interest (get-node deal "%s"))' % name)

    def rates(self, name):
        return self.vector('(table-column (deal-coupon-table deal) "%s")' % name)


class TestInterest(InterestTestCase):

    def test_each_node_is_paid_the_interest_it_is_owed_on_its_balance_at_the_start_of_the_month(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("A"), [0.5, 0.2, 0.0, 0.0])               # (1% a month of 50, 20, 0, 0)
        np.testing.assert_allclose(self.interest("B"), [0.7, 0.7, 0.6, 0.3])
        np.testing.assert_allclose(self.interest("POOL"), [1.2, 0.9, 0.6, 0.3])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_interest_is_worked_out_before_the_principal_of_the_month_is_paid(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        self.assertAlmostEqual(self.interest("A")[0], 0.5)          # (on 50, not on the 20 that is left after the month's principal)

    def test_the_children_of_a_split_have_the_coupon_of_the_parent(self):
        self.a_deal(coupon=0.09)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-pro-rata! deal "B" '(("B1" 20.0) ("B2" 50.0)))""")
        for name in ("A", "B", "B1", "B2"):
            self.assertShows('((node-coupon (get-node deal "%s")) 0.03)' % name, "0.09")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")
        self.assertAlmostEqual(self.interest("B1")[0], 20.0 * 0.09 / 12)

    def test_a_pool_pays_interest_at_its_pass_through_coupon_and_has_that_coupon(self):
        self.run_lisp('(define deal (new-deal "d" :collateral (list (list 1000000.0 7.0 6.5 60))))')
        self.assertShows('((node-coupon (get-node deal "POOL")) (quote ()))', "0.065")
        interest = self.vector('(node-interest (get-node deal "POOL"))')
        balance = self.vector('(node-balance (get-node deal "POOL"))')
        np.testing.assert_allclose(interest, balance[:-1] * 0.065 / 12, rtol=1e-12)

    def test_a_deal_whose_collateral_pays_no_interest_pays_none_to_its_bonds(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("A"), [0, 0, 0, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_index_is_a_number_a_vector_or_not_given(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.run_lisp("(deal-run! deal :index 0.04)")
        self.assertShows("(deal-index-at deal 3)", "0.04")
        self.run_lisp("(deal-run! deal :index (vector 0.01 0.02 0.03 0.04 0.05))")
        self.assertShows("(deal-index-at deal 2)", "0.03")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-index-at deal 2)", "()")
        self.assertLispError("(deal-run! deal :index (vector 0.01 0.02))", "a vector with a number for each of the 4 months")
        self.assertLispError('(deal-run! deal :index "high")', "a number, or a vector")

    def test_a_structure_whose_coupons_do_not_add_up_to_the_parents_is_an_error_that_says_which_way(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.run_lisp('(node-coupon-set! (get-node deal "A") (constant-coupon 0.24))')
        self.assertLispError("(deal-run! deal)", "was paid 1.2 of interest in month 0, and its children are owed 1.7 (there is not enough)")
        self.run_lisp('(node-coupon-set! (get-node deal "A") (constant-coupon 0.06))')
        self.assertLispError("(deal-run! deal)", "children are owed 0.95 (some is left over)")

    def test_deal_check_finds_interest_that_was_not_paid_as_owed(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        self.run_lisp('(vector-increment! (node-interest (get-node deal "B")) 1 0.5)')
        self.assertLispError("(deal-check deal)", "the children of POOL were paid 1.4 of interest in month 1, and POOL was paid 0.9")
        self.run_lisp("(deal-run! deal)")
        self.run_lisp('(vector-increment! (node-interest (get-node deal "A")) 0 0.5) (vector-increment! (node-interest (get-node deal "B")) 0 -0.5)')
        self.assertLispError("(deal-check deal)", "A was paid 1 of interest in month 0, and it is owed 0.5")
        self.run_lisp("(deal-run! deal)")
        self.run_lisp('(node-coupon-set! (get-node deal "A") (constant-coupon 0.24))')
        self.assertLispError("(deal-check deal)", "the coupons of the children of POOL do not add up to its own: they are owed 1.7 in month 0, and it 1.2")

    def test_a_node_without_a_coupon_in_a_deal_that_has_one_is_an_error(self):
        self.a_deal()
        self.run_lisp("""(deal-add-tranche! deal "A" 120.0)""")
        self.run_lisp("""(deal-add-split! deal "POOL" (make-sequential-split :children '("A")))""")
        self.run_lisp('(node-coupon-set! (get-node deal "A") (quote ()))')
        self.assertLispError("(deal-run! deal)", "A has no coupon")

    def test_the_tables_show_the_interest_and_the_coupons(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.vector('(table-column (deal-interest-table deal) "B")'), [0.7, 0.7, 0.6, 0.3])
        np.testing.assert_allclose(self.rates("A"), [0.12] * 4)
        self.assertEqual(list(self.vector('(table-column (deal-interest-table deal) "month")')), [1, 2, 3, 4])


class TestFloaterAndInverse(InterestTestCase):

    def a_floater_deal(self, cap=0.10, margin=0.01, index=0.03, parent_coupon=0.06):
        self.a_deal(coupon=parent_coupon, months=4, amount=25.0)
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap %r :margin %r :index-name "SOFR")' % (cap, margin))
        self.run_lisp("(deal-run! deal :index %r)" % index)

    def test_the_sizes_the_leverage_and_the_constant_come_from_the_cap(self):
        self.a_floater_deal()
        self.assertAlmostEqual(self.balance("F")[0], 60.0)                          # 100 x 0.06 / 0.10
        self.assertAlmostEqual(self.balance("I")[0], 40.0)
        split = "(node-split (get-node deal \"POOL\"))"
        self.assertAlmostEqual(self.run_lisp("(floater-inverse-split-leverage %s)" % split), 1.5)
        self.assertAlmostEqual(self.run_lisp("(floater-inverse-split-constant %s)" % split), 0.135)     # 1.5 x (0.10 - 0.01)
        self.assertShows("(floater-inverse-split-index-name %s)" % split, '"SOFR"')

    def test_the_coupons_are_the_index_plus_the_margin_and_the_constant_less_the_leverage_times_the_index(self):
        self.a_floater_deal(index=0.03)
        np.testing.assert_allclose(self.rates("F"), [0.04] * 4)
        np.testing.assert_allclose(self.rates("I"), [0.09] * 4)                      # 0.135 - 1.5 x 0.03
        self.assertAlmostEqual(self.interest("F")[0], 60 * 0.04 / 12)
        self.assertAlmostEqual(self.interest("I")[0], 40 * 0.09 / 12)
        self.assertAlmostEqual(self.interest("F")[0] + self.interest("I")[0], self.interest("POOL")[0])

    def test_the_two_pay_the_parents_coupon_together_at_every_index(self):
        for index in (-0.01, 0.0, 0.02, 0.0599, 0.09, 0.1, 0.12, 0.5):
            with self.subTest(index=index):
                self.a_floater_deal(index=index)
                self.assertShows("(deal-check deal)", "#t")
                np.testing.assert_allclose(self.interest("F") + self.interest("I"), self.interest("POOL"), rtol=1e-12)

    def test_the_floater_stops_at_the_cap_and_the_inverse_at_nothing(self):
        self.a_floater_deal(index=0.5)
        np.testing.assert_allclose(self.rates("F"), [0.10] * 4)
        np.testing.assert_allclose(self.rates("I"), [0.0] * 4)
        self.a_floater_deal(index=-0.02)                                             # (a negative index is taken as 0)
        np.testing.assert_allclose(self.rates("F"), [0.01] * 4)
        np.testing.assert_allclose(self.rates("I"), [0.135] * 4)

    def test_the_principal_is_paid_pro_rata_so_the_two_stay_in_proportion(self):
        self.a_floater_deal()
        floater, inverse = self.balance("F")[:-1], self.balance("I")[:-1]
        np.testing.assert_allclose(floater / inverse, [1.5] * 4)
        np.testing.assert_allclose(self.principal("F"), [15, 15, 15, 15])
        np.testing.assert_allclose(self.principal("I"), [10, 10, 10, 10])

    def test_a_floater_and_inverse_under_a_pool_with_prepayments_and_an_index_that_moves(self):
        self.run_lisp("(define deal %s)" % psa_deal("fi", 200000000.0, 6.0, psa=200))
        self.run_lisp('''(deal-sequential! deal "POOL" (list (list "A" 120000000.0) (list "B" 80000000.0)))
                         (deal-floater-inverse! deal "B" "F" "I" :cap 0.09 :margin 0.005)
                         (deal-run! deal :index (list->vector (map (lambda (t) (+ 0.01 (* 0.0003 t))) (iota 360))))''')
        self.assertShows("(deal-check deal)", "#t")
        rates = self.rates("F")
        self.assertAlmostEqual(rates[0], 0.015)
        self.assertAlmostEqual(rates[-1], 0.09)                                       # (at the cap by the end)
        total = self.interest("F") + self.interest("I")
        np.testing.assert_allclose(total, self.interest("B"), rtol=1e-10, atol=1e-6)

    def test_the_formulas_wont_take_a_cap_that_is_not_above_the_coupon_or_a_margin_that_is_not_below_the_cap(self):
        self.a_deal(coupon=0.06)
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.06)', "the cap of the floater, 0.06, must be above the coupon")
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.05)', "must be above the coupon of the node that is divided, 0.06")
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.1 :margin -0.01)', "the margin of the floater, -0.01, must be from 0")
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.1 :margin 0.1)', "must be from 0 up to the cap")
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I")', "give the :cap of the floater")
        self.assertShows("(deal-names deal)", '("POOL")')                              # (nothing was added)

    def test_the_names_must_be_new_and_the_node_not_yet_divided(self):
        self.a_deal(coupon=0.06)
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "F" :cap 0.1)', "different names")
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "POOL" :cap 0.1)', "already has a node called POOL")
        self.assertLispError('(deal-floater-inverse! deal "NOPE" "F" "I" :cap 0.1)', "the deal has no node called NOPE")
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.1)')
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F2" "I2" :cap 0.1)', "POOL already has a split")

    def test_the_node_divided_must_have_a_coupon_that_is_fixed(self):
        self.a_deal()
        self.run_lisp('(deal-sequential! deal "POOL" (list (list "A" 50.0) (list "B" 70.0)))')
        self.run_lisp('(deal-floater-inverse! deal "B" "F" "I" :cap 0.2)')
        self.assertLispError('(deal-floater-inverse! deal "F" "F1" "F2" :cap 0.3)', "the coupon of F floats")

    def test_a_deal_with_a_floater_cannot_be_run_without_an_index(self):
        self.a_floater_deal()
        self.assertLispError("(deal-run! deal)", "give deal-run! an :index")

    def test_the_floater_and_inverse_can_be_divided_again(self):
        self.a_floater_deal()
        self.run_lisp('(deal-sequential! deal "F" (list (list "F1" 20.0) (list "F2" 40.0)))')
        self.run_lisp("(deal-run! deal :index 0.03)")
        self.assertShows("(deal-check deal)", "#t")
        self.assertShows("(deal-leaves deal)", '("I" "F1" "F2")')
        np.testing.assert_allclose(self.rates("F2"), [0.04] * 4)


class TestPremiumAndDiscount(InterestTestCase):

    def test_the_sizes_make_the_two_pay_the_parents_coupon_together(self):
        self.a_deal(coupon=0.06, months=4, amount=25.0)
        self.run_lisp('(deal-premium-discount! deal "POOL" "P" "D" :premium-coupon 0.09 :discount-coupon 0.05)')
        self.assertAlmostEqual(self.balance("P")[0], 25.0)                           # 100 x (0.06 - 0.05) / (0.09 - 0.05)
        self.assertAlmostEqual(self.balance("D")[0], 75.0)
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")
        np.testing.assert_allclose(self.rates("P"), [0.09] * 4)
        np.testing.assert_allclose(self.rates("D"), [0.05] * 4)
        self.assertAlmostEqual(self.interest("P")[0], 25 * 0.09 / 12)
        self.assertAlmostEqual(self.interest("P")[0] + self.interest("D")[0], self.interest("POOL")[0])
        np.testing.assert_allclose(self.principal("P"), [6.25] * 4)                  # (pro rata: a quarter of the principal)

    def test_what_it_wont_take(self):
        self.a_deal(coupon=0.06)
        self.assertLispError('(deal-premium-discount! deal "POOL" "P" "D" :premium-coupon 0.05 :discount-coupon 0.04)',
                             "must be between the discount coupon, 0.04, and the premium coupon, 0.05")
        self.assertLispError('(deal-premium-discount! deal "POOL" "P" "D" :premium-coupon 0.09)', "give the :premium-coupon and the :discount-coupon")
        self.assertShows("(deal-names deal)", '("POOL")')


class TestAPoolOfPiecesWithDifferentCoupons(InterestTestCase):
    """The coupon of the collateral is the rate that the interest it pays is of its balance, month by month, when its pieces have different coupons:
    a PAC is sized from the pieces at the other speeds, and a tranche that has no parent is not in the tree."""

    def test_a_tranche_that_has_not_been_given_a_parent_is_not_in_the_tree(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.assertShows('(deal-in-tree? deal "B")', "#t")
        self.assertShows('(deal-in-tree? deal "POOL")', "#t")
        self.run_lisp('(deal-add-tranche! deal "LOOSE" 1.0)')
        self.assertShows('(deal-in-tree? deal "LOOSE")', "#f")
        self.assertLispError('(deal-principal-at deal "LOOSE" 100)', "LOOSE is not in a tree of the deal")

    def test_a_node_cannot_be_the_child_of_a_split_of_another_or_of_the_collateral(self):
        self.a_deal()
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.assertLispError("""(deal-add-split! deal "A" (make-sequential-split :children '("POOL")))""", "POOL is already paid by a split")
        self.assertLispError("""(deal-add-split! deal "A" (make-sequential-split :children '("B")))""", "B is already paid by a split")

    def test_the_tolerance_is_a_fraction_of_the_collateral(self):
        self.a_deal()
        self.assertShows("(deal-size deal)", "120.0")

    def test_a_pac_is_sized_from_all_the_pieces_at_the_other_speeds(self):
        self.run_lisp('''(define mixed (new-deal "mixed" :collateral '((100000000.0 4.5 4.0 360) (100000000.0 7.5 7.0 360))
                                                       :speed (prepayment-speed 'psa 100)))
                         (deal-pac! mixed "POOL" "PAC" "COMP" 100 300)
                         (define alone (new-deal "alone" :collateral '((100000000.0 7.5 7.0 360)) :speed (prepayment-speed 'psa 100)))
                         (deal-pac! alone "POOL" "PAC" "COMP" 100 300)''')
        mixed_size = self.run_lisp('(vector-ref (node-balance (get-node mixed "PAC")) 0)')
        alone_size = self.run_lisp('(vector-ref (node-balance (get-node alone "PAC")) 0)')
        self.assertGreater(mixed_size, alone_size)                       # (twice the collateral, so about twice the PAC)
        self.assertAlmostEqual(mixed_size / alone_size, 2.0, delta=0.05)
        self.run_lisp("(deal-run! mixed)")
        self.assertShows("(deal-check mixed)", "#t")


if __name__ == "__main__":
    unittest.main()
