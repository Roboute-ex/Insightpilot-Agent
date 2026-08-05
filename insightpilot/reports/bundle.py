"""In-memory ZIP export bundle."""

from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from insightpilot.reports.pdf import generate_minimal_pdf_report


MAX_CSV_TABLES = 20
MAX_CSV_ROWS = 100_000


def _ascii_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned[:80] or "result"


def generate_export_bundle(
    markdown_report: str,
    html_report: str,
    excel_bytes: bytes,
    manifest_json: str,
    result_tables: dict[str, pd.DataFrame],
    include_csv_results: bool = True,
    pdf_bytes: bytes | None = None,
) -> bytes:
    """Build a safe report bundle without including source files or credentials."""

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("report.md", markdown_report.encode("utf-8"))
        archive.writestr("report.html", html_report.encode("utf-8"))
        archive.writestr("report.xlsx", excel_bytes)
        archive.writestr("report.pdf", pdf_bytes or generate_minimal_pdf_report(markdown_report))
        archive.writestr("manifest.json", manifest_json.encode("utf-8"))
        if include_csv_results:
            used: set[str] = set()
            for name, frame in list(result_tables.items())[:MAX_CSV_TABLES]:
                if not isinstance(frame, pd.DataFrame):
                    continue
                safe_name = _ascii_name(str(name))
                candidate = safe_name
                index = 2
                while candidate in used:
                    candidate = f"{safe_name}_{index}"
                    index += 1
                used.add(candidate)
                archive.writestr(
                    f"results/{candidate}.csv",
                    frame.head(MAX_CSV_ROWS).to_csv(index=False).encode("utf-8-sig"),
                )
        archive.writestr(
            "README.txt",
            (
                "InsightPilot Agent 中文分析导出包\n\n"
                "内容：中文 PDF、Markdown、离线 HTML、Excel、运行清单和限制行数的分析结果 CSV。\n"
                "导出包不包含上传源文件、完整数据库连接地址、密码或任何密钥。\n"
                "运行清单仅用于复现配置，不能恢复原始输入数据。\n"
            ).encode("utf-8"),
        )
    return buffer.getvalue()
