"""Business navigation and compact, metadata-only workbench summaries."""
from __future__ import annotations
import streamlit as st
from insightpilot.ui.theme import render_compact_summary_card

PAGES = {"workbench": "分析工作台", "explore": "数据探索", "methods": "分析方法", "history": "历史比较"}


def navigate(page):
    if page not in PAGES:
        raise ValueError("未知工作台页面")
    st.session_state["workbench_page"] = page


def render_workbench_navigation():
    st.session_state.setdefault("workbench_page", "workbench")
    return st.segmented_control("主导航", list(PAGES), format_func=PAGES.get, key="workbench_page", required=True, width="stretch")


def render_methods_entry(*, key="workbench_all_methods"):
    st.button("查看全部分析方法", key=key, on_click=navigate, args=("methods",), icon=":material/apps:")


def selected_mapping(prepared):
    mapping = st.session_state.get("guided_mapping") or prepared.get("normalized_request", {}).get("column_mapping") or {}
    if not mapping:
        definitions = prepared.get("metric_definitions") or []
        scopes = {x.get("table_name") for x in definitions if x.get("table_name")}
        dates = {x.get("date_column") for x in definitions if x.get("date_column")}
        if len(scopes) == 1:
            # Read-only display of the already resolved common metric scope.
            mapping = {"table_name": next(iter(scopes)), "metric_columns": [x.get("metric_id") for x in definitions],
                "date_column": next(iter(dates)) if len(dates) == 1 else None, "source": "definition_scope"}
    return mapping


def render_data_summary(snapshot, prepared):
    mapping = selected_mapping(prepared)
    table_name = mapping.get("table_name")
    metadata = snapshot.metadata if snapshot else {}
    table = metadata.get(table_name, {})
    # Unknown analysis scope is shown explicitly, never replaced by preview selection.
    scope = str(table_name) if table_name else "分析范围待确认"
    rows, columns = table.get("row_count"), table.get("column_count")
    size = f"{rows:,} 行 × {columns} 列" if rows is not None and columns is not None else "未确认"
    date_column = mapping.get("date_column")
    fact = table.get("readiness_summary", {}).get("columns", {}).get(date_column, {})
    dates = f"{fact['date_min']} 至 {fact['date_max']}" if fact.get("date_min") and fact.get("date_max") else "未确认"
    warnings = table.get("warnings")
    quality = str(len(warnings)) + " 项摄入提示" if isinstance(warnings, list) else "未生成"
    with st.container(horizontal=True, gap=12, key="workbench_data_summary"):
        for title, content in (("当前分析表", scope), ("数据规模", size), ("已识别日期范围", dates), ("质量提示", quality)):
            with st.container(width=210):
                render_compact_summary_card(title, content)
    if len(metadata) > 1:
        st.caption("当前数据共 " + str(len(metadata)) + " 张表；" + "；".join(f"{name}：{item.get('row_count', '未确认')} 行" for name, item in metadata.items()))
    st.sidebar.caption("分析范围：" + scope + "。预览表不改变分析范围。")


def open_configuration():
    st.session_state["guided_advanced"] = True
    st.session_state["workbench_page"] = "workbench"


def render_config_summary(prepared, config):
    advice = prepared.get("analysis_advice") or {}
    method = advice.get("effective_method") or advice.get("requested_method") or advice.get("recommended_method") or {}
    mapping = selected_mapping(prepared)
    definitions = prepared.get("metric_definitions") or []
    labels = [str(x.get("display_name") or x.get("metric_id")) for x in definitions]
    parameters = config.get("parameters") or {}
    source = {"automatic": "自动推荐", "example_applied": "示例后的自动推荐", "user_selected": "手动选择", "history_restored": "历史恢复", "legacy_unconfirmed": "来源待确认"}.get(config.get("selection_source"), "待确认")
    details = ["方法：" + str(method.get("display_name") or "待确认") + "（" + source + "）",
        "指标：" + ("、".join(labels) or "、".join(mapping.get("metric_columns") or []) or "待确认"),
        "范围：" + str(mapping.get("table_name") or "待确认"),
        "日期：" + str(mapping.get("date_column") or "未配置") + "；粒度：" + {"day":"日", "week":"周", "month":"月"}.get(parameters.get("time_grain", mapping.get("time_grain")), "未确认"),
        "维度：" + ("、".join(mapping.get("dimension_columns") or []) or "整体 / 待方法确定"),
        "基准：" + str(parameters.get("comparison_type") or "由当前方法与已执行范围确定"),
        "映射：" + ("用户已确认" if mapping.get("source") == "user_selected" else "建议或内置映射，结合预检复核")]
    render_compact_summary_card("本次分析配置 · 草稿", details)
    st.button("编辑分析配置", on_click=open_configuration, key="workbench_edit_config")
    st.caption("修改草稿不会改变已执行结果；开始分析前重新检查口径、适配性和安全边界。")
