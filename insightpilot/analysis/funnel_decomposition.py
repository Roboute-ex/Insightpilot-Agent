"""Sequential deterministic decomposition of transaction funnel changes."""

from __future__ import annotations

import numpy as np
import pandas as pd

from insightpilot.analysis.results import FunnelStageResult


FUNNEL_STAGES = (
    ("impressions", "曝光"),
    ("clicks", "点击"),
    ("visitors", "到站/访问"),
    ("add_to_cart_users", "加购"),
    ("checkout_users", "提交订单"),
    ("payment_attempts", "支付尝试"),
    ("successful_payments", "支付成功"),
)


def decompose_transaction_funnel(frame: pd.DataFrame, date_col: str = "date") -> list[FunnelStageResult]:
    required = {date_col, *(stage for stage, _ in FUNNEL_STAGES)}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing funnel columns: {', '.join(sorted(missing))}")
    working = frame.loc[:,[date_col,*[stage for stage,_ in FUNNEL_STAGES]]].copy()
    working[date_col] = pd.to_datetime(working[date_col]).dt.normalize()
    daily = working.groupby(date_col, as_index=False,observed=True)[[stage for stage, _ in FUNNEL_STAGES]].sum().sort_values(date_col)
    if len(daily) < 8:
        raise ValueError("At least eight dated observations are required for funnel decomposition")
    current = daily.iloc[-1]
    target_date = pd.Timestamp(current[date_col])
    history = daily[(daily[date_col] < target_date) & (daily[date_col] >= target_date - pd.Timedelta(days=7))]
    if len(history) != 7:
        raise ValueError("漏斗基准必须有完整前7个日历日。")
    baseline = history.mean(numeric_only=True)
    current_counts = np.array([float(current[stage]) for stage, _ in FUNNEL_STAGES])
    baseline_counts = np.array([float(baseline[stage]) for stage, _ in FUNNEL_STAGES])
    current_rates = np.ones(len(FUNNEL_STAGES))
    baseline_rates = np.ones(len(FUNNEL_STAGES))
    if (current_counts[:-1] <= 0).any() or (baseline_counts[:-1] <= 0).any():
        raise ValueError("漏斗阶段分母为零，顺序分解不可计算。")
    current_rates[1:] = current_counts[1:] / current_counts[:-1]
    baseline_rates[1:] = baseline_counts[1:] / baseline_counts[:-1]

    baseline_factors = np.concatenate(([baseline_counts[0]], baseline_rates[1:]))
    current_factors = np.concatenate(([current_counts[0]], current_rates[1:]))
    working_factors = baseline_factors.copy()
    previous_output = float(np.prod(working_factors))
    impacts: list[float] = []
    for index, value in enumerate(current_factors):
        working_factors[index] = value
        next_output = float(np.prod(working_factors))
        impacts.append(next_output - previous_output)
        previous_output = next_output
    denominator = sum(abs(value) for value in impacts) or 1.0
    results: list[FunnelStageResult] = []
    for index, (stage_id, stage_name) in enumerate(FUNNEL_STAGES):
        rate_change = (current_rates[index] - baseline_rates[index]) * 100
        impact = impacts[index]
        severity = "HIGH" if abs(impact) / denominator >= 0.3 else "MEDIUM" if abs(impact) / denominator >= 0.12 else "LOW"
        results.append(FunnelStageResult(
            stage_id=stage_id,
            stage_name=stage_name,
            current_count=float(current_counts[index]),
            baseline_count=float(baseline_counts[index]),
            current_rate=float(current_rates[index]),
            baseline_rate=float(baseline_rates[index]),
            rate_change_pp=float(rate_change),
            estimated_order_impact=float(impact),
            contribution_pct=float(abs(impact) / denominator),
            severity=severity,
            net_change_contribution=float(impact / (current_counts[-1] - baseline_counts[-1])) if current_counts[-1] != baseline_counts[-1] else None,
            decomposition_order=index + 1,
            residual_error=float(current_counts[-1] - baseline_counts[-1] - sum(impacts)),
            method="曝光→点击→访问→加购→提交→尝试→成功的固定顺序算术替换；非因果；contribution_pct为绝对影响占比；七阶段均为转化旅程计数，历史*_users字段不是全站UV",
        ))
    return results
