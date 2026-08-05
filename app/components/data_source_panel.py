"""Synthetic, upload, and read-only database source controls."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from insightpilot.data.synthetic import generate_all_demo_data, generate_multi_table_commerce_data
from insightpilot.data.scenarios import DemoScale, generate_demo_scenario
from insightpilot.ingestion.db_loader import is_safe_select_query, mask_database_url, run_database_query
from insightpilot.ingestion.file_loader import get_excel_sheet_names, load_uploaded_file
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.ui.formatters import METRIC_DISPLAY_NAMES, format_metric_name
from insightpilot.ui.i18n import t


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
        "tables": ["live_quality_logs", "live_sessions", "live_interactions"],
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


@st.cache_data(show_spinner=False, max_entries=8)
def load_synthetic_tables(dataset: str, scale: str = "standard", seed: int = 42) -> dict[str, pd.DataFrame]:
    if dataset == "multi_table":
        return generate_multi_table_commerce_data(seed=seed)
    if dataset in {"transaction", "content", "live"}:
        return generate_demo_scenario(dataset, scale=scale, seed=seed).tables
    return generate_all_demo_data(seed=seed)


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


def render_synthetic_source(view_mode: str = "demo") -> tuple[dict[str, pd.DataFrame], None, str, str]:
    scenario_name = st.sidebar.selectbox(t("sidebar.demo_scenario"), list(SCENARIOS), key="demo_scenario")
    scenario = SCENARIOS[scenario_name]
    scale_options = [DemoScale.SMALL.value, DemoScale.STANDARD.value]
    if view_mode == "developer":
        scale_options.append(DemoScale.LARGE.value)
    scale = st.sidebar.selectbox(
        "数据规模",
        scale_options,
        index=scale_options.index(DemoScale.STANDARD.value),
        format_func=lambda value: {"small": "小型", "standard": "标准", "large": "大型"}[value],
        key="demo_scale",
    )
    seed = int(st.sidebar.number_input("随机种子", min_value=0, max_value=1_000_000, value=42, key="demo_seed")) if view_mode == "developer" else 42
    tables = load_synthetic_tables(str(scenario["dataset"]), scale, seed)
    st.session_state["current_scenario_id"] = scenario["scenario_id"]
    preview_options = [name for name in scenario["tables"] if name in tables]
    preview = st.sidebar.selectbox(t("sidebar.preview_table"), preview_options, key="preview_table")
    st.subheader(t("section.data_overview"), anchor=False)
    st.caption(t("warning.synthetic_data"))
    st.caption(f"当前为{ {'small': '小型', 'standard': '标准', 'large': '大型'}[scale] }内置模拟数据；预览仅显示前 20 行。")
    preview_frame = tables[preview].head(20).copy()
    display_columns: list[str] = []
    display_counts: dict[str, int] = {}
    for column in preview_frame.columns:
        display = format_metric_name(column, developer_mode=view_mode == "developer") if str(column) in METRIC_DISPLAY_NAMES else str(column)
        display_counts[display] = display_counts.get(display, 0) + 1
        if display_counts[display] > 1:
            display = f"{display}（兼容口径 {display_counts[display]}）"
        display_columns.append(display)
    preview_frame.columns = display_columns
    st.dataframe(preview_frame, hide_index=True, width="stretch")
    return tables, None, str(scenario["question"]), "synthetic"


def load_uploaded_registry(uploaded_files: list[Any]) -> TableRegistry:
    registry = TableRegistry()
    for uploaded in uploaded_files:
        sheet_name: str | int | None = None
        if str(uploaded.name).lower().endswith((".xlsx", ".xlsm", ".xls")):
            try:
                sheets = get_excel_sheet_names(uploaded)
                uploaded.seek(0)
                sheet_name = sheets[0] if sheets else None
            except Exception:
                uploaded.seek(0)
        loaded = load_uploaded_file(uploaded, uploaded.name, sheet_name=sheet_name)
        name = registry.add_table(loaded.name, loaded.dataframe, loaded.source_type, loaded.source_name)
        registry.metadata[name]["warnings"] = list(dict.fromkeys([*registry.metadata[name]["warnings"], *loaded.warnings]))
    return registry


def render_upload_source() -> tuple[dict[str, pd.DataFrame], dict[str, Any] | None, str, str, TableRegistry | None]:
    uploaded_files = st.sidebar.file_uploader(
        "上传 CSV / Excel 文件",
        type=["csv", "xlsx", "xlsm", "xls"],
        accept_multiple_files=True,
        key="uploaded_files",
    )
    if not uploaded_files:
        st.info("上传文件后可在当前会话内存中检查字段并运行分析。", icon=":material/upload:")
        return {}, None, "请对上传数据做通用趋势和结构分析。", "uploaded_files", None
    registry = load_uploaded_registry(uploaded_files)
    render_registry_summary(registry)
    return registry.to_duckdb_tables(), registry.metadata, "请对上传数据做通用趋势和结构分析。", "uploaded_files", registry


def render_database_source() -> tuple[dict[str, pd.DataFrame], dict[str, Any] | None, str, str, TableRegistry | None]:
    st.warning("仅允许单条 SELECT/WITH 查询。请使用本地测试数据，不要输入真实凭据。", icon=":material/security:")
    database_url = st.text_input("本地数据库连接地址", value="sqlite:///path/to/local.db", type="password", key="database_url")
    query = st.text_area("只读查询", value="SELECT * FROM local_table LIMIT 100", key="database_query")
    table_name = st.text_input("结果表名称", value="db_query_result", key="database_table_name")
    if st.button("检查并加载只读查询", icon=":material/database:"):
        if not is_safe_select_query(query):
            st.error("查询安全检查未通过：仅允许单条 SELECT/WITH，禁止任何写操作。")
        else:
            try:
                result = run_database_query(database_url, query, table_name=table_name)
                registry = TableRegistry()
                registered = registry.add_table(result.table_name, result.dataframe, result.source_type, mask_database_url(database_url))
                registry.metadata[registered]["warnings"] = list(dict.fromkeys([*registry.metadata[registered]["warnings"], *result.warnings]))
                st.session_state["database_registry"] = registry
                st.success("查询结果已加载到当前会话内存。")
            except Exception as exc:
                st.error(f"数据库只读查询失败：{exc}")
    registry = st.session_state.get("database_registry")
    if not isinstance(registry, TableRegistry):
        return {}, None, "请对数据库查询结果做通用趋势和结构分析。", "database", None
    render_registry_summary(registry)
    return registry.to_duckdb_tables(), registry.metadata, "请对数据库查询结果做通用趋势和结构分析。", "database", registry
