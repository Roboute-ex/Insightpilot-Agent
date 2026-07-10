from __future__ import annotations

import pytest

from insightpilot.playbooks.executor import execute_playbook


@pytest.mark.parametrize(
    "playbook_id,expected_table",
    [
        ("data_profile", "column_profile"),
        ("metric_trend", "metric_trend"),
        ("period_comparison", "period_comparison"),
        ("dimension_contribution", "dimension_contribution"),
        ("experiment_comparison", "experiment_statistics"),
        ("causal_exploration", "adjusted_effect_summary"),
        ("periodic_summary", "data_profile_column_profile"),
    ],
)
def test_builtin_playbook_executes(playbook_id, expected_table, playbook_tables, playbook_mapping) -> None:
    result = execute_playbook(playbook_id, playbook_tables, playbook_mapping)
    assert result.status in {"PASS", "WARN"}
    assert expected_table in result.result_tables
    assert result.caveats
    assert result.metadata["route_taken"][-1] == "build_chart_specs"


def test_invalid_mapping_returns_structured_failure(playbook_tables) -> None:
    result = execute_playbook("metric_trend", playbook_tables, {"table_name": "analysis_table"})
    assert result.status == "FAIL"
    assert result.warnings


def test_causal_without_covariates_keeps_naive_difference(playbook_tables, playbook_mapping) -> None:
    mapping = dict(playbook_mapping)
    mapping["dimension_columns"] = []
    result = execute_playbook("causal_exploration", playbook_tables, mapping, {"covariates": []})
    assert result.status == "WARN"
    assert "adjusted_effect_summary" in result.result_tables
    assert result.result_tables["adjusted_effect_summary"]["naive_difference"].notna().all()


def test_experiment_optional_dimension_outputs_strata(playbook_tables, playbook_mapping) -> None:
    result = execute_playbook(
        "experiment_comparison",
        playbook_tables,
        playbook_mapping,
        {"metric": "outcome", "dimension": "city", "control_value": "control", "treatment_value": "treatment", "metric_type": "mean", "confidence_level": 0.90},
    )
    assert "experiment_stratified" in result.result_tables
    assert result.result_tables["experiment_statistics"]["confidence_level"].iloc[0] == 0.90
