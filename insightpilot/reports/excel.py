"""In-memory Excel analysis report export."""

from __future__ import annotations

from insightpilot.reports.definitions import bind_report_metadata, definition_cards
from insightpilot.analysis.quality import QUALITY_NOTICE, quality_rows

import json
import re
from io import BytesIO
from typing import Any

from insightpilot.reports.safety import report_result_view

import pandas as pd

from insightpilot.reports.manifest import RunManifest
from insightpilot.ui.formatters import format_enum_value, format_metric_name, format_metric_text, format_reviewer_check_name, format_status
from insightpilot.ui.presenters import present_query_plan
from insightpilot.ui.table_labels import COLUMN_NAMES, localize_result_value
from insightpilot.reports.safety import spreadsheet_cell


MAX_EXCEL_RESULT_ROWS = 100_000


def _sheet_name(value: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", value)[:31] or "Sheet"
    candidate = cleaned
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = f"{cleaned[:31-len(suffix)]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _key_value_frame(values: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"key": key, "value": json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value} for key, value in values.items()]
    )


def _localized_result_frame(frame: pd.DataFrame) -> pd.DataFrame:
    localized = frame.copy()
    for column in ("metric_id", "metric", "verification_metric"):
        if column in localized.columns:
            localized[column] = localized[column].map(format_metric_name)
    for column in ("claim", "finding"):
        if column in localized.columns:
            localized[column] = localized[column].map(format_metric_text)
    for column in localized.columns:
        localized[column] = localized[column].map(lambda value: localize_result_value(value, column))
    return localized.rename(columns={column: COLUMN_NAMES.get(str(column), str(column)) for column in localized.columns})


def generate_excel_report(result: dict[str, Any], manifest: RunManifest, *, compatibility_mode: bool = False) -> bytes:
    """Generate an XLSX workbook without writing it to disk."""

    result = bind_report_metadata(result, manifest)
    quality = quality_rows(result)
    result = report_result_view(result, max_table_rows=MAX_EXCEL_RESULT_ROWS)

    buffer = BytesIO()
    used: set[str] = set()
    reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    summary = {
        "playbook": selected.get("playbook_id") or manifest.playbook_id,
        "playbook_name": selected.get("display_name"),
        "goal_mode": manifest.goal_mode,
        "data_source_type": manifest.data_source_type,
        "execution_status": (result.get("playbook_result") or {}).get("status") if isinstance(result.get("playbook_result"), dict) else reviewer.get("status"),
        "workflow_backend": manifest.workflow_backend,
        "run_id": manifest.run_id,
    }
    summary_zh = {
        "分析剧本": selected.get("display_name") or format_enum_value("playbook", manifest.playbook_id),
        "分析目标": format_enum_value("goal_mode", manifest.goal_mode),
        "数据来源": format_enum_value("data_source", manifest.data_source_type),
        "执行状态": format_status(str(summary["execution_status"] or "WARN")),
        "工作流后端": format_enum_value("backend", manifest.workflow_backend),
        "运行编号": manifest.run_id,
    }
    package = result.get("analysis_result_package") if isinstance(result.get("analysis_result_package"), dict) else {}
    structured_tables = result.get("result_tables") if isinstance(result.get("result_tables"), dict) else {}
    findings = pd.DataFrame({"finding": [format_metric_text(value) for value in result.get("findings", [])]})
    reviewer_rows: list[dict[str, Any]] = [
        {"category": "summary", "name": "status", "value": reviewer.get("status")},
        {"category": "summary", "name": "score", "value": reviewer.get("score")},
    ]
    for category in ("checks", "issues", "suggestions"):
        values = reviewer.get(category, {})
        if isinstance(values, dict):
            reviewer_rows.extend({"category": category, "name": key, "value": value} for key, value in values.items())
        elif isinstance(values, list):
            reviewer_rows.extend({"category": category, "name": str(index + 1), "value": value} for index, value in enumerate(values))
    reviewer_rows_zh: list[dict[str, Any]] = [
        {"类别": "摘要", "检查项": "检查状态", "结果": format_status(str(reviewer.get("status", "WARN")))},
        {"类别": "摘要", "检查项": "质量评分", "结果": reviewer.get("score")},
    ]
    checks = reviewer.get("checks", {}) if isinstance(reviewer.get("checks"), dict) else {}
    reviewer_rows_zh.extend(
        {"类别": "检查项", "检查项": format_reviewer_check_name(name), "结果": "通过" if passed else "未通过"}
        for name, passed in checks.items()
    )
    reviewer_rows_zh.extend(
        {"类别": "问题", "检查项": str(index + 1), "结果": value}
        for index, value in enumerate(reviewer.get("issues", []))
    )
    reviewer_rows_zh.extend(
        {"类别": "建议", "检查项": str(index + 1), "结果": value}
        for index, value in enumerate(reviewer.get("suggestions", []))
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _key_value_frame({
            "执行摘要": package.get("executive_summary") or result.get("summary", ""),
            "分析问题": result.get("question", ""),
            "分析目标": format_enum_value("goal_mode", manifest.goal_mode),
            "运行编号": manifest.run_id,
        }).rename(columns={"key": "项目", "value": "内容"}).to_excel(writer, sheet_name=_sheet_name("执行摘要", used), index=False)
        cards = definition_cards(result)
        pd.DataFrame(cards or [{"说明": "本次运行没有完整口径卡，请复核原映射。"}]).to_excel(writer, sheet_name=_sheet_name("指标口径", used), index=False)
        pd.DataFrame(quality).to_excel(writer, sheet_name=_sheet_name("质量维度", used), index=False)
        _key_value_frame({"评分边界": QUALITY_NOTICE}).rename(columns={"key": "项目", "value": "内容"}).to_excel(writer, sheet_name=_sheet_name("评分说明", used), index=False)
        structured_sheet_names = {
            "experiment_comparison": "实验分析结果",
            "metric_comparisons": "指标对比",
            "anomalies": "异常检测",
            "funnel_decomposition": "漏斗拆解",
            "dimension_contributions": "维度贡献",
            "evidence": "证据链",
            "recommendations": "建议清单",
        }
        for key, sheet_name in structured_sheet_names.items():
            frame = structured_tables.get(key)
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                _localized_result_frame(frame.head(MAX_EXCEL_RESULT_ROWS)).to_excel(writer, sheet_name=_sheet_name(sheet_name, used), index=False)
            else:
                pd.DataFrame({"说明": ["当前分析类型不适用或没有可用结果。"]}).to_excel(writer, sheet_name=_sheet_name(sheet_name, used), index=False)
        _key_value_frame(summary_zh).rename(columns={"key": "项目", "value": "内容"}).to_excel(writer, sheet_name=_sheet_name("分析摘要", used), index=False)
        findings.rename(columns={"finding": "核心发现"}).to_excel(writer, sheet_name=_sheet_name("核心发现", used), index=False)
        pd.DataFrame(reviewer_rows_zh).to_excel(writer, sheet_name=_sheet_name("质量检查", used), index=False)
        _key_value_frame(manifest.column_mapping).rename(columns={"key": "字段", "value": "映射"}).to_excel(writer, sheet_name=_sheet_name("字段映射", used), index=False)
        if result.get("query_plan"):
            query_view = present_query_plan(result["query_plan"])
            _key_value_frame(
                {
                    "计划编号": query_view.plan_id,
                    "查询指标": query_view.metric_names,
                    "分析维度": query_view.dimension_names,
                    "时间范围": query_view.date_range_text,
                    "时间粒度": query_view.time_grain_text,
                    "风险等级": query_view.risk_text,
                    "执行状态": query_view.executable_text,
                    "参数数量": query_view.parameter_count,
                }
            ).rename(columns={"key": "项目", "value": "内容"}).to_excel(writer, sheet_name=_sheet_name("查询计划", used), index=False)
        if result.get("lineage"):
            _key_value_frame(result["lineage"]).to_excel(writer, sheet_name=_sheet_name("数据血缘", used), index=False)
        _key_value_frame(manifest.to_dict()).rename(columns={"key": "配置项", "value": "配置值"}).to_excel(writer, sheet_name=_sheet_name("运行清单", used), index=False)
        # Explicit opt-in retains historical English-sheet consumers.
        if compatibility_mode:
            _key_value_frame(summary).to_excel(writer, sheet_name=_sheet_name("Summary", used), index=False)
            findings.to_excel(writer, sheet_name=_sheet_name("Findings", used), index=False)
            pd.DataFrame(reviewer_rows).to_excel(writer, sheet_name=_sheet_name("Reviewer", used), index=False)
            _key_value_frame(manifest.column_mapping).to_excel(writer, sheet_name=_sheet_name("Mapping", used), index=False)
            _key_value_frame(manifest.to_dict()).to_excel(writer, sheet_name=_sheet_name("Manifest", used), index=False)
        result_tables = result.get("result_tables") if isinstance(result.get("result_tables"), dict) else {}
        for name, frame in result_tables.items():
            if isinstance(frame, pd.DataFrame):
                if name not in structured_sheet_names:
                    _localized_result_frame(frame.head(MAX_EXCEL_RESULT_ROWS)).to_excel(
                        writer, sheet_name=_sheet_name(f"结果_{name}", used), index=False
                    )
                if compatibility_mode:
                    frame.head(MAX_EXCEL_RESULT_ROWS).to_excel(
                        writer, sheet_name=_sheet_name(f"Result_{name}", used), index=False
                    )
        truncations = [{"结果表": name, "原始行数": result["_report_table_row_counts"][name], "导出行数": MAX_EXCEL_RESULT_ROWS}
                       for name, frame in result_tables.items()
                       if isinstance(frame, pd.DataFrame) and result["_report_table_row_counts"][name] > MAX_EXCEL_RESULT_ROWS]
        if truncations:
            pd.DataFrame(truncations).to_excel(writer, sheet_name=_sheet_name("截断说明", used), index=False)
        # openpyxl interprets '=' as a formula, so set output-only safety before serializing.
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for row in sheet.iter_rows():
                for cell in row:
                    safe = spreadsheet_cell(cell.value)
                    if safe != cell.value:
                        cell.value = safe
                        cell.data_type = "s"
    return buffer.getvalue()
