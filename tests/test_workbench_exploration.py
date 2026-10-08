"""Independent hand-calculated exploration answers and fail-closed contracts."""
from __future__ import annotations

from io import BytesIO
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.analysis.exploration import (build_exploration_chart_spec, execute_exploration,
    validate_exploration_request, group_identity)
from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.planning import prepare_analysis_request
from insightpilot.playbooks.executor import execute_playbook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.tools.duckdb_engine import AnalyticsEngine
from insightpilot.tools.sql_safety import validate_sql
from insightpilot.visualization.factory import build_chart


def frame4():
    return pd.DataFrame({"city": ["A", "A", "B", "B"], "channel": ["X", "Y", "X", "Y"], "amount": [10., 30., 20., 60.]})


def mapping(aggregation="sum", metric="amount", **kwargs):
    return {"table_name": "sample", "source": "user_selected", "metric_columns": [metric], "dimension_columns": ["city", "channel"], "aggregation": aggregation, **kwargs}


def execute(frame, cm=None, request=None):
    cm = cm or mapping()
    request = request or {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}
    playbook = "data_profile" if request["kind"] == "distribution" else "dimension_contribution"
    result = execute_playbook(playbook, {"sample": frame}, cm, {"exploration_request": request})
    assert result.status == "PASS", result.warnings
    return result


def total(result, scope="all"):
    return result.result_tables["exploration_totals"].query("scope == @scope")


@pytest.mark.parametrize("aggregation,expected,groups", [("sum", 120, {"A": 40, "B": 80}), ("mean", 30, {"A": 20, "B": 40})])
def test_hand_calculated_sum_mean_and_independent_pivot_totals(aggregation, expected, groups):
    result = execute(frame4(), mapping(aggregation))
    assert total(result).iloc[0].metric_value == expected
    assert total(result, "row").set_index("row_value").metric_value.to_dict() == groups
    assert len(result.result_tables["exploration_cells"]) == 4
    assert result.metadata["exploration"]["scope_row_count"] == 4


def test_weighted_ratio_uses_explicit_existing_mapping_definition():
    frame = pd.DataFrame({"city": ["A", "B"], "channel": ["X", "Y"], "success": [9, 1], "eligible": [90, 2]})
    result = execute(frame, mapping("ratio_of_sums", "success", numerator_column="success", denominator_column="eligible", unit="比例"))
    assert total(result).iloc[0].metric_value == pytest.approx(10 / 92)
    assert total(result).iloc[0].metric_value != pytest.approx(.3)
    card = result.metadata["exploration"]["metric_card"]
    assert (card["numerator"], card["denominator"], card["aggregation"], card["unit"]) == ("success", "eligible", "ratio_of_sums", "比例")
    assert sorted(result.result_tables["exploration_cells"].metric_value) == pytest.approx([.1, .5])


def test_known_ratio_preserves_previous_weighted_contract_even_with_mean_parameter():
    frame = pd.DataFrame({"city": ["A", "B"], "channel": ["X", "Y"], "orders": [9, 1], "visitors": [90, 2], "cvr": [.1, .5]})
    result = execute(frame, mapping("mean", "cvr"))
    assert total(result).iloc[0].metric_value == pytest.approx(10 / 92)
    assert result.metadata["exploration"]["metric_card"]["aggregation"] == "ratio_of_sums"


def test_distinct_entities_are_recounted_across_cells_and_totals():
    frame = pd.DataFrame({"city": ["A", "A", "B", "B"], "channel": ["X", "Y", "Y", "Y"], "user_id": ["u1", "u1", "u2", "u2"]})
    result = execute(frame, mapping("count_distinct", "user_id", deduplication_key="user_id", unit="人"))
    assert result.result_tables["exploration_cells"].metric_value.sum() == 3
    assert total(result).iloc[0].metric_value == 2
    assert total(result, "row").set_index("row_value").metric_value.to_dict() == {"A": 1, "B": 1}
    assert "row_frequency_share" not in result.result_tables["exploration_display"]


def test_zero_denominator_and_null_sum_are_undefined_not_zero():
    frame = pd.DataFrame({"city": ["A", "B"], "channel": ["X", "Y"], "n": [None, 3.], "d": [1., 0.]})
    ratio = execute(frame, mapping("ratio_of_sums", "n", numerator_column="n", denominator_column="d"))
    assert ratio.result_tables["exploration_cells"].metric_value.isna().all()
    assert total(ratio).iloc[0].metric_value == 3
    values = execute(frame.rename(columns={"n": "amount"}), mapping("sum"))
    assert values.result_tables["exploration_cells"].query("row_value == 'A'").metric_value.isna().all()


def test_missing_unobserved_and_literal_display_labels_keep_distinct_keys():
    frame = pd.DataFrame({"city": [None, "缺失值（真实空值）", "A"], "channel": ["X", "X", "Y"], "amount": [2., 3., 4.]})
    result = execute(frame)
    cells = result.result_tables["exploration_cells"]
    assert len(cells) == 3  # Never fill the unobserved 3 x 2 Cartesian grid with zero.
    assert cells.row_key.nunique() == cells.row_label.nunique() == 3
    chart = build_chart(build_exploration_chart_spec(result.result_tables, "pivot"), result.result_tables)
    assert chart is not None
    assert np.isnan(np.array(chart.data[0].z, dtype=float)).sum() == 3


def test_topn_others_mean_is_reaggregated_not_average_of_means():
    frame = pd.DataFrame({"city": ["A", "B", "B", "B", "C"], "amount": [100., 0., 10., 20., 50.]})
    req = {"kind": "grouped", "row_dimension": "city", "top_n": 2}
    result = execute(frame, mapping("mean", dimension_columns=["city"]), req)
    assert len(result.result_tables["exploration_cells"]) == 3
    display = result.result_tables["exploration_display"]
    assert len(display) == 2
    others = display.loc[display.row_is_others].iloc[0]
    assert others.metric_value == 20  # (0 + 10 + 20 + 50) / 4, not (10+50)/2.
    assert others.row_key.startswith("others:") and pd.isna(others.row_value)
    assert total(result).iloc[0].metric_value == 36


def test_topn_others_recounts_cross_group_entities():
    frame = pd.DataFrame({"city": ["A", "A", "A", "B", "C"], "id": ["u1", "u2", "u3", "u4", "u4"]})
    result = execute(frame, mapping("count_distinct", "id", dimension_columns=["city"]), {"kind": "grouped", "row_dimension": "city", "top_n": 2})
    others = result.result_tables["exploration_display"].query("row_is_others").iloc[0]
    assert others.metric_value == 1
    assert total(result).iloc[0].metric_value == 4


def test_high_cardinality_display_budget_does_not_truncate_full_aggregation():
    rows = [{"city": f"R{i:03d}", "channel": f"C{j:02d}", "amount": 1.} for i in range(55) for j in range(35)]
    result = execute(pd.DataFrame(rows), request={"kind": "pivot", "row_dimension": "city", "column_dimension": "channel", "top_n": 50})
    assert len(result.result_tables["exploration_cells"]) == 55 * 35
    assert total(result).iloc[0].metric_value == 55 * 35
    display = result.result_tables["exploration_display"]
    assert display.row_key.nunique() == 50 and display.column_key.nunique() == 30
    assert display.metric_value.sum() == 55 * 35
    assert display.row_is_others.any() and display.column_is_others.any()


def test_full_sort_precedes_pagination_and_ties_are_stable():
    frame = pd.DataFrame({"city": ["C", "A", "B", "D"], "amount": [1, 100, 1, 50]})
    req = {"kind": "grouped", "row_dimension": "city", "top_n": 2, "include_others": False}
    a = execute(frame, mapping(dimension_columns=["city"]), req).result_tables["exploration_cells"]
    b = execute(frame.iloc[::-1].copy(deep=True), mapping(dimension_columns=["city"]), req).result_tables["exploration_cells"]
    assert a.row_key.tolist() == b.row_key.tolist()
    assert a.head(2).row_value.tolist() == ["A", "D"]
    assert len(a.iloc[2:4]) == 2


def test_count_percentages_are_frequency_shares_not_business_conversion():
    result = execute(frame4(), mapping("count"))
    display = result.result_tables["exploration_display"]
    assert display.row_frequency_share.tolist() == [.5] * 4
    assert display.column_frequency_share.tolist() == [.5] * 4
    assert "conversion_rate" not in display


def test_date_scope_and_grain_are_explicit_request_not_display():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02 23:59", "2026-02-01"], format="mixed"), "amount": [10., 30., 100.]})
    req = {"kind": "grouped", "row_dimension": "date", "time_grain": "month", "date_from": "2026-01-01", "date_to": "2026-01-02"}
    result = execute(frame, mapping("mean", dimension_columns=["date"], date_column="date"), req)
    assert total(result).iloc[0].metric_value == 20
    assert result.metadata["exploration"]["scope_row_count"] == 2
    assert len(result.result_tables["exploration_cells"]) == 1


def test_bound_filters_preserve_literal_values_and_real_null():
    attack = "A'; DROP TABLE sample; --"
    frame = pd.DataFrame({"city": [attack, "B", None], "amount": [3., 5., 7.]})
    req = {"kind": "grouped", "row_dimension": "city", "filters": [{"column": "city", "operator": "eq", "value": attack}]}
    result = execute(frame, mapping(dimension_columns=["city"]), req)
    assert total(result).iloc[0].metric_value == 3
    assert all(attack not in item["query"] for item in result.executed_queries)
    req["filters"][0]["value"] = None
    result = execute(frame, mapping(dimension_columns=["city"]), req)
    assert total(result).iloc[0].metric_value == 7


@pytest.mark.parametrize("exploration_request", [
    {"kind": "pivot", "row_dimension": "city", "column_dimension": "city"},
    {"kind": "grouped", "row_dimension": "not_a_column"},
    {"kind": "grouped", "row_dimension": "city", "sql": "SELECT * FROM sample"},
    {"kind": "grouped", "row_dimension": "city", "top_n": 0},
    {"kind": "grouped", "row_dimension": "city", "max_display_rows": 51},
    {"kind": "grouped", "row_dimension": "city", "filters": [{"column": "city", "operator": "execute", "value": "x"}]},
    {"kind": "grouped", "row_dimension": "city", "filters": [{"column": "other", "operator": "eq", "value": "x"}]},
    {"kind": "grouped", "row_dimension": "city", "time_grain": "day"},
])
def test_invalid_exploration_blocks_before_engine_and_workflow_sql(monkeypatch, exploration_request):
    dataset = PreparedDataset.from_tables({"sample": frame4()})
    def denied(*args, **kwargs):
        raise AssertionError("Invalid exploration must not construct or execute an engine")
    monkeypatch.setattr(AnalyticsEngine, "__init__", denied)
    parameters = {"exploration_request": exploration_request}
    prepared = prepare_analysis_request("查看分组汇总", table_metadata=dataset.metadata, goal_mode="periodic_report", playbook_id="dimension_contribution", column_mapping=mapping(), playbook_parameters=parameters)
    assert prepared["planning_status"] != "ready"
    result = run_agent_analysis("查看分组汇总", {}, goal_mode="periodic_report", playbook_id="dimension_contribution", column_mapping=mapping(), playbook_parameters=parameters, prepared_dataset=dataset, presentation_mode="deferred", data_source_type="uploaded_files")
    assert result["execution_status"] != "COMPLETED"
    assert result["trace"]["executed_queries"] == []


def test_numeric_date_does_not_guess_epoch_during_preflight():
    frame = frame4().assign(timestamp=[1, 2, 3, 4])
    ds = PreparedDataset.from_tables({"sample": frame})
    request = {"kind": "distribution", "field": "timestamp", "distribution_type": "date"}
    prepared = prepare_analysis_request("查看字段分布", table_metadata=ds.metadata, playbook_id="data_profile", goal_mode="periodic_report", column_mapping={"table_name": "sample", "source": "user_selected"}, playbook_parameters={"exploration_request": request})
    assert prepared["planning_status"] == "invalid_input"
    assert any("epoch" in message for message in prepared["clarification"]["errors"])


def test_exact_numeric_distribution_and_precomputed_box_do_not_rescan(monkeypatch):
    frame = pd.DataFrame({"amount": [10., 30., 20., 60., None, np.inf, -np.inf]})
    result = execute(frame, {"table_name": "sample"}, {"kind": "distribution", "field": "amount"})
    summary = result.result_tables["distribution_summary"].iloc[0]
    assert (summary.row_count, summary.valid_count, summary.missing_count, summary.nonfinite_count) == (7, 4, 1, 2)
    assert summary["mean"] == 30 and summary["median"] == 25
    assert summary.q1 == 17.5 and summary.q3 == 37.5
    assert summary["stddev"] == pytest.approx((1400 / 3) ** .5) and summary.ddof == 1
    assert result.result_tables["distribution_bins"]["count"].sum() == 4
    def denied(*args, **kwargs):
        raise AssertionError("Changing a chart must not execute SQL")
    monkeypatch.setattr(AnalyticsEngine, "run_parameterized_sql", denied)
    box = build_chart(build_exploration_chart_spec(result.result_tables, "distribution", "box"), result.result_tables)
    assert box is not None and box.data[0].median[0] == 25 and box.data[0].q1[0] == 17.5
    assert build_chart(build_exploration_chart_spec(result.result_tables, "distribution", "histogram"), result.result_tables) is not None


def test_date_distribution_reports_parse_failures_and_range():
    frame = pd.DataFrame({"day": ["2026-01-01", "bad", None, "2026-01-03"]})
    result = execute(frame, {"table_name": "sample"}, {"kind": "distribution", "field": "day", "distribution_type": "date"})
    summary = result.result_tables["distribution_summary"].iloc[0]
    assert (summary.row_count, summary.valid_count, summary.missing_count, summary.parse_failure_count) == (4, 2, 1, 1)
    assert str(summary.minimum).startswith("2026-01-01")


def test_categorical_denominator_includes_missing_without_calling_it_users():
    frame = pd.DataFrame({"kind": ["A", "A", "B", None]})
    result = execute(frame, {"table_name": "sample"}, {"kind": "distribution", "field": "kind", "top_n": 2})
    full = result.result_tables["distribution_frequencies"]
    assert full.metric_value.sum() == 4 and full.frequency_share.sum() == 1
    assert result.result_tables["exploration_display"].metric_value.sum() == 4
    assert "不是去重人数" in result.metadata["exploration"]["display_note"]


def test_result_limit_fails_without_truncating_groups():
    frame = pd.DataFrame({"city": ["A", "B", "C"], "amount": [1, 2, 3]})
    cm = ColumnMapping(**mapping(dimension_columns=["city"]))
    with AnalyticsEngine(max_rows=2) as engine:
        engine.register_tables({"sample": frame})
        with pytest.raises(ValueError):
            execute_exploration(get_playbook_registry().get("dimension_contribution"), {"sample": frame}, cm, frame, {"exploration_request": {"kind": "grouped", "row_dimension": "city"}}, engine)


def test_quantile_ast_allowance_does_not_authorize_nested_external_or_write_queries():
    kwargs = {"allowed_tables": {"sample"}, "table_columns": {"sample": ["amount"]}, "dialect": "duckdb"}
    assert validate_sql('SELECT QUANTILE_CONT(amount, .5) FROM sample', **kwargs).allowed
    for sql in ("SELECT QUANTILE_CONT(x, .5) FROM read_csv_auto('secret.csv') t(x)", "WITH x AS (DELETE FROM sample RETURNING amount) SELECT QUANTILE_CONT(amount, .5) FROM x", "SELECT QUANTILE_CONT(secret, .5) FROM sample", "SELECT QUANTILE_CONT(amount, .5) FROM sample UNION ALL SELECT amount FROM other"):
        assert not validate_sql(sql, **kwargs).allowed


def test_workflow_package_evidence_and_six_lazy_exports_use_same_exploration_run():
    from app.components.export_panel import prepare_export_payload, _new_export_cache
    from insightpilot.performance import PerformanceConfig
    from pypdf import PdfReader
    dataset = PreparedDataset.from_tables({"sample": frame4()})
    result = run_agent_analysis("查看城市渠道交叉表", {}, goal_mode="periodic_report", playbook_id="dimension_contribution", column_mapping=mapping("mean"), playbook_parameters={"exploration_request": {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}}, prepared_dataset=dataset, data_source_type="uploaded_files", presentation_mode="deferred", selection_source="user_selected")
    assert result["execution_status"] == "COMPLETED"
    assert result["analysis_result_package"]["metadata"]["exploration"]["metric_card"]["aggregation"] == "mean"
    assert "30" in result["analysis_result_package"]["executive_summary"]
    assert result["charts"] == []
    cache = _new_export_cache(PerformanceConfig())
    payloads = {name: prepare_export_payload(result, name, cache=cache) for name in ("pdf", "markdown", "html", "excel", "manifest", "bundle")}
    pdf = "".join(page.extract_text() for page in PdfReader(BytesIO(payloads["pdf"])).pages)
    assert "全量描述性探索" in pdf and "30" in pdf
    assert result["run_manifest"]["run_id"] in payloads["manifest"]
    assert "30" in payloads["markdown"] and "30" in payloads["html"]
    book = pd.ExcelFile(BytesIO(payloads["excel"]))
    assert any("exploration" in name for name in book.sheet_names)
    with zipfile.ZipFile(BytesIO(payloads["bundle"])) as archive:
        pdf_name = next(name for name in archive.namelist() if name.endswith(".pdf"))
        assert archive.read(pdf_name) == payloads["pdf"]
    assert len(get_playbook_registry().list_all()) == 10


def test_auto_date_distribution_reuses_csv_readiness_facts():
    frame = pd.DataFrame({"date": ["2026-01-01", "2026-01-02", "bad", None]})
    dataset = PreparedDataset.from_tables({"sample": frame})
    result = execute_playbook("data_profile", {"sample": frame}, {"table_name": "sample"}, {"exploration_request": {"kind": "distribution", "field": "date"}}, dataset.metadata)
    assert result.status == "PASS", result.warnings
    assert result.metadata["exploration"]["distribution_type"] == "date"
    row = result.result_tables["distribution_summary"].iloc[0]
    assert row.valid_count == 2 and row.parse_failure_count == 1


def test_literal_others_label_stays_distinct_after_categorical_concat():
    literal = "其他分组（Others，余集）"
    frame = pd.DataFrame({"kind": [literal] * 10 + ["A", "B", "B"]})
    result = execute(frame, {"table_name": "sample"}, {"kind": "distribution", "field": "kind", "top_n": 2})
    display = result.result_tables["exploration_display"]
    assert display.row_label.nunique() == 2
    assert display.loc[display.row_is_others, "metric_value"].iloc[0] == 3
    assert display.loc[~display.row_is_others, "metric_value"].iloc[0] == 10


def _history_run(dataset, exploration_request):
    cm = mapping("mean", date_column="date", unit="元")
    parameters = {"exploration_request": exploration_request}
    result = run_agent_analysis("查看城市渠道交叉表", {}, goal_mode="periodic_report", playbook_id="dimension_contribution", column_mapping=cm, playbook_parameters=parameters, prepared_dataset=dataset, presentation_mode="deferred", data_source_type="uploaded_files")
    assert result["execution_status"] == "COMPLETED", (result["clarification"], result["errors"])
    return result, {"playbook_id": "dimension_contribution", "column_mapping": cm, "parameters": parameters}


def _compare_exploration(request_a, request_b):
    from insightpilot.analysis.threads import AnalysisThread, compare_runs
    dataset = PreparedDataset.from_tables({"sample": frame4().assign(date=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-03"]))})
    thread = AnalysisThread()
    results = []
    for request in (request_a, request_b):
        result, config = _history_run(dataset, request)
        node = thread.add(result, config, dataset_id=dataset.dataset_id, revision=dataset.revision, schema={"sample": list(dataset.tables["sample"].columns)})
        results.append(node)
    return compare_runs(*results), results


def test_history_comparison_checks_nested_filters_before_subtraction():
    base = {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}
    compared, nodes = _compare_exploration({**base, "filters": [{"column": "city", "operator": "eq", "value": "A"}]}, {**base, "filters": [{"column": "city", "operator": "eq", "value": "B"}]})
    assert compared["status"] == "not_comparable" and compared["rows"] == []
    assert any("过滤条件" in reason for reason in compared["reasons"])
    assert nodes[0].context["filters"][0]["value"] == "A"


def test_history_comparison_records_date_windows_without_filling_absent_groups():
    base = {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}
    compared, nodes = _compare_exploration({**base, "date_from": "2026-01-01", "date_to": "2026-01-02"}, {**base, "date_from": "2026-01-02", "date_to": "2026-01-03"})
    assert compared["status"] == "context_differs"
    assert any(item["field"] == "window" for item in compared["configuration_differences"])
    assert any(row["run_a"] is None or row["run_b"] is None for row in compared["rows"])
    assert all(row["absolute_change"] is None for row in compared["rows"] if row["run_a"] is None or row["run_b"] is None)
    assert nodes[0].context["definitions"][0]["time_range"] == ["2026-01-01", "2026-01-02"]


def test_history_compares_actual_aggregate_keys_and_ignores_display_topn():
    base = {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}
    compared, nodes = _compare_exploration({**base, "top_n": 1}, {**base, "top_n": 2})
    assert compared["status"] == "comparable", compared
    assert len(compared["rows"]) == 5  # Independent all-scope total plus four keyed cells.
    assert all(row["absolute_change"] == 0 for row in compared["rows"])
    assert len(nodes[0].summary["rows"]) <= 128
    assert isinstance(nodes[0].result_summary, str)


def test_filtered_exploration_export_keeps_strict_definition_binding_after_redaction():
    from copy import deepcopy
    from app.components.export_panel import prepare_export_payload
    from insightpilot.reports.definitions import bind_report_metadata
    from insightpilot.reports.manifest import RunManifest
    frame = frame4().assign(date=pd.to_datetime(["2026-06-30"] * 4))
    dataset = PreparedDataset.from_tables({"sample": frame})
    request = {"kind": "grouped", "row_dimension": "city", "filters": [{"column": "city", "operator": "eq", "value": "A"}], "date_from": "2026-06-30", "date_to": "2026-06-30"}
    result, _ = _history_run(dataset, request)
    assert total(type("Result", (), {"result_tables": result["result_tables"]})()).iloc[0].metric_value == 20
    definition = result["metric_definitions"][0]
    assert "value" not in definition["exploration_scope"]["filters"][0]
    assert definition["exploration_scope"]["filters"][0]["value_fingerprint"]
    assert result["run_manifest"]["metric_definitions"][0] == definition
    for name in ("pdf", "excel", "manifest", "bundle"):
        assert prepare_export_payload(result, name)
    changed = deepcopy(result)
    changed["metric_definitions"][0]["exploration_scope"]["filters"][0]["value_fingerprint"] = "different_actual_filter"
    with pytest.raises(ValueError, match="实际计算定义"):
        bind_report_metadata(changed, RunManifest.from_dict(result["run_manifest"]))


@pytest.mark.parametrize("operator,value", [("eq", "<已脱敏，需重新输入>"), ("in", ["A", "<已脱敏，需重新输入>"])])
def test_shared_exploration_preflight_rejects_reserved_redacted_filters(operator, value):
    from unittest.mock import patch
    request = {"kind": "grouped", "row_dimension": "city", "filters": [{"column": "city", "operator": operator, "value": value}]}
    prepared = PreparedDataset.from_tables({"sample": frame4()})
    with patch("insightpilot.agents.workflow.execute_playbook", side_effect=AssertionError("analysis executed")) as executed:
        advice = prepare_analysis_request("查看城市分组", table_metadata=prepared.metadata, dataset_revision=prepared.revision,
            goal_mode="periodic_report", playbook_id="dimension_contribution", column_mapping=mapping(),
            playbook_parameters={"exploration_request": request})
        result = run_agent_analysis("查看城市分组", {}, prepared_dataset=prepared, goal_mode="periodic_report",
            playbook_id="dimension_contribution", column_mapping=mapping(), playbook_parameters={"exploration_request": request})
    assert not advice["preflight"]["can_submit"]
    assert any("已脱敏" in item["message_zh"] for item in advice["preflight"]["blocking_issues"])
    assert result["execution_status"] == "INVALID_INPUT"
    assert not result["trace"]["executed_queries"] and executed.call_count == 0
