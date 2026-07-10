from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis


def test_workflow_playbook_adds_manifest_charts_and_routes(playbook_tables, playbook_mapping) -> None:
    result = run_agent_analysis("trend", playbook_tables, goal_mode="growth_trend", data_source_type="uploaded_files", column_mapping=playbook_mapping, playbook_id="metric_trend")
    assert result["selected_playbook"]["playbook_id"] == "metric_trend"
    assert result["charts"]
    assert result["run_manifest"]["playbook_id"] == "metric_trend"
    assert {"select_playbook", "build_safe_query", "execute_playbook", "generate_charts", "build_manifest"}.issubset(result["route_taken"])
    assert result["reviewer"]["status"] == "PASS"


def test_workflow_without_playbook_keeps_legacy_route(playbook_tables, playbook_mapping) -> None:
    result = run_agent_analysis("summary", playbook_tables, data_source_type="uploaded_files", column_mapping=playbook_mapping)
    assert result["selected_playbook"] is None
    assert "generic_analysis_fallback" in result["route_taken"]


def test_auto_playbook_records_recommendation_source(playbook_tables, playbook_mapping) -> None:
    result = run_agent_analysis("trend", playbook_tables, goal_mode="growth_trend", data_source_type="uploaded_files", column_mapping=playbook_mapping, playbook_id="auto")
    assert result["playbook_source"] == "auto_recommended"
    assert result["selected_playbook"]["playbook_id"] == "metric_trend"
    assert "recommend_playbooks" in result["route_taken"]


def test_playbook_keeps_optional_langgraph_fallback(playbook_tables, playbook_mapping) -> None:
    result = run_agent_analysis("trend", playbook_tables, goal_mode="growth_trend", data_source_type="synthetic", column_mapping=playbook_mapping, playbook_id="metric_trend", use_langgraph=True)
    assert result["workflow_backend"] in {"langgraph", "langgraph_unavailable_fallback"}
    assert result["selected_playbook"]["playbook_id"] == "metric_trend"
