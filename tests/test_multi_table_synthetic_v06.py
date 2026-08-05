from __future__ import annotations

import pandas as pd

from insightpilot.data.synthetic import generate_multi_table_commerce_data


def test_multi_table_synthetic_data_is_deterministic_and_referentially_consistent() -> None:
    first = generate_multi_table_commerce_data(seed=42)
    second = generate_multi_table_commerce_data(seed=42)
    assert set(first) == {"customers", "sessions", "orders", "order_items", "products", "channels", "calendar"}
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name])
    assert set(first["sessions"]["customer_id"]).issubset(set(first["customers"]["customer_id"]))
    assert set(first["sessions"]["channel_id"]).issubset(set(first["channels"]["channel_id"]))
    assert set(first["orders"]["session_id"]).issubset(set(first["sessions"]["session_id"]))
    assert set(first["order_items"]["order_id"]).issubset(set(first["orders"]["order_id"]))
    assert set(first["order_items"]["product_id"]).issubset(set(first["products"]["product_id"]))
