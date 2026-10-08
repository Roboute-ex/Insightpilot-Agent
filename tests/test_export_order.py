from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_pdf_download_button_appears_first() -> None:
    """Check rendered order even when cached files were generated in reverse order."""
    app = AppTest.from_string('''
import streamlit as st
from app.components.export_panel import render_export_panel, export_cache_key, EXPORT_CACHE_KEY
from insightpilot.performance import BoundedCache, PerformanceConfig
config = PerformanceConfig.from_environment()
result = {"run_manifest": {"run_id": "export-order-regression"}}
cache = BoundedCache(config.export_max_entries, config.export_max_bytes, config.session_ttl_seconds)
for format_name in ("bundle", "manifest", "excel", "html", "markdown", "pdf"):
    cache.put(export_cache_key(result, format_name, config=config), b"cached-report-bytes")
st.session_state[EXPORT_CACHE_KEY] = cache
st.session_state["export_run_id"] = "export-order-regression"
render_export_panel(result)
''').run()
    assert not app.exception
    assert [item.proto.label for item in app.get("download_button")] == [
        "下载 PDF 报告", "下载 Markdown 报告", "下载 HTML 报告",
        "下载 Excel 报告", "下载 运行清单 JSON", "下载 ZIP 报告包",
    ]
