"""Data models for reusable deterministic analysis playbooks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from insightpilot.ingestion.mapping import ColumnMapping


PARAMETER_TYPES = {
    "string",
    "integer",
    "float",
    "boolean",
    "date",
    "column",
    "metric_columns",
    "dimension_columns",
    "date_range",
    "choice",
    "metric",
    "dimensions",
}
PLAYBOOK_STATUSES = {"PASS", "WARN", "FAIL"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {
            "row_count": int(len(value)),
            "column_count": int(len(value.columns)),
            "columns": [str(column) for column in value.columns],
        }
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


@dataclass(frozen=True)
class AnalysisParameter:
    name: str
    display_name: str
    parameter_type: str
    required: bool = False
    default: object | None = None
    choices: list[object] = field(default_factory=list)
    description: str = ""

    def __post_init__(self) -> None:
        if self.parameter_type not in PARAMETER_TYPES:
            raise ValueError(f"不支持的 playbook 参数类型：{self.parameter_type}")

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class PlaybookRequirements:
    requires_table: bool = True
    requires_date_column: bool = False
    requires_metric_columns: bool = False
    requires_dimension_columns: bool = False
    requires_group_column: bool = False
    requires_treatment_column: bool = False
    requires_outcome_column: bool = False
    minimum_rows: int = 1
    required_tables: list[str] = field(default_factory=list)
    requires_semantic_model: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisPlaybook:
    playbook_id: str
    display_name: str
    description: str
    supported_goal_modes: list[str]
    requirements: PlaybookRequirements
    parameters: list[AnalysisParameter]
    executor_name: str
    chart_types: list[str]
    output_sections: list[str]
    tags: list[str]
    version: str = "1.0"
    field_requirements_zh: list[str] = field(default_factory=list)
    result_description_zh: str = ""
    caveats_zh: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "display_name": self.display_name,
            "description": self.description,
            "supported_goal_modes": list(self.supported_goal_modes),
            "requirements": self.requirements.to_dict(),
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "executor_name": self.executor_name,
            "chart_types": list(self.chart_types),
            "output_sections": list(self.output_sections),
            "tags": list(self.tags),
            "version": self.version,
            "field_requirements_zh": list(self.field_requirements_zh),
            "result_description_zh": self.result_description_zh,
            "caveats_zh": list(self.caveats_zh),
        }

    def supports_goal_mode(self, goal_mode: str) -> bool:
        return goal_mode == "auto" or goal_mode in self.supported_goal_modes

    def validate_mapping(self, mapping: ColumnMapping) -> list[str]:
        requirements = self.requirements
        errors: list[str] = []
        if requirements.requires_table and not mapping.table_name:
            errors.append("当前分析剧本需要选择目标表。")
        if requirements.requires_date_column and not mapping.date_column:
            errors.append("当前分析剧本需要 date_column。")
        if requirements.requires_metric_columns and not mapping.metric_columns:
            errors.append("当前分析剧本需要至少一个 metric_column。")
        if requirements.requires_dimension_columns and not mapping.dimension_columns:
            errors.append("当前分析剧本需要至少一个 dimension_column。")
        if requirements.requires_group_column and not mapping.group_column:
            errors.append("当前分析剧本需要 group_column。")
        if requirements.requires_treatment_column and not mapping.treatment_column:
            errors.append("当前分析剧本需要 treatment_column。")
        if requirements.requires_outcome_column and not mapping.outcome_column:
            errors.append("当前分析剧本需要 outcome_column。")
        return errors

    def required_parameter_names(self) -> list[str]:
        return [parameter.name for parameter in self.parameters if parameter.required]


@dataclass
class PlaybookExecutionResult:
    playbook_id: str
    playbook_name: str
    status: str
    parameters: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    result_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    executed_queries: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in PLAYBOOK_STATUSES:
            raise ValueError(f"不支持的 playbook status：{self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "playbook_name": self.playbook_name,
            "status": self.status,
            "parameters": _json_safe(self.parameters),
            "findings": list(self.findings),
            "caveats": list(self.caveats),
            "result_tables": {
                name: _json_safe(frame) for name, frame in self.result_tables.items()
            },
            "chart_specs": _json_safe(self.chart_specs),
            "executed_queries": _json_safe(self.executed_queries),
            "warnings": list(self.warnings),
            "metadata": _json_safe(self.metadata),
        }
