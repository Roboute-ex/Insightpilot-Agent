"""Output-only text and spreadsheet safety; never mutate analysis values."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


def spreadsheet_cell(value: Any) -> Any:
    """Keep formula-looking input as text, including leading control characters."""

    if isinstance(value, str):
        value = xml_text(value)
        if len(value) > 30_000:
            value = value[:30_000] + "…（单元格文本已截断）"
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def safe_spreadsheet_frame(frame: pd.DataFrame) -> pd.DataFrame:
    safe = frame.map(spreadsheet_cell)
    safe.columns = [spreadsheet_cell(str(column)) for column in frame.columns]
    return safe


def xml_text(value: Any) -> str:
    """Remove XML-disallowed controls before the caller escapes markup."""

    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value if value is not None else "不可计算"))


def safe_report_result(value: Any, key: str = "", *, synthetic: bool = False) -> Any:
    """Redact metadata and credential-looking result cells, preserving numeric tables."""
    from insightpilot.reports.manifest import sanitize_manifest_value
    from insightpilot.ui.synthetic_display import synthetic_display_text
    prose_keys = {"summary", "executive_summary", "findings", "next_steps", "claim", "action", "reason", "dimension", "dimension_value", "caveats"}
    if isinstance(value, pd.DataFrame):
        safe = value.copy()
        for column in safe.columns:
            safe[column] = safe[column].map(lambda cell: synthetic_display_text(sanitize_manifest_value(cell, str(column))) if synthetic and str(column) in prose_keys and isinstance(cell, str) else sanitize_manifest_value(cell, str(column)))
        return safe
    if isinstance(value, dict):
        synthetic = synthetic or value.get("data_source_type") == "synthetic"
        is_filter = "operator" in value and any(name in value for name in ("dimension_id", "dimension", "column", "field"))
        return {name: ("<已脱敏，需重新输入>" if is_filter and name in {"value", "values"} else safe_report_result(item, str(name), synthetic=synthetic)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        if key == "parameters":
            return ["***" for _ in value]
        return [safe_report_result(item, key, synthetic=synthetic) for item in value]
    safe_value = sanitize_manifest_value(value, key)
    return synthetic_display_text(safe_value) if synthetic and key in prose_keys and isinstance(safe_value, str) else safe_value


# Only fields actually consumed by the report renderers. In particular, source
# tables, Figures, tool artifacts and existing export payloads are not traversed.
_REPORT_FIELDS = frozenset({
    "analysis_result_package", "summary", "question", "execution_mode", "reviewer",
    "caveats", "limitations", "analysis_plan", "plan", "selected_playbook",
    "column_mapping", "mapping_source", "route_taken", "data_source_type",
    "goal_mode", "goal_mode_source", "playbook_result", "query_plan", "join_plan",
    "findings", "lineage", "next_steps", "table_metadata", "metrics", "metric_request",
    "contract_results", "chart_specs", "telemetry", "trace", "workflow_backend",
    "run_manifest", "metric_definitions", "semantic_fingerprint", "presentation_fingerprint",
    "planning_status", "clarification", "execution_status", "errors",
})


def report_result_view(result: dict[str, Any], *, max_table_rows: int | None = None,
                       table_names: list[str] | None = None) -> dict[str, Any]:
    """Select bounded output before redaction, keeping exact original row counts.

    This is an output-only copy, never an analysis sample or a trusted/safe flag.
    Public exporters always call this helper themselves. With no row budget
    (Markdown), no DataFrame is visited or copied.
    """
    from insightpilot.reports.manifest import sanitize_manifest_value

    def metadata_only(value: Any) -> Any:
        if isinstance(value, pd.DataFrame):
            return sanitize_manifest_value(value)
        if isinstance(value, dict):
            return {key: metadata_only(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [metadata_only(item) for item in value]
        return value

    selected = {key: metadata_only(value) for key, value in result.items() if key in _REPORT_FIELDS}
    view = safe_report_result(selected)
    tables = result.get("result_tables")
    tables = tables if isinstance(tables, dict) else {}
    names = list(tables) if table_names is None else table_names
    view["result_tables"] = {}
    view["_report_table_row_counts"] = {}
    view["_report_table_count"] = len(tables)
    if max_table_rows is not None:
        for name in names:
            frame = tables.get(name)
            if isinstance(frame, pd.DataFrame):
                view["_report_table_row_counts"][name] = len(frame)
                view["result_tables"][name] = safe_report_result(
                    frame.head(max(0, int(max_table_rows))), str(name),
                    synthetic=result.get("data_source_type") == "synthetic",
                )
    return view

