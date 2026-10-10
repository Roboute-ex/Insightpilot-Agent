"""Metric anomaly detection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from insightpilot.analysis.metric_diagnosis import _daily_series, _severity
from insightpilot.metrics.aggregation import metric_components


def _good_direction(metric_col: str) -> str | None:
    from insightpilot.metrics.dictionary import get_metric

    try:
        return get_metric(metric_col).good_direction
    except KeyError:
        return None


def _daily_values(df: pd.DataFrame, metric_col: str, date_col: str) -> tuple[pd.DataFrame, bool]:
    """Return the daily series and whether period values must be denominator-weighted."""

    if metric_components(metric_col, df.columns) is not None:
        return _daily_series(df, metric_col, date_col), True
    dates = pd.to_datetime(df[date_col]).dt.normalize()
    if metric_col in df.columns and dates.is_unique:
        # Already one row per date (for example a SQL daily aggregate): never re-aggregate it.
        return pd.DataFrame({date_col: dates.to_numpy(), "metric_value": pd.to_numeric(df[metric_col], errors="coerce").to_numpy()}), False
    return _daily_series(df, metric_col, date_col), False


def detect_metric_anomaly(
    df: pd.DataFrame,
    metric_col: str,
    date_col: str = "date",
    target_date: object | None = None,
) -> dict[str, object]:
    """Compare the target date with the previous 7-day average.

    Daily aggregation, ratio weighting and severity follow ``metric_diagnosis`` so
    intermediate artifacts agree with the final result package.
    """

    if metric_col not in df.columns and metric_components(metric_col, df.columns) is None:
        raise ValueError(f"Missing metric column: {metric_col}")
    if date_col not in df.columns:
        raise ValueError(f"Missing date column: {date_col}")

    daily, weighted = _daily_values(df, metric_col, date_col)
    daily = daily.sort_values(date_col)
    target = pd.Timestamp(target_date).normalize() if target_date is not None else pd.Timestamp(daily[date_col].max()).normalize()
    current_rows = daily[daily[date_col] == target]
    if current_rows.empty:
        raise ValueError(f"Target date not found: {target.date()}")
    baseline_rows = daily[(daily[date_col] < target) & (daily[date_col] >= target - pd.Timedelta(days=7))]
    if baseline_rows.empty:
        raise ValueError("Not enough baseline data before target date")
    current_value = float(current_rows["metric_value"].iloc[0])
    if weighted:
        valid = baseline_rows["metric_value"].notna()
        denominator = float(baseline_rows.loc[valid, "sample_size"].sum())
        baseline_value = float((baseline_rows.loc[valid, "metric_value"] * baseline_rows.loc[valid, "sample_size"]).sum() / denominator) if denominator else float("nan")
    else:
        baseline_value = float(baseline_rows["metric_value"].mean())
    absolute_change = current_value - baseline_value
    computable = np.isfinite(current_value) and np.isfinite(baseline_value) and baseline_value != 0
    relative_change = absolute_change / baseline_value if computable else float("nan")
    std = float(baseline_rows["metric_value"].std(ddof=0))
    z_score = absolute_change / std if std > 1e-12 and len(baseline_rows) >= 2 else float("nan")
    severity = _severity(relative_change, z_score)
    good_direction = _good_direction(metric_col)
    if not np.isfinite(absolute_change):
        direction, is_adverse = "不可计算", None
    else:
        direction = "上升" if absolute_change > 0 else "下降" if absolute_change < 0 else "持平"
        is_adverse = None if good_direction not in {"higher", "lower"} else bool(absolute_change < 0 if good_direction == "higher" else absolute_change > 0)
    return {
        "metric": metric_col,
        "target_date": str(target.date()),
        "current_value": current_value,
        "baseline_value": baseline_value,
        "absolute_change": absolute_change,
        "relative_change": relative_change,
        "is_anomaly": severity in {"HIGH", "MEDIUM"},
        "severity": severity,
        "direction": direction,
        "good_direction": good_direction,
        "is_adverse": is_adverse,
        "z_score": z_score,
        "comparison_method": "target_date_vs_previous_7d_average",
    }
