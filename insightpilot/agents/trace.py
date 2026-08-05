"""Trace model for analysis runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pandas as pd


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {
            "type": "DataFrame",
            "row_count": int(len(value)),
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


def _normalize_query_record(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        normalized = {
            "tool": str(record.get("tool", "unknown")),
            "purpose": str(record.get("purpose", "")),
            "query": str(record.get("query", "")),
            "row_count": int(record.get("row_count", 0) or 0),
            "status": str(record.get("status", "success")),
        }
        if record.get("template_id"):
            normalized["template_id"] = str(record["template_id"])
        if record.get("referenced_tables"):
            normalized["referenced_tables"] = list(record["referenced_tables"])
        if record.get("referenced_columns"):
            normalized["referenced_columns"] = list(record["referenced_columns"])
        return normalized
    return {
        "tool": "legacy",
        "purpose": "legacy_query_record",
        "query": str(record),
        "row_count": 0,
        "status": "success",
    }


@dataclass
class AnalysisTrace:
    user_question: str
    identified_intent: str
    selected_metrics: list[str]
    analysis_plan: dict[str, Any]
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    workflow_backend: str = "rule_based"
    goal_mode: str = ""
    goal_mode_display_name: str = ""
    goal_mode_source: str = ""
    data_source_type: str = "synthetic"
    table_metadata_summary: dict[str, Any] = field(default_factory=dict)
    schema_warnings: list[str] = field(default_factory=list)
    column_mapping: dict[str, Any] = field(default_factory=dict)
    mapping_warnings: list[str] = field(default_factory=list)
    mapping_source: str = "none"
    selected_playbook_id: str | None = None
    playbook_source: str = "none"
    playbook_parameters_summary: dict[str, Any] = field(default_factory=dict)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    manifest_summary: dict[str, Any] = field(default_factory=dict)
    playbook_result_summary: dict[str, Any] = field(default_factory=dict)
    executed_queries: list[Any] = field(default_factory=list)
    route_taken: list[str] = field(default_factory=list)
    generated_findings: list[str] = field(default_factory=list)
    caveats: list[Any] = field(default_factory=list)
    semantic_model_summary: dict[str, Any] = field(default_factory=dict)
    metric_request: dict[str, Any] = field(default_factory=dict)
    join_plan_summary: dict[str, Any] = field(default_factory=dict)
    query_plan_summary: dict[str, Any] = field(default_factory=dict)
    plan_review: dict[str, Any] = field(default_factory=dict)
    contract_summary: dict[str, Any] = field(default_factory=dict)
    lineage_summary: dict[str, Any] = field(default_factory=dict)
    observability_summary: dict[str, Any] = field(default_factory=dict)
    evaluation_summary: dict[str, Any] = field(default_factory=dict)
    analysis_result_summary: dict[str, Any] = field(default_factory=dict)
    reviewer_checks: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["executed_queries"] = [_normalize_query_record(record) for record in self.executed_queries]
        return _json_safe(data)
