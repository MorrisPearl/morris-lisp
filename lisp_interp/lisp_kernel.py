"""
lisp_kernel.py
================
A native Jupyter kernel for the morris_lisp interpreter: every cell is
plain Lisp source, no cell magic needed. Install it once with
    python3 install_lisp_kernel.py
then pick "morris_lisp" from Jupyter's kernel picker / New menu, same as
any other kernel.

Reuses lisp_jupyter.py's shared environment and output/plot/columns
callbacks UNCHANGED (charts render inline, (display-columns ...) renders
as a pandas DataFrame) -- this is built as an IPythonKernel subclass
(NOT the bare ipykernel.kernelbase.Kernel) SPECIFICALLY so
IPython.display.display() (which those callbacks call) keeps resolving
to a real, wired-up display-publisher path: IPythonKernel.__init__
creates and registers a genuine InteractiveShell as the process's active
`get_ipython()` target -- a process-wide registration, done once at
kernel startup -- even though do_execute() below never actually runs any
Python code through it. The bare Kernel base class never creates that
shell at all, so IPython.display.display() would have nothing to route
through and would silently fall back to a plain repr. See
lisp_jupyter.py's own docstring, and the "Running it" section of
lisp_interpreter_reference.md, for more.

A few things worth knowing about how this differs from an ordinary Python
kernel:
  - errors render through Jupyter's own error display (a red traceback
    box), built from the LispError's message -- not a Python traceback,
    since this interpreter's tail-call-optimized evaluator deliberately
    doesn't keep ordinary call-frame history (see lisp_interpreter.py's
    own module docstring);
  - tab-completion is disabled outright (see do_complete, below) rather
    than falling through to IPythonKernel's Python-specific completer,
    which would offer irrelevant Python names for a Lisp symbol prefix;
  - Jupyter-style history variables -- `_` (the most recent result),
    `__`/`___` (the two before that), and `_N` (specifically execution
    N's result) -- are bound directly into the shared Lisp environment
    after every cell that produces one (see _record_history, below).
    This has to be done by hand here: IPython's own `_`/`Out[N]`
    bookkeeping is tied to running Python code through
    `shell.run_cell()`, in the PYTHON namespace -- do_execute() below
    never calls that (it evaluates Lisp source directly through
    L.seval), so IPython's own history variables would never be
    populated, and wouldn't be reachable from Lisp code even if they
    were.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lisp_interpreter as L
import lisp_jupyter

from ipykernel.ipkernel import IPythonKernel


class LispKernel(IPythonKernel):
    implementation = "morris_lisp"
    implementation_version = "1.0"
    language_info = {
        "name": "scheme",              # closest match a Jupyter frontend/pygments/
        "version": "1.0",              # CodeMirror already ship built-in syntax
        "mimetype": "text/x-scheme",   # highlighting for -- this interpreter's
        "file_extension": ".lsp",      # actual syntax (#t/#f, #(...) vectors,
        "pygments_lexer": "scheme",    # '/`/, reader macros) is close enough
        "codemirror_mode": "scheme",   # to Scheme for this to look right.
    }
    banner = (
        "morris_lisp -- a CL-flavored Lisp for structured-finance modeling.\n"
        "Every cell is plain Lisp source. Charts render inline; "
        "(display-columns ...) renders as a pandas table.\n"
        "See lisp_interpreter_reference.md for the full language/builtin reference."
    )

    # IPythonKernel.execution_count is a PROPERTY, not a plain attribute --
    # its getter returns self.shell.execution_count, and (see its own
    # source) its setter is a deliberate NO-OP: "Ignore the incrementing
    # done by KernelBase, in favour of our shell's execution counter."
    # That's exactly backwards for this kernel -- do_execute() below never
    # calls shell.run_cell(), so self.shell.execution_count never advances,
    # which means Kernel.execute_request()'s `self.execution_count += 1`
    # (called BEFORE do_execute, to publish the "execute_input" message the
    # notebook's In[N]: prompt number comes from) silently does nothing,
    # and every cell reports execution_count 1 forever -- found by hitting
    # this directly: prompts stuck at [1]: no matter how many cells ran.
    # Overriding the property again here, backed by a genuinely writable
    # instance attribute instead of the shell's counter, fixes both the
    # prompt number and this kernel's own _record_history() (below), which
    # reads the exact same property.
    _execution_count = 0

    @property
    def execution_count(self):
        return self._execution_count

    @execution_count.setter
    def execution_count(self, value):
        self._execution_count = value

    def do_execute(self, code, silent, store_history=True, user_expressions=None,
                    allow_stdin=False, *, cell_meta=None, cell_id=None):
        env = lisp_jupyter.get_env()
        result = L.NIL
        try:
            for expr in L.parse(code):
                result = L.seval(expr, env)
        except L.LispError as e:
            return self._error_reply("LispError", str(e))
        except Exception as e:
            return self._error_reply(type(e).__name__, str(e))

        if not silent and result is not L.NIL:
            self._record_history(env, result)
            self.send_response(self.iopub_socket, "execute_result", {
                "execution_count": self.execution_count,
                "data": {"text/plain": L.to_string(result)},
                "metadata": {},
            })

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    def _record_history(self, env, result):
        """Jupyter-style history variables, at the Lisp level: `_` is
        always the most recently produced (non-'()) result, `__`/`___`
        the two before that, and `_N` is specifically execution N's
        result -- exactly the `_`/`__`/`___`/`Out[N]` convention IPython
        gives Python cells (see the module docstring for why this kernel
        doesn't get that for free). Only called for a cell that actually
        produced a value (do_execute's `result is not L.NIL` check) --
        the same rule IPython itself uses: a (define x 10)-style cell
        with no displayed result doesn't shift the history either."""
        env[L.Symbol("___")] = env.get(L.Symbol("__"), L.NIL)
        env[L.Symbol("__")] = env.get(L.Symbol("_"), L.NIL)
        env[L.Symbol("_")] = result
        env[L.Symbol("_%d" % self.execution_count)] = result

    def _error_reply(self, ename, evalue):
        """Publish a real Jupyter error display (the red traceback box)
        and return the matching error-status execute_reply -- there's no
        genuine traceback to show (this interpreter's tail-call-
        optimized evaluator deliberately doesn't keep ordinary call-frame
        history -- see lisp_interpreter.py's module docstring), so the
        "traceback" is just the one-line error message."""
        traceback = ["%s: %s" % (ename, evalue)]
        self.send_response(self.iopub_socket, "error", {
            "ename": ename, "evalue": evalue, "traceback": traceback,
        })
        return {
            "status": "error",
            "execution_count": self.execution_count,
            "ename": ename, "evalue": evalue, "traceback": traceback,
        }

    def do_complete(self, code, cursor_pos):
        """No tab-completion implemented (yet) -- report "no matches"
        explicitly rather than falling through to IPythonKernel's
        Python-specific completer."""
        return {
            "status": "ok",
            "matches": [],
            "cursor_start": cursor_pos,
            "cursor_end": cursor_pos,
            "metadata": {},
        }


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=LispKernel)
