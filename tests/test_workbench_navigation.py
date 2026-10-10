"""Business navigation is presentation-only; method identity remains Registry-owned."""
from pathlib import Path
from collections import Counter
import functools
import pytest
from streamlit.testing.v1 import AppTest
from insightpilot.playbooks.registry import get_playbook_registry

APP = Path(__file__).resolve().parents[1] / "app/ui_streamlit.py"


def start():
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["demo_scale"] = "small"
    app.run()
    assert not app.exception
    return app


def navigate(app, page):
    app.segmented_control(key="workbench_page").set_value(page).run()
    assert not app.exception


def body(app):
    return "\n".join(str(x.value) for kind in ("markdown", "caption", "info", "warning", "success") for x in getattr(app, kind))


def test_workbench_shows_metadata_configuration_and_six_real_shortcuts():
    app = start()
    assert app.segmented_control(key="workbench_page").options == ["分析工作台", "数据探索", "分析方法", "历史比较"]
    assert not any(x.label == "界面模式" for x in app.segmented_control)
    assert "daily_metrics" in body(app) and "本次分析配置 · 草稿" in body(app)
    assert "已识别日期范围" in body(app)
    assert {str(x.key).removeprefix("common_choose_") for x in app.button if str(x.key).startswith("common_choose_")} == {
        "data_profile", "metric_trend", "period_comparison", "dimension_contribution", "experiment_comparison", "causal_exploration"}
    assert "分析方法" in app.segmented_control(key="workbench_page").options
    assert not any(item.key in {"workbench_all_methods", "workbench_edit_config"} for item in app.button)
    assert not app.button(key="guided_run").disabled
    assert not app.json and not app.get("plotly_chart")
    assert not app.session_state["performance_result"].history.nodes


def test_method_library_filters_are_explicit_clearable_and_do_not_delete_unavailable_methods():
    app = start()
    navigate(app, "methods")
    assert app.session_state["workbench_page"] == "methods"
    count = len(get_playbook_registry().list_all())
    assert len([x for x in app.button if str(x.key).startswith("guided_choose_")]) == count
    app.selectbox(key="method_category").set_value("实验与效果").run()
    assert {str(x.key).removeprefix("guided_choose_") for x in app.button if str(x.key).startswith("guided_choose_")} == {"causal_exploration", "experiment_comparison"}
    app.text_input(key="method_search").set_value("轻量因果").run()
    assert len([x for x in app.button if str(x.key).startswith("guided_choose_")]) == 1
    assert "处理" in body(app)
    app.button(key="method_clear_filters").click().run()
    assert len([x for x in app.button if str(x.key).startswith("guided_choose_")]) == count
    app.button(key="guided_choose_causal_exploration").click().run()
    assert not app.exception
    assert app.session_state["workbench_page"] == "workbench"
    assert app.selectbox(key="mapping_table").value == "daily_metrics"
    assert app.selectbox(key="mapping_outcome").value == "orders"
    assert app.session_state["guided_selection_source"] == "user_selected"
    assert app.button(key="guided_run").disabled


def test_examples_and_configuration_stay_with_inputs_and_open_without_work(monkeypatch):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    app = start()
    question = next(item for item in app.main if getattr(item, "key", None) == "workbench_question_column")
    config = next(item for item in app.main if getattr(item, "key", None) == "workbench_config_column")
    question_keys = [getattr(item, "key", None) for item in question]
    assert question_keys.index("question") < question_keys.index("guided_more_examples")
    assert "guided_advanced" not in question_keys
    assert "guided_run" not in question_keys
    assert "guided_advanced" in [getattr(item, "key", None) for item in config]
    main_keys = [getattr(item, "key", None) for item in app.main]
    assert main_keys.index("guided_advanced") < main_keys.index("guided_run")
    assert "guided_plan" not in [getattr(item, "key", None) for item in app.main]
    before = counts.copy()
    app.session_state["guided_more_examples"] = True
    app.run()
    assert app.button(key="guided_apply_example")
    app.session_state["guided_advanced"] = True
    app.run()
    assert not app.exception
    advanced = next(item for item in app.expander if item.key == "guided_advanced")
    assert "guided_plan" in [getattr(item, "key", None) for item in advanced]
    assert not any(item.key == "guided_preview" for item in app.button)
    app.session_state["guided_plan"] = True
    app.run()
    assert not app.exception
    assert app.button(key="guided_preview")
    assert_no_work_since(counts, before)
    assert app.session_state["last_analysis_result"] is None
    assert not app.session_state["performance_result"].history.nodes


def test_presentation_navigation_keeps_draft_without_loading_hashing_or_execution(monkeypatch, caplog):
    import app.components.data_source_panel as source
    import insightpilot.agents.dataset as dataset
    import insightpilot.agents.workflow as workflow
    import app.components.export_panel as exports
    import app.background_tasks as background
    counts = Counter()
    for module, name in ((source,"load_synthetic_tables"), (dataset,"infer_schema_mapping"),
        (dataset,"build_readiness_summary"), (dataset,"fingerprint_dataframe"), (workflow,"run_agent_analysis"),
        (exports,"prepare_export_payload"), (background,"request_work")):
        original = getattr(module, name)
        @functools.wraps(original)
        def tracked(*args, _fn=original, _name=name, **kwargs):
            counts[_name] += 1
            return _fn(*args, **kwargs)
        monkeypatch.setattr(module, name, tracked)
    app = start()
    app.button(key="common_choose_causal_exploration").click().run()
    app.selectbox(key="mapping_outcome").set_value("不选择").run()
    expected = counts.copy()
    fingerprint = app.session_state["guided_advice"]["request_fingerprint"]
    for page in ("methods", "history", "explore", "workbench", "methods", "workbench"):
        navigate(app, page)
        assert app.session_state["guided_advice"]["request_fingerprint"] == fingerprint
        assert counts == expected
    assert app.selectbox(key="mapping_outcome").value == "不选择"
    assert "MISSING_OUTCOME_COLUMN" in str(app.session_state["guided_advice"]["blocking_issues"])
    assert app.session_state["guided_selection_source"] == "user_selected"
    assert not any("default value" in str(x.value) for x in app.warning)
    assert not any("created with a default value" in record.getMessage() for record in caplog.records)
    assert not app.session_state["performance_result"].history.nodes


def test_causal_result_layout_never_shows_order_placeholder_cards():
    import pandas as pd
    from app.components.result_layout import _overview_specs, primary_result_table
    result = {"result_tables": {"adjusted_effect_summary": pd.DataFrame([{"naive_difference":2.,"adjusted_effect":float("nan"),"sample_size":24}])},
        "chart_specs":[{"chart_id":"adjusted_effect","chart_type":"bar","title":"adjusted","table_key":"adjusted_effect_summary", "y":["naive_difference","adjusted_effect","propensity_weighted_effect"]}]}
    assert primary_result_table(result) == "adjusted_effect_summary"
    assert _overview_specs(result)[0]["y"] == ["naive_difference"]
    assert _overview_specs(result)[0]["chart_type"] == "grouped_bar"
    assert result["chart_specs"][0]["y"] == ["naive_difference","adjusted_effect","propensity_weighted_effect"]
    app = AppTest.from_string("""
import pandas as pd
from app.components.result_layout import render_causal_kpis
render_causal_kpis({'result_tables': {'adjusted_effect_summary': pd.DataFrame([{'naive_difference':2.,'adjusted_effect':float('nan'),'sample_size':24}])}})
""").run()
    assert not app.exception
    assert "未执行 / 无可用估计" in body(app)
    assert "原始组间差" in body(app) and "24" in body(app)
    assert "主要负向贡献" not in body(app) and "当前分析类型不适用交易漏斗" not in body(app)


@pytest.mark.parametrize("package", [
    {"funnel_results": [{"stage_name": "访问", "current_count": 10}, {"stage_name": "购买", "current_count": 5, "current_rate": .5}]},
    {"cohort_results": [{"cohort": "2026-01", "period": 1, "retention": .5}]},
])
def test_non_transaction_highlights_do_not_fabricate_empty_order_cards(package):
    # Presentation-only fixtures. Actual funnel/retention computations stay in
    # their existing playbook tests; this asserts no irrelevant placeholders.
    app = AppTest.from_string("""
from app.components.result_panel import _render_result_highlights
_render_result_highlights(PACKAGE)
""".replace("PACKAGE", repr(package))).run()
    assert not app.exception
    assert not app.markdown
    assert "主要异常" not in body(app)
    assert "当前分析类型不适用交易漏斗" not in body(app)
