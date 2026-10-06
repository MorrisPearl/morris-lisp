"""Downloading data from the web for the Lisp interpreter: http-get-json,
http-get-csv, and http-get-text, with an optional local cache, plus
http-url for building a URL with query parameters.

These reach any web API that returns JSON, CSV, or text -- the New York
Fed's SOFR history, the Treasury's yield curves, the BLS, and so on --
without writing Python for each one.

CACHE: give a number of hours as cache-hours and a download is saved on
disk; asking for the same URL again within that many hours reads the
saved copy instead of the network. That makes reruns fast, keeps you
under an API's rate limits, and means a notebook gives the same answer
twice. The files go in ~/.cache/morris_lisp/http (or the directory named
by the LISP_HTTP_CACHE environment variable); (http-clear-cache) deletes
them, and any more than KEPT_DAYS old are deleted as new ones are saved.

A download that fails in a way that may pass -- no answer, a dropped
connection, or the server's own trouble (HTTP 500 and up) -- is tried once
more, after RETRY_SECONDS.

JSON becomes Lisp data: an object becomes a hash table with string keys
(read it with hash-table-ref), an array becomes a list, true/false become
#t/#f, and null becomes '().
"""

import csv
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from lisp_core import LispError, LispHashTable, LispString, NIL, Pair, list_to_pairs, pairs_to_list
from lisp_csv import table_from_csv_rows


USER_AGENT = "morris-lisp (https://github.com/MorrisPearl/morris-lisp)"
TIMEOUT_SECONDS = 30
RETRY_SECONDS = 2       # how long to wait before trying a failed download again
KEPT_DAYS = 31          # saved downloads older than this are deleted (no built-in keeps one 30 days or more)


def cache_directory():
    return os.environ.get("LISP_HTTP_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "morris_lisp", "http")


def headers_argument(headers, name):
    """An optional association list of (name . value) header pairs, as a dict."""
    if headers is None or headers is NIL:
        return {}
    result = {}
    for entry in pairs_to_list(headers):
        if not isinstance(entry, Pair):
            raise LispError("%s: headers must be a list of (name . value) pairs" % name)
        result[str(entry.car)] = str(entry.cdr)
    return result


def download(url, cache_hours, headers, name, shown_url=None, body=None, check=None):
    """The bytes at `url`: from the cache if a copy younger than cache_hours
    is saved there, otherwise from the network (saving a copy if
    cache_hours is more than 0). An error message shows shown_url in place
    of url, if it's given -- for a URL with an API key in it. Given a body
    (bytes), the request is a POST that sends it; the cache tells requests
    with different bodies apart. Given check, a function that raises an
    error if the bytes it's passed aren't an answer -- for a web API that
    reports a problem in an answer that says it's fine (HTTP 200) -- it's
    called with each download before it's saved, so a problem isn't
    kept."""
    url = str(url)
    shown_url = shown_url or url
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers_argument(headers, name))
    hours = float(cache_hours) if cache_hours is not None and cache_hours is not NIL else 0.0

    key = hashlib.sha256((url + "\n" + json.dumps(request_headers, sort_keys=True) + "\n" +
                          (body or b"").decode("utf-8", errors="replace")).encode()).hexdigest()
    cached_file = os.path.join(cache_directory(), key)
    if hours > 0 and os.path.exists(cached_file) and time.time() - os.path.getmtime(cached_file) < hours * 3600:
        with open(cached_file, "rb") as f:
            return f.read()

    try:
        request = urllib.request.Request(url, data=body, headers=request_headers)
    except ValueError as e:                     # not a URL
        raise LispError("%s: couldn't download %s: %s" % (name, shown_url, e))
    data = fetch(request, name, shown_url, last_try=False)
    if data is None:                            # it may have been a passing problem: once more, after a moment
        time.sleep(RETRY_SECONDS)
        data = fetch(request, name, shown_url, last_try=True)
    if check:
        check(data)

    if hours > 0:
        os.makedirs(cache_directory(), exist_ok=True)
        with open(cached_file, "wb") as f:
            f.write(data)
        delete_old_downloads()
    return data


def fetch(request, name, shown_url, last_try):
    """One try at a download: its bytes -- or, if it failed in a way that
    may pass (no answer, a dropped connection, or HTTP 500 and up, the
    server's own trouble) and this isn't the last try, None."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", errors="replace").strip()
        e.close()       # the error holds the connection open until it's closed
        if e.code >= 500 and not last_try:
            return None
        raise LispError("%s: %s returned HTTP %d %s%s" % (name, shown_url, e.code, e.reason,
                                                          (" -- " + detail) if detail else ""))
    except (urllib.error.URLError, OSError) as e:
        if not last_try:
            return None
        raise LispError("%s: couldn't download %s: %s" % (name, shown_url, e))


def delete_old_downloads():
    """Delete the saved downloads more than KEPT_DAYS old, so the cache
    doesn't only grow."""
    directory = cache_directory()
    oldest_kept = time.time() - KEPT_DAYS * 24 * 3600
    for file_name in os.listdir(directory):
        path = os.path.join(directory, file_name)
        try:
            if os.path.getmtime(path) < oldest_kept:
                os.remove(path)
        except OSError:                         # (gone already)
            pass


def as_text(data):
    return data.decode("utf-8-sig", errors="replace")


def json_to_lisp(value):
    """Parsed JSON as Lisp data (see the module docstring)."""
    if isinstance(value, dict):
        table = LispHashTable()
        for k, v in value.items():
            table.table[LispString(k)] = json_to_lisp(v)
        return table
    if isinstance(value, list):
        return list_to_pairs([json_to_lisp(v) for v in value])
    if isinstance(value, str):
        return LispString(value)
    if value is None:
        return NIL
    return value            # a number, or True/False


def http_get_text(url, cache_hours=None, headers=None):
    """(http-get-text url [cache-hours headers]) -- the page at url, as a
    string. cache-hours: see the module docstring (default: no cache).
    headers: an optional list of (name . value) pairs to send, e.g. for an
    API key."""
    return LispString(as_text(download(url, cache_hours, headers, "http-get-text")))


def http_get_json(url, cache_hours=None, headers=None):
    """(http-get-json url [cache-hours headers]) -- the JSON at url, as Lisp
    data: objects become hash tables, arrays become lists."""
    text = as_text(download(url, cache_hours, headers, "http-get-json"))
    try:
        return json_to_lisp(json.loads(text))
    except json.JSONDecodeError as e:
        raise LispError("http-get-json: %s didn't return valid JSON (%s); it starts: %s"
                        % (url, e, text[:200]))


def http_get_csv(url, has_header=True, cache_hours=None, headers=None):
    """(http-get-csv url [has-header? cache-hours headers]) -- the CSV file at
    url, as a table, read exactly as load-csv reads a file."""
    text = as_text(download(url, cache_hours, headers, "http-get-csv"))
    rows = list(csv.reader(io.StringIO(text)))
    return table_from_csv_rows(rows, has_header is not False, str(url))


def http_url(base, parameters):
    """(http-url base parameters) -- base with a query string built from
    parameters, a list of (name . value) pairs or a hash table; values are
    encoded properly, so spaces and symbols in them are safe:
    (http-url "https://x.org/data" (list (cons "series" "DGS10") (cons "limit" 5)))
    => "https://x.org/data?series=DGS10&limit=5"."""
    if isinstance(parameters, LispHashTable):
        pairs = list(parameters.table.items())
    else:
        pairs = []
        for entry in pairs_to_list(parameters):
            if not isinstance(entry, Pair):
                raise LispError("http-url: parameters must be a list of (name . value) pairs")
            pairs.append((entry.car, entry.cdr))
    query = urllib.parse.urlencode([(str(k), str(v)) for k, v in pairs])
    base = str(base)
    if not query:
        return LispString(base)
    return LispString(base + ("&" if "?" in base else "?") + query)


def http_clear_cache():
    """(http-clear-cache) -- delete every saved download; returns how many."""
    directory = cache_directory()
    if not os.path.isdir(directory):
        return 0
    removed = 0
    for file_name in os.listdir(directory):
        os.remove(os.path.join(directory, file_name))
        removed += 1
    return removed


BUILTINS = {
    "http-get-text": http_get_text,
    "http-get-json": http_get_json,
    "http-get-csv": http_get_csv,
    "http-url": http_url,
    "http-clear-cache": http_clear_cache,
}
