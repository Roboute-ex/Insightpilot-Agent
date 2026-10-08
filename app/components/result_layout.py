"""Method-specific result presentation from already computed tables and specs."""
from __future__ import annotations
from copy import deepcopy
import math
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
    "dimension_contribution": "维度贡献", "period_comparison": "周期对比",
    "trend": "指标趋势", "metric_trend": "指标趋势", "column_profile": "字段概览",
    "numeric_summary": "数值摘要", "table_profile": "数据概况", "funnel_result": "漏斗阶段",
    "funnel_results": "漏斗阶段", "retention_matrix": "留存矩阵", "cohort_retention": "队列留存",
    "semantic_metric_result": "语义指标结果", "exploration_result": "探索结果", "pivot_values": "交叉表",
    "exploration_display": "探索展示分组", "exploration_cells": "完整分组结果", "exploration_totals": "重新聚合的合计", "distribution_summary": "全量分布统计",
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
    with st.container(horizontal=True, gap=12):
        for title, value in cards:
            with st.container(width=240):
                render_compact_summary_card(title, value)
    if metadata.get("display_note"):
        st.caption(metadata["display_note"])
    return True


def render_primary_table(result):
    name = primary_result_table(result)
    if not name:
        return
    frame = result["result_tables"][name]
    from app.components.result_panel import _localized_frame
    st.markdown("**主要结果：" + RESULT_TITLES.get(name, name) + "**")
    preview = frame
    if name == "dimension_contributions" and "contribution_value" in frame.columns:
        if "dimension" in frame.columns and frame["dimension"].eq("city").any():
            preview = frame.loc[frame["dimension"].eq("city")]
        preview = preview.sort_values("contribution_value", kind="mergesort")
        st.caption("按当前维度的有符号变化排列；这不是当前份额，不跨独立维度相加。")
    # Slice before localizing/copying. Full result remains in the original bounded reference.
    st.dataframe(_localized_frame(preview.head(8), "demo", synthetic=result.get("data_source_type") == "synthetic"),
                 hide_index=True, width="stretch")
    st.caption(f"预览 {min(len(preview), 8)} / {len(preview)} 行；完整排序、筛选和分页在“明细”。结果表标识：{name}。")
    evidence = result.get("result_tables", {}).get("evidence")
    if isinstance(evidence, pd.DataFrame) and not evidence.empty:
        st.caption(f"此运行有 {len(evidence)} 条结构化证据；在“明细”选择证据链，可核对同一运行的来源表与支持值。")


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
        valid.append(spec)
        if len(valid) == 2:
            break
    return valid


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
                    # A lightweight display clone leaves cached figures immutable.
                    shown = go.Figure(figure)
                    shown.update_layout(height=310, margin=dict(l=30, r=15, t=45, b=40))
                    st.plotly_chart(shown, width="stretch", key="overview_chart_" + spec.chart_id)
        st.caption(f"图形来自已计算结果；最多显示 {config.chart_max_points:,} 点，展示预算不改变全量统计。更多图型在“图表”。")


def _show_result_tab(value):
    st.session_state["requested_result_tab"] = value


def render_result_actions():
    with st.container(horizontal=True, gap=12):
        st.button("查看完整明细", key="overview_show_details", on_click=_show_result_tab, args=("结果明细",))
        st.button("生成 PDF 报告", key="overview_open_report", on_click=_show_result_tab, args=("报告导出",),
                  help="打开报告页；选择具体格式后才生成文件。")
