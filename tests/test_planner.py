from __future__ import annotations

from insightpilot.planning.planner import create_analysis_plan


def test_planner_detects_required_intents() -> None:
    assert create_analysis_plan("为什么昨天某城市订单量下降？").intent == "metric_drop_diagnosis"
    assert create_analysis_plan("新策略是否提升了内容完播率？").intent == "experiment_analysis"
    assert create_analysis_plan("请分析不同内容类型的消费表现。").intent == "content_performance_analysis"
    assert create_analysis_plan("请定位直播体验异常的主要维度。").intent == "live_quality_analysis"
    assert create_analysis_plan("收入增长来自哪里？").intent == "metric_growth_analysis"


def test_planner_auto_goal_mode_detects_metric_diagnosis() -> None:
    plan = create_analysis_plan("为什么昨天订单量下降", goal_mode="auto")
    assert plan.intent == "metric_drop_diagnosis"
    assert plan.goal_mode == "metric_diagnosis"
    assert plan.goal_mode_display_name == "指标波动诊断"
    assert plan.goal_mode_source == "auto_detected"


def test_planner_user_goal_mode_overrides_keywords() -> None:
    experiment_plan = create_analysis_plan("请分析这个实验", goal_mode="experiment_analysis")
    assert experiment_plan.intent == "experiment_analysis"
    assert experiment_plan.goal_mode == "experiment_analysis"
    assert experiment_plan.goal_mode_source == "user_selected"

    override_plan = create_analysis_plan("请分析订单下降", goal_mode="experiment_analysis")
    assert override_plan.intent == "experiment_analysis"
    assert override_plan.goal_mode == "experiment_analysis"
    assert override_plan.goal_mode_display_name == "A/B 实验评估"
