"""Explicit, metadata-backed exploration controls over the existing workflow."""
from __future__ import annotations
from copy import deepcopy
import math
import pandas as pd
import streamlit as st

from insightpilot.planning.planner import prepare_analysis_request

SECTIONS = {"fields": "字段概览", "distribution": "分布", "grouped": "分组图", "pivot": "交叉表"}
AGGREGATIONS = {"sum": "求和", "mean": "均值（按有效观测行）", "count": "非空计数", "count_distinct": "去重计数", "min": "最小值", "max": "最大值", "ratio_of_sums": "加权比率（总分子 / 总分母）"}


def exploration_preflight(snapshot, config):
    return prepare_analysis_request(config["question"], table_metadata=snapshot.metadata,
        goal_mode=config["goal_mode"], playbook_id=config["playbook_id"],
        column_mapping=config["column_mapping"], playbook_parameters=config["parameters"],
        dataset_revision=str(snapshot.revision), selection_source="user_selected")


def stage_exploration(snapshot, config, *, parent_run_id=None):
    """Only called on explicit submit. The main pump freezes and checks again."""
    prepared = exploration_preflight(snapshot, config)
    if prepared.get("planning_status") != "ready" or not prepared.get("analysis_advice", {}).get("can_submit", False):
        st.session_state["exploration_errors"] = list(dict.fromkeys([
            *prepared.get("clarification", {}).get("errors", []),
            *[str(item.get("message_zh") or item.get("message") or item) for item in prepared.get("analysis_advice", {}).get("blocking_issues", [])],
            *[str(item.get("question") or item.get("reason") or item) for item in prepared.get("clarification", {}).get("items", [])],
        ])) or ["当前配置仍需补充，请确认字段、聚合口径和分析范围。"]
        return False
    st.session_state.pop("exploration_errors", None)
    st.session_state["performance_pending_branch"] = {"parent_run_id": parent_run_id, "config": deepcopy(config)}
    st.session_state["workbench_submit_requested"] = True
    st.rerun()


def _reset_revision(snapshot):
    identity = (snapshot.dataset_id, str(snapshot.revision))
    if st.session_state.get("exploration_dataset") != identity:
        for key in list(st.session_state):
            if key.startswith("exploration_"):
                st.session_state.pop(key, None)
        st.session_state["exploration_dataset"] = identity


def _select(label, options, key, *, suggested=None, optional=False, **kwargs):
    choices = ([None] if optional else []) + list(options)
    if st.session_state.get(key) not in choices:
        st.session_state[key] = suggested if suggested in choices else choices[0]
    return st.selectbox(label, choices, key=key, placeholder="可不选择" if optional else "请选择字段", format_func=lambda v: "不选择" if v is None else str(v), **kwargs)


def _field_overview(meta):
    facts = meta.get("readiness_summary", {}).get("columns", {})
    rows = []
    total = meta.get("row_count")
    for column in meta.get("columns", []):
        fact = facts.get(column, {})
        valid = fact.get("non_null_count")
        rows.append({"字段": column, "类型": fact.get("dtype", "未确认"), "有效非空": valid,
            "缺失": total-valid if isinstance(total, int) and isinstance(valid, int) else None,
            "不同值数量": fact.get("unique_count"), "日期起": fact.get("date_min"), "日期止": fact.get("date_max")})
    st.caption("以下为本数据修订加载时的实际元数据；空白表示未确认。打开此页不重新扫描原始数据。")
    page = st.number_input("字段页", min_value=1, max_value=max(1, math.ceil(len(rows)/50)), key="exploration_field_page")
    st.dataframe(pd.DataFrame(rows[(page-1)*50:page*50]), hide_index=True, width="stretch")


def _typed_filter(value, fact):
    if fact.get("values_complete"):
        matches = [item for item in fact.get("values", []) if str(item) == value]
        if len(matches) == 1:
            return matches[0]
    if str(fact.get("dtype", "")).lower().startswith(("int", "uint", "float")):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("筛选数值必须有限。")
        return int(number) if number.is_integer() else number
    return value


def _render_result(session):
    node = next((n for n in session.history.nodes if n.node_id == session.history.active_node_id), None)
    result = session.current
    if node is not None and not session.history.result_available(node, result):
        st.info("选定历史结果已释放，需要重新执行；当前探索草稿没有改变该历史结果。")
        return
    if not isinstance(result, dict) or result.get("execution_status") != "COMPLETED":
        return
    exploration = (result.get("result_package") or result.get("analysis_result_package") or {}).get("metadata", {}).get("exploration")
    exploration = exploration or (result.get("playbook_result") or {}).get("metadata", {}).get("exploration")
    if not exploration:
        # Package key is the established workflow 'analysis_package'.
        exploration = (result.get("analysis_package") or {}).get("metadata", {}).get("exploration")
    if not exploration:
        st.caption("当前保留的是其它分析结果；请在分析工作台查看。探索草稿尚未执行。")
        return
    st.subheader("已生成探索结果", anchor=False)
    st.caption("运行 " + str(result.get("run_manifest", {}).get("run_id", "")) + "；下方仅显示该运行的冻结口径，未提交的新配置不参与结果或报告。")
    from app.components.result_panel import render_result_panel
    render_result_panel(result, view_mode="demo")


def render_exploration_panel(snapshot, analysis_session):
    if snapshot is None:
        st.info("请先加载数据，再选择探索范围。")
        return
    _reset_revision(snapshot)
    st.subheader("数据探索", anchor=False)
    tables = list(snapshot.metadata)
    mapping_now = st.session_state.get("guided_mapping") or {}
    table = _select("探索分析表（与预览表独立）", tables, "exploration_table", suggested=mapping_now.get("table_name") or ("daily_metrics" if "daily_metrics" in tables else tables[0]))
    meta = snapshot.metadata[table]
    columns = list(meta.get("columns", []))
    if not columns:
        st.info("所选表没有可用字段。")
        return
    st.session_state.setdefault("exploration_section", "fields")
    section = st.segmented_control("探索视图", list(SECTIONS), format_func=SECTIONS.get, required=True, key="exploration_section")
    if section == "fields":
        _field_overview(meta)
        return
    facts = meta.get("readiness_summary", {}).get("columns", {})
    numeric = [c for c in columns if facts.get(c, {}).get("valid_numeric_count", 0)]
    dates = [c for c in columns if facts.get(c, {}).get("valid_date_count", 0)]
    defaults = meta.get("schema_mapping", {})
    dimensions = defaults.get("possible_dimension_columns", [])
    aggregation = "sum"
    if section != "distribution":
        aggregation = st.selectbox("指标聚合口径", list(AGGREGATIONS), format_func=AGGREGATIONS.get, key="exploration_aggregation")
    st.caption("筛选、时间范围、指标和维度只形成草稿。明确点击生成才进行全量计算；图型与标签切换只改展示。")
    base_filters = st.session_state.get("exploration_base_filters") or []
    if base_filters:
        st.caption("恢复运行的原筛选：" + str(base_filters))
    with st.form("exploration_request_form"):
        st.session_state.setdefault("exploration_keep_filters", True)
        keep_filters = st.checkbox("保留上次运行的上述筛选", key="exploration_keep_filters") if base_filters else False
        left, right = st.columns(2)
        with left:
            field = _select("探索字段", columns, "exploration_field") if section == "distribution" else None
            metric_choices = columns if aggregation in {"count", "count_distinct"} else numeric
            metric = _select("指标字段", metric_choices, "exploration_metric", suggested="orders" if "orders" in metric_choices else None) if section != "distribution" and metric_choices else None
            numerator = denominator = None
            if section != "distribution" and aggregation == "ratio_of_sums":
                numerator = _select("比率分子字段", numeric, "exploration_numerator", optional=True)
                denominator = _select("比率分母字段", numeric, "exploration_denominator", optional=True)
                metric = numerator
            row = _select("行维度 / 分组字段", columns, "exploration_row", suggested="city" if "city" in columns else next(iter(dimensions), None)) if section != "distribution" else None
            col = _select("列维度", columns, "exploration_column", suggested=next((x for x in dimensions if x != row), None)) if section == "pivot" else None
            date_col = _select("日期字段", dates, "exploration_date", optional=True)
            grain = st.selectbox("日期分组粒度（仅行维度为日期字段时生效）", [None, "day", "week", "month"], format_func=lambda x: {None:"不按日期合并", "day":"日", "week":"周", "month":"月"}[x], placeholder="不按日期合并", key="exploration_grain")
        with right:
            st.session_state.setdefault("exploration_date_from", None)
            st.session_state.setdefault("exploration_date_to", None)
            date_from = st.date_input("开始日期（可不填）", key="exploration_date_from")
            date_to = st.date_input("结束日期（可不填）", key="exploration_date_to")
            filter_col = _select("筛选字段（可不选）", columns, "exploration_filter_column", optional=True)
            filter_op = st.selectbox("筛选关系", ["eq", "in", "gt", "gte", "lt", "lte", "between"], format_func={"eq":"等于", "in":"属于（逗号分隔）", "gt":"大于", "gte":"大于等于", "lt":"小于", "lte":"小于等于", "between":"范围（两个值以逗号分隔）"}.get, key="exploration_filter_operator")
            filter_text = st.text_input("筛选值", placeholder="填写真实取值；字符串作为绑定参数处理", key="exploration_filter_value")
            filter_null = st.checkbox("筛选缺失值（仅等于）", key="exploration_filter_null")
            st.session_state.setdefault("exploration_top_n", 15)
            if st.session_state.get("exploration_top_n", 15) > (29 if section == "pivot" else 49):
                st.session_state["exploration_top_n"] = 29 if section == "pivot" else 49
            top_n = st.number_input("图表 Top N（其余组成 Others）", min_value=1, max_value=29 if section == "pivot" else 49, key="exploration_top_n")
            st.session_state.setdefault("exploration_unit", "原字段单位")
            unit = st.text_input("指标单位", key="exploration_unit") if section != "distribution" else "原字段单位"
        confirmed = st.checkbox("我确认以上字段、聚合口径与范围，用于本次描述性探索", key="exploration_confirmed")
        submitted = st.form_submit_button("生成分布" if section == "distribution" else "生成探索结果", key="exploration_generate", type="primary")
    if submitted:
        errors = []
        filters = deepcopy(base_filters) if keep_filters else []
        if not confirmed:
            errors.append("请明确确认本次指标口径与范围，再生成结果。")
        if filter_col:
            try:
                if filter_null:
                    if filter_op != "eq":
                        raise ValueError("缺失值筛选只支持等于。")
                    value = None
                else:
                    if not filter_text.strip():
                        raise ValueError("已选筛选字段，请填写筛选值或明确选择缺失值。")
                    values = [x.strip() for x in filter_text.split(",")] if filter_op in {"in", "between"} else [filter_text]
                    parsed = [_typed_filter(x, facts.get(filter_col, {})) for x in values]
                    value = parsed if filter_op in {"in", "between"} else parsed[0]
                filters.append({"column":filter_col,"operator":filter_op,"value":value})
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        request = {"kind":section,"filters":filters,"date_from":str(date_from) if date_from else None,"date_to":str(date_to) if date_to else None,
            "top_n":int(top_n),"include_others":True,"max_display_rows":50,"max_display_columns":30}
        if section == "distribution":
            request.update(field=field, distribution_type="auto")
        else:
            request.update(row_dimension=row, column_dimension=col, time_grain=grain)
        mapping = {"table_name":table,"source":"user_selected","date_column":date_col,"metric_columns":[metric] if metric else [],
            "dimension_columns":[x for x in [row,col] if x],"aggregation":aggregation,"unit":unit,"statistical_unit":"row",
            "deduplication_key":metric if aggregation == "count_distinct" else None,
            "numerator_column":numerator,"denominator_column":denominator,"time_grain":grain or "day"}
        config = {"question":f"查看 {table} 的{SECTIONS[section]}，按已确认口径作描述性汇总", "goal_mode":"periodic_report", "playbook_id":"data_profile" if section == "distribution" else "dimension_contribution",
            "column_mapping":mapping, "parameters":{"exploration_request":request, **({"aggregation":aggregation} if section != "distribution" else {})},"use_langgraph":False,"selection_source":"user_selected"}
        if errors:
            st.session_state["exploration_errors"] = errors
        else:
            stage_exploration(snapshot, config)
    for message in st.session_state.get("exploration_errors", []):
        st.warning(str(message))
    st.caption("均值按有效观测行计算；比率按总分子/总分母；去重合计在对应范围重新去重。缺失与未观测组合不补成0。")
    _render_result(analysis_session)
