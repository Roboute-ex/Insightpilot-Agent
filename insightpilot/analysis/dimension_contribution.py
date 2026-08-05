"""Rich dimension contribution analysis with bounded drilldowns."""

from __future__ import annotations

import numpy as np
import pandas as pd

from insightpilot.analysis.metric_diagnosis import RATE_FORMULAS
from insightpilot.analysis.results import DimensionContributionResult


DEFAULT_DIMENSIONS = (
    "city", "region", "channel", "user_segment", "device", "platform", "merchant_type",
    "payment_method", "app_version", "customer_type",
)


def _group_values(frame: pd.DataFrame, metric_id: str, dimension: str, target: pd.Timestamp) -> pd.DataFrame:
    formula = RATE_FORMULAS.get(metric_id)
    if formula and set(formula).issubset(frame.columns):
        numerator, denominator = formula
        daily = frame.groupby(["date", dimension], dropna=False, as_index=False)[[numerator, denominator]].sum()
        daily["metric_value"] = daily[numerator] / daily[denominator].replace(0, np.nan)
        daily["sample_size"] = daily[denominator]
    else:
        aggregation = "mean" if metric_id.endswith("_rate") or metric_id in {"watch_time", "startup_latency", "stutter_rate"} else "sum"
        daily = frame.groupby(["date", dimension], dropna=False)[metric_id].agg(aggregation).reset_index(name="metric_value")
        counts = frame.groupby(["date", dimension], dropna=False)[metric_id].count().reset_index(name="sample_size")
        daily = daily.merge(counts, on=["date", dimension], how="left")
    current = daily[daily["date"] == target][[dimension, "metric_value", "sample_size"]].rename(columns={"metric_value": "current_value"})
    history = daily[(daily["date"] < target) & (daily["date"] >= target - pd.Timedelta(days=7))]
    baseline = history.groupby(dimension, dropna=False).agg(baseline_value=("metric_value", "mean"), baseline_sample=("sample_size", "mean")).reset_index()
    result = current.merge(baseline, on=dimension, how="outer").fillna(0.0)
    result["absolute_change"] = result["current_value"] - result["baseline_value"]
    if formula:
        result["contribution_value"] = result["absolute_change"] * result["sample_size"]
    else:
        result["contribution_value"] = result["absolute_change"]
    return result


def dimension_contribution_results(
    frame: pd.DataFrame,
    metric_id: str,
    dimensions: tuple[str, ...] | list[str] = DEFAULT_DIMENSIONS,
    *,
    include_drilldown: bool = True,
) -> list[DimensionContributionResult]:
    if "date" not in frame.columns:
        return []
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"]).dt.normalize()
    target = pd.Timestamp(working["date"].max())
    raw_rows: list[dict[str, object]] = []
    for dimension in dimensions:
        if dimension not in working.columns:
            continue
        grouped = _group_values(working, metric_id, dimension, target)
        grouped["dimension"] = dimension
        grouped["dimension_value"] = grouped[dimension].astype(str)
        grouped = grouped.sort_values("contribution_value")
        selected = pd.concat([grouped.head(10), grouped.tail(5)]).drop_duplicates(subset=[dimension])
        omitted = grouped.drop(selected.index, errors="ignore")
        if not omitted.empty:
            selected = pd.concat([
                selected,
                pd.DataFrame([{
                    dimension: "Others",
                    "current_value": omitted["current_value"].sum(),
                    "sample_size": omitted["sample_size"].sum(),
                    "baseline_value": omitted["baseline_value"].sum(),
                    "baseline_sample": omitted["baseline_sample"].sum(),
                    "absolute_change": omitted["absolute_change"].sum(),
                    "contribution_value": omitted["contribution_value"].sum(),
                    "dimension": dimension,
                    "dimension_value": "Others",
                }]),
            ], ignore_index=True)
        raw_rows.extend(selected.to_dict(orient="records"))

    if include_drilldown and {"city", "device", "app_version"}.issubset(working.columns):
        city_rows = [row for row in raw_rows if row["dimension"] == "city" and row["dimension_value"] != "Others"]
        top_cities = sorted(city_rows, key=lambda item: float(item["contribution_value"]))[:3]
        for city_row in top_cities:
            city = str(city_row["dimension_value"])
            subset = working[working["city"].astype(str) == city].copy()
            subset["device_version"] = subset["device"].astype(str) + " / " + subset["app_version"].astype(str)
            grouped = _group_values(subset, metric_id, "device_version", target).sort_values("contribution_value").head(5)
            for row in grouped.to_dict(orient="records"):
                row["dimension"] = "city > device > app_version"
                row["dimension_value"] = f"{city} > {row['device_version']}"
                raw_rows.append(row)

    denominators: dict[str, float] = {}
    for row in raw_rows:
        dimension = str(row.get("dimension", ""))
        denominators[dimension] = denominators.get(dimension, 0.0) + abs(float(row.get("contribution_value", 0.0)))
    ordered = sorted(raw_rows, key=lambda row: (float(row.get("contribution_value", 0.0)), str(row.get("dimension_value", ""))))
    results: list[DimensionContributionResult] = []
    for rank, row in enumerate(ordered, start=1):
        current = float(row.get("current_value", 0.0))
        baseline = float(row.get("baseline_value", 0.0))
        absolute = float(row.get("absolute_change", current - baseline))
        sample_size = int(float(row.get("sample_size", 0)))
        results.append(DimensionContributionResult(
            metric_id=metric_id,
            dimension=str(row.get("dimension", "")),
            dimension_value=str(row.get("dimension_value", "")),
            current_value=current,
            baseline_value=baseline,
            absolute_change=absolute,
            relative_change=absolute / baseline if baseline else 0.0,
            contribution_value=float(row.get("contribution_value", absolute)),
            contribution_pct=abs(float(row.get("contribution_value", absolute))) / (denominators.get(str(row.get("dimension", ""))) or 1.0),
            rank=rank,
            sample_size=sample_size,
            confidence_flag="低样本" if sample_size < 30 else "可用",
        ))
    return results
