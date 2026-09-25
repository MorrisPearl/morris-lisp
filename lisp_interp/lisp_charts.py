"""XY charts for the Lisp interpreter: plot-xy, plot-xy-regression,
plot-xy-full, and save-chart.

A chart goes through two steps:
  1. build_chart_spec() turns Lisp vectors into a plain-data "chart spec"
     dict (no plotting library involved).
  2. Whoever receives the spec draws it: the GUI's chart tab, a Jupyter
     cell, or the console (which just prints a one-line summary). Drawing
     with matplotlib is shared by all of them through draw_chart_on_axes(),
     so the on-screen chart and a saved image always match.

Only matplotlib is needed to draw or save a chart -- not PyQt6.
"""

import datetime

from lisp_core import LispDate, LispError, LispVector, NIL, is_true, numeric_value, pairs_to_list
from lisp_regression import fit_linear, fit_logistic

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Building a chart spec (pure data)
# ---------------------------------------------------------------------------
#
# Charts only ever plot against a single X vector (a 2-D chart has one X
# axis), so any regression line drawn on a chart is single-predictor, even
# though linear-regression/logistic-regression themselves support multiple
# predictors -- use model-report/model-evaluate for that case instead.

def build_chart_spec(x_vec, y_vecs, labels, connect, title, regression_label, regression_kind="linear"):
    """Build a plain-data chart description dict from Lisp values. This is
    consumed by the GUI's ChartCanvas.plot(), or by the console fallback
    plotter -- neither of those needs to know anything about Lisp."""
    if not isinstance(x_vec, LispVector):
        raise LispError("plot: x must be a vector")
    if not y_vecs:
        raise LispError("plot: at least one y-vector is required")
    if regression_kind not in ("linear", "logistic"):
        raise LispError('plot: regression kind must be "linear" or "logistic"')

    xs_raw = x_vec.items.tolist()
    n = len(xs_raw)
    x_is_date = any(isinstance(v, LispDate) for v in xs_raw)
    xs_plot = [v.date if isinstance(v, LispDate) else v for v in xs_raw]
    xs_numeric = [numeric_value(v) for v in xs_raw]

    series_list = []
    for i, y_vec in enumerate(y_vecs):
        if not isinstance(y_vec, LispVector):
            raise LispError("plot: each y must be a vector")
        if len(y_vec.items) != n:
            raise LispError("plot: every vector must be the same length as x")
        label = labels[i] if labels else ("Y%d" % (i + 1))
        series_list.append({"label": label, "y": y_vec.items.tolist(), "connect": connect})

    spec = {
        "title": title,
        "x_label": "X",
        "x_is_date": x_is_date,
        "x": xs_plot,
        "series": series_list,
        "regression": None,
    }

    if regression_label is not None:
        target = next((s for s in series_list if s["label"] == regression_label), None)
        if target is None:
            raise LispError("plot: no y-series labeled %r to run regression on" % (regression_label,))

        model = (fit_logistic([xs_numeric], target["y"]) if regression_kind == "logistic"
                 else fit_linear([xs_numeric], target["y"]))

        x_min, x_max = min(xs_numeric), max(xs_numeric)
        if regression_kind == "logistic":
            # The fitted curve is an S-shape, not a straight line, so
            # sample enough points across the x-range to draw it smoothly.
            steps = 100
            sample_xs_num = [x_min + (x_max - x_min) * i / (steps - 1) for i in range(steps)]
        else:
            sample_xs_num = [x_min, x_max]  # a straight line only needs two points
        sample_ys = [model.predict([xv]) for xv in sample_xs_num]
        if x_is_date:
            sample_xs_plot = [datetime.date.fromordinal(int(round(v))) for v in sample_xs_num]
        else:
            sample_xs_plot = sample_xs_num

        spec["regression"] = {
            "label": regression_label,
            "kind": regression_kind,
            "model": model,
            "x": sample_xs_plot,
            "y": sample_ys,
        }

    return spec


# ---------------------------------------------------------------------------
# Drawing a chart spec with matplotlib
# ---------------------------------------------------------------------------

# One marker shape per Y-series; cycles if there are more series than
# shapes. Matplotlib's own default color cycle distinguishes them too.
CHART_MARKERS = ["o", "s", "^", "D", "v", "P", "x", "*"]


def draw_chart_on_axes(fig, ax, spec):
    """Draw a chart spec (see build_chart_spec) onto an existing Matplotlib
    Figure/Axes: one X vector against one or more Y vectors, each with its
    own marker symbol and optionally connected by line segments, plus an
    optional dashed regression line/curve. Pure matplotlib -- no Qt."""
    ax.clear()

    xs = spec["x"]
    for i, s in enumerate(spec["series"]):
        marker = CHART_MARKERS[i % len(CHART_MARKERS)]
        linestyle = "-" if s["connect"] else "None"
        ax.plot(xs, s["y"], marker=marker, linestyle=linestyle,
                 markersize=7, label=s["label"])

    reg = spec.get("regression")
    if reg:
        model = reg["model"]
        label = "%s %s fit (slope=%.4g, intercept=%.4g)" % (
            reg["label"], reg["kind"], model.coefficients[0], model.intercept)
        ax.plot(reg["x"], reg["y"], linestyle="--", color="black",
                 linewidth=1.5, label=label)

    ax.set_xlabel(spec.get("x_label", "X"))
    ax.set_title(spec.get("title", "XY Chart"))
    ax.grid(True, alpha=0.3)
    ax.legend()
    if spec.get("x_is_date"):
        fig.autofmt_xdate()


def render_chart_to_file(spec, path, width=8.0, height=6.0, dpi=150):
    """Render a chart spec to a standalone image file (PNG, PDF, SVG, ...
    -- whatever matplotlib recognizes from the file extension). Uses a
    throwaway headless Figure, so this works with or without a GUI running."""
    if not MATPLOTLIB_AVAILABLE:
        raise LispError("save-chart: matplotlib is not installed (pip install matplotlib)")
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
    """The plot-xy.../save-chart builtins for one environment. `plot` is
    that environment's callback: it receives each new chart spec and
    shows it (in the GUI's chart tab, a Jupyter cell, or as a console
    summary). The most recent spec is remembered so save-chart can render
    it to a file without being given the data again."""
    last_chart = {"spec": None}

    def show(spec):
        last_chart["spec"] = spec
        plot(spec)
        return NIL

    def plot_xy(x_vec, y_list):
        y_vecs = pairs_to_list(y_list)
        return show(build_chart_spec(x_vec, y_vecs, labels=None, connect=True,
                                     title="XY Chart", regression_label=None))

    def plot_xy_regression(x_vec, y_vec, label, kind="linear"):
        label = str(label)
        kind = str(kind)
        return show(build_chart_spec(
            x_vec, [y_vec], labels=[label], connect=False,
            title="%s vs X, with %s regression" % (label, kind),
            regression_label=label, regression_kind=kind))

    def plot_xy_full(x_vec, y_list, label_list, connect_flag, title, regression_label,
                     regression_kind="linear"):
        y_vecs = pairs_to_list(y_list)
        labels = [str(s) for s in pairs_to_list(label_list)] if label_list is not NIL else None
        if labels is not None and len(labels) != len(y_vecs):
            raise LispError("plot-xy-full: the labels list must match the number of y-vectors")
        reg_label = None if regression_label is False else str(regression_label)
        return show(build_chart_spec(x_vec, y_vecs, labels, is_true(connect_flag),
                                     str(title), reg_label, str(regression_kind)))

    def save_chart(filename, width=8.0, height=6.0, dpi=150.0):
        if last_chart["spec"] is None:
            raise LispError("save-chart: no chart has been plotted yet (call plot-xy, "
                            "plot-xy-regression, or plot-xy-full first)")
        render_chart_to_file(last_chart["spec"], str(filename), float(width), float(height), int(dpi))
        return NIL

    return {
        "plot-xy": plot_xy,
        "plot-xy-regression": plot_xy_regression,
        "plot-xy-full": plot_xy_full,
        "save-chart": save_chart,
    }


def chart_summary_text(spec):
    """A plain-text description of a chart spec -- what the console and a
    notebook without matplotlib show instead of drawing the chart."""
    lines = ["[chart] %s" % spec["title"]]
    for s in spec["series"]:
        how = "connected" if s["connect"] else "points only"
        lines.append("  %s: %d points (%s)" % (s["label"], len(s["y"]), how))
    if spec.get("regression"):
        r = spec["regression"]
        lines.append("  %s regression on %s: slope=%.6g intercept=%.6g"
                     % (r["kind"], r["label"], r["model"].coefficients[0], r["model"].intercept))
    return "\n".join(lines) + "\n"
