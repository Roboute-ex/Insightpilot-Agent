"""Collapsed raw technical objects for developer mode only."""

from __future__ import annotations

from typing import Any

from insightpilot.ui.renderers import render_developer_details


def render_developer_panel(result: dict[str, Any], view_mode: str) -> None:
    render_developer_details(result, view_mode)
