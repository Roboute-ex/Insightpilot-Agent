from __future__ import annotations

import pytest

from insightpilot.mcp_preview import MCPPreview, MCPPreviewError


def test_mcp_preview_uses_stable_english_schemas_and_never_accepts_sql() -> None:
    preview = MCPPreview()
    tools = preview.list_tools()
    assert {item["name"] for item in tools} == {
        "list_semantic_models",
        "preview_metric_query",
        "execute_metric_query",
        "run_evaluation_suite",
    }
    assert all(any("\u4e00" <= char <= "\u9fff" for char in item["description"]) for item in tools)
    assert all("sql" not in item["inputSchema"].get("properties", {}) for item in tools)
    with pytest.raises(MCPPreviewError, match="SQL"):
        preview.call_tool("preview_metric_query", {"metrics": ["total_revenue"], "sql": "SELECT 1"})


def test_mcp_execution_requires_explicit_authorization_and_plan_review() -> None:
    preview = MCPPreview()
    request = {"metrics": ["total_revenue"], "dimensions": ["customer_city"]}
    plan = preview.call_tool("preview_metric_query", request)
    assert plan["executed"] is False
    assert set(plan["query_plan"]) >= {"plan_id", "sql_template", "parameters", "risk_level"}
    with pytest.raises(MCPPreviewError, match="authorized=true"):
        preview.call_tool("execute_metric_query", {**request, "authorized": False})
    executed = preview.call_tool("execute_metric_query", {**request, "authorized": True})
    assert executed["executed"] is True
    assert executed["plan_review"]["decision"] == "approved"
