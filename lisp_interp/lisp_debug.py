"""Debugging functions for the Lisp interpreter.

  break, unbreak, breakpoints    stop when a procedure is called
  set-debug-hook!, debug-hook    register a function to decide what happens at a stop
  debug-repl                     open the debug REPL (for use in a hook)
  abort                          abandon the computation, back to the top level
  locals                         the variables visible where the program is stopped
  break-on-error                 stop where an error happens

The machinery -- how a stop works, the debug REPL, the breakpoint check in the
evaluator -- is in lisp_core.py, in the section "Debugging". This file is the
part you call from Lisp. "Debugging" in lisp_interpreter_reference.md explains
it all with examples.
"""

from lisp_core import (
    LispAbort, LispError, LispString, Macro, NIL, Procedure, Symbol,
    current_pause, debug_state, is_true, list_to_pairs, open_debug_repl,
    to_string, visible_variables,
)


def make_debug_builtins(env, out):
    """The debug builtins for one global environment `env`, whose display
    output goes to `out`."""

    def breakpoint_name(target, who):
        """The name a breakpoint goes on: the name of the procedure `target`,
        or `target` itself if it's a name (a symbol or string)."""
        if isinstance(target, Procedure):
            if target.name is None:
                raise LispError("%s: that procedure has no name, so it can't have a breakpoint "
                                "-- define it with a name" % who)
            return target.name
        if isinstance(target, Macro):
            raise LispError("%s: a macro can't have a breakpoint" % who)
        if isinstance(target, (Symbol, LispString)):
            return Symbol(str(target))
        if callable(target):
            raise LispError("%s: that's a built-in function; only functions you define can "
                            "have breakpoints" % who)
        raise LispError("%s: expected a procedure or its name, not %s" % (who, to_string(target)))

    def lisp_break(target, condition=NIL):
        """(break procedure-or-name [condition]) -- from now on, stop each time a
        procedure with this name is called, after its arguments are bound.
        `condition`, if given, is an expression evaluated in the procedure's
        scope (so it can use its parameters), and the program only stops if it's
        true. Returns the name."""
        name = breakpoint_name(target, "break")
        if not isinstance(target, Procedure) and not isinstance(env.get(name), Procedure):
            out.write("break: note: no function named %s is defined yet, or it's a local function. "
                      "The breakpoint applies to any function of that name.\n" % name)
        debug_state.breakpoints[name] = None if condition is NIL or condition is False else condition
        return name

    def lisp_unbreak(*target):
        """(unbreak procedure-or-name) -- remove the breakpoint on a procedure.
        (unbreak) removes every breakpoint."""
        if len(target) > 1:
            raise LispError("unbreak: expected at most one argument, got %d" % len(target))
        if target:
            debug_state.breakpoints.pop(breakpoint_name(target[0], "unbreak"), None)
        else:
            debug_state.breakpoints.clear()
        return NIL

    def lisp_breakpoints():
        """(breakpoints) -- the breakpoints that are set, as a list with one entry
        for each: (name), or (name condition) if it has a condition."""
        entries = []
        for name, condition in debug_state.breakpoints.items():
            entries.append(list_to_pairs([name] if condition is None else [name, condition]))
        return list_to_pairs(entries)

    def lisp_set_debug_hook(hook):
        """(set-debug-hook! procedure) -- register the procedure to call at every
        stop, in place of opening the debug REPL. (set-debug-hook! '()) removes
        it. Returns the hook that was registered before, or '()."""
        if hook is NIL or hook is False:
            hook = None
        elif not isinstance(hook, Procedure) and not callable(hook):
            raise LispError("set-debug-hook!: expected a procedure, or '() to remove the hook, not %s"
                            % to_string(hook))
        previous = debug_state.hook
        debug_state.hook = hook
        return NIL if previous is None else previous

    def lisp_debug_hook():
        """(debug-hook) -- the registered debug hook, or '() if there is none."""
        return NIL if debug_state.hook is None else debug_state.hook

    def lisp_break_on_error(*flag):
        """(break-on-error) -- whether errors stop the program where they happen.
        (break-on-error #t) turns that on, (break-on-error #f) off; the previous
        setting is returned."""
        if len(flag) > 1:
            raise LispError("break-on-error: expected at most one argument, got %d" % len(flag))
        previous = debug_state.break_on_error
        if flag:
            debug_state.break_on_error = is_true(flag[0])
        return previous

    def lisp_debug_repl():
        """(debug-repl) -- open the debug REPL where the program is stopped.
        Only for use in a debug hook."""
        open_debug_repl()
        return NIL

    def lisp_abort():
        """(abort) -- abandon the computation and go back to the top level."""
        raise LispAbort()

    def lisp_locals():
        """(locals) -- the variables visible where the program is stopped, as an
        association list of (name . value), innermost scope first."""
        pause = current_pause()
        if pause is None:
            raise LispError("locals: the program isn't stopped anywhere. Use it in the debug REPL "
                            "or in a debug hook.")
        return visible_variables(pause.env)

    return {
        "break": lisp_break,
        "unbreak": lisp_unbreak,
        "breakpoints": lisp_breakpoints,
        "set-debug-hook!": lisp_set_debug_hook,
        "debug-hook": lisp_debug_hook,
        "break-on-error": lisp_break_on_error,
        "debug-repl": lisp_debug_repl,
        "abort": lisp_abort,
        "locals": lisp_locals,
    }
