"""Deterministic, independently generated scenario datasets."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from insightpilot.config import SYNTHETIC_END_DATE


class DemoScale(str, Enum):
    SMALL = "small"
    STANDARD = "standard"
    LARGE = "large"


@dataclass
class DemoDataset:
    scenario: str
    tables: dict[str, pd.DataFrame]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        # This records generator provenance only, never injected anomaly truth.
        for frame in self.tables.values():
            frame.attrs["insightpilot_builtin_scenario"] = self.scenario


def scale_settings(scale: str | DemoScale, sizes: dict[str, tuple[int, ...]]) -> tuple[int, ...]:
    try:
        return sizes[DemoScale(scale).value]
    except (ValueError, KeyError) as exc:
        raise ValueError("规模必须为 small、standard 或 large。") from exc


def dates_for(days: int) -> pd.DatetimeIndex:
    return pd.date_range(end=pd.Timestamp(SYNTHETIC_END_DATE), periods=days, freq="D")


def metadata(scenario: str, scale: str | DemoScale, seed: int, tables: dict[str, pd.DataFrame], anomalies: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "scenario": scenario, "scale": DemoScale(scale).value, "seed": seed,
        "reference_date": SYNTHETIC_END_DATE,
        "yesterday_note": "演示中的昨日指固定数据参考日，不是电脑当天的前一天。",
        "source_type": "synthetic", "row_counts": {name: len(frame) for name, frame in tables.items()},
        "injected_anomalies": anomalies,
        "ground_truth_usage": "仅供生成器验证与评估；分析器不得读取此元数据推断答案。",
        **extra,
    }


def ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def make_users(rng: np.random.Generator, count: int, *, registered_by: pd.Timestamp | None = None) -> pd.DataFrame:
    # Users are eligible before observation starts. Shift the whole enrollment
    # window when needed, preserving its spread and the random stream used by
    # subsequent transaction, experiment and quality measurements.
    enrollment_end = pd.Timestamp("2025-01-01") + pd.Timedelta(days=299)
    if registered_by is not None:
        enrollment_end = min(enrollment_end, pd.Timestamp(registered_by).normalize())
    return pd.DataFrame({
        "user_id": np.arange(1, count + 1),
        "signup_date": rng.choice(pd.date_range(end=enrollment_end, periods=300), count),
        "city": rng.choice(["North City", "South City", "East City", "West City", "Central City"], count),
        "channel": rng.choice(["organic", "search", "social", "referral"], count),
        "user_segment": rng.choice(["new", "active", "returning"], count),
        "historical_activity": rng.gamma(4, 8, count).round(2),
        "historical_revenue": rng.gamma(2.2, 35, count).round(2),
    })
