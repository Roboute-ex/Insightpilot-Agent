"""Column mapping controls for custom data."""

from __future__ import annotations

from typing import Any

import streamlit as st

from insightpilot.ingestion.mapping import suggest_column_mapping
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.ui.i18n import t


def _optional(label: str, columns: list[str], default: str | None, key: str) -> str | None:
    options = ["不选择", *columns]
    selected = st.selectbox(label, options, index=options.index(default) if default in options else 0, key=key)
    return None if selected == "不选择" else selected


def render_mapping_panel(registry: TableRegistry | None, goal_mode: str) -> dict[str, Any] | None:
    del goal_mode
    if registry is None or not registry.list_tables():
        return None
    with st.expander(t("section.field_mapping"), expanded=False, icon=":material/tune:"):
        table_name = st.selectbox("目标数据表", registry.list_tables(), key="mapping_table")
        frame = registry.get_table(table_name)
        columns = [str(column) for column in frame.columns]
        suggested = suggest_column_mapping(table_name, frame)
        date_column = _optional("日期字段", columns, suggested.date_column, "mapping_date")
        metric_columns = st.multiselect("指标字段", columns, default=[item for item in suggested.metric_columns if item in columns], key="mapping_metrics")
        dimension_columns = st.multiselect("维度字段", columns, default=[item for item in suggested.dimension_columns if item in columns], key="mapping_dimensions")
        group_column = _optional("分组字段", columns, suggested.group_column, "mapping_group")
        treatment_column = _optional("处理字段", columns, suggested.treatment_column, "mapping_treatment")
        outcome_column = _optional("结果字段", columns, suggested.outcome_column, "mapping_outcome")
        time_grain = st.selectbox("时间粒度", ["day", "week", "month"], format_func=lambda value: {"day": "按日", "week": "按周", "month": "按月"}[value], key="mapping_grain")
    return {
        "table_name": table_name,
        "date_column": date_column,
        "metric_columns": metric_columns,
        "dimension_columns": dimension_columns,
        "group_column": group_column,
        "treatment_column": treatment_column,
        "outcome_column": outcome_column,
        "time_grain": time_grain,
    }
