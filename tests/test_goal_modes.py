from __future__ import annotations

from insightpilot.planning.goal_modes import (
    get_goal_mode_display_name,
    infer_intent_from_goal_mode,
    normalize_goal_mode,
)


def test_normalize_goal_mode_keeps_known_value() -> None:
    assert normalize_goal_mode("metric_diagnosis") == "metric_diagnosis"


def test_normalize_goal_mode_unknown_falls_back_to_auto() -> None:
    assert normalize_goal_mode("unknown") == "auto"


def test_infer_intent_from_goal_mode() -> None:
    assert infer_intent_from_goal_mode("experiment_analysis") == "experiment_analysis"


def test_get_goal_mode_display_name_returns_chinese_name() -> None:
    assert get_goal_mode_display_name("live_quality") == "体验质量分析"
