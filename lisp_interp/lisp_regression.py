"""Regression models for the Lisp interpreter, with one or more predictors:

                   a straight line (or plane)   a line that bends at knots
  least squares    linear-regression            spline-regression
  least absolute   lad-regression               spline-lad
    deviation
  logistic         logistic-regression          spline-logistic

plus model-report / model-predict / model-evaluate and friends. A logistic
model's curve goes from 0 to 1, unless :floor and :ceiling say otherwise.

The fitting math (fit_linear, fit_lad, fit_logistic) uses numpy matrix
operations, so fitting millions of rows isn't slowed down by a Python-level
loop.
The Lisp-callable builtins are listed in BUILTINS at the bottom of this
file; lisp_builtins.make_global_env() adds them to every environment.
"""

import itertools
import math

import numpy as np

from lisp_core import (
    Keyword, LispDate, LispError, LispString, LispVector, NIL, Pair, Symbol,
    keyword_options, list_to_pairs, numeric_value, pairs_to_list, to_display_string,
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
        """Whether a logistic model's curve goes from 0 to 1: it gives a probability."""
        return (self.floor, self.ceiling) == (0.0, 1.0)

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


def fit_linear(columns, ys, weights=None):
    """Least-squares fit of y = intercept + sum(coef[i] * x[i]). `columns` is
    a list of predictor columns (lists of numbers); `ys` the observed
    values. Returns a LispModel.

    `weights` (optional): one non-negative number per observation. The fit
    then minimizes sum(weight[i] * (y[i] - prediction[i])**2), so an
    observation with weight 3 counts as much as three with weight 1; only
    the weights' relative sizes matter. None weights every observation
    equally.

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
    total_weight = float(w.sum())
    mean_y = float((w * y_arr).sum()) / total_weight
    ss_total = float((w * (y_arr - mean_y) ** 2).sum())
    ss_residual = float((w * (y_arr - predictions) ** 2).sum())

    # Standard errors: the residual variance times (X'WX)^-1, with n - p
    # degrees of freedom. Scaling every weight by the same amount doesn't
    # change them.
    degrees_of_freedom = n - p
    if degrees_of_freedom > 0:
        covariance = (ss_residual / degrees_of_freedom) * np.linalg.inv(normal_matrix)
        std_errors = np.sqrt(np.diag(_original_scale_covariance(covariance, means, scales)))
    else:
        std_errors = np.full(p, np.nan)

    model.stats = {
        "r_squared": (1 - ss_residual / ss_total) if ss_total > 0 else float("nan"),
        "n": n,
        "std_errors": std_errors.tolist(),      # intercept first, then each coefficient
        "test": "t",
        "degrees_of_freedom": degrees_of_freedom,
    }
    return model


def fit_logistic(columns, ys, weights=None, max_iterations=50, tolerance=1e-8):
    """Fit p = sigmoid(intercept + sum(coef[i] * x[i])) by maximum likelihood,
    using Newton-Raphson. Each y must be between 0 and 1 (a 0/1 label or a
    probability). `weights` works as in fit_linear: each observation's
    log-likelihood is multiplied by its weight. (That's unrelated to
    `irls_weight` below, which is part of the Newton-Raphson method itself.)

    Each iteration's gradient and Hessian are built with numpy, so large
    data is fast; this loop is where nearly all the fitting time goes."""
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

    beta = np.zeros(p)
    converged = False
    iterations_used = 0
    log_likelihood = 0.0

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        prob = _sigmoid_vec(X @ beta)             # n
        error = prob - y_arr                      # n
        irls_weight = w * prob * (1.0 - prob)      # n -- IRLS's OWN per-observation
                                                    # weight, unrelated to the case weight `w`
        gradient = X.T @ (w * error)               # p
        hessian = (X.T * irls_weight) @ X          # p x p
        log_likelihood = float((w * (
            y_arr * np.log(np.maximum(prob, eps)) + (1.0 - y_arr) * np.log(np.maximum(1.0 - prob, eps))
        )).sum())

        try:
            delta = solve_linear_system(hessian.tolist(), gradient.tolist())
        except LispError:
            raise LispError(
                "logistic-regression: fitting failed to converge -- this "
                "usually means the data is perfectly (or almost perfectly) "
                "separable by one of the predictors, which sends the "
                "coefficients toward infinity; try more/noisier data")
        beta = beta - np.array(delta)
        if max(abs(d) for d in delta) < tolerance:
            converged = True
            break

    coefficients, intercept = _unstandardize_coefficients(float(beta[0]), beta[1:].tolist(), means, scales)

    # McFadden's pseudo R-squared, comparing against an intercept-only model.
    total_weight = float(w.sum())
    mean_y = min(max(float((w * y_arr).sum()) / total_weight, eps), 1 - eps)
    null_log_likelihood = float((w * (
        y_arr * math.log(mean_y) + (1.0 - y_arr) * math.log(1 - mean_y)
    )).sum())
    pseudo_r_squared = (1 - log_likelihood / null_log_likelihood) if null_log_likelihood != 0 else float("nan")

    # Standard errors from the inverse of the information matrix at the
    # fitted coefficients. The weights are first rescaled to average 1, so
    # they say how much each row matters relative to the others, not how
    # many copies of it there are -- otherwise weighting by loan balance
    # (in dollars) would make the standard errors absurdly small.
    prob = _sigmoid_vec(X @ beta)
    relative_w = w * (n / total_weight)
    information = (X.T * (relative_w * prob * (1.0 - prob))) @ X
    try:
        covariance = np.linalg.inv(information)
        std_errors = np.sqrt(np.diag(_original_scale_covariance(covariance, means, scales)))
    except np.linalg.LinAlgError:
        std_errors = np.full(p, np.nan)

    stats = {
        "log_likelihood": log_likelihood,
        "pseudo_r_squared": pseudo_r_squared,
        "iterations": iterations_used,
        "converged": converged,
        "n": n,
        "std_errors": std_errors.tolist(),      # intercept first, then each coefficient
        "test": "z",
        "auc": weighted_auc(prob, y_arr, w),
    }
    return LispModel("logistic", coefficients, intercept, stats)


def fit_logistic_between(columns, ys, weights, floor, ceiling, who):
    """A logistic model of y between a floor and a ceiling:

        y = floor + (ceiling - floor) * sigmoid(intercept + sum(coef[i] * x[i]))

    a curve in the shape of an S that flattens out at the floor on one side
    and the ceiling on the other. The ys are rescaled to (y - floor) /
    (ceiling - floor), which go from 0 to 1, and fit by fit_logistic. With no
    floor and ceiling (None), they're 0 and 1, and every y must be between
    them, as a probability is. With them, a y below the floor, or above the
    ceiling, is taken to be at it (clipped): data scatters about the levels a
    curve flattens out at, so some of it is beyond them. The model's stats
    say how many were. `who` is the function to name in an error message."""
    if floor is None:
        for y in ys:
            if not 0 <= y <= 1:
                raise LispError("%s: every y must be between 0 and 1, as a probability is (got %r) -- "
                                "or give the curve a :floor and :ceiling" % (who, y))
        return fit_logistic(columns, ys, weights)
    rescaled = [(y - floor) / (ceiling - floor) for y in ys]
    model = fit_logistic(columns, [min(max(r, 0.0), 1.0) for r in rescaled], weights)
    model.floor, model.ceiling = floor, ceiling
    model.stats["below_floor"] = sum(1 for r in rescaled if r < 0)
    model.stats["above_ceiling"] = sum(1 for r in rescaled if r > 1)
    return model


def floor_and_ceiling(options, who):
    """The :floor and :ceiling options, as numbers -- 0 and 1 for one that
    isn't given -- or (None, None) if neither is."""
    if options.get("floor") is None and options.get("ceiling") is None:
        return None, None
    floor = options.get("floor") if options.get("floor") is not None else 0.0
    ceiling = options.get("ceiling") if options.get("ceiling") is not None else 1.0
    for name, value in (("floor", floor), ("ceiling", ceiling)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise LispError("%s: :%s must be a number, not %s" % (who, name, to_display_string(value)))
    if not floor < ceiling:
        raise LispError("%s: the :floor (%s) must be below the :ceiling (%s)" % (who, floor, ceiling))
    return float(floor), float(ceiling)


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

def weighted_median(values, weights):
    """The value t that makes sum(weights[i] * |values[i] - t|) smallest: the
    first value, in sorted order, at which half the total weight is reached.
    `values` and `weights` are numpy arrays."""
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    return float(values[order[np.searchsorted(cumulative, cumulative[-1] / 2.0)]])


def fit_lad(columns, ys, weights=None, max_iterations=1000):
    """Least absolute deviation fit of y = intercept + sum(coef[i] * x[i]):
    the one that makes sum(weight[i] * |y[i] - prediction[i]|) smallest,
    rather than the sum of squares. A point far from the others pulls a
    least-squares fit toward it by the square of its distance, but a LAD fit
    only in proportion to it -- so a few outliers barely move it. With no
    predictors, it would be the median of y, as least squares would be the
    mean. `columns`, `ys`, and `weights` are as for fit_linear. Returns a
    LispModel.

    There's no formula for it, as there is for least squares, but one fact
    makes it easy to find: some best fit goes exactly through p of the
    points, p being the number of coefficients, counting the intercept --
    for a line, through two of them. So, Wesolowsky's method (1981):

    1. Start with the fit through the p points closest to the least-squares
       fit.
    2. Hold the fit at p - 1 of the points it goes through, and swing it
       (for a line: rotate it about one point). As it swings by an amount t,
       point i's residual changes by t * a[i], so the sum of absolute
       deviations is sum(weight[i] * |a[i]| * |residual[i] / a[i] - t|),
       which is smallest when t is a weighted median of the
       residual[i] / a[i] -- where the fit reaches another of the points.
    3. Try that for every set of p - 1 points the fit goes through, and take
       the swing that lowers the sum the most. Repeat until no swing lowers
       it: then no fit is better, since the sum of absolute deviations has
       no local minimum that isn't the minimum.

    Each step is exact, and it usually takes only a few. Fitting is done on
    standardized predictors, as in fit_linear."""
    k = len(columns)
    n = len(ys)
    p = k + 1
    if n < p:
        raise LispError("lad-regression: %d observation(s) is too few to fit %d coefficients" % (n, p))
    for col in columns:
        if len(col) != n:
            raise LispError("lad-regression: all vectors must be the same length")
    if weights is None:
        weights = [1.0] * n

    std_columns, means, scales = _standardize_columns(columns)
    X = np.column_stack([np.ones(n)] + [np.asarray(col, dtype=np.float64) for col in std_columns])
    w = np.asarray(weights, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)

    def sum_abs_deviations(beta):
        return float((w * np.abs(y - X @ beta)).sum())

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
    total = sum_abs_deviations(beta)

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
            t = weighted_median(residuals[moves] / a[moves], w[moves] * np.abs(a[moves]))
            candidate = beta + t * direction
            candidate_total = sum_abs_deviations(candidate)
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

    # How good the fit is, as R-squared says for least squares: 1 - the sum of
    # absolute deviations / that sum about the median of y (a fit with no
    # predictors). Koenker and Machado's R1.
    total_about_median = float((w * np.abs(y - weighted_median(y, w))).sum())
    pseudo_r_squared = (1 - total / total_about_median) if total_about_median > 0 else float("nan")

    # Standard errors. The coefficients' covariance is (sparsity^2 / 4) *
    # A^-1 B A^-1, with A = X'WX and B = X'W^2X -- just (X'X)^-1 without
    # weights -- where the sparsity is 1 / the density of the errors at their
    # median: how closely the residuals crowd around 0. It's estimated as for
    # normally distributed errors, sigma * sqrt(2 pi), but with sigma found
    # from the median absolute residual (times 1.4826, which makes it the
    # standard deviation for normal errors), so that outliers don't inflate
    # it. The p residuals the fit makes exactly 0 are left out of that
    # median. (Simulations with as few as 6 points, and with normal,
    # heavy-tailed, or contaminated errors, give 95% intervals that hold the
    # true coefficient 94% to 97% of the time.) Scaling every weight alike
    # doesn't change them.
    degrees_of_freedom = n - p
    off_fit = np.abs(residuals)[np.abs(residuals) > on_fit_tolerance]
    if degrees_of_freedom > 0 and len(off_fit) > 0:
        sigma = 1.4826 * float(np.median(off_fit))
        sparsity = math.sqrt(2 * math.pi) * sigma
        A_inverse = np.linalg.inv((X.T * w) @ X)
        covariance = 0.25 * sparsity ** 2 * (A_inverse @ ((X.T * w ** 2) @ X) @ A_inverse)
        std_errors = np.sqrt(np.diag(_original_scale_covariance(covariance, means, scales)))
    else:
        std_errors = np.full(p, np.nan)

    stats = {
        "sum_abs_deviations": total,
        "pseudo_r_squared": pseudo_r_squared,
        "iterations": iterations,
        "converged": converged,
        "n": n,
        "std_errors": std_errors.tolist(),      # intercept first, then each coefficient
        "test": "t",
        "degrees_of_freedom": degrees_of_freedom,
    }
    return LispModel("lad", coefficients, intercept, stats)


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


def linear_regression_fn(x_arg, y_arg, weight_vec=None):
    y_vec, y_name = _coerce_y(y_arg, "linear-regression")
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    weights = _optional_weights(weight_vec, len(ys), "linear-regression")
    model = fit_linear(columns, ys, weights)
    model.predictor_names = names
    model.y_name = y_name
    return model


def lad_regression_fn(x_arg, y_arg, weight_vec=None):
    y_vec, y_name = _coerce_y(y_arg, "lad-regression")
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    weights = _optional_weights(weight_vec, len(ys), "lad-regression")
    model = fit_lad(columns, ys, weights)
    model.predictor_names = names
    model.y_name = y_name
    return model


def logistic_regression_fn(x_arg, y_arg, *arguments):
    """(logistic-regression x y [weights] [:floor f :ceiling c]) -- a logistic
    model: see fit_logistic_between."""
    who = "logistic-regression"
    positional, options = positional_and_keywords(arguments, 1, ["floor", "ceiling"], who)
    floor, ceiling = floor_and_ceiling(options, who)
    y_vec, y_name = _coerce_y(y_arg, who)
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    weights = _optional_weights(positional[0] if positional else None, len(ys), who)
    model = fit_logistic_between(columns, ys, weights, floor, ceiling, who)
    model.predictor_names = names
    model.y_name = y_name
    return model


def _is_model(x):
    return isinstance(x, (LispModel, LispSplineModel))


def _is_probabilistic(model):
    """True for models whose .predict() returns a probability in [0,1]: a
    logistic or spline-logistic model whose curve goes from 0 to 1. (One with
    another floor and ceiling predicts a number between them.)"""
    inner = model.inner_model if isinstance(model, LispSplineModel) else model
    return inner.kind == "logistic" and inner.between_0_and_1()


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
    elif model.between_0_and_1():
        lines = ["Logistic model:  p(%s) = sigmoid(%.6g + %s)" % (y_name, model.intercept, terms)]
    else:
        lines = ["Logistic model, between %.6g and %.6g:  %s = %.6g + %.6g * sigmoid(%.6g + %s)"
                 % (model.floor, model.ceiling, y_name, model.floor, model.ceiling - model.floor,
                    model.intercept, terms)]
    lines.extend(coefficient_table_lines(model, names))
    lines.extend(fit_statistics_lines(model))
    return LispString("\n".join(lines))


def fit_statistics_lines(model):
    """The measures of fit at the end of model-report, for a LispModel."""
    stats = model.stats
    if model.kind == "linear":
        return ["  R-squared        = %.6g" % stats["r_squared"],
                "  n                = %d" % stats["n"]]
    if model.kind == "lad":
        return ["  sum |residuals|  = %.6g" % stats["sum_abs_deviations"],
                "  pseudo R-squared = %.6g  (1 - sum |residuals| / the same about the median of y)"
                % stats["pseudo_r_squared"],
                "  iterations       = %d (%s)" % (stats["iterations"],
                                                   "converged" if stats["converged"] else "did NOT converge"),
                "  n                = %d" % stats["n"]]
    between = []
    if not model.between_0_and_1():
        between = ["  floor, ceiling   = %.6g, %.6g  (%d y below the floor, and %d above the ceiling, taken as at them)"
                   % (model.floor, model.ceiling, stats.get("below_floor", 0), stats.get("above_ceiling", 0)),
                   "  (the measures below are of y rescaled to (y - floor) / (ceiling - floor))"]
    return between + [
            "  log-likelihood   = %.6g" % stats["log_likelihood"],
            "  pseudo R-squared = %.6g  (McFadden's)" % stats["pseudo_r_squared"],
            "  AUC              = %.6g" % stats["auc"],
            "  iterations       = %d (%s)" % (stats["iterations"],
                                               "converged" if stats["converged"] else "did NOT converge"),
            "  n                = %d" % stats["n"]]


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
    (typically data held out from fitting), as a text report: R-squared,
    RMSE, and MAE for a linear model; log-likelihood, pseudo R-squared,
    AUC, and accuracy for a logistic one."""
    predictions, ys = evaluation_data(model, x_arg, y_arg, "model-evaluate")
    n = len(ys)
    lines = ["Evaluation on %d held-out observation(s):" % n]
    if not _is_probabilistic(model):
        residuals = ys - predictions
        ss_total = float(((ys - ys.mean()) ** 2).sum())
        ss_residual = float((residuals ** 2).sum())
        lines.append("  R-squared = %.6g" % ((1 - ss_residual / ss_total) if ss_total > 0 else float("nan")))
        lines.append("  RMSE      = %.6g" % math.sqrt(ss_residual / n))
        lines.append("  MAE       = %.6g" % float(np.abs(residuals).mean()))
    else:
        eps = 1e-12
        p = np.clip(predictions, eps, 1 - eps)
        log_likelihood = float((ys * np.log(p) + (1 - ys) * np.log(1 - p)).sum())
        mean_y = min(max(float(ys.mean()), eps), 1 - eps)
        null_log_likelihood = float((ys * math.log(mean_y) + (1 - ys) * math.log(1 - mean_y)).sum())
        pseudo_r_squared = (1 - log_likelihood / null_log_likelihood) if null_log_likelihood != 0 else float("nan")
        accuracy = float(((predictions >= 0.5) == (ys >= 0.5)).mean())
        lines.append("  log-likelihood   = %.6g" % log_likelihood)
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % pseudo_r_squared)
        lines.append("  AUC              = %.6g" % weighted_auc(predictions, ys, np.ones(n)))
        lines.append("  accuracy         = %.6g  (at a 0.5 threshold)" % accuracy)
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
    """How one predictor is expanded into features: either a set of
    hinge-function knots (mode "spline"), or a set of categories to
    dummy-encode (mode "categorical", one 0/1 indicator column per
    non-baseline category)."""

    def __init__(self, mode, knots=None, categories=None, n_distinct=None):
        self.mode = mode
        self.knots = knots or []
        self.categories = categories or []   # sorted; categories[0] is baseline
        self.n_distinct = n_distinct

    def n_features(self):
        return len(self.knots) + 1 if self.mode == "spline" else len(self.categories) - 1


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


def _resolve_predictor_spec(spec, column, name, who):
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

    return _PredictorSpec("spline", knots=knots, n_distinct=n_distinct)


def _resolve_all_predictor_specs(max_knots, columns, names=None, who="spline-regression"):
    """Turn the `max-knots` argument into one _PredictorSpec per predictor.
    `max_knots` is either one setting for every predictor -- a knot count or
    'categorical -- or a list with one setting per predictor, each a knot
    count, 'categorical, or a list of knot locations. With exactly one
    predictor, a flat list of numbers means those knot locations.

    `names` (optional): the predictors' names, for error messages and the
    report; `who`, the function to name in an error message."""
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
            return [_resolve_predictor_spec(list_to_pairs(items), columns[0], names[0], who)]
        if len(items) != k:
            raise LispError(
                "%s: the knot-spec list must have one entry per "
                "predictor (%d), got %d" % (who, k, len(items)))
        return [_resolve_predictor_spec(spec, col, name, who)
                for spec, col, name in zip(items, columns, names)]

    return [_resolve_predictor_spec(max_knots, col, name, who)
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
    row = [v]
    for t in spec.knots:
        row.append(max(0.0, v - t))
    return row


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

    KINDS = {"linear": "spline", "lad": "spline-lad", "logistic": "spline-logistic"}   # by the inner model's kind

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
        total_knots = sum(len(s.knots) for s in self.predictor_specs if s.mode == "spline")
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
        else:
            labels.append(name)
            for t in spec.knots:
                labels.append("%s (knot %.6g)" % (name, t))
    return labels


def _spline_report_lines(model):
    names = model.predictor_names or ["x%d" % (i + 1) for i in range(model.k)]
    y_name = model.y_name or "y"
    lines = []
    if model.kind == "spline-logistic" and model.inner_model.between_0_and_1():
        lines.append("Piecewise-linear spline model, with a logistic link, predicting %s:" % y_name)
    elif model.kind == "spline-logistic":
        lines.append("Piecewise-linear spline model, with a logistic link between %.6g and %.6g, predicting %s:"
                     % (model.inner_model.floor, model.inner_model.ceiling, y_name))
    elif model.kind == "spline-lad":
        lines.append("Piecewise-linear spline model, fit by least absolute deviation, predicting %s:" % y_name)
    else:
        lines.append("Piecewise-linear spline model, predicting %s:" % y_name)
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
            lines.append("  %s: knots %s%s" % (name, knot_text, hint))
    lines.append("")
    lines.append("Coefficients (on the expanded basis):")
    lines.extend(coefficient_table_lines(model.inner_model, _spline_feature_labels(model.predictor_specs, names)))
    lines.append("")
    lines.append("Fit:")
    lines.extend(fit_statistics_lines(model.inner_model))
    return lines


def fit_spline(x_arg, y_arg, max_knots, weight_vec, fit, who):
    """A piecewise-linear spline model: each predictor expanded as max-knots
    says (see _resolve_all_predictor_specs) -- into hinge functions at knots,
    or 0/1 indicators for categories -- and the expanded columns fit by
    `fit` (fit_linear, fit_lad, or fit_logistic). x, y, and the weights are
    as for linear-regression; `who` is the function to name in an error
    message."""
    y_vec, y_name = _coerce_y(y_arg, who)
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    if not ys:
        raise LispError("%s: no data to fit" % who)
    weights = _optional_weights(weight_vec, len(ys), who)
    predictor_specs = _resolve_all_predictor_specs(max_knots, columns, names, who)
    expanded_columns = _spline_expand_columns(columns, predictor_specs)
    return LispSplineModel(fit(expanded_columns, ys, weights), predictor_specs, len(columns), names, y_name)


def spline_regression_fn(x_arg, y_arg, max_knots=3, weight_vec=None):
    """(spline-regression x y [max-knots weights]) -- fit a piecewise-linear
    spline model by least squares. x and y are as for linear-regression.
    max-knots says how to expand each predictor (see
    _resolve_all_predictor_specs)."""
    if isinstance(weight_vec, bool):
        raise LispError("spline-regression: it has no logistic? argument now: "
                        "spline-logistic fits a spline with a logistic link")
    return fit_spline(x_arg, y_arg, max_knots, weight_vec, fit_linear, "spline-regression")


def spline_logistic_fn(x_arg, y_arg, *arguments):
    """(spline-logistic x y [max-knots weights] [:floor f :ceiling c]) -- fit a
    piecewise-linear spline model with a logistic link: spline-regression's
    expansion of the predictors, fit as logistic-regression fits (see
    fit_logistic_between), so the curve can bend, and stays between the
    floor and the ceiling (0 and 1, unless they're given)."""
    who = "spline-logistic"
    positional, options = positional_and_keywords(arguments, 2, ["floor", "ceiling"], who)
    floor, ceiling = floor_and_ceiling(options, who)
    max_knots = positional[0] if positional else 3
    weight_vec = positional[1] if len(positional) > 1 else None

    def fit(columns, ys, weights):
        return fit_logistic_between(columns, ys, weights, floor, ceiling, who)

    return fit_spline(x_arg, y_arg, max_knots, weight_vec, fit, who)


def spline_lad_fn(x_arg, y_arg, max_knots=3, weight_vec=None):
    """(spline-lad x y [max-knots weights]) -- fit a piecewise-linear spline
    model by least absolute deviation: as spline-regression does, but making
    the sum of the absolute residuals smallest (fit_lad) rather than the sum
    of their squares, so a few outliers barely move the curve."""
    return fit_spline(x_arg, y_arg, max_knots, weight_vec, fit_lad, "spline-lad")


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
# The Lisp-callable builtins defined in this file
# ---------------------------------------------------------------------------

def model_intercept(m):
    if isinstance(m, LispSplineModel):
        raise LispError("model-intercept: not available for a spline model; use model-report instead")
    return m.intercept


BUILTINS = {
    "linear-regression": linear_regression_fn,
    "lad-regression": lad_regression_fn,
    "logistic-regression": logistic_regression_fn,
    "spline-regression": spline_regression_fn,
    "spline-lad": spline_lad_fn,
    "spline-logistic": spline_logistic_fn,
    "suggest-knots": suggest_knots_fn,
    "model-report": model_report,
    "model-predict": model_predict,
    "model-evaluate": model_evaluate,
    "model-residuals": model_residuals,
    "model-coefficient-table": model_coefficient_table,
    "model-lift-table": model_lift_table,
    "model-slope": model_slope,
    "model-coefficients": model_coefficients,
    "model-intercept": model_intercept,
    "model-kind": lambda m: LispString(m.kind),
    "model?": lambda x: _is_model(x),
    "sigmoid": lambda z: sigmoid(z),
}
