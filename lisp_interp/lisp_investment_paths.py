"""Simulated investment prices for the Lisp interpreter: a block bootstrap of an
investment's own daily returns.

  (daily-returns prices [:dividends table])
                     an investment's daily returns, from its prices (and dividends)
  (adjust-returns returns annual-return [:days-per-year n])
                     the returns, with their average changed to give an
                     expected annual return
  (bootstrap-path returns start-price days block-size [:seed n])
                     one simulated path of future prices

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

THE PATHS wrap: a block that runs off the end of the history carries on
from its start, so every day is as likely as any other to be in a block.

RANDOM NUMBERS: with :seed, bootstrap-path uses its own generator (as
vectors-shuffle does), so the same seed gives the same path every time --
pass a different seed for each path, or all the paths are the same. Without
:seed it uses the shared generator that random-float and random-int use,
which (random-seed n) makes reproducible.
"""

import math
import random

import numpy as np

from lisp_core import LispDate, LispError, LispVector, keyword_options
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


def dividends_by_day(dividends, day_numbers, who):
    """What each of the prices' days pays in dividends, as an array. A
    dividend counts on its ex-date, or if there's no price that day, the
    next day there is one. One before the first price or after the last
    isn't counted: there's no return for it to be part of."""
    columns = table_columns(dividends, who)
    ex_days = day_numbers_of(find_column(columns, "ex-date", who), who, "the dividends' ex-dates")
    amounts = floats_of(find_column(columns, "amount", who), who)
    if not np.all(amounts >= 0):
        raise LispError("%s: every dividend amount must be a number, 0 or more" % who)
    paid = np.zeros(len(day_numbers))
    first_days_on_or_after = np.searchsorted(day_numbers, ex_days, side="left")
    for day, amount in zip(first_days_on_or_after, amounts):
        if day < len(paid):
            paid[day] += amount
    return paid


def log_returns_of(returns, who):
    """The log-return column of a table of returns, as an array of numbers."""
    values = floats_of(find_column(table_columns(returns, who), RETURN_COLUMN, who), who)
    if len(values) == 0:
        raise LispError("%s: there are no returns" % who)
    if not np.all(np.isfinite(values)):
        raise LispError("%s: every return must be a number, not missing or infinite" % who)
    return values


def adjust_returns(returns, annual_return, *options):
    """(adjust-returns returns annual-return [:days-per-year n]) -- the table
    of returns with its log-return column changed: the average taken out,
    then a number added so that the daily returns average (1 + annual-return)
    ^ (1 / days-per-year) - 1. annual-return is the expected annual return,
    0.08 for 8%; :days-per-year is 252 unless said otherwise."""
    who = "adjust-returns"
    options = keyword_options(options, ["days-per-year"], who)
    days_per_year = options.get("days-per-year", DAYS_PER_YEAR)
    if not is_number(annual_return) or annual_return <= -1:
        raise LispError("%s: the annual return must be a number above -1, as 0.08 is 8%%, not %s"
                        % (who, annual_return))
    if not is_number(days_per_year) or days_per_year <= 0:
        raise LispError("%s: :days-per-year must be a number above 0, not %s" % (who, days_per_year))

    log_returns = log_returns_of(returns, who)
    centered = log_returns - log_returns.mean()
    daily_growth = (1 + annual_return) ** (1 / days_per_year)       # 1.0003 for 8%
    shift = math.log(daily_growth / np.exp(centered).mean())
    adjusted = to_vector(centered + shift)
    return make_table_value([(name, adjusted if name == RETURN_COLUMN else column)
                             for name, column in table_columns(returns, who)])


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def whole_number(value, name, who, at_least):
    if not isinstance(value, int) or isinstance(value, bool) or value < at_least:
        raise LispError("%s: %s must be a whole number, %d or more, not %s" % (who, name, at_least, value))
    return value


def bootstrap_path(returns, start_price, days, block_size, *options):
    """(bootstrap-path returns start-price days block-size [:seed n]) -- one
    simulated path of prices, as a vector of `days` prices: the first is the
    day after start-price's. returns is a table with a log-return column.
    Blocks of block-size consecutive returns, each beginning at a random day
    of the history, are put end to end until there are `days` of them (the
    last block is cut short if it has to be), and the prices are what
    start-price becomes with those returns."""
    who = "bootstrap-path"
    options = keyword_options(options, ["seed"], who)
    seed = options.get("seed")
    log_returns = log_returns_of(returns, who)
    if not is_number(start_price) or start_price <= 0:
        raise LispError("%s: the start price must be a number above 0, not %s" % (who, start_price))
    days = whole_number(days, "days", who, 1)
    block_size = whole_number(block_size, "block-size", who, 1)
    if block_size > len(log_returns):
        raise LispError("%s: block-size %d is more than the %d returns" % (who, block_size, len(log_returns)))
    if seed is not None:
        seed = whole_number(seed, ":seed", who, 0)

    generator = random if seed is None else random.Random(seed)
    blocks = math.ceil(days / block_size)
    starts = np.array([generator.randrange(len(log_returns)) for _ in range(blocks)])
    # each block's days in a row, from where it starts; % wraps them around the end of the history
    block_days = (starts[:, None] + np.arange(block_size)) % len(log_returns)
    chosen = log_returns[block_days.ravel()[:days]]
    return to_vector(start_price * np.exp(np.cumsum(chosen)))


BUILTINS = {
    "daily-returns": daily_returns,
    "adjust-returns": adjust_returns,
    "bootstrap-path": bootstrap_path,
}
