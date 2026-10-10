from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_demo_mode_is_default_and_hides_technical_json() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert app.session_state["view_mode"] == "demo"
    assert app.segmented_control(key="workbench_page").options == ["分析工作台", "数据探索", "分析方法", "历史比较"]
    assert not any(item.label == "界面模式" for item in app.segmented_control)
    assert app.session_state["playbook_selector"] == "auto"
    next(item for item in app.button if item.label == "开始分析").click().run()
    assert not app.exception
    assert not app.tabs
    assert app.segmented_control(key="result_tabs").options == ["结论", "图表", "明细", "报告"]
    assert app.segmented_control(key="result_tabs").value == "分析概览"
    assert {"查看口径与质量", "技术详情"}.issubset({item.label for item in app.expander})
    assert "历史比较" in app.segmented_control(key="workbench_page").options
    assert len(app.json) == 0
    visible_headings = [item.value for item in app.subheader]
    assert [title for title in visible_headings if title in {
        "发生了什么", "变化集中在哪里", "证据支持到哪一步", "下一步"
    }] == ["发生了什么", "变化集中在哪里", "证据支持到哪一步", "下一步"]
    assert "分析方案摘要" not in visible_headings
    app.session_state["guided_technical"] = True
    app.run()
    assert "分析方案摘要" in [item.value for item in app.subheader]
    assert "Analysis Plan" not in visible_headings
