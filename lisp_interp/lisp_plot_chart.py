"""plot-chart, plot-histogram, and plot-panels, for the Lisp interpreter.

plot-chart draws several (X, Y) series on one chart. Each series has its
own X values, and they all go on one axis: dates on a calendar (so
monthly and quarterly series line up by date), numbers on a number line,
or text as categories, in the order they first appear. Each series is
drawn with any combination of symbols, a line, bars, and a filled area;
bars at the same X are side by side ("grouped") or on top of each other
("stacked"). A series can be on a secondary axis, with its own scale. A
chart can be horizontal, with the X values down the side and the bars
going across. Each axis of Y values can have limits, a log scale, ticks
at round numbers, and a number format. A chart can also have reference
lines, shaded spans of X, notes, and the values printed on its bars or
points.

plot-histogram counts how many values fall in each bin and draws the
counts as a plot-chart of bars. plot-panels stacks several plot-charts in
one figure, sharing one X axis.

As with lisp_charts' other charts, each is made in two steps: a builder
turns the Lisp values into a plain-data spec (a dict, checked), and draw()
draws a spec with matplotlib -- for the GUI's chart tab, a Jupyter cell,
or save-chart.
"""

import datetime
import math

import numpy as np

from lisp_core import Keyword, LispDate, LispError, LispString, LispVector, NIL, Pair, keyword_options, list_to_pairs, pairs_to_list
from lisp_regression import fit_lad, fit_linear, fit_logistic

try:
    import matplotlib.dates
    import matplotlib.ticker
except ImportError:
    pass        # (lisp_charts checks for matplotlib before anything is drawn)


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
                  "x-min": None, "x-max": None, "x-format": None, "x-lines": NIL, "shade": NIL, "notes": NIL,
                  "y-min": None, "y-max": None, "y-ticks": None, "y-log": False, "y-format": None, "y-lines": NIL,
                  "secondary-min": None, "secondary-max": None, "secondary-ticks": None, "secondary-log": False,
                  "secondary-format": None, "secondary-lines": NIL}
# The options each series can have.
SERIES_OPTIONS = ["symbol", "line", "bars", "fill", "labels", "color", "line-width", "symbol-size", "secondary", "fit"]
FITS = ["linear", "lad", "logistic"]   # the regressions :fit can draw

MOST_LOG_TICKS = 8              # a log scale has at most this many ticks, unless :y-ticks says
INCHES_PER_CATEGORY = 0.25      # a horizontal chart of categories is this much taller for each one
FILL_OPACITY = 0.3              # a filled area lets what's behind it show through
SHADE_OPACITY = 0.15
REFERENCE_COLOR = "dimgray"     # reference lines' color, unless they say
SHADE_COLOR = "gray"


# ---------------------------------------------------------------------------
# Checking the options
# ---------------------------------------------------------------------------

def is_off(value):
    """Whether an option is turned off: #f or '()."""
    return value is False or value is NIL


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_missing(value):
    return value is None or value is NIL or (isinstance(value, float) and math.isnan(value))


def values_of(value, who, what):
    """A vector's or a list's values, as a Python list."""
    if isinstance(value, LispVector):
        return value.items.tolist()
    if value is NIL or isinstance(value, Pair):
        return pairs_to_list(value)
    raise LispError("%s: %s must be a vector or a list" % (who, what))


def entries_of(value):
    """An option's entries: those of a list or vector, or the one value
    it is. (A Python list is taken as it is.)"""
    if isinstance(value, list):
        return value
    if value is NIL or isinstance(value, Pair):
        return pairs_to_list(value)
    if isinstance(value, LispVector):
        return value.items.tolist()
    return [value]


def kind_of_x(x, who):
    """What kind of X value x is: "date", "number", or "text"."""
    if isinstance(x, LispDate):
        return "date"
    if isinstance(x, str):
        return "text"
    if is_number(x):
        return "number"
    raise LispError("%s: an X value must be a date, a number, or text, not %r" % (who, x))


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


def formatted_number(value, template):
    """value laid out by a format template such as "{:,.0f}". A format for
    whole numbers ("{:,d}") gets the value rounded to one."""
    value = round(value, 10) or 0.0                 # (and never "-0")
    try:
        return template.format(value)
    except ValueError:
        return template.format(int(round(value)))


def number_format(value, who, what):
    """A format for numbers -- a template such as "${:,.0f}" or "{:.1%}", or
    just a spec such as ",.0f" (as display-table takes) -- as a template;
    None if there isn't one."""
    if value is None or is_off(value):
        return None
    template = str(value) if "{" in str(value) else "{:" + str(value) + "}"
    try:
        formatted_number(1234.5, template)
    except (ValueError, IndexError, KeyError) as e:
        raise LispError('%s: %s %r isn\'t a format for numbers, such as ",.0f" or "${:,.0f}" (%s)'
                        % (who, what, str(value), e))
    return template


def series_spec(entry, number, chart, who):
    """One series -- a list (name x y [options]) -- as a dict of its points
    and how to draw them. Points with a missing X or Y (or a missing value
    for :fill to go to) are left out."""
    items = pairs_to_list(entry) if isinstance(entry, Pair) else []
    if len(items) < 3:
        raise LispError('%s: each series is a list (name x y [options]), such as (list "CPI" dates cpi '
                        ':symbol "circle") -- not %r' % (who, entry))
    name = str(items[0])
    x_values, y_values = values_of(items[1], who, "X"), values_of(items[2], who, "Y")
    if len(x_values) != len(y_values):
        raise LispError("%s: series %s has %d X values but %d Y values" % (who, name, len(x_values), len(y_values)))
    options = keyword_options(items[3:], SERIES_OPTIONS, who)
    if not any(k in options for k in ("symbol", "line", "bars", "fill")):
        options["line"] = True                     # with none of them, a series is a line

    fill = options.get("fill", False)              # #t: down to 0; values: to those
    if is_off(fill):
        fill_values = None
    elif fill is True:
        fill_values = [0.0] * len(x_values)
    else:
        fill_values = values_of(fill, who, ":fill")
        if len(fill_values) != len(x_values):
            raise LispError("%s: series %s's :fill has %d values, for %d X values"
                            % (who, name, len(fill_values), len(x_values)))

    kind, xs, ys, fill_to = None, [], [], []
    for j, (x, y) in enumerate(zip(x_values, y_values)):
        if is_missing(x) or is_missing(y) or (fill_values is not None and is_missing(fill_values[j])):
            continue
        if not is_number(y) or (fill_values is not None and not is_number(fill_values[j])):
            raise LispError("%s: series %s has a Y value that isn't a number: %r" % (who, name, y))
        if kind is None:
            kind = kind_of_x(x, who)
        elif kind_of_x(x, who) != kind:
            raise LispError("%s: series %s's X values are a mix of %s and %s"
                            % (who, name, kind_of_x(x, who), kind))
        xs.append(x.date if isinstance(x, LispDate) else str(x) if isinstance(x, str) else float(x))
        ys.append(float(y))
        if fill_values is not None:
            fill_to.append(float(fill_values[j]))

    fit = options.get("fit", False)
    if not is_off(fit) and str(fit) not in FITS:
        raise LispError('%s: :fit is "linear", "lad", or "logistic", not %r' % (who, fit))
    bars = not is_off(options.get("bars", False))
    if bars and len(set(xs)) < len(xs):
        raise LispError("%s: series %s has bars, so it can have only one Y value for each X" % (who, name))
    labels = options.get("labels", False)          # #t, or a format for them
    return {"label": name,
            "x_kind": kind,
            "x": xs,
            "y": ys,
            "symbol": chosen_symbol(options.get("symbol", False), number, who),
            "line": chosen_line(options.get("line", False), who),
            "bars": bars,
            "fill": fill_values is not None,
            "fill_to": fill_to,
            "labels": not is_off(labels),
            "label_format": None if is_off(labels) or labels is True else number_format(labels, who, ":labels"),
            "color": None if is_off(options.get("color", False)) else str(options["color"]),
            "secondary": not is_off(options.get("secondary", False)),
            "line_width": float(options.get("line-width", chart["line-width"])),
            "symbol_size": float(options.get("symbol-size", chart["symbol-size"])),
            "fit": None if is_off(fit) else str(fit)}


def fitted_line(s, who):
    """The series for the line fitted to series s by regression, from its
    smallest X value to its largest: the straight line of least squares for
    "linear", or of least absolute deviation for "lad" (which outliers barely
    move), or the S-shaped curve of a "logistic" regression (for Y values
    from 0 to 1), as a dashed black line."""
    if s["x_kind"] not in ("number", "date"):
        raise LispError("%s: series %s has :fit, which is for X values that are numbers or dates" % (who, s["label"]))
    is_date = s["x_kind"] == "date"
    xs = [x.toordinal() if is_date else x for x in s["x"]]
    fit = {"linear": fit_linear, "lad": fit_lad, "logistic": fit_logistic}[s["fit"]]
    model = fit([xs], s["y"])
    along = np.linspace(min(xs), max(xs), 100 if s["fit"] == "logistic" else 2)
    return dict(s, label="%s, %s fit" % (s["label"], s["fit"]),
                x=[datetime.date.fromordinal(int(round(x))) for x in along] if is_date else [float(x) for x in along],
                y=[float(model.predict([x])) for x in along],
                symbol=None, line="dashed", bars=False, fill=False, fill_to=[], labels=False, label_format=None,
                color="black", fit=None)


def y_value(value, who, what):
    if not is_number(value):
        raise LispError("%s: %s must be a number" % (who, what))
    return float(value)


def reference_lines(entries, convert, who, what):
    """The lines an option (:x-lines, :y-lines, :secondary-lines) asks for:
    each entry a value, or a list (value [label [color]]). convert checks a
    value and gives its Python form."""
    lines = []
    for entry in entries_of(entries):
        items = pairs_to_list(entry) if isinstance(entry, Pair) else [entry]
        if not 1 <= len(items) <= 3:
            raise LispError('%s: each %s entry is a value, or a list (value [label [color]]), such as '
                            '(list 2 "target")' % (who, what))
        lines.append({"at": convert(items[0], who, what),
                      "label": str(items[1]) if len(items) > 1 else "",
                      "color": str(items[2]) if len(items) > 2 else REFERENCE_COLOR})
    return lines


def value_axis_spec(chart, prefix, series_on_it, who):
    """The options for an axis of Y values -- prefix "y" for the primary
    one, "secondary" for the secondary one -- checked: its min, max, ticks
    (about how many, or just where), log scale, number format, and
    reference lines."""
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
            "ticks": ticks, "log": log,
            "format": number_format(chart[prefix + "-format"], who, ":%s-format" % prefix),
            "lines": reference_lines(chart[prefix + "-lines"], y_value, who, ":%s-lines" % prefix)}


def x_converter(kind, categories):
    """A function that checks an X value given in an option (:x-min,
    :x-lines, :shade, :notes) against the chart's X values, and gives its
    Python form."""
    def convert(value, who, what):
        if is_missing(value) or kind_of_x(value, who) != kind:
            raise LispError("%s: %s must be %s, like the chart's X values"
                            % (who, what, {"date": "a date", "number": "a number", "text": "a category"}[kind]))
        if kind == "date":
            return value.date
        if kind == "text":
            if str(value) not in categories:
                raise LispError("%s: %s: the chart has no category %r" % (who, what, str(value)))
            return str(value)
        return float(value)
    return convert


def shaded_spans(entries, convert, who):
    """The spans of X that :shade asks for: each a list (from to [label
    [color]])."""
    spans = []
    for entry in entries_of(entries):
        items = pairs_to_list(entry) if isinstance(entry, Pair) else []
        if not 2 <= len(items) <= 4:
            raise LispError('%s: each :shade entry is a list (from to [label [color]]), such as '
                            '(list (date 2020 2 1) (date 2020 4 1) "recession")' % who)
        spans.append({"from": convert(items[0], who, ":shade"), "to": convert(items[1], who, ":shade"),
                      "label": str(items[2]) if len(items) > 2 else "",
                      "color": str(items[3]) if len(items) > 3 else SHADE_COLOR})
    return spans


def chart_notes(entries, convert, who):
    """The notes :notes asks for: each a list (x y text), on the primary axis."""
    notes = []
    for entry in entries_of(entries):
        items = pairs_to_list(entry) if isinstance(entry, Pair) else []
        if len(items) != 3:
            raise LispError('%s: each :notes entry is a list (x y text), such as (list (date 2020 4 1) 14.8 "the '
                            'pandemic")' % who)
        notes.append({"x": convert(items[0], who, ":notes"), "y": y_value(items[1], who, ":notes"),
                      "text": str(items[2])})
    return notes


# ---------------------------------------------------------------------------
# Building the specs
# ---------------------------------------------------------------------------

def chart_spec(series, chart, who):
    """The spec for one chart: its series (a Lisp list of series lists) and
    its options (a dict with every name in CHART_DEFAULTS)."""
    if chart["bars"] not in ("grouped", "stacked"):
        raise LispError('%s: :bars must be "grouped" or "stacked"' % who)
    if not 0 < float(chart["bar-width"]) <= 1:
        raise LispError("%s: :bar-width is the share of the room between X values the bars take: "
                        "more than 0, and 1 at most" % who)
    legend = chart["legend"]
    if not (legend is True or is_off(legend) or str(legend) in LEGEND_PLACES):
        raise LispError("%s: :legend is #t, #f, or a place: %s" % (who, ", ".join(LEGEND_PLACES)))
    for name in ("width", "height"):
        if chart[name] is not None and not (is_number(chart[name]) and chart[name] > 0):
            raise LispError("%s: :%s is the chart's %s in inches: a number more than 0" % (who, name, name))

    entries = values_of(series, who, "the series")
    if not entries:
        raise LispError("%s: there are no series to plot" % who)
    specs = []
    for i, entry in enumerate(entries):
        specs.append(series_spec(entry, i, chart, who))
        if specs[-1]["fit"]:
            specs.append(fitted_line(specs[-1], who))              # (drawn right after it)
    kinds = {s["x_kind"] for s in specs if s["x_kind"]}
    if len(kinds) > 1:
        raise LispError("%s: the X values must be all dates, all numbers, or all text -- these have %s"
                        % (who, " and ".join(sorted(kinds))))
    kind = kinds.pop() if kinds else "number"
    # Text X values are categories, in the order they first appear (a dict keeps that order).
    categories = list(dict.fromkeys(x for s in specs for x in s["x"])) if kind == "text" else []
    convert_x = x_converter(kind, categories)
    x_limits = {}
    for name in ("x-min", "x-max"):
        if chart[name] is not None:
            if kind == "text":
                raise LispError("%s: :%s is for X values that are dates or numbers, not categories" % (who, name))
            x_limits[name] = convert_x(chart[name], who, ":" + name)
    x_format = number_format(chart["x-format"], who, ":x-format")
    if x_format and kind != "number":
        raise LispError("%s: :x-format is for X values that are numbers" % who)
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
            "x_min": x_limits.get("x-min"),
            "x_max": x_limits.get("x-max"),
            "x_format": x_format,
            "x_lines": reference_lines(chart["x-lines"], convert_x, who, ":x-lines"),
            "shade": shaded_spans(chart["shade"], convert_x, who),
            "notes": chart_notes(chart["notes"], convert_x, who),
            "y_axis": value_axis_spec(chart, "y", [s for s in specs if not s["secondary"]], who),
            "secondary_axis": value_axis_spec(chart, "secondary", [s for s in specs if s["secondary"]], who),
            "bars": str(chart["bars"]),
            "bar_width": float(chart["bar-width"]),
            "legend": None if is_off(legend) else ("best" if legend is True else str(legend)),
            "grid": not is_off(chart["grid"])}


def build_plot_chart_spec(series, options, who="plot-chart"):
    """The spec for (plot-chart series [options])."""
    chart = dict(CHART_DEFAULTS)
    chart.update(keyword_options(options, list(CHART_DEFAULTS), who))
    return chart_spec(series, chart, who)


def histogram_groups(data, who):
    """plot-histogram's data -- a vector or list of numbers, or a list of
    (name values [options]) lists -- as a list of (name, numbers, series
    options), leaving out missing values."""
    if isinstance(data, Pair) and isinstance(data.car, Pair):
        groups = []
        for entry in pairs_to_list(data):
            items = pairs_to_list(entry) if isinstance(entry, Pair) else []
            if len(items) < 2:
                raise LispError('%s: each group of values is a list (name values [options]), such as '
                                '(list "2024" returns)' % who)
            groups.append((str(items[0]), values_of(items[1], who, "the values"), items[2:]))
    else:
        groups = [("values", values_of(data, who, "the values"), [])]
    result = []
    for name, values, options in groups:
        numbers = [float(v) for v in values if not is_missing(v)]
        if not all(is_number(v) for v in values if not is_missing(v)):
            raise LispError("%s: %s has values that aren't numbers" % (who, name))
        result.append((name, numbers, options))
    return result


def build_histogram_spec(data, options, who="plot-histogram"):
    """The spec for (plot-histogram data [options]): a plot-chart of bars,
    one for each bin, as tall as the number of values in it (or their
    percent of all the values, with :percent #t)."""
    given = keyword_options(options, ["bins", "percent"] + list(CHART_DEFAULTS), who)
    bins = given.pop("bins", None)
    percent = not is_off(given.pop("percent", False))
    groups = histogram_groups(data, who)
    every_value = [v for _, numbers, _ in groups for v in numbers]
    if not every_value:
        raise LispError("%s: there are no values to count" % who)

    low = given.get("x-min", min(every_value))
    high = given.get("x-max", max(every_value))
    if not (is_number(low) and is_number(high)) or low > high:
        raise LispError("%s: :x-min and :x-max must be numbers, the first no more than the second" % who)
    if bins is None:
        bins = "auto"                               # numpy picks the number of bins
    elif is_number(bins):
        if bins < 1:
            raise LispError("%s: :bins is how many bins there are (1 or more), or a list of their edges" % who)
        bins = int(bins)
    else:
        bins = sorted(float(edge) for edge in values_of(bins, who, ":bins"))
        if len(bins) < 2:
            raise LispError("%s: a list of :bins edges needs at least 2" % who)
    edges = np.histogram_bin_edges(every_value, bins=bins, range=(float(low), float(high)))
    centers = list((edges[:-1] + edges[1:]) / 2)

    entries = []
    for name, numbers, series_options in groups:
        counts, _ = np.histogram(numbers, bins=edges)        # (values outside the edges aren't counted)
        if percent:
            heights = [100.0 * c / len(numbers) for c in counts] if numbers else [0.0] * len(counts)
        else:
            heights = [float(c) for c in counts]
        entries.append(list_to_pairs([LispString(name), LispVector(centers), LispVector(heights),
                                      Keyword(":bars"), True] + list(series_options)))
    chart = dict(CHART_DEFAULTS)
    chart.update({"bar-width": 1.0, "legend": len(groups) > 1, "y-label": "percent" if percent else "count"})
    chart.update(given)
    return chart_spec(list_to_pairs(entries), chart, who)


# plot-panels' options for the whole figure, with their defaults. Those
# about the X axis apply to every panel, since the panels share it.
PANELS_DEFAULTS = {"title": "", "x-label": "", "width": None, "height": None, "heights": NIL,
                   "x-min": None, "x-max": None, "x-format": None, "x-lines": NIL, "shade": NIL}
# The plot-chart options a panel can't have: they're the figure's.
FIGURE_ONLY_OPTIONS = ["x-label", "x-min", "x-max", "x-format", "horizontal", "width", "height"]
INCHES_PER_PANEL = 2.5


def build_panels_spec(panels, options, who="plot-panels"):
    """The spec for (plot-panels panels [options]): each panel a list
    (series [options]), which is what plot-chart takes. An option for a
    panel given to plot-panels is every panel's, unless the panel says
    otherwise."""
    panel_options = [name for name in CHART_DEFAULTS if name not in FIGURE_ONLY_OPTIONS]
    given = keyword_options(options, list(PANELS_DEFAULTS) + [n for n in panel_options if n not in PANELS_DEFAULTS],
                            who)
    figure = dict(PANELS_DEFAULTS)
    figure.update({name: value for name, value in given.items() if name in PANELS_DEFAULTS})
    every_panel = {name: value for name, value in given.items() if name not in PANELS_DEFAULTS}
    entries = values_of(panels, who, "the panels")
    if not entries:
        raise LispError("%s: there are no panels to draw" % who)
    specs = []
    for number, entry in enumerate(entries):
        items = pairs_to_list(entry) if isinstance(entry, Pair) else []
        if not items:
            raise LispError("%s: each panel is a list (series [options]), as plot-chart takes them" % who)
        chart = dict(CHART_DEFAULTS)
        chart.update(every_panel)
        chart.update(keyword_options(items[1:], panel_options, who))
        chart["x-label"] = figure["x-label"] if number == len(entries) - 1 else ""    # under the bottom panel
        chart["x-min"], chart["x-max"], chart["x-format"] = figure["x-min"], figure["x-max"], figure["x-format"]
        chart["x-lines"] = entries_of(figure["x-lines"]) + entries_of(chart["x-lines"])
        chart["shade"] = entries_of(figure["shade"]) + entries_of(chart["shade"])
        specs.append(chart_spec(items[0], chart, who))

    kinds = {s["x_kind"] for s in specs}
    if len(kinds) > 1:
        raise LispError("%s: the panels share one X axis, so their X values must be all dates, all numbers, "
                        "or all text" % who)
    if kinds == {"text"}:                           # every panel's categories, in the same places
        categories = list(dict.fromkeys(c for s in specs for c in s["categories"]))
        for s in specs:
            s["categories"] = categories
    heights = entries_of(figure["heights"]) or [1] * len(specs)
    if len(heights) != len(specs) or not all(is_number(h) and h > 0 for h in heights):
        raise LispError("%s: :heights is a list of the panels' heights, one for each, such as (list 2 1)" % who)
    for name in ("width", "height"):
        if figure[name] is not None and not (is_number(figure[name]) and figure[name] > 0):
            raise LispError("%s: :%s is the figure's %s in inches: a number more than 0" % (who, name, name))
    return {"kind": "panels",
            "title": str(figure["title"]),
            "width": None if figure["width"] is None else float(figure["width"]),
            "height": float(figure["height"] or (1 + INCHES_PER_PANEL * len(specs))),
            "heights": [float(h) for h in heights],
            "panels": specs}


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def draw(fig, ax, spec):
    """Draw a plot-chart (or plot-histogram) spec or a plot-panels spec on a
    figure whose only axes is ax."""
    if spec["kind"] == "panels":
        draw_panels(fig, ax, spec)
        dates_across = spec["panels"][0]["x_kind"] == "date"
    else:
        draw_chart(ax, spec)
        dates_across = spec["x_kind"] == "date" and not spec["horizontal"]
    if dates_across:
        fig.autofmt_xdate()                         # slanted, so they don't run together
    if spec["kind"] == "panels" and spec["title"]:
        # tight_layout leaves no room for the figure's title, above the panels'
        # own: so it lays the panels out below the top half inch
        fig.tight_layout(rect=(0, 0, 1, 1 - 0.5 / fig.get_figheight()))
    else:
        fig.tight_layout()                          # room for slanted labels


def draw_panels(fig, ax, spec):
    """The panels, one above another, sharing the X axis: ax is the top one."""
    grid = fig.add_gridspec(len(spec["panels"]), 1, height_ratios=spec["heights"])
    ax.set_subplotspec(grid[0])
    every_axes = [ax] + [fig.add_subplot(grid[i], sharex=ax) for i in range(1, len(spec["panels"]))]
    for axes, panel in zip(every_axes, spec["panels"]):
        draw_chart(axes, panel)
    for axes in every_axes[:-1]:                    # the X values' labels just once, at the bottom
        axes.tick_params(axis="x", labelbottom=False)
    if spec["title"]:
        fig.suptitle(spec["title"])


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


def tick_text(value):
    """A tick's number, written plainly, with commas: 1,500 or 0.25 -- never
    1.5e3 -- with just the decimals it needs."""
    decimals = 0
    while decimals < 10 and abs(value - round(value, decimals)) > 1e-9 * max(1.0, abs(value)):
        decimals += 1
    value = round(value, decimals) or 0.0          # (and never "-0")
    return "{:,.{}f}".format(value, decimals)


def label_text(value):
    """A value printed on a chart, plainly: from 100 up, a whole number with
    commas; below that, three significant digits."""
    if abs(value) >= 100:
        return "{:,.0f}".format(value)
    return "{:.3g}".format(value)


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
    -- as its spec says: a log scale, its limits, its ticks, and how
    they're written."""
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
    if scale["format"]:
        axis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda value, position: formatted_number(value, scale["format"])))
    else:
        axis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda value, position: tick_text(value)))


def set_up_x_axis(ax, spec):
    """The axis of X values: categories' names, how numbers are written, its
    limits, and, on a horizontal chart, the first X value at the top."""
    horizontal = spec["horizontal"]
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
    if spec["x_format"]:
        axis = ax.yaxis if horizontal else ax.xaxis
        axis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda value, position: formatted_number(value, spec["x_format"])))
    limits = [None if x is None else x_positions(spec, [x])[0] for x in (spec["x_min"], spec["x_max"])]
    if limits != [None, None]:
        if horizontal:
            ax.set_ylim(*limits)
        else:
            ax.set_xlim(*limits)
    if horizontal:
        ax.invert_yaxis()                           # the first X value at the top


def label_line(axes, vertical, at, text, color):
    """A reference line's label: beside a vertical line, at its top; above a
    horizontal line, at its right end."""
    if vertical:
        axes.annotate(text, xy=(at, 1), xycoords=("data", "axes fraction"), xytext=(3, -3),
                      textcoords="offset points", ha="left", va="top", fontsize=8, color=color)
    else:
        axes.annotate(text, xy=(1, at), xycoords=("axes fraction", "data"), xytext=(-3, 2),
                      textcoords="offset points", ha="right", va="bottom", fontsize=8, color=color)


def draw_reference_line(axes, vertical, line):
    if vertical:
        axes.axvline(line["at"], color=line["color"], linestyle="--", linewidth=1)
    else:
        axes.axhline(line["at"], color=line["color"], linestyle="--", linewidth=1)
    if line["label"]:
        label_line(axes, vertical, line["at"], line["label"], line["color"])


def draw_marks(ax, secondary, spec):
    """The shaded spans of X and the reference lines."""
    horizontal = spec["horizontal"]
    for span in spec["shade"]:
        start, end = sorted(x_positions(spec, [span["from"], span["to"]]))
        if spec["x_kind"] == "text":                # the whole of each category, from and to
            start, end = start - 0.5, end + 0.5
        if horizontal:
            ax.axhspan(start, end, color=span["color"], alpha=SHADE_OPACITY, linewidth=0, zorder=0)
        else:
            ax.axvspan(start, end, color=span["color"], alpha=SHADE_OPACITY, linewidth=0, zorder=0)
        if span["label"]:
            label_line(ax, not horizontal, start, span["label"], REFERENCE_COLOR)
    for line in spec["x_lines"]:
        draw_reference_line(ax, not horizontal, dict(line, at=x_positions(spec, [line["at"]])[0]))
    for axes, scale in ((ax, spec["y_axis"]), (secondary, spec["secondary_axis"])):
        if axes is not None:                        # (no secondary axis, without a series on it)
            for line in scale["lines"]:
                draw_reference_line(axes, horizontal, line)


def draw_notes(ax, spec):
    """The notes: each text with an arrow to its point. The text goes toward
    the middle of the chart from the point, so it stays inside."""
    for note in spec["notes"]:
        x = x_positions(spec, [note["x"]])[0]
        point = (note["y"], x) if spec["horizontal"] else (x, note["y"])
        across, up = ax.transAxes.inverted().transform(ax.transData.transform(point))   # 0 to 1, in the axes
        ax.annotate(note["text"], xy=point, textcoords="offset points",
                    xytext=(20 if across < 0.5 else -20, 20 if up < 0.5 else -20),
                    ha="left" if across < 0.5 else "right", va="bottom" if up < 0.5 else "top", fontsize=9,
                    arrowprops=dict(arrowstyle="->", color="black", linewidth=0.8))


def draw_series(ax, secondary, spec):
    """Each series' fill, bars, line, and symbols, in its own color, on the
    primary axis or the secondary one; and its values, if it's to be
    labeled. Returns the legend's entries: (what's drawn, its label), in
    the order of the series."""
    horizontal = spec["horizontal"]
    bar_series = [s for s in spec["series"] if s["bars"]]
    room = bar_room(spec, bar_series)
    stack_tops = {False: {}, True: {}}      # stacked bars, on each axis (see stacked_bottoms)
    legend_entries = []

    for i, s in enumerate(spec["series"]):
        axes = secondary if s["secondary"] else ax
        scale = spec["secondary_axis"] if s["secondary"] else spec["y_axis"]
        color = s["color"] or "C%d" % i          # matplotlib's colors, in order
        label = s["label"]
        if s["secondary"]:
            label += " (top)" if horizontal else " (right)"
        xs = x_positions(spec, s["x"])
        label_format = s["label_format"] or scale["format"]
        value_texts = [formatted_number(y, label_format) if label_format else label_text(y) for y in s["y"]]
        shown = None                             # what the legend shows for the series

        if s["fill"]:                            # down to 0, or to the other values: a band
            points = sorted(zip(xs, s["y"], s["fill_to"]))
            along, values, to = [p[0] for p in points], [p[1] for p in points], [p[2] for p in points]
            if horizontal:
                shown = axes.fill_betweenx(along, values, to, color=color, alpha=FILL_OPACITY, linewidth=0)
            else:
                shown = axes.fill_between(along, values, to, color=color, alpha=FILL_OPACITY, linewidth=0)
        if s["line"] or s["symbol"]:
            points = sorted(zip(xs, s["y"]))     # a line goes in order of X
            along, values = [x for x, _ in points], [y for _, y in points]
            style = dict(color=color, linestyle=LINE_STYLES[s["line"]] if s["line"] else "None",
                         linewidth=s["line_width"], marker=SYMBOLS[s["symbol"]] if s["symbol"] else "None",
                         markersize=s["symbol_size"])
            if horizontal:
                shown, = axes.plot(values, along, **style)
            else:
                shown, = axes.plot(along, values, **style)
        if s["bars"]:
            if spec["bars"] == "stacked":
                positions, thickness = xs, room
                starts = stacked_bottoms(stack_tops[s["secondary"]], xs, s["y"])
            else:                                # grouped: side by side, in the order of the series
                thickness = room / len(bar_series)
                offset = (bar_series.index(s) - (len(bar_series) - 1) / 2) * thickness
                positions, starts = [x + offset for x in xs], [0.0] * len(xs)
            style = dict(color=color, edgecolor="white", linewidth=0.5)
            if horizontal:
                shown = axes.barh(positions, s["y"], height=thickness, left=starts, **style)
            else:
                shown = axes.bar(positions, s["y"], width=thickness, bottom=starts, **style)
            if s["labels"]:                      # in the middle of a stacked bar; past the end of another
                axes.bar_label(shown, labels=value_texts, fontsize=8, padding=2,
                               label_type="center" if spec["bars"] == "stacked" else "edge")
        elif s["labels"]:                        # beside each point
            for x, y, text in zip(xs, s["y"], value_texts):
                if horizontal:
                    axes.annotate(text, xy=(y, x), xytext=(5, 0), textcoords="offset points",
                                  ha="left", va="center", fontsize=8, color=color)
                else:
                    axes.annotate(text, xy=(x, y), xytext=(0, 5), textcoords="offset points",
                                  ha="center", va="bottom", fontsize=8, color=color)
        if s["labels"]:                          # room for the labels past the largest values
            if horizontal:
                axes.set_xmargin(0.12)
            else:
                axes.set_ymargin(0.12)
        legend_entries.append((shown, label))

    for axes, scale, is_secondary in ((ax, spec["y_axis"], False), (secondary, spec["secondary_axis"], True)):
        if not scale["log"] and any(s["bars"] and s["secondary"] == is_secondary for s in spec["series"]):
            if horizontal:                       # a line at 0, for the bars
                axes.axvline(0, color="black", linewidth=0.8)
            else:
                axes.axhline(0, color="black", linewidth=0.8)
    return legend_entries


def draw_chart(ax, spec):
    """Draw a plot-chart spec on ax (and on a secondary axis it adds, if a
    series is on one). A horizontal chart has the X values down the side
    and the Y values across, so its bars go across."""
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

    legend_entries = draw_series(ax, secondary, spec)
    draw_marks(ax, secondary, spec)
    set_up_value_axis(ax, horizontal, spec["y_axis"])
    if secondary:
        set_up_value_axis(secondary, horizontal, spec["secondary_axis"])
    set_up_x_axis(ax, spec)
    draw_notes(ax, spec)                         # (once the axes' limits are set)

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
        front.legend([shown for shown, _ in legend_entries], [label for _, label in legend_entries],
                     loc=spec["legend"])


# ---------------------------------------------------------------------------
# Without matplotlib: a summary
# ---------------------------------------------------------------------------

def series_lines(spec):
    """A line for each of a chart's series, saying how it's drawn."""
    lines = []
    for s in spec["series"]:
        how = [what for what, drawn in (("symbols", s["symbol"]), ("line", s["line"]), ("bars", s["bars"]),
                                        ("filled", s["fill"]), ("on the secondary axis", s["secondary"]))
               if drawn]
        lines.append("  %s: %d points (%s)" % (s["label"], len(s["y"]), ", ".join(how)))
    return lines


def summary_text(spec):
    """A plain-text description of a plot-chart or plot-panels spec -- what
    the console shows instead of drawing it."""
    lines = [("[chart] " + spec["title"]).rstrip()]
    if spec["kind"] == "panels":
        for number, panel in enumerate(spec["panels"], 1):
            lines.append(("  panel %d: %s" % (number, panel["title"])).rstrip())
            lines += ["  " + line for line in series_lines(panel)]
    else:
        lines += series_lines(spec)
    return "\n".join(lines) + "\n"
