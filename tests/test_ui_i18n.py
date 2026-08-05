from __future__ import annotations

from insightpilot.ui.i18n import UI_TEXT_ZH_CN, t


def test_required_chinese_i18n_keys_are_available() -> None:
    required = {
        "app.title",
        "app.subtitle",
        "sidebar.view_mode",
        "sidebar.data_source",
        "sidebar.goal_mode",
        "sidebar.workflow_backend",
        "section.analysis_summary",
        "section.risks_and_limitations",
        "section.technical_details",
        "action.run",
        "action.preview_plan",
        "action.approve_execute",
        "warning.plan_approval_required",
    }
    assert required.issubset(UI_TEXT_ZH_CN)
    assert all(t(key) == UI_TEXT_ZH_CN[key] for key in required)


def test_missing_i18n_key_has_safe_fallback() -> None:
    assert t("missing.key") == "missing.key"
    assert t("missing.key", "中文回退") == "中文回退"
