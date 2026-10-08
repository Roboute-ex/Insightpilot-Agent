from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_streamlit_result_details_show_structured_sections() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()
    next(item for item in app.button if item.label == "开始分析").click().run(timeout=90)
    assert not app.exception
    result = app.session_state["last_analysis_result"]
    run_id = result["run_manifest"]["run_id"]
    assert len(app.dataframe) == 2  # Bounded computed-result preview and city selection; raw preview remains closed
    assert len(app.dataframe[0].value) <= 8
    assert str(app.dataframe[1].key).startswith("drilldown_select_")
    app.session_state["requested_result_tab"] = "结果明细"
    app.run()
    for key, title in (("metric_comparisons", "指标对比"), ("funnel_decomposition", "漏斗拆解"), ("recommendations", "建议清单")):
        app.selectbox(key="result_table_selector").set_value(key).run()
        assert title in [item.value for item in app.subheader]
        assert len(app.dataframe) == 1  # only the selected computed result page
        original = result["result_tables"][key]
        displayed = app.dataframe[0].value
        assert len(original) > 0 and len(displayed) == min(100, len(original))
        assert len(displayed.columns) == len(original.columns)
        # Independent numeric checks: localization must not change computed values.
        import numpy as np
        for index, column in enumerate(original.columns):
            if original[column].dtype.kind in "iuf":
                np.testing.assert_allclose(displayed.iloc[:, index], original[column].iloc[:100], rtol=0, atol=0, equal_nan=True)
        assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == run_id


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
