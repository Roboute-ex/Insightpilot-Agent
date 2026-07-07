from __future__ import annotations

from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.data.synthetic import generate_all_demo_data


def test_attribution_returns_ranked_contribution() -> None:
    tables = generate_all_demo_data(seed=42)
    result = dimension_contribution(tables["daily_metrics"], "orders", "city")
    assert list(result.columns) == [
        "dimension_value",
        "current_value",
        "baseline_value",
        "change",
        "contribution_share",
    ]
    assert result["contribution_share"].is_monotonic_decreasing
    assert result.iloc[0]["dimension_value"] == "South City"
