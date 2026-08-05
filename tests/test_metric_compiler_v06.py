from __future__ import annotations

import numpy as np
import pytest

from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.compiler import MetricCompiler, execute_query_plan
from insightpilot.semantic.query import MetricFilter, MetricRequest


def _compiler() -> MetricCompiler:
    return MetricCompiler(load_builtin_catalog().get("commerce_demo"))


def test_metric_compiler_is_parameterized_and_plan_id_is_stable() -> None:
    request = MetricRequest(
        metrics=["total_revenue"],
        dimensions=["customer_city"],
        filters=[MetricFilter("customer_city", "eq", "North City")],
    )
    first = _compiler().compile(request)
    second = _compiler().compile(request)
    assert first.plan_id == second.plan_id
    assert "North City" not in first.sql_template
    assert "?" in first.sql_template
    assert first.parameters[-2:] == ["North City", 1000]
    assert all(value.startswith("<") for value in first.to_dict()["parameters"])


def test_simple_ratio_derived_and_cumulative_metrics_are_numerically_correct() -> None:
    tables = generate_multi_table_commerce_data(seed=42)
    compiler = _compiler()
    expectations = {
        "total_revenue": float(tables["orders"]["total_amount"].sum()),
        "average_order_value": float(tables["orders"]["total_amount"].sum() / len(tables["orders"])),
        "revenue_minus_orders": float(tables["orders"]["total_amount"].sum() - len(tables["orders"])),
    }
    for metric_id, expected in expectations.items():
        plan = compiler.compile(MetricRequest(metrics=[metric_id]))
        frame, review = execute_query_plan(plan, tables)
        assert review.decision == "approved"
        assert frame is not None
        assert np.isclose(float(frame[metric_id].iloc[0]), expected)

    plan = compiler.compile(MetricRequest(metrics=["cumulative_revenue"], dimensions=["order_date"]))
    frame, _ = execute_query_plan(plan, tables)
    expected = tables["orders"].groupby(tables["orders"]["order_date"].dt.floor("D"))["total_amount"].sum().sort_index().cumsum()
    actual = frame.set_index("order_date")["cumulative_revenue"]
    assert np.allclose(actual.to_numpy(), expected.to_numpy())


def test_compiler_rejects_unknown_identifiers_and_cumulative_without_time() -> None:
    compiler = _compiler()
    with pytest.raises(ValueError, match="未知指标"):
        compiler.compile(MetricRequest(metrics=["not_allowlisted"]))
    with pytest.raises(ValueError, match="需要时间维度"):
        compiler.compile(MetricRequest(metrics=["cumulative_revenue"]))
