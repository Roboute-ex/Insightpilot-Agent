from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data


def _tables():
    return generate_all_demo_data(seed=42)


def test_metric_diagnosis_route_includes_anomaly_and_attribution() -> None:
    result = run_agent_analysis("为什么昨天某城市订单量下降？", _tables(), goal_mode="metric_diagnosis")
    assert result["intent"] == "metric_drop_diagnosis"
    assert "route_metric_diagnosis" in result["route_taken"]
    assert "run_anomaly" in result["route_taken"]
    assert "run_attribution" in result["route_taken"]
    assert result["reviewer"]["status"] == "PASS"


def test_experiment_route_includes_experiment_node() -> None:
    result = run_agent_analysis("新策略是否提升了内容完播率？", _tables(), goal_mode="experiment_analysis")
    assert result["intent"] == "experiment_analysis"
    assert "route_experiment_analysis" in result["route_taken"]
    assert "run_experiment" in result["route_taken"]
    assert result["reviewer"]["status"] == "PASS"


def test_live_quality_route_includes_live_quality_node() -> None:
    result = run_agent_analysis("请定位直播体验异常的主要维度。", _tables(), goal_mode="live_quality")
    assert result["intent"] == "live_quality_analysis"
    assert "route_live_quality" in result["route_taken"]
    assert "run_live_quality" in result["route_taken"]
    assert result["reviewer"]["status"] == "PASS"


def test_causal_route_includes_causal_node() -> None:
    result = run_agent_analysis("请做轻量因果探索。", _tables(), goal_mode="causal_exploration")
    assert result["intent"] == "causal_exploration"
    assert "route_causal_exploration" in result["route_taken"]
    assert "run_causal_light" in result["route_taken"]
    assert result["reviewer"]["status"] == "PASS"


def test_auto_route_detects_question_intent() -> None:
    result = run_agent_analysis("为什么昨天某城市订单量下降？", _tables(), goal_mode="auto")
    assert result["goal_mode"] == "metric_diagnosis"
    assert result["goal_mode_source"] == "auto_detected"
    assert "route_metric_diagnosis" in result["route_taken"]


def test_user_goal_mode_overrides_question_keywords() -> None:
    result = run_agent_analysis("请分析订单下降", _tables(), goal_mode="experiment_analysis")
    assert result["intent"] == "experiment_analysis"
    assert result["goal_mode_source"] == "user_selected"
    assert "route_experiment_analysis" in result["route_taken"]
