from __future__ import annotations

import pandas as pd

from insightpilot.ingestion.table_registry import TableRegistry


def test_table_registry_add_list_get_and_metadata() -> None:
    registry = TableRegistry()
    df = pd.DataFrame({"date": ["2026-01-01"], "value": [1]})
    name = registry.add_table("Uploaded Table", df, "uploaded_file", "demo.csv")
    assert name == "uploaded_table"
    assert registry.list_tables() == ["uploaded_table"]
    assert registry.get_table(name).equals(df)
    metadata = registry.get_metadata(name)
    assert metadata["row_count"] == 1
    assert "dataframe" not in metadata
    assert "schema_mapping" in metadata


def test_table_registry_auto_renames_duplicates() -> None:
    registry = TableRegistry()
    df = pd.DataFrame({"value": [1]})
    first = registry.add_table("demo", df, "uploaded_file", "a.csv")
    second = registry.add_table("demo", df, "uploaded_file", "b.csv")
    assert first == "demo"
    assert second == "demo_2"


def test_table_registry_to_duckdb_tables() -> None:
    registry = TableRegistry()
    df = pd.DataFrame({"value": [1]})
    registry.add_table("demo", df, "uploaded_file", "a.csv")
    assert registry.to_duckdb_tables()["demo"].equals(df)
