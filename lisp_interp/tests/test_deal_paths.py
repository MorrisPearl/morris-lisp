"""The option-adjusted spread and the effective duration of the tranches of a deal (lib/deal_paths.lsp, and what lib/deal_pricing.lsp does with them): the deal is run on
paths of rates, the collateral prepaid on each by a model, and a tranche is worth the average of its cash flows discounted along the paths. The numbers are checked against
the same sums done here, in numpy, from the paths and the cash flows that the deal made. The deals are of 24 months and a few paths, so that they run quickly."""

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

CURVE = [(1, 4.0), (2, 4.1), (3, 4.2), (5, 4.3), (10, 4.5)]
FRACTION = 35 / 30.0                       # (from the closing date, 2026-11-20, to the first payment, 2026-12-25, by the 30/360 count)

DEAL = '''
  (define deal (new-deal "Demo" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                         :collateral '((10000000.0 6.5 6.0 24)) :speed (prepayment-speed 'psa 150)))
  (deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
  (deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))'''


def mean_value(flows, rates, oas, fraction=FRACTION):
    """What the cash flows, one vector for each path, are worth on average on the paths of short rates, at this spread (a decimal)."""
    values = []
    for flow, path in zip(flows, rates):
        discount, total = 1.0, 0.0
        for month, cash in enumerate(flow):
            discount *= (1 + (path[month] + oas) / 12.0) ** (-(fraction if month == 0 else 1.0))
            total += cash * discount
        values.append(total)
    return float(np.mean(values))


class PathsCase(LispTestCase):

    PATHS = 6

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_pricing.lsp")')
        self.run_lisp(DEAL)

    def run_paths(self, paths=None, options=""):
        self.run_lisp("(deal-run-paths! deal :paths %d %s)" % (paths or self.PATHS, options))

    def slot(self, name, slot):
        return self.run_lisp('(node-%s (get-node deal "%s"))' % (slot, name))

    def vectors(self, source):
        return [np.array(v.items, dtype=float) for v in lisp_core.pairs_to_list(self.run_lisp(source))]

    def path_flows(self, name, which="base"):
        return self.vectors('(hash-table-ref (path-run-flows (path-sets-%s (deal-path-sets deal))) "%s")' % (which, name))

    def path_rates(self, which="base"):
        return self.vectors("(path-run-rates (path-sets-%s (deal-path-sets deal)))" % which)


class TestPiecesAreStructs(PathsCase):

    def test_a_piece_is_made_from_a_list_or_is_a_struct_already(self):
        self.assertShows("(collateral-piece-age (collateral-piece-of '(1000.0 6.0 5.5 12)))", "0")
        self.assertShows("(collateral-piece-age (collateral-piece-of '(1000.0 6.0 5.5 12 3)))", "3")
        self.run_lisp("(define piece (make-collateral-piece :balance 1000.0 :wac 6.0 :coupon 5.5 :wam 12))")
        self.assertShows("(eq? piece (collateral-piece-of piece))", "#t")
        self.assertShows("(collateral-piece-age piece)", "0")
        self.assertLispError("(collateral-piece-of '(1 2 3))", "a piece of collateral is (balance wac coupon wam [age])")
        self.assertLispError("(collateral-piece-of 5)", "a piece of collateral is (balance wac coupon wam [age])")

    def test_structs_and_lists_make_the_same_deal_and_the_same_cash_flows(self):
        self.run_lisp('''(define pieces (list (make-collateral-piece :balance 100000000.0 :wac 6.5 :coupon 6.0 :wam 360)
                                              (make-collateral-piece :balance 50000000.0 :wac 7.5 :coupon 6.5 :wam 240 :age 12)))
                         (define listed '((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.5 240 12)))
                         (define speed (prepayment-speed 'psa 150))''')
        for part in range(4):
            np.testing.assert_allclose(self.vectors("(list (list-ref (project-pieces pieces speed) %d))" % part)[0],
                                       self.vectors("(list (list-ref (project-pieces listed speed) %d))" % part)[0])
        self.run_lisp('(define by-structs (new-deal "S" :collateral pieces)) (define by-lists (new-deal "L" :collateral listed))')
        self.assertShows("(equal? (deal-pieces by-structs) (deal-pieces by-lists))", "#t")             # (their tables have nan, not known, which is not equal to itself)

    def test_the_pieces_of_a_deal_are_structs(self):
        self.assertShows("(collateral-piece? (car (deal-pieces deal)))", "#t")
        self.assertShows("(collateral-piece-wam (car (deal-pieces deal)))", "24")
        self.assertShows("(collateral-piece-coupon (car (deal-pieces deal)))", "6.0")

    def test_a_piece_with_something_wrong_with_it_is_said_so_as_a_struct_too(self):
        self.assertLispError("(project-pieces (list (make-collateral-piece :balance 1.0 :wac 5.0 :coupon 6.0 :wam 12)) (prepayment-speed 'psa 100))",
                             "is above its wac")


class TestPresentValuesOfPaths(PathsCase):

    def test_each_path_is_worth_its_cash_flows_discounted_by_the_rates_of_the_path_and_the_spread(self):
        flows = [np.array([1.0, 2.0, 3.0, 4.0]), np.array([4.0, 3.0, 2.0, 1.0]), np.array([0.0, 5.0, 0.0, 5.0])]
        rates = [np.array([0.04, 0.041, 0.042, 0.043, 0.044]), np.array([0.05] * 5), np.array([0.01, 0.02, 0.03, 0.04, 0.05])]
        lisp_vectors = lambda arrays: "(list %s)" % " ".join("(vector %s)" % " ".join(repr(float(x)) for x in a) for a in arrays)
        for oas, fraction in ((0.0, 1.0), (0.01, 1.0), (-0.005, 35 / 30.0), (0.02, 0.5)):
            with self.subTest(oas=oas, fraction=fraction):
                values = np.array(self.run_lisp("(path-present-values %s %s %r %r)" % (lisp_vectors(flows), lisp_vectors(rates), oas, fraction)).items)
                expected = [mean_value([f], [r], oas, fraction) for f, r in zip(flows, rates)]
                np.testing.assert_allclose(values, expected, rtol=1e-12)

    def test_it_agrees_with_the_library_function_of_one_path(self):
        self.run_lisp('(load "oas_monte_carlo.lsp")')
        self.assertAlmostEqual(self.run_lisp("(vector-ref (path-present-values (list (vector 1.0 2.0 3.0)) (list (vector 0.04 0.05 0.06)) 0.01) 0)"),
                               self.run_lisp("(path-present-value (vector 1.0 2.0 3.0) (vector 0.04 0.05 0.06) 0.01)"), places=12)

    def test_one_vector_of_cash_flows_is_for_every_path(self):
        values = self.vectors("(list (path-present-values (vector 1.0 1.0) (list (vector 0.0 0.0) (vector 0.12 0.12)) 0.0))")[0]
        self.assertAlmostEqual(values[0], 2.0)
        self.assertAlmostEqual(values[1], 1 / 1.01 + 1 / 1.01 ** 2)

    def test_what_is_wrong_is_said(self):
        self.assertLispError("(path-present-values (list (vector 1.0) (vector 1.0)) (list (vector 0.04)) 0.0)", "one for each path")
        self.assertLispError("(path-present-values (vector 1.0 1.0) (list (vector 0.04)) 0.0)", "a rate for each of the 2 months")
        self.assertLispError("(path-present-values (vector 1.0) (list (vector 0.04)) -50.0)", "not above 0")
        self.assertLispError("(path-present-values (vector 1.0) '() 0.0)", "no rate paths")


class TestTheModels(PathsCase):

    def test_a_prepayment_rate_in_percent_is_a_single_monthly_mortality(self):
        smms = self.vectors("(list (smms-from-cprs (vector 6.0 12.0 0.0 100.0) 4))")[0]
        np.testing.assert_allclose(smms, [1 - 0.94 ** (1 / 12), 1 - 0.88 ** (1 / 12), 0.0, 1 - 0.01 ** (1 / 12)])      # (a rate of 100 is capped at 99)
        self.assertLispError("(smms-from-cprs (vector 6.0) 4)", "for 1 months, and the piece of collateral has 4")

    def test_the_static_model_gives_back_the_rates_of_its_speed_whatever_the_path_is(self):
        self.run_lisp('''(define piece (make-collateral-piece :balance 1000.0 :wac 6.0 :coupon 6.0 :wam 36 :age 10))
                         (define model (static-prepayment-model (prepayment-speed 'psa 200)))
                         (define cprs (model piece (make-rate-path :short-rates (make-vector 37 0.04) :long-yields (make-vector 37 0.05))))''')
        cprs = self.vectors("(list cprs)")[0]
        expected = [min(0.06 * (10 + t) / 30, 0.06) * 2 * 100 for t in range(36)]                  # (200% of the PSA curve, at the age of the loans)
        np.testing.assert_allclose(cprs, np.minimum(expected, 99) , rtol=1e-9)
        self.assertEqual(len(cprs), 36)

    def test_the_deal_has_no_model_to_begin_with_and_the_rate_model_has_the_numbers_of_the_manual(self):
        self.assertShows("(deal-prepayment-model deal)", "()")
        self.assertShows("(deal-index-function deal)", "()")
        self.assertShows("(deal-rate-model deal)", "()")
        self.assertShows("(list (rate-model-a (deal-rate-model-in-use deal)) (rate-model-sigma1 (deal-rate-model-in-use deal)) (rate-model-sigma2 (deal-rate-model-in-use deal)))",
                         "(2.75 0.019 0.012)")

    def test_the_paths_start_on_the_forward_curve_of_the_treasury_curve_of_the_deal(self):
        forwards = np.array(self.run_lisp("(deal-forward-curve deal)").items)
        self.assertEqual(len(forwards), 360)
        self.assertTrue((forwards > 0.03).all() and (forwards < 0.08).all())
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0))")                 # (no volatility: every path is the curve, read forward)
        self.run_paths(2)
        np.testing.assert_allclose(self.path_rates()[0][:24], forwards[:24], rtol=1e-9)

    def test_it_needs_a_treasury_curve(self):
        self.run_lisp("(deal-clear-treasury-curve! deal)")
        self.assertLispError("(deal-forward-curve deal)", "has no Treasury curve")
        self.assertLispError("(deal-run-paths! deal :paths 2)", "has no Treasury curve")


class TestRunningThePaths(PathsCase):

    def test_what_is_wrong_with_the_arguments_is_said(self):
        for options, message in ((":paths 0", "a whole number above 0"), (":paths 2.5", "a whole number above 0"), (":shift 0", "a number above 0"),
                                 (":shift -0.01", "a number above 0"), (":seed 1.5", "the seed is a whole number")):
            with self.subTest(options=options):
                self.assertLispError("(deal-run-paths! deal %s)" % options, message)

    def test_a_deal_with_no_collateral_or_with_cash_flows_that_were_not_made_from_pieces_cannot_be_run(self):
        self.run_lisp('(define empty (new-deal "Empty" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)))')
        self.assertLispError("(deal-run-paths! empty :paths 2)", "has no collateral")
        self.run_lisp(hand_deal([100.0, 50.0, 0.0], [50.0, 50.0], interest=[1.0, 0.5], coupon=0.12))
        self.run_lisp("(deal-set-treasury-curve! deal '((2 4.0)))")
        self.assertLispError("(deal-run-paths! deal :paths 2)", "has none")

    def test_the_paths_are_made_even_and_kept_with_the_cash_flows_of_every_tranche_on_each_in_three_sets(self):
        self.run_paths(5)
        self.assertShows("(path-sets-paths (deal-path-sets deal))", "6")
        self.assertShows("(path-sets-shift (deal-path-sets deal))", "0.0025")
        self.assertShows("(path-sets-seed (deal-path-sets deal))", "1")
        for which in ("base", "up", "down"):
            self.assertEqual(len(self.path_rates(which)), 6)
            for name in ("POOL", "A", "B"):
                flows = self.path_flows(name, which)
                self.assertEqual((len(flows), len(flows[0])), (6, 24))

    def test_it_says_how_far_it_has_got(self):
        self.out.clear()
        self.run_paths(10)
        shown = self.printed()
        for text in ("on the curve: 1 of 10 paths", "on the curve: 10 of 10 paths", "on the curve moved up: 10 of 10 paths", "on the curve moved down: 10 of 10 paths"):
            self.assertIn(text, shown)

    def test_the_cash_flows_of_the_tranches_add_up_on_every_path_to_those_of_the_collateral(self):
        self.run_paths()
        pool, a, b = (self.path_flows(name) for name in ("POOL", "A", "B"))
        for path in range(len(pool)):
            np.testing.assert_allclose(a[path] + b[path], pool[path], atol=1e-6)
            self.assertAlmostEqual(pool[path].sum() - 0.0, pool[path].sum())
        self.assertGreater(sum(flow.sum() for flow in a), 0)

    def test_the_same_seed_makes_the_same_paths_and_another_makes_others(self):
        self.run_paths(4)
        first = self.path_rates()
        self.run_paths(4)
        np.testing.assert_array_equal(first[0], self.path_rates()[0])
        self.run_paths(4, ":seed 2")
        self.assertFalse(np.array_equal(first[0], self.path_rates()[0]))

    def test_the_curves_that_are_moved_are_a_shift_up_and_down_with_the_same_random_numbers(self):
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0))")
        self.run_paths(2, ":shift 0.005")
        base, up, down = self.path_rates()[0][:24], self.path_rates("up")[0][:24], self.path_rates("down")[0][:24]
        np.testing.assert_allclose(up - base, 0.005, atol=1e-9)
        np.testing.assert_allclose(base - down, 0.005, atol=1e-9)
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model))")
        self.run_paths(4)
        base, up = self.path_rates()[1], self.path_rates("up")[1]
        np.testing.assert_allclose(up - base, 0.0025, atol=2e-5)                 # (the same shocks, on a curve that is higher: the shift is of the par curve)


class TestTheOasOfAPrice(PathsCase):

    def test_the_oas_is_the_spread_at_which_the_paths_value_the_cash_flows_at_the_money(self):
        self.run_paths()
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        oas, money = self.slot("A", "oas"), self.slot("A", "money")
        self.assertAlmostEqual(money, 6000000 * 1.005 + 6000000 * 0.06 * 19 / 360, places=4)
        self.assertAlmostEqual(mean_value(self.path_flows("A"), self.path_rates(), oas / 10000.0), money, delta=1e-6 * money)
        self.assertNotEqual(mean_value(self.path_flows("A"), self.path_rates(), oas / 10000.0 + 0.001), money)

    def test_a_price_given_before_the_paths_has_its_oas_when_they_are_run(self):
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertShows('(node-oas (get-node deal "A"))', "()")
        self.assertShows('(node-effective-duration (get-node deal "A"))', "()")
        self.run_paths()
        oas = self.slot("A", "oas")
        self.assertAlmostEqual(mean_value(self.path_flows("A"), self.path_rates(), oas / 10000.0), self.slot("A", "money"), delta=1e-4)
        self.assertEqual(self.slot("A", "price"), 100.5)

    def test_a_lower_price_is_a_higher_oas(self):
        self.run_paths()
        oases = []
        for price in (99.0, 100.5, 102.0):
            self.run_lisp('(deal-set-price! deal "A" %r)' % price)
            oases.append(self.slot("A", "oas"))
        self.assertGreater(oases[0], oases[1])
        self.assertGreater(oases[1], oases[2])

    def test_a_model_that_ignores_rates_has_an_oas_near_its_spread_to_the_zero_curve(self):
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0))")           # (one path, which is the curve: no option to be worth anything)
        self.run_paths(2)
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertLess(abs(self.slot("A", "oas") - self.slot("A", "spread")), 8.0)                       # (basis points: the day count, the compounding and the curve differ)

    def test_what_is_wrong_is_said(self):
        self.run_paths()
        self.assertLispError('(deal-set-price! deal "A" 1e9)', "no yield, from -100% to 1000%")


class TestGivingAnOas(PathsCase):

    def test_an_oas_gives_the_price_the_yield_and_the_rest(self):
        self.run_paths()
        self.run_lisp('(deal-set-oas! deal "B" 50)')
        self.assertEqual(self.slot("B", "oas"), 50)
        self.assertShows('(node-priced-by (get-node deal "B"))', "oas")
        money = mean_value(self.path_flows("B"), self.path_rates(), 0.005)
        self.assertAlmostEqual(self.slot("B", "money"), money, delta=1e-6 * money)
        self.assertAlmostEqual(self.slot("B", "price"), 100 * (money - 4000000 * 0.06 * 19 / 360) / 4000000, places=6)
        self.assertTrue(self.slot("B", "yield") > 0 and self.slot("B", "duration") > 0)

    def test_the_price_of_an_oas_has_that_oas_back(self):
        self.run_paths()
        self.run_lisp('(deal-set-oas! deal "B" 75)')
        price = self.slot("B", "price")
        self.run_lisp('(deal-set-price! deal "B" %r)' % price)
        self.assertAlmostEqual(self.slot("B", "oas"), 75.0, places=6)

    def test_it_needs_the_paths(self):
        self.assertLispError('(deal-set-oas! deal "B" 50)', "have not been run")
        self.assertShows('(node-priced-by (get-node deal "B"))', "()")

    def test_a_higher_oas_is_a_lower_price(self):
        self.run_paths()
        prices = []
        for oas in (0, 100, 200):
            self.run_lisp('(deal-set-oas! deal "A" %d)' % oas)
            prices.append(self.slot("A", "price"))
        self.assertGreater(prices[0], prices[1])
        self.assertGreater(prices[1], prices[2])

    def test_plus_and_question_mark_work_with_an_oas(self):
        self.run_paths()
        self.run_lisp('(deal-set-oas! deal "A" 60) (deal-set-oas! deal "B" 90)')
        self.run_lisp('(deal-set-price! deal "POOL" "+")')
        self.assertAlmostEqual(self.slot("POOL", "money"), self.slot("A", "money") + self.slot("B", "money"), places=4)
        self.assertTrue(60 < self.slot("POOL", "oas") < 90)


class TestEffectiveDuration(PathsCase):

    def test_it_is_how_the_value_at_the_oas_falls_for_a_rise_in_rates(self):
        self.run_paths()
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        oas, money = self.slot("A", "oas") / 10000.0, self.slot("A", "money")
        down = mean_value(self.path_flows("A", "down"), self.path_rates("down"), oas)
        up = mean_value(self.path_flows("A", "up"), self.path_rates("up"), oas)
        self.assertAlmostEqual(self.slot("A", "effective-duration"), (down - up) / (2 * 0.0025 * money), places=6)

    def test_for_cash_flows_that_do_not_change_it_is_near_the_modified_duration(self):
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0))")
        self.run_paths(2)
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertAlmostEqual(self.slot("A", "effective-duration"), self.slot("A", "duration"), delta=0.05)
        self.assertGreater(self.slot("A", "effective-duration"), 0)

    def test_a_longer_bond_has_a_longer_one(self):
        self.run_paths()
        self.run_lisp('(deal-set-oas! deal "A" 50) (deal-set-oas! deal "B" 50)')
        self.assertGreater(self.slot("B", "effective-duration"), self.slot("A", "effective-duration"))

    def test_a_larger_shift_is_used_for_the_duration_that_it_says(self):
        self.run_paths(6, ":shift 0.01")
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        oas, money = self.slot("A", "oas") / 10000.0, self.slot("A", "money")
        down = mean_value(self.path_flows("A", "down"), self.path_rates("down"), oas)
        up = mean_value(self.path_flows("A", "up"), self.path_rates("up"), oas)
        self.assertAlmostEqual(self.slot("A", "effective-duration"), (down - up) / (2 * 0.01 * money), places=6)


class TestAModelThatLooksAtRates(PathsCase):

    MODEL = '''(define seen '())
               (define (refinancing piece path)
                 (set! seen (cons (list (collateral-piece? piece) (rate-path? path) (vector-length (rate-path-short-rates path))) seen))
                 (let ((incentive (vector-clip (- 0.045 (vector-take (rate-path-short-rates path) (collateral-piece-wam piece))) 0.0 1.0)))
                   (+ 5.0 (* 800.0 incentive))))
               (deal-set-prepayment-model! deal refinancing)
               (deal-set-pricing-speed! deal (prepayment-speed 'model 100))           ; (a model is used by a speed of the model)
               (set! seen '())'''

    def test_the_model_is_given_a_piece_and_a_path_and_its_rates_change_the_cash_flows_from_path_to_path(self):
        self.run_lisp(self.MODEL)
        self.run_paths(4)
        seen = lisp_core.pairs_to_list(self.run_lisp("seen"))
        self.assertGreaterEqual(len(seen), 12)            # (a piece on each of four paths, and on the two moved curves; and on the forward curve, for the pricing speed)
        self.assertEqual(lisp_core.pairs_to_list(seen[0])[:2], [True, True])
        flows = self.path_flows("A")
        first_months = [flow[:6].sum() for flow in flows]
        self.assertGreater(max(first_months) - min(first_months), 1.0)                  # (they prepay faster on a path where rates are lower)
        pool = self.path_flows("POOL")
        for flow in pool:
            self.assertGreater(flow.sum(), 10000000.0)                                   # (the collateral is paid, and its interest)

    def test_a_prepayment_model_that_prepays_faster_when_rates_fall_lowers_the_oas_of_a_bond_bought_above_par(self):
        self.run_paths(6)
        self.run_lisp('(deal-set-price! deal "A" 104.0)')
        static = self.slot("A", "oas")
        self.run_lisp(self.MODEL)
        self.run_paths(6)
        self.run_lisp('(deal-set-price! deal "A" 104.0)')
        self.assertNotAlmostEqual(self.slot("A", "oas"), static, places=1)

    def test_a_model_of_the_wrong_kind_is_refused_and_the_paths_are_forgotten_when_it_changes(self):
        self.assertLispError("(deal-set-prepayment-model! deal 5)", "a function of a piece of collateral")
        self.run_paths(2)
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertTrue(self.slot("A", "oas") is not None and not isinstance(self.slot("A", "oas"), type(None)))
        self.run_lisp("(deal-set-prepayment-model! deal '())")
        self.assertShows("(deal-path-sets deal)", "()")
        self.assertShows('(node-oas (get-node deal "A"))', "()")


class TestTheIndex(PathsCase):

    def floater_first_month(self, index_function):
        """What the floater F is paid in the first month, on a path of the deal with no volatility, with this index function (as Lisp text, or None for the one it begins with)."""
        self.run_lisp("(deal-set-index-function! deal %s)" % (index_function or "'()"))
        self.run_paths(2)
        return self.path_flows("F")[0][0]

    def setUp(self):
        super().setUp()
        self.run_lisp('(deal-floater-inverse! deal "B" "F" "I" :cap 0.09 :margin 0.005)')
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0))")

    def test_the_floater_is_of_the_short_rate_to_begin_with_and_of_what_the_function_makes_of_it(self):
        identity = self.floater_first_month(None)
        shifted = self.floater_first_month("(lambda (rates) (+ rates 0.01))")
        self.assertGreater(shifted, identity)
        self.assertLess(shifted - identity, 4000000.0 * 0.01 / 12 * 1.5)                # (a higher index of one percent, for a month and some of the balance of F, at most)

    def test_the_function_must_be_a_function_and_the_paths_are_forgotten_when_it_changes(self):
        self.assertLispError("(deal-set-index-function! deal 5)", "a function of a path of short rates")
        self.run_paths(2)
        self.run_lisp("(deal-set-index-function! deal '())")
        self.assertShows("(deal-path-sets deal)", "()")


class TestWhatForgetsThePaths(PathsCase):

    def run_and_price(self):
        self.run_paths(2)
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        self.assertShows("(null? (deal-path-sets deal))", "#f")
        self.assertTrue(self.slot("A", "oas") > -1000)

    def test_a_change_of_the_deal_forgets_them_and_the_oas_goes_with_them(self):
        for change in ("(deal-set-pricing-speed! deal (prepayment-speed 'psa 300))",
                       "(deal-sequential! deal \"B\" '((\"B1\" 1000000.0) (\"B2\" 3000000.0)))",
                       "(deal-set-treasury-curve! deal '((1 3.0) (2 3.1)))",
                       "(deal-set-rate-model! deal (make-rate-model :sigma1 0.01))",
                       "(deal-forget-paths! deal)"):
            with self.subTest(change=change):
                self.setUp()
                self.run_and_price()
                self.run_lisp(change)
                self.assertShows("(deal-path-sets deal)", "()")
                self.assertShows('(node-oas (get-node deal "A"))', "()")
                self.assertShows('(node-effective-duration (get-node deal "A"))', "()")
                self.assertEqual(self.slot("A", "price"), 100.5)                    # (what was given stays)

    def test_an_oas_that_was_given_has_nothing_to_take_its_price_from_and_says_so(self):
        self.run_paths(2)
        self.run_lisp('(deal-set-oas! deal "A" 60)')
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 300))")
        problems = self.run_lisp("(deal-update-analytics! deal)")
        self.assertIn("A: the paths of rates have not been run", str(problems.car))
        self.assertShows('(node-priced-by (get-node deal "A"))', "oas")
        self.run_paths(2)                                                              # (run again, and it is worked out again)
        self.assertEqual(self.slot("A", "oas"), 60)
        self.assertTrue(self.slot("A", "price") > 90)


class TestThePricingTableHasThem(PathsCase):

    def test_the_table_has_the_oas_and_the_effective_duration(self):
        self.run_paths(2)
        self.run_lisp('(deal-set-price! deal "A" 100.5)')
        table = self.run_lisp("(deal-pricing-table deal)")
        columns = {str(pair.car): list(pair.cdr.items) for pair in lisp_core.pairs_to_list(table)}
        self.assertEqual(list(columns), ["tranche", "balance", "price", "yield", "spread", "oas", "duration", "effective duration", "average life", "dv01", "money", "delay"])
        self.assertAlmostEqual(columns["oas"][1], self.slot("A", "oas"))
        self.assertTrue(np.isnan(columns["oas"][2]))


if __name__ == "__main__":
    unittest.main()
