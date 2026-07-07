from __future__ import annotations

from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.data.synthetic import generate_all_demo_data


def test_anomaly_detects_injected_order_drop() -> None:
    tables = generate_all_demo_data(seed=42)
    south_city = tables["daily_metrics"][tables["daily_metrics"]["city"] == "South City"]
    result = detect_metric_anomaly(south_city, "orders")
    assert result["is_anomaly"] is True
    assert result["severity"] == "HIGH"
    assert result["relative_change"] <= -0.2
