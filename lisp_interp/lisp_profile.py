"""Profiling functions for the Lisp interpreter: find out which functions a program spends its time in.

  profile          start counting the calls of functions, and timing them
  unprofile        stop
  profile-reset!   set the counts and times back to zero
  profile-results  what has been found, as a table
  show-profile     the same, printed

The machinery -- what the evaluator does for a function that is being profiled -- is in lisp_core.py, in
the section "Profiling". This file is the part you call from Lisp. "Profiling" in lisp_interpreter_reference.md
explains it all with examples.
"""

import math

import numpy as np

import lisp_tables
from lisp_vector_math import to_vector
from lisp_core import (
    Keyword, LispError, LispString, LispVector, Macro, NIL, Procedure, Symbol, is_true, keyword_options,
    list_to_pairs, profile_state, to_string, set_profiling,
)

SORT_KEYS = ["self", "total", "calls", "name"]


def make_profile_builtins(env, out):
    """The profiling builtins for one global environment `env`, whose display output goes to `out`."""

    def resolve(target, who):
        """What a target names: ('procedure', name) for a function you define, which is found by its
        name wherever it is, or ('builtin', function, name) for one that comes with the interpreter."""
        if isinstance(target, Procedure):
            if target.name is None:
                raise LispError("%s: that procedure has no name, so it can't be profiled -- define it with a name" % who)
            return ("procedure", str(target.name))
        if isinstance(target, Macro):
            raise LispError("%s: a macro can't be profiled (its expansion is made once, not each time it is used)" % who)
        if isinstance(target, (Symbol, LispString)):
            name = str(target)
            found = env.get(Symbol(name))
            if isinstance(found, Macro):
                raise LispError("%s: %s is a macro, and a macro can't be profiled" % (who, name))
            if callable(found) and not isinstance(found, Procedure):
                return ("builtin", found, name)
            if not isinstance(found, Procedure):
                out.write("%s: note: no function named %s is defined yet, or it's a local function. "
                          "The profile applies to any function of that name.\n" % (who, name))
            return ("procedure", name)
        if callable(target):
            names = [str(k) for k, v in env.items() if v is target]
            return ("builtin", target, names[0] if names else getattr(target, "__name__", "a built-in function"))
        raise LispError("%s: expected a function or its name, not %s" % (who, to_string(target)))

    def split_options(arguments, allowed, who):
        """The targets, which come first, and the :name value options after them."""
        first_option = next((i for i, a in enumerate(arguments) if isinstance(a, Keyword)), len(arguments))
        return arguments[:first_option], keyword_options(arguments[first_option:], allowed, who)

    def lisp_profile(*arguments):
        """(profile function-or-name ... [:time #f]) -- from now on, count the calls of each function, and
        time them: how long each takes in all (with the functions it calls), and how long itself (not
        counting calls of other functions being profiled). A function is its name, as in break: any
        function of that name, wherever it's defined, or a built-in function. :time #f counts only, which
        costs less. Returns the names."""
        targets, options = split_options(arguments, ["time"], "profile")
        if not targets:
            raise LispError("profile: expected at least one function or name to profile")
        timed = is_true(options.get("time", True))
        names = []
        for target in targets:
            what = resolve(target, "profile")
            profile_state.add(what, timed)
            names.append(what[-1])
        set_profiling()
        return list_to_pairs([Symbol(n) for n in names])

    def lisp_unprofile(*targets):
        """(unprofile function-or-name ...) -- stop profiling these. (unprofile) stops profiling all of them."""
        if targets:
            for target in targets:
                profile_state.remove(resolve(target, "unprofile"))
        else:
            profile_state.clear()
        set_profiling()
        return NIL

    def lisp_profile_reset():
        """(profile-reset!) -- set every count and time back to zero, and go on profiling."""
        profile_state.reset_counts()
        return NIL

    def lisp_profile_results(*options):
        """(profile-results [:sort key]) -- what profiling has found, as a table with a row for each function
        profiled: its name, the number of calls, the time in all of them (total_s) and in the function itself
        (self_s), in seconds, and the milliseconds of itself for a call. The time is missing for a
        function that is only counted. :sort is self (the default), total, calls, or name."""
        given = keyword_options(options, ["sort"], "profile-results")
        key = str(given.get("sort", Symbol("self")))
        if key not in SORT_KEYS:
            raise LispError("profile-results: :sort is one of %s, not %s" % (", ".join(SORT_KEYS), key))
        entries = profile_state.entries()
        order = {"self": lambda e: (-(e.own if e.timed else -1), -e.calls, e.name),
                 "total": lambda e: (-(e.total if e.timed else -1), -e.calls, e.name),
                 "calls": lambda e: (-e.calls, e.name),
                 "name": lambda e: (e.name,)}[key]
        entries = sorted(entries, key=order)
        nan = math.nan
        columns = [
            ("function", LispVector([LispString(e.name) for e in entries])),
            ("calls", to_vector(np.array([e.calls for e in entries], dtype=np.int64))),
            ("total_s", to_vector(np.array([e.total if e.timed else nan for e in entries], dtype=np.float64))),
            ("self_s", to_vector(np.array([e.own if e.timed else nan for e in entries], dtype=np.float64))),
            ("ms_per_call", to_vector(np.array([1000.0 * e.own / e.calls if e.timed and e.calls else nan
                                                for e in entries], dtype=np.float64))),
        ]
        return lisp_tables.make_table_value(columns)

    def lisp_show_profile(*options):
        """(show-profile [:sort key]) -- print what profile-results gives."""
        table = lisp_profile_results(*options)
        formats = list_to_pairs([list_to_pairs([LispString(column), LispString(spec)]) for column, spec in
                                 [("calls", ","), ("total_s", ".4f"), ("self_s", ".4f"), ("ms_per_call", ".4f")]])
        env[Symbol("display-table")](table, formats, Keyword(":max-rows"), False)
        return NIL

    return {
        "profile": lisp_profile,
        "unprofile": lisp_unprofile,
        "profile-reset!": lisp_profile_reset,
        "profile-results": lisp_profile_results,
        "show-profile": lisp_show_profile,
    }
