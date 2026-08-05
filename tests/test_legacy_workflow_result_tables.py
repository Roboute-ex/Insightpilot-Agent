from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data


def test_legacy_auto_workflow_produces_structured_result_tables() -> None:
    result = run_agent_analysis("昨日订单量为什么下降？", generate_all_demo_data(seed=42), goal_mode="auto")
    assert result["result_tables"]
    for key in ("metric_comparisons", "anomalies", "funnel_decomposition", "dimension_contributions", "evidence", "recommendations", "data_quality"):
        assert key in result["result_tables"]
        assert not result["result_tables"][key].empty
