"""A company's revenue by segment, from the numbers tagged in its 10-Ks and 10-Qs.

lisp_sec.py reads the SEC's "company facts" file, which has each company's totals -- its revenue,
its net income -- but leaves out every number that is for a part of the company: a business
segment, a product, a region. Those are in the filings themselves. Since about 2019 a filing's
main document is "inline XBRL": an ordinary web page whose numbers are tagged as they are
written, as <ix:nonFraction name="us-gaap:Revenues" contextRef="c-17" scale="6">198,083</ix:nonFraction>.
The contextRef names a "context" listed at the top of the page: the period the number is for, and
the "dimensions" it is a part of -- the StatementBusinessSegmentsAxis with the member
AmericasSegmentMember, say. This reads those tags, for the revenue concepts, in the filings that
cover the periods wanted.

The members of an axis can overlap (Apple's ProductOrServiceAxis has Product, Service, and iPhone,
Mac, ... which are parts of Product), so revenue_by_segment picks the largest set of members
that add up to the company's total revenue. Then each member's value for each period is found as
lisp_sec finds a company's -- a fiscal year's from the annual report, a quarter's from its 10-Q or,
for a fourth quarter, the year less the nine months before.

Filings from before inline XBRL have no tagged numbers in the document, so the segments of
earlier years are not found, and revenue_by_segment says so.
"""

import html
import re

import numpy as np

from lisp_core import LispError
import lisp_http
import lisp_sec
import lisp_sec_filings

REVENUE_NAMES = {name.split(":")[-1] for item in lisp_sec.LINE_ITEMS if item[0] == "revenue" for name in item[3]}
MILLION = 1e6
MOST_MEMBERS = 20               # of an axis's members, the largest this many are tried in combination
TOTAL_TOLERANCE = 0.01          # members "add up" to the total if they are within this fraction of it
EARLIER_TOLERANCE = 0.03        # ... and, in the periods before the latest, this fraction (segments get restated)
ROUNDING = 0.5                  # a difference between the members and the total smaller than this (millions) is rounding

# Members that are totals of the others, not segments:
TOTAL_MEMBERS = {"OperatingSegmentsMember", "AllOperatingSegmentsMember", "ReportableSegmentsMember",
                 "SegmentsMember", "AllSegmentsMember", "ConsolidatedMember"}

AXES = {                        # the :segments choices -> the axis, and what else a fact may have
    "business": "StatementBusinessSegmentsAxis",
    "product": "ProductOrServiceAxis",
    "geography": "StatementGeographicalAxis",
}
AUTO_ORDER = ["business", "product"]
# On the business segments axis, a fact is usually also marked as being of the "operating segments":
OTHER_ALLOWED_AXES = {"ConsolidationItemsAxis"}

CONTEXT = re.compile(r"<(?:\w+:)?context\s+id=\"([^\"]+)\"\s*>(.*?)</(?:\w+:)?context>", re.S)
START = re.compile(r"<(?:\w+:)?startDate>\s*([^<\s]+)")
END = re.compile(r"<(?:\w+:)?endDate>\s*([^<\s]+)")
INSTANT = re.compile(r"<(?:\w+:)?instant>\s*([^<\s]+)")
MEMBER = re.compile(r"<(?:\w+:)?explicitMember\s+dimension=\"([^\"]+)\"\s*>\s*([^<\s]+)\s*<")
NON_FRACTION = re.compile(r"<ix:nonFraction\s([^>]*)>(.*?)</ix:nonFraction>", re.S)
ATTRIBUTE = re.compile(r"([\w:.-]+)=\"([^\"]*)\"")
TAGS = re.compile(r"<[^>]+>")

# The tagged revenue numbers of each filing already read: url -> list of
# (concept name, dimensions, start, end, value in dollars).
_filing_numbers = {}


# ---------------------------------------------------------------------------
# Reading a filing
# ---------------------------------------------------------------------------

def contexts_of(document):
    """The contexts at the top of an inline XBRL document: id -> (start, end, dimensions), the
    dimensions a tuple of (axis name, member name) without their prefixes; start is None for a moment."""
    contexts = {}
    for context_id, body in CONTEXT.findall(document):
        start, end, instant = START.search(body), END.search(body), INSTANT.search(body)
        dimensions = tuple((axis.split(":")[-1], member.split(":")[-1]) for axis, member in MEMBER.findall(body))
        if end or instant:
            contexts[context_id] = (start.group(1) if start else None,
                                    end.group(1) if end else instant.group(1), dimensions)
    return contexts


def tagged_number(attributes, text):
    """The value in dollars of an ix:nonFraction tag, or None if it isn't a number."""
    words = html.unescape(TAGS.sub("", text)).replace(",", "").strip()
    try:
        value = float(words)
    except ValueError:
        if words and all(c in "—–-− " for c in words):           # a dash is how a report writes zero
            return 0.0
        return None
    value *= 10 ** int(attributes.get("scale", "0") or 0)
    return -value if attributes.get("sign") == "-" else value


def revenue_numbers(document):
    """Every number tagged as revenue in an inline XBRL document, as (concept, dimensions, start, end, value)."""
    contexts = contexts_of(document)
    numbers = []
    for attribute_text, text in NON_FRACTION.findall(document):
        attributes = dict(ATTRIBUTE.findall(attribute_text))
        concept = attributes.get("name", "").split(":")[-1]
        if concept not in REVENUE_NAMES or attributes.get("contextRef") not in contexts:
            continue
        value = tagged_number(attributes, text)
        if value is not None:
            start, end, dimensions = contexts[attributes["contextRef"]]
            numbers.append((concept, dimensions, start, end, value))
    return numbers


def numbers_in_filing(credentials_path, url, who):
    """The revenue numbers in the filing at this address (kept, once read)."""
    if url not in _filing_numbers:
        document = lisp_http.as_text(
            lisp_sec_filings.sec_download(url, credentials_path, lisp_sec_filings.FILING_CACHE_HOURS, who))
        _filing_numbers[url] = revenue_numbers(document)
    return _filing_numbers[url]


# ---------------------------------------------------------------------------
# The filings to read
# ---------------------------------------------------------------------------

def filings_to_read(credentials_path, cik, periods, quarterly, who):
    """The 10-Ks (and, for quarters, 10-Qs) that report on the periods: a list of
    (report date, form, filing date, url), newest first."""
    answer = lisp_sec_filings.sec_json(lisp_sec_filings.SUBMISSIONS_URL % cik, credentials_path, who)
    rows = lisp_sec_filings.filing_rows(cik, answer["filings"]["recent"])
    forms = {"10-K", "10-Q"} if quarterly else {"10-K"}
    earliest = min(p.year_start for p in periods).isoformat() if quarterly else \
        min(p.end for p in periods).isoformat()
    wanted = [row for row in rows if row["form"] in forms and row["report-date"] and row["report-date"] >= earliest]
    wanted.sort(key=lambda row: row["report-date"], reverse=True)
    return [(row["report-date"], row["form"], row["filing-date"], row["url"]) for row in wanted]


# ---------------------------------------------------------------------------
# Members, and the set that adds up to the revenue
# ---------------------------------------------------------------------------

def member_name(member):
    """A readable name for a member such as 'RestOfAsiaPacificSegmentMember'."""
    name = re.sub(r"(Segment)?Member$", "", member)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip() or member


def axis_facts(numbers_by_filing, axis):
    """For one axis, the facts of its members, in the form of the SEC's company facts file: a dict of
    member name -> list of facts ({"start", "end", "val", "filed", "accn"}), the fact's dimensions
    being the axis with a member -- and, perhaps, a ConsolidationItemsAxis marker -- and no other."""
    members = {}
    for (report_date, form, filed, url), numbers in numbers_by_filing:
        for concept, dimensions, start, end, value in numbers:
            if start is None:
                continue
            axes = {axis_name: member for axis_name, member in dimensions}
            if axis in axes:
                if any(a != axis and a not in OTHER_ALLOWED_AXES for a in axes):
                    continue
                member = axes[axis]
            elif axis == AXES["business"] and set(axes) == {"ConsolidationItemsAxis"}:
                member = axes["ConsolidationItemsAxis"]         # corporate, or the eliminations between segments
            else:
                continue
            members.setdefault(member, []).append({"start": start, "end": end, "val": value / MILLION,
                                                   "filed": filed, "accn": url})
    return members


def members_to_company_facts(members):
    """The members as a lisp_sec company-facts dict, so that lisp_sec can find each period's value."""
    return {"facts": {"segments": {name: {"units": {"USD": facts}} for name, facts in members.items()}}}


def best_combination(values, total, earlier_values=None, earlier_totals=None):
    """Which of the members' values (a list of numbers) add up to `total` (within TOTAL_TOLERANCE of it)
    using the most members; a list of the members' indexes, or None. (The parts of a member -- iPhone,
    which is part of Product -- are also members, so not all of them can be used together.)

    The same members must add up in the earlier periods too, or sets that happen to add up in the latest
    period would do (Berkshire Hathaway's 'Insurance and other' contains its insurance group, so the two
    together count the insurance twice, and leave out McLane, which makes up for it in one year only).
    `earlier_values` has, for each member, its values in the earlier periods (None where it has none; such
    a member cannot be used), and `earlier_totals` the total of each of those periods; the members must add up
    to within EARLIER_TOLERANCE of each of them."""
    order = sorted(range(len(values)), key=lambda i: -abs(values[i]))[:MOST_MEMBERS]
    earlier_values = earlier_values or [[] for _ in values]
    earlier_totals = list(earlier_totals or [])
    totals = np.array([total] + earlier_totals, dtype=float)
    tolerances = np.array([TOTAL_TOLERANCE] + [EARLIER_TOLERANCE] * len(earlier_totals))
    sums, counts = np.zeros((1, len(totals))), np.zeros(1, dtype=int)
    for index in order:
        member = np.array([values[index]] + [np.nan if v is None else v for v in earlier_values[index]], dtype=float)
        sums, counts = np.concatenate([sums, sums + member]), np.concatenate([counts, counts + 1])
    misses = np.abs(sums - totals)                      # (a missing value is nan: never close)
    close = (misses <= tolerances * np.abs(totals)).all(axis=1)
    close[0] = False                                    # (using none of them isn't an answer)
    if not close.any():
        return None
    # Sets that add up exactly (apart from rounding) are preferred to sets that are only close, which may add
    # up by accident, as a member and its own parts do (Berkshire's Insurance and Other, with some of its parts,
    # came to its revenue less a few hundred million, and the railroad and utilities was left out).
    exact = close & (misses <= ROUNDING * np.maximum(counts, 1)[:, None]).all(axis=1)
    if exact.any():
        close = exact
    best_count = counts[close].max()
    candidates = np.where(close & (counts == best_count))[0]
    chosen = candidates[np.argmin(np.abs(sums[candidates, 0] - total))]
    return sorted(order[bit] for bit in range(len(order)) if chosen >> bit & 1)


def segments_on_axis(numbers_by_filing, axis, periods, totals):
    """The segments on one axis, as [(name, a value for each period)] -- the members that add up to the
    revenue, and an 'Other revenue' for what they don't -- or the reason there are none: (segments, reason)."""
    members = axis_facts(numbers_by_filing, axis)
    if not members:
        return None, "the filings tag no revenue by %s" % axis
    company_facts = members_to_company_facts(members)
    names = sorted(name for name in members if name not in TOTAL_MEMBERS)
    values = {name: [lisp_sec.flow_value(lisp_sec.ConceptFacts(company_facts, "segments:" + name), p) for p in periods]
              for name in names}
    latest = [name for name in names if values[name][-1] is not None and abs(values[name][-1]) >= ROUNDING]
    if len(latest) < 2:
        return None, "the filings have fewer than two %s for the latest period" % axis
    latest_values = [values[name][-1] for name in latest]
    chosen = best_combination(latest_values, totals[-1], [values[name][:-1] for name in latest], totals[:-1])
    if chosen is None:
        alone = best_combination(latest_values, totals[-1])
        if alone is None:
            return None, "no %s add up to the company's revenue" % axis
        for index in alone:
            if any(v is None for v in values[latest[index]]):
                return None, "%s %s has no number for every period" % (axis, member_name(latest[index]))
        return None, ("no %s add up to the company's revenue in every period (the segments are not the same "
                      "from year to year)" % axis)
    segments = [(member_name(latest[index]), values[latest[index]]) for index in chosen]
    other = [total - sum(values_[i] for _, values_ in segments) for i, total in enumerate(totals)]
    if any(abs(x) >= ROUNDING for x in other):
        segments.append(("Other revenue", other))
    segments.sort(key=lambda segment: -segment[1][-1] if segment[0] != "Other revenue" else float("inf"))
    return segments, None


def revenue_by_segment(credentials_path, company, periods, totals, kind, who):
    """The company's revenue by segment for each period (oldest first), from the filings: a tuple
    (segments, description) -- segments being [(name, a value in millions for each period)] -- or
    (None, the reason there are none). `totals` is the company's total revenue for each period, in
    millions, and `kind` "auto" (business segments, if the company has them, then products), or one of
    "business", "product", "geography"."""
    kinds = AUTO_ORDER if kind == "auto" else [kind]
    if any(k not in AXES for k in kinds):
        raise LispError('%s: :segments is "auto", "business", "product", "geography", or #f, not %s' % (who, kind))
    quarterly = periods[0].fiscal_period != "FY"
    cik = lisp_sec.company_cik(credentials_path, company, who)
    filings = filings_to_read(credentials_path, cik, periods, quarterly, who)
    if not filings:
        return None, "the SEC has no 10-K filings for these periods"
    numbers_by_filing = []
    for filing in filings:
        try:
            numbers_by_filing.append((filing, numbers_in_filing(credentials_path, filing[3], who)))
        except LispError:
            continue                                    # (a filing that can't be read is left out)
        if not quarterly and covers_all(numbers_by_filing, periods):
            break
    reasons = []
    for k in kinds:
        segments, reason = segments_on_axis(numbers_by_filing, AXES[k], periods, totals)
        if segments:
            return segments, "%s (%s)" % (AXES[k], ", ".join(name for name, _ in segments))
        reasons.append(reason)
    return None, "; ".join(reasons)


def covers_all(numbers_by_filing, periods):
    """Whether the numbers read so far include a number tagged with a dimension for every period's end."""
    ends = {end for _, numbers in numbers_by_filing for _, dimensions, start, end, _ in numbers
            if dimensions and start is not None}
    return all(p.end.isoformat() in ends for p in periods)
