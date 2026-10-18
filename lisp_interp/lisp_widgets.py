"""Widgets for the Jupyter notebook (the morris_lisp kernel): sliders, buttons, drop-down lists and the rest of
ipywidgets, and ipydatagrid's editable grid for a table.

A widget is a Python object that the notebook draws and the user works with the mouse and keyboard. The functions here
make a widget (make-widget), read and change what it holds (widget-get, widget-set!), and call a Lisp function when it
changes or is clicked (widget-on-change, widget-on-click); display-widget shows one. A table is edited with table-grid, which
makes a grid of it that the user can type into, and grid-table, which gives back the table with the edits. The Lisp side,
with examples, is "Widgets" in lisp_interpreter_reference.md.

Widgets work without a notebook (they are made and changed as usual, and call their functions), but only a notebook
can show one, so display-widget is given to the environment by lisp_jupyter.py and is an error anywhere else.

A callback is run by Python when the widget changes: an error in it is reported where its output goes (the Output widget
it is given, if it is given one) and doesn't stop anything. Lisp values become Python ones on the way in (a string is a str, a
list a list, '() None, a symbol or a keyword its name, a hash table a dict), and the other way on the way out.
"""

import contextlib
import datetime
import difflib

import numpy as np

from lisp_core import (
    Keyword, LispAbort, LispDate, LispError, LispHashTable, LispString, LispVector, NIL, Pair, Procedure, Symbol,
    _brief, _date_from_pydate, _lisp_scalar, apply_proc, format_error_report, list_to_pairs, pairs_to_list, parse_date_text,
)
from lisp_tables import column_values, make_table_value, table_columns

EDIT_ROWS_LIMIT = 100_000       # table-grid sends the whole table to the browser: more rows than this is a mistake


# ---------------------------------------------------------------------------
# The packages, which are imported when they are first needed
# ---------------------------------------------------------------------------

def _ipywidgets(who):
    try:
        import ipywidgets
    except ImportError:
        raise LispError("%s: this needs the ipywidgets package (pip install ipywidgets)" % who)
    return ipywidgets


def _datagrid(who):
    try:
        import ipydatagrid
        import pandas
    except ImportError:
        raise LispError("%s: this needs the ipydatagrid package (pip install ipydatagrid)" % who)
    return ipydatagrid, pandas


# ---------------------------------------------------------------------------
# Lisp values and Python values
# ---------------------------------------------------------------------------

def to_python(x):
    """A Lisp value as the Python value a widget takes."""
    if isinstance(x, Keyword):
        return str(x)[1:]
    if isinstance(x, (LispString, Symbol)):
        return str(x)
    if x is NIL:
        return None
    if isinstance(x, Pair):
        return [to_python(item) for item in pairs_to_list(x)]
    if isinstance(x, LispVector):
        return [to_python(_lisp_scalar(item)) for item in x.items]
    if isinstance(x, LispHashTable):
        return {str(key): to_python(value) for key, value in x.table.items()}
    if isinstance(x, LispDate):
        return x.date.isoformat()
    return x


def to_lisp(x):
    """A Python value from a widget as a Lisp value."""
    if x is None:
        return NIL
    if isinstance(x, str):
        return LispString(x)
    if isinstance(x, np.generic):
        return to_lisp(x.item())
    if isinstance(x, (list, tuple)):
        return list_to_pairs([to_lisp(item) for item in x])
    if isinstance(x, dict):
        table = LispHashTable()
        table.table = {LispString(str(key)): to_lisp(value) for key, value in x.items()}
        return table
    if isinstance(x, datetime.date) and not isinstance(x, datetime.datetime):
        return _date_from_pydate(x)
    return x


def trait_name(name, who):
    """A widget's attribute as Python names it, from how Lisp writes it: button-style, :button-style or "button_style"."""
    if not isinstance(name, (LispString, Symbol)):
        raise LispError("%s: a widget's attribute is named by a string, such as \"value\", not %s" % (who, _brief(name)))
    return str(name).lstrip(":").replace("-", "_")


def setting_for(trait, value):
    """The Python value to give a widget's trait for a Lisp value: '() is None where the trait allows it, and an empty
    list where it does not (the children of a box)."""
    python = to_python(value)
    if python is None and not getattr(trait, "allow_none", False):
        return []
    return python


def _public_trait_names(widget_class):
    return sorted(name for name in widget_class.class_trait_names() if not name.startswith("_"))


def check_trait_name(widget_class, name, who):
    traits = widget_class.class_traits()
    if name not in traits or name.startswith("_"):
        close = difflib.get_close_matches(name, _public_trait_names(widget_class), n=4)
        hint = "; did you mean %s?" % ", ".join(close) if close else ""
        raise LispError("%s: a %s has no attribute %s%s" % (who, widget_class.__name__, name, hint))
    return traits[name]


def keyword_settings(arguments, who):
    """The :name value pairs that follow a widget's class, as a list of (Python name, Lisp value)."""
    if len(arguments) % 2:
        raise LispError("%s: after the class come :name value pairs, such as :value 5" % who)
    settings = []
    for key, value in zip(arguments[::2], arguments[1::2]):
        if not isinstance(key, Keyword):
            raise LispError("%s: expected a keyword such as :value, not %s" % (who, _brief(key)))
        settings.append((trait_name(key, who), value))
    return settings


def build_widget(widget_class, settings, who):
    """A widget of this class with these (Python name, Lisp value) settings."""
    from traitlets import TraitError
    traits = {name: setting_for(check_trait_name(widget_class, name, who), value) for name, value in settings}
    try:
        return widget_class(**traits)
    except TraitError as e:
        raise LispError("%s: %s" % (who, e))
    except (TypeError, ValueError) as e:
        raise LispError("%s: %s" % (who, e))


def is_widget(x):
    try:
        import ipywidgets
    except ImportError:
        return False
    return isinstance(x, ipywidgets.Widget)


def check_widget(x, who):
    if not is_widget(x):
        raise LispError("%s: expected a widget (see make-widget), not %s" % (who, _brief(x)))
    return x


# ---------------------------------------------------------------------------
# Making, reading, and changing widgets
# ---------------------------------------------------------------------------

def make_widget(class_name, *arguments):
    """(make-widget "IntSlider" :min 0 :max 10 :value 5) -- a widget of one of ipywidgets' classes, with the attributes
    given by keyword (button-style is button_style). A list gives a list (the :children of a box), a hash table a dict."""
    widgets = _ipywidgets("make-widget")
    name = str(class_name)
    widget_class = getattr(widgets, name, None)
    if not (isinstance(widget_class, type) and issubclass(widget_class, widgets.Widget)):
        names = [n for n in dir(widgets) if isinstance(getattr(widgets, n), type)
                 and issubclass(getattr(widgets, n), widgets.Widget)]
        close = difflib.get_close_matches(name, names, n=4)
        hint = "; did you mean %s?" % ", ".join(close) if close else ""
        raise LispError("make-widget: ipywidgets has no widget class %s%s" % (name, hint))
    return build_widget(widget_class, keyword_settings(arguments, "make-widget"), "make-widget")


def widget_get(widget, name):
    """(widget-get w "value") -- what the widget holds in that attribute: a slider's value, a box's children, ..."""
    check_widget(widget, "widget-get")
    python = trait_name(name, "widget-get")
    check_trait_name(type(widget), python, "widget-get")
    return to_lisp(getattr(widget, python))


def widget_set(widget, name, value):
    """(widget-set! w "value" 7) -- changes an attribute; the notebook shows the change, and a function given to
    widget-on-change for it is called."""
    check_widget(widget, "widget-set!")
    python = trait_name(name, "widget-set!")
    trait = check_trait_name(type(widget), python, "widget-set!")
    from traitlets import TraitError
    try:
        setattr(widget, python, setting_for(trait, value))
    except (TraitError, TypeError, ValueError) as e:
        raise LispError("widget-set!: %s" % e)
    return NIL


def widget_close(widget):
    """(widget-close w) -- takes the widget off the notebook's page."""
    check_widget(widget, "widget-close").close()
    return NIL


def widget_link(source, source_name, target, target_name):
    """(widget-link a "value" b "value") -- keeps two widgets' attributes the same, in the browser: moving one slider moves
    the other. Returns the link."""
    widgets = _ipywidgets("widget-link")
    pairs = []
    for widget, name in ((source, source_name), (target, target_name)):
        check_widget(widget, "widget-link")
        python = trait_name(name, "widget-link")
        check_trait_name(type(widget), python, "widget-link")
        pairs.append((widget, python))
    return widgets.jslink(*pairs)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def output_widget(output, who):
    """The Output widget a :output option names, or None if there is none."""
    if output is NIL or output is False:
        return None
    widgets = _ipywidgets(who)
    if not isinstance(output, widgets.Output):
        raise LispError("%s: :output is an Output widget, (make-widget \"Output\"), not %s" % (who, _brief(output)))
    return output


def output_option(options, who):
    """The Output widget of the :output option, or None."""
    if len(options) % 2 or (options and options[0] != Keyword(":output")):
        raise LispError("%s: the only option is :output, an Output widget" % who)
    return output_widget(options[1], who) if options else None


def callback(function, output, convert):
    """The Python function that calls a Lisp one: with what convert makes of the arguments it is given. What the Lisp function
    displays, and the report of an error in it, go to the Output widget, if there is one."""
    if not (callable(function) or isinstance(function, Procedure)):
        raise LispError("expected a function to call, not %s" % _brief(function))

    def call(*arguments):
        with (output if output is not None else contextlib.nullcontext()):
            try:
                apply_proc(function, convert(*arguments))
            except LispAbort:
                print("Aborted")
            except Exception as e:
                print(format_error_report(e), end="")
    return call


def widget_on_change(widget, name, function, *options):
    """(widget-on-change w "value" f [:output out]) -- calls (f new-value) when the attribute changes, whether the user
    changed it or widget-set! did."""
    check_widget(widget, "widget-on-change")
    python = trait_name(name, "widget-on-change")
    check_trait_name(type(widget), python, "widget-on-change")
    run = callback(function, output_option(options, "widget-on-change"), lambda change: [to_lisp(change["new"])])
    widget.observe(run, names=python)
    return NIL


def widget_on_click(button, function, *options):
    """(widget-on-click button f [:output out]) -- calls (f) each time the button is clicked."""
    check_widget(button, "widget-on-click")
    if not hasattr(button, "on_click"):
        raise LispError("widget-on-click: a %s has no click; a Button does" % type(button).__name__)
    run = callback(function, output_option(options, "widget-on-click"), lambda *_: [])
    button.on_click(run)
    return NIL


def widget_capture(output, thunk):
    """(widget-capture out thunk) -- calls (thunk) with what it displays going into the Output widget (display, display-table,
    plots), and returns its value."""
    out = output_widget(output, "widget-capture")
    if out is None:
        raise LispError("widget-capture: expected an Output widget, (make-widget \"Output\")")
    with out:
        return apply_proc(thunk, [])


def widget_clear(output):
    """(widget-clear out) -- empties an Output widget."""
    out = output_widget(output, "widget-clear")
    if out is None:
        raise LispError("widget-clear: expected an Output widget, (make-widget \"Output\")")
    out.clear_output()
    return NIL


# ---------------------------------------------------------------------------
# A table in a grid
# ---------------------------------------------------------------------------
#
# A table becomes a pandas DataFrame for ipydatagrid's DataGrid. The grid keeps a copy of the frame as it was made (the
# baseline), so that grid-table can give back the table with only the cells the user changed made new: a cell that was not
# changed keeps the value it had, to the last bit, however the grid shows it.

def column_kind(vector):
    """How a column's cells are read back: "float", "int", "date", "number" (numbers in a column of Lisp objects), or "text"."""
    dtype = vector.items.dtype
    if np.issubdtype(dtype, np.floating):
        return "float"
    if np.issubdtype(dtype, np.integer):
        return "int"
    present = [x for x in vector.items if x is not None and x is not NIL]
    if present and all(isinstance(x, LispDate) for x in present):
        return "date"
    if present and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in present):
        return "number"
    return "text"


def grid_column(vector, kind):
    """A column's values for the grid: numbers as float64 or int64 (a float32 as the number it was written as, 0.1 and not
    0.10000000149), dates as YYYY-MM-DD, and anything else as text, a missing value as an empty cell."""
    items = vector.items
    if kind == "float":
        return items.astype(str).astype(np.float64)
    if kind == "int":
        return items.astype(np.int64)
    if kind == "number":
        return np.array([np.nan if x is None or x is NIL else x for x in column_values(vector)], dtype=np.float64)
    cells = []
    for x in column_values(vector):
        if x is None or x is NIL:
            cells.append("")
        elif isinstance(x, LispDate):
            cells.append(x.date.isoformat())
        else:
            cells.append(str(x))
    return np.array(cells, dtype=object)


def table_to_frame(table, who):
    """A table as a pandas DataFrame, and how each column is read back. Returns (frame, kinds)."""
    _, pandas = _datagrid(who)
    columns = table_columns(table, who)
    if not columns:
        raise LispError("%s: the table has no columns" % who)
    kinds = {name: column_kind(vector) for name, vector in columns}
    frame = pandas.DataFrame({name: grid_column(vector, kinds[name]) for name, vector in columns})
    frame.index.name = "row"            # (the grid's heading for the row numbers, which it would call "key")
    return frame, kinds


def read_cell(value, kind, column, row):
    """What a cell of the grid holds, as the Lisp value for a column of this kind. A cell that can't be read as one is an
    error that says which."""
    missing = value is None or (isinstance(value, float) and value != value)
    where = "column %s, row %d" % (column, row)
    if kind in ("float", "number"):
        if missing:
            return float("nan")
        try:
            return float(value)
        except (TypeError, ValueError):
            raise LispError("grid-table: %s: %s is not a number" % (where, _brief(value)))
    if kind == "int":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise LispError("grid-table: %s: %s is not a whole number" % (where, _brief(value)))
        if number != int(number):
            raise LispError("grid-table: %s: %s is not a whole number" % (where, _brief(value)))
        return int(number)
    if kind == "date":
        if missing or str(value) == "":
            return NIL
        date = parse_date_text(str(value).strip())
        if date is None:
            raise LispError("grid-table: %s: %s is not a date written YYYY-MM-DD" % (where, _brief(value)))
        return date
    return NIL if missing else LispString(str(value))


def table_from_frame(table, baseline, current, kinds, who):
    """The table, with the cells where the frame `current` differs from `baseline` made new."""
    columns = table_columns(table, who)
    if list(current.columns) != list(baseline.columns) or len(current) != len(baseline):
        raise LispError("%s: the grid no longer has the table's columns and rows" % who)
    made = []
    for name, vector in columns:
        before, now = baseline[name].reset_index(drop=True), current[name].reset_index(drop=True)
        changed = ~((now == before) | (now.isna() & before.isna())).to_numpy()
        if not changed.any():
            made.append((name, vector))
            continue
        items = vector.items.copy()
        for place in np.flatnonzero(changed):
            value = read_cell(now.iloc[place], kinds[name], name, int(place))
            try:
                items[place] = value
            except OverflowError:
                raise LispError("grid-table: column %s, row %d: %s is too big for the column" % (name, place, value))
        made.append((name, LispVector(items)))
    return make_table_value(made)


def table_grid(table, *arguments):
    """(table-grid table [:editable #t] [:name value ...]) -- a grid of the table, which the user can edit with the keyboard
    and mouse (ipydatagrid's DataGrid, with its attributes as keywords)."""
    ipydatagrid, _ = _datagrid("table-grid")
    columns = table_columns(table, "table-grid")
    rows = len(columns[0][1].items) if columns else 0
    if rows > EDIT_ROWS_LIMIT:
        raise LispError("table-grid: %s rows is more than a grid can carry to the browser (%s); show some of them "
                        "(table-head, table-filter)" % (format(rows, ","), format(EDIT_ROWS_LIMIT, ",")))
    settings = keyword_settings(arguments, "table-grid")
    given = dict(settings)
    for name, value in (("editable", True), ("auto_fit_columns", True)):      # (the usual choices, unless given)
        if name not in given:
            settings.append((name, value))
    frame, kinds = table_to_frame(table, "table-grid")
    grid = _grid_of(ipydatagrid, frame, settings)
    grid._lisp_table = table
    grid._lisp_baseline = frame.copy()
    grid._lisp_kinds = kinds
    return grid


def _grid_of(ipydatagrid, frame, settings):
    """A DataGrid of the frame, with these (Python name, Lisp value) settings."""
    from traitlets import TraitError
    traits = {name: setting_for(check_trait_name(ipydatagrid.DataGrid, name, "table-grid"), value)
              for name, value in settings}
    try:
        return ipydatagrid.DataGrid(frame, **traits)
    except (TraitError, TypeError, ValueError) as e:
        raise LispError("table-grid: %s" % e)


def check_grid(grid, who):
    if not hasattr(grid, "_lisp_baseline"):
        raise LispError("%s: expected a grid made by table-grid, not %s" % (who, _brief(grid)))
    return grid


def grid_table(grid):
    """(grid-table grid) -- the table the grid shows now: the table it was made from, with the cells the user changed."""
    check_grid(grid, "grid-table")
    return table_from_frame(grid._lisp_table, grid._lisp_baseline, grid.data, grid._lisp_kinds, "grid-table")


def grid_set_table(grid, table):
    """(grid-set-table! grid table) -- shows another table in the grid (or the same one again, undoing the edits)."""
    check_grid(grid, "grid-set-table!")
    frame, kinds = table_to_frame(table, "grid-set-table!")
    grid.data = frame
    grid._lisp_table, grid._lisp_baseline, grid._lisp_kinds = table, frame.copy(), kinds
    return NIL


def grid_on_edit(grid, function, *options):
    """(grid-on-edit grid f [:output out]) -- calls (f column row value) each time the user changes a cell: the column's name,
    the row's place in the table (from 0), and the new value."""
    check_grid(grid, "grid-on-edit")

    def convert(cell):
        column, row = str(cell["column"]), int(cell["row"])
        kind = grid._lisp_kinds.get(column, "text")
        return [LispString(column), row, read_cell(cell["value"], kind, column, row)]

    grid.on_cell_change(callback(function, output_option(options, "grid-on-edit"), convert))
    return NIL


def make_widget_builtins(show):
    """display-widget, which hands the widget to show, the environment's way of showing one (a notebook draws it)."""

    def display_widget(widget):
        """(display-widget w) -- shows a widget in the notebook, below the cell, where its output would go."""
        check_widget(widget, "display-widget")
        show(widget)
        return NIL

    return {"display-widget": display_widget}


BUILTINS = {
    "make-widget": make_widget,
    "widget-get": widget_get,
    "widget-set!": widget_set,
    "widget-close": widget_close,
    "widget-link": widget_link,
    "widget-on-change": widget_on_change,
    "widget-on-click": widget_on_click,
    "widget-capture": widget_capture,
    "widget-clear": widget_clear,
    "table-grid": table_grid,
    "grid-table": grid_table,
    "grid-set-table!": grid_set_table,
    "grid-on-edit": grid_on_edit,
}
