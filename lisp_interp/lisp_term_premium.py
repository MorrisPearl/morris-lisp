"""What a Treasury yield is made of: the rates the market expects, and a premium for holding a long bond.

A 10-year yield is close to the average of the short rates of the next 10 years -- what money kept in
1-month bills would earn, a month at a time. It is not exactly that, for two reasons:

  the term premium  a long bond's price swings when rates move, and the people who hold one want to be
                    paid for that: its yield is higher (usually) than the short rates they expect
  convexity         a bond's price is a convex function of its yield, so uncertainty about rates makes
                    the bond worth a little more, and its yield a little lower

so that

  yield = expected short rates (their average to the bond's maturity) + convexity + term premium

Neither the expected rates nor the term premium can be seen in prices: a model has to separate them. The
model here is the one the New York Fed publishes the term premium from, by Adrian, Crump and Moench ("Pricing
the Term Structure with Linear Regressions", 2013), "ACM" for short. Every step of it is a linear
regression:

  1. The curve, at each month's end, is summed up by 5 numbers, the principal components of its yields
     (from 3 months to 10 years): its level, its slope, its curvature and two smaller bends.
  2. How those 5 numbers move from one month to the next: each month's are a straight-line function of the
     last month's (a vector autoregression), plus a surprise. That says what the curve is expected to be
     in a month, a year, or 10 years, and so what the short rate is expected to be.
  3. How much more than the 1-month rate a bond of each maturity earned in each month (its excess return),
     as a straight-line function of the 5 numbers at the start of the month and the month's surprises. The
     part of the excess return the start of the month predicts is what investors were paid for bearing the
     risk of the surprises: the prices of risk.
  4. The yield of a bond of every maturity is then worked out from the model's numbers twice: once with the
     prices of risk (the yield the model fits to the curve), and once without them (the yield the bond
     would have if investors didn't care about risk). The term premium is the difference.

The yield without the prices of risk is the expected short rates plus convexity; the expected short rates,
by themselves, come from step 2. The New York Fed calls the yield without prices of risk the "risk-neutral
yield", and publishes it and the term premium for maturities of 1 to 10 years (www.newyorkfed.org, "Treasury
Term Premia"). The numbers here come out within about 0.2 percentage points of those, moving with them
(correlation 0.9998 for the 10-year term premium from 1961 to 2026): the details of the data differ.

The curve is the Fed's fitted curve (gsw-curve, yield_curves.lsp), which the paper uses: its six numbers
give a zero rate at any maturity, including the 1-month rate, which is the short rate here.

The Lisp builtin is term-premium-decomposition; yield-slope-decomposition (yield_curves.lsp) takes its
table and gives the slope of the curve, between two maturities, in the same pieces.
"""

import datetime
import numbers

import numpy as np

from lisp_core import NIL, LispDate, LispError, LispVector, Pair, keyword_options, pairs_to_list
from lisp_tables import make_table_value, table_columns


# Maturities, in months, of the yields the principal components are taken from, and of the bonds whose
# excess returns give the prices of risk -- the paper's choices.
COMPONENT_MONTHS = np.arange(3, 121)          # 3 months to 10 years
RETURN_MONTHS = np.arange(6, 121, 6)          # 6 months, 1 year, ... 10 years
LONGEST_MONTHS = 120                          # the model is fitted to maturities up to 10 years
FEWEST_MONTHS = 60                            # months of history needed to fit it


# ---------------------------------------------------------------------------
# The curve, from the Fed's table
# ---------------------------------------------------------------------------

def svensson_zero_rates(parameters, months):
    """The zero rates (continuously compounded, as decimals) of Svensson curves, at maturities in months.
    parameters has a row (beta0 beta1 beta2 beta3 tau1 tau2) for each day; the result has a row for each day
    and a column for each maturity. The same formula as svensson-zero-rates in yield_curves.lsp."""
    years = np.asarray(months, dtype=float) / 12.0
    beta0, beta1, beta2, beta3, tau1, tau2 = [parameters[:, [i]] for i in range(6)]
    x1, x2 = years / tau1, years / tau2
    slope1, slope2 = (1 - np.exp(-x1)) / x1, (1 - np.exp(-x2)) / x2
    return beta0 + beta1 * slope1 + beta2 * (slope1 - np.exp(-x1)) + beta3 * (slope2 - np.exp(-x2))


def curve_days_and_parameters(fed, who):
    """The days of the Fed's table (as gsw-curve makes it) and the six numbers of each day's curve, as a list of
    LispDates and an array with a row for each day. Days with no curve are left out. Before 1980 the Fed's curve
    has no second hump (beta3 and tau2 are nan): it is then the same curve with beta3 = 0."""
    columns = dict(table_columns(fed, who))
    needed = ["date", "beta0", "beta1", "beta2", "beta3", "tau1", "tau2"]
    missing = [name for name in needed if name not in columns]
    if missing:
        raise LispError("%s: the table needs the columns %s, as gsw-curve makes; it has no %s"
                        % (who, ", ".join(needed), ", ".join(missing)))
    days = list(columns["date"].items)
    parameters = np.array([[float(x) for x in columns[name].items] for name in needed[1:]]).T
    no_hump = np.isnan(parameters[:, 3]) | np.isnan(parameters[:, 5])
    parameters[no_hump, 3] = 0.0
    parameters[no_hump, 5] = 1.0                  # any number: beta3 is 0
    usable = ~np.isnan(parameters).any(axis=1)
    return [day for day, keep in zip(days, usable) if keep], parameters[usable]


def month_end_rows(days):
    """The positions of the last day of each month among days (which are in order, the oldest first)."""
    rows = []
    for i, day in enumerate(days):
        if i + 1 == len(days) or (days[i + 1].date.year, days[i + 1].date.month) != (day.date.year, day.date.month):
            rows.append(i)
    return rows


# ---------------------------------------------------------------------------
# Fitting the model: steps 1 to 3
# ---------------------------------------------------------------------------

def least_squares(predictors, targets):
    """The coefficients of the straight-line fit of each column of targets on the columns of predictors."""
    return np.linalg.lstsq(predictors, targets, rcond=None)[0]


def fit_term_premium_model(month_end_yields, factors=5):
    """The ACM model, fitted to a history of curves: month_end_yields has a row for each month's end and a column
    for each maturity of 1 to 120 months (zero rates for a year, continuously compounded). The result is a dict
    of the model's numbers, in monthly units (a rate of 0.0036 is 0.0036 a month):

      mean, weights   how a curve becomes its factors: factors = (yields - mean) . weights'
      mu, phi         the factors' movement: next month's = mu + phi . this month's + a surprise
      sigma           the surprises' covariance
      noise           the variance of the part of excess returns the model doesn't explain
      lambda0, lambda1  the prices of risk: what a unit of each surprise is paid, lambda0 + lambda1 . factors
      delta0, delta1  the short rate (the 1-month rate) as delta0 + delta1 . factors
      factors         the factors at each month's end
    """
    monthly_log_prices = -month_end_yields * np.arange(1, LONGEST_MONTHS + 1) / 12.0   # log of what 1 at n months costs
    months = len(month_end_yields)

    # Step 1. The factors: the principal components of the yields of 3 months to 10 years.
    component_yields = month_end_yields[:, COMPONENT_MONTHS - 1]
    mean = component_yields.mean(axis=0)
    weights = np.linalg.svd(component_yields - mean, full_matrices=False)[2][:factors]
    factor_values = (component_yields - mean) @ weights.T

    # Step 2. How the factors move from month to month: next month's on this month's.
    this_month = np.column_stack([np.ones(months - 1), factor_values[:-1]])
    movement = least_squares(this_month, factor_values[1:])
    mu, phi = movement[0], movement[1:].T
    surprises = factor_values[1:] - this_month @ movement
    sigma = surprises.T @ surprises / (months - 1)

    # Step 3. Excess returns: a bond of n months, bought at a month's end and sold a month later (when it has
    # n - 1 months left), less the 1-month rate. Each maturity's, on the factors at the start and the surprises.
    short_rate = -monthly_log_prices[:, 0]
    excess_returns = np.column_stack([monthly_log_prices[1:, n - 2] - monthly_log_prices[:-1, n - 1] - short_rate[:-1]
                                      for n in RETURN_MONTHS])
    predictors = np.column_stack([np.ones(months - 1), surprises, factor_values[:-1]])
    fit = least_squares(predictors, excess_returns)
    constant, exposure, predicted_by_factors = fit[0], fit[1:1 + factors], fit[1 + factors:].T
    left_over = excess_returns - predictors @ fit
    noise = (left_over ** 2).sum() / left_over.size
    # A bond's expected excess return is its exposure to the surprises times the prices of risk, less half
    # its variance (a log return's mean is less than its expected return): solving for the prices of risk.
    exposure_squared = np.array([np.outer(exposure[:, i], exposure[:, i]).ravel() for i in range(len(RETURN_MONTHS))])
    to_prices = np.linalg.solve(exposure @ exposure.T, exposure)
    lambda0 = to_prices @ (constant + 0.5 * (exposure_squared @ sigma.ravel() + noise))
    lambda1 = to_prices @ predicted_by_factors

    # The short rate, on the factors.
    short = least_squares(np.column_stack([np.ones(months), factor_values]), short_rate)
    return {"mean": mean, "weights": weights, "mu": mu, "phi": phi, "sigma": sigma, "noise": noise,
            "lambda0": lambda0, "lambda1": lambda1, "delta0": short[0], "delta1": short[1:],
            "factors": factor_values}


# ---------------------------------------------------------------------------
# Yields from the model: step 4
# ---------------------------------------------------------------------------

def yield_loadings(model, lambda0, lambda1, longest):
    """The log price of a bond of n months, for n = 0 to longest, as A[n] + B[n] . factors, in a model whose
    prices of risk are lambda0 and lambda1. A bond of n months is worth, a month before, the 1-month bond's
    worth of what a bond of n - 1 months will be worth then -- on average over the surprises, with risk
    paid for at the prices of risk -- which gives each A and B from the last:
      A[n] = A[n-1] + B[n-1] . (mu - lambda0) + (B[n-1] . sigma . B[n-1] + noise) / 2 - delta0
      B[n] = B[n-1] . (phi - lambda1) - delta1"""
    factors = len(model["mu"])
    a = np.zeros(longest + 1)
    b = np.zeros((longest + 1, factors))
    for n in range(1, longest + 1):
        a[n] = (a[n - 1] + b[n - 1] @ (model["mu"] - lambda0)
                + 0.5 * (b[n - 1] @ model["sigma"] @ b[n - 1] + model["noise"]) - model["delta0"])
        b[n] = b[n - 1] @ (model["phi"] - lambda1) - model["delta1"]
    return a, b


def model_yields(loadings, factor_values, months):
    """The yields, for a year, of bonds of these maturities (in months), from loadings as yield_loadings gives:
    a row for each row of factor_values and a column for each maturity."""
    a, b = loadings
    return np.column_stack([-(a[n] + factor_values @ b[n]) / n * 12 for n in months])


def expected_short_rates(model, factor_values, months):
    """The average of the short rates expected over each of these maturities (in months), for a year: a row for
    each row of factor_values and a column for each maturity. The factors expected in a month are
    mu + phi . today's, in two months the same again, and so on; the short rate is delta0 + delta1 . factors."""
    expected = factor_values.copy()
    total = np.zeros(len(factor_values))
    averages = {}
    for month in range(1, max(months) + 1):
        total += model["delta0"] + expected @ model["delta1"]       # the rate of this month
        averages[month] = total / month * 12
        expected = model["mu"] + expected @ model["phi"].T
    return np.column_stack([averages[n] for n in months])


# ---------------------------------------------------------------------------
# The builtin
# ---------------------------------------------------------------------------

def _maturities_in_months(years, who):
    """The :years choice -- a number, a list or a vector of them -- as whole months, from 1 to 120."""
    if isinstance(years, numbers.Real):
        values = [years]
    elif isinstance(years, LispVector):
        values = list(years.items)
    elif years is NIL or isinstance(years, Pair):
        values = pairs_to_list(years)
    else:
        raise LispError("%s: :years is a number of years, or a list or vector of them, not %s" % (who, years))
    months = []
    for value in values:
        if not isinstance(value, numbers.Real) or isinstance(value, bool):
            raise LispError("%s: each of :years is a number of years, not %s" % (who, value))
        n = int(round(float(value) * 12))
        if abs(n - float(value) * 12) > 1e-6 or n < 1 or n > LONGEST_MONTHS:
            raise LispError("%s: each of :years is a whole number of months, from 1/12 to 10 years, not %s"
                            % (who, value))
        months.append(n)
    if not months:
        raise LispError("%s: :years is empty" % who)
    return sorted(set(months))


def _day_value(value, who):
    if value is NIL:
        return None
    if isinstance(value, LispDate):
        return value.date
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise LispError("%s: a day is a date, or YYYY-MM-DD text, not %s" % (who, value))


def term_premium_decomposition_fn(fed, *options):
    """(term-premium-decomposition fed [:years y :factors k :daily #t :start-date d]) -> a table

    Each Treasury zero yield split into what it is made of, by the model the New York Fed publishes its
    term premium from (Adrian, Crump and Moench): the rates the market expects, convexity, and the term
    premium. fed is the Fed's curve, a table as gsw-curve makes, with enough history to fit the model to:
    at least 5 years of it, and better all of it, from 1961. The model is fitted to the last day of each
    month, from :start-date (all of fed, if not given) on.

    The table has a row for each day and maturity: each month's last day, and the last day in fed, if that
    isn't one -- or, with :daily #t, every day in fed from :start-date. Its columns, the rates as decimals
    for a year, continuously compounded:
      date           the day
      years          the maturity: each of :years (0.25 2 5 10), from 1/12 to 10
      yield          the Fed's zero rate at that maturity, that day
      fitted         the model's yield, from the day's five factors
      expected       the average of the short rates the model expects, from the day to the maturity
      convexity      what uncertainty about rates takes off the yield (a small negative number)
      term-premium   what investors are paid for holding the bond rather than rolling over 1-month bills
      error          yield less fitted: what the five factors don't capture
    so that yield = expected + convexity + term-premium + error. :factors (5) is how many principal
    components of the curve the model has.

    yield-slope-decomposition takes this table and gives the slope of the curve, between two maturities, in
    the same pieces."""
    who = "term-premium-decomposition"
    chosen = keyword_options(options, ["years", "factors", "daily", "start-date"], who)
    months = _maturities_in_months(chosen.get("years", LispVector([0.25, 2, 5, 10])), who)
    factors = chosen.get("factors", 5)
    if not isinstance(factors, int) or isinstance(factors, bool) or not 1 <= factors <= 10:
        raise LispError("%s: :factors is a whole number from 1 to 10, not %s" % (who, factors))
    daily = chosen.get("daily", False) not in (False, NIL)
    start = _day_value(chosen.get("start-date", NIL), who)

    days, parameters = curve_days_and_parameters(fed, who)
    if start is not None:
        keep = [day.date >= start for day in days]
        days = [day for day, k in zip(days, keep) if k]
        parameters = parameters[np.array(keep, dtype=bool)] if days else parameters[:0]
    month_ends = month_end_rows(days)
    if len(month_ends) < FEWEST_MONTHS:
        raise LispError("%s: the model needs at least %d months of the Fed's curve to be fitted to, and there are %d "
                        "-- (gsw-curve) with no dates has all of it, from 1961" % (who, FEWEST_MONTHS, len(month_ends)))

    model = fit_term_premium_model(svensson_zero_rates(parameters[month_ends], np.arange(1, LONGEST_MONTHS + 1)), factors)

    shown = list(range(len(days))) if daily else month_ends + ([len(days) - 1] if month_ends[-1] != len(days) - 1 else [])
    curves = svensson_zero_rates(parameters[shown], np.arange(1, LONGEST_MONTHS + 1))
    factor_values = (curves[:, COMPONENT_MONTHS - 1] - model["mean"]) @ model["weights"].T
    actual = curves[:, np.array(months) - 1]
    fitted = model_yields(yield_loadings(model, model["lambda0"], model["lambda1"], max(months)), factor_values, months)
    risk_neutral = model_yields(yield_loadings(model, np.zeros(factors), np.zeros((factors, factors)), max(months)),
                                factor_values, months)
    expected = expected_short_rates(model, factor_values, months)
    if not (np.isfinite(fitted).all() and np.isfinite(risk_neutral).all()):
        raise LispError("%s: the model's yields grow without limit: with %d factors, some of them hardly move and their "
                        "prices of risk can't be measured -- try fewer :factors, or more history" % (who, factors))

    def by_row(values):
        return LispVector([float(x) for x in values.ravel()])                # a day's maturities, then the next day's
    return make_table_value([
        ("date", LispVector([days[i] for i in shown for _ in months])),
        ("years", LispVector([n / 12.0 for _ in shown for n in months])),
        ("yield", by_row(actual)),
        ("fitted", by_row(fitted)),
        ("expected", by_row(expected)),
        ("convexity", by_row(risk_neutral - expected)),
        ("term-premium", by_row(fitted - risk_neutral)),
        ("error", by_row(actual - fitted)),
    ])


BUILTINS = {
    "term-premium-decomposition": term_premium_decomposition_fn,
}
