"""One numeric presentation contract for experiment UI and report formats."""

from __future__ import annotations

import math
from typing import Any

from insightpilot.ui.formatters import format_metric_name


def finite_number(value: Any, *, percent: bool = False, points: bool = False) -> str:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return "不可计算"
    if not math.isfinite(number):
        return "不可计算"
    if points:
        return f"{number * 100:.4g} 个百分点"
    return f"{number:.4%}" if percent else f"{number:,.6g}"


def experiment_display(item: dict[str, Any]) -> dict[str, str]:
    metric = str(item.get("metric_id", ""))
    is_rate = metric.endswith("_rate") or metric in {"ctr", "cvr", "conversion_rate"}
    difference = lambda value: finite_number(value, points=is_rate)
    level = finite_number(float(item.get("confidence_level") or 0.95) * 100)
    p = item.get("p_value")
    p_text = finite_number(p)
    if p == 0:
        p_text = "< 1e-300（数值下溢）"
    return {
        "分析指标": format_metric_name(metric),
        "实验组": f"{finite_number(item.get('treatment_value'), percent=is_rate)}；独立样本量 {item.get('treatment_sample_size', '未知')}",
        "对照组": f"{finite_number(item.get('control_value'), percent=is_rate)}；独立样本量 {item.get('control_sample_size', '未知')}",
        "绝对提升（lift）": difference(item.get("absolute_lift")),
        "相对提升（lift）": finite_number(item.get("relative_lift"), percent=True),
        "p-value": p_text,
        f"{level}% 置信区间（实验组减对照组的绝对差）": f"[{difference(item.get('confidence_interval_lower'))}, {difference(item.get('confidence_interval_upper'))}]",
        "检验方法": str(item.get("method", "未声明")),
        "统计单位": str(item.get("statistical_unit", item.get("randomization_unit", "请参见方法与限制"))),
        "显著性结论": str(item.get("significance_conclusion", "未提供")),
    }
