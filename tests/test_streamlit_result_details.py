from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_streamlit_result_details_show_structured_sections() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()
    next(item for item in app.button if item.label == "开始分析").click().run(timeout=90)
    assert not app.exception
    headings = [item.value for item in app.subheader]
    assert "指标对比" in headings
    assert "漏斗拆解" in headings
    assert "建议清单" in headings


def test_streamlit_experiment_result_shows_complete_statistics() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()
    next(item for item in app.selectbox if item.label == "演示场景").select("内容消费与实验分析").run(timeout=90)
    next(item for item in app.button if item.label == "开始分析").click().run(timeout=90)
    assert not app.exception
    visible_text = "\n".join(
        str(item.value)
        for collection in (app.subheader, app.markdown, app.caption)
        for item in collection
    )
    for marker in ("实验分析结果", "实验组", "对照组", "样本量", "lift", "p-value", "95% 置信区间", "显著性结论"):
        assert marker in visible_text
    assert "completion_rate" not in visible_text
    assert all("completion_rate" not in str(item.value) for item in app.dataframe)
