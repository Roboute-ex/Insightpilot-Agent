"""In-memory ZIP export bundle."""

from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd


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
) -> bytes:
    """Build a safe report bundle without including source files or credentials."""

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("report.md", markdown_report.encode("utf-8"))
        archive.writestr("report.html", html_report.encode("utf-8"))
        archive.writestr("report.xlsx", excel_bytes)
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
                "InsightPilot Agent export bundle\n\n"
                "Contents: Markdown, offline HTML, Excel, run manifest, and capped analysis-result CSV files.\n"
                "The bundle does not contain uploaded source files, full database URLs, passwords, or API keys.\n"
                "The manifest reproduces configuration, not the original input data.\n"
            ).encode("utf-8"),
        )
    return buffer.getvalue()
