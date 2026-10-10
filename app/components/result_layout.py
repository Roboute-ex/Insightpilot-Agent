"""Method-specific result presentation from already computed tables and specs."""
from __future__ import annotations
from copy import deepcopy
import math
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from insightpilot.performance import BoundedCache, PerformanceConfig
from insightpilot.ui.theme import render_compact_summary_card
from insightpilot.ui.synthetic_display import synthetic_display_text, synthetic_display_object
from insightpilot.reports.manifest import _safe_string

RESULT_TITLES = {
    "adjusted_effect_summary": "因果探索实际估计", "experiment_summary": "两组结果摘要",
    "experiment_statistics": "实验统计结果", "experiment_comparison": "实验分析结果",
    "metric_comparisons": "指标对比", "dimension_contributions": "维度变化贡献",
    "dimension_contribution": "静态分组表现", "period_comparison": "周期对比",
    "trend": "指标趋势", "metric_trend": "指标趋势", "column_profile": "字段概览",
    "numeric_summary": "数值摘要", "table_profile": "数据概况", "funnel_result": "漏斗阶段",
    "funnel_results": "漏斗阶段", "retention_matrix": "留存矩阵", "cohort_retention": "队列留存",
    "semantic_metric_result": "语义指标结果", "exploration_result": "探索结果", "pivot_values": "交叉表",
    "exploration_display": "分组汇总", "exploration_cells": "完整分组结果", "exploration_totals": "范围合计", "distribution_summary": "分布统计",
}


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def primary_result_table(result):
    tables = result.get("result_tables") or {}
    priority = ["adjusted_effect_summary", "experiment_comparison", "experiment_statistics", "experiment_summary",
        "exploration_display", "distribution_summary", "exploration_result", "pivot_values", "metric_comparisons", "dimension_contributions", "period_comparison",
        "semantic_metric_result", "cohort_retention", "retention_matrix", "funnel_result", "funnel_results",
        "metric_trend", "trend", "column_profile", "numeric_summary"]
    names = [*priority, *tables]
    return next((key for key in names if isinstance(tables.get(key), pd.DataFrame) and not tables[key].empty
                 and key not in {"evidence", "recommendations", "data_quality"}), None)


def render_causal_kpis(result):
    frame = result.get("result_tables", {}).get("adjusted_effect_summary")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return False
    row = frame.iloc[0]
    cards = [("原始组间差", f"{float(row['naive_difference']):.4f}" if _finite(row.get("naive_difference")) else "不可计算"),
        ("OLS 调整估计", f"{float(row['adjusted_effect']):.4f}" if _finite(row.get("adjusted_effect")) else "未执行 / 无可用估计"),
        ("实际分析样本", str(int(row["sample_size"])) if _finite(row.get("sample_size")) else "未确认")]
    with st.container(horizontal=True, gap=12):
        for title, value in cards:
            with st.container(width=240):
                render_compact_summary_card(title, value)
    covariates = (result.get("playbook_result") or {}).get("parameters", {}).get("covariates")
    if covariates is None:
        covariates = (result.get("column_mapping") or {}).get("covariates")
    st.caption("估计使用结果变量原量纲；所用控制变量见已执行配置。字段齐全不等于随机化、独立性、无混杂或因果识别前提成立。当前没有倾向评分加权结果。")
    return True


def render_exploration_kpis(result):
    metadata = (result.get("analysis_result_package") or {}).get("metadata", {}).get("exploration")
    if not isinstance(metadata, dict):
        return False
    from insightpilot.ui.formatters import format_metric_name
    cards = [("当前范围观测行数", str(metadata.get("scope_row_count", "未确认")))]
    totals = result.get("result_tables", {}).get("exploration_totals")
    if isinstance(totals, pd.DataFrame) and "scope" in totals and "metric_value" in totals:
        overall = totals.loc[totals["scope"].eq("all")]
        if not overall.empty:
            value = overall["metric_value"].iloc[0]
            card = metadata.get("metric_card") or {}
            label = card.get("display_name") or format_metric_name(card.get("metric_id"))
            cards.append(("全范围 " + str(label or "指标"), f"{float(value):.8g}" if _finite(value) else "未定义"))
            cards.append(("已执行聚合", str(metadata.get("aggregation", "未确认"))))
            if not _finite(value):
                st.warning("当前范围指标未定义：无有效值或比率分母为零。")
    with st.container(horizontal=True, gap=12):
        for title, value in cards:
            with st.container(width=240):
                render_compact_summary_card(title, value)
    # The shared note also belongs to reports. Remove only its known UI boilerplate;
    # retain the dynamic display budget / Others warning and any unfamiliar note.
    note = str(metadata.get("display_note") or "")
    prefix = "完整观测分组保存在 exploration_cells；未观测组合为缺失而非 0。行/列/总计均在原始对应范围重聚合。"
    note = note.removeprefix(prefix).strip()
    if note:
        st.caption(note)
    # Use the current executed request, not the parent's earlier diagnosis or a draft.
    question = str(result.get("question") or "")
    asks_change = any(
        any(term in clause for term in ("跨期", "环比", "同比", "变化贡献", "为什么", "下降原因", "增长原因"))
        and not any(term in clause for term in ("不做", "不分析", "不要", "无需", "不需要", "不进行", "不比较"))
        for clause in re.split(r"[，,。；;]", question))
    if result.get("goal_mode") in {"metric_diagnosis", "growth_trend"} or asks_change:
        st.warning("本次仅完成已选范围汇总，尚未完整回答所请求的跨期变化或原因。")
    return True


def exploration_ui_items(result, items, *, summary=None):
    """Suppress exact repeated exploration prose without changing stored/report data."""
    metadata = (result.get("analysis_result_package") or {}).get("metadata", {}).get("exploration")
    if not isinstance(metadata, dict):
        return items
    redundant = {metadata.get("display_note"), summary,
        "全量当前范围的描述性探索；字段齐全与查询通过不代表独立性、显著性或因果关系已经成立。"}
    return [item for item in items if not isinstance(item, str) or item not in redundant]


def exploration_heading(result):
    metadata = (result.get("analysis_result_package") or {}).get("metadata", {}).get("exploration")
    if not isinstance(metadata, dict):
        return None
    request = metadata.get("request") or {}
    cities = [item for item in request.get("filters", []) if item.get("column") == "city" and item.get("operator") == "eq"]
    if len(cities) == 1 and request.get("date_from") and request.get("date_from") == request.get("date_to"):
        city = _safe_string(str(cities[0].get("value")))
        if city in {"<已脱敏，需重新输入>", "***", "None"}:
            city = "所选城市"
        if result.get("data_source_type") == "synthetic":
            city = synthetic_display_text(city)
        return f"{city}当日概览（{_safe_string(str(request['date_from']))}）"
    return {"pivot": "交叉表概览", "distribution": "字段分布概览", "grouped": "当前范围概览"}.get(request.get("kind"), "当前范围概览")


def render_primary_table(result):
    name = primary_result_table(result)
    if not name:
        return
    frame = result["result_tables"][name]
    from app.components.result_panel import _localized_frame
    st.markdown("**主要结果：" + RESULT_TITLES.get(name, name) + "**")
    preview = frame
    if name == "dimension_contribution":
        st.caption("这里只展示当前范围内的分组值及已有份额；未计算跨期变化贡献，静态份额不能解释指标变化。")
    if name == "dimension_contributions" and "contribution_value" in frame.columns:
        if "dimension" in frame.columns and frame["dimension"].eq("city").any():
            preview = frame.loc[frame["dimension"].eq("city")]
        preview = preview.sort_values("contribution_value", kind="mergesort")
        st.caption("按当前维度的有符号变化排列；这不是当前份额，不跨独立维度相加。")
    # Slice before localizing/copying. Full result remains in the original bounded reference.
    st.dataframe(_localized_frame(preview.head(8), "demo", synthetic=result.get("data_source_type") == "synthetic"),
                 hide_index=True, width="stretch")
    st.caption(f"预览 {min(len(preview), 8)} / {len(preview)} 行；完整结果在“明细”。")


def _overview_specs(result):
    specs = [deepcopy(s) for s in result.get("chart_specs", []) if isinstance(s, dict) and s.get("chart_id")]
    # Prefer one contribution plot and one metric plot; never manufacture missing CI.
    specs.sort(key=lambda s: (0 if s.get("chart_id") == "actual_contribution" else 1 if s.get("chart_id") in {"actual_metric_0", "actual_experiment", "adjusted_effect"} else 2))
    valid = []
    for spec in specs:
        frame = result.get("result_tables", {}).get(spec.get("table_key"))
        if spec.get("chart_id") == "experiment_ci":
            if not isinstance(frame, pd.DataFrame) or not {"confidence_interval_lower", "confidence_interval_upper"}.issubset(frame.columns):
                continue
        if spec.get("chart_id") == "adjusted_effect":
            frame = result.get("result_tables", {}).get("adjusted_effect_summary")
            spec["y"] = [key for key in ("naive_difference", "adjusted_effect") if isinstance(frame, pd.DataFrame) and key in frame and frame[key].notna().any()]
            spec["title"] = "原始差与实际调整估计"
            spec["chart_type"] = "grouped_bar"
        if spec.get("table_key") == "dimension_contribution":
            spec["title"] = "静态分组表现"
            spec["description"] = "当前范围内的分组值；不是跨期变化贡献或因果影响。"
        valid.append(spec)
        if len(valid) == 2:
            break
    return valid


def render_chart_limits(spec):
    """Show actual display limits recorded by the existing chart builder."""
    note = str(spec.metadata.get("display_note") or "")
    series = spec.metadata.get("series_limit_applied")
    if series and f"前{series}个序列" not in note:
        st.caption(f"仅展示前{series}个序列；完整统计不受影响。")
    if note:
        st.caption(_safe_string(note))


def render_key_charts(result):
    from insightpilot.visualization.result_charts import materialize_charts
    specs = _overview_specs(result)
    if not specs:
        return
    config = PerformanceConfig.from_environment()
    cache = st.session_state.get("performance_chart_cache")
    if not isinstance(cache, BoundedCache):
        cache = BoundedCache(1, min(config.result_max_bytes, 16 * 1024 * 1024), config.session_ttl_seconds)
        st.session_state["performance_chart_cache"] = cache
    key = (result.get("run_manifest", {}).get("run_id"), "overview", tuple(s["chart_id"] for s in specs), config.chart_max_points, config.chart_max_series)
    entry = cache.get(key)
    try:
        if entry is None:
            rendered = materialize_charts({**result, "chart_specs": specs}, max_points=config.chart_max_points)
            pairs = rendered
            if result.get("data_source_type") == "synthetic":
                pairs = [(spec, go.Figure(synthetic_display_object(fig.to_dict()))) for spec, fig in rendered]
            entry = {"pairs": pairs, "warnings": tuple(getattr(rendered, "warnings", ()))}
            cache.put(key, entry)
    except (TypeError, ValueError) as exc:
        st.warning("关键图暂未生成；已有结果仍可查看：" + _safe_string(str(exc)))
        return
    for warning in entry["warnings"]:
        st.warning(warning)
    if entry["pairs"]:
        st.markdown("**关键图**")
        with st.container(horizontal=True, gap=16):
            for spec, figure in entry["pairs"]:
                with st.container(width=540):
                    render_chart_limits(spec)
                    # A lightweight display clone leaves cached figures immutable.
                    shown = go.Figure(figure)
                    shown.update_layout(height=310, margin=dict(l=30, r=15, t=45, b=40))
                    st.plotly_chart(shown, width="stretch", key="overview_chart_" + spec.chart_id)
        st.caption(f"每图最多显示 {config.chart_max_points:,} 点；统计使用全量数据。")


def _show_result_tab(value, table_key=None):
    if table_key:
        st.session_state["result_table_selector"] = table_key
    st.session_state["requested_result_tab"] = value


def render_result_actions(result=None):
    tables = (result or {}).get("result_tables") or {}
    evidence = tables.get("evidence")
    table_key = "evidence" if isinstance(evidence, pd.DataFrame) and not evidence.empty else primary_result_table(result or {})
    with st.container(horizontal=True, gap=12):
        st.button("查看证据与明细", key="overview_show_details", on_click=_show_result_tab, args=("结果明细", table_key),
                  disabled=table_key is None)
        st.button("生成 PDF 报告", key="overview_open_report", on_click=_show_result_tab, args=("报告导出",),
                  help="打开报告页；选择具体格式后才生成文件。")
