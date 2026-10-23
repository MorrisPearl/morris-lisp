"""Hedging a tranche (lib/deal_hedge.lsp): the Treasuries of a deal's curve, each a par bond with its effective duration and convexity, valued off the zero curve; and the
hedge of a tranche, the pair of the Treasuries and the collateral that makes the dollar duration and dollar convexity of the tranche and the hedge together 0 with the least
in all. The Treasuries are checked against the same sums done here, on a flat curve, and the hedge against numpy's solution of the two equations of every pair."""

import math

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

CURVE = "'((0.25 4.0) (1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5) (30 4.8))"


class HedgeCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_hedge.lsp")')

    def columns(self, source):
        table = self.run_lisp(source)
        return {name: v.items.tolist() for name, v in lisp_tables.table_columns(table, "test")}

    def names(self, instruments):
        """The names of the hedge-instruments that the Lisp gives."""
        return [str(name) for name in lisp_core.pairs_to_list(self.run_lisp("(map hedge-instrument-name %s)" % instruments))]

    def make_deal(self, price_pool=True):
        """A deal of 24 months whose loans prepay faster as rates fall (so the tranches have a convexity below 0), divided into A and B, with the paths of rates run, A and B
        priced, and the collateral too, unless price_pool is False."""
        self.run_lisp('''(define deal (new-deal "Hedge" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25) :treasury-curve %s
                                               :collateral '((10000000.0 6.5 6.0 24)) :speed (prepayment-speed 'psa 150)))
                         (deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
                         (define (refinancing piece path)
                           (+ 5.0 (* 3000.0 (vector-clip (- 0.045 (vector-take (rate-path-short-rates path) (collateral-piece-wam piece))) 0.0 1.0))))
                         (deal-set-prepayment-model! deal refinancing)
                         (deal-set-pricing-speed! deal (prepayment-speed 'model 100))
                         (deal-run-paths! deal :paths 4)
                         (deal-set-price! deal "A" 101.0)
                         (deal-set-price! deal "B" 100.0)''' % CURVE)
        if price_pool:
            self.run_lisp('(deal-set-price! deal "POOL" 101.0)')


class TestTheTreasuries(HedgeCase):

    def test_a_treasury_pays_a_coupon_every_six_months_back_from_its_maturity_and_a_bill_pays_once(self):
        self.assertShows("(treasury-cash-flows 1.5 4.0)", "((0.5 2.0) (1.0 2.0) (1.5 102.0))")
        self.assertShows("(treasury-cash-flows 1.25 4.0)", "((0.25 2.0) (0.75 2.0) (1.25 102.0))")
        self.assertShows("(treasury-cash-flows 0.25 4.0)", "((0.25 101.0))")

    def test_on_a_flat_curve_each_is_worth_100_and_its_measures_are_those_of_its_cash_flows(self):
        self.run_lisp('''(define flat (new-deal "Flat" :treasury-curve '((0.5 4.0) (2 4.0) (10 4.0) (30 4.0))))''')
        measures = self.columns("(treasury-measures flat)")
        self.assertEqual(measures["instrument"], ["0.5y Treasury", "2y Treasury", "10y Treasury", "30y Treasury"])
        zero = 2 * math.log(1.02)                                # (a par yield of 4% paid twice a year, continuously compounded)
        for years, price, duration, convexity in zip(measures["years"], measures["price"], measures["effective duration"], measures["effective convexity"]):
            times = np.arange(0.5, years + 1e-9, 0.5)
            flows = np.where(np.isclose(times, years), 102.0, 2.0)
            value = lambda shift: (flows * np.exp(-(zero + shift) * times)).sum()     # (the zero rates all moved by the shift)
            self.assertAlmostEqual(price, 100.0, places=6)
            self.assertAlmostEqual(duration, (value(-0.0025) - value(0.0025)) / (2 * 0.0025 * value(0)), places=6)
            self.assertAlmostEqual(convexity, (value(-0.0025) + value(0.0025) - 2 * value(0)) / (value(0) * 0.0025 ** 2), places=3)
            moments = flows * np.exp(-zero * times)                       # (and they are close to the moments of the times of the cash flows, by their values)
            self.assertAlmostEqual(duration, (times * moments).sum() / moments.sum(), delta=1e-3 * years)

    def test_the_shift_is_that_of_the_paths_and_the_deal_needs_a_curve(self):
        self.make_deal()
        self.run_lisp("(deal-run-paths! deal :paths 2 :shift 0.01)")
        self.assertShows("(deal-shift deal)", "0.01")
        self.run_lisp('(define bare (new-deal "Bare"))')
        self.assertLispError("(treasury-measures bare)", "has no Treasury curve")


class TestTheHedge(HedgeCase):

    def test_the_pairs_of_a_list_are_each_pair_once(self):
        self.assertShows("(pairs-of '(x y z))", "((x y) (x z) (y z))")
        self.assertShows("(pairs-of '(x))", "()")

    def test_the_hedge_makes_the_dollar_duration_and_the_dollar_convexity_nothing(self):
        self.make_deal()
        hedge = self.columns('(deal-hedge deal "B")')
        self.assertEqual(hedge["position"][0], "B")
        self.assertEqual(hedge["position"][3], "net")
        self.assertAlmostEqual(hedge["dollar duration"][3], 0.0, delta=1e-6 * abs(hedge["dollar duration"][0]))
        self.assertAlmostEqual(hedge["dollar convexity"][3], 0.0, delta=1e-6 * abs(hedge["dollar convexity"][0]))
        self.assertLess(self.run_lisp('(node-effective-convexity (get-node deal "B"))'), 0)
        self.assertAlmostEqual(hedge["market value"][0], self.run_lisp('(node-money (get-node deal "B"))'))
        for row in (1, 2):
            self.assertAlmostEqual(hedge["dollar duration"][row], hedge["market value"][row] * hedge["effective duration"][row])

    def test_it_is_the_pair_that_does_it_with_the_least_in_all(self):
        self.make_deal()
        pairs = self.columns('(deal-hedge-pairs deal "B")')
        self.assertEqual(pairs["gross"], sorted(pairs["gross"]))
        money, duration, convexity = (self.run_lisp('(node-%s (get-node deal "B"))' % slot) for slot in ("money", "effective-duration", "effective-convexity"))
        names = self.names('(hedge-instruments deal "B")')
        durations, convexities = (lisp_core.pairs_to_list(self.run_lisp('(map hedge-instrument-%s (hedge-instruments deal "B"))' % slot)) for slot in ("duration", "convexity"))
        instruments = dict(zip(names, zip(durations, convexities)))
        for first, second, h1, h2 in zip(pairs["first"], pairs["second"], pairs["first value"], pairs["second value"]):
            solved = np.linalg.solve(np.array([[instruments[first][0], instruments[second][0]], [instruments[first][1], instruments[second][1]]]),
                                     -money * np.array([duration, convexity]))
            np.testing.assert_allclose([h1, h2], solved, rtol=1e-6)
        hedge = self.columns('(deal-hedge deal "B")')
        self.assertEqual(hedge["position"][1:3], [pairs["first"][0], pairs["second"][0]])
        self.assertEqual(len(pairs["first"]), 7 * 8 // 2)                       # (every pair of the seven Treasuries and the collateral)

    def test_the_collateral_is_an_instrument_when_it_is_priced_and_is_not_the_tranche(self):
        self.make_deal(price_pool=False)
        names = self.names('(hedge-instruments deal "B")')
        self.assertNotIn("POOL", names)
        self.assertEqual(len(names), 7)
        self.run_lisp('(deal-set-price! deal "POOL" 101.0)')
        names = self.names('(hedge-instruments deal "B")')
        self.assertEqual(names[-1], "POOL")
        names = self.names('(hedge-instruments deal "POOL")')
        self.assertNotIn("POOL", names)                                         # (the collateral is not a hedge of itself)
        hedge = self.columns('(deal-hedge deal "POOL")')
        self.assertAlmostEqual(hedge["dollar convexity"][3], 0.0, delta=1e-6 * abs(hedge["dollar convexity"][0]))

    def test_the_face_of_a_position_is_its_market_value_over_its_price(self):
        self.make_deal()
        hedge = self.columns('(deal-hedge deal "A")')
        self.assertAlmostEqual(hedge["face"][0], 6000000.0, places=2)           # (A's balance)
        treasury = [i for i, name in enumerate(hedge["position"]) if name.endswith("Treasury")]
        for row in treasury:
            self.assertAlmostEqual(hedge["face"][row], hedge["market value"][row], delta=1e-3 * abs(hedge["market value"][row]))

    def test_what_is_wrong_is_said(self):
        self.run_lisp('''(define deal (new-deal "Hedge" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25) :treasury-curve '((2 4.0))
                                               :collateral '((10000000.0 6.5 6.0 24))))
                         (deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
                         (deal-set-price! deal "A" 101.0)''')
        self.assertLispError('(deal-hedge deal "A")', "A has no effective duration and convexity to hedge")
        self.run_lisp("(deal-run-paths! deal :paths 2)")
        self.assertLispError('(deal-hedge deal "A")', "there are not two instruments to hedge A with")


if __name__ == "__main__":
    unittest.main()
