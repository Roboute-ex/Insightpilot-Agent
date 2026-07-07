"""Deterministic rule-based analysis planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from insightpilot.metrics.resolver import resolve_metrics_from_question
from insightpilot.planning.goal_modes import (
    get_goal_mode_display_name,
    infer_goal_mode_from_intent,
    infer_intent_from_goal_mode,
    normalize_goal_mode,
)


@dataclass(frozen=True)
class AnalysisPlan:
    intent: str
    goal_mode: str
    goal_mode_display_name: str
    goal_mode_source: str
    related_metrics: list[str]
    comparison_method: str
    dimensions: list[str]
    required_tables: list[str]
    analysis_steps: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _detect_intent(question: str) -> str:
    q = question.lower()
    if any(term in q for term in ("因果", "causal", "影响是否", "是否影响")):
        return "causal_exploration"
    if any(term in q for term in ("实验", "a/b", "ab", "策略", "treatment", "control")):
        return "experiment_analysis"
    if any(term in q for term in ("直播", "卡顿", "stutter", "停留", "体验")):
        return "live_quality_analysis"
    if any(term in q for term in ("内容", "完播", "推荐", "消费", "content")):
        return "content_performance_analysis"
    if any(term in q for term in ("下降", "下滑", "降低", "减少", "drop", "decline", "异常")):
        return "metric_drop_diagnosis"
    if any(term in q for term in ("增长", "提升", "上升", "increase", "growth")):
        return "metric_growth_analysis"
    return "general_summary"


def _plan_parts(intent: str) -> tuple[str, list[str], list[str], list[str]]:
    if intent == "experiment_analysis":
        return (
            "experiment_control_vs_treatment",
            ["user_segment", "city", "channel"],
            ["experiments", "content_events", "users"],
            [
                "识别实验指标和分组字段。",
                "计算对照组与实验组均值或比例。",
                "执行显著性检验并输出 p-value 与区间估计。",
                "检查样本量并给出谨慎结论。",
            ],
        )
    if intent == "live_quality_analysis":
        return (
            "current_day_vs_previous_7d_average",
            ["device", "network_type", "city", "hour_bucket"],
            ["live_sessions", "live_quality_logs", "live_interactions"],
            [
                "检测卡顿率、观看时长和互动率变化。",
                "按设备、网络类型、地区和时段做贡献度排序。",
                "结合体验指标生成风险提示。",
                "保留 synthetic data 与相关性限制说明。",
            ],
        )
    if intent == "content_performance_analysis":
        return (
            "recent_period_profile",
            ["content_category", "device", "user_segment"],
            ["content_items", "content_events", "experiments"],
            [
                "汇总内容类型的消费表现。",
                "比较完播率、观看时长和留存相关指标。",
                "识别表现差异较大的内容分层。",
                "给出继续观察和优化建议。",
            ],
        )
    if intent == "metric_growth_analysis":
        return (
            "current_period_vs_previous_period",
            ["city", "channel", "user_segment", "device"],
            ["daily_metrics"],
            [
                "计算目标指标当前周期与上一周期差异。",
                "按核心维度拆解增长来源。",
                "检查是否存在结构性变化。",
                "输出可复核的下一步分析建议。",
            ],
        )
    if intent == "metric_drop_diagnosis":
        return (
            "yesterday_vs_previous_7d_average",
            ["city", "channel", "user_segment", "device", "merchant_type"],
            ["daily_metrics", "traffic_events", "orders"],
            [
                "检测目标日期相对前 7 日均值的异常程度。",
                "拆解曝光、点击率、转化率和支付成功率变化。",
                "按城市、渠道、用户分层、设备和商户类型排序贡献度。",
                "生成可执行建议并标注限制说明。",
            ],
        )
    if intent == "causal_exploration":
        return (
            "exploratory_adjusted_effect",
            ["city", "channel", "user_segment"],
            ["experiments", "users"],
            [
                "识别 treatment、outcome 和可用控制变量。",
                "计算 naive difference 与 regression adjustment。",
                "补充简化 propensity score weighting 结果。",
                "明确该模式仅用于探索，不能把相关性直接解释为因果关系。",
            ],
        )
    return (
        "descriptive_summary",
        ["city", "channel", "user_segment"],
        ["daily_metrics"],
        [
            "识别问题中的指标口径。",
            "生成基础描述性汇总。",
            "列出建议优先查看的维度。",
            "保留不确定性与 synthetic data 限制说明。",
        ],
    )


def create_analysis_plan(question: str, goal_mode: str = "auto") -> AnalysisPlan:
    """Create a stable structured analysis plan from a natural-language question."""

    normalized_goal_mode = normalize_goal_mode(goal_mode)
    if normalized_goal_mode == "auto":
        intent = _detect_intent(question)
        resolved_goal_mode = infer_goal_mode_from_intent(intent)
        goal_mode_source = "auto_detected"
    else:
        intent = infer_intent_from_goal_mode(normalized_goal_mode)
        resolved_goal_mode = normalized_goal_mode
        goal_mode_source = "user_selected"

    metrics = [metric.metric_name for metric in resolve_metrics_from_question(question)]
    comparison_method, dimensions, required_tables, steps = _plan_parts(intent)
    return AnalysisPlan(
        intent=intent,
        goal_mode=resolved_goal_mode,
        goal_mode_display_name=get_goal_mode_display_name(resolved_goal_mode),
        goal_mode_source=goal_mode_source,
        related_metrics=metrics,
        comparison_method=comparison_method,
        dimensions=dimensions,
        required_tables=required_tables,
        analysis_steps=steps,
    )
