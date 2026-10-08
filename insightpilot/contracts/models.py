"""JSON-serializable data contract models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CONTRACT_SEVERITIES = {"info", "warning", "error"}
CONTRACT_STATUSES = {"PASS", "WARN", "FAIL"}


@dataclass(frozen=True)
class ColumnContract:
    column_name: str
    data_type: str | None = None
    nullable: bool = True
    unique: bool = False
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: list[Any] = field(default_factory=list)
    severity: str = "error"

    def __post_init__(self) -> None:
        if self.severity not in CONTRACT_SEVERITIES:
            raise ValueError(f"不支持的 contract severity：{self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TableContract:
    table_name: str
    columns: list[ColumnContract] = field(default_factory=list)
    minimum_rows: int = 1
    maximum_rows: int | None = None
    unique_key: list[str] = field(default_factory=list)
    severity: str = "error"

    freshness_column: str | None = None
    maximum_age_days: float | None = None
    reference_time: str | None = None

    def __post_init__(self) -> None:
        if self.minimum_rows < 0:
            raise ValueError("minimum_rows 不能小于 0。")
        if self.severity not in CONTRACT_SEVERITIES:
            raise ValueError(f"不支持的 contract severity：{self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "columns": [item.to_dict() for item in self.columns]}


@dataclass(frozen=True)
class MetricContract:
    metric_id: str
    nullable: bool = False
    minimum: float | None = None
    maximum: float | None = None
    severity: str = "warning"

    def __post_init__(self) -> None:
        if self.severity not in CONTRACT_SEVERITIES:
            raise ValueError(f"不支持的 contract severity：{self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContractCheckResult:
    check_name: str
    object_name: str
    actual_value: Any
    expected_value: Any
    severity: str
    status: str
    message: str

    def __post_init__(self) -> None:
        if self.severity not in CONTRACT_SEVERITIES:
            raise ValueError(f"不支持的 contract severity：{self.severity}")
        if self.status not in CONTRACT_STATUSES:
            raise ValueError(f"不支持的 contract status：{self.status}")

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
