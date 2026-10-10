"""Reviewer and contract result panel."""
from __future__ import annotations
from typing import Any
from insightpilot.ui.renderers import render_contracts, render_reviewer
from insightpilot.analysis.quality import quality_rows


def render_quality_dimensions(result: dict[str, Any], view_mode: str = "professional") -> None:
    """Only existing small metadata is read; rendering never triggers analysis."""
    from insightpilot.ui.theme import render_compact_summary_card
    for row in quality_rows(result):
        render_compact_summary_card(row["检查维度"], row["状态"])


def render_reviewer_panel(result: dict[str, Any], view_mode: str) -> None:
    render_quality_dimensions(result, view_mode)
    render_reviewer(result.get("reviewer", {}), view_mode)
    render_contracts(result.get("contract_results", []), view_mode)
