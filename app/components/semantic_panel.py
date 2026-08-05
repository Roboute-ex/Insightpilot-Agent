"""Analysis playbook selection and parameter widgets."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.models import AnalysisPlaybook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.ui.formatters import format_enum_value
from insightpilot.ui.help_text import help_text
from insightpilot.ui.i18n import t
from insightpilot.ui.view_modes import should_show_developer_details


PLAYBOOK_NONE = "__legacy__"
PLAYBOOK_AUTO = "auto"


def playbook_options() -> list[str]:
    return [PLAYBOOK_NONE, PLAYBOOK_AUTO, *[item.playbook_id for item in get_playbook_registry().list_all()]]


def playbook_display_name(playbook_id: str, *, developer: bool = False) -> str:
    if playbook_id == PLAYBOOK_NONE:
        return "保留现有自动工作流"
    if playbook_id == PLAYBOOK_AUTO:
        return "自动推荐分析剧本"
    display = format_enum_value("playbook", playbook_id)
    return f"{display}（{playbook_id}）" if developer else display


def render_playbook_selector(view_mode: str) -> str | None:
    selected = st.selectbox(
        t("sidebar.playbook"),
        playbook_options(),
        format_func=lambda value: playbook_display_name(value, developer=should_show_developer_details(view_mode)),
        help=help_text("playbook"),
        key="playbook_selector",
    )
    return None if selected == PLAYBOOK_NONE else selected


def _available_columns(mapping: ColumnMapping, tables: dict[str, pd.DataFrame]) -> list[str]:
    if mapping.table_name and mapping.table_name in tables:
        return [str(column) for column in tables[mapping.table_name].columns]
    return []


def render_playbook_parameters(
    playbook: AnalysisPlaybook | None,
    mapping: ColumnMapping,
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    if playbook is None:
        st.caption("当前使用原有自动工作流，无额外分析剧本参数。")
        return {}
    st.caption(playbook.description)
    columns = _available_columns(mapping, tables)
    semantic_model = load_builtin_catalog().get("commerce_demo") if playbook.playbook_id == "semantic_metric_query" else None
    values: dict[str, Any] = {}
    for parameter in playbook.parameters:
        if parameter.name in {"execution_mode", "approved_plan_id", "semantic_model_id"}:
            continue
        key = f"playbook_parameter_{playbook.playbook_id}_{parameter.name}"
        default = parameter.default
        if parameter.name == "metric" and playbook.playbook_id != "semantic_metric_query":
            default = next(iter(mapping.metric_columns), default)
        elif parameter.name == "dimension":
            default = next(iter(mapping.dimension_columns), default)
        if parameter.parameter_type == "metric" and semantic_model is not None:
            options = sorted(semantic_model.metrics)
            values[parameter.name] = st.selectbox(parameter.display_name, options, index=options.index(default) if default in options else 0, format_func=lambda value: semantic_model.metrics[value].display_name, help=parameter.description, key=key)
        elif parameter.parameter_type == "dimensions" and semantic_model is not None:
            defaults = [item for item in (default or []) if item in semantic_model.dimensions]
            values[parameter.name] = st.multiselect(parameter.display_name, sorted(semantic_model.dimensions), default=defaults, format_func=lambda value: semantic_model.dimensions[value].display_name, help=parameter.description, key=key)
        elif parameter.parameter_type == "choice":
            options = list(parameter.choices)
            index = options.index(default) if default in options else 0
            formatters = {
                "time_grain": {"day": "按日", "week": "按周", "month": "按月"},
                "aggregation": {"sum": "求和", "mean": "均值", "count": "计数", "min": "最小值", "max": "最大值"},
            }
            values[parameter.name] = st.selectbox(
                parameter.display_name,
                options,
                index=index,
                format_func=lambda value, parameter_name=parameter.name: formatters.get(parameter_name, {}).get(value, value),
                help=parameter.description,
                key=key,
            )
        elif parameter.parameter_type == "integer":
            bounds = {"top_n": (1, 100), "rolling_window": (1, 90), "observation_periods": (1, 26), "limit": (1, 10_000)}
            minimum, maximum = bounds.get(parameter.name, (0, 10_000))
            values[parameter.name] = int(st.number_input(parameter.display_name, min_value=minimum, max_value=maximum, value=int(default or minimum), help=parameter.description, key=key))
        elif parameter.parameter_type == "float":
            if parameter.name == "confidence_level":
                values[parameter.name] = float(st.number_input(parameter.display_name, min_value=0.8, max_value=0.99, value=float(default or 0.95), step=0.01, help=parameter.description, key=key))
            else:
                values[parameter.name] = float(st.number_input(parameter.display_name, value=float(default or 0.0), help=parameter.description, key=key))
        elif parameter.parameter_type == "boolean":
            values[parameter.name] = st.checkbox(parameter.display_name, value=bool(default), help=parameter.description, key=key)
        elif parameter.parameter_type == "column":
            options = ["", *columns]
            values[parameter.name] = st.selectbox(parameter.display_name, options, index=options.index(default) if default in options else 0, help=parameter.description, key=key) or None
        elif parameter.parameter_type in {"metric_columns", "dimension_columns"}:
            defaults = [item for item in (default or []) if item in columns]
            values[parameter.name] = st.multiselect(parameter.display_name, columns, default=defaults, help=parameter.description, key=key)
        elif parameter.parameter_type == "date_range":
            selected = st.date_input(parameter.display_name, value=(), help=parameter.description, key=key)
            if isinstance(selected, (list, tuple)) and len(selected) == 2:
                values[parameter.name] = {"start": str(selected[0]), "end": str(selected[1])}
        elif parameter.parameter_type == "date":
            selected = st.date_input(parameter.display_name, value=None, help=parameter.description, key=key)
            values[parameter.name] = str(selected) if selected else None
        else:
            group_values: list[str] = []
            if parameter.name in {"control_value", "treatment_value"} and mapping.group_column and mapping.table_name in tables:
                group_values = sorted(tables[mapping.table_name][mapping.group_column].dropna().astype(str).unique().tolist())
            if group_values:
                values[parameter.name] = st.selectbox(parameter.display_name, group_values, index=group_values.index(str(default)) if str(default) in group_values else 0, help=parameter.description, key=key)
            elif parameter.name == "date_dimension" and semantic_model is not None:
                date_dimensions = [key for key, item in semantic_model.dimensions.items() if item.is_time_dimension]
                values[parameter.name] = st.selectbox(parameter.display_name, date_dimensions, format_func=lambda value: semantic_model.dimensions[value].display_name, help=parameter.description, key=key)
            else:
                values[parameter.name] = st.text_input(parameter.display_name, value=str(default or ""), help=parameter.description, key=key)
    return {key: value for key, value in values.items() if value not in (None, "", [])}
