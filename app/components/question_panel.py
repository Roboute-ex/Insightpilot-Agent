"""Compact example-question selector for synthetic demos."""

from __future__ import annotations

import streamlit as st

from insightpilot.data.example_questions import ExampleQuestion, get_example_questions, get_question_categories
from insightpilot.ui.formatters import format_enum_value
from insightpilot.ui.view_modes import should_show_developer_details, should_show_professional_details


def _fill_question(selected: ExampleQuestion) -> None:
    from app.components.guidance_panel import restore_recommendation
    restore_recommendation()
    st.session_state.pop("performance_branch_mapping", None)
    st.session_state.pop("performance_branch_parent", None)
    settings = selected.apply_settings()
    st.session_state["question"] = settings["question"]
    st.session_state["guided_selection_source"] = "example_applied"
    st.session_state["example_settings"] = settings
    st.session_state["example_settings_scenario"] = selected.scenario
    # Explicit preset parameters may help a supported question, but are never
    # treated as confirmation of ambiguous fields or custom experiment direction.
    st.session_state["guided_parameters"] = dict(settings.get("parameters") or {})
    st.session_state["guided_example_notice"] = "已填入示例并恢复自动推荐"


def render_example_question_selector(scenario: str, view_mode: str = "demo", snapshot=None) -> ExampleQuestion | None:
    if scenario not in {"transaction", "content", "live"}:
        return None
    from insightpilot.planning.planner import prepare_analysis_request
    questions = get_example_questions(scenario)
    preferred = [q for q in questions if q.common] if questions and hasattr(questions[0], "common") else get_example_questions(scenario, common_only=True)
    cache_key = (scenario, getattr(snapshot, "dataset_id", None), getattr(snapshot, "revision", None))
    cached = st.session_state.get("guided_example_choices")
    if cached and cached[0] == cache_key:
        usable = [q for q in preferred if q.question_id in cached[1]]
    else:
        usable = []
        for q in preferred:
            settings = q.apply_settings()
            check = prepare_analysis_request(q.question_zh, table_metadata=snapshot.metadata if snapshot else {},
                goal_mode="auto", playbook_id="auto", column_mapping=settings.get("column_mapping"),
                playbook_parameters=settings.get("parameters") or {})
            if check["planning_status"] == "ready":
                usable.append(q)
            if len(usable) == 3:
                break
        st.session_state["guided_example_choices"] = (cache_key, [q.question_id for q in usable])
    if usable:
        with st.container(horizontal=True):
            for q in usable:
                st.button(q.question_zh, key="guided_example_"+q.question_id, on_click=_fill_question, args=(q,))
    panel = st.expander("更多示例", expanded=bool(st.session_state.get("guided_more_examples", False)), key="guided_more_examples", on_change="rerun")
    selected = None
    if panel.open:
        with panel:
            categories = get_question_categories(scenario)
            category = st.selectbox("问题类别", categories, key=f"example_category_{scenario}_demo")
            available = [q for q in questions if q.category == category]
            selected_id = st.selectbox("示例问题", [q.question_id for q in available],
                format_func=lambda value: next(q.question_zh for q in available if q.question_id == value),
                key=f"example_question_{scenario}_demo")
            selected = next(q for q in available if q.question_id == selected_id)
            settings = selected.apply_settings()
            check = prepare_analysis_request(selected.question_zh, table_metadata=snapshot.metadata if snapshot else {},
                goal_mode="auto", playbook_id="auto", column_mapping=settings.get("column_mapping"),
                playbook_parameters=settings.get("parameters") or {})
            if check["planning_status"] == "ready":
                st.caption("此示例与当前数据适配。使用后仍需你明确点击开始分析。")
            else:
                st.caption("此示例当前待补充或不支持：")
                for issue in check.get("analysis_advice", {}).get("blocking_issues", []):
                    st.caption(str(issue.get("message_zh", issue)))
            st.caption("使用示例不会执行分析或代替你确认歧义口径。")
            st.button("使用此示例", on_click=_fill_question, args=(selected,), key="guided_apply_example")
    if st.session_state.get("guided_example_notice"):
        st.caption(st.session_state["guided_example_notice"])
    return selected
