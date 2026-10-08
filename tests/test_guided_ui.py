"""Guided workbench interactions over the common metadata-only preflight."""
from collections import Counter
from pathlib import Path
import functools

from streamlit.testing.v1 import AppTest
from ui_session_support import session_snapshot

APP = Path(__file__).resolve().parents[1] / "app/ui_streamlit.py"


def start(*, old_method=None, scale="small"):
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["demo_scale"] = scale
    app.session_state["question"] = "昨日订单量为什么下降？"
    app.session_state["goal_mode_selector"] = "metric_diagnosis"
    if old_method:
        app.session_state["playbook_selector"] = old_method
        app.session_state["playbook_parameter_causal_exploration_treatment_value"] = "treatment"
        app.session_state["playbook_parameter_causal_exploration_control_value"] = "control"
    app.run()
    assert not app.exception
    return app


def click(app, label):
    next(item for item in app.button if item.label == label).click().run()
    assert not app.exception


def open_panel(app, key, value=True):
    # Streamlit 1.63 AppTest exposes expander state but no click method.
    # Browser acceptance separately verifies native details clicks.
    if key == "guided_all_methods":
        app.segmented_control(key="workbench_page").set_value("methods" if value else "workbench").run()
    else:
        app.session_state[key] = value
        app.run()
    assert not app.exception


def watch(monkeypatch):
    import insightpilot.agents.workflow as workflow
    import insightpilot.agents.dataset as dataset
    import app.components.export_panel as exports
    import app.background_tasks as background
    counts = Counter()
    for module, name in ((workflow, "run_agent_analysis"), (dataset, "fingerprint_dataframe"),
                         (exports, "prepare_export_payload"), (background, "request_work")):
        original = getattr(module, name)
        @functools.wraps(original)
        def counted(*args, _function=original, _name=name, **kwargs):
            counts[_name] += 1
            return _function(*args, **kwargs)
        monkeypatch.setattr(module, name, counted)
    return counts


def test_new_standard_session_defaults_to_auto_without_hidden_causal_controls(monkeypatch):
    counts = watch(monkeypatch)
    app = start(scale="standard")
    assert app.session_state["playbook_selector"] == "auto"
    assert app.session_state["guided_selection_source"] == "automatic"
    advice = app.session_state["guided_advice"]
    assert advice["requested_method"] is None and advice["can_submit"]
    assert advice["effective_method"]["method_ref"] == "route:legacy"
    assert not any(x.label in {"界面模式", "工作流后端", "分析目标", "处理组值", "对照组值"} for x in [*app.selectbox, *app.text_input])
    assert len([x for x in app.button if x.proto.type == "primary"]) == 1
    assert len([x for x in app.button if str(x.key).startswith("guided_example_")]) == 3
    assert len(app.json) == len(app.dataframe) == 0
    assert counts["run_agent_analysis"] == counts["prepare_export_payload"] == counts["request_work"] == 0


def test_screenshot_config_blocks_before_task_and_accepting_recommendation_only_changes_config(monkeypatch):
    counts = watch(monkeypatch)
    app = start(old_method="causal_exploration")
    assert app.session_state["guided_selection_source"] == "legacy_unconfirmed"
    assert not app.session_state["guided_advice"]["can_submit"]
    text = " ".join(str(x.value) for x in [*app.markdown, *app.warning, *app.info])
    assert "分组字段" in text and "组别取值" in text
    assert "缺少结果变量" not in text
    assert app.button(key="guided_run").disabled
    assert not app.session_state["performance_result"].history.nodes
    assert counts["run_agent_analysis"] == counts["prepare_export_payload"] == counts["request_work"] == 0
    fingerprints = counts["fingerprint_dataframe"]
    click(app, "改用推荐方法")
    assert app.session_state["playbook_selector"] == "auto"
    assert counts["run_agent_analysis"] == 0
    assert not app.button(key="guided_run").disabled
    click(app, "开始分析")
    result = app.session_state["last_analysis_result"]
    assert result["execution_status"] == "COMPLETED" and result["result_tables"]
    assert counts["run_agent_analysis"] == 1
    assert counts["fingerprint_dataframe"] == fingerprints
    assert counts["prepare_export_payload"] == 0


def test_example_atomically_clears_causal_state_and_does_not_analyze(monkeypatch):
    counts = watch(monkeypatch)
    app = start(old_method="causal_exploration")
    next(x for x in app.button if str(x.key).startswith("guided_example_")).click().run()
    assert not app.exception
    assert app.session_state["playbook_selector"] == "auto"
    assert app.session_state["guided_selection_source"] == "example_applied"
    assert not any(key.startswith("playbook_parameter_causal_exploration_") for key in session_snapshot(app))
    assert any("已填入示例并恢复自动推荐" in str(x.value) for x in app.caption)
    assert counts["run_agent_analysis"] == counts["prepare_export_payload"] == 0


def test_question_changes_refresh_advice_and_preserve_explicit_manual_choice(monkeypatch):
    counts = watch(monkeypatch); app = start()
    before = app.session_state["guided_advice"]["request_fingerprint"]
    app.text_input(key="question").set_value("请看订单趋势").run()
    assert app.session_state["guided_advice"]["request_fingerprint"] != before
    open_panel(app, "guided_advanced")
    app.selectbox(key="playbook_selector").set_value("causal_exploration").run()
    assert app.session_state["guided_selection_source"] == "user_selected"
    open_panel(app, "guided_advanced", False)
    app.text_input(key="question").set_value("昨日订单量为什么下降？").run()
    assert app.session_state["playbook_selector"] == "causal_exploration"
    assert any("已手动选择" in str(x.value) for x in app.caption)
    assert app.button(key="guided_run").disabled
    assert counts["run_agent_analysis"] == 0


def test_preview_table_and_advanced_details_do_not_change_analysis_scope_or_fingerprint(monkeypatch):
    counts = watch(monkeypatch); app = start()
    identity = app.session_state["guided_advice"]["request_fingerprint"]
    before = counts.copy()
    open_panel(app, "guided_data_preview")
    app.selectbox(key="preview_table").set_value("orders").run()
    assert app.session_state["guided_advice"]["request_fingerprint"] == identity
    open_panel(app, "guided_advanced")
    open_panel(app, "guided_all_methods")
    assert counts == before


def test_blocked_new_request_keeps_last_success_and_report_identity(monkeypatch):
    counts = watch(monkeypatch); app = start(); click(app, "开始分析")
    previous = app.session_state["last_analysis_result"]["run_manifest"]["run_id"]
    open_panel(app, "guided_advanced")
    app.selectbox(key="playbook_selector").set_value("causal_exploration").run()
    assert app.button(key="guided_run").disabled
    assert any("上次成功结果" in str(x.value) for x in app.warning)
    assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == previous
    assert len(app.session_state["performance_result"].history.nodes) == 1
    app.session_state["requested_result_tab"] = "报告导出"; app.run()
    assert app.session_state["export_run_id"] == previous
    assert counts["run_agent_analysis"] == 1 and counts["prepare_export_payload"] == 0


def test_engine_exception_still_shows_specific_redacted_failure(monkeypatch):
    import insightpilot.agents.workflow as workflow
    def fail(*args, **kwargs):
        raise RuntimeError("本地测试异常 https://example.invalid/?token=hidden-secret")
    monkeypatch.setattr(workflow, "run_agent_analysis", fail)
    app = start(); click(app, "开始分析")
    text = " ".join(str(x.value) for x in app.error)
    assert "分析执行失败" in text and "本地测试异常" in text
    assert "hidden-secret" not in text
    assert app.session_state["performance_task_status"] == "failed"


def test_apptest_expander_bridge_preserves_only_real_open_state():
    app = AppTest.from_string("""
import streamlit as st
panel = st.expander("测试入口", key="test_panel", on_change="rerun")
if panel.open:
    with panel:
        st.text_input("面板字段", key="test_value")
        st.button("面板动作")
""").run()
    assert not app.text_input and not app.button
    app.session_state["test_panel"] = True; app.run()
    assert len(app.text_input) == 1
    app.text_input(key="test_value").set_value("新内容").run()
    assert len(app.text_input) == 1 and app.text_input[0].value == "新内容"
    app.session_state["test_panel"] = False; app.run()
    assert not app.text_input and not app.button


def test_late_non_success_is_not_recorded_as_success_or_exported(monkeypatch):
    import insightpilot.agents.workflow as workflow
    for status in ("WAITING_APPROVAL", "NEEDS_INPUT", "UNSUPPORTED", "INVALID_INPUT", "FAILED"):
        monkeypatch.setattr(workflow, "run_agent_analysis", lambda *args, _status=status, **kwargs: {
            "execution_status": _status, "execution_mode": "execute", "errors": ["具体阻断说明"],
            "run_manifest": {"run_id": "blocked-"+_status}, "result_tables": {}})
        app = start(); click(app, "开始分析")
        assert app.session_state["guided_execution_status"] == status
        assert not app.session_state["performance_result"].history.nodes
        app.session_state["requested_result_tab"] = "报告导出"; app.run()
        assert not any(x.label.startswith("生成 PDF") for x in app.button)
        assert not any("上次成功结果" in str(x.value) for x in app.warning)
        assert any("尚未成功完成" in str(x.value) for x in app.info)


def test_auto_method_parameter_form_applies_new_values_and_clears_only_on_route_change(monkeypatch):
    counts = watch(monkeypatch); app = start()
    open_panel(app, "guided_advanced")
    app.selectbox(key="goal_mode_selector").set_value("auto").run()
    app.text_input(key="question").set_value("请分析订单趋势").run()
    assert app.session_state["guided_advice"]["effective_method"]["id"] == "metric_trend"
    app.number_input(key="playbook_parameter_metric_trend_rolling_window").set_value(5)
    click(app, "应用参数并更新建议")
    assert app.session_state["guided_parameters"]["rolling_window"] == 5
    app.text_input(key="question").set_value("请看最近的订单趋势").run()
    assert app.session_state["guided_parameters"]["rolling_window"] == 5
    app.text_input(key="question").set_value("昨日订单量为什么下降？").run()
    assert app.session_state["guided_advice"]["effective_method"]["method_ref"] == "route:legacy"
    assert app.session_state["guided_parameters"] == {}
    assert counts["run_agent_analysis"] == counts["prepare_export_payload"] == 0
