"""Generate deterministic synthetic data for the built-in demos."""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from insightpilot.config import SYNTHETIC_END_DATE


def _date_range(days: int = 40) -> pd.DatetimeIndex:
    return pd.date_range(end=pd.Timestamp(SYNTHETIC_END_DATE), periods=days, freq="D")


def _build_users(rng: np.random.Generator, n_users: int = 3200) -> pd.DataFrame:
    cities = np.array(["North City", "South City", "East City", "West City", "Central City"])
    channels = np.array(["organic", "search", "social", "referral"])
    segments = np.array(["new", "active", "returning"])
    devices = np.array(["Android", "iOS", "Web", "Tablet"])
    signup_dates = pd.date_range("2025-01-01", periods=365, freq="D")
    return pd.DataFrame(
        {
            "user_id": np.arange(1, n_users + 1),
            "signup_date": rng.choice(signup_dates, size=n_users),
            "city": rng.choice(cities, size=n_users, p=[0.22, 0.24, 0.2, 0.18, 0.16]),
            "channel": rng.choice(channels, size=n_users, p=[0.35, 0.25, 0.25, 0.15]),
            "user_segment": rng.choice(segments, size=n_users, p=[0.28, 0.48, 0.24]),
            "device": rng.choice(devices, size=n_users, p=[0.42, 0.34, 0.16, 0.08]),
            "historical_activity": rng.gamma(shape=4.0, scale=8.0, size=n_users).round(2),
            "historical_revenue": rng.gamma(shape=2.2, scale=35.0, size=n_users).round(2),
        }
    )


def _build_daily_metrics(rng: np.random.Generator) -> pd.DataFrame:
    dates = _date_range()
    target_date = dates.max()
    cities = ["North City", "South City", "East City", "West City", "Central City"]
    channels = ["organic", "search", "social", "referral"]
    segments = ["new", "active", "returning"]
    devices = ["Android", "iOS", "Web", "Tablet"]
    merchant_types = ["standard", "premium", "local"]
    rows: list[dict[str, object]] = []
    city_factor = {
        "North City": 1.05,
        "South City": 1.12,
        "East City": 0.96,
        "West City": 0.88,
        "Central City": 0.82,
    }
    channel_factor = {"organic": 1.0, "search": 1.08, "social": 0.92, "referral": 0.78}
    segment_cvr = {"new": 0.055, "active": 0.085, "returning": 0.11}
    device_ctr = {"Android": 0.083, "iOS": 0.088, "Web": 0.071, "Tablet": 0.066}
    for date, city, channel, segment, device in product(dates, cities, channels, segments, devices):
        weekday_factor = 1.08 if date.dayofweek in (4, 5) else 1.0
        trend = 1.0 + (date - dates.min()).days * 0.003
        impressions_mean = 235 * city_factor[city] * channel_factor[channel] * weekday_factor * trend
        impressions = int(max(25, rng.normal(impressions_mean, impressions_mean * 0.08)))
        ctr = float(np.clip(rng.normal(device_ctr[device], 0.009), 0.025, 0.16))
        cvr = float(np.clip(rng.normal(segment_cvr[segment], 0.011), 0.015, 0.19))
        payment_success_rate = float(np.clip(rng.normal(0.925, 0.018), 0.82, 0.98))
        if date == target_date and city == "South City":
            impressions = int(impressions * 0.62)
            ctr *= 0.88
            cvr *= 0.82
            payment_success_rate *= 0.94
        clicks = int(round(impressions * ctr))
        visitors = int(round(clicks * 0.88))
        add_to_cart_users = int(round(visitors * min(0.82, cvr * 3.2)))
        checkout_users = int(round(add_to_cart_users * 0.68))
        payment_attempts = int(round(checkout_users * 0.92))
        successful_payments = int(rng.binomial(payment_attempts, payment_success_rate))
        orders = successful_payments
        price = rng.normal(74, 12)
        revenue = max(0.0, orders * price)
        refund_orders = int(round(orders * rng.uniform(0.01, 0.05)))
        refund_amount = refund_orders * price * rng.uniform(0.75, 1.0)
        rows.append(
            {
                "date": date.normalize(),
                "city": city,
                "channel": channel,
                "user_segment": segment,
                "device": device,
                "merchant_type": merchant_types[(date.day + len(city) + len(channel)) % len(merchant_types)],
                "impressions": impressions,
                "clicks": clicks,
                "visitors": visitors,
                "add_to_cart_users": add_to_cart_users,
                "checkout_users": checkout_users,
                "payment_attempts": payment_attempts,
                "successful_payments": successful_payments,
                "orders": orders,
                "revenue": round(revenue, 2),
                "refund_orders": refund_orders,
                "refund_amount": round(refund_amount, 2),
                "ctr": clicks / impressions if impressions else 0.0,
                "cvr": orders / visitors if visitors else np.nan,
                "conversion_rate": orders / visitors if visitors else np.nan,
                "payment_success_rate": successful_payments / payment_attempts if payment_attempts else np.nan,
                "average_order_value": revenue / orders if orders else np.nan,
                "refund_rate": refund_orders / orders if orders else np.nan,
                "active_users": int(impressions * rng.uniform(0.18, 0.32)),
            }
        )
    return pd.DataFrame(rows)


def _build_content_data(
    rng: np.random.Generator, users: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = _date_range()
    categories = np.array(["knowledge", "lifestyle", "commerce", "entertainment"])
    content_items = pd.DataFrame(
        {
            "content_id": np.arange(1, 301),
            "content_category": rng.choice(categories, size=300, p=[0.3, 0.25, 0.2, 0.25]),
            "creator_segment": rng.choice(["small", "mid", "large"], size=300, p=[0.45, 0.38, 0.17]),
        }
    )
    n_events = 6500
    picked_items = content_items.sample(n_events, replace=True, random_state=int(rng.integers(0, 1_000_000)))
    completion_base = np.where(picked_items["content_category"].to_numpy() == "knowledge", 0.62, 0.55)
    completion_base += np.where(picked_items["content_category"].to_numpy() == "entertainment", 0.05, 0.0)
    completion_rate = np.clip(rng.normal(completion_base, 0.16), 0.02, 1.0)
    content_events = pd.DataFrame(
        {
            "event_id": np.arange(1, n_events + 1),
            "date": rng.choice(dates, size=n_events),
            "user_id": rng.choice(users["user_id"].to_numpy(), size=n_events),
            "content_id": picked_items["content_id"].to_numpy(),
            "content_category": picked_items["content_category"].to_numpy(),
            "device": rng.choice(["Android", "iOS", "Web", "Tablet"], size=n_events, p=[0.44, 0.35, 0.14, 0.07]),
            "watch_time": np.clip(rng.normal(85 + completion_rate * 90, 24), 5, 420).round(2),
            "completed": rng.binomial(1, completion_rate).astype(int),
            "completion_rate": completion_rate.round(4),
            "retention_rate": np.clip(completion_rate * rng.normal(0.84, 0.05, n_events), 0.01, 1.0).round(4),
        }
    )

    n_exp = 3000
    exp_users = users.sample(n_exp, random_state=int(rng.integers(0, 1_000_000))).reset_index(drop=True)
    groups = np.array(["control"] * (n_exp // 2) + ["treatment"] * (n_exp - n_exp // 2))
    rng.shuffle(groups)
    lift = np.where(groups == "treatment", 0.075, 0.0)
    exp_completion_rate = np.clip(
        rng.normal(0.56 + lift + exp_users["historical_activity"].to_numpy() * 0.0012, 0.13),
        0.02,
        1.0,
    )
    experiments = pd.DataFrame(
        {
            "experiment_id": "content_strategy_v1",
            "user_id": exp_users["user_id"].to_numpy(),
            "group": groups,
            "completion_rate": exp_completion_rate.round(4),
            "completed": rng.binomial(1, exp_completion_rate).astype(int),
            "watch_time": np.clip(rng.normal(105 + exp_completion_rate * 95, 22), 10, 460).round(2),
            "historical_activity": exp_users["historical_activity"].to_numpy(),
            "historical_revenue": exp_users["historical_revenue"].to_numpy(),
            "city": exp_users["city"].to_numpy(),
            "channel": exp_users["channel"].to_numpy(),
            "user_segment": exp_users["user_segment"].to_numpy(),
        }
    )
    return content_items, content_events, experiments


def _build_live_data(
    rng: np.random.Generator, users: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = _date_range()
    target_date = dates.max()
    n_sessions = 1700
    session_users = users.sample(n_sessions, replace=True, random_state=int(rng.integers(0, 1_000_000))).reset_index(drop=True)
    devices = rng.choice(["Android", "iOS", "Web", "Tablet"], size=n_sessions, p=[0.42, 0.34, 0.15, 0.09])
    network_types = rng.choice(["WiFi", "Cellular", "Wired"], size=n_sessions, p=[0.52, 0.42, 0.06])
    hour_bucket = rng.choice(["00-06", "06-12", "12-18", "18-24"], size=n_sessions, p=[0.12, 0.2, 0.28, 0.4])
    session_dates = rng.choice(dates, size=n_sessions)
    risky = (session_dates == target_date) & ((devices == "Tablet") | (network_types == "Cellular"))
    watch_time = np.clip(rng.normal(520, 130, n_sessions) - risky * rng.normal(110, 25, n_sessions), 80, 1200)
    live_sessions = pd.DataFrame(
        {
            "session_id": np.arange(1, n_sessions + 1),
            "date": session_dates,
            "user_id": session_users["user_id"].to_numpy(),
            "city": session_users["city"].to_numpy(),
            "device": devices,
            "network_type": network_types,
            "hour_bucket": hour_bucket,
            "watch_time": watch_time.round(2),
        }
    )

    n_logs = 4200
    picked_sessions = live_sessions.sample(n_logs, replace=True, random_state=int(rng.integers(0, 1_000_000))).reset_index(drop=True)
    log_risky = (picked_sessions["date"].to_numpy() == target_date) & (
        (picked_sessions["device"].to_numpy() == "Tablet")
        | (picked_sessions["network_type"].to_numpy() == "Cellular")
    )
    stutter_rate = np.clip(rng.normal(0.045, 0.018, n_logs) + log_risky * rng.normal(0.13, 0.025, n_logs), 0.0, 0.45)
    live_quality_logs = pd.DataFrame(
        {
            "log_id": np.arange(1, n_logs + 1),
            "session_id": picked_sessions["session_id"].to_numpy(),
            "date": picked_sessions["date"].to_numpy(),
            "city": picked_sessions["city"].to_numpy(),
            "device": picked_sessions["device"].to_numpy(),
            "network_type": picked_sessions["network_type"].to_numpy(),
            "hour_bucket": picked_sessions["hour_bucket"].to_numpy(),
            "stutter_rate": stutter_rate.round(4),
            "latency_ms": np.clip(rng.normal(115, 24, n_logs) + log_risky * 55, 40, 420).round(2),
        }
    )

    n_interactions = 2600
    picked_interactions = live_sessions.sample(
        n_interactions, replace=True, random_state=int(rng.integers(0, 1_000_000))
    ).reset_index(drop=True)
    interaction_risky = (picked_interactions["date"].to_numpy() == target_date) & (
        (picked_interactions["device"].to_numpy() == "Tablet")
        | (picked_interactions["network_type"].to_numpy() == "Cellular")
    )
    interaction_rate = np.clip(rng.normal(0.16, 0.045, n_interactions) - interaction_risky * 0.045, 0.01, 0.42)
    live_interactions = pd.DataFrame(
        {
            "interaction_id": np.arange(1, n_interactions + 1),
            "session_id": picked_interactions["session_id"].to_numpy(),
            "date": picked_interactions["date"].to_numpy(),
            "city": picked_interactions["city"].to_numpy(),
            "device": picked_interactions["device"].to_numpy(),
            "network_type": picked_interactions["network_type"].to_numpy(),
            "hour_bucket": picked_interactions["hour_bucket"].to_numpy(),
            "interaction_count": np.maximum(0, rng.poisson(8, n_interactions) - interaction_risky * 2).astype(int),
            "interaction_rate": interaction_rate.round(4),
        }
    )
    return live_sessions, live_quality_logs, live_interactions


def generate_all_demo_data(seed: int = 42) -> dict[str, pd.DataFrame]:
    """Return all synthetic tables used by the demos.

    The same seed always produces the same tables. The generated data deliberately
    contains explainable demo patterns: a final-day order drop in South City,
    a treatment-group completion lift, and a final-day live quality issue on
    Tablet or Cellular traffic.
    """

    rng = np.random.default_rng(seed)
    users = _build_users(rng)
    daily_metrics = _build_daily_metrics(rng)
    traffic_events = daily_metrics[
        ["date", "city", "channel", "user_segment", "device", "impressions", "clicks", "ctr"]
    ].copy()
    orders = daily_metrics[
        [
            "date",
            "city",
            "channel",
            "user_segment",
            "device",
            "merchant_type",
            "orders",
            "revenue",
            "payment_success_rate",
        ]
    ].copy()
    content_items, content_events, experiments = _build_content_data(rng, users)
    live_sessions, live_quality_logs, live_interactions = _build_live_data(rng, users)
    tables = {
        "users": users,
        "traffic_events": traffic_events,
        "orders": orders,
        "daily_metrics": daily_metrics,
        "content_items": content_items,
        "content_events": content_events,
        "experiments": experiments,
        "live_sessions": live_sessions,
        "live_quality_logs": live_quality_logs,
        "live_interactions": live_interactions,
    }
    for frame in tables.values():
        frame.attrs["insightpilot_builtin_scenario"] = "legacy_demo"
    return tables


def generate_multi_table_commerce_data(seed: int = 42) -> dict[str, pd.DataFrame]:
    """Return a deterministic seven-table synthetic dataset for semantic analysis.

    The dataset is deliberately small enough for local execution. Identifiers are
    internally consistent, and the generated behavior supports metric, funnel,
    cohort, join-planning, contract, and lineage demonstrations.
    """

    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp(SYNTHETIC_END_DATE), periods=112, freq="D")
    channels = pd.DataFrame(
        {
            "channel_id": np.arange(1, 5),
            "channel_name": ["自然访问", "站内搜索", "内容推荐", "合作入口"],
        }
    )
    products = pd.DataFrame(
        {
            "product_id": np.arange(1, 81),
            "category": rng.choice(["日常用品", "数字配件", "居家用品", "学习用品"], size=80),
            "unit_price": np.round(rng.uniform(12.0, 260.0, size=80), 2),
        }
    )
    customer_count = 600
    signup_dates = rng.choice(dates[:70], size=customer_count)
    customers = pd.DataFrame(
        {
            "customer_id": np.arange(1, customer_count + 1),
            "signup_date": pd.to_datetime(signup_dates),
            "city": rng.choice(["北城", "南城", "东城", "西城", "中城"], size=customer_count),
            "segment": rng.choice(["新客", "活跃", "回访"], size=customer_count, p=[0.32, 0.46, 0.22]),
        }
    )

    session_count = 4200
    session_customers = rng.choice(customers["customer_id"].to_numpy(), size=session_count)
    signup_lookup = customers.set_index("customer_id")["signup_date"]
    session_dates: list[pd.Timestamp] = []
    for customer_id in session_customers:
        eligible = dates[dates >= pd.Timestamp(signup_lookup.loc[customer_id])]
        session_dates.append(pd.Timestamp(rng.choice(eligible)))
    viewed = rng.binomial(1, 0.76, size=session_count)
    added = viewed * rng.binomial(1, 0.43, size=session_count)
    submitted = added * rng.binomial(1, 0.58, size=session_count)
    paid = submitted * rng.binomial(1, 0.82, size=session_count)
    sessions = pd.DataFrame(
        {
            "session_id": np.arange(1, session_count + 1),
            "customer_id": session_customers,
            "channel_id": rng.choice(channels["channel_id"].to_numpy(), size=session_count),
            "session_date": pd.to_datetime(session_dates),
            "visited": np.ones(session_count, dtype=int),
            "viewed_product": viewed.astype(int),
            "added_to_cart": added.astype(int),
            "submitted_order": submitted.astype(int),
            "paid": paid.astype(int),
        }
    )

    paid_sessions = sessions.loc[sessions["paid"] == 1].reset_index(drop=True)
    orders = pd.DataFrame(
        {
            "order_id": np.arange(1, len(paid_sessions) + 1),
            "customer_id": paid_sessions["customer_id"].to_numpy(),
            "session_id": paid_sessions["session_id"].to_numpy(),
            "order_date": paid_sessions["session_date"].to_numpy(),
            "status": "paid",
            "total_amount": np.zeros(len(paid_sessions), dtype=float),
        }
    )
    item_rows: list[dict[str, object]] = []
    item_id = 1
    product_prices = products.set_index("product_id")["unit_price"]
    order_totals: dict[int, float] = {}
    for order_id in orders["order_id"]:
        total = 0.0
        for _ in range(int(rng.integers(1, 4))):
            product_id = int(rng.choice(products["product_id"].to_numpy()))
            quantity = int(rng.integers(1, 4))
            line_amount = round(float(product_prices.loc[product_id]) * quantity, 2)
            item_rows.append(
                {
                    "order_item_id": item_id,
                    "order_id": int(order_id),
                    "product_id": product_id,
                    "quantity": quantity,
                    "line_amount": line_amount,
                }
            )
            item_id += 1
            total += line_amount
        order_totals[int(order_id)] = round(total, 2)
    order_items = pd.DataFrame(item_rows)
    if not orders.empty:
        orders["total_amount"] = orders["order_id"].map(order_totals).astype(float)

    calendar = pd.DataFrame({"date": dates})
    calendar["week_start"] = calendar["date"].dt.to_period("W").dt.start_time
    calendar["month_start"] = calendar["date"].dt.to_period("M").dt.start_time
    calendar["week_number"] = calendar["date"].dt.isocalendar().week.astype(int)
    # Observed synthetic events are generated from the nested session flags,
    # not inferred from the order fact table. Each journey has explicit order/time.
    event_frames = []
    for stage_index, (flag, name) in enumerate([
        ("visited", "visit"), ("viewed_product", "view"),
        ("added_to_cart", "cart"), ("submitted_order", "submit"), ("paid", "paid"),
    ]):
        stage = sessions.loc[sessions[flag] == 1, ["session_id", "customer_id", "session_date"]].copy()
        stage["event_name"] = name
        stage["event_time"] = stage.pop("session_date") + pd.Timedelta(hours=12, minutes=stage_index * 2)
        event_frames.append(stage)
    events = pd.concat(event_frames, ignore_index=True).sort_values(["session_id", "event_time"]).reset_index(drop=True)
    events.insert(0, "event_id", np.arange(1, len(events) + 1))
    return {
        "events": events,
        "customers": customers,
        "sessions": sessions,
        "orders": orders,
        "order_items": order_items,
        "products": products,
        "channels": channels,
        "calendar": calendar,
    }
