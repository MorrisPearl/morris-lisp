"""The words of SEC filings, and their tone, for the Lisp interpreter.

lisp_sec.py reads the numbers companies report; this reads what they
write. EDGAR (https://www.sec.gov/edgar) keeps every filing: 10-Ks and
10-Qs, 8-Ks (news a company must report within days: earnings, a new
chief executive, a merger), and the rest.

  (sec-filings creds company [:forms f :count n])
                     the company's filings: a table with a row for each,
                     oldest first, with its dates, form, and address
  (sec-filing-text creds url [:section s])
                     a filing's words, as plain text -- all of it, or one
                     section: "risk-factors" or "management-discussion" --
                     from the annual report, if the 10-K says it's there
  (text-tone text [:word-lists path])
                     how negative, positive, uncertain, ... a text's words
                     are, by the Loughran-McDonald word lists

THE WORD LISTS: Tim Loughran and Bill McDonald, of the University of Notre
Dame, made lists of the words that make a financial report sound
negative, positive, uncertain, litigious (about lawsuits), or constraining,
from reading 10-Ks; lists made for everyday English call words such as
"liability", "tax", or "cost" negative, which in a 10-K they aren't. The
lists are free for research (not for commercial use) as one CSV file,
from https://sraf.nd.edu/loughranmcdonald-master-dictionary/ -- download
it and put it in morris_lisp/data (where git leaves it out), or leave it
in your Downloads folder; text-tone finds it in either (or in
~/.cache/morris_lisp/word_lists), or where :word-lists says.

The SEC asks that every request say who's making it -- the credentials
file's "sec_user_agent" entry, as for lisp_sec. A filing never changes,
so a filing's text is kept for a week (in lisp_http's cache); a list of
filings, for 12 hours.
"""

import csv
import glob
import html.parser
import json
import os
import re

from lisp_core import LispError, LispHashTable, LispString, Pair, keyword_options, lisp_error_of_kind, list_to_pairs
from lisp_data_common import text_list
from lisp_sec import company_cik, user_agent
from lisp_tables import column_vector, make_table_value
import lisp_http

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%010d.json"
OLDER_SUBMISSIONS_URL = "https://data.sec.gov/submissions/%s"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s"
LIST_CACHE_HOURS = 12
FILING_CACHE_HOURS = 24 * 7

WORD_LISTS_NAME = "Loughran-McDonald_MasterDictionary_*.csv"
WORD_LISTS_FOLDERS = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"),     # morris_lisp/data
                      os.path.join("~", ".cache", "morris_lisp", "word_lists"), os.path.join("~", "Downloads")]
WORD_LISTS_PAGE = "https://sraf.nd.edu/loughranmcdonald-master-dictionary/"

# The measures text-tone gives, and each list's column in the word lists file
TONE_LISTS = [("negative", "Negative"), ("positive", "Positive"), ("uncertainty", "Uncertainty"),
              ("litigious", "Litigious"), ("constraining", "Constraining")]

# A positive word just after one of these ("not profitable") isn't counted
# as positive, as Loughran and McDonald suggest.
NEGATIONS = {"NO", "NOT", "NONE", "NEITHER", "NEVER", "NOBODY", "NOR"}
NEGATION_WORDS_BEFORE = 3

NO_SECTION = "no-section"           # the kind of error when a filing has no such section


def option(options, name):
    """An option's value, or None if it wasn't given -- or was given as '() or #f,
    as a library function passes on an option it was itself not given."""
    value = options.get(name)
    return None if value is False else value


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def sec_download(url, credentials_path, cache_hours, who):
    """The bytes at an SEC address."""
    headers = list_to_pairs([Pair(LispString("User-Agent"), LispString(user_agent(credentials_path, who)))])
    return lisp_http.download(url, cache_hours, headers, who)


def sec_json(url, credentials_path, who):
    """The JSON at an SEC address, as Python data."""
    return json.loads(lisp_http.as_text(sec_download(url, credentials_path, LIST_CACHE_HOURS, who)))


# ---------------------------------------------------------------------------
# The list of filings
# ---------------------------------------------------------------------------

def filing_rows(cik, filings):
    """The filings of one page of the SEC's list -- columns of equal length,
    "form": [...], "filingDate": [...], ... -- as a list of dicts."""
    rows = []
    items = filings.get("items") or [""] * len(filings["form"])
    descriptions = filings.get("primaryDocDescription") or [""] * len(filings["form"])
    for i in range(len(filings["form"])):
        accession = filings["accessionNumber"][i]
        document = filings["primaryDocument"][i]
        rows.append({
            "filing-date": filings["filingDate"][i],
            "report-date": filings["reportDate"][i] or None,
            "form": filings["form"][i],
            "items": items[i],
            "description": descriptions[i],
            "accession": accession,
            # A filing from before about 2001 has no main document: its url is
            # the whole filing as one text file, the way it was sent to the SEC.
            "url": ARCHIVES_URL % (cik, accession.replace("-", ""), document or accession + ".txt"),
        })
    return rows


def sec_filings(credentials_path, company, *options):
    """(sec-filings creds company [:forms f :count n]) -- the company's
    filings with the SEC: a table with a row for each, oldest first, of its
    filing-date, report-date (the end of the period it reports on, or '()),
    form ("10-K", "10-Q", "8-K", ...), items (for an 8-K, the numbers of the
    items it reports: "2.02" is results, "5.02" a change of officers),
    description, accession (the SEC's number for it), and url (its main
    document, for sec-filing-text). The company is a ticker ("AAPL") or a
    CIK number. :forms, a form or a list of them, keeps just those; :count,
    a number, keeps just the most recent that many."""
    who = "sec-filings"
    options = keyword_options(options, ["forms", "count"], who)
    cik = company_cik(credentials_path, company, who)
    answer = sec_json(SUBMISSIONS_URL % cik, credentials_path, who)
    rows = filing_rows(cik, answer["filings"]["recent"])
    for older in answer["filings"].get("files", []):        # filings older than the last 1,000 or so
        rows += filing_rows(cik, sec_json(OLDER_SUBMISSIONS_URL % older["name"], credentials_path, who))
    if option(options, "forms") is not None:
        forms = {form.upper() for form in text_list(options["forms"], who, ":forms")}
        rows = [row for row in rows if row["form"].upper() in forms]
    rows.sort(key=lambda row: (row["filing-date"], row["accession"]))
    if option(options, "count") is not None:
        count = int(options["count"])
        rows = rows[len(rows) - count:] if count > 0 else []
    names = ["filing-date", "report-date", "form", "items", "description", "accession", "url"]
    return make_table_value([(name, column_vector([row[name] for row in rows])) for name in names])


# ---------------------------------------------------------------------------
# A filing's text
# ---------------------------------------------------------------------------

class TextOfHtml(html.parser.HTMLParser):
    """The words of an HTML document, with a line break for each paragraph,
    heading, or row of a table. A filing with its numbers tagged (inline
    XBRL) starts with a hidden ix:header of tags, which is left out, as are
    scripts and styles."""

    LINE_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "title"}
    HIDDEN_TAGS = {"script", "style", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0                 # how many hidden tags we're inside

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN_TAGS:
            self.hidden += 1
        elif tag in self.LINE_TAGS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.HIDDEN_TAGS:
            self.hidden = max(0, self.hidden - 1)
        elif tag in self.LINE_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data.replace("\n", " "))     # in HTML, a line break in text is a space


def plain_text(document):
    """A filing's document (HTML, or plain text for the oldest filings) as
    plain text: a line for each paragraph, with runs of spaces made one."""
    if re.search(r"<(html|body|p|div)\b", document[:20000], re.I):
        parser = TextOfHtml()
        parser.feed(document)
        parser.close()
        document = "".join(parser.parts)
    lines = (re.sub(r"\s+", " ", line).strip() for line in document.replace("\xa0", " ").split("\n"))
    return "\n".join(line for line in lines if line)


# Each section: the item numbers it may be (a 10-K's or a 10-Q's), a word
# its title has, and its usual titles when it's part of an annual report.
SECTIONS = {
    "risk-factors": ({"1A"}, "risk factors", ["risk factors"]),
    "management-discussion": ({"7", "2"}, "management",
                              ["management's discussion and analysis",
                               "management's discussion and analysis of financial condition and results of operations"]),
}
ITEM_HEADING = re.compile(r"^item\s+(\d+[a-c]?)\b[^\n]{0,200}$", re.I | re.M)


def heading_title(text, start):
    """The title of the item heading at start, in small letters: its line --
    and the next line too, when the heading's line is only "Item 7." """
    lines = text[start:].split("\n", 2)
    title = lines[0]
    if len(title) < 12 and len(lines) > 1:
        title += " " + lines[1]
    return title.lower()


def section_text(text, section, who):
    """One section of a filing's text: from its heading ("Item 1A. Risk
    Factors") to the next heading of another item. A table of contents has
    the same headings, so the longest such stretch is the section."""
    if section not in SECTIONS:
        raise LispError("%s: there's no section %s -- the sections are %s"
                        % (who, section, ", ".join('"%s"' % name for name in SECTIONS)))
    items, title_word, _ = SECTIONS[section]
    headings = [(m.start(), m.group(1).upper()) for m in ITEM_HEADING.finditer(text)]
    best = ""
    for i, (start, item) in enumerate(headings):
        if item not in items or title_word not in heading_title(text, start):
            continue
        end = next((at for at, later in headings[i + 1:] if later != item), len(text))
        if end - start > len(best):
            best = text[start:end]
    if not best:
        raise lisp_error_of_kind('%s: the filing has no "%s" section that I could find%s'
                                 % (who, section, " (10-Ks have had one since 2005)" if section == "risk-factors" else ""),
                                 NO_SECTION)
    return best.strip()


# ---------------------------------------------------------------------------
# A section that's somewhere else: the annual report
# ---------------------------------------------------------------------------
# Some companies -- most of the big banks among them -- write their MD&A,
# and sometimes their risk factors, as part of their annual report to
# shareholders, and the 10-K's item only says where it is: 'Information in
# response to this Item 7 can be found in the 2025 Annual Report to
# Shareholders under "Financial Review."' The annual report is in the 10-K's
# own document (after the items), or filed with it as Exhibit 13. Either
# way, the section is found by the title the item quotes: from a line with
# just that title to the next heading that starts another part of the
# report. The title is often at the top of each of its pages, and in a
# table of contents too, so the longest such stretch is the section.

POINTER_WORDS = 150         # an item with fewer words than this may only say where the section is
QUOTED = re.compile(r"[\u201c\"]([^\u201d\"]{3,120})[\u201d\"]")
OTHER_FILING = re.compile(r"\bform 10-k\b")
THIS_FILING = re.compile(r"\bthis (annual report on )?form 10-k\b")

# The headings that start another part of an annual report, and so end a
# section -- the whole heading, since an MD&A has headings of its own such as
# "Consolidated balance sheets and cash flows analysis"
END_HEADING = re.compile(r"risk factors|controls and procedures|management's report on internal control over financial reporting"
                         r"|reports? of independent registered public accounting firm|consolidated balance sheets?"
                         r"|consolidated statements? of [a-z ,']+|(consolidated )?financial statements( and supplementary data)?"
                         r"|glossary( of [a-z ]+)?")


def heading_text(line):
    """A line as a heading to compare: small letters, plain apostrophes, without ending punctuation."""
    return line.lower().replace("\u2019", "'").strip().rstrip(".:,;").strip()


def pointed_titles(item_text, section):
    """The titles a short item says its section is under -- the titles it
    quotes: "Financial Review", or "Risk Factors" for "Financial Review -
    Risk Factors". If it quotes none (it may be just a list of the pages of
    the annual report), the section's usual titles, and any title in
    parentheses on its heading: "Item 2. Management's Discussion and
    Analysis (Financial Review)". None when the item is long enough to be
    the section itself, or points to another filing (a 10-Q's "our Annual
    Report on Form 10-K"), which isn't read."""
    lowered = item_text.lower().replace("\u2019", "'")
    if len(WORD.findall(item_text)) >= POINTER_WORDS:
        return []
    if OTHER_FILING.search(lowered) and not THIS_FILING.search(lowered):
        return []
    titles = []
    for quoted in QUOTED.findall(item_text):
        title = heading_text(re.split(r"\s[\u2013\u2014-]\s", quoted)[-1])
        if title and not title.startswith("item"):          # "Item 1A. Risk Factors" is an item, not a title
            titles.append(title)
    if not titles:
        heading = " ".join(item_text.split("\n")[:2])       # (its "Item 2." may be a line by itself)
        titles = list(SECTIONS[section][2]) + [heading_text(title) for title in re.findall(r"\(([^)]{3,60})\)", heading)]
    return titles


def titled_section(text, titles):
    """The longest stretch of text from a line that is one of the titles to
    the next heading that ends a section (END_HEADING, other than the
    title itself); "" if there's none. A title line with no such heading
    after it isn't counted: it isn't the start of a part of the report."""
    lines = text.split("\n")
    best = ""
    for i, line in enumerate(lines):
        if heading_text(line) not in titles:
            continue
        end = None
        for j in range(i + 1, len(lines)):
            heading = heading_text(lines[j])
            if heading not in titles and END_HEADING.fullmatch(heading):
                end = j
                break
        stretch = "\n".join(lines[i:end]) if end else ""
        if len(stretch) > len(best):
            best = stretch
    return best.strip()


def exhibit_13_urls(credentials_path, url, who):
    """The addresses of the annual report filed with a 10-K as Exhibit 13, from
    the filing's index page (none if it has no Exhibit 13, or no index)."""
    folder = str(url).rsplit("/", 1)[0]
    number = folder.rsplit("/", 1)[1]                  # the accession number, without its dashes
    index_url = "%s/%s-%s-%s-index.htm" % (folder, number[:10], number[10:12], number[12:])
    try:
        index = lisp_http.as_text(sec_download(index_url, credentials_path, FILING_CACHE_HOURS, who))
    except LispError as e:
        if "HTTP 404" in str(e):
            return []
        raise
    urls = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", index, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        link = re.search(r'href="([^"]+)"', row, re.I)
        if len(cells) >= 4 and link and re.sub(r"<[^>]+>", "", cells[3]).strip().upper().startswith("EX-13"):
            document = link.group(1).split("/")[-1]
            urls.append(folder + "/" + document)
    return urls


def sec_filing_text(credentials_path, url, *options):
    """(sec-filing-text creds url [:section s]) -- the words of a filing, as
    plain text, a line for each paragraph: the document at url (a url from
    sec-filings). With :section, just one section of a 10-K or 10-Q:
    "risk-factors" (Item 1A) or "management-discussion" (Item 7 of a 10-K,
    Item 2 of a 10-Q: management's discussion and analysis). When the item
    only says the section is in the annual report, under a title it quotes,
    the section is read from there: later in the same document, or from the
    annual report filed as Exhibit 13. A filing without that section is an
    error of the kind no-section, which (catch-error ... :only (no-section)
    ...) can catch."""
    who = "sec-filing-text"
    options = keyword_options(options, ["section"], who)
    document = lisp_http.as_text(sec_download(str(url), credentials_path, FILING_CACHE_HOURS, who))
    text = plain_text(document)
    if option(options, "section") is None:
        return LispString(text)
    section = section_text(text, str(options["section"]), who)
    titles = pointed_titles(section, str(options["section"]))
    if titles:
        found = [titled_section(text, titles)]
        for exhibit_url in exhibit_13_urls(credentials_path, url, who):
            exhibit = lisp_http.as_text(sec_download(exhibit_url, credentials_path, FILING_CACHE_HOURS, who))
            found.append(titled_section(plain_text(exhibit), titles))
        longest = max(found, key=len)
        if len(WORD.findall(longest)) >= POINTER_WORDS:       # a section, not a line of a table of contents
            section = longest
    return LispString(section)


# ---------------------------------------------------------------------------
# Tone
# ---------------------------------------------------------------------------

# The word lists read from each file: path -> {measure: set of words}
_word_lists = {}


def word_lists_path(path, who):
    """The word lists file: the one given, or the newest one in the folders
    it's looked for in."""
    if path is not None:
        return os.path.expanduser(str(path))
    found = []
    for folder in WORD_LISTS_FOLDERS:
        found += glob.glob(os.path.join(os.path.expanduser(folder), WORD_LISTS_NAME))
    if not found:
        raise LispError("%s: I need the Loughran-McDonald word lists: download %s (free for research) from %s "
                        "and put it in morris_lisp/data or your Downloads folder, or say where it is with :word-lists"
                        % (who, WORD_LISTS_NAME.replace("*", "1993-2025"), WORD_LISTS_PAGE))
    return max(found)                   # the latest years are named last


def read_word_lists(path, who):
    """The word lists in a Loughran-McDonald file: {measure: set of words}.
    The file has a row for each word; a list's column gives the year the
    word was added to that list (0 if it isn't on it, and less than 0 if it
    was taken off)."""
    if path in _word_lists:
        return _word_lists[path]
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            columns = {name.strip().lower(): name for name in reader.fieldnames or []}
            missing = [column for column in ["word"] + [c.lower() for _, c in TONE_LISTS] if column not in columns]
            if missing:
                raise LispError("%s: %s doesn't look like the Loughran-McDonald word lists: it has no %s column"
                                % (who, path, missing[0]))
            lists = {measure: set() for measure, _ in TONE_LISTS}
            for row in reader:
                word = row[columns["word"]].strip().upper()
                for measure, column in TONE_LISTS:
                    try:
                        on_list = float(row[columns[column.lower()]] or 0) > 0
                    except ValueError:
                        on_list = False
                    if on_list:
                        lists[measure].add(word)
    except OSError as e:
        raise LispError("%s: couldn't read the word lists %s: %s" % (who, path, e))
    _word_lists[path] = lists
    return lists


WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")


def text_tone(text, *options):
    """(text-tone text [:word-lists path]) -- the tone of a text's words, by
    the Loughran-McDonald word lists: a hash table of

      "words"         how many words the text has
      "negative"      the percent of its words that are on the negative list
      "positive"      ... on the positive list (not counting one that comes
                      just after "not", "no", "never", ...)
      "uncertainty"   ... on the uncertainty list ("may", "approximately")
      "litigious"     ... on the litigious list ("lawsuit", "plaintiff")
      "constraining"  ... on the constraining list ("required", "covenant")
      "net-tone"      positive less negative

    :word-lists is the word lists file, if it isn't in morris_lisp/data,
    Downloads, or ~/.cache/morris_lisp/word_lists."""
    who = "text-tone"
    options = keyword_options(options, ["word-lists"], who)
    lists = read_word_lists(word_lists_path(option(options, "word-lists"), who), who)
    words = [word.upper().replace("’", "'") for word in WORD.findall(str(text))]
    counts = {measure: 0 for measure, _ in TONE_LISTS}
    for i, word in enumerate(words):
        for measure, _ in TONE_LISTS:
            if word in lists[measure]:
                if measure == "positive" and NEGATIONS & set(words[max(0, i - NEGATION_WORDS_BEFORE):i]):
                    continue
                counts[measure] += 1

    result = LispHashTable()
    result.table[LispString("words")] = len(words)
    for measure, _ in TONE_LISTS:
        result.table[LispString(measure)] = 100.0 * counts[measure] / len(words) if words else float("nan")
    result.table[LispString("net-tone")] = (result.table[LispString("positive")]
                                            - result.table[LispString("negative")])
    return result


BUILTINS = {
    "sec-filings": sec_filings,
    "sec-filing-text": sec_filing_text,
    "text-tone": text_tone,
}
