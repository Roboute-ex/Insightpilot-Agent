from __future__ import annotations

import json

import pandas as pd

from insightpilot.agents.state import WorkflowState, create_initial_state


def test_create_initial_state_defaults() -> None:
    state = create_initial_state("为什么昨天订单量下降？", {"daily_metrics": pd.DataFrame()}, goal_mode="auto")
    assert state.user_question == "为什么昨天订单量下降？"
    assert state.goal_mode == "auto"
    assert state.goal_mode_display_name == "自动识别"
    assert state.goal_mode_source == "auto_detected"
    assert state.tables_available == ["daily_metrics"]


def test_workflow_state_to_dict_is_json_serializable() -> None:
    state = WorkflowState(user_question="问题", goal_mode="metric_diagnosis")
    state.add_route("resolve_metrics")
    state.intermediate_results["preview"] = pd.DataFrame({"x": [1, 2]})
    payload = state.to_dict()
    json.dumps(payload, ensure_ascii=False)
    assert payload["route_taken"] == ["resolve_metrics"]
    assert payload["intermediate_results"]["preview"]["type"] == "DataFrame"
    assert payload["intermediate_results"]["preview"]["row_count"] == 2
    assert "data" not in payload["intermediate_results"]["preview"]


def test_workflow_state_from_partial_falls_back_for_invalid_goal_mode() -> None:
    state = WorkflowState.from_partial({"goal_mode": "unknown", "route_taken": ["create_plan"]})
    assert state.goal_mode == "auto"
    assert state.goal_mode_display_name == "自动识别"
    assert state.route_taken == ["create_plan"]
