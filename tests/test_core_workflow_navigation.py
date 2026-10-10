"""Selected-run navigation, explicit restoration and late-result ownership.

Small component fixtures exercise the one-result memory boundary. Full-app
tests below use actual controls and execution; they do not inject run results.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.session_data import AnalysisSession
from insightpilot.analysis.threads import AnalysisThread


def _config(question="整体订单诊断", *, city=None, outcome="orders"):
    filters = [] if city is None else [{"column": "city", "operator": "eq", "value": city}]
    return {
        "question": question, "goal_mode": "metric_diagnosis",
        "playbook_id": "period_comparison", "effective_playbook_id": "period_comparison",
        "column_mapping": {
            "table_name": "orders", "date_column": "date", "metric_columns": ["orders"],
            "dimension_columns": ["city"], "outcome_column": outcome,
            "group_column": None, "treatment_column": None, "covariates": [],
            "aggregation": "sum", "time_grain": "day", "source": "user_selected",
        },
        "parameters": {"target_date": "2026-09-03", "filters": filters, "aggregation": "sum"},
        "dataset_id": "navigation-data", "dataset_revision": "1",
        "selection_source": "user_selected", "use_langgraph": False,
        "data_source_type": "synthetic",
    }


def _result(run_id, value=120.0, *, config=None):
    config = config or _config()
    return {
        "execution_status": "COMPLETED", "execution_mode": "execute",
        "goal_mode": config["goal_mode"], "summary": f"{config['question']}：订单量 {value:g} 单。",
        "run_manifest": {"run_id": run_id, "created_at": "2026-09-04T00:00:00Z"},
        "column_mapping": deepcopy(config["column_mapping"]),
        "metric_definitions": [{"metric_id": "orders", "display_name": "订单量", "unit": "单",
            "aggregation": "sum", "statistical_unit": "支付订单", "definition_status": "user_confirmed"}],
        "analysis_result_package": {"metric_comparisons": [{"metric_id": "orders", "current_value": value,
            "unit": "单", "current_period": "2026-09-03", "baseline_period": "前 7 日均值"}]},
        "result_tables": {},
    }


def _add(history, run_id, *, parent=None, config=None, activate=True):
    config = config or _config()
    request = history.begin_request(parent)
    return history.add(_result(run_id, config=config), config,
        dataset_id="navigation-data", revision="1", schema={"orders": ["date", "orders", "city"]},
        node_id=request, activate=activate)


def _metadata_snapshot(*, dataset_id="navigation-data", revision="1"):
    return SimpleNamespace(dataset_id=dataset_id, revision=revision, source_type="synthetic",
        metadata={"orders": {"columns": ["date", "orders", "city"], "readiness_summary": {
            "columns": {"date": {"date_min": "2026-08-01", "date_max": "2026-09-03"}}}}})


def test_browsing_parent_keeps_submitted_request_and_accepts_late_child_without_stealing_view():
    history = AnalysisThread()
    parent = _add(history, "parent")
    child = _add(history, "child", parent=parent.run_id, config=_config("西城当日探索", city="西城"))
    request = history.begin_request(child.run_id)
    frozen_parent = parent.config
    history.select(parent.node_id, cancel_request=False)
    assert history.request_node_id == request
    assert history.parent_run_id == child.run_id

    late = history.add(_result("late-child"), _config("更深一层探索"),
        dataset_id="navigation-data", revision="1", schema={"orders": ["date", "orders", "city"]},
        node_id=request, activate=False)
    assert late.parent_run_id == child.run_id
    assert history.active_node_id == parent.node_id
    assert history.request_node_id is None
    assert parent.config == frozen_parent
    assert len(history.nodes) == 3
    assert not history.result_available(parent, _result("late-child"))
    assert history.result_available(late, _result("late-child"))


def test_cached_late_run_does_not_override_explicit_history_selection():
    history = AnalysisThread()
    parent = _add(history, "parent")
    child = _add(history, "child", parent=parent.run_id)
    history.select(parent.node_id, cancel_request=False)
    same = history.add(_result("child"), child.config, dataset_id="navigation-data", revision="1",
        schema={"orders": ["date", "orders", "city"]}, activate=False)
    assert same.node_id == child.node_id
    assert history.active_node_id == parent.node_id
    assert len(history.nodes) == 2


def test_stale_request_cannot_replay_an_existing_run_and_clear_the_current_request():
    history = AnalysisThread()
    node = _add(history, "recorded")
    old_request = history.begin_request(node.run_id)
    current_request = history.begin_request(node.run_id)
    with pytest.raises(ValueError):
        history.add(_result(node.run_id), node.config, dataset_id="navigation-data", revision="1",
            schema={"orders": ["date", "orders", "city"]}, node_id=old_request)
    assert history.request_node_id == current_request
    assert history.active_node_id == node.node_id and len(history.nodes) == 1


def test_preserving_old_summary_on_data_change_revokes_pending_request_and_result_reference():
    history = AnalysisThread()
    parent = _add(history, "parent")
    old_request = history.begin_request(parent.run_id)
    before = parent.config, parent.summary, history.thread_id
    history.bind_dataset("navigation-data", "2", preserve_history=True)
    assert history.get(parent.node_id) is parent
    assert (parent.config, parent.summary, history.thread_id) == before
    assert history.request_node_id is None and history.parent_run_id is None
    assert not history.result_available(parent, _result("parent"))
    with pytest.raises(ValueError):
        history.add(_result("stale"), _config(), dataset_id="navigation-data", revision="2",
            schema={"orders": ["date", "orders", "city"]}, node_id=old_request)


def test_view_selection_rejects_forged_expired_and_cross_session_ids_without_touching_request():
    history = AnalysisThread(max_nodes=2)
    expired = _add(history, "expired")
    parent = _add(history, "parent")
    current = _add(history, "current", parent=parent.run_id)
    foreign = _add(AnalysisThread(), "foreign")
    request = history.begin_request(current.run_id)
    for invalid in ("forged-client-node", expired.node_id, foreign.node_id):
        with pytest.raises(ValueError):
            history.select(invalid, cancel_request=False)
        assert history.active_node_id == current.node_id
        assert history.request_node_id == request
    assert len(history.nodes) == 2 and history.size_bytes <= history.max_bytes


def test_current_session_owns_one_result_and_history_stays_within_existing_budget():
    session = AnalysisSession()
    parent = _add(session.history, "parent")
    session.accept("parent", _result("parent"))
    assert session.history.result_available(parent, session.current)
    child = _add(session.history, "child", parent=parent.run_id)
    session.accept("child", _result("child"))
    assert not session.history.result_available(parent, session.current)
    assert session.history.result_available(child, session.current)
    assert session.cache.max_entries == 1
    assert session.cache.max_bytes + session.history.max_bytes == session.config.result_max_bytes
    assert all(isinstance(node.result_summary, str) and isinstance(node.result_ref, str)
        for node in session.history.nodes)


def _project(history, node, snapshot=None):
    from app.components.analysis_context import project_run_context
    return project_run_context(history, node.node_id, snapshot)


def test_root_and_siblings_follow_parent_identity_instead_of_recent_order_or_city_name():
    history = AnalysisThread()
    root = _add(history, "root")
    west = _add(history, "west", parent=root.run_id, config=_config("同名探索", city="西城"))
    east = _add(history, "east", parent=root.run_id, config=_config("同名探索", city="东城"))
    projected_root = _project(history, root)
    assert [item["node_id"] for item in projected_root["breadcrumbs"]] == [root.node_id]
    assert projected_root["parent_node_id"] is None and not projected_root["boundary"]
    for child in (west, east):
        projected = _project(history, child)
        assert [item["run_id"] for item in projected["breadcrumbs"]] == [root.run_id, child.run_id]
        assert [item["current"] for item in projected["breadcrumbs"]] == [False, True]
        assert projected["parent_node_id"] == root.node_id
        assert projected["run_id"] == child.run_id


def test_projection_reads_frozen_scope_and_actual_date_without_source_tables():
    history = AnalysisThread()
    config = _config("昨日订单量为什么下降？", city="西城")
    node = _add(history, "dated", config=config)
    # Mutating the caller's editable draft cannot change the committed scope.
    config["parameters"]["target_date"] = "2099-01-01"
    config["parameters"]["filters"][0]["value"] = "东城"
    config["column_mapping"]["table_name"] = "private_alternate"
    view = _project(history, node, _metadata_snapshot())
    shown = " ".join(view["scope_lines"])
    assert "2026-09-03" in shown and "西城" in shown and "orders" in shown
    assert "2099-01-01" not in shown and "东城" not in shown and "private_alternate" not in shown
    assert view["data_matches"] is True and view["source_available"] is True
    assert view["method_label"]


def test_relative_period_retains_computed_target_date_after_source_changes():
    history = AnalysisThread()
    config = _config("昨日订单量为什么下降？")
    config["parameters"] = {}
    result = _result("computed-date", config=config)
    result["analysis_result_package"]["metric_comparisons"][0]["current_period"] = "昨日"
    result["analysis_result_package"]["anomalies"] = [{"metric_id": "orders", "date": "2026-06-30"}]
    node = history.add(result, config, dataset_id="navigation-data", revision="1", schema={})
    result["analysis_result_package"]["anomalies"][0]["date"] = "2099-01-01"
    view = _project(history, node, _metadata_snapshot(revision="2"))
    text = " ".join(view["scope_lines"])
    assert "目标日 2026-06-30" in text and "前 7 日均值" in text
    assert "2099-01-01" not in text and "2026-09-03" not in text
    assert view["data_matches"] is False


def test_ten_node_pruning_and_orphan_path_keep_direct_parent_reachable():
    history = AnalysisThread()
    parent = None
    for index in range(12):
        parent = _add(history, f"run-{index}", parent=parent.run_id if parent else None)
    assert len(history.nodes) == 10
    earliest = _project(history, history.nodes[0])
    assert earliest["boundary"] and earliest["parent_node_id"] is None
    newest = _project(history, history.nodes[-1])
    assert newest["parent_node_id"] == history.nodes[-2].node_id
    assert newest["boundary"]
    assert newest["breadcrumbs"][-1]["node_id"] == history.nodes[-1].node_id
    assert history.nodes[-2].node_id in [item["node_id"] for item in newest["breadcrumbs"]]
    assert len(newest["breadcrumbs"]) <= 10


def test_corrupt_parent_cycle_is_bounded_and_announced():
    history = AnalysisThread()
    root = _add(history, "root")
    child = _add(history, "child", parent=root.run_id)
    history.nodes[0] = replace(root, parent_run_id=child.run_id)
    view = _project(history, child)
    assert view["boundary"]
    ids = [item["node_id"] for item in view["breadcrumbs"]]
    assert len(ids) <= len(history.nodes) and len(ids) == len(set(ids))
    assert ids[-1] == child.node_id


@pytest.mark.parametrize("snapshot,expected_matches,expected_source", [
    (None, None, None),
    (_metadata_snapshot(revision="2"), False, True),
    (_metadata_snapshot(dataset_id="another-session"), False, True),
    (SimpleNamespace(dataset_id="navigation-data", revision="1", metadata={}), True, False),
])
def test_projection_distinguishes_changed_data_missing_source_and_missing_snapshot(snapshot, expected_matches, expected_source):
    history = AnalysisThread()
    node = _add(history, "root")
    view = _project(history, node, snapshot)
    assert view["data_matches"] is expected_matches
    assert view["source_available"] is expected_source
    assert node.summary["rows"][0]["value"] == 120


def test_projection_rejects_unknown_and_cross_session_node_ids():
    from app.components.analysis_context import project_run_context
    history = AnalysisThread()
    _add(history, "local")
    foreign = _add(AnalysisThread(), "foreign")
    for node_id in ("fabricated", foreign.node_id):
        with pytest.raises(ValueError):
            project_run_context(history, node_id, _metadata_snapshot())


def _body(app):
    return "\n".join(str(item.value) for kind in ("markdown", "caption", "info", "warning", "success")
        for item in getattr(app, kind))


def _press(app, key):
    app.button(key=key).click().run()
    assert not app.exception


def _open_history_restore(app):
    app.segmented_control(key="workbench_page").set_value("history").run()
    assert not app.exception
    _press(app, "history_restore")


def test_real_controls_restore_without_execution_keep_draft_and_return_without_child_exports(monkeypatch):
    import json
    from app.components.export_panel import export_cache_key
    from test_method_discovery_ui import start, watch, assert_no_work_since

    counts = watch(monkeypatch)
    app = start()
    _press(app, "guided_run")
    session = app.session_state["performance_result"]
    parent = session.history.nodes[-1]
    parent_config = parent.config
    parent_run = parent.run_id
    assert counts["analysis"] == 1 and counts["export"] == 0
    assert not any(item.key == "core_return_parent" for item in app.button)

    app.text_input(key="question").set_value("保留这份尚未提交的问题草稿").run()
    before = counts.copy()
    # Retained results use the existing history configuration action; released
    # results expose restoration beside the summary in the workbench itself.
    _open_history_restore(app)
    assert "草稿" in _body(app) and "未提交" in _body(app)
    _press(app, "core_restore_cancel")
    assert app.session_state["question"] == "保留这份尚未提交的问题草稿"
    assert_no_work_since(counts, before)
    assert parent.config == parent_config and len(session.history.nodes) == 1

    _open_history_restore(app)
    _press(app, "core_restore_confirm")
    assert app.text_input(key="question").value == parent_config["question"]
    assert app.button(key="guided_run").label == "重新运行该分析"
    assert_no_work_since(counts, before)
    assert len(session.history.nodes) == 1
    _press(app, "guided_run")
    child = session.history.nodes[-1]
    assert counts["analysis"] == before["analysis"] + 1
    assert child.run_id != parent_run and child.parent_run_id == parent_run
    assert parent.config == parent_config and len(session.history.nodes) == 2
    assert not session.history.result_available(parent, session.current)

    # Generate just the selected child's JSON; navigation must not surface it
    # as a parent's report or cause other formats to be prepared.
    app.segmented_control(key="result_tabs").set_value("报告导出").run()
    assert not app.exception
    _press(app, "generate_export_manifest")
    child_result = session.current
    cached = app.session_state["performance_export_cache"].get(export_cache_key(child_result, "manifest"))
    assert json.loads(cached)["run_id"] == child.run_id
    assert counts["export"] == 1
    before = counts.copy()
    _press(app, "core_return_parent")
    assert session.history.active_node_id == parent.node_id
    assert len(session.history.nodes) == 2 and parent.config == parent_config
    assert "历史摘要" in _body(app) and "完整结果已释放" in _body(app)
    assert not any(str(item.key).startswith("common_choose_") for item in app.button)
    assert not app.get("plotly_chart")
    assert not any(str(item.key).startswith(("generate_export_", "download_export_")) for item in app.button)
    assert not any(str(item.key).startswith("download_export_") for item in app.get("download_button"))
    assert_no_work_since(counts, before)

    _press(app, "core_restore_config")
    _press(app, "core_restore_confirm")
    assert_no_work_since(counts, before)
    _press(app, "guided_run")
    rerun = session.history.nodes[-1]
    assert counts["analysis"] == before["analysis"] + 1
    assert rerun.run_id not in {parent_run, child.run_id}
    assert rerun.parent_run_id == parent_run
    assert len(session.history.nodes) == 3 and parent.config == parent_config
    assert counts["export"] == before["export"]


def _context_component_app(session, snapshot):
    from streamlit.testing.v1 import AppTest
    # This fixture is intentionally a component test, not a browser/full-task
    # acceptance. It models the retained parent result without a second cache.
    app = AppTest.from_string("""
import streamlit as st
from app.components.analysis_context import render_analysis_context
from app.components.history_panel import apply_pending_branch
apply_pending_branch()
st.text_input("问题草稿", key="question")
render_analysis_context(st.session_state["fixture_session"], st.session_state["fixture_snapshot"])
""")
    app.session_state["fixture_session"] = session
    app.session_state["fixture_snapshot"] = snapshot
    app.session_state["question"] = "尚未提交的草稿"
    app.run()
    assert not app.exception
    return app


def test_return_to_retained_parent_is_view_only_and_excludes_sibling_path(monkeypatch):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    session = AnalysisSession()
    parent = _add(session.history, "parent")
    sibling = _add(session.history, "sibling", parent=parent.run_id, config=_config("东城探索", city="东城"))
    child = _add(session.history, "child", parent=parent.run_id, config=_config("西城探索", city="西城"))
    parent_result = _result("parent", 120)
    session.accept("parent", parent_result)
    request = session.history.begin_request(child.run_id)
    app = _context_component_app(session, _metadata_snapshot())
    assert "西城" in _body(app) and "东城" not in _body(app)
    assert not any(item.key == f"core_ancestor_{sibling.node_id}" for item in app.button)
    before = counts.copy()
    _press(app, "core_return_parent")
    assert session.history.active_node_id == parent.node_id
    assert session.history.request_node_id == request
    assert session.current is parent_result and session.history.result_available(parent, session.current)
    assert session.history.get(parent.node_id).summary["rows"][0]["value"] == 120
    assert not any(item.key == "core_return_parent" for item in app.button)
    assert app.text_input(key="question").value == "尚未提交的草稿"
    assert len(session.history.nodes) == 3
    assert_no_work_since(counts, before)


def test_restore_preserves_explicit_empty_outcome_and_revokes_old_approval(monkeypatch):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    config = _config(outcome=None)
    config.update(execution_mode="execute", approved_plan_id="old-plan", clarification_answers={"confirmed": True})
    session = AnalysisSession()
    node = _add(session.history, "root", config=config)
    app = _context_component_app(session, _metadata_snapshot())
    app.session_state["approve_old_plan"] = True
    app.session_state["performance_clarification_state"] = {"approved": True}
    app.session_state["mapping_outcome"] = "orders"
    before = counts.copy()
    _press(app, "core_restore_config")
    _press(app, "core_restore_confirm")
    from ui_session_support import session_snapshot
    state = session_snapshot(app)
    assert state["mapping_outcome"] == "不选择"
    assert state["guided_mapping"]["outcome_column"] is None
    assert state["mapping_group"] == "不选择" and state["mapping_treatment"] == "不选择"
    assert "approve_old_plan" not in state
    assert "performance_clarification_state" not in state
    assert state["performance_branch_parent"] == node.run_id
    assert len(session.history.nodes) == 1 and node.config == config
    assert_no_work_since(counts, before)


def test_restoring_idle_configuration_does_not_claim_a_task_was_cancelled(monkeypatch):
    import app.background_tasks as background
    calls = []
    monkeypatch.setattr(background, "background_enabled", lambda: True)
    monkeypatch.setattr(background, "task_snapshot", lambda: None)
    monkeypatch.setattr(background, "cancel_current", lambda **kwargs: calls.append(kwargs))
    session = AnalysisSession()
    _add(session.history, "idle-parent")
    app = _context_component_app(session, _metadata_snapshot())
    app.session_state["performance_task_status"] = "completed"
    _press(app, "core_restore_config")
    _press(app, "core_restore_confirm")
    assert calls == []
    assert app.session_state["performance_task_status"] == "completed"


def test_changed_data_restore_needs_explicit_application_to_current_data(monkeypatch):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    session = AnalysisSession()
    node = _add(session.history, "root")
    session.history.bind_dataset("navigation-data", "2", preserve_history=True)
    app = _context_component_app(session, _metadata_snapshot(revision="2"))
    before = counts.copy()
    _press(app, "core_restore_config")
    assert not app.checkbox(key="core_restore_current_data").value
    assert app.button(key="core_restore_confirm").disabled
    assert app.text_input(key="question").value == "尚未提交的草稿"
    # A forged client event cannot bypass the server-side version gate.
    app.button(key="core_restore_confirm").proto.disabled = False
    _press(app, "core_restore_confirm")
    assert app.text_input(key="question").value == "尚未提交的草稿"
    assert app.button(key="core_restore_confirm").disabled
    app.checkbox(key="core_restore_current_data").check().run()
    assert not app.exception
    _press(app, "core_restore_confirm")
    assert app.text_input(key="question").value == node.config["question"]
    assert app.session_state["guided_mapping"]["source"] == "automatic_suggestion"
    assert node.dataset_revision == "1" and len(session.history.nodes) == 1
    assert_no_work_since(counts, before)


@pytest.mark.parametrize("snapshot", [None,
    SimpleNamespace(dataset_id="navigation-data", revision="1", metadata={})])
def test_missing_source_or_expired_snapshot_keeps_restore_blocked_without_reading(snapshot, monkeypatch):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    session = AnalysisSession()
    _add(session.history, "root")
    app = _context_component_app(session, snapshot)
    before = counts.copy()
    _press(app, "core_restore_config")
    assert app.button(key="core_restore_confirm").disabled
    assert any("重新加载" in str(item.value) for item in app.error)
    app.button(key="core_restore_confirm").proto.disabled = False
    _press(app, "core_restore_confirm")
    assert app.text_input(key="question").value == "尚未提交的草稿"
    assert len(session.history.nodes) == 1
    assert_no_work_since(counts, before)


def test_missing_source_from_automatic_run_is_not_silently_remapped(monkeypatch):
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    session = AnalysisSession()
    config = _config()
    config.update(column_mapping=None, playbook_id=None, effective_playbook_id=None)
    result = _result("automatic-root", config=config)
    result["metric_definitions"][0]["table_name"] = "orders"
    node = session.history.add(result, config, dataset_id="navigation-data", revision="1",
        schema={"orders": ["date", "orders", "city"]})
    snapshot = SimpleNamespace(dataset_id="navigation-data", revision="2",
        metadata={"different_table": {"columns": ["date", "orders", "city"]}})
    app = _context_component_app(session, snapshot)
    before = counts.copy()
    _press(app, "core_restore_config")
    app.checkbox(key="core_restore_current_data").check().run()
    assert not app.exception
    assert app.button(key="core_restore_confirm").disabled
    assert any("重新加载" in str(item.value) for item in app.error)
    app.button(key="core_restore_confirm").proto.disabled = False
    _press(app, "core_restore_confirm")
    assert app.text_input(key="question").value == "尚未提交的草稿"
    assert node.config["column_mapping"] is None and len(session.history.nodes) == 1
    assert_no_work_since(counts, before)


def test_restore_prompt_uses_existing_secret_redaction_without_altering_frozen_question():
    session = AnalysisSession()
    config = _config("订单分析 password=private-test-secret")
    node = _add(session.history, "redacted", config=config)
    app = _context_component_app(session, _metadata_snapshot())
    _press(app, "core_restore_config")
    assert "private-test-secret" not in _body(app)
    assert node.config["question"] == config["question"]


@pytest.fixture
def core_task_manager(explicit_ui_synchronous_compatibility, monkeypatch):
    from insightpilot.performance_tasks import TaskManager
    import insightpilot.performance_tasks as tasks
    monkeypatch.delenv("INSIGHTPILOT_UI_SYNC")
    manager = TaskManager(max_workers=2, cleanup_interval_seconds=1)
    monkeypatch.setattr(tasks, "get_task_manager", lambda: manager)
    yield manager
    manager.close()


@pytest.mark.parametrize("late_status", ["COMPLETED", "FAILED", "PREVIEW"])
def test_late_background_child_keeps_returned_parent_and_never_exposes_child_report(core_task_manager, monkeypatch, late_status):
    import threading
    import app.components.data_source_panel as sources
    import insightpilot.agents.workflow as workflow
    from test_performance_background_ui import start_app, tiny_tables, settle, loaded
    from ui_session_support import session_snapshot

    monkeypatch.setattr(sources, "load_synthetic_tables", lambda *args, **kwargs: tiny_tables())
    gate, entered, calls = threading.Event(), threading.Event(), []

    def controlled_worker(question, *args, **kwargs):
        # Only the worker's arithmetic is replaced in this scheduling test.
        # The actual owner/request/revision transfer and UI callbacks run.
        calls.append(question)
        run = len(calls)
        if run == 3:
            entered.set()
            assert gate.wait(20), "test did not release its controlled worker"
        return {"execution_status": late_status if run == 3 else "COMPLETED", "execution_mode": "execute",
            "goal_mode": "metric_diagnosis", "summary": f"受控运行{run}的独有结论",
            "run_manifest": {"run_id": f"owned-run-{run}"}, "result_tables": {}}

    monkeypatch.setattr(workflow, "run_agent_analysis", controlled_worker)
    try:
        app = start_app()
        settle(app, lambda: loaded(app))
        _press(app, "guided_run")
        settle(app, lambda: len(app.session_state["performance_result"].history.nodes) == 1)
        session = app.session_state["performance_result"]
        parent = session.history.nodes[-1]
        _open_history_restore(app)
        _press(app, "core_restore_confirm")
        _press(app, "guided_run")
        settle(app, lambda: len(session.history.nodes) == 2)
        child = session.history.nodes[-1]
        assert child.parent_run_id == parent.run_id
        _open_history_restore(app)
        _press(app, "core_restore_confirm")
        _press(app, "guided_run")
        assert entered.wait(2)
        pending = dict(session_snapshot(app)["performance_background_pending"])
        request = session.history.request_node_id
        owner = app.session_state["_background_owner"]
        assert core_task_manager.snapshot(owner).status == "running"

        # A second click while the same frozen request is running is a no-op.
        _press(app, "guided_run")
        assert len(calls) == 3
        assert session_snapshot(app)["performance_background_pending"]["task_id"] == pending["task_id"]
        assert session.history.request_node_id == request
        _press(app, "core_return_parent")
        assert session.history.active_node_id == parent.node_id
        assert session.history.request_node_id == request
        assert core_task_manager.snapshot(owner).status == "running"
        assert "历史摘要" in _body(app)
        gate.set()
        settle(app, lambda: (session_snapshot(app).get("last_analysis_result") or {}).get("run_manifest", {}).get("run_id") == "owned-run-3")
        if late_status == "COMPLETED":
            late = session.history.nodes[-1]
            assert len(session.history.nodes) == 3
            assert late.parent_run_id == child.run_id and late.run_id == "owned-run-3"
        else:
            assert len(session.history.nodes) == 2
            assert session.history.nodes[-1].run_id == child.run_id
        assert session.history.active_node_id == parent.node_id
        assert "受控运行3的独有结论" not in _body(app)
        assert "受控运行1的独有结论" in _body(app)
        assert not any(item.key == "result_tabs" for item in app.segmented_control)
        assert not any(str(item.key).startswith("generate_export_") for item in app.button)
        assert not app.get("plotly_chart")
        assert len(calls) == 3 and core_task_manager.stats()["tasks"] == 0
    finally:
        gate.set()


def test_city_selection_rejects_foreign_session_stale_revision_and_forged_group():
    import pandas as pd
    from insightpilot.analysis.drilldown import city_candidates, validate_selection
    history = AnalysisThread()
    node = _add(history, "group-owner")
    result = _result(node.run_id)
    result["run_manifest"]["dataset_fingerprints"] = {"orders": "source-fingerprint"}
    result["result_tables"]["dimension_contributions"] = pd.DataFrame([
        {"dimension": "city", "dimension_value": "西城", "metric_id": "orders", "current_value": 40.0}])
    snapshot = _metadata_snapshot()
    snapshot.fingerprints = {"orders": "source-fingerprint"}
    snapshot.metadata["orders"]["readiness_summary"]["columns"]["city"] = {
        "values_complete": True, "values": ["西城"]}
    event = city_candidates(result, node, snapshot)[0]["payload"]
    assert validate_selection(event, result, node, snapshot) == event
    for key, value in (("group_key", "forged"), ("value", "东城"),
        ("dataset_id", "another-session"), ("dataset_revision", "2"),
        ("run_id", "another-run"), ("table_key", "another-table")):
        with pytest.raises(ValueError):
            validate_selection({**event, key: value}, result, node, snapshot)
    another = _metadata_snapshot(dataset_id="foreign-owner")
    another.fingerprints = dict(snapshot.fingerprints)
    another.metadata = deepcopy(snapshot.metadata)
    with pytest.raises(ValueError):
        validate_selection(event, result, node, another)
    assert city_candidates(result, node, another) == []
    with pytest.raises(ValueError):
        validate_selection({**event, "dataset_id": another.dataset_id}, result, node, another)
