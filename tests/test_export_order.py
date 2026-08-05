from __future__ import annotations

from pathlib import Path


def test_pdf_download_button_appears_first() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "components" / "export_panel.py").read_text(encoding="utf-8")
    assert source.index('st.download_button("下载 PDF 报告"') < source.index('st.download_button(t("action.download_markdown")')
