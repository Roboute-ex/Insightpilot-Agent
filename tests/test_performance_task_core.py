"""Real phase and cancellation boundaries; no performance timing assertions."""
from functools import wraps
from threading import Event
import time
from unittest.mock import Mock

import pandas as pd
import pytest

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.observability.tracer import LocalTracer, trace_stage, use_tracer
from insightpilot.performance_tasks import TaskCancelledError, TaskManager, cancellation_checkpoint


def table():
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=35), "sales": range(35), "city": ["A"] * 35})


def terminal(manager, owner="test-owner"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = manager.snapshot(owner)
        if snapshot is not None and snapshot.status not in {"queued", "running", "cancel_requested"}:
            return snapshot
        Event().wait(.005)
    pytest.fail("Worker did not reach a terminal state")


def test_prepared_stages_are_real_and_sync_context_is_noop(monkeypatch):
    import insightpilot.observability.tracer as tracer_module
    stages = []
    original = tracer_module.report_stage
    def report(name):
        stages.append(name)
        original(name)
    monkeypatch.setattr(tracer_module, "report_stage", report)
    with TaskManager() as manager:
        submitted = manager.submit("test-owner", "prepared", "1", lambda: PreparedDataset.from_tables({"t": table()}))
        assert terminal(manager).status == "completed"
        prepared = manager.take_result("test-owner", submitted.task_id, submitted.key, submitted.revision)
    names = {span["name"] for span in prepared.preparation_telemetry["spans"]}
    assert {"dataset_budget", "dataset_table_copy", "dataset_validation", "dataset_schema", "dataset_table_fingerprint"} <= names
    assert stages.index("dataset_table_copy") < stages.index("dataset_validation") < stages.index("dataset_schema") < stages.index("dataset_table_fingerprint")
    assert all(span["status"] == "completed" for span in prepared.preparation_telemetry["spans"])
    cancellation_checkpoint()
    with trace_stage("ordinary_cli_without_task"):
        assert table().sales.sum() == 595


def test_cancel_after_snapshot_copy_stops_before_profile_and_hash(monkeypatch):
    import insightpilot.agents.dataset as dataset
    entered, release = Event(), Event()
    owned_copy = dataset._owned_copy
    def gated_copy(frame):
        copied = owned_copy(frame)
        entered.set()
        assert release.wait(5)
        return copied
    monkeypatch.setattr(dataset, "_owned_copy", gated_copy)
    profile = Mock(wraps=dataset.infer_schema_mapping)
    fingerprint = Mock(wraps=dataset.fingerprint_dataframe)
    monkeypatch.setattr(dataset, "infer_schema_mapping", profile)
    monkeypatch.setattr(dataset, "fingerprint_dataframe", fingerprint)
    with TaskManager() as manager:
        submitted = manager.submit("test-owner", "copy-cancel", "1", lambda: PreparedDataset.from_tables({"t": table()}))
        try:
            assert entered.wait(5)
            assert manager.snapshot("test-owner").phase == "dataset_table_copy"
            assert manager.cancel("test-owner").status == "cancel_requested"
        finally:
            release.set()
        assert terminal(manager).status == "cancelled"
        assert profile.call_count == fingerprint.call_count == 0
        with pytest.raises(TaskCancelledError):
            manager.take_result("test-owner", submitted.task_id, submitted.key, submitted.revision)


def test_nested_cancel_span_is_marked_cancelled_not_completed():
    entered, release = Event(), Event()
    tracer = LocalTracer()
    def work():
        with use_tracer(tracer), trace_stage("parent"):
            with trace_stage("native_step"):
                entered.set()
                assert release.wait(5)
        return "must not complete"
    with TaskManager() as manager:
        manager.submit("test-owner", "trace-cancel", "1", work)
        try:
            assert entered.wait(5)
            assert manager.snapshot("test-owner").phase == "native_step"
            manager.cancel("test-owner")
        finally:
            release.set()
        assert terminal(manager).status == "cancelled"
    assert [span.status for span in tracer.spans] == ["cancelled", "cancelled"]
    assert tracer._stack == [] and tracer._starts == {}
    assert tracer.spans[1].parent_span_id == tracer.spans[0].span_id


def test_cancel_at_connection_construction_exit_closes_unowned_connection(monkeypatch):
    import insightpilot.tools.duckdb_engine as db
    entered, release = Event(), Event()
    original = db.duckdb.connect
    connections, closed = [], []
    class Proxy:
        def __init__(self, connection): self.connection = connection
        def close(self):
            closed.append(self.connection)
            self.connection.close()
        def __getattr__(self, name): return getattr(self.connection, name)
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connections.append(connection)
        entered.set()
        assert release.wait(5)
        return Proxy(connection)
    monkeypatch.setattr(db.duckdb, "connect", connect)
    with TaskManager() as manager:
        manager.submit("test-owner", "constructor-cancel", "1", db.AnalyticsEngine)
        try:
            assert entered.wait(5)
            assert manager.snapshot("test-owner").phase == "database_connection"
            assert manager.cancel("test-owner").status == "cancel_requested"
            assert closed == []
        finally:
            release.set()
        assert terminal(manager).status == "cancelled"
    assert closed == connections and len(closed) == 1
    with pytest.raises(Exception):
        connections[0].execute("SELECT 1")


def test_workflow_cancel_waits_for_sql_boundary_and_finally_closes(monkeypatch):
    import insightpilot.tools.duckdb_engine as db
    from insightpilot.data.scenarios import generate_scenario
    tables = generate_scenario("transaction", scale="small", seed=42).tables
    entered, release = Event(), Event()
    original = db.duckdb.connect
    closed, interrupted = [], []
    class Proxy:
        def __init__(self, connection): self.connection = connection
        def execute(self, *args, **kwargs):
            cursor = self.connection.execute(*args, **kwargs)
            entered.set()
            assert release.wait(5)
            return cursor
        def close(self):
            closed.append(self.connection)
            self.connection.close()
        def interrupt(self):
            interrupted.append(True)
            self.connection.interrupt()
        def __getattr__(self, name): return getattr(self.connection, name)
    monkeypatch.setattr(db.duckdb, "connect", lambda *a, **kw: Proxy(original(*a, **kw)))
    def work():
        return run_agent_analysis("orders", tables, goal_mode="metric_diagnosis", presentation_mode="deferred")
    with TaskManager() as manager:
        submitted = manager.submit("test-owner", "sql-cancel", "1", work)
        try:
            assert entered.wait(5)
            assert manager.snapshot("test-owner").phase == "sql_query"
            assert manager.cancel("test-owner").status == "cancel_requested"
            assert closed == [] and interrupted == []
        finally:
            release.set()
        assert terminal(manager).status == "cancelled"
        with pytest.raises(TaskCancelledError):
            manager.take_result("test-owner", submitted.task_id, submitted.key, submitted.revision)
    assert len(closed) == 1 and interrupted == []


def test_completed_workflow_phases_include_report_and_result_is_unchanged(monkeypatch):
    import insightpilot.observability.tracer as tracer_module
    phases = []
    report = tracer_module.report_stage
    monkeypatch.setattr(tracer_module, "report_stage", lambda name: (phases.append(name), report(name))[-1])
    config = dict(question="trend", tables={"t": table()}, goal_mode="growth_trend", data_source_type="uploaded_files", column_mapping={"table_name": "t", "date_column": "date", "metric_columns": ["sales"]}, presentation_mode="deferred")
    synchronous = run_agent_analysis(**config)
    phases.clear()
    with TaskManager() as manager:
        submitted = manager.submit("test-owner", "analysis", "1", lambda: run_agent_analysis(**config))
        assert terminal(manager).status == "completed"
        result = manager.take_result("test-owner", submitted.task_id, submitted.key, submitted.revision)
    assert {"load_data_source", "run_routed_analysis", "statistics_result_package", "result_quality_scan", "build_governance", "build_manifest", "review", "generate_report:completed"} <= set(phases)
    for name, frame in synchronous["result_tables"].items():
        pd.testing.assert_frame_equal(frame, result["result_tables"][name])


def test_real_langgraph_propagates_worker_context_and_cancellation(monkeypatch):
    pytest.importorskip("langgraph.graph")
    import insightpilot.agents.langgraph_workflow as graph
    entered, release = Event(), Event()
    original = graph._load_data_source_node
    @wraps(original)
    def gate(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(graph, "_load_data_source_node", gate)
    def work():
        return run_agent_analysis("trend", {"t": table()}, goal_mode="growth_trend", use_langgraph=True, presentation_mode="deferred")
    with TaskManager() as manager:
        manager.submit("test-owner", "langgraph-cancel", "1", work)
        try:
            assert entered.wait(5)
            assert manager.snapshot("test-owner").phase == "load_data_source_node"
            manager.cancel("test-owner")
        finally:
            release.set()
        assert terminal(manager).status == "cancelled"
