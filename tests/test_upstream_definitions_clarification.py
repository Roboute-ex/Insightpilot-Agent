from __future__ import annotations
from dataclasses import replace
from copy import deepcopy
import pandas as pd
import pytest
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.agents.dataset import PreparedDataset
from insightpilot.planning.planner import prepare_analysis_request
from insightpilot.metrics.definitions import computation_payload, stable_fingerprint
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.compiler import MetricCompiler, execute_query_plan
from insightpilot.semantic.query import MetricRequest


def rates():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"] * 2 + ["2026-01-02"] * 2), "orders": [1, 9, 3, 2], "visitors": [2, 90, 10, 10], "payment_attempts": [2, 10, 5, 5], "successful_payments": [1, 9, 3, 2]})
    frame["cvr"] = frame.orders / frame.visitors
    frame["payment_success_rate"] = frame.successful_payments / frame.payment_attempts
    return {"daily": frame}


def test_metadata_clarification_is_nonexecuting_and_explicit_choice_uses_weighted_ratio(monkeypatch):
    prepared = PreparedDataset.from_tables(rates())
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    def forbidden(*args, **kwargs):
        raise AssertionError("no SQL is permitted in clarification")
    monkeypatch.setattr(AnalyticsEngine, "run_parameterized_sql", forbidden)
    decision = prepare_analysis_request("转化率为何下降？", table_metadata=prepared.metadata)
    assert decision["planning_status"] == "needs_clarification"
    options = decision["clarification"]["items"][0]["candidates"]
    assert {item["metric_id"] for item in options} == {"cvr", "payment_success_rate"}
    blocked = run_agent_analysis("转化率为何下降？", {}, prepared_dataset=prepared, data_source_type="uploaded_files", presentation_mode="deferred")
    assert blocked["execution_status"] == "NEEDS_INPUT"
    assert blocked["trace"]["executed_queries"] == []
    assert not blocked["result_tables"] and not blocked["analysis_result_package"]["experiment_results"]
    selected = run_agent_analysis("转化率为何下降？", {}, prepared_dataset=prepared, data_source_type="uploaded_files", clarification_answers={"metric": "daily:cvr"}, presentation_mode="deferred")
    assert selected["planning_status"] == "ready"
    assert selected["result_tables"]["metric_trend"].cvr.tolist() == pytest.approx([10 / 92, 5 / 20])
    card = selected["metric_definitions"][0]
    assert (card["numerator"], card["denominator"], card["aggregation"]) == ("orders", "visitors", "ratio_of_sums")
    assert card["definition_status"] == "user_confirmed"
    assert selected["run_manifest"]["metric_definitions"] == selected["metric_definitions"]


def test_automatic_mapping_does_not_imply_confirmation():
    prepared = PreparedDataset.from_tables(rates())
    decision = prepare_analysis_request("转化率", table_metadata=prepared.metadata, column_mapping={"source": "automatic_suggestion", "table_name": "daily", "metric_columns": ["cvr"]})
    assert decision["planning_status"] == "needs_clarification"


def test_synthetic_string_does_not_trust_arbitrary_input():
    result = run_agent_analysis("收入", {"daily_metrics": pd.DataFrame({"date": pd.date_range("2026-01-01", periods=2), "revenue": [10, 20]})}, data_source_type="synthetic", presentation_mode="deferred")
    assert result["execution_status"] == "NEEDS_INPUT"
    assert not any(card["definition_status"] == "builtin_verified" for card in result["metric_definitions"])


def test_invalid_mapping_never_becomes_successful_profile():
    result = run_agent_analysis("趋势", rates(), data_source_type="uploaded_files", column_mapping={"table_name": "daily", "metric_columns": ["missing"]}, presentation_mode="deferred")
    assert result["execution_status"] == "INVALID_INPUT"
    assert not result["result_tables"] and not result["findings"] and not result["trace"]["executed_queries"]


def test_mean_mapping_reaches_computation_regression():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"] * 2 + ["2026-01-02"] * 2), "amount": [10, 30, 20, 60]})
    result = run_agent_analysis("金额趋势", {"daily": frame}, data_source_type="uploaded_files", goal_mode="growth_trend", column_mapping={"table_name": "daily", "date_column": "date", "metric_columns": ["amount"], "aggregation": "mean"}, presentation_mode="deferred")
    assert result["result_tables"]["metric_trend"].amount.tolist() == [20, 40]
    assert result["metric_definitions"][0]["aggregation"] == "mean"


def test_explicit_distinct_user_count_survives_duplicate_rows():
    # Each day independently contains two users despite four duplicate events.
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"] * 4 + ["2026-01-02"] * 4), "user_id": ["u1", "u1", "u2", "u2"] * 2})
    result = run_agent_analysis("用户数趋势", {"events": frame}, goal_mode="growth_trend", data_source_type="uploaded_files", clarification_answers={"metric": "events:user_id"}, presentation_mode="deferred")
    assert result["execution_status"] == "COMPLETED"
    assert result["result_tables"]["metric_trend"].user_id.tolist() == [2, 2]
    assert result["metric_definitions"][0]["deduplication_key"] == "user_id"


def test_single_day_distinct_count_cannot_claim_a_time_trend():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"] * 4), "user_id": ["u1", "u1", "u2", "u2"]})
    result = run_agent_analysis("用户数趋势", {"events": frame}, goal_mode="growth_trend", data_source_type="uploaded_files", clarification_answers={"metric": "events:user_id"}, presentation_mode="deferred")
    assert result["execution_status"] == "NEEDS_INPUT"
    assert "INSUFFICIENT_DATE_COVERAGE" in {item["code"] for item in result["preflight"]["blocking_issues"]}
    assert result["trace"]["executed_queries"] == []
    assert not result["result_tables"]
    assert result["metric_definitions"][0]["deduplication_key"] == "user_id"


def test_experiment_requires_unit_and_direction_then_preserves_independent_sample():
    frame = pd.DataFrame({"participant": ["u1", "u1", "u2", "u2", "u3", "u3", "u4", "u4"], "arm": ["A"] * 4 + ["B"] * 4, "score": [1, 3, 3, 5, 4, 6, 6, 8]})
    kwargs = dict(question="实验效果", tables={"trial": frame}, goal_mode="experiment_analysis", data_source_type="uploaded_files", column_mapping={"table_name": "trial", "metric_columns": ["score"], "group_column": "arm"}, presentation_mode="deferred")
    blocked = run_agent_analysis(**kwargs)
    assert {item["role"] for item in blocked["clarification"]["items"]} == {"control_value", "treatment_value", "statistical_unit"}
    result = run_agent_analysis(**kwargs, clarification_answers={"control_value": "A", "treatment_value": "B", "statistical_unit": "participant"})
    values = result["artifacts"]["generic_ab_test"]
    assert values["sample_size"] == {"control": 2, "treatment": 2}
    assert (values["control_mean"], values["treatment_mean"], values["absolute_lift"]) == (3, 6, 3)


def test_computation_fingerprint_ignores_only_display_fields():
    model = load_builtin_catalog().get("commerce_demo")
    changed = replace(model, display_name="中文新标题", metrics={**model.metrics, "total_revenue": replace(model.metrics["total_revenue"], display_name="显示新标题")})
    assert model.computation_fingerprint() == changed.computation_fingerprint()
    assert model.presentation_fingerprint() != changed.presentation_fingerprint()
    changed_unit = replace(model, metrics={**model.metrics, "total_revenue": replace(model.metrics["total_revenue"], unit="美元")})
    assert model.computation_fingerprint() != changed_unit.computation_fingerprint()
    payload = {"model_id": "m", "metrics": {"title": {"metric_type": "simple", "display_name": "A", "measure_id": "x"}}}
    assert "title" in computation_payload(payload)["metrics"]
    modified = deepcopy(payload); modified["metrics"]["title"]["measure_id"] = "y"
    assert stable_fingerprint(computation_payload(payload)) != stable_fingerprint(computation_payload(modified))


def test_title_only_change_keeps_query_identity_and_policy_version_invalidates_execution():
    model = load_builtin_catalog().get("commerce_demo")
    request = MetricRequest(metrics=["total_revenue"], dimensions=[])
    before = MetricCompiler(model).compile(request)
    after = MetricCompiler(replace(model, display_name="新标题")).compile(request)
    assert before.plan_id == after.plan_id
    before.sql_policy_version = "obsolete-policy"
    frame, review = execute_query_plan(before, {})
    assert frame is None and review.decision == "rejected"
    assert "策略版本" in review.reason


def test_income_candidates_expose_existing_net_column_without_inventing_formula():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "revenue": [100, 200], "net_revenue": [80, 170]})
    # Availability comes from exact preparation, not a hand-written column list.
    meta = PreparedDataset.from_tables({"daily": frame}).metadata
    decision = prepare_analysis_request("收入趋势", table_metadata=meta)
    assert decision["planning_status"] == "needs_clarification"
    options = decision["clarification"]["items"][0]["candidates"]
    assert {item["metric_id"] for item in options} == {"revenue", "net_revenue"}
    selected = prepare_analysis_request("净收入趋势", table_metadata=meta, clarification_answers={"metric": "daily:net_revenue"})
    assert selected["planning_status"] == "ready"
    assert selected["metric_definitions"][0]["expression"] == "sum(net_revenue)"


def test_explicit_date_window_is_applied_not_only_displayed():
    result = run_agent_analysis("转化率趋势", rates(), goal_mode="growth_trend", data_source_type="uploaded_files", clarification_answers={"metric": "daily:cvr", "date_range": ["2026-01-02", "2026-01-02"]}, presentation_mode="deferred")
    table = result["result_tables"]["metric_trend"]
    assert len(table) == 1 and table.cvr.iloc[0] == .25


def test_explicit_dimension_mean_and_ratio_follow_the_same_mapped_definition():
    from insightpilot.analysis.attribution import dimension_contribution
    frame = rates()["daily"].assign(city="A")
    ratio = dimension_contribution(frame, "cvr", "city", aggregation="mean")
    assert ratio.baseline_value.iloc[0] == pytest.approx(10 / 92)
    assert ratio.current_value.iloc[0] == pytest.approx(5 / 20)
    mean = dimension_contribution(frame, "orders", "city", aggregation="mean")
    assert mean.baseline_value.iloc[0] == 5
    assert mean.current_value.iloc[0] == 2.5


def test_format_is_presentation_not_a_unit_override():
    from insightpilot.metrics.definitions import semantic_metric_card
    model = load_builtin_catalog().get("commerce_demo")
    changed = replace(model, metrics={**model.metrics, "total_revenue": replace(model.metrics["total_revenue"], format="number")})
    a = semantic_metric_card(model, "total_revenue", {})
    b = semantic_metric_card(changed, "total_revenue", {})
    assert a["unit"] == b["unit"] == "元"
    assert a["computation_fingerprint"] == b["computation_fingerprint"]
    assert a["presentation_fingerprint"] != b["presentation_fingerprint"]


def test_existing_playbook_widget_date_range_mapping_is_compatible():
    prepared = PreparedDataset.from_tables(rates())
    mapping = {"table_name": "daily", "date_column": "date", "metric_columns": ["cvr"]}
    kwargs = {"question": "转化趋势", "table_metadata": prepared.metadata, "playbook_id": "metric_trend", "column_mapping": mapping}
    start, end = "2026-01-02", "2026-01-02"
    pair = prepare_analysis_request(**kwargs, playbook_parameters={"date_range": [start, end]})
    widget = prepare_analysis_request(**kwargs, playbook_parameters={"date_range": {"start": start, "end": end}})
    assert widget["planning_status"] == "ready"
    assert widget["semantic_fingerprint"] == pair["semantic_fingerprint"]
    result = run_agent_analysis("转化趋势", {}, prepared_dataset=prepared, data_source_type="uploaded_files", playbook_id="metric_trend", column_mapping=mapping, playbook_parameters={"date_range": {"start": start, "end": end}}, presentation_mode="deferred")
    assert result["execution_status"] == "COMPLETED"
    table = result["result_tables"]["metric_trend"]
    assert len(table) == 1 and table.cvr.iloc[0] == .25
