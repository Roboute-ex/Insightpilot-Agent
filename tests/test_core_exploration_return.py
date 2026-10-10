"""Keep the form mounted while viewing another immutable run.

AppTest verifies page/widget identity, not browser-only pending form values;
the real browser workflow checks those values without submitting the form.
"""
from copy import deepcopy

import pytest

from app.session_data import AnalysisSession
from test_core_workflow_navigation import _add, _config, _metadata_snapshot, _press, _body, _result


def _session(*, retain_parent=False):
    session = AnalysisSession()
    parent_config = _config()
    from test_core_result_focus import _result as diagnostic_result
    parent_result = diagnostic_result()
    parent_result["run_manifest"]["run_id"] = "parent-diagnosis"
    parent_result["column_mapping"] = deepcopy(parent_config["column_mapping"])
    parent = session.history.add(parent_result, parent_config, dataset_id="navigation-data",
        revision="1", schema={"orders": ["date", "orders", "city"]})
    child_config = _config("西城当日探索", city="西城")
    child_config["parameters"]["exploration_request"] = {"kind": "grouped",
        "row_dimension": "city", "filters": [{"column": "city", "operator": "eq", "value": "西城"}]}
    child = _add(session.history, "child-exploration", parent=parent.run_id, config=child_config)
    child_result = _result(child.run_id, config=child_config)
    child_result["analysis_result_package"]["metadata"] = {"exploration": {"kind": "grouped"}}
    session.accept("retained", parent_result if retain_parent else child_result)
    return session, parent, child


def _app(monkeypatch, session, snapshot=None):
    from streamlit.testing.v1 import AppTest
    import app.components.data_source_panel as sources
    snapshot = snapshot or _metadata_snapshot()
    # Supply the same read-only metadata used by the form and result guard.
    snapshot.metadata.setdefault("orders", {"columns": ["date", "orders", "city"]})
    facts = snapshot.metadata["orders"].setdefault("readiness_summary", {}).setdefault("columns", {})
    facts["orders"] = {"valid_numeric_count": 4}
    facts["date"] = {"valid_date_count": 4}
    monkeypatch.setattr(sources, "current_dataset", lambda: snapshot)
    app = AppTest.from_string('''
import streamlit as st
from app.components.exploration_panel import render_exploration_panel
from app.components.guidance_panel import initialize_guidance
from app.components.history_panel import apply_pending_branch
initialize_guidance()
apply_pending_branch()
page = st.segmented_control("页面", ["workbench", "explore"], key="workbench_page")
if page == "explore":
    render_exploration_panel(st.session_state["fixture_snapshot"], st.session_state["fixture_session"])
else:
    st.text_input("问题草稿", key="question")
''')
    app.session_state["fixture_session"] = session
    app.session_state["fixture_snapshot"] = snapshot
    app.session_state["workbench_page"] = "explore"
    app.session_state["exploration_dataset"] = (snapshot.dataset_id, str(snapshot.revision))
    app.session_state["exploration_section"] = "grouped"
    app.session_state["exploration_unit"] = "服务器已提交的旧单位"
    app.session_state["question"] = "已有问题草稿"
    app.run()
    assert not app.exception
    return app


@pytest.mark.parametrize("navigation", ["parent", "ancestor"])
def test_return_and_cancel_keep_exploration_form_until_confirmed_restore(monkeypatch, navigation):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    session, parent, child = _session()
    app = _app(monkeypatch, session)
    before = counts.copy()
    field_id = app.text_input(key="exploration_unit").proto.id
    frozen = parent.config
    _press(app, "core_return_parent" if navigation == "parent" else "core_ancestor_" + parent.node_id)
    assert app.session_state["workbench_page"] == "explore"
    assert app.text_input(key="exploration_unit").proto.id == field_id
    assert session.history.active_node_id == parent.node_id
    assert "历史摘要" in _body(app)
    assert not any(item.key == "result_tabs" for item in app.segmented_control)
    assert not any(str(item.key).startswith("generate_export_") for item in app.button)
    assert session.current["run_manifest"]["run_id"] == child.run_id

    _press(app, "core_restore_config")
    _press(app, "core_restore_cancel")
    assert app.session_state["workbench_page"] == "explore"
    assert app.text_input(key="exploration_unit").proto.id == field_id
    assert app.session_state["question"] == "已有问题草稿"
    _press(app, "core_restore_config")
    _press(app, "core_restore_confirm")
    assert app.session_state["workbench_page"] == "workbench"
    assert app.text_input(key="question").value == parent.config["question"]
    assert parent.config == frozen and len(session.history.nodes) == 2
    assert_no_work_since(counts, before)


def test_retained_parent_renders_its_generic_diagnosis_under_same_exploration_form(monkeypatch):
    session, parent, child = _session(retain_parent=True)
    app = _app(monkeypatch, session)
    field_id = app.text_input(key="exploration_unit").proto.id
    _press(app, "core_return_parent")
    assert session.history.active_node_id == parent.node_id
    assert app.session_state["workbench_page"] == "explore"
    assert app.text_input(key="exploration_unit").proto.id == field_id
    headings = [item.value for item in app.subheader]
    assert "已生成分析结果" not in headings and "已生成探索结果" not in headings
    assert [title for title in headings if title in {"发生了什么", "变化集中在哪里", "证据支持到哪一步", "下一步"}] == [
        "发生了什么", "变化集中在哪里", "证据支持到哪一步", "下一步"]
    assert app.segmented_control(key="result_tabs").value == "分析概览"
    assert "当前值：70" in _body(app)
    assert child.run_id not in _body(app)
    assert session.history.result_available(parent, session.current)


@pytest.mark.parametrize("invalid", ["dataset", "revision", "source"])
def test_exploration_parent_result_does_not_bypass_source_and_revision_guards(monkeypatch, invalid):
    session, parent, _ = _session(retain_parent=True)
    snapshot = _metadata_snapshot()
    if invalid == "dataset":
        snapshot.dataset_id = "another-data"
    elif invalid == "revision":
        snapshot.revision = "2"
    app = _app(monkeypatch, session, snapshot)
    if invalid == "source":
        # Keep the form's table available while removing this run's frozen table.
        snapshot.metadata["other"] = snapshot.metadata.pop("orders")
    _press(app, "core_return_parent")
    assert app.session_state["workbench_page"] == "explore"
    assert session.history.active_node_id == parent.node_id
    assert "历史摘要" in _body(app) and "数据版本或源表不一致" in _body(app)
    assert not any(item.key == "result_tabs" for item in app.segmented_control)
    assert not any(str(item.key).startswith(("overview_", "generate_export_")) for item in app.button)
