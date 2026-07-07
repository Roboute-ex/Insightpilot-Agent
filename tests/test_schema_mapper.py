from __future__ import annotations

import pandas as pd

from insightpilot.ingestion.schema_mapper import infer_schema_mapping


def test_infer_schema_mapping_detects_columns() -> None:
    df = pd.DataFrame(
        {
            "event_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "orders": [10, 11, 12],
            "city": ["A", "B", "A"],
            "user_id": [1001, 1002, 1003],
        }
    )
    suggestion = infer_schema_mapping("demo", df)
    assert "event_date" in suggestion.detected_date_columns
    assert "orders" in suggestion.detected_numeric_columns
    assert "city" in suggestion.detected_categorical_columns
    assert "orders" in suggestion.possible_metric_columns
    assert "city" in suggestion.possible_dimension_columns


def test_infer_schema_mapping_outputs_warnings() -> None:
    suggestion = infer_schema_mapping("small", pd.DataFrame({"name": ["a"]}))
    assert suggestion.warnings
    assert any("数值列" in warning for warning in suggestion.warnings)
