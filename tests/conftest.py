from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def playbook_tables() -> dict[str, pd.DataFrame]:
    rows = 40
    return {
        "analysis_table": pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=rows, freq="D"),
                "metric": [float(100 + index * 2 + (index % 3)) for index in range(rows)],
                "outcome": [float(0.4 + (index % 5) * 0.03 + (0.08 if index % 2 else 0.0)) for index in range(rows)],
                "group": ["control" if index % 2 == 0 else "treatment" for index in range(rows)],
                "city": ["A", "B", "C", "A"] * 10,
                "covariate": [float(index % 7) for index in range(rows)],
            }
        )
    }


@pytest.fixture
def playbook_mapping() -> dict[str, object]:
    return {
        "table_name": "analysis_table",
        "date_column": "date",
        "metric_columns": ["metric", "outcome"],
        "dimension_columns": ["city", "covariate"],
        "group_column": "group",
        "treatment_column": "group",
        "outcome_column": "outcome",
        "time_grain": "day",
    }
