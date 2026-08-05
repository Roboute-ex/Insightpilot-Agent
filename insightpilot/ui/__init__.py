"""Chinese-first presentation layer over stable English internal schemas."""

from insightpilot.ui.i18n import t
from insightpilot.ui.view_modes import (
    ViewMode,
    get_view_mode_display_name,
    normalize_view_mode,
    should_show_developer_details,
    should_show_professional_details,
)
from insightpilot.ui.theme import apply_compact_theme, render_compact_summary_card

__all__ = [
    "ViewMode",
    "get_view_mode_display_name",
    "normalize_view_mode",
    "should_show_developer_details",
    "should_show_professional_details",
    "t",
    "apply_compact_theme",
    "render_compact_summary_card",
]
