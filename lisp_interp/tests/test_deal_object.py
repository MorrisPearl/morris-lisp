"""A deal that has the data of its collateral (new-deal in lib/deal.lsp): the collateral as a table, the cash flows of it that are the root of
the tree, worked out again at the pricing speed, or at the speed that deal-run! is given; and what changing the collateral, or the pricing speed,
does to the tranches under it. And the views of a deal, which are told when it changes."""

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class DealObjectCase(LispTestCase):

    PIECES = "'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.5 240 12))"

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal.lsp")')

    def make(self, collateral=None, speed="(prepayment-speed 'psa 150)"):
        self.run_lisp('(define deal (new-deal "Demo" :first-payment (date 2026 11 25) :closing-date (date 2026 11 20) :speed %s :collateral %s))'
                      % (speed, collateral or self.PIECES))

    def vector(self, src):
        return np.array(self.run_lisp(src).items, dtype=float)

    def balance(self, name):
        return self.run_lisp('(vector-ref (node-balance (get-node deal "%s")) 0)' % name)

    def signature(self):
        """Everything about the tranches that a change of the collateral could change, to the cent and a billionth."""
        return self.show('''(map (lambda (name)
                                    (let ((node (get-node deal name)))
                                      (list name (round (* 100 (vector-ref (node-balance node) 0))) (vector-length (node-principal node))
                                            (if (null? (node-split node)) '() (list (split-label (node-split node)) (split-children (node-split node)))))))
                                  (deal-names deal))''')


class TestMakingADeal(DealObjectCase):

    def test_a_new_deal_has_one_tranche_the_cash_flows_of_its_collateral_which_has_none_yet(self):
        self.run_lisp('(define deal (new-deal "Demo"))')
        self.assertShows("(deal-names deal)", '("POOL")')
        self.assertShows("(deal-root deal)", '"POOL"')
        self.assertShows("(deal-periods deal)", "0")
        self.assertShows("(deal-size deal)", "0.0")
        self.assertShows("(collateral? (get-node deal \"POOL\"))", "#t")
        self.assertShows("(table-row-count (deal-collateral deal))", "0")
        self.assertShows("(describe-speed (deal-pricing-speed deal))", '"PSA 100"')
        self.assertShows("(deal-first-payment deal)", "()")
        self.assertShows("(deal-closing-date deal)", "()")
        self.assertShows("(deal-ran deal)", "#f")

    def test_the_name_of_the_collateral_the_speed_and_the_dates_are_asked_for(self):
        self.run_lisp('''(define deal (new-deal "Demo" :collateral-name "COLL" :speed (prepayment-speed 'cpr 8)
                                                 :first-payment (date 2026 11 25) :closing-date (date 2026 11 20)))''')
        self.assertShows("(deal-names deal)", '("COLL")')
        self.assertShows("(describe-speed (deal-pricing-speed deal))", '"CPR 8"')
        self.assertShows("(deal-first-payment deal)", "2026-11-25")
        self.assertShows("(deal-closing-date deal)", "2026-11-20")
        self.assertShows("(deal-name deal)", '"Demo"')

    def test_what_is_wrong_with_the_arguments_is_said(self):
        self.assertLispError('(new-deal "Demo" :speed 100)', "the speed is made by prepayment-speed")
        self.assertLispError('(new-deal "Demo" :closing-date "2026-11-20")', ":closing-date is a date")
        self.assertLispError('(new-deal "Demo" :first-payment 5)', ":first-payment is a date")

    def test_the_collateral_given_with_the_deal_is_its_data_and_its_cash_flows_are_the_root(self):
        self.make()
        self.assertShows("(deal-periods deal)", "360")
        self.assertShows("(deal-size deal)", "150000000.0")
        flows = [np.array(v.items) for v in lisp_core.pairs_to_list(self.run_lisp(
            "(project-pieces %s (prepayment-speed 'psa 150))" % self.PIECES))]
        np.testing.assert_allclose(self.vector('(node-principal (get-node deal "POOL"))'), flows[0])
        np.testing.assert_allclose(self.vector('(node-interest (get-node deal "POOL"))'), flows[1])
        np.testing.assert_allclose(self.vector('(node-balance (get-node deal "POOL"))'), flows[2])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_collateral_is_a_table_that_can_come_from_a_list_of_pieces_or_anywhere(self):
        self.run_lisp('''(define table (make-table "balance" (vector 100000000.0 50000000.0) "wac" (vector 6.5 7.5) "coupon" (vector 6.0 6.5) "wam" (vector 360 240)))
                         (define deal (new-deal "Demo" :collateral table))''')                       # (no age: 0)
        self.assertShows("(deal-size deal)", "150000000.0")
        self.assertShows("(collateral-table-pieces (deal-collateral deal))", "((100000000.0 6.5 6.0 360 0) (50000000.0 7.5 6.5 240 0))")
        self.assertShows("(table-column (collateral-table '((1000.0 6.0 5.5 12 3))) \"age\")", "#(3)")

    def test_a_row_with_no_balance_is_left_out(self):
        self.run_lisp('''(define deal (new-deal "Demo" :collateral '((100000000.0 6.5 6.0 360) (0.0 0.0 0.0 0 0) (50000000.0 7.5 6.5 240 12))))''')
        self.assertShows("(length (collateral-table-pieces (deal-collateral deal)))", "2")

    def test_a_table_that_is_not_collateral_is_said_not_to_be(self):
        self.assertLispError("(collateral-table-pieces 5)", "the collateral is a table")
        self.assertLispError('(collateral-table-pieces (make-table "balance" (vector 1.0) "wac" (vector 6.0)))', "has no column coupon")
        self.assertLispError("(collateral-table '((1 2 3)))", "a piece of collateral is (balance wac coupon wam [age])")
        self.assertLispError('(new-deal "Demo" :collateral (make-table "x" (vector 1.0)))', "has no column balance")

    def test_the_dates_are_checked_and_each_payment_has_its_date(self):
        self.make()
        self.assertShows("(deal-payment-date deal 2)", "2026-12-25")
        self.assertLispError("(deal-set-first-payment! deal 5)", "the first payment is a date")
        self.assertLispError('(deal-set-closing-date! deal "x")', "the closing date is a date")
        self.run_lisp("(deal-set-closing-date! deal (date 2026 12 1)) (deal-set-first-payment! deal (date 2027 1 25))")
        self.assertShows("(deal-closing-date deal)", "2026-12-01")
        self.assertShows("(deal-payment-date deal 1)", "2027-01-25")


class TestOneCouponWhateverTheWacs(DealObjectCase):
    """Pieces that are passed through at the same coupon pay the same rate whatever their wacs are, so a floater can be made of them."""

    def test_pieces_with_the_same_coupon_and_different_wacs_have_a_fixed_coupon(self):
        self.make("'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))")
        self.assertShows('(vector? (node-coupon (get-node deal "POOL")))', "#f")
        self.assertAlmostEqual(self.run_lisp('((node-coupon (get-node deal "POOL")) 0.0)'), 0.06)

    def test_a_floater_and_an_inverse_floater_can_be_made_of_them(self):
        self.make("'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))")
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.0975)')
        self.assertAlmostEqual(self.balance("F"), 150000000.0 * 0.06 / 0.0975, places=4)
        self.assertShows("(begin (deal-run! deal :index 0.04) (deal-check deal))", "#t")

    def test_so_can_a_premium_and_a_discount_bond(self):
        self.make("'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))")
        self.run_lisp('(deal-premium-discount! deal "POOL" "P" "D" :premium-coupon 0.07 :discount-coupon 0.05)')
        self.assertShows("(begin (deal-run! deal) (deal-check deal))", "#t")

    def test_pieces_with_different_coupons_still_have_one_for_each_month_and_say_why_a_floater_cannot_be_made(self):
        self.make()
        self.assertShows('(vector? (node-coupon (get-node deal "POOL")))', "#t")
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.09)', "is not the same every month")


class TestRunningADeal(DealObjectCase):

    def test_a_deal_is_run_at_its_pricing_speed_unless_it_is_given_another(self):
        self.make()
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.run_lisp("(deal-run! deal)")
        at_pricing = self.vector('(node-principal (get-node deal "A"))')
        self.assertShows("(deal-check deal)", "#t")
        self.assertShows("(describe-speed (deal-ran deal))", '"PSA 150"')
        self.run_lisp("(deal-run! deal (prepayment-speed 'psa 300))")
        faster = self.vector('(node-principal (get-node deal "A"))')
        self.assertShows("(deal-check deal)", "#t")
        self.assertShows("(describe-speed (deal-ran deal))", '"PSA 300"')
        self.assertGreater(faster[:12].sum(), at_pricing[:12].sum())
        np.testing.assert_allclose(self.vector('(node-principal (get-node deal "POOL"))')[:3],
                                   self.vector("(car (project-pieces %s (prepayment-speed 'psa 300)))" % self.PIECES)[:3])
        self.run_lisp("(deal-run! deal)")                         # (and run at the pricing speed again, it is as it was)
        np.testing.assert_allclose(self.vector('(node-principal (get-node deal "A"))'), at_pricing)

    def test_the_collateral_is_run_again_every_time_so_a_change_of_its_pieces_shows(self):
        self.make()
        self.run_lisp("(deal-run! deal)")
        before = self.vector('(node-principal (get-node deal "POOL"))')
        self.run_lisp('(deal-set-collateral! deal \'((100000000.0 6.5 6.0 360)))')
        self.run_lisp("(deal-run! deal)")
        self.assertNotEqual(self.vector('(node-principal (get-node deal "POOL"))')[0], before[0])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_sizes_of_the_tranches_are_not_changed_by_the_speed_that_it_is_run_at(self):
        self.make()
        self.run_lisp('''(deal-pac! deal "POOL" "P" "C" 100 300)
                         (deal-average-life! deal "C" '(("C1" 3.0) ("C2")))''')
        sizes = [self.balance(n) for n in ("P", "C", "C1", "C2")]
        self.run_lisp("(deal-run! deal (prepayment-speed 'cpr 30))")
        self.assertEqual([self.balance(n) for n in ("P", "C", "C1", "C2")], sizes)

    def test_a_pac_is_on_schedule_at_any_speed_inside_its_bands_and_off_it_outside(self):
        self.make()
        self.run_lisp('(deal-pac! deal "POOL" "P" "C" 100 300)')
        schedule = self.vector('(pac-split-schedule (node-split (get-node deal "POOL")))')
        for psa, on_schedule in ((100, True), (200, True), (300, True), (500, False)):
            with self.subTest(psa=psa):
                self.run_lisp("(deal-run! deal (prepayment-speed 'psa %d))" % psa)
                balance = self.vector('(node-balance (get-node deal "P"))')[: len(schedule)]
                self.assertEqual(bool(np.allclose(balance, schedule, atol=1e-3)), on_schedule)
                self.assertShows("(deal-check deal)", "#t")

    def test_a_speed_that_changes_with_time_can_be_run(self):
        self.make()
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.run_lisp("(deal-run! deal (prepayment-speed 'cpr '((4 4 6) (4 20 12))) :index 0.04)")
        self.assertShows("(deal-check deal)", "#t")

    def test_a_floater_is_given_its_index_as_before(self):
        self.make("'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))")
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.0975)')
        self.assertLispError("(deal-run! deal)", "give deal-run! an :index")
        self.run_lisp("(deal-run! deal (prepayment-speed 'psa 200) :index 0.03)")
        self.assertShows("(deal-check deal)", "#t")

    def test_what_deal_run_is_given_is_checked(self):
        self.make()
        for src in ("(deal-run! deal 5)", "(deal-run! deal :speed 5)", "(deal-run! deal :index)", "(deal-run! deal (prepayment-speed 'psa 100) 0.04)",
                    "(deal-run! deal :index 0.04 :index 0.05)"):
            with self.subTest(src=src):
                self.assertLispError(src, "expected (deal-run! deal [speed] [:index index])")

    def test_a_deal_with_no_collateral_yet_runs_without_months(self):
        self.run_lisp('(define deal (new-deal "Demo"))')
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")
        self.assertShows("(equal? (deal-ran deal) (deal-pricing-speed deal))", "#t")          # (it has the speed of the run that it was)


class TestChangingTheCollateral(DealObjectCase):

    def build(self):
        self.make()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-pac! deal "A" "AP" "AC" 100 300)
                         (deal-average-life! deal "B" '(("B1" 10.0) ("B2")))''')

    def test_the_tranches_whose_sizes_were_given_keep_their_shares_and_those_that_are_worked_out_are_worked_out_again(self):
        self.build()
        shares = {n: self.balance(n) / 150000000.0 for n in ("A", "B")}
        self.run_lisp("(deal-set-collateral! deal '((200000000.0 6.5 6.0 360) (100000000.0 7.5 6.5 240 12)))")
        self.assertAlmostEqual(self.run_lisp("(deal-size deal)"), 300000000.0)
        for name in ("A", "B"):
            self.assertAlmostEqual(self.balance(name) / 300000000.0, shares[name], places=9)
        self.assertAlmostEqual(self.balance("AP") + self.balance("AC"), self.balance("A"), places=3)
        self.assertAlmostEqual(self.balance("B1") + self.balance("B2"), self.balance("B"), places=3)
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "B1")'), 10.0, places=8)

    def test_the_coupons_of_the_tranches_are_those_of_the_new_collateral_at_once_and_not_only_when_it_is_run(self):
        self.build()
        self.run_lisp("(deal-set-collateral! deal '((200000000.0 6.5 6.0 360) (100000000.0 7.5 6.5 240 12)))")
        self.assertShows('(eq? (node-coupon (get-node deal "A")) (node-coupon (get-node deal "POOL")))', "#t")
        self.assertShows('(eq? (node-coupon (get-node deal "AP")) (node-coupon (get-node deal "POOL")))', "#t")
        np.testing.assert_allclose(self.vector('(node-coupon (get-node deal "A"))'),
                                   self.vector("(let ((flows (project-pieces '((200000000.0 6.5 6.0 360) (100000000.0 7.5 6.5 240 12)) (prepayment-speed 'psa 150)))) (pool-coupons (cadr flows) (caddr flows)))"))

    def test_it_is_the_same_as_a_deal_made_with_the_collateral_in_the_first_place(self):
        self.build()
        self.run_lisp("(deal-set-collateral! deal '((200000000.0 6.5 6.0 360) (100000000.0 7.5 6.5 240 12)))")
        self.run_lisp('''(define direct (new-deal "Demo" :speed (prepayment-speed 'psa 150)
                                                   :collateral '((200000000.0 6.5 6.0 360) (100000000.0 7.5 6.5 240 12))))
                         (deal-sequential! direct "POOL" '(("A" 180000000.0) ("B" 120000000.0)))
                         (deal-pac! direct "A" "AP" "AC" 100 300)
                         (deal-average-life! direct "B" '(("B1" 10.0) ("B2")))''')
        for name in ("A", "B", "AP", "AC", "B1", "B2"):
            self.assertAlmostEqual(self.balance(name), self.run_lisp('(vector-ref (node-balance (get-node direct "%s")) 0)' % name), places=3, msg=name)

    def test_the_months_can_change_and_every_tranche_has_vectors_as_long_as_the_new_deal(self):
        self.build()
        self.run_lisp("(deal-set-collateral! deal '((100000000.0 6.5 6.0 240)))")
        self.assertShows("(deal-periods deal)", "240")
        self.assertShows('(map (lambda (name) (vector-length (node-principal (get-node deal name)))) (deal-names deal))', "(240 240 240 240 240 240 240)")
        self.assertShows('(map (lambda (name) (vector-length (node-balance (get-node deal name)))) (deal-names deal))', "(241 241 241 241 241 241 241)")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")
        self.run_lisp("(deal-set-collateral! deal '((100000000.0 6.5 6.0 360)))")
        self.assertShows("(deal-periods deal)", "360")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")

    def test_the_index_is_forgotten_when_the_months_change(self):
        self.make("'((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))")
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.0975) (deal-run! deal :index 0.04)')
        self.run_lisp("(deal-set-collateral! deal '((100000000.0 6.5 6.0 300)))")
        self.assertShows("(deal-index deal)", "()")
        self.run_lisp("(deal-run! deal :index 0.04)")
        self.assertShows("(deal-check deal)", "#t")

    def test_nothing_is_changed_if_a_split_below_cannot_be_worked_out_again(self):
        self.build()
        before = self.signature()
        table = self.show("(deal-collateral deal)")
        # a pool whose cash flows are so short that no bond can have an average life of 3 years from the end of it
        self.assertLispError("(deal-set-collateral! deal '((150000000.0 6.5 6.0 24)))", "cannot have an average life")
        self.assertEqual(self.signature(), before)
        self.assertEqual(self.show("(deal-collateral deal)"), table)
        self.assertShows("(deal-periods deal)", "360")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")

    def test_what_is_wrong_with_the_new_collateral_is_said_and_nothing_is_changed(self):
        self.build()
        before = self.signature()
        for src, message in (("'()", "there is no collateral"), ("'((0 0 0 0))", "there is no collateral"),
                             ("'((1000.0 6.0 7.0 12))", "is above its wac"), ("5", "the collateral is a table, or a list of pieces")):
            with self.subTest(collateral=src):
                self.assertLispError("(deal-set-collateral! deal %s)" % src, message)
        self.assertEqual(self.signature(), before)

    def test_a_deal_with_no_tranches_yet_just_has_the_new_collateral(self):
        self.make()
        self.run_lisp("(deal-set-collateral! deal '((5000000.0 6.5 6.0 60)))")
        self.assertShows("(deal-size deal)", "5000000.0")
        self.assertShows("(deal-periods deal)", "60")

    def test_an_empty_deal_is_given_its_first_collateral(self):
        self.run_lisp('(define deal (new-deal "Demo")) (deal-set-collateral! deal \'((5000000.0 6.5 6.0 60)))')
        self.assertShows("(deal-periods deal)", "60")
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 3000000.0) ("B" 2000000.0))) (deal-run! deal)')
        self.assertShows("(deal-check deal)", "#t")


class TestChangingThePricingSpeed(DealObjectCase):

    def build(self):
        self.make()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-average-life! deal "A" '(("A1" 1.5) ("A2" 2.8) ("A3")))''')

    def test_the_cash_flows_are_worked_out_at_the_new_speed(self):
        self.make()
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 300))")
        np.testing.assert_allclose(self.vector('(node-principal (get-node deal "POOL"))'),
                                   self.vector("(car (project-pieces %s (prepayment-speed 'psa 300)))" % self.PIECES))
        self.assertShows("(describe-speed (deal-pricing-speed deal))", '"PSA 300"')

    def test_the_sizes_that_depend_on_it_are_worked_out_again_and_the_lives_hold(self):
        self.build()
        before = self.balance("A1")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 400))")
        self.assertGreater(self.balance("A1"), before)                         # (faster: a bond needs to be bigger for the same life)
        self.run_lisp("(deal-run! deal)")
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A1")'), 1.5, places=8)
        self.assertAlmostEqual(self.run_lisp('(deal-average-life deal "A2")'), 2.8, places=8)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_bond_added_after_a_run_at_another_speed_is_sized_at_the_pricing_speed(self):
        self.make()
        self.run_lisp("(deal-run! deal (prepayment-speed 'psa 500))")
        self.run_lisp('(deal-average-life! deal "POOL" \'(("A1" 2.0) ("A2")))')
        sized_after = self.balance("A1")
        self.run_lisp('''(define fresh (new-deal "Fresh" :speed (prepayment-speed 'psa 150) :collateral %s))
                         (deal-average-life! fresh "POOL" '(("A1" 2.0) ("A2")))''' % self.PIECES)
        self.assertAlmostEqual(sized_after, self.run_lisp('(vector-ref (node-balance (get-node fresh "A1")) 0)'), places=3)

    def test_nothing_is_changed_if_it_cannot_be_done(self):
        self.build()
        before = self.signature()
        self.assertLispError("(deal-set-pricing-speed! deal 5)", "the speed is made by prepayment-speed")
        self.assertEqual(self.signature(), before)


class TestSomethingThatShowsTheDeal(DealObjectCase):
    """A view is a function that is called when the deal changes in a kind that it shows."""

    def setUp(self):
        super().setUp()
        self.make()
        self.run_lisp('''(define heard (list))
                         (define (listen kinds label) (deal-add-view! deal kinds (lambda () (set! heard (append heard (list label))))))
                         (listen '(tranches) "tranches")
                         (listen '(collateral) "collateral")
                         (listen '(info) "info")
                         (listen '(tranches collateral) "both")''')

    def heard(self):
        out = self.show("heard")
        self.run_lisp("(set! heard (list))")
        return out

    def test_a_change_of_the_tranches_is_heard_by_the_views_of_them(self):
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.assertEqual(self.heard(), '("tranches" "both")')
        self.run_lisp('(deal-pac! deal "A" "AP" "AC" 100 300)')
        self.assertEqual(self.heard(), '("tranches" "both")')
        self.run_lisp('(deal-replace-split! deal "A" (pac-plan "AP" "AC" 100 250))')
        self.assertEqual(self.heard(), '("tranches" "both")')
        self.run_lisp('(deal-delete-split! deal "A")')
        self.assertEqual(self.heard(), '("tranches" "both")')

    def test_a_change_of_the_collateral_is_heard_by_the_views_of_it_and_of_the_tranches(self):
        self.run_lisp("(deal-set-collateral! deal '((1000000.0 6.0 5.5 120)))")
        self.assertEqual(self.heard(), '("tranches" "collateral" "both")')

    def test_a_change_of_the_dates_or_the_speed_is_heard_by_the_views_of_them(self):
        self.run_lisp("(deal-set-closing-date! deal (date 2026 12 1))")
        self.assertEqual(self.heard(), '("info")')
        self.run_lisp("(deal-set-first-payment! deal (date 2027 1 25))")
        self.assertEqual(self.heard(), '("info")')
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 200))")
        self.assertEqual(self.heard(), '("tranches" "info" "both")')

    def test_a_change_that_fails_is_not_heard(self):
        self.run_lisp("(deal-sequential! deal \"POOL\" '((\"A\" 90000000.0) (\"B\" 60000000.0)))")
        self.heard()
        self.assertLispError("(deal-sequential! deal \"A\" '((\"X\" 1.0) (\"Y\" 1.0)))", "add up to")
        self.assertLispError("(deal-set-collateral! deal '())", "there is no collateral")
        self.assertEqual(self.heard(), "()")

    def test_a_view_that_goes_wrong_is_said_and_does_not_undo_the_change(self):
        self.run_lisp('(deal-add-view! deal \'(tranches) (lambda () (error "the screen is gone")))')
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.assertIn("a view of the deal could not be brought up to date: the screen is gone", self.printed())
        self.assertShows("(deal-names deal)", '("POOL" "A" "B")')
        self.assertEqual(self.heard(), '("tranches" "both")')                      # (and the views after it were told too)

    def test_a_trial_copy_has_no_views_so_trying_a_change_tells_nobody(self):
        self.run_lisp("(define trial (deal-trial-copy deal))")
        self.assertShows("(deal-views trial)", "()")
        self.run_lisp('(deal-trial-of-plan deal "POOL" (sequential-plan \'(("A" 90000000.0) ("B" 60000000.0))))')
        self.assertEqual(self.heard(), "()")

    def test_a_run_makes_the_deal_fresh_and_a_change_makes_it_stale(self):
        self.assertShows("(deal-ran deal)", "#f")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(describe-speed (deal-ran deal))", '"PSA 150"')
        self.run_lisp("(deal-set-closing-date! deal (date 2026 12 1))")
        self.assertShows("(deal-ran deal)", "#f")
        self.run_lisp("(deal-run! deal)")
        self.run_lisp('(deal-sequential! deal "POOL" \'(("A" 90000000.0) ("B" 60000000.0)))')
        self.assertShows("(deal-ran deal)", "#f")

    def test_the_trial_copy_has_the_collateral_the_speed_and_the_dates(self):
        self.run_lisp("(define trial (deal-trial-copy deal))")
        self.assertShows("(equal? (deal-collateral trial) (deal-collateral deal))", "#t")
        self.assertShows("(equal? (deal-pricing-speed trial) (deal-pricing-speed deal))", "#t")
        self.assertShows("(deal-first-payment trial)", "2026-11-25")
        self.assertShows("(deal-closing-date trial)", "2026-11-20")


class TestTheCashFlowsOfATranche(DealObjectCase):

    def build(self):
        self.make()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-run! deal)''')

    def test_the_table_has_a_row_for_each_month_and_the_columns_of_what_is_paid(self):
        self.build()
        columns = self.run_lisp('(map car (deal-flows-table deal "A"))')
        self.assertEqual([str(c) for c in lisp_core.pairs_to_list(columns)], ["month", "payment date", "balance", "principal", "interest"])
        self.assertShows('(table-row-count (deal-flows-table deal "A"))', "360")
        np.testing.assert_allclose(self.vector('(table-column (deal-flows-table deal "A") "principal")'), self.vector('(node-principal (get-node deal "A"))'))
        np.testing.assert_allclose(self.vector('(table-column (deal-flows-table deal "A") "balance")'), self.vector('(node-balance (get-node deal "A"))')[:360])
        self.assertShows('(vector-ref (table-column (deal-flows-table deal "A") "payment date") 1)', "2026-12-25")

    def test_some_of_the_months_can_be_asked_for_and_a_deal_with_no_dates_has_no_column_for_them(self):
        self.build()
        self.assertShows('(table-column (deal-flows-table deal "A" :months \'(1 12 360)) "month")', "#(1 12 360)")
        self.run_lisp('(define undated (new-deal "Undated" :collateral %s))' % self.PIECES)
        self.assertNotIn("payment date", self.show('(map car (deal-flows-table undated "POOL"))'))

    def test_what_is_accrued_written_down_or_carried_is_there_only_if_there_is_ever_any(self):
        self.run_lisp('''(define deal (new-deal "Z" :collateral '((100000000.0 6.5 6.0 360))))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("Z" 40000000.0 z)))
                         (deal-run! deal)''')
        self.assertIn("accrual", self.show('(map car (deal-flows-table deal "Z"))'))
        self.assertNotIn("accrual", self.show('(map car (deal-flows-table deal "A"))'))
        self.assertNotIn("loss", self.show('(map car (deal-flows-table deal "A"))'))

    def test_the_months_to_show_when_all_are_too_many(self):
        self.assertShows("(deal-summary-months 360)", "(1 12 24 36 48 60 72 84 96 108 120 132 144 156 168 180 192 204 216 228 240 252 264 276 288 300 312 324 336 348 360)")
        self.assertShows("(deal-summary-months 30)", "(1 12 24 30)")
        self.assertShows("(deal-summary-months 12)", "(1 12)")
        self.assertShows("(deal-summary-months 1)", "(1)")
