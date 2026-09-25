#!/usr/bin/env python3
"""morris_lisp: a small, Common-Lisp-flavored Lisp interpreter with numeric
vectors, dates, regression, XY charts, SQLite, and access to FRED and
tastytrade market data.

HOW TO RUN IT
    python3 lisp_interpreter.py              open the GUI (needs PyQt6 + matplotlib)
    python3 lisp_interpreter.py file.lsp     run a file
    python3 lisp_interpreter.py -            the console REPL
Put -v, -vv, -vvv, or --verbose=N before the file name to trace procedure
calls as they happen (see (verbose n) in lisp_interpreter_reference.md).
Every fresh environment first loads init.lsp, if it exists (see
load_init_file in lisp_builtins.py).

HOW THE CODE IS ORGANIZED
    lisp_interpreter.py   this file: the command line, console REPL, and batch mode
    lisp_core.py          data types, reader, evaluator, printer -- the language itself
    lisp_builtins.py      the general built-in procedures, and make_global_env(),
                          which puts every builtin into a new environment
    lisp_regression.py    linear-, logistic-, and spline-regression, model-report, ...
    lisp_charts.py        plot-xy, plot-xy-regression, plot-xy-full, save-chart
    lisp_sqlite.py        sqlite-open, sqlite-query, ...
    lisp_fred.py          fred-series                      (downloads from FRED)
    lisp_tastytrade.py    tastytrade-*                     (downloads from tastytrade)
    lisp_sofr.py          sofr-* interest-rate modeling    (sofr-calibration-data
                                                            downloads from tastytrade)
    lisp_gui.py           the PyQt6 window
    lisp_kernel.py        the Jupyter kernel (with lisp_jupyter.py)
Each module that adds builtins lists them in a BUILTINS table at its end;
lisp_builtins.make_global_env() adds those tables to every environment.
lisp_core.py imports none of the other files, so it can be read on its own.

WHAT THE LANGUAGE SUPPORTS (full details in lisp_interpreter_reference.md)
  - integers, floats, strings, symbols, keywords (:name), booleans, lists
  - vectors of numbers and/or dates, #(1 2 3), backed by numpy arrays so a
    vector of millions of numbers stays compact
  - dates: (date year month day)
  - special forms: quote, quasiquote, if, define, set!, lambda, begin, let,
    let*, cond, and, or, dolist, defmacro, defstruct, with-struct,
    catch-error, breakpoint, backtrace
  - variadic procedures (a b . rest) and CL-style &key keyword arguments
  - macros (defmacro), with macroexpand/macroexpand-1/gensym for writing them
  - defstruct records with single inheritance (:include) and call-method
  - tail calls that run in constant stack space (see lisp_core.py)
  - call tracing, (verbose n), and Lisp-level stack traces on errors
  - hash tables, strings, sorting, pseudo-random numbers
  - linear, logistic, and spline regression with any number of predictors
  - XY charts, and saving them as PNG/PDF/SVG
  - SQLite, CSV files, FRED data, and tastytrade broker data
  - redirect-output / reset-output, to send display output to a file
"""

import os
import sys

from lisp_core import (
    LispError, Pair, Symbol, VERBOSE_CALLS, format_error_report,
    format_lisp_traceback, parse, run_file, seval, set_verbose_level, to_string,
)
from lisp_builtins import load_init_file, make_global_env


def repl(env):
    """The console read-eval-print loop. A form is evaluated once its
    parentheses balance, so a definition can span several lines."""
    print("Simple Lisp interpreter. Type (exit) to quit.")
    buffer = ""
    while True:
        try:
            line = input("  ... " if buffer else "lisp> ")
        except EOFError:
            print()
            break
        buffer += line + "\n"
        if buffer.count("(") <= buffer.count(")"):
            try:
                for expr in parse(buffer):
                    if isinstance(expr, Pair) and expr.car == Symbol("exit"):
                        return
                    result = seval(expr, env)
                    print(to_string(result))
            except Exception as e:
                print(format_error_report(e), end="")
            buffer = ""


def run_script(path, env):
    """Run a script file in batch mode. A Lisp error is reported as the REPL
    reports it -- the chain of calls, then the message -- on stderr, with exit
    status 1. (Set LISP_PYTHON_TRACEBACK=1 to see Python's traceback of the
    interpreter too.) Any other exception is a bug in the interpreter: the
    Lisp call chain is printed, then Python's traceback."""
    try:
        run_file(path, env)
    except LispError as e:
        if os.environ.get("LISP_PYTHON_TRACEBACK"):
            sys.stderr.write(format_lisp_traceback(e))
            raise
        sys.stdout.flush()
        sys.stderr.write(format_error_report(e))
        sys.exit(1)
    except Exception as e:
        sys.stdout.flush()
        sys.stderr.write(format_lisp_traceback(e))
        raise


def verbose_flag_level(arg):
    """The verbosity a leading command-line flag asks for: -v / -vv / -vvv
    (levels 1-3), --verbose (level 1), or --verbose=N (N in 0-3). None if
    `arg` isn't a verbose flag at all; -1 if it is one but N is invalid."""
    if arg in ("-v", "-vv", "-vvv"):
        return len(arg) - 1
    if arg == "--verbose":
        return VERBOSE_CALLS
    if arg.startswith("--verbose="):
        text = arg[len("--verbose="):]
        return int(text) if text in ("0", "1", "2", "3") else -1
    return None


def launch_gui_or_repl():
    """Open the GUI if PyQt6 and matplotlib are installed; otherwise say
    so and run the console REPL instead."""
    import lisp_gui    # imported here so the rest of the interpreter never needs PyQt6
    if lisp_gui.PYQT_AVAILABLE:
        lisp_gui.launch_gui()
        return
    print("PyQt6 and matplotlib are required for the GUI:\n\n    pip install PyQt6 matplotlib\n")
    print("Falling back to the console REPL.\n")
    env = make_global_env()
    load_init_file(env)
    repl(env)


def main():
    args = sys.argv[1:]
    while args and verbose_flag_level(args[0]) is not None:
        level = verbose_flag_level(args.pop(0))
        if level < 0:
            sys.stderr.write("--verbose=N: N must be 0, 1, 2, or 3\n")
            sys.exit(2)
        set_verbose_level(level)

    if not args:
        launch_gui_or_repl()
        return

    env = make_global_env()
    load_init_file(env)
    if args[0] == "-":
        repl(env)
    else:
        run_script(args[0], env)


if __name__ == "__main__":
    main()
