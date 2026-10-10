"""Rich dimension contribution analysis with bounded drilldowns."""

from __future__ import annotations

from insightpilot.performance_tasks import cancellation_checkpoint

import numpy as np
import pandas as pd

from insightpilot.metrics.aggregation import is_non_additive_metric, metric_components
from insightpilot.analysis.reuse import aggregate_once
from insightpilot.analysis.results import DimensionContributionResult


DEFAULT_DIMENSIONS = (
    "city", "region", "channel", "user_segment", "device", "platform", "merchant_type",
    "payment_method", "app_version", "customer_type",
)


def _group_values(frame: pd.DataFrame, metric_id: str, dimension: str, target: pd.Timestamp) -> pd.DataFrame:
    formula = metric_components(metric_id, frame.columns)
    history,current = aggregate_once(frame,("contribution_periods",target),lambda:(frame.loc[(frame["date"] < target) & (frame["date"] >= target - pd.Timedelta(days=7))],frame.loc[frame["date"] == target]))
    if formula:
        numerator, denominator = formula
        now = current.groupby(dimension, dropna=False,observed=True)[[numerator, denominator]].sum().rename(columns={numerator: "current_numerator", denominator: "sample_size"})
        before = history.groupby(dimension, dropna=False,observed=True)[[numerator, denominator]].sum().rename(columns={numerator: "baseline_numerator", denominator: "baseline_sample"})
        result = now.join(before, how="outer").fillna(0).reset_index()
        result["current_value"] = result["current_numerator"] / result["sample_size"].replace(0, np.nan)
        result["baseline_value"] = result["baseline_numerator"] / result["baseline_sample"].replace(0, np.nan)
        result["absolute_change"] = result["current_value"] - result["baseline_value"]
        current_total = float(result["sample_size"].sum())
        baseline_total = float(result["baseline_sample"].sum())
        # Exact composition decomposition: group numerator / whole-population denominator.
        # Within one dimension these signed terms sum to the overall rate change.
        result["contribution_value"] = result["current_numerator"] / (current_total or np.nan) - result["baseline_numerator"] / (baseline_total or np.nan)
        return result
    if is_non_additive_metric(metric_id):
        # Same as the overall comparison: daily mean, then the mean over observed baseline days.
        # A group without observations in a period stays undefined instead of becoming 0.
        now = current.groupby(dimension, dropna=False,observed=True)[metric_id].agg(current_value="mean", sample_size="count")
        daily = history.groupby([dimension, "date"], dropna=False,observed=True)[metric_id].mean()
        before = daily.groupby(level=0, dropna=False).mean().rename("baseline_value").to_frame()
        before["baseline_sample"] = history.groupby(dimension, dropna=False,observed=True)[metric_id].count() / max(1, history["date"].nunique())
        result = now.join(before, how="outer").reset_index()
        result[["sample_size", "baseline_sample"]] = result[["sample_size", "baseline_sample"]].fillna(0)
    else:
        now = current.groupby(dimension, dropna=False,observed=True)[metric_id].agg(current_value="sum", sample_size="count")
        before = history.groupby(dimension, dropna=False,observed=True)[metric_id].agg(baseline_value="sum", baseline_sample="count")
        before["baseline_value"] /= max(1, history["date"].nunique())
        before["baseline_sample"] /= max(1, history["date"].nunique())
        result = now.join(before, how="outer").fillna(0).reset_index()
    result["absolute_change"] = result["current_value"] - result["baseline_value"]
    result["contribution_value"] = result["absolute_change"]
    return result


def _others_row(working: pd.DataFrame, metric_id: str, dimension: str, target: pd.Timestamp, omitted: pd.DataFrame) -> dict[str, object]:
    one_period_only = bool(((omitted["sample_size"] > 0) != (omitted["baseline_sample"] > 0)).any())
    return {**_pooled_others(working, metric_id, dimension, target, omitted), "mixed_presence": one_period_only}


def _pooled_others(working: pd.DataFrame, metric_id: str, dimension: str, target: pd.Timestamp, omitted: pd.DataFrame) -> dict[str, object]:
    sizes = {"sample_size": omitted["sample_size"].sum(), "baseline_sample": omitted["baseline_sample"].sum()}
    if "current_numerator" in omitted:
        current = float(omitted["current_numerator"].sum() / sizes["sample_size"]) if sizes["sample_size"] else float("nan")
        baseline = float(omitted["baseline_numerator"].sum() / sizes["baseline_sample"]) if sizes["baseline_sample"] else float("nan")
        return {"current_value": current, "baseline_value": baseline, "absolute_change": current - baseline,
                "contribution_value": omitted["contribution_value"].sum(), **sizes}
    if not is_non_additive_metric(metric_id):
        return {"current_value": omitted["current_value"].sum(), "baseline_value": omitted["baseline_value"].sum(),
                "absolute_change": omitted["absolute_change"].sum(), "contribution_value": omitted["contribution_value"].sum(), **sizes}
    # Averages of omitted groups are recomputed from their rows; group averages are never summed.
    rows = working[working[dimension].isin(omitted[dimension])].assign(**{dimension: "Others"})
    pooled = _group_values(rows, metric_id, dimension, target).iloc[0]
    return {key: pooled[key] for key in ("current_value", "sample_size", "baseline_value", "baseline_sample", "absolute_change", "contribution_value")}


def dimension_contribution_results(
    frame: pd.DataFrame,
    metric_id: str,
    dimensions: tuple[str, ...] | list[str] = DEFAULT_DIMENSIONS,
    *,
    include_drilldown: bool = True,
) -> list[DimensionContributionResult]:
    if "date" not in frame.columns:
        return []
    pair=metric_components(metric_id,frame.columns)
    columns=list(dict.fromkeys(["date",*([metric_id] if metric_id in frame else []),*(pair or ()),*[d for d in dimensions if d in frame],*[d for d in ("city","device","app_version") if include_drilldown and d in frame]]))
    working = frame.loc[:,columns].copy()
    working["date"] = pd.to_datetime(working["date"]).dt.normalize()
    target = pd.Timestamp(working["date"].max())
    working=working.loc[working["date"]>=target-pd.Timedelta(days=7)]
    baseline_days = working.loc[(working["date"] < target) & (working["date"] >= target - pd.Timedelta(days=7)), "date"].nunique()
    raw_rows: list[dict[str, object]] = []
    for dimension in dimensions:
        cancellation_checkpoint()
        if dimension not in working.columns:
            continue
        grouped = _group_values(working, metric_id, dimension, target)
        grouped["dimension"] = dimension
        grouped["dimension_value"] = grouped[dimension].astype(str)
        grouped = grouped.sort_values("contribution_value")
        selected = pd.concat([grouped[grouped["contribution_value"] < 0].head(10), grouped[grouped["contribution_value"] > 0].tail(5)]).drop_duplicates(subset=[dimension])
        omitted = grouped.drop(selected.index, errors="ignore")
        if not omitted.empty:
            selected = pd.concat([
                selected,
                pd.DataFrame([{
                    dimension: "Others",
                    **_others_row(working, metric_id, dimension, target, omitted),
                    "dimension": dimension,
                    "dimension_value": "Others",
                }]),
            ], ignore_index=True)
        raw_rows.extend(selected.to_dict(orient="records"))

    if include_drilldown and {"city", "device", "app_version"}.issubset(working.columns):
        city_rows = [row for row in raw_rows if row["dimension"] == "city" and row["dimension_value"] != "Others"]
        top_cities = sorted(city_rows, key=lambda item: float(item["contribution_value"]))[:3]
        for city_row in top_cities:
            cancellation_checkpoint()
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
        value = float(row.get("contribution_value", 0.0))
        if np.isfinite(value):
            denominators[dimension] = denominators.get(dimension, 0.0) + abs(value)
    def order(row: dict[str, object]) -> tuple[bool, float, str]:
        value = float(row.get("contribution_value", 0.0))
        return (not np.isfinite(value), value if np.isfinite(value) else 0.0, str(row.get("dimension_value", "")))

    ordered = sorted(raw_rows, key=order)
    results: list[DimensionContributionResult] = []
    for rank, row in enumerate(ordered, start=1):
        current = float(row.get("current_value", 0.0))
        baseline = float(row.get("baseline_value", 0.0))
        absolute = current - baseline
        defined = np.isfinite(float(row.get("contribution_value", absolute)))
        sample_size = int(float(row.get("sample_size", 0)))
        results.append(DimensionContributionResult(
            metric_id=metric_id,
            dimension=str(row.get("dimension", "")),
            dimension_value=str(row.get("dimension_value", "")),
            current_value=current,
            baseline_value=baseline,
            absolute_change=absolute,
            relative_change=absolute / baseline if np.isfinite(baseline) and baseline != 0 else float("nan"),
            contribution_value=float(row.get("contribution_value", absolute)),
            contribution_pct=abs(float(row.get("contribution_value", absolute))) / (denominators.get(str(row.get("dimension", ""))) or 1.0),
            rank=rank,
            sample_size=sample_size,
            confidence_flag=("低样本" if sample_size < 30 else "可用") + ("；贡献=该组分子/整体分母的两期差，按单个维度守恒，不跨维度相加" if metric_components(metric_id, working.columns) else "") + (f"；前7日基准不完整({baseline_days}/7)，仅以有观测日期计算" if baseline_days < 7 else "") + _presence_note(row, defined),
        ))
    return results


def _presence_note(row: dict[str, object], defined: bool) -> str:
    mixed = row.get("mixed_presence")
    if mixed is not None and pd.notna(mixed) and bool(mixed):
        return "；Others 包含仅一期有观测的分组，前后观测来自不同分组，变化包含组成变化"
    current_n = float(row.get("sample_size", 0) or 0)
    baseline_n = float(row.get("baseline_sample", 0) or 0)
    suffix = "" if defined else "，变化不可计算"
    if current_n > 0 and not baseline_n > 0:
        return "；该组仅当前期有观测" + suffix
    if baseline_n > 0 and not current_n > 0:
        return "；该组仅基准期有观测" + suffix
    return "" if defined else "；该组在一期无观测，变化不可计算"
