"""XY charts for the Lisp interpreter: plot-xy, plot-xy-regression,
plot-xy-full, plot-chart, and save-chart.

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
import math

from lisp_core import LispDate, LispError, LispVector, NIL, Pair, is_true, numeric_value, pairs_to_list
from lisp_regression import fit_linear, fit_logistic
from lisp_stratify import keyword_options

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.dates
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
# plot-chart: several (X, Y) series on one X axis, as symbols, lines, or bars
# ---------------------------------------------------------------------------
#
# Each series has its own X values. They all go on one axis: dates on a
# calendar (so monthly and quarterly series line up by date), numbers on a
# number line, or text as categories, in the order they first appear. Bars
# at the same X are side by side ("grouped") or on top of each other
# ("stacked").

# The symbols a series can be drawn with, by name: matplotlib's marker codes.
SYMBOLS = {"circle": "o", "square": "s", "triangle": "^", "diamond": "D", "down-triangle": "v",
           "plus": "+", "x": "x", "star": "*", "dot": "."}
SYMBOL_ORDER = ["circle", "square", "triangle", "diamond", "down-triangle", "plus", "x", "star"]   # for :symbol #t
LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-."}
LEGEND_PLACES = ["best", "upper right", "upper left", "lower left", "lower right", "right",
                 "center left", "center right", "lower center", "upper center", "center"]

# plot-chart's options for the whole chart, with their defaults.
CHART_DEFAULTS = {"title": "", "x-label": "", "y-label": "", "legend": True, "bars": "grouped",
                  "bar-width": 0.8, "line-width": 1.5, "symbol-size": 6, "grid": True}
# The options each series can have.
SERIES_OPTIONS = ["symbol", "line", "bars", "color", "line-width", "symbol-size"]


def is_off(value):
    """Whether an option is turned off: #f or '()."""
    return value is False or value is NIL


def values_of(value, who, what):
    """A vector's or a list's values, as a Python list."""
    if isinstance(value, LispVector):
        return value.items.tolist()
    if value is NIL or isinstance(value, Pair):
        return pairs_to_list(value)
    raise LispError("%s: %s must be a vector or a list" % (who, what))


def kind_of_x(x, who):
    """What kind of X value x is: "date", "number", or "text"."""
    if isinstance(x, LispDate):
        return "date"
    if isinstance(x, str):
        return "text"
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return "number"
    raise LispError("%s: an X value must be a date, a number, or text, not %r" % (who, x))


def is_missing(value):
    return value is None or value is NIL or (isinstance(value, float) and math.isnan(value))


def chosen_symbol(value, number, who):
    """A series' :symbol -- a name, #t for the next one in SYMBOL_ORDER, or
    #f for none -- as a name or None."""
    if is_off(value):
        return None
    if value is True:
        return SYMBOL_ORDER[number % len(SYMBOL_ORDER)]
    if str(value) not in SYMBOLS:
        raise LispError("%s: there's no symbol %r -- the symbols are %s" % (who, str(value), ", ".join(SYMBOLS)))
    return str(value)


def chosen_line(value, who):
    """A series' :line -- a style, #t for solid, or #f for none -- as a style
    name or None."""
    if is_off(value):
        return None
    if value is True:
        return "solid"
    if str(value) not in LINE_STYLES:
        raise LispError("%s: there's no line style %r -- the styles are %s"
                        % (who, str(value), ", ".join(LINE_STYLES)))
    return str(value)


def series_spec(entry, number, chart, who):
    """One series of plot-chart -- a list (name x y [options]) -- as a dict
    of its points and how to draw them. Points with a missing X or Y are
    left out."""
    items = pairs_to_list(entry) if isinstance(entry, Pair) else []
    if len(items) < 3:
        raise LispError('%s: each series is a list (name x y [options]), such as (list "CPI" dates cpi '
                        ':symbol "circle") -- not %r' % (who, entry))
    name = str(items[0])
    x_values, y_values = values_of(items[1], who, "X"), values_of(items[2], who, "Y")
    if len(x_values) != len(y_values):
        raise LispError("%s: series %s has %d X values but %d Y values" % (who, name, len(x_values), len(y_values)))
    options = keyword_options(items[3:], SERIES_OPTIONS, who)
    if not any(k in options for k in ("symbol", "line", "bars")):
        options["line"] = True                     # with none of them, a series is a line

    kind, xs, ys = None, [], []
    for x, y in zip(x_values, y_values):
        if is_missing(x) or is_missing(y):
            continue
        if not isinstance(y, (int, float)) or isinstance(y, bool):
            raise LispError("%s: series %s has a Y value that isn't a number: %r" % (who, name, y))
        if kind is None:
            kind = kind_of_x(x, who)
        elif kind_of_x(x, who) != kind:
            raise LispError("%s: series %s's X values are a mix of %s and %s"
                            % (who, name, kind_of_x(x, who), kind))
        xs.append(x.date if isinstance(x, LispDate) else str(x) if isinstance(x, str) else float(x))
        ys.append(float(y))

    bars = not is_off(options.get("bars", False))
    if bars and len(set(xs)) < len(xs):
        raise LispError("%s: series %s has bars, so it can have only one Y value for each X" % (who, name))
    return {"label": name,
            "x_kind": kind,
            "x": xs,
            "y": ys,
            "symbol": chosen_symbol(options.get("symbol", False), number, who),
            "line": chosen_line(options.get("line", False), who),
            "bars": bars,
            "color": None if is_off(options.get("color", False)) else str(options["color"]),
            "line_width": float(options.get("line-width", chart["line-width"])),
            "symbol_size": float(options.get("symbol-size", chart["symbol-size"]))}


def build_plot_chart_spec(series, options, who="plot-chart"):
    """The chart spec for plot-chart: its series (a Lisp list of series
    lists) and its options for the whole chart (see CHART_DEFAULTS)."""
    chart = dict(CHART_DEFAULTS)
    chart.update(keyword_options(options, list(CHART_DEFAULTS), who))
    if chart["bars"] not in ("grouped", "stacked"):
        raise LispError('%s: :bars must be "grouped" or "stacked"' % who)
    if not 0 < float(chart["bar-width"]) <= 1:
        raise LispError("%s: :bar-width is the share of the room between X values the bars take: "
                        "more than 0, and 1 at most" % who)
    legend = chart["legend"]
    if not (legend is True or is_off(legend) or str(legend) in LEGEND_PLACES):
        raise LispError("%s: :legend is #t, #f, or a place: %s" % (who, ", ".join(LEGEND_PLACES)))

    entries = values_of(series, who, "the series")
    if not entries:
        raise LispError("%s: there are no series to plot" % who)
    specs = [series_spec(entry, i, chart, who) for i, entry in enumerate(entries)]
    kinds = {s["x_kind"] for s in specs if s["x_kind"]}
    if len(kinds) > 1:
        raise LispError("%s: the X values must be all dates, all numbers, or all text -- these have %s"
                        % (who, " and ".join(sorted(kinds))))
    kind = kinds.pop() if kinds else "number"
    # Text X values are categories, in the order they first appear (a dict keeps that order).
    categories = list(dict.fromkeys(x for s in specs for x in s["x"])) if kind == "text" else []

    return {"kind": "plot-chart",
            "title": str(chart["title"]),
            "x_label": str(chart["x-label"]),
            "y_label": str(chart["y-label"]),
            "x_kind": kind,
            "categories": categories,
            "series": specs,
            "bars": str(chart["bars"]),
            "bar_width": float(chart["bar-width"]),
            "legend": None if is_off(legend) else ("best" if legend is True else str(legend)),
            "grid": not is_off(chart["grid"])}


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
    if spec.get("kind") == "plot-chart":
        draw_plot_chart(fig, ax, spec)
        return
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


def x_positions(spec, xs):
    """Where X values go on the axis, as numbers: dates as matplotlib's day
    numbers, text as its category's number (0, 1, 2, ...)."""
    if spec["x_kind"] == "date":
        return [float(p) for p in matplotlib.dates.date2num(xs)]
    if spec["x_kind"] == "text":
        number_of = {category: i for i, category in enumerate(spec["categories"])}
        return [number_of[x] for x in xs]
    return list(xs)


def bar_room(spec, bar_series):
    """The room the bars at one X take: bar_width of the smallest gap between
    two neighboring X values that have bars."""
    positions = sorted({p for s in bar_series for p in x_positions(spec, s["x"])})
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    return spec["bar_width"] * (min(gaps) if gaps else 1.0)


def draw_plot_chart(fig, ax, spec):
    """Draw a plot-chart spec: each series' bars, then its line and symbols,
    in its own color."""
    ax.clear()
    if spec["x_kind"] == "date":
        ax.xaxis_date()
    bar_series = [s for s in spec["series"] if s["bars"]]
    room = bar_room(spec, bar_series)
    stack_tops = {}         # stacked bars: X -> (top of the bars above 0, bottom of those below 0)

    for i, s in enumerate(spec["series"]):
        color = s["color"] or "C%d" % i          # matplotlib's colors, in order
        xs = x_positions(spec, s["x"])
        if s["bars"] and spec["bars"] == "stacked":
            bottoms = []
            for x, y in zip(xs, s["y"]):
                above, below = stack_tops.get(x, (0.0, 0.0))
                bottoms.append(above if y >= 0 else below)
                stack_tops[x] = (above + y, below) if y >= 0 else (above, below + y)
            ax.bar(xs, s["y"], width=room, bottom=bottoms, color=color, label=s["label"])
        elif s["bars"]:                          # grouped: side by side, in the order of the series
            width = room / len(bar_series)
            offset = (bar_series.index(s) - (len(bar_series) - 1) / 2) * width
            ax.bar([x + offset for x in xs], s["y"], width=width, color=color, label=s["label"])
        if s["line"] or s["symbol"]:
            points = sorted(zip(xs, s["y"]))     # a line goes from left to right
            ax.plot([x for x, _ in points], [y for _, y in points], color=color,
                    linestyle=LINE_STYLES[s["line"]] if s["line"] else "None", linewidth=s["line_width"],
                    marker=SYMBOLS[s["symbol"]] if s["symbol"] else "None", markersize=s["symbol_size"],
                    label=None if s["bars"] else s["label"])     # a series with bars is in the legend once

    if bar_series:
        ax.axhline(0, color="black", linewidth=0.8)
    if spec["x_kind"] == "text":
        ax.set_xticks(range(len(spec["categories"])))
        ax.set_xticklabels(spec["categories"])
        if len(spec["categories"]) > 6:
            for label in ax.get_xticklabels():
                label.set_rotation(45)
                label.set_horizontalalignment("right")
    ax.set_title(spec["title"])
    ax.set_xlabel(spec["x_label"])
    ax.set_ylabel(spec["y_label"])
    if spec["grid"]:
        ax.grid(True, alpha=0.3)
    if spec["legend"]:
        ax.legend(loc=spec["legend"])
    if spec["x_kind"] == "date":
        fig.autofmt_xdate()
    fig.tight_layout()          # room for slanted labels


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

    def plot_chart(series, *options):
        return show(build_plot_chart_spec(series, options))

    def save_chart(filename, width=8.0, height=6.0, dpi=150.0):
        if last_chart["spec"] is None:
            raise LispError("save-chart: no chart has been plotted yet (call plot-xy, "
                            "plot-xy-regression, plot-xy-full, or plot-chart first)")
        render_chart_to_file(last_chart["spec"], str(filename), float(width), float(height), int(dpi))
        return NIL

    return {
        "plot-xy": plot_xy,
        "plot-xy-regression": plot_xy_regression,
        "plot-xy-full": plot_xy_full,
        "plot-chart": plot_chart,
        "save-chart": save_chart,
    }


def chart_summary_text(spec):
    """A plain-text description of a chart spec -- what the console and a
    notebook without matplotlib show instead of drawing the chart."""
    if spec.get("kind") == "plot-chart":
        lines = [("[chart] " + spec["title"]).rstrip()]
        for s in spec["series"]:
            how = [what for what, drawn in (("symbols", s["symbol"]), ("line", s["line"]), ("bars", s["bars"]))
                   if drawn]
            lines.append("  %s: %d points (%s)" % (s["label"], len(s["y"]), ", ".join(how)))
        return "\n".join(lines) + "\n"
    lines = ["[chart] %s" % spec["title"]]
    for s in spec["series"]:
        how = "connected" if s["connect"] else "points only"
        lines.append("  %s: %d points (%s)" % (s["label"], len(s["y"]), how))
    if spec.get("regression"):
        r = spec["regression"]
        lines.append("  %s regression on %s: slope=%.6g intercept=%.6g"
                     % (r["kind"], r["label"], r["model"].coefficients[0], r["model"].intercept))
    return "\n".join(lines) + "\n"
