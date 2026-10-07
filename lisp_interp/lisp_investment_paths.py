"""Simulated investment prices for the Lisp interpreter: a block bootstrap of an
investment's own daily returns.

  (daily-returns prices [:dividends table])
                     an investment's daily returns, from its prices (and dividends)
  (adjust-returns returns annual-return [:days-per-year n] [:volatility-scale x])
                     the returns, with their average changed to give an
                     expected annual return (and their volatility, if asked)
  (dividend-schedule dividends start-date days [:repeat-last-year #t])
                     the dividends an investment will pay in the days of a path
  (bootstrap-path returns start-price days block-size [:seed n] [:dividends schedule]
                  [:volatility model] [:start-volatility x])
                     one simulated path of future prices
  (bootstrap-days returns days block-size [:seed n] [:volatility model] [:start-volatility x])
                     the days of the history a path is made of
  (volatility-model returns [:symmetric #t] [:days-per-year n])
                     a model of an investment's volatility, which changes from day to day
  (volatility-history returns model)
                     what the model says the volatility was on each day of the history
  (volatility-forecast model days [:start-volatility x])
                     the average volatility the model expects over the next days
  (option-value paths payoff rate years)
                     what an option is worth, from many paths
  (option-payoffs paths days strikes calls)
                     what many European options pay on average, from many paths

The idea: tomorrow's price is probably like the days in the investment's own
history, so build a future by copying pieces of the past. Each piece is a
"block" of consecutive days, rather than one day at a time, so that a
stretch of wild days (or calm ones) stays together, as it does in life.

THE RETURNS are log returns, ln(price today / price yesterday), which add
up: the price after a run of days is the starting price times e to the sum
of the days' log returns. That makes taking out the average and putting in
another a matter of subtracting and adding. A dividend is part of the
return of the day the investment first trades without it (the ex-date):
that day's return is ln((close + dividend) / yesterday's close).

THE DRIFT is an expected annual return, 0.08 for 8%. adjust-returns takes
the average out of the log returns, then adds a number that makes the
average of the daily returns (not the log returns -- the price rises by
those) come out at (1 + annual return) ^ (1 / days per year) - 1. So the
expected price a year out is the right one when a block is a single day;
with longer blocks it's close to right.

THE DIVIDENDS in a path are known amounts on known days, the same in every
path, however the price has done: when one comes, the price falls by its
amount (to 0, at the lowest). dividend-schedule makes the list of them from
a table of actual dividends, counting the days with the NYSE's calendar
(lisp_calendar.py). :repeat-last-year #t makes it from the last year of
actual dividends, which are supposed to go on, on the same dates (or, for a
date the market is closed, the next day it's open) and in the same
amounts. The returns for such a path are total returns, dividends
included, as daily-returns gives with :dividends, so that all of an
investment's return, dividends too, grows at the rate adjust-returns is
given.

THE PATHS wrap: a block that runs off the end of the history carries on
from its start, so every day is as likely as any other to be in a block.

TODAY'S VOLATILITY: a path copies blocks from anywhere in the history, so
it starts as wild as the history is on average, however calm or wild the
market is today. With :volatility, a model from volatility-model, a path
starts at today's volatility instead, and its volatility changes from day
to day as the model says, going back toward the history's average:

  1. The model estimates each day's volatility, from the day before's and
     how big the day before's move was (the formula is at next_variance).
  2. Each day's return less the average, divided by that day's volatility,
     is a "shock": how many of its own standard deviations the day moved.
     A 3% drop on a calm day is a big shock; on a wild day, a small one.
  3. A path copies the shocks of its blocks' days, instead of their
     returns, and multiplies each by the path's own volatility that day,
     which it then updates by the same formula with the move it just made.

So a path's first days are about as wild as the days just before it, and
a big simulated move makes the days after it wild, until they calm down
again -- each path differently. This is called "filtered historical
simulation"; the formula is a "GJR-GARCH(1,1)" model, fitted with the
long-run variance set to the history's ("variance targeting").

OPTION VALUES: the value of an option (or anything else paid after the
prices of a path) is estimated by working out what each path pays, taking
its present value, and averaging them. For that to be the option's fair
value, and not just what it pays on average if the investment earns what
you expect, the paths must grow at the interest rate: make them from
returns that adjust-returns has given the interest rate as the annual
return. The dividends must come out of the price, as above.

RANDOM NUMBERS: with :seed, bootstrap-path uses its own generator (as
vectors-shuffle does), so the same seed gives the same path every time --
pass a different seed for each path, or all the paths are the same. Without
:seed it uses the shared generator that random-float and random-int use,
which (random-seed n) makes reproducible.
"""

import datetime
import math
import random
from collections import namedtuple
from functools import lru_cache

import numpy as np

from lisp_core import (
    LispDate, LispError, LispString, LispVector, Pair, _lisp_scalar, apply_proc, is_true, keyword_options,
    list_to_pairs, pairs_to_list,
)
import lisp_calendar
from lisp_time_series import months_later
from lisp_tables import find_column, make_table_value, table_columns
from lisp_vector_math import floats_of, is_number, to_vector

RETURN_COLUMN = "log-return"        # the column of returns, in the tables these functions make and read
DAYS_PER_YEAR = 252                 # trading days, unless :days-per-year says otherwise


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

def daily_returns(prices, *options):
    """(daily-returns prices [:dividends table]) -- an investment's daily log
    returns: a table of date and log-return, oldest first, a row for each
    day of prices but the first. prices is a table with date and close
    columns, oldest first, as schwab-price-history makes. :dividends is a
    table with ex-date and amount columns, as alpha-vantage-dividends makes;
    without it a dividend shows up as a drop in the price, so an investment's
    returns are low by what it pays."""
    who = "daily-returns"
    options = keyword_options(options, ["dividends"], who)
    columns = table_columns(prices, who)
    dates = find_column(columns, "date", who)
    closes = floats_of(find_column(columns, "close", who), who)
    day_numbers = day_numbers_of(dates, who, "the dates")
    if len(closes) < 2:
        raise LispError("%s: it takes at least two prices to have a return" % who)
    if np.any(np.diff(day_numbers) <= 0):
        raise LispError("%s: the prices must be in order of date, oldest first, with one for each date" % who)
    if not np.all(closes > 0):
        raise LispError("%s: every close must be a number above 0" % who)

    paid = np.zeros(len(closes))
    if options.get("dividends") is not None:
        paid = dividends_by_day(options["dividends"], day_numbers, who)
    log_returns = np.log((closes[1:] + paid[1:]) / closes[:-1])
    return make_table_value([("date", LispVector(dates.items[1:])), (RETURN_COLUMN, to_vector(log_returns))])


def day_numbers_of(dates, who, what):
    """A vector of dates as an array of day numbers, which can be compared."""
    if not all(isinstance(d, LispDate) for d in dates.items):
        raise LispError("%s: %s must all be dates" % (who, what))
    return np.array([d.date.toordinal() for d in dates.items], dtype=np.int64)


def ex_days_and_amounts(dividends, who):
    """The ex-dates (as day numbers) and the amounts of a table of dividends,
    with ex-date and amount columns, as arrays."""
    columns = table_columns(dividends, who)
    ex_days = day_numbers_of(find_column(columns, "ex-date", who), who, "the dividends' ex-dates")
    amounts = floats_of(find_column(columns, "amount", who), who)
    if not np.all(amounts >= 0):
        raise LispError("%s: every dividend amount must be a number, 0 or more" % who)
    return ex_days, amounts


def dividends_by_day(dividends, day_numbers, who):
    """What each of the prices' days pays in dividends, as an array. A
    dividend counts on its ex-date, or if there's no price that day, the
    next day there is one. One before the first price or after the last
    isn't counted: there's no return for it to be part of."""
    ex_days, amounts = ex_days_and_amounts(dividends, who)
    paid = np.zeros(len(day_numbers))
    first_days_on_or_after = np.searchsorted(day_numbers, ex_days, side="left")
    for day, amount in zip(first_days_on_or_after, amounts):
        if day < len(paid):
            paid[day] += amount
    return paid


def return_columns(returns, who):
    """A table of returns' columns of returns, as (name, array of numbers):
    every column of numbers but its date. One investment's table, as
    daily-returns makes it, has one, log-return; combine-returns' has one
    for each investment."""
    columns = [(name, floats_of(vector, who)) for name, vector in table_columns(returns, who)
               if name != "date" and (np.issubdtype(vector.items.dtype, np.number) or len(vector.items) == 0)]
    if not columns:
        raise LispError("%s: the table has no column of returns (log-return, as daily-returns makes)" % who)
    if len(columns[0][1]) == 0:
        raise LispError("%s: there are no returns" % who)
    for name, values in columns:
        if not np.all(np.isfinite(values)):
            raise LispError("%s: every return must be a number, not missing or infinite (%s has one that isn't)"
                            % (who, name))
    return columns


def one_investment_returns(returns, who, several="bootstrap-paths makes paths of several"):
    """The name and the returns of the one column of returns of one
    investment's table of returns. `several` says what to do instead, if
    the table has more than one."""
    columns = return_columns(returns, who)
    if len(columns) > 1:
        raise LispError("%s: the table has the returns of %d investments (%s) -- %s"
                        % (who, len(columns), ", ".join(name for name, _ in columns), several))
    return columns[0]


def adjusted_column(log_returns, annual_return, volatility_scale, days_per_year):
    """One column of log returns with the average taken out, the spread
    about it multiplied by volatility_scale, and then a number added that
    makes the daily returns average (1 + annual_return) ^ (1 / days_per_year) - 1."""
    centered = (log_returns - log_returns.mean()) * volatility_scale
    daily_growth = (1 + annual_return) ** (1 / days_per_year)       # 1.0003 for 8%
    return centered + math.log(daily_growth / np.exp(centered).mean())


def adjust_returns(returns, annual_return, *options):
    """(adjust-returns returns annual-return [:days-per-year n]
    [:volatility-scale x]) -- the table of returns with its returns changed:
    the average taken out, the returns' spread about it multiplied by x (1
    unless given: no change), then a number added so that the daily returns
    average (1 + annual-return) ^ (1 / days-per-year) - 1. annual-return is
    the expected annual return, 0.08 for 8%; for a table of several
    investments' returns (combine-returns makes one), one for all of them,
    or a list of (name . annual-return), one for each. :days-per-year is 252
    unless said otherwise; :volatility-scale 1.2 makes the volatility 20%
    more than the history's."""
    who = "adjust-returns"
    options = keyword_options(options, ["days-per-year", "volatility-scale"], who)
    days_per_year = options.get("days-per-year", DAYS_PER_YEAR)
    volatility_scale = options.get("volatility-scale", 1)
    if not is_number(days_per_year) or days_per_year <= 0:
        raise LispError("%s: :days-per-year must be a number above 0, not %s" % (who, days_per_year))
    if not is_number(volatility_scale) or volatility_scale <= 0:
        raise LispError("%s: :volatility-scale must be a number above 0, not %s" % (who, volatility_scale))
    columns = return_columns(returns, who)
    annual_returns = named_numbers(annual_return, [name for name, _ in columns], "the annual return", who)
    for name, rate in annual_returns.items():
        if rate <= -1:
            raise LispError("%s: the annual return must be a number above -1, as 0.08 is 8%%, not %s" % (who, rate))
    adjusted = {name: to_vector(adjusted_column(values, annual_returns[name], volatility_scale, days_per_year))
                for name, values in columns}
    return make_table_value([(name, adjusted.get(name, column)) for name, column in table_columns(returns, who)])


def named_numbers(value, names, what, who):
    """A number for each of names, as a dict: from one number, the same for
    all, or a list of (name . number) pairs, one for each."""
    if is_number(value):
        return {name: float(value) for name in names}
    pairs = pairs_to_list(value) if isinstance(value, Pair) else None
    if pairs is None or not all(isinstance(p, Pair) and is_number(p.cdr) for p in pairs):
        raise LispError("%s: %s must be a number, or a list of (name . number) pairs, not %s" % (who, what, value))
    numbers = {str(p.car): float(p.cdr) for p in pairs}
    missing = [name for name in names if name not in numbers]
    if missing:
        raise LispError("%s: %s has none for %s" % (who, what, ", ".join(missing)))
    return numbers


# ---------------------------------------------------------------------------
# The dividends to come
# ---------------------------------------------------------------------------

def last_years_dividends_to_come(dividends, start, last_day):
    """The dividends of the year up to start, as (ex-date, amount), repeated
    each year after it, as far as last_day."""
    one_year_before = months_later(start, -12)
    last_year = [(day, amount) for day, amount in dividends if one_year_before < day <= start]
    coming = []
    years_ahead = 1
    while last_year and months_later(min(day for day, _ in last_year), 12 * years_ahead) <= last_day:
        coming += [(months_later(day, 12 * years_ahead), amount) for day, amount in last_year]
        years_ahead += 1
    return coming


def dividend_schedule(dividends, start_date, days, *options):
    """(dividend-schedule dividends start-date days [:repeat-last-year #t]) --
    the dividends an investment will pay in the `days` trading days of a
    path that starts the day after start-date: a table of ex-date, day (the
    ex-date's number among those trading days, 1 for the first), and
    amount, in order. dividends is a table of ex-date and amount columns, as
    alpha-vantage-dividends makes. The schedule has the dividends in it
    that come after start-date, up to the path's last day -- or, with
    :repeat-last-year, the dividends of the year up to start-date, which
    are supposed to go on every year, on the same dates and in the same
    amounts. An ex-date on a day the market is closed is the next day it's
    open."""
    who = "dividend-schedule"
    options = keyword_options(options, ["repeat-last-year"], who)
    if not isinstance(start_date, LispDate):
        raise LispError("%s: the start date must be a date, not %s" % (who, start_date))
    days = whole_number(days, "days", who, 1)
    ex_days, amounts = ex_days_and_amounts(dividends, who)
    paid = [(datetime.date.fromordinal(int(day)), float(amount)) for day, amount in zip(ex_days, amounts)]
    start = start_date.date
    last_day = lisp_calendar.trading_days_after(start, days)
    if is_true(options.get("repeat-last-year", False)):
        paid = last_years_dividends_to_come(paid, start, last_day)

    rows = []
    for ex_date, amount in sorted(paid):
        ex_date = lisp_calendar.first_trading_day_from(ex_date)
        if start < ex_date <= last_day:
            rows.append((ex_date, lisp_calendar.count_trading_days(start, ex_date), amount))
    return make_table_value([
        ("ex-date", LispVector([LispDate(d.year, d.month, d.day) for d, _, _ in rows])),
        ("day", to_vector(np.array([day for _, day, _ in rows], dtype=np.int64))),
        ("amount", to_vector(np.array([amount for _, _, amount in rows], dtype=np.float64))),
    ])


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def whole_number(value, name, who, at_least):
    if not isinstance(value, int) or isinstance(value, bool) or value < at_least:
        raise LispError("%s: %s must be a whole number, %d or more, not %s" % (who, name, at_least, value))
    return value


def schedule_days_and_amounts(schedule, who):
    """The days and the amounts of a dividend schedule, a table of day and
    amount columns, as a list of (day, amount) in order of day; empty for no
    schedule."""
    if schedule is None:
        return []
    columns = table_columns(schedule, who)
    if "day" not in [name for name, _ in columns] and "ex-date" in [name for name, _ in columns]:
        raise LispError("%s: :dividends is a schedule, a table of day and amount columns, as dividend-schedule "
                        "makes from a table of dividends" % who)
    days = floats_of(find_column(columns, "day", who), who)
    amounts = floats_of(find_column(columns, "amount", who), who)
    if not np.all(days >= 1) or not np.all(days == np.round(days)):
        raise LispError("%s: every day of the dividend schedule must be a whole number, 1 or more" % who)
    if not np.all(amounts >= 0):
        raise LispError("%s: every dividend amount must be a number, 0 or more" % who)
    in_order = np.argsort(days, kind="stable")
    return [(int(days[i]), float(amounts[i])) for i in in_order]


def prices_with_dividends(start_price, growth, schedule):
    """The prices of a path, an array with a price for each of `growth`'s
    days: start_price grown by `growth` (the running total of the log
    returns), less each dividend of the schedule, a list of (day, amount) in
    order, on its day. A dividend takes the price down by its amount, to 0
    at the lowest; and a price of 0 stays there. A dividend after the last
    day is left out."""
    prices = np.empty(len(growth))
    price = start_price             # the price after the last dividend (or at the start),
    growth_then = 0.0               # the growth that was in it,
    first = 0                       # and the first day since
    for day, amount in schedule:
        if day > len(growth):
            break
        last = day - 1
        prices[first:last + 1] = price * np.exp(growth[first:last + 1] - growth_then)
        price = max(prices[last] - amount, 0.0)
        prices[last] = price
        growth_then = growth[last]
        first = last + 1
    prices[first:] = price * np.exp(growth[first:] - growth_then)
    return prices


def bootstrap_path(returns, start_price, days, block_size, *options):
    """(bootstrap-path returns start-price days block-size [:seed n]
    [:dividends schedule] [:volatility model] [:start-volatility x]) -- one
    simulated path of prices, as a vector of `days` prices: the first is
    the day after start-price's. returns is a table with a log-return
    column. Blocks of block-size consecutive returns, each beginning at a
    random day of the history, are put end to end until there are `days`
    of them (the last block is cut short if it has to be), and the prices
    are what start-price becomes with those returns. :dividends is a
    schedule, as dividend-schedule makes, of dividends that take their
    amounts off the price on their days. :volatility is a model, as
    volatility-model makes: the path starts at the volatility the model
    gives the day after the history (or at :start-volatility x, for a
    year, if it's given), and the days' returns are their shocks times
    the path's own volatility (see returns_with_volatility)."""
    who = "bootstrap-path"
    options = keyword_options(options, ["seed", "dividends", "volatility", "start-volatility"], who)
    schedule = schedule_days_and_amounts(options.get("dividends"), who)
    name, log_returns = one_investment_returns(returns, who)
    if not is_number(start_price) or start_price <= 0:
        raise LispError("%s: the start price must be a number above 0, not %s" % (who, start_price))
    rows = days_drawn(len(log_returns), days, block_size, options.get("seed"), who)
    chosen = path_log_returns(name, log_returns, rows, options.get("volatility"), options.get("start-volatility"), who)
    return to_vector(prices_with_dividends(start_price, np.cumsum(chosen), schedule))


def path_log_returns(name, log_returns, rows, model, start_volatility, who):
    """A path's log returns, from the history's days `rows` (as days_drawn
    picks them): the returns of those days; or, with a volatility model,
    the returns returns_with_volatility makes, starting at start_volatility
    (for a year), if it isn't None."""
    if model is None:
        if start_volatility is not None:
            raise LispError("%s: :start-volatility needs :volatility, a model as volatility-model makes" % who)
        return log_returns[rows]
    weights, start_variance = weights_and_start(model, name, log_returns, start_volatility, who)
    return returns_with_volatility(log_returns, weights, rows, start_variance)[0]


def days_drawn(history_days, days, block_size, seed, who):
    """The days of the history a path's days are copied from, as an array of
    row numbers: blocks of block_size days in a row, each starting at a day
    picked at random (with its own generator for a seed, or the shared one),
    end to end until there are `days` of them, and wrapping around the end
    of the history."""
    days = whole_number(days, "days", who, 1)
    block_size = whole_number(block_size, "block-size", who, 1)
    if block_size > history_days:
        raise LispError("%s: block-size %d is more than the %d returns" % (who, block_size, history_days))
    if seed is not None:
        seed = whole_number(seed, ":seed", who, 0)
    generator = random if seed is None else random.Random(seed)
    blocks = math.ceil(days / block_size)
    starts = np.array([generator.randrange(history_days) for _ in range(blocks)])
    # each block's days in a row, from where it starts; % wraps them around the end of the history
    block_days = (starts[:, None] + np.arange(block_size)) % history_days
    return block_days.ravel()[:days]


def bootstrap_days(returns, days, block_size, *options):
    """(bootstrap-days returns days block-size [:seed n] [:volatility model]
    [:start-volatility x]) -- the days of the history a path is made of: a
    table of day (1 for the path's first), the date of the history's day it
    copies (if the table of returns has dates), and that day's returns.
    With the same :seed, bootstrap-path and bootstrap-paths make their
    paths from these days. With :volatility (for one investment's
    returns), three more columns say how the path's returns were made from
    them: shock, the day of the history's; volatility, the path's that day
    (for a year); and path-return, the path's log return."""
    who = "bootstrap-days"
    options = keyword_options(options, ["seed", "volatility", "start-volatility"], who)
    columns = return_columns(returns, who)
    rows = days_drawn(len(columns[0][1]), days, block_size, options.get("seed"), who)
    table = [("day", to_vector(np.arange(1, len(rows) + 1)))]
    names = [name for name, _ in table_columns(returns, who)]
    if "date" in names:
        table.append(("date", LispVector(find_column(table_columns(returns, who), "date", who).items[rows])))
    table += [(name, to_vector(values[rows])) for name, values in columns]

    model = options.get("volatility")
    if model is None:
        if options.get("start-volatility") is not None:
            raise LispError("%s: :start-volatility needs :volatility, a model as volatility-model makes" % who)
        return make_table_value(table)
    name, log_returns = one_investment_returns(returns, who, "pick one with table-select")
    weights, start_variance = weights_and_start(model, name, log_returns, options.get("start-volatility"), who)
    path_returns, volatilities = returns_with_volatility(log_returns, weights, rows, start_variance)
    shocks = filtered_history(log_returns.tobytes(), weights).shocks[rows]
    days_per_year = model_days_per_year(model, who)
    return make_table_value(table + [("shock", to_vector(shocks)),
                                     ("volatility", to_vector(volatilities * math.sqrt(days_per_year))),
                                     ("path-return", to_vector(path_returns))])


# ---------------------------------------------------------------------------
# Volatility that changes from day to day
# ---------------------------------------------------------------------------

# The model's three weights, as numbers (or as arrays, for several sets of
# them at once): see next_variance.
VolatilityWeights = namedtuple("VolatilityWeights", ["up_day_weight", "down_day_weight", "variance_weight"])
WEIGHT_COLUMNS = ("up-day-weight", "down-day-weight", "variance-weight")    # their columns in a model's table

MINIMUM_HISTORY = 100           # returns, to fit a model to
MOST_PERSISTENCE = 0.998        # a half-life of 346 days; any more, and the volatility hardly goes back at all
# The weights volatility-model tries: each from the first number to the second,
# by the first of SEARCH_STEPS; then by each finer step, near the best so far.
SEARCH_RANGES = {"up_day_weight": (0.0, 0.3), "down_day_weight": (0.0, 0.5), "variance_weight": (0.5, 0.99)}
SEARCH_STEPS = (0.02, 0.005, 0.001)
EXP_TERMS = 16                  # terms of the series for e^x (average_exp_series)


def next_variance(variance, move, weights, constant):
    """The model: the variance (the volatility squared, for a day) of the
    day after a day with variance `variance` on which the investment moved
    `move` (its return less the average return):

        constant + up-day-weight (or down-day-weight, if move < 0) x move^2
                 + variance-weight x variance

    So a big move makes the next day's volatility higher -- a down move by
    more than an up move, if down-day-weight is the bigger. The constant
    pulls the variance back toward the long-run variance (constant_for):
    on average, the variance's difference from it shrinks each day to
    `persistence` of what it was (persistence_of)."""
    reaction = weights.down_day_weight if move < 0 else weights.up_day_weight
    return constant + reaction * move * move + weights.variance_weight * variance


def persistence_of(weights, down_share):
    """How much of the variance's difference from the long-run variance is
    left the next day, on average: variance-weight, plus the up-day and
    down-day weights, each for its share of the moves. down_share is the
    share of the moves' squares, added up, that is on down days: of the
    shocks' (filtered_history), for a path, or, while the weights are being
    fitted and there are no shocks yet, of the history's moves'."""
    return (weights.variance_weight + weights.up_day_weight * (1 - down_share)
            + weights.down_day_weight * down_share)


def constant_for(weights, long_run, down_share):
    """The model's constant: the one that makes the variance go back toward
    long_run, the long-run variance (a day's)."""
    return long_run * (1 - persistence_of(weights, down_share))


def half_life(persistence):
    """How many days it takes for half of a difference from the long-run
    variance to go, on average."""
    return math.log(0.5) / math.log(persistence) if persistence > 0 else 0.0


def moves_of(log_returns, who):
    """A history's moves (its returns less their average), its long-run
    variance (the moves squared, averaged), and the share of that variance
    that is on down days."""
    if len(log_returns) < MINIMUM_HISTORY:
        raise LispError("%s: it takes at least %d returns to fit a volatility model, not %d"
                        % (who, MINIMUM_HISTORY, len(log_returns)))
    moves = log_returns - log_returns.mean()
    long_run = float(np.mean(moves ** 2))
    if long_run == 0:
        raise LispError("%s: the returns are all the same, so there is no volatility to model" % who)
    down_share = float(np.sum(moves[moves < 0] ** 2) / np.sum(moves ** 2))
    return moves, long_run, down_share


def log_likelihoods(moves, long_run, down_share, weights):
    """How well the model fits the history with each of several sets of
    weights (weights' elements are arrays, an element for each set): the log
    of how likely the history's moves are, if each day's comes from a
    normal distribution with the variance the model gives that day. A move
    that is big for its day's variance counts against a set of weights,
    and so does a variance that is big for its day's move. The higher, the
    better the fit. down_share is the moves'. Returns those, and for each
    set, the share of its shocks' squares that is on down days (as
    filtered_history finds it)."""
    constant = constant_for(weights, long_run, down_share)
    variance = np.full(len(weights.variance_weight), long_run)       # the first day's
    total = np.zeros(len(weights.variance_weight))
    shocks_squared = np.zeros(len(weights.variance_weight))         # added up
    down_shocks_squared = np.zeros(len(weights.variance_weight))    # those on down days
    for move in moves:
        total -= 0.5 * (math.log(2 * math.pi) + np.log(variance) + move * move / variance)
        shocks_squared += move * move / variance
        if move < 0:
            down_shocks_squared += move * move / variance
        variance = next_variance(variance, move, weights, constant)
    return total, down_shocks_squared / shocks_squared


def fitted_weights(moves, long_run, down_share, symmetric):
    """The weights that fit the history best (log_likelihoods), and how well:
    found by trying every set of weights on a grid that covers
    SEARCH_RANGES, and then on finer and finer grids, around the best so
    far (as far as the last grid's step on each side). A set whose
    persistence is more than MOST_PERSISTENCE, with the moves' down share
    (down_share) or with its shocks', isn't taken. symmetric: the up-day
    and down-day weights are the same."""
    names = ["up_day_weight", "variance_weight"] if symmetric else list(VolatilityWeights._fields)
    best = None
    for number, step in enumerate(SEARCH_STEPS):
        axes = []
        for name in names:
            low, high = SEARCH_RANGES[name]
            if best is not None:
                last_step = SEARCH_STEPS[number - 1]
                low, high = max(low, getattr(best, name) - last_step), min(high, getattr(best, name) + last_step)
            axes.append(np.round(np.arange(low, high + step / 2, step), 3))
        grid = [axis.ravel() for axis in np.meshgrid(*axes, indexing="ij")]      # every set of them
        tried = VolatilityWeights(grid[0], grid[0], grid[1]) if symmetric else VolatilityWeights(*grid)
        allowed = persistence_of(tried, down_share) <= MOST_PERSISTENCE
        tried = VolatilityWeights(*(weight[allowed] for weight in tried))
        scores, shocks_down_share = log_likelihoods(moves, long_run, down_share, tried)
        scores[persistence_of(tried, shocks_down_share) > MOST_PERSISTENCE] = -np.inf
        i = int(np.argmax(scores))
        best = VolatilityWeights(*(float(weight[i]) for weight in tried))
        best_score = float(scores[i])
    return best, best_score


def average_exp_series(shocks):
    """The coefficients of a polynomial in v whose value is the average,
    over the shocks z, of e^(v z). Since e^x = 1 + x + x^2/2! + x^3/3! + ...,
    that average is 1 + v avg(z) + v^2 avg(z^2)/2! + v^3 avg(z^3)/3! + ...
    -- here to EXP_TERMS terms, so that it is off by less than a millionth
    even if a day's volatility (v) times a shock were 2. Highest power
    first, as np.polyval takes them."""
    return np.array([np.mean(shocks ** k) / math.factorial(k) for k in reversed(range(EXP_TERMS))])


# What the model makes of a history: see filtered_history.
FilteredHistory = namedtuple("FilteredHistory", ["variances", "shocks", "next_variance", "down_share", "persistence",
                                                 "constant", "log_growth", "exp_series"])


@lru_cache(maxsize=32)
def filtered_history(returns_bytes, weights):
    """What the model, with these weights, makes of a history of log returns
    (given as the bytes of a float64 array, so that the answer can be kept:
    every path made from the same history and weights needs the same):
      variances      each day's variance, as the model estimates it the day
                     before (the first day's is the long-run variance)
      shocks         each day's move divided by its volatility
      next_variance  the variance of the day after the history's last
      down_share     the share of the shocks' squares, added up, on down days
      persistence    the paths' (persistence_of, with that down_share)
      constant       the paths' (constant_for, with that down_share)
      log_growth     the log of the daily growth the returns have: of the
                     average of e^return, which adjust-returns sets
      exp_series     the series for the average of e^(v x shock) (average_exp_series)
    The variances are found with the constant the weights were fitted with
    (with the moves' down share); then all of them, and next_variance, are
    multiplied by the one number that makes the shocks' squares average
    exactly 1, as a volatility's shocks should (they come out within a few
    percent of it). Then a path's variance is the size of its moves
    squared, on average, and the paths' constant makes it go back toward
    the history's long-run variance. The history must be one moves_of
    takes, and the weights' persistence with either down share less than 1."""
    log_returns = np.frombuffer(returns_bytes, dtype=np.float64)
    moves, long_run, moves_down_share = moves_of(log_returns, "filtered_history")
    fitted_constant = constant_for(weights, long_run, moves_down_share)
    variances = np.empty(len(moves))
    variance = long_run
    for day, move in enumerate(moves):
        variances[day] = variance
        variance = next_variance(variance, move, weights, fitted_constant)
    size = np.mean(moves ** 2 / variances)          # the shocks' squares' average, before
    variances, variance = variances * size, variance * size
    shocks = moves / np.sqrt(variances)
    down_share = float(np.sum(shocks[shocks < 0] ** 2) / np.sum(shocks ** 2))
    return FilteredHistory(variances, shocks, variance, down_share, persistence_of(weights, down_share),
                           constant_for(weights, long_run, down_share), math.log(np.mean(np.exp(log_returns))),
                           average_exp_series(shocks))


def returns_with_volatility(log_returns, weights, rows, start_variance=None):
    """A path's log returns, made from the history's days `rows` (as
    days_drawn picks them) with the model's volatility: each day's is its
    day of the history's shock times the path's volatility that day, plus
    the drift. The path's variance starts at start_variance (a day's), or,
    if that's None, the history's next_variance; after each day, it is
    updated (next_variance) with the move the path just made. The drift
    makes e^return average out, over all the history's shocks, at the
    daily growth the history's returns have (which adjust-returns sets): it
    is the log of that growth, less the log of the average of
    e^(volatility x shock). Returns the path's log returns and its
    volatility each day (a day's), as arrays."""
    history = filtered_history(log_returns.tobytes(), weights)
    variance = history.next_variance if start_variance is None else start_variance
    volatilities = np.empty(len(rows))
    moves = np.empty(len(rows))
    for day, row in enumerate(rows):
        volatilities[day] = math.sqrt(variance)
        moves[day] = volatilities[day] * history.shocks[row]
        variance = next_variance(variance, moves[day], weights, history.constant)
    drift = history.log_growth - np.log(np.polyval(history.exp_series, volatilities))
    return moves + drift, volatilities


def model_row(model, name, who):
    """The number of the row of a volatility model (a table, as
    volatility-model makes) that is for the investment `name`."""
    investments = [str(x) for x in find_column(table_columns(model, who), "investment", who).items]
    if name not in investments:
        raise LispError("%s: the volatility model has no row for %s (it has %s) -- make it from the same returns"
                        % (who, name, ", ".join(investments) or "none"))
    return investments.index(name)


def model_days_per_year(model, who):
    days_per_year = floats_of(find_column(table_columns(model, who), "days-per-year", who), who)
    if len(days_per_year) == 0 or not days_per_year[0] > 0:
        raise LispError("%s: the volatility model's days-per-year must be a number above 0" % who)
    return float(days_per_year[0])


def weights_and_start(model, name, log_returns, start_volatility, who):
    """The weights of a volatility model for the investment `name`, whose
    returns are log_returns, and the variance (a day's) a path starts at:
    start_volatility's (for a year), or, if that's None, None, for the
    history's next_variance."""
    columns = table_columns(model, who)
    row = model_row(model, name, who)
    weights = VolatilityWeights(*(float(floats_of(find_column(columns, column, who), who)[row])
                                  for column in WEIGHT_COLUMNS))
    if not all(weight >= 0 for weight in weights):
        raise LispError("%s: the volatility model's weights must all be 0 or more" % who)
    _, _, moves_down_share = moves_of(log_returns, who)
    if (persistence_of(weights, moves_down_share) >= 1 or
            filtered_history(log_returns.tobytes(), weights).persistence >= 1):
        raise LispError("%s: the volatility model's weights add up to too much: its persistence must be less than "
                        "1, or the volatility would never go back" % who)
    if start_volatility is None:
        return weights, None
    if not is_number(start_volatility) or start_volatility <= 0:
        raise LispError("%s: :start-volatility must be a number above 0, 0.2 for 20%%, not %s"
                        % (who, start_volatility))
    return weights, start_volatility ** 2 / model_days_per_year(model, who)


def volatility_model(returns, *options):
    """(volatility-model returns [:symmetric #t] [:days-per-year n]) -- a
    model of each investment's volatility, fitted to its history (the
    returns less their average): a table with a row for each column of
    returns, and these columns:
      investment           the name of the column of returns (log-return,
                           for one investment's returns)
      next-day-volatility  the volatility the model gives the day after the
                           history's last, for a year
      long-run-volatility  the history's volatility, which the model's goes
                           back toward, for a year
      half-life            how many days it takes for half of a difference
                           from the long-run variance to go, on average
      up-day-weight, down-day-weight, variance-weight
                           the model's weights (see next_variance)
      persistence          how much of a difference from the long-run
                           variance is left the next day, on average
      down-share           the share of the shocks' squares on down days
      log-likelihood       how well the weights fit (the higher the better:
                           for comparing models of the same returns)
      days-per-year        what the volatilities are for a year of (252,
                           unless :days-per-year says)
    The weights are those that fit the history best (fitted_weights).
    :symmetric #t makes the up-day and down-day weights the same."""
    who = "volatility-model"
    options = keyword_options(options, ["symmetric", "days-per-year"], who)
    days_per_year = options.get("days-per-year", DAYS_PER_YEAR)
    if not is_number(days_per_year) or days_per_year <= 0:
        raise LispError("%s: :days-per-year must be a number above 0, not %s" % (who, days_per_year))
    symmetric = is_true(options.get("symmetric", False))
    rows = []
    for name, log_returns in return_columns(returns, who):
        moves, long_run, moves_down_share = moves_of(log_returns, who)
        weights, score = fitted_weights(moves, long_run, moves_down_share, symmetric)
        history = filtered_history(log_returns.tobytes(), weights)
        rows.append((name, math.sqrt(history.next_variance * days_per_year), math.sqrt(long_run * days_per_year),
                     half_life(history.persistence)) + tuple(weights) +
                    (history.persistence, history.down_share, score, days_per_year))
    names = ["investment", "next-day-volatility", "long-run-volatility", "half-life", *WEIGHT_COLUMNS,
             "persistence", "down-share", "log-likelihood", "days-per-year"]
    return make_table_value([(names[0], LispVector([LispString(row[0]) for row in rows]))] +
                            [(column, to_vector(np.array([row[i] for row in rows], dtype=np.float64)))
                             for i, column in enumerate(names) if i > 0])


def volatility_history(returns, model):
    """(volatility-history returns model) -- what a volatility model says
    about each day of an investment's history: a table of date (if the
    returns have dates), the returns, volatility (the model's estimate of
    the day's, made the day before, for a year), and shock (the day's
    return less the average, divided by the day's volatility)."""
    who = "volatility-history"
    name, log_returns = one_investment_returns(returns, who, "pick one with table-select")
    weights, _ = weights_and_start(model, name, log_returns, None, who)
    history = filtered_history(log_returns.tobytes(), weights)
    days_per_year = model_days_per_year(model, who)
    table = []
    if "date" in [column for column, _ in table_columns(returns, who)]:
        table.append(("date", find_column(table_columns(returns, who), "date", who)))
    return make_table_value(table + [(name, to_vector(log_returns)),
                                     ("volatility", to_vector(np.sqrt(history.variances * days_per_year))),
                                     ("shock", to_vector(history.shocks))])


def volatility_forecast(model, days, *options):
    """(volatility-forecast model days [:start-volatility x]) -- the
    volatility a model expects over the next `days` days, on average, for a
    year: a number, or for a vector of days, a vector. model is one
    investment's, a table of one row, as volatility-model makes. The first
    day's volatility is the model's next-day-volatility, or x, if it's
    given; after that, the variance's difference from the long-run
    variance shrinks to `persistence` of itself each day, on average, so the
    variance of day k is long-run + persistence^(k-1) x (first day's -
    long-run), and the average of the first n days' is
    long-run + (first day's - long-run) x (1 - persistence^n) / (n x (1 - persistence))."""
    who = "volatility-forecast"
    options = keyword_options(options, ["start-volatility"], who)
    columns = table_columns(model, who)

    def number(column):
        values = floats_of(find_column(columns, column, who), who)
        if len(values) != 1:
            raise LispError("%s: the model must be one investment's, a table of one row (pick one with table-where), "
                            "not %d rows" % (who, len(values)))
        return float(values[0])

    long_run = number("long-run-volatility") ** 2
    first_day = options.get("start-volatility", number("next-day-volatility"))
    if not is_number(first_day) or first_day <= 0:
        raise LispError("%s: :start-volatility must be a number above 0, 0.2 for 20%%, not %s" % (who, first_day))
    persistence = number("persistence")
    if not 0 <= persistence < 1:
        raise LispError("%s: the model's persistence must be at least 0 and less than 1, not %s" % (who, persistence))
    n = floats_of(days, who) if isinstance(days, LispVector) else np.array([days], dtype=np.float64)
    if not np.all((n >= 1) & (n == np.round(n))):
        raise LispError("%s: days must be whole numbers, 1 or more" % who)
    average = long_run + (first_day ** 2 - long_run) * (1 - persistence ** n) / (n * (1 - persistence))
    return to_vector(np.sqrt(average)) if isinstance(days, LispVector) else float(np.sqrt(average[0]))


# ---------------------------------------------------------------------------
# Option values
# ---------------------------------------------------------------------------

def option_value(paths, payoff, rate, years):
    """(option-value paths payoff rate years) -- what an option is worth, from
    simulated paths of the price: a list of two numbers, the value and its
    standard error (how far chance may have put it from the true value
    that these paths are a sample of). paths is a list of paths, vectors of
    prices, such as bootstrap-path makes. payoff is a procedure of one
    argument, a path, that returns what the option pays at the end of it
    (for a call, the final price less the strike, or 0 if that's less). The
    value is the payoffs' present values averaged: each is discounted for
    `years` at the interest rate `rate`, continuously compounded."""
    who = "option-value"
    if not isinstance(paths, Pair) or not all(isinstance(p, LispVector) for p in pairs_to_list(paths)):
        raise LispError("%s: paths must be a list of vectors of prices, such as a list of bootstrap-path's" % who)
    paths = pairs_to_list(paths)
    if len(paths) < 2:
        raise LispError("%s: it takes at least two paths to estimate a value and its error" % who)
    if not is_number(rate):
        raise LispError("%s: the interest rate must be a number, 0.04 for 4%%, not %s" % (who, rate))
    if not is_number(years) or years <= 0:
        raise LispError("%s: years must be a number above 0, not %s" % (who, years))

    payoffs = []
    for path in paths:
        paid = _lisp_scalar(apply_proc(payoff, [path]))
        if not is_number(paid) or not math.isfinite(paid):
            raise LispError("%s: the payoff procedure must return a number, not %s" % (who, paid))
        payoffs.append(paid)
    present_values = math.exp(-rate * years) * np.array(payoffs, dtype=np.float64)
    standard_error = present_values.std(ddof=1) / math.sqrt(len(present_values))
    return list_to_pairs([float(present_values.mean()), float(standard_error)])


def option_payoffs(paths, days, strikes, calls):
    """(option-payoffs paths days strikes calls) -- what many European
    options pay, on average, over a list of paths: a table with a row for
    each option and the columns payoff (the average of what it pays at
    expiration, before discounting), payoff-error (its standard error), and
    paths-paid (how many paths it pays something on). paths is a list of
    paths, vectors of prices of the same length, such as bootstrap-path makes.
    Each option has a day, the number of the path's day it expires on (1 for
    the first), a strike, and a call, 1 for a call or 0 for a put: all three
    are vectors with an element for each option. A call pays the price less
    the strike, if more than 0, and a put the strike less the price."""
    who = "option-payoffs"
    if not isinstance(paths, Pair) or not all(isinstance(p, LispVector) for p in pairs_to_list(paths)):
        raise LispError("%s: paths must be a list of vectors of prices, such as a list of bootstrap-path's" % who)
    path_list = pairs_to_list(paths)
    if len(path_list) < 2:
        raise LispError("%s: it takes at least two paths to estimate a value and its error" % who)
    if len({len(p.items) for p in path_list}) > 1:
        raise LispError("%s: the paths must all be the same length" % who)
    prices = np.array([p.items for p in path_list], dtype=np.float64)       # a row for each path, a column for each day
    path_count, path_days = prices.shape

    days = floats_of(days, who)
    strikes = floats_of(strikes, who)
    calls = floats_of(calls, who) != 0
    if not len(days) == len(strikes) == len(calls):
        raise LispError("%s: days, strikes, and calls must have an element for each option (%d, %d, %d)"
                        % (who, len(days), len(strikes), len(calls)))
    if not np.all(days == np.round(days)) or not np.all((days >= 1) & (days <= path_days)):
        raise LispError("%s: every day must be a whole number from 1 to the paths' %d days" % (who, path_days))

    average = np.zeros(len(days))
    error = np.zeros(len(days))
    paid = np.zeros(len(days), dtype=np.int64)
    for day in np.unique(days):
        options = np.flatnonzero(days == day)
        final_prices = prices[:, int(day) - 1][:, None]                         # a column: the price on that day
        payoffs = np.where(calls[options], final_prices - strikes[options], strikes[options] - final_prices)
        payoffs = np.maximum(payoffs, 0.0)                                      # a row for each path, a column for each option
        average[options] = payoffs.mean(axis=0)
        error[options] = payoffs.std(axis=0, ddof=1) / math.sqrt(path_count)
        paid[options] = (payoffs > 0).sum(axis=0)
    return make_table_value([("payoff", to_vector(average)), ("payoff-error", to_vector(error)),
                             ("paths-paid", to_vector(paid))])


BUILTINS = {
    "daily-returns": daily_returns,
    "adjust-returns": adjust_returns,
    "dividend-schedule": dividend_schedule,
    "bootstrap-path": bootstrap_path,
    "bootstrap-days": bootstrap_days,
    "volatility-model": volatility_model,
    "volatility-history": volatility_history,
    "volatility-forecast": volatility_forecast,
    "option-value": option_value,
    "option-payoffs": option_payoffs,
}
