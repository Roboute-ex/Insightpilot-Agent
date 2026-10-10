"""Small projections of the selected immutable run; no data scans or result copies."""
from __future__ import annotations

import re
from typing import Any

import streamlit as st

from insightpilot.reports.manifest import _safe_string
from insightpilot.ui.synthetic_display import synthetic_display_text


def _display(value, config, *, key=""):
    text = _safe_string(str(value), key=key)
    if config.get("data_source_type") == "synthetic":
        text = synthetic_display_text(text)
    return text[:240]


def _method(node):
    context, config = node.context, node.config
    exploration = (config.get("parameters") or {}).get("exploration_request") or {}
    if exploration:
        return {"grouped": "描述性分组汇总", "pivot": "描述性交叉表", "distribution": "字段分布"}.get(exploration.get("kind"), "描述性探索")
    method = (context.get("method") or {}).get("playbook")
    if method in {None, "legacy", "__legacy__"}:
        return "指标波动诊断（描述性比较）" if (context.get("method") or {}).get("goal") in {"metric_diagnosis", "auto"} else "自动分析工作流"
    from insightpilot.playbooks.registry import get_playbook_registry
    try:
        label = get_playbook_registry().get(method).display_name
    except ValueError:
        label = "已记录的方法（名称待核对）"
    if method == "dimension_contribution":
        label += "（静态分组表现）"
    return label


def _label(node):
    config = node.config
    exploration = (config.get("parameters") or {}).get("exploration_request") or {}
    cities = [x for x in exploration.get("filters", []) if x.get("column") == "city" and x.get("operator") == "eq"]
    if len(cities) == 1:
        same_day = bool(exploration.get("date_from") and exploration.get("date_from") == exploration.get("date_to"))
        return _display(cities[0].get("value"), config) + ("当日探索" if same_day else "分组探索")
    method = _method(node)
    if method.startswith("指标波动诊断"):
        return "整体订单诊断" if "订单" in config.get("question", "") else "整体指标诊断"
    return method.split("（", 1)[0]


def run_source_tables(node, config=None):
    """Resolve only frozen source metadata; no query or inferred replacement table."""
    config = node.config if config is None else config
    table = (config.get("column_mapping") or {}).get("table_name")
    if table:
        return [table]
    context = node.context
    definitions = context.get("definitions") or []
    tables = list(dict.fromkeys(item["table_name"] for item in definitions if item.get("table_name")))
    if tables:
        return tables
    # Semantic cards expose a scope (possibly the model itself for derived metrics),
    # not a single table_name. The already bounded schema records the actual loaded
    # table scope, including join inputs. Require that whole frozen scope rather
    # than guessing dependencies from labels or accepting arbitrary current tables.
    semantic = (context.get("method") or {}).get("playbook") == "semantic_metric_query"
    registered = definitions and all(item.get("scenario") == "semantic" and item.get("source") == "registered_definition" for item in definitions)
    schema = context.get("schema") or {}
    return list(schema) if semantic and registered and isinstance(schema, dict) else []


def project_run_context(history, node_id: str, snapshot=None) -> dict[str, Any]:
    """Only inspect session-owned bounded JSON metadata, including orphan paths."""
    node = history.get(node_id)  # Forged/foreign IDs cannot become a viewing target.
    by_run = {item.run_id: item for item in history.nodes if item.thread_id == history.thread_id}
    chain, visited, boundary = [], set(), None
    cursor = node
    while cursor is not None:
        if cursor.node_id in visited:
            boundary = "历史路径存在循环引用，已停止追溯。"
            break
        visited.add(cursor.node_id)
        chain.append(cursor)
        if not cursor.parent_run_id:
            break
        cursor = by_run.get(cursor.parent_run_id)
        if cursor is None:
            boundary = "上一级历史元数据已清理，无法直接返回；当前运行仍可查看。"
            break
        if len(chain) >= history.max_nodes:
            boundary = "历史路径超过保留范围，已停止追溯。"
            break
    parent = by_run.get(node.parent_run_id)
    if parent is not None and (parent.node_id == node.node_id or boundary and "循环" in boundary):
        parent = None
    config, context = node.config, node.context
    mapping = config.get("column_mapping") or {}
    definitions = context.get("definitions") or []
    tables = run_source_tables(node)
    loaded_scope = bool(tables) and not mapping.get("table_name") and not any(item.get("table_name") for item in definitions)
    source_label = "源表（该运行已加载范围）：" if loaded_scope else "源表："
    lines = [source_label + ("、".join(_display(x, config) for x in tables) or "未记录")]
    window = context.get("window") or {}
    params = (config.get("parameters") or {})
    exploration = params.get("exploration_request") or {}
    dates = []
    if exploration.get("date_from") or exploration.get("date_to"):
        dates.append(str(exploration.get("date_from") or "起点未限定") + " 至 " + str(exploration.get("date_to") or "终点未限定"))
    elif window.get("periods"):
        dates.append(str(window["periods"]))
    else:
        if window.get("target_dates"):
            dates.append("目标日 " + "、".join(window["target_dates"]))
        for item in window.get("computed", []):
            if item and re.search(r"\d{4}-\d{2}-\d{2}", str(item[0])):
                dates.append(str(item[0]))
        for key in ("parameters", "semantic"):
            if window.get(key):
                dates.append(str(window[key]))
        if not dates:
            dates.extend(str(x["time_range"]) for x in definitions if x.get("time_range"))
    lines.append("已执行日期范围：" + _display("；".join(dict.fromkeys(dates)) or "未记录，不能按电脑日期推定", config))
    baselines = list(dict.fromkeys(str(item[1]) for item in window.get("computed", []) if len(item) > 1 and item[1]))
    if baselines:
        lines.append("已执行比较基准：" + _display("、".join(baselines), config))
    filters = context.get("filters") or []
    if filters:
        labels = []
        for item in filters[:8]:
            column = str(item.get("column", item.get("field", "字段")))
            value = _display(item.get("value"), config, key=column)
            column_label = "城市" if column == "city" else _display(column, config)
            operator = {"eq": "=", "in": "属于", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "between": "介于"}.get(item.get("operator"), str(item.get("operator", "=")))
            labels.append(column_label + " " + operator + " " + value)
        lines.append("已执行筛选：" + "；".join(labels))
    else:
        lines.append("已执行筛选：未额外限定分组")
    metrics = []
    for item in definitions[:3]:
        unit = item.get("unit") or "单位未确认"
        statistical = {"row": "观测行", "not_applicable": "不适用"}.get(item.get("statistical_unit"), item.get("statistical_unit") or "未确认")
        metrics.append(f"{item.get('display_name') or item.get('metric_id')}（{unit}；统计单位：{statistical}）")
    if metrics:
        lines.append("指标：" + _display("、".join(metrics), config))
    matches = None if snapshot is None else (context.get("dataset_id") == snapshot.dataset_id and str(node.dataset_revision) == str(snapshot.revision))
    available = None if snapshot is None else bool(tables) and all(x in snapshot.metadata for x in tables)
    return {"run_id": node.run_id, "label": _label(node),
            "breadcrumbs": [{"node_id": item.node_id, "run_id": item.run_id, "label": _label(item), "current": item.node_id == node.node_id} for item in reversed(chain)],
            "parent_node_id": parent.node_id if parent else None, "boundary": boundary,
            "scope_lines": lines, "method_label": _method(node), "data_matches": matches,
            "source_available": available}


def render_analysis_context(session, snapshot):
    """Render a selected run even when its full result has been released."""
    node_id = session.history.active_node_id
    if not node_id:
        return None
    try:
        node = session.history.get(node_id)
        context = project_run_context(session.history, node_id, snapshot)
    except ValueError:
        st.info("当前查看的历史节点已清理，请到“历史比较”选择仍保留的运行。")
        return None
    from app.components.history_panel import _activate_history_run, request_restore, render_restore_prompt
    # Keep the exploration form mounted: its unsubmitted values exist only in
    # the browser. Selecting a run must not replace that page or its widgets.
    return_page = None if st.session_state.get("workbench_page") == "explore" else "workbench"
    with st.container(key="core_analysis_context"):
        st.caption("当前分析路径")
        with st.container(horizontal=True, vertical_alignment="center", gap=8):
            for index, item in enumerate(context["breadcrumbs"]):
                if index:
                    st.text("›")
                if item["current"]:
                    st.text(item["label"])
                else:
                    st.button(item["label"], key="core_ancestor_" + item["node_id"], type="tertiary",
                        on_click=_activate_history_run, args=(session, item["node_id"]), kwargs={"page": return_page})
        st.caption("已执行问题：" + _display(node.config.get("question", "未记录"), node.config))
        for line in context["scope_lines"]:
            st.caption(line)
        st.caption("本次实际方法：" + context["method_label"])
        if context["boundary"]:
            st.info(context["boundary"])
        if context["parent_node_id"]:
            st.button("返回上一级分析", key="core_return_parent", on_click=_activate_history_run,
                args=(session, context["parent_node_id"]), kwargs={"page": return_page})
        valid_data = context["data_matches"] is True and context["source_available"] is True
        if not valid_data:
            st.warning("当前数据与该运行绑定的数据版本或源表不一致。此处仅为历史记录；恢复到当前数据前需明确确认并重新检查。")
        if not valid_data or not session.history.result_available(node, session.current):
            st.info("这是历史摘要；完整结果已释放或其数据引用已失效，尚未重新计算。")
            summary = node.summary.get("text") or "此运行没有保留数值摘要。"
            text = _safe_string(str(summary))
            st.write(synthetic_display_text(text) if node.config.get("data_source_type") == "synthetic" else text)
            st.caption("当前不能查看完整证据或生成该运行的完整报告；请恢复配置，明确重新运行后生成。")
            st.button("恢复该分析配置", key="core_restore_config", on_click=request_restore,
                      args=(session, node.node_id))
        render_restore_prompt(session, snapshot)
    return node
