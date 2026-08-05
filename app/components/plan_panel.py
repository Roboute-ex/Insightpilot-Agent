"""Analysis, semantic, join, and query plan summaries."""

from __future__ import annotations

from typing import Any

from insightpilot.ui.renderers import (
    render_analysis_plan_summary,
    render_join_plan_summary,
    render_plan_review,
    render_query_plan_summary,
    render_route_timeline,
    render_semantic_model_summary,
)


def render_plan_panel(result: dict[str, Any], view_mode: str) -> None:
    render_analysis_plan_summary(result.get("plan", {}), view_mode)
    render_semantic_model_summary(result.get("semantic_model", {}), view_mode)
    render_join_plan_summary(result.get("join_plan", {}), view_mode)
    render_query_plan_summary(result.get("query_plan", {}), view_mode)
    render_plan_review(result.get("plan_review", {}))
    render_route_timeline(result.get("route_taken", []), view_mode)
