from __future__ import annotations

from insightpilot.ui.formatters import (
    BACKEND_DISPLAY_NAMES,
    GOAL_MODE_DISPLAY_NAMES,
    INTENT_DISPLAY_NAMES,
    PLAYBOOK_DISPLAY_NAMES,
    REVIEWER_CHECK_DISPLAY_NAMES,
    ROUTE_STEP_DISPLAY_NAMES,
    format_enum_value,
    format_reviewer_check_name,
    format_route_steps,
    format_status,
)


def test_internal_enums_have_complete_chinese_display_maps() -> None:
    assert set(GOAL_MODE_DISPLAY_NAMES) >= {"auto", "metric_diagnosis", "growth_trend", "experiment_analysis", "content_performance", "live_quality", "causal_exploration", "periodic_report"}
    assert set(INTENT_DISPLAY_NAMES) >= {"metric_drop_diagnosis", "metric_growth_analysis", "experiment_analysis", "content_performance_analysis", "live_quality_analysis", "causal_exploration", "general_summary"}
    assert set(BACKEND_DISPLAY_NAMES) == {"rule_based", "langgraph", "langgraph_unavailable_fallback"}
    assert {"semantic_metric_query", "funnel_analysis", "cohort_retention"}.issubset(PLAYBOOK_DISPLAY_NAMES)
    assert {"load_data_source", "compile_metric_query", "review_query_plan", "build_lineage", "generate_report"}.issubset(ROUTE_STEP_DISPLAY_NAMES)
    assert {"semantic_plan_valid", "join_risk_reviewed", "lineage_generated", "observability_generated"}.issubset(REVIEWER_CHECK_DISPLAY_NAMES)


def test_formatter_returns_chinese_and_unknown_values_fall_back_safely() -> None:
    assert format_enum_value("goal_mode", "metric_diagnosis") == "指标波动诊断"
    assert format_route_steps(["load_data_source"]) == ["加载数据来源"]
    assert format_reviewer_check_name("semantic_plan_valid") == "语义查询计划完整"
    assert format_status("PASS") == "通过"
    assert format_enum_value("goal_mode", "future_mode") == "future_mode"
