"""In-memory ZIP export bundle."""

from __future__ import annotations

import re
from io import BytesIO, TextIOWrapper
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from insightpilot.reports.pdf import generate_minimal_pdf_report
from insightpilot.reports.safety import safe_report_result, safe_spreadsheet_frame


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
    truncations: list[str] = []
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
                if len(frame) > MAX_CSV_ROWS:
                    truncations.append(f"{candidate}.csv：原 {len(frame)} 行，导出前 {MAX_CSV_ROWS} 行。")
                # Stream CSV encoding directly into the ZIP entry. The bounded
                # safe frame remains, but no full CSV string+bytes pair is held.
                safe_frame = safe_spreadsheet_frame(safe_report_result(frame.head(MAX_CSV_ROWS)))
                with archive.open(f"results/{candidate}.csv", "w") as member:
                    with TextIOWrapper(member, encoding="utf-8-sig", newline="") as text_stream:
                        safe_frame.to_csv(text_stream, index=False)
                del safe_frame
        if len(result_tables) > MAX_CSV_TABLES:
            truncations.append(f"结果表共 {len(result_tables)} 张，仅导出前 {MAX_CSV_TABLES} 张。")
        archive.writestr(
            "README.txt",
            (
                "InsightPilot Agent 中文分析导出包\n\n"
                "内容：中文 PDF、Markdown、离线 HTML、Excel、运行清单和限制行数的分析结果 CSV。\n"
                "导出包不包含上传源文件、完整数据库连接地址、密码或任何密钥。\n"
                "运行清单仅用于复现配置，不能恢复原始输入数据。\n"
                + "\n".join(truncations)
            ).encode("utf-8"),
        )
    return buffer.getvalue()
