"""
models.py
=========
Qt model classes that back the QTableView: a thin QAbstractTableModel
wrapper around a pandas DataFrame (with sorting), plus a
QSortFilterProxyModel that supports free-text search + an option-type
filter (All / Call / Put).
"""

from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSortFilterProxyModel
from PyQt6.QtGui import QColor

NUMERIC_COLUMNS = {
    "Strike", "Last Price", "Implied Volatility", "Volume", "Open Interest",
    "Fitted Price", "Rich/Cheap %", "Near Price", "Far Price",
    "Implied Carry Rate %", "Implied Net Storage Cost %", "Implied Convenience Yield %",
}
RIGHT_ALIGN_COLUMNS = NUMERIC_COLUMNS

RICH_COLOR = QColor(255, 205, 210)   # soft red
CHEAP_COLOR = QColor(200, 230, 201)  # soft green


class PandasTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

    # -- data access -------------------------------------------------
    def dataFrame(self) -> pd.DataFrame:
        return self._df

    def setDataFrame(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        self.endResetModel()

    # -- required overrides -------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self._df.empty:
            return QVariant()

        col = self._df.columns[index.column()]
        value = self._df.iat[index.row(), index.column()]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if pd.isna(value):
                return "—"
            if col == "Implied Volatility":
                try:
                    return f"{float(value) * 100:.2f}%"
                except (TypeError, ValueError):
                    return str(value)
            if col.endswith("%"):
                try:
                    return f"{float(value):+.2f}%"
                except (TypeError, ValueError):
                    return str(value)
            if col in ("Last Price", "Strike", "Fitted Price", "Near Price", "Far Price"):
                try:
                    return f"{float(value):,.2f}"
                except (TypeError, ValueError):
                    return str(value)
            if col in ("Volume", "Open Interest", "Days to Delivery", "Days Between"):
                try:
                    return f"{int(value):,}"
                except (TypeError, ValueError):
                    return str(value)
            return str(value)

        if role == Qt.ItemDataRole.BackgroundRole and col == "Signal":
            text = str(value).lower()
            if "rich" in text:
                return RICH_COLOR
            if "cheap" in text:
                return CHEAP_COLOR
            return QVariant()

        if role == Qt.ItemDataRole.TextAlignmentRole and col in RIGHT_ALIGN_COLUMNS:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return QVariant()
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        if self._df.empty or column < 0 or column >= len(self._df.columns):
            return
        col_name = self._df.columns[column]
        self.layoutAboutToBeChanged.emit()
        try:
            self._df = self._df.sort_values(
                by=col_name,
                ascending=(order == Qt.SortOrder.AscendingOrder),
                kind="mergesort",
                na_position="last",
            ).reset_index(drop=True)
        finally:
            self.layoutChanged.emit()


class OptionsFilterProxyModel(QSortFilterProxyModel):
    """Free-text search across Symbol/Delivery Month/Underlying Future,
    plus an exact-match filter on the 'Type' column (Call/Put/All)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self._type_filter = "All"
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def setSearchText(self, text: str):
        self._search_text = text.strip().lower()
        self.invalidateFilter()

    def setTypeFilter(self, option_type: str):
        self._type_filter = option_type
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None:
            return True
        df = model.dataFrame()
        if df.empty:
            return True

        if self._type_filter != "All":
            type_val = str(df.iat[source_row, df.columns.get_loc("Type")])
            if type_val != self._type_filter:
                return False

        if self._search_text:
            searchable_cols = ["Symbol", "Delivery Month", "Underlying Future", "Expiration Date"]
            haystack = " ".join(
                str(df.iat[source_row, df.columns.get_loc(c)]) for c in searchable_cols
            ).lower()
            if self._search_text not in haystack:
                return False

        return True
