"""
stratify_engine.py

Pure-Python / pandas logic for the Stratification Report app.
Kept separate from the PyQt6 GUI so it can be tested and reused independently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# "None" means: do not generate a standalone stratification report for this field.
NUMERIC_METHODS = ["Equal Count Buckets", "Equal Weight Buckets", "Manual Breakpoints", "None"]
CATEGORICAL_METHODS = ["Top Values + Other", "None"]

# Stats that only make sense on numeric data.
NUMERIC_ONLY_STATS = [
    "Sum", "Average", "Median", "Weighted Average", "Weighted Median",
    "Percentile", "Weighted Percentile", "Min", "Max",
]
# Stats that work on numeric OR text/categorical data.
GENERAL_STATS = ["Mode", "Weighted Mode", "Representative Value"]
ALL_STATS = NUMERIC_ONLY_STATS + GENERAL_STATS
PERCENTILE_STATS = {"Percentile", "Weighted Percentile"}


def stats_for_field_type(is_numeric: bool) -> list:
    return ALL_STATS if is_numeric else GENERAL_STATS


def stat_label(stat_cfg: dict) -> str:
    """Human-readable label for one stat config, e.g. 'Weighted Percentile 90'."""
    name = stat_cfg["stat"]
    if name in PERCENTILE_STATS:
        pct = stat_cfg.get("pct", 50)
        pct_str = f"{pct:g}"
        return f"{name} {pct_str}"
    return name


# --------------------------------------------------------------------------
# Field type detection
# --------------------------------------------------------------------------

def detect_field_types(df: pd.DataFrame) -> dict:
    """Return {column_name: 'numeric' | 'categorical'}."""
    types = {}
    for col in df.columns:
        s = df[col].dropna()
        if len(s) == 0:
            types[col] = "categorical"
            continue
        coerced = pd.to_numeric(s, errors="coerce")
        # Numeric only if every non-null value converted cleanly.
        types[col] = "numeric" if coerced.notna().all() else "categorical"
    return types


def _format_number(x) -> str:
    if x == np.inf:
        return "inf"
    if x == -np.inf:
        return "-inf"
    try:
        if float(x).is_integer():
            return str(int(x))
    except (ValueError, OverflowError):
        pass
    return f"{x:g}"


# --------------------------------------------------------------------------
# Bucketing
# --------------------------------------------------------------------------

def assign_numeric_buckets(series: pd.Series, weights: pd.Series, method: str,
                            n, breakpoints=None):
    """
    Assign each row of `series` a string bucket label.

    method: "Equal Count Buckets" | "Equal Weight Buckets" | "Manual Breakpoints"
    Returns (labels: pd.Series[str], ordered_unique_labels: list[str])
    """
    if method == "None":
        raise ValueError("Cannot bucket a field whose Method is 'None'.")

    s = pd.to_numeric(series, errors="coerce")
    w = pd.to_numeric(weights.reindex(s.index), errors="coerce").fillna(0)

    labels = pd.Series("Missing", index=series.index, dtype=object)
    valid_mask = s.notna()
    valid_s = s[valid_mask]

    if len(valid_s) == 0:
        return labels, ["Missing"]

    valid_w = w[valid_mask]

    if method == "Manual Breakpoints" and breakpoints:
        edges = sorted(set(float(b) for b in breakpoints))
        full_edges = [-np.inf] + edges + [np.inf]
        bucket_num = np.searchsorted(edges, valid_s.values, side="right")
        bounds = list(zip(full_edges[:-1], full_edges[1:]))
        bucket_series = pd.Series(bucket_num, index=valid_s.index)
        label_map = {}
        for b in sorted(bucket_series.unique()):
            lo, hi = bounds[b]
            label_map[b] = f"[{_format_number(lo)}, {_format_number(hi)})"
        labels.loc[valid_s.index] = bucket_series.map(label_map)
        order = [label_map[b] for b in sorted(label_map)]
        if (labels == "Missing").any():
            order.append("Missing")
        return labels, order

    # Equal Count / Equal Weight: sort values, split into n groups by position.
    order_idx = valid_s.sort_values(kind="mergesort").index
    ordered_vals = valid_s.loc[order_idx].values
    n_req = max(1, min(int(n), len(ordered_vals)))

    if method == "Equal Weight Buckets":
        ordered_w = valid_w.loc[order_idx].values
        cum_w = np.cumsum(ordered_w)
        total_w = cum_w[-1] if len(cum_w) else 0
        if total_w <= 0:
            split_positions = [int(round(len(ordered_vals) * i / n_req)) for i in range(1, n_req)]
        else:
            thresholds = [total_w * i / n_req for i in range(1, n_req)]
            split_positions = list(np.searchsorted(cum_w, thresholds, side="left"))
    else:  # Equal Count Buckets (default)
        split_positions = [int(round(len(ordered_vals) * i / n_req)) for i in range(1, n_req)]

    split_positions = sorted(set(p for p in split_positions if 0 < p < len(ordered_vals)))
    pos_bucket = np.searchsorted(split_positions, np.arange(len(ordered_vals)), side="right")
    bucket_by_orig_index = pd.Series(pos_bucket, index=order_idx).reindex(valid_s.index)

    # Build a human-readable [min, max] label per bucket, de-duplicated.
    label_map = {}
    seen = {}
    for b in sorted(bucket_by_orig_index.unique()):
        vals_in_bucket = valid_s[bucket_by_orig_index == b]
        lo, hi = vals_in_bucket.min(), vals_in_bucket.max()
        base_label = f"[{_format_number(lo)}, {_format_number(hi)}]"
        if base_label in seen:
            seen[base_label] += 1
            base_label = f"{base_label} ({seen[base_label]})"
        else:
            seen[base_label] = 0
        label_map[b] = base_label

    labels.loc[valid_s.index] = bucket_by_orig_index.map(label_map)
    order = [label_map[b] for b in sorted(label_map)]
    if (labels == "Missing").any():
        order.append("Missing")
    return labels, order


def assign_categorical_buckets(series: pd.Series, n):
    """
    Top (n-1) most common values each get their own bucket; everything else
    (including nulls) falls into "Other" / "Missing".

    n: an int, or the string "All" to give every distinct value its own
       bucket (no "Other" bucket in that case).
    Returns (labels: pd.Series[str], ordered_unique_labels: list[str])
    """
    counts = series.value_counts(dropna=True)
    if isinstance(n, str) and n.strip().lower() == "all":
        n_top = len(counts)
    else:
        n_top = max(0, int(n) - 1)
    top_values = counts.index[:n_top].tolist()
    top_set = set(top_values)

    def label_for(v):
        if pd.isna(v):
            return "Missing"
        return str(v) if v in top_set else "Other"

    labels = series.apply(label_for)
    order = [str(v) for v in top_values]
    if (labels == "Other").any():
        order.append("Other")
    if (labels == "Missing").any():
        order.append("Missing")
    return labels, order


def assign_buckets(series: pd.Series, weights: pd.Series, field_type: str,
                    method: str, n, breakpoints=None):
    """Dispatch to the numeric or categorical bucketing function."""
    if field_type == "numeric":
        return assign_numeric_buckets(series, weights, method, n, breakpoints)
    return assign_categorical_buckets(series, n)


# --------------------------------------------------------------------------
# Summary statistics
# --------------------------------------------------------------------------

def _weighted_percentile(values: pd.Series, weights: pd.Series, pct: float) -> float:
    """Non-interpolated weighted percentile: smallest value whose cumulative
    weight share reaches `pct`."""
    w = pd.to_numeric(weights.reindex(values.index), errors="coerce").fillna(0)
    order_idx = values.sort_values(kind="mergesort").index
    sorted_vals = values.loc[order_idx].to_numpy()
    sorted_w = w.loc[order_idx].to_numpy()
    total = sorted_w.sum()
    if total <= 0:
        return float(np.percentile(sorted_vals, pct))
    cum = np.cumsum(sorted_w)
    frac = cum / total
    target = max(0.0, min(1.0, pct / 100.0))
    idx = int(np.searchsorted(frac, target, side="left"))
    idx = min(idx, len(sorted_vals) - 1)
    return float(sorted_vals[idx])


def compute_stat(values: pd.Series, weights: pd.Series, stat_cfg: dict, is_numeric: bool):
    """Compute one summary statistic (given by stat_cfg) for one bucket / one column."""
    name = stat_cfg["stat"]
    vals = values.dropna()

    if name == "Representative Value":
        return vals.iloc[0] if len(vals) else None

    if name in ("Mode", "Weighted Mode"):
        if len(vals) == 0:
            return None
        if name == "Mode":
            counts = vals.value_counts()
            return counts.idxmax()
        w = pd.to_numeric(weights.reindex(vals.index), errors="coerce").fillna(0)
        grouped = w.groupby(vals).sum()
        if grouped.empty:
            return None
        return grouped.idxmax()

    # Everything else requires numeric data.
    if not is_numeric:
        return None

    numeric_vals = pd.to_numeric(vals, errors="coerce").dropna()
    if len(numeric_vals) == 0:
        return None

    if name == "Sum":
        return float(numeric_vals.sum())
    if name == "Average":
        return float(numeric_vals.mean())
    if name == "Median":
        return float(numeric_vals.median())
    if name == "Min":
        return float(numeric_vals.min())
    if name == "Max":
        return float(numeric_vals.max())
    if name == "Weighted Average":
        w = pd.to_numeric(weights.reindex(numeric_vals.index), errors="coerce").fillna(0)
        total_w = w.sum()
        if total_w == 0:
            return float(numeric_vals.mean())
        return float((numeric_vals * w).sum() / total_w)
    if name == "Weighted Median":
        return _weighted_percentile(numeric_vals, weights, 50)
    if name == "Percentile":
        pct = stat_cfg.get("pct", 50)
        return float(numeric_vals.quantile(pct / 100))
    if name == "Weighted Percentile":
        pct = stat_cfg.get("pct", 50)
        return _weighted_percentile(numeric_vals, weights, pct)
    return None


# --------------------------------------------------------------------------
# Report builders
# --------------------------------------------------------------------------

def _resolve_weights(df: pd.DataFrame, weight_field) -> pd.Series:
    if weight_field and weight_field in df.columns:
        return pd.to_numeric(df[weight_field], errors="coerce").fillna(0)
    return pd.Series(1.0, index=df.index)


def build_report(df: pd.DataFrame, strat_field: str, field_types: dict,
                  weight_field, stat_configs: dict, n, method: str = "Equal Count Buckets",
                  breakpoints=None) -> pd.DataFrame:
    """
    Build one stratification report, stratified on `strat_field`.

    stat_configs: {column_name: [stat_cfg, ...]} — for every OTHER column,
        the list of summary statistics to include (each becomes its own
        column). An empty/missing list means that field is left out of
        the report entirely.
    """
    if method == "None":
        raise ValueError(f"Field '{strat_field}' has Method = 'None' and cannot be stratified.")

    weights = _resolve_weights(df, weight_field)
    ftype = field_types.get(strat_field, "categorical")
    labels, order = assign_buckets(df[strat_field], weights, ftype, method, n, breakpoints)

    other_fields = [c for c in df.columns if c != strat_field]
    columns_spec = [(col, cfg) for col in other_fields for cfg in stat_configs.get(col, [])]

    rows = []
    for bucket_label in order:
        mask = (labels == bucket_label).values
        sub = df.loc[mask]
        sub_w = weights.loc[mask]
        row = {
            "Bucket": bucket_label,
            "Count": int(mask.sum()),
            "Total Weight": float(sub_w.sum()),
        }
        for col, cfg in columns_spec:
            is_num = field_types.get(col) == "numeric"
            row[f"{col} ({stat_label(cfg)})"] = compute_stat(sub[col], sub_w, cfg, is_num)
        rows.append(row)

    col_order = ["Bucket", "Count", "Total Weight"] + [f"{c} ({stat_label(cfg)})" for c, cfg in columns_spec]
    return pd.DataFrame(rows, columns=col_order)


def estimate_combo_count(df: pd.DataFrame, strat_fields: list, n_by_field: dict, field_types: dict) -> int:
    """Rough upper bound on the number of buckets a multi-field report could produce
    (product of each field's bucket count; 'All' is replaced by its actual distinct count)."""
    total = 1
    for f in strat_fields:
        n = n_by_field.get(f)
        if isinstance(n, str) and n.strip().lower() == "all":
            total *= max(1, df[f].nunique(dropna=True))
        else:
            total *= max(1, int(n))
    return total


def build_multi_field_report(df: pd.DataFrame, strat_fields: list, field_types: dict,
                              weight_field, stat_configs: dict, n_by_field: dict,
                              method_by_field: dict, breakpoints_by_field: dict) -> pd.DataFrame:
    """
    Build one stratification report stratified on the INTERSECTION of multiple
    fields at once. Each row of the report is one combination of buckets (one
    per stratification field) that actually occurs in the data — up to the
    product of each field's bucket count, but combinations with zero matching
    records are omitted.
    """
    if len(strat_fields) < 2:
        raise ValueError("A multi-field report needs at least 2 fields.")

    weights = _resolve_weights(df, weight_field)

    bucket_labels = {}
    bucket_orders = {}
    for f in strat_fields:
        method = method_by_field.get(f, "Equal Count Buckets")
        if method == "None":
            raise ValueError(f"Field '{f}' has Method = 'None' and cannot be used in a multi-field report.")
        ftype = field_types.get(f, "categorical")
        labels, order = assign_buckets(df[f], weights, ftype, method, n_by_field.get(f),
                                        breakpoints_by_field.get(f))
        bucket_labels[f] = labels
        bucket_orders[f] = order

    label_df = pd.DataFrame(bucket_labels, index=df.index)
    rank_maps = {f: {lbl: i for i, lbl in enumerate(bucket_orders[f])} for f in strat_fields}

    groups = label_df.groupby(list(strat_fields), dropna=False, sort=False)
    keys = list(groups.groups.keys())

    def sort_key(key):
        key_t = key if isinstance(key, tuple) else (key,)
        return tuple(rank_maps[f].get(key_t[i], len(bucket_orders[f])) for i, f in enumerate(strat_fields))

    keys_sorted = sorted(keys, key=sort_key)

    other_fields = [c for c in df.columns if c not in strat_fields]
    columns_spec = [(col, cfg) for col in other_fields for cfg in stat_configs.get(col, [])]

    rows = []
    for key in keys_sorted:
        idx = groups.groups[key]
        key_t = key if isinstance(key, tuple) else (key,)
        sub = df.loc[idx]
        sub_w = weights.loc[idx]
        row = {}
        for i, f in enumerate(strat_fields):
            row[f"{f} Bucket"] = key_t[i]
        row["Count"] = int(len(idx))
        row["Total Weight"] = float(sub_w.sum())
        for col, cfg in columns_spec:
            is_num = field_types.get(col) == "numeric"
            row[f"{col} ({stat_label(cfg)})"] = compute_stat(sub[col], sub_w, cfg, is_num)
        rows.append(row)

    col_order = ([f"{f} Bucket" for f in strat_fields] + ["Count", "Total Weight"] +
                 [f"{c} ({stat_label(cfg)})" for c, cfg in columns_spec])
    return pd.DataFrame(rows, columns=col_order)
