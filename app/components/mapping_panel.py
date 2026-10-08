"""Column mapping controls for custom data."""

from __future__ import annotations

from typing import Any
import hashlib
import json

import streamlit as st

from insightpilot.ingestion.mapping import suggest_column_mapping
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.ui.i18n import t


def _optional(label: str, columns: list[str], default: str | None, key: str) -> str | None:
    options = ["不选择", *columns]
    if key not in st.session_state:
        st.session_state[key] = default if default in options else "不选择"
    elif st.session_state[key] not in options:
        st.session_state[key] = "不选择"
    selected = st.selectbox(label, options, key=key)
    return None if selected == "不选择" else selected


def initialize_mapping_controls(mapping: dict[str, Any] | None) -> None:
    """Seed the editor from the current request before its widgets are created."""
    for field, key in {
        "table_name": "mapping_table", "date_column": "mapping_date",
        "metric_columns": "mapping_metrics", "dimension_columns": "mapping_dimensions",
        "group_column": "mapping_group", "outcome_column": "mapping_outcome",
        "treatment_column": "mapping_treatment", "covariates": "mapping_covariates",
        "aggregation": "mapping_aggregation", "time_grain": "mapping_grain",
    }.items():
        if field in (mapping or {}):
            value = mapping[field]
            st.session_state[key] = "不选择" if value is None and field.endswith("column") else value


def render_mapping_panel(registry: TableRegistry | None, goal_mode: str) -> dict[str, Any] | None:
    del goal_mode
    if registry is None or not registry.list_tables():
        return None
    if "mapping_table" not in st.session_state:
        prepared = st.session_state.get("guided_last_preflight") or {}
        initialize_mapping_controls(st.session_state.get("guided_mapping") or
                                    prepared.get("normalized_request", {}).get("column_mapping"))
    with st.container(border=True):
        table_name = st.selectbox("分析范围：目标数据表", registry.list_tables(), key="mapping_table")
        frame = registry.get_table(table_name)
        columns = [str(column) for column in frame.columns]
        from app.components.data_source_panel import current_dataset
        snapshot = current_dataset()
        suggested = snapshot.suggest_mapping(table_name) if snapshot is not None else suggest_column_mapping(table_name, frame)
        date_column = _optional("日期字段", columns, suggested.date_column, "mapping_date")
        for key, suggested_values in (("mapping_metrics", suggested.metric_columns), ("mapping_dimensions", suggested.dimension_columns), ("mapping_covariates", suggested.covariates)):
            st.session_state[key] = [item for item in st.session_state.get(key, suggested_values) if item in columns]
        metric_columns = st.multiselect("指标字段", columns, key="mapping_metrics", placeholder="请选择指标字段")
        dimension_columns = st.multiselect("维度字段", columns, key="mapping_dimensions", placeholder="请选择维度字段")
        group_column = _optional("分组字段", columns, suggested.group_column, "mapping_group")
        treatment_column = _optional("处理字段", columns, suggested.treatment_column, "mapping_treatment")
        outcome_column = _optional("结果字段", columns, suggested.outcome_column, "mapping_outcome")
        covariates = st.multiselect("协变量", columns, key="mapping_covariates", placeholder="请选择控制变量")
        aggregation = st.selectbox("聚合方式", ["sum", "mean", "count", "min", "max"], format_func=lambda value: {"sum": "求和", "mean": "均值", "count": "计数", "min": "最小值", "max": "最大值"}[value], key="mapping_aggregation")
        time_grain = st.selectbox("时间粒度", ["day", "week", "month"], format_func=lambda value: {"day": "按日", "week": "按周", "month": "按月"}[value], key="mapping_grain")
    mapping = {
        "table_name": table_name,
        "date_column": date_column,
        "metric_columns": metric_columns,
        "dimension_columns": dimension_columns,
        "group_column": group_column,
        "treatment_column": treatment_column,
        "outcome_column": outcome_column,
        "time_grain": time_grain,
        "covariates": covariates,
        "aggregation": aggregation,
    }
    identity = hashlib.sha256(json.dumps(mapping,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    confirmed = st.session_state.get('performance_mapping_confirmation') == identity
    if st.button('确认当前字段映射', key='confirm_current_mapping'):
        st.session_state['performance_mapping_confirmation'] = identity
        confirmed = True
    mapping['source'] = 'user_selected' if confirmed else 'automatic_suggestion'
    st.caption('当前字段映射已明确确认。' if confirmed else '字段控件当前值是建议；存在影响答案的歧义时仍需确认。')
    return mapping
