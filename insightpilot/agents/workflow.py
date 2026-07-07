"""Rule-based analysis workflow."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.analysis.causal_light import estimate_adjusted_effect
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.agents.reviewer import review_analysis
from insightpilot.agents.trace import AnalysisTrace
from insightpilot.config import REPORT_LIMITATION
from insightpilot.metrics.dictionary import MetricDefinition
from insightpilot.metrics.resolver import resolve_metrics_from_question
from insightpilot.planning.planner import AnalysisPlan, create_analysis_plan
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.tools.duckdb_engine import AnalyticsEngine


def _metric_payload(metrics: list[MetricDefinition]) -> list[dict[str, object]]:
    return [metric.to_dict() for metric in metrics]


def _safe_engine(tables: dict[str, pd.DataFrame]) -> AnalyticsEngine | None:
    try:
        engine = AnalyticsEngine()
        engine.register_tables(tables)
        return engine
    except ImportError:
        return None


def _run_query(
    engine: AnalyticsEngine | None,
    query: str,
    executed_queries: list[str],
    fallback: Callable[[], pd.DataFrame],
) -> pd.DataFrame:
    if engine is not None:
        executed_queries.append(query)
        return engine.run_sql(query)
    executed_queries.append(f"pandas fallback: {query}")
    return fallback()


def _round_dict(data: dict[str, Any]) -> dict[str, Any]:
    rounded: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, float):
            rounded[key] = round(value, 6)
        elif isinstance(value, tuple):
            rounded[key] = tuple(round(float(item), 6) for item in value)
        else:
            rounded[key] = value
    return rounded


def _daily_metric_frame(tables: dict[str, pd.DataFrame], metric: str, city_filter: str | None = None) -> pd.DataFrame:
    daily = tables["daily_metrics"].copy()
    if city_filter:
        daily = daily[daily["city"] == city_filter]
    if metric.endswith("_rate") or metric in {"ctr", "cvr", "payment_success_rate"}:
        return daily.groupby("date", as_index=False)[metric].mean()
    return daily.groupby("date", as_index=False)[metric].sum()


def _transaction_analysis(
    question: str,
    plan: AnalysisPlan,
    tables: dict[str, pd.DataFrame],
    engine: AnalyticsEngine | None,
    executed_queries: list[str],
) -> tuple[list[str], dict[str, Any], list[str]]:
    metric = next((name for name in plan.related_metrics if name in tables["daily_metrics"].columns), "orders")
    city_filter = "South City" if any(term in question for term in ("城市", "某城市", "South")) else None
    where_clause = "WHERE city = 'South City'" if city_filter else ""
    query = f"SELECT date, SUM({metric}) AS {metric} FROM daily_metrics {where_clause} GROUP BY date ORDER BY date"
    metric_frame = _run_query(
        engine,
        query,
        executed_queries,
        lambda: _daily_metric_frame(tables, metric, city_filter),
    )
    anomaly = detect_metric_anomaly(metric_frame, metric)
    contribution_source = tables["daily_metrics"]
    contributions: dict[str, list[dict[str, object]]] = {}
    for dimension in [dim for dim in plan.dimensions if dim in contribution_source.columns]:
        contribution = dimension_contribution(contribution_source, metric, dimension)
        contributions[dimension] = contribution.head(5).to_dict(orient="records")

    top_city = contributions.get("city", [{}])[0].get("dimension_value", "unknown")
    findings = [
        (
            f"{metric} 当前值为 {anomaly['current_value']:.2f}，相对前 7 日均值 "
            f"{anomaly['baseline_value']:.2f} 变化 {anomaly['relative_change']:.2%}，"
            f"severity={anomaly['severity']}。"
        ),
        f"维度贡献排序显示 {top_city} 是主要变化来源之一，建议优先复核该维度的流量与转化链路。",
        "订单类问题建议按曝光、点击率、转化率、支付成功率逐层拆解，避免只看单一结果指标。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "优先查看高贡献城市、渠道和设备的曝光与点击率变化。",
        "对支付成功率和转化率做分层复核，确认是否为局部链路波动。",
    ]
    artifacts = {"anomaly": _round_dict(anomaly), "contributions": contributions}
    return findings, artifacts, next_steps


def _experiment_analysis(
    tables: dict[str, pd.DataFrame],
    executed_queries: list[str],
) -> tuple[list[str], dict[str, Any], list[str]]:
    experiments = tables["experiments"]
    executed_queries.append("pandas: analyze_ab_test(experiments, group, completion_rate, mean)")
    ab_result = analyze_ab_test(experiments, "group", "completion_rate", metric_type="mean")
    executed_queries.append("pandas: estimate_adjusted_effect(experiments, group, completion_rate, covariates)")
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
    findings = [
        (
            f"实验组 completion_rate={ab_result['treatment_mean']:.4f}，对照组 "
            f"{ab_result['control_mean']:.4f}，相对提升 {ab_result['relative_lift']:.2%}。"
        ),
        f"sample_size={ab_result['sample_size']}，用于判断当前 synthetic 实验样本是否足够稳定。",
        f"p_value={ab_result['p_value']:.6f}，confidence_interval={ab_result['confidence_interval']}。",
        f"轻量调整后 effect={effect['adjusted_effect']:.4f}，naive difference={effect['naive_difference']:.4f}。",
        ab_result["conclusion"],
        REPORT_LIMITATION,
    ]
    next_steps = [
        "继续观察分层效果是否稳定，尤其是样本较小的用户分层。",
        "上线前补充更长周期的 synthetic 回放和稳健性检查。",
    ]
    artifacts = {
        "ab_test": _round_dict(ab_result),
        "causal_light": _round_dict(effect),
        "strata": strata.round(6).to_dict(orient="records"),
    }
    return findings, artifacts, next_steps


def _content_analysis(tables: dict[str, pd.DataFrame], executed_queries: list[str]) -> tuple[list[str], dict[str, Any], list[str]]:
    content_events = tables["content_events"]
    executed_queries.append("pandas: group content_events by content_category")
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
        f"{top['content_category']} 的完播率最高，均值约 {top['completion_rate']:.4f}。",
        f"{low['content_category']} 的完播率较低，建议查看内容长度、设备和用户分层差异。",
        "内容分析适合先看完播率、观看时长和留存相关指标，再进入实验或归因分析。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "对低完播内容类型按设备和用户分层继续拆解。",
        "结合实验表验证策略变化是否带来稳定提升。",
    ]
    return findings, {"content_summary": summary.round(6).to_dict(orient="records")}, next_steps


def _causal_exploration_analysis(
    tables: dict[str, pd.DataFrame],
    executed_queries: list[str],
) -> tuple[list[str], dict[str, Any], list[str]]:
    experiments = tables["experiments"]
    executed_queries.append("pandas: estimate_adjusted_effect(experiments, group, completion_rate, covariates)")
    effect = estimate_adjusted_effect(
        experiments,
        "group",
        "completion_rate",
        ["historical_activity", "historical_revenue", "city", "channel", "user_segment"],
    )
    findings = [
        f"naive difference={effect['naive_difference']:.4f}，regression adjusted effect={effect['adjusted_effect']:.4f}。",
        f"propensity weighted effect={effect['propensity_weighted_effect']:.4f}，sample_size={effect['sample_size']}。",
        "轻量因果探索仅用于形成分析假设，不能把相关性直接解释为因果关系。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "补充更明确的处理机制、时间顺序和混杂变量检查。",
        "将探索性结果作为后续实验或更严格评估设计的输入。",
    ]
    return findings, {"causal_light": _round_dict(effect)}, next_steps


def _live_analysis(
    plan: AnalysisPlan,
    tables: dict[str, pd.DataFrame],
    executed_queries: list[str],
) -> tuple[list[str], dict[str, Any], list[str]]:
    quality = tables["live_quality_logs"]
    sessions = tables["live_sessions"]
    interactions = tables["live_interactions"]
    executed_queries.append("pandas: detect stutter_rate anomaly from live_quality_logs")
    stutter = detect_metric_anomaly(quality, "stutter_rate")
    executed_queries.append("pandas: detect watch_time change from live_sessions")
    watch_time = detect_metric_anomaly(sessions, "watch_time")
    executed_queries.append("pandas: detect interaction_rate change from live_interactions")
    interaction_rate = detect_metric_anomaly(interactions, "interaction_rate")
    contributions: dict[str, list[dict[str, object]]] = {}
    for dimension in [dim for dim in plan.dimensions if dim in quality.columns]:
        contribution = dimension_contribution(quality, "stutter_rate", dimension)
        contributions[dimension] = contribution.head(5).to_dict(orient="records")
    top_device = contributions.get("device", [{}])[0].get("dimension_value", "unknown")
    top_network = contributions.get("network_type", [{}])[0].get("dimension_value", "unknown")
    findings = [
        f"卡顿率相对前 7 日均值变化 {stutter['relative_change']:.2%}，需要按体验风险理解该上升信号。",
        f"观看时长变化 {watch_time['relative_change']:.2%}，互动率变化 {interaction_rate['relative_change']:.2%}。",
        f"贡献排序显示 {top_device} 与 {top_network} 是优先排查维度。",
        "直播体验问题建议同时观察设备、网络类型、地区和时段，避免把相关性直接解释为因果。",
        REPORT_LIMITATION,
    ]
    next_steps = [
        "优先复核高贡献设备和网络类型在目标日期的质量日志。",
        "对卡顿率与停留变化做更细时段回放，确认是否持续出现。",
    ]
    artifacts = {
        "stutter_anomaly": _round_dict(stutter),
        "watch_time_change": _round_dict(watch_time),
        "interaction_rate_change": _round_dict(interaction_rate),
        "contributions": contributions,
    }
    return findings, artifacts, next_steps


def _general_analysis(
    plan: AnalysisPlan,
    tables: dict[str, pd.DataFrame],
    executed_queries: list[str],
) -> tuple[list[str], dict[str, Any], list[str]]:
    daily = tables["daily_metrics"]
    metric = next((name for name in plan.related_metrics if name in daily.columns), "active_users")
    executed_queries.append(f"pandas: summarize daily_metrics metric={metric}")
    summary = _daily_metric_frame(tables, metric)
    anomaly = detect_metric_anomaly(summary, metric)
    findings = [
        f"{metric} 当前值为 {anomaly['current_value']:.2f}，相对前 7 日均值变化 {anomaly['relative_change']:.2%}。",
        "当前为基础描述性汇总，如需诊断可补充更明确的目标指标和维度。",
        REPORT_LIMITATION,
    ]
    next_steps = ["明确目标指标、时间窗口和优先维度后，可进一步做归因或实验分析。"]
    return findings, {"summary_change": _round_dict(anomaly)}, next_steps


def run_agent_analysis(
    question: str,
    tables: dict[str, pd.DataFrame],
    goal_mode: str = "auto",
) -> dict[str, Any]:
    """Run the default deterministic workflow over synthetic tables."""

    metrics = resolve_metrics_from_question(question)
    plan = create_analysis_plan(question, goal_mode=goal_mode)
    engine = _safe_engine(tables)
    executed_queries: list[str] = []

    if plan.intent in {"metric_drop_diagnosis", "metric_growth_analysis"}:
        findings, artifacts, next_steps = _transaction_analysis(question, plan, tables, engine, executed_queries)
    elif plan.intent == "experiment_analysis":
        findings, artifacts, next_steps = _experiment_analysis(tables, executed_queries)
    elif plan.intent == "content_performance_analysis":
        findings, artifacts, next_steps = _content_analysis(tables, executed_queries)
    elif plan.intent == "live_quality_analysis":
        findings, artifacts, next_steps = _live_analysis(plan, tables, executed_queries)
    elif plan.intent == "causal_exploration":
        findings, artifacts, next_steps = _causal_exploration_analysis(tables, executed_queries)
    else:
        findings, artifacts, next_steps = _general_analysis(plan, tables, executed_queries)

    trace = AnalysisTrace(
        user_question=question,
        identified_intent=plan.intent,
        selected_metrics=[metric.metric_name for metric in metrics],
        analysis_plan=plan.to_dict(),
        goal_mode=plan.goal_mode,
        goal_mode_display_name=plan.goal_mode_display_name,
        goal_mode_source=plan.goal_mode_source,
        executed_queries=executed_queries,
        generated_findings=findings,
    )
    review = review_analysis(trace)
    trace.reviewer_checks = review.to_dict()
    result: dict[str, Any] = {
        "question": question,
        "intent": plan.intent,
        "goal_mode": plan.goal_mode,
        "goal_mode_display_name": plan.goal_mode_display_name,
        "goal_mode_source": plan.goal_mode_source,
        "metrics": _metric_payload(metrics),
        "plan": plan.to_dict(),
        "findings": findings,
        "reviewer": review.to_dict(),
        "trace": trace.to_dict(),
        "artifacts": artifacts,
        "limitations": [
            "仅使用 synthetic data，不接入真实外部业务数据。",
            "结论用于学习研究、数据分析自动化和 Agent 工程化实践。",
            "相关性不能直接解释为因果关系，实验和轻量调整结果仍需谨慎解读。",
        ],
        "next_steps": next_steps,
    }
    result["report_markdown"] = generate_markdown_report(result)
    return result
