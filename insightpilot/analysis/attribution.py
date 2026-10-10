"""Dimension contribution analysis."""

from __future__ import annotations

import pandas as pd

from insightpilot.metrics.aggregation import is_non_additive_metric, metric_components

ADDITIVE_AGGREGATIONS = {"sum", "count", "count_distinct"}


def dimension_contribution(
    df: pd.DataFrame,
    metric_col: str,
    dimension_col: str,
    date_col: str = "date",
    target_date: object | None = None,
    aggregation: str | None = None,
) -> pd.DataFrame:
    """Rank dimension values by absolute contribution to target-date change.

    Ratio metrics with known numerator/denominator columns are always computed as
    sum(numerator) / sum(denominator), for the target day and for the whole baseline
    window alike. A group observed in only one period counts
    as zero only for additive aggregations; for ratios and means its change is
    undefined and it is excluded from the contribution shares.
    """

    pair = metric_components(metric_col, df.columns)
    required = {dimension_col, date_col, *(pair or (metric_col,))}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")

    working = df.loc[:,list(dict.fromkeys([date_col,dimension_col,*(pair or (metric_col,))]))].copy()
    working[date_col] = pd.to_datetime(working[date_col])
    target = pd.Timestamp(target_date).normalize() if target_date is not None else working[date_col].max().normalize()

    in_baseline = (working[date_col] < target) & (working[date_col] >= target - pd.Timedelta(days=7))
    if pair:
        numerator, denominator = pair

        def pooled_ratio(rows: pd.DataFrame, name: str) -> pd.DataFrame:
            totals = rows.groupby(dimension_col, observed=True)[[numerator, denominator]].sum()
            return (totals[numerator] / totals[denominator].replace(0, float("nan"))).reset_index(name=name)

        current = pooled_ratio(working[working[date_col].dt.normalize() == target], "current_value")
        baseline = pooled_ratio(working[in_baseline], "baseline_value")
        additive = False
    else:
        method = aggregation or ("mean" if is_non_additive_metric(metric_col) else "sum")
        daily = working.groupby([date_col, dimension_col], observed=True)[metric_col].agg("nunique" if method == "count_distinct" else method).reset_index(name="metric_value")
        additive = method in ADDITIVE_AGGREGATIONS
        current = daily[daily[date_col] == target][[dimension_col, "metric_value"]].rename(
            columns={"metric_value": "current_value"}
        )
        baseline = (
            daily[(daily[date_col] < target) & (daily[date_col] >= target - pd.Timedelta(days=7))]
            .groupby(dimension_col)["metric_value"]
            .mean()
            .reset_index(name="baseline_value")
        )
    result = current.merge(baseline, on=dimension_col, how="outer", indicator="group_presence")
    result["group_presence"] = result["group_presence"].map({"both": "both", "left_only": "current_only", "right_only": "baseline_only"}).astype(str)
    if additive:
        result[["current_value", "baseline_value"]] = result[["current_value", "baseline_value"]].fillna(0.0)
    result["change"] = result["current_value"] - result["baseline_value"]
    denominator = result["change"].abs().sum()
    share = result["change"].abs() / denominator if denominator else result["change"].abs() * 0.0
    result["contribution_share"] = share.where(result["change"].notna())
    result = result.rename(columns={dimension_col: "dimension_value"})
    result = result[["dimension_value", "current_value", "baseline_value", "change", "contribution_share", "group_presence"]]
    return result.sort_values(["contribution_share", "dimension_value"], ascending=[False, True], na_position="last").reset_index(drop=True)
