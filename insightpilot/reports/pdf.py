"""A4 Chinese result-first PDF reports, generated entirely in memory.

The standard PDF CJK CID font does not ship a font binary with this package.
No Plotly image engine, browser, online service, or model is required.
"""

from __future__ import annotations

from insightpilot.reports.definitions import bind_report_metadata, definition_cards
from insightpilot.analysis.quality import QUALITY_NOTICE, quality_rows

from html import escape
from io import BytesIO
from typing import Any

from insightpilot.reports.safety import report_result_view

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import CondPageBreak, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.safety import xml_text
from insightpilot.ui.experiment_display import experiment_display, finite_number
from insightpilot.ui.formatters import format_enum_value, format_metric_name, format_metric_text, format_status
from insightpilot.ui.presenters import present_analysis_plan, translate_caveat
from insightpilot.ui.table_labels import COLUMN_NAMES as RESULT_COLUMN_NAMES, localize_result_value


MAX_PDF_TABLE_ROWS = 40
MAX_PDF_TABLES = 20
MAX_PDF_CELL_CHARS = 500
FONT_NAME = "STSong-Light"
PAGE_WIDTH = A4[0] - 36 * mm
TABLE_NAMES = {
    "metric_comparisons": "指标对比", "anomalies": "异常检测",
    "funnel_decomposition": "漏斗拆解", "dimension_contributions": "维度贡献",
    "experiment_comparison": "实验分析结果", "evidence": "证据链",
    "recommendations": "建议清单", "data_quality": "数据质量",
}
COLUMN_NAMES = {
    "metric_id": "指标", "metric_name": "指标名称", "metric": "指标",
    "current_value": "当前值", "baseline_value": "基准值",
    "absolute_change": "绝对变化", "relative_change": "相对变化",
    "current_period": "当前窗口", "baseline_period": "基准窗口",
    "sample_size": "样本量", "unit": "单位", "severity": "严重程度",
    "dimension": "维度", "dimension_value": "分组", "contribution_value": "贡献值",
    "contribution_pct": "绝对影响占比", "stage_name": "阶段", "method": "方法",
    "evidence_id": "证据编号", "claim": "结论", "action": "建议",
    "priority": "优先级", "reason": "依据", "limitation": "限制",
    "supporting_evidence_ids": "关联证据", "verification_metric": "验证指标",
    "supporting_values": "支撑数值", "result_table": "来源结果表",
}


def _styles() -> dict[str, ParagraphStyle]:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    common = dict(fontName=FONT_NAME, wordWrap="CJK", textColor=colors.HexColor("#203347"))
    return {
        "title": ParagraphStyle("ReportTitle", fontSize=21, leading=29, spaceAfter=13, **common),
        "h2": ParagraphStyle("ReportSection", fontSize=13, leading=19, spaceBefore=14, spaceAfter=8, keepWithNext=True, **common),
        "body": ParagraphStyle("ReportBody", fontSize=10.5, leading=16, spaceAfter=7, splitLongWords=True, **common),
        "small": ParagraphStyle("ReportSmall", fontSize=8, leading=12, spaceAfter=5, splitLongWords=True, **common),
        "cell": ParagraphStyle("ReportCell", fontSize=7.5, leading=11, splitLongWords=True, **common),
    }


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(xml_text(value)).replace("\n", "<br/>"), style)


def _cell(value: Any, styles: dict[str, ParagraphStyle]) -> Paragraph:
    if isinstance(value, Paragraph):
        return value
    if isinstance(value, float):
        value = finite_number(value)
    text = format_metric_text(xml_text(value))
    if len(text) > MAX_PDF_CELL_CHARS:
        text = text[:MAX_PDF_CELL_CHARS] + "…（单元格文本已截断）"
    return _paragraph(text, styles["cell"])


def _literal_cell(value: Any, styles: dict[str, ParagraphStyle]) -> Paragraph:
    """Preserve source identifiers while keeping the existing PDF cell budget."""
    text = xml_text(value)
    if len(text) > MAX_PDF_CELL_CHARS:
        text = text[:MAX_PDF_CELL_CHARS] + "…（单元格文本已截断）"
    return _paragraph(text, styles["cell"])


def _table(headers: list[Any], rows: list[Any], styles: dict[str, ParagraphStyle], widths: list[float] | None = None) -> LongTable:
    """Compatibility table helper with escaped Chinese wrapping and repeat headers."""
    data = [[_cell(value, styles) for value in headers]]
    data.extend([_cell(value, styles) for value in row] for row in rows)
    table = LongTable(data, colWidths=widths or [PAGE_WIDTH / len(headers)] * len(headers), repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9f0f6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cfdae4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _frame_table(frame: pd.DataFrame, styles: dict[str, ParagraphStyle]) -> list[Any]:
    # Split wide tables horizontally rather than shrinking text or clipping columns.
    output: list[Any] = []
    columns = list(frame.columns)
    if not columns:
        return [_paragraph("没有可用字段。", styles["body"])]
    for start in range(0, len(columns), 5):
        group = columns[start:start + 5]
        headers = [COLUMN_NAMES.get(str(column), RESULT_COLUMN_NAMES.get(str(column), format_metric_name(column))) for column in group]
        rows = [[localize_result_value(value, column) for column, value in zip(group, row)] for row in frame[group].itertuples(index=False, name=None)]
        table = _table(headers, rows, styles)
        if len(columns) > 5:
            first_height = _table(headers, rows[:1], styles).wrap(PAGE_WIDTH, 10_000)[1]
            output.append(CondPageBreak(first_height + 25))
            output.append(_paragraph(f"字段分组 {start // 5 + 1} / {(len(columns) + 4) // 5}；各分组行顺序一致。", styles["small"]))
        output.extend([table, Spacer(1, 7)])
    return output


def _build(story: list[Any], version: str = "", run_id: str = "") -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="InsightPilot Agent 中文分析报告", author="InsightPilot Agent")
    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cfdae4"))
        canvas.line(18 * mm, 16 * mm, A4[0] - 18 * mm, 16 * mm)
        canvas.setFont(FONT_NAME, 8)
        canvas.drawString(18 * mm, 11 * mm, f"InsightPilot Agent {version} | 运行 {run_id[:12]}")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"第 {document.page} 页")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def generate_pdf_report(result: dict[str, Any], manifest: RunManifest) -> bytes:
    """Render actual result records with bounded tables and explicit omissions."""

    result = bind_report_metadata(result, manifest)
    quality = quality_rows(result)
    source_tables = result.get("result_tables") or {}
    table_order = [name for name in TABLE_NAMES if name in source_tables] + [name for name in source_tables if name not in TABLE_NAMES]
    result = report_result_view(result, max_table_rows=MAX_PDF_TABLE_ROWS, table_names=table_order[:MAX_PDF_TABLES])

    styles = _styles()
    package = result.get("analysis_result_package") or {}
    story: list[Any] = [_paragraph("InsightPilot Agent 中文分析报告", styles["title"])]
    add = lambda text: story.append(_paragraph(text, styles["body"]))
    def heading(text: str, minimum_space: float = 100) -> None:
        story.append(CondPageBreak(minimum_space))
        story.append(_paragraph(text, styles["h2"]))
    add(f"版本 {manifest.project_version} | 运行时间 {manifest.created_at}")
    add(f"分析问题：{result.get('question', '')}")
    heading("执行摘要")
    add(format_metric_text(package.get("executive_summary") or result.get("summary") or "没有已执行的结果。"))
    if result.get("execution_mode") in {"plan_only", "preview"}:
        add("当前仅为方案预览，尚未执行统计计算；下列空项不代表指标为零。")
    heading("指标口径与出处")
    cards = definition_cards(result)
    for card in cards:
        card_rows = [[_literal_cell(key, styles), _literal_cell(value, styles)] for key, value in card.items()]
        story.append(_table(["口径项", "本次运行定义"], card_rows, styles, [PAGE_WIDTH * .27, PAGE_WIDTH * .73]))
        story.append(Spacer(1, 8))
    if not cards:
        add("本次运行没有完整口径卡，请复核原映射。")
    heading("实际分析结果")
    heading("实验分析结果")
    experiments = package.get("experiment_results", [])
    for item in experiments:
        story.append(_table(["实验统计项", "实际结果"], list(experiment_display(item).items()), styles, [PAGE_WIDTH * .39, PAGE_WIDTH * .61]))
    if not experiments:
        add("本次分析不包含可用的实验组与对照组比较。")
    heading("核心指标表现")
    comparisons = package.get("metric_comparisons", [])
    for item in comparisons[:20]:
        add(f"{format_metric_name(item.get('metric_id'))}：当前 {finite_number(item.get('current_value'))}；"
            f"基准 {finite_number(item.get('baseline_value'))}；相对变化 {finite_number(item.get('relative_change'), percent=True)}。"
            f"当前窗口 {item.get('current_period', '未声明')}；基准窗口 {item.get('baseline_period', '未声明')}。")
    if not comparisons:
        add("本次结果未包含指标周期对比；请查看适用的结果表。")
    tables = result.get("result_tables") or {}
    ordered = [name for name in TABLE_NAMES if name in tables] + [name for name in tables if name not in TABLE_NAMES]
    for name in ordered[:MAX_PDF_TABLES]:
        frame = tables[name]
        if not isinstance(frame, pd.DataFrame):
            continue
        first_columns = list(frame.columns)[:5]
        first_headers = [COLUMN_NAMES.get(str(column), RESULT_COLUMN_NAMES.get(str(column), format_metric_name(column))) for column in first_columns]
        first_rows = [[localize_result_value(value, column) for column, value in zip(first_columns, row)] for row in frame[first_columns].head(1).itertuples(index=False, name=None)]
        first_height = _table(first_headers, first_rows, styles).wrap(PAGE_WIDTH, 10_000)[1] if first_columns and first_rows else 30
        heading(TABLE_NAMES.get(name, f"补充结果：{name}"), minimum_space=80 + first_height)
        if frame.empty:
            add("当前分析不适用该结果或没有可计算记录。")
            continue
        story.append(_paragraph(f"共 {result['_report_table_row_counts'][name]} 行，展示前 {len(frame)} 行。"
            + ("已截断，更多结果请查阅 Excel / CSV 导出。" if result["_report_table_row_counts"][name] > MAX_PDF_TABLE_ROWS else ""), styles["small"]))
        story.extend(_frame_table(frame.head(MAX_PDF_TABLE_ROWS), styles))
    if result["_report_table_count"] > MAX_PDF_TABLES:
        add(f"结果表已截断，仅展示前 {MAX_PDF_TABLES} 张。")
    heading("质量检查与风险限制")
    reviewer = result.get("reviewer") or {}
    add(f"质量检查：{format_status(str(reviewer.get('status', 'WARN')))}；规则检查评分：{reviewer.get('score', '未评分')}。")
    add("评分是规则检查结果，不是分析结论正确的概率。")
    add(QUALITY_NOTICE)
    for row in quality:
        add(f"{row['检查维度']}：{row['状态']}；{row['依据与边界']}")
    seen_caveats: set[str] = set()
    for caveat in [*result.get("caveats", []), *reviewer.get("issues", [])]:
        text = translate_caveat(caveat)
        if text not in seen_caveats:
            add(text)
            seen_caveats.add(text)
    heading("分析方案")
    plan = present_analysis_plan(result.get("analysis_plan") or result.get("plan") or {})
    add(f"分析目标：{plan.goal_name}；对比方式：{plan.comparison_method_text}")
    for step in plan.step_descriptions:
        add(step)
    heading("运行与复现摘要")
    add(f"运行编号：{manifest.run_id}")
    add(f"数据来源：{format_enum_value('data_source', manifest.data_source_type)}；工作流：{format_enum_value('backend', manifest.workflow_backend)}")
    add("运行清单仅保存安全配置与数据摘要，不能恢复原始输入。静态图表不是本报告的必需依赖，交互图表见离线 HTML。")
    return _build(story, manifest.project_version, manifest.run_id)


def generate_minimal_pdf_report(markdown_report: str) -> bytes:
    """Compatibility adapter for callers which have only Markdown text."""

    styles = _styles()
    story: list[Any] = []
    for line in str(markdown_report).splitlines():
        if line.strip():
            style = styles["h2"] if line.startswith("#") else styles["body"]
            story.append(_paragraph(line.lstrip("# "), style))
    return _build(story or [_paragraph("暂无报告内容。", styles["body"])])
