"""
term_structure_gui.py

A small PyQt6 GUI on top of term_structure_model.py.

Two tabs:
  - "Rate Path Chart": simulate a chosen number of Monte Carlo interest
    rate paths and plot the short-end (SOFR-like) rate, the model's
    approximate ~10-year (Treasury-like) rate, or a simple proxy
    mortgage rate (~10-year rate + a flat spread you choose).
  - "Callable Bond (OAS)": enter a callable bond's term, coupon rate,
    call date, call price, and an option-adjusted spread (OAS), and see
    the Monte Carlo price the model computes.

Both tabs work off whichever curve + volatilities are currently active,
set by ONE of two "Market & Model Setup" panels at the top:
  - "Treasury Curve (manual)": type in T-bill/par-bond yields yourself
    (bootstrap_forward_curve) and set sigma1/sigma2 by hand.
  - "SOFR Curve (tastytrade, live)": fetch real, exchange-traded CME SOFR
    (SR3) futures + a spread of options on them (sofr_market_data.py),
    bootstrap the curve from the futures (bootstrap_sofr_curve), and
    calibrate sigma1/sigma2 to the options (calibrate_volatilities) --
    all with one click each.

Run with:      python3 term_structure_gui.py
Requires:      pip install PyQt6 matplotlib numpy
Also needs:    term_structure_model.py and sofr_market_data.py in the
               same folder (and, for the SOFR panel, a tastytrade account
               -- see ../tasty_api/README.md for the one-time OAuth setup).

DESIGN NOTE: like term_structure_model.py, this file favors readable,
explicit code over cleverness. Every simulation runs synchronously on
the UI thread when you click a button -- with a few thousand Monte
Carlo paths this takes a fraction of a second, so no background-thread
/ progress-bar machinery is used there. The one exception is the SOFR
panel's tastytrade fetch, which does real network I/O (a few seconds) and
so runs on a QThread, the same pattern ../tasty_api/tastytrade_source.py
uses, so the window doesn't freeze while it waits on the network.
"""

import sys

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import sofr_market_data as smd
import term_structure_model as tsm

# Default yield curve shown when the GUI opens, as (key, rate in percent).
# Illustrative only -- type in real market rates before relying on this.
DEFAULT_CURVE_PCT = [
    ('3m', 4.30), ('6m', 4.10), ('12m', 3.90),
    ('2y', 3.80), ('5y', 4.00), ('10y', 4.30), ('30y', 4.60),
]


class SofrFetchWorker(QThread):
    """Fetches real SOFR futures + option quotes from tastytrade off the
    UI thread (see sofr_market_data.fetch_sofr_calibration_data)."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object, object)  # curve_futures, options
    failed = pyqtSignal(str)

    def __init__(self, credentials_path, parent=None):
        super().__init__(parent)
        self.credentials_path = credentials_path

    def run(self):
        self.progress.emit("Fetching SOFR futures + options from tastytrade...")
        try:
            curve_futures, options = smd.fetch_sofr_calibration_data(self.credentials_path)
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(curve_futures, options)


class SofrCalibrationWorker(QThread):
    """Runs term_structure_model.calibrate_sofr_model() off the UI thread.

    Unlike the plain sigma1/sigma2 calibration this replaced, calibrating
    (a, sigma1, sigma2) together is a 3-D grid search and takes on the
    order of ten to twenty seconds (see calibrate_sofr_model()'s
    docstring for why that's still fast enough to just do directly) --
    long enough that blocking the UI thread for it would be a bad idea."""

    finished_ok = pyqtSignal(object)  # (a, theta_bar, sigma1, sigma2, error)
    failed = pyqtSignal(str)

    def __init__(self, forward_rates, options, curve_real_months, parent=None):
        super().__init__(parent)
        self.forward_rates = forward_rates
        self.options = options
        self.curve_real_months = curve_real_months

    def run(self):
        try:
            result = tsm.calibrate_sofr_model(self.forward_rates, self.options, self.curve_real_months)
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(result)


class TermStructureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Two-Factor Term Structure Model")
        self.resize(1000, 720)

        self.forward_rates = None  # set by _on_bootstrap_clicked() / _on_sofr_fetch_finished()
        self.curve_source = None  # "Treasury (manual)" or "SOFR (live, tastytrade)"
        self.sofr_curve_futures = None  # set once a SOFR fetch succeeds
        self.sofr_options = None
        self.sofr_a = None  # set once "Calibrate to SOFR Options" succeeds
        self.sofr_theta_bar = None  # set together with sofr_a
        self._sofr_fetch_worker = None
        self._sofr_calibration_worker = None

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        main_layout.addWidget(self._build_market_setup_group())
        main_layout.addWidget(self._build_sofr_group())

        tabs = QTabWidget()
        tabs.addTab(self._build_chart_tab(), "Rate Path Chart")
        tabs.addTab(self._build_bond_tab(), "Callable Bond (OAS)")
        main_layout.addWidget(tabs)

        # Bootstrap once at startup with the default Treasury curve, so
        # both tabs have something to work with immediately. Fetching the
        # live SOFR curve is left to the user (it needs a network call).
        self._on_bootstrap_clicked()

    # ------------------------------------------------------------------
    # Shared "Market & Model Setup" panel: yield curve + factor vols
    # ------------------------------------------------------------------
    def _build_market_setup_group(self):
        group = QGroupBox("Treasury Curve (manual) & Model Vols")
        layout = QHBoxLayout(group)

        curve_form = QFormLayout()
        self.rate_inputs = {}
        for key, default_pct in DEFAULT_CURVE_PCT:
            spin = QDoubleSpinBox()
            spin.setRange(-5.0, 20.0)
            spin.setDecimals(3)
            spin.setSuffix(" %")
            spin.setValue(default_pct)
            self.rate_inputs[key] = spin
            curve_form.addRow(f"{key} rate:", spin)
        layout.addLayout(curve_form)

        sigma_form = QFormLayout()

        self.sigma1_input = QDoubleSpinBox()
        self.sigma1_input.setRange(0.0, 20.0)
        self.sigma1_input.setDecimals(3)
        self.sigma1_input.setSuffix(" %")
        self.sigma1_input.setValue(1.00)
        sigma_form.addRow("Short-rate factor vol (sigma1):", self.sigma1_input)

        self.sigma2_input = QDoubleSpinBox()
        self.sigma2_input.setRange(0.0, 20.0)
        self.sigma2_input.setDecimals(3)
        self.sigma2_input.setSuffix(" %")
        self.sigma2_input.setValue(0.50)
        sigma_form.addRow("Mean-reversion level vol (sigma2):", self.sigma2_input)

        self.bootstrap_button = QPushButton("Bootstrap Curve")
        self.bootstrap_button.clicked.connect(self._on_bootstrap_clicked)
        sigma_form.addRow(self.bootstrap_button)

        self.curve_status_label = QLabel("Curve not yet bootstrapped.")
        sigma_form.addRow(self.curve_status_label)

        layout.addLayout(sigma_form)
        return group

    def _on_bootstrap_clicked(self):
        rates = {key: spin.value() / 100.0 for key, spin in self.rate_inputs.items()}
        try:
            curve = tsm.bootstrap_forward_curve(rates)
        except Exception as exc:
            QMessageBox.warning(self, "Bootstrap failed", str(exc))
            return
        self.forward_rates = curve['forward_rates']
        self.curve_source = "Treasury (manual)"
        self.sofr_a = None  # only meaningful for a SOFR-sourced curve
        self.sofr_theta_bar = None
        self.curve_status_label.setText(
            f"Active curve: Treasury (manual) -- 1-month forward: {self.forward_rates[0]:.3%}, "
            f"30-year forward: {self.forward_rates[-1]:.3%}"
        )

    def _current_sigmas(self):
        return self.sigma1_input.value() / 100.0, self.sigma2_input.value() / 100.0

    def _require_curve(self):
        if self.forward_rates is None:
            QMessageBox.warning(self, "No curve", "Click 'Bootstrap Curve' or 'Fetch SOFR Curve' first.")
            return False
        return True

    # ------------------------------------------------------------------
    # "SOFR Curve (tastytrade, live)" panel: real CME SOFR futures +
    # options via sofr_market_data.py
    # ------------------------------------------------------------------
    def _build_sofr_group(self):
        group = QGroupBox("SOFR Curve (tastytrade, live)")
        layout = QHBoxLayout(group)

        creds_form = QFormLayout()
        self.sofr_credentials_edit = QLineEdit(smd.DEFAULT_CREDENTIALS_PATH)
        creds_form.addRow("tastytrade credentials file:", self.sofr_credentials_edit)
        layout.addLayout(creds_form, stretch=1)

        buttons_col = QVBoxLayout()
        self.sofr_fetch_button = QPushButton("Fetch SOFR Curve")
        self.sofr_fetch_button.setToolTip(
            "Fetch every currently-listed CME 3-Month SOFR (SR3) future and "
            "a spread of options on them, and bootstrap the curve from the "
            "futures. Makes this the active curve for both tabs below."
        )
        self.sofr_fetch_button.clicked.connect(self._on_fetch_sofr_clicked)
        buttons_col.addWidget(self.sofr_fetch_button)

        self.sofr_calibrate_button = QPushButton("Calibrate Vols to SOFR Options")
        self.sofr_calibrate_button.setToolTip(
            "Grid-search (a, sigma1, sigma2) so the model's Monte Carlo "
            "prices for the fetched SOFR options match their real market "
            "prices (b is left fixed -- see calibrate_sofr_model()'s "
            "docstring). Fills in sigma1/sigma2 above and stores the fitted "
            "a internally. Takes roughly 10-20 seconds."
        )
        self.sofr_calibrate_button.setEnabled(False)
        self.sofr_calibrate_button.clicked.connect(self._on_calibrate_sofr_clicked)
        buttons_col.addWidget(self.sofr_calibrate_button)
        layout.addLayout(buttons_col)

        self.sofr_status_label = QLabel("Not fetched yet.")
        self.sofr_status_label.setWordWrap(True)
        layout.addWidget(self.sofr_status_label, stretch=2)

        return group

    def _on_fetch_sofr_clicked(self):
        if self._sofr_fetch_worker is not None and self._sofr_fetch_worker.isRunning():
            return
        credentials_path = self.sofr_credentials_edit.text().strip() or None
        self.sofr_fetch_button.setEnabled(False)
        self.sofr_status_label.setText("Fetching from tastytrade...")

        self._sofr_fetch_worker = SofrFetchWorker(credentials_path)
        self._sofr_fetch_worker.progress.connect(self.sofr_status_label.setText)
        self._sofr_fetch_worker.finished_ok.connect(self._on_sofr_fetch_finished)
        self._sofr_fetch_worker.failed.connect(self._on_sofr_fetch_failed)
        self._sofr_fetch_worker.start()

    def _on_sofr_fetch_finished(self, curve_futures, options):
        self.sofr_fetch_button.setEnabled(True)
        self.sofr_curve_futures = curve_futures
        self.sofr_options = options
        self.sofr_a = None  # stale until "Calibrate" is run again
        self.sofr_theta_bar = None

        curve = tsm.bootstrap_sofr_curve(curve_futures)
        self.forward_rates = curve['forward_rates']
        self.curve_source = "SOFR (live, tastytrade)"
        self.curve_status_label.setText(
            f"Active curve: SOFR (live, tastytrade) -- front (SOFR-like) rate: "
            f"{self.forward_rates[0]:.3%}, back contract "
            f"({curve_futures[-1]['symbol']}, ~{curve_futures[-1]['end_months'] / 12:.1f}y out): "
            f"{curve_futures[-1]['rate']:.3%}"
        )
        self.sofr_status_label.setText(
            f"{len(curve_futures)} SOFR futures contract month(s), {len(options)} option quote(s) "
            f"across {len({o['underlying_symbol'] for o in options})} expiries fetched. "
            "Click 'Calibrate Vols to SOFR Options' to fit sigma1/sigma2."
        )
        self.sofr_calibrate_button.setEnabled(bool(options))

    def _on_sofr_fetch_failed(self, message):
        self.sofr_fetch_button.setEnabled(True)
        self.sofr_status_label.setText("Fetch failed -- see dialog.")
        QMessageBox.critical(self, "SOFR fetch failed", message)

    def _on_calibrate_sofr_clicked(self):
        if not self.sofr_curve_futures or not self.sofr_options:
            return
        if self.curve_source != "SOFR (live, tastytrade)":
            QMessageBox.warning(
                self, "Not the active curve",
                "The active curve is currently Treasury (manual). Click "
                "'Fetch SOFR Curve' again to make the SOFR curve active "
                "before calibrating to it.")
            return
        if self._sofr_calibration_worker is not None and self._sofr_calibration_worker.isRunning():
            return

        curve_real_months = self.sofr_curve_futures[-1]['end_months']
        self.sofr_calibrate_button.setEnabled(False)
        self.sofr_fetch_button.setEnabled(False)
        self.sofr_status_label.setText(
            f"Calibrating (a, sigma1, sigma2) to {len(self.sofr_options)} SOFR option "
            "quotes -- a 3-D grid search, roughly 10-20 seconds...")

        self._sofr_calibration_worker = SofrCalibrationWorker(
            self.forward_rates, self.sofr_options, curve_real_months)
        self._sofr_calibration_worker.finished_ok.connect(self._on_sofr_calibration_finished)
        self._sofr_calibration_worker.failed.connect(self._on_sofr_calibration_failed)
        self._sofr_calibration_worker.start()

    def _on_sofr_calibration_finished(self, result):
        a, theta_bar, sigma1, sigma2, error = result
        self.sofr_calibrate_button.setEnabled(True)
        self.sofr_fetch_button.setEnabled(True)

        self.sofr_a = a
        self.sofr_theta_bar = theta_bar
        self.sigma1_input.setValue(sigma1 * 100.0)
        self.sigma2_input.setValue(sigma2 * 100.0)
        self.sofr_status_label.setText(
            f"Calibrated to {len(self.sofr_options)} SOFR options: a={a:.4f} "
            f"(module default {tsm.SHORT_RATE_REVERSION_SPEED}), sigma1={sigma1:.5f}, "
            f"sigma2={sigma2:.5f}, total squared pricing error={error:.5f}."
        )

    def _on_sofr_calibration_failed(self, message):
        self.sofr_calibrate_button.setEnabled(True)
        self.sofr_fetch_button.setEnabled(True)
        self.sofr_status_label.setText("Calibration failed -- see dialog.")
        QMessageBox.critical(self, "Calibration failed", message)

    # ------------------------------------------------------------------
    # Tab 1: rate path chart
    # ------------------------------------------------------------------
    def _build_chart_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls = QHBoxLayout()

        self.n_paths_spin = QSpinBox()
        self.n_paths_spin.setRange(1, 500)
        self.n_paths_spin.setValue(15)
        controls.addWidget(QLabel("Number of paths:"))
        controls.addWidget(self.n_paths_spin)

        self.horizon_spin = QSpinBox()
        self.horizon_spin.setRange(1, 30)
        self.horizon_spin.setValue(10)
        controls.addWidget(QLabel("Horizon (years):"))
        controls.addWidget(self.horizon_spin)

        self.sofr_rate_radio = QRadioButton("SOFR rate (short end)")
        self.treasury_rate_radio = QRadioButton("Treasury rate (~10y)")
        self.mortgage_rate_radio = QRadioButton("Mortgage rate (~10y + spread)")
        self.sofr_rate_radio.setChecked(True)
        rate_choice_group = QButtonGroup(tab)
        rate_choice_group.addButton(self.sofr_rate_radio)
        rate_choice_group.addButton(self.treasury_rate_radio)
        rate_choice_group.addButton(self.mortgage_rate_radio)
        controls.addWidget(self.sofr_rate_radio)
        controls.addWidget(self.treasury_rate_radio)
        controls.addWidget(self.mortgage_rate_radio)

        self.mortgage_spread_spin = QDoubleSpinBox()
        self.mortgage_spread_spin.setRange(-500.0, 1000.0)
        self.mortgage_spread_spin.setDecimals(0)
        self.mortgage_spread_spin.setSuffix(" bp")
        self.mortgage_spread_spin.setValue(175.0)
        self.mortgage_spread_spin.setToolTip(
            "Flat spread added to the model's ~10-year rate to proxy a 30-year "
            "mortgage rate -- only used when 'Mortgage rate' is selected. See "
            "term_structure_model.simulate_mortgage_rate_paths()'s SIMPLIFICATION "
            "note: real mortgage spreads aren't actually constant."
        )
        controls.addWidget(self.mortgage_spread_spin)

        self.simulate_button = QPushButton("Run Simulation")
        self.simulate_button.clicked.connect(self._on_simulate_clicked)
        controls.addWidget(self.simulate_button)
        controls.addStretch()

        layout.addLayout(controls)

        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        return tab

    def _on_simulate_clicked(self):
        if not self._require_curve():
            return

        n_paths = self.n_paths_spin.value()
        horizon_years = self.horizon_spin.value()
        sigma1, sigma2 = self._current_sigmas()
        # (a, theta_bar) are only meaningful (and only set) once "Calibrate
        # Vols to SOFR Options" has been run against the currently-active
        # SOFR curve -- see calibrate_sofr_model()'s / _simulate_two_factor_
        # paths()'s docstrings in term_structure_model.py for why the
        # module defaults would otherwise bias a SOFR-curve simulation.
        is_calibrated_sofr = self.curve_source == "SOFR (live, tastytrade)" and self.sofr_a is not None
        a = self.sofr_a if is_calibrated_sofr else tsm.SHORT_RATE_REVERSION_SPEED
        theta_bar = self.sofr_theta_bar if is_calibrated_sofr else None

        # seed=None -> a fresh random draw every time the button is
        # clicked, so repeated clicks show different sample paths.
        if self.mortgage_rate_radio.isChecked():
            spread = self.mortgage_spread_spin.value() / 10000.0  # bp -> decimal
            years, short_rate_paths, ten_year_paths, values = tsm.simulate_mortgage_rate_paths(
                self.forward_rates, sigma1, sigma2, horizon_years, n_paths,
                mortgage_spread=spread, seed=None, a=a, theta_bar=theta_bar)
            title = f"Simulated mortgage-rate paths (~10y + {self.mortgage_spread_spin.value():.0f}bp)"
        else:
            years, short_rate_paths, ten_year_paths = tsm.simulate_rate_paths(
                self.forward_rates, sigma1, sigma2, horizon_years, n_paths, seed=None,
                a=a, theta_bar=theta_bar)
            if self.treasury_rate_radio.isChecked():
                values = ten_year_paths
                title = "Simulated Treasury rate paths (~10y, approximate)"
            else:
                values = short_rate_paths
                title = "Simulated SOFR (short-end) rate paths"

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        for path_index in range(n_paths):
            ax.plot(years, values[path_index, :] * 100.0, linewidth=0.8)
        ax.set_xlabel("Years from today")
        ax.set_ylabel("Rate (%)")
        ax.set_title(f"{title}  ({n_paths} paths)\ncurve: {self.curve_source}")
        self.figure.tight_layout()
        self.canvas.draw()

    # ------------------------------------------------------------------
    # Tab 2: callable bond (OAS) pricing
    # ------------------------------------------------------------------
    def _build_bond_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        self.bond_term_spin = QDoubleSpinBox()
        self.bond_term_spin.setRange(0.5, 30.0)
        self.bond_term_spin.setDecimals(2)
        self.bond_term_spin.setValue(10.0)
        form.addRow("Bond term (years):", self.bond_term_spin)

        self.bond_coupon_spin = QDoubleSpinBox()
        self.bond_coupon_spin.setRange(0.0, 20.0)
        self.bond_coupon_spin.setDecimals(3)
        self.bond_coupon_spin.setSuffix(" %")
        self.bond_coupon_spin.setValue(5.0)
        form.addRow("Coupon rate:", self.bond_coupon_spin)

        self.call_years_spin = QDoubleSpinBox()
        self.call_years_spin.setRange(0.5, 30.0)
        self.call_years_spin.setDecimals(2)
        self.call_years_spin.setValue(3.0)
        form.addRow("Callable on (years from today):", self.call_years_spin)

        self.call_price_spin = QDoubleSpinBox()
        self.call_price_spin.setRange(0.0, 200.0)
        self.call_price_spin.setDecimals(3)
        self.call_price_spin.setValue(100.0)
        form.addRow("Call price:", self.call_price_spin)

        self.oas_spin = QDoubleSpinBox()
        self.oas_spin.setRange(-500.0, 2000.0)
        self.oas_spin.setDecimals(1)
        self.oas_spin.setSuffix(" bp")
        self.oas_spin.setValue(75.0)
        form.addRow("Option-adjusted spread (OAS):", self.oas_spin)

        self.bond_paths_spin = QSpinBox()
        self.bond_paths_spin.setRange(200, 20000)
        self.bond_paths_spin.setSingleStep(200)
        self.bond_paths_spin.setValue(2000)
        form.addRow("Monte Carlo paths:", self.bond_paths_spin)

        layout.addLayout(form)

        self.price_button = QPushButton("Price Bond")
        self.price_button.clicked.connect(self._on_price_bond_clicked)
        layout.addWidget(self.price_button)

        self.bond_price_label = QLabel("Model price: --")
        label_font = self.bond_price_label.font()
        label_font.setPointSize(label_font.pointSize() + 4)
        label_font.setBold(True)
        self.bond_price_label.setFont(label_font)
        layout.addWidget(self.bond_price_label)

        note = QLabel(
            "Note: this prices a single, one-time call right on the date "
            "above (a 'European' call), not a continuously-callable bond. "
            "See the docstring in term_structure_model.py for details."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()
        return tab

    def _on_price_bond_clicked(self):
        if not self._require_curve():
            return

        term_years = self.bond_term_spin.value()
        call_years = self.call_years_spin.value()
        if call_years >= term_years:
            QMessageBox.warning(
                self, "Invalid input",
                "The call date must be strictly before the bond's maturity.")
            return

        sigma1, sigma2 = self._current_sigmas()
        price = tsm.price_callable_bond_mc(
            self.forward_rates, sigma1, sigma2,
            term_years=term_years,
            coupon_rate=self.bond_coupon_spin.value() / 100.0,
            call_years=call_years,
            call_price=self.call_price_spin.value(),
            oas=self.oas_spin.value() / 10000.0,  # bp -> decimal
            n_paths=self.bond_paths_spin.value(),
        )
        self.bond_price_label.setText(f"Model price: {price:.3f}")


def main():
    app = QApplication(sys.argv)
    window = TermStructureWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
