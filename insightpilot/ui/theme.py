"""Central compact typography and summary-card styling."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st


COMPACT_THEME_CSS = """
<style>
.ip-summary-card {
  border: 1px solid #D7E0DE;
  border-radius: 6px;
  background: #FFFFFF;
  padding: 0.72rem 0.82rem;
  min-height: 0;
  height: 100%;
}
.ip-summary-title {
  color: #40504D;
  font-size: 12pt;
  font-weight: 600;
  line-height: 1.4;
  margin: 0 0 0.28rem 0;
}
.ip-summary-content {
  color: #17201F;
  font-size: 10.5pt;
  font-weight: 400;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.ip-summary-content ul {
  margin: 0;
  padding-left: 1.1rem;
}
.ip-summary-status {
  color: #0F766E;
  font-size: 9.5pt;
  font-weight: 600;
  margin-top: 0.35rem;
}
.ip-result-note {
  border-left: 3px solid #0F766E;
  padding: 0.35rem 0.7rem;
  color: #40504D;
  font-size: 10.5pt;
  line-height: 1.55;
}
</style>
"""


def apply_compact_theme() -> None:
    st.markdown(COMPACT_THEME_CSS, unsafe_allow_html=True)


def render_compact_summary_card(
    title: str,
    content: str | list[str],
    help_text: str | None = None,
    status: str | None = None,
) -> None:
    title_text = escape(str(title))
    help_attr = f' title="{escape(str(help_text))}"' if help_text else ""
    if isinstance(content, list):
        content_html = "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in content) + "</ul>"
    else:
        content_html = escape(str(content)).replace("\n", "<br>")
    status_html = f'<div class="ip-summary-status">{escape(str(status))}</div>' if status else ""
    st.markdown(
        f'<div class="ip-summary-card"{help_attr}>'
        f'<div class="ip-summary-title">{title_text}</div>'
        f'<div class="ip-summary-content">{content_html}</div>'
        f'{status_html}</div>',
        unsafe_allow_html=True,
    )


def render_result_note(message: Any) -> None:
    st.markdown(f'<div class="ip-result-note">{escape(str(message))}</div>', unsafe_allow_html=True)


__all__ = ["COMPACT_THEME_CSS", "apply_compact_theme", "render_compact_summary_card", "render_result_note"]
