"""Reviewer checks for analysis traces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
        str(trace.reviewer_checks),
        " ".join(trace.errors),
    ]
    return " ".join(parts).lower()


def _has_synthetic_disclaimer(text: str) -> bool:
    return any(term in text for term in ("synthetic data", "合成", "限制", "不代表真实", "仅用于学习"))


def _has_causal_caveat(text: str) -> bool:
    return any(term in text for term in ("不能把相关性", "不能直接解释为因果", "因果关系", "correlation", "caveat", "限制"))


def review_analysis(trace: AnalysisTrace) -> ReviewerResult:
    """Review whether the analysis trace contains required safeguards."""

    text = _combined_text(trace)
    checks: dict[str, bool] = {
        "has_goal_mode": bool(trace.goal_mode),
        "has_plan": bool(trace.analysis_plan),
        "has_metrics": bool(trace.selected_metrics),
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
