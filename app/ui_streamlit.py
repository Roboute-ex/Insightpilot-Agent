"""Streamlit UI for InsightPilot Agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data
from insightpilot.ingestion.db_loader import is_safe_select_query, mask_database_url, run_database_query
from insightpilot.ingestion.file_loader import get_excel_sheet_names, load_uploaded_file
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.planning.goal_modes import GOAL_MODE_OPTIONS
from insightpilot.visualization.charts import build_ab_test_comparison_chart, build_contribution_bar_chart


GOAL_MODE_BY_DISPLAY_NAME = {mode.display_name: mode.value for mode in GOAL_MODE_OPTIONS}
GOAL_MODE_DISPLAY_NAMES = list(GOAL_MODE_BY_DISPLAY_NAME.keys())
WORKFLOW_BACKENDS = {"Rule-based": False, "Optional LangGraph": True}

SCENARIOS: dict[str, dict[str, Any]] = {
    "交易转化异常分析": {
        "question": "为什么昨天某城市订单量下降？",
        "tables": ["daily_metrics", "traffic_events", "orders", "users"],
    },
    "内容消费与实验分析": {
        "question": "新策略是否提升了内容完播率？",
        "tables": ["content_events", "content_items", "experiments", "users"],
    },
    "体验质量分析": {
        "question": "请定位直播体验异常的主要维度。",
        "tables": ["live_quality_logs", "live_sessions", "live_interactions"],
    },
}


@st.cache_data(show_spinner=False)
def _load_tables() -> dict[str, pd.DataFrame]:
    return generate_all_demo_data(seed=42)


def _safe_json(data: Any) -> Any:
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def _render_artifacts(result: dict[str, Any]) -> None:
    artifacts = result.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return
    contributions = artifacts.get("contributions")
    if isinstance(contributions, dict):
        for dimension, rows in contributions.items():
            frame = pd.DataFrame(rows)
            if frame.empty:
                continue
            st.plotly_chart(
                build_contribution_bar_chart(frame, title=f"{dimension} contribution"),
                use_container_width=True,
            )
            st.dataframe(frame, use_container_width=True)
    ab_test = artifacts.get("ab_test") or artifacts.get("optional_ab_test") or artifacts.get("generic_ab_test")
    if isinstance(ab_test, dict):
        st.plotly_chart(build_ab_test_comparison_chart(ab_test), use_container_width=True)


def _render_registry(registry: TableRegistry) -> None:
    for table_name in registry.list_tables():
        metadata = registry.get_metadata(table_name)
        with st.expander(f"{table_name} · {metadata['row_count']} rows · {metadata['column_count']} columns", expanded=True):
            st.json(_safe_json(metadata.get("schema_mapping", {})))
            warnings = metadata.get("warnings", [])
            if warnings:
                st.warning("\n".join(f"- {warning}" for warning in warnings))
            st.dataframe(registry.get_table(table_name).head(20), use_container_width=True)


def _load_uploaded_registry(uploaded_files: list[Any]) -> TableRegistry:
    registry = TableRegistry()
    for index, uploaded_file in enumerate(uploaded_files):
        suffix = Path(uploaded_file.name).suffix.lower()
        sheet_name: str | int | None = None
        file_key = f"{index}_{Path(uploaded_file.name).stem}"
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            try:
                sheets = get_excel_sheet_names(uploaded_file)
                sheet_name = st.selectbox(f"{uploaded_file.name} sheet", sheets, key=f"sheet_{file_key}")
            except Exception as exc:
                st.error(f"{uploaded_file.name} sheet 读取失败：{exc}")
                continue
        default_name = Path(uploaded_file.name).stem
        table_name = st.text_input(f"{uploaded_file.name} table name", value=default_name, key=f"table_{file_key}")
        try:
            loaded = load_uploaded_file(uploaded_file, uploaded_file.name, sheet_name=sheet_name, table_name=table_name)
            registered_name = registry.add_table(loaded.name, loaded.dataframe, loaded.source_type, loaded.source_name)
            registry.metadata[registered_name]["warnings"] = list(
                dict.fromkeys(registry.metadata[registered_name]["warnings"] + loaded.warnings)
            )
        except Exception as exc:
            st.error(f"{uploaded_file.name} 读取失败：{exc}")
    return registry


def _render_result(result: dict[str, Any]) -> None:
    trace = result.get("trace", {})
    reviewer = result.get("reviewer", {})
    st.subheader("Workflow Backend")
    st.write(result.get("workflow_backend", "rule_based"))
    st.subheader("Route Taken")
    st.write(" -> ".join(result.get("route_taken", [])))

    col_status, col_score, col_trace = st.columns(3)
    col_status.metric("Reviewer Status", reviewer.get("status", "UNKNOWN"))
    col_score.metric("Reviewer Score", reviewer.get("score", "N/A"))
    col_trace.metric("Trace ID", trace.get("trace_id", "N/A"))

    plan_tab, data_tab, findings_tab, reviewer_tab, trace_tab, report_tab = st.tabs(
        ["Analysis Plan", "Data Source", "Findings", "Reviewer Result", "Trace JSON", "Markdown Report"]
    )
    with plan_tab:
        st.metric("Analysis Goal Mode", f"{result['goal_mode_display_name']} ({result['goal_mode']})")
        st.write(f"Goal Mode Source: {result['goal_mode_source']}")
        st.json(_safe_json(result["plan"]))
    with data_tab:
        st.write(f"Data Source: {result.get('data_source_type', 'synthetic')}")
        st.json(_safe_json(result.get("table_metadata", {})))
        _render_artifacts(result)
    with findings_tab:
        for finding in result["findings"]:
            st.write(f"- {finding}")
        with st.expander("Caveats"):
            for caveat in result.get("caveats", []):
                st.write(f"- {caveat}")
    with reviewer_tab:
        st.json(_safe_json(result["reviewer"]))
    with trace_tab:
        st.json(_safe_json(result["trace"]))
    with report_tab:
        st.markdown(result["report_markdown"])


def main() -> None:
    st.set_page_config(page_title="InsightPilot Agent", layout="wide")
    synthetic_tables = _load_tables()

    st.title("InsightPilot Agent")
    data_source_display = st.sidebar.selectbox(
        "Data Source",
        ["Synthetic demo data", "Upload CSV / Excel", "Database query"],
        index=0,
    )
    selected_goal_mode_display = st.sidebar.selectbox("Analysis Goal Mode", GOAL_MODE_DISPLAY_NAMES, index=0)
    selected_goal_mode = GOAL_MODE_BY_DISPLAY_NAME[selected_goal_mode_display]
    selected_backend_display = st.sidebar.selectbox("Workflow Backend", list(WORKFLOW_BACKENDS.keys()), index=0)
    use_langgraph = WORKFLOW_BACKENDS[selected_backend_display]

    tables: dict[str, pd.DataFrame] = {}
    table_metadata: dict[str, Any] | None = None
    data_source_type = "synthetic"
    default_question = "请对当前数据做通用趋势和结构分析。"

    if data_source_display == "Synthetic demo data":
        scenario_name = st.sidebar.selectbox("Demo 场景", list(SCENARIOS.keys()))
        scenario = SCENARIOS[scenario_name]
        st.sidebar.markdown("### synthetic data")
        selected_table = st.sidebar.selectbox("预览表", scenario["tables"])
        st.dataframe(synthetic_tables[selected_table].head(20), use_container_width=True)
        tables = synthetic_tables
        default_question = scenario["question"]
    elif data_source_display == "Upload CSV / Excel":
        data_source_type = "uploaded_files"
        uploaded_files = st.sidebar.file_uploader(
            "Upload CSV / Excel",
            type=["csv", "xlsx", "xlsm", "xls"],
            accept_multiple_files=True,
        )
        if uploaded_files:
            registry = _load_uploaded_registry(uploaded_files)
            tables = registry.to_duckdb_tables()
            table_metadata = registry.metadata
            _render_registry(registry)
        else:
            st.info("上传 CSV 或 Excel 文件后，可以预览 schema mapping 和运行分析。")
    else:
        data_source_type = "database"
        st.info("数据库模式只执行只读 SELECT/WITH 查询。不要提交真实凭据，UI 和报告只展示 masked URL。")
        database_url = st.text_input("database_url", value="sqlite:///path/to/local.db", type="password")
        query = st.text_area("SQL query", value="SELECT * FROM your_table LIMIT 100")
        table_name = st.text_input("table name", value="db_query_result")
        if st.button("Test Query / Load Data"):
            if not is_safe_select_query(query):
                st.error("SQL 安全检查未通过：仅允许单条 SELECT/WITH 查询，禁止写操作。")
            else:
                try:
                    result = run_database_query(database_url, query, table_name=table_name)
                    registry = TableRegistry()
                    registered_name = registry.add_table(
                        result.table_name,
                        result.dataframe,
                        result.source_type,
                        mask_database_url(database_url),
                    )
                    registry.metadata[registered_name]["warnings"] = list(
                        dict.fromkeys(registry.metadata[registered_name]["warnings"] + result.warnings)
                    )
                    st.session_state.db_registry = registry
                    st.success("查询结果已加载到当前会话内存。")
                except Exception as exc:
                    st.error(f"数据库查询失败：{exc}")
        registry = st.session_state.get("db_registry")
        if isinstance(registry, TableRegistry):
            tables = registry.to_duckdb_tables()
            table_metadata = registry.metadata
            _render_registry(registry)

    if "question" not in st.session_state:
        st.session_state.question = default_question
    if st.button("使用示例问题"):
        st.session_state.question = default_question

    question = st.text_input("问题", value=st.session_state.question, key="question")
    if st.button("运行分析", type="primary"):
        if not tables:
            st.error("没有可用表，请先选择 synthetic demo、上传文件或加载数据库查询结果。")
            return
        result = run_agent_analysis(
            question,
            tables,
            goal_mode=selected_goal_mode,
            use_langgraph=use_langgraph,
            data_source_type=data_source_type,
            table_metadata=table_metadata,
        )
        _render_result(result)


if __name__ == "__main__":
    main()
