"""Reviewer and contract result panel."""

from __future__ import annotations

from typing import Any

from insightpilot.ui.renderers import render_contracts, render_reviewer


def render_reviewer_panel(result: dict[str, Any], view_mode: str) -> None:
    render_reviewer(result.get("reviewer", {}), view_mode)
    render_contracts(result.get("contract_results", []), view_mode)
