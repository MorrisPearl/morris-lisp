"""lib/deal.lsp, the interest: coupons, paying interest before principal, a floater and an inverse floater, a premium and a discount
bond, and a deal with more than one piece of collateral. The small deals are worked out by hand."""

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase
from test_deal import DealTestCase


class InterestTestCase(DealTestCase):

    def pool(self, coupon=0.12, months=4, amount=30.0, name="POOL"):
        """Collateral that pays this principal for this many months, and the interest on its balance at the coupon, in a deal."""
        balances = [amount * (months - t) for t in range(months + 1)]
        interest = [b * coupon / 12 for b in balances[:-1]]
        numbers = lambda values: " ".join(repr(float(v)) for v in values)
        self.run_lisp('''(define %s (make-collateral :name "%s" :balance (vector %s) :principal (make-vector %d %r)
                           :interest (vector %s) :coupon (constant-coupon %r)))''' % (
            name.lower(), name, numbers(balances), months, float(amount), numbers(interest), coupon))

    def a_deal(self, **options):
        self.pool(**options)
        self.run_lisp('(define deal (start-deal "demo" pool))')

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

    def test_the_collateral_from_psa_pays_interest_at_its_rate_and_has_that_coupon(self):
        self.run_lisp('(define pool (collateral-from-psa "POOL" 1000000.0 6.5 :term 60 :psa 100))')
        self.assertShows("((node-coupon pool) '())", "0.065")
        interest = self.vector("(node-interest pool)")
        balance = self.vector("(node-balance pool)")
        np.testing.assert_allclose(interest, balance[:-1] * 0.065 / 12, rtol=1e-12)

    def test_a_deal_run_with_no_collateral_coupon_is_a_deal_of_principal_only(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("A"), [0, 0, 0, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_collateral_that_has_a_coupon_needs_the_interest_it_pays(self):
        self.run_lisp('(define pool (make-collateral :name "POOL" :balance (vector 2.0 0.0) :principal (vector 2.0) :coupon (constant-coupon 0.1)))')
        self.assertLispError('(start-deal "d" pool)', "needs the interest it pays")

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
        self.assertLispError("(deal-check deal)", "A was paid 0.5 of interest in month 0, and it is owed 1 (has deal-run!")

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
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 200000000.0 6.0 :term 360 :psa 200))
                         (define deal (start-deal "fi" pool))
                         (deal-sequential! deal "POOL" (list (list "A" 120000000.0) (list "B" 80000000.0)))
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
        self.run_lisp('(define bare (make-collateral :name "BARE" :balance (vector 10.0 0.0) :principal (vector 10.0 0.0 0.0 0.0)))')
        self.run_lisp('(define bare-deal (start-deal "b" bare))')
        self.assertLispError('(deal-floater-inverse! bare-deal "BARE" "F" "I" :cap 0.1)', "BARE has no coupon")

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


class TestSeveralCollaterals(InterestTestCase):

    def two_groups(self):
        self.pool(coupon=0.12, months=4, amount=30.0, name="G1")
        self.pool(coupon=0.06, months=4, amount=10.0, name="G2")
        self.run_lisp('''(define deal (start-deal "two groups" g1))
                         (deal-add-collateral! deal g2)
                         (deal-sequential! deal "G1" '(("A" 50.0) ("B" 70.0)))
                         (deal-pro-rata! deal "G2" '(("C" 15.0) ("D" 25.0)))
                         (deal-run! deal)''')

    def test_each_piece_of_collateral_is_the_root_of_a_tree_of_its_own(self):
        self.two_groups()
        self.assertShows("(deal-roots deal)", '("G1" "G2")')
        self.assertShows("(deal-names deal)", '("G1" "G2" "A" "B" "C" "D")')
        self.assertShows("(deal-leaves deal)", '("A" "B" "C" "D")')
        np.testing.assert_allclose(self.principal("A"), [30, 20, 0, 0])
        np.testing.assert_allclose(self.principal("C"), [3.75, 3.75, 3.75, 3.75])
        np.testing.assert_allclose(self.interest("A"), [0.5, 0.2, 0, 0])                 # (G1's coupon, 12%)
        np.testing.assert_allclose(self.interest("C"), [15 * 0.005, 11.25 * 0.005, 7.5 * 0.005, 3.75 * 0.005])    # (G2's, 6%)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_tolerance_is_a_fraction_of_all_the_collateral(self):
        self.two_groups()
        self.assertShows("(deal-size deal)", "160.0")

    def test_the_tables_have_a_column_for_each_node_of_each_tree(self):
        self.two_groups()
        names = [str(p.car) for p in lisp_core.pairs_to_list(self.run_lisp("(deal-principal-table deal)"))]
        self.assertEqual(names, ["month", "G1", "G2", "A", "B", "C", "D"])

    def test_the_trees_know_their_roots(self):
        self.two_groups()
        self.assertShows('(deal-root-of deal "B")', '"G1"')
        self.assertShows('(deal-root-of deal "D")', '"G2"')
        self.assertShows('(deal-root-of deal "G2")', '"G2"')
        self.run_lisp('(deal-add-tranche! deal "LOOSE" 1.0)')
        self.assertShows('(deal-root-of deal "LOOSE")', "#f")

    def test_collateral_must_pay_for_the_same_months_and_have_names_of_its_own(self):
        self.pool(months=4, name="G1")
        self.pool(months=3, name="G2")
        self.run_lisp('(define deal (start-deal "d" g1))')
        self.assertLispError("(deal-add-collateral! deal g2)", "G2 pays for 3 months, and the rest of the collateral for 4")
        self.run_lisp('(define twin (make-collateral :name "G1" :balance (vector 0.0 0.0 0.0 0.0 0.0) :principal (make-vector 4 0.0)))')
        self.assertLispError("(deal-add-collateral! deal twin)", "already has a node called G1")
        self.assertLispError("(deal-add-collateral! deal 5)", "expected collateral")
        self.assertLispError('(start-deal "d" (make-tranche :name "T"))', "the collateral is made by")

    def test_a_node_of_one_tree_cannot_be_the_child_of_a_split_of_another_or_of_its_own_root(self):
        self.two_groups()
        self.assertLispError("""(deal-add-split! deal "A" (make-sequential-split :children '("G2")))""", "G2 is already paid by a split")
        self.assertLispError("""(deal-add-split! deal "A" (make-sequential-split :children '("D")))""", "D is already paid by a split")

    def test_a_pac_is_sized_from_the_collateral_of_its_own_tree(self):
        self.run_lisp('''(define slow (collateral-from-psa "SLOW" 100000000.0 4.0 :term 360 :psa 100))
                         (define fast (collateral-from-psa "FAST" 100000000.0 7.0 :term 360 :psa 100))
                         (define both (start-deal "both" slow))
                         (deal-add-collateral! both fast)
                         (deal-pac! both "FAST" "PAC" "COMP" 100 300)
                         (define alone (start-deal "alone" (collateral-from-psa "FAST" 100000000.0 7.0 :term 360 :psa 100)))
                         (deal-pac! alone "FAST" "PAC" "COMP" 100 300)''')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node both "PAC")) 0)'),
                               self.run_lisp('(vector-ref (node-balance (get-node alone "PAC")) 0)'), places=6)
        self.assertLispError('(deal-principal-at both "LOOSE" 100)', "is not in a tree of the deal")
        self.run_lisp('(deal-add-tranche! both "LOOSE" 1.0)')
        self.assertLispError('(deal-principal-at both "LOOSE" 100)', "LOOSE is not in a tree of the deal")


if __name__ == "__main__":
    unittest.main()
