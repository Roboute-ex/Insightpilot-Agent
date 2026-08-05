from __future__ import annotations


def test_content_standard_scale(content_dataset) -> None:
    tables = content_dataset.tables
    assert len(tables["content_items"]) >= 20_000
    assert len(tables["content_daily_metrics"]) >= 40_000
    assert tables["content_daily_metrics"]["date"].nunique() >= 120


def test_content_injected_patterns_are_visible(content_dataset) -> None:
    frame = content_dataset.tables["experiment_assignments"]
    rates = frame.groupby("experiment_group")["completion_rate"].mean()
    assert rates["treatment"] > rates["control"]
