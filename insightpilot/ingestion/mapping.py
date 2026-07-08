"""Column mapping utilities for custom data workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from insightpilot.ingestion.schema_mapper import infer_schema_mapping


ALLOWED_TIME_GRAINS = {"day", "week", "month"}


@dataclass
class ColumnMapping:
    table_name: str | None = None
    date_column: str | None = None
    metric_columns: list[str] = field(default_factory=list)
    dimension_columns: list[str] = field(default_factory=list)
    group_column: str | None = None
    treatment_column: str | None = None
    outcome_column: str | None = None
    time_grain: str = "day"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_empty(self) -> bool:
        return not any(
            [
                self.table_name,
                self.date_column,
                self.metric_columns,
                self.dimension_columns,
                self.group_column,
                self.treatment_column,
                self.outcome_column,
            ]
        )

    def has_trend_mapping(self) -> bool:
        return bool(self.date_column and self.metric_columns)

    def has_experiment_mapping(self) -> bool:
        return bool(self.group_column and self.metric_columns)

    def has_causal_mapping(self) -> bool:
        return bool(self.treatment_column and self.outcome_column)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _valid_column(value: Any, available_columns: list[str], warnings: list[str], field_name: str) -> str | None:
    if value in (None, ""):
        return None
    column = str(value)
    if column not in available_columns:
        warnings.append(f"{field_name} 指定的列不存在，已忽略：{column}")
        return None
    return column


def _valid_columns(values: Any, available_columns: list[str], warnings: list[str], field_name: str) -> list[str]:
    valid: list[str] = []
    for column in _as_list(values):
        if column in available_columns:
            valid.append(column)
        else:
            warnings.append(f"{field_name} 指定的列不存在，已忽略：{column}")
    return valid


def normalize_column_mapping(
    mapping: ColumnMapping | dict[str, Any] | None,
    available_columns: list[str],
) -> ColumnMapping:
    """Normalize mapping input and remove columns that are not available."""

    warnings: list[str] = []
    if mapping is None:
        return ColumnMapping()
    if isinstance(mapping, ColumnMapping):
        raw = mapping.to_dict()
    elif isinstance(mapping, dict):
        raw = dict(mapping)
    else:
        warnings.append("column_mapping 类型不支持，已忽略。")
        return ColumnMapping(notes=warnings)

    normalized = ColumnMapping(
        table_name=str(raw.get("table_name")) if raw.get("table_name") not in (None, "") else None,
        date_column=_valid_column(raw.get("date_column"), available_columns, warnings, "date_column"),
        metric_columns=_valid_columns(raw.get("metric_columns"), available_columns, warnings, "metric_columns"),
        dimension_columns=_valid_columns(raw.get("dimension_columns"), available_columns, warnings, "dimension_columns"),
        group_column=_valid_column(raw.get("group_column"), available_columns, warnings, "group_column"),
        treatment_column=_valid_column(raw.get("treatment_column"), available_columns, warnings, "treatment_column"),
        outcome_column=_valid_column(raw.get("outcome_column"), available_columns, warnings, "outcome_column"),
        time_grain=str(raw.get("time_grain") or "day"),
        notes=_as_list(raw.get("notes")),
    )
    if normalized.time_grain not in ALLOWED_TIME_GRAINS:
        warnings.append(f"time_grain={normalized.time_grain} 不受支持，已回退到 day。")
        normalized.time_grain = "day"
    normalized.notes.extend(warnings)
    return normalized


def validate_column_mapping(mapping: ColumnMapping, available_columns: list[str]) -> list[str]:
    """Return non-blocking mapping warnings."""

    warnings: list[str] = []
    for field_name, value in [
        ("date_column", mapping.date_column),
        ("group_column", mapping.group_column),
        ("treatment_column", mapping.treatment_column),
        ("outcome_column", mapping.outcome_column),
    ]:
        if value and value not in available_columns:
            warnings.append(f"{field_name} 指定的列不存在：{value}")
    for field_name, values in [
        ("metric_columns", mapping.metric_columns),
        ("dimension_columns", mapping.dimension_columns),
    ]:
        for value in values:
            if value not in available_columns:
                warnings.append(f"{field_name} 指定的列不存在：{value}")
    if mapping.time_grain not in ALLOWED_TIME_GRAINS:
        warnings.append(f"time_grain 必须为 day/week/month，当前为：{mapping.time_grain}")
    return warnings


def suggest_column_mapping(table_name: str, df: pd.DataFrame) -> ColumnMapping:
    """Suggest a default ColumnMapping from schema inference."""

    suggestion = infer_schema_mapping(table_name, df)
    return ColumnMapping(
        table_name=table_name,
        date_column=next(iter(suggestion.detected_date_columns), None),
        metric_columns=list(suggestion.possible_metric_columns[:3]),
        dimension_columns=list(suggestion.possible_dimension_columns[:5]),
        group_column=None,
        treatment_column=None,
        outcome_column=next(iter(suggestion.possible_metric_columns), None),
        time_grain="day",
        notes=list(suggestion.warnings),
    )
