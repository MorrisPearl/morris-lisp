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
    import matplotlib.ticker
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
# ("stacked"). A series can be on a secondary axis, with its own scale; a
# chart can be horizontal, with the X values up the side and the bars
# going across. Each axis of Y values can have limits, a log scale, and
# ticks at round numbers.

# The symbols a series can be drawn with, by name: matplotlib's marker codes.
SYMBOLS = {"circle": "o", "square": "s", "triangle": "^", "diamond": "D", "down-triangle": "v",
           "plus": "+", "x": "x", "star": "*", "dot": "."}
SYMBOL_ORDER = ["circle", "square", "triangle", "diamond", "down-triangle", "plus", "x", "star"]   # for :symbol #t
LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-."}
LEGEND_PLACES = ["best", "upper right", "upper left", "lower left", "lower right", "right",
                 "center left", "center right", "lower center", "upper center", "center"]

# plot-chart's options for the whole chart, with their defaults.
CHART_DEFAULTS = {"title": "", "x-label": "", "y-label": "", "secondary-label": "", "legend": True,
                  "bars": "grouped", "bar-width": 0.8, "line-width": 1.5, "symbol-size": 6, "grid": True,
                  "horizontal": False, "width": None, "height": None,
                  "y-min": None, "y-max": None, "y-ticks": None, "y-log": False,
                  "secondary-min": None, "secondary-max": None, "secondary-ticks": None, "secondary-log": False}
# A log scale has at most this many ticks, unless :y-ticks says.
MOST_LOG_TICKS = 8
# The options each series can have.
SERIES_OPTIONS = ["symbol", "line", "bars", "color", "line-width", "symbol-size", "secondary"]
# A horizontal chart of categories is made this tall, in inches, for each
# category (plus room for the title and axis), unless :height says.
INCHES_PER_CATEGORY = 0.25


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
            "secondary": not is_off(options.get("secondary", False)),
            "line_width": float(options.get("line-width", chart["line-width"])),
            "symbol_size": float(options.get("symbol-size", chart["symbol-size"]))}


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def value_axis_spec(chart, prefix, series_on_it, who):
    """The options for an axis of Y values -- prefix "y" for the primary
    one, "secondary" for the secondary one -- checked: its min, max, ticks
    (how many, or just where), and whether it has a log scale."""
    low, high, ticks = chart[prefix + "-min"], chart[prefix + "-max"], chart[prefix + "-ticks"]
    log = not is_off(chart[prefix + "-log"])
    for name, value in (("min", low), ("max", high)):
        if value is not None and not is_number(value):
            raise LispError("%s: :%s-%s must be a number" % (who, prefix, name))
    if low is not None and high is not None and low >= high:
        raise LispError("%s: :%s-min must be less than :%s-max" % (who, prefix, prefix))
    if is_number(ticks):
        if ticks < 2:
            raise LispError("%s: :%s-ticks is about how many ticks there are: 2 or more" % (who, prefix))
        ticks = int(ticks)
    elif ticks is not None:
        ticks = values_of(ticks, who, ":%s-ticks" % prefix)
        if not all(is_number(t) for t in ticks):
            raise LispError("%s: :%s-ticks is a number of ticks, or a list of where they go" % (who, prefix))
        ticks = [float(t) for t in ticks]
    if log:
        if low is not None and low <= 0:
            raise LispError("%s: a log scale's :%s-min must be more than 0" % (who, prefix))
        for s in series_on_it:
            if any(y <= 0 for y in s["y"]):
                raise LispError("%s: series %s has values of 0 or less, which a log scale can't show"
                                % (who, s["label"]))
    return {"min": None if low is None else float(low), "max": None if high is None else float(high),
            "ticks": ticks, "log": log}


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
    for name in ("width", "height"):
        if chart[name] is not None and not (isinstance(chart[name], (int, float)) and chart[name] > 0):
            raise LispError("%s: :%s is the chart's %s in inches: a number more than 0" % (who, name, name))

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
    horizontal = not is_off(chart["horizontal"])
    height = chart["height"]
    if height is None and horizontal and categories:
        height = max(4.0, 1.5 + INCHES_PER_CATEGORY * len(categories))     # room for every label

    return {"kind": "plot-chart",
            "title": str(chart["title"]),
            "x_label": str(chart["x-label"]),
            "y_label": str(chart["y-label"]),
            "secondary_label": str(chart["secondary-label"]),
            "horizontal": horizontal,
            "width": None if chart["width"] is None else float(chart["width"]),
            "height": None if height is None else float(height),
            "x_kind": kind,
            "categories": categories,
            "series": specs,
            "y_axis": value_axis_spec(chart, "y", [s for s in specs if not s["secondary"]], who),
            "secondary_axis": value_axis_spec(chart, "secondary", [s for s in specs if s["secondary"]], who),
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
    for other in list(fig.axes):        # a secondary axis an earlier plot-chart added, in the GUI
        if other is not ax:
            other.remove()
    ax.set_zorder(0)
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


def tick_text(value):
    """A tick's number, written plainly, with commas: 1,500 or 0.25 -- never
    1.5e3 -- with just the decimals it needs."""
    decimals = 0
    while decimals < 10 and abs(value - round(value, decimals)) > 1e-9 * max(1.0, abs(value)):
        decimals += 1
    value = round(value, decimals) or 0.0          # (and never "-0")
    return "{:,.{}f}".format(value, decimals)


def log_ticks(low, high, most):
    """Round numbers for a log scale from low to high, at most `most` of them:
    1, 2, 3, 5, 10, 20, 30, 50, ...; or, if that's too many, 1, 2, 5, 10,
    ...; or 1, 3, 10, 30, ...; or 1, 10, 100, ...; or every other power of
    10, and so on. If the range is too narrow for three of those, ordinary
    round numbers."""
    first, last = math.floor(math.log10(low)), math.ceil(math.log10(high))

    def multiples_of_powers(multiples, step=1):
        return [m * 10.0 ** p for p in range(first, last + 1, step) for m in multiples
                if low <= m * 10.0 ** p <= high]
    ticks = multiples_of_powers((1, 2, 3, 5))
    if len(ticks) < 3:
        return [t for t in matplotlib.ticker.MaxNLocator(nbins=most - 1, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high)
                if low <= t <= high]
    for multiples in ((1, 2, 3, 5), (1, 2, 5), (1, 3), (1,)):
        ticks = multiples_of_powers(multiples)
        if len(ticks) <= most:
            return ticks
    step = 2
    while len(multiples_of_powers((1,), step)) > most:
        step += 1
    return multiples_of_powers((1,), step)


def set_up_value_axis(axes, horizontal, scale):
    """Set up an axis of Y values -- the primary one or the secondary one
    -- as its spec says: a log scale, its limits, and its ticks."""
    if horizontal:
        axis, set_scale, set_limits, get_limits = axes.xaxis, axes.set_xscale, axes.set_xlim, axes.get_xlim
    else:
        axis, set_scale, set_limits, get_limits = axes.yaxis, axes.set_yscale, axes.set_ylim, axes.get_ylim
    if scale["log"]:
        set_scale("log")
    if scale["min"] is not None or scale["max"] is not None:
        set_limits(scale["min"], scale["max"])      # None: that end fits the data
    ticks = scale["ticks"]
    if isinstance(ticks, list):                     # just where they were asked for
        axis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))
    elif scale["log"]:
        low, high = sorted(get_limits())
        axis.set_major_locator(matplotlib.ticker.FixedLocator(log_ticks(low, high, ticks or MOST_LOG_TICKS)))
        axis.set_minor_formatter(matplotlib.ticker.NullFormatter())     # (just marks between them)
    elif ticks:                                     # about that many, at round numbers
        axis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=ticks, steps=[1, 2, 2.5, 5, 10]))
    axis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda value, position: tick_text(value)))


def stacked_bottoms(stack_tops, xs, ys):
    """Where stacked bars start: each on top of the bars already at its X
    (below them, if it's negative). stack_tops holds, for each X, the top of
    the bars above 0 and the bottom of those below 0; it's brought up to
    date."""
    bottoms = []
    for x, y in zip(xs, ys):
        above, below = stack_tops.get(x, (0.0, 0.0))
        bottoms.append(above if y >= 0 else below)
        stack_tops[x] = (above + y, below) if y >= 0 else (above, below + y)
    return bottoms


def draw_plot_chart(fig, ax, spec):
    """Draw a plot-chart spec: each series' bars, then its line and symbols,
    in its own color, on the primary axis or the secondary one. A
    horizontal chart has the X values up the side and the Y values across,
    so its bars go across."""
    ax.clear()
    horizontal = spec["horizontal"]
    if spec["x_kind"] == "date":
        if horizontal:
            ax.yaxis_date()
        else:
            ax.xaxis_date()
    secondary = None
    if any(s["secondary"] for s in spec["series"]):
        # A second scale for the Y values, sharing the X values' axis: on the right, or at the top.
        secondary = ax.twiny() if horizontal else ax.twinx()
    bar_series = [s for s in spec["series"] if s["bars"]]
    room = bar_room(spec, bar_series)
    stack_tops = {False: {}, True: {}}      # stacked bars, on each axis (see stacked_bottoms)
    legend_entries = []                     # (what's drawn, its label), in the order of the series

    for i, s in enumerate(spec["series"]):
        axes = secondary if s["secondary"] else ax
        color = s["color"] or "C%d" % i          # matplotlib's colors, in order
        label = s["label"]
        if s["secondary"]:
            label += " (top)" if horizontal else " (right)"
        xs = x_positions(spec, s["x"])
        if s["bars"]:
            if spec["bars"] == "stacked":
                positions, thickness = xs, room
                starts = stacked_bottoms(stack_tops[s["secondary"]], xs, s["y"])
            else:                                # grouped: side by side, in the order of the series
                thickness = room / len(bar_series)
                offset = (bar_series.index(s) - (len(bar_series) - 1) / 2) * thickness
                positions, starts = [x + offset for x in xs], [0.0] * len(xs)
            if horizontal:
                bars = axes.barh(positions, s["y"], height=thickness, left=starts, color=color)
            else:
                bars = axes.bar(positions, s["y"], width=thickness, bottom=starts, color=color)
            legend_entries.append((bars, label))
        if s["line"] or s["symbol"]:
            points = sorted(zip(xs, s["y"]))     # a line goes in order of X
            positions, values = [x for x, _ in points], [y for _, y in points]
            style = dict(color=color, linestyle=LINE_STYLES[s["line"]] if s["line"] else "None",
                         linewidth=s["line_width"], marker=SYMBOLS[s["symbol"]] if s["symbol"] else "None",
                         markersize=s["symbol_size"])
            if horizontal:
                line, = axes.plot(values, positions, **style)
            else:
                line, = axes.plot(positions, values, **style)
            if not s["bars"]:                    # a series with bars is in the legend once, as its bars
                legend_entries.append((line, label))

    for axes, is_secondary in ((ax, False), (secondary, True)):      # a line at 0 for bars
        log = spec["secondary_axis" if is_secondary else "y_axis"]["log"]
        if not log and any(s["bars"] and s["secondary"] == is_secondary for s in spec["series"]):
            if horizontal:
                axes.axvline(0, color="black", linewidth=0.8)
            else:
                axes.axhline(0, color="black", linewidth=0.8)

    set_up_value_axis(ax, horizontal, spec["y_axis"])
    if secondary:
        set_up_value_axis(secondary, horizontal, spec["secondary_axis"])
    if horizontal:
        ax.invert_yaxis()                        # the first X value at the top
    if spec["x_kind"] == "text":
        positions = range(len(spec["categories"]))
        if horizontal:
            ax.set_yticks(positions)
            ax.set_yticklabels(spec["categories"])
        else:
            ax.set_xticks(positions)
            ax.set_xticklabels(spec["categories"])
            if len(spec["categories"]) > 6:
                for tick_label in ax.get_xticklabels():
                    tick_label.set_rotation(45)
                    tick_label.set_horizontalalignment("right")

    ax.set_title(spec["title"])
    if horizontal:
        ax.set_ylabel(spec["x_label"])
        ax.set_xlabel(spec["y_label"])
        if secondary:
            secondary.set_xlabel(spec["secondary_label"])
    else:
        ax.set_xlabel(spec["x_label"])
        ax.set_ylabel(spec["y_label"])
        if secondary:
            secondary.set_ylabel(spec["secondary_label"])
    if spec["grid"]:
        ax.grid(True, alpha=0.3)

    # The secondary axis is drawn over the primary one. If it has bars, they'd
    # hide the primary axis's lines, so then the primary axis goes in front.
    front = secondary or ax
    if secondary and any(s["bars"] and s["secondary"] for s in spec["series"]):
        ax.set_zorder(secondary.get_zorder() + 1)
        ax.patch.set_visible(False)              # (so the secondary axis shows through)
        front = ax
    if spec["legend"]:                           # both axes' series, in one legend
        front.legend([drawn for drawn, _ in legend_entries], [label for _, label in legend_entries],
                     loc=spec["legend"])
    if spec["x_kind"] == "date" and not horizontal:
        fig.autofmt_xdate()
    fig.tight_layout()          # room for slanted labels


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

    def save_chart(filename, width=NIL, height=NIL, dpi=150.0):
        if last_chart["spec"] is None:
            raise LispError("save-chart: no chart has been plotted yet (call plot-xy, "
                            "plot-xy-regression, plot-xy-full, or plot-chart first)")
        render_chart_to_file(last_chart["spec"], str(filename),
                             None if width is NIL else float(width), None if height is NIL else float(height),
                             int(dpi))
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
            how = [what for what, drawn in (("symbols", s["symbol"]), ("line", s["line"]), ("bars", s["bars"]),
                                            ("on the secondary axis", s["secondary"])) if drawn]
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
