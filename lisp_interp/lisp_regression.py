"""Regression models for the Lisp interpreter: linear, logistic, and
piecewise-linear spline regression, with one or more predictors, plus
model-report / model-predict / model-evaluate and friends.

The fitting math (fit_linear, fit_logistic) uses numpy matrix operations,
so fitting millions of rows isn't slowed down by a Python-level loop.
The Lisp-callable builtins are listed in BUILTINS at the bottom of this
file; lisp_builtins.make_global_env() adds them to every environment.
"""

import math

import numpy as np

from lisp_core import (
    LispDate, LispError, LispString, LispVector, NIL, Pair, Symbol,
    list_to_pairs, numeric_value, pairs_to_list, to_display_string,
)


# ---------------------------------------------------------------------------
# Linear and logistic models
# ---------------------------------------------------------------------------

class LispModel:
    """A fitted regression model: either "linear"
    (y = intercept + sum(coefficients[i] * x[i])) or "logistic"
    (p = sigmoid(intercept + sum(coefficients[i] * x[i]))).
    `coefficients` is always a list, one entry per predictor (even if
    there's only one). `stats` holds a few kind-specific fit diagnostics
    used by `model-report`."""

    def __init__(self, kind, coefficients, intercept, stats, predictor_names=None, y_name=None):
        self.kind = kind                    # "linear" or "logistic"
        self.coefficients = coefficients    # list of floats, one per predictor
        self.intercept = intercept
        self.k = len(coefficients)          # number of predictors
        self.stats = stats                  # dict of extra fit info, kind-specific
        # Set by linear_regression_fn/logistic_regression_fn when x/y were
        # given as (name . vector) pairs (sqlite-query's own column-wise
        # result shape) instead of bare vectors -- lets model_report show
        # real names instead of x1/x2/.../y. None (the default) means no
        # names were available; model_report falls back to x1/x2/.../y.
        self.predictor_names = predictor_names   # list of str, one per predictor, or None
        self.y_name = y_name                     # str, or None

    def predict(self, xs):
        """xs: a list of numbers, one per predictor, in the same order the
        model was fit with."""
        z = self.intercept + sum(c * x for c, x in zip(self.coefficients, xs))
        return sigmoid(z) if self.kind == "logistic" else z

    def __repr__(self):
        if len(self.coefficients) == 1:
            return "#<%s-model slope=%.6g intercept=%.6g>" % (
                self.kind, self.coefficients[0], self.intercept)
        coeffs = ", ".join("%.6g" % c for c in self.coefficients)
        return "#<%s-model coefficients=(%s) intercept=%.6g>" % (self.kind, coeffs, self.intercept)


def sigmoid(z):
    """Numerically stable logistic function 1 / (1 + e^-z)."""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _sigmoid_vec(z):
    """The same numerically-stable sigmoid as sigmoid() (above), but
    elementwise over a whole numpy array at once -- used by
    fit_logistic's Newton-Raphson loop, below, so a whole iteration's
    worth of predictions is one vectorized numpy call instead of a
    Python-level loop calling the scalar sigmoid() once per
    observation. Splits on sign the same way, just with a boolean mask
    selecting which branch each element uses instead of an `if`."""
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def solve_linear_system(matrix, rhs):
    """Solve `matrix @ x = rhs` by Gauss-Jordan elimination with partial
    pivoting. `matrix` is a list of `n` rows, each of length `n`; `rhs` is
    a list of length `n`. Returns the solution as a list of length `n`.
    Plain and O(n^3), which is plenty fast for the handful of predictors
    a small Lisp program will realistically use."""
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
    """columns: a list of predictor columns (each a list of numbers, one
    per observation). Returns (standardized_columns, means, scales).
    Standardizing before fitting keeps both the normal-equations solve and
    Newton-Raphson well-behaved regardless of a predictor's raw scale
    (e.g. a huge ordinal date next to a small percentage)."""
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
    """Ordinary (or weighted) least-squares fit of
    y = intercept + sum(coef[i]*x[i]). `columns` is a list of one or
    more predictor columns (each a list of plain numbers, one per
    observation); `ys` is the list of observed values. Returns a
    LispModel.

    `weights` (optional): a list of one non-negative number per
    observation, or None (the default) to weight every observation
    equally. Fitting still minimizes a sum of squared errors, just a
    WEIGHTED one -- sum(weight[i] * (y[i] - prediction[i])**2) -- which
    is done by carrying `weight[i]` into every observation's
    contribution to the normal equations below (each observation's row
    of the design matrix is effectively counted `weight[i]` times). A
    weight of 0 excludes that observation from the fit entirely, and
    scaling every weight by the same constant doesn't change the result
    -- only the RELATIVE size of the weights matters.

    The normal-equations matrix/vector below (an O(n * p^2) reduction
    over every observation -- n rows, p = k+1 coefficients including
    the intercept) is built with numpy matrix ops (X.T @ X, roughly)
    instead of a Python-level triple loop over n/p/p, which matters for
    a large n (e.g. a multi-million-row dataset pulled in via
    sqlite-query). The actual p-by-p linear solve afterward
    (solve_linear_system) stays plain Python -- p is always small (a
    handful of predictors), so that part was never the bottleneck."""
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
    model.stats = {
        "r_squared": (1 - ss_residual / ss_total) if ss_total > 0 else float("nan"),
        "n": n,
    }
    return model


def fit_logistic(columns, ys, weights=None, max_iterations=50, tolerance=1e-8):
    """Fit p = sigmoid(intercept + sum(coef[i]*x[i])) by maximum
    likelihood, using Newton-Raphson (a.k.a. iteratively reweighted least
    squares). Each y must be in [0, 1] -- either a hard 0/1 label or a
    probability. `columns` is a list of one or more predictor columns.

    `weights` (optional): a list of one non-negative number per
    observation, or None (the default) to weight every observation
    equally -- see fit_linear's docstring for the general idea (and note
    below: this is a DIFFERENT weight than the `irls_weight` computed on
    every iteration below, which is part of the fitting ALGORITHM itself
    and has nothing to do with this one). Maximizing a weighted
    log-likelihood -- sum(weight[i] * observation[i]'s log-likelihood)
    -- just means multiplying `weight[i]` into that observation's
    contribution to the gradient, Hessian, and log-likelihood on every
    Newton-Raphson step.

    Each iteration's gradient/Hessian (an O(n * p^2) reduction over
    every observation, same shape as fit_linear's normal equations) is
    built with numpy matrix ops instead of a Python-level triple loop
    over n/p/p -- this loop runs up to max_iterations times, so for a
    large n this is where nearly all of fit_logistic's time goes; see
    fit_linear's docstring for why the p-by-p linear solve itself
    (solve_linear_system) stays plain Python either way."""
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

    stats = {
        "log_likelihood": log_likelihood,
        "pseudo_r_squared": pseudo_r_squared,
        "iterations": iterations_used,
        "converged": converged,
        "n": n,
    }
    return LispModel("logistic", coefficients, intercept, stats)


def _coerce_predictors(x_arg):
    """Accept a single vector (one predictor), a Lisp list of vectors
    (multiple predictors), or a Lisp list of (name . vector) pairs --
    exactly sqlite-query's own column-wise result shape -- so a query's
    results can be fed straight into a regression with no manual name-
    stripping first. `(linear-regression xs ys)` and
    `(linear-regression (list x1 x2) ys)` both keep working exactly as
    before; `(linear-regression (cdr freddie_loans) ...)` (a list of
    (name . vector) pairs) now also works directly.

    Returns (vectors, names): `names` is a list of strings, one per
    predictor, if every element of a list x_arg was a (name . vector)
    pair; otherwise None (no names available)."""
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
    """Convert the optional trailing `weights` argument shared by
    linear-regression/logistic-regression/spline-regression into a plain
    list of n_expected non-negative floats, or None if no weights were
    given -- None means "fit every observation equally", exactly the
    original unweighted behavior; fit_linear/fit_logistic both treat
    None that way. A typical use is weighting each row by its dollar
    balance, so a fit reflects the population's dollar-weighted behavior
    rather than treating a $1,000 loan and a $1,000,000 loan as equally
    important."""
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


def logistic_regression_fn(x_arg, y_arg, weight_vec=None):
    y_vec, y_name = _coerce_y(y_arg, "logistic-regression")
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    weights = _optional_weights(weight_vec, len(ys), "logistic-regression")
    model = fit_logistic(columns, ys, weights)
    model.predictor_names = names
    model.y_name = y_name
    return model


def _is_model(x):
    return isinstance(x, (LispModel, LispSplineModel))


def _is_probabilistic(model):
    """True for models whose .predict() returns a probability in [0,1]
    (logistic, or a spline model fit with a logistic link)."""
    return model.kind in ("logistic", "spline-logistic")


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


def model_report(model):
    """Produce a human-readable multi-line report of a fitted model's
    parameters (and a couple of fit-quality diagnostics)."""
    if isinstance(model, LispSplineModel):
        return LispString("\n".join(_spline_report_lines(model)))
    if not isinstance(model, LispModel):
        raise LispError("model-report: not a model: %r" % (model,))
    # Real predictor/y names when linear-regression/logistic-regression
    # was given (name . vector) pairs (sqlite-query's own column-wise
    # shape) -- see _coerce_predictors/_coerce_y -- else fall back to
    # the old x1/x2/.../y placeholders.
    names = model.predictor_names or ["x%d" % (i + 1) for i in range(model.k)]
    y_name = model.y_name or "y"
    lines = []
    coefficient_lines = [
        "  %s coefficient = %.6g" % (names[i], c) for i, c in enumerate(model.coefficients)
    ]
    if model.kind == "linear":
        lines.append("Linear model:  %s = %.6g + %s" % (
            y_name, model.intercept,
            " + ".join("%.6g*%s" % (c, names[i]) for i, c in enumerate(model.coefficients))))
        lines.extend(coefficient_lines)
        lines.append("  intercept      = %.6g" % model.intercept)
        lines.append("  R-squared      = %.6g" % model.stats["r_squared"])
        lines.append("  n              = %d" % model.stats["n"])
    else:
        lines.append("Logistic model:  p(%s) = sigmoid(%.6g + %s)" % (
            y_name, model.intercept,
            " + ".join("%.6g*%s" % (c, names[i]) for i, c in enumerate(model.coefficients))))
        lines.extend(coefficient_lines)
        lines.append("  intercept      = %.6g" % model.intercept)
        lines.append("  log-likelihood = %.6g" % model.stats["log_likelihood"])
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % model.stats["pseudo_r_squared"])
        lines.append("  iterations     = %d (%s)" % (
            model.stats["iterations"], "converged" if model.stats["converged"] else "did NOT converge"))
        lines.append("  n              = %d" % model.stats["n"])
    return LispString("\n".join(lines))


def model_evaluate(model, x_arg, y_vec):
    """Evaluate a fitted model's prediction quality against (typically
    held-out) data it was not fit on, and return a human-readable report.
    This is the "quality of the model on the remaining data" step of a
    train/test workflow."""
    if not _is_model(model):
        raise LispError("model-evaluate: not a model: %r" % (model,))
    y_vec, _y_name = _coerce_y(y_vec, "model-evaluate")
    columns, _names = _predictor_columns(x_arg, len(y_vec.items))
    if len(columns) != model.k:
        raise LispError(
            "model-evaluate: model has %d predictor(s), but %d given"
            % (model.k, len(columns)))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    n = len(ys)
    if n == 0:
        raise LispError("model-evaluate: no data to evaluate")
    predictions = [model.predict([col[i] for col in columns]) for i in range(n)]

    lines = ["Evaluation on %d held-out observation(s):" % n]
    if not _is_probabilistic(model):
        mean_y = sum(ys) / n
        ss_total = sum((y - mean_y) ** 2 for y in ys)
        ss_residual = sum((y - p) ** 2 for y, p in zip(ys, predictions))
        r_squared = (1 - ss_residual / ss_total) if ss_total > 0 else float("nan")
        rmse = math.sqrt(ss_residual / n)
        mae = sum(abs(y - p) for y, p in zip(ys, predictions)) / n
        lines.append("  R-squared = %.6g" % r_squared)
        lines.append("  RMSE      = %.6g" % rmse)
        lines.append("  MAE       = %.6g" % mae)
    else:
        eps = 1e-12
        log_likelihood = sum(
            y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps))
            for y, p in zip(ys, predictions))
        mean_y = min(max(sum(ys) / n, eps), 1 - eps)
        null_log_likelihood = sum(y * math.log(mean_y) + (1 - y) * math.log(1 - mean_y) for y in ys)
        pseudo_r_squared = (1 - log_likelihood / null_log_likelihood) if null_log_likelihood != 0 else float("nan")
        correct = sum(1 for y, p in zip(ys, predictions) if (p >= 0.5) == (y >= 0.5))
        accuracy = correct / n
        lines.append("  log-likelihood   = %.6g" % log_likelihood)
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % pseudo_r_squared)
        lines.append("  accuracy         = %.6g  (at a 0.5 threshold)" % accuracy)
    return LispString("\n".join(lines))


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
# ordinary (or logistic) regression -- reusing fit_linear/fit_logistic
# exactly as they are.

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


def _resolve_predictor_spec(spec, column, name):
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
                "spline-regression: %s marked categorical, but only %d distinct "
                "value(s) were found (need at least 2)" % (name, len(categories)))
        return _PredictorSpec("categorical", categories=categories, n_distinct=n_distinct)

    if isinstance(spec, Pair) or spec is NIL:
        knots = _dedupe_preserve_order(sorted(numeric_value(v) for v in pairs_to_list(spec)))
    else:
        count = int(spec)
        if count < 0:
            raise LispError("spline-regression: knot counts must not be negative")
        knots = _choose_knots(column, count)

    if knots and n_distinct <= 3:
        # A knot placed among only 2-3 distinct values is liable to make a
        # hinge column identical (or near-identical) to the plain linear
        # term or to another hinge, making the fit singular -- and hinge
        # knots don't really mean anything for a handful of discrete
        # values anyway. Catch this up front with an actionable message,
        # rather than letting it surface later as a confusing "collinear"
        # error deep in the linear-algebra code.
        raise LispError(
            "spline-regression: %s has only %d distinct value(s), so hinge "
            "knots aren't meaningful there (and can make the fit singular). "
            "Use a knot count of 0 (stay linear) or mark it 'categorical "
            "instead." % (name, n_distinct))

    return _PredictorSpec("spline", knots=knots, n_distinct=n_distinct)


def _resolve_all_predictor_specs(max_knots, columns, names=None):
    """Resolve the `max-knots` argument into one _PredictorSpec per
    predictor. `max_knots` may be:
      - a single int or 'categorical, applied to every predictor
      - a flat list of numbers/dates, when there's exactly one predictor
        (shorthand for explicit knot locations on that one predictor)
      - a list with exactly one entry per predictor, where each entry is
        itself an int, 'categorical, or a list of explicit knot locations

    `names` (optional): real predictor names (from x being given as
    (name . vector) pairs -- see _coerce_predictors) to use in error
    messages and later in the report, instead of the generic x1/x2/...
    placeholders."""
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
            return [_resolve_predictor_spec(list_to_pairs(items), columns[0], names[0])]
        if len(items) != k:
            raise LispError(
                "spline-regression: the knot-spec list must have one entry per "
                "predictor (%d), got %d" % (k, len(items)))
        return [_resolve_predictor_spec(spec, col, name)
                for spec, col, name in zip(items, columns, names)]

    return [_resolve_predictor_spec(max_knots, col, name)
            for col, name in zip(columns, names)]


def _spline_expand_value(v, spec, name):
    if spec.mode == "categorical":
        if v not in spec.categories:
            raise LispError(
                "spline-regression: %s value %r was not one of the categories "
                "seen while fitting (%s)" % (
                    name, v, ", ".join("%.6g" % c for c in spec.categories)))
        return [1.0 if v == cat else 0.0 for cat in spec.categories[1:]]
    row = [v]
    for t in spec.knots:
        row.append(max(0.0, v - t))
    return row


def _spline_expand_row(values, specs):
    """values: one value per original predictor. Returns the expanded
    feature row (hinge features and/or 0/1 category indicators)."""
    row = []
    for i, (v, spec) in enumerate(zip(values, specs)):
        row.extend(_spline_expand_value(v, spec, "x%d" % (i + 1)))
    return row


def _spline_expand_columns(columns, specs):
    """columns: one column (list of n values) per original predictor.
    Returns the same expansion as _spline_expand_row, but column-wise."""
    n = len(columns[0]) if columns else 0
    rows = [_spline_expand_row([col[i] for col in columns], specs) for i in range(n)]
    n_features = len(rows[0]) if rows else 0
    return [[row[j] for row in rows] for j in range(n_features)]


class LispSplineModel:
    """A piecewise-linear spline model: an ordinary linear or logistic
    regression fit on top of a per-predictor feature expansion (hinge
    functions and/or categorical dummy encoding -- see _resolve_predictor_spec
    / _spline_expand_columns above), giving the model a bit of the same
    kind of bendable-curve flexibility as MARS, without any external
    dependency."""

    def __init__(self, inner_model, predictor_specs, k, predictor_names=None, y_name=None):
        self.inner_model = inner_model          # a LispModel fit on the expanded basis
        self.predictor_specs = predictor_specs  # list of k _PredictorSpec
        self.k = k                              # number of original predictors
        self.kind = "spline-logistic" if inner_model.kind == "logistic" else "spline"
        # Set by spline_regression_fn when x/y were given as (name . vector)
        # pairs -- see LispModel's own predictor_names/y_name for the same
        # idea. None means no names were available.
        self.predictor_names = predictor_names   # list of str, one per ORIGINAL predictor, or None
        self.y_name = y_name                     # str, or None

    def predict(self, values):
        return self.inner_model.predict(_spline_expand_row(values, self.predictor_specs))

    def __repr__(self):
        total_knots = sum(len(s.knots) for s in self.predictor_specs if s.mode == "spline")
        n_categorical = sum(1 for s in self.predictor_specs if s.mode == "categorical")
        if n_categorical:
            return "#<%s-model predictors=%d knots=%d categorical=%d>" % (
                self.kind, self.k, total_knots, n_categorical)
        return "#<%s-model predictors=%d knots=%d>" % (self.kind, self.k, total_knots)


def _spline_feature_labels(specs, names):
    """One label per EXPANDED feature (mirrors _spline_expand_value's own
    per-predictor feature order exactly): a plain predictor name for its
    linear term, "name (knot T)" for each hinge, or "name = category" for
    each non-baseline categorical indicator."""
    labels = []
    for name, spec in zip(names, specs):
        if spec.mode == "categorical":
            for cat in spec.categories[1:]:
                labels.append("%s = %.6g" % (name, cat))
        else:
            labels.append(name)
            for t in spec.knots:
                labels.append("%s (knot %.6g)" % (name, t))
    return labels


def _spline_report_lines(model):
    names = model.predictor_names or ["x%d" % (i + 1) for i in range(model.k)]
    y_name = model.y_name or "y"
    lines = []
    if model.kind == "spline-logistic":
        lines.append("Piecewise-linear spline model, with a logistic link, predicting %s:" % y_name)
    else:
        lines.append("Piecewise-linear spline model, predicting %s:" % y_name)
    lines.append("  predictors = %d" % model.k)
    for name, spec in zip(names, model.predictor_specs):
        if spec.mode == "categorical":
            cats = ", ".join("%.6g" % c for c in spec.categories)
            lines.append("  %s: categorical -- categories %s (baseline %.6g)"
                          % (name, cats, spec.categories[0]))
        else:
            knot_text = ", ".join("%.6g" % t for t in spec.knots) if spec.knots else "(none -- plain linear)"
            hint = ""
            if spec.n_distinct is not None and spec.n_distinct <= 3:
                hint = "  [only %d distinct value(s) seen -- consider 'categorical]" % spec.n_distinct
            lines.append("  %s: knots %s%s" % (name, knot_text, hint))
    lines.append("")
    lines.append("Coefficients (on the expanded basis):")
    feature_labels = _spline_feature_labels(model.predictor_specs, names)
    for label, c in zip(feature_labels, model.inner_model.coefficients):
        lines.append("  %s coefficient = %.6g" % (label, c))
    lines.append("  intercept      = %.6g" % model.inner_model.intercept)
    lines.append("")
    stats = model.inner_model.stats
    if model.kind == "spline-logistic":
        lines.append("Logistic fit on the expanded basis:")
        lines.append("  log-likelihood   = %.6g" % stats["log_likelihood"])
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % stats["pseudo_r_squared"])
        lines.append("  iterations       = %d (%s)" % (
            stats["iterations"], "converged" if stats["converged"] else "did NOT converge"))
    else:
        lines.append("Linear fit on the expanded basis:")
        lines.append("  R-squared = %.6g" % stats["r_squared"])
    lines.append("  n = %d" % stats["n"])
    return lines


def spline_regression_fn(x_arg, y_arg, max_knots=3, logistic=False, weight_vec=None):
    """Fit a piecewise-linear spline model. `x_arg` is a vector, a list of
    vectors, or a list of (name . vector) pairs (predictors) -- see
    _coerce_predictors; `y_arg` is likewise a vector or a (name . vector)
    pair -- see _coerce_y. `max_knots` controls how each predictor is
    expanded -- see _resolve_all_predictor_specs for the accepted forms
    (an auto knot count, explicit knot locations, or 'categorical). If
    `logistic` is true, `y` must be in [0, 1], and a logistic regression
    (instead of ordinary least squares) is fit on the expanded basis,
    giving a probability-in-[0,1] output. `weight_vec` (optional): see
    fit_linear's docstring -- passed straight through to whichever fit
    runs on the expanded basis."""
    y_vec, y_name = _coerce_y(y_arg, "spline-regression")
    columns, names = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items.tolist()]
    k = len(columns)
    n = len(ys)
    if n == 0:
        raise LispError("spline-regression: no data to fit")
    if logistic:
        for y in ys:
            if y < 0 or y > 1:
                raise LispError(
                    "spline-regression: with logistic #t, dependent-variable values "
                    "must all be between 0 and 1 (got %r)" % (y,))
    weights = _optional_weights(weight_vec, n, "spline-regression")

    predictor_specs = _resolve_all_predictor_specs(max_knots, columns, names)
    expanded_columns = _spline_expand_columns(columns, predictor_specs)

    inner_model = (fit_logistic(expanded_columns, ys, weights) if logistic
                   else fit_linear(expanded_columns, ys, weights))
    return LispSplineModel(inner_model, predictor_specs, k, names, y_name)


def suggest_knots_fn(x_vec, y_vec, window, n):
    """Suggest n knot locations for spline-regression, based on where y
    curves most sharply as a function of x.

    Method: first aggregate y (by mean) onto each distinct x value seen
    (so `window` counts steps along the distinct-x curve, not raw rows --
    important for panel/pool data where many rows often share the same x).
    Estimate that curve's second derivative at each interior point (via
    the standard 3-point finite-difference formula, which works whether
    or not x is evenly spaced), smooth that sequence with a centered
    moving average of the given `window` size (to reduce sensitivity to
    single-point noise), then greedily pick the `window`-separated points
    with the largest smoothed |second derivative| -- "window-separated"
    meaning no two chosen points are within `window` of each other by
    index, so their smoothing windows don't overlap and they represent
    genuinely distinct bends rather than the same one picked twice.

    Returns a Lisp list of up to n x-values (fewer if there aren't that
    many usable candidates), sorted ascending -- ready to hand straight
    to spline-regression as an explicit knot list, e.g.
    (spline-regression x y (suggest-knots x y 5 2))."""
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

    # Sort by x, then aggregate y (by mean) onto each *distinct* x value.
    # Real/panel data routinely has many rows sharing the same x (e.g. many
    # pools observed at the same rate-incentive level); estimating a second
    # derivative needs distinct neighboring x's, and `window` is meant to
    # count "steps along the curve", not raw rows -- so we collapse to one
    # (x, mean-of-y) point per distinct x first. This also happens to be the
    # statistically sensible thing to do: it's the marginal curve of y
    # against x whose bends we want to find, not the scatter of every row.
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

    # Second-derivative estimate at each interior point i (1 .. m-2):
    #   f''(x_i) ~= 2 * [ (y_{i+1}-y_i)/(x_{i+1}-x_i) - (y_i-y_{i-1})/(x_i-x_{i-1}) ]
    #               / (x_{i+1} - x_{i-1})
    # which reduces to the familiar (y_{i+1} - 2y_i + y_{i-1}) / h^2 when x
    # is evenly spaced by h, but also works for uneven spacing. Since x is
    # now strictly increasing (we've deduplicated), h1/h2 are always > 0.
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
    "logistic-regression": logistic_regression_fn,
    "spline-regression": spline_regression_fn,
    "suggest-knots": suggest_knots_fn,
    "model-report": model_report,
    "model-predict": model_predict,
    "model-evaluate": model_evaluate,
    "model-slope": model_slope,
    "model-coefficients": model_coefficients,
    "model-intercept": model_intercept,
    "model-kind": lambda m: LispString(m.kind),
    "model?": lambda x: _is_model(x),
    "sigmoid": lambda z: sigmoid(z),
}
