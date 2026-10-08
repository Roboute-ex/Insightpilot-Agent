"""Central workflow state for deterministic agent runs."""

from __future__ import annotations

from dataclasses import fields, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pandas as pd

from insightpilot.planning.goal_modes import get_goal_mode_display_name, normalize_goal_mode


def _json_safe(value: Any) -> Any:
    """Return a JSON-serializable preview without exporting whole DataFrames."""

    if isinstance(value, pd.DataFrame):
        return {
            "type": "DataFrame",
            "row_count": int(len(value)),
            "columns": [str(column) for column in value.columns],
        }
    if value.__class__.__module__.startswith("plotly"):
        return {"type": value.__class__.__name__, "serialized": False}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _json_safe(value.to_dict())
        except (TypeError, ValueError):
            return str(value)
    return value


@dataclass
class WorkflowState:
    """Mutable state shared by workflow nodes.

    The state stores only workflow metadata and compact analysis artifacts. Raw
    pandas DataFrames stay outside the export path.
    """

    user_question: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    goal_mode: str = "auto"
    goal_mode_display_name: str = "自动识别"
    goal_mode_source: str = "auto_detected"
    intent: str = "general_summary"
    selected_metrics: list[str] = field(default_factory=list)
    analysis_plan: dict[str, Any] = field(default_factory=dict)
    planning_status: str = "ready"
    clarification: dict[str, Any] = field(default_factory=dict)
    metric_definitions: list[dict[str, Any]] = field(default_factory=list)
    semantic_fingerprint: str = ""
    presentation_fingerprint: str = ""
    tables_available: list[str] = field(default_factory=list)
    executed_queries: list[dict[str, Any]] = field(default_factory=list)
    intermediate_results: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    caveats: list[Any] = field(default_factory=list)
    data_source_type: str = "synthetic"
    table_metadata: dict[str, Any] = field(default_factory=dict)
    schema_warnings: list[str] = field(default_factory=list)
    user_table_mode: bool = False
    column_mapping: dict[str, Any] = field(default_factory=dict)
    mapping_warnings: list[str] = field(default_factory=list)
    mapping_source: str = "none"
    selected_playbook_id: str | None = None
    playbook_source: str = "none"
    playbook_parameters: dict[str, Any] = field(default_factory=dict)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    run_manifest: dict[str, Any] = field(default_factory=dict)
    export_formats: list[str] = field(default_factory=list)
    semantic_model: dict[str, Any] = field(default_factory=dict)
    semantic_catalog: dict[str, Any] = field(default_factory=dict)
    metric_request: dict[str, Any] = field(default_factory=dict)
    relationship_graph: dict[str, Any] = field(default_factory=dict)
    join_plan: dict[str, Any] = field(default_factory=dict)
    query_plan: dict[str, Any] = field(default_factory=dict)
    plan_review: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "execute"
    presentation_mode: str = "eager"
    dataset_fingerprints: dict[str, str] = field(default_factory=dict)
    _input_fingerprint_objects: dict[int,str] = field(default_factory=dict,repr=False)
    dataset_prepared: bool = False
    dataset_id: str = ""
    dataset_revision: str = ""
    contract_results: list[dict[str, Any]] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    evaluation_summary: dict[str, Any] = field(default_factory=dict)
    analysis_result_package: dict[str, Any] = field(default_factory=dict)
    reviewer_status: str = ""
    reviewer_issues: list[str] = field(default_factory=list)
    reviewer_suggestions: list[str] = field(default_factory=list)
    route_taken: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_route(self, node_name: str) -> None:
        if node_name:
            self.route_taken.append(node_name)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe({item.name: getattr(self, item.name) for item in fields(self) if not item.name.startswith("_")})

    @classmethod
    def from_partial(cls, values: dict[str, Any] | None = None) -> "WorkflowState":
        values = values or {}
        field_names = cls.__dataclass_fields__.keys()
        safe_values = {key: value for key, value in values.items() if key in field_names}
        state = cls(**safe_values)
        normalized = normalize_goal_mode(state.goal_mode)
        state.goal_mode = normalized
        state.goal_mode_display_name = values.get(
            "goal_mode_display_name",
            get_goal_mode_display_name(normalized),
        )
        return state


def create_initial_state(
    question: str,
    tables: dict[str, pd.DataFrame] | None = None,
    goal_mode: str = "auto",
    data_source_type: str = "synthetic",
    table_metadata: dict[str, Any] | None = None,
    column_mapping: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    playbook_parameters: dict[str, Any] | None = None,
    execution_mode: str = "execute",
) -> WorkflowState:
    """Create a safe initial state for a workflow run."""

    normalized = normalize_goal_mode(goal_mode)
    source = "auto_detected" if normalized == "auto" else "user_selected"
    return WorkflowState(
        user_question=question,
        goal_mode=normalized,
        goal_mode_display_name=get_goal_mode_display_name(normalized),
        goal_mode_source=source,
        tables_available=sorted((tables or {}).keys()),
        data_source_type=data_source_type,
        table_metadata=table_metadata or {},
        user_table_mode=data_source_type != "synthetic",
        column_mapping=column_mapping or {},
        mapping_source="user_selected" if column_mapping else "none",
        selected_playbook_id=playbook_id,
        playbook_source="user_selected" if playbook_id and playbook_id not in {"auto", "auto_recommended"} else "none",
        playbook_parameters=playbook_parameters or {},
        execution_mode=execution_mode if execution_mode in {"plan_only", "execute"} else "execute",
    )
