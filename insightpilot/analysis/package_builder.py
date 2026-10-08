"""Build evidence-backed result packages from deterministic workflow outputs."""

from __future__ import annotations

from insightpilot.performance_tasks import cancellation_checkpoint
from insightpilot.observability.tracer import trace_stage

from dataclasses import asdict
import math
import re
from typing import Any

import pandas as pd

from insightpilot.analysis.dimension_contribution import dimension_contribution_results
from insightpilot.analysis.associations import quality_conversion_association
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.analysis.funnel_decomposition import decompose_transaction_funnel
from insightpilot.analysis.metric_diagnosis import METRIC_NAMES, diagnose_metrics
from insightpilot.analysis.recommendations import build_recommendations
from insightpilot.analysis.results import (
    ActionRecommendation,
    AnalysisEvidence,
    AnalysisResultPackage,
    AnomalyResult,
    DimensionContributionResult,
    ExperimentComparisonResult,
    FunnelStageResult,
    MetricComparisonResult,
    records_frame,
)


def _is_rate_metric(metric_id: str) -> bool:
    return metric_id.endswith("_rate") or metric_id in {"ctr", "cvr", "conversion_rate"}


def _format_experiment_value(metric_id: str, value: float) -> str:
    return f"{value:.2%}" if _is_rate_metric(metric_id) else f"{value:,.4g}"


def _main_comparisons(values: list[MetricComparisonResult]) -> list[MetricComparisonResult]:
    return [item for item in values if item.baseline_period == "前 7 日均值"]


def _quality_table(state: Any, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, frame in tables.items():
        with trace_stage("result_quality_scan",table=name,rows=len(frame),columns=len(frame.columns)):
            missing = int(frame.isna().sum().sum())
            cancellation_checkpoint()
            duplicates = int(frame.duplicated().sum())
        if missing or duplicates:
            rows.append({
                "table": name,
                "row_count": int(len(frame)),
                "missing_values": missing,
                "duplicate_rows": duplicates,
                "status": "WARN",
            })
    for warning in [*getattr(state, "schema_warnings", []), *getattr(state, "mapping_warnings", [])]:
        rows.append({"table": "workflow", "row_count": 0, "missing_values": 0, "duplicate_rows": 0, "status": str(warning)})
    if not rows:
        rows.append({"table": "workflow", "row_count": sum(len(frame) for frame in tables.values()), "missing_values": 0, "duplicate_rows": 0, "status": "PASS"})
    return pd.DataFrame(rows)


def _evidence_from_results(
    comparisons: list[MetricComparisonResult],
    anomalies: list[AnomalyResult],
    funnel: list[FunnelStageResult],
    contributions: list[DimensionContributionResult],
) -> list[AnalysisEvidence]:
    evidence: list[AnalysisEvidence] = []
    counter = 1
    for item in _main_comparisons(comparisons):
        evidence.append(AnalysisEvidence(
            evidence_id=f"E-{counter:03d}",
            claim=f"{item.metric_name}较{item.baseline_period}{item.direction}{abs(item.relative_change):.1%}。",
            metric=item.metric_id,
            method="目标期与历史基准比较",
            result_table="metric_comparisons",
            supporting_values={"current": item.current_value, "baseline": item.baseline_value, "relative_change": item.relative_change, "z_score": item.z_score},
            confidence="中高" if item.sample_size >= 100 else "中",
            caveat=item.confidence_note,
        ))
        counter += 1
    for item in anomalies:
        if item.severity == "LOW":
            continue
        evidence.append(AnalysisEvidence(
            evidence_id=f"E-{counter:03d}",
            claim=f"{METRIC_NAMES.get(item.metric_id, item.metric_id)}在 {item.date} 超出历史波动区间，等级为 {item.severity}。",
            metric=item.metric_id,
            method=item.method,
            result_table="anomalies",
            supporting_values={"actual": item.actual_value, "expected": item.expected_value, "lower": item.lower_bound, "upper": item.upper_bound},
            confidence="中",
            caveat="异常检测是统计信号，不直接解释原因。",
        ))
        counter += 1
    for item in sorted((row for row in funnel if row.estimated_order_impact < 0), key=lambda row: row.estimated_order_impact)[:4]:
        evidence.append(AnalysisEvidence(
            evidence_id=f"E-{counter:03d}",
            claim=f"{item.stage_name}变化预计影响最终支付成功量 {item.estimated_order_impact:.1f}。",
            metric="orders",
            method="确定性顺序漏斗分解",
            result_table="funnel_decomposition",
            supporting_values={"impact": item.estimated_order_impact, "contribution_pct": item.contribution_pct, "rate_change_pp": item.rate_change_pp},
            confidence="中",
            caveat="该影响是顺序替换近似值，受分解顺序影响。",
        ))
        counter += 1
    selected_contributions = sorted((row for row in contributions if row.contribution_value < 0 and row.dimension_value != "Others"), key=lambda row: row.contribution_value)[:12]
    for item in selected_contributions:
        evidence.append(AnalysisEvidence(
            evidence_id=f"E-{counter:03d}",
            claim=f"{item.dimension}={item.dimension_value} 对 {METRIC_NAMES.get(item.metric_id, item.metric_id)} 产生负向贡献 {item.contribution_value:.2f}。",
            metric=item.metric_id,
            method="目标日与前 7 日均值维度贡献",
            result_table="dimension_contributions",
            supporting_values={"current": item.current_value, "baseline": item.baseline_value, "contribution_pct": item.contribution_pct, "sample_size": item.sample_size},
            confidence="低" if item.confidence_flag == "低样本" else "中",
            caveat="维度贡献反映相关变化，不等同于因果影响。",
        ))
        counter += 1
    return evidence


def _executive_summary(
    comparisons: list[MetricComparisonResult],
    funnel: list[FunnelStageResult],
    contributions: list[DimensionContributionResult],
) -> str:
    main = {item.metric_id: item for item in _main_comparisons(comparisons)}
    primary = next(iter(main.values()), None)
    if primary is None:
        return "本次执行已生成结构化结果，当前数据不足以形成稳定的指标对比摘要。"
    sentence = (
        f"{primary.current_period}{primary.metric_name}为 {primary.current_value:,.2f}，"
        f"较{primary.baseline_period}{primary.direction}{abs(primary.relative_change):.1%}。"
    )
    negative_funnel = sorted((item for item in funnel if item.estimated_order_impact < 0), key=lambda item: item.estimated_order_impact)[:2]
    if negative_funnel:
        sentence += " 漏斗顺序分解显示，" + "、".join(
            f"{item.stage_name}约占绝对影响的 {item.contribution_pct:.1%}" for item in negative_funnel
        ) + "。"
    city_rows = [item for item in contributions if item.metric_id == "orders" and item.dimension == "city" and item.contribution_value < 0][:3]
    if city_rows:
        sentence += " 城市维度中，" + "、".join(item.dimension_value for item in city_rows) + "位于主要负向贡献候选。"
    payment_rows = [item for item in contributions if item.metric_id == "payment_success_rate" and "app_version" in item.dimension and item.contribution_value < 0][:1]
    if payment_rows:
        device_rows = [
            item for item in contributions
            if item.metric_id == "payment_success_rate" and item.dimension == "device" and item.contribution_value < 0
        ]
        device_prefix = f"{device_rows[0].dimension_value} " if device_rows else ""
        sentence += f" {device_prefix}{payment_rows[0].dimension_value} 的支付成功率信号值得优先复核。"
    return sentence


def _tables_from_package(
    comparisons: list[MetricComparisonResult],
    anomalies: list[AnomalyResult],
    funnel: list[FunnelStageResult],
    contributions: list[DimensionContributionResult],
    evidence: list[AnalysisEvidence],
    recommendations: list[ActionRecommendation],
    quality: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    tables = {
        "metric_comparisons": records_frame(comparisons),
        "anomalies": records_frame(anomalies),
        "dimension_contributions": records_frame(contributions),
        "evidence": records_frame(evidence),
        "recommendations": records_frame(recommendations),
        "data_quality": quality,
    }
    if funnel:
        tables["funnel_decomposition"] = records_frame(funnel)
    return {name: frame for name, frame in tables.items() if not frame.empty}


def _transaction_package(state: Any, tables: dict[str, pd.DataFrame]) -> AnalysisResultPackage:
    frame = tables["daily_metrics"]
    selected = getattr(state, "column_mapping", {}).get("metric_columns", [])
    metrics = [metric for metric in (selected or ["orders", "revenue", "impressions", "conversion_rate", "cvr", "payment_success_rate", "refund_rate"]) if metric in frame.columns]
    if "conversion_rate" in metrics and "cvr" in metrics:
        metrics.remove("cvr")
    comparisons, anomalies = diagnose_metrics(frame, [metric for metric in metrics if metric != "active_users"])
    if "active_users" in metrics:
        detail = tables.get("transaction_detail", tables.get("orders", pd.DataFrame()))
        if {"date", "user_id"}.issubset(detail.columns):
            user_comparisons, user_anomalies = diagnose_metrics(detail.assign(active_users=1), ["active_users"])
            comparisons = user_comparisons + comparisons
            anomalies = user_anomalies + anomalies
        else:
            state.caveats.append("活跃用户数缺少日期/user_id明细，不能合计分组UV。")
    funnel: list[FunnelStageResult] = []
    try:
        funnel = decompose_transaction_funnel(frame)
    except ValueError:
        pass
    contributions = dimension_contribution_results(frame, "orders") if "orders" in frame.columns else []
    if "payment_success_rate" in frame.columns:
        contributions.extend(dimension_contribution_results(frame, "payment_success_rate", ["device", "app_version", "city"], include_drilldown=True))
    evidence = _evidence_from_results(comparisons, anomalies, funnel, contributions)
    recommendations = build_recommendations(comparisons, funnel, contributions, evidence)
    quality = _quality_table(state, tables)
    result_tables = _tables_from_package(comparisons, anomalies, funnel, contributions, evidence, recommendations, quality)
    return AnalysisResultPackage(
        run_id=state.trace_id,
        scenario="transaction",
        question=state.user_question,
        executive_summary=_executive_summary(comparisons, funnel, contributions),
        metric_comparisons=comparisons,
        anomalies=anomalies,
        funnel_results=funnel,
        dimension_contributions=contributions,
        evidence=evidence,
        recommendations=recommendations,
        result_tables=result_tables,
        chart_specs=list(state.chart_specs),
        caveats=[str(item) for item in state.caveats],
        metadata={"method": "deterministic_transaction_diagnosis", "primary_baseline": "previous_7d_average"},
    )


def _content_package(state: Any, tables: dict[str, pd.DataFrame]) -> AnalysisResultPackage:
    frame = tables.get("content_daily_metrics", tables.get("content_events", pd.DataFrame()))
    selected = getattr(state, "column_mapping", {}).get("metric_columns", [])
    metrics = [metric for metric in (selected or ["completion_rate", "engagement_rate", "ctr", "watch_time"]) if metric in frame.columns]
    comparisons, anomalies = diagnose_metrics(frame, metrics)
    metric = metrics[0] if metrics else ""
    dimensions = [value for value in ["content_category", "author_tier", "device", "acquisition_channel", "channel", "user_segment", "app_version"] if value in frame.columns]
    contributions = dimension_contribution_results(frame, metric, dimensions, include_drilldown=False) if metric else []
    evidence = _evidence_from_results(comparisons, anomalies, [], contributions)
    recommendations = build_recommendations(comparisons, [], contributions, evidence)
    quality = _quality_table(state, tables)
    result_tables = _tables_from_package(comparisons, anomalies, [], contributions, evidence, recommendations, quality)
    return AnalysisResultPackage(
        run_id=state.trace_id,
        scenario="content",
        question=state.user_question,
        executive_summary=_executive_summary(comparisons, [], contributions),
        metric_comparisons=comparisons,
        anomalies=anomalies,
        dimension_contributions=contributions,
        evidence=evidence,
        recommendations=recommendations,
        result_tables=result_tables,
        chart_specs=list(state.chart_specs),
        caveats=[str(item) for item in state.caveats],
        metadata={"method": "deterministic_content_diagnosis"},
    )


def _live_package(state: Any, tables: dict[str, pd.DataFrame]) -> AnalysisResultPackage:
    state.caveats.append("主播开播场次按broadcast_id，观看会话按session_id，观测去重观众按user_id；观测样本不代表完整观众覆盖。")
    source_frames: list[tuple[pd.DataFrame, list[str]]] = []
    selected = getattr(state, "column_mapping", {}).get("metric_columns", [])
    if "live_daily_metrics" in tables:
        source_frames.append((tables["live_daily_metrics"], selected or ["buffering_rate", "crash_rate", "startup_latency", "watch_time", "interaction_rate"]))
    else:
        if "live_quality_logs" in tables:
            source_frames.append((tables["live_quality_logs"], ["stutter_rate", "latency_ms"]))
        if "live_sessions" in tables:
            source_frames.append((tables["live_sessions"], ["watch_time"]))
        if "live_interactions" in tables:
            source_frames.append((tables["live_interactions"], ["interaction_rate"]))
    comparisons: list[MetricComparisonResult] = []
    anomalies: list[AnomalyResult] = []
    for frame, candidates in source_frames:
        cancellation_checkpoint()
        available = [metric for metric in candidates if metric in frame.columns]
        compared, detected = diagnose_metrics(frame, available)
        comparisons.extend(compared)
        anomalies.extend(detected)
    base = tables.get("live_daily_metrics", tables.get("live_quality_logs", pd.DataFrame()))
    metric = "buffering_rate" if "buffering_rate" in base.columns else "stutter_rate" if "stutter_rate" in base.columns else ""
    dimensions = [value for value in ["device", "network_type", "app_version", "city", "live_category", "host_tier"] if value in base.columns]
    contributions = dimension_contribution_results(base, metric, dimensions, include_drilldown=False) if metric else []
    evidence = _evidence_from_results(comparisons, anomalies, [], contributions)
    recommendations = build_recommendations(comparisons, [], contributions, evidence)
    quality = _quality_table(state, tables)
    result_tables = _tables_from_package(comparisons, anomalies, [], contributions, evidence, recommendations, quality)
    association_text = ""
    association_requested = any(term in state.user_question for term in ("关联", "相关", "关系")) or {"stutter_rate", "conversion_rate"}.issubset(selected)
    if association_requested:
        try:
            association_tables = quality_conversion_association(tables.get("live_sessions", pd.DataFrame()))
            result_tables.update(association_tables)
            row = association_tables["quality_conversion_association"].iloc[0]
            correlation = row["pearson_correlation"]
            coefficient = f"{correlation:.4f}" if pd.notna(correlation) else "不可计算（变量无波动）"
            association_text = f" 会话层级质量与转化的Pearson相关系数为 {coefficient}，有效配对 {int(row['sample_size'])} 个；属于描述性相关，不构成因果证据。"
            evidence.append(AnalysisEvidence("LIVE-ASSOC-001", association_text.strip(), "stutter_rate / conversion_rate", str(row["method"]), "quality_conversion_association", {"pearson_correlation": correlation, "sample_size": int(row["sample_size"]), "statistical_unit": "session_id"}, "描述性", str(row["limitations"])))
            recommendations.append(ActionRecommendation("中", "在设备与网络分组内复核质量和转化，并用随机实验验证改进效果。", "会话相关可能受用户组成及重复会话影响。", ("LIVE-ASSOC-001",), "分析维护方", "卡顿率与转化率", "在稳定质量条件下复核转化变化", "相关性不能说明质量变化导致转化变化。"))
            result_tables["evidence"] = records_frame(evidence)
            result_tables["recommendations"] = records_frame(recommendations)
        except ValueError as exc:
            state.caveats.append(str(exc))
    return AnalysisResultPackage(
        run_id=state.trace_id,
        scenario="live",
        question=state.user_question,
        executive_summary=_executive_summary(comparisons, [], contributions) + association_text,
        metric_comparisons=comparisons,
        anomalies=anomalies,
        dimension_contributions=contributions,
        evidence=evidence,
        recommendations=recommendations,
        result_tables=result_tables,
        chart_specs=list(state.chart_specs),
        caveats=[str(item) for item in state.caveats],
        metadata={"method": "deterministic_live_quality_diagnosis"},
    )


def _generic_package(state: Any, tables: dict[str, pd.DataFrame]) -> AnalysisResultPackage:
    existing = state.intermediate_results.get("result_tables", {})
    result_tables = {name: frame for name, frame in existing.items() if isinstance(frame, pd.DataFrame) and not frame.empty} if isinstance(existing, dict) else {}
    if not result_tables:
        result_tables["table_summary"] = pd.DataFrame([
            {"table": name, "row_count": len(frame), "column_count": len(frame.columns)}
            for name, frame in tables.items()
        ])
    evidence = [AnalysisEvidence(
        evidence_id="E-001",
        claim=f"本次执行生成 {len(result_tables)} 张结构化结果表。",
        metric="structured_results",
        method="结果表摘要",
        result_table=next(iter(result_tables)),
        supporting_values={"table_count": len(result_tables)},
        confidence="中",
        caveat="需结合所选分析剧本和字段口径解释。",
    )]
    # Attach bounded numeric evidence directly to existing computed tables.
    # The first and last result rows cover aggregate/leading and latest-window findings.
    numeric_evidence = []
    for table_name, frame in result_tables.items():
        cancellation_checkpoint()
        if frame.empty:
            continue
        numeric_columns = list(frame.select_dtypes(include="number").columns)
        if not numeric_columns:
            continue
        for position in list(dict.fromkeys([0, len(frame) - 1])):
            row = frame.iloc[position]
            supporting = {str(column): row[column].item() if hasattr(row[column], "item") else row[column] for column in numeric_columns[:12] if pd.notna(row[column])}
            if not supporting:
                continue
            supporting["row_position"] = position
            for group_key in ("row_key", "column_key"):
                if group_key in row and pd.notna(row[group_key]):
                    supporting[group_key] = str(row[group_key])
            numeric_evidence.append(AnalysisEvidence(f"RESULT-{len(numeric_evidence) + 1:03d}", f"结果表 {table_name} 第 {position + 1} 行提供可复核的实际数值。", str(state.playbook_parameters.get("metric") or next(iter(state.column_mapping.get("metric_columns", [])), table_name)), "由实际结果表直接取值；窗口及分组以该行和当前剧本参数为准", table_name, supporting, "描述性", "证据值为计算结果摘要，不能替代业务口径与统计适用性检查。"))
    evidence.extend(numeric_evidence[:30])
    recommendations = [ActionRecommendation(
        priority="低",
        action="复核结果表字段口径和当前筛选条件。",
        reason="自定义或多表分析的结论依赖当前映射与查询计划。",
        supporting_evidence_ids=("E-001",),
        suggested_owner="分析维护方",
        verification_metric="结果表行数与字段口径",
        expected_direction="结果口径与分析问题一致",
        limitation="该建议不替代对数据定义的人工复核。",
    )]
    result_tables["evidence"] = records_frame(evidence)
    result_tables["recommendations"] = records_frame(recommendations)
    result_tables["data_quality"] = _quality_table(state, tables)
    return AnalysisResultPackage(
        run_id=state.trace_id,
        scenario="custom_or_playbook",
        question=state.user_question,
        executive_summary=str(state.intermediate_results.get("summary") or "本次执行已生成结构化分析结果。"),
        evidence=evidence,
        recommendations=recommendations,
        result_tables=result_tables,
        chart_specs=list(state.chart_specs),
        caveats=[str(item) for item in state.caveats],
        metadata={"method": "playbook_or_custom_result_adapter"},
    )


def _experiment_artifact(state: Any, tables: dict[str, pd.DataFrame]) -> tuple[dict[str, Any] | None, str]:
    artifacts = state.intermediate_results.get("artifacts", {})
    values = artifacts if isinstance(artifacts, dict) else {}
    mapping = getattr(state, "column_mapping", {})
    metric_columns = mapping.get("metric_columns", []) if isinstance(mapping, dict) else []
    metric_id = str(metric_columns[0]) if metric_columns else "completion_rate"
    statistics = state.intermediate_results.get("result_tables", {}).get("experiment_statistics")
    if isinstance(statistics, pd.DataFrame) and not statistics.empty:
        return statistics.iloc[0].to_dict(), metric_id
    result = values.get("ab_test") or values.get("generic_ab_test")
    if isinstance(result, dict):
        return result, metric_id
    return None, metric_id


def _experiment_package(state: Any, tables: dict[str, pd.DataFrame]) -> AnalysisResultPackage:
    package = _generic_package(state, tables)
    values, metric_id = _experiment_artifact(state, tables)
    if not values:
        package.executive_summary = "实验分析流程已执行，但当前结果未包含可展示的组间统计量。"
        return package

    sample_size = values.get("sample_size", {})
    samples = sample_size if isinstance(sample_size, dict) else {}
    control_n = int(samples.get("control", 0) or 0)
    treatment_n = int(samples.get("treatment", 0) or 0)
    interval = values.get("confidence_interval", (0.0, 0.0))
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        interval = (0.0, 0.0)
    p_value = float(values.get("p_value", 1.0))
    conclusion = str(values.get("conclusion") or "当前实验结果需要结合样本量继续复核。")
    metric_name = METRIC_NAMES.get(metric_id, metric_id)
    experiment = ExperimentComparisonResult(
        metric_id=metric_id,
        metric_name=metric_name,
        control_group="control",
        treatment_group="treatment",
        control_value=float(values.get("control_mean", 0.0) or 0.0),
        treatment_value=float(values.get("treatment_mean", 0.0) or 0.0),
        control_sample_size=control_n,
        treatment_sample_size=treatment_n,
        total_sample_size=control_n + treatment_n,
        absolute_lift=float(values.get("absolute_lift", 0.0) or 0.0),
        relative_lift=float(values["relative_lift"]) if values.get("relative_lift") is not None else None,
        p_value=p_value,
        confidence_interval_lower=float(interval[0]),
        confidence_interval_upper=float(interval[1]),
        confidence_level=float(values.get("confidence_level", 0.95)),
        is_significant=p_value < 1 - float(values.get("confidence_level", 0.95)),
        significance_conclusion=conclusion,
        method=str(values.get("method", "Welch 两独立样本 t 检验")),
        statistical_unit=str(values.get("statistical_unit", "未确认")),
        limitations=tuple(values.get("limitations", [])),
        metric_type=str(values.get("metric_type", "mean")),
    )
    def difference_text(value):
        return f"{value * 100:.2f} 个百分点" if _is_rate_metric(metric_id) else f"{value:,.4g}"
    interval_text = f"[{difference_text(experiment.confidence_interval_lower)}, {difference_text(experiment.confidence_interval_upper)}]"
    relative_text = f"{experiment.relative_lift:.2%}" if experiment.relative_lift is not None else "不可计算（对照均值为零）"
    significance = "达到统计显著" if experiment.is_significant else "未达到统计显著"
    package.executive_summary = (
        f"{metric_name}实验结果：实验组 {_format_experiment_value(metric_id, experiment.treatment_value)}"
        f"（样本量 n={treatment_n:,}），对照组 {_format_experiment_value(metric_id, experiment.control_value)}"
        f"（样本量 n={control_n:,}），绝对 lift {difference_text(experiment.absolute_lift)}，"
        f"相对 lift {relative_text}；p-value={experiment.p_value:.6g}，"
        f"{experiment.confidence_level:.0%} 绝对差置信区间 {interval_text}，{significance}。"
    )
    experiment_evidence = AnalysisEvidence(
        evidence_id="EXP-001",
        claim=f"{metric_name}实验检验{significance}：p-value={experiment.p_value:.6g}，{experiment.confidence_level:.0%} 绝对差置信区间 {interval_text}。",
        metric=metric_id,
        method=experiment.method,
        result_table="experiment_comparison",
        supporting_values={
            "control_value": experiment.control_value,
            "treatment_value": experiment.treatment_value,
            "control_sample_size": control_n,
            "treatment_sample_size": treatment_n,
            "absolute_lift": experiment.absolute_lift,
            "relative_lift": experiment.relative_lift,
            "p_value": experiment.p_value,
            "confidence_interval": [experiment.confidence_interval_lower, experiment.confidence_interval_upper],
        },
        confidence="高" if experiment.is_significant else "中",
        caveat="统计显著性不等于业务重要性，且实验结果不应外推到未覆盖群体。",
    )
    experiment_recommendation = ActionRecommendation(
        priority="中",
        action="结合实验样本覆盖和长期稳定性复核当前策略，再决定是否扩大使用范围。",
        reason=conclusion,
        supporting_evidence_ids=(experiment_evidence.evidence_id,),
        suggested_owner="分析维护方",
        verification_metric=metric_name,
        expected_direction="实验组效果在后续观察窗口保持稳定",
        limitation="统计显著性不替代业务影响与样本代表性判断。",
    )
    package.scenario = "experiment"
    package.experiment_results = [experiment]
    package.evidence = [experiment_evidence, *package.evidence]
    package.recommendations = [experiment_recommendation, *package.recommendations]
    package.result_tables["experiment_comparison"] = records_frame([experiment])
    package.result_tables["evidence"] = records_frame(package.evidence)
    package.result_tables["recommendations"] = records_frame(package.recommendations)
    package.caveats.extend(experiment.limitations)
    package.metadata = {**package.metadata, "experiment_method": experiment.method}
    return package



def _causal_result_summary(package: AnalysisResultPackage) -> str:
    """Describe existing estimates only; no fitting or source-data scan here."""
    frame = package.result_tables.get("adjusted_effect_summary")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return package.executive_summary
    values = frame.iloc[0]

    def finite_value(name: str) -> float | None:
        try:
            value = float(values.get(name))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    naive, adjusted = finite_value("naive_difference"), finite_value("adjusted_effect")
    sample_size = finite_value("sample_size")
    if naive is None:
        return package.executive_summary
    parts = [f"轻量因果探索：两组原始均值差（处理组−对照组）={naive:.4f}"]
    parts.append(f"回归调整估计={adjusted:.4f}" if adjusted is not None else "未生成回归调整估计，仅展示未经调整的差异")
    if sample_size is not None and sample_size >= 0:
        parts.append(f"有效样本量 n={sample_size:,.0f}")
    return "；".join(parts) + "。估计值采用结果变量原量纲。此结果不是因果证明；随机化、无未观测混杂、重叠性和时序前提尚未验证。"


def build_analysis_result_package(state: Any, tables: dict[str, pd.DataFrame]) -> AnalysisResultPackage:
    goal_mode = str(getattr(state, "goal_mode", ""))
    if getattr(state, "selected_playbook_id", None) == "experiment_comparison" or not getattr(state, "selected_playbook_id", None) and goal_mode == "experiment_analysis":
        package = _experiment_package(state, tables)
    elif getattr(state, "selected_playbook_id", None):
        package = _generic_package(state, tables)
    elif goal_mode == "causal_exploration":
        artifacts = state.intermediate_results.get("artifacts", {})
        effect = artifacts.get("causal_light") or artifacts.get("generic_causal_light")
        if effect:
            state.intermediate_results["result_tables"] = {"adjusted_effect_summary": pd.DataFrame([{key: value for key, value in effect.items() if key != "caveats"}])}
        package = _generic_package(state, tables)
    elif goal_mode == "content_performance" and ("content_daily_metrics" in tables or "content_events" in tables):
        package = _content_package(state, tables)
    elif goal_mode == "live_quality" and ("live_daily_metrics" in tables or "live_quality_logs" in tables):
        package = _live_package(state, tables)
    elif not getattr(state, "user_table_mode", False) and "daily_metrics" in tables:
        package = _transaction_package(state, tables)
    else:
        package = _generic_package(state, tables)
    existing = state.intermediate_results.get("result_tables", {})
    if isinstance(existing, dict):
        package.result_tables = {**existing, **package.result_tables}
    exploration = state.intermediate_results.get("playbook_result", {}).get("metadata", {}).get("exploration")
    if exploration and getattr(state, "planning_status", "ready") == "ready":
        package.metadata["exploration"] = exploration
        if state.findings:
            package.executive_summary = str(state.findings[0])
    selected = getattr(state, "selected_playbook_id", None)
    if selected == "causal_exploration" or not selected and goal_mode == "causal_exploration":
        package.executive_summary = _causal_result_summary(package)
    return package


def _claim_signatures(text: str) -> set[tuple[str, str, str, float]]:
    signatures: set[tuple[str, str, str, float]] = set()
    for segment in re.split(r"[。；;\n]", str(text)):
        compact = re.sub(r"\s+", "", segment).lower()
        if not compact:
            continue
        metrics = [
            metric_id
            for metric_id, metric_name in METRIC_NAMES.items()
            if metric_id.lower() in compact or str(metric_name).lower() in compact
        ]
        baseline = ""
        for key, markers in {
            "previous_7d": ("前7日", "前七日"),
            "previous_28d": ("前28日", "前二十八日"),
            "previous_weekday": ("上周同日",),
            "control": ("对照组", "control"),
        }.items():
            if any(marker in compact for marker in markers):
                baseline = key
                break
        percentages = [round(float(value), 1) for value in re.findall(r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*%", segment)]
        if "下降" in compact or "降低" in compact or ("lift" in compact and any(value < 0 for value in percentages)):
            direction = "decrease"
        elif "上升" in compact or "提升" in compact or "lift" in compact:
            direction = "increase"
        elif "持平" in compact:
            direction = "flat"
        else:
            direction = "change"
        if metrics and baseline and percentages:
            signatures.update((metric, baseline, direction, value) for metric in metrics for value in percentages)
    return signatures


def _experiment_topics(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", str(text)).lower()
    topics: set[str] = set()
    if "实验组" in normalized and "对照组" in normalized:
        topics.add("group_comparison")
    if ("样本量" in normalized or "n=" in normalized) and ("实验组" in normalized or "对照组" in normalized):
        topics.add("sample_size")
    if re.search(r"p[-_]?value", normalized) or "置信区间" in normalized or "confidence_interval" in normalized:
        topics.add("statistical_inference")
    if "统计显著" in normalized:
        topics.add("significance")
    return topics


def deduplicate_findings(executive_summary: str, findings: list[str]) -> list[str]:
    """Remove exact and structured metric/baseline/change repetitions."""

    seen_text = {re.sub(r"\s+", "", str(executive_summary)).strip("。；; ")}
    seen_signatures = _claim_signatures(executive_summary)
    seen_experiment_topics = _experiment_topics(executive_summary)
    unique: list[str] = []
    for value in findings:
        text = str(value).strip()
        normalized = re.sub(r"\s+", "", text).strip("。；; ")
        if not normalized or normalized in seen_text:
            continue
        signatures = _claim_signatures(text)
        if signatures and signatures.intersection(seen_signatures):
            continue
        experiment_topics = _experiment_topics(text)
        if experiment_topics and experiment_topics.issubset(seen_experiment_topics):
            continue
        unique.append(text)
        seen_text.add(normalized)
        seen_signatures.update(signatures)
        seen_experiment_topics.update(experiment_topics)
    return unique


def findings_from_package(package: AnalysisResultPackage) -> list[str]:
    findings = [item.claim for item in package.evidence[:3]]
    findings.append("所有结论均来自结构化结果与确定性计算；相关性不直接代表因果关系。")
    return deduplicate_findings(package.executive_summary, findings)


__all__ = ["build_analysis_result_package", "deduplicate_findings", "findings_from_package"]
