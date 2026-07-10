from __future__ import annotations

import pytest

from insightpilot.tools.duckdb_engine import AnalyticsEngine, run_parameterized_sql


def test_parameterized_sql_binds_values(playbook_tables) -> None:
    engine = AnalyticsEngine()
    engine.register_tables(playbook_tables)
    result = engine.run_parameterized_sql('SELECT COUNT(*) AS n FROM "analysis_table" WHERE "metric" >= ?', [120])
    assert int(result["n"].iloc[0]) > 0
    assert int(run_parameterized_sql("SELECT ? AS value", [7])["value"].iloc[0]) == 7


@pytest.mark.parametrize("query", ["DROP TABLE x", "DELETE FROM x", "UPDATE x SET a = 1"])
def test_parameterized_sql_rejects_writes(query) -> None:
    with pytest.raises(ValueError):
        run_parameterized_sql(query)
