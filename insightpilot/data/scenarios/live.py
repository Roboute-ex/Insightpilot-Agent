"""Session-grain live quality measurements and their daily summaries."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import DemoDataset, DemoScale, dates_for, make_users, metadata, ratio, scale_settings

DIMENSIONS = ["city", "region", "device", "network_type", "carrier", "app_version", "host_tier", "live_category", "user_segment", "hour_bucket"]


def _generate_broadcasts(scale: str | DemoScale, seed: int, dates: pd.DatetimeIndex,
                         sessions_per_day: int) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    broadcasts_per_day, host_count = scale_settings(scale, {
        "small": (60, 180), "standard": (560, 8000), "large": (1000, 12000),
    })
    # Independent stream preserves the established viewer-level quality signals.
    rng = np.random.default_rng(np.random.SeedSequence([seed, 9001]))
    hosts = pd.DataFrame({
        "host_id": np.arange(1, host_count + 1),
        "host_name": [f"模拟主播{i:05d}" for i in range(1, host_count + 1)],
        "host_tier": rng.choice(["新主播", "成长主播", "成熟主播"], host_count),
        "primary_category": rng.choice(["知识分享", "娱乐互动", "生活交流", "消费介绍"], host_count),
    })
    count = len(dates) * broadcasts_per_day
    # A host broadcasts at most once on a day; repeated broadcasts across days
    # are separate records with their own start and end times.
    host_ids = np.concatenate([rng.choice(hosts["host_id"], broadcasts_per_day, replace=False) for _ in dates])
    hour = rng.integers(0, 22, count)
    duration = rng.integers(30, 121, count) * 60
    broadcasts = pd.DataFrame({
        "broadcast_id": np.arange(1, count + 1), "host_id": host_ids,
        "date": np.repeat(dates, broadcasts_per_day),
        "start_time": np.repeat(dates, broadcasts_per_day) + pd.to_timedelta(hour, unit="h"),
        "broadcast_duration_seconds": duration, "broadcasts": 1,
    })
    broadcasts["end_time"] = broadcasts["start_time"] + pd.to_timedelta(duration, unit="s")
    lookup = hosts.set_index("host_id")
    broadcasts["host_tier"] = broadcasts["host_id"].map(lookup["host_tier"])
    broadcasts["live_category"] = broadcasts["host_id"].map(lookup["primary_category"])
    broadcasts["hour_bucket"] = np.array(["00-06", "06-12", "12-18", "18-24"])[hour // 6]
    assignments = []
    for day in range(len(dates)):
        ids = broadcasts["broadcast_id"].iloc[day * broadcasts_per_day:(day + 1) * broadcasts_per_day].to_numpy()
        selected = np.concatenate([ids, rng.choice(ids, sessions_per_day - broadcasts_per_day, replace=True)])
        rng.shuffle(selected)
        assignments.append(selected)
    return hosts, broadcasts, np.concatenate(assignments)


def generate_live_scenario(scale: str | DemoScale = "standard", seed: int = 42) -> DemoDataset:
    days, sessions_per_day, user_count = scale_settings(scale, {
        "small": (35, 80, 2500), "standard": (90, 600, 20000), "large": (180, 1200, 40000),
    })
    rng = np.random.default_rng(seed)
    dates = dates_for(days)
    users = make_users(rng, user_count, registered_by=dates.min())
    hosts, broadcasts, broadcast_ids = _generate_broadcasts(scale, seed, dates, sessions_per_day)
    count = days * sessions_per_day
    sessions = pd.DataFrame({
        "session_id": np.arange(1, count + 1), "date": np.repeat(dates, sessions_per_day),
        "user_id": rng.integers(1, user_count + 1, count),
        "city": rng.choice(["北城", "南城", "东城", "西城", "中城"], count),
        "device": rng.choice(["Android", "iOS", "Web", "Tablet"], count, p=[.35, .3, .15, .2]),
        "network_type": rng.choice(["WiFi", "Cellular", "Wired"], count, p=[.45, .45, .1]),
        "carrier": rng.choice(["运营商甲", "运营商乙", "运营商丙"], count),
        "app_version": rng.choice(["6.0", "6.1", "6.2"], count, p=[.2, .4, .4]),
        "host_tier": rng.choice(["新主播", "成长主播", "成熟主播"], count),
        "live_category": rng.choice(["知识分享", "娱乐互动", "生活交流", "消费介绍"], count),
        "user_segment": rng.choice(["新客", "活跃", "回访"], count),
        "hour_bucket": rng.choice(["00-06", "06-12", "12-18", "18-24"], count),
    })
    sessions["broadcast_id"] = broadcast_ids
    broadcast_lookup = broadcasts.set_index("broadcast_id")
    for column in ["host_id", "host_tier", "live_category", "hour_bucket"]:
        sessions[column] = sessions["broadcast_id"].map(broadcast_lookup[column])
    sessions["session_start_time"] = sessions["broadcast_id"].map(broadcast_lookup["start_time"]) + pd.Timedelta(minutes=5)
    sessions["region"] = sessions["city"].map({"北城": "华北", "南城": "华南", "东城": "华东", "西城": "西部", "中城": "华中"})
    recent = sessions["date"] >= dates.max() - pd.Timedelta(days=2)
    risky = recent & (sessions["device"] == "Tablet") & (sessions["network_type"] == "Cellular")
    version_risk = recent & (sessions["app_version"] == "6.2")
    sessions["device_network"] = sessions["device"] + " / " + sessions["network_type"]
    sessions["viewers"] = 1  # One viewer-session, not a broadcast with repeated viewer logs.
    sessions["sessions"] = 1
    sessions["observation_seconds"] = 600
    sessions["buffering_seconds"] = np.clip(rng.normal(24, 7, count) + risky * 125, 0, 260).round(2)
    sessions["buffering_rate"] = sessions["buffering_seconds"] / sessions["observation_seconds"]
    sessions["stutter_rate"] = sessions["buffering_rate"]
    sessions["crashed"] = rng.binomial(1, np.where(version_risk, .13, .008))
    sessions["crash_rate"] = sessions["crashed"].astype(float)
    sessions["startup_latency"] = np.clip(rng.normal(115, 20, count) + risky * 90 + version_risk * 20, 25, 450).round(2)
    sessions["latency_ms"] = sessions["startup_latency"]
    sessions["watch_time"] = np.clip(rng.normal(490, 90, count) - risky * 170 - sessions["crashed"] * 100, 30, 600).round(2)
    sessions["session_end_time"] = sessions["session_start_time"] + pd.to_timedelta(sessions["watch_time"], unit="s")
    sessions["interaction_count"] = rng.binomial(1, np.where(risky, .08, .18))
    sessions["interaction_rate"] = sessions["interaction_count"].astype(float)
    sessions["converted"] = rng.binomial(1, np.where(risky, .035, .09))
    sessions["conversion_rate"] = sessions["converted"].astype(float)
    keys = ["date", *DIMENSIONS]
    daily = sessions.groupby(keys, as_index=False).agg(sessions=("session_id", "size"), viewers=("viewers", "sum"), buffering_seconds=("buffering_seconds", "sum"), observation_seconds=("observation_seconds", "sum"), crashed=("crashed", "sum"), startup_latency_total=("startup_latency", "sum"), watch_time_total=("watch_time", "sum"), interaction_count=("interaction_count", "sum"), converted=("converted", "sum"))
    for name, numerator, denominator in [("buffering_rate", "buffering_seconds", "observation_seconds"), ("crash_rate", "crashed", "sessions"), ("startup_latency", "startup_latency_total", "sessions"), ("watch_time", "watch_time_total", "sessions"), ("interaction_rate", "interaction_count", "sessions"), ("conversion_rate", "converted", "sessions")]:
        daily[name] = ratio(daily[numerator], daily[denominator])
    daily["stutter_rate"] = daily["buffering_rate"]
    daily["latency_ms"] = daily["startup_latency"]
    quality = sessions[["session_id", *keys, "buffering_seconds", "observation_seconds", "stutter_rate", "buffering_rate", "crashed", "crash_rate", "startup_latency", "latency_ms"]].copy()
    quality.insert(0, "log_id", np.arange(1, count + 1))
    interactions = sessions[["session_id", *keys, "interaction_count", "interaction_rate", "converted", "conversion_rate"]].copy()
    interactions.insert(0, "interaction_id", np.arange(1, count + 1))
    observed = sessions.groupby("broadcast_id").agg(observed_sessions=("session_id", "size"), observed_viewers=("user_id", "nunique"), observed_watch_time_total=("watch_time", "sum"))
    broadcasts = broadcasts.join(observed, on="broadcast_id")
    tables = {"live_hosts": hosts, "live_broadcasts": broadcasts, "users": users, "live_sessions": sessions, "live_quality_logs": quality, "live_interactions": interactions, "live_daily_metrics": daily}
    anomalies = [{"id": "tablet_cellular_buffering", "dimension": ["device", "network_type"], "value": ["Tablet", "Cellular"], "period": "last_3_days"},
                 {"id": "version_crash", "dimension": "app_version", "value": "6.2", "period": "last_3_days"},
                 {"id": "risky_watch_time_drop", "dimension": ["device", "network_type"], "value": ["Tablet", "Cellular"]}]
    return DemoDataset("live", tables, metadata("live", scale, seed, tables, anomalies, dimensions=DIMENSIONS,
        broadcast_unit="live_broadcasts每行是独立主播开播，有唯一broadcast_id、host_id及开始结束时间；观看会话通过外键关联。",
        audience_coverage="观看人数仅指模拟观测会话内去重user_id，不代表每场完整观众覆盖；场次、观看会话数、去重观众数分别统计。",
        session_unit="一行是一个观众观看会话；不是独立主播开播场。跨会话用户数须按 user_id 去重。",
        reconciliation="每日计数/时长总量均从唯一 session_id 聚合；质量和互动各恰好一行/会话，不做重复日志扩张。",
        stable_groups="非6.2版本的WiFi/Wired会话没有注入退化；随机波动仍存在。"))
