"""Google Sheets, for the Lisp interpreter: send tables to a new spreadsheet in
your own Google Drive.

  (google-login creds)                                 sign in: opens your browser
  (google-sheet creds title formats table ... [:names names])
                                                       a new spreadsheet, a tab for each table

Google signs in with OAuth. (google-login creds) opens Google's sign-in page
in your own browser (Google doesn't allow it in an embedded window, as
Schwab's is); you sign in there and approve the app, and Google sends the
browser to a port this program is listening on, with a code in the address.
The code is traded for an access token (good for an hour, and renewed here
as needed) and a refresh token, which are kept in google_tokens.json, next
to the credentials file, readable only by you. After that google-sheet just
works, until the sign-in is revoked, or runs out: a sign-in lasts a week
while the app's "publishing status" in Google Cloud is "Testing", and
indefinitely once it is "In production" (which, for an app that only you
use, you can set yourself, with no review).

The credentials file needs two entries, from a Google Cloud project with the
Google Sheets API turned on and an "OAuth client ID" of type "Desktop app"
(the library manual, "Google Sheets", says how to make them):
  "google_client_id"      "google_client_secret"

The app asks for one permission, https://www.googleapis.com/auth/drive.file:
to see and change the files it made itself, and no others. The spreadsheet
is made in the Drive of whoever signs in, so there is nothing to share.

google-sheet writes each table as a tab: a bold heading row, which stays in
place as you scroll, and a row for each table row. Numbers are written as
numbers, dates as dates, and text as text (never as a formula, even if it
begins with =). A column's format -- the same list of formats display-table
takes -- becomes its number format in the sheet, and a column whose format
is hide, or just (name), is left out.
"""

import base64
import datetime
import hashlib
import http.server
import json
import math
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from lisp_core import LispDate, LispError, LispString, Keyword, NIL, Pair, keyword_options, to_display_string
from lisp_data_common import credential
from lisp_tables import HIDDEN, column_values, format_specs, table_columns
from lisp_vector_math import is_number

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/drive.file"
TIMEOUT_SECONDS = 60
SIGN_IN_WAIT_SECONDS = 300      # how long google-login waits for you to sign in
CELLS_PER_REQUEST = 50000       # how many cells are sent in one request
MOST_CELLS = 10000000           # what one Google spreadsheet can hold
TAB_NAME_LENGTH = 100           # the longest a tab's name can be
SHEETS_EPOCH = datetime.date(1899, 12, 30)      # day 0 of a spreadsheet's dates
DATE_PATTERN = "yyyy-mm-dd"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def google_message(text):
    """What Google's error answer says."""
    try:
        answer = json.loads(text)
    except ValueError:
        return " ".join(text.split())[:300] or "no reason given"
    if isinstance(answer, dict):
        error = answer.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("status") or error)
        if error:
            return "%s%s" % (error, ": " + str(answer["error_description"]) if answer.get("error_description") else "")
    return " ".join(text.split())[:300]


def google_request(method, url, who, headers, body=None):
    """One request to Google: its answer's JSON (None if it has no answer).
    The tokens go in the headers or the body, so they're never in an error
    message."""
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers, Accept="application/json"))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text) if text.strip() else None
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        e.close()
        raise LispError("%s: Google says (HTTP %d): %s" % (who, e.code, google_message(text)))
    except (urllib.error.URLError, OSError) as e:
        raise LispError("%s: couldn't reach Google: %s" % (who, e))


def token_request(credentials_path, form, who):
    """Ask Google for tokens: the app's id and secret, and the form (a code
    to trade, or a refresh token)."""
    form = dict(form,
                client_id=credential(credentials_path, "google_client_id", who,
                                     "the app's client ID, from console.cloud.google.com"),
                client_secret=credential(credentials_path, "google_client_secret", who,
                                         "the app's client secret, from console.cloud.google.com"))
    answer = google_request("POST", TOKEN_URL, who, {"Content-Type": "application/x-www-form-urlencoded"},
                            urllib.parse.urlencode(form).encode())
    if not answer or "access_token" not in answer:
        raise LispError("%s: Google didn't send a token" % who)
    return answer


# ---------------------------------------------------------------------------
# Signing in, and the tokens
# ---------------------------------------------------------------------------

def token_file(credentials_path):
    """Where the tokens are kept: google_tokens.json, next to the credentials file."""
    return os.path.join(os.path.dirname(os.path.abspath(str(credentials_path))), "google_tokens.json")


def save_tokens(credentials_path, tokens):
    """Save the tokens, readable only by you."""
    path = token_file(credentials_path)
    descriptor = os.open(path + ".part", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as f:
        json.dump(tokens, f)
    os.replace(path + ".part", path)


def load_tokens(credentials_path, who):
    try:
        with open(token_file(credentials_path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        raise LispError("%s: not signed in to Google -- sign in with (google-login creds)" % who)


def access_token(credentials_path, who):
    """A current access token: the saved one, or -- if it has run out -- a
    new one, from the refresh token."""
    tokens = load_tokens(credentials_path, who)
    if time.time() < tokens["access_expires"]:
        return tokens["access_token"]
    try:
        answer = token_request(credentials_path, {"grant_type": "refresh_token",
                                                  "refresh_token": tokens["refresh_token"]}, who)
    except LispError as e:
        raise LispError("%s -- sign in again with (google-login creds)" % e)
    tokens["access_token"] = answer["access_token"]
    tokens["access_expires"] = time.time() + float(answer.get("expires_in", 3600)) - 60
    save_tokens(credentials_path, tokens)
    return tokens["access_token"]


def open_browser(url):
    """Open the sign-in page in your browser; if that can't be done, say
    where to go."""
    if not webbrowser.open(url):
        print("Open this address in your browser, and sign in to Google:\n" + url)


def wait_for_sign_in(server, state, who):
    """Wait for Google to send the browser to this program's port, and give
    back the code in the address. `server` is listening on it."""
    server.timeout = 1
    deadline = time.time() + SIGN_IN_WAIT_SECONDS
    while not server.answer and time.time() < deadline:
        server.handle_request()
    if not server.answer:
        raise LispError("%s: no sign-in within %d minutes" % (who, SIGN_IN_WAIT_SECONDS // 60))
    if server.answer.get("error"):
        raise LispError("%s: Google says: %s" % (who, server.answer["error"]))
    if server.answer.get("state") != state or not server.answer.get("code"):
        raise LispError("%s: the sign-in answer wasn't the one asked for -- try again" % who)
    return server.answer["code"]


class SignInPage(http.server.BaseHTTPRequestHandler):
    """The page the browser lands on after signing in: it notes the address's
    query (the code, or the error) and tells you to close the window."""

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in query or "error" in query:
            self.server.answer = {key: values[0] for key, values in query.items()}
        body = b"<html><body><p>Signed in. You can close this window and go back to your program.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *arguments):
        pass                    # (quietly)


def google_login(credentials_path):
    """(google-login creds) -- sign in to Google: opens Google's sign-in page
    in your browser, where you sign in and approve the app; then saves the
    tokens. Returns #t. (The address the browser is sent back to is on your
    own computer, 127.0.0.1, at a port chosen for this sign-in only.)"""
    who = "google-login"
    client_id = credential(credentials_path, "google_client_id", who,
                           "the app's client ID, from console.cloud.google.com")
    credential(credentials_path, "google_client_secret", who, "the app's client secret, from console.cloud.google.com")
    # PKCE: the code can only be traded by this program, which knows the verifier whose hash is sent now.
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    server = http.server.HTTPServer(("127.0.0.1", 0), SignInPage)
    server.answer = None
    try:
        redirect = "http://127.0.0.1:%d" % server.server_address[1]
        open_browser(AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
            "access_type": "offline", "prompt": "consent"}))
        code = wait_for_sign_in(server, state, who)
    finally:
        server.server_close()
    answer = token_request(credentials_path, {"grant_type": "authorization_code", "code": code,
                                              "redirect_uri": redirect, "code_verifier": verifier}, who)
    if not answer.get("refresh_token"):
        raise LispError("%s: Google didn't send a refresh token" % who)
    save_tokens(credentials_path, {"access_token": answer["access_token"], "refresh_token": answer["refresh_token"],
                                   "access_expires": time.time() + float(answer.get("expires_in", 3600)) - 60})
    return True


# ---------------------------------------------------------------------------
# Formats: display-table's format specs, as a spreadsheet's number formats
# ---------------------------------------------------------------------------

# Python's format spec: [[fill]align][sign][#][0][width][,|_][.precision][type]
FORMAT_SPEC = re.compile(r"^(?:.?[<>=^])?([+\- ]?)(#?)(0?)(\d*)([,_]?)(?:\.(\d+))?([a-zA-Z%]?)$")


def number_format(spec, column_name):
    """A spreadsheet's number format for a format spec, as (type, pattern) --
    ("NUMBER", "#,##0.00") for ",.2f" -- or None for one that only lays out
    the text (">12", say), which a spreadsheet does with its column widths.
    The specs it understands are f (decimals), d (a whole number), e (powers
    of 10), and % (a percentage), each with , for commas, a + to always show
    the sign, and .N for the decimals; and , alone, which is a whole number
    with commas. The rest -- g, x, b, and so on -- have no spreadsheet
    equivalent, and are an error."""
    match = FORMAT_SPEC.match(spec)
    if not match:
        raise LispError('google-sheet: column %s: "%s" isn\'t a format spec -- write one as format does, ",.2f", say'
                        % (column_name, spec))
    sign, alternate, zero, width, grouping, precision, kind = match.groups()
    if kind == "s" or (kind == "" and not grouping and precision is None):
        return None                                     # (only the layout of the text)
    if grouping == "_" or alternate or kind not in ("f", "F", "%", "d", "n", "e", "E", ""):
        raise LispError('google-sheet: column %s: the format "%s" has no spreadsheet equivalent -- use f, d, e, or '
                        '%%, with .N for the decimals and , for commas' % (column_name, spec))
    if kind == "" and precision is not None:
        raise LispError('google-sheet: column %s: the format "%s" needs a type: f for decimals, say, as in ".2f"'
                        % (column_name, spec))
    if kind in ("d", "n", "") and precision is not None:
        raise LispError('google-sheet: column %s: the format "%s" has decimals, but d is a whole number'
                        % (column_name, spec))
    decimals = int(precision) if precision is not None else 6
    if grouping:
        whole = "#,##0"
    elif zero and width:
        whole = "0" * int(width)                        # (padded with zeros, to the width)
    else:
        whole = "0"
    if kind in ("d", "n", ""):
        pattern, type_name = whole, "NUMBER"
    elif kind in ("f", "F"):
        pattern, type_name = whole + ("." + "0" * decimals if decimals else ""), "NUMBER"
    elif kind == "%":
        pattern, type_name = whole + ("." + "0" * decimals if decimals else "") + "%", "PERCENT"
    else:
        pattern, type_name = "0" + ("." + "0" * decimals if decimals else "") + "E+00", "SCIENTIFIC"
    if sign == "+":
        pattern = "+%s;-%s" % (pattern, pattern)
    return type_name, pattern


# ---------------------------------------------------------------------------
# A table, as the cells of a tab
# ---------------------------------------------------------------------------

def clean_number(x):
    """A number as a JSON value: nothing (an empty cell) for NaN or infinity."""
    return x if math.isfinite(x) else ""


def tab_values(vector):
    """A column's values as spreadsheet cells, and whether they are
    "numbers", "dates", or "text": a missing value is an empty string, a date
    is its day number (a spreadsheet's dates are numbers, shown as dates by
    the column's number format), text is as it is (written to the sheet as
    it is, so it's never a formula), and anything else (a list, say) is as
    display shows it."""
    values = column_values(vector)          # (a float32 as its shortest decimal form: 0.1, not 0.10000000149)
    present = [x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if present and all(isinstance(x, LispDate) for x in present):
        kind = "dates"
    elif all(is_number(x) for x in present):
        kind = "numbers"
    else:
        kind = "text"
    cells = []
    for x in values:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            cells.append("")
        elif isinstance(x, LispDate):
            cells.append((x.date - SHEETS_EPOCH).days)
        elif isinstance(x, bool):
            cells.append(x)
        elif isinstance(x, (int, float)):
            cells.append(clean_number(x))
        else:
            cells.append(str(to_display_string(x)))
    return cells, kind


def tab_name(name, taken):
    """A tab's name from a table's first column's name: no longer than a
    tab's name can be, and different (as a spreadsheet counts it, not
    caring about capitals) from those already taken -- Sales, Sales 2, ..."""
    name = " ".join(str(name).split())[:TAB_NAME_LENGTH - 4] or "Sheet"
    candidate, count = name, 1
    while candidate.lower() in taken:
        count += 1
        candidate = "%s %d" % (name, count)
    return candidate


def tab_for(table, specs, name):
    """A table as a tab: (the columns' names, the columns' cells, each
    column's number format as (type, pattern) or None). A column whose
    format is hide isn't in it."""
    shown = [(heading, vector) for heading, vector in table_columns(table, "google-sheet")
             if specs.get(heading) != HIDDEN]
    if not shown:
        raise LispError("google-sheet: every column of the table for tab %s is hidden, or it has none" % name)
    headings, columns, formats = [], [], []
    for heading, vector in shown:
        cells, kind = tab_values(vector)
        spec = specs.get(heading)
        if kind == "dates":
            format_ = ("DATE", DATE_PATTERN)
        else:
            format_ = number_format(spec, heading) if spec is not None else None
            if format_ and kind == "text":
                raise LispError('google-sheet: column %s: the format "%s" is for numbers, but it has text'
                                % (heading, spec))
        headings.append(heading)
        columns.append(cells)
        formats.append(format_)
    return headings, columns, formats


def quoted(tab):
    """A tab's name, as a range of a spreadsheet writes it: 'Sales'!A1."""
    return "'%s'" % tab.replace("'", "''")


# ---------------------------------------------------------------------------
# google-sheet
# ---------------------------------------------------------------------------

def tables_and_options(arguments):
    """google-sheet's arguments after the formats: the tables, up to the
    first keyword, and the options after it, as a dict."""
    first_keyword = next((i for i, a in enumerate(arguments) if isinstance(a, Keyword)), len(arguments))
    return list(arguments[:first_keyword]), keyword_options(arguments[first_keyword:], ["names"], "google-sheet")


def tab_names(tables, options):
    """The tabs' names: :names, if given, or one from each table's first column."""
    who = "google-sheet"
    taken, names = set(), []
    if "names" in options:
        given = [str(n) for n in _list(options["names"])]
        if len(given) != len(tables):
            raise LispError("%s: :names has %d names, for %d tables" % (who, len(given), len(tables)))
        for name in given:
            if not name.strip() or len(name) > TAB_NAME_LENGTH or name.lower() in taken:
                raise LispError('%s: each of the :names must be different, and from 1 to %d characters, not "%s"'
                                % (who, TAB_NAME_LENGTH, name))
            taken.add(name.lower())
            names.append(name)
        return names
    for number, table in enumerate(tables, start=1):
        columns = table_columns(table, who)
        names.append(tab_name(columns[0][0] if columns else "Sheet %d" % number, taken))
        taken.add(names[-1].lower())
    return names


def _list(value):
    """A Lisp list as a Python list."""
    items = []
    while isinstance(value, Pair):
        items.append(value.car)
        value = value.cdr
    if value is not NIL:
        raise LispError("google-sheet: :names must be a list of names")
    return items


def requests_of_ranges(names, tabs):
    """The cells to write, as a list of requests, each a list of ranges
    ({"range": "'Sales'!A1", "values": rows}) of at most CELLS_PER_REQUEST
    cells in all (Google limits how much one request can carry, and how
    many requests a minute): each tab's rows, in pieces if it's long, and
    small tabs together."""
    requests, current, cells = [], [], 0
    for name, (headings, columns, _) in zip(names, tabs):
        rows = [headings] + [list(row) for row in zip(*columns)]
        rows_per_piece = max(CELLS_PER_REQUEST // len(headings), 1)
        for first in range(0, len(rows), rows_per_piece):
            piece = rows[first:first + rows_per_piece]
            if current and cells + len(piece) * len(headings) > CELLS_PER_REQUEST:
                requests.append(current)
                current, cells = [], 0
            current.append({"range": "%s!A%d" % (quoted(name), first + 1), "values": piece})
            cells += len(piece) * len(headings)
    return requests + [current]


def google_sheet(credentials_path, title, formats, *arguments):
    """(google-sheet creds title formats table ... [:names names]) -- a new
    spreadsheet in your Google Drive called `title`, with a tab for each
    table; returns its address. `formats` is a list of (column-name spec),
    as display-table takes: a column with a spec has its numbers laid out
    that way, one without is shown plain, and one whose spec is hide, or
    that is just (column-name), is left out. A tab is named for its table's
    first column -- for a stratification table, the column it was
    stratified by -- unless :names gives a list of names. The first call
    needs a sign-in: (google-login creds)."""
    who = "google-sheet"
    if not isinstance(title, str) or not title.strip():
        raise LispError("%s: the title must be a string, not %s" % (who, to_display_string(title)))
    specs = format_specs(formats, who)
    tables, options = tables_and_options(arguments)
    if not tables:
        raise LispError("%s: give it at least one table, after the formats" % who)
    names = tab_names(tables, options)
    tabs = [tab_for(table, specs, name) for table, name in zip(tables, names)]
    if sum((len(columns[0]) + 1) * len(columns) for _, columns, _ in tabs) > MOST_CELLS:
        raise LispError("%s: that's more than the %s cells a Google spreadsheet can hold" % (who, format(MOST_CELLS, ",")))

    token = access_token(credentials_path, who)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    def call(url, body):
        return google_request("POST", url, who, headers, json.dumps(body).encode())

    made = call(SHEETS_URL, {
        "properties": {"title": title.strip()},
        "sheets": [{"properties": {"title": name, "gridProperties": {"rowCount": max(len(columns[0]) + 1, 2),
                                                                     "columnCount": len(columns),
                                                                     "frozenRowCount": 1}}}
                   for name, (_, columns, _) in zip(names, tabs)]})
    url, sheet_ids = made["spreadsheetUrl"], [s["properties"]["sheetId"] for s in made["sheets"]]
    try:
        for ranges in requests_of_ranges(names, tabs):
            call("%s/%s/values:batchUpdate" % (SHEETS_URL, made["spreadsheetId"]),
                 {"valueInputOption": "RAW", "data": ranges})
        requests = []
        for sheet_id, (headings, columns, formats_) in zip(sheet_ids, tabs):
            rows = len(columns[0])
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}})
            for index, format_ in enumerate(formats_):
                if format_ and rows:
                    requests.append({"repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": rows + 1,
                                  "startColumnIndex": index, "endColumnIndex": index + 1},
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": format_[0], "pattern": format_[1]}}},
                        "fields": "userEnteredFormat.numberFormat"}})
            requests.append({"autoResizeDimensions": {"dimensions": {
                "sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(headings)}}})
        call("%s/%s:batchUpdate" % (SHEETS_URL, made["spreadsheetId"]), {"requests": requests})
    except LispError as e:
        raise LispError("%s -- the spreadsheet was made, at %s, but isn't finished" % (e, url))
    return LispString(url)


BUILTINS = {
    "google-login": google_login,
    "google-sheet": google_sheet,
}
