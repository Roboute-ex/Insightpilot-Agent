from __future__ import annotations


def test_south_city_is_a_negative_order_contribution_candidate(transaction_result) -> None:
    table = transaction_result["result_tables"]["dimension_contributions"]
    south = table[(table["metric_id"] == "orders") & (table["dimension"] == "city") & (table["dimension_value"] == "South City")]
    assert not south.empty
    assert south["contribution_value"].iloc[0] < 0


def test_android_version_payment_signal_is_detectable(transaction_result) -> None:
    table = transaction_result["result_tables"]["dimension_contributions"]
    version = table[(table["metric_id"] == "payment_success_rate") & table["dimension_value"].str.contains("6.2", na=False)]
    assert not version.empty
    assert version["contribution_value"].min() < 0
