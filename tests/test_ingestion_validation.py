from __future__ import annotations

import pandas as pd

from insightpilot.ingestion.validation import validate_dataframe_for_analysis, validate_tables_for_workflow


def test_empty_dataframe_warning() -> None:
    warnings = validate_dataframe_for_analysis(pd.DataFrame())
    assert any("为空" in warning for warning in warnings)


def test_missing_numeric_and_date_warnings() -> None:
    warnings = validate_dataframe_for_analysis(pd.DataFrame({"city": ["A", "B", "C"]}))
    assert any("数值列" in warning for warning in warnings)
    assert any("日期列" in warning for warning in warnings)


def test_high_missing_warning() -> None:
    warnings = validate_dataframe_for_analysis(
        pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "value": [1, None], "mostly_null": [None, None]})
    )
    assert any("高缺失率" in warning for warning in warnings)
    assert any("全空列" in warning for warning in warnings)


def test_validate_tables_for_workflow_requires_one_table() -> None:
    assert validate_tables_for_workflow({}) == ["没有可用表，workflow 无法执行分析。"]
