"""Synthetic, upload, and read-only database source controls."""

from __future__ import annotations

from typing import Any
import hashlib
import json
import io
from functools import partial
from copy import deepcopy

import pandas as pd
import streamlit as st

from insightpilot.data.synthetic import generate_all_demo_data, generate_multi_table_commerce_data
from insightpilot.data.scenarios import DemoScale, generate_demo_scenario
from insightpilot.ingestion.db_loader import is_safe_select_query, mask_database_url, run_database_query
from insightpilot.ingestion.file_loader import get_excel_sheet_names, load_uploaded_file, read_csv_file, read_excel_file
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.ui.formatters import METRIC_DISPLAY_NAMES, format_metric_name
from insightpilot.ui.i18n import t
from insightpilot.reports.manifest import _safe_string
from insightpilot.ui.synthetic_display import synthetic_display_text
from app.session_data import DatasetSession, DatasetSnapshot, prepare_dataset_snapshot
from app.background_tasks import background_enabled, source_token, request_work, cancel_current
from insightpilot.performance import MemoryBudgetExceeded


SCENARIOS: dict[str, dict[str, Any]] = {
    "交易转化异常分析": {
        "question": "为什么昨天某城市订单量下降？",
        "tables": ["daily_metrics", "traffic_events", "orders", "users"],
        "dataset": "transaction",
        "scenario_id": "transaction",
    },
    "内容消费与实验分析": {
        "question": "新策略是否提升了内容完播率？",
        "tables": ["content_events", "content_items", "experiments", "users"],
        "dataset": "content",
        "scenario_id": "content",
    },
    "体验质量分析": {
        "question": "请定位体验质量异常的主要维度。",
        "tables": ["live_quality_logs", "live_broadcasts", "live_sessions", "live_hosts", "live_interactions"],
        "dataset": "live",
        "scenario_id": "live",
    },
    "多表语义指标分析": {
        "question": "请按日期分析总金额，并预览多表连接方案。",
        "tables": ["orders", "customers", "sessions", "order_items", "products", "channels", "calendar"],
        "dataset": "multi_table",
        "scenario_id": "multi_table",
    },
}


def load_synthetic_tables(dataset: str, scale: str = "standard", seed: int = 42) -> dict[str, pd.DataFrame]:
    if dataset == "multi_table":
        return generate_multi_table_commerce_data(seed=seed)
    if dataset in {"transaction", "content", "live"}:
        return generate_demo_scenario(dataset, scale=scale, seed=seed).tables
    return generate_all_demo_data(seed=seed)


def dataset_session() -> DatasetSession:
    session = st.session_state.get("performance_dataset")
    if not isinstance(session, DatasetSession):
        session = DatasetSession()
        st.session_state["performance_dataset"] = session
    return session


def current_dataset() -> DatasetSnapshot | None:
    return dataset_session().current


def _dataset_load(key, loader, source_type: str, retained_source_bytes: int = 0) -> DatasetSnapshot | None:
    session = dataset_session()
    current = session.current
    if current is not None and current.source_key == key:
        st.session_state["performance_dataset_cache_hit"] = True
        return current
    if not background_enabled():
        snapshot, hit = session.load(key, loader, source_type=source_type, retained_source_bytes=retained_source_bytes)
        st.session_state["performance_dataset_cache_hit"] = hit
        return snapshot
    token = source_token(key)
    request = st.session_state.get("performance_dataset_request")
    if request and request["key"] == token and st.session_state.get("performance_dataset_consumed") == token:
        st.info("当前数据快照已过期或释放，未自动重读。请点击“加载 / 刷新当前数据”后继续。")
        return None
    request = st.session_state.get("performance_dataset_request")
    if not request or request["key"] != token:
        cancel_current(block=False)
        st.session_state.pop("performance_dataset_consumed", None)
        revision = session.reserve_revision()
        request = {"key": token, "revision": revision}
        st.session_state["performance_dataset_request"] = request
    work = partial(prepare_dataset_snapshot, key, loader, source_type=source_type,
        dataset_id=session.dataset_id, revision=request["revision"], config=session.config,
        retained_source_bytes=retained_source_bytes)
    ready, snapshot = request_work("dataset", token, request["revision"], work,
        result_max_bytes=session.config.dataset_max_bytes, size_estimator=lambda item: item.estimated_bytes)
    if ready:
        session.adopt(snapshot)
        st.session_state["performance_dataset_consumed"] = token
        st.session_state["performance_dataset_cache_hit"] = False
        return snapshot
    return None


def render_registry_summary(registry: TableRegistry) -> None:
    st.subheader(t("section.data_overview"), anchor=False)
    rows = []
    for name in registry.list_tables():
        metadata = registry.get_metadata(name)
        rows.append(
            {
                "数据表": name,
                "行数": metadata.get("row_count"),
                "字段数": metadata.get("column_count"),
                "数据来源": metadata.get("source_type"),
                "警告数": len(metadata.get("warnings", [])),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True)


def render_loaded_registry(registry: TableRegistry) -> None:
    st.caption(f"数据已就绪：{len(registry.list_tables())}张自定义数据表")
    panel = st.expander("查看数据", expanded=bool(st.session_state.get("guided_data_preview", False)), key="guided_data_preview", on_change="rerun")
    if panel.open:
        with panel:
            render_registry_summary(registry)
            preview = st.selectbox("预览数据表（不改变分析范围）", registry.list_tables(), key="preview_table")
            st.dataframe(registry.get_table(preview).head(20), hide_index=True, width="stretch")


def render_synthetic_source(view_mode: str = "demo") -> tuple[dict[str, pd.DataFrame], None, str, str]:
    scenario_name = st.sidebar.selectbox(t("sidebar.demo_scenario"), list(SCENARIOS), key="demo_scenario")
    scenario = SCENARIOS[scenario_name]
    scale_options = [DemoScale.SMALL.value, DemoScale.STANDARD.value, DemoScale.LARGE.value]
    scale = str(st.session_state.get("demo_scale", "standard"))
    seed = int(st.session_state.get("saved_demo_seed", 42))
    with st.sidebar:
        settings = st.expander("数据设置", expanded=bool(st.session_state.get("guided_data_settings", False)), key="guided_data_settings", on_change="rerun")
        if settings.open:
            with settings:
                scale = st.selectbox("数据规模", scale_options, index=scale_options.index(scale),
                    format_func=lambda value: {"small": "小型", "standard": "标准", "large": "大型"}[value], key="demo_scale")
                seed = int(st.number_input("随机种子", min_value=0, max_value=1_000_000, value=seed, key="demo_seed"))
    st.session_state["saved_demo_seed"] = seed
    snapshot = _dataset_load(("synthetic", scenario["dataset"], scale, seed),
                             lambda: (load_synthetic_tables(str(scenario["dataset"]), scale, seed), None), "synthetic")
    if snapshot is None:
        st.session_state["current_scenario_id"] = scenario["scenario_id"]
        return {}, None, str(scenario["question"]), "synthetic"
    tables = snapshot.tables
    st.session_state["current_scenario_id"] = scenario["scenario_id"]
    st.caption(f"数据已就绪：{scenario_name} · { {'small': '小型', 'standard': '标准', 'large': '大型'}[scale] }模拟数据 · {len(tables)}张表")
    st.caption("日期基于数据参考日；问题中的昨日指数据中最近完整日，并非电脑当前日期。")
    preview_panel = st.expander("查看数据", expanded=bool(st.session_state.get("guided_data_preview", False)), key="guided_data_preview", on_change="rerun")
    if preview_panel.open:
        with preview_panel:
            preview_options = [name for name in scenario["tables"] if name in tables]
            preview = st.selectbox("预览数据表（不改变分析范围）", preview_options, key="preview_table")
            st.caption("仅预览前20行；原始字段和取值保持不变，分析使用完整数据。")
            st.dataframe(tables[preview].head(20), hide_index=True, width="stretch")
    return tables, snapshot.metadata, str(scenario["question"]), "synthetic"


def load_uploaded_registry(uploaded_files: list[Any], selections: dict[int, dict[str, Any]] | None = None) -> TableRegistry:
    registry = TableRegistry()
    for index, uploaded in enumerate(uploaded_files):
        options = (selections or {}).get(index, {})
        if str(uploaded.name).lower().endswith((".xlsx", ".xlsm", ".xls")):
            sheets = options.get("sheets")
            if sheets is None:
                sheets = get_excel_sheet_names(uploaded)[:1]
            loaded_tables = [read_excel_file(uploaded, sheet_name=sheet, table_name=f"{uploaded.name}_{sheet}") for sheet in sheets]
        else:
            loaded_tables = [read_csv_file(uploaded, table_name=uploaded.name, encoding=options.get("encoding"), sep=options.get("sep", ","))]
        for loaded in loaded_tables:
            name = registry.add_table(loaded.name, loaded.dataframe, loaded.source_type, loaded.source_name)
            registry.metadata[name]["warnings"] = list(dict.fromkeys([*registry.metadata[name]["warnings"], *loaded.warnings]))
    return registry


def _frozen_uploads(uploaded_files):
    previous = st.session_state.get("performance_upload_inputs", {})
    current = {}
    for uploaded in uploaded_files:
        identity = str(getattr(uploaded, "file_id", id(uploaded)))
        current[identity] = previous.get(identity) or (identity, uploaded.name, uploaded.getvalue())
    st.session_state["performance_upload_inputs"] = current
    return tuple(current.values())


def _upload_stream(item):
    stream = io.BytesIO(item[2])
    stream.name = item[1]
    return stream


def _describe_frozen_uploads(items):
    from insightpilot.performance_tasks import report_stage
    values = []
    for identity, name, data in items:
        report_stage("upload_identification")
        descriptor = {"file_id": identity, "name": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        if str(name).lower().endswith((".xlsx", ".xlsm", ".xls")):
            report_stage("excel_sheet_discovery")
            with _upload_stream((identity, name, data)) as stream:
                descriptor["sheets"] = get_excel_sheet_names(stream)
        values.append(descriptor)
    return values


def _parse_frozen_uploads(items, selections):
    from contextlib import ExitStack
    with ExitStack() as stack:
        streams = [stack.enter_context(_upload_stream(item)) for item in items]
        return _parse_upload_tables(streams, selections)


def _upload_descriptors(uploaded_files: list[Any]) -> list[dict[str, Any]]:
    """Streamlit file_id identifies immutable uploaded bytes; hash once on ingestion."""
    previous = st.session_state.get("performance_upload_files", {})
    if background_enabled():
        identities = [str(getattr(item, "file_id", id(item))) for item in uploaded_files]
        if all(identity in previous for identity in identities):
            return [previous[identity] for identity in identities]
        dataset_session().clear()
        items = _frozen_uploads(uploaded_files)
        token = source_token(("upload_metadata", [(item[0], item[1]) for item in items]))
        ready, descriptors = request_work("upload_metadata", token, token,
            partial(_describe_frozen_uploads, items), result_max_bytes=8 * 1024 * 1024)
        if not ready:
            return None
        st.session_state["performance_upload_files"] = {item["file_id"]: item for item in descriptors}
        return descriptors
    current = {}
    descriptors = []
    for uploaded in uploaded_files:
        # Actual uploader changes file_id even for the same filename and length.
        identity = str(getattr(uploaded, "file_id", id(uploaded)))
        descriptor = previous.get(identity)
        if descriptor is None:
            buffer = uploaded.getbuffer()
            try:
                digest = hashlib.sha256(buffer).hexdigest()
                byte_count = len(buffer)
            finally:
                buffer.release()
            descriptor = {"file_id": identity, "name": uploaded.name, "sha256": digest, "bytes": byte_count}
            if str(uploaded.name).lower().endswith((".xlsx", ".xlsm", ".xls")):
                descriptor["sheets"] = get_excel_sheet_names(uploaded)
        current[identity] = descriptor
        descriptors.append(descriptor)
    st.session_state["performance_upload_files"] = current
    return descriptors


def _parse_upload_tables(uploaded_files: list[Any], selections: dict[int, dict[str, Any]]):
    tables, metadata = {}, {}
    for index, uploaded in enumerate(uploaded_files):
        options = selections[index]
        if str(uploaded.name).lower().endswith((".xlsx", ".xlsm", ".xls")):
            loaded_tables = [read_excel_file(uploaded, sheet_name=sheet, table_name=f"{uploaded.name}_{sheet}") for sheet in options["sheets"]]
        else:
            loaded_tables = [read_csv_file(uploaded, table_name=uploaded.name, encoding=options.get("encoding"), sep=options.get("sep", ","))]
        for loaded in loaded_tables:
            name, suffix = loaded.name, 2
            while name in tables:
                name = f"{loaded.name}_{suffix}"
                suffix += 1
            tables[name] = loaded.dataframe
            metadata[name] = {"source_type": loaded.source_type, "source_name": loaded.source_name, "warnings": loaded.warnings}
    return tables, metadata


def render_upload_source() -> tuple[dict[str, pd.DataFrame], dict[str, Any] | None, str, str, TableRegistry | None]:
    epoch = int(st.session_state.get("uploaded_widget_epoch", 0))
    uploaded_files = st.sidebar.file_uploader("上传 CSV / Excel 文件", type=["csv", "xlsx", "xlsm", "xls"],
        accept_multiple_files=True, key="uploaded_files" if not epoch else f"uploaded_files_{epoch}")
    if not uploaded_files:
        if background_enabled() and st.session_state.get("performance_background_pending") is not None:
            cancel_current(block=False)
        for old_key in ("performance_upload_inputs", "performance_upload_files", "performance_dataset_request"):
            st.session_state.pop(old_key, None)
        if st.session_state.get("performance_upload_error"):
            st.error(st.session_state["performance_upload_error"])
        dataset_session().clear()
        st.info("上传文件后可在当前会话内存中检查字段并运行分析。", icon=":material/upload:")
        return {}, None, "请对上传数据做通用趋势和结构分析。", "uploaded_files", None
    try:
        st.session_state.pop("performance_upload_error", None)
        # UploadedFile.size is assigned by Streamlit from the immutable uploaded bytes.
        retained_bytes = sum(int(uploaded.size) for uploaded in uploaded_files)
        if retained_bytes > dataset_session().config.dataset_max_bytes:
            raise MemoryBudgetExceeded("上传原始文件总大小超过本会话数据预算，已释放上传引用；未解析或截断文件。")
        descriptors = _upload_descriptors(uploaded_files)
        if descriptors is None:
            return {}, None, "请对上传数据做通用趋势和结构分析。", "uploaded_files", None
        retained_bytes = sum(item["bytes"] for item in descriptors)
        selections: dict[int, dict[str, Any]] = {}
        with st.expander("读取设置（Excel 工作表 / CSV 编码与分隔符）", expanded=True):
            for index, (uploaded, descriptor) in enumerate(zip(uploaded_files, descriptors)):
                if "sheets" in descriptor:
                    sheets = descriptor["sheets"]
                    selected = st.multiselect(f"{uploaded.name}：选择工作表", sheets, default=sheets[:1], key=f"upload_sheets_{index}_{uploaded.name}")
                    selections[index] = {"sheets": selected}
                else:
                    encoding = st.selectbox(f"{uploaded.name}：字符编码", ["自动识别", "utf-8-sig", "utf-8", "gbk"], key=f"upload_encoding_{index}")
                    separator = st.selectbox(f"{uploaded.name}：分隔符", ["逗号", "制表符", "分号", "竖线"], key=f"upload_separator_{index}")
                    selections[index] = {"encoding": None if encoding == "自动识别" else encoding, "sep": {"逗号": ",", "制表符": "\t", "分号": ";", "竖线": "|"}[separator]}
        key = ("upload", tuple((item["file_id"], item["sha256"], item["name"]) for item in descriptors), json.dumps(selections, sort_keys=True, ensure_ascii=False))
        parser = partial(_parse_frozen_uploads, _frozen_uploads(uploaded_files), deepcopy(selections)) if background_enabled() else partial(_parse_upload_tables, uploaded_files, selections)
        snapshot = _dataset_load(key, parser, "uploaded_files", retained_source_bytes=retained_bytes)
        if snapshot is None:
            return {}, None, "请对上传数据做通用趋势和结构分析。", "uploaded_files", None
    except MemoryBudgetExceeded as exc:
        dataset_session().clear()
        for state_key in list(st.session_state):
            if state_key.startswith("uploaded_files") or state_key in {"performance_upload_files", "performance_upload_inputs"}:
                st.session_state.pop(state_key, None)
        st.session_state["uploaded_widget_epoch"] = epoch + 1
        st.session_state["performance_upload_error"] = _safe_string(str(exc))
        st.rerun()
    except Exception as exc:
        if "预算" in str(exc):
            dataset_session().clear()
            cancel_current(block=False)
            for state_key in list(st.session_state):
                if state_key.startswith("uploaded_files") or state_key in {"performance_upload_inputs", "performance_upload_files", "performance_dataset_request"}:
                    st.session_state.pop(state_key, None)
            st.session_state["uploaded_widget_epoch"] = epoch + 1
            st.session_state["performance_upload_error"] = _safe_string(str(exc))
            st.rerun()
        st.error(f"上传数据读取失败：{_safe_string(str(exc))}")
        return {}, None, "请修正上传文件后重新分析。", "uploaded_files", None
    render_loaded_registry(snapshot.registry)
    return snapshot.tables, snapshot.metadata, "请对上传数据做通用趋势和结构分析。", "uploaded_files", snapshot.registry


def _load_database_tables(database_url, query, table_name):
    result = run_database_query(database_url, query, table_name=table_name)
    return {result.table_name: result.dataframe}, {
        result.table_name: {"source_type": result.source_type, "source_name": mask_database_url(database_url), "warnings": result.warnings}}


def render_database_source() -> tuple[dict[str, pd.DataFrame], dict[str, Any] | None, str, str, TableRegistry | None]:
    st.warning("仅允许单条 SELECT/WITH 查询。请使用本地测试数据，不要输入真实凭据。", icon=":material/security:")
    database_url = st.text_input("本地数据库连接地址", value="sqlite:///path/to/local.db", type="password", key="database_url")
    query = st.text_area("只读查询", value="SELECT * FROM local_table LIMIT 100", key="database_query")
    table_name = st.text_input("结果表名称", value="db_query_result", key="database_table_name")
    current_query = hashlib.sha256((database_url + "\n" + query + "\n" + table_name).encode()).hexdigest()
    requested = st.session_state.get("performance_database_request")
    if requested and requested["query_key"] != current_query:
        cancel_current(block=False)
        st.session_state.pop("performance_database_request", None)
        requested = None
    if st.button("检查并加载只读查询", icon=":material/database:"):
        if not is_safe_select_query(query):
            st.error("查询安全检查未通过：仅允许单条 SELECT/WITH，禁止任何写操作。")
        else:
            revision = int(st.session_state.get("database_refresh_counter", 0)) + 1
            st.session_state["database_refresh_counter"] = revision
            requested = {"key": ("database", current_query, revision), "query_key": current_query}
            st.session_state["performance_database_request"] = requested
            st.session_state.get("performance_background_blocked", {}).pop("dataset", None)
    if requested:
        try:
            snapshot = _dataset_load(requested["key"], partial(_load_database_tables, database_url, query, table_name), "database")
            if snapshot is not None:
                st.session_state["database_loaded_query"] = current_query
                st.session_state.pop("performance_database_request", None)
                st.success("查询结果已加载到当前会话内存。")
        except Exception as exc:
            st.error(f"数据库只读查询失败：{_safe_string(str(exc))}")
            st.session_state.pop("performance_database_request", None)
    snapshot = current_dataset()
    registry = snapshot.registry if snapshot is not None and snapshot.source_type == "database" else None
    if not isinstance(registry, TableRegistry):
        if st.session_state.get("database_loaded_query"):
            st.info("数据库快照已过期或释放，未自动重查。请点击检查并加载只读查询。")
        return {}, None, "请对数据库查询结果做通用趋势和结构分析。", "database", None
    render_loaded_registry(registry)
    if current_query != st.session_state.get("database_loaded_query"):
        st.warning("查询配置已变化，当前仍是上次加载的数据库快照；请点击检查并加载以刷新。")
    st.caption(f"数据库结果为显式加载快照，修订 {snapshot.revision}；不会按TTL自动重查数据库。")
    return snapshot.tables, snapshot.metadata, "请对数据库查询结果做通用趋势和结构分析。", "database", registry
