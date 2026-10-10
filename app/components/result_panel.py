"""Results-first analysis information architecture."""

from __future__ import annotations

from typing import Any
import inspect
import math
import re
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


def _format_metric_value(metric_id: str, value: Any, *, unit: str | None = None) -> str:
    if finite_number(value) == "不可计算":
        return "不可计算"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    rate = unit == "比例" if unit is not None else metric_id.endswith("_rate") or metric_id in {"ctr", "cvr", "conversion_rate"}
    if rate:
        return f"{numeric:.1%}"
    if metric_id in {"revenue", "refund_amount", "average_order_value"}:
        return f"{numeric:,.2f}"
    return f"{numeric:,.0f}" if abs(numeric) >= 10 else f"{numeric:,.2f}"


def _comparison_note(value: Any) -> str:
    """Keep concrete completeness/calculation problems; omit known implementation prose."""
    notes = []
    for part in str(value or "").split("；"):
        part = part.strip()
        complete = re.fullmatch(r"基准日期完整性 (\d+)/(\d+)", part)
        if complete and complete[1] == complete[2]:
            continue
        if re.fullmatch(r"z-score 使用总体标准差，基准样本数 \d+", part):
            continue
        if part in {"阈值不代表显著性", "比率采用分子合计/分母合计"}:
            continue
        if part:
            notes.append(part)
    return "；".join(notes)


def _render_kpis(package: dict[str, Any], view_mode: str, *, comparisons=None, heading="核心指标表现", result=None) -> None:
    from app.components.diagnostic_summary import metric_unit
    comparisons = _main_comparisons(package)[:6] if comparisons is None else comparisons
    if not comparisons:
        return
    if heading:
        st.subheader(heading, anchor=False)
    for start in range(0, len(comparisons), 3):
        columns = st.columns(3)
        for column, item in zip(columns, comparisons[start:start + 3]):
            metric_id = str(item.get("metric_id", ""))
            raw_delta = item.get("relative_change")
            delta = float(raw_delta or 0.0)
            delta_text = "不可计算" if finite_number(raw_delta) == "不可计算" else f"{'上升' if delta > 0 else '下降' if delta < 0 else '持平'} {abs(delta):.1%}"
            severity = {"HIGH": "高风险", "MEDIUM": "需要关注", "LOW": "正常波动"}.get(str(item.get("severity")), "待复核")
            absolute = item.get("absolute_change")
            unit = metric_unit(result or {}, metric_id, str(item.get("unit") or "单位未确认"))
            rate = unit == "比例"
            absolute_text = "不可计算" if finite_number(absolute) == "不可计算" else (
                f"{float(absolute) * 100:+.2f} 个百分点" if rate else f"{float(absolute):+,.2f}")
            with column:
                render_compact_summary_card(
                    format_metric_name(metric_id, developer_mode=should_show_developer_details(view_mode)),
                    [f"当前值：{_format_metric_value(metric_id, item.get('current_value'), unit=unit)}（{unit}）",
                     f"{item.get('baseline_period', '基准')}：{_format_metric_value(metric_id, item.get('baseline_value'), unit=unit)}",
                     f"绝对变化：{absolute_text}；相对变化：{delta_text}"],
                    status=severity,
                )
                note = _comparison_note(item.get("confidence_note"))
                if note:
                    st.caption(_safe_string(note))
    shared_notes = []
    if any("比率采用分子合计/分母合计" in str(item.get("confidence_note", "")) for item in comparisons):
        shared_notes.append("比率按总分子/总分母计算")
    if any("阈值不代表显著性" in str(item.get("confidence_note", "")) for item in comparisons):
        shared_notes.append("异常等级不代表统计显著性")
    if shared_notes:
        st.caption("；".join(shared_notes) + "。")


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


def _render_findings(result: dict[str, Any], view_mode: str, *, findings=None) -> None:
    findings = result.get("findings", []) if findings is None else findings
    visible = []
    for finding in findings:
        reference_only = re.fullmatch(r"结果表 (\S+) 第 \d+ 行提供可复核的实际数值。", finding) if isinstance(finding, str) else None
        if reference_only and reference_only[1] in (result.get("result_tables") or {}):
            continue
        visible.append(finding)
    findings = visible
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
    if kind == "pivot" and metadata.get("aggregation") not in {"sum", "count"}:
        st.caption("当前指标不可加总，不提供堆叠图。")
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
    st.caption(f"每图最多显示 {config.chart_max_points:,} 点；统计使用全量数据。")
    for spec, figure in pairs:
        from app.components.result_layout import render_chart_limits
        render_chart_limits(spec)
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
    from app.components.result_layout import RESULT_TITLES
    titles = {**RESULT_TITLES, **TABLE_TITLES}
    key = st.selectbox("选择结果明细表", names, format_func=lambda value: titles.get(value, value), key="result_table_selector")
    title = titles.get(key, key)
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


def _render_diagnostic_overview(result: dict[str, Any], package: dict[str, Any], projection: dict[str, Any], view_mode: str) -> None:
    from app.components.diagnostic_summary import supplementary_findings
    from app.components.result_layout import render_key_charts, render_primary_table, render_result_actions
    display = synthetic_display_text if result.get("data_source_type") == "synthetic" else str
    st.subheader("发生了什么", anchor=False)
    _render_kpis(package, view_mode, comparisons=projection["comparisons"], heading=None, result=result)
    st.subheader("变化集中在哪里", anchor=False)
    groups = projection["contribution_groups"]
    if groups:
        metric = projection["metric_id"]
        rate = projection["metric_unit"] == "比例"
        dimensions = {"city": "城市", "channel": "渠道", "device": "设备", "app_version": "版本",
                      "user_segment": "用户分组", "region": "区域", "platform": "平台"}
        for group in groups:
            lines = []
            for row in group["rows"]:
                value = float(row["contribution_value"])
                change = f"{value * 100:+.2f} 个百分点" if rate else f"{value:+,.2f} {projection['metric_unit']}"
                lines.append(display(f"{row.get('dimension_value')}：变化贡献 {change}；{row.get('confidence_flag', '前提待复核')}"))
            render_compact_summary_card(
                f"{format_metric_name(metric)} · {dimensions.get(group['dimension'], group['dimension'])}", lines)
        st.caption("每个维度分别展示绝对变化贡献最大的已有分组；不同维度不可相加。变化贡献是描述性分解，不证明变化原因。完整正负项与其他分组在明细中保留。")
    else:
        static = (result.get("result_tables") or {}).get("dimension_contribution")
        if isinstance(static, pd.DataFrame) and not static.empty:
            st.caption("本次仅有静态分组表现，未计算分组的跨期变化贡献；静态份额不能解释指标变化。")
        else:
            st.caption("本次没有可展示的分组变化贡献，不能据此判断变化集中在哪个分组。")
    render_key_charts(result)
    st.subheader("证据支持到哪一步", anchor=False)
    render_primary_table(result)
    covered = list(projection["covered_evidence"])
    for entry in projection["evidence"]:
        item = entry["record"]
        if not entry["represented"]:
            st.write(display(_safe_string(str(item.get("claim", "")))))
            covered.append(item)
        caveat = item.get("caveat", "")
        # The exact same comparison caveat has already appeared beside its KPI.
        if entry["represented"] and caveat in {row.get("confidence_note") for row in projection["comparisons"]}:
            continue
        note = _comparison_note(caveat) if item.get("result_table") == "metric_comparisons" else caveat
        if note:
            st.caption(display(_safe_string(str(note))))
    if not projection["evidence"]:
        st.warning("当前缺少可对应到本次结果表的结构化证据；已有数值需结合口径与质量复核。")
    _render_findings(result, view_mode, findings=supplementary_findings(result, covered))
    render_caveats(result.get("caveats", []), view_mode)
    st.subheader("下一步", anchor=False)
    render_result_actions(result)


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
    from app.components.diagnostic_summary import diagnostic_projection
    projection = diagnostic_projection(result)
    if projection is not None:
        _render_diagnostic_overview(result, package, projection, view_mode)
        return
    from app.components.result_layout import render_causal_kpis, render_primary_table, render_key_charts, render_result_actions, render_exploration_kpis, exploration_heading, exploration_ui_items
    heading = exploration_heading(result)
    st.subheader(heading or "执行摘要", anchor=False)
    raw_summary = package.get("executive_summary") or result.get("summary") or "本次分析已执行。"
    if not heading:
        summary = format_metric_text(raw_summary)
        st.write(synthetic_display_text(summary) if result.get("data_source_type") == "synthetic" else summary)
    is_causal = render_causal_kpis(result)
    is_exploration = render_exploration_kpis(result)
    if not is_causal and not is_exploration:
        _render_experiment_summary(package, view_mode)
        _render_kpis(package, view_mode, result=result)
    if any(package.get(key) for key in ("anomalies", "dimension_contributions", "funnel_results", "recommendations")) and not is_causal and not is_exploration:
        _render_result_highlights(package, synthetic=result.get("data_source_type") == "synthetic")
    render_key_charts(result)
    render_primary_table(result)
    render_result_actions(result)
    _render_findings(result, view_mode, findings=exploration_ui_items(result, result.get("findings", []), summary=raw_summary))
    caveats = exploration_ui_items(result, result.get("caveats", []))
    if caveats:
        render_caveats(caveats, view_mode)


def _remember_result_tab() -> None:
    st.session_state["performance_selected_result_tab"] = st.session_state.get("result_tabs")


def render_result_panel(result: dict[str, Any], view_mode: str = "demo", *,
                        run_context: dict[str, Any] | None = None, previous_result: bool = False) -> None:
    status = result.get("execution_status", "COMPLETED")
    preview = result.get("execution_mode") == "plan_only" or status == "PREVIEW"
    label = "方案预览" if preview else {
        "COMPLETED": "已完成", "NEEDS_INPUT": "待补充信息", "INVALID_INPUT": "配置无效",
        "UNSUPPORTED": "当前条件不支持", "WAITING_APPROVAL": "等待审批", "FAILED": "分析失败",
    }.get(status, "尚未完成")
    color = "blue" if preview else "green" if status == "COMPLETED" else "red" if status == "FAILED" else "orange"
    with st.container(horizontal=True, vertical_alignment="center", gap=12):
        st.markdown("**上次分析结果**" if previous_result else "**分析结果**")
        st.badge(label, color=color, help="执行状态不代表统计前提或因果识别假设已验证。")
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
    from app.components.diagnostic_summary import visible_quality_risks
    for severity, risk in visible_quality_risks(result, with_severity=True):
        if severity == "error":
            st.error(_safe_string(risk))
        else:
            st.warning(_safe_string(risk))
    quality = st.expander("查看口径与质量", expanded=bool(st.session_state.get("guided_quality", False)), key="guided_quality", on_change="rerun")
    if quality.open:
        with quality:
            from app.components.metric_definition_panel import render_metric_definitions
            render_metric_definitions(result.get("metric_definitions", []), view_mode="professional", required=True)
            render_reviewer_panel(result, "professional")
    details = st.expander("技术详情", expanded=bool(st.session_state.get("guided_technical", False)), key="guided_technical", on_change="rerun")
    if details.open:
        with details:
            from insightpilot.analysis.quality import QUALITY_NOTICE, quality_rows
            st.dataframe(pd.DataFrame(quality_rows(result)), hide_index=True, width="stretch")
            st.caption(QUALITY_NOTICE)
            manifest = result.get("run_manifest") or {}
            st.caption("运行编号：" + str(manifest.get("run_id") or "未记录"))
            if isinstance(run_context, dict):
                st.caption("数据修订：" + str(run_context.get("dataset_revision", "未记录")))
            st.caption("此处方案、证据和报告绑定已提交的运行；未提交的新参数不会改变它。")
            render_plan_panel(result, view_mode="developer")
            render_lineage_panel(result, "developer")
            render_developer_panel(result, "developer")
            evaluation = st.expander("评估工具", key="evaluation_tools_open", on_change="rerun")
            if evaluation.open:
                with evaluation:
                    render_evaluation_panel()
