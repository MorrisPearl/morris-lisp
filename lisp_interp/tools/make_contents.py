"""Rebuild the "## Contents" list at the top of lisp_interpreter_reference.md
from its headings: every ## and ### heading, plus each form's short ####
heading in "Special forms and standard macros". The links are to GitHub's
anchors for the headings. Run it after adding or renaming a section:

    python3 tools/make_contents.py
"""

import os
import re

MANUAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lisp_interpreter_reference.md")


def anchor_of(title):
    """GitHub's anchor for a heading: lower case, punctuation dropped,
    spaces as hyphens."""
    return re.sub(r"[^\w\s-]", "", title.lower()).replace(" ", "-")


def contents(lines):
    """The contents list's lines, from the manual's lines."""
    times_seen = {}             # anchor -> how many headings have had it (GitHub numbers the repeats)
    entries = []
    in_code = False             # inside a ``` block, where a # isn't a heading
    in_forms = False            # in "Special forms and standard macros"
    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_code = not in_code
            continue
        heading = None if in_code else re.match(r"(#{1,6}) (.*)", line)
        if not heading:
            continue
        level, title = len(heading.group(1)), heading.group(2).strip()
        anchor = anchor_of(title)
        repeats = times_seen.get(anchor, 0)
        times_seen[anchor] = repeats + 1
        if repeats:
            anchor += "-%d" % repeats
        if level == 2:
            in_forms = title == "Special forms and standard macros"
        if title == "Contents":
            continue
        # A form's heading is short ("#### define"), followed by its signature ("#### `(define ...)`").
        is_form = level == 4 and i + 1 < len(lines) and lines[i + 1].startswith("#### `")
        if level in (2, 3) or (in_forms and is_form):
            entries.append("%s- [%s](#%s)" % ("  " * (level - 2), title, anchor))
    return entries


def main():
    with open(MANUAL) as f:
        lines = f.read().split("\n")
    start, end = lines.index("## Contents"), lines.index("## Running it")
    lines[start:end] = ["## Contents", ""] + contents(lines) + [""]
    with open(MANUAL, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
