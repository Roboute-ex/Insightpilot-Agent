"""Execution engine for deterministic reusable analysis playbooks."""

from __future__ import annotations

from statistics import NormalDist
from typing import Any, Callable

import numpy as np
import pandas as pd

from insightpilot.analysis.causal_light import estimate_adjusted_effect
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.ingestion.mapping import ColumnMapping, normalize_column_mapping, suggest_column_mapping
from insightpilot.playbooks.models import AnalysisPlaybook, PlaybookExecutionResult
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.playbooks.sql_templates import (
    SQLTemplateResult,
    build_dimension_contribution_query,
    build_experiment_summary_query,
    build_metric_trend_query,
    build_period_comparison_query,
    build_profile_query,
)
from insightpilot.playbooks.validation import validate_playbook_parameters
from insightpilot.tools.duckdb_engine import AnalyticsEngine
from insightpilot.visualization.specs import ChartSpec


BASE_CAVEAT = "分析结果基于当前内存数据与所选字段口径，不代表真实业务结论。"
CAUSAL_CAVEAT = "轻量因果探索依赖已观测控制变量，不能把相关性直接解释为因果关系。"
EXECUTION_ROUTES = [
    "select_playbook",
    "validate_playbook",
    "validate_parameters",
    "build_query",
    "execute_query",
    "build_result_tables",
    "build_chart_specs",
]


def _default_table(playbook_id: str, tables: dict[str, pd.DataFrame]) -> str | None:
    preferred = {
        "data_profile": ["daily_metrics", "orders", "content_events"],
        "metric_trend": ["daily_metrics", "orders", "content_events", "live_quality_logs"],
        "period_comparison": ["daily_metrics", "orders", "content_events"],
        "dimension_contribution": ["daily_metrics", "orders", "content_events", "live_quality_logs"],
        "experiment_comparison": ["experiments"],
        "causal_exploration": ["experiments"],
        "periodic_summary": ["daily_metrics", "orders", "content_events"],
    }.get(playbook_id, [])
    for name in preferred:
        if name in tables:
            return name
    return sorted(tables)[0] if tables else None


def _synthetic_mapping(playbook_id: str, table_name: str, df: pd.DataFrame) -> ColumnMapping:
    columns = set(map(str, df.columns))
    date_column = "date" if "date" in columns else None
    numeric = [str(column) for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    dimensions = [
        column for column in ["city", "channel", "user_segment", "device", "network_type", "content_category"]
        if column in columns
    ]
    if playbook_id in {"experiment_comparison", "causal_exploration"} and table_name == "experiments":
        return ColumnMapping(
            table_name=table_name,
            group_column="group",
            treatment_column="group",
            outcome_column="completion_rate",
            metric_columns=["completion_rate"],
            dimension_columns=[column for column in ["historical_activity", "historical_revenue", "city", "channel"] if column in columns],
        )
    preferred_metrics = [
        column for column in ["orders", "revenue", "completion_rate", "stutter_rate", "watch_time"]
        if column in columns
    ]
    return ColumnMapping(
        table_name=table_name,
        date_column=date_column,
        metric_columns=preferred_metrics[:2] or numeric[:2],
        dimension_columns=dimensions[:4],
        outcome_column=(preferred_metrics or numeric or [None])[0],
    )


def _prepare_mapping(
    playbook_id: str,
    tables: dict[str, pd.DataFrame],
    column_mapping: ColumnMapping | dict[str, Any] | None,
) -> tuple[ColumnMapping, pd.DataFrame | None, list[str], str]:
    warnings: list[str] = []
    raw = column_mapping.to_dict() if isinstance(column_mapping, ColumnMapping) else dict(column_mapping or {})
    requested_table = raw.get("table_name")
    if requested_table and requested_table not in tables:
        warnings.append(f"映射指定的表不存在：{requested_table}，已使用确定性 fallback。")
        requested_table = None
    table_name = str(requested_table or _default_table(playbook_id, tables) or "")
    if not table_name:
        return ColumnMapping(notes=["没有可用数据表。"]), None, ["没有可用数据表。"], "none"
    df = tables[table_name]
    if column_mapping is None:
        if table_name in {"daily_metrics", "orders", "content_events", "experiments", "live_quality_logs"}:
            mapping = _synthetic_mapping(playbook_id, table_name, df)
        else:
            mapping = suggest_column_mapping(table_name, df)
        source = "auto_suggested"
    else:
        raw["table_name"] = table_name
        mapping = normalize_column_mapping(raw, [str(column) for column in df.columns])
        source = "user_selected"
    mapping.table_name = table_name
    warnings.extend(mapping.notes)
    return mapping, df, list(dict.fromkeys(warnings)), source


def _apply_defaults(playbook: AnalysisPlaybook, parameters: dict[str, Any] | None) -> dict[str, Any]:
    values = {
        parameter.name: parameter.default
        for parameter in playbook.parameters
        if parameter.default is not None
    }
    values.update(parameters or {})
    return values


def _allowlist(tables: dict[str, pd.DataFrame], table_name: str) -> set[str]:
    return set(tables) | {str(column) for column in tables[table_name].columns}


def _query_record(template: SQLTemplateResult, purpose: str, status: str, row_count: int) -> dict[str, Any]:
    return {
        "tool": "duckdb",
        "template_id": template.template_id,
        "purpose": purpose,
        "query": template.sql,
        "status": status,
        "row_count": int(row_count),
        "referenced_tables": list(template.referenced_tables),
        "referenced_columns": list(template.referenced_columns),
    }


def _run_template(
    engine: AnalyticsEngine,
    template: SQLTemplateResult,
    purpose: str,
    executed_queries: list[dict[str, Any]],
    warnings: list[str],
) -> pd.DataFrame:
    try:
        frame = engine.run_parameterized_sql(template.sql, template.parameters)
        executed_queries.append(_query_record(template, purpose, "success", len(frame)))
        return frame
    except Exception as exc:
        warnings.append(f"{purpose} 查询失败：{exc}")
        executed_queries.append(_query_record(template, purpose, "failed", 0))
        return pd.DataFrame()


def _failure_result(
    playbook: AnalysisPlaybook,
    parameters: dict[str, Any],
    warnings: list[str],
    mapping: ColumnMapping,
    mapping_source: str,
) -> PlaybookExecutionResult:
    return PlaybookExecutionResult(
        playbook_id=playbook.playbook_id,
        playbook_name=playbook.display_name,
        status="FAIL",
        parameters=parameters,
        findings=[],
        caveats=[BASE_CAVEAT],
        warnings=list(dict.fromkeys(warnings)),
        metadata={
            "route_taken": EXECUTION_ROUTES[:3],
            "column_mapping": mapping.to_dict(),
            "mapping_source": mapping_source,
            "requirements_satisfied": False,
            "parameters_valid": not any("参数" in warning for warning in warnings),
            "safe_query_generated": False,
        },
    )


def _profile_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    row_count = max(len(df), 1)
    column_profile = pd.DataFrame(
        [
            {
                "column": str(column),
                "dtype": str(df[column].dtype),
                "missing_count": int(df[column].isna().sum()),
                "missing_rate": float(df[column].isna().sum() / row_count),
                "unique_count": int(df[column].nunique(dropna=True)),
                "high_cardinality": bool(df[column].nunique(dropna=True) > max(50, len(df) * 0.8)),
            }
            for column in df.columns
        ]
    )
    numeric = df.select_dtypes(include="number")
    numeric_summary = numeric.describe().T.reset_index(names="column") if not numeric.empty else pd.DataFrame()
    duplicate_summary = pd.DataFrame(
        [{"row_count": int(len(df)), "duplicate_rows": int(df.duplicated().sum()), "column_count": int(len(df.columns))}]
    )
    result = {
        "column_profile": column_profile,
        "numeric_summary": numeric_summary,
        "duplicate_summary": duplicate_summary,
    }
    if not numeric.empty:
        metric = str(numeric.columns[0])
        values = pd.to_numeric(numeric[metric], errors="coerce").dropna()
        if not values.empty:
            counts, edges = np.histogram(values, bins=min(20, max(5, int(np.sqrt(len(values))))))
            result["numeric_distribution"] = pd.DataFrame(
                {"bin_start": edges[:-1], "bin_end": edges[1:], "count": counts, "metric": metric}
            )
    return result


def _execute_data_profile(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    warnings: list[str] = []
    executed: list[dict[str, Any]] = []
    template = build_profile_query(
        mapping.table_name or "",
        allowed_identifiers=_allowlist(tables, mapping.table_name or ""),
    )
    _run_template(engine, template, "profile_sample", executed, warnings)
    result_tables = _profile_tables(df)
    high_missing = result_tables["column_profile"]
    threshold = float(parameters.get("high_missing_threshold", 0.5))
    high_missing_count = int((high_missing["missing_rate"] >= threshold).sum())
    findings = [
        f"目标表包含 {len(df)} 行、{len(df.columns)} 列。",
        f"检测到 {int(df.duplicated().sum())} 个重复行，{high_missing_count} 个高缺失字段。",
    ]
    specs = [
        ChartSpec("profile_missingness", "missingness_bar", "字段缺失率", "column_profile", x="column", y=["missing_rate"], sort="descending", top_n=30, description="按字段展示缺失比例。"),
    ]
    if "numeric_distribution" in result_tables:
        specs.append(ChartSpec("profile_distribution", "histogram", "数值分布", "numeric_distribution", x="bin_start", y=["count"], description="首个数值指标的分箱分布。"))
    return PlaybookExecutionResult(
        playbook.playbook_id, playbook.display_name, "WARN" if warnings else "PASS", parameters,
        findings, [BASE_CAVEAT], result_tables, [spec.to_dict() for spec in specs], executed, warnings,
    )


def _execute_metric_trend(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    warnings: list[str] = []
    executed: list[dict[str, Any]] = []
    date_range = parameters.get("date_range")
    date_from = date_to = None
    if isinstance(date_range, dict):
        date_from, date_to = date_range.get("start"), date_range.get("end")
    elif isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        date_from, date_to = date_range
    metrics = list(mapping.metric_columns)
    template = build_metric_trend_query(
        mapping.table_name or "",
        mapping.date_column or "",
        metrics,
        _allowlist(tables, mapping.table_name or ""),
        str(parameters.get("time_grain", mapping.time_grain or "day")),
        str(parameters.get("aggregation", "sum")),
        date_from,
        date_to,
    )
    trend = _run_template(engine, template, "metric_trend", executed, warnings)
    rolling_window = int(parameters.get("rolling_window", 7))
    threshold = float(parameters.get("anomaly_threshold", 2.0))
    findings: list[str] = []
    if not trend.empty:
        trend["period"] = pd.to_datetime(trend["period"], errors="coerce")
        for metric in metrics:
            values = pd.to_numeric(trend[metric], errors="coerce")
            trend[f"{metric}_change_rate"] = values.pct_change()
            trend[f"{metric}_rolling_average"] = values.rolling(rolling_window, min_periods=1).mean()
            rolling_std = values.rolling(rolling_window, min_periods=2).std().replace(0, np.nan)
            trend[f"{metric}_anomaly"] = ((values - trend[f"{metric}_rolling_average"]).abs() / rolling_std >= threshold).fillna(False)
            latest = values.dropna().iloc[-1] if values.notna().any() else float("nan")
            findings.append(f"{metric} 最新聚合值为 {latest:.4f}，检测到 {int(trend[f'{metric}_anomaly'].sum())} 个候选异常点。")
    else:
        warnings.append("趋势查询未返回可用数据。")
    specs = [
        ChartSpec("metric_trend", "time_series", "指标趋势", "metric_trend", x="period", y=metrics, description="按时间粒度聚合的指标走势。"),
        ChartSpec("metric_rolling", "line", "滚动均值", "metric_trend", x="period", y=[f"{metric}_rolling_average" for metric in metrics], description="用于观察平滑趋势的滚动均值。"),
    ]
    return PlaybookExecutionResult(
        playbook.playbook_id, playbook.display_name, "WARN" if warnings else "PASS", parameters,
        findings, [BASE_CAVEAT, "异常标记是统计诊断信号，需要结合字段口径复核。"],
        {"metric_trend": trend}, [spec.to_dict() for spec in specs], executed, warnings,
    )


def _period_ranges(df: pd.DataFrame, date_column: str, parameters: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    dates = pd.to_datetime(df[date_column], errors="coerce").dropna()
    if dates.empty:
        raise ValueError("日期列没有有效日期。")
    current_end = pd.Timestamp(parameters.get("current_end") or dates.max()).normalize()
    current_start = pd.Timestamp(parameters.get("current_start") or (current_end - pd.Timedelta(days=6))).normalize()
    duration = current_end - current_start
    previous_end = pd.Timestamp(parameters.get("previous_end") or (current_start - pd.Timedelta(days=1))).normalize()
    previous_start = pd.Timestamp(parameters.get("previous_start") or (previous_end - duration)).normalize()
    return current_start, current_end, previous_start, previous_end


def _execute_period_comparison(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    warnings: list[str] = []
    executed: list[dict[str, Any]] = []
    current_start, current_end, previous_start, previous_end = _period_ranges(df, mapping.date_column or "", parameters)
    metric = mapping.metric_columns[0]
    dimension = mapping.dimension_columns[0] if mapping.dimension_columns else None
    template = build_period_comparison_query(
        mapping.table_name or "", mapping.date_column or "", metric,
        _allowlist(tables, mapping.table_name or ""), current_start, current_end,
        previous_start, previous_end, dimension, str(parameters.get("aggregation", "sum")),
    )
    comparison = _run_template(engine, template, "period_comparison", executed, warnings)
    summary = comparison.groupby("comparison_period", as_index=False)["metric_value"].sum() if not comparison.empty else pd.DataFrame()
    findings: list[str] = []
    if not summary.empty and {"current", "previous"}.issubset(set(summary["comparison_period"])):
        values = summary.set_index("comparison_period")["metric_value"]
        current = float(values["current"])
        previous = float(values["previous"])
        relative = (current - previous) / previous if previous else 0.0
        findings.append(f"{metric} 当前周期相对对比周期变化 {relative:.2%}，绝对变化 {current - previous:.4f}。")
    else:
        warnings.append("两个周期未同时返回可比较结果。")
    specs = [ChartSpec("period_comparison", "grouped_bar", "周期指标对比", "period_comparison", x="comparison_period", y=["metric_value"], color="dimension_value" if dimension else None, description="当前周期与对比周期的聚合指标。")]
    return PlaybookExecutionResult(
        playbook.playbook_id, playbook.display_name, "WARN" if warnings else "PASS", parameters,
        findings, [BASE_CAVEAT], {"period_comparison": comparison, "period_summary": summary},
        [spec.to_dict() for spec in specs], executed, warnings,
        metadata={"periods": {"current": [str(current_start.date()), str(current_end.date())], "previous": [str(previous_start.date()), str(previous_end.date())]}},
    )


def _execute_dimension_contribution(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    warnings: list[str] = []
    executed: list[dict[str, Any]] = []
    metric = str(parameters.get("metric") or mapping.metric_columns[0])
    dimension = str(parameters.get("dimension") or mapping.dimension_columns[0])
    top_n = int(parameters.get("top_n", 10))
    aggregation = str(parameters.get("aggregation", "sum"))
    template = build_dimension_contribution_query(
        mapping.table_name or "", dimension, metric, _allowlist(tables, mapping.table_name or ""), aggregation, top_n
    )
    contribution = _run_template(engine, template, "dimension_contribution", executed, warnings)
    if not contribution.empty:
        denominator = float(contribution["metric_value"].abs().sum())
        contribution["contribution_share"] = contribution["metric_value"].abs() / denominator if denominator else 0.0
        contribution["rank"] = range(1, len(contribution) + 1)
        if bool(parameters.get("include_others", True)) and aggregation in {"sum", "count"}:
            numeric = pd.to_numeric(df[metric], errors="coerce")
            total = float(numeric.sum()) if aggregation == "sum" else float(numeric.notna().sum())
            others = total - float(contribution["metric_value"].sum())
            if abs(others) > 1e-12:
                contribution = pd.concat([contribution, pd.DataFrame([{"dimension_value": "Others", "metric_value": others, "contribution_share": abs(others) / (abs(total) or 1.0), "rank": len(contribution) + 1}])], ignore_index=True)
    findings = [f"{dimension} 维度已输出前 {min(top_n, len(contribution))} 个贡献项。"] if not contribution.empty else []
    if contribution.empty:
        warnings.append("维度贡献查询未返回可用数据。")
    specs = [
        ChartSpec("dimension_contribution", "contribution_bar", "维度贡献", "dimension_contribution", x="dimension_value", y=["metric_value"], sort=str(parameters.get("sort_order", "descending")), top_n=top_n + 1, description="按维度展示指标贡献值。"),
        ChartSpec("dimension_table", "table", "维度贡献明细", "dimension_contribution", description="贡献值、占比与排名。"),
    ]
    return PlaybookExecutionResult(
        playbook.playbook_id, playbook.display_name, "WARN" if warnings else "PASS", parameters,
        findings, [BASE_CAVEAT], {"dimension_contribution": contribution},
        [spec.to_dict() for spec in specs], executed, warnings,
    )


def _execute_experiment_comparison(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    warnings: list[str] = []
    executed: list[dict[str, Any]] = []
    metric = str(parameters.get("metric") or mapping.metric_columns[0])
    control = parameters.get("control_value", "control")
    treatment = parameters.get("treatment_value", "treatment")
    template = build_experiment_summary_query(
        mapping.table_name or "", mapping.group_column or "", metric,
        _allowlist(tables, mapping.table_name or ""), control, treatment,
    )
    summary = _run_template(engine, template, "experiment_summary", executed, warnings)
    working = df[df[mapping.group_column].isin([control, treatment])][[mapping.group_column, metric]].copy()
    working[mapping.group_column] = working[mapping.group_column].map({control: "control", treatment: "treatment"})
    result_tables: dict[str, pd.DataFrame] = {"experiment_summary": summary}
    findings: list[str] = []
    try:
        analysis = analyze_ab_test(working, mapping.group_column or "", metric, str(parameters.get("metric_type", "mean")))
        confidence = float(parameters.get("confidence_level", 0.95))
        z_value = NormalDist().inv_cdf(0.5 + confidence / 2)
        control_values = pd.to_numeric(
            working.loc[working[mapping.group_column] == "control", metric], errors="coerce"
        ).dropna()
        treatment_values = pd.to_numeric(
            working.loc[working[mapping.group_column] == "treatment", metric], errors="coerce"
        ).dropna()
        if str(parameters.get("metric_type", "mean")) == "proportion":
            standard_error_lift = float(
                np.sqrt(
                    treatment_values.mean() * (1 - treatment_values.mean()) / len(treatment_values)
                    + control_values.mean() * (1 - control_values.mean()) / len(control_values)
                )
            )
        else:
            standard_error_lift = float(
                np.sqrt(
                    treatment_values.var(ddof=1) / len(treatment_values)
                    + control_values.var(ddof=1) / len(control_values)
                )
            )
        absolute_lift = float(analysis["absolute_lift"])
        analysis["confidence_level"] = confidence
        analysis["confidence_interval"] = (
            absolute_lift - z_value * standard_error_lift,
            absolute_lift + z_value * standard_error_lift,
        )
        if not summary.empty and "metric_std" in summary.columns:
            standard_error = pd.to_numeric(summary["metric_std"], errors="coerce") / np.sqrt(pd.to_numeric(summary["sample_size"], errors="coerce"))
            summary["ci_lower"] = summary["metric_mean"] - z_value * standard_error
            summary["ci_upper"] = summary["metric_mean"] + z_value * standard_error
        result_tables["experiment_statistics"] = pd.DataFrame([analysis])
        findings = [
            f"实验组相对对照组 lift 为 {float(analysis['relative_lift']):.2%}。",
            f"p-value={float(analysis['p_value']):.6f}，样本量={analysis['sample_size']}。",
            str(analysis["conclusion"]),
        ]
        dimension = parameters.get("dimension")
        if dimension:
            stratified_rows: list[dict[str, Any]] = []
            for value, subset in df.groupby(str(dimension), dropna=False):
                stratum = subset[subset[mapping.group_column].isin([control, treatment])][[mapping.group_column, metric]].copy()
                stratum[mapping.group_column] = stratum[mapping.group_column].map({control: "control", treatment: "treatment"})
                try:
                    stratum_result = analyze_ab_test(
                        stratum,
                        mapping.group_column or "",
                        metric,
                        str(parameters.get("metric_type", "mean")),
                    )
                except Exception:
                    continue
                stratified_rows.append(
                    {
                        "dimension_value": value,
                        "absolute_lift": stratum_result["absolute_lift"],
                        "relative_lift": stratum_result["relative_lift"],
                        "p_value": stratum_result["p_value"],
                        "sample_size": str(stratum_result["sample_size"]),
                    }
                )
            if stratified_rows:
                result_tables["experiment_stratified"] = pd.DataFrame(stratified_rows)
    except Exception as exc:
        warnings.append(f"实验统计检验失败：{exc}")
    specs = [
        ChartSpec("experiment_bar", "grouped_bar", "实验组与对照组", "experiment_summary", x="group_value", y=["metric_mean"], description="展示两组均值。"),
        ChartSpec("experiment_ci", "confidence_interval", "实验结果置信区间", "experiment_summary", x="group_value", y=["metric_mean"], description="展示组均值及置信区间。"),
    ]
    return PlaybookExecutionResult(
        playbook.playbook_id, playbook.display_name, "WARN" if warnings else "PASS", parameters,
        findings, [BASE_CAVEAT, "统计显著性不等于业务重要性，需同时复核样本与指标口径。"],
        result_tables, [spec.to_dict() for spec in specs], executed, warnings,
    )


def _execute_causal_exploration(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    del tables, engine
    warnings: list[str] = []
    covariates = parameters.get("covariates") or mapping.dimension_columns
    if isinstance(covariates, str):
        covariates = [item.strip() for item in covariates.split(",") if item.strip()]
    covariates = [str(column) for column in covariates]
    control = parameters.get("control_value", "control")
    treatment = parameters.get("treatment_value", "treatment")
    working = df.copy()
    treatment_column = mapping.treatment_column or ""
    outcome_column = mapping.outcome_column or ""
    working[treatment_column] = working[treatment_column].map({control: "control", treatment: "treatment"})
    working = working[working[treatment_column].notna()]
    outcome = pd.to_numeric(working[outcome_column], errors="coerce")
    treated = outcome[working[treatment_column] == "treatment"].dropna()
    control_rows = outcome[working[treatment_column] == "control"].dropna()
    naive_difference = float(treated.mean() - control_rows.mean()) if not treated.empty and not control_rows.empty else float("nan")
    findings: list[str] = [f"naive difference={naive_difference:.4f}。"]
    summary_row: dict[str, Any] = {
        "naive_difference": naive_difference,
        "adjusted_effect": np.nan,
        "propensity_weighted_effect": np.nan,
        "sample_size": int(outcome.notna().sum()),
    }
    result_tables: dict[str, pd.DataFrame] = {}
    if not covariates:
        warnings.append("缺少控制变量，已输出 naive difference，未执行回归调整。")
    else:
        try:
            analysis = estimate_adjusted_effect(working, treatment_column, outcome_column, covariates)
            summary_row = {key: value for key, value in analysis.items() if key != "caveats"}
            findings.append(f"regression adjusted effect={float(analysis['adjusted_effect']):.4f}。")
        except Exception as exc:
            warnings.append(f"轻量因果估计失败：{exc}")
    result_tables["adjusted_effect_summary"] = pd.DataFrame([summary_row])
    specs = [ChartSpec("adjusted_effect", "bar", "调整效应摘要", "adjusted_effect_summary", x=None, y=["naive_difference", "adjusted_effect", "propensity_weighted_effect"], description="对比未调整与轻量调整估计。")]
    return PlaybookExecutionResult(
        playbook.playbook_id, playbook.display_name, "WARN" if warnings else "PASS", parameters,
        findings, [BASE_CAVEAT, CAUSAL_CAVEAT], result_tables,
        [spec.to_dict() for spec in specs], [], warnings,
        metadata={"uses_pandas_fallback": True},
    )


def _execute_periodic_summary(
    playbook: AnalysisPlaybook,
    tables: dict[str, pd.DataFrame],
    mapping: ColumnMapping,
    df: pd.DataFrame,
    parameters: dict[str, Any],
    engine: AnalyticsEngine,
) -> PlaybookExecutionResult:
    del playbook, df, engine
    parts: list[PlaybookExecutionResult] = []
    parts.append(execute_playbook("data_profile", tables, mapping, {"high_missing_threshold": 0.5}))
    caveats = [BASE_CAVEAT]
    warnings: list[str] = []
    if mapping.date_column and mapping.metric_columns:
        parts.append(execute_playbook("metric_trend", tables, mapping, {
            "time_grain": parameters.get("time_grain", mapping.time_grain),
            "aggregation": parameters.get("aggregation", "sum"),
            "rolling_window": parameters.get("rolling_window", 7),
            "anomaly_threshold": 2.0,
        }))
        parts.append(execute_playbook("period_comparison", tables, mapping, {
            "comparison_type": "previous_period",
            "top_n": parameters.get("top_n", 5),
            "aggregation": parameters.get("aggregation", "sum"),
        }))
    else:
        warnings.append("缺少 date_column 或 metric_columns，周期摘要已降级为 profile 与指标摘要。")
        caveats.append("由于日期映射不完整，本次未生成时间趋势。")
    if mapping.metric_columns and mapping.dimension_columns:
        parts.append(execute_playbook("dimension_contribution", tables, mapping, {
            "metric": mapping.metric_columns[0],
            "dimension": mapping.dimension_columns[0],
            "top_n": parameters.get("top_n", 5),
            "sort_order": "descending",
            "include_others": True,
            "aggregation": parameters.get("aggregation", "sum"),
        }))
    result_tables: dict[str, pd.DataFrame] = {}
    chart_specs: list[dict[str, Any]] = []
    findings: list[str] = []
    executed: list[dict[str, Any]] = []
    if mapping.metric_columns:
        metric_summary_rows: list[dict[str, Any]] = []
        source = tables[mapping.table_name or ""]
        for metric in mapping.metric_columns:
            values = pd.to_numeric(source[metric], errors="coerce").dropna()
            if not values.empty:
                metric_summary_rows.append(
                    {
                        "metric": metric,
                        "count": int(values.count()),
                        "mean": float(values.mean()),
                        "min": float(values.min()),
                        "max": float(values.max()),
                    }
                )
        if metric_summary_rows:
            result_tables["metric_summary"] = pd.DataFrame(metric_summary_rows)
    for part in parts:
        prefix = part.playbook_id
        findings.extend(part.findings)
        warnings.extend(part.warnings)
        executed.extend(part.executed_queries)
        key_map: dict[str, str] = {}
        for key, frame in part.result_tables.items():
            new_key = f"{prefix}_{key}"
            key_map[key] = new_key
            result_tables[new_key] = frame
        for spec_dict in part.chart_specs:
            spec = dict(spec_dict)
            spec["chart_id"] = f"{prefix}_{spec['chart_id']}"
            spec["table_key"] = key_map.get(str(spec["table_key"]), str(spec["table_key"]))
            chart_specs.append(spec)
    return PlaybookExecutionResult(
        "periodic_summary", "周期分析摘要", "WARN" if warnings else "PASS", parameters,
        list(dict.fromkeys(findings)), caveats, result_tables, chart_specs, executed,
        list(dict.fromkeys(warnings)), metadata={"component_playbooks": [part.playbook_id for part in parts]},
    )


EXECUTORS: dict[str, Callable[..., PlaybookExecutionResult]] = {
    "execute_data_profile": _execute_data_profile,
    "execute_metric_trend": _execute_metric_trend,
    "execute_period_comparison": _execute_period_comparison,
    "execute_dimension_contribution": _execute_dimension_contribution,
    "execute_experiment_comparison": _execute_experiment_comparison,
    "execute_causal_exploration": _execute_causal_exploration,
    "execute_periodic_summary": _execute_periodic_summary,
}


def execute_playbook(
    playbook_id: str,
    tables: dict[str, pd.DataFrame],
    column_mapping: ColumnMapping | dict[str, Any] | None,
    parameters: dict[str, Any] | None = None,
    table_metadata: dict[str, Any] | None = None,
) -> PlaybookExecutionResult:
    """Validate and execute one built-in playbook without external services."""

    del table_metadata
    registry = get_playbook_registry()
    playbook = registry.get(playbook_id)
    mapping, df, mapping_warnings, mapping_source = _prepare_mapping(playbook_id, tables, column_mapping)
    normalized_parameters = _apply_defaults(playbook, parameters)
    if df is None or not mapping.table_name:
        return _failure_result(playbook, normalized_parameters, mapping_warnings or ["没有可用数据表。"], mapping, mapping_source)
    if "metric" in normalized_parameters and not normalized_parameters.get("metric") and mapping.metric_columns:
        normalized_parameters["metric"] = mapping.metric_columns[0]
    if "dimension" in normalized_parameters and not normalized_parameters.get("dimension") and mapping.dimension_columns:
        normalized_parameters["dimension"] = mapping.dimension_columns[0]
    if "covariates" in normalized_parameters and not normalized_parameters.get("covariates"):
        normalized_parameters["covariates"] = list(mapping.dimension_columns)

    validation_errors = validate_playbook_parameters(
        playbook,
        normalized_parameters,
        mapping,
        [str(column) for column in df.columns],
        dataframe=df,
    )
    if len(df) < playbook.requirements.minimum_rows:
        validation_errors.append(
            f"当前表只有 {len(df)} 行，剧本至少需要 {playbook.requirements.minimum_rows} 行。"
        )
    if validation_errors:
        return _failure_result(
            playbook,
            normalized_parameters,
            [*mapping_warnings, *validation_errors],
            mapping,
            mapping_source,
        )

    engine = AnalyticsEngine()
    engine.register_tables(tables)
    executor = EXECUTORS[playbook.executor_name]
    try:
        result = executor(playbook, tables, mapping, df, normalized_parameters, engine)
    except Exception as exc:
        return _failure_result(
            playbook,
            normalized_parameters,
            [*mapping_warnings, f"playbook 执行失败：{exc}"],
            mapping,
            mapping_source,
        )
    result.warnings = list(dict.fromkeys([*mapping_warnings, *result.warnings]))
    if result.status == "PASS" and result.warnings:
        result.status = "WARN"
    result.metadata.update(
        {
            "route_taken": EXECUTION_ROUTES,
            "column_mapping": mapping.to_dict(),
            "mapping_source": mapping_source,
            "requirements_satisfied": True,
            "parameters_valid": True,
            "safe_query_generated": all(query.get("status") == "success" for query in result.executed_queries)
            if result.executed_queries
            else bool(result.metadata.get("uses_pandas_fallback")),
            "result_table_names": sorted(result.result_tables),
        }
    )
    return result
