from __future__ import annotations

from app.ui_streamlit import _mapping_for_playbook_ui, _playbook_label_map, _recommended_playbook_ids


def test_streamlit_playbook_helpers_are_deterministic(playbook_tables, playbook_mapping) -> None:
    mapping = _mapping_for_playbook_ui("metric_trend", playbook_tables, playbook_mapping)
    first = _recommended_playbook_ids("growth_trend", mapping)
    second = _recommended_playbook_ids("growth_trend", mapping)
    assert first == second
    assert "Auto recommended" in _playbook_label_map()
