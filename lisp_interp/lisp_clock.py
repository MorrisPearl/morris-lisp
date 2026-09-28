"""The clock for the Lisp interpreter: what time it is, and waiting until a
later time -- e.g. to check something every hour.

A TIME is a list (year month day hour minute second), in local time, as
current-time returns it: (2026 9 28 14 37 5) is 2:37:05 pm on September 28,
2026. Wherever a time is expected, the hour, minute, and second may be left
off (they're then 0), and a date means midnight at its start.
"""

import datetime
import time

from lisp_core import LispDate, LispError, LispString, NIL, Pair, _brief, _date_from_pydate, list_to_pairs, pairs_to_list
from lisp_vector_math import is_number


def now():
    """The time now, as a Python datetime. (A function of its own so the tests
    can pretend it's another time.)"""
    return datetime.datetime.now()


def time_list(moment):
    """A Python datetime as a Lisp time: (year month day hour minute second)."""
    return list_to_pairs([moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second])


def as_datetime(t, who):
    """A Lisp time -- a list (year month day [hour minute second]), or a
    date -- as a Python datetime."""
    if isinstance(t, LispDate):
        return datetime.datetime(t.date.year, t.date.month, t.date.day)
    parts = pairs_to_list(t) if isinstance(t, Pair) else None
    if parts is None or not 3 <= len(parts) <= 6 or \
            not all(isinstance(p, int) and not isinstance(p, bool) for p in parts):
        raise LispError("%s: a time is a list of whole numbers, (year month day [hour minute second]), "
                        "or a date -- not %s" % (who, _brief(t)))
    try:
        return datetime.datetime(*parts)
    except ValueError as e:
        raise LispError("%s: %s isn't a real time (%s)" % (who, _brief(t), e))


def check_seconds(seconds, who):
    if not is_number(seconds):
        raise LispError("%s: the number of seconds must be a number, not %s" % (who, _brief(seconds)))


def current_time():
    """(current-time) -- the time now, as a list (year month day hour minute
    second), in local time."""
    return time_list(now())


def today():
    """(today) -- today's date."""
    return _date_from_pydate(now().date())


def time_add(t, seconds):
    """(time-add time seconds) -- the time `seconds` after `time` (before, if
    it's negative). An hour is (* 60 60) seconds."""
    check_seconds(seconds, "time-add")
    return time_list(as_datetime(t, "time-add") + datetime.timedelta(seconds=seconds))


def seconds_between(t1, t2):
    """(seconds-between time1 time2) -- the number of seconds from time1 to
    time2 (negative if time2 is earlier)."""
    return int((as_datetime(t2, "seconds-between") - as_datetime(t1, "seconds-between")).total_seconds())


def time_to_string(t):
    """(time->string time) -- the time as text, e.g. "2026-09-28 14:37:05"."""
    return LispString(as_datetime(t, "time->string").strftime("%Y-%m-%d %H:%M:%S"))


def next_time(hour, minute=0, second=0):
    """(next-time hour [minute second]) -- the next time the clock will read
    hour:minute:second (on a 24-hour clock): today, if that's still to come,
    otherwise tomorrow. So (sleep-until (next-time 9 30)) waits until 9:30 am."""
    current = now().replace(microsecond=0)
    try:
        target = current.replace(hour=hour, minute=minute, second=second)
    except (TypeError, ValueError):
        raise LispError("next-time: %s:%s:%s isn't a time of day -- the hour is 0 to 23, and the "
                        "minute and second 0 to 59" % (_brief(hour), _brief(minute), _brief(second)))
    if target <= current:
        target += datetime.timedelta(days=1)
    return time_list(target)


def lisp_sleep(seconds):
    """(sleep seconds) -- wait that many seconds (a fraction is fine), then
    return '(). Interrupting the kernel, or Ctrl-C at the console, stops the
    wait."""
    check_seconds(seconds, "sleep")
    if seconds < 0:
        raise LispError("sleep: can't wait %s seconds -- the number must be 0 or more" % (seconds,))
    time.sleep(seconds)
    return NIL


SLEEP_UNTIL_CHECK_SECONDS = 60      # sleep-until looks at the clock at least this often


def sleep_until(t):
    """(sleep-until time) -- wait until the clock reaches `time`, then return
    '(); return at once if it already has. It looks at the clock at least
    once a minute while it waits, so it still wakes on time if the computer
    was asleep in between, or the clock was changed."""
    target = as_datetime(t, "sleep-until")
    while True:
        wait = (target - now()).total_seconds()
        if wait <= 0:
            return NIL
        time.sleep(min(wait, SLEEP_UNTIL_CHECK_SECONDS))


BUILTINS = {
    "current-time": current_time,
    "today": today,
    "time-add": time_add,
    "seconds-between": seconds_between,
    "time->string": time_to_string,
    "next-time": next_time,
    "sleep": lisp_sleep,
    "sleep-until": sleep_until,
}
