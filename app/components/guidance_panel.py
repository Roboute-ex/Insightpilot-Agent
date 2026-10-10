"""Small session-owned guidance state and presentation; no analysis work here."""
from __future__ import annotations

from copy import deepcopy
import streamlit as st

from insightpilot.planning.goal_modes import GOAL_MODE_OPTIONS
from insightpilot.ui.i18n import t
from app.components.semantic_panel import PLAYBOOK_AUTO, PLAYBOOK_NONE, playbook_display_name


def clear_request_confirmations() -> None:
    for key in list(st.session_state):
        if key.startswith("approve_") or key in {"performance_clarification_state", "guided_advice", "guided_last_preflight"}:
            st.session_state.pop(key, None)


def _mounted_form_keys() -> set[str]:
    """Visible form values stay browser-owned until submit or explicit restore."""
    page = st.session_state.get("workbench_page", "workbench")
    keys = set()
    section = st.session_state.get("exploration_section", "fields")
    if page == "explore" and section in {"distribution", "grouped", "pivot"}:
        keys.update("exploration_" + name for name in (
            "date", "grain", "date_from", "date_to", "filter_column", "filter_operator",
            "filter_value", "filter_null", "top_n", "confirmed"))
        if st.session_state.get("exploration_base_filters"):
            keys.add("exploration_keep_filters")
        if section == "distribution":
            keys.add("exploration_field")
        else:
            keys.update({"exploration_metric", "exploration_row", "exploration_unit"})
            if st.session_state.get("exploration_aggregation") == "ratio_of_sums":
                keys.update({"exploration_numerator", "exploration_denominator"})
            if section == "pivot":
                keys.add("exploration_column")
    if page == "workbench" and st.session_state.get("guided_advanced", False):
        method = st.session_state.get("playbook_selector")
        if method == PLAYBOOK_AUTO:
            method = ((st.session_state.get("guided_advice") or {}).get("effective_method") or {}).get("id")
        if method not in {None, "legacy", PLAYBOOK_NONE, PLAYBOOK_AUTO}:
            keys.update(key for key in st.session_state if key.startswith(f"playbook_parameter_{method}_"))
    return keys


def initialize_guidance() -> None:
    # Keep stable configuration even when its widget is deliberately not rendered.
    mounted_form_keys = _mounted_form_keys()
    for key in list(st.session_state):
        # Self-assignment marks a value as new and sends set_value=True to the
        # browser, overwriting pending form edits even if the widget stays mounted.
        if key in mounted_form_keys:
            continue
        if (key.startswith(("playbook_parameter_", "mapping_", "exploration_chart_type_"))
                or key.startswith("result_table_") and key.endswith(("_size", "_sort", "_descending", "_filter_column", "_filter_text", "_page"))
                or key in {
            "exploration_aggregation", "exploration_column", "exploration_confirmed", "exploration_date_from", "exploration_date_to", "exploration_date",
            "exploration_denominator", "exploration_field_page", "exploration_field", "exploration_filter_column", "exploration_filter_null",
            "exploration_filter_operator", "exploration_filter_value", "exploration_grain", "exploration_keep_filters", "exploration_metric",
            "exploration_numerator", "exploration_row", "exploration_section", "exploration_table", "exploration_top_n", "exploration_unit",
            "history_run_selector", "history_details", "history_dimension", "history_current_end", "history_baseline_end", "history_compare_target",
            "question", "playbook_selector", "goal_mode_selector", "workflow_backend_selector",
            "force_recompute", "demo_scale", "demo_seed", "history_run_selector",
            "workbench_page", "method_search", "method_category", "result_chart_selector", "result_table_selector", "result_tabs",
            "guided_advanced", "guided_mapping_open", "guided_plan", "guided_more_examples", "guided_quality", "guided_technical",
        }):
            st.session_state[key] = st.session_state[key]
    if "guided_selection_source" not in st.session_state:
        old = st.session_state.get("playbook_selector")
        st.session_state["guided_selection_source"] = "legacy_unconfirmed" if old not in {None, PLAYBOOK_AUTO} else "automatic"
        st.session_state.setdefault("playbook_selector", PLAYBOOK_AUTO)
    st.session_state.setdefault("goal_mode_selector", "auto")
    st.session_state.setdefault("workflow_backend_selector", "rule_based")
    st.session_state.setdefault("guided_parameters", {})
    # Keep the old machine field without bringing the three-mode UI back.
    st.session_state.setdefault("view_mode", "demo")


def question_changed() -> None:
    st.session_state.pop("guided_example_notice", None)
    previous = st.session_state.get("guided_advice") or {}
    if st.session_state.get("playbook_selector") == PLAYBOOK_AUTO:
        from app.components.data_source_panel import current_dataset
        from insightpilot.planning.planner import prepare_analysis_request
        snapshot = current_dataset()
        probe = prepare_analysis_request(str(st.session_state.get("question") or ""),
            table_metadata=snapshot.metadata if snapshot else {},
            goal_mode=st.session_state.get("goal_mode_selector", "auto"), playbook_id=PLAYBOOK_AUTO,
            column_mapping=st.session_state.get("guided_mapping") or st.session_state.get("performance_branch_mapping"),
            playbook_parameters={}, dataset_revision=str(snapshot.revision) if snapshot else "", selection_source="automatic")
        old_method = (previous.get("effective_method") or {}).get("method_ref")
        new_method = (probe.get("analysis_advice", {}).get("effective_method") or {}).get("method_ref")
        if old_method and old_method != new_method:
            st.session_state["guided_parameters"] = {}
            for key in list(st.session_state):
                if key.startswith("playbook_parameter_"):
                    st.session_state.pop(key, None)
            st.session_state["guided_parameter_notice"] = "问题对应的推荐方法已变化，已清理旧方法参数；尚未执行分析。"
        if st.session_state.get("guided_selection_source") == "example_applied":
            st.session_state["guided_selection_source"] = "automatic"
    clear_request_confirmations()


def restore_recommendation() -> None:
    st.session_state["playbook_selector"] = PLAYBOOK_AUTO
    st.session_state["goal_mode_selector"] = "auto"
    st.session_state["guided_selection_source"] = "automatic"
    st.session_state["guided_parameters"] = {}
    st.session_state.pop("guided_parameter_notice", None)
    for key in list(st.session_state):
        if key.startswith("playbook_parameter_"):
            st.session_state.pop(key, None)
    clear_request_confirmations()


def open_mapping() -> None:
    st.session_state["guided_advanced"] = True
    st.session_state["guided_mapping_open"] = True


def open_goal_settings() -> None:
    st.session_state["guided_advanced"] = True


def confirm_old_method() -> None:
    st.session_state["guided_selection_source"] = "user_selected"
    clear_request_confirmations()


def render_goal_backend() -> tuple[str, bool]:
    goal = st.selectbox("分析目标", [x.value for x in GOAL_MODE_OPTIONS],
        format_func=lambda value: t(f"goal.{value}", value), key="goal_mode_selector")
    backend = st.selectbox("工作流后端", ["rule_based", "langgraph"],
        format_func=lambda value: t(f"backend.{value}"), key="workflow_backend_selector")
    return str(goal), backend == "langgraph"


def _method_name(method) -> str:
    return str((method or {}).get("display_name") or "待确认")


def render_advice(prepared) -> bool:
    advice = prepared.get("analysis_advice") or {}
    st.session_state["guided_advice"] = deepcopy(advice)
    st.session_state["guided_last_preflight"] = prepared
    status = prepared.get("planning_status", "invalid_input")
    if st.session_state.get("guided_parameter_notice"):
        st.caption(st.session_state["guided_parameter_notice"])
    can_submit = bool(advice.get("can_submit", status == "ready"))
    recommended = advice.get("recommended_method") or {}
    effective = advice.get("effective_method") or {}
    requested = advice.get("requested_method") or {}
    source = st.session_state.get("guided_selection_source", "automatic")
    from insightpilot.ui.theme import render_compact_summary_card
    reason = recommended.get("reason_zh") or recommended.get("reason") or recommended.get("reasons") or recommended.get("reason_messages")
    details = []
    definitions = prepared.get("metric_definitions") or []
    if definitions:
        details.append("指标：" + "、".join(str(item.get("display_name", item.get("metric_id", ""))) for item in definitions[:3]))
    if reason:
        details.append("；".join(map(str, reason)) if isinstance(reason, list) else str(reason))
    render_compact_summary_card("建议：" + _method_name(recommended), details or "请先确认当前分析范围与指标。")
    if source in {"user_selected", "history_restored", "legacy_unconfirmed"}:
        prefix = {"user_selected": "已手动选择", "history_restored": "从历史恢复", "legacy_unconfirmed": "旧会话保留的方法（来源尚未确认）"}[source]
        st.caption(f"{prefix}：{_method_name(requested or effective)}。调整面板收起时仍按此配置检查。")
    st.caption("实际将采用：" + (_method_name(effective) if can_submit else "完成当前配置检查后确定"))
    issues = advice.get("blocking_issues") or advice.get("missing_requirements") or []
    if issues:
        st.warning("当前方法暂不可用：" + _method_name(requested or effective or recommended))
        seen = set()
        for issue in issues:
            message = str(issue.get("message_zh") or issue.get("message") or issue) if isinstance(issue, dict) else str(issue)
            if message not in seen:
                st.write(message)
                seen.add(message)
    if source == "legacy_unconfirmed":
        can_submit = False
        st.info("待确认旧会话方法。无法判断此前是否由你主动选择，请接受推荐或明确保留该方法；保留后仍须通过适配检查。")
        st.button("明确保留当前方法", on_click=confirm_old_method, key="guided_confirm_legacy")
    if can_submit:
        st.success("当前配置可用。仅点击“开始分析”后才执行；统计前提与安全门禁仍将在执行时核对。")
    elif status in {"needs_clarification", "invalid_input"}:
        st.info("待补充信息：请修正上述配置或确认必要口径；当前尚未创建分析任务。")
    elif status == "unsupported":
        st.info("当前条件不支持此分析；请查看具体限制或明确调整分析目标。")
    if source in {"user_selected", "history_restored", "legacy_unconfirmed"} or not can_submit:
        with st.container(horizontal=True):
            # Selecting a replacement only changes configuration. Its readiness is
            # checked again by the common Planner on the next normal rerun.
            replacement_ready = recommended.get("data_readiness") == "ready" and recommended.get("goal_fit") != "unrelated"
            st.button("改用推荐方法", on_click=restore_recommendation,
                disabled=not replacement_ready, key="guided_use_recommendation")
            st.button("补充字段配置", on_click=open_mapping, key="guided_configure_mapping")
            if any("GOAL" in str(issue.get("code", "")) for issue in issues if isinstance(issue, dict)):
                st.button("修改本次分析目标", on_click=open_goal_settings, key="guided_change_goal")
    for caveat in effective.get("necessary_caveats", []) if effective else []:
        st.caption(str(caveat))
    return can_submit


def configure_method(playbook_id: str) -> None:
    """Explicit catalog selection opens the existing editor; it never executes."""
    from insightpilot.playbooks.registry import get_playbook_registry
    from app.components.semantic_panel import _method_selected
    playbook = get_playbook_registry().get(playbook_id)
    from app.components.mapping_panel import initialize_mapping_controls
    prepared = st.session_state.get("guided_last_preflight") or {}
    mapping = (st.session_state.get("guided_mapping") or
               prepared.get("normalized_request", {}).get("column_mapping"))
    if not mapping and prepared.get("normalized_request"):
        from app.components.data_source_panel import current_dataset
        from insightpilot.planning.analysis_advisor import _mapping_for_candidate
        snapshot = current_dataset()
        if snapshot is not None:
            mapping, _ = _mapping_for_candidate(playbook_id, prepared, snapshot.metadata)
    if mapping and mapping.get("table_name"):
        from insightpilot.ingestion.mapping import ColumnMapping
        initialize_mapping_controls({**ColumnMapping().to_dict(), **mapping})
    st.session_state["playbook_selector"] = playbook.playbook_id
    _method_selected()
    st.session_state["guided_advanced"] = True
    st.session_state["guided_mapping_open"] = True
    st.session_state["guided_all_methods"] = False
    st.session_state["workbench_page"] = "workbench"
    st.session_state["guided_catalog_notice"] = (
        f"已选择{playbook.display_name}，请确认分析目标、字段映射和参数。"
        "本次选择没有修改问题或分析目标，也没有开始计算。"
    )


def _catalog_state(candidate: dict) -> str:
    if candidate.get("data_readiness") == "incompatible":
        return "当前数据不支持"
    if candidate.get("goal_fit") == "unrelated":
        return "与当前问题不匹配"
    return "可用" if candidate.get("data_readiness") == "ready" else "待补充"


def render_all_methods(advice) -> None:
    """Compatibility wrapper for embedded callers; the workbench links to the library."""
    panel = st.expander("查看全部分析方法", expanded=bool(st.session_state.get("guided_all_methods", False)), key="guided_all_methods", on_change="rerun")
    if panel.open:
        from app.components.method_gallery import render_method_gallery
        with panel:
            render_method_gallery(advice, filters=False)
