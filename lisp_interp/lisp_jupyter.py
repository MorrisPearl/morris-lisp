"""
lisp_jupyter.py
================
Run the morris_lisp interpreter (lisp_interpreter.py) inside a Jupyter
notebook, with no PyQt6 GUI involved at all: charts render inline via
matplotlib, and (display-columns ...) output renders as a pandas
DataFrame (a real HTML table) instead of the console's plain text table.
This module itself only wires up the output/plot/columns callbacks
make_global_env() already accepts -- it doesn't touch lisp_interpreter.py.
The tastytrade-*/sofr-*  builtins DO need one thing from lisp_interpreter.
py itself to work correctly here, already in place: they run their
network I/O via asyncio, and asyncio.run() can't be called again from
inside a thread that already has its OWN running event loop -- which is
exactly what a Jupyter/IPython kernel has. See _run_async() in
lisp_interpreter.py (and its twin in term_structure/sofr_market_data.py)
-- both fall back to running the coroutine on a separate thread with its
own fresh loop instead of failing outright, so every tastytrade-*/sofr-*
builtin still just returns a plain value here, synchronously, exactly as
it does from the console REPL/GUI/a plain script.

Usage
-----
As a cell magic (nicest -- run this once per notebook):
    %load_ext lisp_jupyter

then, in any cell:
    %%lisp
    (define x (vector 1 2 3))
    (display-columns (list (cons "x" x)))

As a plain function (works anywhere -- a plain .py script, a notebook
that skipped %load_ext, a non-IPython REPL):
    from lisp_jupyter import lisp
    lisp("(define x 10)")
    lisp("(+ x 5)")             ; => prints 15, the way the console REPL would

Both share ONE persistent environment (module-level, created lazily on
first use, with init.lsp already loaded) -- exactly like typing into the
console REPL, so a definition from one cell is visible in the next. Call
reset() to discard it and start fresh (e.g. after editing column_engine.
lsp/prepayment_model.lsp/etc. on disk and wanting a clean (load ...)).

Only the LAST top-level form in a `%%lisp` cell (or a `lisp(...)` call)
has its value printed -- matching how a Jupyter/IPython cell shows only
its last expression's value, not every intermediate one -- and it's
skipped entirely when that value is '() (e.g. a cell that ends with
display/write-columns-csv/calculate-all, all of which return '() and
already produce their own output), so cells don't end with a stray "()".
A LispError (or any other exception) is caught and printed as "Error:
...", the same as the console REPL and GUI already do, instead of
surfacing a raw Python traceback full of interpreter internals.
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lisp_interpreter as L

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
    """The same plain-text chart summary make_global_env()'s own
    console-mode default produces -- used here as the no-matplotlib
    fallback, so a notebook without matplotlib installed still gets
    SOME feedback from plot-xy/plot-xy-regression/plot-xy-full instead
    of a silent no-op."""
    lines = ["[chart] %s" % spec["title"]]
    for s in spec["series"]:
        how = "connected" if s["connect"] else "points only"
        lines.append("  %s: %d points (%s)" % (s["label"], len(s["y"]), how))
    if spec.get("regression"):
        r = spec["regression"]
        lines.append(
            "  %s regression on %s: slope=%.6g intercept=%.6g"
            % (r["kind"], r["label"], r["model"].coefficients[0], r["model"].intercept))
    print("\n".join(lines))


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
    L.draw_chart_on_axes(fig, ax, spec)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    _ipy_display(_ipy_image(data=buf.getvalue()))


def _print_columns_table(name_value_pairs):
    """The no-pandas/no-IPython fallback: the same right-justified plain
    text table make_global_env()'s own console-mode default produces."""
    names = [name for name, _ in name_value_pairs]
    rows = max((len(values) for _, values in name_value_pairs), default=0)
    widths = [max([len(name)] + [len(str(v)) for v in values])
              for name, values in name_value_pairs]

    def row(cells):
        return "  ".join(str(c).rjust(w) for c, w in zip(cells, widths))

    lines = [row(names)]
    for i in range(rows):
        lines.append(row(values[i] if i < len(values) else ""
                          for _, values in name_value_pairs))
    print("\n".join(lines))


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


_env = None


def get_env():
    """The persistent environment shared by every lisp(...) call and
    every %%lisp cell -- created lazily on first use, with init.lsp
    already loaded (same as the console REPL/batch mode/GUI all do)."""
    global _env
    if _env is None:
        _env = L.make_global_env(output=_notebook_output, plot=_notebook_plot,
                                  columns=_notebook_columns)
        L.load_init_file(_env)
    return _env


def reset():
    """Discard the current environment; the next lisp(...) call/%%lisp
    cell starts fresh (init.lsp reloaded, every prior definition gone)
    -- handy after editing a .lsp file on disk, or just to get back to a
    known-clean state without restarting the whole kernel."""
    global _env
    _env = None


def lisp(code):
    """Evaluate one or more top-level Lisp forms (a plain Python string
    of Lisp source) against the shared notebook environment. Prints the
    LAST form's value the way the console REPL would -- skipped when
    that value is '() -- and returns that same value, so `x = lisp("(+ 1
    2)")` works too. A LispError (or any other exception) is caught and
    printed as "Error: ..." rather than raising a raw Python traceback."""
    env = get_env()
    result = L.NIL
    try:
        for expr in L.parse(code):
            result = L.seval(expr, env)
    except L.LispError as e:
        print("Error:", e)
        return None
    except Exception as e:
        print("Error:", e)
        return None
    if result is not L.NIL:
        print(L.to_string(result))
    return result


def _lisp_cell_magic(line, cell):
    """The actual %%lisp cell-magic implementation -- registered under
    the name `lisp` (not this function's own name) by
    load_ipython_extension(), below, via register_magic_function()."""
    return lisp(cell)


def load_ipython_extension(ipython):
    """Called by `%load_ext lisp_jupyter` -- registers %%lisp as a cell
    magic. Nothing is registered just from `import lisp_jupyter` alone;
    %load_ext is the standard, explicit way every IPython extension
    opts into this, so there's no surprise magic appearing just because
    some other import happened to pull this module in."""
    ipython.register_magic_function(_lisp_cell_magic, magic_kind="cell", magic_name="lisp")
