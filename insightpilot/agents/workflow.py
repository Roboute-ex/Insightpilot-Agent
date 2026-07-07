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
from insightpilot.metrics.dictionary import MetricDefinition
from insightpilot.metrics.resolver import resolve_metrics_from_question
from insightpilot.planning.planner import AnalysisPlan, create_analysis_plan
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.tools.duckdb_engine import AnalyticsEngine


WORKFLOW_BACKEND_RULE_BASED = "rule_based"
WORKFLOW_BACKEND_LANGGRAPH = "langgraph"
WORKFLOW_BACKEND_LANGGRAPH_FALLBACK = "langgraph_unavailable_fallback"

DEFAULT_CAVEATS = [
    "本次分析仅使用 synthetic data，用于学习研究和工作流演示，不代表真实业务结论。",
    "相关性不能直接解释为因果关系；实验和轻量调整结果仍需谨慎解读。",
    "rule-based planner 依赖 deterministic keyword rules，复杂表达需要继续扩展规则覆盖。",
]


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
    _append_unique(state.caveats, DEFAULT_CAVEATS)
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
        workflow_backend=str(state.intermediate_results.get("workflow_backend", WORKFLOW_BACKEND_RULE_BASED)),
        user_question=state.user_question,
        goal_mode=state.goal_mode,
        goal_mode_display_name=state.goal_mode_display_name,
        goal_mode_source=state.goal_mode_source,
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
    }


def _run_routed_analysis(
    state: WorkflowState,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None,
) -> WorkflowState:
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
) -> dict[str, Any]:
    state = create_initial_state(question, tables, goal_mode)
    state.intermediate_results["workflow_backend"] = workflow_backend
    if initial_caveats:
        _append_unique(state.caveats, initial_caveats)
    if initial_errors:
        _append_unique(state.errors, initial_errors)
    engine = _safe_engine(tables)
    _resolve_metrics_node(state, tables, engine)
    _create_plan_node(state, tables, engine)
    _run_routed_analysis(state, tables, engine)
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
) -> dict[str, Any]:
    """Run the deterministic workflow over synthetic tables."""

    if use_langgraph:
        if _langgraph_available():
            try:
                from insightpilot.agents.langgraph_workflow import run_langgraph_workflow

                return run_langgraph_workflow(question, tables, goal_mode=goal_mode)
            except Exception as exc:
                return _run_rule_based_workflow(
                    question,
                    tables,
                    goal_mode=goal_mode,
                    workflow_backend=WORKFLOW_BACKEND_LANGGRAPH_FALLBACK,
                    initial_caveats=["Optional LangGraph workflow 不可用，已自动回退到 rule-based workflow。"],
                    initial_errors=[f"LangGraph workflow fallback: {exc}"],
                )
        return _run_rule_based_workflow(
            question,
            tables,
            goal_mode=goal_mode,
            workflow_backend=WORKFLOW_BACKEND_LANGGRAPH_FALLBACK,
            initial_caveats=["Optional LangGraph 未安装，已自动回退到 rule-based workflow。"],
        )

    return _run_rule_based_workflow(
        question,
        tables,
        goal_mode=goal_mode,
        workflow_backend=WORKFLOW_BACKEND_RULE_BASED,
    )


__all__ = [
    "WORKFLOW_BACKEND_LANGGRAPH",
    "WORKFLOW_BACKEND_LANGGRAPH_FALLBACK",
    "WORKFLOW_BACKEND_RULE_BASED",
    "_create_plan_node",
    "_langgraph_available",
    "_report_node",
    "_resolve_metrics_node",
    "_review_node",
    "_route_from_plan",
    "_run_causal_exploration_node",
    "_run_content_performance_node",
    "_run_experiment_node",
    "_run_growth_trend_node",
    "_run_live_quality_node",
    "_run_metric_diagnosis_node",
    "_run_periodic_report_node",
    "run_agent_analysis",
]
