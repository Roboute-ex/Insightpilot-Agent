from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_professional_mode_shows_chinese_query_summary_without_json() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert app.segmented_control(key="workbench_page").value == "workbench"
    assert not any(item.label == "界面模式" for item in app.segmented_control)
    app.session_state["guided_advanced"] = True; app.run()
    next(item for item in app.selectbox if item.label == "演示场景").set_value("多表语义指标分析").run()
    next(item for item in app.selectbox if item.label == "分析方法").set_value("semantic_metric_query").run()
    # The independent parameter form does not send displayed defaults until applied.
    next(item for item in app.button if item.label == "应用参数并更新建议").click().run()
    next(item for item in app.button if item.label == "开始分析").click().run()
    assert not app.exception
    result = app.session_state["last_analysis_result"]
    run_id = result["run_manifest"]["run_id"]
    assert "查看口径与质量" in [item.label for item in app.expander]
    assert len(app.json) == 0
    app.session_state["guided_quality"] = True; app.run()
    assert not app.exception
    visible = "\n".join(str(item.value) for items in (app.markdown, app.caption, app.subheader) for item in items)
    for label in ("执行", "指标口径", "数据质量", "统计前提", "证据"):
        assert f'class="ip-summary-title">{label}</div>' in visible
    assert len(app.json) == 0
    app.session_state["guided_technical"] = True; app.run()
    assert "查询计划" in [item.value for item in app.subheader]
    # Technical details were explicitly opened; the default workbench and quality
    # summary above remain free of JSON. Technical plan data can now be rendered.
    assert app.session_state["last_analysis_result"] is result
    assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == run_id
