from __future__ import annotations

import pytest

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.models import AnalysisPlaybook, PlaybookRequirements
from insightpilot.playbooks.registry import PlaybookRegistry, get_playbook_registry


def test_seven_builtin_playbooks_are_registered() -> None:
    registry = get_playbook_registry()
    expected = {"data_profile", "metric_trend", "period_comparison", "dimension_contribution", "experiment_comparison", "causal_exploration", "periodic_summary"}
    registered = {playbook.playbook_id for playbook in registry.list_all()}
    assert expected.issubset(registered)
    assert {"semantic_metric_query", "funnel_analysis", "cohort_retention"}.issubset(registered)


def test_registry_rejects_duplicate_and_recommends_deterministically() -> None:
    registry = PlaybookRegistry()
    playbook = AnalysisPlaybook("one", "One", "", ["growth_trend"], PlaybookRequirements(), [], "executor", [], [], [])
    registry.register(playbook)
    with pytest.raises(ValueError, match="已存在"):
        registry.register(playbook)
    mapping = ColumnMapping(table_name="table", date_column="date", metric_columns=["metric"])
    first = [item.playbook_id for item in get_playbook_registry().recommend("growth_trend", mapping)]
    second = [item.playbook_id for item in get_playbook_registry().recommend("growth_trend", mapping)]
    assert first == second
    with pytest.raises(ValueError, match="未找到"):
        registry.get("missing")
