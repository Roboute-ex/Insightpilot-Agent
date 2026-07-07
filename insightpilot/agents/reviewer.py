"""Reviewer checks for analysis traces."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from insightpilot.agents.trace import AnalysisTrace


@dataclass(frozen=True)
class ReviewResult:
    status: str
    issues: list[str]
    suggestions: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def review_analysis(trace: AnalysisTrace) -> ReviewResult:
    """Review whether the analysis trace contains required safeguards."""

    issues: list[str] = []
    suggestions: list[str] = []
    fail_reasons: list[str] = []

    if not trace.selected_metrics:
        issues.append("未识别到指标口径。")
        suggestions.append("补充指标解析规则或请用户明确目标指标。")
    if not trace.analysis_plan:
        issues.append("缺少分析计划。")
        suggestions.append("生成结构化 AnalysisPlan 后再执行分析。")
    if not trace.executed_queries:
        issues.append("缺少已执行查询记录。")
        suggestions.append("记录 SQL 或 pandas 查询步骤，方便复核。")
    if not trace.generated_findings:
        issues.append("缺少核心发现。")
        suggestions.append("至少输出指标变化、归因或实验结论。")
        fail_reasons.append("missing_findings")

    if not trace.goal_mode:
        issues.append("缺少 goal_mode。")
        suggestions.append("在 plan、trace 和 report 中保留分析目标模式。")
    elif trace.goal_mode_source == "user_selected" and trace.goal_mode not in str(trace.analysis_plan):
        issues.append("用户选择的 goal_mode 未在分析计划中保留。")
        suggestions.append("将用户选择的目标模式写入 AnalysisPlan。")
    elif trace.goal_mode_source == "auto_detected" and not trace.goal_mode_display_name:
        issues.append("自动识别的 goal_mode 缺少展示名。")
        suggestions.append("补充 goal_mode_display_name 以便报告解释来源。")

    joined_findings = " ".join(trace.generated_findings).lower()
    has_limitation = any(term in joined_findings for term in ("caution", "caveat", "限制", "不确定", "synthetic"))
    if not has_limitation:
        issues.append("缺少 caution/caveat/限制说明。")
        suggestions.append("在报告中明确 synthetic data 与相关性限制。")

    if trace.goal_mode == "causal_exploration" and not any(
        term in joined_findings for term in ("因果", "相关性", "caveat", "限制")
    ):
        issues.append("轻量因果探索缺少因果解释边界。")
        suggestions.append("说明该模式仅用于探索，不能把相关性直接解释为因果关系。")

    if trace.goal_mode == "experiment_analysis" and not any(
        term in joined_findings for term in ("sample", "样本", "p_value", "显著")
    ):
        issues.append("实验评估缺少样本量或显著性解释。")
        suggestions.append("补充 sample size、p_value 或显著性相关说明。")

    if fail_reasons:
        status = "FAIL"
    elif issues:
        status = "WARN"
    else:
        status = "PASS"
    return ReviewResult(status=status, issues=issues, suggestions=suggestions)
