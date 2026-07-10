from __future__ import annotations

import json

import pandas as pd

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.models import PlaybookExecutionResult
from insightpilot.playbooks.registry import get_playbook_registry


def test_analysis_playbook_is_json_serializable() -> None:
    playbook = get_playbook_registry().get("metric_trend")
    assert json.loads(json.dumps(playbook.to_dict(), ensure_ascii=False))["playbook_id"] == "metric_trend"
    assert playbook.supports_goal_mode("growth_trend")
    assert "date_column" in " ".join(playbook.validate_mapping(ColumnMapping(table_name="table")))


def test_execution_result_summarizes_dataframes() -> None:
    result = PlaybookExecutionResult("profile", "Profile", "PASS", result_tables={"table": pd.DataFrame({"x": [1, 2]})})
    payload = result.to_dict()
    assert payload["result_tables"]["table"]["row_count"] == 2
    assert "DataFrame" not in json.dumps(payload)
