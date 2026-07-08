"""Optional LangGraph workflow wrapper.

LangGraph is intentionally optional. Import failures or incompatible APIs are
handled by ``run_agent_analysis`` in ``workflow.py`` via rule-based fallback.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pandas as pd

from insightpilot.agents.state import WorkflowState, create_initial_state
from insightpilot.agents.workflow import (
    WORKFLOW_BACKEND_LANGGRAPH,
    _build_result_from_state,
    _create_plan_node,
    _load_data_source_node,
    _report_node,
    _resolve_metrics_node,
    _review_node,
    _route_from_plan,
    _run_causal_exploration_node,
    _run_content_performance_node,
    _run_experiment_node,
    _run_growth_trend_node,
    _run_live_quality_node,
    _run_metric_diagnosis_node,
    _run_periodic_report_node,
    _safe_engine,
)


class GraphState(TypedDict, total=False):
    user_question: str
    goal_mode: str
    goal_mode_display_name: str
    goal_mode_source: str
    intent: str
    selected_metrics: list[str]
    analysis_plan: dict[str, Any]
    tables_available: list[str]
    executed_queries: list[dict[str, Any]]
    intermediate_results: dict[str, Any]
    findings: list[str]
    caveats: list[str]
    column_mapping: dict[str, Any]
    mapping_warnings: list[str]
    mapping_source: str
    reviewer_status: str
    reviewer_issues: list[str]
    reviewer_suggestions: list[str]
    route_taken: list[str]
    errors: list[str]


def _state(values: dict[str, Any] | WorkflowState) -> WorkflowState:
    if isinstance(values, WorkflowState):
        return values
    return WorkflowState.from_partial(dict(values))


def run_langgraph_workflow(
    question: str,
    tables: dict[str, pd.DataFrame],
    goal_mode: str = "auto",
    data_source_type: str = "synthetic",
    table_metadata: dict[str, Any] | None = None,
    column_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the optional LangGraph graph and return the standard workflow result."""

    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as exc:  # pragma: no cover - exercised through fallback tests
        raise ImportError("LangGraph is not available") from exc

    engine = _safe_engine(tables)

    def node(fn):
        def wrapped(values: GraphState) -> GraphState:
            state = _state(values)
            fn(state, tables, engine)
            return state.to_dict()

        return wrapped

    def route(values: GraphState) -> str:
        return _route_from_plan(_state(values))

    initial_state = create_initial_state(
        question,
        tables,
        goal_mode,
        data_source_type=data_source_type,
        table_metadata=table_metadata,
        column_mapping=column_mapping,
    )
    initial_state.intermediate_results["workflow_backend"] = WORKFLOW_BACKEND_LANGGRAPH

    try:
        graph = StateGraph(GraphState)
        graph.add_node("load_data_source", node(_load_data_source_node))
        graph.add_node("resolve_metrics", node(_resolve_metrics_node))
        graph.add_node("create_plan", node(_create_plan_node))
        graph.add_node("metric_diagnosis", node(_run_metric_diagnosis_node))
        graph.add_node("growth_trend", node(_run_growth_trend_node))
        graph.add_node("experiment_analysis", node(_run_experiment_node))
        graph.add_node("content_performance", node(_run_content_performance_node))
        graph.add_node("live_quality", node(_run_live_quality_node))
        graph.add_node("causal_exploration", node(_run_causal_exploration_node))
        graph.add_node("periodic_report", node(_run_periodic_report_node))
        graph.add_node("review", node(_review_node))
        graph.add_node("report", node(_report_node))

        graph.add_edge(START, "load_data_source")
        graph.add_edge("load_data_source", "resolve_metrics")
        graph.add_edge("resolve_metrics", "create_plan")
        graph.add_conditional_edges(
            "create_plan",
            route,
            {
                "metric_diagnosis": "metric_diagnosis",
                "growth_trend": "growth_trend",
                "experiment_analysis": "experiment_analysis",
                "content_performance": "content_performance",
                "live_quality": "live_quality",
                "causal_exploration": "causal_exploration",
                "periodic_report": "periodic_report",
            },
        )
        for route_node in [
            "metric_diagnosis",
            "growth_trend",
            "experiment_analysis",
            "content_performance",
            "live_quality",
            "causal_exploration",
            "periodic_report",
        ]:
            graph.add_edge(route_node, "review")
        graph.add_edge("review", "report")
        graph.add_edge("report", END)

        compiled = graph.compile()
        final_values = compiled.invoke(initial_state.to_dict())
    except Exception as exc:  # pragma: no cover - depends on optional API versions
        raise RuntimeError(f"LangGraph workflow failed: {exc}") from exc

    final_state = _state(final_values)
    result = final_state.intermediate_results.get("result")
    if isinstance(result, dict):
        return result
    result = _build_result_from_state(final_state)
    result["report_markdown"] = result.get("report_markdown", "")
    return result
