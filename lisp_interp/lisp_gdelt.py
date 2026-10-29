"""The tone of the news, from GDELT, for the Lisp interpreter.

GDELT (https://www.gdeltproject.org) reads news sites around the world,
in many languages, as articles come out, and scores the tone of each
article: how positive or negative its words are, from about -10 (very
negative) to +10 (very positive), though most articles are between -5 and
+5. Its DOC API (https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
finds the articles that match a search, from 2017 on, and gives their
average tone, day by day. It's free and needs no key.

  (gdelt-tone query [:start-date d :end-date d :cache-hours h])
                     a table with a row per day: the average tone of the
                     articles that match, how many there were, and what
                     share they were of all the articles GDELT read

GDELT asks for no more than one request every 5 seconds, and each call
makes two (the tone and the number of articles), so these wait between
requests. Downloads are kept for 12 hours (in lisp_http's cache).
"""

import datetime
import json
import time
import urllib.parse

from lisp_core import NETWORK, LispError, date_argument, keyword_options, lisp_error_of_kind
from lisp_data_common import dated_table
import lisp_http

DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
CACHE_HOURS = 12
SECONDS_BETWEEN_REQUESTS = 6        # GDELT asks for at most one every 5 seconds
FIRST_DATE = datetime.date(2017, 1, 1)
DEFAULT_DAYS = 90                   # with no :start-date, the last 90 days

last_request_time = 0.0             # when this module last asked GDELT, by time.time()


def wait_for_gdelt():
    """Wait until SECONDS_BETWEEN_REQUESTS have passed since the last request to GDELT."""
    global last_request_time
    seconds_left = last_request_time + SECONDS_BETWEEN_REQUESTS - time.time()
    if seconds_left > 0:
        time.sleep(seconds_left)
    last_request_time = time.time()


def gdelt_timeline(query, mode, start, end, cache_hours, who):
    """One of GDELT's timelines for the query, from start to end (dates): a
    list of its points, {"date": "20261001T000000Z", "value": ..., ...}.
    An empty list if no articles match."""
    url = DOC_API_URL + "?" + urllib.parse.urlencode({
        "query": query, "mode": mode, "format": "json",
        "startdatetime": start.strftime("%Y%m%d") + "000000",
        "enddatetime": end.strftime("%Y%m%d") + "235959"})

    def check(data):
        read_answer(data, who)                  # a problem isn't kept in the cache

    try:
        data = lisp_http.download(url, cache_hours, None, who, check=check, wait=wait_for_gdelt)
    except LispError as e:
        if "HTTP 429" not in str(e):
            raise
        raise lisp_error_of_kind("%s: GDELT says it has been asked too often (it allows one request every %d "
                                 "seconds, and asks for a pause after more); try again in a few minutes"
                                 % (who, 5), NETWORK)
    timeline = read_answer(data, who).get("timeline") or []
    return timeline[0]["data"] if timeline else []


def read_answer(data, who):
    """GDELT's answer, as a dict. When GDELT can't answer -- a search it
    doesn't understand, or too many requests -- it says so in text, not
    JSON, in an answer that says it's fine (HTTP 200)."""
    text = lisp_http.as_text(data).strip()
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        answer = None
    if not isinstance(answer, dict):
        raise LispError("%s: GDELT says: %s" % (who, text[:300]))
    return answer


def point_date(point):
    """The day of one point of a timeline, whose "date" is like "20261001T000000Z"."""
    text = point["date"]
    return datetime.date(int(text[0:4]), int(text[4:6]), int(text[6:8]))


def gdelt_tone(query, *options):
    """(gdelt-tone query [:start-date d :end-date d :cache-hours h]) -- the tone
    of the news articles that match the query, by day: a table with a date
    column, oldest first, and

      tone      the average tone of the day's articles that match: below 0
                is negative, above 0 positive (most are between -5 and +5)
      articles  how many articles matched
      share     the percent of all the articles GDELT read that day that matched

    The query is GDELT's: words ("inflation") match articles with all of
    them, a phrase in quotes ("\\"mortgage rates\\"") matches the phrase, OR
    in parentheses matches any ("(recession OR layoffs)"), a minus leaves
    articles out (-sports), and sourcelang:english or sourcecountry:US
    limits where they're from. The days are the last 90 days, unless
    :start-date and :end-date (dates, or YYYY-MM-DD text) say otherwise;
    GDELT goes back to 2017. A day with no articles that match has a tone
    of NaN."""
    who = "gdelt-tone"
    options = keyword_options(options, ["start-date", "end-date", "cache-hours"], who)
    end = date_argument(options["end-date"], who, ":end-date") if "end-date" in options else datetime.date.today()
    if "start-date" in options:
        start = date_argument(options["start-date"], who, ":start-date")
    else:
        start = end - datetime.timedelta(days=DEFAULT_DAYS - 1)
    if start < FIRST_DATE:
        raise LispError("%s: GDELT's searches go back only to %s, not %s" % (who, FIRST_DATE, start))
    if start > end:
        raise LispError("%s: the :start-date, %s, is after the :end-date, %s" % (who, start, end))
    cache_hours = options.get("cache-hours", CACHE_HOURS)

    # GDELT gives points every 15 minutes or every hour for a short span of
    # days, and every day for a longer one; either way, they're added up by day.
    tone_points = gdelt_timeline(str(query), "timelinetone", start, end, cache_hours, who)
    count_points = gdelt_timeline(str(query), "timelinevolraw", start, end, cache_hours, who)
    articles = {}                       # day -> articles that match
    all_articles = {}                   # day -> all the articles GDELT read
    for point in count_points:
        day = point_date(point)
        articles[day] = articles.get(day, 0) + point["value"]
        all_articles[day] = all_articles.get(day, 0) + point.get("norm", 0)
    count_at = {point["date"]: point["value"] for point in count_points}     # articles at each time GDELT gives
    tone_sums = {}                      # day -> the sum of the tone of each article that matches
    for point in tone_points:
        day = point_date(point)
        tone_sums[day] = tone_sums.get(day, 0.0) + point["value"] * count_at.get(point["date"], 0)

    tone = {day: (tone_sums.get(day, 0.0) / n if n else float("nan")) for day, n in articles.items()}
    share = {day: (100.0 * articles[day] / n if n else float("nan")) for day, n in all_articles.items()}
    return dated_table([("tone", tone),
                        ("articles", articles),
                        ("share", share)])


BUILTINS = {
    "gdelt-tone": gdelt_tone,
}
