from __future__ import annotations

import pandas as pd

from insightpilot.ingestion.mapping import (
    ColumnMapping,
    normalize_column_mapping,
    suggest_column_mapping,
    validate_column_mapping,
)


def test_empty_mapping_detection() -> None:
    mapping = ColumnMapping()
    assert mapping.is_empty()
    assert not mapping.has_trend_mapping()
    assert not mapping.has_experiment_mapping()
    assert not mapping.has_causal_mapping()


def test_normalize_column_mapping_removes_missing_columns() -> None:
    mapping = normalize_column_mapping(
        {
            "date_column": "date",
            "metric_columns": ["orders", "missing_metric"],
            "dimension_columns": ["city", "missing_dim"],
            "group_column": "missing_group",
            "time_grain": "hour",
        },
        ["date", "orders", "city"],
    )
    assert mapping.date_column == "date"
    assert mapping.metric_columns == ["orders"]
    assert mapping.dimension_columns == ["city"]
    assert mapping.group_column is None
    assert mapping.time_grain == "day"
    assert mapping.notes


def test_validate_column_mapping_reports_missing_columns() -> None:
    warnings = validate_column_mapping(
        ColumnMapping(date_column="missing", metric_columns=["orders"], time_grain="week"),
        ["orders"],
    )
    assert any("date_column" in warning for warning in warnings)


def test_suggest_column_mapping_uses_schema_mapper() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3),
            "orders": [1, 2, 3],
            "city": ["A", "B", "A"],
        }
    )
    mapping = suggest_column_mapping("uploaded_table", df)
    assert mapping.table_name == "uploaded_table"
    assert mapping.date_column == "date"
    assert "orders" in mapping.metric_columns
    assert "city" in mapping.dimension_columns
    assert mapping.has_trend_mapping()


def test_mapping_mode_helpers() -> None:
    assert ColumnMapping(date_column="date", metric_columns=["orders"]).has_trend_mapping()
    assert ColumnMapping(group_column="group", metric_columns=["orders"]).has_experiment_mapping()
    assert ColumnMapping(treatment_column="treatment", outcome_column="outcome").has_causal_mapping()
