"""Option prices for the Lisp interpreter: Black-Scholes-Merton and Black's
formula, implied volatility, the Greeks, and American options, by a
binomial tree.

  (normal-cdf x)                                      N(x), the standard normal distribution
  (bsm-price type spot strike time rate vol [:dividend-yield q])
  (implied-vol price type spot strike time rate [:dividend-yield q])
  (bsm-delta ...), (bsm-gamma ...), (bsm-vega ...), (bsm-theta ...), (bsm-rho ...)
                                                      the Greeks, with bsm-price's arguments
  (black-price type forward strike T discount vol)    Black's formula, from a forward price
  (black-implied-vol type price forward strike T discount)
  (american-price type spot strike time rate vol [:dividend-yield q] [:dividends table]
                  [:steps n] [:early-exercise #f])
  (american-implied-vol price type spot strike time rate [the same options])

ARGUMENTS: each can be a number or a vector, with an element for each
option, so a whole chain is priced at once, and the answer is then a
vector. type is "call" or "put" (in any case: tastytrade has "Call"), or
#t or 1 for a call and #f or 0 for a put. time and T are in years, rate is
continuously compounded (0.04 for 4%), and vol is a year's volatility (0.2
for 20%).

BLACK-SCHOLES-MERTON prices a European option on a stock from the stock's
price; Black's formula prices it from the forward price F and the discount
factor. They are the same formula, since F = spot e^((rate - q) time) and
discount = e^(-rate time); bsm-price is black-price with those.

IMPLIED VOLATILITY is the volatility at which the formula gives the price.
It is found by bisection: start with the range 0.1% to 500%, and halve it
50 times, each time keeping the half the answer is in (the price rises
with volatility). It is NaN where no volatility gives the price: one below
what the option would be worth at expiration, say.

THE GREEKS are how much the price changes: delta, for a change of 1 in the
stock's price; gamma, how much delta changes for that; vega, for a change
of 1 point (0.01) in volatility; theta, for a calendar day passing (1/365
of a year); and rho, for a change of 1 point (0.01) in the interest rate.
They are the formulas' derivatives.

AMERICAN OPTIONS can be exercised before they expire. Their price is found
with a binomial tree (Cox, Ross, and Rubinstein's): in each of `steps`
steps the price goes up by a factor u = e^(vol sqrt(dt)) or down by 1/u,
with the chance of going up that makes the stock grow at the interest rate
(less q). Working back from expiration, an option is worth the larger of
what it would pay if exercised then and what keeping it is worth.
Dividends that are known amounts on known dates (:dividends, a table of
time, in years, and amount) are handled by giving the tree the price less
the present value of the dividends still to come before expiration: an
option exercised early gets the whole price, that part and the rest.
"""

import math

import numpy as np

from lisp_core import LispError, LispVector, keyword_options
from lisp_tables import find_column, table_columns
from lisp_vector_math import floats_of, is_number, to_vector

LOWEST_VOL, HIGHEST_VOL = 0.001, 5.0        # the range implied volatility is looked for in
HALVINGS = 50                               # how many times the range is halved
STEPS = 200                                 # a binomial tree's steps, unless :steps says


# ---------------------------------------------------------------------------
# Arguments: a number or a vector, for each option
# ---------------------------------------------------------------------------

def numbers_argument(value, name, who):
    """A number, or a vector of numbers, as a float64 array."""
    if isinstance(value, LispVector):
        return floats_of(value, who)
    if is_number(value):
        return np.array([float(value)])
    raise LispError("%s: %s must be a number or a vector of numbers, not %s" % (who, name, value))


def calls_argument(value, who):
    """An option type, or a vector of them, as a bool array: True for a call."""
    items = value.items.tolist() if isinstance(value, LispVector) else [value]
    calls = []
    for item in items:
        if isinstance(item, str) and item.lower() in ("call", "put"):
            calls.append(item.lower() == "call")
        elif isinstance(item, bool) or is_number(item):
            calls.append(bool(item))
        else:
            raise LispError('%s: an option type is "call" or "put" (or #t or 1 for a call), not %s' % (who, item))
    return np.array(calls)


def side_by_side(who, *arrays):
    """The arrays made the same length: an array of one element stands for
    every option. An error if two vectors have different lengths."""
    try:
        return np.broadcast_arrays(*arrays)
    except ValueError:
        raise LispError("%s: the vectors must all be the same length, one element for each option" % who)


def answer(result, arguments):
    """A vector if any argument was one, otherwise the one number."""
    if any(isinstance(a, LispVector) for a in arguments):
        return to_vector(result)
    return float(result[0])


def dividend_yield_option(options, who):
    q = options.get("dividend-yield", 0.0)
    if not is_number(q):
        raise LispError("%s: :dividend-yield must be a number, 0.02 for 2%%, not %s" % (who, q))
    return float(q)


# ---------------------------------------------------------------------------
# The normal distribution, and Black's formula
# ---------------------------------------------------------------------------

_erf = np.vectorize(math.erf, otypes=[float])


def normal_cdf_array(x):
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / math.sqrt(2.0)))


def normal_density(x):
    return np.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def normal_cdf(x):
    """(normal-cdf x) -- the chance that a standard normal number is below x:
    0.5 (1 + erf(x / sqrt 2)). x can be a vector."""
    return answer(normal_cdf_array(numbers_argument(x, "x", "normal-cdf")), [x])


def black_formula(call, forward, strike, T, discount, vol):
    """Black's formula, for arrays of options: discount (F N(d1) - K N(d2))
    for a call and discount (K N(-d2) - F N(-d1)) for a put, with
    d1 = log(F/K) / (vol sqrt(T)) + vol sqrt(T) / 2 and d2 = d1 - vol sqrt(T).
    With no time or no volatility left, an option is worth what it pays now."""
    spread = vol * np.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = np.log(forward / strike) / spread + spread / 2
        d2 = d1 - spread
        call_price = discount * (forward * normal_cdf_array(d1) - strike * normal_cdf_array(d2))
        put_price = discount * (strike * normal_cdf_array(-d2) - forward * normal_cdf_array(-d1))
    priced = np.where(call, call_price, put_price)
    at_once = discount * np.where(call, np.maximum(forward - strike, 0), np.maximum(strike - forward, 0))
    return np.where(spread > 0, priced, at_once)


def black_implied(call, price, forward, strike, T, discount):
    """The volatility at which Black's formula gives price, for arrays of
    options, by bisection; NaN where none in the range does."""
    low = np.full(len(price), LOWEST_VOL)
    high = np.full(len(price), HIGHEST_VOL)
    for _ in range(HALVINGS):
        middle = (low + high) / 2
        too_high = black_formula(call, forward, strike, T, discount, middle) > price
        high = np.where(too_high, middle, high)
        low = np.where(too_high, low, middle)
    found = (low + high) / 2
    # an answer at either end of the range means no volatility gives the price
    return np.where((found > LOWEST_VOL * 1.1) & (found < HIGHEST_VOL * 0.9998), found, np.nan)


def black_price(kind, forward, strike, T, discount, vol):
    """(black-price type forward strike T discount vol) -- the price of a
    European option by Black's formula, from the forward price."""
    who = "black-price"
    arguments = [kind, forward, strike, T, discount, vol]
    arrays = side_by_side(who, calls_argument(kind, who), numbers_argument(forward, "forward", who),
                          numbers_argument(strike, "strike", who), numbers_argument(T, "T", who),
                          numbers_argument(discount, "discount", who), numbers_argument(vol, "vol", who))
    return answer(black_formula(*arrays), arguments)


def black_implied_vol(kind, price, forward, strike, T, discount):
    """(black-implied-vol type price forward strike T discount) -- the
    volatility at which Black's formula gives price; NaN where none does."""
    who = "black-implied-vol"
    arguments = [kind, price, forward, strike, T, discount]
    call, price, forward, strike, T, discount = side_by_side(
        who, calls_argument(kind, who), numbers_argument(price, "price", who),
        numbers_argument(forward, "forward", who), numbers_argument(strike, "strike", who),
        numbers_argument(T, "T", who), numbers_argument(discount, "discount", who))
    return answer(black_implied(call, price, forward, strike, T, discount), arguments)


# ---------------------------------------------------------------------------
# Black-Scholes-Merton: from the stock's price
# ---------------------------------------------------------------------------

def bsm_arrays(kind, spot, strike, time, rate, vol, options, who, vol_name="vol"):
    """The arguments of a bsm- function, as arrays of the same length, with
    the dividend yield; vol may be None (for implied-vol)."""
    options = keyword_options(options, ["dividend-yield"], who)
    arrays = [calls_argument(kind, who), numbers_argument(spot, "spot", who),
              numbers_argument(strike, "strike", who), numbers_argument(time, "time", who),
              numbers_argument(rate, "rate", who)]
    if vol is not None:
        arrays.append(numbers_argument(vol, vol_name, who))
    return side_by_side(who, *arrays), dividend_yield_option(options, who)


def bsm_price(kind, spot, strike, time, rate, vol, *options):
    """(bsm-price type spot strike time rate vol [:dividend-yield q]) -- the
    Black-Scholes-Merton price of a European option."""
    (call, spot_, strike_, time_, rate_, vol_), q = bsm_arrays(kind, spot, strike, time, rate, vol, options, "bsm-price")
    forward = spot_ * np.exp((rate_ - q) * time_)
    discount = np.exp(-rate_ * time_)
    return answer(black_formula(call, forward, strike_, time_, discount, vol_), [kind, spot, strike, time, rate, vol])


def implied_vol(price, kind, spot, strike, time, rate, *options):
    """(implied-vol price type spot strike time rate [:dividend-yield q]) --
    the volatility at which bsm-price gives price; NaN where none does."""
    who = "implied-vol"
    (call, spot_, strike_, time_, rate_, price_), q = bsm_arrays(kind, spot, strike, time, rate, price, options, who,
                                                                 vol_name="price")
    forward = spot_ * np.exp((rate_ - q) * time_)
    discount = np.exp(-rate_ * time_)
    return answer(black_implied(call, price_, forward, strike_, time_, discount),
                  [price, kind, spot, strike, time, rate])


def bsm_greek(name, formula):
    """A bsm- function for one of the Greeks: formula is given the options'
    arrays and returns the Greek's for each."""
    who = "bsm-" + name

    def greek(kind, spot, strike, time, rate, vol, *options):
        (call, s, k, t, r, v), q = bsm_arrays(kind, spot, strike, time, rate, vol, options, who)
        if not np.all((t > 0) & (v > 0)):
            raise LispError("%s: the time and the volatility must be above 0" % who)
        d1 = (np.log(s / k) + (r - q + v * v / 2) * t) / (v * np.sqrt(t))
        d2 = d1 - v * np.sqrt(t)
        return answer(formula(call, s, k, t, r, v, q, d1, d2), [kind, spot, strike, time, rate, vol])
    greek.__doc__ = "(%s type spot strike time rate vol [:dividend-yield q]) -- see this file's comment." % who
    return greek


def delta(call, s, k, t, r, v, q, d1, d2):
    return np.exp(-q * t) * np.where(call, normal_cdf_array(d1), normal_cdf_array(d1) - 1)


def gamma(call, s, k, t, r, v, q, d1, d2):
    return np.exp(-q * t) * normal_density(d1) / (s * v * np.sqrt(t))


def vega(call, s, k, t, r, v, q, d1, d2):
    return s * np.exp(-q * t) * normal_density(d1) * np.sqrt(t) * 0.01        # for a volatility point


def theta(call, s, k, t, r, v, q, d1, d2):
    decay = -s * np.exp(-q * t) * normal_density(d1) * v / (2 * np.sqrt(t))
    call_theta = decay - r * k * np.exp(-r * t) * normal_cdf_array(d2) + q * s * np.exp(-q * t) * normal_cdf_array(d1)
    put_theta = decay + r * k * np.exp(-r * t) * normal_cdf_array(-d2) - q * s * np.exp(-q * t) * normal_cdf_array(-d1)
    return np.where(call, call_theta, put_theta) / 365                          # for a calendar day


def rho(call, s, k, t, r, v, q, d1, d2):
    return np.where(call, k * t * np.exp(-r * t) * normal_cdf_array(d2),
                    -k * t * np.exp(-r * t) * normal_cdf_array(-d2)) * 0.01    # for a point of interest rate


# ---------------------------------------------------------------------------
# American options: a binomial tree
# ---------------------------------------------------------------------------

def dividends_option(options, who):
    """:dividends, a table of time (in years) and amount columns, as arrays;
    empty ones if there are none."""
    table = options.get("dividends")
    if table is None:
        return np.zeros(0), np.zeros(0)
    columns = table_columns(table, who)
    times = floats_of(find_column(columns, "time", who), who)
    amounts = floats_of(find_column(columns, "amount", who), who)
    if not np.all(amounts >= 0):
        raise LispError("%s: every dividend amount must be a number, 0 or more" % who)
    return times, amounts


def tree_price(call, spot, strike, time, rate, vol, q, dividend_times, dividend_amounts, steps, early):
    """One option's price, by a binomial tree of `steps` steps; early says
    whether it can be exercised before it expires (American) or not."""
    if math.isnan(vol) or math.isnan(spot):
        return math.nan                                 # (no volatility to price it with)
    if time <= 0:
        return max(spot - strike, 0.0) if call else max(strike - spot, 0.0)
    if vol <= 0:
        raise LispError("american-price: the volatility must be above 0")
    dt = time / steps
    up = math.exp(vol * math.sqrt(dt))
    chance_up = (math.exp((rate - q) * dt) - 1 / up) / (up - 1 / up)
    if not 0 < chance_up < 1:
        raise LispError("american-price: %d steps are too few for this volatility and rate -- give more :steps" % steps)
    step_discount = math.exp(-rate * dt)

    before_expiration = (dividend_times > 0) & (dividend_times <= time)
    times, amounts = dividend_times[before_expiration], dividend_amounts[before_expiration]

    def dividends_to_come(t):
        """The present value, at time t, of the dividends after t."""
        later = times > t
        return float(np.sum(amounts[later] * np.exp(-rate * (times[later] - t))))

    start = spot - dividends_to_come(0.0)           # the price less the dividends to come, which the tree moves
    if start <= 0:
        raise LispError("american-price: the dividends are worth more than the price")

    def exercise_values(step):
        """What the option would pay at each node of a step, exercised then."""
        prices = start * up ** (step - 2.0 * np.arange(step + 1)) + dividends_to_come(step * dt)
        return np.maximum(prices - strike, 0.0) if call else np.maximum(strike - prices, 0.0)

    values = exercise_values(steps)
    for step in range(steps - 1, -1, -1):
        values = step_discount * (chance_up * values[:-1] + (1 - chance_up) * values[1:])
        if early:
            values = np.maximum(values, exercise_values(step))
    return float(values[0])


def american_arrays(kind, spot, strike, time, rate, vol, options, who, vol_name="vol"):
    options = keyword_options(options, ["dividend-yield", "dividends", "steps", "early-exercise"], who)
    arrays = side_by_side(who, calls_argument(kind, who), numbers_argument(spot, "spot", who),
                          numbers_argument(strike, "strike", who), numbers_argument(time, "time", who),
                          numbers_argument(rate, "rate", who), numbers_argument(vol, vol_name, who))
    steps = options.get("steps", STEPS)
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 1:
        raise LispError("%s: :steps must be a whole number, 1 or more, not %s" % (who, steps))
    early = options.get("early-exercise", True) is not False
    return arrays, dividend_yield_option(options, who), dividends_option(options, who), steps, early


def american_price(kind, spot, strike, time, rate, vol, *options):
    """(american-price type spot strike time rate vol [:dividend-yield q]
    [:dividends table] [:steps n] [:early-exercise #f]) -- the price of an
    option that can be exercised early, by a binomial tree. :early-exercise
    #f prices the European option with the same tree, for comparing."""
    who = "american-price"
    arrays, q, (times, amounts), steps, early = american_arrays(kind, spot, strike, time, rate, vol, options, who)
    prices = [tree_price(c, s, k, t, r, v, q, times, amounts, steps, early) for c, s, k, t, r, v in zip(*arrays)]
    return answer(np.array(prices), [kind, spot, strike, time, rate, vol])


def american_implied_vol(price, kind, spot, strike, time, rate, *options):
    """(american-implied-vol price type spot strike time rate [the options of
    american-price]) -- the volatility at which american-price gives price,
    by bisection; NaN where none does."""
    who = "american-implied-vol"
    arrays, q, (times, amounts), steps, early = american_arrays(kind, spot, strike, time, rate, price, options, who,
                                                                vol_name="price")
    found = []
    for call, s, k, t, r, target in zip(*arrays):
        low, high = LOWEST_VOL, HIGHEST_VOL
        for _ in range(HALVINGS):
            middle = (low + high) / 2
            if tree_price(call, s, k, t, r, middle, q, times, amounts, steps, early) > target:
                high = middle
            else:
                low = middle
        middle = (low + high) / 2
        found.append(middle if LOWEST_VOL * 1.1 < middle < HIGHEST_VOL * 0.9998 else math.nan)
    return answer(np.array(found), [price, kind, spot, strike, time, rate])


BUILTINS = {
    "normal-cdf": normal_cdf,
    "black-price": black_price,
    "black-implied-vol": black_implied_vol,
    "bsm-price": bsm_price,
    "implied-vol": implied_vol,
    "bsm-delta": bsm_greek("delta", delta),
    "bsm-gamma": bsm_greek("gamma", gamma),
    "bsm-vega": bsm_greek("vega", vega),
    "bsm-theta": bsm_greek("theta", theta),
    "bsm-rho": bsm_greek("rho", rho),
    "american-price": american_price,
    "american-implied-vol": american_implied_vol,
}
