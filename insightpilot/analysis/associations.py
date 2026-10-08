"""Descriptive quality/conversion association at explicit session and group grains."""
from __future__ import annotations
import numpy as np
import pandas as pd


def quality_conversion_association(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    required = {"session_id", "stutter_rate", "conversion_rate"}
    if not required.issubset(frame.columns):
        raise ValueError("关联分析需要同会话 session_id、stutter_rate、conversion_rate；不连接无法核对单位的汇总表。")
    if frame["session_id"].isna().any() or frame["session_id"].duplicated().any():
        raise ValueError("关联分析会话键必须非空且唯一，请先核对重复记录。")
    working = frame.copy()
    for column in ["stutter_rate", "conversion_rate"]:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.replace([np.inf, -np.inf], np.nan).dropna(subset=["stutter_rate", "conversion_rate"])
    if len(working) < 3:
        raise ValueError("质量/转化有效配对少于3个会话，无法计算相关系数。")
    r = float(working["stutter_rate"].corr(working["conversion_rate"])) if working["stutter_rate"].nunique() > 1 and working["conversion_rate"].nunique() > 1 else None
    repeated_users = bool("user_id" in working and working["user_id"].duplicated().any())
    note = "描述性Pearson相关，按会话配对；不检验因果，不输出独立样本显著性。"
    if repeated_users:
        note += "同一用户可能多次会话，样本量是会话数量，并非独立用户数量。"
    summary = pd.DataFrame([{"quality_metric": "stutter_rate", "outcome_metric": "conversion_rate", "statistical_unit": "session_id", "sample_size": len(working), "unique_users": int(working["user_id"].nunique()) if "user_id" in working else None, "pearson_correlation": r, "quality_mean": float(working["stutter_rate"].mean()), "conversion_rate": float(working["conversion_rate"].mean()), "method": "descriptive_pearson_at_session_grain", "limitations": note}])
    dimensions = [column for column in ["device", "network_type"] if column in working]
    groups = working.groupby(dimensions, dropna=False).agg(sample_size=("session_id", "nunique"), stutter_rate=("stutter_rate", "mean"), conversion_rate=("conversion_rate", "mean")).reset_index() if dimensions else pd.DataFrame()
    if not groups.empty:
        groups["statistical_unit"] = "设备×网络分组内会话等权均值"
        groups["low_sample"] = groups["sample_size"] < 30
    return {"quality_conversion_association": summary, "quality_conversion_groups": groups}
