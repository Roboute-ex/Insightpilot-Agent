"""Sparse transaction journeys with reconciled paid-order detail."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import DemoDataset, DemoScale, dates_for, make_users, metadata, ratio, scale_settings

DIMENSIONS = ["city", "region", "channel", "user_segment", "device", "platform", "merchant_type", "payment_method", "customer_type", "campaign", "app_version", "hour_bucket", "weekday", "is_holiday"]


def generate_transaction_scenario(scale: str | DemoScale = "standard", seed: int = 42) -> DemoDataset:
    days, profiles, user_count, merchant_count = scale_settings(scale, {
        "small": (35, 40, 2500, 400), "standard": (180, 200, 20000, 3000), "large": (365, 400, 40000, 6000),
    })
    rng = np.random.default_rng(seed)
    dates = dates_for(days)
    users = make_users(rng, user_count, registered_by=dates.min())
    merchants = pd.DataFrame({"merchant_id": np.arange(1, merchant_count + 1), "merchant_name": [f"模拟商户{i:05d}" for i in range(1, merchant_count + 1)], "merchant_type": rng.choice(["标准商户", "品牌商户", "本地商户"], merchant_count)})
    profile = pd.DataFrame({
        "profile_id": np.arange(profiles),
        "city": rng.choice(["North City", "South City", "East City", "West City", "Central City"], profiles, p=[.2, .3, .2, .15, .15]),
        "channel": rng.choice(["organic", "search", "social", "referral"], profiles, p=[.3, .25, .3, .15]),
        "user_segment": rng.choice(["new", "active", "returning"], profiles, p=[.35, .4, .25]),
        "device": rng.choice(["Android", "iOS", "Web", "Tablet"], profiles, p=[.45, .3, .15, .1]),
        "merchant_type": rng.choice(["标准商户", "品牌商户", "本地商户"], profiles),
        "payment_method": rng.choice(["银行卡", "余额", "快捷支付"], profiles),
        "campaign": rng.choice(["日常", "新客活动", "会员活动"], profiles),
        "app_version": rng.choice(["6.0", "6.1", "6.2"], profiles, p=[.2, .35, .45]),
        "hour_bucket": rng.choice(["00-06", "06-12", "12-18", "18-24"], profiles),
    })
    profile["region"] = profile["city"].map({"North City": "华北", "South City": "华南", "East City": "华东", "West City": "西部", "Central City": "华中"})
    profile["platform"] = np.where(profile["device"].isin(["Web"]), "网页", "移动应用")
    profile["customer_type"] = np.where(profile["user_segment"] == "new", "新客", "老客")
    # Repeat a sparse set of observed profiles, not a Cartesian product of dimensions.
    daily = profile.iloc[np.tile(np.arange(profiles), days)].reset_index(drop=True)
    daily.insert(0, "date", np.repeat(dates, profiles))
    daily["campaign_customer_type"] = daily["campaign"] + " / " + daily["customer_type"]
    daily["weekday"] = daily["date"].dt.dayofweek
    daily["is_holiday"] = daily["weekday"] >= 5
    current = daily["date"] == dates.max()
    recent = daily["date"] >= dates.max() - pd.Timedelta(days=2)
    demand = np.full(len(daily), 105.0)
    demand *= np.where(daily["is_holiday"], 1.05, 1.0)
    demand *= np.where(current & (daily["city"] == "South City"), .28, 1.0)
    demand *= np.where(current & (daily["channel"] == "social"), .38, 1.0)
    demand *= np.where(current & (daily["channel"] == "referral"), 1.12, 1.0)
    daily["impressions"] = rng.poisson(demand)
    daily["clicks"] = rng.binomial(daily["impressions"], .32)
    daily["visitors"] = rng.binomial(daily["clicks"], .88)
    cart_probability = np.where(current & (daily["user_segment"] == "new"), .17, .45)
    daily["add_to_cart_users"] = rng.binomial(daily["visitors"], cart_probability)
    daily["checkout_users"] = rng.binomial(daily["add_to_cart_users"], .72)
    daily["payment_attempts"] = rng.binomial(daily["checkout_users"], .94)
    payment_probability = np.where(recent & (daily["device"] == "Android") & (daily["app_version"] == "6.2"), .48, .965)
    daily["successful_payments"] = rng.binomial(daily["payment_attempts"], payment_probability)
    daily["orders"] = daily["successful_payments"]
    daily["daily_row_id"] = np.arange(len(daily))
    detail = daily.loc[daily.index.repeat(daily["orders"]), ["daily_row_id", "date", *DIMENSIONS]].reset_index(drop=True)
    detail.insert(0, "order_id", np.arange(1, len(detail) + 1))
    detail["journey_id"] = detail["order_id"]
    detail["user_id"] = rng.integers(1, user_count + 1, len(detail))
    # Match the merchant type carried by the aggregate profile.
    detail["merchant_id"] = 0
    for merchant_type, group in detail.groupby("merchant_type"):
        eligible = merchants.loc[merchants["merchant_type"] == merchant_type, "merchant_id"].to_numpy()
        detail.loc[group.index, "merchant_id"] = rng.choice(eligible, len(group))
    detail["amount_cents"] = rng.integers(1200, 24001, len(detail))
    detail["revenue"] = detail["amount_cents"] / 100
    detail["orders"] = 1
    detail["refund_orders"] = rng.binomial(1, .025, len(detail))
    detail["refund_amount_cents"] = detail["amount_cents"] * detail["refund_orders"]
    detail["refund_rate"] = detail["refund_orders"].astype(float)
    detail["refund_amount"] = detail["refund_amount_cents"] / 100
    sums = detail.groupby("daily_row_id")[["amount_cents", "refund_orders", "refund_amount_cents"]].sum()
    for name in sums:
        daily[name] = daily["daily_row_id"].map(sums[name]).fillna(0).astype("int64")
    daily["revenue"] = daily["amount_cents"] / 100
    daily["refund_amount"] = daily["refund_amount_cents"] / 100
    for name, numerator, denominator in [("ctr", "clicks", "impressions"), ("cvr", "orders", "visitors"), ("conversion_rate", "orders", "visitors"), ("payment_success_rate", "successful_payments", "payment_attempts"), ("average_order_value", "revenue", "orders"), ("refund_rate", "refund_orders", "orders")]:
        daily[name] = ratio(daily[numerator], daily[denominator])
    # Entity users are deliberately not invented by multiplying traffic counts.
    daily["active_users"] = daily["daily_row_id"].map(detail.groupby("daily_row_id")["user_id"].nunique()).fillna(0).astype(int)
    daily["active_users_scope"] = "该分组发生支付的去重用户，不可跨分组累加为全站UV"
    tables = {"users": users, "merchants": merchants, "daily_metrics": daily, "transaction_detail": detail,
              "orders": detail.copy(), "traffic_events": daily[["date", "daily_row_id", *DIMENSIONS, "impressions", "clicks", "visitors"]].copy()}
    anomalies = [{"id": "south_city_orders", "dimension": "city", "value": "South City", "period": "reference_date"},
                 {"id": "social_channel_traffic", "dimension": "channel", "value": "social", "period": "reference_date"},
                 {"id": "new_customer_conversion", "dimension": "user_segment", "value": "new", "period": "reference_date"},
                 {"id": "android_version_payment", "dimension": ["device", "app_version"], "value": ["Android", "6.2"], "period": "last_3_days"}]
    return DemoDataset("transaction", tables, metadata("transaction", scale, seed, tables, anomalies,
        dimensions=DIMENSIONS, funnel_unit="单次转化旅程；七阶段均为嵌套旅程计数，历史 *_users 字段名不表示全站去重UV；每次支付最多一张订单。",
        reconciliation="transaction_detail 按 daily_row_id 汇总，订单数、金额分、退款数与 daily_metrics 精确一致。",
        dimension_labels={"North City": "北城", "South City": "南城", "East City": "东城", "West City": "西城", "Central City": "中城", "organic": "自然访问", "search": "搜索", "social": "社交推荐", "referral": "合作入口", "new": "新客", "active": "活跃", "returning": "回访"}))
