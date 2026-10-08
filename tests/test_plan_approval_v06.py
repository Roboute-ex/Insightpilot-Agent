from __future__ import annotations

from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.semantic.approval import review_query_plan
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.compiler import MetricCompiler, execute_query_plan
from insightpilot.semantic.query import MetricRequest


def test_plan_only_never_executes_and_high_risk_approval_is_bound_to_plan_id() -> None:
    compiler = MetricCompiler(load_builtin_catalog().get("commerce_demo"))
    tables = generate_multi_table_commerce_data(seed=42)
    preview = compiler.compile(MetricRequest(metrics=["total_revenue"], execution_mode="plan_only"))
    frame, review = execute_query_plan(preview, tables)
    assert frame is None
    assert review.decision == "pending"

    risky = compiler.compile(MetricRequest(metrics=["customer_count"], dimensions=["order_status"]), tables=tables)
    assert risky.requires_approval is True
    stale = review_query_plan(risky, decision="approved", approved_plan_id="query_stale")
    assert stale.decision == "pending"
    blocked_frame, blocked_review = execute_query_plan(risky, tables, approved_plan_id="query_stale")
    assert blocked_frame is None
    assert blocked_review.decision == "pending"
    approved_frame, approved_review = execute_query_plan(risky, tables, approved_plan_id=risky.plan_id)
    assert approved_frame is not None
    assert approved_review.approved_for_read_only_execution is True
