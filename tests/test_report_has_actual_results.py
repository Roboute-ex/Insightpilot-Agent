from __future__ import annotations

from io import BytesIO

import openpyxl

from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest


def test_reports_include_actual_result_sections(transaction_result) -> None:
    manifest = RunManifest.from_dict(transaction_result["run_manifest"])
    markdown = transaction_result["report_markdown"]
    html = generate_html_report(transaction_result, [], manifest)
    for title in ("执行摘要", "核心指标表现", "异常检测结果", "漏斗拆解", "维度贡献", "证据链", "建议清单"):
        assert title in markdown
        assert title in html
    workbook = openpyxl.load_workbook(BytesIO(generate_excel_report(transaction_result, manifest)), read_only=True)
    assert {"执行摘要", "指标对比", "异常检测", "漏斗拆解", "维度贡献", "证据链", "建议清单"}.issubset(workbook.sheetnames)
