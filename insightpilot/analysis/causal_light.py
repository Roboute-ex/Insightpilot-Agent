"""Lightweight exploratory adjustment for treatment effects."""

from __future__ import annotations

import numpy as np
import pandas as pd

from insightpilot.analysis.groups import GroupSelectionError, group_labels

try:
    from sklearn.linear_model import LinearRegression, LogisticRegression
except ImportError:  # pragma: no cover - dependency is declared for normal use
    LinearRegression = None
    LogisticRegression = None


_TREATMENT_TOKENS = {"1", "true", "treated", "treatment", "yes"}
_CONTROL_TOKENS = {"0", "false", "control", "untreated", "no"}


class TreatmentDirectionError(GroupSelectionError):
    """Raised when treatment and control groups cannot be identified without guessing."""


def treatment_indicator(
    series: pd.Series,
    *,
    treatment_value: object | None = None,
    control_value: object | None = None,
) -> pd.Series:
    """Return 1/0 for treatment/control and NaN for rows outside the two selected groups."""

    if treatment_value is not None or control_value is not None:
        try:
            labels = group_labels(series, treatment_value=treatment_value, control_value=control_value)
        except GroupSelectionError as exc:
            raise TreatmentDirectionError(str(exc)) from exc
        return labels.map({"treatment": 1.0, "control": 0.0}).astype(float)
    if series.dtype == bool:
        return series.astype(float)
    if pd.api.types.is_numeric_dtype(series) and set(series.unique()) <= {0, 1}:
        return series.astype(float)
    lowered = series.astype(str).str.strip().str.lower()
    observed = set(lowered.unique())
    if observed <= _TREATMENT_TOKENS | _CONTROL_TOKENS and observed & _TREATMENT_TOKENS and observed & _CONTROL_TOKENS:
        return lowered.isin(_TREATMENT_TOKENS).astype(float)
    shown = "、".join(sorted(map(str, series.astype(str).unique()))[:5])
    raise TreatmentDirectionError(f"处理字段取值（{shown}）无法确定哪一组是处理组，请明确选择处理组与对照组取值。")


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
    treatment_value: object | None = None,
    control_value: object | None = None,
) -> dict[str, object]:
    """Estimate exploratory treatment effect with regression and simple weighting.

    When ``treatment_value``/``control_value`` are given they define the comparison
    direction; otherwise only unambiguous binary encodings are accepted.
    """

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
    indicator = treatment_indicator(working[treatment_col], treatment_value=treatment_value, control_value=control_value)
    selected = indicator.notna()
    excluded_rows = int((~selected).sum())
    working = working.loc[selected]
    treatment = indicator.loc[selected].astype(int).rename("treatment_indicator")
    if treatment.nunique() != 2:
        raise TreatmentDirectionError("因果探索需要两个有效处理组；所选处理组或对照组取值在数据中不存在。")
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
    if excluded_rows:
        caveats.append(f"排除 {excluded_rows} 行不属于所选处理组或对照组的记录。")
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
