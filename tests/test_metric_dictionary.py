from __future__ import annotations

from insightpilot.metrics.dictionary import get_metric, get_metric_dictionary, list_metrics
from insightpilot.metrics.resolver import resolve_metrics_from_question


def test_metric_dictionary_contains_required_metrics() -> None:
    metrics = get_metric_dictionary()
    for name in [
        "active_users",
        "impressions",
        "clicks",
        "ctr",
        "orders",
        "cvr",
        "payment_success_rate",
        "revenue",
        "completion_rate",
        "retention_rate",
        "stutter_rate",
        "watch_time",
        "interaction_rate",
    ]:
        assert name in metrics
        assert get_metric(name).metric_name == name
    assert len(list_metrics()) >= 13


def test_resolver_recognizes_chinese_questions() -> None:
    assert [m.metric_name for m in resolve_metrics_from_question("订单下降")] == [
        "orders",
        "cvr",
        "payment_success_rate",
    ]
    assert [m.metric_name for m in resolve_metrics_from_question("完播率是否提升")][0] == "completion_rate"
    assert [m.metric_name for m in resolve_metrics_from_question("直播卡顿影响停留")][:3] == [
        "stutter_rate",
        "watch_time",
        "interaction_rate",
    ]
    assert resolve_metrics_from_question("收入变化")[0].metric_name == "revenue"
