"""What every test file uses: the interpreter's modules, the paths to its files, and
LispTestCase, whose tests each get a fresh global environment.

Run the tests from lisp_interp/ with either of:

    python3 -m pytest -q tests                      # add -k name to pick some
    python3 -m unittest discover -s tests           # add -v for names

They use only the standard library (plus numpy, which the interpreter itself needs),
and never touch the network, the GUI, your credentials, or any file outside a
temporary directory -- so they are safe to run anywhere, anytime. The two slowest
example scripts (about 15s and 60s) are skipped unless you set LISP_TEST_SLOW=1. Not
covered on purpose: anything that needs a network connection or an account
(fred-table, tastytrade-*, sofr-calibration-data). "Running the tests" in
lisp_interpreter_reference.md says more.

Most tests use the helpers on LispTestCase: run a snippet of Lisp source in a fresh
global environment, and compare either the raw result, its printed form (`show`, i.e.
what the REPL would print), or the text the program displayed (`printed`).
"""

import base64
import contextlib
import datetime
import importlib.util
import io
import itertools
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # lisp_interp/
sys.path.insert(0, HERE)

import lisp_alpha_vantage  # noqa: E402
import lisp_calendar  # noqa: E402
import lisp_investment_paths  # noqa: E402
import lisp_options  # noqa: E402
import lisp_builtins  # noqa: E402  (these need the sys.path line above)
import lisp_core     # noqa: E402
import lisp_charts  # noqa: E402
import lisp_clock  # noqa: E402
import lisp_plot_chart  # noqa: E402
import lisp_portfolio  # noqa: E402
import lisp_fred  # noqa: E402
import lisp_http  # noqa: E402
import lisp_jupyter_debug  # noqa: E402
import lisp_tastytrade  # noqa: E402
import lisp_tables  # noqa: E402
import lisp_time_series  # noqa: E402
import lisp_vector_math  # noqa: E402

INTERPRETER = os.path.join(HERE, "lisp_interpreter.py")
LIB = os.path.join(HERE, "lib")                 # the Lisp libraries that come with the interpreter
EXAMPLES = os.path.join(HERE, "examples")
REFERENCE_DOC = os.path.join(HERE, "lisp_interpreter_reference.md")
LIBRARY_DOC = os.path.join(HERE, "lisp_library_reference.md")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class LispTestCase(unittest.TestCase):
    """Every test gets a fresh global environment (no init.lsp loaded) whose
    display/print output is captured rather than written to the console."""

    def setUp(self):
        lisp_core.set_verbose_level(0)         # verbosity is process-wide: never leak it between tests
        self.addCleanup(lisp_core.set_verbose_level, 0)
        lisp_core.debug_state.reset()          # so are breakpoints and the debug hook
        self.addCleanup(lisp_core.debug_state.reset)
        # A stop that opens the debug REPL reads the keyboard. Tests that expect
        # one use run_with_input; any other must fail, not wait for a person.
        patcher = mock.patch("builtins.input", side_effect=AssertionError(
            "the debug REPL asked for input -- use run_with_input to answer it"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out = []
        self.env = lisp_builtins.make_global_env(output=self.out.append)

    # -- running code ------------------------------------------------------

    def run_lisp(self, src, env=None):
        """Evaluate every top-level form in `src`; return the last value."""
        env = self.env if env is None else env
        result = lisp_core.NIL
        for expr in lisp_core.parse(src):
            result = lisp_core.seval(expr, env)
        return result

    def show(self, src):
        """The last value's printed (REPL) form, e.g. '(1 2 3)'."""
        return lisp_core.to_string(self.run_lisp(src))

    def printed(self):
        """Everything display/newline/print have written so far."""
        return "".join(self.out)

    def run_with_input(self, src, lines):
        """Run `src` with the debug REPL reading `lines` as if they were typed;
        return what was printed to the console (the REPL's own output), and
        keep it in self.console and the value in self.result. If the program
        stops more often than there are lines, input() raises StopIteration, so
        the test fails instead of waiting for the keyboard."""
        feed = iter(lines)
        self.console = io.StringIO()
        with mock.patch("builtins.input", lambda prompt="": next(feed)):
            with contextlib.redirect_stdout(self.console):
                self.result = self.run_lisp(src)
        return self.console.getvalue()

    # -- assertions --------------------------------------------------------

    def assertShows(self, src, expected):
        self.assertEqual(self.show(src), expected, msg="source: %s" % src)

    def assertLispError(self, src, fragment=""):
        """`src` must raise the interpreter's own LispError whose message
        contains `fragment`."""
        with self.assertRaises(lisp_core.LispError, msg="source: %s" % src) as cm:
            self.run_lisp(src)
        self.assertIn(fragment, str(cm.exception))

    def assertAborts(self, src):
        """`src` must be abandoned by (abort), which no catch-error stops."""
        with self.assertRaises(lisp_core.LispAbort, msg="source: %s" % src):
            self.run_lisp(src)

    def assertRaisesFromLisp(self, exc_type, src):
        """`src` must raise `exc_type` (for the few builtins documented as
        raising a raw Python exception rather than a LispError)."""
        with self.assertRaises(exc_type, msg="source: %s" % src):
            self.run_lisp(src)
