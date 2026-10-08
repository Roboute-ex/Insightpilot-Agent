"""Lightweight exploratory adjustment for treatment effects."""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from sklearn.linear_model import LinearRegression, LogisticRegression
except ImportError:  # pragma: no cover - dependency is declared for normal use
    LinearRegression = None
    LogisticRegression = None


def _treatment_as_binary(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.astype(int)
    lowered = series.astype(str).str.lower()
    return lowered.isin({"1", "true", "treated", "treatment", "yes"}).astype(int)


def _linear_effect(x: pd.DataFrame, y: pd.Series, treatment_col: str) -> float:
    if LinearRegression is not None:
        model = LinearRegression()
        model.fit(x, y)
        return float(model.coef_[list(x.columns).index(treatment_col)])
    matrix = np.column_stack([np.ones(len(x)), x.to_numpy(dtype=float)])
    coef, *_ = np.linalg.lstsq(matrix, y.to_numpy(dtype=float), rcond=None)
    return float(coef[list(x.columns).index(treatment_col) + 1])


def _propensity_weighted_effect(x_covariates: pd.DataFrame, treatment: pd.Series, outcome: pd.Series) -> float:
    if LogisticRegression is not None and len(treatment.unique()) == 2:
        model = LogisticRegression(max_iter=500)
        model.fit(x_covariates, treatment)
        propensity = model.predict_proba(x_covariates)[:, 1]
    else:
        propensity = np.repeat(float(treatment.mean()), len(treatment))
    propensity = np.clip(propensity, 0.05, 0.95)
    treated_weight = treatment / propensity
    control_weight = (1 - treatment) / (1 - propensity)
    treated_mean = np.average(outcome, weights=treated_weight) if treated_weight.sum() else np.nan
    control_mean = np.average(outcome, weights=control_weight) if control_weight.sum() else np.nan
    return float(treated_mean - control_mean)


def estimate_adjusted_effect(
    df: pd.DataFrame,
    treatment_col: str,
    outcome_col: str,
    covariates: list[str],
    *, include_propensity: bool = False,
) -> dict[str, object]:
    """Estimate exploratory treatment effect with regression and simple weighting."""

    required = {treatment_col, outcome_col, *covariates}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")

    covariates = list(dict.fromkeys(column for column in covariates if column not in {treatment_col, outcome_col}))
    working = df[[treatment_col, outcome_col, *covariates]].copy()
    working[outcome_col] = pd.to_numeric(working[outcome_col], errors="coerce")
    working = working.replace([np.inf, -np.inf], np.nan).dropna()
    if working.empty:
        raise ValueError("没有完整有效的处理、结果及协变量样本。")
    treatment = _treatment_as_binary(working[treatment_col]).rename("treatment_indicator")
    if treatment.nunique() != 2:
        raise ValueError("因果探索需要两个有效处理组。")
    outcome = pd.to_numeric(working[outcome_col], errors="coerce")
    covariate_frame = pd.get_dummies(working[covariates], drop_first=True, dtype=float)
    x = pd.concat([treatment, covariate_frame], axis=1)

    treated = outcome[treatment == 1]
    control = outcome[treatment == 0]
    naive_difference = float(treated.mean() - control.mean())
    adjusted_effect = _linear_effect(x, outcome, "treatment_indicator")
    propensity_effect = _propensity_weighted_effect(covariate_frame, treatment, outcome) if include_propensity else None
    caveats = [
        "该模块用于探索性分析。",
        "不能把相关性直接解释为因果关系。",
        "synthetic data 不代表真实业务结论。",
        "结果依赖已纳入的控制变量，未观测混杂仍可能存在。",
        "需确认协变量先于处理发生，并检查两组协变量重叠性；回归调整不能证明因果。",
        "倾向评分加权默认关闭，只有显式 include_propensity=True 才运行可选方法。",
    ]
    return {
        "estimated_effect": adjusted_effect,
        "naive_difference": naive_difference,
        "adjusted_effect": adjusted_effect,
        "propensity_weighted_effect": propensity_effect,
        "sample_size": int(len(working)),
        "covariates": list(covariates),
        "method": "ordinary_least_squares_regression_adjustment",
        "caveats": caveats,
    }
