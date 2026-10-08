"""Explicit branch controls over session-owned immutable run metadata."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json
import hashlib
from typing import Any

import pandas as pd
import streamlit as st

from insightpilot.analysis.threads import compare_runs, validate_history_json
from insightpilot.ui.theme import render_compact_summary_card


def apply_pending_branch() -> None:
    draft = st.session_state.pop("performance_pending_branch", None)
    if not draft:
        return
    from app.background_tasks import background_enabled, cancel_current
    if background_enabled():
        cancel_current(block=False)
    config = draft["config"]
    st.session_state["workbench_page"] = "explore" if (config.get("parameters") or {}).get("exploration_request") else "workbench"
    st.session_state["question"] = str(config.get("question", ""))
    st.session_state["goal_mode_selector"] = config.get("goal_mode", "auto")
    st.session_state["workflow_backend_selector"] = "langgraph" if config.get("use_langgraph") else "rule_based"
    st.session_state["playbook_selector"] = config.get("requested_playbook_id", config.get("playbook_id")) or "__legacy__"
    st.session_state["guided_selection_source"] = "history_restored"
    st.session_state["guided_parameters"] = deepcopy(config.get("parameters") or {})
    st.session_state["guided_mapping"] = deepcopy(config.get("column_mapping"))
    st.session_state["guided_advanced"] = True
    for approval_key in list(st.session_state):
        if approval_key.startswith("approve_"):
            st.session_state.pop(approval_key, None)
    st.session_state["performance_branch_parent"] = draft["parent_run_id"]
    st.session_state["performance_branch_mapping"] = deepcopy(config.get("column_mapping"))
    st.session_state.pop("example_settings", None)
    st.session_state.pop("performance_clarification_state", None)
    # Restore only registered form controls; imported JSON is never sent here.
    mapping = config.get("column_mapping") or {}
    for field, key in {"table_name": "mapping_table", "date_column": "mapping_date", "metric_columns": "mapping_metrics",
        "dimension_columns": "mapping_dimensions", "group_column": "mapping_group", "outcome_column": "mapping_outcome",
        "treatment_column": "mapping_treatment", "covariates": "mapping_covariates", "aggregation": "mapping_aggregation",
        "time_grain": "mapping_grain"}.items():
        if field in mapping:
            value = mapping[field]
            if value is None and field.endswith("column"):
                value = "不选择"
            st.session_state[key] = value
    for key in list(st.session_state):
        if key.startswith("playbook_parameter_"):
            del st.session_state[key]
    requested_method = config.get("playbook_id")
    parameter_method = config.get("effective_playbook_id") if requested_method in {None, "auto", "auto_recommended"} else requested_method
    for name, value in (config.get("parameters") or {}).items():
        if value is not None:
            if name in {"current_start", "current_end", "previous_start", "previous_end", "date_from", "date_to"} and isinstance(value, str):
                value = date.fromisoformat(value[:10])
            st.session_state[f"playbook_parameter_{parameter_method}_{name}"] = value
    st.session_state["force_recompute"] = False
    exploration = (config.get("parameters") or {}).get("exploration_request")
    if exploration:
        from app.components.data_source_panel import current_dataset
        dataset = current_dataset()
        if dataset is not None:
            st.session_state["exploration_dataset"] = (dataset.dataset_id, str(dataset.revision))
        restore = {"kind":"exploration_section", "field":"exploration_field", "row_dimension":"exploration_row",
            "column_dimension":"exploration_column", "time_grain":"exploration_grain", "top_n":"exploration_top_n"}
        for name, key in restore.items():
            if exploration.get(name) is not None:
                st.session_state[key] = exploration[name]
        for name,key in {"table_name":"exploration_table", "aggregation":"exploration_aggregation", "date_column":"exploration_date", "unit":"exploration_unit", "numerator_column":"exploration_numerator", "denominator_column":"exploration_denominator"}.items():
            st.session_state[key] = mapping.get(name)
        metrics = mapping.get("metric_columns") or []
        if metrics:
            st.session_state["exploration_metric"] = metrics[0]
        for key in ("date_from", "date_to"):
            value = exploration.get(key)
            st.session_state["exploration_" + key] = date.fromisoformat(str(value)[:10]) if value else None
        # A restored scope is not a new explicit approval. The immutable run
        # remains available; generating a new exploration requires confirmation.
        st.session_state["exploration_confirmed"] = False
        st.session_state["exploration_base_filters"] = deepcopy(exploration.get("filters") or [])
        st.session_state["exploration_filter_column"] = None
        st.session_state["exploration_filter_value"] = ""
        st.session_state["exploration_filter_null"] = False
        st.session_state["exploration_keep_filters"] = True


def _stage(node, config):
    st.session_state["performance_pending_branch"] = {"parent_run_id": node.run_id, "config": config}
    st.rerun()


def _branch_config(node, snapshot):
    config = deepcopy(node.config)
    config.pop("execution_mode", None)
    config.pop("approved_plan_id", None)
    mapping = config.get("column_mapping") or {}
    if not mapping.get("table_name"):
        table = "daily_metrics" if "daily_metrics" in snapshot.metadata else next(iter(snapshot.metadata))
        columns = snapshot.metadata[table].get("columns", [])
        defs = node.context.get("definitions", [])
        metric = next((d.get("metric_id", d.get("metric_name")) for d in defs if d.get("metric_id", d.get("metric_name")) in columns), None)
        mapping = {"table_name": table, "date_column": "date" if "date" in columns else None,
                   "metric_columns": [metric] if metric else [], "dimension_columns": [], "aggregation": "sum", "time_grain": "day"}
    config["column_mapping"] = mapping
    return config


def _activate_history_run(session, node_id):
    if node_id is None:
        return
    from app.background_tasks import background_enabled, cancel_current
    pending = st.session_state.get("performance_background_pending")
    if background_enabled() and pending and pending["kind"] == "analysis":
        cancel_current(block=False)
    session.history.select(node_id)
    st.session_state["history_run_selector"] = node_id


def _select_history_run(session):
    _activate_history_run(session, st.session_state.get("history_run_selector"))


def render_history_controls(session, snapshot, view_mode: str) -> str | None:
    history = session.history
    if not history.nodes:
        return None
    st.subheader("继续分析 / 历史对比", anchor=False)
    labels = {n.node_id: f"{i+1}. {n.config.get('question', '分析')[:38]} · {n.run_id[:8]}" for i, n in enumerate(history.nodes)}
    if st.session_state.get("history_run_selector") not in labels:
        st.session_state["history_run_selector"] = history.active_node_id if history.active_node_id in labels else history.nodes[-1].node_id
    selected = st.selectbox("查看历史运行", list(labels), format_func=labels.get, key="history_run_selector",
                            on_change=_select_history_run, args=(session,))
    if selected != history.active_node_id:
        from app.background_tasks import background_enabled, cancel_current
        if background_enabled():
            pending = st.session_state.get("performance_background_pending")
            if pending and pending["kind"] == "analysis":
                cancel_current(block=False)
        history.select(selected)
    node = history.get(selected)
    available = history.result_available(node, session.current)
    st.caption(f"当前选定运行 {node.run_id}；历史仅保留配置、有限聚合摘要及受控结果引用。最多10条，不增加结果总预算。")
    if not available:
        st.info("结果已释放，点击恢复配置后需要重新执行。此处摘要不代表完整结果仍在。")
        render_compact_summary_card("历史摘要", node.summary.get("text") or "此运行没有数值结论。")
    with st.container(horizontal=True):
        if st.button("基于本次结果继续分析", key="history_continue"):
            _stage(node, _branch_config(node, snapshot))
        if st.button("恢复此运行配置", key="history_restore"):
            _stage(node, deepcopy(node.config))
        parent = next((n for n in history.nodes if n.run_id == node.parent_run_id), None)
        st.button("返回上一步", disabled=parent is None, key="history_back",
                  on_click=_activate_history_run, args=(session, parent.node_id if parent else None))
    details_open = st.toggle("修改维度、基准或比较两次分析", value=False, key="history_details")
    if details_open:
        with st.container(border=True):
            config = _branch_config(node, snapshot)
            mapping = config.get("column_mapping") or {}
            columns = snapshot.metadata.get(mapping.get("table_name"), {}).get("columns", [])
            suggested = snapshot.metadata.get(mapping.get("table_name"), {}).get("schema_mapping", {}).get("possible_dimension_columns", [])
            dimensions = [c for c in suggested if c in columns] or [c for c in columns if c not in {mapping.get("date_column"), *(mapping.get("metric_columns") or [])}]
            selected_dimension = st.selectbox("分支维度", dimensions, index=None, placeholder="请选择本次要分析的维度", key="history_dimension") if dimensions else None
            if st.button("修改维度重新分析", disabled=not selected_dimension, key="history_change_dimension"):
                mapping["dimension_columns"] = [selected_dimension]
                config.update(playbook_id="period_comparison" if mapping.get("date_column") else "dimension_contribution", goal_mode="metric_diagnosis")
                config["parameters"] = {"aggregation": mapping.get("aggregation", "sum")}
                if config["playbook_id"] == "dimension_contribution":
                    config["parameters"].update(dimension=selected_dimension, metric=next(iter(mapping.get("metric_columns") or []), None))
                _stage(node, config)
            end = st.date_input("分支当前周期结束", value=None, key="history_current_end")
            base = st.date_input("分支对比周期结束", value=None, key="history_baseline_end")
            if st.button("修改对比基准", disabled=not (end and base and mapping.get("date_column")), key="history_change_baseline"):
                config.update(playbook_id="period_comparison", goal_mode="metric_diagnosis")
                config["parameters"] = {"comparison_type": "custom", "current_start": str(end-timedelta(days=6)), "current_end": str(end),
                                        "previous_start": str(base-timedelta(days=6)), "previous_end": str(base), "aggregation": mapping.get("aggregation", "sum")}
                _stage(node, config)
            st.caption("上述操作只预填现有表单；只有点击“开始分析”才执行。")
            other_ids = [n.node_id for n in history.nodes if n.node_id != node.node_id]
            other = st.selectbox("与另一条分析比较", other_ids, index=None, format_func=labels.get, placeholder="请选择另一运行", key="history_compare_target")
            if other:
                compared = compare_runs(history.get(other), node)
                status = {"comparable": "口径一致，可描述性比较", "context_differs": "上下文不同，仅作描述性比较", "not_comparable": "不可直接比较"}[compared["status"]]
                render_compact_summary_card("可比性检查", [status, *compared["reasons"], compared["notice"]])
                if compared["configuration_differences"]:
                    st.dataframe(pd.DataFrame([{"配置": x["field"], "运行A": str(x["left"]), "运行B": str(x["right"])} for x in compared["configuration_differences"]]),hide_index=True)
                if compared["rows"]:
                    rows = [{"指标":r["metric_id"], "口径版本":r["definition_version"], "维度键":str(r["group"]), "运行A":r["run_a"], "运行B":r["run_b"], "绝对差":r["absolute_change"], "相对差":r["relative_change"], "单位":r["unit"], "说明":r["note"]} for r in compared["rows"]]
                    st.dataframe(pd.DataFrame(rows), hide_index=True)
    if view_mode == "developer":
        portable = st.expander("脱敏分支配置文件", key="history_portable", on_change="rerun")
        if portable.open:
            with portable:
                history_key = ("history", history.thread_id, hashlib.sha256("|".join(n.node_id+":"+n.run_id for n in history.nodes).encode()).hexdigest())
                if st.button("生成脱敏分支历史 JSON", key="history_export_prepare"):
                    from app.components.export_panel import EXPORT_CACHE_KEY, _new_export_cache
                    cache = st.session_state.get(EXPORT_CACHE_KEY)
                    if cache is None:
                        cache = _new_export_cache(session.config); st.session_state[EXPORT_CACHE_KEY] = cache
                    cache.put(history_key, history.export_json().encode("utf-8"))
                cache = st.session_state.get("performance_export_cache")
                payload = cache.get(history_key) if cache is not None else None
                if payload is not None:
                    st.download_button("下载脱敏分支历史 JSON", payload, file_name="analysis_history.json", mime="application/json", on_click="ignore")
                epoch = int(st.session_state.get("performance_history_import_epoch", 0))
                uploaded = st.file_uploader("核验历史 JSON（不恢复授权或结果）", type=["json"],
                    key=f"history_import_{epoch}", max_upload_size=1)
                if uploaded is not None:
                    try:
                        if uploaded.size > 512 * 1024 or uploaded.size + history.size_bytes > history.max_bytes:
                            raise ValueError("历史JSON超过512KiB或当前历史元数据预算。")
                        parsed = validate_history_json(uploaded.getvalue().decode("utf-8"))
                        message = f"schema、版本和引用关系通过；{len(parsed['nodes'])}条配置需要重新提供数据与脱敏字段。未恢复结果、执行SQL或读取文件路径。"
                        st.session_state["performance_history_import_message"] = (True, message)
                    except (ValueError, UnicodeError, TypeError) as exc:
                        st.session_state["performance_history_import_message"] = (False, "历史导入拒绝：" + str(exc))
                    st.session_state["performance_history_import_epoch"] = epoch + 1
                    st.rerun()
                message = st.session_state.get("performance_history_import_message")
                if message:
                    (st.success if message[0] else st.error)(message[1])

    return node.node_id
