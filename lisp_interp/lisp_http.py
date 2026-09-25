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
them.

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


def download(url, cache_hours, headers, name):
    """The bytes at `url`: from the cache if a copy younger than cache_hours
    is saved there, otherwise from the network (saving a copy if
    cache_hours is more than 0)."""
    url = str(url)
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers_argument(headers, name))
    hours = float(cache_hours) if cache_hours is not None and cache_hours is not NIL else 0.0

    key = hashlib.sha256((url + "\n" + json.dumps(request_headers, sort_keys=True)).encode()).hexdigest()
    cached_file = os.path.join(cache_directory(), key)
    if hours > 0 and os.path.exists(cached_file) and time.time() - os.path.getmtime(cached_file) < hours * 3600:
        with open(cached_file, "rb") as f:
            return f.read()

    try:
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read()
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", errors="replace").strip()
        raise LispError("%s: %s returned HTTP %d %s%s" % (name, url, e.code, e.reason,
                                                          (" -- " + detail) if detail else ""))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LispError("%s: couldn't download %s: %s" % (name, url, e))

    if hours > 0:
        os.makedirs(cache_directory(), exist_ok=True)
        with open(cached_file, "wb") as f:
            f.write(data)
    return data


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
