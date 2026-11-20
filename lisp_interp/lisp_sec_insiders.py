"""What a company's insiders -- its officers, its directors, and anyone who owns a tenth of it -- have bought and sold
of its shares, from the reports they file with the SEC (Form 4), for the Lisp interpreter.

  (sec-insider-trades creds company [:count n])

An insider must report a trade in the company's shares within two business days, on a Form 4, which the SEC keeps
as XML: who traded, their role, and for each trade its date, its code, the shares, the price, and the shares owned
after. The codes that matter most:

  P   bought in the open market, with their own money -- the trade that says the most
  S   sold in the open market (often under a plan set up in advance, a "10b5-1 plan", which says little)
  A   a grant of shares, as pay                M   an option exercised
  F   shares withheld to pay the tax on a grant G   a gift

So the signal is in the purchases, and in sales that are large and not planned. The company is a ticker or a CIK,
as for sec-filings; it needs the credentials file's "sec_user_agent" entry. Each Form 4 is kept for a week.
"""

import re
import xml.etree.ElementTree as ElementTree

from lisp_core import LispDate, LispError, keyword_options
from lisp_sec import company_cik
from lisp_sec_filings import FILING_CACHE_HOURS, SUBMISSIONS_URL, filing_rows, sec_download, sec_json
from lisp_tables import column_vector, make_table_value
import lisp_http

DEFAULT_COUNT = 40                          # the most recent this many Form 4s, unless :count says
MOST_COUNT = 500
TRANSACTION_CODES = {
    "P": "bought", "S": "sold", "A": "granted", "M": "option exercised", "F": "withheld for taxes", "G": "gift",
    "D": "returned to the company", "C": "converted", "X": "option exercised", "J": "other", "W": "inherited",
    "I": "discretionary", "K": "swap", "L": "small purchase", "V": "reported early", "Z": "trust",
}
COLUMNS = ["filing-date", "date", "insider", "role", "code", "what", "shares", "price", "value", "owned-after",
           "planned", "url"]


def text_of(element, path):
    """The text at a path in a Form 4 (most values are in a <value> under the field), or None."""
    if element is None:
        return None
    found = element.find(path)
    if found is not None and found.find("value") is not None:
        found = found.find("value")
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def number_of(element, path):
    text = text_of(element, path)
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def role_of(document):
    """The insider's role: their title if an officer, or director, or ten-percent owner."""
    roles = []
    for owner in document.findall("reportingOwner"):
        relationship = owner.find("reportingOwnerRelationship")
        if relationship is None:
            continue
        if (text_of(relationship, "isOfficer") or "").lower() in ("true", "1"):
            roles.append(text_of(relationship, "officerTitle") or "officer")
        if (text_of(relationship, "isDirector") or "").lower() in ("true", "1"):
            roles.append("director")
        if (text_of(relationship, "isTenPercentOwner") or "").lower() in ("true", "1"):
            roles.append("ten-percent owner")
    return " ".join(", ".join(dict.fromkeys(roles)).split()) or "other"


def form4_trades(xml_text, filing):
    """The trades of one Form 4 (its table of shares, not of options): a dict of the COLUMNS for each."""
    try:
        document = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    insider = "; ".join(text_of(owner, "reportingOwnerId/rptOwnerName") or "" for owner in document.findall("reportingOwner"))
    role = role_of(document)
    planned = (text_of(document, "aff10b5One") or "").lower() in ("true", "1")
    trades = []
    for trade in document.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = text_of(trade, "transactionCoding/transactionCode")
        shares = number_of(trade, "transactionAmounts/transactionShares")
        if shares is not None and text_of(trade, "transactionAmounts/transactionAcquiredDisposedCode") == "D":
            shares = -shares
        price = number_of(trade, "transactionAmounts/transactionPricePerShare")
        date_text = text_of(trade, "transactionDate")
        trades.append({
            "filing-date": filing["filing-date"],
            "date": LispDate(*(int(part) for part in date_text[:10].split("-"))) if date_text else None,
            "insider": insider, "role": role, "code": code, "what": TRANSACTION_CODES.get(code, code),
            "shares": shares, "price": price,
            "value": shares * price if shares is not None and price is not None else None,
            "owned-after": number_of(trade, "postTransactionAmounts/sharesOwnedFollowingTransaction"),
            "planned": planned, "url": filing["url"],
        })
    return trades


def sec_insider_trades(credentials_path, company, *options):
    """(sec-insider-trades creds company [:count n]) -- what the company's officers, directors, and large owners have
    bought and sold of its shares: a table with a row for each trade of its last :count Form 4s (40, unless you say),
    oldest first, of filing-date, date (of the trade), insider, role (their title, director, ten-percent owner), code
    (P bought in the open market, S sold, A granted, M option exercised, F withheld for taxes, G gift, ...), what (the
    code in words), shares (above 0 acquired, below 0 disposed of), price, value (shares x price), owned-after (the
    shares they own after it), planned (#t if under a plan set up in advance -- a 10b5-1 plan -- which says little about
    what they think), and url (the Form 4). Open-market purchases (code P) say the most."""
    who = "sec-insider-trades"
    options = keyword_options(options, ["count"], who)
    count = options.get("count", DEFAULT_COUNT)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MOST_COUNT:
        raise LispError("%s: :count is a whole number of Form 4s, from 1 to %d" % (who, MOST_COUNT))
    cik = company_cik(credentials_path, company, who)
    answer = sec_json(SUBMISSIONS_URL % cik, credentials_path, who)
    filings = [row for row in filing_rows(cik, answer["filings"]["recent"]) if row["form"] == "4"]
    filings.sort(key=lambda row: (row["filing-date"], row["accession"]))
    trades = []
    for filing in filings[-count:]:
        # (the list gives the Form 4 as the SEC shows it, through a style sheet: xslF345X06/form4.xml; the XML itself is
        # the same file without that folder)
        url = re.sub(r"/xslF345X\d+/", "/", filing["url"])
        xml_text = lisp_http.as_text(sec_download(url, credentials_path, FILING_CACHE_HOURS, who))
        trades += form4_trades(xml_text, dict(filing, url=url))
    trades.sort(key=lambda trade: (trade["filing-date"], str(trade["date"])))
    return make_table_value([(name, column_vector([trade[name] for trade in trades])) for name in COLUMNS])


BUILTINS = {
    "sec-insider-trades": sec_insider_trades,
}
