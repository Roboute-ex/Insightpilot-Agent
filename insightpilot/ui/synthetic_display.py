"""Chinese display aliases only for built-in synthetic data; stable IDs are preserved."""
from __future__ import annotations

import re
from typing import Any

SYNTHETIC_LABELS = {
    'North City': '北城', 'South City': '南城', 'East City': '东城', 'West City': '西城', 'Central City': '中城',
    'city': '城市', 'region': '区域', 'channel': '渠道', 'user_segment': '用户分层',
    'device': '设备', 'device_type': '设备', 'platform': '平台', 'merchant_type': '商户类型',
    'payment_method': '支付方式', 'customer_type': '新老客', 'campaign': '活动', 'app_version': '应用版本',
    'hour_bucket': '时段', 'weekday': '星期', 'is_holiday': '节假日',
    'network_type': '网络类型', 'content_category': '内容分类', 'author_level': '作者层级',
    'host_tier': '主播层级', 'live_category': '直播类别', 'content_format': '内容形式',
    'organic': '自然访问', 'search': '搜索', 'social': '社交推荐', 'referral': '合作入口',
    'new': '新客', 'active': '活跃用户', 'returning': '回访用户', 'Others': '其他',
    'Tablet': '平板', 'Mobile': '移动网络', 'Web': '网页', 'Cellular': '移动网络',
    'HIGH': '高风险', 'MEDIUM': '需要关注', 'LOW': '正常波动',
}


def synthetic_display_text(value: Any) -> str:
    text = str(value if value is not None else '')
    for key in sorted(SYNTHETIC_LABELS, key=len, reverse=True):
        text = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])', SYNTHETIC_LABELS[key], text)
    return text


def synthetic_display_object(value: Any) -> Any:
    if isinstance(value, str):
        return synthetic_display_text(value)
    if isinstance(value, dict):
        return {key: synthetic_display_object(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [synthetic_display_object(item) for item in value]
    if hasattr(value, "tolist"):
        return synthetic_display_object(value.tolist())
    return value
