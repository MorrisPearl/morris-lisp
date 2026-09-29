"""Regular expressions for the Lisp interpreter: a thin layer over Python's re
module (https://docs.python.org/3/library/re.html), so the patterns are
Python's.

  (regex-search pattern s)            the first match anywhere in s
  (regex-match pattern s)             a match of the whole of s
  (regex-find-all pattern s)          every match
  (regex-replace pattern s new [n])   s with matches replaced
  (regex-split pattern s)             s split where the pattern matches
  (regex-quote s)                     s with its special characters escaped

A match is a list: the text that matched, then the text of each group in
the pattern ('() for a group that took no part): (regex-search "(\\d+)-(\\d+)"
"pages 12-34") is ("12-34" "12" "34"). No match is #f.

Flags go in the pattern itself, as Python allows: "(?i)" at the start makes
it ignore case, "(?m)" makes ^ and $ match at each line.
"""

import re

from lisp_core import LispError, LispString, NIL, apply_proc, list_to_pairs, to_display_string


def compiled(pattern, who):
    """The pattern, compiled -- Python keeps the ones used recently, so this
    is quick when the same pattern is used again."""
    try:
        return re.compile(str(pattern))
    except re.error as e:
        raise LispError("%s: %s isn't a valid regular expression: %s" % (who, _quoted(pattern), e))


def _quoted(text):
    return '"%s"' % text


def match_list(m):
    """A match as a Lisp list: the matched text, then each group's text
    ('() for a group that took no part)."""
    return list_to_pairs([LispString(m.group(0))] + [NIL if g is None else LispString(g) for g in m.groups()])


def regex_search(pattern, s):
    """(regex-search pattern s) -- the first match of pattern anywhere in s,
    as a list of the matched text and each group's text, or #f."""
    m = compiled(pattern, "regex-search").search(str(s))
    return match_list(m) if m else False


def regex_match(pattern, s):
    """(regex-match pattern s) -- a match of pattern against the whole of s
    (as regex-search gives it), or #f."""
    m = compiled(pattern, "regex-match").fullmatch(str(s))
    return match_list(m) if m else False


def regex_find_all(pattern, s):
    """(regex-find-all pattern s) -- every match of pattern in s, as a list,
    as Python's findall gives them: with no groups in the pattern, the
    matched texts; with one group, that group's texts; with several, a list
    of the groups' texts for each match."""
    def as_lisp(found):
        if isinstance(found, tuple):
            return list_to_pairs([LispString(g) for g in found])
        return LispString(found)
    return list_to_pairs([as_lisp(found) for found in compiled(pattern, "regex-find-all").findall(str(s))])


def regex_replace(pattern, s, replacement, count=0):
    """(regex-replace pattern s replacement [count]) -- s with each match of
    pattern replaced (only the first `count`, if given). The replacement is a
    string, where \\1 or \\g<1> stands for what group 1 matched; or a
    procedure, which is given the match (as regex-search gives it) and
    returns the text to put in its place."""
    regex = compiled(pattern, "regex-replace")
    if not isinstance(replacement, str):
        def replace(m):
            return str(to_display_string(apply_proc(replacement, [match_list(m)])))
        return LispString(regex.sub(replace, str(s), count=int(count)))
    try:
        return LispString(regex.sub(str(replacement), str(s), count=int(count)))
    except re.error as e:
        raise LispError("regex-replace: the replacement %s isn't valid: %s" % (_quoted(replacement), e))


def regex_split(pattern, s):
    """(regex-split pattern s) -- the pieces of s between matches of
    pattern, as a list of strings. (A group in the pattern also puts what it
    matched in the list, as Python's split does.)"""
    pieces = compiled(pattern, "regex-split").split(str(s))
    return list_to_pairs([NIL if p is None else LispString(p) for p in pieces])


def regex_quote(s):
    """(regex-quote s) -- s with every character that's special in a pattern
    escaped, so that the pattern matches s exactly."""
    return LispString(re.escape(str(s)))


BUILTINS = {
    "regex-search": regex_search,
    "regex-match": regex_match,
    "regex-find-all": regex_find_all,
    "regex-replace": regex_replace,
    "regex-split": regex_split,
    "regex-quote": regex_quote,
}
