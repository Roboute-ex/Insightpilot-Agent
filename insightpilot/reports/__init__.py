"""Report generation helpers."""

from insightpilot.reports.markdown import generate_markdown_report

__all__ = ["generate_markdown_report"]
"""Report generation and in-memory exports."""

from insightpilot.reports.bundle import generate_export_bundle
from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest, fingerprint_dataframe
from insightpilot.reports.markdown import generate_markdown_report

__all__ = [
    "RunManifest",
    "fingerprint_dataframe",
    "generate_excel_report",
    "generate_export_bundle",
    "generate_html_report",
    "generate_markdown_report",
]
