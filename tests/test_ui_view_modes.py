from __future__ import annotations

from insightpilot.ui.view_modes import (
    ViewMode,
    get_view_mode_display_name,
    normalize_view_mode,
    should_show_developer_details,
    should_show_professional_details,
)


def test_view_mode_defaults_to_demo_and_normalizes_unknown_values() -> None:
    assert normalize_view_mode(None) == "demo"
    assert normalize_view_mode("unknown") == "demo"
    assert normalize_view_mode(ViewMode.PROFESSIONAL) == "professional"
    assert get_view_mode_display_name("demo") == "简洁演示"


def test_view_mode_detail_visibility_is_layered() -> None:
    assert should_show_professional_details("demo") is False
    assert should_show_professional_details("professional") is True
    assert should_show_professional_details("developer") is True
    assert should_show_developer_details("professional") is False
    assert should_show_developer_details("developer") is True
