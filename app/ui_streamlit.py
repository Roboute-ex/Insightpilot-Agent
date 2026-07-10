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
from insightpilot.ingestion.mapping import ColumnMapping, normalize_column_mapping, suggest_column_mapping
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.planning.goal_modes import GOAL_MODE_OPTIONS
from insightpilot.playbooks.models import AnalysisPlaybook
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.reports.bundle import generate_export_bundle
from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.markdown import generate_markdown_report
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

PLAYBOOK_AUTOMATIC = "保留现有自动工作流"
PLAYBOOK_RECOMMENDED = "Auto recommended"


def _mapping_for_playbook_ui(
    playbook_id: str,
    tables: dict[str, pd.DataFrame],
    mapping: dict[str, Any] | None,
) -> ColumnMapping:
    if mapping:
        table_name = str(mapping.get("table_name") or "")
        columns = [str(column) for column in tables[table_name].columns] if table_name in tables else []
        return normalize_column_mapping(mapping, columns)
    if not tables:
        return ColumnMapping()
    if playbook_id in {"experiment_comparison", "causal_exploration"} and "experiments" in tables:
        df = tables["experiments"]
        return ColumnMapping(
            table_name="experiments",
            group_column="group" if "group" in df.columns else None,
            treatment_column="group" if "group" in df.columns else None,
            outcome_column="completion_rate" if "completion_rate" in df.columns else None,
            metric_columns=["completion_rate"] if "completion_rate" in df.columns else [],
            dimension_columns=[column for column in ["historical_activity", "historical_revenue", "city"] if column in df.columns],
        )
    table_name = "daily_metrics" if "daily_metrics" in tables else sorted(tables)[0]
    return suggest_column_mapping(table_name, tables[table_name])


def _recommended_playbook_ids(goal_mode: str, mapping: ColumnMapping) -> list[str]:
    return [playbook.playbook_id for playbook in get_playbook_registry().recommend(goal_mode, mapping)]


def _playbook_label_map() -> dict[str, str | None]:
    labels: dict[str, str | None] = {PLAYBOOK_AUTOMATIC: None, PLAYBOOK_RECOMMENDED: "auto"}
    for playbook in get_playbook_registry().list_all():
        labels[f"{playbook.display_name} ({playbook.playbook_id})"] = playbook.playbook_id
    return labels


def _available_columns(mapping: ColumnMapping, tables: dict[str, pd.DataFrame]) -> list[str]:
    if mapping.table_name and mapping.table_name in tables:
        return [str(column) for column in tables[mapping.table_name].columns]
    return []


def _render_playbook_parameters(
    playbook: AnalysisPlaybook | None,
    mapping: ColumnMapping,
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    if playbook is None:
        st.caption("当前使用原有自动工作流，无额外 playbook 参数。")
        return {}
    columns = _available_columns(mapping, tables)
    values: dict[str, Any] = {}
    for parameter in playbook.parameters:
        key = f"playbook_parameter_{playbook.playbook_id}_{parameter.name}"
        default = parameter.default
        if parameter.name == "metric":
            default = next(iter(mapping.metric_columns), default)
        elif parameter.name == "dimension":
            default = next(iter(mapping.dimension_columns), default)
        if parameter.parameter_type == "choice":
            options = list(parameter.choices)
            index = options.index(default) if default in options else 0
            values[parameter.name] = st.selectbox(parameter.display_name, options, index=index, key=key)
        elif parameter.parameter_type == "integer":
            bounds = {"top_n": (1, 100), "rolling_window": (1, 90)}
            minimum, maximum = bounds.get(parameter.name, (0, 10_000))
            values[parameter.name] = int(st.number_input(parameter.display_name, minimum, maximum, int(default or minimum), key=key))
        elif parameter.parameter_type == "float":
            if parameter.name == "confidence_level":
                values[parameter.name] = float(st.number_input(parameter.display_name, 0.8, 0.99, float(default or 0.95), 0.01, key=key))
            else:
                values[parameter.name] = float(st.number_input(parameter.display_name, value=float(default or 0.0), key=key))
        elif parameter.parameter_type == "boolean":
            values[parameter.name] = st.checkbox(parameter.display_name, value=bool(default), key=key)
        elif parameter.parameter_type == "column":
            options = [""] + columns
            index = options.index(default) if default in options else 0
            values[parameter.name] = st.selectbox(parameter.display_name, options, index=index, key=key) or None
        elif parameter.parameter_type in {"metric_columns", "dimension_columns"}:
            defaults = default if isinstance(default, list) else []
            values[parameter.name] = st.multiselect(parameter.display_name, columns, default=[item for item in defaults if item in columns], key=key)
        elif parameter.parameter_type == "date_range":
            selected = st.date_input(parameter.display_name, value=(), key=key)
            if isinstance(selected, (list, tuple)) and len(selected) == 2:
                values[parameter.name] = {"start": str(selected[0]), "end": str(selected[1])}
        elif parameter.parameter_type == "date":
            selected = st.date_input(parameter.display_name, value=None, key=key)
            values[parameter.name] = str(selected) if selected else None
        else:
            group_values: list[str] = []
            if parameter.name in {"control_value", "treatment_value"} and mapping.group_column and mapping.table_name in tables:
                group_values = sorted(tables[mapping.table_name][mapping.group_column].dropna().astype(str).unique().tolist())
            if group_values:
                index = group_values.index(str(default)) if str(default) in group_values else 0
                values[parameter.name] = st.selectbox(parameter.display_name, group_values, index=index, key=key)
            else:
                values[parameter.name] = st.text_input(parameter.display_name, value=str(default or ""), key=key)
    return {key: value for key, value in values.items() if value not in (None, "", [])}


def _prepare_export_payloads(result: dict[str, Any]) -> dict[str, str | bytes]:
    result["route_taken"] = list(dict.fromkeys([*result.get("route_taken", []), "generate_exports"]))
    if isinstance(result.get("trace"), dict):
        result["trace"]["route_taken"] = list(result["route_taken"])
    result["export_formats"] = ["markdown", "html", "excel", "manifest", "bundle"]
    manifest_values = dict(result["run_manifest"])
    manifest_values["route_taken"] = list(result["route_taken"])
    manifest = RunManifest.from_dict(manifest_values)
    result["run_manifest"] = manifest.to_dict()
    result["report_markdown"] = generate_markdown_report(result)
    html_report = generate_html_report(result, result.get("charts", []), manifest)
    excel_bytes = generate_excel_report(result, manifest)
    manifest_json = manifest.to_json()
    bundle = generate_export_bundle(
        result["report_markdown"], html_report, excel_bytes, manifest_json, result.get("result_tables", {})
    )
    return {
        "markdown": result["report_markdown"],
        "html": html_report,
        "excel": excel_bytes,
        "manifest": manifest_json,
        "bundle": bundle,
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
                width="stretch",
            )
            st.dataframe(frame, width="stretch")
    ab_test = artifacts.get("ab_test") or artifacts.get("optional_ab_test") or artifacts.get("generic_ab_test")
    if isinstance(ab_test, dict):
        st.plotly_chart(build_ab_test_comparison_chart(ab_test), width="stretch")


def _render_registry(registry: TableRegistry) -> None:
    for table_name in registry.list_tables():
        metadata = registry.get_metadata(table_name)
        with st.expander(f"{table_name} · {metadata['row_count']} rows · {metadata['column_count']} columns", expanded=True):
            st.json(_safe_json(metadata.get("schema_mapping", {})))
            warnings = metadata.get("warnings", [])
            if warnings:
                st.warning("\n".join(f"- {warning}" for warning in warnings))
            st.dataframe(registry.get_table(table_name).head(20), width="stretch")


def _select_optional(label: str, options: list[str], default: str | None, key: str) -> str | None:
    values = [""] + options
    index = values.index(default) if default in values else 0
    selected = st.selectbox(label, values, index=index, key=key)
    return selected or None


def _render_column_mapping_panel(registry: TableRegistry, goal_mode: str) -> dict[str, Any] | None:
    if not registry.list_tables():
        return None
    st.subheader("Metric / Column Mapping")
    table_name = st.selectbox("Mapping table", registry.list_tables(), key="mapping_table")
    df = registry.get_table(table_name)
    suggestion = suggest_column_mapping(table_name, df)
    columns = [str(column) for column in df.columns]
    numeric_columns = [str(column) for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    dimension_candidates = [
        column
        for column in columns
        if column not in numeric_columns or column in suggestion.dimension_columns
    ]

    st.caption("手动选择会优先于自动 schema 推断；不完整时会进入通用 fallback 并写入 caveat。")
    if goal_mode in {"metric_diagnosis", "growth_trend"}:
        st.info("建议选择 date column、至少一个 metric column，以及可选 dimension columns。")
    elif goal_mode == "experiment_analysis":
        st.info("建议选择 group column 和至少一个 metric column。")
    elif goal_mode == "causal_exploration":
        st.info("建议选择 treatment column、outcome column 和可选维度/控制变量。")

    col_left, col_right = st.columns(2)
    with col_left:
        date_column = _select_optional("Date column", columns, suggestion.date_column, "mapping_date")
        metric_columns = st.multiselect(
            "Metric columns",
            columns,
            default=[column for column in suggestion.metric_columns if column in columns],
            key="mapping_metrics",
            help=f"Numeric candidates: {', '.join(numeric_columns[:8]) or 'none'}",
        )
        dimension_columns = st.multiselect(
            "Dimension columns",
            columns,
            default=[column for column in suggestion.dimension_columns if column in columns],
            key="mapping_dimensions",
            help=f"Dimension candidates: {', '.join(dimension_candidates[:8]) or 'none'}",
        )
    with col_right:
        group_column = _select_optional("Group column", columns, suggestion.group_column, "mapping_group")
        treatment_column = _select_optional("Treatment column", columns, suggestion.treatment_column, "mapping_treatment")
        outcome_column = _select_optional("Outcome column", columns, suggestion.outcome_column, "mapping_outcome")
        time_grain = st.selectbox("Time grain", ["day", "week", "month"], index=0, key="mapping_time_grain")

    mapping = {
        "table_name": table_name,
        "date_column": date_column,
        "metric_columns": metric_columns,
        "dimension_columns": dimension_columns,
        "group_column": group_column,
        "treatment_column": treatment_column,
        "outcome_column": outcome_column,
        "time_grain": time_grain,
    }
    st.markdown("#### Mapping Summary")
    st.json(_safe_json(mapping))
    return mapping


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
    selected = result.get("selected_playbook") or {}
    col_status, col_score, col_trace, col_backend = st.columns(4)
    col_status.metric("Reviewer Status", reviewer.get("status", "UNKNOWN"))
    col_score.metric("Reviewer Score", reviewer.get("score", "N/A"))
    col_trace.metric("Trace ID", trace.get("trace_id", "N/A"))
    col_backend.metric("Workflow Backend", result.get("workflow_backend", "rule_based"))

    summary_tab, tables_tab, visual_tab, reviewer_tab, trace_tab, export_tab = st.tabs(
        ["Summary", "Result Tables", "Visual Diagnostics", "Reviewer", "Trace", "Export"]
    )
    with summary_tab:
        st.metric("Analysis Goal Mode", f"{result['goal_mode_display_name']} ({result['goal_mode']})")
        st.write(f"Goal Mode Source: {result['goal_mode_source']}")
        st.write(f"Playbook: {selected.get('display_name') or '现有自动工作流'}")
        st.write(f"Playbook Source: {result.get('playbook_source', 'none')}")
        st.write("Workflow Route: " + " -> ".join(result.get("route_taken", [])))
        st.markdown("#### 核心发现")
        for finding in result.get("findings", []):
            st.write(f"- {finding}")
        with st.expander("Caveats"):
            for caveat in result.get("caveats", []):
                st.write(f"- {caveat}")
        st.markdown("#### Analysis Plan")
        st.json(_safe_json(result["plan"]))
    with tables_tab:
        result_tables = result.get("result_tables", {})
        if isinstance(result_tables, dict) and result_tables:
            for name, frame in result_tables.items():
                st.markdown(f"#### {name}")
                if isinstance(frame, pd.DataFrame):
                    st.dataframe(frame, width="stretch")
        else:
            st.info("当前自动工作流没有结构化 playbook 结果表。")
            _render_artifacts(result)
    with visual_tab:
        charts = result.get("charts", [])
        specs = result.get("chart_specs", [])
        if charts:
            descriptions = {
                str(spec.get("title")): str(spec.get("description", ""))
                for spec in specs if isinstance(spec, dict)
            }
            for figure in charts:
                title_object = getattr(getattr(figure, "layout", None), "title", None)
                title = str(getattr(title_object, "text", None) or "Visual Diagnostic")
                st.markdown(f"#### {title}")
                if descriptions.get(title):
                    st.caption(descriptions[title])
                st.plotly_chart(figure, width="stretch")
        else:
            st.info("当前结果没有可用的结构化图表；核心发现仍可正常查看。")
    with reviewer_tab:
        st.json(_safe_json(result["reviewer"]))
    with trace_tab:
        st.json(_safe_json(result["trace"]))
        st.markdown("#### Run Manifest")
        st.json(_safe_json(result.get("run_manifest", {})))
    with export_tab:
        st.caption("导出仅包含分析结果、图表和复现配置，不包含上传源文件或数据库凭据。")
        export_key = str(result.get("run_manifest", {}).get("run_id", "latest"))
        if st.button("准备内存导出", key=f"prepare_exports_{export_key}"):
            try:
                st.session_state.export_payloads = _prepare_export_payloads(result)
                st.session_state.export_run_id = export_key
            except Exception as exc:
                st.warning(f"导出生成失败：{exc}")
        payloads = st.session_state.get("export_payloads") if st.session_state.get("export_run_id") == export_key else None
        if isinstance(payloads, dict):
            short_run_id = export_key[:8]
            playbook_id = selected.get("playbook_id") or "analysis"
            prefix = f"{playbook_id}_{short_run_id}"
            st.download_button("下载 Markdown", payloads["markdown"], f"{prefix}.md", "text/markdown")
            st.download_button("下载交互式 HTML", payloads["html"], f"{prefix}.html", "text/html")
            st.download_button("下载 Excel", payloads["excel"], f"{prefix}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.download_button("下载 Manifest JSON", payloads["manifest"], f"{prefix}_manifest.json", "application/json")
            st.download_button("下载完整 ZIP 分析包", payloads["bundle"], f"{prefix}.zip", "application/zip")


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
    column_mapping: dict[str, Any] | None = None
    data_source_type = "synthetic"
    default_question = "请对当前数据做通用趋势和结构分析。"

    if data_source_display == "Synthetic demo data":
        scenario_name = st.sidebar.selectbox("Demo 场景", list(SCENARIOS.keys()))
        scenario = SCENARIOS[scenario_name]
        st.sidebar.markdown("### synthetic data")
        selected_table = st.sidebar.selectbox("预览表", scenario["tables"])
        st.dataframe(synthetic_tables[selected_table].head(20), width="stretch")
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
            column_mapping = _render_column_mapping_panel(registry, selected_goal_mode)
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
            column_mapping = _render_column_mapping_panel(registry, selected_goal_mode)

    if "question" not in st.session_state:
        st.session_state.question = default_question
    if st.button("使用示例问题"):
        st.session_state.question = default_question

    question = st.text_input("问题", key="question")

    st.subheader("Analysis Playbook")
    playbook_labels = _playbook_label_map()
    selected_playbook_label = st.selectbox("选择分析剧本", list(playbook_labels), index=0)
    selected_playbook_id = playbook_labels[selected_playbook_label]
    recommendation_mapping = _mapping_for_playbook_ui("periodic_summary", tables, column_mapping)
    recommended_ids = _recommended_playbook_ids(selected_goal_mode, recommendation_mapping) if tables else []
    resolved_playbook_id = recommended_ids[0] if selected_playbook_id == "auto" and recommended_ids else selected_playbook_id
    selected_playbook = (
        get_playbook_registry().get(str(resolved_playbook_id)) if resolved_playbook_id else None
    )
    playbook_mapping = _mapping_for_playbook_ui(str(resolved_playbook_id or "data_profile"), tables, column_mapping)
    if selected_playbook is not None:
        st.write(selected_playbook.description)
        required_fields = [
            name.removeprefix("requires_")
            for name, required in selected_playbook.requirements.to_dict().items()
            if name.startswith("requires_") and required
        ]
        st.caption("Required fields: " + (", ".join(required_fields) or "table only"))
        requirement_warnings = selected_playbook.validate_mapping(playbook_mapping)
        if requirement_warnings:
            st.warning("\n".join(f"- {warning}" for warning in requirement_warnings))
        else:
            st.success("当前 Column Mapping 满足所选 playbook 的字段要求。")
        if selected_playbook_id == "auto":
            st.caption(f"当前推荐：{selected_playbook.display_name} ({selected_playbook.playbook_id})")

    with st.form("analysis_playbook_form"):
        st.markdown("#### Playbook Parameters")
        playbook_parameters = _render_playbook_parameters(selected_playbook, playbook_mapping, tables)
        run_analysis = st.form_submit_button("运行分析", type="primary")

    if run_analysis:
        if not tables:
            st.error("没有可用表，请先选择 synthetic demo、上传文件或加载数据库查询结果。")
            return
        try:
            result = run_agent_analysis(
                question,
                tables,
                goal_mode=selected_goal_mode,
                use_langgraph=use_langgraph,
                data_source_type=data_source_type,
                table_metadata=table_metadata,
                column_mapping=column_mapping,
                playbook_id=selected_playbook_id,
                playbook_parameters=playbook_parameters,
            )
            st.session_state.last_analysis_result = result
            st.session_state.pop("export_payloads", None)
            st.session_state.pop("export_run_id", None)
        except Exception as exc:
            st.error(f"分析执行失败：{exc}")
    latest_result = st.session_state.get("last_analysis_result")
    if isinstance(latest_result, dict):
        _render_result(latest_result)


if __name__ == "__main__":
    main()
