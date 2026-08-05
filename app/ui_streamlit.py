"""Chinese-first Streamlit entry point for InsightPilot Agent v0.6."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from app.components.data_source_panel import (
    SCENARIOS,
    load_synthetic_tables,
    render_database_source,
    render_synthetic_source,
    render_upload_source,
)
from app.components.export_panel import prepare_export_payloads
from app.components.mapping_panel import render_mapping_panel
from app.components.question_panel import render_example_question_selector
from app.components.result_panel import render_result_panel
from app.components.semantic_panel import (
    PLAYBOOK_AUTO,
    PLAYBOOK_NONE,
    playbook_display_name,
    playbook_options,
    render_playbook_parameters,
    render_playbook_selector,
)
from app.components.sidebar import render_source_goal_backend, render_view_mode_selector
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.ingestion.mapping import ColumnMapping, normalize_column_mapping, suggest_column_mapping
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.planning.goal_modes import GOAL_MODE_OPTIONS
from insightpilot.playbooks.models import AnalysisPlaybook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.ui.i18n import t
from insightpilot.ui.theme import apply_compact_theme, render_result_note
from insightpilot.ui.view_modes import should_show_developer_details, should_show_professional_details


PLAYBOOK_AUTOMATIC = "保留现有自动工作流"
PLAYBOOK_RECOMMENDED = "Auto recommended"


def _mapping_for_playbook_ui(
    playbook_id: str,
    tables: dict[str, pd.DataFrame],
    mapping: dict[str, Any] | None,
) -> ColumnMapping:
    """Compatibility helper retained for v0.5 callers and tests."""

    if mapping:
        table_name = str(mapping.get("table_name") or "")
        columns = [str(column) for column in tables[table_name].columns] if table_name in tables else []
        return normalize_column_mapping(mapping, columns)
    if not tables:
        return ColumnMapping()
    if playbook_id in {"experiment_comparison", "causal_exploration"} and "experiments" in tables:
        frame = tables["experiments"]
        return ColumnMapping(
            table_name="experiments",
            group_column="group" if "group" in frame.columns else None,
            treatment_column="group" if "group" in frame.columns else None,
            outcome_column="completion_rate" if "completion_rate" in frame.columns else None,
            metric_columns=["completion_rate"] if "completion_rate" in frame.columns else [],
            dimension_columns=[column for column in ["historical_activity", "historical_revenue", "city"] if column in frame.columns],
        )
    table_name = "daily_metrics" if "daily_metrics" in tables else sorted(tables)[0]
    return suggest_column_mapping(table_name, tables[table_name])


def _recommended_playbook_ids(goal_mode: str, mapping: ColumnMapping) -> list[str]:
    return [item.playbook_id for item in get_playbook_registry().recommend(goal_mode, mapping)]


def _playbook_label_map() -> dict[str, str | None]:
    """Legacy label map; the v0.6 page uses localized formatters instead."""

    labels: dict[str, str | None] = {PLAYBOOK_AUTOMATIC: None, PLAYBOOK_RECOMMENDED: PLAYBOOK_AUTO}
    for playbook in get_playbook_registry().list_all():
        labels[f"{playbook.display_name} ({playbook.playbook_id})"] = playbook.playbook_id
    return labels


def _render_playbook_parameters(
    playbook: AnalysisPlaybook | None,
    mapping: ColumnMapping,
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    return render_playbook_parameters(playbook, mapping, tables)


def _prepare_export_payloads(result: dict[str, Any]) -> dict[str, str | bytes]:
    return prepare_export_payloads(result)


@st.cache_data(show_spinner=False, max_entries=2)
def _load_tables() -> dict[str, pd.DataFrame]:
    return load_synthetic_tables("legacy")


def _set_example_question(value: str) -> None:
    st.session_state["question"] = value


def _run_analysis(
    *,
    question: str,
    tables: dict[str, pd.DataFrame],
    goal_mode: str,
    use_langgraph: bool,
    data_source_type: str,
    table_metadata: dict[str, Any] | None,
    column_mapping: dict[str, Any] | None,
    playbook_id: str | None,
    parameters: dict[str, Any],
    execution_mode: str,
    approved_plan_id: str | None = None,
) -> dict[str, Any]:
    return run_agent_analysis(
        question,
        tables,
        goal_mode=goal_mode,
        use_langgraph=use_langgraph,
        data_source_type=data_source_type,
        table_metadata=table_metadata,
        column_mapping=column_mapping,
        playbook_id=playbook_id,
        playbook_parameters=parameters,
        execution_mode=execution_mode,
        approved_plan_id=approved_plan_id,
    )


def main() -> None:
    st.set_page_config(page_title="InsightPilot Agent", page_icon=":material/analytics:", layout="wide")
    apply_compact_theme()
    st.session_state.setdefault("last_analysis_result", None)
    st.session_state.setdefault("last_run_context", None)
    st.title(t("app.title"), anchor=False)
    st.caption(t("app.subtitle"))

    view_mode = render_view_mode_selector()
    goal_modes = [item.value for item in GOAL_MODE_OPTIONS]
    source_mode, goal_mode, use_langgraph = render_source_goal_backend(goal_modes)

    tables: dict[str, pd.DataFrame]
    table_metadata: dict[str, Any] | None
    default_question: str
    data_source_type: str
    registry: TableRegistry | None = None
    if source_mode == "synthetic":
        tables, table_metadata, default_question, data_source_type = render_synthetic_source(view_mode)
    elif source_mode == "upload":
        st.session_state["current_scenario_id"] = "custom"
        tables, table_metadata, default_question, data_source_type, registry = render_upload_source()
    else:
        st.session_state["current_scenario_id"] = "custom"
        tables, table_metadata, default_question, data_source_type, registry = render_database_source()

    column_mapping = render_mapping_panel(registry, goal_mode) if registry is not None else None
    previous_default_question = st.session_state.get("_default_question")
    if "question" not in st.session_state or st.session_state.get("question") == previous_default_question:
        st.session_state["question"] = default_question
    st.session_state["_default_question"] = default_question
    render_example_question_selector(str(st.session_state.get("current_scenario_id", "custom")), view_mode)
    st.text_input(t("section.analysis_question"), key="question", placeholder="请输入希望分析的问题")
    question = str(st.session_state.get("question") or default_question)

    selected_playbook_id = render_playbook_selector(view_mode)
    recommendation_mapping = _mapping_for_playbook_ui("periodic_summary", tables, column_mapping)
    recommended_ids = _recommended_playbook_ids(goal_mode, recommendation_mapping) if tables else []
    resolved_playbook_id = recommended_ids[0] if selected_playbook_id == PLAYBOOK_AUTO and recommended_ids else selected_playbook_id
    selected_playbook = get_playbook_registry().get(str(resolved_playbook_id)) if resolved_playbook_id else None
    playbook_mapping = _mapping_for_playbook_ui(str(resolved_playbook_id or "data_profile"), tables, column_mapping)
    if selected_playbook is not None:
        st.caption(selected_playbook.description)
        if selected_playbook_id == PLAYBOOK_AUTO:
            st.caption(f"当前推荐：{playbook_display_name(selected_playbook.playbook_id, developer=should_show_developer_details(view_mode))}")
        if should_show_professional_details(view_mode):
            requirements = selected_playbook.field_requirements_zh or [
                name.removeprefix("requires_")
                for name, required in selected_playbook.requirements.to_dict().items()
                if name.startswith("requires_") and required
            ]
            st.caption("字段要求：" + ("；".join(requirements) if requirements else "仅需要可用数据表"))

    with st.form("analysis_form", border=True):
        st.markdown("**分析参数**")
        parameters = render_playbook_parameters(selected_playbook, playbook_mapping, tables)
        st.caption("预览分析方案只展示将采用的指标、基准、维度和方法，不执行实际计算。")
        with st.container(horizontal=True):
            preview_plan = st.form_submit_button(t("action.preview_plan"), icon=":material/preview:")
            run_analysis = st.form_submit_button(t("action.run"), type="primary", icon=":material/play_arrow:")

    if preview_plan or run_analysis:
        if not tables:
            st.error(t("empty.no_table"))
        else:
            execution_mode = "plan_only" if preview_plan else "execute"
            try:
                result = _run_analysis(
                    question=question,
                    tables=tables,
                    goal_mode=goal_mode,
                    use_langgraph=use_langgraph,
                    data_source_type=data_source_type,
                    table_metadata=table_metadata,
                    column_mapping=column_mapping,
                    playbook_id=resolved_playbook_id,
                    parameters=parameters,
                    execution_mode=execution_mode,
                )
                st.session_state["last_analysis_result"] = result
                st.session_state["last_run_context"] = {
                    "question": question,
                    "goal_mode": goal_mode,
                    "use_langgraph": use_langgraph,
                    "data_source_type": data_source_type,
                    "table_metadata": table_metadata,
                    "column_mapping": column_mapping,
                    "playbook_id": resolved_playbook_id,
                    "parameters": parameters,
                }
                st.session_state.pop("export_payloads", None)
                st.session_state.pop("export_run_id", None)
                if execution_mode == "execute":
                    render_result_note("分析已完成。以下内容由当前数据实际计算生成。")
                else:
                    render_result_note("当前仅展示分析方案，尚未执行实际计算。")
            except Exception as exc:
                st.error(f"分析执行失败：{exc}")

    latest = st.session_state.get("last_analysis_result")
    context = st.session_state.get("last_run_context")
    if isinstance(latest, dict):
        query_plan = latest.get("query_plan", {})
        review = latest.get("plan_review", {})
        if query_plan.get("requires_approval") and review.get("decision") == "pending" and isinstance(context, dict):
            st.warning(t("warning.plan_approval_required"), icon=":material/warning:")
            approval_key = f"approve_{query_plan.get('plan_id')}"
            approved = st.checkbox(
                "我已复核连接关系、指标粒度和 fanout 风险，并同意执行当前只读查询计划。",
                value=False,
                key=approval_key,
            )
            if st.button(t("action.approve_execute"), type="primary", icon=":material/verified:", disabled=not approved):
                try:
                    latest = _run_analysis(
                        question=context["question"],
                        tables=tables,
                        goal_mode=context["goal_mode"],
                        use_langgraph=context["use_langgraph"],
                        data_source_type=context["data_source_type"],
                        table_metadata=context["table_metadata"],
                        column_mapping=context["column_mapping"],
                        playbook_id=context["playbook_id"],
                        parameters=context["parameters"],
                        execution_mode="execute",
                        approved_plan_id=str(query_plan.get("plan_id")),
                    )
                    st.session_state["last_analysis_result"] = latest
                except Exception as exc:
                    st.error(f"批准后的只读查询执行失败：{exc}")
        render_result_panel(latest, view_mode)
    else:
        st.info(t("empty.no_result"), icon=":material/info:")


if __name__ == "__main__":
    main()
