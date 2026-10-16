"""The documents' own examples: every `expr ; => value` in lisp_interpreter_reference.md (the
language), lisp_library_reference.md (the library), and lisp_example_programs.md (the example
programs) must still be what the interpreter gives; and every link between and within them must
go somewhere. support.py says how to run them."""

import importlib.util

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


#
# Every fenced ```lisp block in lisp_interpreter_reference.md is run, and each
# top-level form written as   (expr)   ; => value   must print as `value`.
# That keeps the documentation honest: if a builtin's behavior changes, this
# fails until the doc (or the interpreter) is fixed.

# blocks that would block on stdin, need the network/GUI, or touch the disk
_RISKY_BLOCK_WORDS = (
    "(breakpoint)", "(breakpoint (", '(breakpoint "', "(abort", "debug-repl",
    "fred-table", "tastytrade", "schwab-", "treasury-par-curve", "gsw-curve", "google-", "alpha-vantage-", "sofr-", "(sec-", "(fdic-", "(census-", "(bls-", "(bea-", "(sleep", "redirect-output", "sqlite-open", "with-sqlite", "lp-read-file",
    "save-chart", "load-csv", "write-columns-csv",
    "input", "(read-line", "exit", "load-init", "http-get", "http-clear-cache",
)


# A block that loads a file is skipped (it might read anything) -- except in the example programs
# document, for these programs, which load quickly and print nothing a block depends on.
_LOADABLE_IN_EXAMPLES_DOC = {
    "parser.lsp", "chess.lsp", "sql.lsp", "column_engine.lsp", "eliza_example.lsp",
    "symbolic_algebra_example.lsp", "nlp_parsing_example.lsp", "unification_grammar_example.lsp",
    "othello_example.lsp",
}


def _loads_something_unsafe(doc, block):
    """Whether the block loads a file that a block in this document isn't allowed to."""
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
_SKIPPED_FORMS = ("(gensym", "(defined-functions)", "(bound-variables)")


def _split_doc_forms(block):
    """Yield (form_text, expected_or_None) for each top-level form in a doc
    code block; `expected` is the text after a trailing `; =>` comment."""
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
        yield block[start:i], (m.group(1).strip() if m else None)


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


def _doc_value_matches(actual, documented):
    """Exact, or exact followed by explanatory prose ('3  -- because ...')."""
    if documented == actual:
        return True
    return documented.startswith(actual) and documented[len(actual):len(actual) + 1] in (" ", ",", "\t")


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
        blocks = []                 # (the document's name, the block, its section if blocks share an environment)
        for doc, fewest in ((REFERENCE_DOC, 50), (LIBRARY_DOC, 50), (EXAMPLES_DOC, 10)):
            with open(doc, encoding="utf-8") as f:
                text = f.read()
            found = re.findall(r"```lisp\n(.*?)```", text, re.S)
            self.assertGreater(len(found), fewest, "found few lisp code blocks in " + os.path.basename(doc))
            if doc == EXAMPLES_DOC:
                blocks += [(os.path.basename(doc), block, section) for section, block in _blocks_by_section(text)]
            else:
                blocks += [(os.path.basename(doc), block, None) for block in found]

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

        shared_envs = {}            # section -> the environment its blocks run in, one after another
        for bi, (doc, block, section) in enumerate(blocks):
            if any(word in block for word in _RISKY_BLOCK_WORDS) or _loads_something_unsafe(doc, block):
                continue
            if section is not None and "; =>" not in block and "(load " not in block:
                continue                    # an excerpt from a program, shown for reading, not for running
            if section is None:
                env = _fresh_env()
            else:
                if section not in shared_envs:
                    shared_envs[section] = _fresh_env()
                env = shared_envs[section]
            lisp_core.debug_state.reset()       # breakpoints belong to the whole process, not one block
            if use_alarm:
                signal.alarm(20)
            try:
                for text, documented in _split_doc_forms(block):
                    try:
                        exprs = lisp_core.parse(text)
                    except lisp_core.LispError:
                        break
                    stop = False
                    for expr in exprs:
                        try:
                            value = lisp_core.seval(expr, env)
                        except TimeoutError:
                            raise
                        except Exception as e:
                            # an example whose setup lives in an earlier block, or one
                            # that documents an error, has nothing to compare here
                            if documented is not None and ("unbound symbol" not in str(e) or section is not None):
                                failures.append("%s, block %d: %s  raised %s: %s"
                                                % (doc, bi, text.replace("\n", " ")[:80], type(e).__name__, e))
                            stop = True
                            break
                        if documented is None or documented.startswith(_ILLUSTRATIVE_PREFIXES) \
                                or "again" in documented or any(s in text for s in _SKIPPED_FORMS):
                            continue
                        if (_doc_value_matches(lisp_core.to_string(value), documented)
                                or _doc_value_matches(lisp_core.to_display_string(value), documented)):
                            verified += 1
                        else:
                            failures.append("%s, block %d: %s\n      doc says: %s\n      got:      %s"
                                            % (doc, bi, text.replace("\n", " ")[:80], documented,
                                               lisp_core.to_string(value)))
                    if stop:
                        break
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
        documents = [REFERENCE_DOC, LIBRARY_DOC, EXAMPLES_DOC, os.path.join(HERE, "economic_data_guide.md"),
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
