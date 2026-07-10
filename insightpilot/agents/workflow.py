"""Deterministic analysis workflow with optional LangGraph orchestration."""

from __future__ import annotations

import importlib.util
from typing import Any, Callable

import pandas as pd

from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.analysis.causal_light import estimate_adjusted_effect
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.agents.reviewer import review_analysis
from insightpilot.agents.state import WorkflowState, create_initial_state
from insightpilot.agents.trace import AnalysisTrace
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
from insightpilot.metrics.resolver import resolve_metrics_from_question
from insightpilot.planning.planner import AnalysisPlan, create_analysis_plan
from insightpilot.playbooks.executor import execute_playbook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.reports.manifest import RunManifest, fingerprint_dataframe, sanitize_manifest_value
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.tools.duckdb_engine import AnalyticsEngine
from insightpilot.visualization.factory import build_charts


WORKFLOW_BACKEND_RULE_BASED = "rule_based"
WORKFLOW_BACKEND_LANGGRAPH = "langgraph"
WORKFLOW_BACKEND_LANGGRAPH_FALLBACK = "langgraph_unavailable_fallback"

DEFAULT_CAVEATS = [
    "本次分析仅使用 synthetic data，用于学习研究和工作流演示，不代表真实业务结论。",
    "相关性不能直接解释为因果关系；实验和轻量调整结果仍需谨慎解读。",
    "rule-based planner 依赖 deterministic keyword rules，复杂表达需要继续扩展规则覆盖。",
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
        engine = AnalyticsEngine()
        engine.register_tables(tables)
        return engine
    except ImportError:
        return None
    except Exception:
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
        return round(value, 6)
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
    return ColumnMapping(
        table_name=state.column_mapping.get("table_name"),
        date_column=state.column_mapping.get("date_column"),
        metric_columns=list(state.column_mapping.get("metric_columns", [])),
        dimension_columns=list(state.column_mapping.get("dimension_columns", [])),
        group_column=state.column_mapping.get("group_column"),
        treatment_column=state.column_mapping.get("treatment_column"),
        outcome_column=state.column_mapping.get("outcome_column"),
        time_grain=state.column_mapping.get("time_grain", "day"),
        notes=list(state.column_mapping.get("notes", [])),
    )


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
    if not state.user_table_mode:
        state.column_mapping = {}
        state.mapping_source = "none"
        state.mapping_warnings = []
        return state

    raw_mapping = state.column_mapping if isinstance(state.column_mapping, dict) and state.column_mapping else None
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
    daily = tables["daily_metrics"].copy()
    if city_filter:
        daily = daily[daily["city"] == city_filter]
    if metric.endswith("_rate") or metric in {"ctr", "cvr", "payment_success_rate"}:
        return daily.groupby("date", as_index=False)[metric].mean()
    return daily.groupby("date", as_index=False)[metric].sum()


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
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("load_data_source")
    state.tables_available = sorted(tables.keys())
    if not state.table_metadata:
        state.table_metadata = _metadata_from_tables(tables)
    state.add_route("validate_tables")
    state.schema_warnings = validate_tables_for_workflow(tables)
    state.add_route("infer_schema")
    for table_name, df in tables.items():
        metadata = state.table_metadata.setdefault(
            table_name,
            {
                "source_type": state.data_source_type,
                "source_name": table_name,
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                "columns": [str(column) for column in df.columns],
            },
        )
        metadata.setdefault("schema_mapping", infer_schema_mapping(table_name, df).to_dict())
        metadata.setdefault("warnings", validate_tables_for_workflow({table_name: df}))
    if state.schema_warnings:
        _append_unique(state.caveats, state.schema_warnings)
    if state.user_table_mode:
        _append_unique(state.caveats, CUSTOM_DATA_CAVEATS)
    return state


def _create_plan_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("create_plan")
    plan = create_analysis_plan(state.user_question, goal_mode=state.goal_mode)
    state.intent = plan.intent
    state.goal_mode = plan.goal_mode
    state.goal_mode_display_name = plan.goal_mode_display_name
    state.goal_mode_source = plan.goal_mode_source
    state.analysis_plan = plan.to_dict()
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
        state.playbook_source = "user_selected"
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

    state.add_route("build_safe_query")
    state.add_route("execute_playbook")
    state.executed_queries.extend(execution.executed_queries)
    for query_record in execution.executed_queries:
        if query_record.get("status") == "failed":
            state.errors.append(
                f"Playbook query failed: {query_record.get('template_id', 'unknown')} "
                f"({query_record.get('purpose', '')})"
            )
    state.playbook_parameters = dict(execution.parameters)
    state.chart_specs = list(execution.chart_specs)
    mapping = execution.metadata.get("column_mapping", {})
    if isinstance(mapping, dict) and mapping:
        state.column_mapping = mapping
        state.mapping_source = str(execution.metadata.get("mapping_source", state.mapping_source))
        state.mapping_warnings = list(dict.fromkeys([*state.mapping_warnings, *execution.warnings]))
        if not state.selected_metrics:
            state.selected_metrics = list(mapping.get("metric_columns", []))
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
    state.add_route("generate_charts")
    chart_pairs = build_charts(execution.chart_specs, execution.result_tables)
    state.intermediate_results["chart_pairs"] = chart_pairs
    state.intermediate_results["charts"] = [figure for _, figure in chart_pairs]
    return state


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
        manifest_version="1.0",
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
        dataset_fingerprints={name: fingerprint_dataframe(df) for name, df in sorted(tables.items())},
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
    city_filter = "South City" if any(term in state.user_question for term in ("城市", "South")) else None
    where_clause = "WHERE city = 'South City'" if city_filter else ""
    query = f"SELECT date, SUM({metric}) AS {metric} FROM daily_metrics {where_clause} GROUP BY date ORDER BY date"
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
    for dimension in [dim for dim in plan.dimensions if dim in tables["daily_metrics"].columns]:
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
    query = f"SELECT date, SUM({metric}) AS {metric} FROM daily_metrics GROUP BY date ORDER BY date"
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

    state.add_route("run_causal_light")
    _record_operation(
        state,
        "experiment_adjusted_effect",
        "estimate_adjusted_effect(experiments, group, completion_rate, covariates)",
        len(experiments),
    )
    effect = estimate_adjusted_effect(
        experiments,
        "group",
        "completion_rate",
        ["historical_activity", "historical_revenue", "city", "channel", "user_segment"],
    )
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
            f"实验组 completion_rate={float(ab_result['treatment_mean']):.4f}，对照组 "
            f"{float(ab_result['control_mean']):.4f}，相对提升 {float(ab_result['relative_lift']):.2%}。"
        ),
        f"sample_size={sample_size}，用于判断当前 synthetic 实验样本是否足够稳定。",
        f"p_value={float(ab_result['p_value']):.6f}，confidence_interval={ab_result['confidence_interval']}。",
        (
            f"轻量调整后 effect={float(effect['adjusted_effect']):.4f}，"
            f"naive difference={float(effect['naive_difference']):.4f}。"
        ),
        str(ab_result["conclusion"]),
        REPORT_LIMITATION,
    ]
    next_steps = [
        "继续观察分层效果是否稳定，尤其是样本较小的用户分层。",
        "补充更长周期的 synthetic 回放和稳定性检查。",
    ]
    _set_node_outputs(
        state,
        summary="A/B 实验评估已完成，包含 p_value、sample_size 和轻量调整结果。",
        findings=findings,
        artifacts={
            "ab_test": ab_result,
            "causal_light": effect,
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
            f"propensity weighted effect={float(effect['propensity_weighted_effect']):.4f}，"
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
    query = f"SELECT date, SUM({metric}) AS {metric} FROM daily_metrics GROUP BY date ORDER BY date"
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


def _custom_date_metric_frame(df: pd.DataFrame, date_col: str, metric_col: str, time_grain: str = "day") -> pd.DataFrame:
    working = df[[date_col, metric_col]].copy()
    working[date_col] = pd.to_datetime(working[date_col], errors="coerce")
    working[metric_col] = pd.to_numeric(working[metric_col], errors="coerce")
    working = working.dropna(subset=[date_col, metric_col])
    if time_grain == "week":
        working[date_col] = working[date_col].dt.to_period("W").dt.start_time
    elif time_grain == "month":
        working[date_col] = working[date_col].dt.to_period("M").dt.to_timestamp()
    return working.groupby(date_col, as_index=False)[metric_col].sum().sort_values(date_col)


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
            metric_frame = _custom_date_metric_frame(df, date_col, metric_col, applied_mapping.time_grain)
            artifacts["generic_trend"] = _round_value(metric_frame.tail(20).to_dict(orient="records"))
            if len(metric_frame) >= 8:
                state.add_route("run_generic_anomaly")
                anomaly = detect_metric_anomaly(metric_frame, metric_col, date_col=date_col)
                artifacts["generic_anomaly"] = _round_value(anomaly)
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
                            contribution = dimension_contribution(df, metric_col, dimension, date_col=date_col)
                            breakdowns[dimension] = contribution.head(5).to_dict(orient="records")
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
            values = set(df[group_col].dropna().astype(str).str.lower().unique())
            if {"control", "treatment"}.issubset(values):
                ab_result = analyze_ab_test(df, group_col, metric_col, metric_type="mean")
                artifacts["generic_ab_test"] = _round_value(ab_result)
                findings.extend(
                    [
                        f"识别到实验分组字段 {group_col} 和指标字段 {metric_col}。",
                        f"p_value={float(ab_result['p_value']):.6f}，sample_size={ab_result['sample_size']}。",
                        str(ab_result["conclusion"]),
                    ]
                )
            else:
                group_summary = (
                    df[[group_col, metric_col]]
                    .assign(**{metric_col: pd.to_numeric(df[metric_col], errors="coerce")})
                    .dropna(subset=[group_col, metric_col])
                    .groupby(group_col)[metric_col]
                    .agg(["count", "mean"])
                    .reset_index()
                )
                artifacts["generic_group_mean_comparison"] = _round_value(group_summary.to_dict(orient="records"))
                findings.append(f"使用 group_column={group_col} 和 metric={metric_col} 输出组间均值比较。")
                caveats.append("group_column 未同时包含 control/treatment，未执行 A/B 显著性检验。")
        else:
            findings.append("未识别到包含 control/treatment 的分组字段和数值指标，无法执行通用实验评估。")
            caveats.append("实验分析需要明确 group 字段且包含 control/treatment，以及一个数值 outcome 字段。")
    elif route == "causal_exploration":
        if applied_mapping.treatment_column and applied_mapping.outcome_column:
            state.add_route("run_generic_causal_light")
            covariates = [
                column
                for column in dimension_columns[:5]
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


def _report_node(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None = None,
) -> WorkflowState:
    state.add_route("generate_report")
    result = _build_result_from_state(state)
    result["report_markdown"] = generate_markdown_report(result)
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
    )


def _build_result_from_state(state: WorkflowState) -> dict[str, Any]:
    metrics = state.intermediate_results.get("metrics", [])
    reviewer = state.intermediate_results.get("reviewer", {})
    trace = _build_trace_from_state(state)
    trace_dict = trace.to_dict()
    workflow_backend = str(state.intermediate_results.get("workflow_backend", WORKFLOW_BACKEND_RULE_BASED))
    return {
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
    }


def _run_routed_analysis(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None,
) -> WorkflowState:
    if state.user_table_mode:
        return _run_generic_analysis_node(state, tables, engine)
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
    initial_caveats: list[str] | None = None,
    initial_errors: list[str] | None = None,
    data_source_type: str = "synthetic",
    table_metadata: dict[str, Any] | None = None,
    column_mapping: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    playbook_parameters: dict[str, Any] | None = None,
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
    )
    state.intermediate_results["workflow_backend"] = workflow_backend
    if initial_caveats:
        _append_unique(state.caveats, initial_caveats)
    if initial_errors:
        _append_unique(state.errors, initial_errors)
    engine = _safe_engine(tables)
    _load_data_source_node(state, tables, engine)
    _prepare_column_mapping_node(state, tables, engine)
    _resolve_metrics_node(state, tables, engine)
    _create_plan_node(state, tables, engine)
    if state.selected_playbook_id:
        _run_playbook_node(state, tables, engine)
    else:
        _run_routed_analysis(state, tables, engine)
    _build_manifest_node(state, tables, engine)
    _review_node(state, tables, engine)
    _report_node(state, tables, engine)
    return state.intermediate_results["result"]


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
) -> dict[str, Any]:
    """Run the deterministic workflow over synthetic tables."""

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
                    playbook_parameters=playbook_parameters,
                )
            except Exception as exc:
                return _run_rule_based_workflow(
                    question,
                    tables,
                    goal_mode=goal_mode,
                    workflow_backend=WORKFLOW_BACKEND_LANGGRAPH_FALLBACK,
                    initial_caveats=["Optional LangGraph workflow 不可用，已自动回退到 rule-based workflow。"],
                    initial_errors=[f"LangGraph workflow fallback: {exc}"],
                    data_source_type=data_source_type,
                    table_metadata=table_metadata,
                    column_mapping=column_mapping,
                    playbook_id=playbook_id,
                    playbook_parameters=playbook_parameters,
                )
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
            playbook_parameters=playbook_parameters,
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
        playbook_parameters=playbook_parameters,
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
