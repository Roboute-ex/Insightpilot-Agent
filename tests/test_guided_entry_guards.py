"""Real asynchronous submission guards and shared UI/CLI/workflow preflight."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import functools
import json
from pathlib import Path
import sys
import time

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.errors import AppTestError

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.performance_tasks import TaskManager

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "ui_streamlit.py"


def _record(name, payload):
    directory = ROOT / "reports" / "guided"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _settle(app, predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.run()
        assert not app.exception
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("真实后台任务没有在验收期限内完成并被界面接收")


@pytest.fixture
def actual_manager(explicit_ui_synchronous_compatibility, monkeypatch):
    import insightpilot.performance_tasks as tasks
    monkeypatch.delenv("INSIGHTPILOT_UI_SYNC")
    manager = TaskManager(max_workers=2, cleanup_interval_seconds=1)
    monkeypatch.setattr(tasks, "get_task_manager", lambda: manager)
    yield manager
    manager.close()


def test_real_async_bad_method_never_submits_then_accept_and_start_runs_once(actual_manager, monkeypatch):
    import insightpilot.agents.workflow as workflow
    import app.components.export_panel as exports
    from insightpilot.tools.duckdb_engine import AnalyticsEngine

    counts = Counter({key: 0 for key in ("submit", "workflow", "sql", "bound_sql", "routed_statistics", "playbook_statistics", "experiment_statistics", "causal_statistics", "exports")})

    def watch(owner, attribute, key):
        original = getattr(owner, attribute)
        @functools.wraps(original)
        def counted(*args, **kwargs):
            counts[key] += 1
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, attribute, counted)

    watch(actual_manager, "submit", "submit")
    watch(workflow, "run_agent_analysis", "workflow")
    watch(AnalyticsEngine, "run_sql", "sql")
    watch(AnalyticsEngine, "run_parameterized_sql", "bound_sql")
    watch(workflow, "_run_routed_analysis", "routed_statistics")
    watch(workflow, "execute_playbook", "playbook_statistics")
    watch(workflow, "analyze_ab_test", "experiment_statistics")
    watch(workflow, "estimate_adjusted_effect", "causal_statistics")
    watch(exports, "prepare_export_payload", "exports")

    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["demo_scale"] = "standard"
    app.session_state["question"] = "昨日订单量为什么下降？"
    app.session_state["goal_mode_selector"] = "metric_diagnosis"
    app.session_state["playbook_selector"] = "causal_exploration"
    app.session_state["guided_selection_source"] = "user_selected"
    app.session_state["guided_parameters"] = {"control_value": "control", "treatment_value": "treatment"}
    app.run()
    assert not app.exception
    _settle(app, lambda: app.session_state.filtered_state.get("performance_dataset") is not None and app.session_state["performance_dataset"].current is not None and actual_manager.stats()["tasks"] == 0)
    loading = dict(counts)
    assert loading["submit"] == 1
    counts.subtract(counts.copy())
    stages = {}

    def assert_no_execution(name):
        stages[name] = dict(counts)
        assert all(value == 0 for value in counts.values()), stages[name]
        assert not app.session_state["performance_result"].history.nodes
        assert actual_manager.stats()["tasks"] == 0
        assert not app.exception

    assert app.button(key="guided_run").disabled
    assert "MISSING_TREATMENT_COLUMN" in str(app.session_state["guided_advice"]["blocking_issues"])
    assert_no_execution("loaded_blocked")
    app.text_input(key="question").set_value("昨日订单量为何下降？").run()
    app.text_input(key="question").set_value("昨日订单量为什么下降？").run()
    app.session_state["guided_advanced"] = True
    app.run()
    app.segmented_control(key="workbench_page").set_value("methods").run()
    app.segmented_control(key="workbench_page").set_value("workbench").run()
    assert_no_execution("question_changes_and_panels")
    # Normal AppTest, like a browser, rejects interacting with a disabled button.
    assert app.button(key="guided_run").disabled
    with pytest.raises(AppTestError, match="disabled"):
        app.button(key="guided_run").click()
    assert_no_execution("disabled_button_native_rejected")
    # Adversarial client event only: change the test's received client protobuf,
    # never application code or button SessionState, to send a forged click. The
    # real server renders disabled again and must still enforce shared preflight.
    app.button(key="guided_run").proto.disabled = False
    app.button(key="guided_run").click().run()
    assert app.button(key="guided_run").disabled
    assert_no_execution("forged_client_event_blocked")
    app.button(key="guided_use_recommendation").click().run()
    assert not app.button(key="guided_run").disabled
    assert_no_execution("accepted_recommendation_only")
    app.button(key="guided_run").click().run()
    _settle(app, lambda: isinstance(app.session_state.filtered_state.get("last_analysis_result"), dict) and actual_manager.stats()["tasks"] == 0)
    actual = app.session_state["last_analysis_result"]
    assert actual["execution_status"] == "COMPLETED"
    assert counts["submit"] == counts["workflow"] == 1
    assert counts["routed_statistics"] + counts["playbook_statistics"] >= 1
    assert counts["exports"] == 0
    assert len(app.session_state["performance_result"].history.nodes) == 1
    assert sum(len(table) for table in actual["result_tables"].values()) > 0
    stages["explicit_start_completed"] = dict(counts)
    _record("entry-guards-async.json", {"passed": True, "scale": "standard", "real_task_manager": True,
        "loading_counts_before_reset": loading, "stages": stages, "execution_status": actual["execution_status"],
        "result_tables": {name: len(table) for name, table in actual["result_tables"].items()},
        "manager_after_adoption": actual_manager.stats(), "test_ui_adapter": "Expander bool WidgetState bridge; native disabled click is rejected, and one adversarial client protobuf event is separately labelled. Analysis and workers run real code."})


def test_ui_cli_and_workflow_share_method_and_blocking_messages(monkeypatch, capsys, tmp_path):
    from insightpilot import cli
    from insightpilot.agents.workflow import run_agent_analysis
    from insightpilot.tools.duckdb_engine import AnalyticsEngine

    frame = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=16), "orders": list(range(16))})
    mapping = {"table_name": "daily", "date_column": "date", "metric_columns": ["orders"],
               "dimension_columns": [], "group_column": None, "treatment_column": None,
               "outcome_column": "orders", "time_grain": "day", "aggregation": "sum", "covariates": []}
    parameters = {"control_value": "control", "treatment_value": "treatment"}
    config = {"question": "昨日订单量为什么下降？", "goal_mode": "metric_diagnosis",
              "playbook_id": "causal_exploration", "column_mapping": mapping,
              "parameters": parameters, "selection_source": "user_selected"}
    dataset = PreparedDataset.from_tables({"daily": frame}, dataset_id="guided-ui-identity", revision="1")
    counts = Counter({"sql": 0, "bound_sql": 0})
    def forbidden(key):
        def fail(*args, **kwargs):
            counts[key] += 1
            raise AssertionError("被阻断请求不得执行分析SQL")
        return fail
    monkeypatch.setattr(AnalyticsEngine, "run_sql", forbidden("sql"))
    monkeypatch.setattr(AnalyticsEngine, "run_parameterized_sql", forbidden("bound_sql"))

    app = AppTest.from_string("""
import streamlit as st
from app.components.metric_definition_panel import prepare_and_render_clarification
prepared, _ = prepare_and_render_clarification(st.session_state['fixture_dataset'], st.session_state['fixture_config'], 'demo')
st.session_state['fixture_prepared'] = prepared
""")
    app.session_state["fixture_dataset"] = dataset
    app.session_state["fixture_config"] = deepcopy(config)
    app.run()
    assert not app.exception
    ui = app.session_state["fixture_prepared"]

    monkeypatch.setattr(cli, "_load_file_tables", lambda args: ({"daily": frame}, None, ""))
    monkeypatch.setattr(sys, "argv", ["insightpilot", "--data-source", "file", "--input-file", "unused.csv", "--table-name", "daily",
        "--date-column", "date", "--metric-columns", "orders", "--outcome-column", "orders", "--aggregation", "sum",
        "--question", config["question"], "--goal-mode", "metric_diagnosis", "--playbook", "causal_exploration",
        "--control-value", "control", "--treatment-value", "treatment", "--advise-only", "--output-format", "json", "--export-dir", str(tmp_path)])
    assert cli.main() == 0
    command_line = json.loads(capsys.readouterr().out)["runs"][0]
    workflow = run_agent_analysis(config["question"], {}, goal_mode="metric_diagnosis", playbook_id="causal_exploration",
        column_mapping=deepcopy(mapping), playbook_parameters=deepcopy(parameters), selection_source="user_selected",
        prepared_dataset=dataset, presentation_mode="deferred", data_source_type="csv")

    def contract(result):
        advice = result["analysis_advice"]
        return {"status": advice["status"], "can_submit": advice["can_submit"],
                "requested": advice["requested_method"]["method_ref"],
                "recommended": advice["recommended_method"]["method_ref"],
                "effective": advice["effective_method"]["method_ref"],
                "reasons": [{"code": item["code"], "message_zh": item["message_zh"], "related_fields": item["related_fields"]}
                            for item in advice["blocking_issues"]]}
    contracts = {name: contract(result) for name, result in (("ui", ui), ("cli", command_line), ("workflow", workflow))}
    assert contracts["ui"] == contracts["cli"] == contracts["workflow"]
    assert contracts["ui"]["status"] == "needs_clarification"
    assert {item["code"] for item in contracts["ui"]["reasons"]} == {"MISSING_TREATMENT_COLUMN", "METHOD_GOAL_MISMATCH"}
    assert command_line["execution_status"] == "NOT_STARTED" and workflow["execution_status"] == "NEEDS_INPUT"
    assert all(value == 0 for value in counts.values())
    fingerprints = {name: result["analysis_advice"]["request_fingerprint"] for name, result in (("ui", ui), ("cli", command_line), ("workflow", workflow))}
    assert fingerprints["ui"] == fingerprints["workflow"]
    assert fingerprints["ui"] != fingerprints["cli"]
    _record("entry-guards-three-interfaces.json", {"passed": True, "contracts": contracts, "sql_counts": dict(counts),
        "fingerprints": fingerprints, "identity_note": "UI/workflow share one dataset snapshot; CLI owns a separately prepared snapshot. Different dataset IDs intentionally give different fingerprints."})
