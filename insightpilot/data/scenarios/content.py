"""Content exposures, observed playback detail and user-randomized experiments."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import DemoDataset, DemoScale, dates_for, make_users, metadata, ratio, scale_settings

DIMENSIONS = ["content_category", "content_format", "author_tier", "region", "channel", "user_segment", "device", "app_version", "publish_hour", "content_length", "experiment_group"]


def generate_content_scenario(scale: str | DemoScale = "standard", seed: int = 42) -> DemoDataset:
    days, item_count, observations_per_day, assignment_count, user_count = scale_settings(scale, {
        "small": (35, 1200, 50, 1200, 2500), "standard": (120, 20000, 360, 12000, 20000), "large": (240, 40000, 720, 24000, 40000),
    })
    rng = np.random.default_rng(seed)
    dates = dates_for(days)
    users = make_users(rng, user_count, registered_by=dates.min())
    items = pd.DataFrame({
        "content_id": np.arange(1, item_count + 1),
        "content_category": rng.choice(["知识", "生活", "消费", "娱乐"], item_count),
        "content_format": rng.choice(["短视频", "长视频", "音频"], item_count),
        "author_tier": rng.choice(["新作者", "成长作者", "成熟作者"], item_count),
        "content_length": rng.choice(["短内容", "长内容"], item_count),
        "publish_hour": rng.choice(["清晨", "午间", "下午", "晚间"], item_count),
    })
    items["creator_segment"] = items["author_tier"]
    items["duration_seconds"] = np.where(items["content_length"] == "长内容", 300, 60)
    observation_count = days * observations_per_day
    # Every content is observed at least once; subsequent samples are sparse.
    picked = np.tile(rng.permutation(item_count), int(np.ceil(observation_count / item_count)))[:observation_count]
    daily = items.iloc[picked].reset_index(drop=True)
    daily.insert(0, "daily_row_id", np.arange(observation_count))
    daily.insert(0, "date", np.repeat(dates, observations_per_day))
    daily["region"] = rng.choice(["华北", "华南", "华东", "西部"], observation_count)
    daily["channel"] = rng.choice(["自然访问", "搜索", "内容推荐", "合作入口"], observation_count)
    daily["acquisition_channel"] = daily["channel"]
    daily["user_segment"] = rng.choice(["新客", "活跃", "回访"], observation_count)
    daily["device"] = rng.choice(["Android", "iOS", "Web", "Tablet"], observation_count)
    daily["app_version"] = rng.choice(["6.0", "6.1", "6.2"], observation_count)
    daily["experiment_group"] = "非实验流量"
    daily["impressions"] = rng.integers(12, 31, observation_count)
    daily["clicks"] = rng.binomial(daily["impressions"], .6)
    # At least one exposure progresses to playback; clicks remain upstream.
    daily["clicks"] = daily["clicks"].clip(lower=1)
    daily["plays"] = np.minimum(daily["clicks"], rng.integers(1, 5, observation_count))
    events = daily.loc[daily.index.repeat(daily["plays"]), ["date", "daily_row_id", "content_id", "duration_seconds", *DIMENSIONS]].reset_index(drop=True)
    events.insert(0, "event_id", np.arange(1, len(events) + 1))
    events["length_device"] = events["content_length"] + " / " + events["device"]
    events["user_id"] = rng.integers(1, user_count + 1, len(events))
    probabilities = np.full(len(events), .57)
    probabilities += np.where(events["content_category"] == "知识", .1, 0)
    probabilities += np.where(events["content_category"] == "娱乐", .04, 0)
    probabilities -= np.where((events["content_length"] == "长内容") & (events["device"] == "Android"), .18, 0)
    probabilities += np.where(events["author_tier"] == "成熟作者", .025, 0)
    events["completed"] = rng.binomial(1, probabilities)
    events["completion_rate"] = events["completed"].astype(float)
    fraction = np.where(events["completed"] == 1, 1, rng.uniform(.05, .92, len(events)))
    events["watch_time"] = (fraction * events["duration_seconds"]).round(2)
    events["retained"] = rng.binomial(1, np.clip(probabilities - .12, 0, 1))
    events["retention_rate"] = events["retained"].astype(float)
    for name, probability in [("likes", .13), ("comments", .035), ("shares", .045), ("follows", .025)]:
        events[name] = rng.binomial(1, probability, len(events))
    events["engaged"] = (events[["likes", "comments", "shares", "follows"]].sum(axis=1) > 0).astype(int)
    events["interaction_rate"] = events["engaged"].astype(float)
    aggregation = events.groupby("daily_row_id").agg(completed=("completed", "sum"), watch_time_total=("watch_time", "sum"), retained=("retained", "sum"), likes=("likes", "sum"), comments=("comments", "sum"), shares=("shares", "sum"), follows=("follows", "sum"), engaged=("engaged", "sum"))
    daily = daily.join(aggregation, on="daily_row_id")
    for name, numerator, denominator in [("ctr", "clicks", "impressions"), ("completion_rate", "completed", "plays"), ("engagement_rate", "engaged", "plays"), ("interaction_rate", "engaged", "plays"), ("retention_rate", "retained", "plays"), ("watch_time", "watch_time_total", "plays")]:
        daily[name] = ratio(daily[numerator], daily[denominator])
    assignments = users.sample(assignment_count, random_state=seed).reset_index(drop=True).copy()
    groups = np.array(["control", "treatment"] * (assignment_count // 2))
    rng.shuffle(groups)
    assignments["experiment_id"] = "content_strategy_local"
    assignments["group"] = groups
    assignments["experiment_group"] = groups
    assignments["date"] = dates.max()
    assignments["device"] = rng.choice(["Android", "iOS", "Web", "Tablet"], assignment_count)
    assignments["plays"] = rng.integers(15, 36, assignment_count)
    completion_probability = np.clip(.51 + assignments["historical_activity"].to_numpy() * .001 + (groups == "treatment") * .025 + rng.normal(0, .11, assignment_count), .05, .95)
    assignments["completed_count"] = rng.binomial(assignments["plays"], completion_probability)
    assignments["completion_rate"] = assignments["completed_count"] / assignments["plays"]
    assignments["completed"] = rng.binomial(1, completion_probability)
    assignments["watch_time"] = (40 + assignments["completion_rate"] * 85 + rng.normal(0, 12, assignment_count)).round(2)
    tables = {"users": users, "content_items": items, "content_daily_metrics": daily, "content_events": events,
              "experiment_assignments": assignments, "experiments": assignments.copy()}
    anomalies = [{"id": "content_strategy_completion_lift", "unit": "user_id", "outcome": "observed completed_count / plays", "assignment": "balanced shuffled randomized"},
                 {"id": "category_completion_difference", "dimension": "content_category"},
                 {"id": "long_content_android", "dimension": ["content_length", "device"], "value": ["长内容", "Android"]}]
    return DemoDataset("content", tables, metadata("content", scale, seed, tables, anomalies, dimensions=DIMENSIONS,
        experiment_unit="每行一名唯一用户，随机分组；completion_rate 为该用户观测播放的完播比例；用户均值差使用 Welch t 检验，非逐播放独立检验。",
        reconciliation="content_daily_metrics 的 plays/completed/watch_time_total/互动计数来自 content_events；实验用户来自独立实验观察窗口，不与自然流量重复汇总。",
        retention_note="retained 为模拟后续观察结果；真正队列留存请使用多表 cohort_retention 剧本。"))
