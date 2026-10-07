"""Portfolios of investments, for the Lisp interpreter.

  (combine-returns named-returns)          several investments' returns, lined up by date
  (bootstrap-paths returns start-prices days block-size [:seed n] [:dividends schedules]
                   [:volatility model] [:start-volatility x])
                                           paths of all of them, made from the same days
  (portfolio-value prices weights [:start-prices p] [:rebalance n] [:start-value v])
                                           a portfolio's value along a table of prices
  (covariance-matrix returns [:days-per-year n]), (correlation-matrix returns)
  (portfolio-volatility weights covariance)
  (minimum-variance-weights covariance [:long-only #t])
  (mean-variance-weights expected-returns covariance risk-aversion [:long-only #t])

SEVERAL INVESTMENTS: combine-returns lines up their daily returns (from
daily-returns) by date, keeping the days they all have, in a table with a
column of returns for each, named for it. adjust-returns gives each its
expected return. bootstrap-paths then copies the same days of the history
for all of them, so that when one had a bad day in the history, the others
have that day too: their correlation is kept. With a volatility model
(volatility-model, made from the same table of returns: it has a row for
each investment), each one's volatility starts at its own today's and
changes as its own model says, and the paths copy the same days' shocks.

WEIGHTS and other things that have a number for each investment are lists
of (name . number) pairs: (list (cons "SPY" 0.6) (cons "TLT" 0.4)).

A COVARIANCE MATRIX is a table: an investment column with their names, and
a column for each of them. Its numbers are for a year: the daily returns'
covariance times the days in a year.

THE WEIGHTS that are best by Markowitz's mean-variance analysis: those that
make the portfolio's variance least (minimum-variance-weights), or that make
its expected return less risk-aversion / 2 times its variance greatest
(mean-variance-weights), with the weights adding to 1. Weights can be
negative (selling short), unless :long-only #t. Without that, the answer is
a formula (a set of linear equations, solved); with it, it is found by
trying the formula on fewer and fewer of the investments: an investment
that would have a weight below 0 is left out (its weight is 0), and one
left out is let back in if the portfolio would be better with some of it,
until neither happens.
"""

import numpy as np

from lisp_core import LispError, LispString, LispVector, Pair, is_true, keyword_options, list_to_pairs, pairs_to_list
from lisp_investment_paths import (
    days_drawn, named_numbers, path_log_returns, prices_with_dividends, return_columns, schedule_days_and_amounts,
    whole_number,
)
from lisp_tables import find_column, make_table_value, table_columns
from lisp_vector_math import floats_of, is_number, to_vector

DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Several investments' returns, and paths of them
# ---------------------------------------------------------------------------

def combine_returns(named_returns):
    """(combine-returns named-returns) -- several investments' returns, a
    list of (name . table of returns), each table as daily-returns makes it,
    lined up by date: a table of date and a column of returns for each,
    named for it, with a row for each date they all have."""
    who = "combine-returns"
    entries = pairs_to_list(named_returns) if isinstance(named_returns, Pair) else []
    if not entries or not all(isinstance(e, Pair) for e in entries):
        raise LispError('%s: expected a list of (name . returns), such as (list (cons "SPY" spy-returns))' % who)
    by_date = []
    for entry in entries:
        name = str(entry.car)
        if name in [n for n, _ in by_date]:
            raise LispError("%s: two of them are named %s" % (who, name))
        dates = find_column(table_columns(entry.cdr, who), "date", who).items.tolist()
        columns = return_columns(entry.cdr, who)
        if len(columns) > 1:
            raise LispError("%s: %s's table has the returns of more than one investment" % (who, name))
        by_date.append((name, dict(zip(dates, columns[0][1]))))
    common = sorted(set.intersection(*[set(values) for _, values in by_date]))
    if not common:
        raise LispError("%s: there is no date all of them have a return for" % who)
    return make_table_value([("date", LispVector(common))] +
                            [(name, to_vector(np.array([values[d] for d in common]))) for name, values in by_date])


def bootstrap_paths(returns, start_prices, days, block_size, *options):
    """(bootstrap-paths returns start-prices days block-size [:seed n]
    [:dividends schedules] [:volatility model] [:start-volatility x]) -- one
    path of prices for each of several investments, made from the same
    days of the history: a table of day (1 for the first) and a column of
    prices for each investment. returns is a table with a column of returns
    for each, as combine-returns makes (and adjust-returns adjusts);
    start-prices a list of (name . price), one for each; :dividends a list
    of (name . schedule), as dividend-schedule makes, for those that pay
    dividends; :volatility a model with a row for each investment, as
    volatility-model makes from the same returns; and :start-volatility one
    volatility for all of them, or a list of (name . volatility), one for
    each. As bootstrap-path does for one."""
    who = "bootstrap-paths"
    options = keyword_options(options, ["seed", "dividends", "volatility", "start-volatility"], who)
    columns = return_columns(returns, who)
    names = [name for name, _ in columns]
    prices = named_numbers(start_prices, names, "start-prices", who)
    if any(price <= 0 for price in prices.values()):
        raise LispError("%s: every start price must be above 0" % who)
    schedules = {}
    for entry in pairs_to_list(options["dividends"]) if options.get("dividends") is not None else []:
        if not isinstance(entry, Pair) or str(entry.car) not in names:
            raise LispError("%s: :dividends is a list of (name . schedule), for the investments %s"
                            % (who, ", ".join(names)))
        schedules[str(entry.car)] = schedule_days_and_amounts(entry.cdr, who)

    start_volatilities = {name: None for name in names}
    if options.get("start-volatility") is not None:
        start_volatilities = named_numbers(options["start-volatility"], names, ":start-volatility", who)

    rows = days_drawn(len(columns[0][1]), days, block_size, options.get("seed"), who)   # the same days for every one
    paths = []
    for name, values in columns:
        log_returns = path_log_returns(name, values, rows, options.get("volatility"), start_volatilities[name], who)
        paths.append((name, to_vector(prices_with_dividends(prices[name], np.cumsum(log_returns),
                                                            schedules.get(name, [])))))
    return make_table_value([("day", to_vector(np.arange(1, len(rows) + 1)))] + paths)


# ---------------------------------------------------------------------------
# A portfolio's value
# ---------------------------------------------------------------------------

def portfolio_value(prices, weights, *options):
    """(portfolio-value prices weights [:start-prices p] [:rebalance n]
    [:start-value v]) -- the value of a portfolio along a table of prices
    (a column for each investment and a row for each day: a price history,
    or bootstrap-paths' paths), as a vector with a value for each row. weights
    is a list of (name . weight), adding to 1. The portfolio is bought with
    start-value (1 unless given) at :start-prices, a list of (name . price),
    if they're given, and otherwise at the first row's prices. :rebalance n
    puts it back to the weights every n rows; without it, it is bought and
    held. (The prices should have dividends in them, if there are any: the
    portfolio doesn't get them otherwise.)"""
    who = "portfolio-value"
    options = keyword_options(options, ["start-prices", "rebalance", "start-value"], who)
    weight_pairs = pairs_to_list(weights) if isinstance(weights, Pair) else []
    names = [str(p.car) for p in weight_pairs if isinstance(p, Pair)]
    if not names:
        raise LispError("%s: weights is a list of (name . weight), such as (list (cons \"SPY\" 0.6) (cons \"TLT\" 0.4))" % who)
    w = np.array([named_numbers(weights, names, "weights", who)[name] for name in names])
    if abs(w.sum() - 1) > 1e-9:
        raise LispError("%s: the weights add up to %s, not 1" % (who, w.sum()))
    columns = table_columns(prices, who)
    table = np.column_stack([floats_of(find_column(columns, name, who), who) for name in names])
    if "start-prices" in options:
        starts = named_numbers(options["start-prices"], names, ":start-prices", who)
        bought_at = np.array([starts[name] for name in names])
    else:
        bought_at = table[0]
    rebalance = options.get("rebalance", False)
    if rebalance is not False:
        rebalance = whole_number(rebalance, ":rebalance", who, 1)
    start_value = options.get("start-value", 1.0)
    if not is_number(start_value):
        raise LispError("%s: :start-value must be a number, not %s" % (who, start_value))

    holdings = start_value * w / bought_at                  # how many of each
    values = np.empty(len(table))
    for row, row_prices in enumerate(table):
        values[row] = holdings @ row_prices
        if rebalance and (row + 1) % rebalance == 0:
            holdings = values[row] * w / row_prices
    return to_vector(values)


# ---------------------------------------------------------------------------
# Covariance and correlation
# ---------------------------------------------------------------------------

def matrix_table(names, matrix):
    """A matrix as a table: an investment column with the names, and a column
    for each of them."""
    return make_table_value([("investment", LispVector([LispString(n) for n in names]))] +
                            [(name, to_vector(matrix[:, j])) for j, name in enumerate(names)])


def covariance_matrix(returns, *options):
    """(covariance-matrix returns [:days-per-year n]) -- the covariance of
    each pair of investments' returns, for a year: the daily returns'
    covariance times the days in a year (252, unless :days-per-year says), as
    a table (see this file's comment)."""
    who = "covariance-matrix"
    options = keyword_options(options, ["days-per-year"], who)
    days_per_year = options.get("days-per-year", DAYS_PER_YEAR)
    if not is_number(days_per_year) or days_per_year <= 0:
        raise LispError("%s: :days-per-year must be a number above 0, not %s" % (who, days_per_year))
    columns = return_columns(returns, who)
    if len(columns[0][1]) < 2:
        raise LispError("%s: it takes at least two days of returns" % who)
    data = np.array([values for _, values in columns])
    return matrix_table([name for name, _ in columns], np.atleast_2d(np.cov(data, ddof=1)) * days_per_year)


def correlation_matrix(returns):
    """(correlation-matrix returns) -- the correlation of each pair of
    investments' returns, from -1 to 1, as a table (see this file's comment)."""
    who = "correlation-matrix"
    columns = return_columns(returns, who)
    if len(columns[0][1]) < 2:
        raise LispError("%s: it takes at least two days of returns" % who)
    data = np.array([values for _, values in columns])
    return matrix_table([name for name, _ in columns], np.atleast_2d(np.corrcoef(data)))


def matrix_of(table, who):
    """A covariance matrix's table, as (names, numpy matrix)."""
    columns = table_columns(table, who)
    names = [str(n) for n in find_column(columns, "investment", who).items.tolist()]
    matrix = np.column_stack([floats_of(find_column(columns, name, who), who) for name in names])
    if matrix.shape != (len(names), len(names)) or not np.allclose(matrix, matrix.T):
        raise LispError("%s: the covariance matrix must be square and symmetric, as covariance-matrix makes" % who)
    return names, matrix


# ---------------------------------------------------------------------------
# Mean-variance weights
# ---------------------------------------------------------------------------

def solve_on(investments, Q, c):
    """The best weights for the quadratic program, using only the given
    investments (the others are 0): the weights w that make
    w Q w / 2 - c w least with the weights adding to 1, from the equations
    Q w - c = m (the same m for each) and sum w = 1. Returns (w, m)."""
    n = len(investments)
    equations = np.zeros((n + 1, n + 1))
    equations[:n, :n] = Q[np.ix_(investments, investments)]
    equations[:n, n] = -1.0
    equations[n, :n] = 1.0
    right = np.append(c[investments], 1.0)
    try:
        answer = np.linalg.solve(equations, right)
    except np.linalg.LinAlgError:
        raise LispError("the covariance matrix is singular: two investments move exactly together, or one never moves")
    w = np.zeros(len(c))
    w[investments] = answer[:n]
    return w, answer[n]


def best_weights(Q, c, long_only):
    """The weights that make w Q w / 2 - c w least, adding to 1, and, if
    long_only, none below 0 -- by leaving out, one at a time, the investment
    that would go furthest below 0, and letting back in one whose being left
    out costs the most, until neither happens (see this file's comment)."""
    everyone = list(range(len(c)))
    if not long_only:
        return solve_on(everyone, Q, c)[0]
    w = np.full(len(c), 1.0 / len(c))                      # a start with every weight allowed: equal weights
    free = list(everyone)
    for _ in range(10 * len(c) + 10):
        target, m = solve_on(free, Q, c)
        if np.all(target[free] >= -1e-12):
            w = np.maximum(target, 0.0)
            # A left-out investment would make it better if the slope there is below the others' (m).
            slopes = Q @ w - c - m
            out = [i for i in everyone if i not in free]
            if not out or min(slopes[i] for i in out) >= -1e-10:
                return w
            free.append(min(out, key=lambda i: slopes[i]))
            free.sort()
        else:
            # Go from w toward target as far as keeps every weight at 0 or more; the one that reaches 0 is left out.
            going_down = [i for i in free if target[i] < 0]
            steps = [w[i] / (w[i] - target[i]) for i in going_down]
            step = min(steps)
            w = w + step * (target - w)
            leaving = going_down[int(np.argmin(steps))]
            w[leaving] = 0.0
            free.remove(leaving)
    raise LispError("the long-only weights weren't found")


def weights_answer(names, w):
    return list_to_pairs([Pair(LispString(name), float(weight)) for name, weight in zip(names, w)])


def minimum_variance_weights(covariance, *options):
    """(minimum-variance-weights covariance [:long-only #t]) -- the weights,
    adding to 1, that make the portfolio's variance least, as a list of
    (name . weight). covariance is a table as covariance-matrix makes."""
    who = "minimum-variance-weights"
    options = keyword_options(options, ["long-only"], who)
    names, matrix = matrix_of(covariance, who)
    try:
        w = best_weights(matrix, np.zeros(len(names)), is_true(options.get("long-only", False)))
    except LispError as e:
        raise LispError("%s: %s" % (who, e))
    return weights_answer(names, w)


def mean_variance_weights(expected_returns, covariance, risk_aversion, *options):
    """(mean-variance-weights expected-returns covariance risk-aversion
    [:long-only #t]) -- the weights, adding to 1, that make the portfolio's
    expected return less risk-aversion / 2 times its variance greatest, as a
    list of (name . weight). expected-returns is a list of (name . annual
    return), one for each investment of covariance, a table as
    covariance-matrix makes. The larger risk-aversion, the closer the
    weights are to the minimum-variance ones; the smaller, the more of the
    investments with the highest expected returns."""
    who = "mean-variance-weights"
    options = keyword_options(options, ["long-only"], who)
    names, matrix = matrix_of(covariance, who)
    expected = named_numbers(expected_returns, names, "expected-returns", who)
    if not is_number(risk_aversion) or risk_aversion <= 0:
        raise LispError("%s: risk-aversion must be a number above 0, not %s" % (who, risk_aversion))
    try:
        w = best_weights(risk_aversion * matrix, np.array([expected[n] for n in names]),
                         is_true(options.get("long-only", False)))
    except LispError as e:
        raise LispError("%s: %s" % (who, e))
    return weights_answer(names, w)


def portfolio_volatility(weights, covariance):
    """(portfolio-volatility weights covariance) -- the volatility of a
    portfolio with these weights, a list of (name . weight), by the covariance
    matrix (as covariance-matrix makes, for a year): the square root of
    the sum of weight(i) weight(j) covariance(i, j)."""
    who = "portfolio-volatility"
    names, matrix = matrix_of(covariance, who)
    by_name = named_numbers(weights, names, "weights", who)
    w = np.array([by_name[n] for n in names])
    return float(np.sqrt(max(w @ matrix @ w, 0.0)))


BUILTINS = {
    "combine-returns": combine_returns,
    "bootstrap-paths": bootstrap_paths,
    "portfolio-value": portfolio_value,
    "covariance-matrix": covariance_matrix,
    "correlation-matrix": correlation_matrix,
    "portfolio-volatility": portfolio_volatility,
    "minimum-variance-weights": minimum_variance_weights,
    "mean-variance-weights": mean_variance_weights,
}
