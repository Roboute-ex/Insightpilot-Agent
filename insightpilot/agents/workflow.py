"""Deterministic analysis workflow with optional LangGraph orchestration."""

from __future__ import annotations

from insightpilot.performance_tasks import cancellation_checkpoint

import importlib.util
from typing import Any, Callable

import pandas as pd

from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.analysis.metric_diagnosis import _daily_series
from insightpilot.metrics.aggregation import metric_components
from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.analysis.causal_light import estimate_adjusted_effect
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.analysis.package_builder import build_analysis_result_package, deduplicate_findings, findings_from_package
from insightpilot.analysis.results import AnalysisResultPackage
from insightpilot.agents.reviewer import review_analysis
from insightpilot.agents.state import WorkflowState, create_initial_state
from insightpilot.agents.trace import AnalysisTrace
from insightpilot.contracts import ColumnContract, TableContract, validate_contracts
from insightpilot.config import REPORT_LIMITATION
from insightpilot._version import __version__
from insightpilot.ingestion.mapping import (
    ColumnMapping,
    normalize_column_mapping,
    suggest_column_mapping,
    validate_column_mapping,
)
from insightpilot.ingestion.schema_mapper import infer_schema_mapping
from insightpilot.ingestion.validation import validate_tables_for_workflow
from insightpilot.metrics.dictionary import MetricDefinition
from insightpilot.playbooks.sql_templates import metric_aggregate_sql
from insightpilot.metrics.resolver import resolve_metrics_from_question
from insightpilot.lineage import DatasetNode, LineageEdge, LineageGraph, OperationNode
from insightpilot.observability.tracer import LocalTracer, use_tracer, trace_stage
from insightpilot.analysis.reuse import aggregate_scope
from insightpilot.planning.planner import AnalysisPlan, UNRESOLVED_METRIC_STEP, create_analysis_plan, prepare_analysis_request
from insightpilot.playbooks.executor import execute_playbook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.reports.manifest import CURRENT_MANIFEST_VERSION, RunManifest, fingerprint_dataframe, sanitize_manifest_value
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.relationships import RelationshipGraph
from insightpilot.tools.duckdb_engine import AnalyticsEngine, LazyAnalyticsEngine
from insightpilot.visualization.factory import build_charts


WORKFLOW_BACKEND_RULE_BASED = "rule_based"
WORKFLOW_BACKEND_LANGGRAPH = "langgraph"
WORKFLOW_BACKEND_LANGGRAPH_FALLBACK = "langgraph_unavailable_fallback"

DEFAULT_CAVEATS = [
    "本次分析仅使用内置模拟数据，用于学习研究和工作流演示，不代表真实业务结论。",
    "相关性不能直接解释为因果关系；实验和轻量调整结果仍需谨慎解读。",
    "当前分析计划由确定性规则生成。对于表达复杂或口径不明确的问题，建议手动选择分析目标、指标和字段映射。",
]

CUSTOM_DATA_CAVEATS = [
    "自定义数据仅在当前会话内存中分析，默认不写入仓库。",
    "当前通用分析基于字段类型和列名规则推断，必要时需要用户指定日期列、指标列或维度列。",
    "上传文件或数据库查询结果不应被描述为真实业务结论，分析仍需结合数据口径复核。",
]
CUSTOM_REPORT_LIMITATION = (
    "限制说明：本次分析基于当前会话内存中的自定义表，未写入仓库；"
    "字段含义和数据口径需要用户复核，相关性不能直接解释为因果关系。"
)


def _metric_payload(metrics: list[MetricDefinition]) -> list[dict[str, object]]:
    return [metric.to_dict() for metric in metrics]


def _safe_engine(tables: dict[str, pd.DataFrame]) -> AnalyticsEngine | None:
    try:
        return LazyAnalyticsEngine(tables)
    except ImportError:
        return None


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_to_builtin(item) for item in value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    return value


def _round_value(value: Any) -> Any:
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {key: _round_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_round_value(item) for item in value)
    return _to_builtin(value)


def _append_unique(items: list[str], new_items: list[str]) -> None:
    for item in new_items:
        if item and item not in items:
            items.append(item)


def _metadata_from_tables(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for name, df in tables.items():
        schema_mapping = infer_schema_mapping(name, df).to_dict()
        metadata[name] = {
            "source_type": "in_memory",
            "source_name": name,
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": [str(column) for column in df.columns],
            "schema_mapping": schema_mapping,
            "warnings": validate_tables_for_workflow({name: df}),
        }
    return metadata


def _summarize_table_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for table_name, item in metadata.items():
        if not isinstance(item, dict):
            continue
        summary[table_name] = {
            "source_type": item.get("source_type"),
            "source_name": item.get("source_name"),
            "row_count": item.get("row_count"),
            "column_count": item.get("column_count"),
            "columns": item.get("columns", []),
            "schema_mapping": item.get("schema_mapping", {}),
            "warnings": item.get("warnings", []),
        }
    sanitized = sanitize_manifest_value(summary)
    return sanitized if isinstance(sanitized, dict) else {}


def _first_custom_table(state: WorkflowState, tables: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame] | None:
    if not tables:
        return None
    for name, df in tables.items():
        mapping = state.table_metadata.get(name, {}).get("schema_mapping", {})
        if mapping.get("possible_metric_columns"):
            return name, df
    return next(iter(tables.items()))


def _mapping_for_table(state: WorkflowState, table_name: str, df: pd.DataFrame) -> dict[str, Any]:
    metadata = state.table_metadata.get(table_name, {})
    mapping = metadata.get("schema_mapping") if isinstance(metadata, dict) else {}
    if isinstance(mapping, dict) and mapping:
        return mapping
    return infer_schema_mapping(table_name, df).to_dict()


def _column_mapping_from_state(state: WorkflowState) -> ColumnMapping:
    if not isinstance(state.column_mapping, dict) or not state.column_mapping:
        return ColumnMapping()
    from dataclasses import fields
    allowed = {item.name for item in fields(ColumnMapping)}
    return ColumnMapping(**{key: value for key, value in state.column_mapping.items() if key in allowed})


def _select_mapping_table(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    requested_table: str | None = None,
) -> tuple[str, pd.DataFrame] | None:
    if not tables:
        return None
    if requested_table and requested_table in tables:
        return requested_table, tables[requested_table]
    current_table = state.column_mapping.get("table_name") if isinstance(state.column_mapping, dict) else None
    if current_table and current_table in tables:
        return str(current_table), tables[str(current_table)]
    return _first_custom_table(state, tables)


def _prepare_column_mapping_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    if not state.user_table_mode and not state.column_mapping:
        state.column_mapping = {}
        state.mapping_source = "none"
        state.mapping_warnings = []
        return state

    raw_mapping = state.column_mapping if isinstance(state.column_mapping, dict) and state.column_mapping else None
    # Preflight must receive the same user request as the UI. Normalization here
    # supplies execution defaults and provenance, but cannot turn those defaults
    # into an additional user choice before the shared planner has resolved it.
    from copy import deepcopy
    state.intermediate_results["_requested_column_mapping"] = deepcopy(raw_mapping)
    requested_table = raw_mapping.get("table_name") if raw_mapping else None
    selected = _select_mapping_table(state, tables, str(requested_table) if requested_table else None)
    if selected is None:
        state.mapping_source = "none"
        state.mapping_warnings = ["没有可用表，无法生成字段映射。"]
        return state

    table_name, df = selected
    available_columns = [str(column) for column in df.columns]
    if raw_mapping:
        state.mapping_source = "user_selected"
        mapping = normalize_column_mapping(raw_mapping, available_columns)
        mapping.table_name = table_name
    else:
        state.add_route("suggest_column_mapping")
        state.mapping_source = "auto_suggested"
        mapping = suggest_column_mapping(table_name, df)

    state.add_route("validate_column_mapping")
    warnings = validate_column_mapping(mapping, available_columns)
    for note in mapping.notes:
        if note not in warnings:
            warnings.append(note)
    for metric_column in mapping.metric_columns:
        if metric_column in df.columns and not pd.api.types.is_numeric_dtype(df[metric_column]):
            warnings.append(f"metric_columns 包含非数值列，将在分析时尝试转换：{metric_column}")
    if mapping.outcome_column and mapping.outcome_column in df.columns and not pd.api.types.is_numeric_dtype(df[mapping.outcome_column]):
        warnings.append(f"outcome_column 不是数值列，将在因果探索时尝试转换：{mapping.outcome_column}")

    state.add_route("apply_column_mapping")
    state.column_mapping = mapping.to_dict()
    state.mapping_warnings = list(dict.fromkeys(warnings))
    if state.mapping_warnings:
        _append_unique(state.caveats, state.mapping_warnings)
    return state


def _record_query(
    state: WorkflowState,
    tool: str,
    purpose: str,
    query: str,
    row_count: int = 0,
    status: str = "success",
) -> None:
    state.executed_queries.append(
        {
            "tool": tool,
            "purpose": purpose,
            "query": query,
            "row_count": int(row_count),
            "status": status,
        }
    )


def _run_query(
    engine: AnalyticsEngine | None,
    query: str,
    state: WorkflowState,
    purpose: str,
    fallback: Callable[[], pd.DataFrame],
) -> pd.DataFrame:
    if engine is not None:
        try:
            result = engine.run_sql(query)
            _record_query(state, "duckdb", purpose, query, len(result), "success")
            return result
        except Exception as exc:
            state.errors.append(f"DuckDB query failed for {purpose}: {exc}")
            _record_query(state, "duckdb", purpose, query, 0, "failed")

    try:
        result = fallback()
        _record_query(state, "pandas", purpose, f"pandas fallback: {query}", len(result), "success")
        return result
    except Exception as exc:
        state.errors.append(f"pandas fallback failed for {purpose}: {exc}")
        _record_query(state, "pandas", purpose, f"pandas fallback: {query}", 0, "failed")
        return pd.DataFrame()


def _record_operation(state: WorkflowState, purpose: str, operation: str, row_count: int = 0) -> None:
    _record_query(state, "pandas", purpose, operation, row_count, "success")


def _daily_metric_frame(tables: dict[str, pd.DataFrame], metric: str, city_filter: str | None = None) -> pd.DataFrame:
    daily = tables.get("transaction_detail", tables.get("orders", tables["daily_metrics"])).copy() if metric == "active_users" else tables["daily_metrics"].copy()
    if city_filter:
        daily = daily[daily["city"] == city_filter]
    return _daily_series(daily, metric).rename(columns={"metric_value": metric})[["date", metric]]


def _table_missing(state: WorkflowState, tables: dict[str, pd.DataFrame], required: list[str], route_name: str) -> bool:
    missing = [table for table in required if table not in tables]
    if not missing:
        return False
    state.errors.append(f"Missing table(s) for {route_name}: {', '.join(missing)}")
    state.caveats.append(f"{route_name} 所需 synthetic 表缺失：{', '.join(missing)}，已记录错误并返回可复核结果。")
    return True


def _first_metric(plan: AnalysisPlan, table: pd.DataFrame, default: str) -> str:
    return next((name for name in plan.related_metrics if name in table.columns), default)


def _set_node_outputs(
    state: WorkflowState,
    summary: str,
    findings: list[str],
    artifacts: dict[str, Any],
    next_steps: list[str],
    caveats: list[str] | None = None,
) -> None:
    state.intermediate_results["summary"] = summary
    state.intermediate_results["artifacts"] = _round_value(artifacts)
    state.intermediate_results["next_steps"] = next_steps
    state.findings = findings
    _append_unique(state.caveats, DEFAULT_CAVEATS if state.data_source_type == "synthetic" else CUSTOM_DATA_CAVEATS)
    if caveats:
        _append_unique(state.caveats, caveats)


def _resolve_metrics_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("resolve_metrics")
    metrics = resolve_metrics_from_question(state.user_question)
    state.selected_metrics = [metric.metric_name for metric in metrics]
    state.intermediate_results["metrics"] = _metric_payload(metrics)
    state.tables_available = sorted(tables.keys())
    return state


def _load_data_source_node(
    state: WorkflowState,
    tables: dict[str,pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("load_data_source")
    state.tables_available=sorted(tables)
    state.add_route("validate_tables")
    state.add_route("infer_schema")
    with trace_stage("data_profile_validation",rows=sum(len(frame) for frame in tables.values()),table_count=len(tables),cache_hit=state.dataset_prepared):
        if state.dataset_prepared:
            state.schema_warnings=list(dict.fromkeys(warning for meta in state.table_metadata.values() for warning in meta.get("warnings",[])))
        else:
            state.schema_warnings=validate_tables_for_workflow(tables)
            metadata={}
            readiness_by_object={}
            from insightpilot.agents.dataset import build_readiness_summary
            for name,frame in tables.items():
                cancellation_checkpoint()
                item=dict(state.table_metadata.get(name,{}))
                item.update(row_count=len(frame),column_count=len(frame.columns),columns=list(map(str,frame.columns)),schema_mapping=infer_schema_mapping(name,frame).to_dict())
                if id(frame) not in readiness_by_object:
                    with trace_stage("dataset_readiness",table=name,rows=len(frame)):
                        readiness_by_object[id(frame)] = build_readiness_summary(frame,item["schema_mapping"])
                item["readiness_summary"] = readiness_by_object[id(frame)]
                item.pop("builtin_scenario", None)
                if frame.attrs.get("insightpilot_builtin_scenario"):
                    item["builtin_scenario"] = frame.attrs["insightpilot_builtin_scenario"]
                item.setdefault("source_type",state.data_source_type)
                item.setdefault("source_name",name)
                item["warnings"]=list(dict.fromkeys([*item.get("warnings",[]),*[warning for warning in state.schema_warnings if warning.startswith(name+":")]]))
                metadata[name]=item
            state.table_metadata=metadata
    _append_unique(state.caveats,state.schema_warnings)
    if state.user_table_mode:
        _append_unique(state.caveats,CUSTOM_DATA_CAVEATS)
    return state


def _input_fingerprint(state: WorkflowState,name: str,frame: pd.DataFrame) -> str:
    cached=name in state.dataset_fingerprints
    with trace_stage("input_fingerprint",table=name,rows=len(frame),columns=len(frame.columns),cache_hit=cached):
        if not cached:
            if id(frame) not in state._input_fingerprint_objects:
                state._input_fingerprint_objects[id(frame)]=fingerprint_dataframe(frame)
            state.dataset_fingerprints[name]=state._input_fingerprint_objects[id(frame)]
        return state.dataset_fingerprints[name]


def _initialize_run_options(state: WorkflowState,presentation_mode: str,prepared_dataset=None) -> None:
    state.presentation_mode=presentation_mode
    if prepared_dataset is not None:
        state.dataset_prepared=True
        state.dataset_id=prepared_dataset.dataset_id
        state.dataset_revision=prepared_dataset.revision
        state.dataset_fingerprints=prepared_dataset.fingerprints


def _create_plan_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("create_plan")
    answers = state.playbook_parameters.pop("_clarification_answers", None)
    guidance_context = state.playbook_parameters.pop("_guidance_context", {})
    if state.selected_playbook_id in {"auto", "auto_recommended"}:
        state.add_route("recommend_playbooks")
    prepared = prepare_analysis_request(
        state.user_question, table_metadata=state.table_metadata, goal_mode=state.goal_mode,
        playbook_id=state.selected_playbook_id,
        column_mapping=state.intermediate_results.pop("_requested_column_mapping", state.column_mapping if state.mapping_source == "user_selected" else None),
        playbook_parameters=state.playbook_parameters,
        semantic_model_id=str(state.playbook_parameters.get("semantic_model_id", "commerce_demo")),
        clarification_answers=answers,
        dataset_revision=state.dataset_revision,
        selection_source=guidance_context.get("selection_source"),
        analysis_scope=guidance_context.get("analysis_scope"),
    )
    for key in ("planning_status", "clarification", "metric_definitions", "semantic_fingerprint", "presentation_fingerprint"):
        setattr(state, key, prepared[key])
    state.intermediate_results["analysis_advice"] = prepared["analysis_advice"]
    state.intermediate_results["preflight"] = prepared["preflight"]
    normalized = prepared["normalized_request"]
    originally_auto = state.selected_playbook_id in {"auto", "auto_recommended"}
    state.selected_playbook_id = normalized["playbook_id"]
    state.playbook_source = "auto_recommended" if originally_auto else prepared["analysis_advice"]["selection_source"]
    _append_unique(state.caveats, prepared["analysis_advice"]["effective_method"].get("necessary_caveats", []))
    state.playbook_parameters = normalized["playbook_parameters"]
    state.goal_mode = normalized["goal_mode"]
    if normalized["column_mapping"]:
        state.column_mapping = normalized["column_mapping"]
        state.mapping_source = "user_selected"
    if state.planning_status != "ready":
        state.add_route("needs_input" if state.planning_status == "needs_clarification" else state.planning_status)
        messages = [item["question"] for item in state.clarification.get("items", [])]
        messages += state.clarification.get("errors", []) + state.clarification.get("unsupported_reasons", [])
        state.intermediate_results["summary"] = "；".join(messages) or "需要补充分析配置。"
        state.findings = []
        state.intermediate_results["next_steps"] = messages
    plan = create_analysis_plan(state.user_question, goal_mode=state.goal_mode)
    state.intent = plan.intent
    state.goal_mode = plan.goal_mode
    state.goal_mode_display_name = plan.goal_mode_display_name
    state.goal_mode_source = plan.goal_mode_source
    state.analysis_plan = plan.to_dict()
    if state.column_mapping.get("metric_columns"):
        state.selected_metrics = list(state.column_mapping["metric_columns"])
        state.analysis_plan["related_metrics"] = list(state.selected_metrics)
        if state.column_mapping.get("dimension_columns"):
            state.analysis_plan["dimensions"] = list(state.column_mapping["dimension_columns"])
        if state.planning_status == "ready":
            state.analysis_plan["analysis_steps"] = [step for step in state.analysis_plan["analysis_steps"] if step != UNRESOLVED_METRIC_STEP]
        state.analysis_plan["analysis_steps"].insert(0, "本次手动字段映射优先于问题关键词。")
        plan = AnalysisPlan(**state.analysis_plan)
    state.intermediate_results["plan"] = plan
    return state


def _mapping_for_recommendation(state: WorkflowState, tables: dict[str, pd.DataFrame]) -> ColumnMapping:
    if state.column_mapping:
        return _column_mapping_from_state(state)
    if not tables:
        return ColumnMapping()
    if state.goal_mode in {"experiment_analysis", "causal_exploration"} and "experiments" in tables:
        df = tables["experiments"]
        return ColumnMapping(
            table_name="experiments",
            group_column="group" if "group" in df.columns else None,
            treatment_column="group" if "group" in df.columns else None,
            outcome_column="completion_rate" if "completion_rate" in df.columns else None,
            metric_columns=["completion_rate"] if "completion_rate" in df.columns else [],
            dimension_columns=[column for column in ["historical_activity", "historical_revenue", "city"] if column in df.columns],
        )
    table_name = "daily_metrics" if "daily_metrics" in tables else sorted(tables)[0]
    return suggest_column_mapping(table_name, tables[table_name])


def _run_playbook_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    del engine
    requested_id = state.selected_playbook_id
    if requested_id in {"auto", "auto_recommended"}:
        state.add_route("recommend_playbooks")
        recommendations = get_playbook_registry().recommend(
            state.goal_mode,
            _mapping_for_recommendation(state, tables),
        )
        requested_id = recommendations[0].playbook_id if recommendations else "data_profile"
        state.playbook_source = "auto_recommended"
    else:
        state.playbook_source = "auto_recommended" if state.playbook_source == "auto_recommended" else state.intermediate_results.get("analysis_advice", {}).get("selection_source", "user_selected")
    state.selected_playbook_id = requested_id
    state.add_route("select_playbook")
    state.add_route("validate_playbook")
    try:
        state.intermediate_results["selected_playbook"] = get_playbook_registry().get(requested_id or "").to_dict()
        execution = execute_playbook(
            requested_id or "",
            tables,
            state.column_mapping or None,
            state.playbook_parameters,
            state.table_metadata,
        )
    except Exception as exc:
        state.errors.append(f"playbook selection failed: {exc}")
        state.findings = []
        _append_unique(state.caveats, [f"分析剧本无法执行：{exc}"])
        return state

    metadata = execution.metadata if isinstance(execution.metadata, dict) else {}
    preview_only = metadata.get("metric_request", {}).get("execution_mode") == "plan_only" or state.execution_mode == "plan_only"
    if execution.executed_queries:
        state.add_route("build_safe_query")
    if metadata.get("multi_table"):
        state.add_route("load_semantic_model") if metadata.get("semantic_model") else None
        state.add_route("build_relationship_graph") if metadata.get("semantic_model") else None
        state.add_route("plan_joins") if metadata.get("join_plan") else None
        state.add_route("compile_metric_query") if metadata.get("query_plan") else None
        state.add_route("review_query_plan") if metadata.get("plan_review") else None
    state.add_route("preview_playbook" if preview_only else "execute_playbook")
    state.executed_queries.extend(execution.executed_queries)
    for query_record in execution.executed_queries:
        if query_record.get("status") == "failed":
            state.errors.append(
                f"Playbook query failed: {query_record.get('template_id', 'unknown')} "
                f"({query_record.get('purpose', '')})"
            )
    state.playbook_parameters = dict(execution.parameters)
    state.chart_specs = list(execution.chart_specs)
    if metadata.get("semantic_model"):
        state.semantic_model = dict(metadata["semantic_model"])
        state.semantic_catalog = {"fingerprint": metadata.get("catalog_fingerprint")}
        state.metric_request = dict(metadata.get("metric_request") or {})
        state.join_plan = dict(metadata.get("join_plan") or {})
        state.query_plan = dict(metadata.get("query_plan") or {})
        state.plan_review = dict(metadata.get("plan_review") or {})
        state.execution_mode = str(state.metric_request.get("execution_mode") or state.execution_mode)
        requested_metrics = state.metric_request.get("metrics", [])
        if isinstance(requested_metrics, list):
            state.selected_metrics = [str(item) for item in requested_metrics]
        if execution.result_tables:
            state.add_route("execute_query_plan")
    mapping = execution.metadata.get("column_mapping", {})
    if isinstance(mapping, dict) and mapping:
        state.column_mapping = mapping
        state.mapping_source = str(execution.metadata.get("mapping_source", state.mapping_source))
        state.mapping_warnings = list(dict.fromkeys([*state.mapping_warnings, *execution.warnings]))
        if not state.selected_metrics:
            state.selected_metrics = list(mapping.get("metric_columns", []))
    if execution.playbook_id == "funnel_analysis":
        state.selected_metrics = ["session_conversion_rate"]
    elif execution.playbook_id == "cohort_retention":
        state.selected_metrics = ["cohort_retention_rate"]
    if state.goal_mode not in get_playbook_registry().get(execution.playbook_id).supported_goal_modes:
        _append_unique(state.caveats, ["显式分析剧本优先于目标模式，本次执行所选剧本的字段与方法。 "])
    state.findings = list(execution.findings)
    _append_unique(state.caveats, execution.caveats)
    _append_unique(state.caveats, execution.warnings)
    if execution.status == "FAIL":
        state.errors.extend(
            warning for warning in execution.warnings if warning not in state.errors
        )
    state.intermediate_results["summary"] = f"{execution.playbook_name}执行完成，状态为 {execution.status}。"
    state.intermediate_results["playbook_result"] = execution.to_dict()
    state.intermediate_results["result_tables"] = execution.result_tables
    state.intermediate_results["artifacts"] = {
        "playbook_id": execution.playbook_id,
        "result_tables": execution.to_dict()["result_tables"],
    }
    state.intermediate_results["next_steps"] = [
        "复核 Column Mapping、playbook 参数与 caveats 后再解释结果。"
    ]
    chart_pairs=[]
    if state.presentation_mode == "eager" and execution.chart_specs and execution.result_tables:
        state.add_route("generate_charts")
        with trace_stage("chart_construction",chart_count=len(execution.chart_specs)):
            chart_pairs=build_charts(execution.chart_specs,execution.result_tables)
    state.intermediate_results["chart_pairs"] = chart_pairs
    state.intermediate_results["charts"] = [figure for _, figure in chart_pairs]
    return state


def _build_governance_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    """Build contracts and lineage for semantic runs without affecting legacy routes."""

    del engine
    if state.planning_status != "ready":
        return state
    if not state.semantic_model:
        graph = LineageGraph()
        for name, frame in sorted(tables.items()):
            graph.add_dataset(DatasetNode(f"input_{name}", name, "input", _input_fingerprint(state,name,frame), len(frame), list(map(str, frame.columns))))
        results = state.intermediate_results.get("result_tables", {})
        if state.execution_mode != "plan_only" and results:
            operation = "operation_analysis"
            graph.add_operation(OperationNode(operation, "analysis", "本次本地分析", str(state.selected_playbook_id or state.goal_mode), {"route_taken": list(state.route_taken)}))
            for name in sorted(tables):
                graph.add_edge(LineageEdge(f"input_{name}", operation, "used_by"))
            for name, frame in sorted(results.items()):
                graph.add_dataset(DatasetNode(f"result_{name}", name, "output", fingerprint_dataframe(frame), len(frame), list(map(str, frame.columns))))
                graph.add_edge(LineageEdge(operation, f"result_{name}", "produces"))
        state.lineage = graph.to_dict()
        state.add_route("build_lineage")
        return state
    model_id = str(state.semantic_model.get("model_id") or "commerce_demo")
    try:
        model = load_builtin_catalog().get(model_id)
    except ValueError as exc:
        state.errors.append(str(exc))
        return state
    state.add_route("check_data_contracts")
    contracts: list[TableContract] = []
    for entity in model.entities.values():
        if entity.table_name not in tables:
            continue
        contracts.append(
            TableContract(
                table_name=entity.table_name,
                minimum_rows=1,
                unique_key=[entity.primary_key],
                columns=[ColumnContract(entity.primary_key, nullable=False, unique=True)],
            )
        )
    checks = validate_contracts(tables, contracts)
    state.contract_results = [item.to_dict() for item in checks]
    state.relationship_graph = RelationshipGraph(model).to_dict()

    state.add_route("build_lineage")
    lineage = LineageGraph()
    required_entities = state.query_plan.get("required_entities", []) if state.query_plan else []
    table_names = [model.entities[item].table_name for item in required_entities if item in model.entities]
    if not table_names:
        selected = state.intermediate_results.get("selected_playbook", {})
        requirements = selected.get("requirements", {}) if isinstance(selected, dict) else {}
        table_names = [name for name in requirements.get("required_tables", []) if name in tables]
    for table_name in sorted(set(table_names)):
        frame = tables[table_name]
        lineage.add_dataset(
            DatasetNode(
                f"input_{table_name}",
                table_name,
                "input",
                _input_fingerprint(state,table_name,frame),
                int(len(frame)),
                [str(column) for column in frame.columns],
            )
        )
    operation_id = f"operation_{state.query_plan.get('plan_id') or state.selected_playbook_id}"
    lineage.add_operation(
        OperationNode(
            operation_id,
            "semantic_query" if state.query_plan else "multi_table_playbook",
            "执行语义指标查询" if state.query_plan else "执行多表分析剧本",
            str(state.query_plan.get("plan_id") or ""),
            {"playbook_id": state.selected_playbook_id},
        )
    )
    for table_name in sorted(set(table_names)):
        lineage.add_edge(LineageEdge(f"input_{table_name}", operation_id, "input_to_operation"))
    result_tables = state.intermediate_results.get("result_tables", {})
    if isinstance(result_tables, dict):
        for name, frame in sorted(result_tables.items()):
            if not isinstance(frame, pd.DataFrame):
                continue
            output_id = f"output_{name}"
            lineage.add_dataset(
                DatasetNode(
                    output_id,
                    name,
                    "output",
                    fingerprint_dataframe(frame),
                    int(len(frame)),
                    [str(column) for column in frame.columns],
                )
            )
            lineage.add_edge(LineageEdge(operation_id, output_id, "operation_to_output"))
    state.lineage = {**lineage.to_dict(), "dot": lineage.to_dot()}
    return state


def _set_observability(state: WorkflowState, tracer: LocalTracer, *, add_route: bool = True) -> WorkflowState:
    if add_route:
        state.add_route("summarize_observability")
    join_risk_count = sum(
        1
        for step in state.join_plan.get("steps", [])
        if isinstance(step, dict) and step.get("risk_level") != "safe"
    )
    summary = tracer.summary(
        query_count=sum(span.name == "sql_query" for span in tracer.spans),
        warning_count=len(state.schema_warnings) + len(state.mapping_warnings),
        error_count=len(state.errors),
        join_risk_count=join_risk_count,
    )
    state.telemetry = {**tracer.to_dict(), "summary": {**summary.to_dict(),"operation_count":len(state.executed_queries)}}
    return state


def _build_observability_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    del tables, engine
    tracer = LocalTracer(state.trace_id)
    # Without the runner tracer, no historical durations were measured.
    # Never fabricate timings by replaying routes after execution.
    return _set_observability(state, tracer)


def _build_manifest_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    del engine
    state.add_route("build_manifest")
    table_summary_map = _summarize_table_metadata(state.table_metadata)
    table_summaries = [
        {"table_name": table_name, **summary}
        for table_name, summary in table_summary_map.items()
        if isinstance(summary, dict)
    ]
    reviewer = state.intermediate_results.get("reviewer", {})
    reviewer_dict = reviewer if isinstance(reviewer, dict) else {}
    manifest = RunManifest(
        manifest_version=CURRENT_MANIFEST_VERSION,
        metric_definitions=state.metric_definitions,
        semantic_fingerprint=state.semantic_fingerprint,
        presentation_fingerprint=state.presentation_fingerprint,
        planning_status=state.planning_status,
        clarification=state.clarification,
        analysis_advice=state.intermediate_results.get("analysis_advice", {}),
        preflight=state.intermediate_results.get("preflight", {}),
        project_version=__version__,
        run_id=state.trace_id,
        created_at=state.created_at,
        data_source_type=state.data_source_type,
        source_summary={
            "data_source_type": state.data_source_type,
            "table_count": len(tables),
            "table_names": sorted(tables),
        },
        table_summaries=table_summaries,
        dataset_fingerprints={name: _input_fingerprint(state,name,df) for name, df in sorted(tables.items())},
        question=state.user_question,
        goal_mode=state.goal_mode,
        goal_mode_source=state.goal_mode_source,
        workflow_backend=str(state.intermediate_results.get("workflow_backend", WORKFLOW_BACKEND_RULE_BASED)),
        playbook_id=state.selected_playbook_id,
        playbook_parameters=state.playbook_parameters,
        column_mapping=state.column_mapping,
        route_taken=list(state.route_taken),
        reviewer_status=str(reviewer_dict.get("status", state.reviewer_status or "PENDING")),
        reviewer_score=int(reviewer_dict.get("score", 0) or 0),
        caveats=list(state.caveats),
        errors=list(state.errors),
        semantic_model_id=str(state.semantic_model.get("model_id")) if state.semantic_model else None,
        catalog_fingerprint=str(state.semantic_catalog.get("fingerprint")) if state.semantic_catalog.get("fingerprint") else None,
        metric_request=state.metric_request,
        query_plan_id=str(state.query_plan.get("plan_id")) if state.query_plan else None,
        join_plan_id=str(state.join_plan.get("plan_id")) if state.join_plan else None,
        plan_review=state.plan_review,
        contract_summary={
            "check_count": len(state.contract_results),
            "failed_count": sum(item.get("status") == "FAIL" for item in state.contract_results),
            "warning_count": sum(item.get("status") == "WARN" for item in state.contract_results),
        },
        lineage_summary={
            "dataset_count": len(state.lineage.get("datasets", [])),
            "operation_count": len(state.lineage.get("operations", [])),
            "edge_count": len(state.lineage.get("edges", [])),
            "lineage_fingerprint": state.lineage.get("lineage_fingerprint"),
        },
        telemetry_summary=state.telemetry.get("summary", {}),
        evaluation_summary=state.evaluation_summary,
    )
    state.run_manifest = manifest.to_dict()
    state.intermediate_results["run_manifest_object"] = manifest
    return state


def _refresh_manifest_reviewer(state: WorkflowState) -> None:
    reviewer = state.intermediate_results.get("reviewer", {})
    manifest = state.intermediate_results.get("run_manifest_object")
    if not isinstance(manifest, RunManifest) or not isinstance(reviewer, dict):
        return
    manifest.reviewer_status = str(reviewer.get("status", "UNKNOWN"))
    manifest.reviewer_score = int(reviewer.get("score", 0) or 0)
    manifest.route_taken = list(state.route_taken)
    manifest.caveats = list(state.caveats)
    manifest.errors = list(state.errors)
    state.run_manifest = manifest.to_dict()


def _route_from_plan(state: WorkflowState) -> str:
    goal_mode = state.goal_mode
    intent = state.intent
    if goal_mode == "metric_diagnosis" or intent == "metric_drop_diagnosis":
        return "metric_diagnosis"
    if goal_mode == "growth_trend" or intent == "metric_growth_analysis":
        return "growth_trend"
    if goal_mode == "experiment_analysis" or intent == "experiment_analysis":
        return "experiment_analysis"
    if goal_mode == "content_performance" or intent == "content_performance_analysis":
        return "content_performance"
    if goal_mode == "live_quality" or intent == "live_quality_analysis":
        return "live_quality"
    if goal_mode == "causal_exploration" or intent == "causal_exploration":
        return "causal_exploration"
    return "periodic_report"


def _run_metric_diagnosis_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_metric_diagnosis")
    if _table_missing(state, tables, ["daily_metrics"], "metric_diagnosis"):
        return state

    plan = AnalysisPlan(**state.analysis_plan)
    metric = _first_metric(plan, tables["daily_metrics"], "orders")
    city_filter = None
    where_clause = ""
    if any(term in state.user_question for term in ("城市", "South", "北城", "南城")):
        _append_unique(state.caveats, ["本次城市问题按所有城市比较，不从自然语言静默选择城市；如需单城请使用明确筛选后的数据。 "])
    aggregate = "COUNT(DISTINCT user_id)" if metric == "active_users" and "transaction_detail" in tables else metric_aggregate_sql(metric, set(tables["daily_metrics"].columns), "mean" if metric.endswith("_rate") or metric in {"ctr", "cvr"} else "sum")
    query = f"SELECT date, {aggregate} AS {metric} FROM daily_metrics {where_clause} GROUP BY date ORDER BY date"
    if metric == "active_users" and "transaction_detail" in tables:
        query = query.replace("FROM daily_metrics", "FROM transaction_detail")
        _append_unique(state.caveats, ["支付活跃用户按支付明细user_id逐日去重，不代表全站访问UV；不能累加各维度UV。 "])
    metric_frame = _run_query(
        engine,
        query,
        state,
        "metric_diagnosis_daily_metric",
        lambda: _daily_metric_frame(tables, metric, city_filter),
    )
    state.add_route("run_anomaly")
    anomaly = detect_metric_anomaly(metric_frame, metric) if not metric_frame.empty else {}

    state.add_route("run_attribution")
    contributions: dict[str, list[dict[str, object]]] = {}
    for dimension in [dim for dim in plan.dimensions if dim in tables["daily_metrics"].columns and metric != "active_users"]:
        contribution = dimension_contribution(tables["daily_metrics"], metric, dimension)
        contributions[dimension] = contribution.head(5).to_dict(orient="records")

    top_city = contributions.get("city", [{}])[0].get("dimension_value", "unknown")
    findings = [
        (
            f"{metric} 当前值为 {float(anomaly.get('current_value', 0.0)):.2f}，相对前 7 日均值 "
            f"{float(anomaly.get('baseline_value', 0.0)):.2f} 变化 "
            f"{float(anomaly.get('relative_change', 0.0)):.2%}，severity={anomaly.get('severity', 'UNKNOWN')}。"
        ),
        f"维度贡献排序显示 {top_city} 是主要变化来源之一，建议优先复核该维度的流量与转化链路。",
        "订单类问题建议按曝光、点击率、转化率、支付成功率逐层拆解，避免只看单一结果指标。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "优先查看高贡献城市、渠道和设备的曝光与点击率变化。",
        "对支付成功率和转化率做分层复核，确认是否为局部链路波动。",
    ]
    _set_node_outputs(
        state,
        summary=f"{metric} 波动诊断已完成，包含异常检测和维度归因。",
        findings=findings,
        artifacts={"anomaly": anomaly, "contributions": contributions},
        next_steps=next_steps,
    )
    return state


def _run_growth_trend_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_growth_trend")
    if _table_missing(state, tables, ["daily_metrics"], "growth_trend"):
        return state

    plan = AnalysisPlan(**state.analysis_plan)
    metric = _first_metric(plan, tables["daily_metrics"], "active_users")
    state.add_route("run_trend_summary")
    aggregate = "COUNT(DISTINCT user_id)" if metric == "active_users" and "transaction_detail" in tables else metric_aggregate_sql(metric, set(tables["daily_metrics"].columns), "mean" if metric.endswith("_rate") or metric in {"ctr", "cvr"} else "sum")
    query = f"SELECT date, {aggregate} AS {metric} FROM daily_metrics GROUP BY date ORDER BY date"
    if metric == "active_users" and "transaction_detail" in tables:
        query = query.replace("FROM daily_metrics", "FROM transaction_detail")
        _append_unique(state.caveats, ["支付活跃用户按支付明细user_id逐日去重，不代表全站访问UV；不能累加各维度UV。 "])
    metric_frame = _run_query(
        engine,
        query,
        state,
        "growth_trend_daily_metric",
        lambda: _daily_metric_frame(tables, metric),
    )
    state.add_route("run_anomaly")
    anomaly = detect_metric_anomaly(metric_frame, metric) if not metric_frame.empty else {}
    relative_change = float(anomaly.get("relative_change", 0.0))
    findings = [
        f"{metric} 相对前 7 日均值变化 {relative_change:.2%}，用于判断 synthetic 趋势方向。",
        "增长/趋势分析当前采用描述性趋势摘要，并保留异常检测作为辅助信号。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "按 city、channel、user_segment 等维度拆解趋势来源。",
        "补充更长时间窗的 synthetic 回放，确认趋势是否稳定。",
    ]
    _set_node_outputs(
        state,
        summary=f"{metric} 趋势摘要已完成。",
        findings=findings,
        artifacts={"trend_change": anomaly},
        next_steps=next_steps,
        caveats=["growth_trend 当前以描述性趋势和异常检测为主，未输出真实预测结论。"],
    )
    return state


def _run_experiment_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_experiment_analysis")
    if _table_missing(state, tables, ["experiments"], "experiment_analysis"):
        return state

    experiments = tables["experiments"]
    state.add_route("run_experiment")
    _record_operation(
        state,
        "experiment_ab_test",
        "analyze_ab_test(experiments, group, completion_rate, mean)",
        len(experiments),
    )
    ab_result = analyze_ab_test(experiments, "group", "completion_rate", metric_type="mean")

    strata = (
        experiments.groupby(["user_segment", "group"])["completion_rate"]
        .mean()
        .unstack("group")
        .assign(lift=lambda frame: frame["treatment"] - frame["control"])
        .reset_index()
    )
    sample_size = ab_result["sample_size"]
    findings = [
        (
            f"实验组完播率为 {float(ab_result['treatment_mean']):.2%}，对照组为 "
            f"{float(ab_result['control_mean']):.2%}，相对 lift 为 {float(ab_result['relative_lift']):.2%}。"
        ),
        f"实验样本量：对照组 {sample_size['control']:,}，实验组 {sample_size['treatment']:,}。",
        f"显著性检验：p-value={float(ab_result['p_value']):.3g}，95% 置信区间={ab_result['confidence_interval']}。",
        str(ab_result["conclusion"]),
        REPORT_LIMITATION,
    ]
    next_steps = [
        "继续观察分层效果是否稳定，尤其是样本较小的用户分层。",
        "补充更长周期的 synthetic 回放和稳定性检查。",
    ]
    _set_node_outputs(
        state,
        summary="A/B 实验评估已完成，包含独立样本量、Welch 检验及绝对差置信区间。",
        findings=findings,
        artifacts={
            "ab_test": ab_result,
            "strata": strata.round(6).to_dict(orient="records"),
        },
        next_steps=next_steps,
    )
    return state


def _run_content_performance_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_content_performance")
    if _table_missing(state, tables, ["content_events"], "content_performance"):
        return state

    content_events = tables["content_events"]
    state.add_route("run_content_performance")
    _record_operation(state, "content_performance_summary", "group content_events by content_category", len(content_events))
    summary = (
        content_events.groupby("content_category")
        .agg(
            events=("event_id", "count"),
            completion_rate=("completion_rate", "mean"),
            watch_time=("watch_time", "mean"),
            retention_rate=("retention_rate", "mean"),
        )
        .reset_index()
        .sort_values("completion_rate", ascending=False)
    )
    top = summary.iloc[0].to_dict()
    low = summary.iloc[-1].to_dict()
    findings = [
        f"{top['content_category']} 的完播率最高，均值约 {float(top['completion_rate']):.4f}。",
        f"{low['content_category']} 的完播率较低，建议查看内容长度、设备和用户分层差异。",
        "内容分析适合先看完播率、观看时长和留存相关指标，再进入实验或归因分析。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "对低完播内容类型按设备和用户分层继续拆解。",
        "结合 experiments 表验证策略变化是否带来稳定提升。",
    ]
    artifacts: dict[str, Any] = {"content_summary": summary.round(6).to_dict(orient="records")}
    if "experiments" in tables:
        state.add_route("run_experiment_optional")
        _record_operation(
            state,
            "content_optional_experiment",
            "analyze_ab_test(experiments, group, completion_rate, mean)",
            len(tables["experiments"]),
        )
        artifacts["optional_ab_test"] = analyze_ab_test(tables["experiments"], "group", "completion_rate", metric_type="mean")
    _set_node_outputs(
        state,
        summary="内容表现摘要已完成，包含内容类型表现和可选实验摘要。",
        findings=findings,
        artifacts=artifacts,
        next_steps=next_steps,
        caveats=["content_performance 当前以描述性分层为主，策略效果仍需实验或更长周期验证。"],
    )
    return state


def _run_live_quality_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_live_quality")
    required = ["live_quality_logs", "live_sessions", "live_interactions"]
    if _table_missing(state, tables, required, "live_quality"):
        return state

    plan = AnalysisPlan(**state.analysis_plan)
    quality = tables["live_quality_logs"]
    sessions = tables["live_sessions"]
    interactions = tables["live_interactions"]
    state.add_route("run_live_quality")
    _record_operation(state, "live_stutter_anomaly", "detect stutter_rate anomaly from live_quality_logs", len(quality))
    stutter = detect_metric_anomaly(quality, "stutter_rate")
    _record_operation(state, "live_watch_time_change", "detect watch_time change from live_sessions", len(sessions))
    watch_time = detect_metric_anomaly(sessions, "watch_time")
    _record_operation(state, "live_interaction_change", "detect interaction_rate change from live_interactions", len(interactions))
    interaction_rate = detect_metric_anomaly(interactions, "interaction_rate")

    state.add_route("run_attribution")
    contributions: dict[str, list[dict[str, object]]] = {}
    for dimension in [dim for dim in plan.dimensions if dim in quality.columns]:
        contribution = dimension_contribution(quality, "stutter_rate", dimension)
        contributions[dimension] = contribution.head(5).to_dict(orient="records")
    top_device = contributions.get("device", [{}])[0].get("dimension_value", "unknown")
    top_network = contributions.get("network_type", [{}])[0].get("dimension_value", "unknown")
    findings = [
        f"卡顿率相对前 7 日均值变化 {float(stutter['relative_change']):.2%}，需要按体验风险理解该上升信号。",
        (
            f"观看时长变化 {float(watch_time['relative_change']):.2%}，"
            f"互动率变化 {float(interaction_rate['relative_change']):.2%}。"
        ),
        f"贡献排序显示 {top_device} 与 {top_network} 是优先排查维度。",
        "体验质量问题建议同时观察设备、网络类型、地区和时段，避免把相关性直接解释为因果。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "优先复核高贡献设备和网络类型在目标日期的质量日志。",
        "对卡顿率与停留变化做更细时段回放，确认是否持续出现。",
    ]
    _set_node_outputs(
        state,
        summary="体验质量分析已完成，包含卡顿、停留、互动和归因维度。",
        findings=findings,
        artifacts={
            "stutter_anomaly": stutter,
            "watch_time_change": watch_time,
            "interaction_rate_change": interaction_rate,
            "contributions": contributions,
        },
        next_steps=next_steps,
    )
    return state


def _run_causal_exploration_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_causal_exploration")
    if _table_missing(state, tables, ["experiments"], "causal_exploration"):
        return state

    experiments = tables["experiments"]
    state.add_route("run_causal_light")
    state.selected_metrics = ["completion_rate"]
    _record_operation(
        state,
        "causal_light_adjusted_effect",
        "estimate_adjusted_effect(experiments, group, completion_rate, covariates)",
        len(experiments),
    )
    effect = estimate_adjusted_effect(
        experiments,
        "group",
        "completion_rate",
        ["historical_activity", "historical_revenue", "city", "channel", "user_segment"],
    )
    findings = [
        (
            f"naive difference={float(effect['naive_difference']):.4f}，"
            f"regression adjusted effect={float(effect['adjusted_effect']):.4f}。"
        ),
        (
            f"倾向评分加权默认关闭；"
            f"sample_size={effect['sample_size']}。"
        ),
        "轻量因果探索仅用于形成分析假设，不能把相关性直接解释为因果关系。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "补充更明确的处理机制、时间顺序和混杂变量检查。",
        "将探索性结果作为后续更严格评估设计的输入。",
    ]
    _set_node_outputs(
        state,
        summary="轻量因果探索已完成，结果仅作为假设生成输入。",
        findings=findings,
        artifacts={"causal_light": effect},
        next_steps=next_steps,
        caveats=[str(item) for item in effect.get("caveats", [])],
    )
    return state


def _run_periodic_report_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("route_periodic_report")
    if _table_missing(state, tables, ["daily_metrics"], "periodic_report"):
        return state

    plan = AnalysisPlan(**state.analysis_plan)
    daily = tables["daily_metrics"]
    metric = _first_metric(plan, daily, "active_users")
    state.add_route("run_periodic_report")
    aggregate = "COUNT(DISTINCT user_id)" if metric == "active_users" and "transaction_detail" in tables else metric_aggregate_sql(metric, set(tables["daily_metrics"].columns), "mean" if metric.endswith("_rate") or metric in {"ctr", "cvr"} else "sum")
    query = f"SELECT date, {aggregate} AS {metric} FROM daily_metrics GROUP BY date ORDER BY date"
    summary_frame = _run_query(
        engine,
        query,
        state,
        "periodic_report_metric_summary",
        lambda: _daily_metric_frame(tables, metric),
    )
    anomaly = detect_metric_anomaly(summary_frame, metric) if not summary_frame.empty else {}
    findings = [
        f"{metric} 当前值为 {float(anomaly.get('current_value', 0.0)):.2f}，相对前 7 日均值变化 {float(anomaly.get('relative_change', 0.0)):.2%}。",
        "当前为基础描述性汇总，如需诊断可补充更明确的目标指标和维度。",
        REPORT_LIMITATION,
    ]
    next_steps = ["明确目标指标、时间窗口和优先维度后，可进一步做归因或实验分析。"]
    _set_node_outputs(
        state,
        summary="周期性描述报告已完成。",
        findings=findings,
        artifacts={"summary_change": anomaly},
        next_steps=next_steps,
    )
    return state


def _profile_custom_tables(state: WorkflowState, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for table_name, df in tables.items():
        mapping = _mapping_for_table(state, table_name, df)
        profiles[table_name] = {
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": [str(column) for column in df.columns],
            "numeric_columns": mapping.get("detected_numeric_columns", []),
            "date_columns": mapping.get("detected_date_columns", []),
            "categorical_columns": mapping.get("detected_categorical_columns", []),
            "warnings": state.table_metadata.get(table_name, {}).get("warnings", []),
        }
    return profiles


def _custom_date_metric_frame(df: pd.DataFrame, date_col: str, metric_col: str, time_grain: str = "day", aggregation: str = "sum") -> pd.DataFrame:
    pair=metric_components(metric_col,df.columns)
    working = df.loc[:,list(dict.fromkeys([date_col,metric_col,*(pair or ())]))].copy()
    working[date_col] = pd.to_datetime(working[date_col], errors="coerce")
    if aggregation != "count_distinct":
        working[metric_col] = pd.to_numeric(working[metric_col], errors="coerce")
    working = working.dropna(subset=[date_col, metric_col])
    if time_grain == "week":
        working[date_col] = working[date_col].dt.to_period("W").dt.start_time
    elif time_grain == "month":
        working[date_col] = working[date_col].dt.to_period("M").dt.to_timestamp()
    pair = metric_components(metric_col, working.columns)
    if pair:
        numerator, denominator = pair
        result = working.groupby(date_col, as_index=False)[[numerator, denominator]].sum()
        result[metric_col] = result[numerator] / result[denominator].replace(0, float("nan"))
        return result[[date_col, metric_col]].sort_values(date_col)
    if metric_col.endswith("_rate") or metric_col in {"ctr", "cvr"}:
        if aggregation != "mean":
            raise ValueError("比率缺少分子分母，不能求和，请明确等权单位后选择 mean。")
    return working.groupby(date_col, as_index=False)[metric_col].agg("nunique" if aggregation == "count_distinct" else aggregation).sort_values(date_col)


def _find_experiment_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    group_col: str | None = None
    metric_col: str | None = None
    for column in df.columns:
        values = set(df[column].dropna().astype(str).str.lower().unique())
        if {"control", "treatment"}.issubset(values):
            group_col = str(column)
            break
    for column in df.columns:
        if pd.api.types.is_numeric_dtype(df[column]) and str(column) != group_col:
            metric_col = str(column)
            break
    return group_col, metric_col


def _run_generic_analysis_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("generic_analysis_fallback")
    profiles = _profile_custom_tables(state, tables)
    applied_mapping = _column_mapping_from_state(state)
    selected = _select_mapping_table(state, tables, applied_mapping.table_name)
    if selected is None:
        state.errors.append("No tables available for custom data workflow.")
        _set_node_outputs(
            state,
            summary="没有可用表，无法执行自定义数据分析。",
            findings=["没有可用表，请先上传 CSV/Excel 或加载数据库查询结果。", REPORT_LIMITATION],
            artifacts={"table_profiles": profiles},
            next_steps=["提供至少一张包含可分析字段的表。"],
            caveats=CUSTOM_DATA_CAVEATS,
        )
        return state

    table_name, df = selected
    schema_mapping = _mapping_for_table(state, table_name, df)
    date_columns = [applied_mapping.date_column] if applied_mapping.date_column else list(schema_mapping.get("detected_date_columns", []))
    metric_columns = applied_mapping.metric_columns or list(
        schema_mapping.get("possible_metric_columns") or schema_mapping.get("detected_numeric_columns", [])
    )
    dimension_columns = applied_mapping.dimension_columns or list(
        schema_mapping.get("possible_dimension_columns") or schema_mapping.get("detected_categorical_columns", [])
    )
    if state.mapping_source == "user_selected":
        date_columns = [applied_mapping.date_column] if applied_mapping.date_column else []
        metric_columns = list(applied_mapping.metric_columns)
        dimension_columns = list(applied_mapping.dimension_columns)
    route = _route_from_plan(state)
    findings: list[str] = [
        f"数据来源为 {state.data_source_type}，当前使用表 {table_name}（{len(df)} 行，{len(df.columns)} 列）进行通用分析。",
        f"字段映射来源为 {state.mapping_source}，优先使用已应用的 Column Mapping。",
    ]
    next_steps = [
        "如需更稳定的诊断，请明确日期列、指标列和优先维度字段。",
        "复核上传文件或数据库查询结果的字段口径、缺失率和时间范围。",
    ]
    artifacts: dict[str, Any] = {"table_profiles": profiles, "selected_table": table_name}
    caveats = list(CUSTOM_DATA_CAVEATS)

    if route in {"metric_diagnosis", "growth_trend", "periodic_report"}:
        if date_columns and metric_columns:
            date_col = date_columns[0]
            metric_col = metric_columns[0]
            state.add_route("run_generic_trend")
            metric_frame = _custom_date_metric_frame(df, date_col, metric_col, applied_mapping.time_grain, applied_mapping.aggregation)
            state.intermediate_results.setdefault("result_tables", {})["metric_trend"] = metric_frame.copy()
            artifacts["generic_trend"] = _round_value(metric_frame.tail(20).to_dict(orient="records"))
            if len(metric_frame) >= 8:
                state.add_route("run_generic_anomaly")
                anomaly = detect_metric_anomaly(metric_frame, metric_col, date_col=date_col)
                artifacts["generic_anomaly"] = _round_value(anomaly)
                state.intermediate_results.setdefault("result_tables", {})["anomalies"] = pd.DataFrame([anomaly])
                findings.append(
                    f"{metric_col} 最新日期相对前 7 日均值变化 {float(anomaly['relative_change']):.2%}，severity={anomaly['severity']}。"
                )
            else:
                findings.append(f"{metric_col} 已按 {date_col} 聚合，但可用日期少于 8 个，暂不输出异常结论。")
                caveats.append("日期样本不足，异常检测退化为趋势摘要。")
            if dimension_columns:
                findings.append(f"可作为后续拆解的候选维度包括：{', '.join(dimension_columns[:5])}。")
                if route == "metric_diagnosis":
                    state.add_route("run_generic_dimension_breakdown")
                    breakdowns: dict[str, Any] = {}
                    for dimension in dimension_columns[:3]:
                        try:
                            contribution = dimension_contribution(df, metric_col, dimension, date_col=date_col, aggregation=applied_mapping.aggregation)
                            breakdowns[dimension] = contribution.head(5).to_dict(orient="records")
                            state.intermediate_results.setdefault("result_tables", {})[f"dimension_{dimension}"] = contribution.copy()
                        except Exception as exc:
                            state.mapping_warnings.append(f"维度 {dimension} 拆解失败：{exc}")
                    if breakdowns:
                        artifacts["generic_dimension_breakdown"] = _round_value(breakdowns)
        else:
            if metric_columns:
                state.add_route("run_generic_metric_summary")
                summary: dict[str, Any] = {}
                for metric_col in metric_columns[:5]:
                    numeric = pd.to_numeric(df[metric_col], errors="coerce").dropna()
                    if not numeric.empty:
                        summary[metric_col] = {
                            "count": int(numeric.count()),
                            "mean": float(numeric.mean()),
                            "min": float(numeric.min()),
                            "max": float(numeric.max()),
                        }
                artifacts["generic_metric_summary"] = _round_value(summary)
                state.intermediate_results.setdefault("result_tables", {})["metric_summary"] = pd.DataFrame.from_dict(summary, orient="index").reset_index(names="metric")
                findings.append("未选择日期列，已根据 metric_columns 输出指标摘要。")
                caveats.append("缺少 date_column，无法执行时间趋势或异常检测。")
            else:
                findings.append("未同时识别到日期列和数值指标列，已退化为表结构 profile 摘要。")
                caveats.append("需要指定日期列和数值指标列后才能执行通用趋势或异常检测。")
    elif route == "experiment_analysis":
        group_col = applied_mapping.group_column
        metric_col = next(iter(applied_mapping.metric_columns), None)
        if not (group_col and metric_col):
            group_col, metric_col = _find_experiment_columns(df)
        if group_col and metric_col:
            state.add_route("run_generic_experiment")
            control = state.playbook_parameters.get("control_value", "control")
            treatment = state.playbook_parameters.get("treatment_value", "treatment")
            values = set(df[group_col].dropna().unique())
            if {control, treatment}.issubset(values):
                unit = state.playbook_parameters.get("statistical_unit") or applied_mapping.statistical_unit
                ab_result = analyze_ab_test(df, group_col, metric_col, metric_type=str(state.playbook_parameters.get("metric_type", "mean")),
                    statistical_unit=unit, control_value=control, treatment_value=treatment,
                    confidence_level=float(state.playbook_parameters.get("confidence_level", .95)))
                artifacts["generic_ab_test"] = _round_value(ab_result)
                findings.extend(
                    [
                        f"识别到实验分组字段 {group_col} 和指标字段 {metric_col}。",
                        f"p_value={float(ab_result['p_value']):.3g}，sample_size={ab_result['sample_size']}。",
                        str(ab_result["conclusion"]),
                    ]
                )
            else:
                state.errors.append("所选对照值/实验值不同时存在于分组列；请修正明确分组配置，未执行显著性检验。")
                caveats.append(state.errors[-1])
        else:
            findings.append("未识别到包含 control/treatment 的分组字段和数值指标，无法执行通用实验评估。")
            caveats.append("实验分析需要明确 group 字段且包含 control/treatment，以及一个数值 outcome 字段。")
    elif route == "causal_exploration":
        if applied_mapping.treatment_column and applied_mapping.outcome_column:
            state.add_route("run_generic_causal_light")
            covariates = [
                column
                for column in (applied_mapping.covariates or dimension_columns[:5])
                if column not in {applied_mapping.treatment_column, applied_mapping.outcome_column}
            ]
            if covariates:
                try:
                    effect = estimate_adjusted_effect(
                        df,
                        applied_mapping.treatment_column,
                        applied_mapping.outcome_column,
                        covariates,
                    )
                    artifacts["generic_causal_light"] = _round_value(effect)
                    findings.append(
                        f"使用 treatment={applied_mapping.treatment_column} 和 outcome={applied_mapping.outcome_column} 完成轻量因果探索。"
                    )
                    findings.append(
                        f"adjusted_effect={float(effect['adjusted_effect']):.4f}，sample_size={effect['sample_size']}。"
                    )
                    caveats.extend(str(item) for item in effect.get("caveats", []))
                except Exception as exc:
                    findings.append("已识别 treatment/outcome，但轻量因果估计执行失败，已退化为 schema profile。")
                    caveats.append(f"轻量因果估计失败：{exc}")
            else:
                findings.append("已识别 treatment/outcome，但缺少控制变量，暂不执行轻量因果估计。")
                caveats.append("causal_exploration 建议至少选择一个维度或控制变量字段。")
        else:
            findings.append("自定义数据的轻量因果探索需要明确 treatment、outcome 和控制变量，当前仅输出 schema profile。")
            caveats.append("未指定 treatment/outcome 字段时，不执行轻量因果估计，避免误读相关性。")
    else:
        findings.append("当前目标模式缺少标准 demo 字段，已转为通用表结构和字段候选摘要。")
        if metric_columns:
            findings.append(f"候选指标字段：{', '.join(metric_columns[:5])}。")
        if dimension_columns:
            findings.append(f"候选维度字段：{', '.join(dimension_columns[:5])}。")

    findings.append(CUSTOM_REPORT_LIMITATION)
    _set_node_outputs(
        state,
        summary="自定义数据通用分析已完成。",
        findings=findings,
        artifacts=artifacts,
        next_steps=next_steps,
        caveats=caveats,
    )
    return state


def _review_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("review")
    trace = _build_trace_from_state(state)
    review = review_analysis(trace)
    state.reviewer_status = review.status
    state.reviewer_issues = review.issues
    state.reviewer_suggestions = review.suggestions
    state.intermediate_results["reviewer"] = review.to_dict()
    _refresh_manifest_reviewer(state)
    return state


def _build_analysis_results_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    """Normalize routed and playbook output into one structured result contract."""

    del engine
    state.add_route("build_analysis_results")
    if state.planning_status != "ready":
        status = {"needs_clarification": "NEEDS_INPUT", "unsupported": "UNSUPPORTED", "invalid_input": "INVALID_INPUT"}[state.planning_status]
        package = AnalysisResultPackage(run_id=state.trace_id, scenario="planning", question=state.user_question,
            executive_summary=state.intermediate_results.get("summary", "请补充输入。"), execution_status=status,
            metadata={"planning_status": state.planning_status})
        state.analysis_result_package = package.to_dict_summary()
        return state
    if state.execution_mode == "plan_only":
        package = AnalysisResultPackage(
            run_id=state.trace_id,
            scenario="plan_only",
            question=state.user_question,
            executive_summary="方案校验失败，未执行实际计算，请修正输入。" if state.errors else "当前仅展示分析方案，尚未执行实际计算。",
            caveats=[str(item) for item in state.caveats],
            metadata={"execution_mode": "plan_only"},
            execution_status="FAILED" if state.errors else "PREVIEW",
        )
        state.analysis_result_package = package.to_dict_summary()
        state.intermediate_results["summary"] = package.executive_summary
        state.findings = [package.executive_summary]
        return state
    if "needs_input" in state.route_taken:
        state.analysis_result_package = AnalysisResultPackage(run_id=state.trace_id, scenario="needs_input", question=state.user_question, executive_summary=state.intermediate_results.get("summary", "请补充输入。"), execution_status="NEEDS_INPUT").to_dict_summary()
        return state
    if state.selected_playbook_id == "semantic_metric_query" and state.plan_review.get("decision") != "approved":
        state.analysis_result_package = AnalysisResultPackage(run_id=state.trace_id, scenario="semantic", question=state.user_question, executive_summary=state.plan_review.get("reason", "等待方案审批。"), execution_status="WAITING_APPROVAL" if state.plan_review.get("decision") == "pending" else "FAILED").to_dict_summary()
        return state
    existing_findings = list(state.findings)
    with trace_stage("statistics_result_package",table_count=len(tables)):
        package = build_analysis_result_package(state, tables)
    if state.errors:
        package.execution_status = "FAILED"
    elif not package.has_structured_results() or ((state.selected_playbook_id == "experiment_comparison" or not state.selected_playbook_id and state.goal_mode == "experiment_analysis") and not package.experiment_results):
        package.execution_status = "NEEDS_INPUT"
    if not state.chart_specs and package.execution_status == "COMPLETED":
        from insightpilot.visualization.result_charts import build_result_chart_specs
        state.chart_specs=[spec.to_dict() for spec in build_result_chart_specs(package.result_tables)]
        package.chart_specs=list(state.chart_specs)
        if state.presentation_mode == "eager":
            with trace_stage("chart_construction",chart_count=len(state.chart_specs)):
                chart_pairs=build_charts(state.chart_specs,package.result_tables)
            state.intermediate_results["charts"]=[figure for _,figure in chart_pairs]
    validation_issues = package.validate()
    if validation_issues:
        _append_unique(state.caveats, [f"结构化结果校验提示：{item}" for item in validation_issues])
    state.analysis_result_package = package.to_dict_summary()
    state.intermediate_results["result_tables"] = package.result_tables
    state.intermediate_results["analysis_result_package"] = state.analysis_result_package
    state.intermediate_results["summary"] = package.executive_summary
    state.findings = deduplicate_findings(
        package.executive_summary,
        [*findings_from_package(package), *existing_findings],
    )
    state.intermediate_results["next_steps"] = [item.action for item in package.recommendations]
    return state


def _preview_analysis_plan_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    del tables, engine
    state.add_route("preview_analysis_plan")
    return state


def _report_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("generate_report")
    result = _build_result_from_state(state)
    result["report_markdown"] = generate_markdown_report(result) if state.presentation_mode == "eager" and state.planning_status == "ready" else ""
    state.intermediate_results["result"] = result
    return state


def _build_trace_from_state(state: WorkflowState) -> AnalysisTrace:
    reviewer_payload = state.intermediate_results.get("reviewer", {})
    return AnalysisTrace(
        trace_id=state.trace_id,
        created_at=state.created_at,
        workflow_backend=str(state.intermediate_results.get("workflow_backend", WORKFLOW_BACKEND_RULE_BASED)),
        user_question=state.user_question,
        goal_mode=state.goal_mode,
        goal_mode_display_name=state.goal_mode_display_name,
        goal_mode_source=state.goal_mode_source,
        data_source_type=state.data_source_type,
        table_metadata_summary=_summarize_table_metadata(state.table_metadata),
        schema_warnings=state.schema_warnings,
        column_mapping=state.column_mapping,
        mapping_warnings=state.mapping_warnings,
        mapping_source=state.mapping_source,
        selected_playbook_id=state.selected_playbook_id,
        playbook_source=state.playbook_source,
        playbook_parameters_summary=state.playbook_parameters,
        chart_specs=state.chart_specs,
        manifest_summary={
            "run_id": state.run_manifest.get("run_id"),
            "manifest_version": state.run_manifest.get("manifest_version"),
            "project_version": state.run_manifest.get("project_version"),
            "dataset_fingerprint_count": len(state.run_manifest.get("dataset_fingerprints", {})),
        } if state.run_manifest else {},
        playbook_result_summary=state.intermediate_results.get("playbook_result", {}),
        identified_intent=state.intent,
        selected_metrics=state.selected_metrics,
        analysis_plan=state.analysis_plan,
        executed_queries=state.executed_queries,
        route_taken=state.route_taken,
        generated_findings=state.findings,
        caveats=state.caveats,
        reviewer_checks=reviewer_payload if isinstance(reviewer_payload, dict) else {},
        errors=state.errors,
        semantic_model_summary=state.semantic_model,
        metric_request=state.metric_request,
        join_plan_summary=state.join_plan,
        query_plan_summary=state.query_plan,
        plan_review=state.plan_review,
        contract_summary={
            "check_count": len(state.contract_results),
            "failed_count": sum(item.get("status") == "FAIL" for item in state.contract_results),
            "warning_count": sum(item.get("status") == "WARN" for item in state.contract_results),
        },
        lineage_summary={
            "dataset_count": len(state.lineage.get("datasets", [])),
            "operation_count": len(state.lineage.get("operations", [])),
            "edge_count": len(state.lineage.get("edges", [])),
            "lineage_fingerprint": state.lineage.get("lineage_fingerprint"),
        },
        observability_summary=state.telemetry.get("summary", {}),
        evaluation_summary=state.evaluation_summary,
        analysis_result_summary=state.analysis_result_package,
    )


def _build_result_from_state(state: WorkflowState) -> dict[str, Any]:
    metrics = state.intermediate_results.get("metrics", [])
    reviewer = state.intermediate_results.get("reviewer", {})
    trace = _build_trace_from_state(state)
    trace_dict = trace.to_dict()
    workflow_backend = str(state.intermediate_results.get("workflow_backend", WORKFLOW_BACKEND_RULE_BASED))
    return {
        "execution_status": state.analysis_result_package.get("execution_status", "NEEDS_INPUT"),
        "planning_status": state.planning_status,
        "analysis_advice": state.intermediate_results.get("analysis_advice", {}),
        "preflight": state.intermediate_results.get("preflight", {}),
        "clarification": state.clarification,
        "metric_definitions": state.metric_definitions,
        "semantic_fingerprint": state.semantic_fingerprint,
        "presentation_fingerprint": state.presentation_fingerprint,
        "question": state.user_question,
        "summary": state.intermediate_results.get("summary", ""),
        "intent": state.intent,
        "goal_mode": state.goal_mode,
        "goal_mode_display_name": state.goal_mode_display_name,
        "goal_mode_source": state.goal_mode_source,
        "metrics": metrics,
        "plan": state.analysis_plan,
        "findings": state.findings,
        "caveats": state.caveats,
        "reviewer": reviewer,
        "trace": trace_dict,
        "artifacts": state.intermediate_results.get("artifacts", {}),
        "limitations": state.caveats,
        "next_steps": state.intermediate_results.get("next_steps", []),
        "workflow_backend": workflow_backend,
        "presentation_mode": state.presentation_mode,
        "route_taken": state.route_taken,
        "errors": state.errors,
        "data_source_type": state.data_source_type,
        "table_metadata": _summarize_table_metadata(state.table_metadata),
        "schema_warnings": state.schema_warnings,
        "user_table_mode": state.user_table_mode,
        "column_mapping": state.column_mapping,
        "mapping_warnings": state.mapping_warnings,
        "mapping_source": state.mapping_source,
        "selected_playbook": (
            state.intermediate_results.get("selected_playbook")
            if isinstance(state.intermediate_results.get("selected_playbook"), dict)
            else None
        ),
        "playbook_source": state.playbook_source,
        "playbook_parameters": state.playbook_parameters,
        "playbook_result": state.intermediate_results.get("playbook_result"),
        "result_tables": state.intermediate_results.get("result_tables", {}),
        "chart_specs": state.chart_specs,
        "charts": state.intermediate_results.get("charts", []),
        "run_manifest": state.run_manifest,
        "export_formats": state.export_formats,
        "semantic_model": state.semantic_model,
        "semantic_catalog": state.semantic_catalog,
        "metric_request": sanitize_manifest_value(state.metric_request),
        "relationship_graph": state.relationship_graph,
        "join_plan": state.join_plan,
        "query_plan": state.query_plan,
        "plan_review": state.plan_review,
        "execution_mode": state.execution_mode,
        "contract_results": state.contract_results,
        "lineage": state.lineage,
        "telemetry": state.telemetry,
        "evaluation": state.evaluation_summary,
        "analysis_result_package": state.analysis_result_package,
        "workflow_state": state.to_dict(),
    }


def _scope_analysis_tables(state: WorkflowState, tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Apply an explicitly selected inclusive date window to date-bearing inputs.

    Source snapshots/manifest fingerprints remain the original dataset; the filter
    is part of the request and definition fingerprint. No work occurs on browsing.
    """
    window = state.playbook_parameters.get("date_range")
    if not window or state.selected_playbook_id:
        return tables  # Playbooks already apply their own declared date window.
    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1]) + pd.Timedelta(days=1)
    selected = state.column_mapping.get("table_name")
    result = dict(tables)
    for name, frame in tables.items():
        date_column = state.column_mapping.get("date_column") if name == selected else "date"
        if date_column and date_column in frame:
            cancellation_checkpoint()
            dates = pd.to_datetime(frame[date_column], errors="coerce")
            result[name] = frame.loc[(dates >= start) & (dates < end)]
    return result


def _run_routed_analysis(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None,
) -> WorkflowState:
    if state.planning_status != "ready":
        return state
    if state.user_table_mode:
        return _run_generic_analysis_node(state, tables, engine)
    if not state.selected_metrics and state.goal_mode_source == "auto_detected" and state.intent == "general_summary":
        state.add_route("needs_input")
        _set_node_outputs(state, "未识别到受支持的分析指标，请选择指标、示例问题或字段映射。", ["规则规划器仅支持明确的指标与目标；当前问题需要补充输入。"], {}, ["选择一个已有指标或分析剧本。"])
        return state
    route = _route_from_plan(state)
    route_nodes: dict[str, Callable[[WorkflowState, dict[str, pd.DataFrame], AnalyticsEngine | None], WorkflowState]] = {
        "metric_diagnosis": _run_metric_diagnosis_node,
        "growth_trend": _run_growth_trend_node,
        "experiment_analysis": _run_experiment_node,
        "content_performance": _run_content_performance_node,
        "live_quality": _run_live_quality_node,
        "causal_exploration": _run_causal_exploration_node,
        "periodic_report": _run_periodic_report_node,
    }
    return route_nodes.get(route, _run_periodic_report_node)(state, tables, engine)


def _run_rule_based_workflow(
    question: str,
    tables: dict[str, pd.DataFrame],
    goal_mode: str = "auto",
    workflow_backend: str = WORKFLOW_BACKEND_RULE_BASED,
    initial_caveats: list[Any] | None = None,
    initial_errors: list[str] | None = None,
    data_source_type: str = "synthetic",
    table_metadata: dict[str, Any] | None = None,
    column_mapping: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    playbook_parameters: dict[str, Any] | None = None,
    execution_mode: str = "execute",
    presentation_mode: str = "eager",
    prepared_dataset=None,
) -> dict[str, Any]:
    state = create_initial_state(
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
    _initialize_run_options(state,presentation_mode,prepared_dataset)
    state.intermediate_results["workflow_backend"] = workflow_backend
    if initial_caveats:
        _append_unique(state.caveats, initial_caveats)
    if initial_errors:
        _append_unique(state.errors, initial_errors)
    engine = _safe_engine(tables)
    tracer = LocalTracer(state.trace_id)

    def run_traced(name: str,fn: Callable[...,WorkflowState]) -> None:
        with tracer.span(name):
            if name in {"run_routed_analysis", "build_analysis_results"} and state.planning_status == "ready" and state.playbook_parameters.get("date_range") and not state.selected_playbook_id:
                scoped = _scope_analysis_tables(state, tables)
                scoped_engine = _safe_engine(scoped)
                try:
                    fn(state, scoped, scoped_engine)
                finally:
                    if scoped_engine is not None:
                        scoped_engine.close()
            else:
                fn(state,tables,engine)

    try:
        with use_tracer(tracer), aggregate_scope():
            run_traced("load_data_source",_load_data_source_node)
            run_traced("prepare_column_mapping",_prepare_column_mapping_node)
            run_traced("resolve_metrics",_resolve_metrics_node)
            run_traced("create_plan",_create_plan_node)
            if state.planning_status != "ready":
                pass
            elif state.execution_mode == "plan_only" and state.selected_playbook_id != "semantic_metric_query":
                state.add_route("preview_analysis_plan")
            elif state.selected_playbook_id:
                run_traced("run_playbook",_run_playbook_node)
            else:
                run_traced("run_routed_analysis",_run_routed_analysis)
            run_traced("build_analysis_results",_build_analysis_results_node)
            run_traced("build_governance",_build_governance_node)
            _set_observability(state,tracer)
            run_traced("build_manifest",_build_manifest_node)
            run_traced("review",_review_node)
            run_traced("generate_report",_report_node)
    finally:
        if engine is not None:
            engine.close()
    return _finalize_observability(state,tracer)


def _finalize_observability(state: WorkflowState,tracer: LocalTracer) -> dict[str,Any]:
    """Refresh compact telemetry after every measured node without rebuilding data."""
    _set_observability(state,tracer,add_route=False)
    result=state.intermediate_results["result"]
    result["telemetry"]=state.telemetry
    result["trace"]["observability_summary"]=state.telemetry["summary"]
    if isinstance(result.get("workflow_state"),dict):
        result["workflow_state"]["telemetry"]=state.telemetry
    return result


def _langgraph_available() -> bool:
    return importlib.util.find_spec("langgraph") is not None and importlib.util.find_spec("langgraph.graph") is not None


def run_agent_analysis(
    question: str,
    tables: dict[str, pd.DataFrame],
    goal_mode: str = "auto",
    use_langgraph: bool = False,
    data_source_type: str = "synthetic",
    table_metadata: dict[str, Any] | None = None,
    column_mapping: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    playbook_parameters: dict[str, Any] | None = None,
    execution_mode: str | None = None,
    plan_only: bool = False,
    approved_plan_id: str | None = None,
    semantic_model_id: str = "commerce_demo",
    metric_request: dict[str, Any] | None = None,
    presentation_mode: str = "eager",
    prepared_dataset=None,
    clarification_answers: dict[str, Any] | None = None,
    selection_source: str | None = None,
    analysis_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the deterministic workflow over synthetic tables."""

    cancellation_checkpoint()
    if presentation_mode not in {"eager","deferred"}:
        raise ValueError("presentation_mode 必须为eager或deferred。")
    if prepared_dataset is not None:
        from insightpilot.agents.dataset import PreparedDataset
        if not isinstance(prepared_dataset,PreparedDataset):
            raise TypeError("prepared_dataset必须是受控PreparedDataset。")
        tables=dict(prepared_dataset._tables)
        table_metadata=prepared_dataset.metadata
    effective_parameters = dict(playbook_parameters or {})
    effective_parameters["_guidance_context"] = {"selection_source": selection_source, "analysis_scope": analysis_scope}
    if clarification_answers is not None:
        effective_parameters["_clarification_answers"] = dict(clarification_answers)
    effective_execution_mode = "plan_only" if plan_only else (execution_mode or "execute")
    if playbook_id == "semantic_metric_query":
        request_values = dict(metric_request or {})
        if request_values.get("metrics") and not effective_parameters.get("metrics"):
            effective_parameters["metrics"] = list(request_values["metrics"])
        if request_values.get("dimensions") is not None and "dimensions" not in effective_parameters:
            effective_parameters["dimensions"] = request_values["dimensions"]
        for key in ["date_dimension", "date_from", "date_to", "time_grain", "limit", "sort", "filters"]:
            if key in request_values and key not in effective_parameters:
                effective_parameters[key] = request_values[key]
        if metric_request:
            effective_parameters.setdefault("date_dimension", None)
            effective_parameters.setdefault("dimensions", [])
        effective_parameters["semantic_model_id"] = semantic_model_id
        effective_parameters["execution_mode"] = effective_execution_mode
        if approved_plan_id:
            effective_parameters["approved_plan_id"] = approved_plan_id

    if use_langgraph and data_source_type == "synthetic":
        if _langgraph_available():
            try:
                from insightpilot.agents.langgraph_workflow import run_langgraph_workflow

                return run_langgraph_workflow(
                    question,
                    tables,
                    goal_mode=goal_mode,
                    data_source_type=data_source_type,
                    table_metadata=table_metadata,
                    column_mapping=column_mapping,
                    playbook_id=playbook_id,
                    playbook_parameters=effective_parameters,
                    execution_mode=effective_execution_mode,
                    presentation_mode=presentation_mode,
                    prepared_dataset=prepared_dataset,
                )
            except Exception as exc:
                raise RuntimeError("LangGraph 已安装，但工作流节点执行失败；请检查真实异常，未伪装缺依赖或静默重跑。") from exc
        return _run_rule_based_workflow(
            question,
            tables,
            goal_mode=goal_mode,
            workflow_backend=WORKFLOW_BACKEND_LANGGRAPH_FALLBACK,
            initial_caveats=["Optional LangGraph 未安装，已自动回退到 rule-based workflow。"],
            data_source_type=data_source_type,
            table_metadata=table_metadata,
            column_mapping=column_mapping,
            playbook_id=playbook_id,
            playbook_parameters=effective_parameters,
            execution_mode=effective_execution_mode,
            presentation_mode=presentation_mode,
            prepared_dataset=prepared_dataset,
        )

    return _run_rule_based_workflow(
        question,
        tables,
        goal_mode=goal_mode,
        workflow_backend=WORKFLOW_BACKEND_RULE_BASED,
        data_source_type=data_source_type,
        table_metadata=table_metadata,
        column_mapping=column_mapping,
        playbook_id=playbook_id,
        playbook_parameters=effective_parameters,
        execution_mode=effective_execution_mode,
        presentation_mode=presentation_mode,
        prepared_dataset=prepared_dataset,
    )


__all__ = [
    "WORKFLOW_BACKEND_LANGGRAPH",
    "WORKFLOW_BACKEND_LANGGRAPH_FALLBACK",
    "WORKFLOW_BACKEND_RULE_BASED",
    "_create_plan_node",
    "_langgraph_available",
    "_load_data_source_node",
    "_build_manifest_node",
    "_run_playbook_node",
    "_report_node",
    "_resolve_metrics_node",
    "_review_node",
    "_route_from_plan",
    "_run_causal_exploration_node",
    "_run_content_performance_node",
    "_run_experiment_node",
    "_run_growth_trend_node",
    "_run_live_quality_node",
    "_run_generic_analysis_node",
    "_run_metric_diagnosis_node",
    "_run_periodic_report_node",
    "run_agent_analysis",
]
