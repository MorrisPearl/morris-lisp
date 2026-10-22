"""What a price says about a tranche (lib/deal_pricing.lsp): accrued interest, the yield of a price and the price of a yield, the spread to a Treasury curve at the
average life, the duration, the dv01 and the money, and a price given as + or ?. The numbers are checked against the same sums done here, in numpy, from the cash
flows that the tranche is paid."""

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

CURVE = [(1, 4.0), (2, 4.1), (3, 4.2), (5, 4.3), (10, 4.5)]
DEAL = '''
  (define deal (new-deal "Demo" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                         :collateral '((10000000.0 6.5 6.0 60)) :speed (prepayment-speed 'psa 150)))
  (deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
  (deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))'''


def present_value(flows, months, yield_percent):
    """What the cash flows are worth at a bond equivalent yield (percent), when each is the months from the closing date."""
    return float(np.sum(flows * (1 + yield_percent / 200.0) ** (-months / 6.0)))


def yield_of(flows, months, money):
    """The yield, by halving the range."""
    low, high = -100.0, 1000.0
    for _ in range(200):
        middle = (low + high) / 2
        if present_value(flows, months, middle) > money:
            low = middle
        else:
            high = middle
    return (low + high) / 2


class PricingCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_pricing.lsp")')
        self.run_lisp(DEAL)

    def slot(self, name, slot):
        value = self.run_lisp('(node-%s (get-node deal "%s"))' % (slot, name))
        return value

    def flows(self, name):
        """What the tranche is paid each month at the pricing speed, from a run of the deal: its principal and interest."""
        self.run_lisp("(deal-run! deal)")
        principal = np.array(self.run_lisp('(node-principal (get-node deal "%s"))' % name).items, dtype=float)
        interest = np.array(self.run_lisp('(node-interest (get-node deal "%s"))' % name).items, dtype=float)
        return principal + interest

    def months(self, count):
        """The months from the closing date, 2026-11-20, to each payment, from 2026-12-25: 35 days, by the 30/360 count, and a month each after."""
        return 35 / 30.0 + np.arange(count)


class TestDays(PricingCase):

    def test_the_30_360_count_has_months_of_30_days_and_the_31st_is_the_30th(self):
        for first, second, days in (((2026, 11, 1), (2026, 11, 20), 19), ((2026, 1, 30), (2026, 1, 31), 0), ((2026, 1, 31), (2026, 3, 31), 60),
                                    ((2026, 1, 31), (2026, 3, 1), 31), ((2026, 12, 25), (2027, 1, 25), 30), ((2026, 11, 20), (2026, 12, 25), 35)):
            with self.subTest(first=first, second=second):
                self.assertShows("(days-360 (date %d %d %d) (date %d %d %d))" % (first + second), str(days))


class TestAccruedInterest(PricingCase):

    def accrued(self, name="A"):
        return self.run_lisp('(accrued-interest deal (get-node deal "%s"))' % name)

    def test_it_is_the_balance_times_the_coupon_for_the_days_since_the_accrual_period_began_over_360(self):
        # the first payment is 2026-12-25 and its delay 24 days: its period ends 2026-12-01, and began 2026-11-01, so 19 days have gone at the closing date
        self.assertAlmostEqual(self.accrued("A"), 6000000 * 0.06 * 19 / 360)
        self.assertAlmostEqual(self.accrued("B"), 4000000 * 0.06 * 19 / 360)
        self.assertAlmostEqual(self.accrued("POOL"), 10000000 * 0.06 * 19 / 360)

    def test_the_delay_moves_the_accrual_period(self):
        self.run_lisp('(node-delay-set! (get-node deal "A") 14)')                    # (the period began 2026-11-11: 9 days)
        self.assertAlmostEqual(self.accrued("A"), 6000000 * 0.06 * 9 / 360)
        self.run_lisp('(node-delay-set! (get-node deal "A") 0)')                     # (it began 2026-11-25, after the closing date: nothing has accrued)
        self.assertEqual(self.accrued("A"), 0.0)

    def test_a_closing_date_after_the_end_of_the_first_period_is_an_error(self):
        self.run_lisp("(deal-set-closing-date! deal (date 2026 12 10))")
        self.assertLispError('(accrued-interest deal (get-node deal "A"))', "after the end of the first accrual period of A")

    def test_it_needs_the_dates(self):
        self.run_lisp('(define bare (new-deal "Bare" :collateral \'((1000000.0 6.5 6.0 24)))) (deal-sequential! bare "POOL" \'(("A" 1000000.0)))')
        self.assertLispError("(deal-set-price! bare \"A\" 100.0)", "has no closing date")
        self.run_lisp("(deal-set-closing-date! bare (date 2026 11 20))")
        self.assertLispError("(deal-set-price! bare \"A\" 100.0)", "has no first payment date")


class TestYieldAndMoney(PricingCase):

    def test_a_price_has_the_yield_that_makes_the_cash_flows_worth_the_money(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        flows = self.flows("A")
        money = 6000000 * 1.005 + 6000000 * 0.06 * 19 / 360
        self.assertAlmostEqual(self.slot("A", "money"), money, places=4)
        self.assertAlmostEqual(self.slot("A", "yield"), yield_of(flows, self.months(len(flows)), money), places=6)
        self.assertAlmostEqual(present_value(flows, self.months(len(flows)), self.slot("A", "yield")), money, places=3)
        self.assertEqual(self.slot("A", "price"), 100.5)
        self.assertShows('(node-priced-by (get-node deal "A"))', "price")

    def test_a_yield_has_the_price_that_makes_the_cash_flows_worth_it(self):
        self.run_lisp('(deal-set-yield! deal "A" 5.25)')
        flows = self.flows("A")
        money = present_value(flows, self.months(len(flows)), 5.25)
        self.assertAlmostEqual(self.slot("A", "money"), money, places=4)
        self.assertAlmostEqual(self.slot("A", "price"), 100 * (money - 6000000 * 0.06 * 19 / 360) / 6000000, places=8)
        self.assertEqual(self.slot("A", "yield"), 5.25)
        self.assertShows('(node-priced-by (get-node deal "A"))', "yield")

    def test_the_price_of_a_yield_gives_the_yield_back(self):
        self.run_lisp('(deal-set-yield! deal "B" 6.1)')
        price = self.slot("B", "price")
        self.run_lisp('(deal-set-price! deal "B" %r)' % price)
        self.assertAlmostEqual(self.slot("B", "yield"), 6.1, places=7)

    def test_a_lower_price_is_a_higher_yield(self):
        yields = []
        for price in (98.0, 100.0, 102.0):
            self.run_lisp('(deal-set-price! deal "A" %r)' % price)
            yields.append(self.slot("A", "yield"))
        self.assertGreater(yields[0], yields[1])
        self.assertGreater(yields[1], yields[2])

    def test_money_is_the_balance_times_the_price_over_100_and_the_accrued_interest(self):
        self.run_lisp('(deal-set-price! deal "B" 97.25)')
        self.assertAlmostEqual(self.slot("B", "money"), 4000000 * 0.9725 + 4000000 * 0.06 * 19 / 360, places=6)

    def test_a_price_that_is_not_a_number_is_an_error_and_changes_nothing(self):
        self.run_lisp('(deal-set-price! deal "A" 100.0)')
        self.assertLispError('(deal-set-price! deal "A" "high")', "a price is a number")
        self.assertEqual(self.slot("A", "price"), 100.0)

    def test_a_price_with_no_yield_is_an_error_that_says_so(self):
        self.assertLispError('(deal-set-price! deal "A" -50.0)', "has to be more than 0")
        self.assertLispError('(deal-set-price! deal "A" 1e12)', "no yield, from -100% to 1000%")


class TestDurationAndDv01(PricingCase):

    def test_the_dv01_is_how_much_the_money_falls_when_the_yield_is_a_basis_point_higher(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        flows = self.flows("A")
        months = self.months(len(flows))
        y = self.slot("A", "yield")
        self.assertAlmostEqual(self.slot("A", "dv01"), present_value(flows, months, y) - present_value(flows, months, y + 0.01), places=4)
        self.assertGreater(self.slot("A", "dv01"), 0)

    def test_the_duration_is_the_proportion_that_the_money_falls_by_for_a_rise_of_one_in_the_yield(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        flows = self.flows("A")
        months = self.months(len(flows))
        y = self.slot("A", "yield")
        h = 0.001                                                              # (a tenth of a basis point, in percent)
        slope = (present_value(flows, months, y + h) - present_value(flows, months, y - h)) / (2 * h / 100.0)
        self.assertAlmostEqual(self.slot("A", "duration"), -slope / present_value(flows, months, y), places=5)

    def test_the_dv01_does_not_depend_on_the_price_that_was_given_only_on_the_yield(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        by_price = self.slot("A", "dv01")
        self.run_lisp('(deal-set-yield! deal "A" %r)' % self.slot("A", "yield"))
        self.assertAlmostEqual(self.slot("A", "dv01"), by_price, places=3)

    def test_a_longer_bond_has_a_longer_duration(self):
        self.run_lisp('(deal-set-yield! deal "A" 5.0) (deal-set-yield! deal "B" 5.0)')
        self.assertGreater(self.slot("B", "duration"), self.slot("A", "duration"))
        self.assertGreater(self.slot("B", "dv01") / self.slot("B", "money"), self.slot("A", "dv01") / self.slot("A", "money"))


class TestSpread(PricingCase):

    def test_the_treasury_curve_is_a_straight_line_between_its_points_and_flat_beyond_them(self):
        self.run_lisp("(deal-set-treasury-curve! deal '((2 4.0) (3 5.0)))")
        self.assertAlmostEqual(self.run_lisp("(treasury-yield deal 2.25)"), 4.25)          # (a quarter of the way from the two year note to the three year)
        self.assertAlmostEqual(self.run_lisp("(treasury-yield deal 2.75)"), 4.75)
        self.assertAlmostEqual(self.run_lisp("(treasury-yield deal 1.0)"), 4.0)
        self.assertAlmostEqual(self.run_lisp("(treasury-yield deal 7.0)"), 5.0)
        self.assertAlmostEqual(self.run_lisp("(treasury-yield deal 3.0)"), 5.0)

    def test_it_interpolates_a_curve_of_many_points(self):
        for years in (0.5, 1.5, 2.25, 4.0, 7.5, 12.0):
            with self.subTest(years=years):
                self.assertAlmostEqual(self.run_lisp("(treasury-yield deal %r)" % years), float(np.interp(years, [p[0] for p in CURVE], [p[1] for p in CURVE])))

    def test_the_spread_of_a_price_is_its_yield_less_the_curve_at_its_average_life(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        life = self.slot("A", "average-life")
        curve_yield = float(np.interp(life, [p[0] for p in CURVE], [p[1] for p in CURVE]))
        self.assertAlmostEqual(self.slot("A", "spread"), (self.slot("A", "yield") - curve_yield) * 100, places=6)

    def test_a_spread_has_the_yield_that_is_that_over_the_curve_and_the_price_of_it(self):
        self.run_lisp('(deal-set-spread! deal "A" 150)')
        life = self.slot("A", "average-life")
        curve_yield = float(np.interp(life, [p[0] for p in CURVE], [p[1] for p in CURVE]))
        self.assertAlmostEqual(self.slot("A", "yield"), curve_yield + 1.5, places=9)
        self.assertEqual(self.slot("A", "spread"), 150)
        flows = self.flows("A")
        money = present_value(flows, self.months(len(flows)), curve_yield + 1.5)
        self.assertAlmostEqual(self.slot("A", "money"), money, places=4)
        self.assertShows('(node-priced-by (get-node deal "A"))', "spread")

    def test_the_average_life_is_that_of_the_principal_in_years(self):
        self.run_lisp('(deal-set-price! deal "B" 100.0)')
        self.flows("B")
        self.assertAlmostEqual(self.slot("B", "average-life"), self.run_lisp('(deal-average-life deal "B")'))

    def test_a_spread_needs_a_treasury_curve(self):
        self.run_lisp("(deal-treasury-curve-set! deal '())")
        self.assertLispError('(deal-set-spread! deal "A" 100)', "has no Treasury curve")
        self.run_lisp('(deal-set-price! deal "A" 100.0)')                          # (a price needs none: it has no spread)
        self.assertShows('(node-spread (get-node deal "A"))', "()")
        self.assertAlmostEqual(self.slot("A", "money"), 6000000 + 6000000 * 0.06 * 19 / 360, places=4)

    def test_a_new_curve_changes_the_spreads_of_the_prices_that_were_given(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        before = self.slot("A", "spread")
        self.run_lisp("(deal-set-treasury-curve! deal '((1 3.0) (2 3.1) (3 3.2) (5 3.3) (10 3.5)))")        # (a point lower: the spread is 100 basis points more)
        self.assertAlmostEqual(self.slot("A", "spread"), before + 100, places=6)

    def test_the_curve_is_a_table_too(self):
        self.run_lisp('(deal-set-treasury-curve! deal (make-table "years" (vector 2.0 3.0) "yield" (vector 4.0 5.0)))')
        self.assertShows("(deal-treasury-curve deal)", "((2.0 4.0) (3.0 5.0))")

    def test_what_is_wrong_with_a_curve_is_said(self):
        for source, message in (("'()", "is a list of (years yield)"),
                                ("'((2 4.0) (2 4.1))", "two yields for 2 years"),
                                ("'((0 4.0))", "years above 0"),
                                ("'((2))", "is a list of (years yield)"),
                                ('(make-table "years" (vector 2.0))', "no column yield")):
            with self.subTest(curve=source):
                self.assertLispError("(deal-set-treasury-curve! deal %s)" % source, message)


class TestPlusAndQuestionMark(PricingCase):

    def money(self, name):
        return self.slot(name, "money")

    def test_plus_is_the_price_that_makes_the_money_what_the_children_have_between_them(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5) (deal-set-yield! deal "B" 6.0)')
        self.run_lisp('(deal-set-price! deal "POOL" "+")')
        self.assertAlmostEqual(self.money("POOL"), self.money("A") + self.money("B"), places=4)
        self.assertShows('(node-priced-by (get-node deal "POOL"))', "price")
        self.assertAlmostEqual(self.slot("POOL", "price"),
                               100 * (self.money("A") + self.money("B") - 10000000 * 0.06 * 19 / 360) / 10000000, places=8)

    def test_question_mark_is_the_price_that_makes_it_and_its_siblings_the_money_of_the_parent(self):
        self.run_lisp('(deal-set-price! deal "POOL" 101.0) (deal-set-price! deal "A" 100.5)')
        self.run_lisp('(deal-set-price! deal "B" "?")')
        self.assertAlmostEqual(self.money("A") + self.money("B"), self.money("POOL"), places=4)
        self.assertAlmostEqual(self.money("B"), 10000000 * 1.01 + 10000000 * 0.06 * 19 / 360 - self.money("A"), places=4)

    def test_it_works_a_level_down_and_with_several_siblings(self):
        self.run_lisp('''(deal-sequential! deal "A" '(("A1" 2000000.0) ("A2" 2000000.0) ("A3" 2000000.0)))
                         (deal-set-price! deal "A" 100.5) (deal-set-price! deal "A1" 99.0) (deal-set-yield! deal "A3" 5.0)''')
        self.run_lisp('(deal-set-price! deal "A2" "?")')
        self.assertAlmostEqual(self.money("A1") + self.money("A2") + self.money("A3"), self.money("A"), places=4)
        self.run_lisp('(deal-set-price! deal "A" "+")')                              # (and back up again: A is what its children have)
        self.assertAlmostEqual(self.money("A"), self.money("A1") + self.money("A2") + self.money("A3"), places=4)

    def test_the_symbols_do_as_the_strings_do(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5) (deal-set-price! deal "B" 99.5)')
        self.run_lisp("(deal-set-price! deal \"POOL\" '+)")
        first = self.money("POOL")
        self.run_lisp('(deal-set-price! deal "POOL" 100.0) (deal-set-price! deal "POOL" "+")')
        self.assertAlmostEqual(self.money("POOL"), first, places=6)

    def test_plus_needs_children_that_are_priced_and_a_tranche_that_is_divided(self):
        self.assertLispError('(deal-set-price! deal "POOL" "+")', "A has no price yet")
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertLispError('(deal-set-price! deal "POOL" "+")', "B has no price yet")
        self.assertLispError('(deal-set-price! deal "A" "+")', "is not divided")

    def test_question_mark_needs_a_parent_that_is_priced_and_siblings_that_are(self):
        self.assertLispError('(deal-set-price! deal "POOL" "?")', "is the collateral")
        self.assertLispError('(deal-set-price! deal "B" "?")', "POOL has no price yet")
        self.run_lisp('(deal-set-price! deal "POOL" 100.0)')
        self.assertLispError('(deal-set-price! deal "B" "?")', "A has no price yet")


class TestWhatKeepsAndWhatChanges(PricingCase):
    """What was typed stays as it was typed, and what is worked out from it is worked out again when the deal changes."""

    def test_a_price_stays_and_its_yield_follows_the_pricing_speed(self):
        self.run_lisp('(deal-set-price! deal "A" 103.0)')
        yield_before = self.slot("A", "yield")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 400))")
        self.assertEqual(self.slot("A", "price"), 103.0)
        self.assertLess(self.slot("A", "yield"), yield_before)                      # (a bond bought at a premium is repaid sooner: it yields less)
        flows = self.flows("A")
        self.assertAlmostEqual(present_value(flows, self.months(len(flows)), self.slot("A", "yield")), self.slot("A", "money"), places=3)

    def test_a_yield_stays_and_its_price_follows_the_pricing_speed(self):
        self.run_lisp('(deal-set-yield! deal "A" 5.0)')
        price_before = self.slot("A", "price")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 400))")
        self.assertEqual(self.slot("A", "yield"), 5.0)
        self.assertNotAlmostEqual(self.slot("A", "price"), price_before, places=3)

    def test_a_spread_stays_and_its_yield_follows_the_average_life(self):
        self.run_lisp('(deal-set-spread! deal "B" 120)')
        yield_before = self.slot("B", "yield")
        life_before = self.slot("B", "average-life")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 400))")
        self.assertEqual(self.slot("B", "spread"), 120)
        self.assertNotAlmostEqual(self.slot("B", "average-life"), life_before, places=3)
        self.assertNotAlmostEqual(self.slot("B", "yield"), yield_before, places=3)
        self.assertAlmostEqual(self.slot("B", "yield"), float(np.interp(self.slot("B", "average-life"), [p[0] for p in CURVE], [p[1] for p in CURVE])) + 1.2, places=9)

    def test_the_prices_stay_when_a_tranche_is_divided(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        before = (self.slot("A", "yield"), self.slot("A", "money"))
        self.run_lisp('(deal-sequential! deal "B" \'(("B1" 1000000.0) ("B2" 3000000.0)))')
        self.run_lisp("(deal-update-analytics! deal)")
        self.assertEqual((self.slot("A", "yield"), self.slot("A", "money")), before)
        self.assertShows('(node-money (get-node deal "B1"))', "()")                  # (a new tranche has no price)
        self.assertTrue(self.slot("B1", "average-life") > 0)

    def test_the_delay_changes_the_accrued_interest_and_so_the_money_and_not_the_price(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.run_lisp('(deal-set-delay! deal "A" 14)')
        self.assertEqual(self.slot("A", "price"), 100.5)
        self.assertAlmostEqual(self.slot("A", "money"), 6000000 * 1.005 + 6000000 * 0.06 * 9 / 360, places=4)
        self.assertEqual(self.slot("A", "delay"), 14)

    def test_a_delay_that_the_deal_cannot_be_priced_with_is_not_taken(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertLispError('(deal-set-delay! deal "A" -1)', "a whole number of days")
        self.run_lisp("(deal-set-closing-date! deal (date 2026 12 5))")              # (the period of a delay of 24 ends 2026-12-01: the closing date is after it)
        self.assertLispError('(deal-set-delay! deal "B" 20)', "after the end of the first accrual period")
        self.assertEqual(self.slot("B", "delay"), 24)

    def test_a_price_can_be_taken_away(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.run_lisp('(deal-clear-price! deal "A")')
        for slot in ("price", "yield", "spread", "duration", "dv01", "money", "priced-by"):
            self.assertShows('(node-%s (get-node deal "A"))' % slot, "()")
        self.assertTrue(self.slot("A", "average-life") > 0)

    def test_what_cannot_be_worked_out_is_cleared_and_said(self):
        self.run_lisp('(deal-set-spread! deal "A" 100)')
        self.run_lisp("(deal-treasury-curve-set! deal '())")
        problems = self.run_lisp("(deal-update-analytics! deal)")
        self.assertIn("A: the deal has no Treasury curve", str(problems.car))
        self.assertShows('(node-yield (get-node deal "A"))', "()")
        self.assertShows('(node-priced-by (get-node deal "A"))', "spread")            # (it was priced by a spread, still)


class TestWhatCanBePriced(PricingCase):

    def test_an_interest_only_bond_has_a_yield_and_no_spread(self):
        self.run_lisp('(deal-io-po! deal "B" "IO" "PO")')
        self.run_lisp('(deal-set-price! deal "IO" 12.0)')
        self.assertTrue(self.slot("IO", "yield") > 0)
        self.assertTrue(self.slot("IO", "duration") != 0)
        self.assertShows('(node-spread (get-node deal "IO"))', "()")
        self.assertShows('(node-average-life (get-node deal "IO"))', "()")
        self.assertLispError('(deal-set-spread! deal "IO" 100)', "is paid no principal")

    def test_a_z_bond_is_priced_by_what_it_is_paid(self):
        self.run_lisp('''(deal-sequential! deal "B" '(("B1" 2000000.0) ("Z" 2000000.0 z)))''')
        self.run_lisp('(deal-set-price! deal "Z" 80.0)')
        self.run_lisp("(deal-run! deal)")
        flows = np.array(self.run_lisp('(node-principal (get-node deal "Z"))').items, dtype=float)
        self.assertAlmostEqual(self.slot("Z", "money"), 2000000 * 0.8 + 2000000 * 0.06 * 19 / 360, places=4)
        self.assertAlmostEqual(present_value(flows, self.months(len(flows)), self.slot("Z", "yield")), self.slot("Z", "money"), places=2)

    def test_a_tranche_that_is_not_in_the_tree_cannot_be_priced(self):
        self.run_lisp('(deal-add-tranche! deal "LOOSE" 1.0)')
        self.assertLispError('(deal-set-price! deal "LOOSE" 100.0)', "is not in a tree of the deal")

    def test_a_deal_with_no_collateral_cannot(self):
        self.run_lisp('(define empty (new-deal "Empty" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)))')
        self.assertLispError('(deal-set-price! empty "POOL" 100.0)', "has no collateral")
        self.assertShows("(deal-update-analytics! empty)", "()")

    def test_a_floating_bond_is_priced_at_the_index_the_deal_was_run_with(self):
        self.run_lisp('(deal-floater-inverse! deal "B" "F" "I" :cap 0.09 :margin 0.005)')
        self.assertLispError('(deal-set-price! deal "F" 100.0)', "F floats, and the deal has no index")
        self.assertIn("F floats", str(self.run_lisp("(deal-update-analytics! deal)").car))
        self.run_lisp("(deal-run! deal :index 0.04)")
        self.run_lisp('(deal-set-price! deal "F" 100.0)')
        at_four = self.slot("F", "yield")
        self.run_lisp("(deal-run! deal :index 0.06)")                                 # (a higher index: the floater pays more, and has a higher yield at the same price)
        self.assertGreater(self.slot("F", "yield"), at_four + 1.0)

    def test_the_pricing_run_is_kept_until_the_deal_changes(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.run_lisp("(define first-run (deal-priced-run deal))")
        self.run_lisp('(deal-set-price! deal "B" 99.0)')
        self.assertShows("(eq? first-run (deal-priced-run deal))", "#t")
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 300))")             # (a deal that has a price works it out again when it changes)
        self.assertShows("(eq? first-run (deal-priced-run deal))", "#f")
        self.assertShows("(null? (deal-priced-run deal))", "#f")


class TestThePricingTable(PricingCase):

    def test_it_has_a_row_for_each_tranche_and_nan_for_what_is_not_there(self):
        self.run_lisp('(deal-update-analytics! deal) (deal-set-price! deal "A" 100.5)')
        table = self.run_lisp("(deal-pricing-table deal)")
        columns = {str(pair.car): list(pair.cdr.items) for pair in lisp_core.pairs_to_list(table)}
        self.assertEqual(list(columns), ["tranche", "balance", "price", "yield", "spread", "duration", "average life", "dv01", "money", "delay"])
        self.assertEqual(columns["tranche"], ["POOL", "A", "B"])
        self.assertEqual(columns["price"][1], 100.5)
        self.assertTrue(np.isnan(columns["price"][0]) and np.isnan(columns["price"][2]))
        self.assertTrue(all(value > 0 for value in columns["average life"]))
        self.assertEqual(columns["delay"], [24, 24, 24])


if __name__ == "__main__":
    unittest.main()
