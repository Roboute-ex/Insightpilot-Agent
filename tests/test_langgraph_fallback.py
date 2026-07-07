from __future__ import annotations

from insightpilot.agents import workflow
from insightpilot.data.synthetic import generate_all_demo_data


def test_use_langgraph_falls_back_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(workflow, "_langgraph_available", lambda: False)
    result = workflow.run_agent_analysis(
        "为什么昨天某城市订单量下降？",
        generate_all_demo_data(seed=42),
        goal_mode="metric_diagnosis",
        use_langgraph=True,
    )
    assert result["workflow_backend"] == "langgraph_unavailable_fallback"
    assert result["findings"]
    assert result["trace"]["workflow_backend"] == "langgraph_unavailable_fallback"
    assert result["reviewer"]["status"] == "PASS"
    assert "InsightPilot Agent Analysis Report" in result["report_markdown"]
