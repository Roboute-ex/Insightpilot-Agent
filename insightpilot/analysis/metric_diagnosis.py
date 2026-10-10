"""Deterministic multi-baseline metric comparison and anomaly detection."""

from __future__ import annotations

from insightpilot.performance_tasks import cancellation_checkpoint

from collections.abc import Iterable

import numpy as np
import pandas as pd

from insightpilot.analysis.results import AnomalyResult, MetricComparisonResult
from insightpilot.metrics.aggregation import is_non_additive_metric, metric_components
from insightpilot.analysis.reuse import aggregate_once
from insightpilot.observability.tracer import trace_stage


METRIC_NAMES = {
    "orders": "订单量",
    "active_users": "支付活跃用户数",
    "revenue": "收入",
    "impressions": "曝光量",
    "clicks": "点击量",
    "visitors": "访问次数",
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
    return aggregate_once(frame,("daily_metric",metric_id,date_col),lambda:_build_daily_series(frame,metric_id,date_col))


def _build_daily_series(frame: pd.DataFrame,metric_id: str,date_col: str) -> pd.DataFrame:
    if metric_id == "active_users" and "user_id" not in frame:
        raise ValueError("用户数需要实体user_id去重，不能求和分组UV。")
    pair=metric_components(metric_id,frame.columns)
    columns=[date_col,"user_id"] if metric_id == "active_users" else [date_col,*(pair or (metric_id,))]
    working = frame.loc[:,list(dict.fromkeys(columns))].copy()
    working[date_col] = pd.to_datetime(working[date_col]).dt.normalize()
    if metric_id == "active_users":
        if "user_id" not in working:
            raise ValueError("用户数需要实体user_id去重，不能求和分组UV。")
        grouped = working.groupby(date_col,observed=True)["user_id"].nunique().reset_index(name="metric_value")
        grouped["sample_size"] = grouped["metric_value"]
        return grouped
    numerator_denominator = metric_components(metric_id, working.columns)
    if numerator_denominator and set(numerator_denominator).issubset(working.columns):
        numerator, denominator = numerator_denominator
        grouped = working.groupby(date_col, as_index=False,observed=True)[[numerator, denominator]].sum()
        grouped["metric_value"] = grouped[numerator] / grouped[denominator].replace(0, np.nan)
        grouped["sample_size"] = grouped[denominator]
        return grouped[[date_col, "metric_value", "sample_size"]]
    grouped = working.groupby(date_col,observed=True)[metric_id]
    if is_non_additive_metric(metric_id):
        values = grouped.mean()
    else:
        values = grouped.sum()
    counts = grouped.count()
    return pd.DataFrame({date_col: values.index, "metric_value": values.values, "sample_size": counts.values})


def _severity(relative_change: float, z_score: float) -> str:
    if not np.isfinite(relative_change):
        return "UNKNOWN"
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
    if metric_id in {"latency_ms", "startup_latency"}:
        return "毫秒"
    if metric_id == "watch_time":
        return "秒"
    return "数量"


def compare_metric_baselines(frame: pd.DataFrame, metric_id: str, date_col: str = "date") -> tuple[list[MetricComparisonResult], AnomalyResult]:
    if metric_id not in frame.columns and metric_id not in RATE_FORMULAS and not (metric_id == "active_users" and "user_id" in frame):
        raise ValueError(f"Missing metric column: {metric_id}")
    daily = _daily_series(frame, metric_id, date_col).sort_values(date_col).reset_index(drop=True)
    if len(daily) < 9:
        raise ValueError(f"Not enough dated observations for {metric_id}")
    target_date = pd.Timestamp(daily[date_col].max())
    target_row = daily[daily[date_col] == target_date].iloc[-1]
    history = daily[daily[date_col] < target_date]
    previous_7 = history[history[date_col] >= target_date - pd.Timedelta(days=7)]
    previous_28 = history[history[date_col] >= target_date - pd.Timedelta(days=28)]
    prior_week = history[history[date_col] == target_date - pd.Timedelta(days=7)]
    recent_7 = daily[daily[date_col] >= target_date - pd.Timedelta(days=6)]
    preceding_7 = daily[(daily[date_col] < target_date - pd.Timedelta(days=6)) & (daily[date_col] >= target_date - pd.Timedelta(days=13))]
    formula = metric_components(metric_id, frame.columns)
    def period_value(period):
        if formula:
            valid = period["metric_value"].notna()
            denominator = period.loc[valid, "sample_size"].sum()
            return float((period.loc[valid, "metric_value"] * period.loc[valid, "sample_size"]).sum() / denominator) if denominator else float("nan")
        return float(period["metric_value"].mean())

    comparisons: list[tuple[str, float, float, int, pd.Series]] = [
        ("昨日", float(target_row["metric_value"]), period_value(previous_7), int(target_row["sample_size"]), previous_7["metric_value"]),
        ("昨日", float(target_row["metric_value"]), period_value(previous_28), int(target_row["sample_size"]), previous_28["metric_value"]),
        ("昨日", float(target_row["metric_value"]), float(prior_week["metric_value"].iloc[0]) if not prior_week.empty else float("nan"), int(target_row["sample_size"]), previous_7["metric_value"]),
        ("近 7 日均值", period_value(recent_7), period_value(preceding_7), int(recent_7["sample_size"].sum()), preceding_7["metric_value"]),
    ]
    baseline_names = ["前 7 日均值", "前 28 日均值", "上周同日", "前一个 7 日均值"]
    results: list[MetricComparisonResult] = []
    for index, ((current_period, current_value, baseline_value, sample_size, distribution), baseline_period) in enumerate(zip(comparisons, baseline_names)):
        absolute = current_value - baseline_value
        relative = absolute / baseline_value if baseline_value else float("nan")
        std = float(distribution.std(ddof=0))
        z_score = absolute / std if std > 1e-12 and len(distribution) >= 2 else float("nan")
        expected_n = [7, 28, 1, 7][index]
        actual_n = [len(previous_7), len(previous_28), len(prior_week), len(preceding_7)][index]
        notes = [f"基准日期完整性 {actual_n}/{expected_n}；z-score 使用总体标准差，基准样本数 {len(distribution)}；阈值不代表显著性"]
        if actual_n < expected_n:
            notes.append("基准周期不完整或存在缺失日期")
        if index == 3 and len(recent_7) < 7:
            notes.append(f"当前近7日周期不完整：{len(recent_7)}/7")
        if not np.isfinite(current_value) or not np.isfinite(baseline_value):
            notes.append("分母为零或观测缺失，指标不可计算")
        if not np.isfinite(z_score):
            notes.append("零方差或样本不足，z-score 不可计算")
        if formula:
            notes.append("比率采用分子合计/分母合计")
        if metric_id == "active_users":
            notes.append("按支付明细user_id逐日去重，表示支付活跃用户，不等于全站访问UV；周期值为每日去重人数的均值")
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
            direction="不可计算" if not np.isfinite(absolute) else "上升" if absolute > 0 else "下降" if absolute < 0 else "持平",
            severity=_severity(relative, z_score),
            z_score=z_score,
            confidence_note="；".join(notes),
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
        cancellation_checkpoint()
        if metric_id not in frame.columns and not set(RATE_FORMULAS.get(metric_id, ())).issubset(frame.columns):
            continue
        try:
            metric_results, anomaly = compare_metric_baselines(frame, metric_id)
        except ValueError:
            continue
        comparisons.extend(metric_results)
        anomalies.append(anomaly)
    return comparisons, anomalies
