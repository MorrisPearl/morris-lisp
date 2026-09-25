"""
lisp_jupyter.py
================
Shared plumbing for running the morris_lisp interpreter inside a Jupyter
notebook with no PyQt6 GUI involved at all: charts render inline via
matplotlib, and (display-columns ...) renders as a pandas DataFrame (a
real HTML table) instead of the console's plain text table. This module
just supplies the output/plot/columns/markdown callbacks that
lisp_builtins.make_global_env() accepts.

Not meant to be used directly. lisp_kernel.py -- the native "morris_lisp"
Jupyter kernel (see install_lisp_kernel.py) -- is the supported way to use
this in a notebook: pick "morris_lisp" from Jupyter's kernel picker/New
menu, and every cell is plain Lisp source, no magic needed. It imports
this module for get_env() (the environment shared across a kernel's whole
lifetime) and the three callbacks below. (An earlier version of this file
also registered a `%%lisp` cell magic for running Lisp cells inside an
ordinary Python kernel; that approach was superseded by lisp_kernel.py and
has been removed.)

The tastytrade-*/sofr-* builtins need one thing to work correctly here,
already in place: they run their network I/O via asyncio, and
asyncio.run() can't be called again from inside a thread that already has
its OWN running event loop -- which is exactly what a Jupyter/IPython
kernel has. See _run_async() in lisp_tastytrade.py (and its twin in
term_structure/sofr_market_data.py)
-- both fall back to running the coroutine on a separate thread with its
own fresh loop instead of failing outright, so every tastytrade-*/sofr-*
builtin still just returns a plain value here, synchronously, exactly as
it does from the console REPL/GUI/a plain script.
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lisp_builtins import load_init_file, make_global_env, print_columns_table
from lisp_charts import chart_summary_text, draw_chart_on_axes

try:
    # matplotlib.figure.Figure directly, NOT pyplot -- pyplot's plt.show()
    # depends on whatever backend happens to be active (e.g. a plain
    # `ipykernel` without `%matplotlib inline` defaults to an
    # INTERACTIVE backend, so plt.show() opens a real window and BLOCKS
    # the cell until it's closed -- found by actually hitting this: a
    # test cell hung until a stray window was killed). Rendering
    # straight to a PNG buffer via Figure/FigureCanvasAgg and handing
    # THAT to IPython.display.Image sidesteps backend state entirely --
    # works the same whether or not %matplotlib inline was ever run.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False

try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False

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
    """plot-xy/plot-xy-regression/plot-xy-full -- renders INLINE in the
    notebook (via draw_chart_on_axes(), the same pure-matplotlib drawing
    code save-chart uses -- no Qt involved, and no dependency on pyplot's
    backend/`%matplotlib inline` state either -- see the Figure/
    FigureCanvasAgg import comment above for why) instead of needing a
    GUI chart tab or a save-chart call to a file. Falls back to a plain
    text summary if matplotlib isn't installed, or if IPython's rich
    display isn't available to hand the rendered image to."""
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


def _print_columns_table(name_value_pairs):
    """The no-pandas/no-IPython fallback: the console's plain text table."""
    print_columns_table(name_value_pairs, lambda text: print(text, end=""))


def _notebook_columns(name_value_pairs):
    """display-columns -- shown as a pandas DataFrame (a real HTML
    table, sortable/scrollable in the notebook) instead of the console's
    plain text table, when pandas and IPython are both available; falls
    back to that plain text table otherwise. Values arrive already
    rendered as display strings (see *column-number-format* / the
    `decimals` slot column_engine.lsp's column struct has) -- the exact
    same numbers you'd see in the GUI's Columns tab or the console
    fallback, just as a nicer table; NOT the raw underlying floats (use
    write-columns-csv, or read the column structs' own `series` vectors
    directly, if you want those for further analysis instead of
    display)."""
    if _PANDAS_AVAILABLE and _IPYTHON_AVAILABLE:
        df = pd.DataFrame({name: values for name, values in name_value_pairs})
        _ipy_display(df)
        return
    _print_columns_table(name_value_pairs)


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
    """The environment lisp_kernel.py's LispKernel evaluates every cell
    in -- created lazily on first use (once per kernel process, since
    this module-level `_env` starts fresh every time a new kernel
    process launches), with init.lsp already loaded (same as the
    console REPL/batch mode/GUI all do). There's no separate reset(): a
    Jupyter "Restart Kernel" already starts a brand-new lisp_kernel.py
    process -- and therefore a brand-new environment here -- so it
    already does exactly what a reset() would."""
    global _env
    if _env is None:
        _env = make_global_env(output=_notebook_output, plot=_notebook_plot,
                               columns=_notebook_columns, markdown=_notebook_markdown)
        load_init_file(_env)
    return _env
