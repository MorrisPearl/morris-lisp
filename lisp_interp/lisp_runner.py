"""Running the Lisp interpreter from Python. The command line, lisp_interpreter.py, is made of these
functions, and any other Python program can import this file and use them the same way:

    import sys
    sys.path.insert(0, "/path/to/morris_lisp/lisp_interp")      # the folder this file is in
    import lisp_runner

    lisp_runner.run_file("model.lsp")              # runs a Lisp file; returns the value of its last form
    lisp_runner.run_file("prices.lsp", arguments=["KO", "6"])    # its (command-line-arguments) is ("KO" "6")

    env = lisp_runner.new_environment()            # one environment, for several things in turn
    lisp_runner.run_file("setup.lsp", env)
    lisp_runner.run_text("(+ 1 2)", env)           # => 3
    lisp_runner.repl(env)                          # the console, in that environment

Each new environment is the one a notebook or the console has: the builtins and the standard macros, the
libraries' functions (lib/autoloads.lsp), and the init file (init.lsp, or the LISP_INIT_FILE environment
variable's).

What the Lisp program displays goes to standard output, unless new_environment is told where:
new_environment(output=texts.append) collects it in a list. A value comes back as the interpreter holds it:
an int or a float, a str for a string or a symbol, a lisp_core.Pair for a list (lisp_core.pairs_to_list(value)
makes a Python list of one), a lisp_core.LispVector for a vector (its .items is a numpy array), and so on;
lisp_core.to_string(value) is the text the console would show for it.

A Lisp error raises lisp_core.LispError, and lisp_core.format_error_report(error) is the report the console
prints for it: the chain of Lisp calls that led to it, then the message. (abort) raises lisp_core.LispAbort.
"""

import lisp_core
from lisp_core import (
    UNFINISHED, LispAbort, LispError, NIL, Pair, Symbol, TOP_LEVEL_MAX_ITEMS, format_call_stack, format_error_report, parse,
    seval, to_string,
)
from lisp_builtins import load_init_file, make_global_env, set_command_line_arguments
from lisp_tables import is_table


def new_environment(**outputs):
    """A new environment, as a notebook or the console has one: the builtins and the standard macros, the libraries'
    functions, and the init file. outputs, if any, are make_global_env's (in lisp_builtins.py), which say where the
    environment's output goes: output (a function given each piece of text that display, print, and newline write),
    plot (given each chart), table (given each table that display-table shows), and so on. Without them it is the
    console's: text to standard output, and a line about each chart."""
    env = make_global_env(**outputs)
    load_init_file(env)
    return env


def run_file(path, env=None, arguments=()):
    """Runs the Lisp file at path (a file name, or a path from the current directory or from the top), in env -- a
    new environment, unless it is given -- and returns the value of its last form. arguments, a list of strings, are
    what (command-line-arguments) gives the program: the words after a script's name on the command line."""
    set_command_line_arguments(arguments)
    if env is None:
        env = new_environment()
    return lisp_core.run_file(path, env)


def run_text(text, env=None):
    """Runs Lisp source text, a string of one or more forms, in env (a new environment, unless it is given), and
    returns the value of the last form."""
    if env is None:
        env = new_environment()
    value = NIL
    for form in parse(text):
        value = seval(form, env)
    return value


def repl(env=None):
    """The console: it reads a form, runs it, and shows its value, until (exit) or the end of the input. A form
    is run once it is finished -- its parentheses and strings closed -- so a definition can span several lines.
    The forms typed on a line are read before any of them runs, as a notebook's cell is. Its value is shown as a notebook
    cell's is: a table as display-table shows it, and only the first 100 elements of a list or vector. Control-C
    stops what is running (and shows where it was), or, while typing, throws away the lines typed so far."""
    if env is None:
        env = new_environment()
    print("Simple Lisp interpreter. Type (exit) to quit, (help name) for help with a name, and (apropos \"text\") to look for one.")
    buffer = ""
    while True:
        try:
            line = input("  ... " if buffer else "lisp> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            buffer = ""
            continue
        buffer += line + "\n"
        try:
            forms = list(parse(buffer))
        except LispError as e:
            if e.kind == UNFINISHED:
                continue                        # the form goes on, on the next line
            print("Error: %s" % e)
            buffer = ""
            continue
        try:
            for expr in forms:
                if isinstance(expr, Pair) and expr.car == Symbol("exit"):
                    return
                result = seval(expr, env)
                if is_table(result) and result is not NIL:
                    env[Symbol("display-table")](result)
                else:
                    print(to_string(result, TOP_LEVEL_MAX_ITEMS))
        except LispAbort:
            print("Aborted -- back at the top level.")
        except KeyboardInterrupt as e:
            print(format_call_stack(getattr(e, "lisp_trace", None) or [],
                                    "Interrupted while running (most recent call last):") + "Interrupted.")
        except Exception as e:
            print(format_error_report(e), end="")
        buffer = ""
