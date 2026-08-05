"""Results-first analysis information architecture."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.components.developer_panel import render_developer_panel
from app.components.evaluation_panel import render_evaluation_panel
from app.components.export_panel import render_export_panel
from app.components.lineage_panel import render_lineage_panel
from app.components.plan_panel import render_plan_panel
from app.components.reviewer_panel import render_reviewer_panel
from insightpilot.ui.formatters import format_metric_name, format_metric_text
from insightpilot.ui.i18n import t
from insightpilot.ui.renderers import render_caveats
from insightpilot.ui.theme import render_compact_summary_card, render_result_note
from insightpilot.ui.view_modes import should_show_developer_details, should_show_professional_details


TABLE_ORDER = (
    "experiment_comparison",
    "metric_comparisons",
    "anomalies",
    "funnel_decomposition",
    "dimension_contributions",
    "evidence",
    "recommendations",
    "data_quality",
)
TABLE_TITLES = {
    "experiment_comparison": "实验分析结果",
    "metric_comparisons": "指标对比",
    "anomalies": "异常检测",
    "funnel_decomposition": "漏斗拆解",
    "dimension_contributions": "维度贡献",
    "evidence": "证据链",
    "recommendations": "建议清单",
    "data_quality": "数据质量明细",
}
COLUMN_NAMES = {
    "metric_id": "指标",
    "metric_name": "指标名称",
    "current_value": "当前值",
    "baseline_value": "基准值",
    "absolute_change": "绝对变化",
    "relative_change": "相对变化",
    "current_period": "当前周期",
    "baseline_period": "基准周期",
    "sample_size": "样本量",
    "unit": "单位",
    "direction": "变化方向",
    "severity": "异常等级",
    "z_score": "标准分",
    "confidence_note": "数据完整性",
    "date": "日期",
    "actual_value": "实际值",
    "expected_value": "预期值",
    "lower_bound": "下界",
    "upper_bound": "上界",
    "deviation": "偏差",
    "deviation_pct": "偏差比例",
    "method": "计算方法",
    "stage_name": "漏斗阶段",
    "current_count": "当前数量",
    "baseline_count": "基准数量",
    "current_rate": "当前转化率",
    "baseline_rate": "基准转化率",
    "rate_change_pp": "转化率变化百分点",
    "estimated_order_impact": "估算订单影响",
    "contribution_pct": "贡献占比",
    "dimension": "贡献维度",
    "dimension_value": "维度取值",
    "contribution_value": "贡献值",
    "rank": "排序",
    "confidence_flag": "置信提示",
    "evidence_id": "证据编号",
    "claim": "证据结论",
    "metric": "关联指标",
    "result_table": "来源结果表",
    "supporting_values": "支持数值",
    "confidence": "置信度",
    "caveat": "限制",
    "priority": "优先级",
    "action": "建议",
    "reason": "依据",
    "supporting_evidence_ids": "支持证据",
    "suggested_owner": "建议负责方",
    "verification_metric": "验证指标",
    "expected_direction": "预期方向",
    "limitation": "建议限制",
    "table": "数据表",
    "row_count": "行数",
    "missing_values": "缺失值数量",
    "duplicate_rows": "重复行数量",
    "status": "检查状态",
    "control_group": "对照组",
    "treatment_group": "实验组",
    "control_value": "对照组指标值",
    "treatment_value": "实验组指标值",
    "control_sample_size": "对照组样本量",
    "treatment_sample_size": "实验组样本量",
    "total_sample_size": "总样本量",
    "absolute_lift": "绝对 lift",
    "relative_lift": "相对 lift",
    "p_value": "p-value",
    "confidence_interval_lower": "置信区间下界",
    "confidence_interval_upper": "置信区间上界",
    "confidence_level": "置信水平",
    "is_significant": "是否显著",
    "significance_conclusion": "显著性结论",
}


def _main_comparisons(package: dict[str, Any]) -> list[dict[str, Any]]:
    values = package.get("metric_comparisons", []) if isinstance(package, dict) else []
    main = [item for item in values if isinstance(item, dict) and item.get("baseline_period") == "前 7 日均值"]
    return main or [item for item in values if isinstance(item, dict)][:6]


def _format_metric_value(metric_id: str, value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if metric_id.endswith("_rate") or metric_id in {"ctr", "cvr", "conversion_rate"}:
        return f"{numeric:.1%}"
    if metric_id in {"revenue", "refund_amount", "average_order_value"}:
        return f"{numeric:,.2f}"
    return f"{numeric:,.0f}" if abs(numeric) >= 10 else f"{numeric:,.2f}"


def _render_kpis(package: dict[str, Any], view_mode: str) -> None:
    comparisons = _main_comparisons(package)[:6]
    if not comparisons:
        return
    st.subheader("核心指标表现", anchor=False)
    for start in range(0, len(comparisons), 3):
        columns = st.columns(3)
        for column, item in zip(columns, comparisons[start:start + 3]):
            metric_id = str(item.get("metric_id", ""))
            delta = float(item.get("relative_change", 0.0) or 0.0)
            severity = {"HIGH": "高风险", "MEDIUM": "需要关注", "LOW": "正常波动"}.get(str(item.get("severity")), "待复核")
            with column:
                render_compact_summary_card(
                    format_metric_name(metric_id, developer_mode=should_show_developer_details(view_mode)),
                    f"{_format_metric_value(metric_id, item.get('current_value'))}\n较{item.get('baseline_period', '基准')}{'上升' if delta > 0 else '下降' if delta < 0 else '持平'} {abs(delta):.1%}",
                    status=severity,
                )


def _render_result_highlights(package: dict[str, Any]) -> None:
    anomalies = [item for item in package.get("anomalies", []) if isinstance(item, dict) and item.get("severity") in {"HIGH", "MEDIUM"}]
    contributions = [
        item for item in package.get("dimension_contributions", [])
        if isinstance(item, dict) and float(item.get("contribution_value", 0.0) or 0.0) < 0 and item.get("dimension_value") != "Others"
    ]
    funnel = sorted(
        [item for item in package.get("funnel_results", []) if isinstance(item, dict) and float(item.get("estimated_order_impact", 0.0) or 0.0) < 0],
        key=lambda item: float(item.get("estimated_order_impact", 0.0)),
    )
    recommendations = [item for item in package.get("recommendations", []) if isinstance(item, dict)]
    columns = st.columns(2)
    with columns[0]:
        render_compact_summary_card(
            "主要异常",
            [f"{format_metric_name(item.get('metric_id'))}：{item.get('severity')}" for item in anomalies[:3]] or ["未发现中高等级异常"],
        )
    with columns[1]:
        render_compact_summary_card(
            "主要负向贡献",
            [f"{item.get('dimension')}：{item.get('dimension_value')}" for item in contributions[:3]] or ["当前没有可用维度贡献"],
        )
    columns = st.columns(2)
    with columns[0]:
        render_compact_summary_card(
            "漏斗主要变化",
            [f"{item.get('stage_name')}：估算影响 {float(item.get('estimated_order_impact', 0.0)):.1f}" for item in funnel[:3]] or ["当前分析类型不适用交易漏斗"],
        )
    with columns[1]:
        render_compact_summary_card(
            "建议优先级",
            [f"{item.get('priority')}：{item.get('action')}" for item in recommendations[:3]] or ["尚未生成证据绑定建议"],
        )


def _render_experiment_summary(package: dict[str, Any], view_mode: str) -> None:
    values = [item for item in package.get("experiment_results", []) if isinstance(item, dict)]
    if not values:
        return
    item = values[0]
    metric_id = str(item.get("metric_id", ""))
    st.subheader("实验分析结果", anchor=False)
    columns = st.columns(2)
    with columns[0]:
        render_compact_summary_card(
            "实验组与对照组",
            [
                f"实验组：{_format_metric_value(metric_id, item.get('treatment_value'))}",
                f"对照组：{_format_metric_value(metric_id, item.get('control_value'))}",
            ],
        )
    with columns[1]:
        render_compact_summary_card(
            "样本量",
            [
                f"实验组：{int(item.get('treatment_sample_size', 0)):,}",
                f"对照组：{int(item.get('control_sample_size', 0)):,}",
                f"合计：{int(item.get('total_sample_size', 0)):,}",
            ],
        )
    columns = st.columns(2)
    with columns[0]:
        render_compact_summary_card(
            "实验提升",
            [
                f"绝对 lift：{_format_metric_value(metric_id, item.get('absolute_lift'))}",
                f"相对 lift：{float(item.get('relative_lift', 0)):.2%}",
            ],
        )
    with columns[1]:
        render_compact_summary_card(
            "显著性检验",
            [
                f"p-value：{float(item.get('p_value', 1)):.6g}",
                f"95% 置信区间：[{_format_metric_value(metric_id, item.get('confidence_interval_lower'))}, {_format_metric_value(metric_id, item.get('confidence_interval_upper'))}]",
                f"显著性结论：{item.get('significance_conclusion', '待复核')}",
            ],
            status="显著" if item.get("is_significant") else "未显著",
        )
    if should_show_developer_details(view_mode):
        st.caption(f"分析指标：{format_metric_name(metric_id, developer_mode=True)}")


def _render_findings(result: dict[str, Any], view_mode: str) -> None:
    findings = result.get("findings", [])
    if not findings:
        return
    with st.expander("查看补充发现", expanded=False, icon=":material/notes:"):
        for finding in findings:
            st.markdown(f"- {format_metric_text(finding, developer_mode=should_show_developer_details(view_mode))}")


def _render_visuals(result: dict[str, Any]) -> None:
    chart_pairs = result.get("chart_pairs", [])
    charts = result.get("charts", [])
    if chart_pairs:
        for spec, figure in chart_pairs:
            st.plotly_chart(figure, width="stretch", key=f"chart_{spec.chart_id}")
    elif charts:
        for index, figure in enumerate(charts):
            st.plotly_chart(figure, width="stretch", key=f"chart_{index}")
    else:
        st.caption(t("empty.no_chart"))


def _localized_frame(frame: pd.DataFrame, view_mode: str) -> pd.DataFrame:
    display = frame.head(2_000).copy()
    if "metric_id" in display.columns:
        display["metric_id"] = display["metric_id"].map(
            lambda value: format_metric_name(value, developer_mode=should_show_developer_details(view_mode))
        )
    for metric_column in ("metric", "verification_metric"):
        if metric_column in display.columns:
            display[metric_column] = display[metric_column].map(
                lambda value: format_metric_name(value, developer_mode=should_show_developer_details(view_mode))
            )
    for group_column in ("control_group", "treatment_group"):
        if group_column in display.columns:
            display[group_column] = display[group_column].replace({"control": "对照组", "treatment": "实验组"})
    if "is_significant" in display.columns:
        display["is_significant"] = display["is_significant"].map(lambda value: "显著" if bool(value) else "未显著")
    return display.rename(columns={name: COLUMN_NAMES.get(name, name) for name in display.columns})


def _render_tables(result: dict[str, Any], view_mode: str) -> None:
    if result.get("execution_mode") == "plan_only":
        render_result_note("请先点击“开始分析”，系统将在执行后生成指标异常、漏斗拆解、维度贡献和建议明细。")
        return
    tables = result.get("result_tables", {})
    if not isinstance(tables, dict) or not tables:
        st.error("结构化结果生成失败：本次执行没有返回结果表。请查看质量检查中的具体错误。")
        return
    for key in TABLE_ORDER:
        title = TABLE_TITLES[key]
        frame = tables.get(key)
        if key == "experiment_comparison" and (not isinstance(frame, pd.DataFrame) or frame.empty):
            continue
        st.subheader(title, anchor=False)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            if key == "funnel_decomposition":
                st.caption("当前分析类型不适用交易漏斗拆解。")
            else:
                st.caption(f"当前分析没有适用的{title}记录。")
            continue
        display = _localized_frame(frame, view_mode)
        st.dataframe(display, hide_index=True, width="stretch")
        if should_show_professional_details(view_mode):
            st.download_button(
                f"下载{title} CSV",
                display.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{key}.csv",
                mime="text/csv",
                icon=":material/download:",
                key=f"download_result_table_{key}",
            )
        if should_show_developer_details(view_mode):
            st.caption(f"结果表标识：{key}")
    extra_keys = [key for key in tables if key not in TABLE_ORDER]
    if extra_keys:
        with st.expander("其他分析剧本结果表", expanded=False, icon=":material/table_chart:"):
            for key in extra_keys:
                frame = tables[key]
                if isinstance(frame, pd.DataFrame):
                    st.markdown(f"**{key if should_show_developer_details(view_mode) else '补充结果'}**")
                    st.dataframe(frame.head(2_000), hide_index=True, width="stretch")


def _render_overview(result: dict[str, Any], view_mode: str) -> None:
    package = result.get("analysis_result_package", {}) if isinstance(result.get("analysis_result_package"), dict) else {}
    if result.get("execution_mode") == "plan_only" or package.get("scenario") == "plan_only":
        render_result_note("当前为分析方案预览。该步骤不执行实际计算，也不产生分析结论。")
        render_plan_panel(result, view_mode="demo")
        return
    st.subheader("执行摘要", anchor=False)
    st.write(format_metric_text(package.get("executive_summary") or result.get("summary") or "本次分析已执行。"))
    _render_experiment_summary(package, view_mode)
    _render_kpis(package, view_mode)
    _render_result_highlights(package)
    _render_findings(result, view_mode)
    render_caveats(result.get("caveats", []), view_mode)
    reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
    columns = st.columns(3)
    with columns[0]:
        render_compact_summary_card("质量评分", str(reviewer.get("score", "-")))
    with columns[1]:
        render_compact_summary_card("检查状态", {"PASS": "通过", "WARN": "需要关注", "FAIL": "未通过"}.get(reviewer.get("status"), "待检查"))
    with columns[2]:
        render_compact_summary_card("主要警告", str(len(reviewer.get("issues", []))))
    with st.expander("查看分析方案", expanded=False, icon=":material/account_tree:"):
        render_plan_panel(result, view_mode="demo")


def render_result_panel(result: dict[str, Any], view_mode: str) -> None:
    tabs = [t("tab.overview"), t("tab.visual"), t("tab.results"), t("tab.quality"), t("tab.export")]
    if should_show_professional_details(view_mode):
        tabs.append(t("tab.professional"))
    if should_show_developer_details(view_mode):
        tabs.append(t("tab.developer"))
    containers = st.tabs(tabs, key="result_tabs")
    with containers[0]:
        _render_overview(result, view_mode)
    with containers[1]:
        st.subheader(t("section.visual_diagnostics"), anchor=False)
        _render_visuals(result)
    with containers[2]:
        _render_tables(result, view_mode)
    with containers[3]:
        render_reviewer_panel(result, view_mode)
    with containers[4]:
        render_export_panel(result)
    index = 5
    if should_show_professional_details(view_mode):
        with containers[index]:
            render_plan_panel(result, view_mode="professional")
            render_lineage_panel(result, view_mode)
        index += 1
    if should_show_developer_details(view_mode):
        with containers[index]:
            render_developer_panel(result, view_mode)
            render_evaluation_panel()
