"""The documents' own examples: every `expr ; => value` in lisp_interpreter_reference.md (the
language), lisp_library_reference.md (the library), and lisp_example_programs.md (the example
programs) must still be what the interpreter gives; and every link between and within them must
go somewhere. support.py says how to run them."""

import importlib.util
import math

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


#
# Every fenced ```lisp block of the documents is run (but for those that need
# what the tests don't have, see _has_risky_word, and those that a document
# marks, see _blocks_marked_not_run), and each top-level form
# written as   (expr)   ; => value   must print as `value`. That keeps the
# documentation honest: if a builtin's behavior changes, this fails until the
# doc (or the interpreter) is fixed. The blocks of a section (a ## or ###
# heading) run one after another in one environment, so a block can use what
# an earlier one defined. A form that is an error fails the test, unless the
# document says it is one (its comment begins "an error" or "raises"), or it
# uses a name that a block of the document defines that is not run with it
# (one in another section, or one that is skipped): then the rest of its
# block is not run either.

# blocks that would block on stdin, need the network/GUI, or touch the disk: a block that has one of these at the start of a word
# (see _has_risky_word) is not run
_RISKY_BLOCK_WORDS = (
    "(breakpoint)", "(breakpoint (", '(breakpoint "', "(abort", "debug-repl",
    "fred-table", "tastytrade", "schwab-", "treasury-par-curve", "gsw-curve", "tips-curve", "google-", "three-statement-model", "sensitivity-workbook", "compare-companies", "alpha-vantage-", "text-tone", "filing-tone", "sofr-", "(sec-", "(fdic-", "(census-", "(bls-", "(bea-", "(sleep", "redirect-output", "sqlite-open", "with-sqlite", "lp-read-file",
    "save-chart", "load-csv", "write-columns-csv", "write-text-file", "display-widget", "(deal-tree ",
    "input", "(read-line", "exit", "load-init", "http-get", "http-clear-cache",
    "dynare-run", "oil-model", "oil-shock-responses", "plot-oil-shock", "show-oil-estimates",     # these need Octave and Dynare
    "crash-model", "stock-crash-responses", "plot-stock-crash", "show-crash-estimates",
    "wealth-by-type", "types-model", "types-crash-", "plot-types-crash", "wealth-tax-responses", "plot-wealth-tax", "compare-wealth-taxes",
    "fit-baseball-model", "baseball-backtest", "baseball-team-in-", "ai-bust", "compare-ai-busts", "plot-ai-bust", "ai-investment-data", "vendor-financing",
)


# A block that loads a file is skipped (it might read anything) -- except in the example programs
# document, for these programs, which load quickly and print nothing a block depends on.
_LOADABLE_IN_EXAMPLES_DOC = {
    "parser.lsp", "chess.lsp", "sql.lsp", "column_engine.lsp", "eliza_example.lsp",
    "symbolic_algebra_example.lsp", "nlp_parsing_example.lsp", "unification_grammar_example.lsp",
    "othello_example.lsp",
}


def _blocks_marked_not_run(text):
    """The ```lisp blocks of a document's text that it marks as not to be run by the tests, with an HTML comment on the line before
    them, which a reader does not see: <!-- not run by the tests: it takes 40 seconds -->."""
    return set(re.findall(r"<!-- not run by the tests[^>]*-->\s*\n```lisp\n(.*?)```", text, re.S))


def _has_risky_word(block):
    """Whether the block has one of _RISKY_BLOCK_WORDS at the start of a word: exit is in (exit), but not in convexity."""
    return any(re.search(r"(?<![\w-])" + re.escape(word), block) for word in _RISKY_BLOCK_WORDS)


def _loads_something_unsafe(doc, block):
    """Whether the block loads a file that a block in this document isn't allowed to. A block that calls file-to-notebook, set-slide-types or
    notebook-to-slides is never run: it writes a notebook (and file-to-notebook, without a path, opens a file dialog)."""
    if any(call in block for call in ("(file-to-notebook", "(set-slide-types", "(notebook-to-slides")):
        return True
    loaded = re.findall(r'\(load "([^"]*)"\)', block)
    if "(load " in block and not loaded:
        return True                                 # a load whose file isn't written out
    if doc == os.path.basename(EXAMPLES_DOC):
        return any(name not in _LOADABLE_IN_EXAMPLES_DOC for name in loaded)
    return bool(loaded)


# examples whose documented value is illustrative rather than exact
_ILLUSTRATIVE_PREFIXES = ("e.g.", "one of", "some", "a ", "an ", "somewhere", "error", "raises",
                          "Lisp", "prints", "(same", "same")


# examples that depend on global counters / what else has been defined
_SKIPPED_FORMS = ("(gensym", "(defined-functions)", "(bound-variables)", "(defined-macros)")

# how a document says that a form is an error: its comment, or what follows its ; =>, begins with one of these
_ERROR_WORDS = ("an error", "error", "raises")


def _says_error(documented, comment):
    """Whether the document says that the form is an error: what follows its ; =>, or else its comment, begins with an error or raises."""
    said = documented if documented is not None else comment
    return said is not None and said.lower().startswith(_ERROR_WORDS)


def _definitions(code):
    """The names that some code defines (with define, defmacro, defgeneric, defmethod or defstruct), and the names of its structs, whose
    functions (make-point, point-x, point?) are defined too."""
    names = set(re.findall(r"\((?:define|defmacro|defgeneric|defmethod)\s+\(?([^\s()]+)", code))
    structs = set(re.findall(r"\(defstruct\s+\(?([^\s()]+)", code))
    return names | structs, structs


def _names_defined_in(text):
    """The names that the ```lisp blocks of a document's text define, and its structs (see _definitions)."""
    return _definitions("\n".join(re.findall(r"```lisp\n(.*?)```", text, re.S)))


_SYMBOL_EDGE = r"[\w\-?!*<>=/+.%]"         # a character that a symbol can have, so that one next to a name makes it part of a longer one


def _uses_name(block, name):
    """Whether the block has the name as a symbol of its own, not as a part of a longer one."""
    return re.search(r"(?<!%s)%s(?!%s)" % (_SYMBOL_EDGE, re.escape(name), _SYMBOL_EDGE), block) is not None


def _blocks_not_run(doc, sections):
    """The numbers of the blocks of a document (the (section, block) pairs of _blocks_by_section) that are not run: those with a risky word
    or an unsafe load."""
    return {number for number, (_, block) in enumerate(sections) if _has_risky_word(block) or _loads_something_unsafe(doc, block)}


def _names_only_not_run(sections, not_run):
    """The names that only blocks that are not run define: a block that uses one, and fails, fails for want of what those blocks need (the
    network, a file, a window), not because the document is wrong."""
    run_names = set().union(*[_definitions(block)[0] for number, (_, block) in enumerate(sections) if number not in not_run])
    return set().union(*[_definitions(block)[0] for number, (_, block) in enumerate(sections) if number in not_run]) - run_names


def _defined_in_document(name, names, structs):
    """Whether the name is one that a block of the document defines: a function or variable, or a function of one of its structs."""
    return name in names or any(name in ("make-" + struct, "copy-" + struct, struct + "?") or name.startswith(struct + "-")
                                for struct in structs)


def _split_doc_forms(block):
    """Yield (form_text, expected_or_None, comment_or_None) for each top-level
    form in a doc code block; `expected` is the text after a trailing `; =>`
    comment, and `comment` the whole of a comment after it on its line."""
    i, n = 0, len(block)
    while i < n:
        c = block[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == ";":
            j = block.find("\n", i)
            i = n if j < 0 else j
            continue
        start, depth, in_str = i, 0, False
        while i < n:
            c = block[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == ";":
                    j = block.find("\n", i)
                    i = n if j < 0 else j
                    continue
                elif c in "([":
                    depth += 1
                elif c in ")]":
                    depth -= 1
                elif depth == 0 and c in " \t\r\n":
                    break
                if depth == 0 and c in ")]":
                    i += 1
                    break
            i += 1
        eol = block.find("\n", i)
        eol = n if eol < 0 else eol
        m = re.match(r"\s*;\s*=>\s*(.*)$", block[i:eol])
        comment = re.match(r"\s*;+\s*(.*)$", block[i:eol])
        if not comment:                     # (or a line of comment of its own, right under the form)
            next_eol = block.find("\n", eol + 1)
            comment = re.match(r"\s*;+\s*(.*)$", block[eol + 1:n if next_eol < 0 else next_eol])
        yield block[start:i], (m.group(1).strip() if m else None), (comment.group(1).strip() if comment else None)


def _blocks_by_section(text):
    """(section number, block) for each ```lisp block of a document: sections begin at each ## or ### heading.
    In the document of example programs, a section loads a program once, and its blocks use it in turn."""
    section, in_code, block, found = 0, False, [], []
    for line in text.split("\n"):
        if not in_code and re.match(r"#{2,3} ", line):
            section += 1
        if line.startswith("```"):
            if in_code and block is not None:
                if block and block[0] == "lisp":
                    found.append((section, "\n".join(block[1:]) + "\n"))
                block = []
            else:
                block = [line[3:].strip()]
            in_code = not in_code
        elif in_code:
            block.append(line)
    return found


_DECIMAL = re.compile(r"-?\d+\.\d+(?:e[-+]?\d+)?")


def _same_up_to_digits(actual, documented):
    """Whether two printed values are the same but for the last digits of their decimal numbers: the manual shows 0.96116877
    where the interpreter, in double precision, prints 0.9611687812379853. Everything else (the whole numbers, the strings, the
    shape) has to be the same, and each decimal is to within 1 part in 100,000."""
    a, b = _DECIMAL.findall(actual), _DECIMAL.findall(documented)
    if not a or len(a) != len(b) or _DECIMAL.sub("#", actual) != _DECIMAL.sub("#", documented):
        return False
    return all(math.isclose(float(x), float(y), rel_tol=1e-5, abs_tol=1e-9) for x, y in zip(a, b))


def _doc_value_matches(actual, documented):
    """Exact, or exact followed by explanatory prose ('3  -- because ...'), or the same to the digits shown."""
    if documented == actual:
        return True
    if documented.startswith(actual) and documented[len(actual):len(actual) + 1] in (" ", ",", "\t"):
        return True
    return _same_up_to_digits(actual, documented)


def _fresh_env():
    """A new environment, with the libraries' functions callable (init.lsp's autoloads), as at the console: an
    example that calls one is run, not skipped as using a name that isn't there."""
    env = lisp_builtins.make_global_env(output=lambda s: None)
    lisp_core.run_file(os.path.join(LIB, "autoloads.lsp"), env)
    return env


class TestReferenceDocExamples(unittest.TestCase):

    MIN_VERIFIED = 150          # guard: the checker must not silently verify nothing

    def test_every_documented_result_is_what_the_interpreter_returns(self):
        self.addCleanup(lisp_core.set_verbose_level, 0)     # some doc examples turn tracing on
        self.addCleanup(lisp_core.debug_state.reset)        # ...and set breakpoints and hooks
        # An example that stops the program and opens the debug REPL would wait
        # for the keyboard. Make that a failure instead.
        patcher = mock.patch("builtins.input", side_effect=AssertionError(
            "a doc example opened the debug REPL"))
        patcher.start()
        self.addCleanup(patcher.stop)
        blocks = []                 # (the document's name, the block, the section whose environment it runs in)
        defined = {}                # the document's name -> the names its blocks define, and its structs (see _names_defined_in)
        needs_not_run = {}          # the document's name -> the names that only its blocks that are not run define
        for doc, fewest in ((REFERENCE_DOC, 50), (LIBRARY_DOC, 50), (EXAMPLES_DOC, 10), (CMO_DOC, 5), (FORECASTING_DOC, 5), (PATHS_DOC, 5),
                            (MACRO_DOC, 5), (REGRESSION_DOC, 10), (BASEBALL_DOC, 5)):
            with open(doc, encoding="utf-8") as f:
                text = f.read()
            name = os.path.basename(doc)
            sections = _blocks_by_section(text)
            self.assertGreater(len(sections), fewest, "found few lisp code blocks in " + name)
            not_run = _blocks_not_run(name, sections) | {number for number, (_, block) in enumerate(sections)
                                                         if block.rstrip("\n") in {marked.rstrip("\n") for marked in _blocks_marked_not_run(text)}}
            blocks += [(name, block, (name, section)) for number, (section, block) in enumerate(sections) if number not in not_run]
            defined[name] = _names_defined_in(text)
            needs_not_run[name] = _names_only_not_run(sections, not_run)

        use_alarm = hasattr(signal, "SIGALRM")
        verified, failures = 0, []
        # A throwaway working directory: even a doc example that writes a file
        # (a database, a log, a CSV) can then never leave anything behind in
        # the repository.
        scratch = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        os.chdir(scratch)

        def on_alarm(signum, frame):
            raise TimeoutError("doc example ran too long")

        if use_alarm:
            signal.signal(signal.SIGALRM, on_alarm)

        shared_envs = {}            # (document, section) -> the environment its blocks run in, one after another
        for bi, (doc, block, section) in enumerate(blocks):
            if doc == os.path.basename(EXAMPLES_DOC) and "; =>" not in block and "(load " not in block:
                continue                    # an excerpt from a program, shown for reading, not for running
            if section not in shared_envs:
                shared_envs[section] = _fresh_env()
            env = shared_envs[section]
            lisp_core.debug_state.reset()       # breakpoints belong to the whole process, not one block
            if use_alarm:
                signal.alarm(20)
            try:
                for text, documented, comment in _split_doc_forms(block):
                    where = "%s, block %d: %s" % (doc, bi, text.replace("\n", " ")[:80])
                    expects_error = _says_error(documented, comment)
                    try:
                        value = lisp_core.NIL
                        for expr in lisp_core.parse(text):
                            value = lisp_core.seval(expr, env)
                    except TimeoutError:
                        raise
                    except Exception as e:
                        if expects_error:
                            continue                # (the document says that it is an error)
                        unbound = re.match(r"unbound symbol: (\S+)", str(e))
                        set_up_elsewhere = unbound and _defined_in_document(unbound.group(1), *defined[doc])
                        needs_what_is_not_run = any(_uses_name(block, name) for name in needs_not_run[doc])
                        if not (set_up_elsewhere or needs_what_is_not_run):
                            failures.append("%s  raised %s: %s" % (where, type(e).__name__, e))
                        break                       # (the rest of the block depends on it; an unbound name that the document defines
                                                    # is set up by a block that is not run with this one, and a block that uses what only
                                                    # blocks that are not run make cannot be run either)
                    if expects_error and documented is None:
                        failures.append("%s  -- the document says it is an error, and it gave %s" % (where, lisp_core.to_string(value)[:80]))
                        continue
                    if documented is None or documented.startswith(_ILLUSTRATIVE_PREFIXES) \
                            or "again" in documented or any(s in text for s in _SKIPPED_FORMS):
                        continue
                    if (_doc_value_matches(lisp_core.to_string(value), documented)
                            or _doc_value_matches(lisp_core.to_display_string(value), documented)):
                        verified += 1
                    else:
                        failures.append("%s\n      doc says: %s\n      got:      %s" % (where, documented, lisp_core.to_string(value)))
            except TimeoutError:
                failures.append("%s, block %d timed out" % (doc, bi))
            finally:
                if use_alarm:
                    signal.alarm(0)

        os.chdir(old_cwd)
        shutil.rmtree(scratch, ignore_errors=True)

        self.assertEqual(failures, [], "documented examples that no longer hold:\n" + "\n".join(failures))
        self.assertGreaterEqual(verified, self.MIN_VERIFIED,
                                "only %d doc examples were verified" % verified)


def _headings_anchors(text):
    """The anchors GitHub gives the headings of a markdown document (the way tools/make_contents.py makes them)."""
    spec = importlib.util.spec_from_file_location("make_contents", os.path.join(HERE, "tools", "make_contents.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    seen, anchors, in_code = {}, set(), False
    for line in text.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
            continue
        heading = None if in_code else re.match(r"#{1,6} (.*)", line)
        if heading:
            anchor = tool.anchor_of(heading.group(1).strip())
            repeats = seen.get(anchor, 0)
            seen[anchor] = repeats + 1
            anchors.add(anchor + ("-%d" % repeats if repeats else ""))
    return anchors


def _links_outside_code(text):
    """The targets of the markdown links [text](target) that aren't in a code block or a code span."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return re.findall(r"\[[^\]\n]*\]\(([^)\s]+)\)", text)


class TestDocumentLinks(unittest.TestCase):
    """The documents link to each other and to sections of themselves, and to the files they describe: all of
    those links must go somewhere, or moving a section would leave readers at a dead end."""

    def test_every_link_goes_to_a_file_and_a_heading_that_exist(self):
        documents = [REFERENCE_DOC, LIBRARY_DOC, EXAMPLES_DOC, CMO_DOC, FORECASTING_DOC, PATHS_DOC, MACRO_DOC, REGRESSION_DOC, BASEBALL_DOC,
                     os.path.join(DOC_DIRECTORY, "economic_data_guide.md"),
                     os.path.join(HERE, "..", "README.md")]
        texts = {}
        for path in documents:
            with open(path, encoding="utf-8") as f:
                texts[os.path.abspath(path)] = f.read()
        anchors = {path: _headings_anchors(text) for path, text in texts.items()}
        broken = []
        for path, text in texts.items():
            for target in _links_outside_code(text):
                if re.match(r"[a-z]+://|mailto:", target):
                    continue
                name, _, anchor = target.partition("#")
                linked = os.path.abspath(os.path.join(os.path.dirname(path), name)) if name else path
                if not os.path.exists(linked):
                    broken.append("%s links to %s, which doesn't exist" % (os.path.basename(path), target))
                elif anchor and linked in anchors and anchor not in anchors[linked]:
                    broken.append("%s links to %s, which has no such heading" % (os.path.basename(path), target))
        self.assertEqual(broken, [], "links that go nowhere:\n" + "\n".join(broken))

    def test_every_example_program_is_described_in_the_document_of_examples(self):
        """A program added to examples/ gets a place in lisp_example_programs.md, or this fails."""
        with open(EXAMPLES_DOC, encoding="utf-8") as f:
            described = f.read()
        missing = [name for name in sorted(os.listdir(EXAMPLES)) if name.endswith(".lsp") and name not in described]
        self.assertEqual(missing, [], "examples that lisp_example_programs.md doesn't mention")

    def test_the_contents_of_each_document_lists_its_headings(self):
        """tools/make_contents.py has been run since the headings last changed."""
        spec = importlib.util.spec_from_file_location("make_contents", os.path.join(HERE, "tools", "make_contents.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        for path in tool.MANUALS:
            with self.subTest(document=os.path.basename(path)):
                with open(path, encoding="utf-8") as f:
                    lines = f.read().split("\n")
                start = lines.index("## Contents")
                end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
                self.assertEqual([line for line in lines[start + 1:end] if line.strip()], tool.contents(lines),
                                 "run python3 tools/make_contents.py")


if __name__ == "__main__":
    unittest.main()
