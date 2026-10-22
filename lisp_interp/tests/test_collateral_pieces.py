"""Prepayment speeds that change with time, the cash flows of pieces of collateral added together, and a deal made of them
(lib/prepayment_speed.lsp, and new-deal, deal-payment-dates and the coupon that is a vector, in lib/deal.lsp)."""

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make


class PiecesCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal.lsp")')

    def vector(self, src):
        return np.array(self.run_lisp(src).items, dtype=float)

    def flows(self, src):
        """The three vectors (principal, interest, balance) that the Lisp makes, as numpy arrays."""
        return [np.array(v.items, dtype=float) for v in lisp_core.pairs_to_list(self.run_lisp(src))]


class TestSpeeds(PiecesCase):

    def test_a_single_number_is_the_speed_in_every_month(self):
        np.testing.assert_allclose(self.vector("(speed-values (prepayment-speed 'psa 150) 4)"), [150, 150, 150, 150])
        np.testing.assert_allclose(self.vector("(speed-values (prepayment-speed 'cpr 6.5) 3)"), [6.5, 6.5, 6.5])

    def test_a_piece_goes_in_a_straight_line_and_is_at_its_to_in_its_last_month(self):
        """The PSA curve itself: 0 at the start to 6 CPR over 30 months, which is 0.2 CPR in month 1, up to 6 in month 30."""
        speeds = self.vector("(speed-values (prepayment-speed 'cpr '((0 6 30))) 32)")
        np.testing.assert_allclose(speeds[:3], [0.2, 0.4, 0.6])
        self.assertAlmostEqual(speeds[29], 6.0)
        self.assertEqual(list(speeds[30:]), [6.0, 6.0])                                   # (and it holds after the last piece)

    def test_pieces_follow_one_another_and_a_flat_piece_is_one_whose_ends_are_the_same(self):
        speeds = self.vector("(speed-values (prepayment-speed 'cpr '((5 5 3) (5 20 3))) 9)")
        np.testing.assert_allclose(speeds, [5, 5, 5, 10, 15, 20, 20, 20, 20])

    def test_the_last_month_of_a_piece_is_its_to_even_if_the_next_piece_starts_somewhere_else(self):
        speeds = self.vector("(speed-values (prepayment-speed 'cpr '((5 5 3) (10 20 3))) 8)")
        np.testing.assert_allclose(speeds, [5, 5, 5, 10 + 10 / 3, 10 + 20 / 3, 20, 20, 20])       # (a jump after month 3: 5 then, in month 4, a third of the way from 10 to 20)

    def test_a_piece_with_no_months_is_for_the_rest_of_the_time(self):
        speeds = self.vector("(speed-values (prepayment-speed 'smm '((0.2 0.4 2) (0.4 0.4))) 5)")
        np.testing.assert_allclose(speeds, [0.3, 0.4, 0.4, 0.4, 0.4])

    def test_a_speed_that_is_not_one_is_an_error_that_says_what_is_wrong(self):
        for src, message in (("(prepayment-speed 'ppr 5)", "psa, cpr or smm"),
                             ("(prepayment-speed 'cpr -5)", "cannot be below 0"),
                             ("(prepayment-speed 'cpr '())", "a number, or a list of pieces"),
                             ("(prepayment-speed 'cpr '((5)))", "a piece of a speed is (from to months)"),
                             ("(prepayment-speed 'cpr '((5 6 0)))", "a whole number above 0"),
                             ("(prepayment-speed 'cpr '((5 6 1.5)))", "a whole number above 0"),
                             ("(prepayment-speed 'cpr '((5 6)))", "goes on for ever is one speed"),
                             ("(prepayment-speed 'cpr '((5 5) (6 6 3)))", "is for the rest of the time, so it is the last"),
                             ("(prepayment-speed 'cpr '((a b 3)))", "a piece of a speed is (from to months)")):
            with self.subTest(src=src):
                self.assertLispError(src, message)

    def test_a_psa_speed_is_a_multiple_of_the_curve_at_the_age_of_the_loans_and_the_others_are_not(self):
        smms = self.vector("(speed-smms (prepayment-speed 'psa 200) 10 3)")
        expected = [self.run_lisp("(smm-from-cpr (cpr %d 200))" % age) for age in (10, 11, 12)]
        np.testing.assert_allclose(smms, expected)
        np.testing.assert_allclose(self.vector("(speed-smms (prepayment-speed 'cpr 6) 10 2)"), [1 - (1 - 0.06) ** (1 / 12)] * 2)
        np.testing.assert_allclose(self.vector("(speed-smms (prepayment-speed 'smm 0.5) 10 2)"), [0.005, 0.005])
        np.testing.assert_allclose(self.vector("(speed-smms (prepayment-speed 'cpr '((0 12 2))) 99 2)"),
                                   [1 - (1 - 0.06) ** (1 / 12), 1 - (1 - 0.12) ** (1 / 12)])

    def test_a_speed_is_described_in_words(self):
        self.assertShows("(describe-speed (prepayment-speed 'psa 150))", '"PSA 150"')
        self.assertShows("(describe-speed (prepayment-speed 'cpr '((5 5 12) (5 20 24) (20 20))))",
                         '"CPR: 5 for 12 months, then from 5 to 20 over 24 months, then 20 from then on"')
        self.assertShows("(describe-speed (prepayment-speed 'smm '((0.2 0.4 6))))", '"SMM: from 0.2 to 0.4 over 6 months"')

    def test_a_cpr_speed_is_capped_below_all_of_it(self):
        self.assertLessEqual(self.vector("(speed-smms (prepayment-speed 'cpr 200) 0 1)")[0], 1.0)


class TestProjecting(PiecesCase):

    def test_a_pool_of_one_piece_is_a_pool_whose_prepayments_follow_the_psa_curve_from_its_age(self):
        principal, interest, balance, gross = self.flows("(project-pieces '((100000.0 6.0 6.0 348 12)) (prepayment-speed 'psa 100))")
        monthly = 0.005
        payment = 100000 * monthly / (1 - (1 + monthly) ** -348)
        scheduled = payment - 100000 * monthly
        smm = 1 - (1 - 0.06 * 12 / 30) ** (1 / 12)                                  # (12 months of the 30-month ramp)
        self.assertAlmostEqual(principal[0], scheduled + smm * (100000 - scheduled), places=8)
        self.assertEqual(len(principal), 348)

    def test_the_cash_flows_of_the_pieces_are_added_together_month_by_month(self):
        self.run_lisp("""(define speed (prepayment-speed 'cpr '((4 12 12))))
                         (define one (project-pieces '((100000.0 6.0 5.5 360)) speed))
                         (define two (project-pieces '((50000.0 7.5 7.0 180 24)) speed))
                         (define both (project-pieces '((100000.0 6.0 5.5 360) (50000.0 7.5 7.0 180 24)) speed))""")
        for part in range(4):
            first = self.vector("(list-ref one %d)" % part)
            second = self.vector("(list-ref two %d)" % part)
            second = np.concatenate([second, np.zeros(len(first) - len(second))])       # (the shorter piece is paid off: nothing after it)
            total = self.vector("(list-ref both %d)" % part)
            np.testing.assert_allclose(total, first + second, rtol=1e-12, atol=1e-9)

    def test_the_balance_is_what_there_was_less_what_was_paid(self):
        principal, interest, balance, gross = self.flows("(project-pieces '((100000.0 6.0 5.5 360) (50000.0 7.0 6.5 120)) (prepayment-speed 'psa 200))")
        self.assertEqual((len(principal), len(interest), len(balance)), (360, 360, 361))
        np.testing.assert_allclose(balance[1:], balance[:-1] - principal, atol=1e-6)
        self.assertEqual(balance[0], 150000.0)
        self.assertAlmostEqual(balance[-1], 0.0, places=6)
        self.assertAlmostEqual(principal.sum(), 150000.0, places=6)

    def test_a_piece_with_no_balance_is_an_empty_row_and_is_left_out(self):
        np.testing.assert_allclose(self.vector("(car (project-pieces '((100000.0 6.0 6.0 360) (0 0 0 0) (0.0 5.0 5.0 12)) (prepayment-speed 'psa 100)))"),
                                   self.vector("(car (project-pieces '((100000.0 6.0 6.0 360)) (prepayment-speed 'psa 100)))"))

    def test_what_is_wrong_with_a_piece_is_said(self):
        for src, message in (("'()", "there is no collateral"),
                             ("'((0 0 0 0))", "there is no collateral"),
                             ("'((100000.0 -1.0 -1.0 360))", "the wac of a piece of collateral is in percent"),
                             ("'((100000.0 6.0 -0.5 360))", "the pass-through coupon of a piece of collateral is in percent, from 0"),
                             ("'((100000.0 6.0 6.5 360))", "the pass-through coupon of a piece of collateral, 6.5, is above its wac, 6.0"),
                             ("'((100000.0 6.0 5.5 0))", "the wam of a piece of collateral is the months that are left"),
                             ("'((100000.0 6.0 5.5 12.5))", "the wam of a piece of collateral is the months that are left"),
                             ("'((100000.0 6.0 5.5 12 -1))", "the age of a piece of collateral"),
                             ("'((-5.0 6.0 5.5 12))", "the balance of a piece of collateral is from 0"),
                             ("'((100000.0 6.0 360))", "a piece of collateral is (balance wac coupon wam [age])"),
                             ("'((100000.0 6.0 5.5))", "a piece of collateral is (balance wac coupon wam [age])"),
                             ("'((100000.0 6.0 5.5 12 3 4))", "a piece of collateral is (balance wac coupon wam [age])"),
                             ("'((a b c d))", "a piece of collateral is (balance wac coupon wam [age])")):
            with self.subTest(pieces=src):
                self.assertLispError("(project-pieces %s (prepayment-speed 'psa 100))" % src, message)

    def test_a_piece_in_the_old_form_with_the_age_and_no_coupon_is_not_taken_for_one_with_a_coupon(self):
        """(balance wac wam age) has a wam where the coupon is: 240 is no pass-through coupon of a loan at 7."""
        self.assertLispError("(project-pieces '((50000000.0 7.0 240 12)) (prepayment-speed 'psa 100))", "is above its wac")

    def test_the_interest_is_at_the_pass_through_coupon_and_the_principal_is_what_the_wac_pays(self):
        """Loans at 6.0 that are passed through at 5.5 pay the investors 5.5 on the balance, and pay off as loans at 6.0 do."""
        same = self.flows("(project-pieces '((100000.0 6.0 6.0 360)) (prepayment-speed 'psa 150))")
        passed = self.flows("(project-pieces '((100000.0 6.0 5.5 360)) (prepayment-speed 'psa 150))")
        np.testing.assert_allclose(passed[0], same[0])                               # (the same principal, and the same balances)
        np.testing.assert_allclose(passed[2], same[2])
        np.testing.assert_allclose(passed[1], same[1] * 5.5 / 6.0, rtol=1e-12)       # (interest at 5.5 on the balance)
        np.testing.assert_allclose(passed[3], same[1], rtol=1e-12)                   # (what the loans pay is interest at 6.0)
        self.assertAlmostEqual(passed[1][0], 100000.0 * 0.055 / 12)
        self.assertAlmostEqual(passed[3][0], 100000.0 * 0.06 / 12)

    def test_the_wac_and_the_pass_through_coupon_of_a_pool_are_the_interest_over_the_balance_month_by_month(self):
        self.run_lisp("""(define flows (project-pieces '((100000.0 6.0 5.0 360) (100000.0 8.0 7.0 120)) (prepayment-speed 'psa 100)))
                         (define wacs (pool-coupons (cadddr flows) (caddr flows)))
                         (define coupons (pool-coupons (cadr flows) (caddr flows)))""")
        self.assertAlmostEqual(self.vector("wacs")[0], 0.07)
        self.assertAlmostEqual(self.vector("coupons")[0], 0.06)
        self.assertAlmostEqual(self.vector("wacs")[300], 0.06, places=4)             # (only the loans at 6, passed through at 5, are left)
        self.assertAlmostEqual(self.vector("coupons")[300], 0.05, places=4)

    def test_a_pool_that_has_all_prepaid_has_no_coupon_after_that(self):
        """At 100 SMM everything is paid in the first month: the balance is 0 from the second, and its rate is 0, not an error."""
        self.run_lisp("""(define flows (project-pieces '((1000.0 6.0 6.0 12)) (prepayment-speed 'smm 100)))
                         (define rates (pool-coupons (cadr flows) (caddr flows)))""")
        rates = self.vector("rates")
        self.assertAlmostEqual(rates[0], 0.06)
        self.assertEqual(list(rates[1:]), [0.0] * 11)

    def test_the_coupon_of_a_pool_is_the_interest_over_the_balance_month_by_month(self):
        self.run_lisp("""(define flows (project-pieces '((100000.0 5.0 5.0 360) (100000.0 7.0 7.0 120)) (prepayment-speed 'psa 100)))
                         (define rates (pool-coupons (cadr flows) (caddr flows)))""")
        rates = self.vector("rates")
        self.assertAlmostEqual(rates[0], 0.06)                                    # (half at 5% and half at 7%)
        self.assertGreater(rates[60], 0.05)
        self.assertLess(rates[60], 0.06 + 0.001 * 100)
        self.assertTrue(rates[200] < 0.0501 and rates[200] > 0.0499)              # (only the 5% is left once the 7% is paid off)
        self.assertEqual(len(rates), 360)


class TestADealOfPieces(PiecesCase):

    PIECES = "'((100000000.0 6.0 5.5 360) (50000000.0 7.0 6.5 240 12))"

    def make(self, speed="(prepayment-speed 'psa 150)"):
        self.run_lisp('''(define deal (new-deal "Demo" :collateral %s :speed %s :first-payment (date 2026 11 25)))
                         (define pool (get-node deal "POOL"))''' % (self.PIECES, speed))

    def test_the_collateral_pays_what_the_pieces_pay(self):
        self.make()
        flows = self.flows("(project-pieces %s (prepayment-speed 'psa 150))" % self.PIECES)
        np.testing.assert_allclose(self.vector("(node-principal pool)"), flows[0])
        np.testing.assert_allclose(self.vector("(node-interest pool)"), flows[1])
        np.testing.assert_allclose(self.vector("(node-balance pool)"), flows[2])
        self.assertShows("(deal-size deal)", "150000000.0")
        self.assertShows("(vector-length (node-principal pool))", "360")
        self.assertShows("(speed-curve-type (deal-pricing-speed deal))", "psa")

    def test_its_coupon_is_the_rate_of_each_month_and_what_it_owes_is_what_it_pays(self):
        self.make()
        self.assertShows("(vector? (node-coupon pool))", "#t")
        for month in (0, 50, 200, 359):
            self.assertAlmostEqual(self.run_lisp("(node-interest-due deal pool %d)" % month), self.run_lisp("(vector-ref (node-interest pool) %d)" % month), places=6)

    def test_a_pieces_collateral_can_be_divided_in_every_way_that_has_no_fixed_coupon_to_find(self):
        self.make()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-pac! deal "A" "AP" "AC" 100 300)
                         (deal-io-po! deal "B" "BIO" "BPO" :io-coupon 0.02)''')
        self.assertShows("(begin (deal-run! deal) (deal-check deal))", "#t")
        self.assertAlmostEqual(self.run_lisp('(vector-sum (node-principal (get-node deal "AP")))'), self.run_lisp('(vector-ref (node-balance (get-node deal "AP")) 0)'), places=4)

    def test_the_io_strip_of_a_pool_with_a_coupon_that_changes_pays_the_rest_to_the_po(self):
        self.make()
        self.run_lisp('''(deal-io-po! deal "POOL" "IO" "PO" :io-coupon 0.02)
                         (deal-run! deal)''')
        io = self.vector('(node-interest (get-node deal "IO"))')
        po = self.vector('(node-interest (get-node deal "PO"))')
        pool = self.vector("(node-interest pool)")
        np.testing.assert_allclose(io + po, pool, rtol=1e-9, atol=1e-6)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_split_that_needs_a_fixed_coupon_says_it_is_not_one(self):
        self.make()
        self.assertLispError('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.09)', "is not the same every month")
        self.assertLispError('(deal-premium-discount! deal "POOL" "P" "D" :premium-coupon 0.08 :discount-coupon 0.05)', "is not the same every month")
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_pac_is_sized_from_the_pieces_at_the_two_speeds(self):
        self.make()
        self.run_lisp('(deal-pac! deal "POOL" "P" "C" 100 300)')
        slow = self.vector("(car (project-pieces %s (prepayment-speed 'psa 100)))" % self.PIECES)
        fast = self.vector("(car (project-pieces %s (prepayment-speed 'psa 300)))" % self.PIECES)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "P")) 0)'), np.minimum(slow, fast).sum(), places=4)
        self.assertShows("(begin (deal-run! deal) (deal-check deal))", "#t")

    def test_the_pac_stays_on_schedule_at_a_speed_between_the_two(self):
        """The schedule is made from pieces projected at the PSA speeds, so a collateral that prepays at 200 PSA, between them, pays it exactly."""
        self.make("(prepayment-speed 'psa 200)")
        self.run_lisp('(deal-pac! deal "POOL" "P" "C" 100 300)')
        self.run_lisp("(deal-run! deal)")
        schedule = self.vector('(pac-split-schedule (node-split pool))')
        np.testing.assert_allclose(self.vector('(node-balance (get-node deal "P"))')[: len(schedule)], schedule, atol=1e-3)

    def test_a_speed_that_changes_with_time_is_the_pricing_speed(self):
        self.make("(prepayment-speed 'cpr '((4 4 6) (4 20 12)))")
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-run! deal)''')
        self.assertShows("(deal-check deal)", "#t")
        # more is paid in the early months than at a flat 4 CPR, which the pieces' own cash flows at that speed show
        flat = self.vector("(car (project-pieces %s (prepayment-speed 'cpr 4)))" % self.PIECES)
        self.assertGreater(self.vector("(node-principal pool)")[24:36].sum(), flat[24:36].sum())

    def test_a_deal_with_no_collateral_cannot_be_run_at_a_speed(self):
        self.run_lisp('(define bare (new-deal "Bare"))')
        self.assertLispError("(deal-run! bare (prepayment-speed 'psa 100))", "the deal has no collateral")
        self.assertLispError('(deal-pac! bare "POOL" "P" "C" 100 300)', "the deal has no collateral")

    def test_what_the_collateral_needs_is_checked(self):
        self.run_lisp('(define bare (new-deal "Bare"))')
        self.assertLispError("(deal-set-collateral! bare '())", "there is no collateral")

    def test_the_principal_of_a_node_at_the_speed_it_has_now_is_what_the_run_pays_it(self):
        self.make()
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
                         (deal-pac! deal "A" "AP" "AC" 100 300)''')
        before = self.run_lisp('(deal-principal-now deal "AC")')
        self.run_lisp("(deal-run! deal)")
        np.testing.assert_allclose(before.items, self.run_lisp('(node-principal (get-node deal "AC"))').items, atol=1e-6)
        self.assertLispError('(deal-principal-now deal "NOPE")', "NOPE")


class TestTheFirstPaymentDate(PiecesCase):

    def make(self, options=""):
        self.run_lisp("(define deal %s)" % psa_deal("Demo", 1000000.0, 6.0, term=24, options=options))

    def test_the_payments_are_on_the_same_day_of_each_month_from_the_first(self):
        self.make(":first-payment (date 2026 11 25)")
        self.assertShows("(deal-payment-date deal 1)", "2026-11-25")
        self.assertShows("(deal-payment-date deal 3)", "2027-01-25")
        dates = self.run_lisp("(deal-payment-dates deal)")
        self.assertEqual(len(dates.items), 24)
        self.assertEqual(str(dates.items[0]), "2026-11-25")
        self.assertEqual(str(dates.items[23]), "2028-10-25")

    def test_a_day_that_is_not_in_a_month_is_the_end_of_it(self):
        self.make(":first-payment (date 2026 1 31)")
        self.assertShows("(deal-payment-date deal 2)", "2026-02-28")

    def test_the_first_payment_date_is_not_needed_to_run_a_deal_but_is_to_ask_for_one(self):
        self.make()
        self.assertShows("(deal-first-payment deal)", "()")
        self.assertLispError("(deal-payment-dates deal)", "the deal has no first payment date")

    def test_it_is_a_date(self):
        self.assertLispError('(new-deal "x" :first-payment "2026-11-25")', "is a date")


class TestCoupons(PiecesCase):

    def test_a_coupon_is_a_function_of_the_index_or_a_rate_for_each_month(self):
        self.assertShows("(coupon-at (constant-coupon 0.05) 0.03 7)", "0.05")
        self.assertShows("(coupon-at (lambda (index) (+ index 0.01)) 0.03 7)", "0.04")
        self.assertShows("(coupon-at (vector 0.05 0.06 0.07) 0.03 2)", "0.07")

    def test_what_is_left_of_a_coupon_when_a_rate_is_taken_from_it(self):
        self.assertAlmostEqual(self.run_lisp("((coupon-less (constant-coupon 0.05) 0.02) 0.0)"), 0.03)
        self.assertShows("((coupon-less (constant-coupon 0.05) 0.07) 0.0)", "0.0")
        np.testing.assert_allclose(self.vector("(coupon-less (vector 0.05 0.06 0.01) 0.02)"), [0.03, 0.04, 0.0])


class TestWhatTheLoansAreLike(PiecesCase):
    """The slots of a collateral-piece that say what its loans are like, for a prepayment model: '() when they are not known."""

    CHARACTERISTICS = ["loan-size", "credit-score", "ltv", "sato", "burnout", "investor-share", "second-home-share", "cash-out-share", "refinance-share"]

    def test_they_are_not_known_unless_they_are_given(self):
        self.run_lisp("(define piece (collateral-piece-of '(1000.0 6.0 5.5 12)))")
        for slot in self.CHARACTERISTICS:
            self.assertShows("(collateral-piece-%s piece)" % slot, "()")
        self.run_lisp("(define piece (make-collateral-piece :balance 1000.0 :wac 6.0 :coupon 5.5 :wam 12 :loan-size 250000 :credit-score 745 :ltv 68.5 :sato 0.2 "
                      ":burnout 4 :investor-share 0.1 :second-home-share 0.05 :cash-out-share 0.2 :refinance-share 0.3))")
        self.assertShows("(map (lambda (slot) (slot piece)) (map cadr collateral-characteristics))", "(250000 745 68.5 0.2 4 0.1 0.05 0.2 0.3)")

    def test_what_makes_no_sense_is_said(self):
        for given, message in ((":loan-size 0", "the loan size of a piece of collateral is the balance of a loan"),
                               (":credit-score 200", "the credit score of a piece of collateral is from 300 to 850"),
                               (":ltv -5", "the ltv of a piece of collateral is the loan-to-value in percent"),
                               (":burnout -1", "the burnout of a piece of collateral is a number of months"),
                               (":investor-share 1.2", "the investor share of a piece of collateral is a share of the balance, from 0 to 1"),
                               (":cash-out-share \"most\"", "the cash-out share of a piece of collateral is a share of the balance"),
                               (":investor-share 0.6 :second-home-share 0.6", "the investor share and the second home share of a piece of collateral are 1.2 together"),
                               (":cash-out-share 0.7 :refinance-share 0.4", "the cash-out share and the refinance share")):
            with self.subTest(given=given):
                self.assertLispError("(new-deal \"D\" :collateral (list (make-collateral-piece :balance 1000.0 :wac 6.0 :coupon 5.5 :wam 12 %s)))" % given, message)

    def test_the_table_of_collateral_has_a_column_for_each_and_nan_where_it_is_not_known(self):
        self.run_lisp("(define table (collateral-table (list (make-collateral-piece :balance 1000.0 :wac 6.0 :coupon 5.5 :wam 12 :credit-score 760 :investor-share 0.1) "
                      "'(500.0 6.0 5.5 12))))")
        self.assertShows("(map car table)", '("balance" "wac" "coupon" "wam" "age" "loan size" "credit score" "ltv" "sato" "burnout" "investor share" '
                                            '"second home share" "cash-out share" "refinance share")')
        self.assertShows('(table-column table "credit score")', "#(760.0 nan)")
        self.assertShows("(map collateral-piece-credit-score (collateral-table-pieces table))", "(760.0 ())")
        self.assertShows("(map collateral-piece-investor-share (collateral-table-pieces table))", "(0.1 ())")
        self.assertShows("(map collateral-piece-ltv (collateral-table-pieces table))", "(() ())")

    def test_a_table_of_collateral_needs_only_the_first_four_columns(self):
        self.run_lisp('''(define deal (new-deal "D" :collateral (make-table "balance" (vector 1000.0) "wac" (vector 6.0) "coupon" (vector 5.5) "wam" (vector 12)
                                                                    "credit score" (vector 700.0))))''')
        self.assertShows("(collateral-piece-credit-score (car (deal-pieces deal)))", "700.0")
        self.assertShows("(collateral-piece-age (car (deal-pieces deal)))", "0")
        self.assertShows("(collateral-piece-ltv (car (deal-pieces deal)))", "()")

    def test_a_prepayment_model_is_given_them(self):
        self.run_lisp('''(load "deal_pricing.lsp")
                         (define seen '())
                         (define deal (new-deal "D" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                                                :collateral (list (make-collateral-piece :balance 1000000.0 :wac 6.5 :coupon 6.0 :wam 12 :credit-score 720 :ltv 85.0))))
                         (deal-set-treasury-curve! deal '((1 4.0) (2 4.1)))
                         (deal-set-prepayment-model! deal (lambda (piece path)
                                                            (set! seen (list (collateral-piece-credit-score piece) (collateral-piece-ltv piece)))
                                                            (make-vector (collateral-piece-wam piece) 6.0)))
                         (deal-run-paths! deal :paths 2)''')
        self.assertShows("seen", "(720.0 85.0)")                                  # (the deal keeps its pieces in a table, of decimals)
