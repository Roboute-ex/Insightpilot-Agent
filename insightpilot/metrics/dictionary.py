"""Governed built-in metric definitions with aggregation and unit metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MetricDefinition:
    metric_name: str
    display_name: str
    definition: str
    formula: str
    business_meaning: str
    required_columns: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    numerator: str | None = None
    denominator: str | None = None
    unit: str = "数量"
    grain: str = "观测行"
    aggregation: str = "sum"
    available_dimensions: tuple[str, ...] = ("date", "city", "channel", "user_segment", "device")
    good_direction: str = "higher"
    definition_version: str = "0.1.0"
    timezone: str = "naive"
    valid_sample: str = "当前过滤范围内有效观测"
    null_policy: str = "exclude_invalid_numeric"
    zero_denominator_policy: str = "undefined"
    definition_status: str = "draft"
    source: str = "builtin_definition"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        for name in ("required_columns", "aliases", "available_dimensions"):
            result[name] = list(result[name])
        return result


def get_metric_dictionary() -> dict[str, MetricDefinition]:
    metrics: list[MetricDefinition] = []
    for name, display, definition, unit in [
        ("impressions", "曝光量", "转化旅程或内容曝光机会的计数。", "次"),
        ("clicks", "点击量", "进入点击阶段的旅程或内容点击次数。", "次"),
        ("visitors", "访问次数", "进入访问阶段的转化旅程计数；不是全站去重用户。", "次"),
        ("add_to_cart_users", "加购旅程数", "进入加购阶段的旅程计数，保留历史字段名。", "次"),
        ("checkout_users", "结算旅程数", "进入结算阶段的旅程计数，保留历史字段名。", "次"),
        ("payment_attempts", "支付尝试数", "进入支付尝试阶段的旅程数。", "次"),
        ("successful_payments", "支付成功数", "支付成功的旅程数；每旅程最多一张订单。", "次"),
        ("orders", "订单量", "支付成功订单数。", "单"),
        ("revenue", "收入", "支付订单金额之和，未扣退款。", "元"),
        ("refund_orders", "退款订单量", "发生退款的订单数。", "单"),
        ("refund_amount", "退款金额", "订单实际退款金额。", "元"),
        ("plays", "播放次数", "逐播放观测行数。", "次"),
        ("likes", "点赞量", "播放观测中记录的点赞事件数。", "次"),
        ("comments", "评论量", "播放观测中记录的评论事件数。", "次"),
        ("shares", "分享量", "播放观测中记录的分享事件数。", "次"),
        ("follows", "关注量", "播放观测中记录的关注事件数。", "次"),
        ("sessions", "观看会话数", "独立观众观看会话数，非主播开播数。", "次"),
    ]:
        metrics.append(MetricDefinition(name, display, definition, f"sum({name})", definition, (name,), aliases=(display,), unit=unit))
    metrics.append(MetricDefinition("active_users", "活跃用户数", "在指定统计范围内产生行为的去重用户数。", "count_distinct(user_id)", "不同分组UV不可直接累加；汇总表缺少实体ID时不能宣称全站UV。", ("user_id",), aliases=("用户数", "UV"), grain="用户", aggregation="count_distinct"))
    for name, display, numerator, denominator, unit, direction, aliases in [
        ("ctr", "点击率", "clicks", "impressions", "比例", "higher", ("点击转化",)),
        ("cvr", "访问转化率", "orders", "visitors", "比例", "higher", ("conversion_rate", "转化率")),
        ("payment_success_rate", "支付成功率", "successful_payments", "payment_attempts", "比例", "higher", ("支付成功比例",)),
        ("average_order_value", "客单价", "revenue", "orders", "元", "context", ("AOV",)),
        ("refund_rate", "退款率", "refund_orders", "orders", "比例", "lower", ("订单退款率",)),
        ("completion_rate", "完播率", "completed", "plays", "比例", "higher", ("完整观看",)),
        ("engagement_rate", "内容互动率", "engaged", "plays", "比例", "higher", ("内容参与率",)),
        ("retention_rate", "留存率", "retained_users", "eligible_users", "比例", "higher", ("留存",)),
        ("buffering_rate", "卡顿率", "buffering_seconds", "observation_seconds", "比例", "lower", ("卡顿", "stutter_rate")),
        ("crash_rate", "崩溃率", "crashed", "sessions", "比例", "lower", ("崩溃",)),
        ("startup_latency", "启动延迟", "startup_latency_total", "sessions", "毫秒", "lower", ("latency_ms", "启动耗时")),
        ("watch_time", "观看时长", "watch_time_total", "sessions", "秒", "higher", ("停留", "观看秒数")),
        ("interaction_rate", "互动率", "interaction_count", "sessions", "比例", "higher", ("参与率",)),
    ]:
        definition = f"先汇总{numerator}和{denominator}再相除；分母为0不可计算。"
        metrics.append(MetricDefinition(name, display, definition, f"sum({numerator}) / sum({denominator})", "不直接平均不同样本量分组的比率；须结合统计单位和样本量解释。", (numerator, denominator), aliases=(display, *aliases), numerator=numerator, denominator=denominator, unit=unit, grain="明确分母的观测单位", aggregation="ratio", good_direction=direction))
    canonical = {metric.metric_name: metric for metric in metrics}
    # Compatibility aliases keep their internal names but list_metrics deduplicates labels.
    for alias, target in {"stutter_rate": "buffering_rate", "latency_ms": "startup_latency", "conversion_rate": "cvr"}.items():
        original = canonical[target]
        canonical[alias] = MetricDefinition(**{**asdict(original), "metric_name": alias})
    return canonical


def get_metric(name: str) -> MetricDefinition:
    metrics = get_metric_dictionary()
    if name in metrics:
        return metrics[name]
    normalized = name.casefold()
    for metric in metrics.values():
        if any(alias.casefold() == normalized for alias in metric.aliases):
            return metric
    raise KeyError(f"未知指标：{name}")


def list_metrics() -> list[MetricDefinition]:
    seen: set[str] = set()
    result: list[MetricDefinition] = []
    for metric in get_metric_dictionary().values():
        if metric.display_name not in seen:
            seen.add(metric.display_name)
            result.append(metric)
    return result
