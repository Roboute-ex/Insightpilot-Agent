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
    return [PLAYBOOK_AUTO, PLAYBOOK_NONE, *[item.playbook_id for item in get_playbook_registry().list_all()]]


def playbook_display_name(playbook_id: str, *, developer: bool = False) -> str:
    if playbook_id == PLAYBOOK_NONE:
        return "保留现有自动工作流"
    if playbook_id == PLAYBOOK_AUTO:
        return "自动推荐分析方法"
    display = format_enum_value("playbook", playbook_id)
    return f"{display}（{playbook_id}）" if developer else display


def _method_selected() -> None:
    from app.components.guidance_panel import clear_request_confirmations
    st.session_state["guided_selection_source"] = "automatic" if st.session_state.get("playbook_selector") == PLAYBOOK_AUTO else "user_selected"
    st.session_state["guided_parameters"] = {}
    for key in list(st.session_state):
        if key.startswith("playbook_parameter_"):
            st.session_state.pop(key, None)
    clear_request_confirmations()


def render_playbook_selector(view_mode: str) -> str | None:
    selected = st.selectbox(
        "分析方法",
        playbook_options(),
        format_func=lambda value: playbook_display_name(value, developer=should_show_developer_details(view_mode)),
        help=help_text("playbook"),
        key="playbook_selector",
        on_change=_method_selected,
    )
    return str(selected)


def _available_columns(mapping: ColumnMapping, tables: dict[str, pd.DataFrame]) -> list[str]:
    if mapping.table_name and mapping.table_name in tables:
        return [str(column) for column in tables[mapping.table_name].columns]
    return []


def _experiment_direction_context(playbook, mapping):
    """Scope explicit form choices to one actual dataset revision and group.

    Widget defaults are not confirmations. Only generated built-in metadata or a
    bounded, session-owned historical run can supply preconfirmed directions.
    """
    from app.components.data_source_panel import current_dataset
    snapshot = current_dataset()
    context = (getattr(snapshot, "dataset_id", None), getattr(snapshot, "revision", None),
               mapping.table_name, mapping.group_column or mapping.treatment_column)
    metadata = snapshot.metadata.get(mapping.table_name, {}) if snapshot is not None else {}
    builtin = bool(metadata.get("builtin_scenario"))
    contexts = st.session_state.setdefault("performance_direction_contexts", {})
    if contexts.get(playbook.playbook_id) != context:
        restored = {}
        session = st.session_state.get("performance_result")
        parent_run = st.session_state.get("performance_branch_parent")
        if session is not None and parent_run and snapshot is not None:
            node = next((item for item in session.history.nodes if item.run_id == parent_run), None)
            if node is not None:
                saved = node.config
                saved_mapping = saved.get("column_mapping") or {}
                saved_context = node.context
                if (saved_context.get("dataset_id") == context[0]
                        and str(node.dataset_revision) == str(context[1])
                        and (saved.get("effective_playbook_id") if saved.get("playbook_id") in {None, "auto", "auto_recommended"} else saved.get("playbook_id")) == playbook.playbook_id
                        and saved_mapping.get("table_name") == context[2]
                        and (saved_mapping.get("group_column") or saved_mapping.get("treatment_column")) == context[3]):
                    restored = saved.get("parameters") or {}
        retained = st.session_state.get("guided_parameters", {})
        for role in ("control_value", "treatment_value", "statistical_unit"):
            retained.pop(role, None)
        retained.update({key: value for key, value in restored.items() if key in {"control_value", "treatment_value", "statistical_unit"}})
        st.session_state["guided_parameters"] = retained
        for role in ("control_value", "treatment_value", "statistical_unit"):
            key = f"playbook_parameter_{playbook.playbook_id}_{role}"
            st.session_state.pop(key, None)
            if role in restored:
                st.session_state[key] = restored[role]
        contexts[playbook.playbook_id] = context
    return context, builtin


def _widget_default(key, **default):
    """A restored widget uses its session value, never a competing explicit default."""
    return {} if key in st.session_state else default


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
    direction_context, builtin_directions = _experiment_direction_context(playbook, mapping) if any(
        parameter.name in {"control_value", "treatment_value"} for parameter in playbook.parameters
    ) else (None, False)
    semantic_model = load_builtin_catalog().get("commerce_demo") if playbook.playbook_id == "semantic_metric_query" else None
    values: dict[str, Any] = {}
    for parameter in playbook.parameters:
        if parameter.name in {"execution_mode", "approved_plan_id", "semantic_model_id"}:
            continue
        key = f"playbook_parameter_{playbook.playbook_id}_{parameter.name}"
        default = parameter.default
        if parameter.name in {"control_value", "treatment_value"} and not builtin_directions:
            default = None
        if parameter.name == "metric" and playbook.playbook_id != "semantic_metric_query":
            default = next(iter(mapping.metric_columns), default)
        elif parameter.name == "dimension":
            default = next(iter(mapping.dimension_columns), default)
        if parameter.parameter_type == "metric" and semantic_model is not None:
            options = sorted(semantic_model.metrics)
            values[parameter.name] = st.selectbox(parameter.display_name, options, **_widget_default(key, index=options.index(default) if default in options else 0), format_func=lambda value: semantic_model.metrics[value].display_name, help=parameter.description, key=key)
        elif parameter.parameter_type == "dimensions" and semantic_model is not None:
            defaults = [item for item in (default or []) if item in semantic_model.dimensions]
            values[parameter.name] = st.multiselect(parameter.display_name, sorted(semantic_model.dimensions), **_widget_default(key, default=defaults), placeholder="请选择维度", format_func=lambda value: semantic_model.dimensions[value].display_name, help=parameter.description, key=key)
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
                **_widget_default(key, index=index),
                format_func=lambda value, parameter_name=parameter.name: formatters.get(parameter_name, {}).get(value, value),
                help=parameter.description,
                key=key,
            )
        elif parameter.parameter_type == "integer":
            bounds = {"top_n": (1, 100), "rolling_window": (1, 90), "observation_periods": (1, 26), "limit": (1, 10_000)}
            minimum, maximum = bounds.get(parameter.name, (0, 10_000))
            values[parameter.name] = int(st.number_input(parameter.display_name, min_value=minimum, max_value=maximum, **_widget_default(key, value=int(default or minimum)), help=parameter.description, key=key))
        elif parameter.parameter_type == "float":
            if parameter.name == "confidence_level":
                values[parameter.name] = float(st.number_input(parameter.display_name, min_value=0.8, max_value=0.99, **_widget_default(key, value=float(default or 0.95)), step=0.01, help=parameter.description, key=key))
            else:
                values[parameter.name] = float(st.number_input(parameter.display_name, **_widget_default(key, value=float(default or 0.0)), help=parameter.description, key=key))
        elif parameter.parameter_type == "boolean":
            values[parameter.name] = st.checkbox(parameter.display_name, **_widget_default(key, value=bool(default)), help=parameter.description, key=key)
        elif parameter.parameter_type == "column":
            options = ["", *columns]
            values[parameter.name] = st.selectbox(parameter.display_name, options, **_widget_default(key, index=options.index(default) if default in options else 0), help=parameter.description, key=key) or None
        elif parameter.parameter_type in {"metric_columns", "dimension_columns"}:
            defaults = [item for item in (default or []) if item in columns]
            values[parameter.name] = st.multiselect(parameter.display_name, columns, **_widget_default(key, default=defaults), placeholder="请选择控制变量" if parameter.name == "covariates" else "请选择字段", help=parameter.description, key=key)
        elif parameter.parameter_type == "date_range":
            selected = st.date_input(parameter.display_name, **_widget_default(key, value=()), help=parameter.description, key=key)
            if isinstance(selected, (list, tuple)) and len(selected) == 2:
                values[parameter.name] = {"start": str(selected[0]), "end": str(selected[1])}
        elif parameter.parameter_type == "date":
            selected = st.date_input(parameter.display_name, **_widget_default(key, value=None), help=parameter.description, key=key)
            values[parameter.name] = str(selected) if selected else None
        else:
            group_values: list[Any] = []
            group_column = mapping.group_column or mapping.treatment_column
            if parameter.name in {"control_value", "treatment_value"} and group_column and mapping.table_name in tables:
                from app.components.data_source_panel import current_dataset
                prepared = current_dataset()
                fact = ((prepared.metadata.get(mapping.table_name, {}).get("readiness_summary") or {}).get("columns", {}).get(group_column, {})) if prepared else {}
                if fact.get("values_complete"):
                    group_values = list(fact.get("values", []))
                elif fact:
                    st.caption("分组字段没有完整的受控取值列表，请输入真实组值；预检仍须验证其存在。")
            if group_values:
                values[parameter.name] = st.selectbox(parameter.display_name, group_values, **_widget_default(key, index=group_values.index(default) if default in group_values else None), format_func=str, placeholder="请选择组值；不自动确认对照方向", help=parameter.description, key=key)
            elif parameter.name == "date_dimension" and semantic_model is not None:
                date_dimensions = [key for key, item in semantic_model.dimensions.items() if item.is_time_dimension]
                values[parameter.name] = st.selectbox(parameter.display_name, date_dimensions, format_func=lambda value: semantic_model.dimensions[value].display_name, help=parameter.description, key=key)
            else:
                values[parameter.name] = st.text_input(parameter.display_name, **_widget_default(key, value=str(default or "")), help=parameter.description, key=key)
    return {key: value for key, value in values.items() if value not in (None, "", [])}
