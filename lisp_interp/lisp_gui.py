"""The PyQt6 GUI for the Lisp interpreter: an input box, an output log, a
"Columns" tab (filled by display-columns), and a "Chart" tab (drawn by the
plot-xy... builtins, with a "Save Chart..." button).

Opened by running lisp_interpreter.py with no arguments. Needs PyQt6 and
matplotlib (pip install PyQt6 matplotlib); PYQT_AVAILABLE says whether
they're installed. Nothing else in the interpreter imports this file, so
everything else works without PyQt6.
"""

import sys

from lisp_core import LispError, NIL, format_error_report, parse, seval, to_string
from lisp_builtins import load_init_file, make_global_env
from lisp_charts import MATPLOTLIB_AVAILABLE, draw_chart_on_axes, render_chart_to_file

try:
    from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
    from PyQt6.QtGui import QTextCursor, QFontDatabase
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPlainTextEdit, QPushButton, QTextEdit, QTableView, QSplitter,
        QTabWidget, QFileDialog, QMessageBox,
    )
    import matplotlib
    matplotlib.use("QtAgg")  # auto-detects the installed Qt binding (PyQt6 here)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    PYQT_AVAILABLE = MATPLOTLIB_AVAILABLE  # the GUI needs both PyQt6 and matplotlib
except ImportError:
    PYQT_AVAILABLE = False


if PYQT_AVAILABLE:

    class ChartCanvas(FigureCanvasQTAgg):
        """Renders a chart spec (see build_chart_spec): one X vector against
        one or more Y vectors, each with its own marker symbol and
        optionally connected by line segments, plus an optional dashed
        regression line/curve. Drawing itself is shared with the headless
        save-chart path via draw_chart_on_axes()."""

        def __init__(self):
            figure = Figure(figsize=(6, 5))
            super().__init__(figure)
            self.ax = figure.add_subplot(111)

        def plot(self, spec):
            draw_chart_on_axes(self.figure, self.ax, spec)
            self.draw()

    class VectorTableModel(QAbstractTableModel):
        """Displays a set of named number vectors as columns: one column
        per vector, headed by its variable name, one row per index."""

        def __init__(self):
            super().__init__()
            self.names = []    # column headers, in display order
            self.columns = []  # parallel list of plain Python number lists

        def set_vectors(self, name_value_pairs):
            """Replace the full set of displayed vectors.
            name_value_pairs: list of (name, list-of-numbers) tuples."""
            self.beginResetModel()
            self.names = [name for name, _ in name_value_pairs]
            self.columns = [values for _, values in name_value_pairs]
            self.endResetModel()

        def rowCount(self, parent=QModelIndex()):
            return max((len(col) for col in self.columns), default=0)

        def columnCount(self, parent=QModelIndex()):
            return len(self.columns)

        def data(self, index, role=Qt.ItemDataRole.DisplayRole):
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            if role != Qt.ItemDataRole.DisplayRole:
                return None
            col = self.columns[index.column()]
            row = index.row()
            if row < len(col):
                # Values arriving here (via display-columns) are already
                # rendered strings -- see format_column_value() and the
                # *column-number-format* global -- so this is just a
                # pass-through; right-aligning them (above) in the
                # monospace font the GUI sets on this table (see
                # LispMainWindow.__init__) is what actually makes a
                # column of numbers line up on its ones place.
                return str(col[row])
            return ""

        def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
            if role != Qt.ItemDataRole.DisplayRole:
                return None
            if orientation == Qt.Orientation.Horizontal:
                return self.names[section]
            return str(section)

    class InputEdit(QPlainTextEdit):
        """A plain-text box that runs its contents on Ctrl+Enter, while
        letting a plain Enter insert a newline (so multi-line definitions
        are easy to type)."""

        def __init__(self, on_submit):
            super().__init__()
            self._on_submit = on_submit

        def keyPressEvent(self, event):
            is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            if is_enter and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self._on_submit()
                return
            super().keyPressEvent(event)

    WELCOME_MESSAGE = (
        "Simple Lisp, with vectors/dates, XY charts, and FRED data access.\n"
        "Try, for example:\n"
        "  (define prices (vector 10 20 30 40 50))\n"
        "  (define doubled (vector-map (lambda (x) (* x 2)) prices))\n"
        "  (define powers-of-two (vector-iterate 1 8 (lambda (x) (* x 2))))\n"
        "  (define squares #(1 4 9 16 25))\n"
        "  (define home-type (vector 0 1 0 1 1))  ; 0=own, 1=rent\n"
        "  (plot-xy prices (list doubled squares))\n"
        "  (plot-xy-regression prices squares \"Squares\")             ; linear\n"
        "  (define m (logistic-regression prices (vector 0 1 0 1 1)))  ; y in [0,1]\n"
        "  (display (model-report m))\n"
        "  (plot-xy-regression prices (vector 0 1 0 1 1) \"Y\" \"logistic\")\n"
        "  ; multiple predictors: pass a list of x-vectors instead of one\n"
        "  (define m2 (linear-regression (list prices squares) doubled))\n"
        "  (display (model-coefficients m2))\n"
        "  ; train/test split: fit on a subset, evaluate on the rest\n"
        "  (define n-train (floor (* (vector-length prices) 0.7)))\n"
        "  (define train-x (vector-take prices n-train))\n"
        "  (define test-x (vector-drop prices n-train))\n"
        "  (define m3 (linear-regression train-x (vector-take squares n-train)))\n"
        "  (display (model-evaluate m3 test-x (vector-drop squares n-train)))\n"
        "  (define d (fred-series \"GDP\" \"YOUR_FRED_API_KEY\"))\n"
        "  (plot-xy (car d) (list (cdr d)))\n"
        "  (save-chart \"chart.png\")   ; or use the Save Chart... button\n"
        "  ; spline-regression: a bit of non-linearity via hinge functions\n"
        "  (define m4 (spline-regression prices squares 3))  ; up to 3 auto knots\n"
        "  (display (model-report m4))\n"
        "  ; explicit knots (e.g. bracketing a critical range) instead of auto:\n"
        "  (define m5 (spline-regression prices squares (list 25 35)))\n"
        "  ; or let suggest-knots propose locations from the data itself:\n"
        "  (define knots (suggest-knots prices squares 2 2))\n"
        "  (define m5b (spline-regression prices squares knots))\n"
        "  ; different max knots per predictor: pass a list instead of one number\n"
        "  (define m6 (spline-regression (list prices squares) doubled (list 1 0)))\n"
        "  ; a 2-3-valued predictor (e.g. home-type: 0=own/1=rent) -> 'categorical\n"
        "  (define m7 (spline-regression (list prices home-type) doubled\n"
        "                                 (list 2 (quote categorical))))\n"
        "  (define m8 (spline-regression (vector 10 20 30 40 50 60 70 80 90 100 110 120)\n"
        "                                 (vector 0 0 1 0 1 1 0 1 1 1 0 1) 2 #t))\n"
        "  ; load-csv returns (cons headers vectors); e.g.:\n"
        "  ; (define d2 (load-csv \"data.csv\"))  (define cols (cdr d2))\n"
        "  ; tastytrade real broker data (needs a credentials JSON file --\n"
        "  ; see tasty_api/README.md for one-time OAuth setup):\n"
        "  (define creds \"tastytrade_credentials.json\")\n"
        "  (define curve (tastytrade-futures-curve creds \"CL\" 12))\n"
        "  (plot-xy (car curve) (list (cdr curve)))\n"
        "  (define chain (tastytrade-option-chain creds \"CL\" 3 10 #f))\n"
        "  (display (length chain))  ; #f above skips the slower IV stream\n"
        "  ; equity option chains work the same way -- any symbol not\n"
        "  ; starting with \"/\" and not a futures short code is fetched\n"
        "  ; as an equity chain, no translation needed:\n"
        "  (define aapl-chain (tastytrade-option-chain creds \"AAPL\" 2 10 #f))\n"
        "  ; rich/cheap curve analysis (fetch once, re-analyze free of charge\n"
        "  ; with different assumptions -- these two are pure, no networking):\n"
        "  (define rows (tastytrade-futures-curve-rows creds \"CL\" 12))\n"
        "  (define fit (tastytrade-curve-fit rows 0.75))\n"
        "  (define legs (tastytrade-leg-carry rows 4.25 3.0 1.0))\n"
        "  ; structs + keyword args (see column_engine.lsp for a full\n"
        "  ; mortgage-amortization example built on these):\n"
        "  (defstruct point x y (label \"\"))\n"
        "  (define p (make-point :x 1 :y 2))\n"
        "  (display (list (point-x p) (point-y p) (point? p)))\n"
        "  (display-columns (list (cons \"prices\" prices) (cons \"squares\" squares)))\n"
        "display-columns populates the Columns tab; plot-xy... calls draw\n"
        "into the Chart tab.\n"
        "Press Ctrl+Enter, or click Run, to evaluate.\n\n"
    )

    class LispMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Simple Lisp \u2014 vectors, charts, and FRED data")
            self.resize(1150, 620)

            self.env = make_global_env(
                output=self._write_output, plot=self._on_plot, columns=self._on_columns)
            load_init_file(self.env)

            central = QWidget()
            self.setCentralWidget(central)
            outer_layout = QVBoxLayout(central)

            input_row = QHBoxLayout()
            self.input_edit = InputEdit(self._on_run)
            self.input_edit.setPlaceholderText(
                "Enter one or more Lisp expressions, then press Ctrl+Enter or click Run...")
            self.input_edit.setFixedHeight(90)
            input_row.addWidget(self.input_edit, 1)

            run_button = QPushButton("Run (Ctrl+Enter)")
            run_button.clicked.connect(self._on_run)
            input_row.addWidget(run_button)

            outer_layout.addLayout(input_row)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            outer_layout.addWidget(splitter, 1)

            self.output_view = QTextEdit()
            self.output_view.setReadOnly(True)
            splitter.addWidget(self.output_view)

            self.tabs = QTabWidget()
            splitter.addWidget(self.tabs)

            self.table_model = VectorTableModel()
            self.table_view = QTableView()
            self.table_view.setModel(self.table_model)
            # Fixed-width font so a column of right-aligned numbers (see
            # VectorTableModel.data()'s TextAlignmentRole) lines up
            # vertically on its ones place, not just left-to-right.
            self.table_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            self.tabs.addTab(self.table_view, "Columns")

            chart_tab = QWidget()
            chart_layout = QVBoxLayout(chart_tab)
            chart_layout.setContentsMargins(0, 0, 0, 0)
            self.chart_canvas = ChartCanvas()
            chart_layout.addWidget(self.chart_canvas, 1)
            save_chart_button = QPushButton("Save Chart...")
            save_chart_button.clicked.connect(self._on_save_chart)
            chart_layout.addWidget(save_chart_button)
            self.tabs.addTab(chart_tab, "Chart")

            self.last_chart_spec = None
            splitter.setSizes([500, 650])

            self._append_text(WELCOME_MESSAGE)

        def _write_output(self, text):
            """Called directly by the Lisp `display` / `newline` / `print`
            builtins -- this is the only bit of "wiring" between the
            interpreter and the GUI."""
            self._append_text(text)

        def _on_plot(self, spec):
            """Called directly by the Lisp `plot-xy...` builtins with a
            plain-data chart spec (see build_chart_spec)."""
            self.last_chart_spec = spec
            self.chart_canvas.plot(spec)
            self.tabs.setCurrentIndex(1)

        def _on_columns(self, name_value_pairs):
            """Called directly by the Lisp `display-columns` builtin --
            the ONLY way the Columns tab is populated."""
            self.table_model.set_vectors(name_value_pairs)
            self.tabs.setCurrentIndex(0)

        def _on_save_chart(self):
            if self.last_chart_spec is None:
                QMessageBox.information(
                    self, "No chart yet", "Plot a chart first, e.g. with plot-xy.")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Chart", "chart.png",
                "PNG Image (*.png);;PDF Document (*.pdf);;SVG Image (*.svg);;All Files (*)")
            if not path:
                return
            try:
                render_chart_to_file(self.last_chart_spec, path)
                self._append_text("Chart saved to %s\n\n" % path)
            except LispError as e:
                QMessageBox.warning(self, "Save failed", str(e))

        def _append_text(self, text):
            self.output_view.moveCursor(QTextCursor.MoveOperation.End)
            self.output_view.insertPlainText(text)
            self.output_view.moveCursor(QTextCursor.MoveOperation.End)

        def _on_run(self):
            source = self.input_edit.toPlainText().strip()
            if not source:
                return
            self._append_text("lisp> " + source + "\n")
            try:
                result = NIL
                for expr in parse(source):
                    result = seval(expr, self.env)
                self._append_text("=> " + to_string(result) + "\n\n")
            except Exception as e:
                self._append_text(format_error_report(e) + "\n")
            self.input_edit.clear()


def launch_gui():
    """Open the GUI window and run until it's closed. Only call this when
    PYQT_AVAILABLE is true."""
    app = QApplication(sys.argv)
    window = LispMainWindow()
    window.show()
    sys.exit(app.exec())

