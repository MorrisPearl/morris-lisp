"""Output callbacks for running the interpreter in a Jupyter notebook, used
by lisp_kernel.py (the "morris_lisp" kernel -- see install_lisp_kernel.py):
charts are drawn inline with matplotlib, display-table shows a table (as
Markdown), and display-markdown renders Markdown. get_env() holds the
one environment a kernel uses for its whole life.

The tastytrade-* and sofr-calibration-data builtins work here too: a
Jupyter kernel already has an asyncio event loop running, which
_run_async() in lisp_tastytrade.py handles."""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lisp_builtins import load_init_file, make_global_env, markdown_table, print_table
from lisp_charts import chart_summary_text, draw_chart_on_axes

try:
    # Figure and FigureCanvasAgg rather than pyplot: pyplot's backend may be
    # an interactive one that opens a window and blocks the cell. Drawing
    # straight to a PNG works the same in every notebook.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False

try:
    from IPython.display import display as _ipy_display
    from IPython.display import Image as _ipy_image
    _IPYTHON_AVAILABLE = True
except ImportError:
    _IPYTHON_AVAILABLE = False


def _notebook_output(text):
    """display/newline/print -- plain stdout. Jupyter captures a cell's
    stdout automatically; no special handling needed."""
    print(text, end="")


def _print_chart_summary(spec):
    """The no-matplotlib fallback: the same one-line-per-series summary the
    console prints, so a notebook without matplotlib still gets SOME
    feedback from plot-xy/plot-xy-regression/plot-xy-full."""
    print(chart_summary_text(spec), end="")


def _notebook_plot(spec):
    """plot-xy... -- draw the chart inline, as a PNG image. Falls back to the
    console's text summary without matplotlib or IPython."""
    if not (_MATPLOTLIB_AVAILABLE and _IPYTHON_AVAILABLE):
        _print_chart_summary(spec)
        return
    fig = Figure(figsize=(6, 4))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    draw_chart_on_axes(fig, ax, spec)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    _ipy_display(_ipy_image(data=buf.getvalue()))


def _notebook_table(columns):
    """display-table -- shown as a Markdown table (numbers right-aligned),
    or, without IPython, as the console's plain text table."""
    if _IPYTHON_AVAILABLE:
        from IPython.display import Markdown
        _ipy_display(Markdown(markdown_table(columns)))
    else:
        print_table(columns, lambda text: print(text, end=""))


def _notebook_markdown(text):
    """display-markdown -- rendered as Markdown (tables, headings, ...)
    via IPython.display.Markdown; plain text if IPython isn't available."""
    if _IPYTHON_AVAILABLE:
        from IPython.display import Markdown
        _ipy_display(Markdown(text))
    else:
        print(text)


_env = None


def get_env():
    """The environment every cell of this kernel runs in, created (with
    init.lsp loaded) the first time it's needed. Restarting the kernel
    starts a new process, and so a new environment."""
    global _env
    if _env is None:
        _env = make_global_env(output=_notebook_output, plot=_notebook_plot,
                               table=_notebook_table, markdown=_notebook_markdown)
        load_init_file(_env)
    return _env
