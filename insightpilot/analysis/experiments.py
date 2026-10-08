"""Experiment statistics computed at an explicitly reported independent unit."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import stats


def analyze_ab_test(df: pd.DataFrame, group_col: str, metric_col: str, metric_type: str = "mean", *, confidence_level: float = 0.95, statistical_unit: str | None = None, control_value: str = "control", treatment_value: str = "treatment") -> dict[str, object]:
    if group_col not in df or metric_col not in df:
        raise ValueError("缺少实验分组或结果字段，请补充字段映射。")
    if metric_type not in {"mean", "proportion"} or not 0 < confidence_level < 1:
        raise ValueError("实验类型或置信水平无效。")
    if control_value == treatment_value:
        raise ValueError("实验组与对照组不能相同。")
    unit = None if statistical_unit == "row" else statistical_unit or next((column for column in ("user_id", "customer_id", "participant_id") if column in df), None)
    limitations = ["统计显著性不等于业务重要性；上线前应复核随机化、长期稳定性及多重比较。"]
    working = df[df[group_col].isin([control_value, treatment_value])].copy()
    working[metric_col] = pd.to_numeric(working[metric_col], errors="coerce")
    valid = working[metric_col].notna() & np.isfinite(working[metric_col])
    excluded = int((~valid).sum())
    working = working[valid]
    if excluded:
        limitations.append(f"排除 {excluded} 条缺失或非有限结果值。")
    if unit:
        if unit not in working or working[unit].isna().any():
            raise ValueError("统计单位字段缺失或包含空值，无法确认独立样本。")
        if (working.groupby(unit)[group_col].nunique() > 1).any():
            raise ValueError("同一统计单位出现在多个实验组中，请检查随机化分配。")
        if working[unit].duplicated().any():
            if metric_type == "proportion":
                raise ValueError("二元实验有重复统计单位，请先按明确的用户级成功定义汇总。")
            working = working.groupby([unit, group_col], as_index=False)[metric_col].mean()
            limitations.append("重复事件已按随机化单位取均值，每个单位贡献一个连续结果；请确认该口径。")
    else:
        limitations.append("未提供随机化单位字段，暂按每行一个单位计算；独立性尚未验证。")
    control = working.loc[working[group_col] == control_value, metric_col].to_numpy(dtype=float)
    treatment = working.loc[working[group_col] == treatment_value, metric_col].to_numpy(dtype=float)
    sizes = {"control": len(control), "treatment": len(treatment)}
    if min(sizes.values()) < 2:
        raise ValueError("每组至少需要两个有效独立样本。")
    if min(sizes.values()) < 30:
        limitations.append("至少一组少于 30 个独立单位，结果存在低样本风险。")
    cm, tm = float(control.mean()), float(treatment.mean())
    diff = tm - cm
    if metric_type == "proportion":
        if not np.isin(np.concatenate([control, treatment]), [0, 1]).all():
            raise ValueError("比例检验要求真实 0/1 二元结果；连续用户完播率请使用 mean。")
        v1, v2 = cm * (1 - cm) / len(control), tm * (1 - tm) / len(treatment)
        se = float(np.sqrt(v1 + v2))
        critical = float(stats.norm.ppf(0.5 + confidence_level / 2))
        p_value = float(2 * stats.norm.sf(abs(diff / se))) if se else (1.0 if diff == 0 else float(np.nextafter(0, 1)))
        method = "用户级二元结果的非合并 Wald 比例差检验及同口径正态置信区间"
        if min(control.sum(), treatment.sum(), len(control) - control.sum(), len(treatment) - treatment.sum()) < 5:
            limitations.append("成功或失败事件少于 5，Wald 正态近似不稳定，应增加样本或复核精确方法。")
        dfree = None
    else:
        v1, v2 = float(control.var(ddof=1) / len(control)), float(treatment.var(ddof=1) / len(treatment))
        se = float(np.sqrt(v1 + v2))
        denominator = v1 * v1 / (len(control) - 1) + v2 * v2 / (len(treatment) - 1)
        dfree = (v1 + v2) ** 2 / denominator if denominator else float("inf")
        critical = float(stats.t.ppf(0.5 + confidence_level / 2, dfree))
        p_value = float(2 * stats.t.sf(abs(diff / se), dfree)) if se else (1.0 if diff == 0 else float(np.nextafter(0, 1)))
        method = "Welch t-test；置信区间使用同一有效样本和 Welch–Satterthwaite 自由度"
    if se == 0:
        limitations.append("两组均为零方差，常规推断的适用性有限。")
    p_value = max(float(np.nextafter(0, 1)), p_value)
    ci = (float(diff - critical * se), float(diff + critical * se))
    significant = p_value < 1 - confidence_level
    conclusion = "当前样本显示统计差异，仍需验证随机化、长期稳定性及业务意义。" if significant else "当前样本未显示统计差异；非显著不等于没有效果。"
    return {"control_mean": cm, "treatment_mean": tm, "absolute_lift": diff, "relative_lift": diff / cm if cm else None, "p_value": p_value, "confidence_interval": ci, "sample_size": sizes, "conclusion": conclusion, "metric_type": metric_type, "confidence_level": confidence_level, "method": method, "statistical_unit": unit or "row (independence unverified)", "randomization_unit": unit, "standard_error": se, "degrees_of_freedom": dfree, "is_significant": significant, "limitations": limitations, "excluded_rows": excluded, "confidence_interval_type": "absolute_difference_treatment_minus_control"}
