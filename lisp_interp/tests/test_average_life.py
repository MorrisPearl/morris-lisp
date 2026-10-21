"""The average life of a bond, and the split that works out the sizes of its children from the average lives that they are to have
(lib/deal.lsp: average-life, deal-average-life, average-life-split, average-life-plan, deal-average-life!)."""

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class AverageLifeCase(LispTestCase):

    PIECES = "'((100000000.0 6.0 5.5 360) (50000000.0 7.0 6.5 240 12))"

    def setUp(self):
        super().setUp()
        self.run_lisp('''(load "deal.lsp")
                         (define (make-deal-of &key (speed (prepayment-speed 'psa 150)))
                           (start-deal "Demo" (collateral-from-pieces "POOL" %s speed) :first-payment (date 2026 11 25)))
                         (define deal (make-deal-of))''' % self.PIECES)

    def life(self, name):
        return self.run_lisp('(deal-average-life deal "%s")' % name)

    def size(self, name):
        return self.run_lisp('(vector-ref (node-balance (get-node deal "%s")) 0)' % name)

    def principal(self, src):
        return np.array(self.run_lisp(src).items, dtype=float)


class TestAverageLife(AverageLifeCase):

    def test_it_is_the_months_weighted_by_the_principal_over_twelve(self):
        self.assertShows("(average-life (vector 100.0))", "0.08333333333333333")
        self.assertAlmostEqual(self.run_lisp("(average-life (vector 50.0 0.0 0.0 50.0))"), (1 * 50 + 4 * 50) / 100 / 12)
        self.assertAlmostEqual(self.run_lisp("(average-life (vector 0.0 0.0 12.0))"), 3 / 12)

    def test_nothing_paid_has_no_average_life(self):
        self.assertLispError("(average-life (vector 0.0 0.0))", "no principal is paid")

    def test_the_life_of_a_bond_is_that_of_what_it_was_paid_by_the_last_run(self):
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 50000000.0) ("B" 100000000.0)))
                         (deal-run! deal)''')
        paid = self.principal('(node-principal (get-node deal "A"))')
        self.assertAlmostEqual(self.life("A"), (np.arange(1, len(paid) + 1) * paid).sum() / paid.sum() / 12)
        self.assertGreater(self.life("B"), self.life("A"))

    def test_the_life_of_the_whole_pool_is_between_its_bonds(self):
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 50000000.0) ("B" 100000000.0)))
                         (deal-run! deal)''')
        self.assertLess(self.life("A"), self.life("POOL"))
        self.assertLess(self.life("POOL"), self.life("B"))


class TestSizingByAverageLife(AverageLifeCase):

    def lives_after_run(self, names):
        self.run_lisp("(deal-run! deal)")
        return [self.life(name) for name in names]

    def test_the_last_bond_is_what_is_left_and_each_of_the_others_has_the_life_it_was_given(self):
        self.run_lisp('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2" 5.0) ("A3")))''')
        a1, a2, a3 = self.lives_after_run(("A1", "A2", "A3"))
        self.assertAlmostEqual(a1, 2.0, places=8)
        self.assertAlmostEqual(a2, 5.0, places=8)
        self.assertGreater(a3, 5.0)
        self.assertAlmostEqual(self.size("A1") + self.size("A2") + self.size("A3"), 150000000.0, places=3)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_one_that_is_left_can_be_first_in_the_middle_or_last(self):
        """Bonds are made of sizes first, and their lives are what they are paid; the split, given all the lives but one, must find the sizes."""
        for shares, free in (((0.1, 0.2, 0.3, 0.4), 0), ((0.1, 0.2, 0.3, 0.4), 1), ((0.1, 0.2, 0.3, 0.4), 3),
                             ((0.05, 0.1, 0.2, 0.25, 0.4), 2), ((0.6, 0.4), 0), ((0.6, 0.4), 1)):
            with self.subTest(shares=shares, free=free):
                names = ["B%d" % (i + 1) for i in range(len(shares))]
                sizes = [150000000.0 * share for share in shares]
                self.run_lisp("(define deal (make-deal-of))")
                self.run_lisp("(deal-sequential! deal \"POOL\" '(%s))" % " ".join('("%s" %r)' % pair for pair in zip(names, sizes)))
                self.run_lisp("(deal-run! deal)")
                lives = [self.life(name) for name in names]
                children = " ".join('("%s")' % name if i == free else '("%s" %r)' % (name, life)
                                    for i, (name, life) in enumerate(zip(names, lives)))
                self.run_lisp("(define deal (make-deal-of))")
                self.run_lisp("(deal-average-life! deal \"POOL\" '(%s))" % children)
                for name, size in zip(names, sizes):
                    self.assertAlmostEqual(self.size(name) / size, 1.0, places=6, msg=name)
                achieved = self.lives_after_run(names)
                for i, (want, got) in enumerate(zip(lives, achieved)):
                    self.assertAlmostEqual(got, want, places=7)
                self.assertShows("(deal-check deal)", "#t")

    def test_the_lives_are_by_the_months_of_the_pricing_speed(self):
        """Faster prepayments pay the same lives with smaller bonds in front."""
        sizes = {}
        for speed in (100, 300):
            self.run_lisp("(define deal (make-deal-of :speed (prepayment-speed 'psa %d)))" % speed)
            self.run_lisp('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2")))''')
            sizes[speed] = self.size("A1")
        self.assertLess(sizes[100], sizes[300])

    def test_the_first_size_is_what_a_bond_of_that_life_has_by_a_calculation_of_my_own(self):
        """The principal of the pool, in order: the first bond is the first so many dollars of it, whose life is found here, not by the split."""
        self.run_lisp('''(deal-average-life! deal "POOL" '(("A1" 3.0) ("A2")))''')
        principal = self.principal('(node-principal (get-node deal "POOL"))')
        size = self.size("A1")
        paid = np.diff(np.concatenate([[0.0], np.minimum(np.cumsum(principal), size)]))
        self.assertAlmostEqual(paid.sum(), size, places=3)
        self.assertAlmostEqual((np.arange(1, len(paid) + 1) * paid).sum() / paid.sum() / 12, 3.0, places=8)

    def test_a_child_below_another_split_is_sized_from_what_its_parent_is_paid(self):
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-pac! deal "A" "AP" "AC" 100 300)
                         (deal-average-life! deal "AC" '(("AC1" 3.0) ("AC2")))''')
        self.run_lisp("(deal-run! deal)")
        self.assertAlmostEqual(self.life("AC1"), 3.0, places=8)
        self.assertAlmostEqual(self.size("AC1") + self.size("AC2"), self.size("AC"), places=3)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_change_above_works_the_sizes_out_again_so_the_lives_still_hold(self):
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-average-life! deal "A" '(("A1" 2.0) ("A2" 4.0) ("A3")))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 100000000.0) ("B" 50000000.0))))''')
        before = self.size("A1") + self.size("A2") + self.size("A3")
        self.assertAlmostEqual(before, 100000000.0, places=3)
        a1, a2 = self.lives_after_run(("A1", "A2"))
        self.assertAlmostEqual(a1, 2.0, places=8)
        self.assertAlmostEqual(a2, 4.0, places=8)

    def test_a_change_of_the_lives_is_a_change_of_the_sizes(self):
        self.run_lisp('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2")))''')
        small = self.size("A1")
        self.run_lisp('''(deal-replace-split! deal "POOL" (average-life-plan '(("A1" 6.0) ("A2"))))''')
        self.assertGreater(self.size("A1"), small)
        self.assertAlmostEqual(self.lives_after_run(("A1",))[0], 6.0, places=8)

    def test_the_split_is_a_sequential_split_that_pays_in_order_and_has_a_label_of_its_own(self):
        self.run_lisp('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2")) :losses 'forward)''')
        self.assertShows('(sequential-split? (node-split (get-node deal "POOL")))', "#t")
        self.assertShows('(average-life-split? (node-split (get-node deal "POOL")))', "#t")
        self.assertShows('(split-label (node-split (get-node deal "POOL")))', '"sequential by average life"')
        self.assertShows('(split-loss-rule (node-split (get-node deal "POOL")))', "forward")
        self.assertShows('(average-life-split-lives (node-split (get-node deal "POOL")))', "(2.0 ())")
        self.assertShows("(deal-names deal)", '("POOL" "A1" "A2")')

    def test_a_life_that_the_cash_flows_cannot_give_is_an_error_that_says_what_they_can(self):
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" 40.0) ("A2")))''', "A1 cannot have an average life of 40.0 years")
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" 0.01) ("A2")))''', "can have from")
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_lives_that_leave_nothing_for_the_bond_that_is_left_are_an_error(self):
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" 8.0) ("A2")  ("A3" 12.0)))''', "leave nothing for A2")
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_all_but_one_of_the_children_are_given_a_life(self):
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2" 4.0)))''', "all but one of its children")
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1") ("A2")))''', "all but one of its children")
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2") ("A3")))''', "all but one of its children")

    def test_a_life_is_a_number_of_years_above_nothing_and_a_child_is_a_name_and_perhaps_a_life(self):
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" -2.0) ("A2")))''', "a number of years above 0")
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" "two") ("A2")))''', "a number of years above 0")
        self.assertLispError('''(deal-average-life! deal "POOL" '(("A1" 2.0 3.0) ("A2")))''', "a child is (name years)")
        self.assertLispError('''(deal-average-life! deal "POOL" '("A1" ("A2")))''', "a child is (name years)")

    def test_a_z_bond_cannot_be_a_child(self):
        self.run_lisp('''(define plan (average-life-plan '(("A1" 2.0) ("A2"))))
                         (deal-add-tranche! deal "A1" 1.0 :z #t)
                         (deal-add-tranche! deal "A2" 1.0)''')
        self.assertLispError('(deal-add-split! deal "POOL" (split-plan-split plan))', "A1 is a Z bond")

    def test_the_parent_has_to_be_paid_in_full_for_the_lives_to_mean_anything(self):
        self.run_lisp('''(define bare (make-collateral :name "POOL" :balance (vector 100.0 40.0 0.0) :principal (vector 30.0 30.0)
                                                      :interest (vector 0.0 0.0) :coupon (constant-coupon 0.05)))
                         (define short (start-deal "Short" bare))''')
        self.assertLispError('''(deal-average-life! short "POOL" '(("A1" 1.0) ("A2")))''', "is paid 60.00 of principal in all, and its balance is 100.00")

    def test_a_deal_with_no_pieces_works_too(self):
        self.run_lisp('''(define deal (start-deal "Plain" (collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :psa 150)))
                         (deal-average-life! deal "POOL" '(("A1" 2.0) ("A2" 5.0) ("A3")))''')
        self.assertAlmostEqual(self.lives_after_run(("A1",))[0], 2.0, places=8)

    def test_the_sizes_a_plan_would_have_are_shown_without_changing_the_deal(self):
        self.run_lisp('''(define plan (average-life-plan '(("A1" 2.0) ("A2"))))''')
        sizes = self.run_lisp('(split-plan-sizes deal (get-node deal "POOL") plan)')
        self.assertAlmostEqual(sizes.car + sizes.cdr.car, 150000000.0, places=3)
        self.assertShows("(deal-names deal)", '("POOL")')
