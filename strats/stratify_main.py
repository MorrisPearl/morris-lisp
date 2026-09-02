"""
Stratification Report Builder
==============================

A PyQt6 desktop app that:
  1. Loads input data either from a delimited file (CSV/TSV, with or
     without a header row) or, directly, from a table in a SQLite
     database.
  2. Lets the user configure, per field: whether it is the WEIGHT field,
     how many buckets (N, or "All" distinct values for categorical fields)
     to stratify it into, the bucketing method (equal count / equal weight /
     manual breakpoints / none), and one or more summary statistics to use
     for that field when it appears as a column in other fields' reports.
  3. Generates one stratification report per field (skipping fields whose
     Method is "None"), plus any user-defined multi-field ("intersection")
     reports, and shows each in its own tab.
  4. Exports all reports to a single multi-sheet Excel workbook, or to a
     folder of CSV files.
  5. Saves / loads the entire configuration to / from a JSON file.

Run with:  python main.py
"""

import sys
import os
import json
import sqlite3
import datetime

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
    QSpinBox, QDoubleSpinBox, QComboBox, QRadioButton, QButtonGroup, QTabWidget,
    QMessageBox, QHeaderView, QGroupBox, QAbstractItemView, QCheckBox, QDialog,
    QDialogButtonBox, QListWidget, QListWidgetItem
)

from stratify_engine import (
    detect_field_types, build_report, build_multi_field_report, build_overall_report,
    estimate_combo_count,
    NUMERIC_METHODS, DATE_METHODS, CATEGORICAL_METHODS, stats_for_field_type, stat_label,
    PERCENTILE_STATS,
)

APP_TITLE = "Stratification Report Builder"
CONFIG_VERSION = 1
MULTI_COMBO_WARN_THRESHOLD = 2000


def format_stat_button_text(stats: list) -> str:
    if not stats:
        return "(none)"
    return ", ".join(stat_label(s) for s in stats)


# ============================================================================
# Small reusable widgets / dialogs
# ============================================================================

class NBucketsWidget(QWidget):
    """A spinbox for N, plus an 'All' checkbox (categorical fields only)."""

    def __init__(self, is_categorical: bool, default_n: int = 5, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.spin = QSpinBox()
        self.spin.setRange(2, 500)
        self.spin.setValue(default_n)
        layout.addWidget(self.spin)
        self.all_checkbox = QCheckBox("All")
        self.all_checkbox.setVisible(is_categorical)
        self.all_checkbox.toggled.connect(lambda checked: self.spin.setEnabled(not checked))
        layout.addWidget(self.all_checkbox)

    def value(self):
        if self.all_checkbox.isVisible() and self.all_checkbox.isChecked():
            return "All"
        return self.spin.value()

    def set_value(self, n):
        if isinstance(n, str) and n.strip().lower() == "all":
            self.all_checkbox.setChecked(True)
        else:
            self.all_checkbox.setChecked(False)
            try:
                self.spin.setValue(int(n))
            except (TypeError, ValueError):
                pass

    def set_enabled_all(self, enabled: bool):
        self.all_checkbox.setEnabled(enabled)
        is_all = self.all_checkbox.isVisible() and self.all_checkbox.isChecked()
        self.spin.setEnabled(enabled and not is_all)

    def set_categorical(self, is_categorical: bool):
        """Show/hide the 'All' checkbox -- used when a field's effective
        bucketing type changes on the fly (the "treat as categorical"
        override below), rather than replacing this widget outright."""
        self.all_checkbox.setVisible(is_categorical)
        if not is_categorical and self.all_checkbox.isChecked():
            self.all_checkbox.setChecked(False)


class StatSelectorDialog(QDialog):
    """Lets the user pick one or more summary statistics for a field."""

    def __init__(self, field_name: str, field_type: str, current_stats: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Summary Statistics — '{field_name}'")
        self.resize(430, 420)
        self.stats = [dict(s) for s in current_stats]

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Choose one or more summary statistics for '{field_name}'.\n"
            "Each one becomes its own column in other fields' reports.\n"
            "Leave the list empty to exclude this field entirely (= None)."
        ))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        add_row = QHBoxLayout()
        self.stat_combo = QComboBox()
        self.stat_combo.addItems(stats_for_field_type(field_type))
        self.pct_spin = QDoubleSpinBox()
        self.pct_spin.setRange(0, 100)
        self.pct_spin.setValue(50)
        self.pct_spin.setSuffix(" pct")
        self.pct_spin.setEnabled(self.stat_combo.currentText() in PERCENTILE_STATS)
        self.stat_combo.currentTextChanged.connect(
            lambda text: self.pct_spin.setEnabled(text in PERCENTILE_STATS))
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_stat)
        add_row.addWidget(self.stat_combo, 2)
        add_row.addWidget(self.pct_spin, 1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        layout.addWidget(remove_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_list()

    def _add_stat(self):
        name = self.stat_combo.currentText()
        cfg = {"stat": name}
        if name in PERCENTILE_STATS:
            cfg["pct"] = self.pct_spin.value()
        if cfg not in self.stats:
            self.stats.append(cfg)
            self._refresh_list()

    def _remove_selected(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            del self.stats[row]
            self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for cfg in self.stats:
            self.list_widget.addItem(stat_label(cfg))

    def get_stats(self):
        return self.stats


class MultiFieldDialog(QDialog):
    """Lets the user pick 2+ fields for a combined ('intersection') report."""

    def __init__(self, eligible_fields: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Multi-Field Report")
        self.resize(380, 440)
        self._selected = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Select 2 or more fields to stratify on at the same time.\n"
            "The report will have one row per combination that actually occurs "
            "in the data (up to the product of each field's bucket count).\n"
            "Only fields with a bucketing Method set (not 'None') are listed."
        ))

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Report name (optional)")
        layout.addWidget(self.name_edit)

        self.list_widget = QListWidget()
        for name, ftype in eligible_fields:
            item = QListWidgetItem(f"{name}  ({ftype})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_ok(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        if len(selected) < 2:
            QMessageBox.warning(self, "Add Multi-Field Report", "Select at least 2 fields.")
            return
        self._selected = selected
        self.accept()

    def get_result(self):
        name = self.name_edit.text().strip() or " + ".join(self._selected)
        return name, self._selected


# ============================================================================
# Field configuration "spreadsheet"
# ============================================================================

class FieldConfigTable(QTableWidget):
    COL_FIELD = 0
    COL_TYPE = 1
    COL_CATEGORICAL = 2
    COL_WEIGHT = 3
    COL_N = 4
    COL_METHOD = 5
    COL_BREAKPOINTS = 6
    COL_STAT = 7

    HEADERS = ["Field", "Type", "Categorical?", "Weight?", "N (buckets)", "Method", "Breakpoints",
               "Summary Stats"]

    # Defaults for a field's OWN report -- see the class docstring-ish note
    # in populate(), below, for why weighted/equal-weight was chosen.
    DEFAULT_NUMERIC_METHOD = "Equal Weight Buckets"
    DEFAULT_NUMERIC_STAT = "Weighted Average"
    DEFAULT_DATE_METHOD = "Equal Weight Buckets"
    DEFAULT_DATE_STAT = "Representative Value"
    DEFAULT_CATEGORICAL_METHOD = "Top Values + Other"

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(self.COL_FIELD, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self.COL_CATEGORICAL, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self.COL_WEIGHT, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.weight_group = QButtonGroup(self)
        self.weight_group.setExclusive(True)
        self.row_types = []

    # -- construction ---------------------------------------------------

    def populate(self, field_types: dict, default_n: int = 5):
        """Build one row per field. field_types: {name: 'numeric'/'date'/'categorical'}.

        row_types (below) always holds each field's TRUE, detected type --
        it never changes, and it's what governs which summary stats are
        available for a field (stats_for_field_type) and how a field is
        treated as a COLUMN in some other field's report (is it averaged,
        summed, etc.). The "Categorical?" checkbox, by contrast, only
        overrides how a numeric field buckets ITSELF for its own report
        (see effective_type()/on_categorical_toggled(), below) -- e.g. a
        0/1 flag that's technically numeric but should get one bucket per
        value instead of being split into quantile ranges. That's a
        purely presentational override, so it's tracked separately and
        never touches row_types."""
        self.setRowCount(0)
        self.row_types = []
        self.weight_group = QButtonGroup(self)
        self.weight_group.setExclusive(True)

        for row, (name, ftype) in enumerate(field_types.items()):
            self.insertRow(row)
            self.row_types.append(ftype)

            # Field name is editable so users can rename fields / type in names
            # for headerless files.
            field_item = QTableWidgetItem(name)
            self.setItem(row, self.COL_FIELD, field_item)

            type_item = QTableWidgetItem(ftype)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, self.COL_TYPE, type_item)

            categorical_checkbox = QCheckBox()
            categorical_checkbox.setToolTip(
                "Treat this field as categorical for its OWN report, even though its\n"
                "values look numeric -- useful for a field known to have only a\n"
                "handful of distinct values (e.g. a 0/1 flag), so its report gets one\n"
                "row per distinct value instead of being split into quantile ranges.\n"
                "It's still treated as numeric (e.g. averaged normally) wherever it\n"
                "appears as a column in some OTHER field's report.")
            categorical_checkbox.setEnabled(ftype == "numeric")
            categorical_wrapper = QWidget()
            cw_layout = QHBoxLayout(categorical_wrapper)
            cw_layout.addWidget(categorical_checkbox)
            cw_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cw_layout.setContentsMargins(0, 0, 0, 0)
            self.setCellWidget(row, self.COL_CATEGORICAL, categorical_wrapper)

            radio = QRadioButton()
            wrapper = QWidget()
            wl = QHBoxLayout(wrapper)
            wl.addWidget(radio)
            wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wl.setContentsMargins(0, 0, 0, 0)
            self.weight_group.addButton(radio, row)
            self.setCellWidget(row, self.COL_WEIGHT, wrapper)

            # "All" (no fixed bucket count) only makes sense for a true
            # categorical field -- both numeric and date quantile
            # bucketing always split into a specific count.
            n_widget = NBucketsWidget(is_categorical=(ftype not in ("numeric", "date")), default_n=default_n)
            self.setCellWidget(row, self.COL_N, n_widget)

            method_combo = QComboBox()
            self.setCellWidget(row, self.COL_METHOD, method_combo)

            bp_edit = QLineEdit()
            bp_edit.setPlaceholderText("e.g. 2020-01-01, 2021-06-15" if ftype == "date" else "e.g. 100, 250, 500")
            bp_edit.setEnabled(False)
            self.setCellWidget(row, self.COL_BREAKPOINTS, bp_edit)

            def on_method_changed(text, edit=bp_edit, nwidget=n_widget):
                # Neither "None" nor "Calendar Year" (dates only) uses a
                # fixed bucket count -- "Calendar Year" always produces
                # one bucket per year actually present instead.
                needs_n = text not in ("None", "Calendar Year")
                is_manual = (text == "Manual Breakpoints")
                nwidget.set_enabled_all(needs_n)
                edit.setEnabled(is_manual)
            method_combo.currentTextChanged.connect(on_method_changed)
            self._fill_method_combo(method_combo, ftype)  # fires on_method_changed once

            def on_categorical_toggled(checked, nwidget=n_widget, combo=method_combo, n=default_n):
                effective = "categorical" if checked else "numeric"
                nwidget.set_categorical(checked)
                self._fill_method_combo(combo, effective)
                nwidget.set_value("All" if checked else n)
            categorical_checkbox.toggled.connect(on_categorical_toggled)

            if ftype == "numeric":
                default_stats = [{"stat": self.DEFAULT_NUMERIC_STAT}]
            elif ftype == "date":
                default_stats = [{"stat": self.DEFAULT_DATE_STAT}]
            else:
                default_stats = [{"stat": "Representative Value"}]
            stat_btn = QPushButton(format_stat_button_text(default_stats))
            stat_btn.stat_cfgs = default_stats
            stat_btn.clicked.connect(lambda _checked=False, r=row: self._open_stat_dialog(r))
            self.setCellWidget(row, self.COL_STAT, stat_btn)

    def _fill_method_combo(self, method_combo: QComboBox, effective_type: str):
        """(Re)fill a row's Method combo box for the given effective type
        ("numeric", "date", or "categorical"), selecting this app's
        default method for that type. Used both for a row's initial type
        and whenever the "Categorical?" checkbox flips a numeric row's
        effective type on the fly."""
        method_combo.clear()
        if effective_type == "numeric":
            method_combo.addItems(NUMERIC_METHODS)
            default = self.DEFAULT_NUMERIC_METHOD
        elif effective_type == "date":
            method_combo.addItems(DATE_METHODS)
            default = self.DEFAULT_DATE_METHOD
        else:
            method_combo.addItems(CATEGORICAL_METHODS)
            default = self.DEFAULT_CATEGORICAL_METHOD
        idx = method_combo.findText(default)
        method_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _categorical_checkbox(self, row: int) -> QCheckBox:
        return self.cellWidget(row, self.COL_CATEGORICAL).findChild(QCheckBox)

    def effective_type(self, row: int) -> str:
        """This row's type for BUCKETING purposes -- "categorical" if the
        "Categorical?" override is checked, else its true row_types[row]
        (only numeric fields can be checked in the first place)."""
        checkbox = self._categorical_checkbox(row)
        if checkbox is not None and checkbox.isChecked():
            return "categorical"
        return self.row_types[row]

    def _open_stat_dialog(self, row: int):
        name = self.item(row, self.COL_FIELD).text()
        ftype = self.row_types[row]
        btn = self.cellWidget(row, self.COL_STAT)
        dlg = StatSelectorDialog(name, ftype, getattr(btn, "stat_cfgs", []), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            stats = dlg.get_stats()
            btn.stat_cfgs = stats
            btn.setText(format_stat_button_text(stats))

    # -- weight selection -------------------------------------------------

    def clear_weight_selection(self):
        checked = self.weight_group.checkedButton()
        if checked is not None:
            self.weight_group.setExclusive(False)
            checked.setChecked(False)
            self.weight_group.setExclusive(True)

    def get_weight_field(self):
        row = self.weight_group.checkedId()
        if row is None or row < 0:
            return None
        return self.item(row, self.COL_FIELD).text()

    def set_weight_field(self, name):
        for row in range(self.rowCount()):
            if self.item(row, self.COL_FIELD).text() == name:
                btn = self.weight_group.button(row)
                if btn is not None:
                    btn.setChecked(True)
                return

    # -- reading / writing config -----------------------------------------

    def get_row_config(self, row: int) -> dict:
        name = self.item(row, self.COL_FIELD).text()
        ftype = self.row_types[row]
        categorical_override = self.effective_type(row) == "categorical" and ftype == "numeric"
        n_widget = self.cellWidget(row, self.COL_N)
        method_combo = self.cellWidget(row, self.COL_METHOD)
        bp_edit = self.cellWidget(row, self.COL_BREAKPOINTS)
        stat_btn = self.cellWidget(row, self.COL_STAT)

        method = method_combo.currentText()
        breakpoints = None
        if not categorical_override and method == "Manual Breakpoints" and ftype in ("numeric", "date"):
            text = bp_edit.text().strip()
            breakpoints = []
            if text:
                for piece in text.split(","):
                    piece = piece.strip()
                    if piece:
                        # Numeric breakpoints are parsed here; date
                        # breakpoints are kept as plain strings and
                        # parsed by assign_date_buckets (pd.Timestamp
                        # accepts them directly).
                        breakpoints.append(float(piece) if ftype == "numeric" else piece)

        return {
            "name": name,
            "type": ftype,
            "categorical_override": categorical_override,
            "n": n_widget.value(),
            "method": method,
            "breakpoints": breakpoints,
            "stats": list(getattr(stat_btn, "stat_cfgs", [])),
        }

    def all_configs(self) -> dict:
        return {self.item(r, self.COL_FIELD).text(): self.get_row_config(r) for r in range(self.rowCount())}

    def apply_saved_config(self, fields_cfg: dict, weight_field):
        """fields_cfg: {name: {n, method, breakpoints, stats, ...}} loaded from JSON."""
        for row in range(self.rowCount()):
            name = self.item(row, self.COL_FIELD).text()
            cfg = fields_cfg.get(name)
            if not cfg:
                continue
            n_widget = self.cellWidget(row, self.COL_N)
            method_combo = self.cellWidget(row, self.COL_METHOD)
            bp_edit = self.cellWidget(row, self.COL_BREAKPOINTS)
            stat_btn = self.cellWidget(row, self.COL_STAT)

            # Restore the categorical override FIRST -- it swaps the
            # Method combo's item list (and resets N), so the method/n
            # restored just below need to land after that reset, not
            # before it.
            checkbox = self._categorical_checkbox(row)
            if checkbox is not None and checkbox.isEnabled():
                checkbox.setChecked(bool(cfg.get("categorical_override", False)))

            method = cfg.get("method")
            if method:
                idx = method_combo.findText(method)
                if idx >= 0:
                    method_combo.setCurrentIndex(idx)  # fires the enable/disable handler

            if cfg.get("n") is not None:
                n_widget.set_value(cfg["n"])

            if cfg.get("breakpoints"):
                bp_edit.setText(", ".join(str(b) for b in cfg["breakpoints"]))

            stats = cfg.get("stats") or []
            stat_btn.stat_cfgs = stats
            stat_btn.setText(format_stat_button_text(stats))

        if weight_field:
            self.set_weight_field(weight_field)


# ============================================================================
# Main window
# ============================================================================

class MainWindow(QMainWindow):
    AUTOSAVE_EXCEL_NAME = "stratification_reports.xlsx"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 900)

        self.df: pd.DataFrame | None = None
        self.field_types: dict = {}
        self.reports: dict = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- 1. File loading --------------------------------------------------
        file_box = QGroupBox("1. Load Input Data")
        file_layout = QGridLayout(file_box)

        self.csv_radio = QRadioButton("CSV/TSV file")
        self.csv_radio.setChecked(True)
        self.sqlite_radio = QRadioButton("SQLite database")
        source_group = QButtonGroup(self)
        source_group.addButton(self.csv_radio)
        source_group.addButton(self.sqlite_radio)
        self.csv_radio.toggled.connect(self.update_source_mode)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose a CSV/TSV file...")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)

        self.db_path_edit = QLineEdit()
        self.db_path_edit.setPlaceholderText("Choose a SQLite database file...")
        self.db_path_edit.editingFinished.connect(self.refresh_table_list)
        db_browse_btn = QPushButton("Browse...")
        db_browse_btn.clicked.connect(self.browse_database)
        table_label = QLabel("Table:")
        self.table_combo = QComboBox()
        self.table_combo.setEditable(True)
        self.table_combo.setToolTip(
            "Pick a table from the database, or type its name directly.")

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self.load_file)
        self.no_header_checkbox = QCheckBox(
            "File has no header row (columns will be named Column1, Column2, ... — "
            "rename them in the Field column below, then click Apply)")
        apply_names_btn = QPushButton("Apply Column Names")
        apply_names_btn.setToolTip("Sync any names you've typed into the Field column into the loaded data.")
        apply_names_btn.clicked.connect(self.apply_column_names)
        self.summary_label = QLabel("No data loaded.")

        file_layout.addWidget(self.csv_radio, 0, 0)
        file_layout.addWidget(self.path_edit, 0, 1, 1, 3)
        file_layout.addWidget(browse_btn, 0, 4)
        file_layout.addWidget(self.sqlite_radio, 1, 0)
        file_layout.addWidget(self.db_path_edit, 1, 1, 1, 3)
        file_layout.addWidget(db_browse_btn, 1, 4)
        file_layout.addWidget(table_label, 2, 1)
        file_layout.addWidget(self.table_combo, 2, 2, 1, 2)
        file_layout.addWidget(self.no_header_checkbox, 3, 0, 1, 4)
        file_layout.addWidget(apply_names_btn, 3, 4)
        file_layout.addWidget(load_btn, 4, 0)
        file_layout.addWidget(self.summary_label, 4, 1, 1, 4)
        root.addWidget(file_box)

        self.update_source_mode()

        # --- 2. Field configuration table --------------------------------------
        config_box = QGroupBox("2. Configure Fields")
        config_layout = QVBoxLayout(config_box)
        controls = QHBoxLayout()
        clear_weight_btn = QPushButton("Clear Weight Selection")
        clear_weight_btn.clicked.connect(lambda: self.field_table.clear_weight_selection())
        controls.addWidget(QLabel(
            "Pick exactly one field as WEIGHT (optional). Method='None' skips a field's own report. "
            "'All' (categorical only) gives every distinct value its own bucket. Click Summary Stats to "
            "pick one or more statistics — each becomes its own report column."))
        controls.addStretch()
        controls.addWidget(clear_weight_btn)
        config_layout.addLayout(controls)

        self.field_table = FieldConfigTable()
        config_layout.addWidget(self.field_table)
        root.addWidget(config_box, 2)

        # --- 3. Multi-field reports --------------------------------------------
        multi_box = QGroupBox("3. Multi-Field Reports (optional) — stratify on the intersection of 2+ fields")
        multi_layout = QVBoxLayout(multi_box)
        multi_btn_row = QHBoxLayout()
        add_multi_btn = QPushButton("Add Multi-Field Report...")
        add_multi_btn.clicked.connect(self.add_multi_field_report)
        remove_multi_btn = QPushButton("Remove Selected")
        remove_multi_btn.clicked.connect(self.remove_multi_field_report)
        multi_btn_row.addWidget(add_multi_btn)
        multi_btn_row.addWidget(remove_multi_btn)
        multi_btn_row.addStretch()
        multi_layout.addLayout(multi_btn_row)
        self.multi_list_widget = QListWidget()
        self.multi_list_widget.setMaximumHeight(110)
        multi_layout.addWidget(self.multi_list_widget)
        root.addWidget(multi_box)

        # --- 4. Save / load configuration --------------------------------------
        save_box = QGroupBox("4. Save / Load Configuration")
        save_layout = QHBoxLayout(save_box)
        save_cfg_btn = QPushButton("Save Configuration (.json)")
        save_cfg_btn.clicked.connect(self.save_configuration)
        load_cfg_btn = QPushButton("Load Configuration (.json)")
        load_cfg_btn.clicked.connect(self.load_configuration)
        save_layout.addWidget(save_cfg_btn)
        save_layout.addWidget(load_cfg_btn)
        save_layout.addStretch()
        root.addWidget(save_box)

        # --- 5. Generate / export ------------------------------------------------
        action_box = QGroupBox("5. Generate & Export Reports")
        action_box_layout = QVBoxLayout(action_box)

        action_layout = QHBoxLayout()
        gen_btn = QPushButton("Generate Reports")
        gen_btn.clicked.connect(self.generate_reports)
        export_xlsx_btn = QPushButton("Export All to Excel (.xlsx)")
        export_xlsx_btn.clicked.connect(self.export_excel)
        export_csv_btn = QPushButton("Export All to CSV Folder")
        export_csv_btn.clicked.connect(self.export_csv_folder)
        action_layout.addWidget(gen_btn)
        action_layout.addWidget(export_xlsx_btn)
        action_layout.addWidget(export_csv_btn)
        action_layout.addStretch()
        action_box_layout.addLayout(action_layout)

        autosave_layout = QHBoxLayout()
        self.autosave_checkbox = QCheckBox("Auto-save reports to a folder after generating")
        self.autosave_checkbox.setToolTip(
            "Handy for a report that takes a while to generate -- every report is written\n"
            "to this folder (as separate CSV files, one per report, PLUS one combined\n"
            f"{self.AUTOSAVE_EXCEL_NAME} workbook) right after Generate Reports finishes,\n"
            "with no extra click, so it's there to look at later even if you've stepped away.")
        self.autosave_checkbox.toggled.connect(self._update_autosave_enabled)
        self.autosave_folder_edit = QLineEdit()
        self.autosave_folder_edit.setPlaceholderText("Choose a folder...")
        self.autosave_folder_edit.setEnabled(False)
        autosave_browse_btn = QPushButton("Browse...")
        autosave_browse_btn.setEnabled(False)
        autosave_browse_btn.clicked.connect(self.browse_autosave_folder)
        self.autosave_browse_btn = autosave_browse_btn
        autosave_layout.addWidget(self.autosave_checkbox)
        autosave_layout.addWidget(self.autosave_folder_edit)
        autosave_layout.addWidget(autosave_browse_btn)
        action_box_layout.addLayout(autosave_layout)

        self.autosave_status_label = QLabel("")
        action_box_layout.addWidget(self.autosave_status_label)

        root.addWidget(action_box)

        # --- 6. Report tabs ---------------------------------------------------------
        reports_box = QGroupBox("6. Reports")
        reports_layout = QVBoxLayout(reports_box)
        self.tabs = QTabWidget()
        reports_layout.addWidget(self.tabs)
        root.addWidget(reports_box, 3)

    # ------------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------------

    def update_source_mode(self):
        """Enable/disable the CSV-only and SQLite-only controls to match
        whichever source radio is selected."""
        is_csv = self.csv_radio.isChecked()
        self.path_edit.setEnabled(is_csv)
        self.no_header_checkbox.setEnabled(is_csv)
        self.db_path_edit.setEnabled(not is_csv)
        self.table_combo.setEnabled(not is_csv)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select input data file", "", "Data files (*.csv *.tsv *.txt);;All files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def browse_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SQLite database", "",
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)"
        )
        if path:
            self.db_path_edit.setText(path)
            self.refresh_table_list()

    def refresh_table_list(self):
        """Populate the Table combo box with every table in whatever
        database db_path_edit currently points to, so the user can pick
        one from a list instead of having to already know its name.
        Silently does nothing if the path isn't (yet) a valid SQLite
        file -- e.g. while the user is still typing it -- rather than
        popping up an error for an incomplete path."""
        db_path = self.db_path_edit.text().strip()
        self.table_combo.clear()
        if not db_path or not os.path.isfile(db_path):
            return
        try:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return
        self.table_combo.addItems([row[0] for row in rows])

    def load_file(self):
        if self.sqlite_radio.isChecked():
            df = self._read_sqlite_table()
        else:
            df = self._read_csv_file()
        if df is None:
            return

        if df.shape[1] < 2:
            QMessageBox.warning(self, APP_TITLE, "Data must have at least 2 columns "
                                                   "(need something to stratify and summarize).")

        self.df = df
        self.field_types = detect_field_types(df)
        self.field_table.populate(self.field_types, default_n=5)
        self.summary_label.setText(f"Loaded {len(df):,} rows, {df.shape[1]} fields.")
        self.tabs.clear()
        self.reports = {}
        self.multi_list_widget.clear()

    def _read_csv_file(self):
        """Read the CSV/TSV file named in path_edit. Returns a DataFrame,
        or None (after showing an error) if it couldn't be read."""
        path = self.path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, APP_TITLE, "Please choose a valid file first.")
            return None

        no_header = self.no_header_checkbox.isChecked()
        df = None
        for kwargs in ([{"sep": None, "engine": "python"}], [{}]):
            try:
                read_kwargs = dict(kwargs[0])
                if no_header:
                    read_kwargs["header"] = None
                df = pd.read_csv(path, **read_kwargs)
                break
            except Exception:
                continue
        if df is None:
            QMessageBox.critical(self, APP_TITLE, "Could not read this file as delimited data.")
            return None

        if no_header:
            df.columns = [f"Column{i + 1}" for i in range(df.shape[1])]
        return df

    def _read_sqlite_table(self):
        """Read every row of the table named in table_combo from the
        SQLite database named in db_path_edit. Returns a DataFrame, or
        None (after showing an error) if it couldn't be read."""
        db_path = self.db_path_edit.text().strip()
        table = self.table_combo.currentText().strip()
        if not db_path or not os.path.isfile(db_path):
            QMessageBox.warning(self, APP_TITLE, "Please choose a valid SQLite database file first.")
            return None
        if not table:
            QMessageBox.warning(self, APP_TITLE, "Please choose or type a table name first.")
            return None

        try:
            conn = sqlite3.connect(db_path)
            try:
                # Confirm the table actually exists before splicing its
                # name into a SQL string -- both to give a clear error
                # message for a typo'd/missing table, and so the name
                # (typed by hand, not chosen from the list) can't be
                # anything other than a real table identifier.
                existing_tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if table not in existing_tables:
                    QMessageBox.critical(self, APP_TITLE, f"No table named {table!r} in this database.")
                    return None
                quoted_table = '"%s"' % table.replace('"', '""')
                df = pd.read_sql_query(f"SELECT * FROM {quoted_table}", conn)
            finally:
                conn.close()
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Could not read table {table!r}:\n{exc}")
            return None
        return df

    def apply_column_names(self):
        if self.df is None:
            QMessageBox.warning(self, APP_TITLE, "Load a data file first.")
            return
        try:
            self._sync_column_names()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        QMessageBox.information(self, APP_TITLE, "Column names updated.")

    def _sync_column_names(self):
        """Make self.df / self.field_types match whatever is currently typed
        into the Field column of the table (position-for-position)."""
        if self.df is None:
            return
        new_names = [self.field_table.item(r, FieldConfigTable.COL_FIELD).text().strip()
                     for r in range(self.field_table.rowCount())]
        if len(new_names) != self.df.shape[1]:
            return
        if any(not nm for nm in new_names):
            raise ValueError("Field names cannot be blank.")
        if len(set(new_names)) != len(new_names):
            raise ValueError("Field names must be unique.")
        old_names = list(self.df.columns)
        if new_names == old_names:
            return
        self.field_types = {new_names[i]: self.field_types[old_names[i]] for i in range(len(old_names))}
        self.df.columns = new_names

    # ------------------------------------------------------------------------
    # Multi-field report management
    # ------------------------------------------------------------------------

    def add_multi_field_report(self):
        if self.df is None:
            QMessageBox.warning(self, APP_TITLE, "Load a data file first.")
            return
        try:
            self._sync_column_names()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return

        eligible = []
        for row in range(self.field_table.rowCount()):
            cfg = self.field_table.get_row_config(row)
            if cfg["method"] != "None":
                eligible.append((cfg["name"], cfg["type"]))
        if len(eligible) < 2:
            QMessageBox.warning(self, APP_TITLE, "Need at least 2 fields with a bucketing Method "
                                                   "(not 'None') to build a multi-field report.")
            return

        dlg = MultiFieldDialog(eligible, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, fields = dlg.get_result()
            self._add_multi_field_item(name, fields)

    def _add_multi_field_item(self, name, fields):
        item = QListWidgetItem(f"{name}:  {' × '.join(fields)}")
        item.setData(Qt.ItemDataRole.UserRole, {"name": name, "fields": fields})
        self.multi_list_widget.addItem(item)

    def remove_multi_field_report(self):
        row = self.multi_list_widget.currentRow()
        if row >= 0:
            self.multi_list_widget.takeItem(row)

    # ------------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------------

    def generate_reports(self):
        if self.df is None:
            QMessageBox.warning(self, APP_TITLE, "Load a data file first.")
            return
        try:
            self._sync_column_names()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return

        try:
            configs = self.field_table.all_configs()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, f"Invalid breakpoints: {exc}")
            return

        weight_field = self.field_table.get_weight_field()
        stat_configs = {name: cfg["stats"] for name, cfg in configs.items()}
        categorical_overrides = frozenset(
            name for name, cfg in configs.items() if cfg["categorical_override"])

        self.tabs.clear()
        self.reports = {}
        errors = []

        # --- overall report: every record in the file, as a single row ---
        try:
            overall_df = build_overall_report(self.df, self.field_types, weight_field, stat_configs)
            self.reports["All Records"] = overall_df
            self._add_report_tab("All Records", overall_df)
        except Exception as exc:
            errors.append(f"'All Records': {exc}")

        # --- single-field reports ---
        for name, cfg in configs.items():
            if cfg["method"] == "None":
                continue
            try:
                if (not cfg["categorical_override"] and cfg["type"] in ("numeric", "date")
                        and cfg["method"] == "Manual Breakpoints" and not cfg["breakpoints"]):
                    errors.append(f"'{name}': Manual Breakpoints selected but no breakpoints were entered.")
                    continue
                report_df = build_report(
                    self.df, name, self.field_types, weight_field, stat_configs,
                    n=cfg["n"], method=cfg["method"], breakpoints=cfg["breakpoints"],
                    categorical_overrides=categorical_overrides,
                )
                self.reports[name] = report_df
                self._add_report_tab(name, report_df)
            except Exception as exc:
                errors.append(f"'{name}': {exc}")

        # --- multi-field reports ---
        n_by_field = {name: cfg["n"] for name, cfg in configs.items()}
        method_by_field = {name: cfg["method"] for name, cfg in configs.items()}
        breakpoints_by_field = {name: cfg["breakpoints"] for name, cfg in configs.items()}

        for i in range(self.multi_list_widget.count()):
            item = self.multi_list_widget.item(i)
            spec = item.data(Qt.ItemDataRole.UserRole)
            name, fields = spec["name"], spec["fields"]
            try:
                bad = [f for f in fields if method_by_field.get(f) == "None"]
                if bad:
                    errors.append(f"Multi-field report '{name}': fields {bad} have Method = 'None'.")
                    continue
                est = estimate_combo_count(self.df, fields, n_by_field, self.field_types)
                if est > MULTI_COMBO_WARN_THRESHOLD:
                    resp = QMessageBox.question(
                        self, APP_TITLE,
                        f"Multi-field report '{name}' could produce up to ~{est:,} bucket combinations "
                        "(actual rows with missing values may add a few more). This may be slow. Continue?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if resp != QMessageBox.StandardButton.Yes:
                        continue
                report_df = build_multi_field_report(
                    self.df, fields, self.field_types, weight_field, stat_configs,
                    n_by_field, method_by_field, breakpoints_by_field,
                    categorical_overrides=categorical_overrides,
                )
                tab_name = f"[Multi] {name}"
                self.reports[tab_name] = report_df
                self._add_report_tab(tab_name, report_df)
            except Exception as exc:
                errors.append(f"Multi-field report '{name}': {exc}")

        if errors:
            QMessageBox.warning(self, APP_TITLE, "Some reports could not be generated:\n\n" + "\n".join(errors))

        self._maybe_autosave_reports()

    def _add_report_tab(self, tab_name: str, report_df: pd.DataFrame):
        table = QTableWidget(report_df.shape[0], report_df.shape[1])
        table.setHorizontalHeaderLabels([str(c) for c in report_df.columns])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)

        for r in range(report_df.shape[0]):
            for c, col in enumerate(report_df.columns):
                val = report_df.iat[r, c]
                if isinstance(val, float):
                    text = f"{val:,.4g}"
                elif pd.isna(val):
                    text = ""
                else:
                    text = str(val)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)

        self.tabs.addTab(table, tab_name)

    # ------------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------------

    def export_excel(self):
        if not self.reports:
            QMessageBox.warning(self, APP_TITLE, "Generate reports first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel workbook", "stratification_reports.xlsx",
                                                "Excel files (*.xlsx)")
        if not path:
            return
        try:
            self._write_reports_to_excel(path)
            QMessageBox.information(self, APP_TITLE, f"Saved workbook to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Could not save workbook:\n{exc}")

    def _write_reports_to_excel(self, path: str):
        """The actual Excel-writing logic, shared by export_excel()
        (explicit button, path chosen via a dialog every time) and the
        "Auto-save" checkbox (implicit, fixed filename every time -- see
        generate_reports())."""
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            used_names = set()
            for name, report_df in self.reports.items():
                sheet_name = str(name)[:31] or "Sheet"
                base = sheet_name
                i = 1
                while sheet_name in used_names:
                    suffix = f"_{i}"
                    sheet_name = base[: 31 - len(suffix)] + suffix
                    i += 1
                used_names.add(sheet_name)
                report_df.to_excel(writer, sheet_name=sheet_name, index=False)

    def export_csv_folder(self):
        if not self.reports:
            QMessageBox.warning(self, APP_TITLE, "Generate reports first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not folder:
            return
        try:
            self._write_reports_to_csv_folder(folder)
            QMessageBox.information(self, APP_TITLE, f"Saved {len(self.reports)} CSV files to:\n{folder}")
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Could not save CSV files:\n{exc}")

    def _write_reports_to_csv_folder(self, folder: str):
        """The actual CSV-writing loop, shared by export_csv_folder()
        (explicit button, folder chosen via a dialog every time) and the
        "Auto-save" checkbox (implicit, same folder every time -- see
        generate_reports())."""
        for name, report_df in self.reports.items():
            safe_name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in str(name))
            out_path = os.path.join(folder, f"{safe_name}_report.csv")
            report_df.to_csv(out_path, index=False)

    # ------------------------------------------------------------------------
    # Auto-save
    # ------------------------------------------------------------------------

    def _update_autosave_enabled(self, checked: bool):
        self.autosave_folder_edit.setEnabled(checked)
        self.autosave_browse_btn.setEnabled(checked)

    def browse_autosave_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose auto-save folder")
        if folder:
            self.autosave_folder_edit.setText(folder)

    def _maybe_autosave_reports(self):
        """Called at the end of generate_reports(), below. Silent on
        success (just updates autosave_status_label) so re-generating
        reports repeatedly while iterating on settings doesn't pop up a
        dialog every time; still shown as a critical error on failure,
        since that's something the user needs to actually notice."""
        if not self.autosave_checkbox.isChecked():
            return
        folder = self.autosave_folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(
                self, APP_TITLE,
                "Auto-save is checked, but no valid folder is set -- reports were "
                "generated but NOT auto-saved. Choose a folder next to the checkbox.")
            return
        try:
            self._write_reports_to_csv_folder(folder)
            self._write_reports_to_excel(os.path.join(folder, self.AUTOSAVE_EXCEL_NAME))
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Auto-save failed:\n{exc}")
            return
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.autosave_status_label.setText(
            f"Auto-saved {len(self.reports)} report(s) as CSVs and {self.AUTOSAVE_EXCEL_NAME} "
            f"to {folder} at {timestamp}.")

    # ------------------------------------------------------------------------
    # Save / load configuration
    # ------------------------------------------------------------------------

    def save_configuration(self):
        if self.df is None:
            QMessageBox.warning(self, APP_TITLE, "Load a data file first.")
            return
        try:
            self._sync_column_names()
            configs = self.field_table.all_configs()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return

        path, _ = QFileDialog.getSaveFileName(self, "Save configuration", "stratification_config.json",
                                                "JSON files (*.json)")
        if not path:
            return

        fields_list = []
        for name, cfg in configs.items():
            fields_list.append({
                "name": name,
                "type": cfg["type"],
                "categorical_override": cfg["categorical_override"],
                "n": cfg["n"],
                "method": cfg["method"],
                "breakpoints": cfg["breakpoints"],
                "stats": cfg["stats"],
            })

        multi_list = []
        for i in range(self.multi_list_widget.count()):
            multi_list.append(self.multi_list_widget.item(i).data(Qt.ItemDataRole.UserRole))

        data = {
            "app": APP_TITLE,
            "config_version": CONFIG_VERSION,
            "input_source": "sqlite" if self.sqlite_radio.isChecked() else "csv",
            "input_file": self.path_edit.text(),
            "no_header": self.no_header_checkbox.isChecked(),
            "database_file": self.db_path_edit.text(),
            "table_name": self.table_combo.currentText(),
            "weight_field": self.field_table.get_weight_field(),
            "fields": fields_list,
            "multi_field_reports": multi_list,
        }
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, APP_TITLE, f"Saved configuration to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Could not save configuration:\n{exc}")

    def load_configuration(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load configuration", "", "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Could not read configuration:\n{exc}")
            return

        input_source = data.get("input_source", "csv")   # older configs predate SQLite support
        input_file = data.get("input_file")
        no_header = bool(data.get("no_header", False))
        database_file = data.get("database_file")
        table_name = data.get("table_name")

        if input_source == "sqlite" and database_file and os.path.isfile(database_file):
            self.sqlite_radio.setChecked(True)
            self.db_path_edit.setText(database_file)
            self.refresh_table_list()
            self.table_combo.setCurrentText(table_name or "")
            self.load_file()
        elif input_source == "csv" and input_file and os.path.isfile(input_file):
            self.csv_radio.setChecked(True)
            self.no_header_checkbox.setChecked(no_header)
            self.path_edit.setText(input_file)
            self.load_file()
        elif self.df is None:
            missing = database_file if input_source == "sqlite" else input_file
            QMessageBox.warning(
                self, APP_TITLE,
                "This configuration references a data source that could not be found:\n"
                f"{missing}\n\nLoad a data source first, then load this configuration again "
                "to apply the saved field settings.")
            return
        # else: keep using whatever data source is already loaded

        fields_cfg = {f["name"]: f for f in data.get("fields", [])}
        self.field_table.apply_saved_config(fields_cfg, data.get("weight_field"))

        self.multi_list_widget.clear()
        for spec in data.get("multi_field_reports", []):
            self._add_multi_field_item(spec.get("name", ""), spec.get("fields", []))

        QMessageBox.information(self, APP_TITLE, "Configuration loaded.")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
