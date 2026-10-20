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

    def test_a_kind_of_split_of_your_own_is_a_type_with_methods_and_call_next_method_gets_at_the_one_it_extends(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""
          (define calls '())
          (defstruct (noting-split (:include sequential-split)))
          (defmethod pay-principal ((split noting-split) deal parent t)
            (push t calls)
            (call-next-method))
          (deal-add-tranche! deal "A" 50.0)
          (deal-add-tranche! deal "B" 70.0)
          (deal-add-split! deal "POOL" (make-noting-split :children '("A" "B")))
          (deal-run! deal)""")
        self.assertShows("(reverse calls)", "(0 1 2 3)")
        np.testing.assert_allclose(self.principal("A"), [30, 20, 0, 0])               # (paid as a sequential split pays)


class TestTheSplitsAreMethods(DealTestCase):

    def test_the_verbs_are_generic_functions_with_a_method_for_each_kind_of_split(self):
        self.assertShows("(generic-function? pay-principal)", "#t")
        self.assertShows("(generic-function-methods pay-principal)", "(sequential-split pro-rata-split io-po-split pac-split)")

    def test_a_split_of_no_kind_that_pays_cannot_be_run(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp('(deal-add-tranche! deal "A" 120.0)')
        self.run_lisp("""(deal-add-split! deal "POOL" (make-split :children '("A")))""")
        self.assertLispError("(deal-run! deal)", "pay-principal: there is no method for a split")

    def test_a_split_has_only_its_children_as_data(self):
        self.run_lisp("""(define s (make-pac-split :children '("A" "B") :low-psa 100 :high-psa 300))""")
        self.assertShows("s", '#S(pac-split :children ("A" "B") :loss-rule reverse :low-psa 100 :high-psa 300 :schedule ())')


class TestThePac(DealTestCase):
    """A PAC and its companion: sized from the collateral at two speeds, and paid on the schedule that gives."""

    def a_hand_made_pac(self, principal, size, schedule):
        """A pool that pays this principal, and a PAC of this size on this schedule (the balances at the start of each month), with
        the companion for the rest: the schedule is given, not worked out."""
        total = sum(principal)
        owed = [total - sum(principal[:t]) for t in range(len(principal) + 1)]
        numbers = lambda values: " ".join(repr(float(v)) for v in values)
        self.run_lisp('(define pool (make-collateral :name "POOL" :balance (vector %s) :principal (vector %s)))'
                      % (numbers(owed), numbers(principal)))
        self.run_lisp('(define deal (start-deal "demo" pool))')
        self.run_lisp('(deal-add-tranche! deal "PAC" %r) (deal-add-tranche! deal "COMP" %r)' % (float(size), float(total - size)))
        # (a PAC split that is given its schedule: it pays as a PAC does, and works out no sizes)
        self.run_lisp("""(defstruct (given-pac-split (:include pac-split)))
                         (defmethod calculate-sizes ((split given-pac-split) deal parent) '())""")
        self.run_lisp('''(deal-add-split! deal "POOL" (make-given-pac-split :children '("PAC" "COMP") :low-psa 100 :high-psa 300
                          :schedule (vector %s)))''' % numbers(schedule))
        self.run_lisp("(deal-run! deal)")

    def test_the_pac_is_paid_its_schedule_and_the_companion_what_is_over(self):
        self.a_hand_made_pac([20, 40, 10, 50], 60, [60, 40, 20, 10, 0])
        np.testing.assert_allclose(self.principal("PAC"), [20, 20, 10, 10])
        np.testing.assert_allclose(self.principal("COMP"), [0, 20, 0, 40])
        np.testing.assert_allclose(self.balance("PAC"), [60, 40, 20, 10, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_pac_is_paid_more_than_its_schedule_when_the_companion_is_paid_off(self):
        self.a_hand_made_pac([60, 40, 20], 100, [100, 70, 40, 0])
        np.testing.assert_allclose(self.principal("COMP"), [20, 0, 0])           # (it is only 20, and is paid first)
        np.testing.assert_allclose(self.principal("PAC"), [40, 40, 20])         # (30, and then the 10 over; then it is ahead of schedule)
        np.testing.assert_allclose(self.balance("PAC"), [100, 60, 20, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_a_pac_that_is_behind_its_schedule_catches_up_before_the_companion_is_paid(self):
        self.a_hand_made_pac([5, 5, 50, 20], 50, [50, 30, 10, 0, 0])             # (the pool pays less than the schedule at first)
        np.testing.assert_allclose(self.principal("PAC"), [5, 5, 40, 0])         # (month 3: 20 to be on schedule, 10 more to catch up)
        np.testing.assert_allclose(self.principal("COMP"), [0, 0, 10, 20])
        self.assertShows("(deal-check deal)", "#t")

    def test_pay_child_will_not_pay_a_child_below_the_floor_it_is_given(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp('(deal-add-tranche! deal "A" 50.0)')
        self.assertShows('(pay-child! (get-node deal "A") 0 30.0 40.0)', "20.0")      # (only 10 of it: down to 40)
        self.assertShows('(vector-ref (node-principal (get-node deal "A")) 0)', "10.0")
        self.assertShows('(pay-child! (get-node deal "A") 0 30.0 45.0)', "30.0")      # (it is at 40 now, below the floor)
        self.assertShows('(pay-child! (get-node deal "A") 0 100.0)', "60.0")          # (no floor: it is paid off, with 40 to go)

    # --- sized from the collateral ---

    def pool_principal(self, psa, balance=100000000.0, rate=6.5, term=360, age=0):
        flows = self.run_lisp("(pool-cash-flows %r %r %d %d %d)" % (balance, rate, term, age, psa))
        return np.array(lisp_core.pairs_to_list(flows)[0].items)

    def a_pac_deal(self, psa, low=100, high=300, age=0):
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :age %d :psa %d))
                         (define deal (start-deal "pac" pool))
                         (deal-pac! deal "POOL" "PAC" "COMP" %d %d)''' % (age, psa, low, high))

    def schedule(self):
        return self.vector('(pac-split-schedule (node-split (get-node deal "POOL")))')

    def test_the_pac_is_as_big_as_the_least_the_pool_pays_at_the_two_speeds_added_up(self):
        self.a_pac_deal(200)
        least = np.minimum(self.pool_principal(100), self.pool_principal(300))
        self.assertAlmostEqual(self.balance("PAC")[0], least.sum(), places=4)
        self.assertAlmostEqual(self.balance("COMP")[0], 100000000.0 - least.sum(), places=4)
        self.assertGreater(least.sum(), 0.5e8)                                    # (a good deal of the pool)
        self.assertLess(least.sum(), 1e8)

    def test_the_schedule_is_the_balance_the_pac_has_after_each_months_least(self):
        self.a_pac_deal(200)
        schedule = self.schedule()
        least = np.minimum(self.pool_principal(100), self.pool_principal(300))
        self.assertEqual(len(schedule), 361)
        self.assertAlmostEqual(schedule[0], least.sum(), places=4)
        np.testing.assert_allclose(schedule[1:], schedule[:-1] - least, atol=1e-6)
        self.assertAlmostEqual(schedule[-1], 0.0, places=4)

    def test_the_sizes_follow_the_age_of_the_loans(self):
        self.a_pac_deal(200, age=36)
        least = np.minimum(self.pool_principal(100, age=36), self.pool_principal(300, age=36))
        self.assertAlmostEqual(self.balance("PAC")[0], least.sum(), places=4)
        self.assertEqual(len(self.balance("PAC")), 325)                           # 360 - 36 months, and one

    def test_at_any_speed_between_the_two_the_pac_is_on_schedule_every_month(self):
        for psa in (100, 150, 200, 250, 300):
            with self.subTest(psa=psa):
                self.a_pac_deal(psa)
                self.run_lisp("(deal-run! deal)")
                np.testing.assert_allclose(self.balance("PAC"), self.schedule(), atol=1e-5)
                self.assertShows("(deal-check deal)", "#t")
                self.assertAlmostEqual(self.balance("COMP")[-1], 0.0, places=4)

    def test_faster_than_the_bands_the_pac_gets_ahead_of_its_schedule_and_slower_it_falls_behind(self):
        self.a_pac_deal(800)
        schedule = self.schedule()
        self.run_lisp("(deal-run! deal)")
        self.assertTrue((self.balance("PAC") <= schedule + 1e-5).all())
        self.assertTrue((self.balance("PAC") < schedule - 1.0).any())            # (ahead of it, once the companion is paid off)
        self.assertShows("(deal-check deal)", "#t")
        self.a_pac_deal(40)
        schedule = self.schedule()
        self.run_lisp("(deal-run! deal)")
        self.assertGreater(self.balance("PAC")[24], schedule[24] + 1.0)          # (behind it)
        self.assertShows("(deal-check deal)", "#t")
        self.assertAlmostEqual(self.balance("PAC")[-1], 0.0, places=4)           # (and the pool pays it all in the end)

    def test_a_pac_and_its_companion_can_be_divided_again(self):
        self.a_pac_deal(200)
        size = self.balance("PAC")[0]
        self.run_lisp('''(deal-sequential! deal "PAC" (list (list "P1" 20000000.0) (list "P2" (- %r 20000000.0))))
                         (deal-pro-rata! deal "COMP" (list (list "C1" 10000000.0) (list "C2" (- %r 10000000.0))))
                         (deal-run! deal)''' % (float(size), 1e8 - float(size)))
        self.assertShows("(deal-check deal)", "#t")
        leaves = sum(self.principal(n) for n in ("P1", "P2", "C1", "C2"))
        np.testing.assert_allclose(leaves, self.principal("POOL"), rtol=1e-12, atol=1e-5)

    # --- what it won't take ---

    def test_a_pac_needs_two_speeds_names_of_its_own_and_a_collateral_that_can_be_run_at_them(self):
        self.a_pac_deal(200)
        self.assertLispError('(deal-pac! deal "POOL" "X" "Y" 100 300)', "POOL already has a split")
        self.run_lisp('(define pool (collateral-from-psa "POOL" 100.0 6.5)) (define deal (start-deal "d" pool))')
        self.assertLispError('(deal-pac! deal "POOL" "A" "A" 100 300)', "different names")
        self.assertLispError('(deal-pac! deal "POOL" "A" "POOL" 100 300)', "already has a node called POOL")
        self.assertLispError('(deal-pac! deal "POOL" "A" "B" 300 100)', "speeds must be from the lower to the higher")
        self.assertLispError('(deal-pac! deal "POOL" "A" "B" 0 100)', "speeds must be from the lower to the higher")
        self.assertShows("(deal-names deal)", '("POOL")')                               # (nothing was added)
        self.run_lisp('(define hand (make-collateral :name "H" :balance (vector 10.0 0.0) :principal (vector 10.0)))'
                      ' (define deal (start-deal "d" hand))')
        self.assertLispError('(deal-pac! deal "H" "A" "B" 100 300)', "made by collateral-from-psa")
        self.assertShows("(deal-names deal)", '("H")')

    def test_a_pac_split_has_two_children_the_pac_and_the_companion(self):
        self.run_lisp('(define pool (collateral-from-psa "POOL" 100.0 6.5)) (define deal (start-deal "d" pool))')
        self.run_lisp('(deal-add-tranche! deal "A" 0.0) (deal-add-tranche! deal "B" 0.0) (deal-add-tranche! deal "C" 0.0)')
        self.assertLispError("""(deal-add-split! deal "POOL" (make-pac-split :children '("A" "B" "C") :low-psa 100 :high-psa 300))""",
                             "has two children: the PAC and the companion")


class TestAPacUnderAnotherNode(DealTestCase):
    """The PAC is sized from what its parent is paid, whether the parent is the collateral or not: a second PAC, from the first one's
    companion. The deal is run at each speed, down to the parent."""

    def pool_principal(self, psa):
        flows = self.run_lisp("(pool-cash-flows 100000000.0 6.5 360 0 %d)" % psa)
        return np.array(lisp_core.pairs_to_list(flows)[0].items)

    def two_pacs(self, psa, first=(100, 300), second=(150, 250)):
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :psa %d))
                         (define deal (start-deal "two pacs" pool))
                         (deal-pac! deal "POOL" "PAC1" "COMP1" %d %d)
                         (deal-pac! deal "COMP1" "PAC2" "COMP2" %d %d)
                         (deal-run! deal)''' % ((psa,) + first + second))

    def schedule(self, owner):
        return self.vector('(pac-split-schedule (node-split (get-node deal "%s")))' % owner)

    def test_the_principal_of_a_node_at_another_speed_is_found_by_running_the_deal_down_to_it(self):
        self.two_pacs(200)
        np.testing.assert_allclose(self.vector('(deal-principal-at deal "POOL" 150)'), self.pool_principal(150), rtol=1e-12)
        schedule1 = self.schedule("POOL")
        pac1 = schedule1[:-1] - schedule1[1:]                                      # (what the PAC is paid at any speed in its bands)
        for psa in (100, 180, 300):
            np.testing.assert_allclose(self.vector('(deal-principal-at deal "PAC1" %d)' % psa), pac1, atol=1e-5)
            np.testing.assert_allclose(self.vector('(deal-principal-at deal "COMP1" %d)' % psa), self.pool_principal(psa) - pac1,
                                       atol=1e-5)

    def test_it_does_not_change_the_deal(self):
        self.two_pacs(200)
        before = {name: (self.principal(name).copy(), self.balance(name).copy()) for name in ("POOL", "PAC1", "COMP1", "PAC2", "COMP2")}
        self.run_lisp('(deal-principal-at deal "COMP2" 400)')
        for name, (principal, balance) in before.items():
            np.testing.assert_array_equal(self.principal(name), principal)
            np.testing.assert_array_equal(self.balance(name), balance)
        self.assertShows("(deal-names deal)", '("POOL" "PAC1" "COMP1" "PAC2" "COMP2")')

    def test_the_second_pac_is_as_big_as_the_least_its_parent_is_paid_at_the_two_speeds(self):
        self.two_pacs(200)
        pac1 = self.schedule("POOL")
        pac1 = pac1[:-1] - pac1[1:]
        least = np.minimum(self.pool_principal(150) - pac1, self.pool_principal(250) - pac1)
        self.assertAlmostEqual(self.balance("PAC2")[0], least.sum(), places=3)
        self.assertAlmostEqual(self.balance("COMP2")[0], self.balance("COMP1")[0] - least.sum(), places=3)
        schedule2 = self.schedule("COMP1")
        self.assertAlmostEqual(schedule2[0], least.sum(), places=3)
        np.testing.assert_allclose(schedule2[1:], schedule2[:-1] - least, atol=1e-5)

    def test_each_pac_is_on_schedule_at_the_speeds_of_its_own_bands(self):
        for psa in (150, 200, 250):                                               # (in the bands of both)
            with self.subTest(psa=psa):
                self.two_pacs(psa)
                np.testing.assert_allclose(self.balance("PAC1"), self.schedule("POOL"), atol=1e-5)
                np.testing.assert_allclose(self.balance("PAC2"), self.schedule("COMP1"), atol=1e-5)
                self.assertShows("(deal-check deal)", "#t")
        for psa in (110, 290):                                                    # (in the first only)
            with self.subTest(psa=psa):
                self.two_pacs(psa)
                np.testing.assert_allclose(self.balance("PAC1"), self.schedule("POOL"), atol=1e-5)
                self.assertGreater(np.abs(self.balance("PAC2") - self.schedule("COMP1")).max(), 1000.0)
                self.assertShows("(deal-check deal)", "#t")

    def test_the_leaves_of_a_deal_of_two_pacs_add_up_to_the_pool(self):
        self.two_pacs(130)
        total = sum(self.principal(name) for name in ("PAC1", "PAC2", "COMP2"))
        np.testing.assert_allclose(total, self.principal("POOL"), rtol=1e-12, atol=1e-5)


class TestSizesAreWorkedOutBySplits(DealTestCase):
    """Every kind of split has a calculate-sizes method (the one for split, any kind, works nothing out), and another kind can."""

    def test_a_split_that_works_out_the_sizes_of_its_children_sets_their_balances(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""
          (defstruct (halves-split (:include sequential-split)))
          (defmethod calculate-sizes ((split halves-split) deal parent)
            (let ((half (/ (vector-ref (node-balance parent) 0) 2)))
              (list half half)))
          (deal-add-tranche! deal "A" 0.0)
          (deal-add-tranche! deal "B" 0.0)
          (deal-add-split! deal "POOL" (make-halves-split :children '("A" "B")))
          (deal-run! deal)""")
        np.testing.assert_allclose(self.balance("A"), [60, 30, 0, 0, 0])
        np.testing.assert_allclose(self.balance("B"), [60, 60, 60, 30, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_sizes_a_split_works_out_must_add_up_to_the_parent(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""
          (defstruct (small-split (:include sequential-split)))
          (defmethod calculate-sizes ((split small-split) deal parent) (list 10.0 10.0))
          (deal-add-tranche! deal "A" 0.0)
          (deal-add-tranche! deal "B" 0.0)""")
        self.assertLispError("""(deal-add-split! deal "POOL" (make-small-split :children '("A" "B")))""", "add up to 20.0, and POOL has 120.0")

    def test_a_sequential_split_leaves_the_sizes_as_they_were_made(self):
        self.a_pool_paying(30.0, 4)
        self.run_lisp("""(define split (make-sequential-split :children '("A" "B")))""")
        self.assertShows("(calculate-sizes split deal pool)", "()")
        self.assertShows("(generic-function-methods calculate-sizes)", "(split floater-inverse-split premium-discount-split io-po-split pac-split)")


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
