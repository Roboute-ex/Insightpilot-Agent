"""Built-in metric dictionary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    metric_name: str
    display_name: str
    definition: str
    formula: str
    business_meaning: str
    required_columns: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "display_name": self.display_name,
            "definition": self.definition,
            "formula": self.formula,
            "business_meaning": self.business_meaning,
            "required_columns": list(self.required_columns),
        }


def get_metric_dictionary() -> dict[str, MetricDefinition]:
    metrics = [
        MetricDefinition(
            "active_users",
            "活跃用户数",
            "在分析周期内产生关键行为的去重用户数。",
            "count_distinct(user_id)",
            "衡量整体参与规模。",
            ("user_id", "date"),
        ),
        MetricDefinition(
            "impressions",
            "曝光量",
            "内容或入口被展示的次数。",
            "sum(impressions)",
            "衡量上游流量供给。",
            ("impressions", "date"),
        ),
        MetricDefinition(
            "clicks",
            "点击量",
            "用户点击内容、入口或动作的次数。",
            "sum(clicks)",
            "衡量用户初步兴趣。",
            ("clicks", "date"),
        ),
        MetricDefinition(
            "ctr",
            "点击率",
            "点击量相对曝光量的比例。",
            "sum(clicks) / sum(impressions)",
            "衡量曝光到点击的吸引力。",
            ("clicks", "impressions"),
        ),
        MetricDefinition(
            "orders",
            "订单量",
            "分析周期内完成下单的数量。",
            "sum(orders)",
            "衡量交易转化规模。",
            ("orders", "date"),
        ),
        MetricDefinition(
            "cvr",
            "转化率",
            "订单量相对点击量的比例。",
            "sum(orders) / sum(clicks)",
            "衡量点击后的转化效率。",
            ("orders", "clicks"),
        ),
        MetricDefinition(
            "payment_success_rate",
            "支付成功率",
            "支付成功订单相对提交支付订单的比例。",
            "successful_payments / payment_attempts",
            "衡量支付链路稳定性。",
            ("payment_success_rate",),
        ),
        MetricDefinition(
            "revenue",
            "收入",
            "分析周期内的合成收入金额。",
            "sum(revenue)",
            "衡量交易价值。",
            ("revenue", "date"),
        ),
        MetricDefinition(
            "completion_rate",
            "完播率",
            "完整消费内容的行为占比。",
            "sum(completed) / count(events)",
            "衡量内容消费质量。",
            ("completed", "event_id"),
        ),
        MetricDefinition(
            "retention_rate",
            "留存率",
            "后续周期仍保持活跃的用户占比。",
            "retained_users / eligible_users",
            "衡量持续参与情况。",
            ("retention_rate",),
        ),
        MetricDefinition(
            "stutter_rate",
            "卡顿率",
            "直播质量日志中发生卡顿的相对比例或强度。",
            "avg(stutter_rate)",
            "衡量体验流畅性。",
            ("stutter_rate", "date"),
        ),
        MetricDefinition(
            "watch_time",
            "观看时长",
            "用户观看内容或直播的时长。",
            "avg(watch_time)",
            "衡量停留和消费深度。",
            ("watch_time",),
        ),
        MetricDefinition(
            "interaction_rate",
            "互动率",
            "互动行为相对观看或会话的比例。",
            "avg(interaction_rate)",
            "衡量参与活跃度。",
            ("interaction_rate",),
        ),
    ]
    return {metric.metric_name: metric for metric in metrics}


def get_metric(name: str) -> MetricDefinition:
    metrics = get_metric_dictionary()
    try:
        return metrics[name]
    except KeyError as exc:
        raise KeyError(f"Unknown metric: {name}") from exc


def list_metrics() -> list[MetricDefinition]:
    return list(get_metric_dictionary().values())
