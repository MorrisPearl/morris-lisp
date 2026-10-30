"""How much of the interpreter the tests run: which lines of each lisp_*.py
file, and which top-level functions of each lib/*.lsp library, the whole test
suite (or the test files named) runs at least once. Run it from lisp_interp:

    python3 tools/measure_coverage.py                       # the whole suite (about 20 minutes)
    python3 tools/measure_coverage.py tests/test_models.py  # some test files

It prints, for Python, the share of lines run in each file and the functions
of 15 or more lines that never ran; for Lisp, the share of functions called in
each library and the names of those never called.

How it measures:
  - Python: Python's own monitoring (sys.monitoring, Python 3.12 and later)
    notes the first time each line runs, and then stops watching that line,
    so the tests run nearly as fast as usual.
  - Lisp: the interpreter already calls a hook when a function is defined and
    another when a user-defined function is called (for the profiler and for
    lisp_coverage.py). This wraps those hooks to note which library file each
    top-level function was defined in, and count its calls.

What it can't see:
  - Code that the tests run in another process: lisp_interpreter.py's main,
    repl and run_script show as never run, though tests/test_programs.py runs
    programs with them.
  - Branches inside a Lisp function: a Lisp function counts as covered if it
    was called once, so Lisp coverage looks higher than Python's.

The tests that check that coverage and profiling can be turned off are left
out, since this keeps the interpreter's hooks on for the whole run.
"""

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import types

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))   # lisp_interp
OUTPUT = "MEASURE_COVERAGE_OUTPUT"      # the environment variable naming the file the results go to

# Tests that turn coverage or profiling off and check that it is off.
LEFT_OUT = ["tests/test_coverage.py::TestOffAndOn",
            "tests/test_profiling.py::TestCounting::test_unprofile_stops_counting_one_function_or_all"]


# ---------------------------------------------------------------------------
# While the tests run: this file is also a pytest plugin (pytest -p measure_coverage)
# ---------------------------------------------------------------------------

TOOL_ID = 3                 # one of sys.monitoring's ids for tools like this one
lines_run = {}              # a lisp_*.py file's path -> the line numbers that ran
lisp_calls = {}             # "library.lsp<tab>function name" -> how many times it was called


def on_line(code, line):
    """A line ran for the first time: note it if it is in one of the interpreter's files, then stop watching it."""
    path = code.co_filename
    if os.path.dirname(path) == ROOT and os.path.basename(path).startswith("lisp_"):
        lines_run.setdefault(path, set()).add(line)
    return sys.monitoring.DISABLE


def pytest_configure(config):
    """Start watching lines, and wrap the interpreter's hooks for defining and calling functions."""
    sys.monitoring.use_tool_id(TOOL_ID, "measure_coverage")
    sys.monitoring.register_callback(TOOL_ID, sys.monitoring.events.LINE, on_line)
    sys.monitoring.set_events(TOOL_ID, sys.monitoring.events.LINE)

    sys.path.insert(0, ROOT)
    import lisp_core
    defined, enter, set_profiling = lisp_core._coverage_defined, lisp_core._profile_enter, lisp_core.set_profiling

    def noting_defined(procedure, label, env):
        """A top-level function defined while a file is loading: mark it with its file and name."""
        if env.outer is None and lisp_core.coverage_state.files:
            procedure.measured_as = "%s\t%s" % (os.path.basename(lisp_core.coverage_state.files[-1]), label)
            lisp_calls.setdefault(procedure.measured_as, 0)
        return defined(procedure, label, env)

    def counting_enter(procedure, below=None):
        """A user-defined function is called: count it, if it is a marked one."""
        name = getattr(procedure, "measured_as", None)
        if name is not None:
            lisp_calls[name] += 1
        return enter(procedure, below)

    def keeping_hooks_on():
        """The interpreter calls the hooks only while something is profiled or covered: keep that true."""
        set_profiling()
        lisp_core._profiling = True

    lisp_core._coverage_defined = noting_defined
    lisp_core._profile_enter = counting_enter
    lisp_core.set_profiling = keeping_hooks_on
    lisp_core._profiling = True


def pytest_unconfigure(config):
    """Stop watching, and save what was found for the report."""
    sys.monitoring.set_events(TOOL_ID, 0)
    sys.monitoring.free_tool_id(TOOL_ID)
    with open(os.environ[OUTPUT], "w") as out:
        json.dump({"lines": {path: sorted(lines) for path, lines in lines_run.items()}, "lisp_calls": lisp_calls}, out)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def code_lines(code):
    """The lines of a compiled file, or function, that can run: its own and its nested functions'."""
    lines = {line for _, _, line in code.co_lines() if line is not None}
    for inner in code.co_consts:
        if isinstance(inner, types.CodeType):
            lines |= code_lines(inner)
    return lines


def functions_of(code):
    """(name, first line, the lines of its body) for each function in compiled code, nested ones too."""
    for inner in code.co_consts:
        if isinstance(inner, types.CodeType):
            body = {line for _, _, line in inner.co_lines() if line is not None and line != inner.co_firstlineno}
            yield inner.co_qualname, inner.co_firstlineno, body
            yield from functions_of(inner)


def python_report(lines_run):
    """The share of lines run in each lisp_*.py file, least covered first, and the big functions never run."""
    rows, never_run = [], []
    for path in sorted(glob.glob(os.path.join(ROOT, "lisp_*.py"))):
        code = compile(open(path).read(), path, "exec")
        ran = set(lines_run.get(path, []))
        lines = code_lines(code)
        rows.append((os.path.basename(path), len(lines), len(lines & ran)))
        for name, first, body in functions_of(code):
            if len(body) >= 15 and not (body & ran):
                never_run.append((os.path.basename(path), name, first, len(body)))

    total, run = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print("PYTHON: lines run, by file (least covered first)")
    print("  all files: %d of %d lines (%.0f%%)" % (run, total, 100 * run / total))
    for name, lines, ran in sorted(rows, key=lambda row: row[2] / max(row[1], 1)):
        print("  %-28s %5d of %5d  %3.0f%%" % (name, ran, lines, 100 * ran / max(lines, 1)))
    print("\nPYTHON: functions of 15 or more lines never run")
    for name, function, first, size in sorted(never_run, key=lambda f: -f[3]):
        print("  %-24s %-40s line %5d  %4d lines" % (name, function, first, size))


# A library's functions: (define (name ...)), (defun name ...) and (defmethod name ...).
FUNCTION = re.compile(r"^\((?:define\s+\(|defun\s+|defmethod\s+)([^\s()]+)", re.M)


def lisp_report(lisp_calls):
    """The share of top-level functions called in each lib/*.lsp library, least covered first, and those never
    called. A method is counted as called if any of a generic function's methods is (it is labelled "name (type)")."""
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "lib", "*.lsp"))):
        library = os.path.basename(path)
        names = list(dict.fromkeys(FUNCTION.findall(open(path).read())))
        if not names:
            continue

        def calls_of(name):
            return sum(count for key, count in lisp_calls.items()
                       if key == "%s\t%s" % (library, name) or key.startswith("%s\t%s (" % (library, name)))
        loaded = any(key.startswith(library + "\t") for key in lisp_calls)
        rows.append((library, names, [name for name in names if calls_of(name) == 0], loaded))

    total = sum(len(names) for _, names, _, _ in rows)
    called = total - sum(len(never) for _, _, never, _ in rows)
    print("\nLISP LIBRARIES: top-level functions called at least once, by file (least covered first)")
    print("  all libraries: %d of %d functions (%.0f%%)" % (called, total, 100 * called / max(total, 1)))
    for library, names, never, loaded in sorted(rows, key=lambda row: 1 - len(row[2]) / len(row[1])):
        print("  %-28s %4d of %4d  %3.0f%%%s" % (library, len(names) - len(never), len(names),
                                                100 * (1 - len(never) / len(names)),
                                                "" if loaded else "   (no test loads it)"))
    print("\nLISP: functions never called")
    for library, names, never, loaded in rows:
        if never and loaded:
            print("  %s: %s" % (library, ", ".join(never)))


def main(test_paths):
    """Run the tests with this file as a plugin, then print the report."""
    with tempfile.TemporaryDirectory() as folder:
        results = os.path.join(folder, "coverage.json")
        environment = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.abspath(__file__)), **{OUTPUT: results})
        left_out = [option for test in LEFT_OUT for option in ("--deselect", test)]
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "measure_coverage"]
                       + left_out + (test_paths or ["tests"]), cwd=ROOT, env=environment)
        if not os.path.exists(results):
            sys.exit("measure_coverage: the tests didn't finish, so there is nothing to report")
        found = json.load(open(results))
    print()
    python_report(found["lines"])
    lisp_report(found["lisp_calls"])


if __name__ == "__main__":
    main(sys.argv[1:])
