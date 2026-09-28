#!/usr/bin/env python3
"""
Chalkboard Chart Maker
======================

A small PyQt6 application:

  - A QTableView (backed by a QStandardItemModel) where the user types in
    data. The left column is the X value; up to 6 more columns are data
    series to plot.
  - Buttons to add/remove rows, and add/remove data columns (max 6).
  - A "Plot Chart" button that draws the data with Matplotlib, styled to
    look hand-drawn -- like a professor sketching on a chalkboard: a dark
    green board, "chalk" colored wobbly lines, and a different marker
    shape for each of the (up to 6) data columns.

Requirements: PyQt6 and matplotlib (`pip install PyQt6 matplotlib`).
"""

import sys
import logging

# Matplotlib's font-fallback search is noisy on machines that don't have
# any of the hand-writing-style fonts installed; the chart still looks
# fine with the fallback font, so we just quiet the warnings.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QStandardItemModel, QStandardItem
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTableView, QPushButton, QSplitter, QMessageBox, QHeaderView,
        QLabel,
    )
except ImportError:
    print("This application requires PyQt6. Install it with:\n\n    pip install PyQt6\n")
    sys.exit(1)

import matplotlib
matplotlib.use("QtAgg")  # auto-detects the installed Qt binding (PyQt6 here)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except ImportError:
    print(
        "Could not load Matplotlib's Qt backend. Make sure both matplotlib "
        "and PyQt6 are installed:\n\n    pip install matplotlib PyQt6\n"
    )
    sys.exit(1)

from matplotlib.figure import Figure
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Hand-drawn / chalkboard styling
# ---------------------------------------------------------------------------
#
# plt.xkcd() sets a handful of rcParams (a "sketch" path-distortion effect,
# plus a hand-writing font) to give matplotlib's normally-crisp lines a
# hand-drawn wobble. Normally it's used as a `with plt.xkcd(): ...` context
# manager that reverts those rcParams on exit -- but we want the sketch
# look to persist for the whole application (including redraws triggered
# later by window resizes etc.), so we enter the context once at startup
# and simply never exit it.
_xkcd_context = plt.xkcd(scale=1.5, length=120, randomness=2)
_xkcd_context.__enter__()

BOARD_COLOR = "#173a26"        # dark chalkboard green
CHALK_WHITE = "#f5f5f0"        # the color used for axes, ticks, and text

# One "chalk" color and one marker shape per data column (up to 6).
CHALK_COLORS = ["#f5f5f0", "#f6e58d", "#7ed6df", "#ff9ff3", "#95e6a5", "#ffbe76"]
MARKERS = ["o", "s", "^", "D", "v", "P"]

MAX_DATA_COLUMNS = 6


# ---------------------------------------------------------------------------
# The chart itself
# ---------------------------------------------------------------------------

class ChalkboardCanvas(FigureCanvasQTAgg):
    """A Matplotlib canvas that renders (x, y) series in a hand-drawn,
    chalkboard-styled chart, one marker shape and chalk color per series."""

    def __init__(self):
        figure = Figure(figsize=(6, 5), facecolor=BOARD_COLOR)
        super().__init__(figure)
        self.ax = figure.add_subplot(111)
        self._style_axes()

    def _style_axes(self):
        """Reset the axes to the blank chalkboard look."""
        ax = self.ax
        ax.clear()
        ax.set_facecolor(BOARD_COLOR)
        for spine in ax.spines.values():
            spine.set_color(CHALK_WHITE)
            spine.set_linewidth(1.5)
        ax.tick_params(colors=CHALK_WHITE)
        ax.xaxis.label.set_color(CHALK_WHITE)
        ax.yaxis.label.set_color(CHALK_WHITE)
        ax.title.set_color(CHALK_WHITE)
        ax.grid(True, color=CHALK_WHITE, alpha=0.15, linestyle="--")

    def plot_series(self, x_label, named_series):
        """named_series: list of (name, [(x, y), ...]) for each data column.
        Empty series (no valid points) are skipped."""
        self._style_axes()
        ax = self.ax

        plotted_any = False
        for i, (name, points) in enumerate(named_series):
            if not points:
                continue
            points = sorted(points, key=lambda p: p[0])
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            color = CHALK_COLORS[i % len(CHALK_COLORS)]
            marker = MARKERS[i % len(MARKERS)]
            ax.plot(
                xs, ys,
                marker=marker, color=color, linewidth=2,
                markersize=8, markeredgecolor=color, markerfacecolor=color,
                label=name,
            )
            plotted_any = True

        ax.set_xlabel(x_label)
        ax.set_title("Chalkboard Chart")
        if plotted_any:
            legend = ax.legend(
                facecolor=BOARD_COLOR, edgecolor=CHALK_WHITE, labelcolor=CHALK_WHITE
            )
            legend.get_frame().set_alpha(0.9)

        self.draw()


# ---------------------------------------------------------------------------
# Main window: table on the left, chart on the right
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chalkboard Chart Maker")
        self.resize(1150, 620)

        self.model = QStandardItemModel()
        self._init_model()

        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_layout.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())

        self.canvas = ChalkboardCanvas()
        splitter.addWidget(self.canvas)
        splitter.setSizes([500, 650])

        self._update_column_buttons()
        self.plot_chart()  # show a demo chart immediately, using sample data

    # -- UI construction -----------------------------------------------

    def _build_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        layout.addWidget(QLabel(
            "Left column = X axis. Up to 6 more columns = data series,\n"
            "each drawn with its own chalk color and marker shape."
        ))

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_view)

        row_buttons = QHBoxLayout()
        add_row_btn = QPushButton("Add Row")
        add_row_btn.clicked.connect(self.add_row)
        remove_row_btn = QPushButton("Remove Row")
        remove_row_btn.clicked.connect(self.remove_row)
        row_buttons.addWidget(add_row_btn)
        row_buttons.addWidget(remove_row_btn)
        layout.addLayout(row_buttons)

        col_buttons = QHBoxLayout()
        self.add_col_btn = QPushButton("Add Data Column")
        self.add_col_btn.clicked.connect(self.add_column)
        self.remove_col_btn = QPushButton("Remove Data Column")
        self.remove_col_btn.clicked.connect(self.remove_column)
        col_buttons.addWidget(self.add_col_btn)
        col_buttons.addWidget(self.remove_col_btn)
        layout.addLayout(col_buttons)

        plot_btn = QPushButton("Plot Chart")
        plot_btn.setStyleSheet("font-weight: bold;")
        plot_btn.clicked.connect(self.plot_chart)
        layout.addWidget(plot_btn)

        return panel

    def _init_model(self):
        headers = ["X", "Series 1", "Series 2", "Series 3"]
        self.model.setHorizontalHeaderLabels(headers)
        # A few rows of sample data, so the app shows a working chart
        # right away -- the user can edit or replace any of these values.
        sample_rows = [
            [0, 2, 5, 3],
            [1, 3, 4, 4],
            [2, 5, 6, 2],
            [3, 4, 3, 6],
            [4, 7, 5, 5],
            [5, 6, 7, 7],
            [6, 8, 4, 4],
            [7, 7, 6, 8],
        ]
        for row in sample_rows:
            self.model.appendRow([QStandardItem(str(v)) for v in row])

    # -- row / column editing -------------------------------------------

    def add_row(self):
        blank_row = [QStandardItem("") for _ in range(self.model.columnCount())]
        self.model.appendRow(blank_row)

    def remove_row(self):
        if self.model.rowCount() > 1:
            self.model.removeRow(self.model.rowCount() - 1)

    def add_column(self):
        data_columns = self.model.columnCount() - 1
        if data_columns >= MAX_DATA_COLUMNS:
            QMessageBox.information(
                self, "Limit reached",
                "You can plot at most %d data columns." % MAX_DATA_COLUMNS)
            return
        new_col_index = self.model.columnCount()
        self.model.insertColumn(new_col_index)
        self.model.setHeaderData(
            new_col_index, Qt.Orientation.Horizontal,
            "Series %d" % (data_columns + 1))
        for r in range(self.model.rowCount()):
            self.model.setItem(r, new_col_index, QStandardItem(""))
        self._update_column_buttons()

    def remove_column(self):
        data_columns = self.model.columnCount() - 1
        if data_columns <= 1:
            QMessageBox.information(
                self, "Minimum reached", "At least one data column is required.")
            return
        self.model.removeColumn(self.model.columnCount() - 1)
        self._update_column_buttons()

    def _update_column_buttons(self):
        data_columns = self.model.columnCount() - 1
        self.add_col_btn.setEnabled(data_columns < MAX_DATA_COLUMNS)
        self.remove_col_btn.setEnabled(data_columns > 1)

    # -- reading the table & plotting ------------------------------------

    def read_series(self):
        """Read the table into (headers, series), where series is a list
        of (x, y) point lists -- one list per data column. Blank cells and
        cells that don't parse as numbers are simply skipped; a blank or
        non-numeric X cell skips the whole row."""
        rows = self.model.rowCount()
        cols = self.model.columnCount()
        headers = [
            self.model.headerData(c, Qt.Orientation.Horizontal) or ("Column %d" % c)
            for c in range(cols)
        ]
        series = [[] for _ in range(cols - 1)]

        for r in range(rows):
            x_item = self.model.item(r, 0)
            if x_item is None or not x_item.text().strip():
                continue
            try:
                x_val = float(x_item.text())
            except ValueError:
                continue
            for c in range(1, cols):
                item = self.model.item(r, c)
                if item is None or not item.text().strip():
                    continue
                try:
                    y_val = float(item.text())
                except ValueError:
                    continue
                series[c - 1].append((x_val, y_val))

        return headers, series

    def plot_chart(self):
        headers, series = self.read_series()
        if not any(series):
            QMessageBox.warning(
                self, "No data",
                "Enter some numeric data first: an X value plus at least\n"
                "one value in a data column, in the same row.")
            return
        named_series = list(zip(headers[1:], series))
        x_label = headers[0] if headers else "X"
        self.canvas.plot_series(x_label, named_series)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
