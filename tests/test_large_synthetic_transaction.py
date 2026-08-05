from __future__ import annotations


def test_transaction_standard_scale_and_dimensions(transaction_dataset) -> None:
    tables = transaction_dataset.tables
    daily = tables["daily_metrics"]
    assert daily["date"].nunique() >= 180
    assert len(daily) >= 30_000
    assert len(tables["transaction_detail"]) >= 50_000
    dimensions = {"date", "city", "region", "channel", "user_segment", "device", "platform", "merchant_type", "payment_method", "customer_type", "campaign", "app_version", "hour_bucket", "weekday", "is_holiday"}
    assert len(dimensions & set(daily.columns)) >= 10


def test_transaction_generation_is_deterministic_and_metadata_records_anomalies(transaction_dataset) -> None:
    from insightpilot.data.scenarios import generate_transaction_scenario

    repeat = generate_transaction_scenario(scale="standard", seed=42)
    assert transaction_dataset.tables["daily_metrics"].head(20).equals(repeat.tables["daily_metrics"].head(20))
    assert any(item["id"] == "android_version_payment" for item in transaction_dataset.metadata["injected_anomalies"])
