from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_demo_mode_is_default_and_hides_technical_json() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert app.segmented_control[0].value == "demo"
    next(item for item in app.button if item.label == "开始分析").click().run()
    assert not app.exception
    assert [item.label for item in app.tabs] == ["分析概览", "可视化诊断", "结果明细", "质量检查", "报告导出"]
    assert len(app.json) == 0
    visible_headings = [item.value for item in app.subheader]
    assert "分析方案摘要" in visible_headings
    assert "Analysis Plan" not in visible_headings
