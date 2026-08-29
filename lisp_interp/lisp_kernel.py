"""
lisp_kernel.py
================
A native Jupyter kernel for the morris_lisp interpreter: every cell is
plain Lisp source -- no %%lisp magic needed. Install it once with
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
lisp_jupyter.py's own docstring, and the "Running in Jupyter" section of
lisp_interpreter_reference.md, for the fuller comparison.

Only two things differ from %%lisp's behavior, both improvements a
native kernel can make that a cell magic can't:
  - errors render through Jupyter's own error display (a red traceback
    box) instead of a plain printed "Error: ..." line;
  - tab-completion is disabled outright (see do_complete, below) rather
    than falling through to IPythonKernel's Python-specific completer,
    which would offer irrelevant Python names for a Lisp symbol prefix.
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
