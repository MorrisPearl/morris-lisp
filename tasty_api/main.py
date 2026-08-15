#!/usr/bin/env python3
"""
CME Futures Options & Relative Value Viewer (tastytrade)
===========================================================
Tab 1 "Options": lists options on CME futures for a selected product
(WTI Crude Oil, Micro WTI, E-mini S&P 500, E-mini Nasdaq-100, Three-Month
SOFR, 10-Year T-Note, 30-Day Fed Funds) in a sortable, filterable PyQt6
QTableView.

Tab 2 "Futures Relative Value": pulls the selected product's futures term
structure and flags contract months that look rich/cheap relative to a
fitted curve, plus a calendar-spread breakdown of implied carry (with a
storage-cost/convenience-yield decomposition that's economically
meaningful for CL/MCL, and a looser "implied carry" read for the
financial products — see the in-app note).

Data source: tastytrade (real broker data). Requires a tastytrade
account and a small local JSON credentials file — see README.md for the
one-time OAuth setup.

Run:
    pip install -r requirements.txt
    python main.py
"""

from __future__ import annotations

import sys
import datetime as dt

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableView, QPushButton, QLabel, QLineEdit, QComboBox, QSpinBox,
    QDoubleSpinBox, QHeaderView, QStatusBar, QMessageBox, QAbstractItemView,
    QTabWidget, QGroupBox, QFileDialog,
)

from relative_value import compute_curve_fit, compute_leg_carry
from models import PandasTableModel, OptionsFilterProxyModel
from tastytrade_source import (
    PRODUCTS, TastytradeOptionsFetchWorker, TastytradeFuturesCurveWorker,
    TastytradeTestConnectionWorker,
)


class CredentialsBar(QWidget):
    """tastytrade credentials-file picker + connection test, shared by
    both tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("CMECrudeOptionsApp", "CMECrudeOptionsApp")
        self._test_worker: TastytradeTestConnectionWorker | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("tastytrade credentials file:"))
        self.path_edit = QLineEdit()
        default_path = self._settings.value(
            "tastytrade_credentials_path", "tastytrade_credentials.json"
        )
        self.path_edit.setText(default_path)
        self.path_edit.textChanged.connect(
            lambda text: self._settings.setValue("tastytrade_credentials_path", text)
        )
        layout.addWidget(self.path_edit, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        layout.addWidget(self.test_btn)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def credentials_path(self) -> str:
        return self.path_edit.text().strip()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select tastytrade credentials JSON file", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def _test_connection(self):
        if self._test_worker is not None and self._test_worker.isRunning():
            return
        self.status_label.setText("Testing...")
        self.status_label.setStyleSheet("")
        self.test_btn.setEnabled(False)
        self._test_worker = TastytradeTestConnectionWorker(self.credentials_path())
        self._test_worker.succeeded.connect(self._on_test_ok)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.start()

    def _on_test_ok(self, message):
        self.test_btn.setEnabled(True)
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #2e7d32;")

    def _on_test_failed(self, message):
        self.test_btn.setEnabled(True)
        self.status_label.setText("Connection failed — see dialog")
        self.status_label.setStyleSheet("color: #c62828;")
        QMessageBox.critical(self, "tastytrade connection failed", message)


def _populate_product_combo(combo: QComboBox):
    for code, info in PRODUCTS.items():
        combo.addItem(info["label"], code)


class OptionsTab(QWidget):
    """Tab 1: the options chain table."""

    def __init__(self, credentials_bar: CredentialsBar, parent=None):
        super().__init__(parent)
        self.credentials_bar = credentials_bar
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Product:"))
        self.product_combo = QComboBox()
        _populate_product_combo(self.product_combo)
        controls.addWidget(self.product_combo)

        controls.addWidget(QLabel("Months ahead:"))
        self.months_spin = QSpinBox()
        self.months_spin.setRange(1, 36)
        self.months_spin.setValue(12)
        self.months_spin.setToolTip("How many upcoming delivery months to fetch.")
        controls.addWidget(self.months_spin)

        self.refresh_btn = QPushButton("Refresh Data")
        controls.addWidget(self.refresh_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_fetch)
        controls.addWidget(self.cancel_btn)

        layout.addLayout(controls)

        tt_row = QHBoxLayout()
        tt_row.addWidget(QLabel("Max strikes near money (per expiration):"))
        self.max_strikes_spin = QSpinBox()
        self.max_strikes_spin.setRange(3, 100)
        self.max_strikes_spin.setValue(15)
        self.max_strikes_spin.setToolTip(
            "Implied volatility comes from a live Greeks stream, one "
            "subscription per contract, so the chain is trimmed to the N "
            "strikes nearest the underlying's price per expiration to keep "
            "fetch time and subscription count reasonable."
        )
        tt_row.addWidget(self.max_strikes_spin)
        tt_row.addWidget(QLabel("Greeks stream timeout (sec):"))
        self.greeks_timeout_spin = QDoubleSpinBox()
        self.greeks_timeout_spin.setRange(5.0, 180.0)
        self.greeks_timeout_spin.setValue(25.0)
        self.greeks_timeout_spin.setDecimals(0)
        tt_row.addWidget(self.greeks_timeout_spin)
        tt_row.addStretch(1)
        layout.addLayout(tt_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["All", "Call", "Put"])
        self.type_combo.currentTextChanged.connect(self._apply_filters)
        filter_row.addWidget(self.type_combo)

        filter_row.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("symbol, delivery month, expiration...")
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_edit, stretch=1)
        layout.addLayout(filter_row)

        self.table_model = PandasTableModel()
        self.proxy_model = OptionsFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)

        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setVisible(False)
        layout.addWidget(self.table_view, stretch=1)

        self.info_label = QLabel(
            "Real chains via tastytrade — implied volatility comes from a live Greeks "
            "stream, so it may be blank for illiquid strikes that haven't published a "
            "recent snapshot within the timeout above."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.info_label)

    def _apply_filters(self):
        self.proxy_model.setTypeFilter(self.type_combo.currentText())
        self.proxy_model.setSearchText(self.search_edit.text())

    def start_fetch(self, status_cb=None, finished_cb=None, failed_cb=None):
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        creds_path = self.credentials_bar.credentials_path()
        if not creds_path:
            self.refresh_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            if failed_cb:
                failed_cb("Set a tastytrade credentials file path above first.")
            return

        product = self.product_combo.currentData()
        self._worker = TastytradeOptionsFetchWorker(
            credentials_path=creds_path,
            product=product,
            n_months=self.months_spin.value(),
            max_strikes_per_expiration=self.max_strikes_spin.value(),
            greeks_timeout=self.greeks_timeout_spin.value(),
        )

        if status_cb:
            self._worker.progress.connect(status_cb)
        self._worker.finished_ok.connect(lambda df: self._on_finished(df, finished_cb))
        self._worker.failed.connect(lambda msg: self._on_failed(msg, failed_cb))
        self._worker.start()

    def cancel_fetch(self):
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self, df, finished_cb):
        self.refresh_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.table_model.setDataFrame(df)
        self.table_view.resizeColumnsToContents()
        if finished_cb:
            finished_cb(df)

    def _on_failed(self, message, failed_cb):
        self.refresh_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if failed_cb:
            failed_cb(message)

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)


class RelativeValueTab(QWidget):
    """Tab 2: futures curve rich/cheap + calendar-spread carry analysis."""

    def __init__(self, credentials_bar: CredentialsBar, parent=None):
        super().__init__(parent)
        self.credentials_bar = credentials_bar
        self._worker = None
        self._raw_curve = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Product:"))
        self.product_combo = QComboBox()
        _populate_product_combo(self.product_combo)
        controls.addWidget(self.product_combo)

        controls.addWidget(QLabel("Months ahead:"))
        self.months_spin = QSpinBox()
        self.months_spin.setRange(2, 36)
        self.months_spin.setValue(18)
        controls.addWidget(self.months_spin)

        self.refresh_btn = QPushButton("Refresh Curve")
        controls.addWidget(self.refresh_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_fetch)
        controls.addWidget(self.cancel_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        assumptions_box = QGroupBox("Assumptions (editable — recompute instantly, no refetch needed)")
        assumptions_layout = QHBoxLayout(assumptions_box)

        assumptions_layout.addWidget(QLabel("Annual funding rate r (%):"))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(-10.0, 25.0)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSingleStep(0.25)
        self.rate_spin.setValue(4.25)
        self.rate_spin.setToolTip(
            "Your assumed cost of financing (e.g. current SOFR/T-bill rate). "
            "Used to back out implied storage cost from the observed curve."
        )
        self.rate_spin.valueChanged.connect(self._recompute)
        assumptions_layout.addWidget(self.rate_spin)

        assumptions_layout.addWidget(QLabel("Annual storage cost u (%):"))
        self.storage_spin = QDoubleSpinBox()
        self.storage_spin.setRange(-10.0, 25.0)
        self.storage_spin.setDecimals(2)
        self.storage_spin.setSingleStep(0.25)
        self.storage_spin.setValue(3.0)
        self.storage_spin.setToolTip(
            "Your assumed annualized storage cost as a % of the futures price. "
            "Only economically meaningful for physical commodities (CL/MCL) — "
            "for financial products (ES, NQ, ZN, SR3, ZQ) there's no real "
            "storage, so treat this column as illustrative there, not literal. "
            "Used to back out implied convenience yield from the observed curve."
        )
        self.storage_spin.valueChanged.connect(self._recompute)
        assumptions_layout.addWidget(self.storage_spin)

        assumptions_layout.addWidget(QLabel("Rich/Cheap threshold (%):"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.05, 10.0)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.75)
        self.threshold_spin.setToolTip(
            "Minimum deviation from the fitted curve (per-contract) or from "
            "the median implied carry rate (per-leg) before a contract is "
            "flagged Rich or Cheap."
        )
        self.threshold_spin.valueChanged.connect(self._recompute)
        assumptions_layout.addWidget(self.threshold_spin)

        layout.addWidget(assumptions_box)

        layout.addWidget(QLabel("Per-contract rich/cheap vs. fitted curve:"))
        self.curve_model = PandasTableModel()
        self.curve_view = QTableView()
        self.curve_view.setModel(self.curve_model)
        self.curve_view.setSortingEnabled(True)
        self.curve_view.setAlternatingRowColors(True)
        self.curve_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.curve_view.horizontalHeader().setStretchLastSection(True)
        self.curve_view.verticalHeader().setVisible(False)
        layout.addWidget(self.curve_view, stretch=1)

        layout.addWidget(QLabel("Calendar-spread implied carry / storage / convenience yield:"))
        self.leg_model = PandasTableModel()
        self.leg_view = QTableView()
        self.leg_view.setModel(self.leg_model)
        self.leg_view.setSortingEnabled(True)
        self.leg_view.setAlternatingRowColors(True)
        self.leg_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.leg_view.horizontalHeader().setStretchLastSection(True)
        self.leg_view.verticalHeader().setVisible(False)
        layout.addWidget(self.leg_view, stretch=1)

        note = QLabel(
            "Methodology: c = ln(F2/F1)/(T2-T1) is observed from prices. "
            "Net storage cost = c − r (given your funding-rate assumption). "
            "Convenience yield = r + u − c (given both assumptions). Storage/"
            "convenience-yield labels are literal for CL/MCL only — for ES, NQ, "
            "ZN, SR3, ZQ read them as an illustrative decomposition of implied "
            "carry, not a real storage estimate. This is a simplified "
            "single-factor model either way — treat flags as a starting point "
            "for research, not a trading signal on their own."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(note)

    def start_fetch(self, status_cb=None, finished_cb=None, failed_cb=None):
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        creds_path = self.credentials_bar.credentials_path()
        if not creds_path:
            self.refresh_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            if failed_cb:
                failed_cb("Set a tastytrade credentials file path above first.")
            return

        self._worker = TastytradeFuturesCurveWorker(
            credentials_path=creds_path,
            product=self.product_combo.currentData(),
            n_months=self.months_spin.value(),
        )

        if status_cb:
            self._worker.progress.connect(status_cb)
        self._worker.finished_ok.connect(lambda df: self._on_finished(df, finished_cb))
        self._worker.failed.connect(lambda msg: self._on_failed(msg, failed_cb))
        self._worker.start()

    def cancel_fetch(self):
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self, df, finished_cb):
        self.refresh_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._raw_curve = df
        self._recompute()
        if finished_cb:
            finished_cb(df)

    def _on_failed(self, message, failed_cb):
        self.refresh_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if failed_cb:
            failed_cb(message)

    def _recompute(self):
        if self._raw_curve is None or self._raw_curve.empty:
            return
        curve_df = compute_curve_fit(
            self._raw_curve, rich_cheap_threshold_pct=self.threshold_spin.value()
        )
        leg_df = compute_leg_carry(
            self._raw_curve,
            funding_rate_pct=self.rate_spin.value(),
            storage_cost_pct=self.storage_spin.value(),
            leg_signal_threshold_pct=self.threshold_spin.value(),
        )
        self.curve_model.setDataFrame(curve_df)
        self.leg_model.setDataFrame(leg_df)
        self.curve_view.resizeColumnsToContents()
        self.leg_view.resizeColumnsToContents()

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CME Futures Options & Relative Value (tastytrade) — delayed / EOD data")
        self.resize(1300, 850)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(6, 6, 6, 6)

        self.credentials_bar = CredentialsBar()
        central_layout.addWidget(self.credentials_bar)

        self.options_tab = OptionsTab(self.credentials_bar)
        self.rv_tab = RelativeValueTab(self.credentials_bar)

        tabs = QTabWidget()
        tabs.addTab(self.options_tab, "Options")
        tabs.addTab(self.rv_tab, "Futures Relative Value")
        central_layout.addWidget(tabs, stretch=1)

        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.last_updated_label = QLabel("No data loaded yet.")
        self.status.addPermanentWidget(self.last_updated_label)
        self.status.showMessage(
            "Tip: click column headers to sort. Rich/Cheap rows on the "
            "Relative Value tab are color-highlighted."
        )

        self.options_tab.refresh_btn.clicked.connect(
            lambda: self.options_tab.start_fetch(
                status_cb=self.status.showMessage,
                finished_cb=lambda df: self._note_update(f"{len(df)} option contracts"),
                failed_cb=lambda msg: self._on_failed(msg),
            )
        )
        self.rv_tab.refresh_btn.clicked.connect(
            lambda: self.rv_tab.start_fetch(
                status_cb=self.status.showMessage,
                finished_cb=lambda df: self._note_update(f"{len(df)} futures contract months"),
                failed_cb=lambda msg: self._on_failed(msg),
            )
        )

    def _note_update(self, detail: str):
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_updated_label.setText(f"Last updated: {now}  |  {detail}")

    def _on_failed(self, message):
        self.status.showMessage("Fetch failed.")
        QMessageBox.critical(self, "Fetch failed", message)

    def closeEvent(self, event):
        self.options_tab.shutdown()
        self.rv_tab.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CME Futures Options & Relative Value Viewer")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
