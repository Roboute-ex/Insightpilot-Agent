"""Independent adversarial cases for run-comparison provenance, not UI snapshots."""
from dataclasses import replace
import json
import pytest
from insightpilot.analysis.threads import AnalysisThread, compare_runs


def complete_result(run_id, value=100.0):
    return {
        "execution_status": "COMPLETED", "goal_mode": "metric_diagnosis",
        "run_manifest": {"run_id": run_id},
        "metric_definitions": [{
            "metric_id": "revenue", "definition_version": "1", "unit": "元",
            "aggregation": "sum", "statistical_unit": "not_applicable",
            "timezone": "Asia/Shanghai", "scope": "orders", "table_name": "orders",
            "expression": "sum(revenue)", "date_column": "date",
            "deduplication_key": None, "grain": "支付订单",
            "business_meaning": "支付金额（未扣退款）", "numerator": None,
            "denominator": None, "null_policy": "exclude_invalid_numeric",
            "zero_denominator_policy": "undefined", "additivity": "additive",
            "valid_sample": "paid rows", "definition_status": "builtin_verified",
            "model_computation_fingerprint": "model-v1",
        }],
        "column_mapping": {"table_name": "orders", "date_column": "date",
            "timezone": "Asia/Shanghai", "aggregation": "sum", "dimension_columns": []},
        "analysis_result_package": {"metric_comparisons": [{
            "metric_id": "revenue", "current_value": value, "unit": "元",
            "current_period": "2026-09-01", "baseline_period": "前 7 日均值",
        }]}, "result_tables": {},
    }


def nodes(left, right):
    history = AnalysisThread()
    kwargs = dict(dataset_id="same", revision="1", schema={"orders": ["revenue", "date"], "refunds": ["revenue", "date"]})
    a = history.add(left, {}, **kwargs)
    b = history.add(right, {}, **kwargs)
    return a, b


@pytest.mark.parametrize("missing", ["metric_id", "definition_version", "unit", "aggregation", "statistical_unit", "timezone", "scope", "expression", "date_column", "deduplication_key"])
def test_both_runs_missing_required_definition_are_not_certified(missing):
    a, b = complete_result("a"), complete_result("b", 120)
    del a["metric_definitions"][0][missing]
    del b["metric_definitions"][0][missing]
    compared = compare_runs(*nodes(a, b))
    assert compared["status"] == "not_comparable"
    assert not compared["rows"]


@pytest.mark.parametrize("unit", ["未声明", "未确认", "unknown", ""])
def test_unknown_unit_sentinel_is_not_a_unit(unit):
    a, b = complete_result("a"), complete_result("b", 120)
    for result in (a, b): result["metric_definitions"][0]["unit"] = unit
    assert compare_runs(*nodes(a, b))["status"] == "not_comparable"


@pytest.mark.parametrize("field,new_value", [
    ("scope", "refunds"), ("table_name", "refunds"),
    ("grain", "退款订单"), ("business_meaning", "扣退款净收入"),
    ("model_computation_fingerprint", "different-measure-column"),
])
def test_actual_source_or_business_definition_changes_refuse_subtraction(field, new_value):
    a, b = complete_result("a"), complete_result("b", 120)
    b["metric_definitions"][0][field] = new_value
    compared = compare_runs(*nodes(a, b))
    assert compared["status"] == "not_comparable"
    assert not compared["rows"]


def test_semantic_request_date_window_is_not_ignored():
    a, b = complete_result("a"), complete_result("b", 120)
    for result, start, end in ((a, "2026-08-01", "2026-08-31"), (b, "2026-09-01", "2026-09-30")):
        result["metric_request"] = {"metrics": ["revenue"], "date_dimension": "date", "date_from": start, "date_to": end, "time_grain": "day"}
    compared = compare_runs(*nodes(a, b))
    assert compared["status"] == "context_differs"
    assert any(row["field"] == "window" for row in compared["configuration_differences"])


def test_semantic_request_grain_changes_are_not_comparable():
    a, b = complete_result("a"), complete_result("b", 120)
    a["metric_request"] = {"metrics": ["revenue"], "time_grain": "day"}
    b["metric_request"] = {"metrics": ["revenue"], "time_grain": "month"}
    assert compare_runs(*nodes(a, b))["status"] == "not_comparable"


def test_actual_computed_window_and_baseline_change_are_reported():
    a, b = complete_result("a"), complete_result("b", 120)
    b["analysis_result_package"]["metric_comparisons"][0].update(current_period="2026-09-02", baseline_period="前 28 日均值")
    assert compare_runs(*nodes(a, b))["status"] == "context_differs"


def test_summary_metric_without_definition_is_never_subtracted():
    a, b = complete_result("a"), complete_result("b", 120)
    for result, value in ((a, .2), (b, .3)):
        result["analysis_result_package"]["metric_comparisons"].append({"metric_id": "unregistered_cvr", "current_value": value, "unit": "比例"})
    compared = compare_runs(*nodes(a, b))
    assert not any(row["metric_id"] == "unregistered_cvr" and row.get("absolute_change") is not None for row in compared["rows"])
    # It is valid to construct a smaller summary containing only defined metrics.
    left, right = nodes(a, b)
    summary = right.summary
    summary["rows"].append({"metric_id": "unregistered_cvr", "value": .3, "unit": "比例", "group": {}})
    unsafe_summary = replace(right, result_summary=json.dumps(summary))
    assert compare_runs(left, unsafe_summary)["status"] == "not_comparable"


def test_display_only_labels_do_not_disable_valid_comparison():
    a, b = complete_result("a"), complete_result("b", 120)
    a["metric_definitions"][0]["display_name"] = "支付金额"
    b["metric_definitions"][0]["display_name"] = "已支付总额"
    compared = compare_runs(*nodes(a, b))
    assert compared["status"] == "comparable"
    assert compared["rows"][0]["absolute_change"] == 20


def test_history_back_uses_safe_widget_lifecycle():
    from streamlit.testing.v1 import AppTest
    script = r'''from types import SimpleNamespace
import streamlit as st
from app.session_data import AnalysisSession
from app.components.history_panel import render_history_controls
if "test_history_session" not in st.session_state:
    session = AnalysisSession()
    def result(run):
        return {"run_manifest":{"run_id":run}, "execution_status":"COMPLETED", "result_tables":{}}
    common = dict(dataset_id="same",revision="1",schema={"orders":["date","revenue"]})
    a = session.history.add(result("a"),{"question":"first"}, **common)
    requested = session.history.begin_request(a.run_id)
    b = session.history.add(result("b"),{"question":"second"},node_id=requested, **common)
    session.accept("b",result("b"))
    st.session_state["test_history_session"] = session
render_history_controls(st.session_state["test_history_session"], SimpleNamespace(metadata={"orders":{"columns":["date","revenue"]}}), "business")
'''
    app = AppTest.from_string(script).run()
    assert not app.exception
    app.button(key="history_back").click().run()
    assert not app.exception
    history = app.session_state["test_history_session"].history
    assert history.get(history.active_node_id).run_id == "a"


def _portable_history():
    history = AnalysisThread()
    history.add(complete_result("portable"), {}, dataset_id="same", revision="1", schema={"orders": ["revenue", "date"]})
    return json.loads(history.export_json())


@pytest.mark.parametrize("field,value", [
    ("summary", "not-an-object"), ("summary", []),
    ("summary", {"evidence_count": "1", "table_rows": {}}),
    ("summary", {"evidence_count": True, "table_rows": {}}),
    ("summary", {"evidence_count": 1, "table_rows": {"orders": -1}}),
    ("summary", {"evidence_count": 1, "table_rows": {"orders": "5"}}),
    ("status", "UNRECOGNIZED_STATUS"),
])
def test_history_import_rejects_malformed_summary_and_status(field, value):
    from insightpilot.analysis.threads import validate_history_json
    document = _portable_history()
    document["nodes"][0][field] = value
    with pytest.raises(ValueError):
        validate_history_json(json.dumps(document))


def test_history_import_deep_json_returns_controlled_value_error():
    from insightpilot.analysis.threads import validate_history_json
    document = _portable_history()
    document["nodes"][0]["config"] = {"nested": "deep-placeholder"}
    payload = json.dumps(document).replace('"deep-placeholder"', '[' * 3000 + '0' + ']' * 3000)
    assert len(payload.encode("utf-8")) < 512 * 1024
    with pytest.raises(ValueError):
        validate_history_json(payload)


@pytest.mark.parametrize("status", ["PREVIEW", "WAITING_APPROVAL"])
def test_history_import_accepts_actual_workflow_preview_states(status):
    from insightpilot.analysis.threads import validate_history_json
    document = _portable_history()
    document["nodes"][0]["status"] = status
    assert validate_history_json(json.dumps(document))["nodes"][0]["status"] == status
