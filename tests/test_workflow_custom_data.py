from __future__ import annotations

import pandas as pd

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.ingestion.table_registry import TableRegistry


def _custom_registry(source_type: str = "uploaded_file") -> TableRegistry:
    registry = TableRegistry()
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=12, freq="D"),
            "orders": [10, 11, 12, 13, 12, 11, 10, 9, 8, 7, 6, 5],
            "city": ["A", "B"] * 6,
        }
    )
    registry.add_table("custom_metrics", df, source_type, "memory")
    return registry


def test_uploaded_files_workflow_uses_generic_fallback() -> None:
    registry = _custom_registry()
    result = run_agent_analysis(
        "请分析订单趋势",
        registry.to_duckdb_tables(),
        goal_mode="growth_trend",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
    )
    assert result["data_source_type"] == "uploaded_files"
    assert "generic_analysis_fallback" in result["route_taken"]
    assert "run_generic_trend" in result["route_taken"]
    assert result["trace"]["data_source_type"] == "uploaded_files"
    assert result["table_metadata"]
    assert "数据来源" in result["report_markdown"]


def test_database_workflow_uses_generic_fallback() -> None:
    registry = _custom_registry(source_type="database")
    result = run_agent_analysis(
        "请诊断指标波动",
        registry.to_duckdb_tables(),
        goal_mode="metric_diagnosis",
        data_source_type="database",
        table_metadata=registry.metadata,
    )
    assert result["data_source_type"] == "database"
    assert "generic_analysis_fallback" in result["route_taken"]
    assert result["reviewer"]["status"] in {"PASS", "WARN"}


def test_custom_experiment_without_required_fields_does_not_crash() -> None:
    registry = _custom_registry()
    result = run_agent_analysis(
        "请分析实验",
        registry.to_duckdb_tables(),
        goal_mode="experiment_analysis",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
    )
    assert result["findings"]
    assert any("control/treatment" in finding for finding in result["findings"])
    assert result["errors"] == []
