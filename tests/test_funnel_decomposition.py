from __future__ import annotations


def test_funnel_decomposition_has_real_stage_impacts(transaction_result) -> None:
    table = transaction_result["result_tables"]["funnel_decomposition"]
    assert len(table) == 7
    assert table["estimated_order_impact"].abs().sum() > 0
    assert 0.99 <= table["contribution_pct"].sum() <= 1.01
    assert {"曝光", "支付成功"}.issubset(set(table["stage_name"]))
