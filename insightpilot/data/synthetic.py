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
        orders = int(round(clicks * cvr * payment_success_rate))
        price = rng.normal(74, 12)
        revenue = max(0.0, orders * price)
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
                "orders": orders,
                "revenue": round(revenue, 2),
                "ctr": clicks / impressions if impressions else 0.0,
                "cvr": orders / clicks if clicks else 0.0,
                "payment_success_rate": payment_success_rate,
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
    return {
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
