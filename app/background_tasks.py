"""UI-thread bridge to bounded pure workers. No waiting on a future in the UI."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from uuid import uuid4

import streamlit as st

from insightpilot.reports.manifest import _safe_string


def background_enabled() -> bool:
    return os.environ.get("INSIGHTPILOT_UI_SYNC", "0") != "1"


def source_token(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def task_owner() -> str:
    # Keep the owner through release so a draining native task still owns its slot.
    return st.session_state.setdefault("_background_owner", str(uuid4()))


def task_snapshot():
    from insightpilot.performance_tasks import get_task_manager
    return get_task_manager().snapshot(task_owner())


def cancel_current(*, block: bool = True) -> None:
    from insightpilot.performance_tasks import get_task_manager
    pending = st.session_state.pop("performance_background_pending", None)
    if block and pending:
        blocked = st.session_state.setdefault("performance_background_blocked", {})
        blocked[pending["kind"]] = pending["key"]
    manager = get_task_manager()
    active = manager.snapshot(task_owner())
    if active is not None and active.status in {"queued", "running", "cancel_requested"}:
        st.session_state["_background_draining"] = True
    manager.discard(task_owner())
    st.session_state["performance_task_status"] = "cancel_requested" if active is not None else "cancelled"


def request_work(kind: str, key: str, revision: str, work, *, result_max_bytes: int,
                 size_estimator=None, context: dict[str, Any] | None = None, explicit_retry: bool = False) -> tuple[bool, Any]:
    """Submit once, or transfer a completed exact-match result; never wait."""
    from insightpilot.performance_tasks import (get_task_manager, TaskBusyError,
        TaskCancelledError, TaskExecutionError)
    manager = get_task_manager()
    owner = task_owner()
    pending = st.session_state.get("performance_background_pending")
    identity = (kind, key, str(revision))
    if pending and (pending["kind"], pending["key"], pending["revision"]) != identity:
        cancel_current(block=False)
        pending = None
    if st.session_state.get("performance_background_blocked", {}).get(kind) == key:
        return False, None
    snapshot = manager.snapshot(owner)
    if pending and snapshot is None:
        st.session_state.pop("performance_background_pending", None)
        st.session_state["performance_task_status"] = "cancelled"
        if not explicit_retry:
            st.session_state.setdefault("performance_background_blocked", {})[kind] = key
            st.warning("之前提交的任务已过期或被清理，未自动重跑。请显式刷新数据或重新提交分析。")
            return False, None
        pending = None
    if pending and snapshot is not None and snapshot.task_id == pending["task_id"]:
        st.session_state["performance_task_status"] = snapshot.status
        if snapshot.status in {"completed", "failed", "cancelled"}:
            st.session_state.pop("performance_background_pending", None)
            try:
                value = manager.take_result(owner, pending["task_id"], key, str(revision))
            except TaskCancelledError:
                st.session_state.setdefault("performance_background_blocked", {})[kind] = key
                st.session_state["performance_task_status"] = "cancelled"
                return False, None
            except TaskExecutionError:
                st.session_state.setdefault("performance_background_blocked", {})[kind] = key
                st.session_state["performance_task_status"] = "failed"
                raise
            return True, value
        return False, None
    if snapshot is not None and snapshot.status in {"queued", "running", "cancel_requested"}:
        # No pending queue: the user may retry after the previous native stage ends.
        st.session_state["performance_task_status"] = snapshot.status
        if kind == "analysis":
            st.warning("旧任务的当前步骤尚未结束，本次新分析未提交。请等待取消完成后再次点击开始分析或批准执行。")
        return False, None
    if snapshot is not None:
        manager.discard(owner)
    try:
        snapshot = manager.submit(owner, key, str(revision), work,
            result_max_bytes=result_max_bytes, size_estimator=size_estimator)
    except TaskBusyError:
        st.session_state["performance_task_status"] = "busy"
        st.warning("计算槽位正忙，未排入等待队列。可稍后点击“加载 / 刷新当前数据”或重新提交分析。")
        st.session_state.setdefault("performance_background_blocked", {})[kind] = key
        return False, None
    st.session_state.pop("_background_draining", None)
    st.session_state["performance_background_pending"] = {
        "kind": kind, "key": key, "revision": str(revision), "task_id": snapshot.task_id,
        "context": dict(context or {}),
    }
    st.session_state["performance_task_status"] = snapshot.status
    return False, None


_PHASE_LABELS = {
    "dataset_budget": "检查数据内存预算", "dataset_table_copy": "创建受控表快照",
    "dataset_snapshot": "创建受控数据快照", "dataset_validation": "检查数据质量",
    "dataset_schema": "识别字段结构", "dataset_table_fingerprint": "计算完整表指纹",
    "dataset_profile": "检查数据质量与字段结构", "dataset_fingerprints": "计算精确数据指纹",
    "result_quality_scan": "检查分析结果质量", "load_data_source": "准备数据源",
    "run_playbook": "执行分析剧本", "run_routed_analysis": "执行所选分析",
    "statistics_result_package": "构建统计结果", "input_fingerprint": "校验输入指纹",
    "build_manifest": "构建运行清单", "review": "复核分析结果", "generate_report": "生成结果摘要",
    "database_connection": "建立只读数据库连接", "table_registration": "注册查询表",
    "sql_query": "执行只读查询", "observability": "整理运行记录",
    "planning": "制定分析计划", "start": "开始任务", "completed": "完成任务",

    "data_loading": "数据加载 / 文件解析 / 模拟数据生成",
    "dataset_preparation": "数据快照、质量检查与精确指纹",
    "upload_identification": "上传内容精确哈希",
    "excel_sheet_discovery": "Excel 工作表目录读取",
    "analysis": "已提交的分析工作流",
}
_STATUS_LABELS = {"idle": "空闲", "queued": "准备中", "running": "运行中",
    "cancel_requested": "取消请求已收到", "cancelled": "已取消",
    "completed": "已完成", "failed": "失败", "busy": "计算槽位正忙"}


@st.fragment(run_every=0.5)
def _poll_background_status() -> None:
    snapshot = task_snapshot()
    if snapshot is None:
        if st.session_state.get("performance_background_pending") is not None:
            st.rerun()
        if st.session_state.pop("_background_draining", False):
            st.session_state["performance_task_status"] = "cancelled"
            st.rerun()
        status = st.session_state.get("performance_task_status", "idle")
        st.caption("当前任务：" + _STATUS_LABELS.get(status, status))
        return
    status = snapshot.status
    pending = st.session_state.get("performance_background_pending")
    if pending and pending["kind"] == "analysis" and pending["task_id"] == snapshot.task_id:
        dataset = st.session_state.get("performance_dataset")
        context = pending.get("context", {})
        if (dataset is not None and dataset.dataset_id == context.get("dataset_id")
                and str(dataset.revision) == pending["revision"]):
            # Touch only the bound revision; no parsing, profiling or fingerprint work.
            _ = dataset.current
    phase_key = snapshot.phase.removesuffix(":completed")
    phase = _PHASE_LABELS.get(phase_key, phase_key if any("\u4e00" <= char <= "\u9fff" for char in phase_key) else "执行分析步骤")
    if snapshot.phase.endswith(":completed"):
        phase += "（已完成）"
    st.caption(f"当前任务：{_STATUS_LABELS.get(status, status)}；阶段：{_safe_string(phase)}；已用时 {snapshot.elapsed:.1f} 秒。")
    if status in {"queued", "running", "cancel_requested"}:
        if st.button("取消当前任务", disabled=status == "cancel_requested", key="cancel_background_task"):
            cancel_current()
            st.rerun()
        if status == "cancel_requested":
            st.info("取消请求已收到，当前步骤结束后停止；运行中的原生计算所持引用尚未释放。")
    elif st.session_state.get("performance_background_pending") is not None:
        # Transfer and adoption happen in the full app after current UI configuration is known.
        st.rerun()
    else:
        from insightpilot.performance_tasks import get_task_manager
        get_task_manager().discard(task_owner())
        st.rerun()


def render_background_status() -> None:
    if (task_snapshot() is not None or st.session_state.get("performance_background_pending") is not None
            or st.session_state.get("_background_draining")):
        _poll_background_status()
    else:
        status = st.session_state.get("performance_task_status", "idle")
        st.caption("当前任务：" + _STATUS_LABELS.get(status, status))
