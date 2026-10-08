"""Metric anomaly detection."""

from __future__ import annotations

import pandas as pd


MEAN_METRICS = {
    "ctr",
    "cvr",
    "payment_success_rate",
    "completion_rate",
    "retention_rate",
    "stutter_rate",
    "watch_time",
    "interaction_rate",
}


def _aggregate(values: pd.Series, metric_col: str) -> float:
    if metric_col in MEAN_METRICS or metric_col.endswith("_rate") or metric_col.endswith("_time"):
        return float(values.mean())
    return float(values.sum())


def _severity(relative_change: float) -> str:
    if relative_change <= -0.2:
        return "HIGH"
    if relative_change <= -0.1:
        return "MEDIUM"
    return "LOW"


def detect_metric_anomaly(
    df: pd.DataFrame,
    metric_col: str,
    date_col: str = "date",
    target_date: object | None = None,
) -> dict[str, object]:
    """Compare the target date with the previous 7-day average."""

    if metric_col not in df.columns:
        raise ValueError(f"Missing metric column: {metric_col}")
    if date_col not in df.columns:
        raise ValueError(f"Missing date column: {date_col}")

    working = df.loc[:,[date_col,metric_col]].copy()
    working[date_col] = pd.to_datetime(working[date_col])
    target = pd.Timestamp(target_date).normalize() if target_date is not None else working[date_col].max().normalize()
    daily = (
        working.groupby(date_col,observed=True)[metric_col]
        .agg("mean" if metric_col in MEAN_METRICS or metric_col.endswith(("_rate","_time")) else "sum")
        .reset_index(name="metric_value")
        .sort_values(date_col)
    )
    current_rows = daily[daily[date_col] == target]
    if current_rows.empty:
        raise ValueError(f"Target date not found: {target.date()}")
    baseline_rows = daily[(daily[date_col] < target) & (daily[date_col] >= target - pd.Timedelta(days=7))]
    if baseline_rows.empty:
        raise ValueError("Not enough baseline data before target date")
    current_value = float(current_rows["metric_value"].iloc[0])
    baseline_value = float(baseline_rows["metric_value"].mean())
    absolute_change = current_value - baseline_value
    relative_change = absolute_change / baseline_value if baseline_value else 0.0
    return {
        "metric": metric_col,
        "target_date": str(target.date()),
        "current_value": current_value,
        "baseline_value": baseline_value,
        "absolute_change": absolute_change,
        "relative_change": relative_change,
        "is_anomaly": relative_change <= -0.1,
        "severity": _severity(relative_change),
        "comparison_method": "target_date_vs_previous_7d_average",
    }
