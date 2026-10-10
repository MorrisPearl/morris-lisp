"""The manuals' own examples: every `expr ; => value` in lisp_interpreter_reference.md (the
language) and lisp_library_reference.md (the library) must still be what the interpreter gives.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


#
# Every fenced ```lisp block in lisp_interpreter_reference.md is run, and each
# top-level form written as   (expr)   ; => value   must print as `value`.
# That keeps the documentation honest: if a builtin's behavior changes, this
# fails until the doc (or the interpreter) is fixed.

# blocks that would block on stdin, need the network/GUI, or touch the disk
_RISKY_BLOCK_WORDS = (
    "(breakpoint)", "(breakpoint (", '(breakpoint "', "(abort", "debug-repl",
    "fred-table", "tastytrade", "schwab-", "google-", "alpha-vantage-", "sofr-", "(sec-", "(fdic-", "(census-", "(bls-", "(bea-", "(sleep", "(load ", "redirect-output", "sqlite-open", "with-sqlite", "lp-read-file",
    "save-chart", "load-csv", "write-columns-csv",
    "input", "(read-line", "exit", "load-init", "http-get", "http-clear-cache",
)


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


def _doc_value_matches(actual, documented):
    """Exact, or exact followed by explanatory prose ('3  -- because ...')."""
    if documented == actual:
        return True
    return documented.startswith(actual) and documented[len(actual):len(actual) + 1] in (" ", ",", "\t")


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
        blocks = []                 # (the manual's name, the block)
        for doc in (REFERENCE_DOC, LIBRARY_DOC):
            with open(doc, encoding="utf-8") as f:
                found = re.findall(r"```lisp\n(.*?)```", f.read(), re.S)
            self.assertGreater(len(found), 50, "found few lisp code blocks in " + os.path.basename(doc))
            blocks += [(os.path.basename(doc), block) for block in found]

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

        for bi, (doc, block) in enumerate(blocks):
            if any(word in block for word in _RISKY_BLOCK_WORDS):
                continue
            env = lisp_builtins.make_global_env(output=lambda s: None)
            lisp_core.debug_state.reset()       # breakpoints belong to the whole process, not one block
            if use_alarm:
                signal.alarm(10)
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
                            if documented is not None and "unbound symbol" not in str(e):
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


if __name__ == "__main__":
    unittest.main()
