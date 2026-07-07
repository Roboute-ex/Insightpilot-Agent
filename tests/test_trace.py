from __future__ import annotations

import json

from insightpilot.agents.trace import AnalysisTrace
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data


def test_trace_contains_v02_fields_and_is_json_serializable() -> None:
    trace = AnalysisTrace(
        workflow_backend="rule_based",
        user_question="为什么昨天订单量下降？",
        goal_mode="metric_diagnosis",
        goal_mode_display_name="指标波动诊断",
        goal_mode_source="user_selected",
        identified_intent="metric_drop_diagnosis",
        selected_metrics=["orders"],
        analysis_plan={"intent": "metric_drop_diagnosis"},
        executed_queries=[
            {
                "tool": "duckdb",
                "purpose": "daily metric",
                "query": "SELECT 1",
                "row_count": 1,
                "status": "success",
            }
        ],
        route_taken=["resolve_metrics", "create_plan"],
        generated_findings=["限制说明：synthetic data only。"],
        caveats=["仅使用 synthetic data。"],
        errors=[],
    )
    payload = trace.to_dict()
    json.dumps(payload, ensure_ascii=False)
    assert payload["trace_id"]
    assert payload["created_at"]
    assert payload["workflow_backend"] == "rule_based"
    assert payload["route_taken"] == ["resolve_metrics", "create_plan"]
    assert payload["executed_queries"][0]["tool"] == "duckdb"


def test_workflow_trace_includes_backend_route_and_reviewer_checks() -> None:
    result = run_agent_analysis(
        "为什么昨天某城市订单量下降？",
        generate_all_demo_data(seed=42),
        goal_mode="metric_diagnosis",
    )
    trace = result["trace"]
    json.dumps(trace, ensure_ascii=False)
    assert trace["trace_id"]
    assert trace["workflow_backend"] == "rule_based"
    assert "route_metric_diagnosis" in trace["route_taken"]
    assert trace["reviewer_checks"]["status"] == "PASS"
