"""Actual bounded worker integration. These tests explicitly disable sync compatibility."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import threading
import time

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.runtime.scriptrunner import get_script_run_ctx
from insightpilot.performance_tasks import TaskManager, report_stage

APP = Path(__file__).resolve().parents[1] / "app/ui_streamlit.py"


@pytest.fixture
def async_mode(explicit_ui_synchronous_compatibility, monkeypatch):
    monkeypatch.delenv("INSIGHTPILOT_UI_SYNC")
    import insightpilot.performance_tasks as tasks
    manager = TaskManager(max_workers=2, cleanup_interval_seconds=1)
    monkeypatch.setattr(tasks, "get_task_manager", lambda: manager)
    yield manager
    manager.close()


def tiny_tables(value=1):
    return {"daily_metrics": pd.DataFrame({"date": pd.date_range("2026-01-01", periods=4), "orders": [value]*4, "visitors": [10]*4})}


def start_app():
    app = AppTest.from_file(str(APP), default_timeout=15)
    app.session_state["demo_scale"] = "small"
    app.session_state["guided_data_settings"] = True
    # This suite isolates scheduling. Explicit fixture mapping satisfies the new
    # definition gate; it does not bypass SQL or worker ownership checks.
    app.session_state["performance_branch_mapping"] = {"table_name":"daily_metrics", "date_column":"date",
        "metric_columns":["orders"], "dimension_columns":[], "aggregation":"sum", "source":"user_selected"}
    return app.run()


def click(app, label):
    next(item for item in app.button if item.label == label).click().run()
    assert not app.exception


def settle(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.run()
        assert not app.exception
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Background result was not adopted before the test deadline")


def loaded(app):
    session = app.session_state.filtered_state.get("performance_dataset")
    return session is not None and session.current is not None


def dummy_result(call=1):
    return {"execution_status": "COMPLETED", "execution_mode": "execute", "summary": "实际后台测试结果", "run_manifest": {"run_id": f"async-{call}"}}


def test_background_source_returns_before_worker_and_deduplicates(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    gate = threading.Event(); entered = threading.Event(); calls = Counter()
    def load(*args):
        assert get_script_run_ctx(suppress_warning=True) is None
        calls["load"] += 1; entered.set(); report_stage("data_loading")
        gate.wait(5)
        return tiny_tables()
    monkeypatch.setattr(source, "load_synthetic_tables", load)
    try:
        started=time.monotonic(); app=start_app()
        assert time.monotonic()-started < 2 and entered.wait(1)
        assert not loaded(app) and not any(x.label=="开始分析" for x in app.button)
        assert any("当前任务" in str(x.value) for x in app.caption)
        app.session_state["guided_advanced"] = True; app.run()
        assert calls["load"]==1 and not loaded(app)
        gate.set(); settle(app,lambda:loaded(app))
        assert app.session_state["performance_dataset"].current.revision=="1"
        assert calls["load"]==1 and async_mode.stats()["tasks"]==0
    finally:
        gate.set()


def test_source_switch_during_native_stage_restarts_only_latest_selection(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    gate=threading.Event(); entered=threading.Event(); calls=[]
    def load(dataset,scale,seed):
        calls.append(scale)
        if scale=="large": entered.set(); gate.wait(5)
        return tiny_tables(100 if scale=="large" else 1)
    monkeypatch.setattr(source,"load_synthetic_tables",load)
    try:
        app=start_app(); settle(app,lambda:loaded(app))
        app.selectbox(key="demo_scale").set_value("large").run()
        assert entered.wait(1)
        app.selectbox(key="demo_scale").set_value("small").run()
        assert not loaded(app) and async_mode.snapshot(app.session_state["_background_owner"]).status=="cancel_requested"
        gate.set(); settle(app,lambda:loaded(app))
        snapshot=app.session_state["performance_dataset"].current
        assert snapshot.source_key[2]=="small" and snapshot.tables["daily_metrics"]["orders"].tolist()==[1]*4
        assert calls==["small","large","small"] and async_mode.stats()["tasks"]==0
    finally:
        gate.set()


def test_async_analysis_config_change_cancels_stale_result_and_retries(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    import insightpilot.agents.workflow as workflow
    monkeypatch.setattr(source,"load_synthetic_tables",lambda *args:tiny_tables())
    gate=threading.Event(); entered=threading.Event(); calls=[]
    def run(question,*args,**kwargs):
        assert get_script_run_ctx(suppress_warning=True) is None
        calls.append(question)
        if len(calls)==1: entered.set(); gate.wait(5)
        return dummy_result(len(calls))
    monkeypatch.setattr(workflow,"run_agent_analysis",run)
    try:
        app=start_app(); settle(app,lambda:loaded(app))
        started=time.monotonic(); click(app,"开始分析")
        assert time.monotonic()-started<2 and entered.wait(1)
        click(app,"开始分析")
        assert len(calls)==1
        app.text_input(key="question").set_value("订单量有何变化？").run()
        assert app.session_state.filtered_state.get("last_analysis_result") is None
        assert async_mode.snapshot(app.session_state["_background_owner"]).status=="cancel_requested"
        click(app,"开始分析")
        assert any("本次新分析未提交" in str(x.value) for x in app.warning)
        click(app,"开始分析")
        assert len(calls)==1 and "performance_background_pending" not in app.session_state.filtered_state
        gate.set(); settle(app,lambda:async_mode.stats()["tasks"]==0)
        assert app.session_state.filtered_state.get("last_analysis_result") is None
        click(app,"开始分析")
        settle(app,lambda:app.session_state.filtered_state.get("last_analysis_result") is not None)
        assert len(calls)==2 and app.session_state["last_run_context"]["question"]=="订单量有何变化？"
        click(app,"开始分析")
        assert len(calls)==2 and app.session_state["performance_analysis_cache_hit"] is True
    finally:
        gate.set()


def test_release_requests_cancel_without_claiming_native_worker_stopped(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    gate=threading.Event(); entered=threading.Event()
    def load(*args): entered.set(); gate.wait(5); return tiny_tables()
    monkeypatch.setattr(source,"load_synthetic_tables",load)
    try:
        app=start_app(); assert entered.wait(1)
        owner=app.session_state["_background_owner"]
        click(app,"释放本会话数据与结果")
        assert async_mode.snapshot(owner).status=="cancel_requested"
        assert any("仍持有必要数据" in str(x.value) for x in app.info)
        assert "performance_dataset" not in app.session_state.filtered_state
        gate.set(); settle(app,lambda:async_mode.stats()["tasks"]==0)
        assert app.session_state["performance_released"] is True
        assert not loaded(app)
    finally:
        gate.set()


def test_async_failure_is_visible_and_explicit_retry_runs_again(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    import insightpilot.agents.workflow as workflow
    monkeypatch.setattr(source,"load_synthetic_tables",lambda *args:tiny_tables())
    calls=[]
    def run(*args,**kwargs):
        calls.append(1)
        if len(calls)==1: raise RuntimeError("synthetic failure")
        return dummy_result(2)
    monkeypatch.setattr(workflow,"run_agent_analysis",run)
    app=start_app(); settle(app,lambda:loaded(app))
    click(app,"开始分析")
    settle(app,lambda:bool(app.error))
    assert len(calls)==1 and app.session_state.filtered_state.get("last_analysis_result") is None
    click(app,"开始分析")
    settle(app,lambda:app.session_state.filtered_state.get("last_analysis_result") is not None)
    assert len(calls)==2


def test_completed_old_analysis_is_not_adopted_after_configuration_change(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    import insightpilot.agents.workflow as workflow
    monkeypatch.setattr(source,"load_synthetic_tables",lambda *args:tiny_tables())
    gate=threading.Event(); entered=threading.Event(); calls=[]
    def run(question,*args,**kwargs):
        calls.append(question)
        if len(calls)==1: entered.set(); gate.wait(5)
        return dummy_result(len(calls))
    monkeypatch.setattr(workflow,"run_agent_analysis",run)
    try:
        app=start_app(); settle(app,lambda:loaded(app)); click(app,"开始分析")
        assert entered.wait(1)
        owner=app.session_state["_background_owner"]
        gate.set()
        deadline=time.monotonic()+3
        while async_mode.snapshot(owner).status!="completed" and time.monotonic()<deadline: time.sleep(0.01)
        assert async_mode.snapshot(owner).status=="completed"
        app.text_input(key="question").set_value("请分析订单变化")
        click(app,"开始分析")
        settle(app,lambda:app.session_state.filtered_state.get("last_analysis_result") is not None)
        assert len(calls)==2 and app.session_state["last_analysis_result"]["run_manifest"]["run_id"]=="async-2"
        assert app.session_state["last_run_context"]["question"]=="请分析订单变化"
    finally:
        gate.set()


def test_upload_removal_cancels_metadata_task_and_releases_frozen_bytes(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    original=source._describe_frozen_uploads
    gate=threading.Event(); entered=threading.Event()
    def describe(items): entered.set(); gate.wait(5); return original(items)
    monkeypatch.setattr(source,"_describe_frozen_uploads",describe)
    try:
        app=AppTest.from_file(str(APP),default_timeout=15)
        app.session_state["data_source_selector"]="upload"
        app.run()
        app.file_uploader[0].set_value(("test.csv",b"date,orders\n2026-01-01,1\n","text/csv")).run()
        assert entered.wait(1)
        assert "performance_upload_inputs" in app.session_state.filtered_state
        app.file_uploader[0].set_value([]).run()
        assert not app.exception and not loaded(app)
        for key in ("performance_upload_inputs","performance_upload_files","performance_background_pending"):
            assert key not in app.session_state.filtered_state
        gate.set(); settle(app,lambda:async_mode.stats()["tasks"]==0)
        assert not loaded(app)
    finally:
        gate.set()


def _database_app():
    app=AppTest.from_file(str(APP),default_timeout=15)
    app.session_state["data_source_selector"]="database"
    return app.run()


def _database_result():
    from types import SimpleNamespace
    return SimpleNamespace(table_name="db_query_result",dataframe=tiny_tables()["daily_metrics"],source_type="database",warnings=[])


def test_async_database_snapshot_expiry_requires_explicit_query(async_mode, monkeypatch):
    from dataclasses import replace
    from app.session_data import DatasetSession
    from insightpilot.performance import PerformanceConfig
    import app.components.data_source_panel as source
    clock=[0.0]; calls=[]
    def query(*args,**kwargs):
        assert get_script_run_ctx(suppress_warning=True) is None
        calls.append(1)
        return _database_result()
    monkeypatch.setattr(source,"run_database_query",query)
    app=_database_app()
    app.session_state["performance_dataset"]=DatasetSession(replace(PerformanceConfig(),session_ttl_seconds=5),clock=lambda:clock[0])
    click(app,"检查并加载只读查询"); settle(app,lambda:loaded(app))
    assert len(calls)==1 and "performance_database_request" not in app.session_state.filtered_state
    clock[0]=6
    app.run(); app.run()
    assert not loaded(app) and len(calls)==1
    assert any("数据库快照已过期" in str(x.value) for x in app.info)
    click(app,"检查并加载只读查询"); settle(app,lambda:loaded(app))
    assert len(calls)==2


def test_expired_pending_database_task_does_not_automatically_requery(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    clock=[0.0]; async_mode._clock=lambda:clock[0]; async_mode.ttl_seconds=5
    gate=threading.Event(); entered=threading.Event(); calls=[]
    def query(*args,**kwargs): entered.set(); calls.append(1); gate.wait(5); return _database_result()
    monkeypatch.setattr(source,"run_database_query",query)
    try:
        app=_database_app(); click(app,"检查并加载只读查询"); assert entered.wait(1)
        owner=app.session_state["_background_owner"]
        gate.set()
        deadline=time.monotonic()+3
        while async_mode.snapshot(owner).status!="completed" and time.monotonic()<deadline: time.sleep(0.01)
        clock[0]=6; async_mode.sweep()
        assert async_mode.snapshot(owner) is None
        app.run(); app.run()
        assert len(calls)==1 and not loaded(app)
        assert "performance_background_pending" not in app.session_state.filtered_state
        assert app.session_state["performance_background_blocked"].get("dataset")
        click(app,"检查并加载只读查询"); settle(app,lambda:loaded(app))
        assert len(calls)==2
    finally:
        gate.set()


def test_active_analysis_fragment_keeps_only_bound_dataset_revision_alive(async_mode):
    from dataclasses import replace
    from app.session_data import DatasetSession
    from insightpilot.performance import PerformanceConfig
    clock=[0.0]
    session=DatasetSession(replace(PerformanceConfig(),session_ttl_seconds=3),clock=lambda:clock[0])
    snapshot,_=session.load("tiny",lambda:(tiny_tables(),None),source_type="synthetic")
    gate=threading.Event()
    owner="ttl-fragment-owner"
    task=async_mode.submit(owner,"analysis-key",snapshot.revision,lambda:gate.wait(5))
    app=AppTest.from_string("from app.background_tasks import render_background_status; render_background_status()")
    app.session_state["_background_owner"]=owner
    app.session_state["performance_dataset"]=session
    app.session_state["performance_background_pending"]={"kind":"analysis","key":"analysis-key","revision":snapshot.revision,"task_id":task.task_id,"context":{"dataset_id":snapshot.dataset_id}}
    try:
        for value in (2.0,4.0,6.0,8.0):
            clock[0]=value
            app.run()
            assert not app.exception
        assert session.current is snapshot
    finally:
        gate.set()


def test_async_csv_parse_runs_once_in_worker_and_content_change_revises(async_mode, monkeypatch):
    import app.components.data_source_panel as source
    original=source.read_csv_file; calls=[]
    def parse(*args,**kwargs):
        assert get_script_run_ctx(suppress_warning=True) is None
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(source,"read_csv_file",parse)
    app=AppTest.from_file(str(APP),default_timeout=15)
    app.session_state["data_source_selector"]="upload"; app.run()
    app.file_uploader[0].set_value(("same.csv",b"date,orders\n2026-01-01,1\n","text/csv")).run()
    settle(app,lambda:loaded(app))
    first=app.session_state["performance_dataset"].current
    app.session_state["guided_advanced"] = True; app.run()
    assert len(calls)==1 and app.session_state["performance_dataset"].current is first
    app.file_uploader[0].set_value(("same.csv",b"date,orders\n2026-01-01,9\n","text/csv")).run()
    settle(app,lambda:loaded(app))
    second=app.session_state["performance_dataset"].current
    assert len(calls)==2 and first.revision!=second.revision and first.fingerprints!=second.fingerprints


def test_async_excel_discovery_and_selected_sheet_parse_are_worker_only(async_mode, monkeypatch):
    from io import BytesIO
    import app.components.data_source_panel as source
    original_parse=source.read_excel_file; original_names=source.get_excel_sheet_names; counts=Counter()
    def names(*args,**kwargs):
        assert get_script_run_ctx(suppress_warning=True) is None
        counts["names"]+=1
        return original_names(*args,**kwargs)
    def parse(*args,**kwargs):
        assert get_script_run_ctx(suppress_warning=True) is None
        counts["parse"]+=1
        return original_parse(*args,**kwargs)
    monkeypatch.setattr(source,"get_excel_sheet_names",names)
    monkeypatch.setattr(source,"read_excel_file",parse)
    data=BytesIO()
    with pd.ExcelWriter(data,engine="openpyxl") as writer:
        pd.DataFrame({"orders":[1]}).to_excel(writer,sheet_name="First",index=False)
        pd.DataFrame({"orders":[7]}).to_excel(writer,sheet_name="Second",index=False)
    app=AppTest.from_file(str(APP),default_timeout=15)
    app.session_state["data_source_selector"]="upload"; app.run()
    app.file_uploader[0].set_value(("tiny.xlsx",data.getvalue(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    settle(app,lambda:loaded(app))
    assert counts=={"names":1,"parse":1}
    first=app.session_state["performance_dataset"].current
    next(item for item in app.multiselect if "选择工作表" in item.label).set_value(["Second"]).run()
    settle(app,lambda:loaded(app))
    second=app.session_state["performance_dataset"].current
    assert second.revision!=first.revision
    assert next(iter(second.tables.values()))["orders"].tolist()==[7]
    app.session_state["guided_advanced"] = True; app.run()
    assert counts=={"names":1,"parse":2}
