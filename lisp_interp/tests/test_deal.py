"""lib/deal.lsp: a deal as a tree of nodes, the pool at the root, divided by splits. The small deals here are worked out by hand
(the collateral pays a round amount of principal each month); the pool of mortgages is checked against its own formulas
and, with the whole tree, against the rules a deal has to keep: every split pays out what its parent was paid, and the leaves are
paid what they were owed, no more."""

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class DealTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal.lsp")')

    def vector(self, src):
        return np.array(self.run_lisp(src).items, dtype=float)

    def principal(self, name):
        return self.vector('(node-principal (get-node deal "%s"))' % name)

    def balance(self, name):
        return self.vector('(node-balance (get-node deal "%s"))' % name)

    def a_pool_paying(self, amount=30.0, months=4):
        """A pool that pays this principal each month, for this many, in a deal called deal."""
        balances = " ".join(repr(float(amount * (months - t))) for t in range(months + 1))
        self.run_lisp('(define pool (make-collateral :name "POOL" :balance (vector %s) :principal (make-vector %d %r)))'
                      % (balances, months, float(amount)))
        self.run_lisp('(define deal (start-deal "demo" pool))')


class TestThePool(DealTestCase):

    def test_with_no_prepayment_it_is_a_level_payment_loan(self):
        flows = self.run_lisp("(pool-cash-flows 1200.0 12.0 12 0 0)")
        principal, interest, balance = [np.array(v.items) for v in lisp_core.pairs_to_list(flows)]
        payment = 1200 * 0.01 / (1 - 1.01 ** -12)
        owed = 1200.0
        for t in range(12):
            self.assertAlmostEqual(interest[t], owed * 0.01, places=10)
            self.assertAlmostEqual(principal[t], payment - owed * 0.01, places=10)
            owed -= principal[t]
            self.assertAlmostEqual(balance[t + 1], owed, places=9)
        self.assertAlmostEqual(principal.sum(), 1200.0, places=9)
        self.assertAlmostEqual(balance[12], 0.0, places=9)
        self.assertEqual((len(principal), len(interest), len(balance)), (12, 12, 13))

    def test_a_pool_with_prepayments_pays_off_what_it_owes_sooner(self):
        slow = self.run_lisp('(pool-cash-flows 100000.0 6.0 360 0 100)')
        fast = self.run_lisp('(pool-cash-flows 100000.0 6.0 360 0 300)')
        (slow_principal, _, slow_balance), (fast_principal, _, fast_balance) = [
            [np.array(v.items) for v in lisp_core.pairs_to_list(flows)] for flows in (slow, fast)]
        for principal, balance in ((slow_principal, slow_balance), (fast_principal, fast_balance)):
            self.assertAlmostEqual(principal.sum(), 100000.0, places=6)
            np.testing.assert_allclose(balance[1:], balance[:-1] - principal, atol=1e-8)
            self.assertAlmostEqual(balance[-1], 0.0, places=6)
        self.assertEqual(slow_principal[0], fast_principal[0])                 # (no prepayments in the first month)
        self.assertLess(fast_balance[60], slow_balance[60])
        self.assertGreater(fast_principal[30], slow_principal[30])

    def test_the_prepayment_speed_follows_the_age_of_the_loans(self):
        flows = self.run_lisp("(pool-cash-flows 100000.0 6.0 360 24 100)")
        principal = np.array(lisp_core.pairs_to_list(flows)[0].items)
        self.assertEqual(len(principal), 336)                                   # 360 - 24 months to run
        monthly = 0.005
        payment = 100000 * monthly / (1 - (1 + monthly) ** -336)
        scheduled = payment - 100000 * monthly
        cpr = 0.06 * 24 / 30                                                    # (24 months of the 30-month ramp)
        smm = 1 - (1 - cpr) ** (1 / 12)
        self.assertAlmostEqual(principal[0], scheduled + smm * (100000 - scheduled), places=8)

    def test_the_collateral_node_holds_the_flows(self):
        self.run_lisp('(define pool (collateral-from-psa "POOL" 1000000.0 5.5 :term 120 :age 6 :psa 200))')
        self.assertShows("(collateral? pool)", "#t")
        self.assertShows("(node? pool)", "#t")
        self.assertShows("(list (collateral-rate pool) (collateral-term pool) (collateral-age pool) (collateral-psa pool))", "(5.5 120 6 200)")
        self.assertEqual(len(self.vector("(node-principal pool)")), 114)
        self.assertEqual(len(self.vector("(node-balance pool)")), 115)
        self.assertEqual(len(self.vector("(collateral-interest pool)")), 114)
        self.assertEqual(self.vector("(node-balance pool)")[0], 1000000.0)

    def test_the_age_must_be_less_than_the_term(self):
        self.assertLispError('(collateral-from-psa "POOL" 100.0 5.0 :term 120 :age 120)', "the age 120 must be from 0 up to the term 120")
        self.assertLispError('(collateral-from-psa "POOL" 100.0 5.0 :age -1)', "must be from 0")


class TestSplits(DealTestCase):

    def test_a_sequential_split_pays_the_first_child_until_it_is_paid_and_then_the_next(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.principal("A"), [30, 20, 0, 0])
        np.testing.assert_allclose(self.principal("B"), [0, 10, 30, 30])
        np.testing.assert_allclose(self.balance("A"), [50, 20, 0, 0, 0])
        np.testing.assert_allclose(self.balance("B"), [70, 70, 60, 30, 0])
        np.testing.assert_allclose(self.balance("POOL"), [120, 90, 60, 30, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_a_pro_rata_split_pays_each_child_in_proportion_to_what_it_owes(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-pro-rata! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.principal("A"), [12.5] * 4)
        np.testing.assert_allclose(self.principal("B"), [17.5] * 4)
        np.testing.assert_allclose(self.balance("A"), [50, 37.5, 25, 12.5, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_a_pro_rata_split_pays_the_children_that_owe_less_by_less_as_they_are_paid_off(self):
        self.a_pool_paying(40.0, 3)
        self.run_lisp("""(deal-pro-rata! deal "POOL" '(("A" 20.0) ("B" 100.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.principal("A"), [20 / 3, 20 / 3, 20 / 3])
        np.testing.assert_allclose(self.principal("B"), [100 / 3] * 3)

    def test_the_tree_goes_down_to_any_depth_each_level_with_its_own_kind_of_split(self):
        self.a_pool_paying(25.0, 4)
        self.run_lisp("""
          (deal-sequential! deal "POOL" '(("SR" 60.0) ("JR" 40.0)))
          (deal-sequential! deal "SR" '(("S1" 25.0) ("S2" 35.0)))
          (deal-pro-rata! deal "JR" '(("J1" 10.0) ("J2" 30.0)))
          (deal-run! deal)""")
        for name, expected in (("SR", [25, 25, 10, 0]), ("JR", [0, 0, 15, 25]), ("S1", [25, 0, 0, 0]), ("S2", [0, 25, 10, 0]),
                               ("J1", [0, 0, 3.75, 6.25]), ("J2", [0, 0, 11.25, 18.75])):
            np.testing.assert_allclose(self.principal(name), expected, err_msg=name)
        self.assertShows("(deal-check deal)", "#t")
        self.assertShows("(deal-leaves deal)", '("S1" "S2" "J1" "J2")')
        self.assertShows("(deal-names deal)", '("POOL" "SR" "JR" "S1" "S2" "J1" "J2")')

    def test_the_deal_can_be_run_again_and_gives_the_same_answer(self):
        self.a_pool_paying(25.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 60.0) ("B" 40.0))) (deal-run! deal)""")
        first = {name: self.principal(name) for name in ("A", "B")}
        self.run_lisp("(deal-run! deal)")
        for name in ("A", "B"):
            np.testing.assert_allclose(self.principal(name), first[name])
        np.testing.assert_allclose(self.principal("POOL"), [25] * 4)             # (the pool's own flows are as they were)

    def test_a_kind_of_split_of_your_own_is_a_function_in_the_slot_and_call_super_gets_at_the_one_it_extends(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""
          (define calls '())
          (defstruct (noting-split (:include sequential-split))
            (pay-principal (lambda (self deal parent t)
                             (push t calls)
                             (call-super noting-split-pay-principal self deal parent t))))
          (define pool-node (get-node deal "POOL"))
          (deal-add-tranche! deal "A" 50.0)
          (deal-add-tranche! deal "B" 70.0)
          (deal-add-split! deal "POOL" (make-noting-split :children '("A" "B")))
          (deal-run! deal)""")
        self.assertShows("(reverse calls)", "(0 1 2 3)")
        np.testing.assert_allclose(self.principal("A"), [30, 20, 0, 0])               # (paid as a sequential split pays)


class TestARandomDeal(DealTestCase):
    """A pool of mortgages and a deal of several levels: whatever the speed, the rules of a deal hold."""

    def build(self, psa, age=0):
        self.run_lisp('''
          (define pool (collateral-from-psa "POOL" 250000000.0 6.25 :term 360 :age %d :psa %d))
          (define deal (start-deal "Random" pool))
          (deal-sequential! deal "POOL" '(("SR" 150000000.0) ("JR" 100000000.0)))
          (deal-sequential! deal "SR" '(("S1" 40000000.0) ("S2" 70000000.0) ("S3" 40000000.0)))
          (deal-pro-rata! deal "JR" '(("J1" 30000000.0) ("J2" 70000000.0)))
          (deal-sequential! deal "S3" '(("S3A" 15000000.0) ("S3B" 25000000.0)))
          (deal-run! deal)''' % (age, psa))

    def test_what_the_leaves_are_paid_adds_up_to_what_the_pool_pays_every_month(self):
        for psa, age in ((0, 0), (100, 0), (250, 0), (150, 30), (600, 12)):
            with self.subTest(psa=psa, age=age):
                self.build(psa, age)
                self.assertShows("(deal-check deal)", "#t")
                leaves = self.run_lisp("(deal-leaves deal)")
                total = sum(self.principal(name) for name in lisp_core.pairs_to_list(leaves))
                np.testing.assert_allclose(total, self.principal("POOL"), rtol=1e-12, atol=1e-6)

    def test_every_leaf_is_paid_exactly_what_it_began_with_and_ends_at_nothing(self):
        self.build(180)
        for name, size in (("S1", 40e6), ("S2", 70e6), ("S3A", 15e6), ("S3B", 25e6), ("J1", 30e6), ("J2", 70e6)):
            self.assertAlmostEqual(self.principal(name).sum(), size, delta=1e-5, msg=name)
            self.assertAlmostEqual(self.balance(name)[-1], 0.0, delta=1e-5, msg=name)
            self.assertGreaterEqual(self.balance(name).min(), -1e-5, name)

    def test_a_sequential_pair_never_pays_the_second_while_the_first_is_owed(self):
        self.build(120)
        p1, p2 = self.principal("S1"), self.principal("S2")
        owed_p1 = self.balance("S1")[:-1] - p1                  # (what S1 still owed after the month)
        for t in range(len(p1)):
            if p2[t] > 1e-6:
                self.assertLess(owed_p1[t], 1e-6, "month %d" % t)

    def test_faster_prepayments_pay_the_early_bonds_off_sooner(self):
        self.build(100)
        slow = int(np.argmax(self.balance("S1") < 1e-6))
        self.build(400)
        fast = int(np.argmax(self.balance("S1") < 1e-6))
        self.assertLess(fast, slow)

    def test_the_tables_have_a_column_for_every_node(self):
        self.build(150)
        principal = self.run_lisp("(deal-principal-table deal)")
        balance = self.run_lisp("(deal-balance-table deal)")
        names = [str(p.car) for p in lisp_core.pairs_to_list(principal)]
        self.assertEqual(names, ["month", "POOL", "SR", "JR", "S1", "S2", "S3", "J1", "J2", "S3A", "S3B"])
        self.assertEqual(len(lisp_core.pairs_to_list(principal)[0].cdr.items), 360)
        self.assertEqual(len(lisp_core.pairs_to_list(balance)[0].cdr.items), 361)
        self.assertEqual(list(lisp_core.pairs_to_list(principal)[0].cdr.items[:3]), [1, 2, 3])
        self.assertEqual(list(lisp_core.pairs_to_list(balance)[0].cdr.items[:3]), [0, 1, 2])


class TestWhatTheDealWontTake(DealTestCase):

    def test_the_children_must_add_up_to_the_parent(self):
        self.a_pool_paying(30.0, 4)
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 60.0)))""", "have balances that add up to 110.0, and POOL has 120.0")

    def test_the_names_must_be_known_and_new(self):
        self.a_pool_paying(30.0, 4)
        self.assertLispError("""(deal-sequential! deal "NOPE" '(("A" 120.0)))""", "the deal has no node called NOPE")
        self.assertShows("(deal-names deal)", '("POOL")')                         # (nothing was added)
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 60.0) ("A" 60.0)))""", "not all called by different names")
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 60.0)))""", "add up to 110.0")
        self.assertShows("(deal-names deal)", '("POOL")')
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.assertLispError("""(deal-sequential! deal "A" '(("B" 50.0)))""", "already has a node called B")
        self.assertLispError("""(deal-sequential! deal "A" '(("X" 20.0) ("B" 30.0)))""", "already has a node called B")
        self.assertShows("(deal-names deal)", '("POOL" "A" "B")')                  # (X was not added)
        self.assertLispError("""(deal-pro-rata! deal "POOL" '(("C" 120.0)))""", "POOL already has a split")
        self.assertLispError('(get-node deal "Z")', "the deal has no node called Z (it has POOL A B)")

    def test_a_node_is_paid_by_one_split_and_the_collateral_by_none(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.run_lisp('(deal-add-tranche! deal "X" 50.0) (deal-add-tranche! deal "Y" 20.0)')
        self.assertLispError("""(deal-add-split! deal "A" (make-sequential-split :children '("B")))""", "B is already paid by a split")
        self.assertLispError("""(deal-add-split! deal "A" (make-sequential-split :children '("POOL")))""", "POOL is already paid by a split")

    def test_a_split_added_to_tranches_already_there_is_checked_too(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp('(deal-add-tranche! deal "A" 50.0) (deal-add-tranche! deal "B" 60.0)')
        self.assertLispError("""(deal-add-split! deal "POOL" (make-sequential-split :children '("A" "B")))""", "add up to 110.0, and POOL has 120.0")
        self.assertShows('(null? (node-split (get-node deal "POOL")))', "#t")
        self.run_lisp('(deal-add-tranche! deal "C" 10.0)')
        self.run_lisp("""(deal-add-split! deal "POOL" (make-sequential-split :children '("A" "B" "C")))""")
        self.assertShows('(split-children (node-split (get-node deal "POOL")))', '("A" "B" "C")')

    def test_a_split_needs_children(self):
        self.a_pool_paying(30.0, 4)
        self.assertLispError('(deal-add-split! deal "POOL" (make-sequential-split :children (list)))', "has no children")

    def test_a_deal_is_made_in_double_precision(self):
        self.a_pool_paying(30.0, 4)
        self.use_single_precision()
        self.assertLispError('(start-deal "x" pool)', "a deal is made in double precision")

    def test_principal_that_no_child_can_be_paid_is_an_error(self):
        self.run_lisp('''(define pool (make-collateral :name "POOL" :balance (vector 100.0 40.0 0.0) :principal (vector 60.0 80.0)))
                         (define deal (start-deal "demo" pool))
                         (deal-sequential! deal "POOL" '(("A" 100.0)))''')
        self.assertLispError("(deal-run! deal)", "the split of POOL has 40.0 of principal left over in month 1")

    def test_deal_check_finds_principal_that_does_not_add_up(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))""")
        self.assertLispError("(deal-check deal)", "has deal-run! been called?")
        self.run_lisp("(deal-run! deal)")
        self.run_lisp('(vector-increment! (node-principal (get-node deal "B")) 2 5.0)')
        self.assertLispError("(deal-check deal)", "the children of POOL were paid 35.0 in month 2, and POOL was paid 30.0")

    def test_deal_check_finds_a_node_that_was_paid_more_than_it_was_owed(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0))) (deal-run! deal)""")
        self.run_lisp('(vector-set! (node-balance (get-node deal "A")) 3 -9.0)')
        self.assertLispError("(deal-check deal)", "A owes -9.0 in month 3: it has been paid more than it was owed")


class TestTheLibraryIsThereWithoutLoadingIt(LispTestCase):

    def test_the_functions_are_there_when_the_autoloads_are_loaded(self):
        self.run_lisp('(load "autoloads.lsp")')
        self.run_lisp("""
          (define pool (collateral-from-psa "POOL" 1000000.0 6.0 :term 24 :psa 100))
          (define deal (start-deal "d" pool))
          (deal-sequential! deal "POOL" '(("A" 400000.0) ("B" 600000.0)))
          (deal-run! deal)""")
        self.assertShows("(deal-check deal)", "#t")


if __name__ == "__main__":
    unittest.main()
