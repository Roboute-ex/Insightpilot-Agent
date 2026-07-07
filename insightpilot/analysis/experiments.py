"""A/B experiment analysis."""

from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd

try:
    from scipy import stats
except ImportError:  # pragma: no cover - dependency is declared for normal use
    stats = None

try:
    from statsmodels.stats.proportion import proportions_ztest
except ImportError:  # pragma: no cover - optional fallback is covered by logic
    proportions_ztest = None


def _normal_two_sided_p(z_value: float) -> float:
    cdf = 0.5 * (1.0 + erf(abs(z_value) / sqrt(2.0)))
    return float(2.0 * (1.0 - cdf))


def _conclusion(p_value: float, sample_size: dict[str, int]) -> str:
    if min(sample_size.values()) < 30:
        return "样本量偏小，结果仅适合继续观察，不应放大结论。"
    if p_value < 0.05:
        return "p_value < 0.05，合成实验中存在统计显著差异；仍需结合长期稳定性继续观察。"
    return "p_value >= 0.05，当前合成样本未显示统计显著差异，建议继续观察或扩大样本。"


def analyze_ab_test(
    df: pd.DataFrame,
    group_col: str,
    metric_col: str,
    metric_type: str = "mean",
) -> dict[str, object]:
    """Analyze control and treatment groups with deterministic statistics."""

    if group_col not in df.columns or metric_col not in df.columns:
        raise ValueError("Missing group or metric column")
    groups = set(df[group_col].dropna().astype(str).unique())
    if not {"control", "treatment"}.issubset(groups):
        raise ValueError("Expected groups named control and treatment")

    control = pd.to_numeric(df[df[group_col] == "control"][metric_col], errors="coerce").dropna().to_numpy()
    treatment = pd.to_numeric(df[df[group_col] == "treatment"][metric_col], errors="coerce").dropna().to_numpy()
    sample_size = {"control": int(len(control)), "treatment": int(len(treatment))}
    control_mean = float(np.mean(control))
    treatment_mean = float(np.mean(treatment))
    absolute_lift = treatment_mean - control_mean
    relative_lift = absolute_lift / control_mean if control_mean else 0.0

    if metric_type == "proportion":
        control_success = float(control.sum())
        treatment_success = float(treatment.sum())
        if proportions_ztest is not None:
            _, p_value = proportions_ztest(
                count=np.array([treatment_success, control_success]),
                nobs=np.array([len(treatment), len(control)]),
            )
            p_value = float(p_value)
        else:
            pooled = (control_success + treatment_success) / (len(control) + len(treatment))
            se = sqrt(max(pooled * (1 - pooled) * (1 / len(control) + 1 / len(treatment)), 1e-12))
            p_value = _normal_two_sided_p(absolute_lift / se)
        ci_se = sqrt(
            max(
                treatment_mean * (1 - treatment_mean) / len(treatment)
                + control_mean * (1 - control_mean) / len(control),
                1e-12,
            )
        )
    elif metric_type == "mean":
        if stats is not None:
            _, p_value = stats.ttest_ind(treatment, control, equal_var=False, nan_policy="omit")
            p_value = float(p_value)
        else:
            se = sqrt(max(np.var(treatment, ddof=1) / len(treatment) + np.var(control, ddof=1) / len(control), 1e-12))
            p_value = _normal_two_sided_p(absolute_lift / se)
        ci_se = sqrt(max(np.var(treatment, ddof=1) / len(treatment) + np.var(control, ddof=1) / len(control), 1e-12))
    else:
        raise ValueError("metric_type must be 'mean' or 'proportion'")

    confidence_interval = (float(absolute_lift - 1.96 * ci_se), float(absolute_lift + 1.96 * ci_se))
    return {
        "control_mean": control_mean,
        "treatment_mean": treatment_mean,
        "absolute_lift": absolute_lift,
        "relative_lift": relative_lift,
        "p_value": p_value,
        "confidence_interval": confidence_interval,
        "sample_size": sample_size,
        "conclusion": _conclusion(p_value, sample_size),
        "metric_type": metric_type,
    }
