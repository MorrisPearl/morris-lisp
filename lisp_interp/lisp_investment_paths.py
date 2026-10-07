"""Simulated investment prices for the Lisp interpreter: a block bootstrap of an
investment's own daily returns.

  (daily-returns prices [:dividends table])
                     an investment's daily returns, from its prices (and dividends)
  (adjust-returns returns annual-return [:days-per-year n] [:volatility-scale x])
                     the returns, with their average changed to give an
                     expected annual return (and their volatility, if asked)
  (dividend-schedule dividends start-date days [:repeat-last-year #t])
                     the dividends an investment will pay in the days of a path
  (bootstrap-path returns start-price days block-size [:seed n] [:dividends schedule])
                     one simulated path of future prices
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

import numpy as np

from lisp_core import (
    LispDate, LispError, LispVector, Pair, _lisp_scalar, apply_proc, is_true, keyword_options, list_to_pairs,
    pairs_to_list,
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


def log_returns_of(returns, who):
    """The one column of returns of one investment's table of returns."""
    columns = return_columns(returns, who)
    if len(columns) > 1:
        raise LispError("%s: the table has the returns of %d investments (%s) -- bootstrap-paths makes paths of "
                        "several" % (who, len(columns), ", ".join(name for name, _ in columns)))
    return columns[0][1]


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
    [:dividends schedule]) -- one simulated path of prices, as a vector of
    `days` prices: the first is the day after start-price's. returns is a
    table with a log-return column. Blocks of block-size consecutive
    returns, each beginning at a random day of the history, are put end to
    end until there are `days` of them (the last block is cut short if it
    has to be), and the prices are what start-price becomes with those
    returns. :dividends is a schedule, as dividend-schedule makes, of
    dividends that take their amounts off the price on their days."""
    who = "bootstrap-path"
    options = keyword_options(options, ["seed", "dividends"], who)
    seed = options.get("seed")
    schedule = schedule_days_and_amounts(options.get("dividends"), who)
    log_returns = log_returns_of(returns, who)
    if not is_number(start_price) or start_price <= 0:
        raise LispError("%s: the start price must be a number above 0, not %s" % (who, start_price))
    chosen = log_returns[days_drawn(len(log_returns), days, block_size, seed, who)]
    return to_vector(prices_with_dividends(start_price, np.cumsum(chosen), schedule))


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


def bootstrap_days(returns, days, block_size, *options):
    """(bootstrap-days returns days block-size [:seed n]) -- the days of the
    history a path is made of: a table of day (1 for the path's first), the
    date of the history's day it copies (if the table of returns has dates),
    and that day's returns. With the same :seed, bootstrap-path and
    bootstrap-paths make their paths from these days."""
    who = "bootstrap-days"
    options = keyword_options(options, ["seed"], who)
    columns = return_columns(returns, who)
    rows = days_drawn(len(columns[0][1]), days, block_size, options.get("seed"), who)
    table = [("day", to_vector(np.arange(1, len(rows) + 1)))]
    names = [name for name, _ in table_columns(returns, who)]
    if "date" in names:
        table.append(("date", LispVector(find_column(table_columns(returns, who), "date", who).items[rows])))
    return make_table_value(table + [(name, to_vector(values[rows])) for name, values in columns])


BUILTINS = {
    "daily-returns": daily_returns,
    "adjust-returns": adjust_returns,
    "dividend-schedule": dividend_schedule,
    "bootstrap-path": bootstrap_path,
    "bootstrap-days": bootstrap_days,
    "option-value": option_value,
    "option-payoffs": option_payoffs,
}
