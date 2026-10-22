"""Defaults and losses in a deal: project-pool with defaults (lib/prepayment_speed.lsp), the default and severity models for a deal (freddie-default-model,
freddie-severity-model in lib/freddie_default.lsp), and a deal whose loans default (deal-set-defaults!, deal-set-liquidation-lag!, in lib/deal.lsp and
lib/deal_paths.lsp). The fitted models are stood in for by ones fitted here to made-up loans whose default rate is exactly a logistic curve of the loan-to-value,
and whose severity is exactly a straight line in it, so that what the deal does with them can be worked out here."""

import tempfile

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

DEFAULT_PREDICTORS = ["credit_score", "current_ltv", "loan_age", "dti", "sato", "incentive_bp", "loan_size_k",
                      "investor", "second_home", "cash_out", "refinance", "one_borrower"]
SEVERITY_PREDICTORS = ["ltv_at_default", "loan_size_k", "mi_percent", "months_since_default", "investor"]


def stand_in_mdr(current_ltv):
    return 1 / (1 + np.exp(-(-7.0 + 0.04 * (current_ltv - 80))))


def stand_in_severity(ltv_at_default):
    return 0.2 + 0.004 * (ltv_at_default - 60)


def lisp_columns(columns, names):
    vector = lambda values: "(vector %s)" % " ".join(repr(float(v)) for v in values)
    return "(list %s)" % " ".join('(cons "%s" %s)' % (name, vector(columns[name])) for name in names)


def stand_in_fits_source(rows=400, seed=5):
    """Lisp that makes the stand-ins the fitted models, as the deal reads them."""
    rng = np.random.default_rng(seed)
    columns = {name: rng.uniform(0, 1, rows) for name in DEFAULT_PREDICTORS}
    columns.update(current_ltv=rng.uniform(30, 160, rows), credit_score=rng.uniform(620, 820, rows), loan_age=rng.uniform(1, 300, rows),
                   dti=rng.uniform(10, 50, rows), incentive_bp=rng.uniform(-200, 300, rows), loan_size_k=rng.uniform(50, 600, rows))
    sales = {name: rng.uniform(0, 1, rows) for name in SEVERITY_PREDICTORS}
    sales.update(ltv_at_default=rng.uniform(30, 160, rows), loan_size_k=rng.uniform(50, 600, rows), mi_percent=rng.uniform(0, 30, rows),
                 months_since_default=rng.uniform(3, 40, rows))
    vector = lambda values: "(vector %s)" % " ".join(repr(float(v)) for v in values)
    return ("(set! freddie-default-fit-read (spline-logistic %s %s 0))" % (lisp_columns(columns, DEFAULT_PREDICTORS), vector(stand_in_mdr(columns["current_ltv"])))
            + "(set! freddie-severity-fit-read (spline-regression %s %s 0))" % (lisp_columns(sales, SEVERITY_PREDICTORS),
                                                                              vector(stand_in_severity(sales["ltv_at_default"]))))


def balance_left(wac, wam, months):
    growth = 1 + wac / 1200
    return (growth ** wam - growth ** np.arange(months)) / (growth ** wam - 1)


CURVE = "'((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5) (30 4.8))"
PIECE = "(make-collateral-piece :balance 10000000.0 :wac 6.5 :coupon 6.0 :wam 36 :age 10 :ltv 90.0 :credit-score 700)"


class DefaultsCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "deal_pricing.lsp") %s' % stand_in_fits_source())

    def vector(self, source):
        return np.array(self.run_lisp(source).items, dtype=float)

    def make_deal(self, defaults=100, speed="(prepayment-speed 'psa 150)"):
        self.run_lisp('''(define deal (new-deal "Losses" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25) :treasury-curve %s
                                               :collateral (list %s) :speed %s))
                         (deal-sequential! deal "POOL" '(("A" 8000000.0) ("B" 1500000.0) ("C" 500000.0)))
                         (deal-set-defaults! deal %s)
                         (deal-run! deal)''' % (CURVE, PIECE, speed, defaults))

    def node(self, name, slot):
        return self.vector('(node-%s (get-node deal "%s"))' % (slot, name))


class TestAPoolThatDefaults(DefaultsCase):

    def test_a_default_stops_paying_is_advanced_its_interest_and_is_sold_after_the_lag(self):
        # 1,000 at 12%, three months, no prepayments; a tenth defaults in the first month, and is sold a month later at a loss of 40%
        flows = self.run_lisp("(project-pool 1000.0 12.0 12.0 3 (vector 0.0 0.0 0.0) :mdrs (vector 0.1 0.0 0.0) :severities (vector 0.4 0.4 0.4) :lag 1)")
        principal, interest, balances, gross, loss = [np.array(v.items, dtype=float) for v in lisp_core.pairs_to_list(flows)]
        paying = 900.0
        scheduled = []
        for months_left in (3, 2, 1):
            payment = paying * 0.01 / (1 - 1.01 ** -months_left)
            scheduled.append(payment - paying * 0.01)
            paying -= scheduled[-1]
        np.testing.assert_allclose(principal, [scheduled[0], scheduled[1] + 60.0, scheduled[2], 0.0])      # (the sale brings back 60 of the 100)
        np.testing.assert_allclose(loss, [0.0, 40.0, 0.0, 0.0])
        np.testing.assert_allclose(interest[0], 10.0)                       # (all that is owed, 1,000, pays its coupon: the 100 is advanced)
        np.testing.assert_allclose(interest[1], (1000.0 - scheduled[0]) * 0.01)
        self.assertAlmostEqual(principal.sum() + loss.sum(), 1000.0)
        self.assertAlmostEqual(balances[-1], 0.0)
        self.assertEqual(len(principal), 4)                                 # (three months, and the month of the last sale)

    def test_no_defaults_are_the_cash_flows_there_were(self):
        before = self.run_lisp("(project-pool 1000.0 6.0 5.5 12 (make-vector 12 0.01))")
        after = self.run_lisp("(project-pool 1000.0 6.0 5.5 12 (make-vector 12 0.01) :mdrs (make-vector 12 0.0) :severities (make-vector 12 0.4) :lag 0)")
        for a, b in zip(lisp_core.pairs_to_list(before), lisp_core.pairs_to_list(after)):
            np.testing.assert_allclose(a.items, b.items)


class TestTheModelsForADeal(DefaultsCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('''(define piece %s)
                         (define path (make-rate-path :short-rates (make-vector 37 0.04) :long-yields (make-vector 37 0.045) :first-payment (date 2026 12 25)))''' % PIECE)

    def test_the_default_model_looks_at_the_loan_to_value_along_the_path(self):
        self.assertShows("(map car (default-model-columns piece path))", "(%s)" % " ".join('"%s"' % name for name in DEFAULT_PREDICTORS))
        ltv = 90 * balance_left(6.5, 36, 36) / 1.03 ** (np.arange(36) / 12)
        np.testing.assert_allclose(self.vector('(cdr (assoc "current_ltv" (default-model-columns piece path)))'), ltv)
        np.testing.assert_allclose(self.vector('(cdr (assoc "dti" (default-model-columns piece path)))'), 36)              # (the piece does not say)
        np.testing.assert_allclose(self.vector('(cdr (assoc "one_borrower" (default-model-columns piece path)))'), 0.5)
        np.testing.assert_allclose(self.vector("((freddie-default-model) piece path)"), 100 * (1 - (1 - stand_in_mdr(ltv)) ** 12), rtol=1e-4)

    def test_the_severity_model_looks_at_the_loan_to_value_when_they_default_and_the_lag(self):
        self.assertShows("(map car (severity-model-columns piece path))", "(%s)" % " ".join('"%s"' % name for name in SEVERITY_PREDICTORS))
        np.testing.assert_allclose(self.vector('(cdr (assoc "months_since_default" (severity-model-columns piece path :lag 24)))'), 24)
        ltv = 90 * balance_left(6.5, 36, 36) / 1.03 ** (np.arange(36) / 12)
        np.testing.assert_allclose(self.vector("((freddie-severity-model) piece path)"), np.clip(stand_in_severity(ltv), 0, 1), atol=1e-6)
        self.run_lisp("(collateral-piece-ltv-set! piece 20.0)")
        self.assertEqual(self.vector("((freddie-severity-model) piece path)").min(), 0.0)          # (no less than nothing is lost)


class TestADealThatDefaults(DefaultsCase):

    def test_the_collateral_loses_what_the_models_say_and_the_tranches_are_written_down_from_the_bottom(self):
        self.make_deal()
        self.assertShows("(deal-periods deal)", "54")                                  # (36 months, and the 18 to the last sale)
        pool_loss = self.node("POOL", "loss")
        self.assertGreater(pool_loss.sum(), 1000.0)
        self.assertEqual(pool_loss[:18].sum(), 0.0)                                     # (nothing is sold for 18 months)
        self.assertAlmostEqual(self.node("C", "loss").sum() + self.node("B", "loss").sum() + self.node("A", "loss").sum(), pool_loss.sum(), places=4)
        self.assertEqual(self.node("A", "loss").sum(), 0.0)
        self.assertShows("(deal-check deal)", "#t")
        self.assertAlmostEqual(self.node("POOL", "principal").sum() + pool_loss.sum(), 10000000.0, places=3)
        defaults = self.run_lisp("(deal-piece-defaults deal (car (deal-pieces deal)) (deal-forward-path deal 36))")
        mdrs, severities = (np.array(v.items) for v in lisp_core.pairs_to_list(defaults))
        flows = self.run_lisp("(project-pool 10000000.0 6.5 6.0 36 (speed-smms (prepayment-speed 'psa 150) 10 36) :mdrs (vector %s) :severities (vector %s) :lag 18)"
                              % (" ".join(repr(float(x)) for x in mdrs), " ".join(repr(float(x)) for x in severities)))
        np.testing.assert_allclose(pool_loss, lisp_core.pairs_to_list(flows)[4].items, rtol=1e-9)

    def test_twice_the_model_defaults_about_twice_as_much_and_none_is_none(self):
        self.make_deal(100)
        once = self.node("POOL", "loss").sum()
        self.run_lisp("(deal-set-defaults! deal 200) (deal-run! deal)")
        self.assertAlmostEqual(self.node("POOL", "loss").sum() / once, 2.0, delta=0.1)
        self.run_lisp("(deal-set-defaults! deal 0) (deal-run! deal)")
        self.assertEqual(self.node("POOL", "loss").sum(), 0.0)
        self.assertShows("(deal-periods deal)", "36")

    def test_the_lag_moves_the_losses_and_the_model_says_more_is_lost_for_waiting(self):
        self.make_deal()
        first_loss = lambda: int(np.nonzero(self.node("POOL", "loss"))[0][0])
        self.assertEqual(first_loss(), 18)
        self.run_lisp("(deal-set-liquidation-lag! deal 6) (deal-run! deal)")
        self.assertEqual(first_loss(), 6)
        self.assertShows("(deal-periods deal)", "42")

    def test_home_prices_that_fall_lose_more(self):
        self.make_deal()
        before = self.node("POOL", "loss").sum()
        self.run_lisp("(deal-set-home-price-growth! deal -10.0) (deal-run! deal)")
        self.assertGreater(self.node("POOL", "loss").sum(), 1.2 * before)                # (more default, and each loses more)

    def test_a_bond_that_is_written_down_yields_less_at_the_same_price(self):
        self.make_deal(0)
        self.run_lisp('(deal-set-price! deal "C" 95.0)')
        clean = self.run_lisp('(node-yield (get-node deal "C"))')
        self.run_lisp("(deal-set-defaults! deal 300)")
        self.assertLess(self.run_lisp('(node-yield (get-node deal "C"))'), clean - 1.0)

    def test_what_is_wrong_is_said_and_the_default_model_needs_the_curve(self):
        self.make_deal()
        self.assertLispError("(deal-set-defaults! deal -5)", "a percent of the default model, from 0")
        self.assertLispError("(deal-set-liquidation-lag! deal 2.5)", "a whole number, from 0")
        self.assertLispError("(deal-clear-treasury-curve! deal)", "make the defaults 0 before taking the curve away")
        self.run_lisp('(define plain (new-deal "Plain" :collateral (list %s)))' % PIECE)
        self.assertLispError("(deal-set-defaults! plain 100)", "needs a Treasury curve")
        self.assertShows("(deal-defaults plain)", "0")


class TestTheFitsThatComeWithTheLibrary(LispTestCase):

    def test_they_are_read_from_beside_the_library_and_lose_more_at_a_higher_loan_to_value(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        cwd = os.getcwd()
        os.chdir(folder)
        try:
            self.run_lisp('(load "freddie_default.lsp") (define defaults (freddie-default-fit)) (define severity (freddie-severity-fit))')
        finally:
            os.chdir(cwd)
        self.assertShows("(model-kind defaults)", '"spline-logistic"')
        self.assertShows("(model-kind severity)", '"spline"')
        cdrs = np.array(self.run_lisp('(table-column (default-ltv-curves defaults) "CDR, credit score 700")').items)
        self.assertTrue(cdrs[0] < cdrs[4] < cdrs[8] < 20)                                  # (at 40%, 80% and 120% loan-to-value)
        severities = np.array(self.run_lisp('(table-column (severity-ltv-curve severity) "severity")').items)
        self.assertTrue(0 < severities[2] < severities[6] < severities[10] < 100)          # (at 60%, 100% and 140%)


class TestTheOas(DefaultsCase):

    def test_with_no_volatility_every_path_has_the_losses_of_the_pricing_speed(self):
        self.make_deal(100, "(prepayment-speed 'model 100)")
        self.run_lisp('''(set! freddie-prepayment-fit-read (spline-logistic (list (cons "incentive_bp" (vector -100.0 0.0 100.0 200.0)) (cons "loan_age" (vector 1.0 2.0 3.0 4.0))
                            (cons "loan_size_k" (vector 100.0 200.0 300.0 250.0)) (cons "credit_score" (vector 700.0 720.0 740.0 760.0)) (cons "current_ltv" (vector 50.0 60.0 70.0 80.0))
                            (cons "sato" (vector 0.0 0.1 0.2 0.3)) (cons "burnout" (vector 0.0 1.0 2.0 3.0)) (cons "investor" (vector 0.0 0.0 1.0 0.0))
                            (cons "second_home" (vector 0.0 1.0 0.0 0.0)) (cons "cash_out" (vector 1.0 0.0 0.0 0.0)) (cons "refinance" (vector 0.0 0.0 0.0 1.0))
                            (cons "winter" (vector 1.0 0.0 0.0 0.0)) (cons "summer" (vector 0.0 1.0 0.0 0.0))) (vector 0.01 0.02 0.05 0.2) 0))''')
        self.run_lisp("(deal-set-rate-model! deal (make-rate-model :sigma1 0.0 :sigma2 0.0)) (deal-run-paths! deal :paths 2)")
        flows = self.run_lisp("(deal-pricing-flows deal)")
        for name in ("POOL", "C"):
            paid = [np.array(v.items, dtype=float) for v in lisp_core.pairs_to_list(
                self.run_lisp('(hash-table-ref (path-run-flows (path-sets-base (deal-path-sets deal))) "%s")' % name))]
            expected = (np.array(self.run_lisp('(node-principal (get-node (deal-run-copy deal (deal-pricing-flows deal) #t) "%s"))' % name).items)
                        + np.array(self.run_lisp('(node-interest (get-node (deal-run-copy deal (deal-pricing-flows deal) #t) "%s"))' % name).items))
            np.testing.assert_allclose(paid[0], expected, rtol=1e-9)
        self.assertGreater(np.array(flows.cdr.cdr.cdr.car.items).sum(), 0.0)           # (the pricing flows have their losses)


if __name__ == "__main__":
    unittest.main()
