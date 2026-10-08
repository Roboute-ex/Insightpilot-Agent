from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_default_app_controls_use_chinese_labels() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    # The home page is one workbench; advanced controls still use Chinese.
    labels = {item.label for collection in (app.selectbox, app.segmented_control, app.button, app.text_input) for item in collection}
    assert {"数据来源", "演示场景", "你想分析什么？", "开始分析"}.issubset(labels)
    assert {"界面模式", "分析目标", "工作流后端", "分析方法", "预览分析方案"}.isdisjoint(labels)
    assert app.session_state["view_mode"] == "demo"  # retained machine compatibility
    assert not app.json and not app.dataframe
    for key in ("guided_advanced", "guided_data_preview", "guided_data_settings", "guided_plan"):
        app.session_state[key] = True
    app.run()
    assert not app.exception
    labels = {item.label for collection in (app.selectbox, app.segmented_control, app.button, app.text_input) for item in collection}
    assert {"分析目标", "工作流后端", "分析方法", "数据规模", "预览数据表（不改变分析范围）", "预览分析方案"}.issubset(labels)
    assert {"Data Source", "Analysis Goal Mode", "Workflow Backend", "Caveats", "Analysis Plan"}.isdisjoint(labels)
    assert app.session_state["last_analysis_result"] is None
