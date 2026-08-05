"""Reviewer checks for analysis traces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from insightpilot.agents.trace import AnalysisTrace


@dataclass(frozen=True)
class ReviewerResult:
    status: str
    score: int
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ReviewResult = ReviewerResult


def _combined_text(trace: AnalysisTrace) -> str:
    parts = [
        trace.user_question,
        trace.identified_intent,
        trace.goal_mode,
        trace.data_source_type,
        " ".join(trace.selected_metrics),
        " ".join(trace.generated_findings),
        " ".join(trace.caveats),
        str(trace.analysis_plan),
        str(trace.table_metadata_summary),
        " ".join(trace.schema_warnings),
        str(trace.column_mapping),
        " ".join(trace.mapping_warnings),
        trace.mapping_source,
        str(trace.selected_playbook_id),
        trace.playbook_source,
        str(trace.playbook_parameters_summary),
        str(trace.chart_specs),
        str(trace.manifest_summary),
        str(trace.playbook_result_summary),
        str(trace.semantic_model_summary),
        str(trace.metric_request),
        str(trace.join_plan_summary),
        str(trace.query_plan_summary),
        str(trace.plan_review),
        str(trace.contract_summary),
        str(trace.lineage_summary),
        str(trace.observability_summary),
        str(trace.evaluation_summary),
        str(trace.analysis_result_summary),
        str(trace.reviewer_checks),
        " ".join(trace.errors),
    ]
    return " ".join(parts).lower()


def _has_synthetic_disclaimer(text: str) -> bool:
    return any(term in text for term in ("synthetic data", "合成", "模拟数据", "限制", "不代表真实", "仅用于学习"))


def _has_causal_caveat(text: str) -> bool:
    return any(term in text for term in ("不能把相关性", "不能直接解释为因果", "因果关系", "correlation", "caveat", "限制"))


def review_analysis(trace: AnalysisTrace) -> ReviewerResult:
    """Review whether the analysis trace contains required safeguards."""

    text = _combined_text(trace)
    playbook_selected = bool(trace.selected_playbook_id)
    playbook_result = trace.playbook_result_summary if isinstance(trace.playbook_result_summary, dict) else {}
    playbook_metadata = playbook_result.get("metadata", {}) if isinstance(playbook_result.get("metadata"), dict) else {}
    result_table_summaries = playbook_result.get("result_tables", {}) if isinstance(playbook_result.get("result_tables"), dict) else {}
    semantic_selected = trace.selected_playbook_id == "semantic_metric_query"
    plan_execution_mode = str(trace.metric_request.get("execution_mode", "execute"))
    review_decision = str(trace.plan_review.get("decision", ""))
    unsafe_sql_pattern = re.compile(r"\b(drop|delete|insert|update|alter|create|truncate|merge|replace|attach|copy)\b", re.IGNORECASE)
    credential_pattern = re.compile(r"://[^:/@\s]+:[^*@/\s]+@")
    checks: dict[str, bool] = {
        "has_goal_mode": bool(trace.goal_mode),
        "has_plan": bool(trace.analysis_plan),
        "has_metrics": bool(trace.selected_metrics) or trace.selected_playbook_id in {"data_profile", "periodic_summary"},
        "has_findings": bool(trace.generated_findings),
        "has_route_taken": bool(trace.route_taken),
        "has_caveats": bool(trace.caveats) or _has_synthetic_disclaimer(text),
        "has_reviewer_context": bool(trace.goal_mode and trace.identified_intent),
        "experiment_has_p_value_when_needed": True,
        "causal_has_caveat_when_needed": True,
        "errors_are_reported": isinstance(trace.errors, list),
        "no_overclaimed_causality": True,
        "synthetic_data_disclaimer_present": trace.data_source_type != "synthetic" or _has_synthetic_disclaimer(text),
        "has_data_source": bool(trace.data_source_type),
        "has_table_metadata": trace.data_source_type == "synthetic" or bool(trace.table_metadata_summary),
        "has_schema_validation": trace.data_source_type == "synthetic" or bool(trace.schema_warnings or trace.table_metadata_summary),
        "custom_data_limitations_reported": trace.data_source_type == "synthetic" or any(
            term in text for term in ("自定义数据", "上传", "database", "数据库", "schema", "字段", "仅基于当前表")
        ),
        "unsafe_query_blocked": True,
        "has_column_mapping_for_custom_data": trace.data_source_type == "synthetic" or bool(trace.column_mapping),
        "mapping_warnings_reported": True,
        "manual_mapping_respected": trace.mapping_source != "user_selected" or bool(trace.column_mapping),
        "custom_data_has_metric_selection": trace.data_source_type == "synthetic"
        or trace.goal_mode not in {"metric_diagnosis", "growth_trend", "experiment_analysis"}
        or bool(trace.column_mapping.get("metric_columns")),
        "custom_data_has_date_selection_when_trend": trace.data_source_type == "synthetic"
        or trace.goal_mode not in {"metric_diagnosis", "growth_trend"}
        or bool(trace.column_mapping.get("date_column")),
        "has_playbook_when_selected": not playbook_selected or bool(playbook_result),
        "playbook_requirements_satisfied": not playbook_selected or bool(playbook_metadata.get("requirements_satisfied")),
        "playbook_parameters_valid": not playbook_selected or bool(playbook_metadata.get("parameters_valid")),
        "safe_query_generated": not playbook_selected or (
            bool(playbook_metadata.get("safe_query_generated"))
            and all(not unsafe_sql_pattern.search(str(record.get("query", ""))) for record in trace.executed_queries if isinstance(record, dict))
        ),
        "chart_specs_valid": not playbook_selected or (
            bool(trace.chart_specs)
            and all(
                isinstance(spec, dict) and bool(spec.get("chart_id")) and bool(spec.get("chart_type")) and bool(spec.get("table_key"))
                for spec in trace.chart_specs
            )
        ),
        "manifest_generated": not playbook_selected or bool(trace.manifest_summary.get("run_id")),
        "mapping_matches_playbook": not playbook_selected or bool(playbook_metadata.get("requirements_satisfied")),
        "result_tables_available": not playbook_selected or bool(result_table_summaries),
        "export_contains_no_raw_credentials": not credential_pattern.search(text),
        "export_limitations_reported": not playbook_selected or any(
            term in text for term in ("不代表真实", "内存", "限制", "caveat", "不包含", "原始数据")
        ),
        "semantic_plan_valid": not semantic_selected or bool(
            trace.semantic_model_summary.get("model_id")
            and trace.query_plan_summary.get("plan_id")
            and trace.join_plan_summary.get("plan_id")
        ),
        "join_risk_reviewed": not semantic_selected
        or not trace.query_plan_summary.get("requires_approval")
        or review_decision == "approved"
        or (plan_execution_mode == "plan_only" and review_decision == "pending"),
        "contract_checks_available": not semantic_selected or bool(trace.contract_summary.get("check_count")),
        "lineage_generated": not semantic_selected or bool(trace.lineage_summary.get("lineage_fingerprint")),
        "observability_generated": not semantic_selected or bool(trace.observability_summary.get("span_count")),
    }
    if trace.mapping_warnings and "mapping" not in text and "字段" not in text:
        checks["mapping_warnings_reported"] = False

    is_experiment = trace.goal_mode == "experiment_analysis" or trace.identified_intent == "experiment_analysis"
    if is_experiment:
        checks["experiment_has_p_value_when_needed"] = (
            "p_value" in text and ("sample_size" in text or "样本" in text or "sample" in text)
        )

    is_causal = trace.goal_mode == "causal_exploration" or trace.identified_intent == "causal_exploration"
    if is_causal:
        checks["causal_has_caveat_when_needed"] = _has_causal_caveat(text)

    overclaimed_terms = ("证明因果", "确定因果", "直接导致", "caused by")
    if any(term in text for term in overclaimed_terms) and not _has_causal_caveat(text):
        checks["no_overclaimed_causality"] = False

    issues: list[str] = []
    suggestions: list[str] = []
    severe_failures: list[str] = []

    issue_messages = {
        "has_goal_mode": ("缺少 goal_mode。", "在 plan、trace、report 中保留分析目标模式。"),
        "has_plan": ("缺少分析计划。", "先生成结构化 AnalysisPlan 再执行分析。"),
        "has_metrics": ("未识别到指标口径。", "补充指标解析规则或请用户明确目标指标。"),
        "has_findings": ("缺少核心发现。", "至少输出指标变化、归因、实验或描述性发现。"),
        "has_route_taken": ("缺少 route_taken。", "记录 workflow 节点执行路径，便于复核。"),
        "has_caveats": ("缺少限制说明。", "明确 synthetic data、相关性和不确定性边界。"),
        "has_reviewer_context": ("Reviewer 缺少目标模式或意图上下文。", "把 goal_mode 和 intent 写入 trace。"),
        "experiment_has_p_value_when_needed": (
            "实验分析缺少 p_value 或 sample_size。",
            "补充显著性和样本量说明，避免放大 synthetic 结果。",
        ),
        "causal_has_caveat_when_needed": (
            "轻量因果探索缺少因果解释边界。",
            "说明该模式仅用于探索，不能把相关性直接解释为因果关系。",
        ),
        "errors_are_reported": ("错误未以列表形式记录。", "把可控异常写入 trace.errors。"),
        "no_overclaimed_causality": ("发现过度因果表述。", "改为相关性或探索性表述，并补充限制说明。"),
        "synthetic_data_disclaimer_present": (
            "缺少 synthetic data 声明。",
            "说明所有 demo 和结论均基于 synthetic data，不代表真实业务结论。",
        ),
        "has_data_source": ("缺少 data_source_type。", "把数据来源写入 trace 和 report。"),
        "has_table_metadata": ("缺少表结构 metadata。", "对上传文件或数据库查询结果记录表结构摘要。"),
        "has_schema_validation": ("缺少 schema validation 结果。", "记录 schema warnings 或字段映射建议。"),
        "custom_data_limitations_reported": (
            "自定义数据缺少限制说明。",
            "说明当前结果仅基于用户提供表结构，必要时需要指定日期、指标或维度字段。",
        ),
        "unsafe_query_blocked": ("SQL 安全检查上下文缺失。", "数据库模式下保留只读 SQL 安全边界说明。"),
        "has_column_mapping_for_custom_data": (
            "自定义数据缺少 Column Mapping。",
            "请选择日期列、至少一个指标列，或保留自动字段映射建议。",
        ),
        "mapping_warnings_reported": (
            "字段映射 warning 未进入 trace/report 上下文。",
            "把 mapping_warnings 写入 reviewer、trace 和 report。",
        ),
        "manual_mapping_respected": ("手动字段映射未被保留。", "用户选择的 Column Mapping 必须优先于自动推断。"),
        "custom_data_has_metric_selection": (
            "自定义数据缺少指标列选择。",
            "请选择至少一个数值指标列，或补充字段映射。",
        ),
        "custom_data_has_date_selection_when_trend": (
            "趋势/诊断模式缺少日期列选择。",
            "请选择日期列和至少一个指标列以启用趋势或异常检测。",
        ),
        "has_playbook_when_selected": (
            "已选择 playbook，但 trace 中缺少执行结果。",
            "确认 selected_playbook_id 已传入统一 executor 并写入 trace。",
        ),
        "playbook_requirements_satisfied": (
            "当前 Column Mapping 不满足 playbook requirements。",
            "根据剧本补充所需日期列、指标列、维度列、分组列或处理/结果列。",
        ),
        "playbook_parameters_valid": (
            "playbook 参数校验未通过。",
            "复核日期范围、Top N、滚动窗口、置信水平和字段参数。",
        ),
        "safe_query_generated": (
            "playbook 未生成可复核的安全查询或查询安全检查失败。",
            "仅使用 allowlist identifier 与绑定参数重新生成只读 SQL template。",
        ),
        "chart_specs_valid": (
            "ChartSpec 缺少必要字段。",
            "为每张图补充 chart_id、chart_type 和结果表 table_key。",
        ),
        "manifest_generated": (
            "playbook 运行缺少 RunManifest。",
            "生成不含原始数据和凭据的 manifest 配置摘要。",
        ),
        "mapping_matches_playbook": (
            "Column Mapping 与所选 playbook 不匹配。",
            "按剧本要求补充具体字段角色后重新执行。",
        ),
        "result_tables_available": (
            "playbook 未生成结果表。",
            "复核映射与参数，确保至少生成一张结构化分析结果表。",
        ),
        "export_contains_no_raw_credentials": (
            "运行上下文可能包含未遮罩凭据。",
            "移除完整 database URL，并对密码、token 和 secret 做遮罩。",
        ),
        "export_limitations_reported": (
            "缺少导出与复现边界说明。",
            "说明导出不含原始数据或凭据，manifest 仅用于复现配置。",
        ),
        "semantic_plan_valid": (
            "语义查询缺少完整的模型、连接或查询计划。",
            "重新加载语义模型并生成稳定 JoinPlan 与 QueryPlan。",
        ),
        "join_risk_reviewed": (
            "高风险 Join 尚未获得与当前计划编号匹配的审批。",
            "复核 fanout 与输出粒度后，明确批准当前只读查询计划。",
        ),
        "contract_checks_available": (
            "语义查询缺少数据契约检查。",
            "在执行前检查主键、必填字段、行数与指标范围。",
        ),
        "lineage_generated": (
            "语义查询缺少数据血缘。",
            "记录输入表、查询操作与输出结果之间的派生关系。",
        ),
        "observability_generated": (
            "语义查询缺少本地运行摘要。",
            "记录本地 span、查询次数、警告与错误数量。",
        ),
    }

    for check_name, passed in checks.items():
        if not passed:
            issue, suggestion = issue_messages[check_name]
            issues.append(issue)
            suggestions.append(suggestion)

    if not checks["has_plan"]:
        severe_failures.append("missing_plan")
    if not checks["has_findings"]:
        severe_failures.append("missing_findings")
    if playbook_selected and not checks["safe_query_generated"]:
        severe_failures.append("unsafe_playbook_query")
    if any("missing table" in error.lower() or "critical" in error.lower() for error in trace.errors):
        severe_failures.append("critical_error")
    if trace.errors:
        issues.append("workflow 记录了运行错误。")
        suggestions.append("复核 errors 字段并确认是否需要补充 fallback 或数据表。")

    score = 100
    penalties = {
        "has_goal_mode": 10,
        "has_plan": 30,
        "has_metrics": 12,
        "has_findings": 35,
        "has_route_taken": 10,
        "has_caveats": 25,
        "has_reviewer_context": 10,
        "experiment_has_p_value_when_needed": 25,
        "causal_has_caveat_when_needed": 25,
        "errors_are_reported": 15,
        "no_overclaimed_causality": 25,
        "synthetic_data_disclaimer_present": 20,
        "has_data_source": 8,
        "has_table_metadata": 12,
        "has_schema_validation": 10,
        "custom_data_limitations_reported": 12,
        "unsafe_query_blocked": 20,
        "has_column_mapping_for_custom_data": 12,
        "mapping_warnings_reported": 8,
        "manual_mapping_respected": 20,
        "custom_data_has_metric_selection": 15,
        "custom_data_has_date_selection_when_trend": 10,
        "has_playbook_when_selected": 20,
        "playbook_requirements_satisfied": 20,
        "playbook_parameters_valid": 20,
        "safe_query_generated": 35,
        "chart_specs_valid": 10,
        "manifest_generated": 12,
        "mapping_matches_playbook": 15,
        "result_tables_available": 20,
        "export_contains_no_raw_credentials": 35,
        "export_limitations_reported": 8,
        "semantic_plan_valid": 30,
        "join_risk_reviewed": 35,
        "contract_checks_available": 12,
        "lineage_generated": 12,
        "observability_generated": 8,
    }
    for check_name, passed in checks.items():
        if not passed:
            score -= penalties[check_name]
    if trace.errors:
        score -= 20 if severe_failures else 12
    score = max(0, min(100, score))

    if severe_failures or score < 50:
        status = "FAIL"
        score = min(score, 49)
    elif issues or score < 80:
        status = "WARN"
        score = min(score, 79)
    else:
        status = "PASS"

    return ReviewerResult(status=status, score=score, checks=checks, issues=issues, suggestions=suggestions)
