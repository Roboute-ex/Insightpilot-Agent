"""Central workflow state for deterministic agent runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
class WorkflowState:
    """Mutable state shared by workflow nodes.

    The state stores only workflow metadata and compact analysis artifacts. Raw
    pandas DataFrames stay outside the export path.
    """

    user_question: str = ""
    goal_mode: str = "auto"
    goal_mode_display_name: str = "自动识别"
    goal_mode_source: str = "auto_detected"
    intent: str = "general_summary"
    selected_metrics: list[str] = field(default_factory=list)
    analysis_plan: dict[str, Any] = field(default_factory=dict)
    tables_available: list[str] = field(default_factory=list)
    executed_queries: list[dict[str, Any]] = field(default_factory=list)
    intermediate_results: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    reviewer_status: str = ""
    reviewer_issues: list[str] = field(default_factory=list)
    reviewer_suggestions: list[str] = field(default_factory=list)
    route_taken: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_route(self, node_name: str) -> None:
        if node_name:
            self.route_taken.append(node_name)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

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
    )
