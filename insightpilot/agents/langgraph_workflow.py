"""Optional LangGraph workflow wrapper.

LangGraph is optional. Missing installation uses rule-based fallback. Installed
backend node/API failures are reported as real failures without silent rerun.
"""

from __future__ import annotations

from insightpilot.performance_tasks import cancellation_checkpoint, report_stage

from typing import Any, TypedDict
from dataclasses import fields

import pandas as pd

from insightpilot.agents.state import WorkflowState, create_initial_state
from insightpilot.agents.workflow import (
    WORKFLOW_BACKEND_LANGGRAPH,
    _build_manifest_node,
    _build_analysis_results_node,
    _build_governance_node,
    _build_observability_node,
    _build_result_from_state,
    _create_plan_node,
    _load_data_source_node,
    _prepare_column_mapping_node,
    _preview_analysis_plan_node,
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
    _run_playbook_node,
    _run_routed_analysis,
    _set_observability,
    _initialize_run_options,
    _finalize_observability,
    _safe_engine,
    _scope_analysis_tables,
)

from insightpilot.observability.tracer import LocalTracer, use_tracer
from insightpilot.analysis.reuse import aggregate_scope

# Keep the graph schema synchronized with every shared WorkflowState field.
# Missing TypedDict keys are silently dropped by LangGraph between nodes.
GraphState = TypedDict("GraphState", {item.name: Any for item in fields(WorkflowState)}, total=False)


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
    playbook_id: str | None = None,
    playbook_parameters: dict[str, Any] | None = None,
    execution_mode: str = "execute",
    presentation_mode: str = "eager",
    prepared_dataset=None,
) -> dict[str, Any]:
    """Run the optional LangGraph graph and return the standard workflow result."""

    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as exc:  # pragma: no cover - exercised through fallback tests
        raise ImportError("LangGraph is not available") from exc

    engine = _safe_engine(tables)

    def node(fn):
        def wrapped(values: GraphState) -> GraphState:
            cancellation_checkpoint()
            state = _state(values)
            if fn is _build_observability_node:
                report_stage("observability")
                _set_observability(state, tracer)
            else:
                with tracer.span(fn.__name__.strip("_")):
                    analysis_nodes = {_run_routed_analysis, _run_metric_diagnosis_node, _run_growth_trend_node, _run_experiment_node, _run_content_performance_node, _run_live_quality_node, _run_causal_exploration_node, _run_periodic_report_node, _build_analysis_results_node}
                    if fn in analysis_nodes and state.planning_status == "ready" and state.playbook_parameters.get("date_range") and not state.selected_playbook_id:
                        scoped = _scope_analysis_tables(state, tables)
                        scoped_engine = _safe_engine(scoped)
                        try:
                            fn(state, scoped, scoped_engine)
                        finally:
                            if scoped_engine is not None:
                                scoped_engine.close()
                    else:
                        fn(state, tables, engine)
            cancellation_checkpoint()
            return dict(state.__dict__)

        return wrapped

    def route(values: GraphState) -> str:
        cancellation_checkpoint()
        current = _state(values)
        if current.planning_status != "ready":
            return "routed_analysis"
        if current.execution_mode == "plan_only" and current.selected_playbook_id != "semantic_metric_query":
            return "plan_preview"
        if not current.selected_playbook_id and (current.user_table_mode or (not current.selected_metrics and current.goal_mode_source == "auto_detected" and current.intent == "general_summary")):
            return "routed_analysis"
        return "playbook" if current.selected_playbook_id else _route_from_plan(current)

    initial_state = create_initial_state(
        question,
        tables,
        goal_mode,
        data_source_type=data_source_type,
        table_metadata=table_metadata,
        column_mapping=column_mapping,
        playbook_id=playbook_id,
        playbook_parameters=playbook_parameters,
        execution_mode=execution_mode,
    )
    _initialize_run_options(initial_state,presentation_mode,prepared_dataset)
    initial_state.intermediate_results["workflow_backend"] = WORKFLOW_BACKEND_LANGGRAPH
    tracer = LocalTracer(initial_state.trace_id)

    try:
        graph = StateGraph(GraphState)
        graph.add_node("load_data_source", node(_load_data_source_node))
        graph.add_node("prepare_column_mapping", node(_prepare_column_mapping_node))
        graph.add_node("resolve_metrics", node(_resolve_metrics_node))
        graph.add_node("create_plan", node(_create_plan_node))
        graph.add_node("metric_diagnosis", node(_run_metric_diagnosis_node))
        graph.add_node("growth_trend", node(_run_growth_trend_node))
        graph.add_node("experiment_analysis", node(_run_experiment_node))
        graph.add_node("content_performance", node(_run_content_performance_node))
        graph.add_node("live_quality", node(_run_live_quality_node))
        graph.add_node("causal_exploration", node(_run_causal_exploration_node))
        graph.add_node("periodic_report", node(_run_periodic_report_node))
        graph.add_node("playbook", node(_run_playbook_node))
        graph.add_node("routed_analysis", node(_run_routed_analysis))
        graph.add_node("plan_preview", node(_preview_analysis_plan_node))
        graph.add_node("build_analysis_results", node(_build_analysis_results_node))
        graph.add_node("governance", node(_build_governance_node))
        graph.add_node("observability", node(_build_observability_node))
        graph.add_node("build_manifest", node(_build_manifest_node))
        graph.add_node("review", node(_review_node))
        graph.add_node("report", node(_report_node))

        graph.add_edge(START, "load_data_source")
        graph.add_edge("load_data_source", "prepare_column_mapping")
        graph.add_edge("prepare_column_mapping", "resolve_metrics")
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
                "playbook": "playbook",
                "routed_analysis": "routed_analysis",
                "plan_preview": "plan_preview",
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
            "playbook",
            "routed_analysis",
            "plan_preview",
        ]:
            graph.add_edge(route_node, "build_analysis_results")
        graph.add_edge("build_analysis_results", "governance")
        graph.add_edge("governance", "observability")
        graph.add_edge("observability", "build_manifest")
        graph.add_edge("build_manifest", "review")
        graph.add_edge("review", "report")
        graph.add_edge("report", END)

        compiled = graph.compile()
        with use_tracer(tracer), aggregate_scope():
            final_values = compiled.invoke(initial_state.to_dict())
    except Exception as exc:  # pragma: no cover - depends on optional API versions
        raise RuntimeError(f"LangGraph workflow failed: {exc}") from exc
    finally:
        if engine is not None:
            engine.close()

    final_state = _state(final_values)
    result = final_state.intermediate_results.get("result")
    if isinstance(result, dict):
        return _finalize_observability(final_state,tracer)
    result = _build_result_from_state(final_state)
    result["report_markdown"] = result.get("report_markdown", "")
    return result
