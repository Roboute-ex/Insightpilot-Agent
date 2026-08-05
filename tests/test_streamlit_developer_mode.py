from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_developer_mode_exposes_collapsed_json_and_preserves_session_result() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    next(item for item in app.button if item.label == "开始分析").click().run()
    run_id = app.session_state["last_analysis_result"]["run_manifest"]["run_id"]
    app.segmented_control[0].set_value("developer").run()
    assert not app.exception
    assert "开发者详情" in [item.label for item in app.tabs]
    assert len(app.json) > 0
    assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == run_id
    assert any("原始分析计划 JSON" in item.value for item in app.markdown)
