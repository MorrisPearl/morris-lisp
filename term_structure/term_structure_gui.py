"""
term_structure_gui.py

A small PyQt6 GUI on top of term_structure_model.py.

Two tabs:
  - "Rate Path Chart": simulate a chosen number of Monte Carlo interest
    rate paths and plot either the short rate or an approximate
    ten-year rate over time.
  - "Callable Bond (OAS)": enter a callable bond's term, coupon rate,
    call date, call price, and an option-adjusted spread (OAS), and see
    the Monte Carlo price the model computes.

Both tabs share one "Market & Model Setup" panel at the top (the yield
curve inputs and the two factor volatilities, sigma1 and sigma2), since
the chart and the bond price both come from the same underlying
simulation.

Run with:      python3 term_structure_gui.py
Requires:      pip install PyQt6 matplotlib numpy
Also needs:    term_structure_model.py in the same folder.

DESIGN NOTE: like term_structure_model.py, this file favors readable,
explicit code over cleverness. Every simulation runs synchronously on
the UI thread when you click a button -- with a few thousand Monte
Carlo paths this takes a fraction of a second, so no background-thread
/ progress-bar machinery is used. If you push the path counts much
higher, the window may briefly freeze while it computes.
"""

import sys

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import term_structure_model as tsm

# Default yield curve shown when the GUI opens, as (key, rate in percent).
# Illustrative only -- type in real market rates before relying on this.
DEFAULT_CURVE_PCT = [
    ('3m', 4.30), ('6m', 4.10), ('12m', 3.90),
    ('2y', 3.80), ('5y', 4.00), ('10y', 4.30), ('30y', 4.60),
]


class TermStructureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Two-Factor Term Structure Model")
        self.resize(1000, 720)

        self.forward_rates = None  # set by _on_bootstrap_clicked()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        main_layout.addWidget(self._build_market_setup_group())

        tabs = QTabWidget()
        tabs.addTab(self._build_chart_tab(), "Rate Path Chart")
        tabs.addTab(self._build_bond_tab(), "Callable Bond (OAS)")
        main_layout.addWidget(tabs)

        # Bootstrap once at startup with the default curve, so both tabs
        # have something to work with immediately.
        self._on_bootstrap_clicked()

    # ------------------------------------------------------------------
    # Shared "Market & Model Setup" panel: yield curve + factor vols
    # ------------------------------------------------------------------
    def _build_market_setup_group(self):
        group = QGroupBox("Market & Model Setup")
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
        self.curve_status_label.setText(
            f"Curve ready -- 1-month forward: {self.forward_rates[0]:.3%}, "
            f"30-year forward: {self.forward_rates[-1]:.3%}"
        )

    def _current_sigmas(self):
        return self.sigma1_input.value() / 100.0, self.sigma2_input.value() / 100.0

    def _require_curve(self):
        if self.forward_rates is None:
            QMessageBox.warning(self, "No curve", "Click 'Bootstrap Curve' first.")
            return False
        return True

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

        self.short_rate_radio = QRadioButton("Short rate")
        self.ten_year_radio = QRadioButton("Ten-year rate")
        self.short_rate_radio.setChecked(True)
        rate_choice_group = QButtonGroup(tab)
        rate_choice_group.addButton(self.short_rate_radio)
        rate_choice_group.addButton(self.ten_year_radio)
        controls.addWidget(self.short_rate_radio)
        controls.addWidget(self.ten_year_radio)

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

        # seed=None -> a fresh random draw every time the button is
        # clicked, so repeated clicks show different sample paths.
        years, short_rate_paths, ten_year_paths = tsm.simulate_rate_paths(
            self.forward_rates, sigma1, sigma2, horizon_years, n_paths, seed=None)

        if self.short_rate_radio.isChecked():
            values = short_rate_paths
            title = "Simulated short-rate paths"
        else:
            values = ten_year_paths
            title = "Simulated ten-year rate paths (approximate)"

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        for path_index in range(n_paths):
            ax.plot(years, values[path_index, :] * 100.0, linewidth=0.8)
        ax.set_xlabel("Years from today")
        ax.set_ylabel("Rate (%)")
        ax.set_title(f"{title}  ({n_paths} paths)")
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
