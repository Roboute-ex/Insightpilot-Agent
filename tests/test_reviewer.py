from __future__ import annotations

from insightpilot.agents.reviewer import review_analysis
from insightpilot.agents.trace import AnalysisTrace


def test_reviewer_returns_pass_for_complete_trace() -> None:
    trace = AnalysisTrace(
        user_question="为什么昨天某城市订单量下降？",
        identified_intent="metric_drop_diagnosis",
        selected_metrics=["orders"],
        analysis_plan={"intent": "metric_drop_diagnosis", "goal_mode": "metric_diagnosis"},
        goal_mode="metric_diagnosis",
        goal_mode_display_name="指标波动诊断",
        goal_mode_source="user_selected",
        executed_queries=["SELECT date, SUM(orders) FROM daily_metrics GROUP BY date"],
        generated_findings=["限制说明：synthetic data only，相关性不能直接解释为因果关系。"],
    )
    assert review_analysis(trace).status == "PASS"


def test_reviewer_returns_fail_for_missing_core_fields() -> None:
    trace = AnalysisTrace(
        user_question="问题",
        identified_intent="general_summary",
        selected_metrics=[],
        analysis_plan={},
        executed_queries=[],
        generated_findings=[],
    )
    assert review_analysis(trace).status == "FAIL"


def test_reviewer_missing_goal_mode_is_warn_only_when_findings_exist() -> None:
    trace = AnalysisTrace(
        user_question="为什么昨天某城市订单量下降？",
        identified_intent="metric_drop_diagnosis",
        selected_metrics=["orders"],
        analysis_plan={"intent": "metric_drop_diagnosis"},
        executed_queries=["pandas: summary"],
        generated_findings=["限制说明：synthetic data only，保留不确定性。"],
    )
    review = review_analysis(trace)
    assert review.status == "WARN"
    assert any("goal_mode" in issue for issue in review.issues)
