"""Results-first analysis information architecture."""

from __future__ import annotations

from typing import Any
import inspect
import math
import numpy as np

from insightpilot.ui.experiment_display import experiment_display, finite_number
from insightpilot.reports.safety import safe_spreadsheet_frame
from insightpilot.reports.manifest import _safe_string
from insightpilot.ui.table_labels import localize_result_value
from insightpilot.performance import BoundedCache, PerformanceConfig

import pandas as pd
import plotly.graph_objects as go

from insightpilot.ui.synthetic_display import synthetic_display_text, synthetic_display_object
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
    if finite_number(value) == "不可计算":
        return "不可计算"
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
            raw_delta = item.get("relative_change")
            delta = float(raw_delta or 0.0)
            delta_text = "不可计算" if finite_number(raw_delta) == "不可计算" else f"{'上升' if delta > 0 else '下降' if delta < 0 else '持平'} {abs(delta):.1%}"
            severity = {"HIGH": "高风险", "MEDIUM": "需要关注", "LOW": "正常波动"}.get(str(item.get("severity")), "待复核")
            with column:
                render_compact_summary_card(
                    format_metric_name(metric_id, developer_mode=should_show_developer_details(view_mode)),
                    f"{_format_metric_value(metric_id, item.get('current_value'))}\n较{item.get('baseline_period', '基准')}{delta_text}",
                    status=severity,
                )


def _render_result_highlights(package: dict[str, Any], *, synthetic: bool = False) -> None:
    display = synthetic_display_text if synthetic else str
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
    cards = []
    if anomalies:
        cards.append(("主要异常", [f"{format_metric_name(item.get('metric_id'))}：{localize_result_value(item.get('severity'), 'severity')}" for item in anomalies[:3]]))
    if contributions:
        cards.append(("主要负向贡献", [display(f"{item.get('dimension')}：{item.get('dimension_value')}") for item in contributions[:3]]))
    if funnel:
        cards.append(("漏斗主要变化", [f"{item.get('stage_name')}：估算影响 {float(item.get('estimated_order_impact', 0.0)):.1f}" for item in funnel[:3]]))
    if recommendations:
        cards.append(("建议优先级", [display(f"{item.get('priority')}：{item.get('action')}") for item in recommendations[:3]]))
    # Method-specific absence is not a result: do not fill non-transaction runs
    # with order/anomaly/funnel placeholder cards. Existing nonempty cards retain
    # their exact content, order and two-column layout.
    for offset in range(0, len(cards), 2):
        columns = st.columns(2)
        for column, (title, content) in zip(columns, cards[offset:offset + 2]):
            with column:
                render_compact_summary_card(title, content)


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
    formatted = experiment_display(item)
    columns = st.columns(2)
    with columns[0]:
        render_compact_summary_card(
            "实验提升",
            [
                f"绝对提升（lift）：{formatted['绝对提升（lift）']}",
                f"相对提升（lift）：{formatted['相对提升（lift）']}",
            ],
        )
    with columns[1]:
        render_compact_summary_card(
            "显著性检验",
            [
                f"p-value：{formatted['p-value']}",
                next(f"{label}：{value}" for label, value in formatted.items() if "置信区间" in label),
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
            text = format_metric_text(finding, developer_mode=should_show_developer_details(view_mode))
            st.markdown(f"- {synthetic_display_text(text) if result.get('data_source_type') == 'synthetic' else text}")


def _exploration_chart_settings(result):
    metadata = (result.get("analysis_result_package") or {}).get("metadata", {}).get("exploration")
    if not isinstance(metadata, dict):
        return None
    kind = metadata.get("request", {}).get("kind")
    if kind == "pivot":
        options = ["heatmap", "grouped_bar", "table"]
        if metadata.get("aggregation") in {"sum", "count"}:
            options.insert(2, "bar")
    elif kind == "grouped":
        options = ["bar", "line", "table"]
    elif kind == "distribution":
        distribution = metadata.get("distribution_type")
        options = ["histogram", "box", "table"] if distribution == "numeric" else ["line", "bar", "table"] if distribution == "date" else ["bar", "table"]
    else:
        return None
    labels = {"heatmap": "交叉表热力图", "grouped_bar": "并列柱状图", "bar": "堆叠柱状图" if kind == "pivot" else "柱状图",
              "line": "折线图", "histogram": "直方图", "box": "箱线图", "table": "表格"}
    key = "exploration_chart_type_" + str(result.get("run_manifest", {}).get("run_id"))
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    selected = st.selectbox("展示图型", options, key=key, format_func=labels.get)
    st.caption("这里只改变已计算结果的展示；改变指标、维度、时间范围、粒度或筛选，请回数据探索明确生成新结果。")
    if kind == "pivot" and metadata.get("aggregation") not in {"sum", "count"}:
        st.caption("当前指标非可加总量，不提供堆叠图；合计采用对应原始范围重新聚合的实际结果。")
    if kind == "grouped" and selected == "line" and not metadata.get("request", {}).get("time_grain"):
        st.caption("连线仅连接当前分组的展示顺序，不表示时间连续性或因果关系。")
    return kind, selected


def _render_visuals(result: dict[str, Any]) -> None:
    """Materialize one selected chart only while its page is open."""
    from insightpilot.visualization.result_charts import materialize_charts
    chart_settings = _exploration_chart_settings(result)
    chart_style = None
    if chart_settings:
        kind, chart_style = chart_settings
        if chart_style == "table":
            _render_tables(result, "professional")
            return
        from insightpilot.analysis.exploration import build_exploration_chart_spec
        spec = build_exploration_chart_spec(result.get("result_tables", {}), kind, chart_style)
        result = {**result, "chart_specs": [spec] if spec else []}
    config = PerformanceConfig.from_environment()
    specs = result.get("chart_specs", [])
    choices = {str(spec["chart_id"]): spec for spec in specs if isinstance(spec, dict) and spec.get("chart_id")}
    if not choices:
        st.caption(t("empty.no_chart"))
        return
    if st.session_state.get("result_chart_selector") not in choices:
        st.session_state["result_chart_selector"] = next(iter(choices))
    selected = next(iter(choices)) if chart_settings else st.selectbox("选择图表", list(choices), format_func=lambda key: synthetic_display_text(choices[key].get("title", key)) if result.get("data_source_type") == "synthetic" else choices[key].get("title", key), key="result_chart_selector")
    cache = st.session_state.get("performance_chart_cache")
    if not isinstance(cache, BoundedCache):
        cache = BoundedCache(1, min(config.result_max_bytes, 16 * 1024 * 1024), config.session_ttl_seconds)
        st.session_state["performance_chart_cache"] = cache
    key = (result.get("run_manifest", {}).get("run_id"), selected, chart_style, config.chart_max_points, config.chart_max_series)
    entry = cache.get(key)
    try:
        if entry is None:
            pairs = materialize_charts(result, spec_ids=[selected], max_points=config.chart_max_points)
            warnings = tuple(getattr(pairs, "warnings", ()))
            if result.get("data_source_type") == "synthetic":
                pairs = [(spec, go.Figure(synthetic_display_object(figure.to_dict()))) for spec, figure in pairs]
            entry = {"pairs": pairs, "warnings": warnings}
            cache.put(key, entry)
    except (ValueError, TypeError) as exc:
        st.warning(f"图表未生成或超过显示预算，分析结果仍可查看：{_safe_string(str(exc))}")
        return
    for warning in entry["warnings"]:
        st.warning(warning)
    pairs = entry["pairs"]
    st.caption(f"当前仅构建所选图表；展示预算每图 {config.chart_max_points:,} 点。展示筛选或确定性采样不参与统计计算，完整结果与报告结论保持原口径。")
    for spec, figure in pairs:
        if spec.description:
            st.caption(synthetic_display_text(spec.description) if result.get("data_source_type") == "synthetic" else spec.description)
        st.plotly_chart(figure, width="stretch", key=f"chart_{spec.chart_id}")


def _localized_frame(frame: pd.DataFrame, view_mode: str, *, synthetic: bool = False) -> pd.DataFrame:
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
    for column in display.columns:
        display[column] = display[column].map(lambda value: localize_result_value(value, column))
    if synthetic and not should_show_developer_details(view_mode):
        display = display.map(lambda value: synthetic_display_text(value) if isinstance(value, str) else value)
    return display.rename(columns={name: COLUMN_NAMES.get(name, name) for name in display.columns})


def paginate_result_table(frame: pd.DataFrame, *, page: int = 1, page_size: int = 100,
                          sort_column: str | None = None, descending: bool = False,
                          filter_column: str | None = None, filter_text: str = "") -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Filter/sort the full result, then slice; stable ties keep original row order."""
    if page_size not in {50, 100, 200, 500}:
        raise ValueError("每页行数必须为50、100、200或500")
    selected = frame
    if filter_text and filter_column in frame.columns:
        selected = selected.loc[selected[filter_column].astype(str).str.contains(filter_text, regex=False, case=False, na=False)]
    if sort_column in selected.columns:
        selected = selected.sort_values(sort_column, ascending=not descending, kind="mergesort", na_position="last")
    page = max(1, min(int(page), max(1, math.ceil(len(selected) / page_size))))
    return selected.iloc[(page - 1) * page_size:page * page_size], selected, page


def _render_tables(result: dict[str, Any], view_mode: str) -> None:
    if result.get("execution_mode") == "plan_only":
        render_result_note("请先点击“开始分析”，系统将在执行后生成指标异常、漏斗拆解、维度贡献和建议明细。")
        return
    tables = result.get("result_tables", {})
    names = [key for key in TABLE_ORDER if isinstance(tables.get(key), pd.DataFrame) and not tables[key].empty]
    names += [key for key, frame in tables.items() if key not in names and key not in TABLE_ORDER and isinstance(frame, pd.DataFrame)]
    if not names:
        st.error("本次执行没有可用结果表，请查看质量检查中的具体说明。")
        return
    if st.session_state.get("result_table_selector") not in names:
        st.session_state["result_table_selector"] = names[0]
    key = st.selectbox("选择结果明细表", names, format_func=lambda value: TABLE_TITLES.get(value, value), key="result_table_selector")
    title = TABLE_TITLES.get(key, key)
    frame = tables[key]
    run_id = str(result.get("run_manifest", {}).get("run_id", "analysis"))
    control_key = f"result_table_{run_id}_{key}"
    st.subheader(title, anchor=False)
    with st.container(horizontal=True):
        page_size = st.selectbox("每页行数", [50, 100, 200, 500], index=[50, 100, 200, 500].index(PerformanceConfig.from_environment().table_page_size), key=f"{control_key}_size")
        sort_column = st.selectbox("全表排序字段", [None, *frame.columns], format_func=lambda value: "保持原始顺序" if value is None else COLUMN_NAMES.get(value, value), key=f"{control_key}_sort")
        descending = st.checkbox("降序", key=f"{control_key}_descending")
    with st.form(f"{control_key}_filter"):
        filter_column = st.selectbox("筛选字段", [None, *frame.columns], format_func=lambda value: "不筛选" if value is None else COLUMN_NAMES.get(value, value), key=f"{control_key}_filter_column")
        filter_text = st.text_input("筛选文本（不区分大小写，匹配完整结果集）", key=f"{control_key}_filter_text")
        st.form_submit_button("应用明细筛选")
    # Cache only row positions, avoiding another retained copy of the full result.
    view_cache = st.session_state.get("performance_table_view_cache")
    if not isinstance(view_cache, BoundedCache):
        config = PerformanceConfig.from_environment()
        view_cache = BoundedCache(1, min(config.result_max_bytes, 16 * 1024 * 1024), config.session_ttl_seconds)
        st.session_state["performance_table_view_cache"] = view_cache
    view_key = (run_id, key, sort_column, descending, filter_column, filter_text)
    entry = view_cache.get(view_key)
    try:
        if entry is None:
            positions = None
            if (filter_text and filter_column in frame.columns) or sort_column in frame.columns:
                positions = np.arange(len(frame), dtype=np.int64)
                if filter_text and filter_column in frame.columns:
                    mask = frame[filter_column].astype(str).str.contains(filter_text, regex=False, case=False, na=False).to_numpy()
                    positions = positions[mask]
                if sort_column in frame.columns:
                    order = frame[sort_column].iloc[positions].reset_index(drop=True).sort_values(ascending=not descending, kind="mergesort", na_position="last").index.to_numpy()
                    positions = positions[order]
            entry = {"positions": positions}
            view_cache.put(view_key, entry)
    except (TypeError, ValueError) as exc:
        st.warning(f"无法应用当前完整结果排序或筛选：{exc}。请选择其他字段或调整明确预算。")
        return
    positions = entry["positions"]
    selected_count = len(frame) if positions is None else len(positions)
    total_pages = max(1, math.ceil(selected_count / page_size))
    page_key = f"{control_key}_page"
    if not 1 <= int(st.session_state.get(page_key, 1)) <= total_pages:
        st.session_state[page_key] = 1
    st.session_state.setdefault(page_key, 1)
    page = int(st.number_input("页码", min_value=1, max_value=total_pages, step=1, key=page_key))
    page_frame = frame.iloc[(page - 1) * page_size:page * page_size] if positions is None else frame.iloc[positions[(page - 1) * page_size:page * page_size]]
    start = (page - 1) * page_size + 1 if selected_count else 0
    stop = min(page * page_size, selected_count)
    st.caption(f"展示第 {start:,}–{stop:,} 行，筛选后共 {selected_count:,} 行，原始结果共 {len(frame):,} 行；第 {page}/{total_pages} 页。排序与筛选应用于完整结果集。表格工具栏的下载仅包含当前页。")
    display = _localized_frame(page_frame, view_mode, synthetic=result.get("data_source_type") == "synthetic")
    st.dataframe(display, hide_index=True, width="stretch", lazy=False)
    if should_show_professional_details(view_mode):
        st.caption("完整筛选结果 CSV 最多导出 100,000 行；超过上限明确截断，完整分析仍保留。")
        cache = st.session_state.get("performance_table_csv_cache")
        if not isinstance(cache, BoundedCache):
            config = PerformanceConfig.from_environment()
            cache = BoundedCache(1, config.export_max_bytes, config.session_ttl_seconds)
            st.session_state["performance_table_csv_cache"] = cache
        csv_key = (run_id, key, sort_column, descending, filter_column, filter_text)
        if st.button(f"生成{title} CSV", key=f"{control_key}_prepare_csv"):
            try:
                export_frame = frame.head(100_000) if positions is None else frame.iloc[positions[:100_000]]
                csv = safe_spreadsheet_frame(export_frame).to_csv(index=False).encode("utf-8-sig")
                cache.put(csv_key, csv)
            except (ValueError, TypeError) as exc:
                st.warning(f"CSV 生成失败，当前分析仍可查看：{_safe_string(str(exc))}")
        csv = cache.get(csv_key)
        if csv is not None:
            if selected_count > 100_000:
                st.warning(f"CSV 实际导出前 100,000 行，共 {selected_count:,} 行；未导出的行不在本文件中。")
            st.download_button(f"下载{title} CSV", csv, file_name=f"{key}.csv", mime="text/csv", on_click="ignore", key=f"{control_key}_download_csv")
    if should_show_developer_details(view_mode):
        st.caption(f"结果表标识：{key}")


def _render_overview(result: dict[str, Any], view_mode: str) -> None:
    package = result.get("analysis_result_package", {}) if isinstance(result.get("analysis_result_package"), dict) else {}
    if result.get("execution_mode") == "plan_only" or package.get("scenario") == "plan_only":
        render_result_note("当前为分析方案预览。该步骤不执行实际计算，也不产生分析结论。")
        render_plan_panel(result, view_mode="demo")
        return
    status = result.get("execution_status", "COMPLETED")
    if status != "COMPLETED":
        label = {"NEEDS_INPUT": "待补充信息", "INVALID_INPUT": "配置无效", "UNSUPPORTED": "当前条件不支持", "WAITING_APPROVAL": "等待审批", "FAILED": "分析失败"}.get(status, "分析尚未完成")
        st.warning(label + "。当前运行没有可作为成功结论的分析结果。")
        for issue in result.get("analysis_advice", {}).get("blocking_issues", []):
            st.write(_safe_string(str(issue.get("message_zh", issue))))
        for error in result.get("errors", []):
            st.error(_safe_string(str(error)))
        return
    st.subheader("执行摘要", anchor=False)
    summary = format_metric_text(package.get("executive_summary") or result.get("summary") or "本次分析已执行。")
    st.write(synthetic_display_text(summary) if result.get("data_source_type") == "synthetic" else summary)
    from app.components.result_layout import render_causal_kpis, render_primary_table, render_key_charts, render_result_actions, render_exploration_kpis
    is_causal = render_causal_kpis(result)
    is_exploration = render_exploration_kpis(result)
    if not is_causal and not is_exploration:
        _render_experiment_summary(package, view_mode)
        _render_kpis(package, view_mode)
    if any(package.get(key) for key in ("anomalies", "dimension_contributions", "funnel_results", "recommendations")) and not is_causal and not is_exploration:
        _render_result_highlights(package, synthetic=result.get("data_source_type") == "synthetic")
    render_key_charts(result)
    render_primary_table(result)
    render_result_actions()
    _render_findings(result, view_mode)
    render_caveats(result.get("caveats", []), view_mode)
    reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
    columns = st.columns(3)
    with columns[0]:
        render_compact_summary_card("流程检查评分", str(reviewer.get("score", "-")))
    with columns[1]:
        render_compact_summary_card("检查状态", {"PASS": "通过", "WARN": "需要关注", "FAIL": "未通过"}.get(reviewer.get("status"), "待检查"))
    with columns[2]:
        render_compact_summary_card("主要警告", str(len(reviewer.get("issues", []))))
    st.caption("流程检查评分不代表统计结论百分之百正确；统计前提与证据状态请查看质量检查。")
    details = st.expander("查看分析方案", expanded=False, icon=":material/account_tree:", key="overview_plan_open", on_change="rerun")
    if details.open:
        with details:
            render_plan_panel(result, view_mode="demo")


def _remember_result_tab() -> None:
    st.session_state["performance_selected_result_tab"] = st.session_state.get("result_tabs")


def render_result_panel(result: dict[str, Any], view_mode: str = "demo") -> None:
    tabs = [t("tab.overview"), t("tab.visual"), t("tab.results"), t("tab.export")]
    labels = dict(zip(tabs, ["结论", "图表", "明细", "报告"]))
    requested = st.session_state.pop("requested_result_tab", None)
    selected = requested or st.session_state.get("performance_selected_result_tab", tabs[0])
    if selected not in tabs:
        selected = tabs[0]
    st.session_state["performance_selected_result_tab"] = selected
    st.session_state["result_tabs"] = selected
    selected = st.segmented_control("分析结果", tabs, format_func=labels.get, required=True,
        key="result_tabs", on_change=_remember_result_tab, label_visibility="collapsed")
    def reports():
        if result.get("execution_status", "COMPLETED") == "COMPLETED" and result.get("execution_mode") != "plan_only":
            render_export_panel(result)
        else:
            st.info("当前运行尚未成功完成，不能生成成功分析报告；请先完成配置、审批或执行。")
    renderers = {tabs[0]: lambda: _render_overview(result, "demo"), tabs[1]: lambda: _render_visuals(result),
                 tabs[2]: lambda: _render_tables(result, "professional"), tabs[3]: reports}
    renderers[selected]()
    from insightpilot.analysis.quality import quality_rows
    st.caption("质量摘要：" + "；".join(row["检查维度"] + "：" + row["状态"] for row in quality_rows(result)))
    quality = st.expander("查看口径与质量", expanded=bool(st.session_state.get("guided_quality", False)), key="guided_quality", on_change="rerun")
    if quality.open:
        with quality:
            from app.components.metric_definition_panel import render_metric_definitions
            render_metric_definitions(result.get("metric_definitions", []), view_mode="professional", required=True)
            render_reviewer_panel(result, "professional")
    details = st.expander("技术详情", expanded=bool(st.session_state.get("guided_technical", False)), key="guided_technical", on_change="rerun")
    if details.open:
        with details:
            render_plan_panel(result, view_mode="developer")
            render_lineage_panel(result, "developer")
            render_developer_panel(result, "developer")
            evaluation = st.expander("评估工具", key="evaluation_tools_open", on_change="rerun")
            if evaluation.open:
                with evaluation:
                    render_evaluation_panel()
