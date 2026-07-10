"""In-memory Excel analysis report export."""

from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

import pandas as pd

from insightpilot.reports.manifest import RunManifest


MAX_EXCEL_RESULT_ROWS = 100_000


def _sheet_name(value: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", value)[:31] or "Sheet"
    candidate = cleaned
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = f"{cleaned[:31-len(suffix)]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _key_value_frame(values: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"key": key, "value": json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value} for key, value in values.items()]
    )


def generate_excel_report(result: dict[str, Any], manifest: RunManifest) -> bytes:
    """Generate an XLSX workbook without writing it to disk."""

    buffer = BytesIO()
    used: set[str] = set()
    reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    summary = {
        "playbook": selected.get("playbook_id") or manifest.playbook_id,
        "playbook_name": selected.get("display_name"),
        "goal_mode": manifest.goal_mode,
        "data_source_type": manifest.data_source_type,
        "execution_status": (result.get("playbook_result") or {}).get("status") if isinstance(result.get("playbook_result"), dict) else reviewer.get("status"),
        "workflow_backend": manifest.workflow_backend,
        "run_id": manifest.run_id,
    }
    findings = pd.DataFrame({"finding": [str(value) for value in result.get("findings", [])]})
    reviewer_rows: list[dict[str, Any]] = [
        {"category": "summary", "name": "status", "value": reviewer.get("status")},
        {"category": "summary", "name": "score", "value": reviewer.get("score")},
    ]
    for category in ("checks", "issues", "suggestions"):
        values = reviewer.get(category, {})
        if isinstance(values, dict):
            reviewer_rows.extend({"category": category, "name": key, "value": value} for key, value in values.items())
        elif isinstance(values, list):
            reviewer_rows.extend({"category": category, "name": str(index + 1), "value": value} for index, value in enumerate(values))
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _key_value_frame(summary).to_excel(writer, sheet_name=_sheet_name("Summary", used), index=False)
        findings.to_excel(writer, sheet_name=_sheet_name("Findings", used), index=False)
        pd.DataFrame(reviewer_rows).to_excel(writer, sheet_name=_sheet_name("Reviewer", used), index=False)
        _key_value_frame(manifest.column_mapping).to_excel(writer, sheet_name=_sheet_name("Mapping", used), index=False)
        _key_value_frame(manifest.to_dict()).to_excel(writer, sheet_name=_sheet_name("Manifest", used), index=False)
        result_tables = result.get("result_tables") if isinstance(result.get("result_tables"), dict) else {}
        for name, frame in result_tables.items():
            if isinstance(frame, pd.DataFrame):
                frame.head(MAX_EXCEL_RESULT_ROWS).to_excel(
                    writer, sheet_name=_sheet_name(f"Result_{name}", used), index=False
                )
    return buffer.getvalue()
