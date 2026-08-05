from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_professional_mode_shows_chinese_query_summary_without_json() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    app.segmented_control[0].set_value("professional").run()
    next(item for item in app.selectbox if item.label == "演示场景").set_value("多表语义指标分析").run()
    next(item for item in app.selectbox if item.label == "分析剧本").set_value("semantic_metric_query").run()
    next(item for item in app.button if item.label == "开始分析").click().run()
    assert not app.exception
    assert "专业分析详情" in [item.label for item in app.tabs]
    assert "查询计划" in [item.value for item in app.subheader]
    assert len(app.json) == 0
