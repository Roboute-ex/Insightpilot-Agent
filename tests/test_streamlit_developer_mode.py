from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_developer_mode_exposes_collapsed_json_and_preserves_session_result(monkeypatch) -> None:
    import insightpilot.agents.workflow as workflow
    calls = []
    original = workflow.run_agent_analysis
    def watched(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(workflow, "run_agent_analysis", watched)
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    next(item for item in app.button if item.label == "开始分析").click().run()
    run_id = app.session_state["last_analysis_result"]["run_manifest"]["run_id"]
    assert "技术详情" in [item.label for item in app.expander]
    assert len(app.json) == 0
    assert not any(item.label == "显示所选 JSON" for item in app.button)
    app.session_state["guided_technical"] = True
    app.run()
    assert not app.exception
    # Opening technical details explicitly permits its existing folded plan JSON;
    # requesting the selected object remains a separate, counted UI action.
    detail_json_count = len(app.json)
    next(item for item in app.button if item.label == "显示所选 JSON").click().run()
    assert len(app.json) == detail_json_count + 1
    assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == run_id
    assert any("原始分析计划 JSON" in item.value for item in app.markdown)
    assert calls == [1], "Opening technical details or JSON must not repeat analysis"
