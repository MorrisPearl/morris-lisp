"""A pricing speed of the prepayment model: (prepayment-speed 'model 105) is 105% of what the deal's prepayment model says, and the model looks at rates
(deal-project-pieces in lib/deal.lsp, model-speed-smms and deal-prepayment-model-in-use in lib/deal_paths.lsp, freddie-prepayment-model in
lib/freddie_prepayment.lsp). The model fitted to Freddie Mac's loans is stood in for by one fitted here to made-up loans whose monthly prepayment is exactly
a logistic curve of the incentive and the loan-to-value, so that what the deal does with it can be worked out here, month by month."""

import tempfile

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

PREDICTORS = ["incentive_bp", "loan_age", "loan_size_k", "credit_score", "current_ltv", "sato", "burnout",
              "investor", "second_home", "cash_out", "refinance", "winter", "summer"]


def stand_in_smm(incentive_bp, current_ltv):
    """The monthly prepayment of the made-up loans: it rises with the incentive, and falls as the loan-to-value rises."""
    return 1 / (1 + np.exp(-(-5.0 + 0.02 * incentive_bp - 0.02 * (current_ltv - 70))))


def cpr(smm):
    return 100 * (1 - (1 - smm) ** 12)


def stand_in_fit_source(rows=400, seed=3):
    """Lisp that fits the stand-in: a spline-logistic with no knots, on made-up loans whose smm is exactly stand_in_smm, so the fit is that curve."""
    rng = np.random.default_rng(seed)
    columns = {name: rng.uniform(0, 1, rows) for name in PREDICTORS}
    columns.update(incentive_bp=rng.uniform(-200, 300, rows), current_ltv=rng.uniform(30, 130, rows), loan_age=rng.uniform(1, 300, rows),
                   loan_size_k=rng.uniform(50, 600, rows), credit_score=rng.uniform(620, 820, rows), burnout=rng.uniform(0, 40, rows))
    smm = stand_in_smm(columns["incentive_bp"], columns["current_ltv"])
    vector = lambda values: "(vector %s)" % " ".join(repr(float(v)) for v in values)
    return "(spline-logistic (list %s) %s 0)" % (" ".join('(cons "%s" %s)' % (name, vector(columns[name])) for name in PREDICTORS), vector(smm))


def balance_left(wac, wam, months):
    """The share of the balance left at the start of each month, 1 to months, of a level-payment loan at the wac with wam payments to go."""
    growth = 1 + wac / 1200
    paid = np.arange(months)
    return (growth ** wam - growth ** paid) / (growth ** wam - 1)


CURVE = "'((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5) (30 4.8))"
PIECE = "(make-collateral-piece :balance 10000000.0 :wac 6.5 :coupon 6.0 :wam 36 :age 10 :loan-size 300000 :ltv 80.0 :credit-score 760)"


class ModelSpeedCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_pricing.lsp") (set! freddie-prepayment-fit-read %s)' % stand_in_fit_source())    # (the stand-in is the fitted model)
        self.run_lisp('''(define piece %s)
                         (define path (make-rate-path :short-rates (make-vector 37 0.04) :long-yields (make-vector 37 0.045) :first-payment (date 2026 12 25)))''' % PIECE)

    def vector(self, source):
        return np.array(self.run_lisp(source).items, dtype=float)

    def column(self, name, source="(prepayment-model-columns piece path)"):
        return self.vector('(cdr (assoc "%s" %s))' % (name, source))

    def make_deal(self, speed="(prepayment-speed 'model 100)"):
        self.run_lisp('''(define deal (new-deal "Model" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25) :treasury-curve %s
                                               :collateral (list %s) :speed %s))
                         (deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))''' % (CURVE, PIECE, speed))

    def smms(self, speed="(deal-pricing-speed deal)"):
        return self.vector("(model-speed-smms deal %s (car (deal-pieces deal)))" % speed)


class TestWhatTheModelLooksAt(ModelSpeedCase):

    def test_the_incentive_is_the_wac_over_the_10_year_yield_and_the_mortgage_spread(self):
        np.testing.assert_allclose(self.column("incentive_bp"), (6.5 - (4.5 + 1.75)) * 100)
        np.testing.assert_allclose(self.column("incentive_bp", "(prepayment-model-columns piece path :mortgage-spread 2.0)"), 0.0, atol=1e-9)

    def test_the_age_goes_on_from_the_piece_and_the_loan_size_and_the_ltv_are_paid_down(self):
        left = balance_left(6.5, 36, 36)
        np.testing.assert_allclose(self.column("loan_age"), np.arange(11, 47))
        np.testing.assert_allclose(self.column("loan_size_k"), 300 * left)
        np.testing.assert_allclose(self.column("current_ltv"), 80 * left / 1.03 ** (np.arange(36) / 12))       # (home prices grow 3% a year)
        np.testing.assert_allclose(self.column("current_ltv", "(prepayment-model-columns piece path :home-price-growth -10.0)"),
                                   80 * left / 0.9 ** (np.arange(36) / 12))
        self.assertAlmostEqual(self.column("loan_size_k")[-1] / 300, left[-1])
        self.assertLess(left[-1], 0.05)                                           # (the last payment is nearly all of what is left)

    def test_burnout_counts_the_months_in_the_money_before_each_after_the_first_year(self):
        self.run_lisp("(define low (make-rate-path :short-rates (make-vector 37 0.02) :long-yields (make-vector 37 0.03)))")   # (an incentive of 175)
        burnout = self.column("burnout", "(prepayment-model-columns piece low)")
        # (the age is 10 + the month, over 12 from month 3: month t has had the months from 3 to t - 1)
        np.testing.assert_allclose(burnout, np.maximum(0, np.arange(1, 37) - 3))
        self.assertEqual(self.column("burnout").sum(), 0)                         # (an incentive of 25 is not in the money)
        self.run_lisp("(collateral-piece-burnout-set! piece 7)")
        self.assertEqual(self.column("burnout", "(prepayment-model-columns piece low)")[0], 7)

    def test_the_seasons_are_of_the_months_from_the_first_payment_or_an_average_year(self):
        winter, summer = self.column("winter"), self.column("summer")
        self.assertEqual(list(winter[:4]), [0, 1, 1, 0])                          # (December, January, February, March)
        self.assertEqual(list(summer[:9]), [0, 0, 0, 0, 0, 1, 1, 1, 1])           # (May to August are months 6 to 9)
        self.run_lisp("(rate-path-first-payment-set! path '())")
        np.testing.assert_allclose(self.column("winter"), 2 / 12)
        np.testing.assert_allclose(self.column("summer"), 4 / 12)

    def test_what_a_piece_does_not_say_is_taken_from_the_typical_loan(self):
        self.run_lisp("(define bare (collateral-piece-of '(1000.0 6.5 6.0 36 10)))")
        self.assertEqual(self.column("credit_score", "(prepayment-model-columns bare path)")[0], 750)
        self.assertEqual(self.column("loan_size_k", "(prepayment-model-columns bare path)")[0], 250)
        self.assertEqual(self.column("current_ltv", "(prepayment-model-columns bare path)")[0], 70)
        self.assertEqual(self.column("investor", "(prepayment-model-columns bare path)")[0], 0)
        self.assertEqual(self.column("credit_score")[0], 760)

    def test_the_columns_are_the_predictors_of_the_model_and_the_path_must_be_long_enough(self):
        self.assertShows("(map car (prepayment-model-columns piece path))", "(%s)" % " ".join('"%s"' % name for name in PREDICTORS))
        self.assertLispError("(prepayment-model-columns piece (make-rate-path :short-rates (make-vector 12 0.04) :long-yields (make-vector 12 0.04)))",
                             "the path of rates has 12 months, and the piece of collateral 36")


class TestTheModel(ModelSpeedCase):

    def test_it_is_the_cpr_of_the_fitted_model_on_what_it_looks_at(self):
        cprs = self.vector("((freddie-prepayment-model) piece path)")
        incentive, ltv = self.column("incentive_bp"), self.column("current_ltv")
        np.testing.assert_allclose(cprs, cpr(stand_in_smm(incentive, ltv)), rtol=1e-4)
        np.testing.assert_allclose(self.vector("((freddie-prepayment-model :fit freddie-prepayment-fit-read) piece path)"), cprs)

    def test_lower_mortgage_rates_and_higher_home_prices_prepay_faster(self):
        base = self.vector("((freddie-prepayment-model) piece path)")
        self.assertTrue((self.vector("((freddie-prepayment-model :mortgage-spread 1.0) piece path)") > base).all())
        self.assertTrue((self.vector("((freddie-prepayment-model :home-price-growth 8.0) piece path)") > base)[1:].all())
        self.assertTrue((self.vector("((freddie-prepayment-model :home-price-growth -8.0) piece path)") < base)[1:].all())


class TestAPricingSpeedOfTheModel(ModelSpeedCase):

    def test_it_is_a_share_of_the_model_and_has_no_rates_of_its_own(self):
        self.assertShows("(describe-speed (prepayment-speed 'model 105))", '"MODEL 105"')
        self.assertShows("(model-speed? (prepayment-speed 'model 105))", "#t")
        self.assertShows("(model-speed? (prepayment-speed 'psa 105))", "#f")
        self.assertLispError("(speed-smms (prepayment-speed 'model 100) 0 12)", "MODEL 100 is a share of a prepayment model")

    def test_the_collateral_prepays_as_the_model_says_on_the_forward_curve(self):
        self.make_deal()
        long_yields = self.vector("(rate-path-long-yields (deal-forward-path deal 36))")[:36]
        ltv = 80 * balance_left(6.5, 36, 36) / 1.03 ** (np.arange(36) / 12)
        expected = 1 - (1 - cpr(stand_in_smm((6.5 - (100 * long_yields + 1.75)) * 100, ltv)) / 100) ** (1 / 12)
        np.testing.assert_allclose(self.smms(), expected, rtol=1e-4)
        principal = self.vector('(node-principal (get-node deal "POOL"))')
        np.testing.assert_allclose(principal, self.vector("(car (project-pieces-with (deal-pieces deal) (lambda (piece) (model-speed-smms deal (deal-pricing-speed deal) piece))))"))
        self.assertAlmostEqual(principal.sum(), 10000000.0, places=2)

    def test_the_number_of_the_speed_is_a_share_of_the_model_month_by_month(self):
        self.make_deal()
        base = cpr(self.smms())
        np.testing.assert_allclose(cpr(self.smms("(prepayment-speed 'model 105)")), 1.05 * base, rtol=1e-9)
        ramp = cpr(self.smms("(prepayment-speed 'model '((50 100 12)))"))
        np.testing.assert_allclose(ramp[11:], base[11:], rtol=1e-9)              # (from 50% to 100% over a year, then 100%)
        np.testing.assert_allclose(ramp[0] / base[0], (50 + 50 / 12) / 100, rtol=1e-9)

    def test_it_needs_a_treasury_curve_and_nothing_is_changed_without_one(self):
        self.run_lisp('''(define deal (new-deal "Model" :collateral (list %s)))''' % PIECE)
        self.assertLispError("(deal-set-pricing-speed! deal (prepayment-speed 'model 100))", "needs a Treasury curve")
        self.assertShows("(speed-curve-type (deal-pricing-speed deal))", "psa")
        self.run_lisp("(deal-set-treasury-curve! deal %s) (deal-set-pricing-speed! deal (prepayment-speed 'model 100))" % CURVE)
        self.assertLispError("(deal-clear-treasury-curve! deal)", "choose another speed before taking the curve away")

    def test_what_the_model_is_told_changes_the_cash_flows_at_a_speed_of_the_model(self):
        self.make_deal()
        principal = lambda: self.vector('(node-principal (get-node deal "POOL"))')[:12].sum()
        a_life = lambda: self.run_lisp('(begin (deal-run! deal) (average-life (node-principal (get-node deal "A"))))')
        before, life = principal(), a_life()
        self.run_lisp("(deal-set-mortgage-spread! deal 1.0)")                          # (lower mortgage rates: faster)
        self.assertGreater(principal(), before)
        self.assertLess(a_life(), life)
        before = principal()
        self.run_lisp("(deal-set-home-price-growth! deal -10.0)")                     # (less equity: slower)
        self.assertLess(principal(), before)
        before = principal()
        self.run_lisp("(deal-set-treasury-curve! deal '((1 3.0) (10 3.5) (30 3.8)))")  # (rates a point lower: faster)
        self.assertGreater(principal(), before)
        self.assertShows("(list (deal-mortgage-spread deal) (deal-home-price-growth deal))", "(1.0 -10.0)")
        self.assertLispError("(deal-set-home-price-growth! deal -100)", "above -100")
        self.assertLispError('(deal-set-mortgage-spread! deal "wide")', "the mortgage spread is in percent")

    def test_at_another_speed_what_the_model_is_told_changes_nothing(self):
        self.make_deal("(prepayment-speed 'psa 150)")
        before = self.vector('(node-principal (get-node deal "POOL"))')
        self.run_lisp("(deal-set-mortgage-spread! deal 1.0) (deal-set-home-price-growth! deal -10.0)")
        np.testing.assert_allclose(self.vector('(node-principal (get-node deal "POOL"))'), before)

    def test_a_model_of_ones_own_is_the_one_the_speed_is_a_share_of(self):
        self.make_deal("(prepayment-speed 'model 200)")
        self.run_lisp("(deal-set-prepayment-model! deal (lambda (piece path) (make-vector (collateral-piece-wam piece) 6.0)))")
        np.testing.assert_allclose(cpr(self.smms()), 12.0, rtol=1e-9)                # (200% of 6 CPR)
        self.run_lisp("(deal-set-prepayment-model! deal '())")                        # (and '() is the fitted one again)
        self.assertGreater(np.ptp(cpr(self.smms())), 0.1)


class TestTheFitThatComesWithTheLibrary(LispTestCase):

    def test_it_is_read_from_beside_the_library_wherever_the_notebook_is_and_prepays_faster_in_the_money(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        cwd = os.getcwd()
        os.chdir(folder)
        try:
            self.run_lisp('(load "freddie_prepayment.lsp") (define fit (freddie-prepayment-fit))')
        finally:
            os.chdir(cwd)
        self.assertShows("(model-kind fit)", '"spline-logistic"')
        self.assertIn("burnout", self.run_lisp("(model-report fit)"))
        self.run_lisp('(define curve (prepayment-s-curve fit))')
        cprs = dict(zip(self.run_lisp('(table-column curve "incentive_bp")').items, self.run_lisp('(table-column curve "CPR")').items))
        self.assertTrue(2 < cprs[-100] < cprs[0] < cprs[100] < cprs[200] < 90)


class TestTheOas(ModelSpeedCase):

    def test_with_no_volatility_every_path_prepays_as_the_pricing_speed_does(self):
        self.make_deal()
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0)) (deal-run-paths! deal :paths 2)")
        pool = [np.array(v.items, dtype=float) for v in lisp_core.pairs_to_list(
            self.run_lisp('(hash-table-ref (path-run-flows (path-sets-base (deal-path-sets deal))) "POOL")'))]
        flows = self.run_lisp("(deal-pricing-flows deal)")
        expected = np.array(flows.car.items) + np.array(flows.cdr.car.items)                  # (principal and interest, at the pricing speed)
        for flow in pool:
            np.testing.assert_allclose(flow, expected, rtol=1e-9)

    def test_on_paths_that_differ_the_collateral_prepays_differently_and_the_effective_duration_feels_it(self):
        self.make_deal()
        self.run_lisp("(deal-run-paths! deal :paths 6) (deal-set-price! deal \"A\" 101.0)")
        pool = [np.array(v.items, dtype=float) for v in lisp_core.pairs_to_list(
            self.run_lisp('(hash-table-ref (path-run-flows (path-sets-base (deal-path-sets deal))) "POOL")'))]
        firsts = [flow[:12].sum() for flow in pool]
        self.assertGreater(max(firsts) - min(firsts), 1000.0)                  # (on a path where rates fall, the loans prepay faster)
        self.assertTrue(self.run_lisp('(number? (node-oas (get-node deal "A")))'))
        duration, effective = self.run_lisp('(node-duration (get-node deal "A"))'), self.run_lisp('(node-effective-duration (get-node deal "A"))')
        self.assertLess(effective, duration)                                   # (when rates rise, the loans prepay slower, and A is paid later)
        self.run_lisp("(deal-set-pricing-speed! deal (prepayment-speed 'psa 150))")
        self.assertShows("(deal-path-sets deal)", "()")                          # (the paths were of the model: they are forgotten)


if __name__ == "__main__":
    unittest.main()
