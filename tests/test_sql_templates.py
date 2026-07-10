from __future__ import annotations

import pytest

from insightpilot.playbooks.sql_templates import build_dimension_contribution_query, build_metric_trend_query, quote_identifier


def test_identifier_allowlist_blocks_unknown_names() -> None:
    with pytest.raises(ValueError, match="允许列表"):
        quote_identifier("missing", {"table", "metric"})


def test_scalar_values_are_bound_not_interpolated() -> None:
    allowed = {"events", "date", "metric", "city"}
    trend = build_metric_trend_query("events", "date", "metric", allowed, date_from="2026-01-01", date_to="2026-01-31")
    assert trend.sql.lstrip().upper().startswith("SELECT")
    assert "2026-01-01" not in trend.sql
    assert trend.parameters == ["2026-01-01", "2026-01-31"]
    contribution = build_dimension_contribution_query("events", "city", "metric", allowed, top_n=7)
    assert "7" not in contribution.sql
    assert contribution.parameters == [7]
