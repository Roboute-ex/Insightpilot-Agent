from __future__ import annotations

from insightpilot.agents.reviewer import review_analysis
from insightpilot.agents.trace import AnalysisTrace
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data


def _trace(**overrides):
    values = {
        "user_question": "问题",
        "identified_intent": "metric_drop_diagnosis",
        "selected_metrics": ["orders"],
        "analysis_plan": {"intent": "metric_drop_diagnosis", "goal_mode": "metric_diagnosis"},
        "goal_mode": "metric_diagnosis",
        "goal_mode_display_name": "指标波动诊断",
        "goal_mode_source": "user_selected",
        "executed_queries": [{"tool": "pandas", "purpose": "summary", "query": "summary", "row_count": 1, "status": "success"}],
        "route_taken": ["resolve_metrics", "create_plan", "route_metric_diagnosis"],
        "generated_findings": ["限制说明：synthetic data only，相关性不能直接解释为因果关系。"],
        "caveats": ["仅使用 synthetic data，不代表真实业务结论。"],
        "errors": [],
    }
    values.update(overrides)
    return AnalysisTrace(**values)


def test_normal_demo_passes_with_high_score() -> None:
    result = run_agent_analysis(
        "为什么昨天某城市订单量下降？",
        generate_all_demo_data(seed=42),
        goal_mode="metric_diagnosis",
    )
    assert result["reviewer"]["status"] == "PASS"
    assert result["reviewer"]["score"] >= 80


def test_missing_caveats_is_warn() -> None:
    review = review_analysis(_trace(generated_findings=["发现一个指标变化。"], caveats=[]))
    assert review.status == "WARN"
    assert review.score < 80


def test_missing_findings_is_fail() -> None:
    review = review_analysis(_trace(generated_findings=[]))
    assert review.status == "FAIL"
    assert review.score < 50


def test_experiment_missing_p_value_is_warn() -> None:
    review = review_analysis(
        _trace(
            identified_intent="experiment_analysis",
            goal_mode="experiment_analysis",
            generated_findings=["sample_size={'control': 50, 'treatment': 50}，synthetic data only。"],
        )
    )
    assert review.status == "WARN"
    assert not review.checks["experiment_has_p_value_when_needed"]


def test_causal_missing_caveat_is_warn() -> None:
    review = review_analysis(
        _trace(
            identified_intent="causal_exploration",
            goal_mode="causal_exploration",
            generated_findings=["estimated_effect=0.1，synthetic data only。"],
            caveats=["仅使用 synthetic data。"],
        )
    )
    assert review.status == "WARN"
    assert not review.checks["causal_has_caveat_when_needed"]
