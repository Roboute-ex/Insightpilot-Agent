"""Analysis goal mode definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoalMode:
    value: str
    display_name: str
    intent: str


GOAL_MODE_OPTIONS: list[GoalMode] = [
    GoalMode("auto", "自动识别", "auto"),
    GoalMode("metric_diagnosis", "指标波动诊断", "metric_drop_diagnosis"),
    GoalMode("growth_trend", "增长/趋势分析", "metric_growth_analysis"),
    GoalMode("experiment_analysis", "A/B 实验评估", "experiment_analysis"),
    GoalMode("content_performance", "内容表现分析", "content_performance_analysis"),
    GoalMode("live_quality", "体验质量分析", "live_quality_analysis"),
    GoalMode("causal_exploration", "轻量因果探索", "causal_exploration"),
    GoalMode("periodic_report", "周期性分析报告", "general_summary"),
]

GOAL_MODE_DISPLAY_NAMES: dict[str, str] = {mode.value: mode.display_name for mode in GOAL_MODE_OPTIONS}
GOAL_MODE_TO_INTENT: dict[str, str] = {mode.value: mode.intent for mode in GOAL_MODE_OPTIONS}
INTENT_TO_GOAL_MODE: dict[str, str] = {
    "metric_drop_diagnosis": "metric_diagnosis",
    "metric_growth_analysis": "growth_trend",
    "experiment_analysis": "experiment_analysis",
    "content_performance_analysis": "content_performance",
    "live_quality_analysis": "live_quality",
    "causal_exploration": "causal_exploration",
    "general_summary": "periodic_report",
}


def normalize_goal_mode(goal_mode: str) -> str:
    """Return a supported goal mode, falling back to auto for unknown values."""

    normalized = (goal_mode or "auto").strip()
    return normalized if normalized in GOAL_MODE_DISPLAY_NAMES else "auto"


def infer_intent_from_goal_mode(goal_mode: str) -> str:
    """Map a goal mode to the intent used by the planner and workflow."""

    normalized = normalize_goal_mode(goal_mode)
    return GOAL_MODE_TO_INTENT.get(normalized, "auto")


def infer_goal_mode_from_intent(intent: str) -> str:
    """Map an automatically detected intent back to a goal mode."""

    return INTENT_TO_GOAL_MODE.get(intent, "periodic_report")


def get_goal_mode_display_name(goal_mode: str) -> str:
    """Return the Chinese display name for a goal mode."""

    return GOAL_MODE_DISPLAY_NAMES[normalize_goal_mode(goal_mode)]
