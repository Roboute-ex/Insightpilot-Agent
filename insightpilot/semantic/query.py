"""Metric request and compiled query plan models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from insightpilot.semantic.join_planner import JoinPlan


FILTER_OPERATORS = {"eq", "in", "gt", "gte", "lt", "lte", "between"}
TIME_GRAINS = {"day", "week", "month"}
EXECUTION_MODES = {"plan_only", "execute"}


@dataclass(frozen=True)
class MetricFilter:
    dimension_id: str
    operator: str
    value: Any

    def __post_init__(self) -> None:
        if self.operator not in FILTER_OPERATORS:
            raise ValueError(f"不支持的筛选操作：{self.operator}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricRequest:
    metrics: list[str]
    dimensions: list[str] = field(default_factory=list)
    filters: list[MetricFilter] = field(default_factory=list)
    date_dimension: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    time_grain: str = "day"
    limit: int = 1000
    execution_mode: str = "execute"

    def __post_init__(self) -> None:
        if not self.metrics:
            raise ValueError("MetricRequest 至少需要一个指标。")
        if self.time_grain not in TIME_GRAINS:
            raise ValueError("time_grain 必须为 day、week 或 month。")
        if self.execution_mode not in EXECUTION_MODES:
            raise ValueError("execution_mode 必须为 plan_only 或 execute。")
        if self.limit < 1 or self.limit > 10000:
            raise ValueError("limit 必须在 1 到 10000 之间。")

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "MetricRequest":
        filters = [item if isinstance(item, MetricFilter) else MetricFilter(**item) for item in values.get("filters", [])]
        return cls(
            metrics=[str(item) for item in values.get("metrics", [])],
            dimensions=[str(item) for item in values.get("dimensions", [])],
            filters=filters,
            date_dimension=values.get("date_dimension"),
            date_from=values.get("date_from"),
            date_to=values.get("date_to"),
            time_grain=str(values.get("time_grain", "day")),
            limit=int(values.get("limit", 1000)),
            execution_mode=str(values.get("execution_mode", "execute")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": list(self.metrics),
            "dimensions": list(self.dimensions),
            "filters": [item.to_dict() for item in self.filters],
            "date_dimension": self.date_dimension,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "time_grain": self.time_grain,
            "limit": self.limit,
            "execution_mode": self.execution_mode,
        }


@dataclass
class QueryPlan:
    plan_id: str
    semantic_model_id: str
    request: MetricRequest
    base_entity: str
    metric_dependencies: dict[str, list[str]]
    required_entities: list[str]
    join_plan: JoinPlan
    sql_template: str
    parameters: list[Any]
    output_columns: list[str]
    risk_level: str
    requires_approval: bool
    executable: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "semantic_model_id": self.semantic_model_id,
            "request": self.request.to_dict(),
            "base_entity": self.base_entity,
            "metric_dependencies": {key: list(value) for key, value in self.metric_dependencies.items()},
            "required_entities": list(self.required_entities),
            "join_plan": self.join_plan.to_dict(),
            "sql_template": self.sql_template,
            "parameters": [f"<{type(value).__name__}>" for value in self.parameters],
            "parameter_count": len(self.parameters),
            "output_columns": list(self.output_columns),
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "executable": self.executable,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
