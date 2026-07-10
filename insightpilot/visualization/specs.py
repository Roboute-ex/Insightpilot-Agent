"""Serializable chart specifications for deterministic visual diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SUPPORTED_CHART_TYPES = {
    "metric_card",
    "time_series",
    "line",
    "bar",
    "grouped_bar",
    "contribution_bar",
    "histogram",
    "box",
    "missingness_bar",
    "confidence_interval",
    "table",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    return value


@dataclass
class ChartSpec:
    chart_id: str
    chart_type: str
    title: str
    table_key: str
    x: str | None = None
    y: list[str] = field(default_factory=list)
    color: str | None = None
    facet: str | None = None
    aggregation: str | None = None
    sort: str | None = None
    top_n: int | None = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.chart_type not in SUPPORTED_CHART_TYPES:
            raise ValueError(f"不支持的 chart_type：{self.chart_type}")

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ChartSpec":
        field_names = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in field_names})
