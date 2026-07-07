"""Rule-based metric resolver."""

from __future__ import annotations

from insightpilot.metrics.dictionary import MetricDefinition, get_metric, get_metric_dictionary


KEYWORD_RULES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("订单", "下单", "交易", "order", "orders"), ("orders", "cvr", "payment_success_rate")),
    (("转化", "cvr", "conversion"), ("cvr", "ctr", "orders")),
    (("支付", "payment"), ("payment_success_rate", "orders")),
    (("收入", "营收", "revenue"), ("revenue", "orders", "cvr")),
    (("曝光", "impression"), ("impressions", "ctr")),
    (("点击", "click", "ctr"), ("clicks", "ctr")),
    (("活跃", "用户数", "active"), ("active_users",)),
    (("完播", "completion", "完整观看"), ("completion_rate", "watch_time")),
    (("留存", "retention"), ("retention_rate", "active_users")),
    (("卡顿", "stutter", "直播质量", "体验异常"), ("stutter_rate", "watch_time", "interaction_rate")),
    (("停留", "观看时长", "watch"), ("watch_time", "stutter_rate")),
    (("互动", "interaction"), ("interaction_rate", "watch_time")),
]


def resolve_metrics_from_question(question: str) -> list[MetricDefinition]:
    """Resolve relevant metrics with deterministic keyword rules."""

    normalized = question.lower()
    selected_names: list[str] = []
    for keywords, metric_names in KEYWORD_RULES:
        if any(keyword.lower() in normalized for keyword in keywords):
            for metric_name in metric_names:
                if metric_name not in selected_names:
                    selected_names.append(metric_name)

    if not selected_names:
        selected_names = ["active_users", "revenue"]

    metric_dict = get_metric_dictionary()
    return [metric_dict[name] for name in selected_names if name in metric_dict]
