"""Reviewer and contract result panel."""
from __future__ import annotations
from typing import Any
from insightpilot.ui.renderers import render_contracts, render_reviewer
from insightpilot.analysis.quality import QUALITY_NOTICE, quality_rows


def render_quality_dimensions(result: dict[str, Any], view_mode: str = "professional") -> None:
    """Only existing small metadata is read; rendering never triggers analysis."""
    import streamlit as st
    from insightpilot.ui.theme import render_compact_summary_card
    from insightpilot.ui.view_modes import should_show_professional_details
    st.caption(QUALITY_NOTICE)
    for row in quality_rows(result):
        render_compact_summary_card(row["检查维度"], row["状态"])
        if should_show_professional_details(view_mode):
            st.caption(row["依据与边界"])


def render_reviewer_panel(result: dict[str, Any], view_mode: str) -> None:
    render_quality_dimensions(result, view_mode)
    render_reviewer(result.get("reviewer", {}), view_mode)
    render_contracts(result.get("contract_results", []), view_mode)
