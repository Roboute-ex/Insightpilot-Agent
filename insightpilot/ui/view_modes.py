"""Central definitions for layered Streamlit views."""

from __future__ import annotations

from enum import Enum


class ViewMode(str, Enum):
    DEMO = "demo"
    PROFESSIONAL = "professional"
    DEVELOPER = "developer"


VIEW_MODE_DISPLAY_NAMES = {
    ViewMode.DEMO.value: "简洁演示",
    ViewMode.PROFESSIONAL.value: "专业分析",
    ViewMode.DEVELOPER.value: "开发者模式",
}


def normalize_view_mode(value: str | ViewMode | None) -> str:
    normalized = value.value if isinstance(value, ViewMode) else str(value or ViewMode.DEMO.value).strip().lower()
    return normalized if normalized in VIEW_MODE_DISPLAY_NAMES else ViewMode.DEMO.value


def get_view_mode_display_name(value: str | ViewMode | None) -> str:
    return VIEW_MODE_DISPLAY_NAMES[normalize_view_mode(value)]


def should_show_professional_details(view_mode: str | ViewMode | None) -> bool:
    return normalize_view_mode(view_mode) in {ViewMode.PROFESSIONAL.value, ViewMode.DEVELOPER.value}


def should_show_developer_details(view_mode: str | ViewMode | None) -> bool:
    return normalize_view_mode(view_mode) == ViewMode.DEVELOPER.value
