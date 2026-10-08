"""Global sidebar controls."""

from __future__ import annotations

import streamlit as st

from insightpilot.ui.help_text import help_text
from insightpilot.ui.i18n import t
from insightpilot.ui.view_modes import ViewMode, get_view_mode_display_name, normalize_view_mode


def render_view_mode_selector() -> str:
    options = [item.value for item in ViewMode]
    selected = st.sidebar.segmented_control(
        t("sidebar.view_mode"),
        options,
        default=ViewMode.DEMO.value,
        required=True,
        format_func=get_view_mode_display_name,
        key="view_mode",
        width="stretch",
    )
    return normalize_view_mode(selected)


def render_source_goal_backend(
    goal_modes: list[str],
) -> tuple[str, str, bool]:
    source = st.sidebar.selectbox(
        t("sidebar.data_source"),
        ["synthetic", "upload", "database"],
        format_func=lambda value: t(f"source.{value}"),
        key="data_source_selector",
    )
    # Goal and backend are retained as stable internal configuration, rendered
    # only in the workbench's explicitly opened advanced settings.
    goal_mode = st.session_state.get("goal_mode_selector", "auto")
    backend = st.session_state.get("workflow_backend_selector", "rule_based")
    return str(source), str(goal_mode), backend == "langgraph"
