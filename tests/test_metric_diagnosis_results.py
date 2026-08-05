from __future__ import annotations


def test_metric_diagnosis_has_multiple_baselines_and_detects_drop(transaction_result) -> None:
    table = transaction_result["result_tables"]["metric_comparisons"]
    orders = table[table["metric_id"] == "orders"]
    assert {"前 7 日均值", "前 28 日均值", "上周同日", "前一个 7 日均值"}.issubset(set(orders["baseline_period"]))
    assert orders.loc[orders["baseline_period"] == "前 7 日均值", "relative_change"].iloc[0] < -0.2


def test_anomaly_table_is_non_empty(transaction_result) -> None:
    assert not transaction_result["result_tables"]["anomalies"].empty
