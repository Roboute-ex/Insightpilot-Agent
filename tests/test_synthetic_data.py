from __future__ import annotations

from insightpilot.data.synthetic import generate_all_demo_data


def test_generate_all_demo_data_shapes_are_deterministic() -> None:
    tables = generate_all_demo_data(seed=42)
    repeat = generate_all_demo_data(seed=42)

    expected = {
        "users",
        "traffic_events",
        "orders",
        "daily_metrics",
        "content_items",
        "content_events",
        "experiments",
        "live_sessions",
        "live_quality_logs",
        "live_interactions",
    }
    assert expected.issubset(tables)
    assert len(tables["users"]) >= 2000
    assert tables["daily_metrics"]["date"].nunique() >= 30
    assert len(tables["content_events"]) >= 5000
    assert len(tables["live_quality_logs"]) >= 3000
    assert tables["users"].head(5).equals(repeat["users"].head(5))
