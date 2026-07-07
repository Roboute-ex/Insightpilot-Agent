"""Dimension contribution analysis."""

from __future__ import annotations

import pandas as pd

from insightpilot.analysis.anomaly import _aggregate


def dimension_contribution(
    df: pd.DataFrame,
    metric_col: str,
    dimension_col: str,
    date_col: str = "date",
    target_date: object | None = None,
) -> pd.DataFrame:
    """Rank dimension values by absolute contribution to target-date change."""

    required = {metric_col, dimension_col, date_col}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")

    working = df.copy()
    working[date_col] = pd.to_datetime(working[date_col])
    target = pd.Timestamp(target_date).normalize() if target_date is not None else working[date_col].max().normalize()

    daily = (
        working.groupby([date_col, dimension_col])[metric_col]
        .apply(lambda values: _aggregate(values, metric_col))
        .reset_index(name="metric_value")
    )
    current = daily[daily[date_col] == target][[dimension_col, "metric_value"]].rename(
        columns={"metric_value": "current_value"}
    )
    baseline = (
        daily[(daily[date_col] < target) & (daily[date_col] >= target - pd.Timedelta(days=7))]
        .groupby(dimension_col)["metric_value"]
        .mean()
        .reset_index(name="baseline_value")
    )
    result = current.merge(baseline, on=dimension_col, how="outer").fillna(0.0)
    result["change"] = result["current_value"] - result["baseline_value"]
    denominator = result["change"].abs().sum()
    result["contribution_share"] = result["change"].abs() / denominator if denominator else 0.0
    result = result.rename(columns={dimension_col: "dimension_value"})
    return result.sort_values(["contribution_share", "dimension_value"], ascending=[False, True]).reset_index(drop=True)
