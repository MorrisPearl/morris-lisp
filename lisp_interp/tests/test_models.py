"""Models: regression, linear programming, the solver, day counts and cash flows, and the
template and column-engine libraries.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class TestDayCounts(LispTestCase):
    """day-count and year-fraction under each basis (lisp_finance.py)."""

    def test_30_360(self):
        self.assertShows('(day-count (date 2024 1 31) (date 2024 3 1) "30/360")', "31")
        self.assertShows('(day-count (date 2024 1 31) (date 2024 3 31) "30/360")', "60")
        self.assertShows('(day-count (date 2024 1 29) (date 2024 3 31) "30/360")', "62")     # the 31st stays
        self.assertShows('(day-count (date 2024 1 29) (date 2024 3 31) "30E/360")', "61")    # ...but not in 30E
        self.assertShows('(year-fraction (date 2024 1 15) (date 2024 7 15) "30/360")', "0.5")

    def test_actual_bases(self):
        self.assertShows('(day-count (date 2024 1 1) (date 2024 7 1) "ACT/360")', "182")
        self.assertShows("(year-fraction (date 2024 1 1) (date 2024 7 1) 'act/360)", "0.5055555555555555")
        self.assertShows('(year-fraction (date 2024 1 1) (date 2025 1 1) "ACT/365")', "1.0027397260273974")
        self.assertShows('(year-fraction (date 2024 1 1) (date 2025 1 1) "ACT/ACT")', "1.0")
        self.assertAlmostEqual(self.run_lisp('(year-fraction (date 2023 7 1) (date 2024 7 1) "ACT/ACT")'),
                               184 / 365 + 182 / 366)

    def test_vectors_of_dates(self):
        self.assertShows('(day-count (date 2024 1 1) (vector (date 2024 2 1) (date 2024 3 1)) "30/360")', "#(30 60)")

    def test_an_unknown_basis(self):
        self.assertLispError('(year-fraction (date 2024 1 1) (date 2024 7 1) "bus/252")',
                             "year-fraction: unknown day count basis \"bus/252\" -- use one of 30/360, 30E/360, "
                             "ACT/360, ACT/365, ACT/ACT")


class TestCashFlowMath(LispTestCase):
    """npv, irr, xnpv, xirr, payment, present-value, yield, duration,
    modified-duration, convexity, and bond-cashflows (lisp_finance.py)."""

    def value(self, src):
        return self.run_lisp(src)

    def test_npv_counts_the_first_cash_flow_as_now(self):
        self.assertAlmostEqual(self.value("(npv 0.1 (list -100 60 60))"), -100 + 60 / 1.1 + 60 / 1.21)
        self.assertAlmostEqual(self.value("(npv 0.1 #(-100 60 60))"), -100 + 60 / 1.1 + 60 / 1.21)

    def test_irr(self):
        rate = self.value("(irr (list -100 60 60))")
        self.assertAlmostEqual(rate, 0.1306623862918975, places=10)
        self.assertAlmostEqual(self.value("(npv %r (list -100 60 60))" % rate), 0, places=8)

    def test_irr_of_a_long_monthly_series(self):
        # a 30-year loan of 300,000 at 6.5%: the monthly irr of its cash flows is 6.5% / 12
        rate = self.value("(irr (cons -300000 (loop repeat 360 collect (payment (/ 0.065 12) 360 300000))))")
        self.assertAlmostEqual(rate, 0.065 / 12, places=10)

    def test_irr_with_no_answer(self):
        self.assertLispError("(irr (list 100 60))", "irr: no rate from -99% to 1000% a period gives a value of 0")

    def test_irr_between_given_rates(self):
        # -100, 230, -132 has two irrs, 10% and 20%; without low and high, the one nearer 0
        self.assertAlmostEqual(self.value("(irr (list -100 230 -132))"), 0.1, places=10)
        self.assertAlmostEqual(self.value("(irr (list -100 230 -132) 0.15 0.5)"), 0.2, places=10)

    def test_xnpv_and_xirr_match_excel(self):
        self.run_lisp("""(define dates (list (date 2008 1 1) (date 2008 3 1) (date 2008 10 30)
                                                (date 2009 2 15) (date 2009 4 1)))
                         (define flows (list -10000 2750 4250 3250 2750))""")
        self.assertAlmostEqual(self.value("(xnpv 0.09 dates flows)"), 2086.6476020315, places=6)
        self.assertAlmostEqual(self.value("(xirr dates flows)"), 0.373362535, places=8)
        self.assertLispError("(xirr (list (date 2008 1 1)) flows)", "xirr: there are 1 dates but 5 cash flows")

    def test_payment(self):
        self.assertAlmostEqual(self.value("(payment (/ 0.065 12) 360 300000)"), 1896.2040704789, places=8)
        self.assertShows("(payment 0 12 1200)", "100.0")
        self.assertLispError("(payment 0.01 0 1000)", "the number of periods must be more than 0")

    def test_a_bond(self):
        self.run_lisp("(define flows (bond-cashflows 0.06 5 2))")
        self.assertShows("flows", "#(3.0 3.0 3.0 3.0 3.0 3.0 3.0 3.0 3.0 103.0)")
        price = self.value("(present-value 0.05 2 flows)")
        self.assertAlmostEqual(price, 104.3760319655, places=8)
        self.assertAlmostEqual(self.value("(yield %r 2 flows)" % price), 0.05, places=10)
        self.assertAlmostEqual(self.value("(present-value 0.06 2 flows)"), 100, places=10)   # par, at the coupon

    def test_duration_and_convexity(self):
        self.run_lisp("(define flows (bond-cashflows 0.06 5 2))")
        # the same measures, straight from their definitions
        v = [1.025 ** -t for t in range(1, 11)]
        c = [3.0] * 9 + [103.0]
        price = sum(ci * vi for ci, vi in zip(c, v))
        macaulay = sum(t / 2 * ci * vi for t, ci, vi in zip(range(1, 11), c, v)) / price
        convexity = sum(t * (t + 1) * ci * vi for t, ci, vi in zip(range(1, 11), c, v)) / (price * 1.025 ** 2 * 4)
        self.assertAlmostEqual(self.value("(duration 0.05 2 flows)"), macaulay, places=10)
        self.assertAlmostEqual(self.value("(modified-duration 0.05 2 flows)"), macaulay / 1.025, places=10)
        self.assertAlmostEqual(self.value("(convexity 0.05 2 flows)"), convexity, places=10)

    def test_duration_predicts_a_small_price_change(self):
        self.run_lisp("(define flows (bond-cashflows 0.06 5 2))")
        p0 = self.value("(present-value 0.05 2 flows)")
        p1 = self.value("(present-value 0.0501 2 flows)")
        d = self.value("(modified-duration 0.05 2 flows)")
        cx = self.value("(convexity 0.05 2 flows)")
        self.assertAlmostEqual((p1 - p0) / p0, -d * 0.0001 + cx * 0.0001 ** 2 / 2, places=9)

    def test_bad_cash_flows(self):
        self.assertLispError("(npv 0.1 '())", "npv: there are no cash flows")
        self.assertLispError("(npv 0.1 (list 1 \"a\"))", 'npv: every cash flow must be a number, not "a"')
        self.assertLispError("(npv 0.1 (vector 1 nan))", "every cash flow must be a number, not nan")
        self.assertLispError("(bond-cashflows 0.05 1.3 2)", "whole number of periods")


class TestSolverLibrary(LispTestCase):
    """lib/solver.lsp: Ridders' method and Nelder-Mead."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "%s")' % os.path.join(LIB, "solver.lsp"))

    def test_ridders_finds_a_root(self):
        self.assertAlmostEqual(self.run_lisp("(ridders (lambda (x) (- (* x x) 2)) 0 2)"), 2 ** 0.5, places=10)
        self.assertLispError("(ridders (lambda (x) (+ (* x x) 1)) 0 2)", "no root is bracketed")

    def test_nelder_mead_finds_the_minimum_of_the_rosenbrock_function(self):
        self.run_lisp("""(define (rosenbrock p)
                           (let ((x (car p)) (y (car (cdr p))))
                             (+ (expt (- 1 x) 2) (* 100 (expt (- y (* x x)) 2)))))""")
        point, value = lisp_core.pairs_to_list(self.run_lisp("(nelder-mead rosenbrock (list -1.2 1.0))"))
        x, y = lisp_core.pairs_to_list(point)
        self.assertAlmostEqual(x, 1.0, places=6)
        self.assertAlmostEqual(y, 1.0, places=6)
        self.assertLess(value, 1e-12)

    def test_implied_volatility_round_trip(self):
        self.run_lisp('(define price (bsm-price "call" 100 105 0.5 0.04 0.25))')
        self.assertAlmostEqual(self.run_lisp('(implied-vol price "call" 100 105 0.5 0.04)'), 0.25, places=8)


class TestRegression(LispTestCase):

    def test_linear_fit_recovers_an_exact_line(self):
        self.run_lisp("(define m (linear-regression #(1 2 3 4 5) #(3 5 7 9 11)))")   # y = 2x + 1
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)
        self.assertAlmostEqual(self.run_lisp("(model-predict m 10)"), 21.0)
        self.assertShows("(model-kind m)", '"linear"')
        self.assertShows("(model? m)", "#t")

    def test_multiple_predictors(self):
        # y = 1 + 2*a + 3*b
        self.run_lisp("""
          (define a (vector 1 2 3 4 5 6))
          (define b (vector 2 1 4 3 6 5))
          (define y (vector-map (lambda (i) i) (vector 0 0 0 0 0 0)))
          (define ys (vectors-map (lambda (x1 x2 i) (+ 1 (* 2 x1) (* 3 x2))) (list a b)))
          (define m (linear-regression (list a b) ys))""")
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0, places=3)
        c = self.run_lisp("(model-coefficients m)")
        self.assertAlmostEqual(float(c.items[0]), 2.0, places=3)
        self.assertAlmostEqual(float(c.items[1]), 3.0, places=3)
        self.assertAlmostEqual(self.run_lisp("(model-predict m (list 10 10))"), 51.0, places=2)

    def test_weights_of_zero_exclude_an_observation(self):
        # the outlier at x=5 is weighted out, so the line through the rest is exact
        self.run_lisp("""
          (define m (linear-regression #(1 2 3 4 5) #(3 5 7 9 500) #(1 1 1 1 0)))""")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)

    def test_mismatched_lengths_are_an_error(self):
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(linear-regression #(1 2 3) #(1 2))")

    def test_constant_predictor_is_an_error(self):
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(linear-regression #(2 2 2 2) #(1 2 3 4))")

    def test_logistic_fit_is_monotonic_and_bounded(self):
        self.run_lisp("(define m (logistic-regression #(1 2 3 4 5 6 7 8) #(0 0 0 1 0 1 1 1)))")
        self.assertShows("(model-kind m)", '"logistic"')
        lo = self.run_lisp("(model-predict m 1)")
        hi = self.run_lisp("(model-predict m 8)")
        self.assertTrue(0.0 < lo < hi < 1.0)

    def test_logistic_rejects_y_outside_zero_one(self):
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(logistic-regression #(1 2 3 4) #(0 1 2 1))")

    def test_spline_fit_bends_where_a_line_cannot(self):
        # y = |x - 5| : a straight line fits this badly, a spline should not
        self.run_lisp("""
          (define xs (vector-iterate 0 11 (lambda (x) (+ x 1))))
          (define ys (vector-map (lambda (x) (abs (- x 5))) xs))
          (define line (linear-regression xs ys))
          (define spl (spline-regression xs ys (list 5)))""")
        line_err = abs(self.run_lisp("(model-predict line 0)") - 5)
        spline_err = abs(self.run_lisp("(model-predict spl 0)") - 5)
        self.assertLess(spline_err, line_err)
        self.assertLess(spline_err, 1e-3)
        self.assertShows("(model-kind spl)", '"spline"')

    def test_spline_models_refuse_flat_coefficient_accessors(self):
        self.run_lisp("(define spl (spline-regression (vector-iterate 0 11 (lambda (x) (+ x 1))) "
                      "(vector-map (lambda (x) (abs (- x 5))) (vector-iterate 0 11 (lambda (x) (+ x 1)))) (list 5)))")
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(model-slope spl)")

    def test_model_report_and_evaluate_run(self):
        self.run_lisp("(define m (linear-regression #(1 2 3 4 5) #(3 5 7 9 11)))")
        self.assertIn("linear", self.show("(model-report m)").lower())
        self.run_lisp("(model-evaluate m #(6 7) #(13 15))")

    def test_standard_errors_and_p_values(self):
        # Checked against statsmodels: OLS of (10 20 29 41 51) on (1 2 3 4 5).
        self.run_lisp("(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))")
        self.run_lisp("(define ct (model-coefficient-table m))")
        self.assertShows('(table-column ct "term")', '#("intercept" "x1")')
        std_errors = self.run_lisp('(table-column ct "std_error")').items.tolist()
        p_values = self.run_lisp('(table-column ct "p_value")').items.tolist()
        self.assertAlmostEqual(std_errors[0], 0.834666, places=5)
        self.assertAlmostEqual(std_errors[1], 0.251661, places=5)
        self.assertAlmostEqual(p_values[1] / 3.209778e-05, 1.0, places=5)     # statsmodels' value
        report = self.show("(model-report m)")
        self.assertIn("std error", report)
        self.assertIn("t value", report)

    def test_logistic_report_has_z_values_and_auc(self):
        self.run_lisp("(define m (logistic-regression #(1 2 3 4 5 6 7 8) #(0 0 1 0 0 1 1 1)))")
        self.assertIn("z value", self.show("(model-report m)"))
        self.assertIn("AUC", self.show("(model-report m)"))
        self.assertShows('(table-column-names (model-coefficient-table m))',
                         '("term" "coefficient" "std_error" "z_value" "p_value")')
        self.assertIn("AUC              = 0.875", self.show("(model-evaluate m #(1 2 3 4 5 6 7 8) #(0 0 1 0 0 1 1 1))"))

    def test_lift_table(self):
        self.run_lisp("(define m (logistic-regression #(1 2 3 4 5 6 7 8 9 10) #(0 0 1 0 0 1 0 1 1 1)))")
        self.run_lisp("(define lt (model-lift-table m #(1 2 3 4 5 6 7 8 9 10) #(0 0 1 0 0 1 0 1 1 1) 5))")
        self.assertShows('(table-column lt "rows")', "#(2 2 2 2 2)")
        self.assertShows('(table-column lt "mean_actual")', "#(1.0 0.5 0.5 0.5 0.0)")
        self.assertShows('(table-column lt "cumulative_share")', "#(0.4 0.6 0.8 1.0 1.0)")
        self.assertLispError("(model-lift-table m #(1 2) #(0 1) 5)", "bins must be")

    def test_spline_report_has_the_coefficient_table(self):
        self.run_lisp("(define spl (spline-regression (list (cons \"x\" (vector-range 11))) "
                      "(vector-map (lambda (x) (abs (- x 5))) (vector-range 11)) (list 5)))")
        self.assertIn("x (knot 5)", self.show("(model-report spl)"))
        self.assertShows('(table-column (model-coefficient-table spl) "term")', '#("intercept" "x" "x (knot 5)")')

    def test_train_test_split_helpers(self):
        self.assertShows("(vector-take #(1 2 3 4 5) 3)", "#(1 2 3)")
        self.assertShows("(vector-drop #(1 2 3 4 5) 3)", "#(4 5)")


class TestLadRegression(LispTestCase):
    """lad-regression: least absolute deviation, which a few outliers
    barely move."""

    def test_an_outlier_pulls_least_squares_but_not_lad(self):
        # y = 2x + 1, except at x = 10
        self.run_lisp("(define x #(1 2 3 4 5 6 7 8 9 10))"
                      "(define y #(3 5 7 9 11 13 15 17 19 100))"
                      "(define m (lad-regression x y))")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)
        self.assertGreater(self.run_lisp("(model-slope (linear-regression x y))"), 5)
        self.assertShows("(model-kind m)", '"lad"')
        self.assertShows("(model-residuals m x y)", "#(0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 79.0)")

    def test_the_fit_is_the_least_absolute_deviation_one(self):
        """Some best fit goes through p of the points, so the best of all the
        fits through p points is the answer: compare with that, for many
        small data sets, with ties, repeated x values, and weights."""
        import itertools
        import numpy as np
        import lisp_regression
        rng = np.random.default_rng(1)
        for trial in range(150):
            n, k = int(rng.integers(4, 15)), int(rng.integers(1, 3))
            columns = rng.normal(size=(k, n)) * 10
            if trial % 4 == 0:
                columns = np.round(columns / 5)                 # repeated x values
            X = np.column_stack([np.ones(n), columns.T])
            if np.linalg.matrix_rank(X) < k + 1 or np.any(columns.std(axis=1) == 0):
                continue
            y = X @ rng.normal(size=k + 1) + rng.standard_t(2, size=n)
            if trial % 3 == 0:
                y = np.round(y)                                 # ties
            w = rng.uniform(0.5, 3, n) if trial % 2 else np.ones(n)
            model = lisp_regression.fit_lad(columns.tolist(), y.tolist(), w.tolist())
            best = min(float((w * abs(y - X @ np.linalg.solve(X[list(rows)], y[list(rows)]))).sum())
                       for rows in itertools.combinations(range(n), k + 1)
                       if abs(np.linalg.det(X[list(rows)])) > 1e-9)
            with self.subTest(trial=trial):
                self.assertTrue(model.stats["converged"])
                self.assertAlmostEqual(model.stats["sum_abs_deviations"] / best, 1.0, places=9)

    def test_weights_count_rows_as_copies(self):
        self.run_lisp("(define x #(1 2 3 4 5 6))"
                      "(define y #(2 3 7 8 13 12))"
                      "(define weighted (lad-regression x y #(1 3 1 1 2 1)))"
                      "(define copied (lad-regression #(1 2 2 2 3 4 5 5 6) #(2 3 3 3 7 8 13 13 12)))")
        self.assertAlmostEqual(self.run_lisp("(model-slope weighted)"), self.run_lisp("(model-slope copied)"))
        self.assertAlmostEqual(self.run_lisp("(model-intercept weighted)"),
                               self.run_lisp("(model-intercept copied)"))
        # a weight of 0 leaves a row out
        self.run_lisp("(define m (lad-regression #(1 2 3 4 5) #(3 5 7 9 500) #(1 1 1 1 0)))")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)

    def test_several_predictors(self):
        # y = 1 + 2a - 3b, but for one outlier
        self.run_lisp("(define a #(1 2 3 4 5 6 7 8))"
                      "(define b #(2 1 4 3 6 5 8 9))"
                      "(define y (+ 1 (* 2 a) (* -3 b)))"
                      "(vector-set! y 3 50)"
                      "(define m (lad-regression (list a b) y))")
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)
        c = self.run_lisp("(model-coefficients m)").items.tolist()
        self.assertAlmostEqual(c[0], 2.0)
        self.assertAlmostEqual(c[1], -3.0)
        self.assertAlmostEqual(self.run_lisp("(model-predict m (list 10 10))"), -9.0)

    def test_the_report_and_standard_errors_ignore_how_far_out_the_outlier_is(self):
        def report(outlier):
            return self.show('(model-report (lad-regression (list (cons "month" #(1 2 3 4 5 6 7 8 9 10))) '
                             '(cons "cpr" #(3 5.5 6.5 9 11 13.5 14.5 17 19 %s))))' % outlier)
        near, far = report(60), report(600)
        self.assertIn("Least absolute deviation model:  cpr = ", near)
        self.assertIn("month", near)
        self.assertIn("sum |residuals|", near)
        self.assertIn("iterations       = ", near)
        std_error_lines = [line for line in near.splitlines() if line.startswith(("  intercept", "  month"))]
        self.assertEqual(std_error_lines,
                         [line for line in far.splitlines() if line.startswith(("  intercept", "  month"))])

    def test_standard_errors_are_undefined_for_an_exact_fit(self):
        self.run_lisp("(define m (lad-regression #(1 2 3) #(3 5 7)))")
        self.assertShows('(table-column (model-coefficient-table m) "std_error")', "#(nan nan)")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)

    def test_errors(self):
        self.assertLispError("(lad-regression #(1) #(1))", "too few to fit 2 coefficients")
        self.assertLispError("(lad-regression #(1 2 3) #(1 2))", "must be the same length")
        self.assertLispError("(lad-regression #(2 2 2) #(1 2 3))", "no variation")
        self.assertLispError("(lad-regression #(1 2 3) #(1 2 3) #(1 -1 1))", "must not be negative")

    def test_model_residuals_works_for_every_kind_of_model(self):
        self.run_lisp("(define m (linear-regression #(1 2 3) #(1 3 2)))")
        self.assertShows("(model-residuals m #(1 2 3) #(1 3 2))", "#(-0.5 1.0 -0.5)")
        self.assertLispError("(model-residuals m (list #(1 2) #(3 4)) #(1 2))", "model has 1 predictor(s), but 2 given")


class TestSplineLad(LispTestCase):
    """spline-lad: a piecewise-linear spline fit by least absolute deviation, as
    spline-regression fits one by least squares."""

    V = """(define xs (vector-range 21))
           (define ys (vector-map (lambda (x) (abs (- x 10))) xs))      ; a V, bending at 10
           (vector-set! ys 18 40)                                       ; and one outlier
        """

    def test_an_outlier_pulls_a_least_squares_spline_but_not_a_lad_one(self):
        self.run_lisp(self.V + "(define squares (spline-regression xs ys (list 10)))"
                               "(define lad (spline-lad xs ys (list 10)))")
        for x in (0, 5, 10, 15, 20):
            self.assertAlmostEqual(self.run_lisp("(model-predict lad %d)" % x), abs(x - 10), places=9)
        self.assertGreater(self.run_lisp("(model-predict squares 20)"), 15)
        self.assertShows("(model-kind lad)", '"spline-lad"')
        self.assertShows("(model-kind squares)", '"spline"')
        residuals = [float(r) for r in self.run_lisp("(model-residuals lad xs ys)").items]
        self.assertEqual([i for i, r in enumerate(residuals) if abs(r) > 1e-9], [18])

    def test_it_is_lad_regression_on_the_spline_s_hinges(self):
        # the model is lad-regression of y on x and max(0, x - knot), for each knot
        self.run_lisp(self.V + """
          (define hinge-7 (vector-map (lambda (x) (max 0 (- x 7))) xs))
          (define hinge-13 (vector-map (lambda (x) (max 0 (- x 13))) xs))
          (define weights (vector-map (lambda (x) (+ 1 (mod x 3))) xs))
          (define spline (spline-lad xs ys (list 7 13) weights))
          (define by-hand (lad-regression (list xs hinge-7 hinge-13) ys weights))""")
        for x in (0, 3.5, 7, 9, 13, 16, 20):
            self.assertAlmostEqual(self.run_lisp("(model-predict spline %s)" % x),
                                   self.run_lisp("(model-predict by-hand (list %s %s %s))"
                                                 % (x, max(0, x - 7), max(0, x - 13))), places=9)

    def test_knot_counts_categories_and_the_report(self):
        self.run_lisp("""
          (define x (cons "income" #(10 20 30 40 50 60 70 80 90 100)))
          (define kind (cons "kind" (vector "own" "rent" "own" "rent" "own" "rent" "own" "rent" "own" "rent")))
          (define y (cons "spend" #(9 15 33 38 52 58 74 77 300 95)))
          (define m (spline-lad (list x kind) y (list 2 'categorical)))""")
        report = self.show("(model-report m)")
        self.assertIn("Piecewise-linear spline model, fit by least absolute deviation, predicting spend:", report)
        self.assertIn("kind: categorical -- categories own, rent (baseline own)", report)
        self.assertIn("sum |residuals|", report)
        terms = [str(t) for t in self.run_lisp('(table-column (model-coefficient-table m) "term")').items]
        self.assertEqual(terms[:2], ["intercept", "income"])
        self.assertEqual(terms[-1], "kind = rent")
        self.assertEqual(len(terms), 5)                          # and two knots for income
        self.run_lisp('(model-evaluate m (list x kind) y)')
        self.assertLispError('(model-predict m (list 45 "lease"))', "kind value 'lease' was not one of the categories")

    def test_errors_name_spline_lad(self):
        self.assertLispError("(spline-lad #(1 2 3) #(1 2))", "all vectors must be the same length")
        self.assertLispError("(spline-lad #(1 2 1 2 1) #(1 2 3 4 5) 1)", "spline-lad: x1 has only 2 distinct value(s)")
        self.assertLispError("(spline-lad #(1 2 3 4 5) #(1 2 3 4 5) -1)", "spline-lad: knot counts must not be negative")
        self.assertLispError("(spline-lad (list #(1 2 3 4 5) #(5 1 4 2 3)) #(1 2 3 4 5) (list 1))",
                             "spline-lad: the knot-spec list must have one entry per predictor (2), got 1")


class TestLogisticFloorAndCeiling(LispTestCase):
    """logistic-regression and spline-logistic with :floor and :ceiling: a curve from the floor to the
    ceiling, in place of from 0 to 1. Between 0 and 1, it's a probability, fit as one; outside them, a
    number, fit by rescaling it."""

    CURVE = """(define x (- (/ (vector-range 41) 8.0) 2))
               (define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))
            """          # 0.03 + 0.45 * sigmoid(-3 + 3x): from 3% to 48%

    def test_a_floor_and_ceiling_find_the_curve_the_data_was_made_from(self):
        self.run_lisp(self.CURVE + "(define m (logistic-regression x y :floor 0.03 :ceiling 0.48))")
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), -3.0, places=5)
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 3.0, places=5)
        self.assertAlmostEqual(self.run_lisp("(model-predict m 10)"), 0.48, places=6)
        self.assertAlmostEqual(self.run_lisp("(model-predict m -10)"), 0.03, places=6)
        self.assertShows("m", "#<logistic-model slope=3 intercept=-3 floor=0.03 ceiling=0.48>")
        report = self.show("(model-report m)")
        self.assertIn("Logistic model, between 0.03 and 0.48:  p(y) = 0.03 + 0.45 * sigmoid(-3 + 3*x1)", report)
        self.assertIn("floor, ceiling   = 0.03, 0.48  (the probability is between them)", report)
        self.assertIn("AUC", self.show("(model-evaluate m x y)"))   # a probability, between 0.03 and 0.48
        self.assertShows("(model-kind (logistic-regression x y))", '"logistic"')

    def test_a_floor_and_ceiling_of_0_and_1_are_the_usual_fit(self):
        self.run_lisp(self.CURVE + "(define usual (logistic-regression x y))"
                                   "(define given (logistic-regression x y :floor 0 :ceiling 1))")
        self.assertEqual(self.show("(model-coefficients given)"), self.show("(model-coefficients usual)"))
        self.assertEqual(self.show("(model-report given)"), self.show("(model-report usual)"))

    def test_the_probability_of_a_0_or_1_outcome_between_a_floor_and_ceiling(self):
        # 20,000 loans, each prepaid or not, with a chance from 3% to 48%: the fit finds that curve, where
        # rescaling 0 and 1 between the floor and ceiling (and clipping them back) would just fit 0s and 1s
        rng = np.random.default_rng(1)
        x = rng.uniform(-2, 3, 20000)
        chance = 0.03 + 0.45 / (1 + np.exp(-3 * (x - 1)))
        self.env[lisp_core.Symbol("x")] = lisp_vector_math.to_vector(x)
        self.env[lisp_core.Symbol("prepaid")] = lisp_vector_math.to_vector((rng.uniform(size=len(x)) < chance) * 1.0)
        self.run_lisp("(define m (logistic-regression x prepaid :floor 0.03 :ceiling 0.48))")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 3.0, delta=0.3)
        for v in (-2, 0, 1, 2, 3):
            self.assertAlmostEqual(self.run_lisp("(model-predict m %s)" % v),
                                   0.03 + 0.45 / (1 + math.exp(-3 * (v - 1))), delta=0.01, msg=v)
        self.assertGreater(self.run_lisp("(model-predict (logistic-regression x prepaid) 3)"), 0.55)  # (it overshoots)
        # and it's the most likely curve: moving the intercept or slope either way makes the outcomes less likely
        outcomes = np.array(self.run_lisp("prepaid").items, dtype=np.float64)
        model = self.run_lisp("m")

        def log_likelihood(intercept, slope):
            p = 0.03 + 0.45 / (1 + np.exp(-(intercept + slope * x)))
            return float((outcomes * np.log(p) + (1 - outcomes) * np.log(1 - p)).sum())

        best = log_likelihood(model.intercept, model.coefficients[0])
        for d_intercept, d_slope in ((0.02, 0), (-0.02, 0), (0, 0.02), (0, -0.02)):
            self.assertLess(log_likelihood(model.intercept + d_intercept, model.coefficients[0] + d_slope), best)

    def test_a_number_that_isn_t_a_probability_is_rescaled(self):
        # in percent: from 3 to 48, rescaled to (y - 3) / 45
        self.run_lisp(self.CURVE + """
          (define percent (* 100 y))
          (define m (logistic-regression x percent :floor 3 :ceiling 48))""")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 3.0, places=5)
        self.assertAlmostEqual(self.run_lisp("(model-predict m 1)"), 25.5, places=5)
        report = self.show("(model-report m)")
        self.assertIn("Logistic model, between 3 and 48:  y = 3 + 45 * sigmoid(-3 + 3*x1)", report)
        self.assertIn("(the measures below are of y rescaled to (y - floor) / (ceiling - floor))", report)
        evaluation = self.show("(model-evaluate m x percent)")      # a number between them, not a probability
        self.assertIn("R-squared = 1", evaluation)
        self.assertNotIn("AUC", evaluation)

    def test_a_number_beyond_the_floor_or_ceiling_is_taken_as_at_it(self):
        self.run_lisp(self.CURVE + """
          (define percent (* 100 y))
          (vector-set! percent 0 1) (vector-set! percent 1 0)            ; below the floor
          (vector-set! percent 39 50) (vector-set! percent 40 60)        ; above the ceiling
          (define m (logistic-regression x percent :floor 3 :ceiling 48))
          (define clipped (vector-map (lambda (v) (min 48 (max 3 v))) percent))
          (define by-hand (logistic-regression x clipped :floor 3 :ceiling 48))""")
        self.assertIn("(2 y below the floor, and 2 above the ceiling, taken as at them)", self.show("(model-report m)"))
        for v in (-2, 0, 1, 2.5):            # (to the fit's own tolerance)
            self.assertAlmostEqual(self.run_lisp("(model-predict m %s)" % v),
                                   self.run_lisp("(model-predict by-hand %s)" % v), places=5)

    def test_one_of_them_can_be_left_out_and_weights_still_come_first(self):
        self.run_lisp(self.CURVE + """
          (define m (logistic-regression x y :ceiling 0.5))
          (define weights (vector-map (lambda (v) (if (> v 2.9) 0 1)) x))   ; the last point left out
          (define weighted (logistic-regression x y weights :floor 0.03 :ceiling 0.48))
          (define without (logistic-regression (vector-take x 40) (vector-take y 40) :floor 0.03 :ceiling 0.48))""")
        self.assertIn("Logistic model, between 0 and 0.5:", self.show("(model-report m)"))
        self.assertAlmostEqual(self.run_lisp("(model-predict weighted 0.5)"),
                               self.run_lisp("(model-predict without 0.5)"), places=9)

    def test_what_the_options_won_t_take(self):
        self.run_lisp(self.CURVE)
        self.assertLispError("(logistic-regression x (* 3 y))", "every y must be between 0 and 1, as a probability is")
        self.assertLispError("(logistic-regression x (* 3 y) :ceiling 0.9)",
                             "or give the curve a :floor or :ceiling outside 0 and 1, for a number that isn't one")
        self.assertLispError("(logistic-regression x y :floor 0.5 :ceiling 0.4)",
                             "the :floor (0.5) must be below the :ceiling (0.4)")
        self.assertLispError('(logistic-regression x y :floor "low")', ":floor must be a number")
        self.assertLispError("(logistic-regression x y :cap 0.5)", ":cap")
        self.assertLispError("(logistic-regression x y '() '() :floor 0.1)",
                             "expected at most 1 argument(s) after x and y, before the keyword options, not 2")

    def test_spline_logistic_is_logistic_regression_on_the_hinges(self):
        self.run_lisp(self.CURVE + """
          (define hinge (vector-map (lambda (v) (max 0 (- v 1.5))) x))
          (define spline (spline-logistic x y (list 1.5) :floor 0.03 :ceiling 0.48))
          (define by-hand (logistic-regression (list x hinge) y :floor 0.03 :ceiling 0.48))
          (define plain (spline-logistic x (* 2 y) (list 1.5)))""")       # (2y is between 0 and 0.96)
        for v in (-2, 0, 1.5, 2, 3):
            self.assertAlmostEqual(self.run_lisp("(model-predict spline %s)" % v),
                                   self.run_lisp("(model-predict by-hand (list %s %s))" % (v, max(0, v - 1.5))),
                                   places=9)
        self.assertShows("(model-kind spline)", '"spline-logistic"')
        self.assertShows("(model-kind plain)", '"spline-logistic"')
        self.assertIn("Piecewise-linear spline model, with a logistic link between 0.03 and 0.48, predicting y:",
                      self.show("(model-report spline)"))
        self.assertIn("Piecewise-linear spline model, with a logistic link, predicting y:",
                      self.show("(model-report plain)"))
        self.assertLispError("(spline-logistic x (* 3 y) (list 1.5))", "spline-logistic: every y must be between 0 and 1")
        self.assertLispError("(spline-regression x y 3 #t)", "spline-logistic fits a spline with a logistic link")


class TestLinearProgramming(LispTestCase):
    """lp-read-file and lp-solve (lisp_simplex.py, using simplex/simplex_solver.py)."""

    EXAMPLE_FILE = os.path.join(HERE, "..", "simplex", "example_problem.txt")

    def write_problem_file(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "problem.txt")
        with open(path, "w") as f:
            f.write(text)
        return path.replace("\\", "/")

    def test_read_the_example_file(self):
        self.run_lisp('(define problem (lp-read-file "%s"))' % self.EXAMPLE_FILE.replace("\\", "/"))
        self.assertShows("problem",
                         '(("objective" -3.0 -5.0) ("constraints" (1.0 0.0) (0.0 2.0) (3.0 2.0)) '
                         '("relations" "<=" "<=" "<=") ("rhs" 4.0 12.0 18.0) '
                         '("variables" "x1" "x2") ("goal" "minimize"))')

    def test_solve_the_example_file(self):
        self.run_lisp('(define result (lp-solve (lp-read-file "%s")))' % self.EXAMPLE_FILE.replace("\\", "/"))
        self.assertShows('(cdr (assoc "solution" result))', "(2.0 6.0)")
        self.assertShows('(cdr (assoc "optimal-value" result))', "-36.0")

    def test_read_skips_comments_and_blank_lines_and_handles_every_relation(self):
        path = self.write_problem_file("# a comment\n\nminimize\n2 3\n\nsubject to\n1 1 = 10\n"
                                       "1 0 <= 6\n0 1 >= 1\n")
        self.assertShows('(cdr (assoc "relations" (lp-read-file "%s")))' % path, '("=" "<=" ">=")')
        self.assertShows('(lp-solve (lp-read-file "%s"))' % path,
                         '(("solution" 6.0 4.0) ("optimal-value" . 24.0))')

    def test_read_errors_say_what_is_wrong(self):
        self.assertLispError('(lp-read-file "/definitely/not/here.txt")', "No such file")
        path = self.write_problem_file("optimize\n1 2\nsubject to\n1 1 <= 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "must start with a 'minimize' or 'maximize' line")
        path = self.write_problem_file("minimize\n1 2\nsubject to\n1 <= 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "expected 2")
        path = self.write_problem_file("minimize\n1 2\nsubject to\n1 1 < 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "Unrecognized relation")

    NAMED_FILE = """
        # Maximize 3x1 + 5x2
        maximize
        3 x1 + 5 x2
        subject to
        x1 <= 4
        2 x2 <= 12
        3 x1 + 2 x2 <= 18
    """

    def test_read_a_file_with_variable_names(self):
        path = self.write_problem_file(self.NAMED_FILE)
        self.assertShows('(lp-read-file "%s")' % path,
                         '(("objective" 3.0 5.0) ("constraints" (1.0 0.0) (0.0 2.0) (3.0 2.0)) '
                         '("relations" "<=" "<=" "<=") ("rhs" 4.0 12.0 18.0) '
                         '("variables" "x1" "x2") ("goal" "maximize"))')

    def test_a_maximize_problem_gives_the_maximum(self):
        path = self.write_problem_file(self.NAMED_FILE)
        self.assertShows('(lp-solve (lp-read-file "%s"))' % path,
                         '(("solution" 2.0 6.0) ("optimal-value" . 36.0))')

    def test_maximize_and_negated_minimize_agree(self):
        # Maximizing 3x1 + 5x2, and minimizing -3x1 - 5x2 in the coefficients-only form.
        self.assertShows('(cdr (assoc "solution" (lp-solve (lp-read-file "%s"))))'
                         % self.write_problem_file(self.NAMED_FILE), "(2.0 6.0)")
        self.assertShows('(cdr (assoc "solution" (lp-solve (lp-read-file "%s"))))'
                         % self.EXAMPLE_FILE.replace("\\", "/"), "(2.0 6.0)")

    def test_variables_are_numbered_in_order_of_first_appearance(self):
        # z appears in a constraint but not the objective; it costs nothing (coefficient 0).
        path = self.write_problem_file("minimize\nb + a\nsubject to\na + z >= 3\nz <= 2\nb >= 1\n")
        self.assertShows('(cdr (assoc "variables" (lp-read-file "%s")))' % path, '("b" "a" "z")')
        self.assertShows('(cdr (assoc "objective" (lp-read-file "%s")))' % path, "(1.0 1.0 0.0)")
        self.assertShows('(cdr (assoc "constraints" (lp-read-file "%s")))' % path,
                         "((0.0 1.0 1.0) (0.0 0.0 1.0) (1.0 0.0 0.0))")

    def test_a_name_used_twice_in_a_formula_has_its_coefficients_added(self):
        path = self.write_problem_file("minimize\nx + x + y\nsubject to\nx + y >= 3\ny <= 5\n")
        self.assertShows('(cdr (assoc "objective" (lp-read-file "%s")))' % path, "(2.0 1.0)")

    def test_a_formula_can_start_with_a_sign_and_use_minus(self):
        path = self.write_problem_file("minimize\n- x + 2 y\nsubject to\nx <= 3\ny >= 1\n")
        self.assertShows('(lp-solve (lp-read-file "%s"))' % path,
                         '(("solution" 3.0 1.0) ("optimal-value" . -1.0))')

    def test_names_can_have_underscores_and_digits_and_are_case_sensitive(self):
        path = self.write_problem_file("minimize\ngnma_30 + GNMA_30 + _x2\nsubject to\n"
                                       "gnma_30 + GNMA_30 + _x2 >= 1\n")
        self.assertShows('(cdr (assoc "variables" (lp-read-file "%s")))' % path, '("gnma_30" "GNMA_30" "_x2")')

    def test_the_header_words_are_not_case_sensitive(self):
        path = self.write_problem_file("MAXIMIZE\n2 x\nSubject To\nx <= 4\n")
        self.assertShows('(cdr (assoc "optimal-value" (lp-solve (lp-read-file "%s"))))' % path, "8.0")

    def test_named_file_errors_say_what_is_wrong(self):
        head = "maximize\n3 x + 5 y\nsubject to\n"
        cases = [
            (head + "3x + 2 y <= 4\n", "'3x' is not a number or a variable name"),
            (head + "x+y <= 4\n", "'x+y' is not a number or a variable name"),
            (head + "x y <= 4\n", "Expected + or - after 'x', but found 'y'"),
            (head + "3 + 2 y <= 4\n", "Expected a variable name"),
            (head + "3 x + <= 4\n", "Expected a variable name"),
            (head + "x + y < 4\n", "Unrecognized relation '<'"),
            (head + "x + y <= many\n", "'many' is not a number"),
            (head + "x <=\n", "A constraint needs a left-hand side"),
            ("maximize\n3 x\nsubject to\n", "No constraints were found"),
            ("maximize\nsubject to\nx <= 4\n", "Expected the objective"),
            ("maximize\n3 x\nx <= 4\n", "Expected a 'subject to' line"),
            ("minimize\n1 2\nsubject to\nx + y <= 4\n", "the objective has no variable names"),
        ]
        for text, message in cases:
            with self.subTest(text=text):
                self.assertLispError('(lp-read-file "%s")' % self.write_problem_file(text), message)

    def test_a_problem_built_in_lisp_can_say_maximize_by_string_or_symbol(self):
        for goal in ['"maximize"', "maximize"]:
            with self.subTest(goal=goal):
                self.assertShows("""(lp-solve '(("objective" 3 5) ("constraints" (1 0) (0 2) (3 2))
                                                ("relations" <= <= <=) ("rhs" 4 12 18) ("goal" %s)))""" % goal,
                                 '(("solution" 2.0 6.0) ("optimal-value" . 36.0))')

    def test_a_problem_with_no_goal_is_minimized(self):
        self.assertShows("""(lp-solve '(("objective" 1 1) ("constraints" (1 2) (3 1))
                                        ("relations" >= >=) ("rhs" 4 6)))""",
                         '(("solution" 1.6 1.2) ("optimal-value" . 2.8))')

    def test_a_bad_goal_or_variables_list_is_an_error(self):
        base = '("objective" 1 1) ("constraints" (1 1)) ("relations" <=) ("rhs" 4)'
        self.assertLispError("(lp-solve '(%s (\"goal\" \"largest\")))" % base, '"goal" must be "minimize" or "maximize"')
        self.assertLispError("(lp-solve '(%s (\"goal\")))" % base, '"goal" must be "minimize" or "maximize"')
        self.assertLispError("(lp-solve '(%s (\"variables\" \"x\")))" % base,
                             '"variables" has 1 names, but the objective has 2 coefficients')

    def test_the_default_iteration_limit_is_three_times_the_number_of_variables(self):
        # Beale's example makes this solver cycle forever. It has 4 variables and 3 constraints,
        # each of which adds a slack variable: 7 in all, so the default limit is 21.
        beale = """'(("objective" -0.75 20 -0.5 6)
                      ("constraints" (0.25 -8 -1 9) (0.5 -12 -0.5 3) (0 0 1 0))
                      ("relations" <= <= <=) ("rhs" 0 0 1))"""
        self.assertLispError("(lp-solve %s)" % beale, "did not converge within 21 iterations")
        self.assertLispError("(lp-solve %s 50)" % beale, "did not converge within 50 iterations")

    def test_slack_surplus_and_artificial_variables_count_toward_the_default_limit(self):
        # The same cycling problem, plus all-zero rows, which don't change the pivoting but do
        # add columns. ">=" adds a surplus and an artificial variable, and "=" an artificial one.
        def beale_with(extra_relations):
            rows = "".join(" (0 0 0 0)" for _ in extra_relations)
            return """'(("objective" -0.75 20 -0.5 6)
                        ("constraints" (0.25 -8 -1 9) (0.5 -12 -0.5 3) (0 0 1 0)%s)
                        ("relations" <= <= <= %s) ("rhs" 0 0 1%s))""" % (
                rows, " ".join(extra_relations), " 0" * len(extra_relations))
        # 4 variables + 3 slack = 7, so 21
        self.assertLispError("(lp-solve %s)" % beale_with([]), "within 21 iterations")
        # + 1 surplus + 1 artificial = 9, so 27
        self.assertLispError("(lp-solve %s)" % beale_with([">="]), "within 27 iterations")
        # + 1 artificial = 8, so 24
        self.assertLispError("(lp-solve %s)" % beale_with(["="]), "within 24 iterations")
        # 4 + 3 + 1 surplus + 2 artificial = 10, so 30
        self.assertLispError("(lp-solve %s)" % beale_with([">=", "="]), "within 30 iterations")

    def test_max_iterations_can_be_given_and_must_be_a_positive_whole_number(self):
        self.assertLispError("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                            ("relations" <= <= <=) ("rhs" 4 12 18)) 1)""",
                             "did not converge within 1 iterations")
        self.assertShows("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                        ("relations" <= <= <=) ("rhs" 4 12 18)) 10)""",
                         '(("solution" 2.0 6.0) ("optimal-value" . -36.0))')
        self.assertShows("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                        ("relations" <= <= <=) ("rhs" 4 12 18)) '())""",
                         '(("solution" 2.0 6.0) ("optimal-value" . -36.0))')
        for bad in ["0", "-3", "2.5", '"many"', "#t"]:
            with self.subTest(max_iterations=bad):
                self.assertLispError("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                                    ("relations" <= <= <=) ("rhs" 4 12 18)) %s)""" % bad,
                                     "max-iterations must be a whole number of at least 1")

    def test_solve_a_problem_built_in_lisp(self):
        self.assertShows("""(lp-solve (list (cons "objective" (list 1 1))
                                            (cons "constraints" (list (list 1 2) (list 3 1)))
                                            (cons "relations" (list ">=" ">="))
                                            (cons "rhs" (list 4 6))))""",
                         '(("solution" 1.6 1.2) ("optimal-value" . 2.8))')

    def test_relations_can_be_symbols_in_a_quoted_problem(self):
        self.assertShows("""(lp-solve '(("objective" 2 3) ("constraints" (1 1) (1 0))
                                        ("relations" = <=) ("rhs" 10 6)))""",
                         '(("solution" 6.0 4.0) ("optimal-value" . 24.0))')

    def test_infeasible_and_unbounded_problems_are_errors(self):
        self.assertLispError("""(lp-solve '(("objective" 1) ("constraints" (1) (1))
                                            ("relations" <= >=) ("rhs" 1 2)))""", "infeasible")
        self.assertLispError("""(lp-solve '(("objective" -1) ("constraints" (1))
                                            ("relations" >=) ("rhs" 1)))""", "unbounded")

    def test_malformed_problems_are_errors(self):
        cases = [
            ("""'(("objective" 1 1) ("constraints" (1 2)) ("relations" <=))""", 'no "rhs" list'),
            ("""'(("objective" 1 1) ("constraints" (1)) ("relations" <=) ("rhs" 4))""",
             "a constraint has 1 coefficients, but the objective has 2"),
            ("""'(("objective" 1 1) ("constraints" (1 1) (1 0)) ("relations" <=) ("rhs" 4))""",
             "2 constraints, 1 relations, and 1 rhs values"),
            ("""'(("objective" 1 1) ("constraints" (1 1)) ("relations" <) ("rhs" 4))""",
             'a relation must be "<=", ">=", or "="'),
            ("""'(("objective" 1 "a") ("constraints" (1 1)) ("relations" <=) ("rhs" 4))""",
             '"objective" must hold only numbers, but it has "a"'),
            ("""'(("objective" 1 1) ("constraints" 5) ("relations" <=) ("rhs" 4))""",
             '"constraints" must be a list, not 5'),
            ("""'(("objective") ("constraints" (1)) ("relations" <=) ("rhs" 4))""", '"objective" is empty'),
        ]
        for problem, message in cases:
            with self.subTest(problem=problem):
                self.assertLispError("(lp-solve %s)" % problem, message)

    def test_costs_and_balances_in_the_millions(self):
        # Costs above a million once looked infeasible (the Big-M method with M = 1e6).
        self.assertShows("""(lp-solve '(("objective" 5000000) ("constraints" (1)) ("relations" >=) ("rhs" 1)))""",
                         '(("solution" 1.0) ("optimal-value" . 5000000.0))')
        # Rates on balances in the hundreds of millions.
        self.assertShows("""(lp-solve '(("objective" 0.065 0.07) ("constraints" (1 1) (1 0))
                                        ("relations" >= <=) ("rhs" 250000000 100000000)))""",
                         '(("solution" 100000000.0 150000000.0) ("optimal-value" . 17000000.0))')
        # Costs in the hundreds of millions, where rounding once made a solvable problem look unbounded.
        self.assertShows("""(round (cdr (assoc "optimal-value"
                                (lp-solve '(("objective" 300000000 -100000000 700000000 -400000000)
                                            ("constraints" (-3 3 -1 2) (0 -2 4 2) (-2 6 6 2) (-2 0 6 2))
                                            ("relations" <= <= >= <=)
                                            ("rhs" 1 18 20 4))))))""",
                         "-1900000000")

    def test_small_fractional_costs(self):
        self.assertShows("""(lp-solve '(("objective" 0.001 0.002) ("constraints" (1 1) (1 0))
                                        ("relations" >= >=) ("rhs" 3 0.5)))""",
                         '(("solution" 3.0 0.0) ("optimal-value" . 0.003))')

    def test_an_infeasible_problem_is_not_called_unbounded(self):
        # 0 * x1 = 20 can't hold; the old solver reported "unbounded".
        self.assertLispError("""(lp-solve '(("objective" -1) ("constraints" (2) (0))
                                            ("relations" >= =) ("rhs" 1 20)))""", "infeasible")

    def test_solving_does_not_change_the_problem(self):
        self.run_lisp("""(define problem (list (cons "objective" (list 1 1))
                                                (cons "constraints" (list (list 1 1)))
                                                (cons "relations" (list ">="))
                                                (cons "rhs" (list -4))))""")
        self.run_lisp("(lp-solve problem)")      # a negative rhs makes the solver flip the row
        self.assertShows("problem", '(("objective" 1 1) ("constraints" (1 1)) ("relations" ">=") ("rhs" -4))')


class TestTemplateLibrary(LispTestCase):
    """template.lsp: text templating plus a SQL mode that can only ever
    produce bound parameters, never spliced-in text."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "%s")' % os.path.join(LIB, "template.lsp"))

    def test_variable_substitution(self):
        self.assertShows('(template-render "Hello, {{name}}! {{count}} new{{s}}." '
                         '(template-bindings (name "Ada") (count 3) (s "!")))',
                         '"Hello, Ada! 3 new!."')

    def test_each_loop_with_separator(self):
        self.assertShows('(template-render "[{{#each x in xs sep comma}}{{x}}{{/each}}]" '
                         '(template-bindings (xs (list 1 2 3)) (comma ", ")))',
                         '"[1, 2, 3]"')

    def test_if_else(self):
        tpl = '"{{#if flag}}yes{{else}}no{{/if}}"'
        self.assertShows("(template-render %s (template-bindings (flag #t)))" % tpl, '"yes"')
        self.assertShows("(template-render %s (template-bindings (flag #f)))" % tpl, '"no"')

    def test_if_on_a_missing_binding_is_false(self):
        self.assertShows('(template-render "{{#if maybe}}yes{{else}}no{{/if}}" (template-bindings))', '"no"')

    def test_nested_loops(self):
        self.assertShows('(template-render "{{#each r in rows}}<{{#each c in r}}{{c}}{{/each}}>{{/each}}" '
                         '(template-bindings (rows (list (list 1 2) (list 3 4)))))',
                         '"<12><34>"')

    def test_sql_mode_turns_every_placeholder_into_a_question_mark(self):
        self.assertShows('(template-render-sql "SELECT * FROM loans WHERE state = {{state}} AND balance > {{min}}" '
                         '(template-bindings (state "CA") (min 100000)))',
                         '("SELECT * FROM loans WHERE state = ? AND balance > ?" "CA" 100000)')

    def test_sql_mode_in_list(self):
        self.assertShows('(template-render-sql "id IN ({{#each x in ids sep comma}}{{x}}{{/each}})" '
                         '(template-bindings (ids (list 1 2 3)) (comma ", ")))',
                         '("id IN (?, ?, ?)" 1 2 3)')

    def test_hostile_value_can_never_reach_the_sql_text(self):
        hostile = "x'; DROP TABLE t; --"
        rendered = self.run_lisp('(template-render-sql "SELECT * FROM t WHERE name = {{n}}" '
                                 '(template-bindings (n "%s")))' % hostile)
        sql, params = lisp_core.to_display_string(rendered.car), lisp_core.to_string(rendered.cdr)
        self.assertEqual(sql, "SELECT * FROM t WHERE name = ?")
        self.assertNotIn("DROP", sql)
        self.assertIn("DROP", params)

    def test_sqlite_query_template_end_to_end_with_a_hostile_value(self):
        self.run_lisp("""
          (define conn (sqlite-open ":memory:"))
          (sqlite-execute conn "CREATE TABLE t (name TEXT)")
          (sqlite-execute conn "INSERT INTO t VALUES ('safe')")
          (define r (sqlite-query-template conn "SELECT name FROM t WHERE name = {{n}}"
                      (template-bindings (n "safe' OR '1'='1"))))""")
        # the injection attempt matches nothing (a real injection would return 'safe')
        self.assertShows("(vector-length (cdr (car r)))", "0")

    def test_format_spec_in_a_tag(self):
        self.assertShows('(template-render "{{state:<6}}{{upb:>15,.2f}}{{wac:>8.3f}}" '
                         '(template-bindings (state "CA") (upb 1234567.5) (wac 6.25)))',
                         '"CA       1,234,567.50   6.250"')

    def test_format_spec_inside_an_each_loop(self):
        self.assertShows('(template-render "{{#each x in xs}}[{{x:^7,}}]{{/each}}" '
                         '(template-bindings (xs (list 1000 25))))',
                         '"[ 1,000 ][  25   ]"')

    def test_spaces_around_the_name_are_ignored(self):
        self.assertShows('(template-render "{{ n :>4}}|" (template-bindings (n 5)))', '"   5|"')

    def test_a_bad_format_spec_in_a_tag_is_an_error(self):
        self.assertLispError('(template-render "{{x:.2f}}" (template-bindings (x "CA")))', "isn't a number")

    def test_sql_mode_rejects_a_format_spec(self):
        self.assertLispError('(template-render-sql "WHERE a = {{a:.2f}}" (template-bindings (a 5)))',
                             "{{a:.2f}}")

    def test_parse_once_render_many_times(self):
        self.run_lisp('(define parsed (template-parse "n={{n}}"))')
        self.assertShows("(template-render parsed (template-bindings (n 1)))", '"n=1"')
        self.assertShows("(template-render parsed (template-bindings (n 2)))", '"n=2"')


class TestColumnEngineLibrary(LispTestCase):
    """column_engine.lsp: a small defstruct/&key-based row-by-row calculator.

    Each column's declared :name (e.g. "period") becomes a real global
    variable while calculate-all runs -- so it must differ from the Lisp
    variable holding the column struct itself (period-col), or the struct
    would be overwritten by the row value. (column_engine.lsp's header
    documents this caveat.)"""

    def setUp(self):
        lisp_core.set_verbose_level(0)
        self.tables = []
        self.out = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, table=self.tables.append)
        self.run_lisp('(load "%s")' % os.path.join(LIB, "column_engine.lsp"))

    def test_columns_chain_and_lag_across_rows(self):
        self.run_lisp("""
          (defcolumn period-col :name "period" :initial_value 0 :value_calculation (+ period 1))
          (defcolumn double-col :name "double" :initial_value 0 :value_calculation (* 2 period))
          (defcolumn running-col :name "running" :initial_value 0
                     :value_calculation (+ (lag running 1) double))
          (calculate-all *columns* 5)""")
        self.assertShows("(column-series period-col)", "#(0 1 2 3 4)")
        self.assertShows("(column-series double-col)", "#(0 2 4 6 8)")
        self.assertShows("(column-series running-col)", "#(0 2 6 12 20)")

    def test_display_table_receives_only_the_visible_columns(self):
        self.run_lisp("""
          (defcolumn a-col :name "a" :initial_value 1 :value_calculation (+ a 1))
          (defcolumn hidden-col :name "hidden" :initial_value 0 :visible #f
                     :value_calculation (+ hidden 1))
          (calculate-all *columns* 3)""")
        self.assertEqual(len(self.tables), 1)
        self.assertEqual(self.tables[0], [("a", ["1", "2", "3"], "right")])     # decimals 0, with commas

    def test_lag_default_before_the_first_row(self):
        self.run_lisp("""
          (defcolumn n-col :name "n" :initial_value 1 :value_calculation (+ (lag n 1) 1))
          (defcolumn back-col :name "back" :initial_value 0 :after n-col
                     :value_calculation (lag n 2 -1))
          (calculate-all *columns* 4)""")
        self.assertShows("(column-series back-col)", "#(0 -1 1 2)")

    def test_lag_without_a_default_before_the_first_row_is_an_error(self):
        self.run_lisp("""
          (defcolumn n-col :name "n" :initial_value 1 :value_calculation (+ (lag n 1) 1))
          (defcolumn bad-col :name "bad" :initial_value 0 :after n-col :value_calculation (lag n 2))""")
        self.assertLispError("(calculate-all *columns* 3)", "give lag a default")

    def test_after_orders_columns_by_dependency_not_declaration(self):
        self.run_lisp("""
          (defcolumn base-col :name "base" :initial_value 1 :value_calculation (+ base 1))
          (defcolumn derived-col :name "derived" :after base-col :initial_value 0
                     :value_calculation (* base 10))
          (calculate-all (reverse *columns*) 4)""")
        self.assertShows("(column-series derived-col)", "#(0 20 30 40)")

    def test_a_circular_dependency_is_reported(self):
        self.run_lisp("""
          (define c1 (make-column :name "c1" :initial_value 0 :value_calculation '(+ 1 1) :after '()))
          (define c2 (make-column :name "c2" :initial_value 0 :value_calculation '(+ 1 1) :after c1))
          (column-after-set! c1 c2)""")
        self.assertLispError("(calculate-all (list c1 c2) 3)", "circular or missing")

    def test_write_csv_writes_the_visible_columns(self):
        self.run_lisp("""
          (defcolumn n-col :name "n" :initial_value 0 :value_calculation (+ n 1))
          (calculate-all *columns* 3)""")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            self.run_lisp('(write-csv "%s" *columns*)' % path)
            with open(path) as f:
                lines = f.read().split()
        self.assertEqual(lines[0], "n")
        self.assertEqual(lines[1:], ["0", "1", "2"])


if __name__ == "__main__":
    unittest.main()
