"""Charts for the Lisp interpreter: the plot- builtins and save-chart.
The charts themselves are plot-chart, plot-histogram, and plot-panels, in
lisp_plot_chart.py, and plot-map, in lisp_maps.py.

A chart goes through two steps:
  1. A builder turns Lisp values into a plain-data "chart spec", a dict
     (no plotting library involved).
  2. Whoever receives the spec draws it: the GUI's chart tab, a Jupyter
     cell, or the console (which just prints a summary). Drawing with
     matplotlib is shared by all of them through draw_chart_on_axes(), so
     the on-screen chart and a saved image always match.

Only matplotlib is needed to draw or save a chart -- not PyQt6.
"""

from lisp_core import LispError, NIL
import lisp_maps
import lisp_plot_chart

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Drawing a chart spec with matplotlib
# ---------------------------------------------------------------------------

def draw_chart_on_axes(fig, ax, spec):
    """Draw a chart spec onto an existing Matplotlib Figure and Axes:
    plot-chart's, plot-histogram's, and plot-panels' with lisp_plot_chart,
    and plot-map's with lisp_maps. Pure matplotlib -- no Qt."""
    # The GUI draws every chart on the same figure and axes: first, undo
    # what an earlier chart did to them -- secondary axes, panels, and color
    # bars added, ax moved to the top panel and brought to the front, a
    # figure title, a map's equal scales and hidden axes.
    for other in list(fig.axes):
        if other is not ax:
            other.remove()
    ax.set_subplotspec(fig.add_gridspec(1, 1)[0])
    ax.set_zorder(0)
    ax.set_aspect("auto")
    ax.set_axis_on()
    fig.suptitle("")
    if spec.get("kind") == "map":
        lisp_maps.draw(fig, ax, spec)
    else:
        lisp_plot_chart.draw(fig, ax, spec)


def render_chart_to_file(spec, path, width=None, height=None, dpi=150):
    """Render a chart spec to a standalone image file (PNG, PDF, SVG, ...
    -- whatever matplotlib recognizes from the file extension). Uses a
    throwaway headless Figure, so this works with or without a GUI running.
    Its size, in inches, is width by height if they're given, or else the
    chart's own (plot-chart's :width and :height), or else 8 by 6."""
    if not MATPLOTLIB_AVAILABLE:
        raise LispError("save-chart: matplotlib is not installed (pip install matplotlib)")
    width = width or spec.get("width") or 8.0
    height = height or spec.get("height") or 6.0
    fig = Figure(figsize=(width, height), dpi=dpi)
    FigureCanvasAgg(fig)  # attach a headless (non-interactive) canvas
    ax = fig.add_subplot(111)
    draw_chart_on_axes(fig, ax, spec)
    try:
        fig.savefig(path)
    except Exception as e:
        raise LispError("save-chart: could not save %r: %s" % (path, e))


# ---------------------------------------------------------------------------
# The Lisp-callable chart builtins
# ---------------------------------------------------------------------------

def make_chart_builtins(plot):
    """The plot- and save-chart builtins for one environment. `plot` is
    that environment's callback: it receives each new chart spec and
    shows it (in the GUI's chart tab, a Jupyter cell, or as a console
    summary). The most recent spec is remembered so save-chart can render
    it to a file without being given the data again."""
    last_chart = {"spec": None}

    def show(spec):
        last_chart["spec"] = spec
        plot(spec)
        return NIL

    def plot_chart(series, *options):
        return show(lisp_plot_chart.build_plot_chart_spec(series, options))

    def plot_histogram(data, *options):
        return show(lisp_plot_chart.build_histogram_spec(data, options))

    def plot_panels(panels, *options):
        return show(lisp_plot_chart.build_panels_spec(panels, options))

    def plot_map(shapes, *options):
        return show(lisp_maps.build_map_spec(shapes, options))

    def save_chart(filename, width=NIL, height=NIL, dpi=150.0):
        if last_chart["spec"] is None:
            raise LispError("save-chart: no chart has been plotted yet (call plot-chart, "
                            "or another plot- function, first)")
        render_chart_to_file(last_chart["spec"], str(filename),
                             None if width is NIL else float(width), None if height is NIL else float(height),
                             int(dpi))
        return NIL

    return {
        "plot-chart": plot_chart,
        "plot-histogram": plot_histogram,
        "plot-panels": plot_panels,
        "plot-map": plot_map,
        "save-chart": save_chart,
    }


def chart_summary_text(spec):
    """A plain-text description of a chart spec -- what the console and a
    notebook without matplotlib show instead of drawing the chart."""
    if spec.get("kind") == "map":
        return lisp_maps.summary_text(spec)
    return lisp_plot_chart.summary_text(spec)
