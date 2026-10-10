"""Semantic cards have scopes, while navigation/restoration need frozen tables."""
from types import SimpleNamespace

import pytest

from app.components.analysis_context import project_run_context, run_source_tables
from app.session_data import AnalysisSession


def _semantic_session():
    session = AnalysisSession()
    config = {"question": "按城市汇总收入", "goal_mode": "periodic_report",
        "playbook_id": "semantic_metric_query", "effective_playbook_id": "semantic_metric_query",
        "column_mapping": None, "parameters": {"metric": "total_revenue", "dimensions": ["customer_city"]}}
    result = {"execution_status": "COMPLETED", "goal_mode": "periodic_report", "summary": "已有语义结果",
        "run_manifest": {"run_id": "semantic-source"}, "result_tables": {},
        "metric_definitions": [{"metric_id": "total_revenue", "scope": "orders", "scenario": "semantic",
            "source": "registered_definition", "unit": "元", "aggregation": "sum"}]}
    node = session.history.add(result, config, dataset_id="semantic-data", revision="1",
        schema={"orders": ["order_id", "customer_id", "total_amount"], "customers": ["customer_id", "city"]})
    return session, node


def test_semantic_projection_uses_complete_frozen_loaded_scope():
    session, node = _semantic_session()
    snapshot = SimpleNamespace(dataset_id="semantic-data", revision="1", metadata={"orders": {}, "customers": {}})
    assert run_source_tables(node) == ["customers", "orders"]
    view = project_run_context(session.history, node.node_id, snapshot)
    assert view["source_available"] and view["data_matches"]
    assert any("该运行已加载范围" in line and "customers" in line and "orders" in line for line in view["scope_lines"])


@pytest.mark.parametrize("missing", ["orders", "customers"])
def test_missing_any_semantic_source_blocks_restore_without_execution(missing, monkeypatch):
    from test_core_workflow_navigation import _context_component_app, _press
    from test_method_discovery_ui import watch, assert_no_work_since
    counts = watch(monkeypatch)
    session, node = _semantic_session()
    snapshot = SimpleNamespace(dataset_id="semantic-data", revision="1",
        metadata={key: {} for key in ("orders", "customers") if key != missing})
    assert not project_run_context(session.history, node.node_id, snapshot)["source_available"]
    app = _context_component_app(session, snapshot)
    before = counts.copy()
    _press(app, "core_restore_config")
    assert app.button(key="core_restore_confirm").disabled
    # A forged enabled button still cannot bypass the server-side source check.
    app.button(key="core_restore_confirm").proto.disabled = False
    _press(app, "core_restore_confirm")
    assert app.text_input(key="question").value == "尚未提交的草稿"
    assert len(session.history.nodes) == 1
    assert_no_work_since(counts, before)


def test_nonsemantic_unmapped_history_cannot_use_arbitrary_schema_as_source():
    node = SimpleNamespace(config={"column_mapping": None}, context={
        "method": {"playbook": "data_profile"}, "definitions": [], "schema": {"other": ["amount"]}})
    assert run_source_tables(node) == []


def test_real_semantic_controls_keep_result_export_and_nonexecuting_restore(monkeypatch):
    from test_method_discovery_ui import start, press, watch, assert_no_work_since, text
    counts = watch(monkeypatch)
    app = start()
    app.session_state["guided_advanced"] = True
    app.run()
    next(item for item in app.selectbox if item.label == "演示场景").set_value("多表语义指标分析").run()
    next(item for item in app.selectbox if item.label == "分析方法").set_value("semantic_metric_query").run()
    next(item for item in app.button if item.label == "应用参数并更新建议").click().run()
    press(app, "guided_run")
    result = app.session_state["last_analysis_result"]
    session = app.session_state["performance_result"]
    node = session.history.get(session.history.active_node_id)
    assert result["execution_status"] == "COMPLETED"
    assert "查看口径与质量" in [item.label for item in app.expander]
    assert "该运行已加载范围" in text(app)
    before = counts.copy()
    app.segmented_control(key="result_tabs").set_value("报告导出").run()
    assert not app.exception
    assert not app.button(key="generate_export_pdf").disabled
    assert_no_work_since(counts, before)
    app.segmented_control(key="workbench_page").set_value("history").run()
    press(app, "history_restore")
    assert not app.button(key="core_restore_confirm").disabled
    press(app, "core_restore_confirm")
    assert app.button(key="guided_run").label == "重新运行该分析"
    assert session.current is result and node.config["column_mapping"] is None
    assert len(session.history.nodes) == 1
    assert_no_work_since(counts, before)
