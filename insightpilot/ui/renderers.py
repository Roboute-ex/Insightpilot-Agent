"""Native Streamlit renderers for Chinese-first layered analysis views."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from insightpilot.ui.formatters import (
    format_enum_value,
    format_reviewer_check_name,
    format_status,
    format_value_with_id,
    format_metric_name,
)
from insightpilot.ui.i18n import t
from insightpilot.ui.presenters import (
    METRIC_DISPLAY_NAMES,
    present_analysis_plan,
    present_join_plan,
    present_plan_review,
    present_query_plan,
    present_route_timeline,
    present_semantic_model,
    translate_caveat,
)
from insightpilot.ui.view_modes import should_show_developer_details, should_show_professional_details
from insightpilot.ui.theme import render_compact_summary_card
from insightpilot.reports.manifest import sanitize_manifest_value


def _compact_value(label: str, value: Any, delta: Any = None, *, border: bool = True) -> None:
    render_compact_summary_card(label, str(value), status=str(delta) if delta else None)


def _join(values: list[str], fallback: str = "待识别", limit: int = 4) -> str:
    return "、".join(values[:limit]) if values else fallback


def render_analysis_overview(result: dict[str, Any], view_mode: str) -> None:
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    metrics = result.get("metrics", []) if isinstance(result.get("metrics"), list) else []
    metric_names = []
    for metric in metrics:
        if isinstance(metric, dict):
            metric_names.append(str(metric.get("display_name") or metric.get("metric_name") or ""))
        else:
            metric_names.append(METRIC_DISPLAY_NAMES.get(str(metric), str(metric)))
    if result.get("metric_request", {}).get("metrics"):
        metric_names = [METRIC_DISPLAY_NAMES.get(str(item), str(item)) for item in result["metric_request"]["metrics"]]
    with st.container(horizontal=True):
        _compact_value("数据来源", format_enum_value("data_source", result.get("data_source_type")), border=True)
        _compact_value("分析目标", format_enum_value("goal_mode", result.get("goal_mode")), border=True)
        _compact_value("分析剧本", format_enum_value("playbook", selected.get("playbook_id") or "未选择"), border=True)
        _compact_value("主要指标", _join(metric_names), border=True)
        _compact_value("工作流后端", format_enum_value("backend", result.get("workflow_backend")), border=True)
        reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
        _compact_value("质量评分", reviewer.get("score", "-"), format_status(str(reviewer.get("status", ""))), border=True)
    if should_show_developer_details(view_mode):
        st.caption(f"运行编号：{result.get('run_manifest', {}).get('run_id', '-')} ")


def render_analysis_plan_summary(plan: dict[str, Any], view_mode: str) -> None:
    view = present_analysis_plan(plan)
    st.subheader(t("section.analysis_summary"), anchor=False)
    cards = [
        ("分析目标", view.goal_name),
        ("主要指标", _join(view.metric_names)),
        ("对比方式", view.comparison_method_text),
        ("分析维度", _join(view.dimension_names)),
    ]
    if hasattr(st, "columns"):
        for start in (0, 2):
            row = st.columns(2)
            for column, (title, content) in zip(row, cards[start:start + 2]):
                with column:
                    render_compact_summary_card(title, content)
    else:
        for title, content in cards:
            st.markdown(f"**{title}**：{content}")
    if view.step_descriptions:
        st.markdown("\n".join(f"{index}. {step}" for index, step in enumerate(view.step_descriptions, start=1)))
    if should_show_professional_details(view_mode):
        detail = pd.DataFrame(
            [
                {"项目": "识别意图", "说明": view.intent_name},
                {"项目": "目标来源", "说明": view.goal_source_text},
                {"项目": "所需数据表", "说明": _join(view.required_table_names, "未明确", 20)},
                {"项目": "维度列表", "说明": _join(view.dimension_names, "整体", 20)},
            ]
        )
        st.dataframe(detail, hide_index=True)
        for warning in view.warnings:
            st.warning(warning, icon=":material/warning:")
    if should_show_developer_details(view_mode):
        with st.expander("原始分析计划 JSON", expanded=False, icon=":material/code:"):
            st.json(sanitize_manifest_value(plan), expanded=False)


def render_route_timeline(route_taken: list[str], view_mode: str) -> None:
    st.subheader(t("section.execution_steps"), anchor=False)
    compact = not should_show_professional_details(view_mode)
    rows = present_route_timeline(route_taken, compact=compact, show_ids=should_show_developer_details(view_mode))
    if not rows:
        st.caption("暂无可展示的执行步骤。")
        return
    for row in rows:
        suffix = ""
        if row.get("step_id"):
            suffix = f"（{row['step_id']}）"
        elif row.get("step_ids"):
            suffix = f"（{', '.join(row['step_ids'])}）"
        st.markdown(f"{row['step']}. {row['name']}{suffix}")


def render_semantic_model_summary(model: dict[str, Any], view_mode: str) -> None:
    if not model:
        return
    view = present_semantic_model(model)
    st.subheader("语义模型摘要", anchor=False)
    with st.container(horizontal=True):
        _compact_value("模型", view.model_name, border=True)
        _compact_value("实体", view.entity_count, border=True)
        _compact_value("指标", view.metric_count, border=True)
        _compact_value("关系", view.relationship_count, border=True)
    if should_show_professional_details(view_mode) and view.entity_rows:
        st.dataframe(pd.DataFrame(view.entity_rows), hide_index=True)


def render_join_plan_summary(plan: dict[str, Any], view_mode: str) -> None:
    if not plan:
        return
    view = present_join_plan(plan)
    st.subheader(t("section.join_plan"), anchor=False)
    with st.container(horizontal=True):
        _compact_value("使用数据表", view.table_count, border=True)
        _compact_value("连接步骤", view.step_count, border=True)
        _compact_value("风险等级", view.risk_text, border=True)
        _compact_value("需要审批", view.requires_approval_text, border=True)
    if should_show_professional_details(view_mode):
        if view.step_rows:
            st.dataframe(pd.DataFrame(view.step_rows), hide_index=True)
        st.caption(f"输出粒度：{view.output_grain}；执行状态：{view.executable_text}")
        for warning in view.warnings:
            st.warning(warning, icon=":material/warning:")
        for error in view.errors:
            st.error(error, icon=":material/error:")


def render_query_plan_summary(plan: dict[str, Any], view_mode: str) -> None:
    if not plan:
        return
    view = present_query_plan(plan)
    st.subheader(t("section.query_plan"), anchor=False)
    with st.container(horizontal=True):
        _compact_value("查询指标", _join(view.metric_names), border=True)
        _compact_value("分析维度", _join(view.dimension_names, "整体"), border=True)
        _compact_value("时间粒度", view.time_grain_text, border=True)
        _compact_value("风险等级", view.risk_text, border=True)
    st.caption(f"计划编号：{view.plan_id}；时间范围：{view.date_range_text}；执行状态：{view.executable_text}")
    if should_show_professional_details(view_mode):
        details = pd.DataFrame(
            [
                {"项目": "所需实体", "说明": _join(view.table_names, "无", 20)},
                {"项目": "输出粒度", "说明": view.output_grain},
                {"项目": "筛选摘要", "说明": view.filter_summary},
                {"项目": "参数数量", "说明": view.parameter_count},
                {"项目": "指标依赖", "说明": _join(view.metric_dependencies, "基础度量", 20)},
            ]
        )
        st.dataframe(details, hide_index=True)
        if should_show_developer_details(view_mode):
            with st.expander("查看只读 SQL 预览", expanded=False, icon=":material/code:"):
                st.code(view.sql_preview, language="sql")


def render_plan_review(review: dict[str, Any]) -> None:
    if not review:
        return
    view = present_plan_review(review)
    message = f"{view.decision_text}：{view.reason} {view.approved_for_execution_text}。"
    if review.get("decision") == "approved":
        st.success(message, icon=":material/check_circle:")
    elif review.get("decision") == "rejected":
        st.error(message, icon=":material/error:")
    else:
        st.warning(message, icon=":material/pending:")


def render_caveats(caveats: list[Any], view_mode: str) -> None:
    values = caveats if isinstance(caveats, list) else []
    if not values:
        return
    st.subheader(t("section.risks_and_limitations"), anchor=False)
    errors = [item for item in values if isinstance(item, dict) and item.get("severity") == "error"]
    for item in errors:
        st.error(translate_caveat(item), icon=":material/error:")
    non_errors = [item for item in values if item not in errors]
    if not non_errors:
        return
    with st.expander("查看风险与限制", expanded=False, icon=":material/info:"):
        if not should_show_professional_details(view_mode):
            for item in non_errors:
                st.markdown(f"- {translate_caveat(item)}")
            return
        categories = {"数据质量": [], "分析方法": [], "因果解释": [], "系统边界": []}
        for item in non_errors:
            message = translate_caveat(item)
            lowered = message.lower()
            if any(term in lowered for term in ("缺少", "字段", "数据质量", "样本")):
                category = "数据质量"
            elif any(term in lowered for term in ("因果", "相关性")):
                category = "因果解释"
            elif any(term in lowered for term in ("模拟数据", "内存", "后端", "系统")):
                category = "系统边界"
            else:
                category = "分析方法"
            categories[category].append((item, message))
        for category, items in categories.items():
            if not items:
                continue
            st.markdown(f"**{category}**")
            for raw, message in items:
                if should_show_developer_details(view_mode) and isinstance(raw, dict) and raw.get("code"):
                    st.markdown(f"- {message}（{raw['code']}）")
                else:
                    st.markdown(f"- {message}")


def render_reviewer(reviewer: dict[str, Any], view_mode: str) -> None:
    st.subheader(t("section.quality_review"), anchor=False)
    status = str(reviewer.get("status", "WARN"))
    score = reviewer.get("score", 0)
    columns = st.columns(3)
    with columns[0]:
        render_compact_summary_card("质量评分", str(score))
    with columns[1]:
        render_compact_summary_card("检查状态", format_status(status))
    with columns[2]:
        render_compact_summary_card("主要警告", str(len(reviewer.get("issues", []))))
    issues = reviewer.get("issues", [])
    if issues:
        with st.expander("查看质量检查问题", expanded=False, icon=":material/warning:"):
            for issue in issues:
                st.markdown(f"- {issue}")
    if should_show_professional_details(view_mode):
        rows = [
            {"检查项": format_reviewer_check_name(name), "检查结果": "通过" if passed else "未通过"}
            for name, passed in reviewer.get("checks", {}).items()
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        for suggestion in reviewer.get("suggestions", []):
            st.caption(f"建议：{suggestion}")


def render_contracts(results: list[dict[str, Any]], view_mode: str) -> None:
    if not results:
        return
    st.subheader(t("section.contracts"), anchor=False)
    failed = sum(item.get("status") == "FAIL" for item in results)
    warned = sum(item.get("status") == "WARN" for item in results)
    with st.container(horizontal=True):
        _compact_value("错误", failed, border=True)
        _compact_value("警告", warned, border=True)
        _compact_value("检查总数", len(results), border=True)
    if should_show_professional_details(view_mode):
        rows = [
            {
                "检查项": item.get("check_name"),
                "对象": item.get("object_name"),
                "实际值": str(item.get("actual_value")),
                "期望值": str(item.get("expected_value")),
                "严重程度": format_enum_value("contract_status", item.get("severity")),
                "检查结果": format_enum_value("contract_status", item.get("status")),
                "说明": item.get("message"),
            }
            for item in results
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True)


def render_lineage(lineage: dict[str, Any], view_mode: str) -> None:
    if not lineage:
        return
    st.subheader(t("section.lineage"), anchor=False)
    datasets = lineage.get("datasets", [])
    operations = lineage.get("operations", [])
    edges = lineage.get("edges", [])
    inputs = sum(item.get("dataset_type") == "input" for item in datasets if isinstance(item, dict))
    outputs = sum(item.get("dataset_type") == "output" for item in datasets if isinstance(item, dict))
    with st.container(horizontal=True):
        _compact_value("输入数据表", inputs, border=True)
        _compact_value("执行操作", len(operations), border=True)
        _compact_value("输出结果表", outputs, border=True)
        _compact_value("派生关系", len(edges), border=True)
    if should_show_professional_details(view_mode):
        st.caption(f"数据指纹：{lineage.get('lineage_fingerprint', '-')}")


def render_observability(telemetry: dict[str, Any], view_mode: str) -> None:
    if not telemetry:
        return
    summary = telemetry.get("summary", {}) if isinstance(telemetry.get("summary"), dict) else {}
    st.subheader(t("section.observability"), anchor=False)
    with st.container(horizontal=True):
        _compact_value("总耗时", f"{summary.get('total_duration_ms', 0):.1f} 毫秒", border=True)
        _compact_value("查询次数", summary.get("query_count", 0), border=True)
        _compact_value("最慢步骤", format_enum_value("route_step", summary.get("slowest_step")), border=True)
        _compact_value("警告数量", summary.get("warning_count", 0), border=True)
    if should_show_professional_details(view_mode):
        st.caption(
            f"错误数量：{summary.get('error_count', 0)}；Join 风险数量：{summary.get('join_risk_count', 0)}；"
            f"本地 span：{summary.get('span_count', 0)}"
        )


def render_developer_details(result: dict[str, Any], view_mode: str) -> None:
    if not should_show_developer_details(view_mode):
        return
    objects = {
        "原始分析计划 JSON": "plan", "原始工作流状态 JSON": "workflow_state",
        "原始执行记录 JSON": "trace", "原始查询计划 JSON": "query_plan",
        "原始连接方案 JSON": "join_plan", "原始运行清单 JSON": "run_manifest",
        "原始图表规格 JSON": "chart_specs", "原始数据血缘 JSON": "lineage",
        "原始本地观测 JSON": "telemetry", "原始数据契约 JSON": "contract_results",
        "原始评估 JSON": "evaluation",
    }
    available = [title for title, key in objects.items() if result.get(key)]
    st.caption(f"可用技术对象 {len(available)} 项。默认仅展示摘要；主动请求后显示单个脱敏 JSON，原始数据表不进入 JSON。")
    if not available:
        return
    if st.session_state.get("developer_object_selector") not in available:
        st.session_state["developer_object_selector"] = available[0]
    selected = st.selectbox("选择技术对象", available, key="developer_object_selector")
    value = result.get(objects[selected])
    st.caption(f"对象类型：{type(value).__name__}；顶层条目：{len(value) if isinstance(value, (dict, list)) else 1}。")
    run_id = result.get("run_manifest", {}).get("run_id")
    from insightpilot.performance import BoundedCache, PerformanceConfig, estimate_size_bytes
    cache = st.session_state.get("performance_developer_json_cache")
    if not isinstance(cache, BoundedCache):
        cache = BoundedCache(1, 8 * 1024 * 1024, PerformanceConfig.from_environment().session_ttl_seconds)
        st.session_state["performance_developer_json_cache"] = cache
    if st.button("显示所选 JSON", key="developer_json_show"):
        if estimate_size_bytes(value) > 8 * 1024 * 1024:
            st.warning("该对象超过技术详情 8 MiB 显示预算。请选择更小的对象或查看运行清单摘要；未改变分析数据。")
            cache.clear()
        else:
            cache.put((run_id, selected), sanitize_manifest_value(value))
    request = cache.get((run_id, selected))
    if request is not None:
        st.markdown(f"**{selected}**")
        st.json(request, expanded=False)
