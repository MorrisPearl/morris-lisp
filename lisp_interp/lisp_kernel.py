"""The "morris_lisp" Jupyter kernel: every cell is Lisp source. Install it
once with
    python3 install_lisp_kernel.py
then choose "morris_lisp" in Jupyter's kernel picker.

Output (charts, tables, Markdown) goes through lisp_jupyter.py. The kernel
subclasses IPythonKernel, not the bare Kernel class, because that sets up
the IPython shell that IPython.display.display() needs -- even though no
Python code is ever run through it.

Differences from a Python kernel:
  - An error shows the Lisp chain of calls that led to it, not a Python
    traceback. (A tail call replaces its caller's frame, shown as
    "[+N tail calls]".)
  - There's no tab completion.
  - The history variables _, __, ___, and _N (the result of cell N) are
    set in the Lisp environment by hand (see _record_history), since
    IPython only sets them for Python code."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lisp_core import LispError, NIL, Symbol, format_lisp_traceback, parse, seval, to_string
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

    # IPythonKernel.execution_count reads the IPython shell's counter and
    # ignores assignments. This kernel never runs code through the shell, so
    # that counter never moves and every cell would be numbered [1]. Keep our
    # own counter instead; _record_history uses it too.
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
        result = NIL
        try:
            for expr in parse(code):
                result = seval(expr, env)
        except LispError as e:
            return self._error_reply("LispError", str(e), format_lisp_traceback(e))
        except Exception as e:
            return self._error_reply(type(e).__name__, str(e), format_lisp_traceback(e))

        if not silent and result is not NIL:
            self._record_history(env, result)
            self.send_response(self.iopub_socket, "execute_result", {
                "execution_count": self.execution_count,
                "data": {"text/plain": to_string(result)},
                "metadata": {},
            })

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    def _record_history(self, env, result):
        """Set Jupyter's history variables in the Lisp environment: _ is the
        latest result, __ and ___ the two before it, and _N the result of
        execution N. Only a cell that produces a value counts, as in IPython."""
        env[Symbol("___")] = env.get(Symbol("__"), NIL)
        env[Symbol("__")] = env.get(Symbol("_"), NIL)
        env[Symbol("_")] = result
        env[Symbol("_%d" % self.execution_count)] = result

    def _error_reply(self, ename, evalue, lisp_traceback=""):
        """Show a Jupyter error box, and return the matching error reply. Its
        "traceback" is the Lisp chain of calls that led to the error (see
        lisp_core.format_lisp_traceback), then the error message."""
        traceback = lisp_traceback.splitlines() + ["%s: %s" % (ename, evalue)]
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
