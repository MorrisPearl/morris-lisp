"""The New York Stock Exchange's trading calendar for the Lisp interpreter:
which days the market is open, and counting them.

  (trading-day? date)                 #t if the market is open that day
  (next-trading-day date)             the date, or the first trading day after it
  (add-trading-days date n)           the date n trading days later (earlier, if n is negative)
  (trading-days-between start end)    how many trading days after start, up to and including end
  (market-open?)                      #t if the stock market is open now
  (nyse-holidays year)                the weekdays the market is closed in a year

A trading day is a Monday through Friday that isn't a holiday. The NYSE
publishes its holidays for the next few years
(https://www.nyse.com/trade/hours-calendars), but they follow rules, so
they can be worked out for any year:

  - New Year's Day, January 1; Juneteenth, June 19 (a holiday since 2022);
    Independence Day, July 4; and Christmas, December 25. One on a Saturday
    is kept on the Friday before, and one on a Sunday on the Monday after.
    The exception is New Year's Day on a Saturday, which isn't kept at all:
    the market is open the Friday before.
  - Martin Luther King Jr. Day (since 1998), the third Monday of January;
    Washington's Birthday, the third Monday of February; Memorial Day, the
    last Monday of May; Labor Day, the first Monday of September; and
    Thanksgiving, the fourth Thursday of November.
  - Good Friday, the Friday before Easter.

A day the market closes early (the day after Thanksgiving, for one) is a
trading day. Closings that weren't planned -- for a funeral, a storm, or
September 11, 2001 -- aren't known to the rules.
"""

import datetime
from functools import lru_cache

import lisp_clock
from lisp_core import LispError, LispVector, _date_from_pydate, date_argument

MONDAY, THURSDAY = 0, 3
SATURDAY = 5
ONE_DAY = datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# The holidays of a year
# ---------------------------------------------------------------------------

def nth_weekday(year, month, weekday, n):
    """The nth (1 for the first) given weekday of a month, as a date."""
    first = datetime.date(year, month, 1)
    first_one = first + datetime.timedelta(days=(weekday - first.weekday()) % 7)
    return first_one + datetime.timedelta(weeks=n - 1)


def last_weekday(year, month, weekday):
    """The last of a given weekday in a month, as a date."""
    last = nth_weekday(year, month, weekday, 4)
    if (last + datetime.timedelta(weeks=1)).month == month:
        last += datetime.timedelta(weeks=1)
    return last


def easter(year):
    """Easter Sunday of a year, as a date, by the usual calculation for the
    Gregorian calendar (Meeus, Jones, and Butcher's)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day_less_one = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day_less_one + 1)


def observed(day):
    """The day a holiday on a fixed date is kept: a Saturday's holiday on the
    Friday before, and a Sunday's on the Monday after."""
    if day.weekday() == SATURDAY:
        return day - ONE_DAY
    if day.weekday() == SATURDAY + 1:
        return day + ONE_DAY
    return day


@lru_cache(maxsize=None)
def holidays(year):
    """The days the market is closed in a year, in order, as a tuple of dates."""
    days = []
    new_years_day = datetime.date(year, 1, 1)
    if new_years_day.weekday() != SATURDAY:                 # (then it isn't kept at all)
        days.append(observed(new_years_day))
    if year >= 1998:
        days.append(nth_weekday(year, 1, MONDAY, 3))        # Martin Luther King Jr. Day
    days.append(nth_weekday(year, 2, MONDAY, 3))            # Washington's Birthday
    days.append(easter(year) - 2 * ONE_DAY)                 # Good Friday
    days.append(last_weekday(year, 5, MONDAY))              # Memorial Day
    if year >= 2022:
        days.append(observed(datetime.date(year, 6, 19)))   # Juneteenth
    days.append(observed(datetime.date(year, 7, 4)))        # Independence Day
    days.append(nth_weekday(year, 9, MONDAY, 1))            # Labor Day
    days.append(nth_weekday(year, 11, THURSDAY, 4))         # Thanksgiving
    days.append(observed(datetime.date(year, 12, 25)))      # Christmas
    return tuple(sorted(days))


# ---------------------------------------------------------------------------
# Trading days
# ---------------------------------------------------------------------------

def is_trading_day(day):
    return day.weekday() < SATURDAY and day not in holidays(day.year)


def first_trading_day_from(day):
    """day, or the first trading day after it."""
    while not is_trading_day(day):
        day += ONE_DAY
    return day


def trading_days_after(day, n):
    """The trading day n trading days after day (before, if n is negative)."""
    step = ONE_DAY if n >= 0 else -ONE_DAY
    for _ in range(abs(n)):
        day += step
        while not is_trading_day(day):
            day += step
    return day


def count_trading_days(start, end):
    """How many trading days there are after start, up to and including end
    (the opposite of that number if end is before start)."""
    if end < start:
        return -count_trading_days(end, start)
    count = 0
    day = start
    while day < end:
        day += ONE_DAY
        if is_trading_day(day):
            count += 1
    return count


# ---------------------------------------------------------------------------
# The Lisp functions
# ---------------------------------------------------------------------------

def trading_day_p(d):
    """(trading-day? date) -- #t if the market is open that day: a Monday
    through Friday that isn't a holiday."""
    return is_trading_day(date_argument(d, "trading-day?", "the date"))


def next_trading_day(d):
    """(next-trading-day date) -- the date, if the market is open that day,
    and if not the first day after it that it's open."""
    return _date_from_pydate(first_trading_day_from(date_argument(d, "next-trading-day", "the date")))


def add_trading_days(d, n):
    """(add-trading-days date n) -- the date n trading days after date, or
    before it if n is negative. With n of 0 it is the date itself, whether
    or not that's a trading day."""
    who = "add-trading-days"
    day = date_argument(d, who, "the date")
    if not isinstance(n, int) or isinstance(n, bool):
        raise LispError("%s: the number of days must be a whole number, not %r" % (who, n))
    return _date_from_pydate(trading_days_after(day, n))


def _dates_of(value, who, what):
    """A date, or a vector of them, as a list of Python dates."""
    if isinstance(value, LispVector):
        return [date_argument(d, who, what) for d in value.items]
    return [date_argument(value, who, what)]


def trading_days_between(start, end):
    """(trading-days-between start end) -- how many trading days there are
    after start, up to and including end: 1 from a Friday to the Monday
    after it, if that is a trading day. Negative if end is before start.
    Either can be a vector of dates -- an option chain's expirations, say --
    and the answer is then a vector, with the other date used for each."""
    who = "trading-days-between"
    if not isinstance(start, LispVector) and not isinstance(end, LispVector):
        return count_trading_days(date_argument(start, who, "the start"), date_argument(end, who, "the end"))
    starts, ends = _dates_of(start, who, "the start"), _dates_of(end, who, "the end")
    if isinstance(start, LispVector) and isinstance(end, LispVector):
        if len(starts) != len(ends):
            raise LispError("%s: the vectors of dates are %d and %d long: they must be as long as each other"
                            % (who, len(starts), len(ends)))
    elif isinstance(start, LispVector):
        ends = ends * len(starts)
    else:
        starts = starts * len(ends)
    counted = {}                                     # (each pair of dates is counted once, however often it comes)
    for pair in zip(starts, ends):
        if pair not in counted:
            counted[pair] = count_trading_days(*pair)
    return LispVector([counted[pair] for pair in zip(starts, ends)])


def market_open_p():
    """(market-open?) -- #t if the stock market is open now: from 9:30 am to
    4:00 pm on a trading day. The computer's clock is taken to be on New
    York time."""
    moment = lisp_clock.now()
    minutes = moment.hour * 60 + moment.minute
    return is_trading_day(moment.date()) and 9 * 60 + 30 <= minutes < 16 * 60


def nyse_holidays(year):
    """(nyse-holidays year) -- a vector of the dates in a year when the
    market is closed on a weekday, in order, as the rules (see this file's
    comment) give them: the NYSE's published holidays for 2026 through 2028
    are what they give."""
    if not isinstance(year, int) or isinstance(year, bool) or not 1 <= year <= 9999:
        raise LispError("nyse-holidays: the year must be a whole number, such as 2026, not %r" % (year,))
    return LispVector([_date_from_pydate(day) for day in holidays(year)])


BUILTINS = {
    "trading-day?": trading_day_p,
    "next-trading-day": next_trading_day,
    "add-trading-days": add_trading_days,
    "trading-days-between": trading_days_between,
    "market-open?": market_open_p,
    "nyse-holidays": nyse_holidays,
}
