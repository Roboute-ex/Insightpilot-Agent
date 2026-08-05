"""Human-readable workflow route panel."""

from __future__ import annotations

from typing import Any

from insightpilot.ui.renderers import render_route_timeline


def render_trace_panel(result: dict[str, Any], view_mode: str) -> None:
    render_route_timeline(result.get("route_taken", []), view_mode)
