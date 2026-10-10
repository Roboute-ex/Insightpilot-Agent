"""Check server set_value signals, not AppTest's simulated form submissions."""
import pytest

from app.session_data import AnalysisSession
from test_core_exploration_return import _app, _session
from test_core_workflow_navigation import _add, _config, _press, _result


def test_mounted_exploration_form_does_not_receive_old_value_on_return_or_cancel(monkeypatch):
    session, parent, _ = _session()
    app = _app(monkeypatch, session)
    app.run()
    assert not app.exception
    assert not app.text_input(key="exploration_unit").proto.set_value
    _press(app, "core_return_parent")
    assert session.history.active_node_id == parent.node_id
    assert not app.text_input(key="exploration_unit").proto.set_value
    _press(app, "core_restore_config")
    assert not app.text_input(key="exploration_unit").proto.set_value
    _press(app, "core_restore_cancel")
    assert not app.text_input(key="exploration_unit").proto.set_value


def test_explicit_exploration_restore_still_sends_the_frozen_unit(monkeypatch):
    session = AnalysisSession()
    config = _config("父分组探索")
    config["column_mapping"]["unit"] = "冻结的订单单位"
    config["parameters"]["exploration_request"] = {"kind": "grouped", "row_dimension": "city", "filters": []}
    parent = _add(session.history, "parent-explore", config=config)
    child = _add(session.history, "child", parent=parent.run_id)
    session.accept("child", _result(child.run_id))
    app = _app(monkeypatch, session)
    _press(app, "core_return_parent")
    _press(app, "core_restore_config")
    _press(app, "core_restore_confirm")
    widget = app.text_input(key="exploration_unit")
    assert widget.value == "冻结的订单单位"
    assert widget.proto.set_value
    app.run()
    assert not app.exception
    assert not app.text_input(key="exploration_unit").proto.set_value


def test_hidden_exploration_form_keeps_last_submitted_configuration(monkeypatch):
    session, _, _ = _session()
    app = _app(monkeypatch, session)
    app.segmented_control(key="workbench_page").set_value("workbench").run()
    assert not app.exception
    assert app.session_state["exploration_unit"] == "服务器已提交的旧单位"
    app.run()
    app.segmented_control(key="workbench_page").set_value("explore").run()
    assert not app.exception
    assert app.text_input(key="exploration_unit").value == "服务器已提交的旧单位"


@pytest.mark.parametrize("automatic", [False, True])
def test_mounted_parameter_form_skips_writeback_but_hidden_parameters_persist(automatic):
    from streamlit.testing.v1 import AppTest
    from app.components.semantic_panel import PLAYBOOK_AUTO
    app = AppTest.from_string('''
import streamlit as st
from app.components.guidance_panel import initialize_guidance
initialize_guidance()
st.segmented_control("页面", ["workbench", "history"], key="workbench_page")
if st.session_state["workbench_page"] == "workbench" and st.session_state["guided_advanced"]:
    with st.form("analysis_parameter_form"):
        st.text_input("参数", key="playbook_parameter_period_comparison_metric")
        st.form_submit_button("应用")
''')
    key = "playbook_parameter_period_comparison_metric"
    app.session_state["workbench_page"] = "workbench"
    app.session_state["guided_advanced"] = True
    app.session_state["playbook_selector"] = PLAYBOOK_AUTO if automatic else "period_comparison"
    app.session_state["guided_advice"] = {"effective_method": {"id": "period_comparison"}}
    app.session_state[key] = "orders"
    app.run()
    app.run()
    assert not app.exception
    assert not app.text_input(key=key).proto.set_value
    app.segmented_control(key="workbench_page").set_value("history").run()
    assert app.session_state[key] == "orders"
    app.run()
    app.segmented_control(key="workbench_page").set_value("workbench").run()
    assert not app.exception
    assert app.text_input(key=key).value == "orders"
    app.run()
    assert not app.text_input(key=key).proto.set_value
    app.session_state["guided_advanced"] = False
    app.run()
    assert app.session_state[key] == "orders"
