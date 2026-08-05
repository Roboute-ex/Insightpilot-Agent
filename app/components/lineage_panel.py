"""Lineage and local observability summaries."""

from __future__ import annotations

from typing import Any

from insightpilot.ui.renderers import render_lineage, render_observability


def render_lineage_panel(result: dict[str, Any], view_mode: str) -> None:
    render_lineage(result.get("lineage", {}), view_mode)
    render_observability(result.get("telemetry", {}), view_mode)
