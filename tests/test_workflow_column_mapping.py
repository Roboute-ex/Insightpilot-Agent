from __future__ import annotations

import pandas as pd

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.ingestion.table_registry import TableRegistry


def _trend_registry() -> TableRegistry:
    registry = TableRegistry()
    df = pd.DataFrame(
        {
            "event_day": pd.date_range("2026-01-01", periods=14, freq="D"),
            "revenue": [100, 110, 120, 130, 125, 122, 119, 90, 85, 80, 78, 75, 72, 70],
            "orders": [10, 11, 12, 12, 13, 12, 11, 9, 8, 8, 7, 7, 6, 6],
            "city": ["A", "B"] * 7,
            "channel": ["organic", "search"] * 7,
        }
    )
    registry.add_table("custom_metrics", df, "uploaded_file", "memory")
    return registry


def _experiment_registry() -> TableRegistry:
    registry = TableRegistry()
    df = pd.DataFrame(
        {
            "group": ["control"] * 20 + ["treatment"] * 20,
            "completion": [0.45, 0.5, 0.52, 0.48, 0.51] * 4 + [0.58, 0.61, 0.6, 0.63, 0.59] * 4,
            "segment": ["A", "B"] * 20,
        }
    )
    registry.add_table("experiment_table", df, "uploaded_file", "memory")
    return registry


def test_growth_trend_uses_manual_date_metric_dimension_mapping() -> None:
    registry = _trend_registry()
    result = run_agent_analysis(
        "请分析收入趋势",
        registry.to_duckdb_tables(),
        goal_mode="growth_trend",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
        column_mapping={
            "table_name": "custom_metrics",
            "date_column": "event_day",
            "metric_columns": ["revenue", "orders"],
            "dimension_columns": ["city", "channel"],
            "time_grain": "day",
        },
    )
    assert result["mapping_source"] == "user_selected"
    assert result["column_mapping"]["date_column"] == "event_day"
    assert result["column_mapping"]["metric_columns"] == ["revenue", "orders"]
    assert "run_generic_trend" in result["route_taken"]
    assert "Column Mapping" in result["report_markdown"]
    assert result["trace"]["column_mapping"]["date_column"] == "event_day"


def test_metric_diagnosis_uses_dimension_mapping() -> None:
    registry = _trend_registry()
    result = run_agent_analysis(
        "请诊断收入波动",
        registry.to_duckdb_tables(),
        goal_mode="metric_diagnosis",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
        column_mapping={
            "table_name": "custom_metrics",
            "date_column": "event_day",
            "metric_columns": ["revenue"],
            "dimension_columns": ["city"],
        },
    )
    assert "run_generic_dimension_breakdown" in result["route_taken"]
    assert "generic_dimension_breakdown" in result["artifacts"]


def test_experiment_analysis_uses_group_and_metric_mapping() -> None:
    registry = _experiment_registry()
    result = run_agent_analysis(
        "请分析实验效果",
        registry.to_duckdb_tables(),
        goal_mode="experiment_analysis",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
        clarification_answers={"statistical_unit": "row", "control_value": "control", "treatment_value": "treatment"},
        column_mapping={
            "table_name": "experiment_table",
            "group_column": "group",
            "metric_columns": ["completion"],
            "dimension_columns": ["segment"],
        },
    )
    assert "run_generic_experiment" in result["route_taken"]
    assert "generic_ab_test" in result["artifacts"]
    assert result["reviewer"]["status"] in {"PASS", "WARN"}


def test_causal_exploration_uses_treatment_and_outcome_mapping() -> None:
    registry = _experiment_registry()
    result = run_agent_analysis(
        "请做轻量因果探索",
        registry.to_duckdb_tables(),
        goal_mode="causal_exploration",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
        playbook_parameters={"control_value": "control", "treatment_value": "treatment"},
        column_mapping={
            "table_name": "experiment_table",
            "treatment_column": "group",
            "outcome_column": "completion",
            "dimension_columns": ["segment"],
        },
    )
    assert "run_generic_causal_light" in result["route_taken"]
    assert "generic_causal_light" in result["artifacts"]
    assert result["column_mapping"]["treatment_column"] == "group"


def test_invalid_mapping_produces_warnings_without_crashing() -> None:
    registry = _trend_registry()
    result = run_agent_analysis(
        "请分析趋势",
        registry.to_duckdb_tables(),
        goal_mode="growth_trend",
        data_source_type="uploaded_files",
        table_metadata=registry.metadata,
        column_mapping={
            "table_name": "custom_metrics",
            "date_column": "missing_date",
            "metric_columns": ["missing_metric"],
        },
    )
    assert result["execution_status"] == "INVALID_INPUT"
    assert result["mapping_warnings"]
    assert not result["findings"] and not result["trace"]["executed_queries"]
