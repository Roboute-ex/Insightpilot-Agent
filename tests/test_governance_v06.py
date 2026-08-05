from __future__ import annotations

import pandas as pd

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.contracts import ColumnContract, TableContract, validate_table_contract
from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.evaluation.harness import run_core_evaluation, run_determinism_evaluation, run_safety_evaluation
from insightpilot.lineage import DatasetNode, LineageEdge, LineageGraph, OperationNode
from insightpilot.observability import LocalTracer, get_opentelemetry_preview, trace_attributes


def test_contracts_report_pass_and_failure_without_crashing() -> None:
    frame = pd.DataFrame({"id": [1, 2], "value": [3.0, None]})
    contract = TableContract(
        "sample",
        columns=[ColumnContract("id", unique=True), ColumnContract("value", nullable=False, severity="warning")],
        unique_key=["id"],
    )
    results = validate_table_contract(frame, contract)
    assert any(item.status == "PASS" for item in results)
    assert any(item.status == "WARN" for item in results)
    assert all(item.to_dict()["object_name"] for item in results)


def test_lineage_is_deterministic_and_dot_export_is_local() -> None:
    graph = LineageGraph()
    graph.add_dataset(DatasetNode("input_orders", "orders", "input", fingerprint="abc", row_count=2))
    graph.add_operation(OperationNode("op_metric", "aggregate", "指标聚合", plan_id="query_demo"))
    graph.add_dataset(DatasetNode("output_metric", "result", "output", fingerprint="def", row_count=1))
    graph.add_edge(LineageEdge("input_orders", "op_metric", "consumed_by"))
    graph.add_edge(LineageEdge("op_metric", "output_metric", "produced"))
    assert graph.fingerprint() == graph.fingerprint()
    assert "digraph lineage" in graph.to_dot()
    assert graph.to_dict()["lineage_fingerprint"]


def test_local_observability_masks_sensitive_attributes_and_optional_otel_falls_back() -> None:
    tracer = LocalTracer("trace-test")
    with tracer.span("read_only_query", attributes={"password": "hidden", "database_url": "duckdb://user:secret@local/db"}):
        pass
    values = tracer.to_dict()
    assert values["spans"][0]["attributes"]["password"] == "***"
    assert "secret" not in values["spans"][0]["attributes"]["database_url"]
    summary = tracer.summary(query_count=1).to_dict()
    assert summary["query_count"] == 1
    assert trace_attributes({"trace_id": "trace-test", "summary": summary})["insightpilot.span_count"] == 1
    preview = get_opentelemetry_preview(enabled=True)
    assert preview.backend in {"local_tracer", "opentelemetry_preview"}


def test_workflow_contains_contract_lineage_and_observability_summaries() -> None:
    result = run_agent_analysis(
        "按城市分析总收入",
        generate_multi_table_commerce_data(seed=42),
        playbook_id="semantic_metric_query",
        playbook_parameters={"metric": "total_revenue", "dimensions": ["customer_city"]},
    )
    assert result["contract_results"]
    assert result["lineage"]["lineage_fingerprint"]
    assert result["telemetry"]["summary"]["span_count"] > 0
    assert {"check_data_contracts", "build_lineage", "summarize_observability"}.issubset(result["route_taken"])


def test_local_evaluation_quality_gates_are_met() -> None:
    core = run_core_evaluation()
    safety = run_safety_evaluation()
    determinism = run_determinism_evaluation()
    assert core.overall_score >= 0.95
    assert safety.overall_score == 1.0
    assert determinism.overall_score == 1.0
    numerical = next(item for item in core.results if item.case_id == "semantic_numerical_correctness")
    assert numerical.scores["numerical_correctness"] >= 0.98
