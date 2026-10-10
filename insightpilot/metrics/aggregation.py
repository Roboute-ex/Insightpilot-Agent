"""Column-aware aggregate components shared by diagnosis and playbooks."""
from __future__ import annotations

from collections.abc import Iterable

# Ordered alternatives distinguish transaction, content and live fact grains.
METRIC_COMPONENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "ctr": (("clicks", "impressions"),),
    "cvr": (("orders", "visitors"),),
    "conversion_rate": (("orders", "visitors"), ("converted", "sessions")),
    "payment_success_rate": (("successful_payments", "payment_attempts"),),
    "add_to_cart_rate": (("add_to_cart_users", "visitors"),),
    "checkout_rate": (("checkout_users", "add_to_cart_users"),),
    "average_order_value": (("revenue", "orders"),),
    "refund_rate": (("refund_orders", "orders"),),
    "completion_rate": (("completed", "plays"),),
    "engagement_rate": (("engaged", "plays"),),
    "retention_rate": (("retained", "plays"), ("retained_users", "eligible_users")),
    "buffering_rate": (("buffering_seconds", "observation_seconds"),),
    "stutter_rate": (("buffering_seconds", "observation_seconds"),),
    "crash_rate": (("crashed", "sessions"),),
    "startup_latency": (("startup_latency_total", "sessions"),),
    "latency_ms": (("startup_latency_total", "sessions"),),
    "watch_time": (("watch_time_total", "plays"), ("watch_time_total", "sessions")),
    "interaction_rate": (("engaged", "plays"), ("interaction_count", "sessions")),
}


def metric_components(metric: str, columns: Iterable[str]) -> tuple[str, str] | None:
    available = set(columns)
    return next((pair for pair in METRIC_COMPONENTS.get(metric, ()) if set(pair).issubset(available)), None)


def is_non_additive_metric(metric: str) -> bool:
    """Ratios and averages: when components are missing they may be averaged, never summed."""
    return metric in METRIC_COMPONENTS or metric.endswith(("_rate", "_time", "_latency"))
