from __future__ import annotations

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.playbooks.validation import validate_playbook_parameters


def test_invalid_parameter_ranges_and_columns_are_rejected(playbook_tables) -> None:
    frame = playbook_tables["analysis_table"]
    playbook = get_playbook_registry().get("metric_trend")
    mapping = ColumnMapping(table_name="analysis_table", date_column="date", metric_columns=["metric"])
    errors = validate_playbook_parameters(
        playbook,
        {"time_grain": "day", "aggregation": "sum", "rolling_window": 100, "anomaly_threshold": 2.0, "date_range": ["2026-02-01", "2026-01-01"]},
        mapping,
        list(frame.columns),
        frame,
    )
    assert any("rolling_window" in error for error in errors)
    assert any("开始日期" in error for error in errors)


def test_group_requires_two_values(playbook_tables) -> None:
    frame = playbook_tables["analysis_table"].copy()
    frame["group"] = "control"
    playbook = get_playbook_registry().get("experiment_comparison")
    mapping = ColumnMapping(table_name="analysis_table", group_column="group", metric_columns=["metric"])
    errors = validate_playbook_parameters(playbook, {"control_value": "control", "treatment_value": "treatment", "metric": "metric", "metric_type": "mean", "confidence_level": 0.95}, mapping, list(frame.columns), frame)
    assert any("两个有效分组" in error for error in errors)


def test_arbitrary_sql_fragment_parameter_is_rejected(playbook_tables) -> None:
    frame = playbook_tables["analysis_table"]
    playbook = get_playbook_registry().get("data_profile")
    mapping = ColumnMapping(table_name="analysis_table")
    errors = validate_playbook_parameters(playbook, {"where_sql": "DROP TABLE analysis_table"}, mapping, list(frame.columns), frame)
    assert any("不支持" in error for error in errors)
