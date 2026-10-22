"""Test coverage for the Lisp interpreter: which functions a program defined, and never called.

  coverage-on       start noting the functions that are defined, and counting their calls
  coverage-off      stop noting (what was found is kept)
  coverage-reset!   forget what was found, and go on noting
  coverage-results  every function defined since coverage-on, with its file and the number of calls, as a table
  coverage-report   the same, printed: the functions never called, by file

The machinery -- what the evaluator does while coverage is on -- is in lisp_core.py, next to the profiler it shares its test of
_profiling with. This file is the part you call from Lisp. "Test coverage" in lisp_interpreter_reference.md explains it with an example.
"""

import os

import numpy as np

import lisp_tables
from lisp_vector_math import to_vector
from lisp_core import (
    Keyword, LispString, LispVector, NIL, coverage_state, is_true, keyword_options, set_profiling,
)

TYPED_IN = "(typed in)"


def make_coverage_builtins(env, out):
    """The coverage builtins for one global environment `env`, whose display output goes to `out`."""

    def functions():
        """(label, file, calls) for each function defined since coverage-on, in the order that they were defined, ordered by file."""
        found = [(label, os.path.basename(file) if file else TYPED_IN, coverage_state.calls.get(id(procedure), 0))
                 for label, (procedure, file) in coverage_state.defined.items()]
        files = []
        for _, file, _ in found:
            if file not in files:
                files.append(file)
        return sorted(found, key=lambda row: files.index(row[1]))

    def lisp_coverage_on():
        """(coverage-on) -- from now on, note every function that is defined at the top level (by define or defmethod), in a file or not, and
        count its calls. Starts from nothing. A function made inside another is left out, as an anonymous lambda is. Costs a program that
        isn't being covered nothing more than the profiler does."""
        coverage_state.clear()
        coverage_state.on = True
        set_profiling()
        return NIL

    def lisp_coverage_off():
        """(coverage-off) -- stop noting functions and counting calls. What was found is kept, for coverage-report."""
        coverage_state.on = False
        set_profiling()
        return NIL

    def lisp_coverage_reset():
        """(coverage-reset!) -- forget what was found, and go on as before: on if it was on."""
        coverage_state.clear()
        return NIL

    def lisp_coverage_results(*options):
        """(coverage-results [:uncalled #t]) -- every function defined since coverage-on, as a table: its name (a method is `name (type)`),
        the file that it is in, and its calls. :uncalled #t is only those with none."""
        given = keyword_options(options, ["uncalled"], "coverage-results")
        rows = functions()
        if is_true(given.get("uncalled", False)):
            rows = [row for row in rows if row[2] == 0]
        columns = [("function", LispVector([LispString(label) for label, _, _ in rows])),
                   ("file", LispVector([LispString(file) for _, file, _ in rows])),
                   ("calls", to_vector(np.array([calls for _, _, calls in rows], dtype=np.int64)))]
        return lisp_tables.make_table_value(columns)

    def lisp_coverage_report():
        """(coverage-report) -- print what was found: how many functions were defined since coverage-on, how many of them were called,
        and the ones that were not, by file."""
        rows = functions()
        uncalled = [row for row in rows if row[2] == 0]
        if not rows:
            out.write("No function has been defined since coverage-on.\n")
            return NIL
        out.write("%d of %d functions were called (%d%%)%s.\n" % (
            len(rows) - len(uncalled), len(rows), round(100.0 * (len(rows) - len(uncalled)) / len(rows)),
            "" if coverage_state.on else "; coverage is off"))
        files = []
        for _, file, _ in uncalled:
            if file not in files:
                files.append(file)
        for file in files:
            names = [label for label, f, _ in uncalled if f == file]
            total = len([row for row in rows if row[1] == file])
            out.write("\n%s: %d of %d never called\n" % (file, len(names), total))
            for name in names:
                out.write("  %s\n" % name)
        return NIL

    return {
        "coverage-on": lisp_coverage_on,
        "coverage-off": lisp_coverage_off,
        "coverage-reset!": lisp_coverage_reset,
        "coverage-results": lisp_coverage_results,
        "coverage-report": lisp_coverage_report,
    }
