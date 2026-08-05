from __future__ import annotations

from insightpilot.ui.formatters import METRIC_DISPLAY_NAMES, format_metric_name, format_metric_text


def test_metric_ids_are_chinese_by_default_and_visible_in_developer_mode() -> None:
    assert format_metric_name("payment_success_rate") == "支付成功率"
    assert format_metric_name("payment_success_rate", developer_mode=True) == "支付成功率（payment_success_rate）"
    assert format_metric_name("latency_ms") == "启动延迟"
    assert format_metric_name("startup_latency") == "启动延迟"
    assert format_metric_text("latency_ms 与 startup_latency 均上升") == "启动延迟 与 启动延迟 均上升"


def test_all_builtin_user_facing_metric_ids_have_chinese_names() -> None:
    expected = {
        "impressions", "clicks", "visitors", "add_to_cart_users", "checkout_users",
        "payment_attempts", "successful_payments", "orders", "revenue", "refund_orders",
        "refund_amount", "ctr", "add_to_cart_rate", "checkout_rate", "conversion_rate",
        "payment_success_rate", "average_order_value", "refund_rate", "starts", "completions",
        "likes", "comments", "shares", "follows", "completion_rate", "engagement_rate",
        "follow_rate", "watch_time", "session_count", "viewer_count", "buffering_rate",
        "crash_rate", "latency_ms", "startup_latency", "interaction_rate",
    }
    assert expected.issubset(METRIC_DISPLAY_NAMES)
    assert all(format_metric_name(metric_id) != metric_id for metric_id in expected)
