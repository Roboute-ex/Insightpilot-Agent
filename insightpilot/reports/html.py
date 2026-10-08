"""Single-file offline HTML report export."""

from __future__ import annotations

from insightpilot.reports.definitions import bind_report_metadata, definition_cards
from insightpilot.analysis.quality import QUALITY_NOTICE, quality_rows

from html import escape
from typing import Any

from insightpilot.reports.safety import report_result_view

from insightpilot.ui.experiment_display import experiment_display, finite_number
from insightpilot.ui.table_labels import COLUMN_NAMES, localize_result_value

import pandas as pd
import plotly.graph_objects as go
from insightpilot.ui.synthetic_display import synthetic_display_object

from insightpilot.reports.manifest import RunManifest
from insightpilot.ui.formatters import format_enum_value, format_metric_name, format_metric_text, format_status
from insightpilot.ui.presenters import present_join_plan, present_query_plan, translate_caveat


MAX_HTML_TABLE_ROWS = 100


def _items(values: Any) -> str:
    if not values:
        return "<p>暂无</p>"
    return "<ul>" + "".join(f"<li>{escape(str(value))}</li>" for value in values) + "</ul>"


def _definition(values: dict[str, Any]) -> str:
    return "<dl>" + "".join(
        f"<dt>{escape(str(key))}</dt><dd>{escape(str(value))}</dd>" for key, value in values.items()
    ) + "</dl>"


def _source_definition(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "数据来源": format_enum_value("data_source", values.get("data_source_type")),
        "数据表数量": values.get("table_count", 0),
        "数据表": "、".join(str(item) for item in values.get("table_names", [])) or "暂无",
    }


def _query_definition(values: dict[str, Any]) -> dict[str, Any]:
    if not values:
        return {"说明": "本次未生成语义查询计划"}
    view = present_query_plan(values)
    return {
        "计划编号": view.plan_id,
        "查询指标": "、".join(view.metric_names),
        "分析维度": "、".join(view.dimension_names) or "整体",
        "时间范围": view.date_range_text,
        "时间粒度": view.time_grain_text,
        "风险等级": view.risk_text,
        "执行状态": view.executable_text,
        "参数数量": view.parameter_count,
    }


def _join_definition(values: dict[str, Any]) -> dict[str, Any]:
    if not values:
        return {"说明": "本次未使用语义多表连接"}
    view = present_join_plan(values)
    return {
        "使用数据表数量": view.table_count,
        "连接步骤数量": view.step_count,
        "风险等级": view.risk_text,
        "需要审批": view.requires_approval_text,
        "执行状态": view.executable_text,
        "输出粒度": view.output_grain,
    }


def _table_sections(result_tables: dict[str, pd.DataFrame], row_counts: dict[str, int] | None = None) -> str:
    sections: list[str] = []
    for name, frame in result_tables.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        preview = frame.head(MAX_HTML_TABLE_ROWS).copy()
        for column in ("metric_id", "metric", "verification_metric"):
            if column in preview.columns:
                preview[column] = preview[column].map(format_metric_name)
        for column in preview.columns:
            preview[column] = preview[column].map(lambda value: localize_result_value(value, column))
        preview = preview.rename(columns={column: COLUMN_NAMES.get(str(column), str(column)) for column in preview.columns})
        sections.append(
            f"<h3>{escape(str(name))}</h3>"
            f"<p>共 {(row_counts or {}).get(name, len(frame))} 行、{len(frame.columns)} 个字段；预览最多显示 {MAX_HTML_TABLE_ROWS} 行。</p>"
            + preview.to_html(index=False, escape=True, border=0)
        )
    return "".join(sections) or "<p>暂无结果表。</p>"


def generate_html_report(
    result: dict[str, Any],
    figures: list[Any],
    manifest: RunManifest,
) -> str:
    """Generate an offline HTML report with embedded Plotly figures."""

    result = bind_report_metadata(result, manifest)
    quality = quality_rows(result)
    if not figures and result.get("chart_specs") and result.get("presentation_mode") == "deferred":
        from insightpilot.performance import PerformanceConfig
        from insightpilot.visualization.result_charts import materialize_charts
        figures = materialize_charts(result, max_points=PerformanceConfig.from_environment().chart_max_points)
    chart_warnings = list(getattr(figures, "warnings", ()))
    if chart_warnings:
        # Report-only metadata copy; never change the completed analysis snapshot.
        result = {**result, "caveats": [*(result.get("caveats") or []), *chart_warnings]}
    result = report_result_view(result, max_table_rows=MAX_HTML_TABLE_ROWS)

    chart_fragments: list[str] = []
    for index, item in enumerate(figures):
        figure = item[1] if isinstance(item, tuple) and len(item) == 2 else item
        if result.get("data_source_type") == "synthetic" and isinstance(figure, go.Figure):
            figure = go.Figure(synthetic_display_object(figure.to_dict()))
        if not hasattr(figure, "to_html"):
            continue
        chart_fragments.append(
            figure.to_html(full_html=False, include_plotlyjs=not chart_fragments)
        )
    reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    mapping = result.get("column_mapping") if isinstance(result.get("column_mapping"), dict) else {}
    route = result.get("route_taken") or []
    result_tables = result.get("result_tables") if isinstance(result.get("result_tables"), dict) else {}
    source_summary = manifest.source_summary
    package = result.get("analysis_result_package") if isinstance(result.get("analysis_result_package"), dict) else {}
    comparisons = package.get("metric_comparisons", []) if isinstance(package, dict) else []
    anomalies = package.get("anomalies", []) if isinstance(package, dict) else []
    funnel = package.get("funnel_results", []) if isinstance(package, dict) else []
    contributions = package.get("dimension_contributions", []) if isinstance(package, dict) else []
    evidence = package.get("evidence", []) if isinstance(package, dict) else []
    recommendations = package.get("recommendations", []) if isinstance(package, dict) else []
    experiment_results = package.get("experiment_results", []) if isinstance(package, dict) else []
    comparison_items = [
        f"{format_metric_name(item.get('metric_id'))}：当前 {finite_number(item.get('current_value'))}，"
        f"基准 {finite_number(item.get('baseline_value'))}，变化 {finite_number(item.get('relative_change'), percent=True)}"
        for item in comparisons[:20] if isinstance(item, dict)
    ]
    anomaly_items = [
        f"{format_metric_name(item.get('metric_id'))}：{localize_result_value(item.get('severity'), 'severity')}，偏差 {finite_number(item.get('deviation_pct'), percent=True)}"
        for item in anomalies[:20] if isinstance(item, dict)
    ]
    funnel_items = [
        f"{item.get('stage_name')}：估算订单影响 {finite_number(item.get('estimated_order_impact'))}，"
        f"贡献占比 {finite_number(item.get('contribution_pct'), percent=True)}"
        for item in funnel if isinstance(item, dict)
    ]
    contribution_items = [
        f"{item.get('dimension')}={item.get('dimension_value')}：贡献值 {finite_number(item.get('contribution_value'))}"
        for item in contributions[:20] if isinstance(item, dict)
    ]
    evidence_items = [f"{item.get('evidence_id')}：{format_metric_text(item.get('claim'))}" for item in evidence[:20] if isinstance(item, dict)]
    recommendation_items = [f"[{item.get('priority')}] {item.get('action')}；关联证据：{'、'.join(item.get('supporting_evidence_ids', []))}" for item in recommendations[:20] if isinstance(item, dict)]
    experiment_sections: list[str] = []
    for item in experiment_results:
        if not isinstance(item, dict):
            continue
        experiment_sections.append(_definition(experiment_display(item)))
    experiment_html = "".join(experiment_sections) or "<p>当前分析不包含实验组与对照组比较。</p>"
    style = """
body{font-family:Arial,sans-serif;max-width:1180px;margin:0 auto;padding:28px;color:#202124;line-height:1.5}
h1,h2{color:#15324a}section{border-top:1px solid #d9e0e5;padding:18px 0}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #d9e0e5;padding:6px;text-align:left}th{background:#f4f7f9}dt{font-weight:700}dd{margin:0 0 8px}
"""
    return "".join(
        [
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
            f"<title>{escape(str(selected.get('display_name') or 'InsightPilot 中文分析报告'))}</title>",
            f"<style>{style}</style></head><body>",
            "<h1>InsightPilot Agent 中文分析报告</h1>",
            f"<p>运行时间：{escape(manifest.created_at)}</p>",
            f"<section><h2>执行摘要</h2><p>{escape(format_metric_text(package.get('executive_summary') or result.get('summary', '')))}</p></section>",
            "<section><h2>指标口径与出处</h2>" + ("".join(_definition(card) for card in definition_cards(result)) or "<p>本次运行没有完整口径卡，请复核原映射。</p>") + "</section>",
            f"<section><h2>实验分析结果</h2>{experiment_html}</section>",
            f"<section><h2>核心指标表现</h2>{_items(comparison_items)}</section>",
            f"<section><h2>异常检测结果</h2>{_items(anomaly_items)}</section>",
            f"<section><h2>漏斗拆解</h2>{_items(funnel_items)}</section>",
            f"<section><h2>维度贡献</h2>{_items(contribution_items)}</section>",
            f"<section><h2>证据链</h2>{_items(evidence_items)}</section>",
            f"<section><h2>建议清单</h2>{_items(recommendation_items)}</section>",
            f"<section><h2>分析质量检查</h2>{_definition({'检查状态': format_status(str(reviewer.get('status', 'WARN'))), '质量评分': reviewer.get('score', 'N/A')})}</section>",
            "<section><h2>质量维度与评分边界</h2><p>" + escape(QUALITY_NOTICE) + "</p>" + "".join(_definition(row) for row in quality) + "</section>",
            f"<section><h2>风险与限制</h2>{_items([translate_caveat(item) for item in result.get('caveats', [])])}</section>",
            f"<section><h2>分析结果表</h2>{_table_sections(result_tables, result['_report_table_row_counts'])}</section>",
            f"<section><h2>交互式图表（Interactive Plotly Charts）</h2>{''.join(chart_fragments) or '<p>暂无可用图表。</p>'}</section>",
            f"<section><h2>数据来源摘要</h2>{_definition(_source_definition(source_summary))}</section>",
            f"<section><h2>分析问题</h2><p>{escape(str(result.get('question', '')))}</p></section>",
            f"<section><h2>分析目标</h2><p>{escape(format_enum_value('goal_mode', result.get('goal_mode', 'auto')))}</p></section>",
            f"<section><h2>分析剧本</h2>{_definition({'中文名称': selected.get('display_name') or format_enum_value('playbook', manifest.playbook_id or '未选择'), '执行状态': format_status(str((result.get('playbook_result') or {}).get('status', reviewer.get('status', 'WARN'))))})}</section>",
            f"<section><h2>字段映射</h2>{_definition(mapping)}</section>",
            f"<section><h2>分析参数</h2>{_definition(manifest.playbook_parameters)}</section>",
            f"<section><h2>执行步骤</h2>{_items([format_enum_value('route_step', item) for item in route])}</section>",
            f"<section><h2>查询计划</h2>{_definition(_query_definition(result.get('query_plan', {})))}</section>",
            f"<section><h2>多表连接方案</h2>{_definition(_join_definition(result.get('join_plan', {})))}</section>",
            f"<section><h2>核心发现</h2>{_items([format_metric_text(item) for item in result.get('findings', [])])}</section>",
            f"<section><h2>数据血缘</h2>{_definition({'数据节点': len(result.get('lineage', {}).get('datasets', [])), '执行操作': len(result.get('lineage', {}).get('operations', [])), '派生关系': len(result.get('lineage', {}).get('edges', []))})}</section>",
            f"<section><h2>运行清单</h2>{_definition({'运行编号': manifest.run_id, '项目版本': manifest.project_version, '工作流后端': format_enum_value('backend', manifest.workflow_backend), '质量评分': manifest.reviewer_score})}</section>",
            "</body></html>",
        ]
    )
