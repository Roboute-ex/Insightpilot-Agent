"""Chinese-first guided Streamlit workbench for InsightPilot Agent."""

from __future__ import annotations

import sys
import hashlib
import json
from pathlib import Path
from typing import Any
from copy import deepcopy
from functools import partial

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from app.components.data_source_panel import (
    SCENARIOS,
    current_dataset,
    dataset_session,
    load_synthetic_tables,
    render_database_source,
    render_synthetic_source,
    render_upload_source,
)
from app.components.export_panel import prepare_export_payloads
from app.components.mapping_panel import render_mapping_panel
from app.components.history_panel import apply_pending_branch, render_history_controls, render_restore_prompt
from app.components.analysis_context import render_analysis_context, project_run_context
from app.components.metric_definition_panel import prepare_and_render_clarification, refresh_result_presentation
from app.components.question_panel import render_example_question_selector
from app.components.guidance_panel import initialize_guidance, render_goal_backend, render_advice, clear_request_confirmations, question_changed
from app.components.workbench_shell import render_workbench_navigation, render_data_summary, render_config_summary
from app.components.method_gallery import render_method_gallery, render_common_methods
from insightpilot.planning.planner import prepare_analysis_request
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
from insightpilot.metrics.definitions import computation_payload
from insightpilot.playbooks.models import AnalysisPlaybook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.ui.i18n import t
from insightpilot.reports.manifest import _safe_string
from insightpilot.performance import PerformanceConfig, estimate_size_bytes
from app.background_tasks import background_enabled, cancel_current, request_work, render_background_status, task_snapshot
from app.session_data import AnalysisSession, analysis_cache_key, catalog_version, expire_session_caches
from insightpilot.ui.theme import apply_compact_theme, render_result_note
from insightpilot.ui.view_modes import should_show_developer_details, should_show_professional_details


PLAYBOOK_AUTOMATIC = "保留现有自动工作流"
PLAYBOOK_RECOMMENDED = "Auto recommended"


def _mapping_for_playbook_ui(
    playbook_id: str,
    tables: dict[str, pd.DataFrame],
    mapping: dict[str, Any] | None,
    snapshot=None,
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
    return snapshot.suggest_mapping(table_name) if snapshot is not None else suggest_column_mapping(table_name, tables[table_name])


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
    prepared_dataset=None,
    clarification_answers=None,
    selection_source=None,
    analysis_scope=None,
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
        prepared_dataset=prepared_dataset,
        clarification_answers=clarification_answers,
        selection_source=selection_source, analysis_scope=analysis_scope,
        presentation_mode="deferred",
    )


def _clear_result_views() -> None:
    for key in ("performance_chart_cache", "performance_table_view_cache", "performance_table_csv_cache", "performance_export_cache", "performance_developer_json_cache", "export_payloads", "export_run_id", "developer_json_request"):
        st.session_state.pop(key, None)


def _release_session() -> None:
    if background_enabled():
        cancel_current(block=False)
    for key in list(st.session_state):
        if key.startswith(("performance_", "uploaded_files", "exploration_", "drilldown_", "mapping_", "playbook_parameter_")) or key in {"last_analysis_result", "last_run_context", "export_payloads", "export_run_id", "database_registry", "database_loaded_query", "developer_json_request", "workbench_drilldown_draft", "guided_last_preflight", "guided_advice", "guided_mapping", "guided_parameters"}:
            st.session_state.pop(key, None)
    st.session_state["uploaded_widget_epoch"] = int(st.session_state.get("uploaded_widget_epoch", 0)) + 1
    st.session_state["performance_released"] = True


def _refresh_dataset() -> None:
    if background_enabled():
        cancel_current(block=False)
    dataset_session().clear()
    st.session_state.pop("performance_dataset_request", None)
    st.session_state.pop("performance_dataset_consumed", None)
    st.session_state.pop("performance_background_blocked", None)
    st.session_state["performance_released"] = False


def _analysis_session() -> AnalysisSession:
    session = st.session_state.get("performance_result")
    if not isinstance(session, AnalysisSession):
        session = AnalysisSession()
        st.session_state["performance_result"] = session
    return session


def _analysis_worker(arguments):
    from insightpilot.performance_tasks import report_stage, cancellation_checkpoint
    report_stage("analysis")
    result = _run_analysis(**arguments)
    cancellation_checkpoint()
    return result, estimate_size_bytes(result)


def _accept_analysis_result(result, context, *, cache_hit: bool) -> None:
    if not cache_hit:
        _clear_result_views()
    st.session_state["performance_analysis_cache_hit"] = cache_hit
    context["run_id"] = str((result.get("run_manifest") or {}).get("run_id") or "")
    st.session_state["last_analysis_result"] = result
    st.session_state["last_run_context"] = context
    session = _analysis_session()
    snapshot = current_dataset()
    status = result.get("execution_status", "COMPLETED")
    if (status == "COMPLETED" and result.get("execution_mode") != "plan_only"
            and snapshot is not None and context.get("analysis_config_snapshot") is not None):
        try:
            activate = context.get("view_epoch", 0) == st.session_state.get("performance_view_epoch", 0)
            node = session.history.add(result, context["analysis_config_snapshot"],
                dataset_id=snapshot.dataset_id, revision=snapshot.revision,
                schema={name: metadata.get("columns", []) for name, metadata in snapshot.metadata.items()},
                node_id=None if cache_hit else context.get("node_id"), activate=activate)
            if activate:
                st.session_state["history_run_selector"] = node.node_id
                st.session_state.pop("performance_restored_run_id", None)
            else:
                st.info("已提交的分析已完成，保存在历史比较中；当前查看的历史分析保持不变。")
        except (ValueError, MemoryError) as exc:
            st.warning(f"历史记录未保留：{_safe_string(str(exc))}")
    status = result.get("execution_status", "COMPLETED")
    st.session_state["performance_task_status"] = "failed" if status == "FAILED" else "completed"
    st.session_state["guided_execution_status"] = status
    if result.get("execution_mode") == "plan_only" or status == "PREVIEW":
        render_result_note("当前仅展示分析方案，尚未执行实际计算。")
    elif status == "COMPLETED":
        if cache_hit:
            st.caption("已复用相同配置的成功结果。")
    else:
        label = {"NEEDS_INPUT": "待补充信息", "UNSUPPORTED": "当前条件不支持", "INVALID_INPUT": "配置无效", "WAITING_APPROVAL": "等待审批"}.get(status, "分析失败")
        reasons = result.get("analysis_advice", {}).get("blocking_issues", [])
        messages = [str(x.get("message_zh", x)) if isinstance(x, dict) else str(x) for x in reasons]
        errors = result.get("errors") or result.get("error") or []
        if isinstance(errors, str):
            errors = [errors]
        messages.extend(str(x) for x in errors)
        (st.error if status == "FAILED" else st.warning)(label + ("：" + _safe_string("；".join(messages)) if messages else "。请查看具体检查信息。"))


def _request_analysis(snapshot, current_snapshot, snapshot_signature, *, execution_mode,
                      approved_plan_id=None, force=False, explicit=False) -> None:
    # Recheck this exact frozen request immediately before touching task/history
    # state. Advice rendered before a form submission cannot authorize new values.
    checked = prepare_analysis_request(current_snapshot["question"], table_metadata=snapshot.metadata,
        goal_mode=current_snapshot["goal_mode"], playbook_id=current_snapshot["playbook_id"],
        column_mapping=current_snapshot["column_mapping"], playbook_parameters=current_snapshot["parameters"],
        clarification_answers=current_snapshot.get("clarification_answers"), dataset_revision=str(snapshot.revision),
        selection_source=current_snapshot.get("selection_source"), analysis_scope=current_snapshot.get("analysis_scope"))
    if checked["planning_status"] != "ready" or not checked.get("analysis_advice", {}).get("can_submit", True):
        st.session_state["guided_last_preflight"] = checked
        st.info("待补充信息或当前条件不支持；本次未创建任务，也未执行分析。")
        return
    if checked.get("analysis_advice", {}).get("request_fingerprint") != current_snapshot.get("request_fingerprint"):
        st.warning("分析请求已变化，请核对更新后的建议并重新提交。")
        return
    session = _analysis_session()
    history = session.history
    history.bind_dataset(snapshot.dataset_id, snapshot.revision, preserve_history=True)
    key_config = {**current_snapshot, "execution_mode": execution_mode}
    if approved_plan_id is not None:
        key_config["approved_plan_id"] = approved_plan_id
    key = analysis_cache_key(dataset_id=snapshot.dataset_id, dataset_revision=snapshot.revision,
        config=key_config, catalog_version=current_snapshot["catalog_version"],
        computation_version=current_snapshot["computation_version"])
    pending = st.session_state.get("performance_background_pending")
    if (explicit and pending and pending.get("kind") == "analysis"
            and pending.get("revision") == str(snapshot.revision)
            and pending.get("context", {}).get("dataset_id") == snapshot.dataset_id
            and pending.get("context", {}).get("snapshot_signature") == snapshot_signature):
        st.info("相同分析请求已提交，正在处理；重复点击不会创建第二个任务。")
        return
    if explicit:
        parent = st.session_state.get("performance_branch_parent")
        if parent is not None and not any(n.run_id == parent for n in history.nodes):
            parent = None
        node_id = history.begin_request(parent)
    else:
        node_id = (pending or {}).get("context", {}).get("node_id")
        if node_id is None or node_id != history.request_node_id:
            return
    context = {name: current_snapshot[name] for name in ("question", "goal_mode", "use_langgraph",
        "data_source_type", "column_mapping", "playbook_id", "parameters", "dataset_revision")}
    recorded = {k: deepcopy(v) for k, v in current_snapshot.items() if k not in {"playbook_definition", "catalog_version", "computation_version"}}
    context.update(snapshot_signature=snapshot_signature, table_metadata=snapshot.metadata,
                   analysis_config_snapshot=recorded, node_id=node_id,
                   view_epoch=st.session_state.get("performance_view_epoch", 0) if explicit else
                       (pending or {}).get("context", {}).get("view_epoch", 0))
    cached = None if force else session.lookup(key)
    if cached is not None:
        if background_enabled() and pending and pending["kind"] == "analysis":
            cancel_current(block=False)
        _accept_analysis_result(cached, context, cache_hit=True)
        return
    arguments = deepcopy({name: current_snapshot[name] for name in ("question", "goal_mode",
        "use_langgraph", "data_source_type", "column_mapping", "playbook_id", "parameters")})
    for name in ("clarification_answers", "selection_source", "analysis_scope"):
        if name in current_snapshot:
            arguments[name] = deepcopy(current_snapshot[name])
    arguments.update(tables={}, prepared_dataset=snapshot.prepared, table_metadata=None,
        execution_mode=execution_mode, approved_plan_id=approved_plan_id)
    if not background_enabled():
        st.session_state.pop("last_analysis_result", None)
        st.session_state.pop("last_run_context", None)
        _clear_result_views()
        st.session_state["performance_task_status"] = "running"
        result, hit = session.run(key, partial(_run_analysis, **arguments), force=force)
        _accept_analysis_result(result, context, cache_hit=hit)
        return
    task_key = key + ":" + node_id
    if explicit:
        st.session_state.get("performance_background_blocked", {}).pop("analysis", None)
    if not pending or pending["key"] != task_key:
        st.session_state.pop("last_analysis_result", None)
        st.session_state.pop("last_run_context", None)
        session.clear()
        _clear_result_views()
    ready, output = request_work("analysis", task_key, snapshot.revision, partial(_analysis_worker, arguments),
        result_max_bytes=session.cache.max_bytes, size_estimator=lambda item: item[1],
        context={"snapshot_signature": snapshot_signature, "dataset_id": snapshot.dataset_id,
            "execution_mode": execution_mode, "approved_plan_id": approved_plan_id, "node_id": node_id,
            "view_epoch": context["view_epoch"]}, explicit_retry=explicit)
    if ready:
        if node_id != history.request_node_id:
            return
        result, size = output
        session.accept(key, result, size_bytes=size)
        _accept_analysis_result(result, context, cache_hit=False)


def main() -> None:
    st.set_page_config(page_title="InsightPilot Agent", page_icon=":material/analytics:", layout="wide")
    apply_compact_theme()
    initialize_guidance()
    apply_pending_branch()
    submit_requested = bool(st.session_state.pop("workbench_submit_requested", False))
    if submit_requested:
        st.session_state["guided_selection_source"] = "user_selected"
    expire_session_caches(st.session_state)
    st.session_state.setdefault("last_analysis_result", None)
    st.session_state.setdefault("last_run_context", None)
    st.markdown('<h1 class="ip-workbench-title">InsightPilot Agent</h1>', unsafe_allow_html=True)
    st.caption(t("app.subtitle"))
    page = render_workbench_navigation()

    view_mode = "demo"
    goal_modes = [item.value for item in GOAL_MODE_OPTIONS]
    source_mode, goal_mode, use_langgraph = render_source_goal_backend(goal_modes)
    with st.sidebar.expander("数据管理"):
        st.button("释放本会话数据与结果", on_click=_release_session)
        st.button("加载 / 刷新当前数据", on_click=_refresh_dataset)
    if st.session_state.get("performance_released"):
        active = task_snapshot() if background_enabled() else None
        if active is not None and active.status in {"queued", "running", "cancel_requested"}:
            st.info("已清除本会话页面引用并请求取消；运行中的当前步骤仍持有必要数据，结束后释放。")
            render_background_status()
        else:
            st.info("本会话数据与结果引用已释放。点击“加载 / 刷新当前数据”后继续；上传文件需要重新选择。")
        return
    previous_source = st.session_state.get("performance_source_mode")
    if previous_source is not None and previous_source != source_mode:
        if background_enabled():
            cancel_current(block=False)
        dataset_session().clear()
        st.session_state.pop("performance_dataset_request", None)
        st.session_state.pop("performance_dataset_consumed", None)
        st.session_state.pop("performance_upload_inputs", None)
        st.session_state.pop("performance_upload_files", None)
        st.session_state.pop("performance_database_request", None)
        st.session_state.pop("performance_group_options", None)
    st.session_state["performance_source_mode"] = source_mode
    analysis_session = _analysis_session()
    if st.session_state.get("last_analysis_result") is not None and analysis_session.current is None:
        st.session_state.pop("last_analysis_result", None)
        st.session_state.pop("last_run_context", None)
        _clear_result_views()
        st.info("上次结果已超过会话保留时间，请重新分析。")
    st.session_state.setdefault("performance_task_status", "idle")

    tables: dict[str, pd.DataFrame]
    table_metadata: dict[str, Any] | None
    default_question: str
    data_source_type: str
    registry: TableRegistry | None = None
    try:
        with st.sidebar:
            if source_mode == "synthetic":
                tables, table_metadata, default_question, data_source_type = render_synthetic_source(view_mode)
            elif source_mode == "upload":
                st.session_state["current_scenario_id"] = "custom"
                tables, table_metadata, default_question, data_source_type, registry = render_upload_source()
            else:
                st.session_state["current_scenario_id"] = "custom"
                tables, table_metadata, default_question, data_source_type, registry = render_database_source()
    except Exception as exc:
        st.error(f"数据准备失败：{_safe_string(str(exc))}")
        return
    snapshot = current_dataset()
    if background_enabled() and not tables:
        pending = st.session_state.get("performance_background_pending")
        if pending and pending["kind"] == "analysis":
            cancel_current()
            st.warning("任务绑定的数据快照已不可用，已请求取消；请重新加载数据并显式分析。")
        render_background_status()
        if st.session_state.get("last_analysis_result") is not None:
            st.info("当前数据尚未就绪，上次结果不能作为此数据的分析结果。")
        if page in {"workbench", "history"}:
            render_analysis_context(analysis_session, snapshot)
        return
    if snapshot is not None:
        previous_identity = analysis_session.history.dataset_identity
        analysis_session.history.bind_dataset(snapshot.dataset_id, snapshot.revision, preserve_history=True)
        if previous_identity is not None and previous_identity != (snapshot.dataset_id, str(snapshot.revision)):
            for key in list(st.session_state):
                if key.startswith(("mapping_", "playbook_parameter_", "approve_")) or key in {
                    "performance_branch_mapping", "performance_branch_parent", "performance_clarification_state",
                    "performance_mapping_confirmation", "guided_mapping", "guided_parameters", "guided_advice",
                }:
                    st.session_state.pop(key, None)
    previous_default_question = st.session_state.get("_default_question")
    if "question" not in st.session_state or st.session_state.get("question") == previous_default_question:
        st.session_state["question"] = default_question
    st.session_state["_default_question"] = default_question
    summary_slot = st.container()
    plan_slot = None
    if page == "workbench":
        with st.container(horizontal=True, gap=24, key="workbench_columns"):
            question_column = st.container(width=600, key="workbench_question_column")
            config_column = st.container(width=300, key="workbench_config_column")
        with question_column:
            st.text_input("你想分析什么？", key="question", placeholder="例如：数据中最近完整日的订单量为什么下降？", on_change=question_changed)
            render_example_question_selector(str(st.session_state.get("current_scenario_id", "custom")), view_mode, snapshot)
            advice_slot = st.container()
        with config_column:
            config_summary_slot = st.container()
            configuration_slot = st.container()
        # Keep the primary action after both columns when they stack on narrow screens.
        actions_slot = st.container()
    else:
        question_column = st.container()
        advice_slot = question_column
    question = str(st.session_state.get("question") or "").strip()

    column_mapping = st.session_state.get("guided_mapping") or st.session_state.get("performance_branch_mapping")
    example_settings = st.session_state.get("example_settings") or {}
    if (data_source_type == "synthetic" and
            st.session_state.get("example_settings_scenario") == st.session_state.get("current_scenario_id") and
            question == example_settings.get("question")):
        column_mapping = example_settings.get("column_mapping") or column_mapping
    parameters = deepcopy(st.session_state.get("guided_parameters") or {})
    selected_playbook_id = st.session_state.get("playbook_selector", PLAYBOOK_AUTO)
    if page == "workbench":
        with configuration_slot:
            advanced = st.expander("调整方法与参数", expanded=bool(st.session_state.get("guided_advanced", False)), key="guided_advanced", on_change="rerun")
            if advanced.open:
                with advanced:
                    if notice := st.session_state.pop("guided_catalog_notice", None):
                        st.caption(notice)
                    goal_mode, use_langgraph = render_goal_backend()
                    render_playbook_selector("demo")
                    selected_playbook_id = st.session_state.get("playbook_selector", PLAYBOOK_AUTO)
                    st.caption("方法可以查看和配置；不适用的方法仍会阻断执行。改变分析目标须明确选择，系统不会代选。")
                    if st.toggle("配置分析范围与字段映射", key="guided_mapping_open"):
                        column_mapping = render_mapping_panel(registry or (snapshot.registry if snapshot else None), goal_mode)
                        st.session_state["guided_mapping"] = column_mapping
                    method_id = selected_playbook_id
                    if method_id == PLAYBOOK_AUTO:
                        parameter_context = prepare_analysis_request(question, table_metadata=snapshot.metadata if snapshot else {},
                            goal_mode=goal_mode, playbook_id=PLAYBOOK_AUTO, column_mapping=column_mapping,
                            playbook_parameters=parameters, dataset_revision=str(snapshot.revision) if snapshot else "",
                            selection_source=st.session_state.get("guided_selection_source"))
                        method_id = (parameter_context.get("analysis_advice", {}).get("effective_method") or {}).get("id")
                    selected_playbook = get_playbook_registry().get(str(method_id)) if method_id not in {None, "legacy", PLAYBOOK_NONE, PLAYBOOK_AUTO} else None
                    if selected_playbook is not None:
                        playbook_mapping = _mapping_for_playbook_ui(str(method_id), tables, column_mapping, snapshot)
                        with st.form("analysis_parameter_form"):
                            submitted_parameters = render_playbook_parameters(selected_playbook, playbook_mapping, tables)
                            applied = st.form_submit_button("应用参数并更新建议")
                        if applied:
                            parameters = submitted_parameters
                            st.session_state["guided_parameters"] = deepcopy(parameters)
                            clear_request_confirmations()
                            st.caption("已读取本次提交的参数并重新预检；尚未开始分析。")
                        else:
                            parameters = deepcopy(st.session_state.get("guided_parameters") or {})
                            st.caption("参数表单内的编辑只有点击“应用参数并更新建议”后才生效。")
                    st.checkbox("强制重新计算（忽略上次相同配置结果）", key="force_recompute")
                    plan_slot = st.container()
    force_recompute = bool(st.session_state.get("force_recompute", False))
    selection_source = st.session_state.get("guided_selection_source", "automatic")
    request_config = {"question": question, "goal_mode": goal_mode, "playbook_id": selected_playbook_id,
        "column_mapping": column_mapping, "parameters": parameters, "selection_source": selection_source}
    request_identity = hashlib.sha256(json.dumps(request_config, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    if st.session_state.get("guided_request_identity") != request_identity:
        for approval_key in list(st.session_state):
            if approval_key.startswith("approve_"):
                st.session_state.pop(approval_key, None)
        st.session_state["guided_request_identity"] = request_identity
    with advice_slot:
        prepared_request, clarification_answers = prepare_and_render_clarification(snapshot, request_config, view_mode, render_ui=page == "workbench")
        if page == "workbench":
            can_submit = render_advice(prepared_request) and bool(tables) and bool(question)
        else:
            st.session_state["guided_advice"] = deepcopy(prepared_request.get("analysis_advice") or {})
            st.session_state["guided_last_preflight"] = prepared_request
            can_submit = bool(prepared_request.get("analysis_advice", {}).get("can_submit")) and bool(tables) and bool(question)
    with summary_slot:
        render_data_summary(snapshot, prepared_request)
    if page == "workbench":
        with config_summary_slot:
            render_config_summary(prepared_request, request_config)
    current_snapshot = {
        **request_config, "use_langgraph": use_langgraph, "data_source_type": data_source_type,
        "dataset_id": snapshot.dataset_id if snapshot is not None else None,
        "dataset_revision": snapshot.revision if snapshot is not None else None,
        "catalog_version": catalog_version(PROJECT_ROOT),
        "computation_version": PerformanceConfig.from_environment().computation_version,
        "semantic_fingerprint": prepared_request["semantic_fingerprint"],
        "request_fingerprint": prepared_request.get("analysis_advice", {}).get("request_fingerprint"),
        "effective_playbook_id": prepared_request.get("normalized_request", {}).get("playbook_id"),
        "clarification_answers": clarification_answers,
        "sql_policy_version": __import__("insightpilot.tools.sql_safety",fromlist=["SQL_POLICY_VERSION"]).SQL_POLICY_VERSION,
    }
    snapshot_signature = hashlib.sha256(json.dumps(computation_payload(current_snapshot), sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    run_analysis = submit_requested
    preview_plan = False
    if page == "workbench":
        with actions_slot:
            restored = bool(st.session_state.get("performance_restored_run_id"))
            if restored:
                st.caption("历史配置已恢复为草稿，尚未重新计算。将按当前数据重新预检，并创建新的运行记录。")
            run_analysis = submit_requested or st.button("重新运行该分析" if restored else "开始分析", type="primary", icon=":material/play_arrow:", disabled=not can_submit, key="guided_run")
    if plan_slot is not None:
        with plan_slot:
            plan_details = st.expander("查看分析方案", expanded=bool(st.session_state.get("guided_plan", False)), key="guided_plan", on_change="rerun")
            if plan_details.open:
                with plan_details:
                    st.caption("只检查和展示分析方案，不执行分析SQL或统计。")
                    preview_plan = st.button("预览分析方案", disabled=not can_submit, key="guided_preview")
    if background_enabled():
        pending = st.session_state.get("performance_background_pending")
        if pending and pending["kind"] == "analysis":
            pending_context = pending.get("context", {})
            if (pending["revision"] != str(snapshot.revision)
                    or pending_context.get("dataset_id") != snapshot.dataset_id
                    or pending_context.get("snapshot_signature") != snapshot_signature
                    or pending_context.get("node_id") != analysis_session.history.request_node_id):
                cancel_current(block=False)
                st.warning("数据或分析配置已变化，旧任务已请求取消；旧任务结果不会覆盖当前配置。")
            elif not (preview_plan or run_analysis):
                try:
                    _request_analysis(snapshot, current_snapshot, snapshot_signature,
                        execution_mode=pending_context["execution_mode"],
                        approved_plan_id=pending_context.get("approved_plan_id"))
                except Exception as exc:
                    st.error(f"分析执行失败：{_safe_string(str(exc))}")
    if preview_plan or run_analysis:
        if prepared_request["planning_status"] != "ready":
            st.info("本次未执行分析。请完成必要澄清或修正上述限制后，再明确提交。")
        elif not tables:
            st.error(t("empty.no_table"))
        else:
            try:
                _request_analysis(snapshot, current_snapshot, snapshot_signature,
                    execution_mode="plan_only" if preview_plan else "execute",
                    force=force_recompute or bool(st.session_state.get("performance_restored_run_id")), explicit=True)
            except Exception as exc:
                st.session_state["performance_task_status"] = "failed"
                st.error(f"分析执行失败：{_safe_string(str(exc))}")
    if background_enabled():
        active_task = task_snapshot()
        if (active_task is not None or st.session_state.get("performance_background_pending")
                or st.session_state.get("_background_draining")
                or st.session_state.get("performance_task_status") in {"failed", "cancelled", "busy"}):
            render_background_status()

    selected_node_id = analysis_session.history.active_node_id
    latest = st.session_state.get("last_analysis_result")
    context = st.session_state.get("last_run_context")
    selected_node = None
    viewing_other_request = isinstance(context, dict) and context.get("view_epoch", 0) != st.session_state.get("performance_view_epoch", 0)
    if selected_node_id and (viewing_other_request or latest is None or (latest.get("execution_status") == "COMPLETED" and latest.get("execution_mode") != "plan_only")):
        try:
            selected_node = analysis_session.history.get(selected_node_id)
        except ValueError:
            pass
        if (selected_node is None or not analysis_session.history.result_available(selected_node, analysis_session.current)
                or not project_run_context(analysis_session.history, selected_node.node_id, snapshot)["source_available"]):
            latest = None
        else:
            latest = analysis_session.current
            if not context or context.get("run_id") != selected_node.run_id:
                context = {**selected_node.config, "dataset_revision": selected_node.dataset_revision}
    if (isinstance(context, dict) and snapshot is not None
            and str(context.get("dataset_revision")) != str(snapshot.revision)):
        latest = None
    if page in {"workbench", "history"}:
        # Reserve results after the controls, preserving the input-to-result order.
        with st.container(key="analysis_result_panel"):
            render_analysis_context(analysis_session, snapshot)
            if isinstance(latest, dict):
                stale_result = isinstance(context, dict) and context.get("snapshot_signature") != snapshot_signature
                unfinished_request = (latest.get("execution_status") == "COMPLETED"
                    and st.session_state.get("performance_task_status") in {"queued", "running", "cancel_requested", "cancelled", "failed", "busy"})
                if stale_result:
                    if latest.get("execution_status") == "COMPLETED" and latest.get("execution_mode") != "plan_only":
                        st.warning("上次成功结果：它不是当前未完成请求的结果。编辑中的问题或参数不会混入其报告；请明确开始新的分析。")
                    else:
                        st.warning("上次运行尚未成功完成，且当前配置已变化；下方内容不是本次配置的分析结论。")
                elif unfinished_request:
                    st.info("本次请求尚未产生新结果，下面保留上次成功结果。")
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
                    if st.button(t("action.approve_execute"), type="primary", icon=":material/verified:", disabled=not approved or stale_result):
                        try:
                            _request_analysis(snapshot, current_snapshot, snapshot_signature,
                                execution_mode="execute", approved_plan_id=str(query_plan.get("plan_id")), explicit=True)
                            latest = st.session_state.get("last_analysis_result")
                            if latest is None:
                                st.rerun()
                        except Exception as exc:
                            st.session_state["performance_task_status"] = "failed"
                            st.error(f"批准后的只读查询执行失败：{_safe_string(str(exc))}")
                            return
                # Presentation and exports belong to the selected frozen run,
                # never a newly edited form or a late task's different context.
                render_result_panel(latest, view_mode, run_context=context, previous_result=stale_result or unfinished_request)
                if page == "workbench" and st.session_state.get("performance_selected_result_tab", "分析概览") == "分析概览":
                    from app.components.drilldown_panel import render_drilldown_panel
                    render_drilldown_panel(latest, snapshot, analysis_session)
            elif page == "history" and not selected_node_id:
                st.info(t("empty.no_result"), icon=":material/info:")

    if page == "methods":
        render_method_gallery(prepared_request.get("analysis_advice") or {})
    elif page == "explore":
        from app.components.exploration_panel import render_exploration_panel
        render_exploration_panel(snapshot, analysis_session)
    elif page == "history":
        if snapshot is not None and analysis_session.history.nodes:
            render_history_controls(analysis_session, snapshot, "developer")
        else:
            st.info("还没有历史运行。先在分析工作台或数据探索中明确生成一次结果。")
    elif page == "workbench":
        if not analysis_session.history.nodes and (not isinstance(latest, dict) or latest.get("execution_status") != "COMPLETED"):
            render_common_methods(prepared_request.get("analysis_advice") or {})


if __name__ == "__main__":
    main()
