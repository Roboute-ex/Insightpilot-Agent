"""Compact example-question selector for synthetic demos."""

from __future__ import annotations

import streamlit as st

from insightpilot.data.example_questions import ExampleQuestion, get_example_questions, get_question_categories
from insightpilot.ui.formatters import format_enum_value
from insightpilot.ui.view_modes import should_show_developer_details, should_show_professional_details


def _fill_question(value: str) -> None:
    st.session_state["question"] = value


def render_example_question_selector(scenario: str, view_mode: str) -> ExampleQuestion | None:
    if scenario not in {"transaction", "content", "live"}:
        return None
    common_only = not should_show_professional_details(view_mode)
    questions = get_example_questions(scenario, common_only=common_only)
    categories = get_question_categories(scenario, common_only=common_only)
    if not questions or not categories:
        return None
    with st.container(border=True):
        st.markdown("**示例问题**")
        category = st.selectbox("问题类别", categories, key=f"example_category_{scenario}_{view_mode}")
        available = [item for item in questions if item.category == category]
        selected_id = st.selectbox(
            "示例问题",
            [item.question_id for item in available],
            format_func=lambda value: next(
                (
                    f"{item.question_zh}（{item.question_id}）"
                    if should_show_developer_details(view_mode)
                    else item.question_zh
                )
                for item in available
                if item.question_id == value
            ),
            key=f"example_question_{scenario}_{view_mode}",
        )
        selected = next(item for item in available if item.question_id == selected_id)
        playbook = format_enum_value("playbook", selected.recommended_playbook) if selected.recommended_playbook else "自动工作流"
        route_suffix = f"；问题编号：{selected.question_id}" if should_show_developer_details(view_mode) else ""
        st.caption(
            f"推荐分析目标：{format_enum_value('goal_mode', selected.recommended_goal_mode)}；"
            f"推荐分析剧本：{playbook}{route_suffix}"
        )
        st.button(
            "填入此问题",
            icon=":material/edit_note:",
            on_click=_fill_question,
            args=(selected.question_zh,),
            key=f"fill_example_{selected.question_id}_{view_mode}",
        )
        if should_show_professional_details(view_mode):
            st.caption(f"所需字段：{'、'.join(selected.required_fields)}；难度：{selected.difficulty}")
    return selected
