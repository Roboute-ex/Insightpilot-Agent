from __future__ import annotations

from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.compiler import MetricCompiler
from insightpilot.semantic.query import MetricRequest
from insightpilot.ui.presenters import (
    present_analysis_plan,
    present_join_plan,
    present_query_plan,
    present_semantic_model,
    translate_caveat,
)


def test_analysis_plan_presenter_replaces_internal_values_with_chinese_summary() -> None:
    view = present_analysis_plan(
        {
            "goal_mode": "metric_diagnosis",
            "intent": "metric_drop_diagnosis",
            "goal_mode_source": "user_selected",
            "related_metrics": ["orders"],
            "comparison_method": "current_day_vs_previous_7d_average",
            "dimensions": ["city"],
            "required_tables": ["orders"],
            "analysis_steps": ["检查数据完整性", "比较历史基准"],
        }
    )
    assert view.goal_name == "指标波动诊断"
    assert view.intent_name == "指标下降诊断"
    assert view.goal_source_text == "用户手动选择"
    assert view.metric_names == ["订单量"]
    assert view.step_descriptions == ["检查数据完整性", "比较历史基准"]


def test_semantic_join_and_query_presenters_are_chinese_first() -> None:
    model = load_builtin_catalog().get("commerce_demo")
    plan = MetricCompiler(model).compile(MetricRequest(metrics=["total_revenue"], dimensions=["customer_city"]))
    model_view = present_semantic_model(model.to_dict())
    join_view = present_join_plan(plan.join_plan.to_dict())
    query_view = present_query_plan(plan.to_dict())
    assert model_view.model_name
    assert model_view.entity_count == 7
    assert join_view.risk_text == "安全"
    assert query_view.metric_names == ["总金额"]
    assert query_view.dimension_names == ["城市"]
    assert "SELECT" in query_view.sql_preview
    assert translate_caveat("synthetic data only") == "当前结果仅基于内置模拟数据，不代表真实业务结论。"
