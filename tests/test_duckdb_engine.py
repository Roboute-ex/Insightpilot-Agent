from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from insightpilot.data.synthetic import generate_all_demo_data
from insightpilot.tools.duckdb_engine import AnalyticsEngine, safe_query_templates


def test_duckdb_engine_runs_readonly_query() -> None:
    tables = generate_all_demo_data(seed=42)
    engine = AnalyticsEngine()
    engine.register_tables({"daily_metrics": tables["daily_metrics"]})
    result = engine.run_sql("SELECT COUNT(*) AS row_count FROM daily_metrics")
    assert result["row_count"].iloc[0] == len(tables["daily_metrics"])
    assert "daily_metrics" in engine.list_tables()
    assert "daily_metrics" in engine.list_registered_tables()
    profile = engine.profile_table("daily_metrics")
    assert profile["row_count"] == len(tables["daily_metrics"])
    assert "daily_metric_by_date" in safe_query_templates


def test_duckdb_engine_blocks_write_operations() -> None:
    engine = AnalyticsEngine()
    with pytest.raises(ValueError):
        engine.run_sql("DROP TABLE daily_metrics")
    with pytest.raises(ValueError):
        engine.run_sql("SELECT * FROM daily_metrics; DELETE FROM daily_metrics")


def test_duckdb_engine_sanitizes_registered_table_names() -> None:
    tables = generate_all_demo_data(seed=42)
    engine = AnalyticsEngine()
    engine.register_tables({"Uploaded Table!": tables["daily_metrics"].head(1)})
    assert "uploaded_table" in engine.list_registered_tables()
