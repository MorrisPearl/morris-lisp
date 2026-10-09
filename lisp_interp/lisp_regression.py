"""Regression models for the Lisp interpreter, with one or more predictors:

                   a straight line (or plane)   a line that bends at knots
  least squares    linear-regression            spline-regression
  least absolute   lad-regression               spline-lad
    deviation
  a quantile       quantile-regression          spline-quantile
  logistic         logistic-regression          spline-logistic

plus model-report / model-predict / model-evaluate and friends, and
cross-validate, which measures how well a model predicts data it wasn't
fit to. A logistic model's curve goes from 0 to 1, unless :floor and
:ceiling say otherwise. Every fitting function takes :groups, for standard
errors that allow for rows in the same group being alike
(clustered_covariance).

The fitting math (fit_linear, fit_lad, fit_logistic) uses numpy matrix
operations, so fitting millions of rows isn't slowed down by a Python-level
loop.
The Lisp-callable builtins are listed in BUILTINS at the bottom of this
file; lisp_builtins.make_global_env() adds them to every environment.
"""

import itertools
import math
import random

import numpy as np

from lisp_core import (
    Keyword, LispDate, LispError, LispString, LispVector, NIL, Pair, Symbol,
    apply_proc, is_true, keyword_options, list_to_pairs, numeric_value, pairs_to_list, to_display_string,
)
from lisp_vector_math import to_vector


# ---------------------------------------------------------------------------
# Linear and logistic models
# ---------------------------------------------------------------------------

class LispModel:
    """A fitted linear model, y = intercept + sum(coefficients[i] * x[i]) --
    fit by least squares ("linear") or least absolute deviation ("lad") -- or
    logistic model, y = floor + (ceiling - floor) * sigmoid(intercept +
    sum(coefficients[i] * x[i])), whose floor and ceiling are 0 and 1 unless
    it was fit with others (fit_logistic_between). `coefficients` has one
    entry per predictor; `stats` holds the fit statistics model-report shows."""

    def __init__(self, kind, coefficients, intercept, stats, predictor_names=None, y_name=None,
                 floor=0.0, ceiling=1.0):
        self.kind = kind                    # "linear", "lad", or "logistic"
        self.coefficients = coefficients    # list of floats, one per predictor
        self.intercept = intercept
        self.k = len(coefficients)          # number of predictors
        self.stats = stats                  # dict of extra fit info, kind-specific
        # The predictors' and y's names, when they were given as (name . vector)
        # pairs; model-report uses them in place of x1/x2/.../y. None if unnamed.
        self.predictor_names = predictor_names   # list of str, one per predictor, or None
        self.y_name = y_name                     # str, or None
        self.floor, self.ceiling = floor, ceiling   # a logistic model's curve goes from floor to ceiling

    def between_0_and_1(self):
        """Whether a logistic model's curve goes from 0 to 1."""
        return (self.floor, self.ceiling) == (0.0, 1.0)

    def is_probability(self):
        """Whether a logistic model gives a probability: its floor and ceiling
        are between 0 and 1."""
        return self.kind == "logistic" and 0 <= self.floor and self.ceiling <= 1

    def predict(self, xs):
        """xs: a list of numbers, one per predictor, in the same order the
        model was fit with."""
        z = self.intercept + sum(c * x for c, x in zip(self.coefficients, xs))
        return self.floor + (self.ceiling - self.floor) * sigmoid(z) if self.kind == "logistic" else z

    def __repr__(self):
        between = "" if self.kind != "logistic" or self.between_0_and_1() else \
            " floor=%.6g ceiling=%.6g" % (self.floor, self.ceiling)
        if len(self.coefficients) == 1:
            return "#<%s-model slope=%.6g intercept=%.6g%s>" % (
                self.kind, self.coefficients[0], self.intercept, between)
        coeffs = ", ".join("%.6g" % c for c in self.coefficients)
        return "#<%s-model coefficients=(%s) intercept=%.6g%s>" % (self.kind, coeffs, self.intercept, between)


def sigmoid(z):
    """Numerically stable logistic function 1 / (1 + e^-z)."""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _sigmoid_vec(z):
    """sigmoid() applied to every element of a numpy array at once, in the
    same numerically stable way. Used by fit_logistic."""
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def solve_linear_system(matrix, rhs):
    """Solve matrix @ x = rhs by Gauss-Jordan elimination with partial
    pivoting. `matrix` is n lists of n numbers; `rhs` is n numbers. Plain
    O(n^3) Python, which is fast for the handful of predictors a model has."""
    n = len(matrix)
    augmented = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-12:
            raise LispError(
                "regression: the predictors are collinear or there isn't "
                "enough data to fit this model")
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot_value = augmented[col][col]
        augmented[col] = [v / pivot_value for v in augmented[col]]
        for row in range(n):
            if row != col:
                factor = augmented[row][col]
                augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[col])]
    return [augmented[i][n] for i in range(n)]


def _standardize_columns(columns):
    """Rescale each predictor column to mean 0 and standard deviation 1, and
    return (standardized_columns, means, scales). Fitting on standardized
    columns keeps the math well-behaved whatever the predictors' scales
    (e.g. a day number next to a small percentage)."""
    means, scales, standardized = [], [], []
    n = len(columns[0])
    for i, col in enumerate(columns):
        mean = sum(col) / n
        variance = sum((v - mean) ** 2 for v in col) / n
        if variance == 0:
            raise LispError("regression: predictor %d has no variation; cannot fit a model" % (i + 1,))
        scale = math.sqrt(variance)
        means.append(mean)
        scales.append(scale)
        standardized.append([(v - mean) / scale for v in col])
    return standardized, means, scales


def _unstandardize_coefficients(b0, betas, means, scales):
    """Convert coefficients fit in standardized-predictor space back to
    the original, unstandardized scale."""
    coefficients = [b / scale for b, scale in zip(betas, scales)]
    intercept = b0 - sum(b * mean / scale for b, mean, scale in zip(betas, means, scales))
    return coefficients, intercept


def fit_linear(columns, ys, weights=None, groups=None):
    """Least-squares fit of y = intercept + sum(coef[i] * x[i]). `columns` is
    a list of predictor columns (lists of numbers); `ys` the observed
    values. Returns a LispModel.

    `weights` (optional): one non-negative number per observation. The fit
    then minimizes sum(weight[i] * (y[i] - prediction[i])**2), so an
    observation with weight 3 counts as much as three with weight 1; only
    the weights' relative sizes matter. None weights every observation
    equally.

    `groups` (optional): each observation's group, a number from 0, for
    standard errors that allow for observations in the same group being
    alike (clustered_covariance). It doesn't change the fit.

    The normal equations are built with numpy (X.T @ X, roughly), so
    millions of rows are fast; the small p-by-p solve is plain Python."""
    k = len(columns)
    n = len(ys)
    if n == 0:
        raise LispError("linear-regression: no data to fit")
    for col in columns:
        if len(col) != n:
            raise LispError("linear-regression: all vectors must be the same length")
    if weights is None:
        weights = [1.0] * n

    std_columns, means, scales = _standardize_columns(columns)
    p = k + 1
    X = np.column_stack([np.ones(n)] + [np.asarray(col, dtype=np.float64) for col in std_columns])
    w = np.asarray(weights, dtype=np.float64)
    y_arr = np.asarray(ys, dtype=np.float64)

    normal_matrix = (X.T * w) @ X       # p x p: sum_i w[i] * X[i,a] * X[i,b]
    normal_rhs = (X.T * w) @ y_arr      # p:     sum_i w[i] * X[i,a] * y[i]
    solved = solve_linear_system(normal_matrix.tolist(), normal_rhs.tolist())
    coefficients, intercept = _unstandardize_coefficients(solved[0], solved[1:], means, scales)

    model = LispModel("linear", coefficients, intercept, {})
    X_orig = np.column_stack([np.asarray(col, dtype=np.float64) for col in columns])
    predictions = intercept + X_orig @ np.asarray(coefficients, dtype=np.float64)
    ss_residual = float((w * (y_arr - predictions) ** 2).sum())

    # Standard errors: the residual variance times (X'WX)^-1, with n - p
    # degrees of freedom. With groups, the sandwich of clustered_covariance,
    # each row's score being weight * residual * x, times (n - 1) / (n - p)
    # (Stata's small-sample correction), with one degree of freedom fewer than
    # the number of groups. Scaling every weight by the same amount changes
    # neither.
    degrees_of_freedom = n - p
    if degrees_of_freedom > 0 and groups is not None:
        residuals = y_arr - X @ np.array(solved)
        covariance = clustered_covariance(np.linalg.inv(normal_matrix), X * (w * residuals)[:, None], groups)
        covariance *= (n - 1) / (n - p)
        degrees_of_freedom = int(groups.max())          # the number of groups, less 1
        std_errors = np.sqrt(np.diag(_original_scale_covariance(covariance, means, scales)))
    elif degrees_of_freedom > 0:
        covariance = (ss_residual / degrees_of_freedom) * np.linalg.inv(normal_matrix)
        std_errors = np.sqrt(np.diag(_original_scale_covariance(covariance, means, scales)))
    else:
        std_errors = np.full(p, np.nan)

    measures = measures_of_fit(predictions, y_arr, w, "least squares")
    model.stats = {
        "r_squared": measure(measures, "R-squared"),
        "measures": measures,                   # see measures_of_fit
        "n": n,
        "std_errors": std_errors.tolist(),      # intercept first, then each coefficient
        "test": "t",
        "degrees_of_freedom": degrees_of_freedom,
    }
    if groups is not None:
        model.stats["groups"] = int(groups.max()) + 1
    return model


def fit_logistic(columns, ys, weights=None, floor=0.0, ceiling=1.0, groups=None, max_iterations=50, tolerance=1e-8):
    """Fit p = floor + (ceiling - floor) * sigmoid(intercept + sum(coef[i] *
    x[i])) by maximum likelihood: the curve from 0 to 1, unless the floor
    and ceiling, both between 0 and 1, say otherwise. Each y must be between
    0 and 1 (a 0/1 label or a probability), and the likelihood is that of y
    having probability p. `weights` works as in fit_linear: each
    observation's log-likelihood is multiplied by its weight. (That's
    unrelated to `irls_weight` below, which is part of the method itself.)
    `groups`, as in fit_linear, is for the standard errors.

    The coefficients are found by Fisher scoring, a kind of Newton-Raphson:
    each step solves for the change that would reach the maximum if the
    log-likelihood were a parabola there. With a floor of 0 and a ceiling of
    1 it's Newton-Raphson exactly (also called iteratively reweighted least
    squares, IRLS). Each iteration's gradient and information matrix are
    built with numpy, so large data is fast; this loop is where nearly all
    the fitting time goes."""
    k = len(columns)
    n = len(ys)
    if n == 0:
        raise LispError("logistic-regression: no data to fit")
    for col in columns:
        if len(col) != n:
            raise LispError("logistic-regression: all vectors must be the same length")
    for y in ys:
        if y < 0 or y > 1:
            raise LispError(
                "logistic-regression: dependent-variable values must all be "
                "between 0 and 1 (got %r)" % (y,))
    if weights is None:
        weights = [1.0] * n

    std_columns, means, scales = _standardize_columns(columns)
    p = k + 1
    eps = 1e-12
    X = np.column_stack([np.ones(n)] + [np.asarray(col, dtype=np.float64) for col in std_columns])
    w = np.asarray(weights, dtype=np.float64)
    y_arr = np.asarray(ys, dtype=np.float64)
    span = ceiling - floor

    def probability_and_irls_weight(beta):
        """Each row's probability, and how much its log-likelihood's slope
        changes with the coefficients -- the information it carries -- per
        unit of `w`: dp/dz squared over p (1 - p), z being the row's
        intercept + sum(coef[i] * x[i]). Also the factor (dp/dz) / (p (1 -
        p)) that turns y - p into the slope. With a floor of 0 and a ceiling
        of 1, dp/dz = p (1 - p), so the factor is exactly 1."""
        s = _sigmoid_vec(X @ beta)
        prob = floor + span * s
        if (floor, ceiling) == (0.0, 1.0):
            factor = np.ones(n)
        else:
            factor = span * s * (1.0 - s) / np.maximum(prob * (1.0 - prob), eps)
        return prob, factor, factor * span * s * (1.0 - s)

    def log_likelihood_of(prob):
        return float((w * (
            y_arr * np.log(np.maximum(prob, eps)) + (1.0 - y_arr) * np.log(np.maximum(1.0 - prob, eps))
        )).sum())

    beta = np.zeros(p)
    converged = False
    iterations_used = 0
    log_likelihood = 0.0

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        prob, factor, irls_weight = probability_and_irls_weight(beta)     # n each
        if (floor, ceiling) == (0.0, 1.0):
            irls_weight = prob * (1.0 - prob)
        gradient = X.T @ (w * (y_arr - prob) * factor)                   # p
        information = (X.T * (w * irls_weight)) @ X                       # p x p
        log_likelihood = log_likelihood_of(prob)

        try:
            delta = np.array(solve_linear_system(information.tolist(), gradient.tolist()))
        except LispError:
            # The information is gone: the curve has become so steep, or so
            # flat, at the points that it can't tell the coefficients apart.
            # That happens when the most likely curve has a coefficient of
            # infinity -- data perfectly separated into 0s and 1s by a
            # predictor, or a spline's piece where every point is at or past
            # the floor or ceiling, which it can come ever closer to by
            # getting steeper. Stop here; it hasn't converged.
            break
        # A step that goes too far -- the log-likelihood isn't a parabola,
        # far from its top -- and makes the data less likely is halved, until
        # it doesn't (step halving).
        for _ in range(30):
            if log_likelihood_of(probability_and_irls_weight(beta + delta)[0]) >= log_likelihood - 1e-10 * abs(log_likelihood):
                break
            delta = delta / 2
        beta = beta + delta
        if max(abs(d) for d in delta) < tolerance:
            converged = True
            break

    coefficients, intercept = _unstandardize_coefficients(float(beta[0]), beta[1:].tolist(), means, scales)

    prob, factor, irls_weight = probability_and_irls_weight(beta)
    if (floor, ceiling) == (0.0, 1.0):
        irls_weight = prob * (1.0 - prob)
    measures = measures_of_fit(prob, y_arr, w, "probability")
    shares = not is_all_0_or_1(y_arr)

    # Standard errors from the inverse of the information matrix at the
    # fitted coefficients. The weights are first rescaled to average 1, so
    # they say how much each row matters relative to the others, not how
    # many copies of it there are -- otherwise weighting by loan balance
    # (in dollars) would make the standard errors absurdly small.
    #
    # That takes each y to be a 0 or a 1, whose scatter about its chance p
    # is p (1 - p). A share -- the part of a pool that prepaid -- is an
    # average over many loans, and scatters far less, so for shares the
    # standard errors come from the scatter of y about the fit instead: the
    # sandwich of clustered_covariance, with each row its own group. With
    # groups, it's that sandwich with the groups, for 0s and 1s too. Each
    # row's score is the slope of its log-likelihood: weight * (y - p) *
    # factor * x.
    total_weight = float(w.sum())
    relative_w = w * (n / total_weight)
    # (A fit that didn't converge can have no information left: then they're
    # nan, quietly.)
    information = (X.T * (relative_w * irls_weight)) @ X
    try:
        with np.errstate(invalid="ignore", over="ignore", divide="ignore"):
            covariance = np.linalg.inv(information)
            if groups is not None or shares:
                covariance = clustered_covariance(covariance, X * (relative_w * (y_arr - prob) * factor)[:, None],
                                                  groups if groups is not None else np.arange(n))
            variances = np.diag(_original_scale_covariance(covariance, means, scales))
            std_errors = np.sqrt(np.where(variances >= 0, variances, np.nan))
    except np.linalg.LinAlgError:
        std_errors = np.full(p, np.nan)

    # How much y scatters about the fit, compared with 0s and 1s, in the
    # units of the weights: for 0s and 1s, the average weight; for shares,
    # also how much less they scatter -- the average of (y - p)^2 / (p (1 -
    # p)) -- which fit_logistic_bounds needs.
    if shares and n > p:
        dispersion = float((w * (y_arr - prob) ** 2 / np.maximum(prob * (1 - prob), eps)).sum()) / (n - p)
    else:
        dispersion = total_weight / n

    stats = {
        "log_likelihood": measure(measures, "log-likelihood"),
        "pseudo_r_squared": measure(measures, "pseudo R-squared"),
        "measures": measures,                   # see measures_of_fit
        "y_is_0_or_1": not shares,
        "dispersion": dispersion,
        "iterations": iterations_used,
        "converged": converged,
        "n": n,
        "std_errors": std_errors.tolist(),      # intercept first, then each coefficient
        "test": "z",
        "auc": measure(measures, "AUC"),
    }
    if groups is not None:
        stats["groups"] = int(groups.max()) + 1
    return LispModel("logistic", coefficients, intercept, stats, floor=floor, ceiling=ceiling)


FIT = "fit"                     # a :floor or :ceiling to be fit to the data
BOUND_STEPS = (0.05, 0.01, 0.002)   # the grids a fitted floor and ceiling are looked for on (fit_logistic_bounds)
BOUND_GAP = 0.01                # how far apart the floor and the ceiling must be, at least
CHI_SQUARED_95 = 3.84           # a log-likelihood this much less, times 2, is a clearly worse fit (95%)


def fit_logistic_bounds(columns, ys, weights, floor, ceiling, who, groups=None):
    """A logistic model of a probability whose floor, or ceiling, or both,
    are fit to the data too (the other being given, or 0 or 1): the ones
    that make the data most likely. Every y must be between 0 and 1.

    They're found by trying them on a grid -- every 0.05 from 0 to 1 --
    fitting the curve for each (fit_logistic) and keeping the most likely;
    then every 0.01 near the best of those, and every 0.002 near the best
    of them. Then, for each one fitted, how far it can move either way
    (holding the other where it was fitted) before the fit is clearly
    worse -- its log-likelihood lower by 3.84 / 2, which for 0/1 outcomes
    makes the range roughly a 95% confidence interval. That's in units of
    the average weight, and for shares, which scatter less than 0s and 1s,
    times how much less (the model's stats["dispersion"]): a quasi-
    likelihood ratio. It doesn't allow for groups. The model's
    stats["fitted"] has those ranges."""
    for y in ys:
        if not 0 <= y <= 1:
            raise LispError("%s: fitting a floor or ceiling is for a probability: every y must be between 0 and 1 "
                            "(got %r)" % (who, y))
    fit_floor, fit_ceiling = floor == FIT, ceiling == FIT
    fixed_floor = 0.0 if fit_floor or floor is None else floor
    fixed_ceiling = 1.0 if fit_ceiling or ceiling is None else ceiling

    tried = {}

    def log_likelihood_at(f, c):
        """How likely the data is with this floor and ceiling (-inf if the fit fails)."""
        key = (round(f, 6), round(c, 6))
        if key not in tried:
            try:
                tried[key] = fit_logistic(columns, ys, weights, f, c).stats["log_likelihood"]
            except LispError:
                tried[key] = -math.inf
        return tried[key]

    def axis(fitted, fixed, best_value, number):
        """The values a floor or ceiling is tried at, on grid `number`."""
        step = BOUND_STEPS[number]
        if not fitted:
            return [fixed]
        if best_value is None:
            low, high = 0.0, 1.0
        else:
            low, high = max(0.0, best_value - BOUND_STEPS[number - 1]), min(1.0, best_value + BOUND_STEPS[number - 1])
        return [round(float(v), 6) for v in np.arange(low, high + step / 2, step)]

    best = (None, None)
    for number in range(len(BOUND_STEPS)):
        pairs = [(f, c) for f in axis(fit_floor, fixed_floor, best[0], number)
                 for c in axis(fit_ceiling, fixed_ceiling, best[1], number) if c - f >= BOUND_GAP - 1e-12]
        if not pairs:
            raise LispError("%s: the floor must be at least %s below the ceiling" % (who, BOUND_GAP))
        best = max(pairs, key=lambda pair: log_likelihood_at(*pair))
    best_floor, best_ceiling = best
    model = fit_logistic(columns, ys, weights, best_floor, best_ceiling, groups)
    best_log_likelihood = log_likelihood_at(best_floor, best_ceiling)

    def likelihood_range(at, value, lowest, highest):
        """How far a fitted value can move either way, before the log-likelihood is clearly lower."""
        step = BOUND_STEPS[-1]
        enough = best_log_likelihood - CHI_SQUARED_95 / 2 * model.stats["dispersion"]
        low = value
        while low - step >= lowest - 1e-12 and at(low - step) >= enough:
            low = round(low - step, 6)
        high = value
        while high + step <= highest + 1e-12 and at(high + step) >= enough:
            high = round(high + step, 6)
        return [low, high]

    fitted = {}
    if fit_floor:
        fitted["floor"] = likelihood_range(lambda f: log_likelihood_at(f, best_ceiling), best_floor,
                                           0.0, best_ceiling - BOUND_GAP)
    if fit_ceiling:
        fitted["ceiling"] = likelihood_range(lambda c: log_likelihood_at(best_floor, c), best_ceiling,
                                             best_floor + BOUND_GAP, 1.0)
    model.stats["fitted"] = fitted
    return model


def fit_logistic_between(columns, ys, weights, floor, ceiling, who, groups=None):
    """A logistic model of y between a floor and a ceiling:

        y = floor + (ceiling - floor) * sigmoid(intercept + sum(coef[i] * x[i]))

    a curve in the shape of an S that flattens out at the floor on one side
    and the ceiling on the other. There are three cases:

    - No floor and ceiling (None): they're 0 and 1, and every y must be
      between them, as a probability is.
    - A floor and ceiling between 0 and 1: the model is still of a
      probability -- one that can't go below the floor, or above the
      ceiling -- and every y must be between 0 and 1, a 0/1 label or a
      probability. fit_logistic fits it by maximum likelihood, as it is. A y
      beyond the floor or ceiling is just one that happened to be.
    - A floor or ceiling outside 0 and 1: y isn't a probability, but a
      number that flattens out at the floor and the ceiling. It's rescaled
      to (y - floor) / (ceiling - floor), which goes from 0 to 1, and that
      is fit as a probability would be. A y below the floor, or above the
      ceiling, is taken to be at it (clipped): data scatters about the
      levels a curve flattens out at, so some of it is beyond them. The
      model's stats say how many were.

    A floor or ceiling of FIT is fit to the data (fit_logistic_bounds).
    `who` is the function to name in an error message; `groups` is for the
    standard errors, as in fit_linear."""
    if floor == FIT or ceiling == FIT:
        return fit_logistic_bounds(columns, ys, weights, floor, ceiling, who, groups)
    if floor is None or (0 <= floor and ceiling <= 1):
        for y in ys:
            if not 0 <= y <= 1:
                raise LispError("%s: every y must be between 0 and 1, as a probability is (got %r) -- or give the "
                                "curve a :floor or :ceiling outside 0 and 1, for a number that isn't one" % (who, y))
        if floor is None:
            return fit_logistic(columns, ys, weights, groups=groups)
        return fit_logistic(columns, ys, weights, floor, ceiling, groups)
    rescaled = [(y - floor) / (ceiling - floor) for y in ys]
    model = fit_logistic(columns, [min(max(r, 0.0), 1.0) for r in rescaled], weights, groups=groups)
    model.floor, model.ceiling = floor, ceiling
    model.stats["below_floor"] = sum(1 for r in rescaled if r < 0)
    model.stats["above_ceiling"] = sum(1 for r in rescaled if r > 1)
    return model


def floor_and_ceiling(options, who):
    """The :floor and :ceiling options, as numbers -- 0 and 1 for one that
    isn't given -- or FIT for one given as 'fit; or (None, None) if neither
    is given."""
    if options.get("floor") is None and options.get("ceiling") is None:
        return None, None
    bounds = []
    for name, default in (("floor", 0.0), ("ceiling", 1.0)):
        value = options.get(name)
        if value is None:
            bounds.append(default)
        elif isinstance(value, Symbol) and str(value) == FIT:
            bounds.append(FIT)
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise LispError("%s: :%s must be a number, or 'fit to fit it to the data, not %s"
                            % (who, name, to_display_string(value)))
        else:
            bounds.append(float(value))
    floor, ceiling = bounds
    if FIT in bounds:
        for name, value in (("floor", floor), ("ceiling", ceiling)):
            if value != FIT and not 0 <= value <= 1:
                raise LispError("%s: to fit the floor or ceiling, the other must be between 0 and 1 (the :%s is %s)"
                                % (who, name, value))
    elif not floor < ceiling:
        raise LispError("%s: the :floor (%s) must be below the :ceiling (%s)" % (who, floor, ceiling))
    return floor, ceiling


def positional_and_keywords(arguments, most_positional, keywords, who):
    """A builtin's optional arguments, split into the positional ones, before
    the first keyword (at most most_positional of them), and the keyword
    options after it, as a dict."""
    first_keyword = next((i for i, a in enumerate(arguments) if isinstance(a, Keyword)), len(arguments))
    if first_keyword > most_positional:
        raise LispError("%s: expected at most %d argument(s) after x and y, before the keyword options, not %d"
                        % (who, most_positional, first_keyword))
    return list(arguments[:first_keyword]), keyword_options(arguments[first_keyword:], keywords, who)


# ---------------------------------------------------------------------------
# Least absolute deviation (LAD) regression
# ---------------------------------------------------------------------------

def weighted_quantile(values, weights, levels):
    """The value t that makes sum(weights[i] * check(levels[i], values[i] - t))
    smallest, where check(q, r) is q * r for r above 0 and (1 - q) * |r| for
    r below: a point above t costs q per unit, one below it 1 - q. levels
    are the quantile each value is weighed for (one number, for all of them).
    The answer is the first value, in sorted order, at which the weight
    added up from the smallest reaches sum(weights * levels): there, moving t
    either way no longer lowers the sum. With every level 0.5, it's the
    weighted median. `values`, `weights`, and `levels` are numpy arrays (or
    levels a number)."""
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    return float(values[order[np.searchsorted(cumulative, float(np.sum(weights * levels)))]])


def weighted_median(values, weights):
    """The value t that makes sum(weights[i] * |values[i] - t|) smallest."""
    return weighted_quantile(values, weights, 0.5)


def check_loss(residuals, quantile):
    """Each residual's cost for a quantile fit: quantile * r above the fit,
    (1 - quantile) * |r| below it. For the median (0.5), half of |r|."""
    return np.where(residuals >= 0, quantile * residuals, (quantile - 1) * residuals)


def fit_quantile(columns, ys, quantile, weights=None, groups=None, max_iterations=1000, kind="quantile",
                 who="quantile-regression"):
    """Quantile regression: the fit of y = intercept + sum(coef[i] * x[i])
    with `quantile` of the points below it (0.9: 90% below, 10% above). It
    makes sum(weight[i] * check(y[i] - prediction[i])) smallest, where a
    point above the fit costs quantile times its distance and one below it
    1 - quantile times its distance (check_loss). For the median (0.5) the
    two are alike, and the fit is the least absolute deviation one
    (fit_lad): a point far from the others pulls a least-squares fit toward
    it by the square of its distance, but this only in proportion to it --
    so a few outliers barely move it. With no predictors, it would be the
    quantile of y. `columns`, `ys`, `weights`, and `groups` are as for
    fit_linear. Returns a LispModel of the given kind.

    There's no formula for it, as there is for least squares, but one fact
    makes it easy to find: some best fit goes exactly through p of the
    points, p being the number of coefficients, counting the intercept --
    for a line, through two of them. So, Wesolowsky's method (1981):

    1. Start with the fit through the p points closest to the least-squares
       fit.
    2. Hold the fit at p - 1 of the points it goes through, and swing it
       (for a line: rotate it about one point). As it swings by an amount t,
       point i's residual changes by t * a[i], so the sum is
       sum(weight[i] * |a[i]| * check(residual[i] / a[i] - t)) -- with the
       quantile turned around (1 - quantile) for a point whose a[i] is
       below 0 -- which is smallest when t is a weighted quantile of the
       residual[i] / a[i] (weighted_quantile), where the fit reaches
       another of the points.
    3. Try that for every set of p - 1 points the fit goes through, and take
       the swing that lowers the sum the most. Repeat until no swing lowers
       it: then no fit is better, since the sum has no local minimum that
       isn't the minimum.

    Each step is exact, and it usually takes only a few. Fitting is done on
    standardized predictors, as in fit_linear."""
    k = len(columns)
    n = len(ys)
    p = k + 1
    if not 0 < quantile < 1:
        raise LispError("%s: the quantile must be between 0 and 1, 0.9 for the 90th percentile, not %s"
                        % (who, quantile))
    if n < p:
        raise LispError("%s: %d observation(s) is too few to fit %d coefficients" % (who, n, p))
    for col in columns:
        if len(col) != n:
            raise LispError("%s: all vectors must be the same length" % who)
    if weights is None:
        weights = [1.0] * n

    std_columns, means, scales = _standardize_columns(columns)
    X = np.column_stack([np.ones(n)] + [np.asarray(col, dtype=np.float64) for col in std_columns])
    w = np.asarray(weights, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)

    def loss(beta):
        return float((w * check_loss(y - X @ beta, quantile)).sum())

    # 1. The fit through the p points closest to the least-squares fit (taking
    #    a point only if it isn't in line with the ones already taken).
    least_squares = solve_linear_system(((X.T * w) @ X).tolist(), ((X.T * w) @ y).tolist())
    through = []
    for i in np.argsort(np.abs(y - X @ np.array(least_squares)), kind="stable"):
        if np.linalg.matrix_rank(X[through + [i]]) == len(through) + 1:
            through.append(int(i))
        if len(through) == p:
            break
    if len(through) < p:
        raise LispError(
            "regression: the predictors are collinear or there isn't enough data to fit this model")
    beta = np.linalg.solve(X[through], y[through])
    total = loss(beta)

    # 2 and 3. Swing the fit about each p - 1 of the points it goes through.
    on_fit_tolerance = 1e-9 * float(np.abs(y).max())
    converged = False
    iterations = 0
    while iterations < max_iterations and total > 0:
        iterations += 1
        residuals = y - X @ beta
        on_fit = np.nonzero(np.abs(residuals) <= on_fit_tolerance)[0]
        best_total, best_beta = total, None
        for pivots in itertools.combinations(on_fit, p - 1):
            pivot_rows = X[list(pivots)]
            if np.linalg.matrix_rank(pivot_rows) < p - 1:
                continue
            direction = np.linalg.svd(pivot_rows)[2][-1]    # keeps the pivots' predictions fixed
            a = X @ direction                               # how each prediction changes per unit of swing
            moves = np.abs(a) > 1e-12 * np.abs(a).max()     # the points whose residuals change
            levels = np.where(a[moves] > 0, quantile, 1 - quantile)
            t = weighted_quantile(residuals[moves] / a[moves], w[moves] * np.abs(a[moves]), levels)
            candidate = beta + t * direction
            candidate_total = loss(candidate)
            if candidate_total < best_total * (1 - 1e-12):
                best_total, best_beta = candidate_total, candidate
        if best_beta is None:
            converged = True
            break
        total, beta = best_total, best_beta
    if total == 0:
        converged = True

    coefficients, intercept = _unstandardize_coefficients(float(beta[0]), beta[1:].tolist(), means, scales)
    residuals = y - X @ beta

    # How good the fit is, as R-squared says for least squares: 1 - the sum
    # / that sum about the quantile of y (a fit with no predictors). Koenker
    # and Machado's R1.
    total_without = float((w * check_loss(y - weighted_quantile(y, w, quantile), quantile)).sum())
    pseudo_r_squared = (1 - total / total_without) if total_without > 0 else float("nan")

    # Standard errors. The coefficients' covariance is quantile * (1 -
    # quantile) * sparsity^2 * A^-1 B A^-1, with A = X'WX and B = X'W^2X --
    # just (X'X)^-1 without weights -- where the sparsity is 1 / the density
    # of the errors at the quantile: how thinly the residuals are spread
    # there. It's estimated two ways, and the larger is used:
    #   - as for normally distributed errors: sigma / the normal density at
    #     the quantile (sigma * sqrt(2 pi), for the median), with sigma found
    #     from the median distance of the residuals from their own median
    #     (times 1.4826, which makes it the standard deviation for normal
    #     errors), so that outliers don't inflate it. The p residuals the fit
    #     makes exactly 0 are left out.
    #   - from the residuals themselves (Siddiqui's): how far apart their
    #     quantile - h and quantile + h are, divided by 2h, h being Hall and
    #     Sheather's bandwidth (sparsity_bandwidth), kept away from the most
    #     extreme residuals.
    # The first is better with few points, the second with heavy-tailed
    # errors, far from the median. (Simulations with normal, heavy-tailed,
    # or contaminated errors, for the 0.5, 0.75, and 0.9 quantiles, give 95%
    # intervals that hold the true coefficient 94% to 97% of the time with
    # 200 points; with 30, 92% to 97%, but 80% to 83% for the 0.9 quantile
    # with heavy-tailed errors; with 8, 75% to 93%, the least far from the
    # median, where only a point or two is beyond the fit.) Scaling every
    # weight alike doesn't change them.
    #
    # With groups, quantile * (1 - quantile) * B is replaced by the "meat" of
    # clustered_covariance, each row's score being weight * x * (quantile, if
    # it's above the fit; quantile - 1, if below; 0, if on it), with one
    # degree of freedom fewer than the number of groups. (With every row its
    # own group, the meat averages out to quantile * (1 - quantile) * B.)
    degrees_of_freedom = n - p
    off_fit = residuals[np.abs(residuals) > on_fit_tolerance]
    if degrees_of_freedom > 0 and len(off_fit) > 0:
        sigma = 1.4826 * float(np.median(np.abs(off_fit - np.median(off_fit))))
        z = _normal_quantile(quantile)
        as_if_normal = sigma * math.sqrt(2 * math.pi) * math.exp(z * z / 2)
        h = sparsity_bandwidth(quantile, n)
        from_residuals = (weighted_quantile(residuals, w, quantile + h) -
                          weighted_quantile(residuals, w, quantile - h)) / (2 * h) if h > 0 else 0.0
        sparsity = max(as_if_normal, from_residuals)
        A_inverse = np.linalg.inv((X.T * w) @ X)
        if groups is None:
            covariance = quantile * (1 - quantile) * sparsity ** 2 * (A_inverse @ ((X.T * w ** 2) @ X) @ A_inverse)
        else:
            pull = np.where(residuals > on_fit_tolerance, quantile,
                            np.where(residuals < -on_fit_tolerance, quantile - 1, 0.0))
            covariance = sparsity ** 2 * clustered_covariance(A_inverse, X * (w * pull)[:, None], groups)
            degrees_of_freedom = int(groups.max())          # the number of groups, less 1
        std_errors = np.sqrt(np.diag(_original_scale_covariance(covariance, means, scales)))
    else:
        std_errors = np.full(p, np.nan)

    below, above = int((residuals < -on_fit_tolerance).sum()), int((residuals > on_fit_tolerance).sum())
    stats = {
        "quantile": quantile,
        "measures": measures_of_fit(X @ beta, y, w, "lad" if kind == "lad" else "quantile", quantile),
        "loss": total,                          # the sum of check_loss
        "sum_abs_deviations": float((w * np.abs(residuals)).sum()),
        "pseudo_r_squared": pseudo_r_squared,
        "iterations": iterations,
        "converged": converged,
        "n": n,
        "below_on_above": [below, n - below - above, above],    # how many points are below the fit, on it, above it
        "std_errors": std_errors.tolist(),      # intercept first, then each coefficient
        "test": "t",
        "degrees_of_freedom": degrees_of_freedom,
    }
    if groups is not None:
        stats["groups"] = int(groups.max()) + 1
    return LispModel(kind, coefficients, intercept, stats)


def sparsity_bandwidth(quantile, n):
    """Hall and Sheather's bandwidth, h, for estimating the sparsity at a
    quantile from n residuals (as Koenker's quantreg does, for a 95%
    interval) -- made smaller, if it has to be, so that quantile - h and
    quantile + h stay two points in from each end of the residuals, and
    one far-out point can't decide it. 0 if there isn't room for that."""
    z = _normal_quantile(quantile)
    density = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    h = n ** (-1 / 3) * 1.96 ** (2 / 3) * (1.5 * density ** 2 / (2 * z * z + 1)) ** (1 / 3)
    return max(0.0, min(h, quantile - 2 / n, 1 - 2 / n - quantile))


def _normal_quantile(q):
    """The z with N(z) = q, the standard normal distribution's quantile, by
    bisection of math.erf (to well within a millionth)."""
    low, high = -10.0, 10.0
    for _ in range(80):
        middle = (low + high) / 2
        if 0.5 * (1 + math.erf(middle / math.sqrt(2))) < q:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def fit_lad(columns, ys, weights=None, groups=None):
    """Least absolute deviation fit of y = intercept + sum(coef[i] * x[i]):
    the one that makes sum(weight[i] * |y[i] - prediction[i]|) smallest,
    rather than the sum of squares -- the quantile fit for the median
    (fit_quantile). Returns a LispModel of kind "lad"."""
    return fit_quantile(columns, ys, 0.5, weights, groups, kind="lad", who="lad-regression")


# ---------------------------------------------------------------------------
# Standard errors, p-values, and AUC
# ---------------------------------------------------------------------------

def _original_scale_covariance(covariance, means, scales):
    """The covariance matrix of (intercept, coefficients) on the original
    scale, from the one fitted on standardized columns. The original
    coefficients are a linear function of the standardized ones (see
    _unstandardize_coefficients): original = T @ standardized, so the
    covariance becomes T @ covariance @ T'."""
    k = len(means)
    T = np.zeros((k + 1, k + 1))
    T[0, 0] = 1.0
    for j in range(k):
        T[0, j + 1] = -means[j] / scales[j]
        T[j + 1, j + 1] = 1.0 / scales[j]
    return T @ covariance @ T.T


def clustered_covariance(bread, scores, groups):
    """The covariance of a fit's coefficients when its rows come in groups
    whose rows are alike -- the months of one loan, say -- so that they
    aren't each new information ("clustered" standard errors). The usual
    standard errors take every row to be new; these take every group to be.

    `scores` has a row for each data row: how hard it pulls on each
    coefficient, at the fit (for least squares, weight * residual * x). At
    the fit, they add up to 0. Added up over each group instead, they say
    how hard the group as a whole pulls. How much those sums vary from group
    to group -- the "meat", the sum of each sum times itself -- says how
    much the coefficients would vary from one sample of groups to another,
    once it's divided, on both sides, by how sharply the fit's measure (the
    sum of squares, or the likelihood) curves at its best: `bread` is the
    inverse of that curvature, (X'WX)^-1 for least squares. So the
    covariance is bread @ meat @ bread -- a "sandwich" -- times G / (G - 1),
    G being the number of groups, since the sums are measured from the fit,
    not from the truth. `groups` is each row's group, a number from 0 to
    G - 1."""
    number_of_groups = int(groups.max()) + 1
    group_sums = np.zeros((number_of_groups, scores.shape[1]))
    np.add.at(group_sums, groups, scores)
    meat = group_sums.T @ group_sums
    return number_of_groups / (number_of_groups - 1) * (bread @ meat @ bread)


def _beta_continued_fraction(a, b, x):
    """The continued fraction in the incomplete beta function (the method
    in Numerical Recipes, "betacf")."""
    tiny = 1e-300
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 301):
        for numerator in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                          -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + numerator * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + numerator / c
            c = c if abs(c) > tiny else tiny
            step = c * d
            result *= step
        if abs(step - 1.0) < 3e-14:
            break
    return result


def _incomplete_beta(a, b, x):
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1 - x) / b


def two_sided_p_value(statistic, test, degrees_of_freedom=None):
    """The chance of a statistic at least this far from 0 if the true
    coefficient were 0: from the t distribution (test "t", for linear
    models) or the normal distribution (test "z", for logistic models)."""
    if statistic != statistic:                      # NaN
        return float("nan")
    if test == "z":
        return math.erfc(abs(statistic) / math.sqrt(2))
    df = degrees_of_freedom
    return _incomplete_beta(df / 2.0, 0.5, df / (df + statistic * statistic))


def weighted_auc(scores, ys, weights):
    """The area under the ROC curve: the chance that a randomly chosen row
    with y = 1 has a higher score (prediction) than a randomly chosen row
    with y = 0, counting ties as half. 0.5 is no better than guessing; 1.0
    ranks perfectly. A y between 0 and 1 counts as that fraction of a 1,
    and each row counts in proportion to its weight."""
    if len(scores) == 0:
        return float("nan")
    positive, negative = weights * ys, weights * (1.0 - ys)
    order = np.argsort(scores, kind="stable")
    scores, positive, negative = scores[order], positive[order], negative[order]
    tie_starts = np.flatnonzero(np.concatenate([[True], scores[1:] != scores[:-1]]))
    positive_per_score = np.add.reduceat(positive, tie_starts)
    negative_per_score = np.add.reduceat(negative, tie_starts)
    negatives_below = np.cumsum(negative_per_score) - negative_per_score
    total_positive, total_negative = positive.sum(), negative.sum()
    if total_positive == 0 or total_negative == 0:
        return float("nan")
    wins = (positive_per_score * (negatives_below + 0.5 * negative_per_score)).sum()
    return float(wins / (total_positive * total_negative))


# ---------------------------------------------------------------------------
# Measures of fit, each beside what a perfect model would get, and a model
# that predicts the same for every row
# ---------------------------------------------------------------------------

def is_all_0_or_1(ys):
    """Whether every y is 0 or 1 -- an outcome, such as whether a loan
    prepaid -- rather than some being shares between them."""
    return bool(np.all((ys == 0) | (ys == 1)))


def _x_log_x(v):
    """v * log(v), taking 0 * log(0) to be 0, as its limit is."""
    return np.where(v > 0, v * np.log(np.maximum(v, 1e-300)), 0.0)


def log_likelihood_of_shares(predictions, ys, weights):
    """sum(weight * (y log p + (1 - y) log(1 - p))): how likely the
    predicted chances p made the outcomes y (or, for shares, the
    quasi-likelihood used just as if they were)."""
    p = np.clip(predictions, 1e-12, 1 - 1e-12)
    return float((weights * (ys * np.log(p) + (1 - ys) * np.log(1 - p))).sum())


def measures_of_fit(predictions, ys, weights, kind, quantile=0.5):
    """How close the predictions are to y, as a list of measures, each a
    list [name, value, perfect, same, what]: the model's value; a perfect
    model's -- one that predicted every y exactly; and that of a model
    that predicts the same for every row -- `what`, such as "the average
    of y" -- as a model with no predictors would. Where the model's value
    is, between those two, says how good it is. Each row counts by its
    weight. The kinds of model, and their measures:

      "least squares"  R-squared, RMSE, MAE
      "lad"            MAE, pseudo R-squared (1 - the MAE / the same model's)
      "quantile"       average loss, pseudo R-squared (the same, with losses)
      "probability"    log-likelihood, pseudo R-squared (McFadden's), AUC;
                       and, when y isn't all 0s and 1s -- shares -- first
                       R-squared, RMSE, and MAE, as for least squares

    For 0s and 1s, a perfect model's log-likelihood is 0 and its pseudo
    R-squared and AUC are 1. For shares they're not: a share of 0.1 isn't
    an outcome a chance can be sure of, as it can be of a 0 or a 1, so even
    predicting it exactly leaves the log-likelihood below 0 (y log y + (1 -
    y) log(1 - y), for that row), and its pseudo R-squared and AUC below 1."""
    w = weights / weights.sum()                 # each row's share of the weight
    residuals = ys - predictions
    mean_y = float((w * ys).sum())
    rows = []

    def mae_and_same():
        """The model's MAE, and that of predicting the median of y."""
        return float((w * np.abs(residuals)).sum()), float((w * np.abs(ys - weighted_median(ys, w))).sum())

    def least_squares_rows():
        ss_total = float((w * (ys - mean_y) ** 2).sum())
        ss_residual = float((w * residuals ** 2).sum())
        mae, mae_same = mae_and_same()
        return [["R-squared", (1 - ss_residual / ss_total) if ss_total > 0 else float("nan"), 1.0, 0.0,
                 "the average of y"],
                ["RMSE", math.sqrt(ss_residual), 0.0, math.sqrt(ss_total), "the average of y"],
                ["MAE", mae, 0.0, mae_same, "the median of y"]]

    if kind == "least squares":
        rows = least_squares_rows()
    elif kind == "lad":
        mae, mae_same = mae_and_same()
        rows = [["MAE", mae, 0.0, mae_same, "the median of y"],
                ["pseudo R-squared", (1 - mae / mae_same) if mae_same > 0 else float("nan"), 1.0, 0.0,
                 "the median of y"]]
    elif kind == "quantile":
        quantile_y = weighted_quantile(ys, w, quantile)
        loss, loss_same = float((w * check_loss(residuals, quantile)).sum()), \
            float((w * check_loss(ys - quantile_y, quantile)).sum())
        what = "the %.6g quantile of y" % quantile
        rows = [["average loss", loss, 0.0, loss_same, what],
                ["pseudo R-squared", (1 - loss / loss_same) if loss_same > 0 else float("nan"), 1.0, 0.0, what]]
    else:
        shares = not is_all_0_or_1(ys)
        if shares:
            rows = least_squares_rows()
        log_likelihood = log_likelihood_of_shares(predictions, ys, weights)
        same = log_likelihood_of_shares(np.full(len(ys), mean_y), ys, weights)
        perfect = float((weights * (_x_log_x(ys) + _x_log_x(1 - ys))).sum()) if shares else 0.0

        def pseudo_r_squared(value):
            return (1 - value / same) if same != 0 else float("nan")

        rows += [["log-likelihood", log_likelihood, perfect, same, "the average of y"],
                 ["pseudo R-squared", pseudo_r_squared(log_likelihood), pseudo_r_squared(perfect), 0.0,
                  "the average of y"],
                 ["AUC", weighted_auc(predictions, ys, weights),
                  weighted_auc(ys, ys, weights) if shares else 1.0, 0.5, "the same"]]
    return rows


def measure(rows, name):
    """One measure's value, from measures_of_fit's rows."""
    return next(row[1] for row in rows if row[0] == name)


def measure_lines(rows):
    """measures_of_fit's rows as report lines, such as
      R-squared        = 0.81  (perfect: 1; predicting the average of y for every row: 0)"""
    return ["  %-16s = %-10.6g (perfect: %.6g; predicting %s for every row: %.6g)"
            % (name, value, perfect, what, same) for name, value, perfect, same, what in rows]


def _coerce_predictors(x_arg):
    """Accept the predictors as a single vector, a list of vectors, or a list
    of (name . vector) pairs -- the shape sqlite-query returns, so a query's
    columns can go straight into a regression.

    Returns (vectors, names). `names` is a list of strings if every element
    was a (name . vector) pair, otherwise None."""
    if isinstance(x_arg, LispVector):
        return [x_arg], None
    if x_arg is NIL or isinstance(x_arg, Pair):
        items = pairs_to_list(x_arg)
        if not items:
            raise LispError("regression: at least one predictor vector is required")
        if all(isinstance(it, Pair) and isinstance(it.cdr, LispVector) for it in items):
            return [it.cdr for it in items], [to_display_string(it.car) for it in items]
        return items, None
    raise LispError(
        "regression: expected a vector, a list of vectors, or a list of "
        "(name . vector) pairs, of predictors")


def _predictor_columns(x_arg, n_expected):
    x_vecs, names = _coerce_predictors(x_arg)
    columns = []
    for xv in x_vecs:
        if not isinstance(xv, LispVector):
            raise LispError("regression: each predictor must be a vector")
        if len(xv.items) != n_expected:
            raise LispError("regression: all vectors must be the same length")
        columns.append([numeric_value(v) for v in xv.items.tolist()])
    return columns, names


def _coerce_y(y_arg, name):
    """Accept a bare vector, or a (name . vector) pair -- sqlite-query's
    own per-column result shape, e.g. (car freddie_loans) -- for the
    dependent variable. Returns (vector, y_name_or_None)."""
    if isinstance(y_arg, LispVector):
        return y_arg, None
    if isinstance(y_arg, Pair) and isinstance(y_arg.cdr, LispVector):
        return y_arg.cdr, to_display_string(y_arg.car)
    raise LispError("%s: y must be a vector, or a (name . vector) pair" % name)


def _optional_weights(weight_vec, n_expected, name):
    """The optional `weights` vector as a list of non-negative floats, or None
    if it wasn't given (meaning: weight every observation equally). A common
    use is weighting each loan by its balance, so the fit reflects dollars
    rather than loan counts."""
    if weight_vec is None or weight_vec is NIL:
        return None
    if not isinstance(weight_vec, LispVector):
        raise LispError("%s: weights must be a vector" % name)
    if len(weight_vec.items) != n_expected:
        raise LispError("%s: weights must be the same length as y" % name)
    weights = [numeric_value(v) for v in weight_vec.items.tolist()]
    for w in weights:
        if w < 0:
            raise LispError("%s: weights must not be negative (got %r)" % (name, w))
    return weights


def group_numbers(value, n, who, option="groups"):
    """A :groups or :times option -- a vector or a list with a value for
    each row: a number, a string, or a date, such as a loan's ID or a month
    -- as (numbers, values): each row's group as a number from 0, in the
    order the groups first appear, and each group's value, in that order."""
    if isinstance(value, LispVector):
        items = value.items.tolist()
    elif isinstance(value, Pair) or value is NIL:
        items = pairs_to_list(value)
    else:
        raise LispError("%s: :%s must be a vector or a list, with a value for each row, not %s"
                        % (who, option, to_display_string(value)))
    if len(items) != n:
        raise LispError("%s: :%s must have a value for each row (%d), not %d" % (who, option, n, len(items)))
    number_of = {}
    numbers = np.empty(n, dtype=np.int64)
    for row, item in enumerate(items):
        if not isinstance(item, (int, float, str, LispDate)) or isinstance(item, bool) or item != item:
            raise LispError("%s: each of the :%s must be a number, a string, or a date, not %s"
                            % (who, option, to_display_string(item)))
        numbers[row] = number_of.setdefault(item, len(number_of))
    return numbers, list(number_of)


def _optional_groups(value, n, who):
    """A fitting function's :groups option (see group_numbers) as each row's
    group number, or None if it wasn't given."""
    if value is None:
        return None
    numbers, values = group_numbers(value, n, who)
    if len(values) < 2:
        raise LispError("%s: :groups must have at least 2 groups, for the standard errors to allow for them" % who)
    return numbers


def fit_flat(x_arg, y_arg, weight_vec, groups_arg, fit, who):
    """A model of a straight line (or plane): x, y, and the weights as
    linear-regression takes them, and :groups (_optional_groups), fit by
    fit(columns, ys, weights, groups) -- fit_linear, fit_lad, or another.
    `who` is the function to name in an error message."""
    y_vec, y_name = _coerce_y(y_arg, who)
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    weights = _optional_weights(weight_vec, len(ys), who)
    model = fit(columns, ys, weights, _optional_groups(groups_arg, len(ys), who))
    model.predictor_names = names
    model.y_name = y_name
    return model


def flat_arguments(arguments, keywords, who):
    """A flat model's optional arguments: the weights, then its keyword
    options -- :groups, and the keywords -- as a dict."""
    positional, options = positional_and_keywords(arguments, 1, ["groups"] + keywords, who)
    return (positional[0] if positional else None), options


def linear_regression_fn(x_arg, y_arg, *arguments):
    """(linear-regression x y [weights] [:groups g]) -- a least-squares fit:
    see fit_linear."""
    who = "linear-regression"
    weight_vec, options = flat_arguments(arguments, [], who)
    return fit_flat(x_arg, y_arg, weight_vec, options.get("groups"), fit_linear, who)


def lad_regression_fn(x_arg, y_arg, *arguments):
    """(lad-regression x y [weights] [:groups g]) -- a least absolute
    deviation fit: see fit_lad."""
    who = "lad-regression"
    weight_vec, options = flat_arguments(arguments, [], who)
    return fit_flat(x_arg, y_arg, weight_vec, options.get("groups"), fit_lad, who)


def quantile_regression_fn(x_arg, y_arg, quantile, *arguments):
    """(quantile-regression x y quantile [weights] [:groups g]) -- the fit
    with `quantile` of the points below it: see fit_quantile."""
    who = "quantile-regression"
    quantile = _quantile_argument(quantile, who)
    weight_vec, options = flat_arguments(arguments, [], who)

    def fit(columns, ys, weights, groups):
        return fit_quantile(columns, ys, quantile, weights, groups)

    return fit_flat(x_arg, y_arg, weight_vec, options.get("groups"), fit, who)


def _quantile_argument(quantile, who):
    if not isinstance(quantile, (int, float)) or isinstance(quantile, bool) or not 0 < quantile < 1:
        raise LispError("%s: the quantile must be a number between 0 and 1, 0.9 for the 90th percentile, not %s"
                        % (who, to_display_string(quantile)))
    return float(quantile)


def logistic_regression_fn(x_arg, y_arg, *arguments):
    """(logistic-regression x y [weights] [:floor f :ceiling c :groups g]) --
    a logistic model: see fit_logistic_between."""
    who = "logistic-regression"
    weight_vec, options = flat_arguments(arguments, ["floor", "ceiling"], who)
    floor, ceiling = floor_and_ceiling(options, who)

    def fit(columns, ys, weights, groups):
        return fit_logistic_between(columns, ys, weights, floor, ceiling, who, groups)

    return fit_flat(x_arg, y_arg, weight_vec, options.get("groups"), fit, who)


def _is_model(x):
    return isinstance(x, (LispModel, LispSplineModel))


def _is_probabilistic(model):
    """True for models whose .predict() returns a probability: a logistic or
    spline-logistic model whose floor and ceiling are between 0 and 1. (One
    with a floor or ceiling outside them predicts a number between them.)"""
    inner = model.inner_model if isinstance(model, LispSplineModel) else model
    return inner.is_probability()


def model_predict(model, x_arg):
    if not _is_model(model):
        raise LispError("model-predict: not a model: %r" % (model,))
    if isinstance(x_arg, Pair) or x_arg is NIL:
        xs = [numeric_value(v) for v in pairs_to_list(x_arg)]
    else:
        xs = [numeric_value(x_arg)]
    if len(xs) != model.k:
        raise LispError(
            "model-predict: model has %d predictor(s), but %d given"
            % (model.k, len(xs)))
    return model.predict(xs)


def model_slope(model):
    if isinstance(model, LispSplineModel):
        raise LispError("model-slope: not available for a spline model; use model-report instead")
    if not isinstance(model, LispModel):
        raise LispError("model-slope: not a model: %r" % (model,))
    if len(model.coefficients) != 1:
        raise LispError(
            "model-slope: this model has %d predictors; use model-coefficients instead"
            % len(model.coefficients))
    return model.coefficients[0]


def model_coefficients(model):
    if isinstance(model, LispSplineModel):
        raise LispError("model-coefficients: not available for a spline model; use model-report instead")
    if not isinstance(model, LispModel):
        raise LispError("model-coefficients: not a model: %r" % (model,))
    return LispVector(list(model.coefficients))


def _names(model):
    """The model's predictor names, or x1, x2, ... if it has none."""
    return model.predictor_names or ["x%d" % (i + 1) for i in range(model.k)]


def coefficient_rows(model, terms):
    """For a LispModel, one (term, estimate, std_error, statistic, p_value)
    tuple for the intercept and each coefficient. `terms` names the
    coefficients."""
    std_errors = model.stats.get("std_errors") or [float("nan")] * (len(terms) + 1)
    test = model.stats.get("test", "t")
    rows = []
    for term, estimate, std_error in zip(["intercept"] + list(terms),
                                         [model.intercept] + list(model.coefficients), std_errors):
        statistic = estimate / std_error if std_error and std_error == std_error else float("nan")
        rows.append((term, estimate, std_error, statistic,
                     two_sided_p_value(statistic, test, model.stats.get("degrees_of_freedom"))))
    return rows


def coefficient_table_lines(model, terms):
    """model-report's coefficient table, one line per term."""
    rows = coefficient_rows(model, terms)
    width = max(len("term"), max(len(r[0]) for r in rows))
    statistic_name = model.stats.get("test", "t") + " value"
    lines = ["  %-*s  %12s  %12s  %9s  %9s" % (width, "term", "coefficient", "std error", statistic_name, "p value")]
    for term, estimate, std_error, statistic, p_value in rows:
        lines.append("  %-*s  %12.6g  %12.6g  %9.4g  %9.3g" % (width, term, estimate, std_error, statistic, p_value))
    return lines


def model_report(model):
    """(model-report m) -- a text report of a fitted model: its equation, a
    table of coefficients with standard errors, t or z statistics, and
    p-values, and measures of fit."""
    if isinstance(model, LispSplineModel):
        return LispString("\n".join(_spline_report_lines(model)))
    if not isinstance(model, LispModel):
        raise LispError("model-report: not a model: %r" % (model,))
    names = _names(model)
    y_name = model.y_name or "y"
    terms = " + ".join("%.6g*%s" % (c, names[i]) for i, c in enumerate(model.coefficients))
    if model.kind == "linear":
        lines = ["Linear model:  %s = %.6g + %s" % (y_name, model.intercept, terms)]
    elif model.kind == "lad":
        lines = ["Least absolute deviation model:  %s = %.6g + %s" % (y_name, model.intercept, terms)]
    elif model.kind == "quantile":
        lines = ["Quantile regression model, for the %.6g quantile:  %s = %.6g + %s"
                 % (model.stats["quantile"], y_name, model.intercept, terms)]
    elif model.between_0_and_1():
        lines = ["Logistic model:  p(%s) = sigmoid(%.6g + %s)" % (y_name, model.intercept, terms)]
    else:
        lines = ["Logistic model, between %.6g and %.6g:  %s = %.6g + %.6g * sigmoid(%.6g + %s)"
                 % (model.floor, model.ceiling, ("p(%s)" if model.is_probability() else "%s") % y_name,
                    model.floor, model.ceiling - model.floor, model.intercept, terms)]
    lines.extend(coefficient_table_lines(model, names))
    lines.extend(fit_statistics_lines(model))
    return LispString("\n".join(lines))


def fit_statistics_lines(model):
    """The measures of fit at the end of model-report, for a LispModel, each
    beside a perfect model's and that of a model predicting the same for
    every row (measures_of_fit); then the number of iterations, n, and the
    number of groups the standard errors allow for, if it has them."""
    stats = model.stats
    if "measures" in stats:
        measures = measure_lines(stats["measures"])
    else:                                   # a model saved before there were measures_of_fit
        measures = ["  (saved by an older version, without its measures of fit: fit it again to see them)"]
    iterations = "  iterations       = %d (%s)" % (stats.get("iterations", 0), "converged" if stats.get("converged", True)
                                                   else "did NOT converge")
    end = ["  n                = %d" % stats["n"]]
    if "groups" in stats:
        end.append("  groups           = %d  (the standard errors allow for rows in the same group being alike)"
                   % stats["groups"])

    if model.kind == "linear":
        return measures + end
    if model.kind == "lad":
        return measures + [iterations] + end
    if model.kind == "quantile":
        below, on, above = stats["below_on_above"]
        quantile = stats["quantile"]
        return ["  quantile         = %.6g  (a point above the fit costs %.6g of its distance, below it %.6g)"
                % (quantile, quantile, 1 - quantile),
                "  points           = %d below the fit, %d on it, %d above it" % (below, on, above)] + \
            measures + [iterations] + end

    between = []
    fitted = stats.get("fitted", {})
    if fitted:
        for name, value in (("floor", model.floor), ("ceiling", model.ceiling)):
            if name in fitted:
                low, high = fitted[name]
                between.append("  %-16s = %.6g  (fitted; its 95%% range is %.6g to %.6g)" % (name, value, low, high))
            else:
                between.append("  %-16s = %.6g" % (name, value))
    elif model.is_probability() and not model.between_0_and_1():
        between = ["  floor, ceiling   = %.6g, %.6g  (the probability is between them)" % (model.floor, model.ceiling)]
    elif not model.is_probability():
        between = ["  floor, ceiling   = %.6g, %.6g  (%d y below the floor, and %d above the ceiling, taken as at them)"
                   % (model.floor, model.ceiling, stats.get("below_floor", 0), stats.get("above_ceiling", 0)),
                   "  (the measures below are of y rescaled to (y - floor) / (ceiling - floor))"]
    if not stats.get("converged", True):
        iterations = ("  iterations       = %d (did NOT converge: a coefficient is growing without end -- the curve "
                      "comes ever closer to some of the points by getting steeper. Its predictions are near that "
                      "limit, but its coefficients and standard errors mean little)" % stats["iterations"])
    if not stats.get("y_is_0_or_1", True) and "groups" not in stats:
        end.append("  standard errors  = from the scatter of y about the fit, since y isn't all 0s and 1s")
    return between + measures + [iterations] + end


def model_coefficient_table(model):
    """(model-coefficient-table m) -- the model's coefficients as a table,
    with columns term, coefficient, std_error, t_value (z_value for a
    logistic model), and p_value; the first row is the intercept. For a
    spline model, the terms are its expanded features (see model-report)."""
    if isinstance(model, LispSplineModel):
        inner, terms = model.inner_model, _spline_feature_labels(model.predictor_specs, _names(model))
    elif isinstance(model, LispModel):
        inner, terms = model, _names(model)
    else:
        raise LispError("model-coefficient-table: not a model: %r" % (model,))
    rows = coefficient_rows(inner, terms)
    statistic_name = inner.stats.get("test", "t") + "_value"
    columns = [("term", LispVector([LispString(r[0]) for r in rows]))]
    for j, column_name in enumerate(["coefficient", "std_error", statistic_name, "p_value"], start=1):
        columns.append((column_name, LispVector(np.array([r[j] for r in rows], dtype=np.float64))))
    return list_to_pairs([Pair(LispString(n), v) for n, v in columns])


def predict_all(model, columns):
    """The model's predictions for every row at once, as a numpy array.
    `columns` is a list of predictor columns (lists of numbers)."""
    if isinstance(model, LispSplineModel):
        return predict_all(model.inner_model, _spline_expand_columns(columns, model.predictor_specs))
    X = np.column_stack([np.asarray(col, dtype=np.float64) for col in columns])
    z = model.intercept + X @ np.asarray(model.coefficients, dtype=np.float64)
    return model.floor + (model.ceiling - model.floor) * _sigmoid_vec(z) if model.kind == "logistic" else z


def evaluation_data(model, x_arg, y_arg, name):
    """(predictions, ys) numpy arrays for model-evaluate / model-lift-table."""
    if not _is_model(model):
        raise LispError("%s: not a model: %r" % (name, model))
    y_vec, _ = _coerce_y(y_arg, name)
    columns, _ = _predictor_columns(x_arg, len(y_vec.items))
    if len(columns) != model.k:
        raise LispError("%s: model has %d predictor(s), but %d given" % (name, model.k, len(columns)))
    ys = np.array([numeric_value(v) for v in y_vec.items.tolist()], dtype=np.float64)
    if len(ys) == 0:
        raise LispError("%s: no data to evaluate" % name)
    return predict_all(model, columns), ys


def model_evaluate(model, x_arg, y_arg):
    """(model-evaluate m x y) -- how well a fitted model predicts other data
    (typically data held out from fitting), as a text report: the measures
    of measures_of_fit, each beside a perfect model's and that of a model
    predicting the same for every row (from this data: its average, say) --
    R-squared, RMSE, and MAE for a model of a number; log-likelihood,
    pseudo R-squared, and AUC for one of a probability (with R-squared,
    RMSE, and MAE first, if y is shares, not 0s and 1s); and, for 0s and
    1s, accuracy."""
    predictions, ys = evaluation_data(model, x_arg, y_arg, "model-evaluate")
    n = len(ys)
    probability = _is_probabilistic(model)
    lines = ["Evaluation on %d held-out observation(s):" % n]
    lines += measure_lines(measures_of_fit(predictions, ys, np.ones(n), "probability" if probability
                                           else "least squares"))
    if probability and is_all_0_or_1(ys):
        # How often a prediction of 0.5 or more went with a 1, and one of less
        # with a 0 -- beside always predicting the commoner of the two, which,
        # for something rare, is right nearly all the time.
        accuracy = float(((predictions >= 0.5) == (ys >= 0.5)).mean())
        commoner = max(float(ys.mean()), 1 - float(ys.mean()))
        lines.append("  %-16s = %-10.6g (perfect: 1; predicting the commoner outcome for every row: %.6g; "
                     "a prediction of 0.5 or more counts as a 1)" % ("accuracy", accuracy, commoner))
    return LispString("\n".join(lines))


def model_residuals(model, x_arg, y_arg):
    """(model-residuals m x y) -- y minus the model's prediction, for each
    row, as a vector. After a lad-regression, the outliers it set aside are
    the rows with the largest residuals."""
    predictions, ys = evaluation_data(model, x_arg, y_arg, "model-residuals")
    return to_vector(ys - predictions)


def model_lift_table(model, x_arg, y_arg, n_bins=10, weight_vec=None):
    """(model-lift-table m x y [bins weights]) -- how well a model ranks
    rows: sorted by prediction, highest first, and split into `bins`
    groups of (nearly) equal row count -- 10 by default, i.e. deciles. One
    row per group:
      bin               1 holds the highest predictions
      rows              the number of rows in the group
      weight            their total weight (the row count, without weights)
      mean_predicted    the group's average prediction
      mean_actual       the group's average actual y
      lift              mean_actual divided by the overall average y
      cumulative_share  the fraction of all y (e.g. of all payoffs) in
                        groups 1 through this one
    The averages are weighted when weights are given."""
    predictions, ys = evaluation_data(model, x_arg, y_arg, "model-lift-table")
    weights = np.ones(len(ys)) if weight_vec is None or weight_vec is NIL else \
        np.asarray(_optional_weights(weight_vec, len(ys), "model-lift-table"), dtype=np.float64)
    n_bins = int(n_bins)
    if not 1 <= n_bins <= len(ys):
        raise LispError("model-lift-table: bins must be between 1 and the number of rows (%d)" % len(ys))
    order = np.argsort(-predictions, kind="stable")
    groups = np.array_split(order, n_bins)
    overall = float((weights * ys).sum() / weights.sum())
    total_y = float((weights * ys).sum())
    rows, weight, mean_predicted, mean_actual, share = [], [], [], [], []
    captured = 0.0
    for group in groups:
        w = weights[group]
        rows.append(len(group))
        weight.append(w.sum())
        mean_predicted.append((w * predictions[group]).sum() / w.sum())
        mean_actual.append((w * ys[group]).sum() / w.sum())
        captured += (w * ys[group]).sum()
        share.append(captured / total_y if total_y else float("nan"))
    lift = [a / overall if overall else float("nan") for a in mean_actual]
    columns = [("bin", np.arange(1, n_bins + 1)), ("rows", np.array(rows)),
               ("weight", np.array(weight)), ("mean_predicted", np.array(mean_predicted)),
               ("mean_actual", np.array(mean_actual)), ("lift", np.array(lift)),
               ("cumulative_share", np.array(share))]
    return list_to_pairs([Pair(LispString(n), to_vector(v)) for n, v in columns])


# ---------------------------------------------------------------------------
# Spline regression: a piecewise-linear hinge basis, no external dependencies
# ---------------------------------------------------------------------------
#
# A simple, hand-rolled way to let a model bend: for each predictor x,
# pick a handful of "knot" locations (by default, evenly spaced quantiles
# of that predictor's own values -- or exact locations the user supplies)
# and add a hinge feature max(0, x - t) for each knot t, alongside the
# plain linear term. A predictor can also be marked "categorical" (for a
# variable like home-type, coded e.g. 0=own/1=rent) instead, in which case
# it's expanded into 0/1 indicator columns -- one per non-baseline value --
# rather than hinge features, since hinges/knots don't mean anything for a
# handful of discrete codes. Fitting the expanded basis is then just an
# ordinary least-squares, LAD, or logistic regression -- reusing fit_linear,
# fit_lad, or fit_logistic_between exactly as they are.

class _PredictorSpec:
    """How one predictor is expanded into features: a set of knots, for
    hinge functions (mode "spline") or for a restricted cubic spline's
    curved terms (mode "smooth"), or a set of categories to dummy-encode
    (mode "categorical", one 0/1 indicator column per non-baseline
    category)."""

    def __init__(self, mode, knots=None, categories=None, n_distinct=None):
        self.mode = mode
        self.knots = knots or []
        self.categories = categories or []   # sorted; categories[0] is baseline
        self.n_distinct = n_distinct

    def n_features(self):
        if self.mode == "spline":
            return len(self.knots) + 1          # the predictor, and a hinge at each knot
        if self.mode == "smooth":
            return len(self.knots) - 1          # the predictor, and a curved term for each knot but the last two
        return len(self.categories) - 1


def _choose_knots(column, n_knots):
    """Pick n_knots knot locations at roughly evenly spaced quantiles of
    column's values, staying strictly inside the data range (a knot at
    the max value would produce an all-zero, useless hinge column)."""
    if n_knots <= 0:
        return []
    values = sorted(column)
    n = len(values)
    if n < 3:
        return []  # too little data to place an interior knot meaningfully
    knots = []
    for i in range(1, n_knots + 1):
        q = i / (n_knots + 1)
        idx = int(round(q * (n - 1)))
        idx = min(max(idx, 1), n - 2)  # keep strictly interior
        knots.append(values[idx])
    return _dedupe_preserve_order(knots)


def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def _resolve_predictor_spec(spec, column, name, who, smooth=False):
    """Turn one raw per-predictor argument into a _PredictorSpec:
      - the symbol 'categorical  -> dummy-encode the distinct values seen
      - a Lisp list of numbers   -> use exactly those knot locations
      - a plain non-negative int -> auto-pick that many knots by quantile
    """
    n_distinct = len(set(column))
    if isinstance(spec, Symbol) and spec == "categorical":
        categories = sorted(set(column))
        if len(categories) < 2:
            raise LispError(
                "%s: %s marked categorical, but only %d distinct "
                "value(s) were found (need at least 2)" % (who, name, len(categories)))
        return _PredictorSpec("categorical", categories=categories, n_distinct=n_distinct)

    if isinstance(spec, Pair) or spec is NIL:
        knots = _dedupe_preserve_order(sorted(numeric_value(v) for v in pairs_to_list(spec)))
    else:
        count = int(spec)
        if count < 0:
            raise LispError("%s: knot counts must not be negative" % who)
        knots = _choose_knots(column, count)

    if knots and n_distinct <= 3:
        # A knot among only 2 or 3 distinct values can make a hinge column
        # duplicate another column, making the fit fail with a confusing
        # "collinear" error -- so say what to do instead, up front.
        raise LispError(
            "%s: %s has only %d distinct value(s), so hinge "
            "knots aren't meaningful there (and can make the fit singular). "
            "Use a knot count of 0 (stay linear) or mark it 'categorical "
            "instead." % (who, name, n_distinct))
    if smooth and knots:
        if len(knots) < 3:
            raise LispError("%s: a smooth spline needs at least 3 knots, and %s has %d -- give it more, or 0 for a "
                            "straight line" % (who, name, len(knots)))
        return _PredictorSpec("smooth", knots=knots, n_distinct=n_distinct)
    return _PredictorSpec("spline", knots=knots, n_distinct=n_distinct)


def _resolve_all_predictor_specs(max_knots, columns, names=None, who="spline-regression", smooth=False):
    """Turn the `max-knots` argument into one _PredictorSpec per predictor.
    `max_knots` is either one setting for every predictor -- a knot count or
    'categorical -- or a list with one setting per predictor, each a knot
    count, 'categorical, or a list of knot locations. With exactly one
    predictor, a flat list of numbers means those knot locations.

    `names` (optional): the predictors' names, for error messages and the
    report; `who`, the function to name in an error message. smooth: a
    predictor with knots gets a restricted cubic spline's curved terms
    (restricted_cubic_terms) in place of hinges."""
    k = len(columns)
    if names is None:
        names = ["x%d" % (i + 1) for i in range(k)]

    def is_knot_value(v):
        return (isinstance(v, (int, float)) and not isinstance(v, bool)) or isinstance(v, LispDate)

    if isinstance(max_knots, Pair) or max_knots is NIL:
        items = pairs_to_list(max_knots)
        all_knot_values = items and all(is_knot_value(v) for v in items)
        if k == 1 and all_knot_values:
            # A flat list of numbers/dates with one predictor: explicit knots.
            return [_resolve_predictor_spec(list_to_pairs(items), columns[0], names[0], who, smooth)]
        if len(items) != k:
            raise LispError(
                "%s: the knot-spec list must have one entry per "
                "predictor (%d), got %d" % (who, k, len(items)))
        return [_resolve_predictor_spec(spec, col, name, who, smooth)
                for spec, col, name in zip(items, columns, names)]

    return [_resolve_predictor_spec(max_knots, col, name, who, smooth)
            for col, name in zip(columns, names)]


def _category_text(category):
    """A category as a report or message shows it: a number to 6
    significant digits, and anything else (text, a date) as it is."""
    if isinstance(category, (int, float)) and not isinstance(category, bool):
        return "%.6g" % category
    return str(category)


def _spline_expand_value(v, spec, name):
    if spec.mode == "categorical":
        if v not in spec.categories:
            raise LispError(
                "spline model: %s value %r was not one of the categories "
                "seen while fitting (%s)" % (
                    name, v, ", ".join(_category_text(c) for c in spec.categories)))
        return [1.0 if v == cat else 0.0 for cat in spec.categories[1:]]
    if spec.mode == "smooth":
        return [v] + restricted_cubic_terms(v, spec.knots)
    row = [v]
    for t in spec.knots:
        row.append(max(0.0, v - t))
    return row


def restricted_cubic_terms(v, knots):
    """The curved terms of a restricted cubic spline (a "natural" spline) at
    v, for its knots t1 < t2 < ... < tk, k being at least 3: one for each
    knot but the last two,

        term_j(v) = ( (v - tj)+^3
                      - (v - t(k-1))+^3 * (tk - tj) / (tk - t(k-1))
                      + (v - tk)+^3 * (t(k-1) - tj) / (tk - t(k-1)) ) / (tk - t1)^2

    where (u)+ is u if it's above 0, and 0 if not. With the predictor
    itself, these make a curve of cubic pieces that join smoothly at the
    knots -- with no corners, as hinges have -- and is a straight line below
    the first knot and above the last: past tk, the parts of each term that
    are squared and cubed in v cancel, leaving a straight line. (Stone and
    Koo's, as Harrell gives it; dividing by (tk - t1)^2 keeps the terms in
    the predictor's own units.)"""
    def cube(u):
        return u ** 3 if u > 0 else 0.0
    last, before_last = knots[-1], knots[-2]
    return [(cube(v - t) - cube(v - before_last) * (last - t) / (last - before_last)
             + cube(v - last) * (before_last - t) / (last - before_last)) / (last - knots[0]) ** 2
            for t in knots[:-2]]


def _spline_expand_row(values, specs, names=None):
    """values: one value per original predictor. Returns the expanded
    feature row (hinge features and/or 0/1 category indicators). names, the
    predictors' names, if they have them, are for error messages."""
    row = []
    for i, (v, spec) in enumerate(zip(values, specs)):
        row.extend(_spline_expand_value(v, spec, names[i] if names else "x%d" % (i + 1)))
    return row


def _spline_expand_columns(columns, specs):
    """columns: one column (list of n values) per original predictor.
    Returns the same expansion as _spline_expand_row, but column-wise."""
    n = len(columns[0]) if columns else 0
    rows = [_spline_expand_row([col[i] for col in columns], specs) for i in range(n)]
    n_features = len(rows[0]) if rows else 0
    return [[row[j] for row in rows] for j in range(n_features)]


class LispSplineModel:
    """A piecewise-linear spline model: an ordinary linear, LAD, or logistic
    regression fitted to an expanded set of features -- hinge functions at
    knots, and/or 0/1 indicators for categories -- which lets the fitted
    curve bend. See _resolve_predictor_spec and _spline_expand_columns."""

    KINDS = {"linear": "spline", "lad": "spline-lad", "quantile": "spline-quantile",
             "logistic": "spline-logistic"}             # by the inner model's kind

    def __init__(self, inner_model, predictor_specs, k, predictor_names=None, y_name=None):
        self.inner_model = inner_model          # a LispModel fit on the expanded basis
        self.predictor_specs = predictor_specs  # list of k _PredictorSpec
        self.k = k                              # number of original predictors
        self.kind = self.KINDS[inner_model.kind]
        # Names as in LispModel; None if unnamed.
        self.predictor_names = predictor_names   # list of str, one per ORIGINAL predictor, or None
        self.y_name = y_name                     # str, or None

    def predict(self, values):
        return self.inner_model.predict(_spline_expand_row(values, self.predictor_specs, self.predictor_names))

    def __repr__(self):
        total_knots = sum(len(s.knots) for s in self.predictor_specs if s.mode in ("spline", "smooth"))
        n_categorical = sum(1 for s in self.predictor_specs if s.mode == "categorical")
        if n_categorical:
            return "#<%s-model predictors=%d knots=%d categorical=%d>" % (
                self.kind, self.k, total_knots, n_categorical)
        return "#<%s-model predictors=%d knots=%d>" % (self.kind, self.k, total_knots)


def model_data(model):
    """A fitted model as plain data -- a dict of strings, numbers, lists,
    and dicts -- for save-variables to write as JSON; model_from_data makes
    the model again. A field that's None is left out."""
    if isinstance(model, LispSplineModel):
        specs = []
        for spec in model.predictor_specs:
            fields = {"mode": spec.mode, "knots": list(spec.knots), "categories": list(spec.categories)}
            if spec.n_distinct is not None:
                fields["n-distinct"] = spec.n_distinct
            specs.append(fields)
        data = {"kind": model.kind, "k": model.k, "inner-model": model_data(model.inner_model),
                "predictor-specs": specs}
    else:
        data = {"kind": model.kind, "coefficients": [float(c) for c in model.coefficients],
                "intercept": float(model.intercept), "stats": dict(model.stats)}
        if model.kind == "logistic" and not model.between_0_and_1():
            data["floor"], data["ceiling"] = model.floor, model.ceiling
    if model.predictor_names is not None:
        data["predictor-names"] = list(model.predictor_names)
    if model.y_name is not None:
        data["y-name"] = model.y_name
    return data


def model_from_data(data):
    """The model that model_data describes."""
    names = data.get("predictor-names")
    if "inner-model" in data:
        specs = [_PredictorSpec(spec["mode"], spec["knots"], spec["categories"], spec.get("n-distinct"))
                 for spec in data["predictor-specs"]]
        return LispSplineModel(model_from_data(data["inner-model"]), specs, data["k"], names, data.get("y-name"))
    return LispModel(data["kind"], data["coefficients"], data["intercept"], data["stats"], names, data.get("y-name"),
                     data.get("floor", 0.0), data.get("ceiling", 1.0))


def _spline_feature_labels(specs, names):
    """One label per expanded feature, in _spline_expand_value's order: the
    predictor's name for its linear term, "name (knot T)" for each hinge,
    and "name = category" for each category indicator."""
    labels = []
    for name, spec in zip(names, specs):
        if spec.mode == "categorical":
            for cat in spec.categories[1:]:
                labels.append("%s = %s" % (name, _category_text(cat)))
        elif spec.mode == "smooth":
            labels.append(name)
            for t in spec.knots[:-2]:
                labels.append("%s (curve at knot %.6g)" % (name, t))
        else:
            labels.append(name)
            for t in spec.knots:
                labels.append("%s (knot %.6g)" % (name, t))
    return labels


def _spline_report_lines(model):
    names = model.predictor_names or ["x%d" % (i + 1) for i in range(model.k)]
    y_name = model.y_name or "y"
    lines = []
    shape = ("Smooth (restricted cubic)" if any(spec.mode == "smooth" for spec in model.predictor_specs)
             else "Piecewise-linear")
    if model.kind == "spline-logistic" and model.inner_model.between_0_and_1():
        lines.append("%s spline model, with a logistic link, predicting %s:" % (shape, y_name))
    elif model.kind == "spline-logistic":
        lines.append("%s spline model, with a logistic link between %.6g and %.6g, predicting %s:"
                     % (shape, model.inner_model.floor, model.inner_model.ceiling, y_name))
    elif model.kind == "spline-lad":
        lines.append("%s spline model, fit by least absolute deviation, predicting %s:" % (shape, y_name))
    elif model.kind == "spline-quantile":
        lines.append("%s spline model, fit to the %.6g quantile, predicting %s:"
                     % (shape, model.inner_model.stats["quantile"], y_name))
    else:
        lines.append("%s spline model, predicting %s:" % (shape, y_name))
    lines.append("  predictors = %d" % model.k)
    for name, spec in zip(names, model.predictor_specs):
        if spec.mode == "categorical":
            cats = ", ".join(_category_text(c) for c in spec.categories)
            lines.append("  %s: categorical -- categories %s (baseline %s)"
                          % (name, cats, _category_text(spec.categories[0])))
        else:
            knot_text = ", ".join("%.6g" % t for t in spec.knots) if spec.knots else "(none -- plain linear)"
            hint = ""
            if spec.n_distinct is not None and spec.n_distinct <= 3:
                hint = "  [only %d distinct value(s) seen -- consider 'categorical]" % spec.n_distinct
            lines.append("  %s: knots %s%s%s" % (name, knot_text, ", smooth" if spec.mode == "smooth" else "", hint))
    lines.append("")
    lines.append("Coefficients (on the expanded basis):")
    lines.extend(coefficient_table_lines(model.inner_model, _spline_feature_labels(model.predictor_specs, names)))
    lines.append("")
    lines.append("Fit:")
    lines.extend(fit_statistics_lines(model.inner_model))
    return lines


def fit_spline(x_arg, y_arg, max_knots, weight_vec, options, fit, who):
    """A spline model: each predictor expanded as max-knots says (see
    _resolve_all_predictor_specs) -- into hinge functions at knots, or a
    smooth curve's terms (if options has :smooth), or 0/1 indicators for
    categories -- and the expanded columns fit by fit(columns, ys, weights,
    groups): fit_linear, fit_lad, or another. x, y, the weights, and
    options' :groups are as for linear-regression; `who` is the function to
    name in an error message."""
    y_vec, y_name = _coerce_y(y_arg, who)
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    if not ys:
        raise LispError("%s: no data to fit" % who)
    weights = _optional_weights(weight_vec, len(ys), who)
    groups = _optional_groups(options.get("groups"), len(ys), who)
    predictor_specs = _resolve_all_predictor_specs(max_knots, columns, names, who,
                                                   is_true(options.get("smooth", False)))
    expanded_columns = _spline_expand_columns(columns, predictor_specs)
    return LispSplineModel(fit(expanded_columns, ys, weights, groups), predictor_specs, len(columns), names, y_name)


def spline_arguments(arguments, keywords, who):
    """A spline function's optional arguments: max-knots (3 unless given)
    and weights, in that order, then its keyword options -- :smooth,
    :groups, and the keywords -- as a dict."""
    positional, options = positional_and_keywords(arguments, 2, ["smooth", "groups"] + keywords, who)
    if any(isinstance(a, bool) for a in positional):
        raise LispError("%s: it has no logistic? argument now: spline-logistic fits a spline with a logistic link"
                        % who)
    max_knots = positional[0] if positional else 3
    weight_vec = positional[1] if len(positional) > 1 else None
    return max_knots, weight_vec, options


def spline_regression_fn(x_arg, y_arg, *arguments):
    """(spline-regression x y [max-knots weights] [:smooth #t :groups g]) --
    fit a spline model by least squares. x and y are as for
    linear-regression. max-knots says how to expand each predictor (see
    _resolve_all_predictor_specs); :smooth #t makes the curve smooth
    (restricted_cubic_terms), in place of straight pieces."""
    who = "spline-regression"
    max_knots, weight_vec, options = spline_arguments(arguments, [], who)
    return fit_spline(x_arg, y_arg, max_knots, weight_vec, options, fit_linear, who)


def spline_logistic_fn(x_arg, y_arg, *arguments):
    """(spline-logistic x y [max-knots weights] [:floor f :ceiling c :smooth #t
    :groups g]) -- fit a spline model with a logistic link:
    spline-regression's expansion of the predictors, fit as
    logistic-regression fits (see fit_logistic_between), so the curve can
    bend, and stays between the floor and the ceiling (0 and 1, unless
    they're given)."""
    who = "spline-logistic"
    max_knots, weight_vec, options = spline_arguments(arguments, ["floor", "ceiling"], who)
    floor, ceiling = floor_and_ceiling(options, who)

    def fit(columns, ys, weights, groups):
        return fit_logistic_between(columns, ys, weights, floor, ceiling, who, groups)

    return fit_spline(x_arg, y_arg, max_knots, weight_vec, options, fit, who)


def spline_quantile_fn(x_arg, y_arg, quantile, *arguments):
    """(spline-quantile x y quantile [max-knots weights] [:smooth #t :groups
    g]) -- fit a spline model to a quantile: spline-regression's expansion
    of the predictors, fit as quantile-regression fits, so the curve can
    bend, with `quantile` of the points below it."""
    who = "spline-quantile"
    quantile = _quantile_argument(quantile, who)
    max_knots, weight_vec, options = spline_arguments(arguments, [], who)

    def fit(columns, ys, weights, groups):
        return fit_quantile(columns, ys, quantile, weights, groups, who=who)

    return fit_spline(x_arg, y_arg, max_knots, weight_vec, options, fit, who)


def spline_lad_fn(x_arg, y_arg, *arguments):
    """(spline-lad x y [max-knots weights] [:smooth #t :groups g]) -- fit a
    spline model by least absolute deviation: as spline-regression does, but
    making the sum of the absolute residuals smallest (fit_lad) rather than
    the sum of their squares, so a few outliers barely move the curve."""
    who = "spline-lad"
    max_knots, weight_vec, options = spline_arguments(arguments, [], who)
    return fit_spline(x_arg, y_arg, max_knots, weight_vec, options, fit_lad, who)


def suggest_knots_fn(x_vec, y_vec, window, n):
    """(suggest-knots x y window n) -- up to n x-values where y bends most
    sharply, sorted, ready to pass to spline-regression as knot locations:
    (spline-regression x y (suggest-knots x y 5 2)).

    Method: average y at each distinct x value; estimate the curve's second
    derivative at each point; smooth it with a moving average `window`
    points wide; then pick the points with the largest |second derivative|,
    at least `window` points apart so each is a different bend."""
    if not isinstance(x_vec, LispVector) or not isinstance(y_vec, LispVector):
        raise LispError("suggest-knots: x and y must be vectors")
    if len(x_vec.items) != len(y_vec.items):
        raise LispError("suggest-knots: x and y must be the same length")

    window = int(window)
    n = int(n)
    if window < 1:
        raise LispError("suggest-knots: window must be a positive integer")
    if n < 0:
        raise LispError("suggest-knots: n must not be negative")
    if n == 0:
        return NIL

    # Average y at each distinct x. Real data often has many rows at the same
    # x, and the second derivative needs distinct neighboring x values;
    # `window` counts steps along this curve, not rows.
    pairs = sorted(zip(x_vec.items.tolist(), y_vec.items.tolist()), key=lambda p: numeric_value(p[0]))
    groups = {}
    order = []
    for raw_xi, raw_yi in pairs:
        key = numeric_value(raw_xi)
        if key not in groups:
            groups[key] = {"raw_x": raw_xi, "ys": []}
            order.append(key)
        groups[key]["ys"].append(numeric_value(raw_yi))

    raw_x = [groups[k]["raw_x"] for k in order]
    xs = list(order)
    ys = [sum(groups[k]["ys"]) / len(groups[k]["ys"]) for k in order]
    m = len(xs)
    if m < 3:
        raise LispError(
            "suggest-knots: need at least 3 distinct x values to estimate curvature "
            "(found %d)" % m)

    # Second derivative at each interior point i, allowing uneven spacing:
    #   f''(x_i) ~= 2 * [ (y_{i+1}-y_i)/(x_{i+1}-x_i) - (y_i-y_{i-1})/(x_i-x_{i-1}) ]
    #               / (x_{i+1} - x_{i-1})
    # (the usual (y_{i+1} - 2y_i + y_{i-1}) / h^2 when spacing is even).
    raw_d2 = [0.0] * m
    for i in range(1, m - 1):
        h1 = xs[i] - xs[i - 1]
        h2 = xs[i + 1] - xs[i]
        raw_d2[i] = 2.0 * ((ys[i + 1] - ys[i]) / h2 - (ys[i] - ys[i - 1]) / h1) / (xs[i + 1] - xs[i - 1])

    # Centered moving average of the second-derivative sequence.
    half_before = window // 2
    half_after = window - 1 - half_before
    smoothed = [0.0] * m
    for i in range(1, m - 1):
        lo = max(1, i - half_before)
        hi = min(m - 2, i + half_after)
        segment = raw_d2[lo:hi + 1]
        smoothed[i] = sum(segment) / len(segment)

    # Greedily take the largest-|smoothed-second-derivative| points,
    # skipping any candidate within `window` (by index) of one already
    # chosen.
    candidates = sorted(range(1, m - 1), key=lambda i: abs(smoothed[i]), reverse=True)
    selected = []
    for i in candidates:
        if smoothed[i] == 0.0:
            continue
        if any(abs(i - j) < window for j in selected):
            continue
        selected.append(i)
        if len(selected) == n:
            break

    selected.sort()
    return list_to_pairs([raw_x[i] for i in selected])


# ---------------------------------------------------------------------------
# Cross-validation: how well a model predicts data it wasn't fit to
# ---------------------------------------------------------------------------

def _some_rows(value, rows):
    """x or y (a vector, a (name . vector) pair, or a list of either) with
    only the given rows of each vector, in the same shape."""
    if isinstance(value, LispVector):
        return LispVector(value.items[rows])
    if isinstance(value, Pair) and isinstance(value.cdr, LispVector):
        return Pair(value.car, LispVector(value.cdr.items[rows]))
    if isinstance(value, Pair):
        return list_to_pairs([_some_rows(item, rows) for item in pairs_to_list(value)])
    raise LispError("cross-validate: x and y must be vectors, (name . vector) pairs, or lists of them")


def cross_validate(fit, x_arg, y_arg, *options):
    """(cross-validate fit x y [:folds 5 :seed 1 :groups g]) or
    (cross-validate fit x y :times t [:last 1]) -- how well the models that
    `fit` makes predict data they weren't fit to. fit is a procedure of x
    and y that returns a model -- (lambda (x y) (spline-lad x y 3)), say.

    With folds (_folds_split), the rows are shuffled (by the seed, so the
    same each time) and dealt into `folds` groups -- with :groups, the
    groups, each kept whole: a loan's months, say; for each fold, a model is
    fit to the other rows, and its predictions of this fold's y are
    measured. With :times (_latest_times_split), a model is fit to the rows
    before the `last` latest times -- months, say -- and its predictions of
    theirs are measured.

    The result is a table with a row for each fold, or each latest time,
    and a last row, "all", for every row predicted:
      fold (or time)  1, 2, ..., (or the time) and "all"
      rows        how many rows were predicted
      groups      with :groups, how many groups they're in
      rmse        the root mean squared error
      mae         the mean absolute error
      log-loss    for a model of a probability: the mean of -log of the
                  chance it gave what happened (y log p + (1 - y) log(1 - p))
      quantile-loss  for a quantile model: the mean of check_loss, at its quantile
    The lower, the better the model predicts. A model that fits its own data
    closely, by bending to every point, may predict new data worse: this
    shows it, where the fit to the data it was fit to can't."""
    who = "cross-validate"
    options = keyword_options(options, ["folds", "seed", "groups", "times", "last"], who)
    y_vec, _ = _coerce_y(y_arg, who)
    n = len(y_vec.items)
    if "times" in options:
        label_name, fits, tests = _latest_times_split(options, n, who)
    else:
        label_name, fits, tests = _folds_split(options, n, who)

    predictions = np.empty(n)
    ys = np.empty(n)
    probability = quantile = None
    for description, kept, held_out in fits:
        try:
            model = apply_proc(fit, [_some_rows(x_arg, kept), _some_rows(y_arg, kept)])
            if not _is_model(model):
                raise LispError("%s: the fitting procedure must return a model, not %s"
                                % (who, to_display_string(model)))
            predicted, actual = evaluation_data(model, _some_rows(x_arg, held_out), _some_rows(y_arg, held_out), who)
        except LispError as e:       # (say which fit)
            message = str(e)[len(who) + 2:] if str(e).startswith(who + ": ") else str(e)
            raise LispError("%s: %s: %s" % (who, description, message))
        predictions[held_out], ys[held_out] = predicted, actual
        inner = model.inner_model if isinstance(model, LispSplineModel) else model
        probability = _is_probabilistic(model)
        quantile = inner.stats["quantile"] if inner.kind == "quantile" else None

    groups = group_numbers(options["groups"], n, who)[0] if "groups" in options else None

    def measures(rows):
        error = ys[rows] - predictions[rows]
        row = [len(rows)]
        if groups is not None:
            row.append(len(np.unique(groups[rows])))
        row += [math.sqrt(float(np.mean(error ** 2))), float(np.mean(np.abs(error)))]
        if probability:
            p = np.clip(predictions[rows], 1e-12, 1 - 1e-12)
            row.append(-float(np.mean(ys[rows] * np.log(p) + (1 - ys[rows]) * np.log(1 - p))))
        if quantile is not None:
            row.append(float(np.mean(check_loss(error, quantile))))
        return row

    table = [[label] + measures(rows) for label, rows in tests]
    table.append(["all"] + measures(np.concatenate([rows for _, rows in tests])))
    names = [label_name, "rows"] + (["groups"] if groups is not None else []) + ["rmse", "mae"] + \
        (["log-loss"] if probability else []) + (["quantile-loss"] if quantile is not None else [])
    columns = [(label_name, LispVector([LispString(row[0]) for row in table]))]
    columns += [(name, to_vector(np.array([row[i] for row in table]))) for i, name in enumerate(names) if i > 0]
    return list_to_pairs([Pair(LispString(name), vector) for name, vector in columns])


def _folds_split(options, n, who):
    """cross-validate's folds: ("fold", fits, tests), where `fits` has a
    (description, rows to fit to, rows to predict) for each fold, and
    `tests` a (label, rows) for each fold. The rows are in groups -- each
    row its own, unless :groups says otherwise -- and the groups are
    shuffled (by :seed) and each, in turn, given to the fold with the fewest
    rows so far. A group is kept whole, so the folds come out within about
    one group's size of each other; with every row its own group, the rows
    are dealt out like cards."""
    if "last" in options:
        raise LispError("%s: :last goes with :times, the time of each row" % who)
    groups = group_numbers(options["groups"], n, who)[0] if "groups" in options else np.arange(n)
    sizes = np.bincount(groups)
    number_of_groups = len(sizes)
    folds = options.get("folds", 5)
    if not isinstance(folds, int) or isinstance(folds, bool) or not 2 <= folds <= number_of_groups:
        raise LispError("%s: :folds must be a whole number from 2 to the number of %s (%d), not %s"
                        % (who, "groups" if "groups" in options else "rows", number_of_groups,
                           to_display_string(folds)))
    order = list(range(number_of_groups))
    random.Random(options.get("seed", 1)).shuffle(order)
    fold_of_group = np.empty(number_of_groups, dtype=np.int64)
    rows_in_fold = [0] * folds
    for group in order:
        fold = rows_in_fold.index(min(rows_in_fold))     # the fold with the fewest rows (the first, if a tie)
        fold_of_group[group] = fold
        rows_in_fold[fold] += sizes[group]
    fold_of = fold_of_group[groups]
    fits = [("fold %d" % (fold + 1), np.flatnonzero(fold_of != fold), np.flatnonzero(fold_of == fold))
            for fold in range(folds)]
    tests = [(str(fold + 1), held_out) for fold, (_, _, held_out) in enumerate(fits)]
    return "fold", fits, tests


def _latest_times_split(options, n, who):
    """cross-validate's split by time, as _folds_split's by folds: one fit,
    to the rows before the latest :last times (1, unless given) -- each
    row's time is in :times -- to predict their rows; and a test for each of
    those times. The times are numbers, strings, or dates, all of one kind:
    months as 202506, "2025-06", or a date."""
    for name in ("folds", "seed", "groups"):
        if name in options:
            raise LispError("%s: :%s is for dealing rows into folds; with :times, a model is fit once, to the "
                            "rows before the latest times" % (who, name))
    times, values = group_numbers(options["times"], n, who, "times")
    kinds = set("number" if isinstance(v, (int, float)) else "date" if isinstance(v, LispDate) else "string"
                for v in values)
    if len(kinds) > 1:
        raise LispError("%s: the :times must be all numbers, all strings, or all dates, not a mix" % who)
    last = options.get("last", 1)
    if not isinstance(last, int) or isinstance(last, bool) or not 1 <= last < len(values):
        raise LispError("%s: :last must be a whole number from 1 to one less than the number of times (%d), not %s"
                        % (who, len(values), to_display_string(last)))
    latest = sorted(range(len(values)), key=lambda number: values[number])[-last:]
    is_latest = np.isin(times, latest)
    fits = [("the fit to the rows before %s" % to_display_string(values[latest[0]]),
             np.flatnonzero(~is_latest), np.flatnonzero(is_latest))]
    tests = [(to_display_string(values[number]), np.flatnonzero(times == number)) for number in latest]
    return "time", fits, tests


def model_floor_or_ceiling(which):
    """model-floor or model-ceiling: a logistic model's floor or ceiling."""
    who = "model-" + which

    def get(model):
        inner = model.inner_model if isinstance(model, LispSplineModel) else model
        if not isinstance(inner, LispModel) or inner.kind != "logistic":
            raise LispError("%s: only a logistic or spline-logistic model has a %s, not %s"
                            % (who, which, to_display_string(model)))
        return inner.floor if which == "floor" else inner.ceiling
    get.__doc__ = ("(%s m) -- the %s of a logistic or spline-logistic model's curve: 0 or 1, unless it was "
                   "given, or fit with '%s 'fit." % (who, which, which))
    return get


def model_intercept(m):
    if isinstance(m, LispSplineModel):
        raise LispError("model-intercept: not available for a spline model; use model-report instead")
    return m.intercept


# ---------------------------------------------------------------------------
# The Lisp-callable builtins defined in this file
# ---------------------------------------------------------------------------

BUILTINS = {
    "linear-regression": linear_regression_fn,
    "lad-regression": lad_regression_fn,
    "quantile-regression": quantile_regression_fn,
    "logistic-regression": logistic_regression_fn,
    "spline-regression": spline_regression_fn,
    "spline-lad": spline_lad_fn,
    "spline-quantile": spline_quantile_fn,
    "spline-logistic": spline_logistic_fn,
    "suggest-knots": suggest_knots_fn,
    "model-report": model_report,
    "model-predict": model_predict,
    "model-evaluate": model_evaluate,
    "model-residuals": model_residuals,
    "model-coefficient-table": model_coefficient_table,
    "model-lift-table": model_lift_table,
    "cross-validate": cross_validate,
    "model-slope": model_slope,
    "model-coefficients": model_coefficients,
    "model-intercept": model_intercept,
    "model-floor": model_floor_or_ceiling("floor"),
    "model-ceiling": model_floor_or_ceiling("ceiling"),
    "model-kind": lambda m: LispString(m.kind),
    "model?": lambda x: _is_model(x),
    "sigmoid": lambda z: sigmoid(z),
}
