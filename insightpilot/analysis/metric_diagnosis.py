"""Deterministic multi-baseline metric comparison and anomaly detection."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from insightpilot.analysis.results import AnomalyResult, MetricComparisonResult


METRIC_NAMES = {
    "orders": "订单量",
    "revenue": "收入",
    "impressions": "曝光量",
    "clicks": "点击量",
    "visitors": "访问用户数",
    "ctr": "点击率",
    "cvr": "转化率",
    "conversion_rate": "转化率",
    "payment_success_rate": "支付成功率",
    "average_order_value": "客单价",
    "refund_rate": "退款率",
    "completion_rate": "完播率",
    "engagement_rate": "互动率",
    "buffering_rate": "卡顿率",
    "stutter_rate": "卡顿率",
    "crash_rate": "崩溃率",
    "latency_ms": "启动延迟",
    "startup_latency": "启动延迟",
    "watch_time": "观看时长",
    "interaction_rate": "互动率",
}

RATE_FORMULAS = {
    "ctr": ("clicks", "impressions"),
    "add_to_cart_rate": ("add_to_cart_users", "visitors"),
    "checkout_rate": ("checkout_users", "add_to_cart_users"),
    "conversion_rate": ("orders", "visitors"),
    "cvr": ("orders", "visitors"),
    "payment_success_rate": ("successful_payments", "payment_attempts"),
    "average_order_value": ("revenue", "orders"),
    "refund_rate": ("refund_orders", "orders"),
}


def _daily_series(frame: pd.DataFrame, metric_id: str, date_col: str = "date") -> pd.DataFrame:
    working = frame.copy()
    working[date_col] = pd.to_datetime(working[date_col]).dt.normalize()
    numerator_denominator = RATE_FORMULAS.get(metric_id)
    if numerator_denominator and set(numerator_denominator).issubset(working.columns):
        numerator, denominator = numerator_denominator
        grouped = working.groupby(date_col, as_index=False)[[numerator, denominator]].sum()
        grouped["metric_value"] = grouped[numerator] / grouped[denominator].replace(0, np.nan)
        grouped["sample_size"] = grouped[denominator]
        return grouped[[date_col, "metric_value", "sample_size"]].fillna(0.0)
    grouped = working.groupby(date_col)[metric_id]
    if metric_id.endswith("_rate") or metric_id.endswith("_latency") or metric_id in {"latency_ms", "watch_time", "stutter_rate"}:
        values = grouped.mean()
    else:
        values = grouped.sum()
    counts = grouped.count()
    return pd.DataFrame({date_col: values.index, "metric_value": values.values, "sample_size": counts.values})


def _severity(relative_change: float, z_score: float) -> str:
    magnitude = abs(relative_change)
    if abs(z_score) >= 3 or magnitude >= 0.2:
        return "HIGH"
    if abs(z_score) >= 2 or magnitude >= 0.1:
        return "MEDIUM"
    return "LOW"


def _unit(metric_id: str) -> str:
    if metric_id.endswith("_rate") or metric_id in {"ctr", "cvr", "conversion_rate"}:
        return "比例"
    if metric_id in {"revenue", "refund_amount", "average_order_value"}:
        return "金额"
    if metric_id in {"watch_time", "startup_latency"}:
        return "时长"
    return "数量"


def compare_metric_baselines(frame: pd.DataFrame, metric_id: str, date_col: str = "date") -> tuple[list[MetricComparisonResult], AnomalyResult]:
    if metric_id not in frame.columns and metric_id not in RATE_FORMULAS:
        raise ValueError(f"Missing metric column: {metric_id}")
    daily = _daily_series(frame, metric_id, date_col).sort_values(date_col).reset_index(drop=True)
    if len(daily) < 9:
        raise ValueError(f"Not enough dated observations for {metric_id}")
    target_date = pd.Timestamp(daily[date_col].max())
    target_row = daily[daily[date_col] == target_date].iloc[-1]
    history = daily[daily[date_col] < target_date]
    previous_7 = history.tail(7)
    previous_28 = history.tail(28)
    prior_week = history[history[date_col] == target_date - pd.Timedelta(days=7)]
    recent_7 = daily.tail(7)
    preceding_7 = daily.iloc[max(0, len(daily) - 14): max(0, len(daily) - 7)]

    comparisons: list[tuple[str, float, float, int, pd.Series]] = [
        ("昨日", float(target_row["metric_value"]), float(previous_7["metric_value"].mean()), int(target_row["sample_size"]), previous_7["metric_value"]),
        ("昨日", float(target_row["metric_value"]), float(previous_28["metric_value"].mean()), int(target_row["sample_size"]), previous_28["metric_value"]),
        ("昨日", float(target_row["metric_value"]), float(prior_week["metric_value"].iloc[0]) if not prior_week.empty else float(previous_7["metric_value"].mean()), int(target_row["sample_size"]), previous_7["metric_value"]),
        ("近 7 日均值", float(recent_7["metric_value"].mean()), float(preceding_7["metric_value"].mean()), int(recent_7["sample_size"].sum()), preceding_7["metric_value"]),
    ]
    baseline_names = ["前 7 日均值", "前 28 日均值", "上周同日", "前一个 7 日均值"]
    results: list[MetricComparisonResult] = []
    for (current_period, current_value, baseline_value, sample_size, distribution), baseline_period in zip(comparisons, baseline_names):
        absolute = current_value - baseline_value
        relative = absolute / baseline_value if baseline_value else 0.0
        std = float(distribution.std(ddof=0))
        z_score = absolute / std if std > 1e-12 else 0.0
        results.append(MetricComparisonResult(
            metric_id=metric_id,
            metric_name=METRIC_NAMES.get(metric_id, metric_id),
            current_value=current_value,
            baseline_value=baseline_value,
            absolute_change=absolute,
            relative_change=relative,
            current_period=current_period,
            baseline_period=baseline_period,
            sample_size=sample_size,
            unit=_unit(metric_id),
            direction="上升" if absolute > 0 else "下降" if absolute < 0 else "持平",
            severity=_severity(relative, z_score),
            z_score=z_score,
            confidence_note="基于完整日期聚合" if not daily["metric_value"].isna().any() else "存在缺失日期或数值",
        ))
    main = results[0]
    std = float(previous_7["metric_value"].std(ddof=0))
    anomaly = AnomalyResult(
        metric_id=metric_id,
        date=str(target_date.date()),
        actual_value=main.current_value,
        expected_value=main.baseline_value,
        lower_bound=main.baseline_value - 2 * std,
        upper_bound=main.baseline_value + 2 * std,
        deviation=main.absolute_change,
        deviation_pct=main.relative_change,
        z_score=main.z_score,
        severity=main.severity,
        method="目标日与前 7 日均值及 2σ 区间比较",
        evidence=f"{main.metric_name}目标日值与前 7 日分布比较",
    )
    return results, anomaly


def diagnose_metrics(frame: pd.DataFrame, metric_ids: Iterable[str]) -> tuple[list[MetricComparisonResult], list[AnomalyResult]]:
    comparisons: list[MetricComparisonResult] = []
    anomalies: list[AnomalyResult] = []
    for metric_id in metric_ids:
        if metric_id not in frame.columns and not set(RATE_FORMULAS.get(metric_id, ())).issubset(frame.columns):
            continue
        try:
            metric_results, anomaly = compare_metric_baselines(frame, metric_id)
        except ValueError:
            continue
        comparisons.extend(metric_results)
        anomalies.append(anomaly)
    return comparisons, anomalies
