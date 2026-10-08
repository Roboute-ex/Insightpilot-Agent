"""Registry-driven, metadata-only method discovery and configuration."""
from __future__ import annotations
import streamlit as st
from html import escape
from insightpilot.playbooks.registry import get_playbook_registry

# Display taxonomy only. Registry remains the only source of method identity.
CATEGORIES = {
    "data_profile": "数据理解",
    "metric_trend": "变化与诊断", "period_comparison": "变化与诊断",
    "dimension_contribution": "变化与诊断", "periodic_summary": "变化与诊断",
    "experiment_comparison": "实验与效果", "causal_exploration": "实验与效果",
    "semantic_metric_query": "用户与多表", "funnel_analysis": "用户与多表", "cohort_retention": "用户与多表",
}
COMMON_IDS = ("data_profile", "metric_trend", "period_comparison", "dimension_contribution", "experiment_comparison", "causal_exploration")
OUTPUT_LABELS = {
    "profile": "字段画像", "quality": "质量检查", "numeric_summary": "数值摘要", "trend": "趋势",
    "change": "指标变化", "anomalies": "异常点", "comparison": "周期对比", "dimensions": "维度拆解",
    "ranking": "完整范围排名", "contribution": "贡献及占比", "experiment": "组间比较",
    "significance": "对应检验", "confidence_interval": "匹配的置信区间", "naive": "原始组间差",
    "adjusted": "有协变量时的OLS调整估计", "caveats": "适用边界", "top_dimensions": "主要维度",
    "semantic_model": "指标口径", "join_plan": "连接方案", "query_plan": "查询与审批计划",
    "metric_result": "指标结果", "funnel": "阶段转化", "cohort": "队列矩阵", "retention": "留存率",
}


def candidate_index(advice):
    return {x.get("method_ref"): x for x in [*(advice.get("candidates") or []), *(advice.get("other_methods") or [])]}


def method_requirements(playbook):
    labels = {"requires_table": "目标数据表", "requires_date_column": "日期字段", "requires_metric_columns": "指标字段",
        "requires_dimension_columns": "分析维度", "requires_group_column": "分组字段",
        "requires_treatment_column": "处理变量字段", "requires_outcome_column": "结果变量字段"}
    requirements = playbook.requirements.to_dict()
    needed = [label for key, label in labels.items() if requirements.get(key)]
    needed.extend("数据表：" + name for name in requirements.get("required_tables", []))
    if requirements.get("minimum_rows"):
        needed.append(f"至少 {requirements['minimum_rows']} 行")
    if requirements.get("requires_semantic_model"):
        needed.append("已定义的语义模型")
    return [*needed, *playbook.field_requirements_zh]


def clear_method_filters():
    st.session_state["method_search"] = ""
    st.session_state["method_category"] = "全部"


def render_method_card(playbook, candidate, *, compact=False, key_prefix="guided_choose_"):
    from app.components.guidance_panel import _catalog_state, configure_method
    with st.container(border=True, key="method_card_" + key_prefix + playbook.playbook_id):
        st.markdown('<div class="ip-method-title">' + escape(f"{playbook.display_name} · {_catalog_state(candidate)}") + "</div>", unsafe_allow_html=True)
        st.write("用途：" + playbook.description)
        if not compact:
            outputs = playbook.result_description_zh or "、".join(OUTPUT_LABELS.get(x, x) for x in playbook.output_sections)
            st.caption("主要输出：" + outputs)
        issues = candidate.get("missing_inputs") or []
        if issues:
            for issue in issues[:2] if compact else issues:
                st.caption("缺失条件或限制：" + (str(issue.get("message_zh", issue)) if isinstance(issue, dict) else str(issue)))
        elif not candidate:
            st.caption("缺失条件：尚无完整适配检查，请进入配置后重新预检。")
        else:
            st.caption("缺失条件：暂无已知字段或参数缺口；统计前提仍需核对。")
        if candidate.get("goal_fit") == "unrelated":
            st.caption("与当前问题不匹配；须明确调整分析目标或问题。")
        st.button("配置：" + playbook.display_name, key=key_prefix + playbook.playbook_id,
                  on_click=configure_method, args=(playbook.playbook_id,), width="stretch")
        if not compact:
            details = st.expander("查看要求与限制", key="method_requirements_" + playbook.playbook_id, on_change="rerun")
            if details.open:
                with details:
                    st.write("基本要求：" + "、".join(method_requirements(playbook)))
                    for caveat in playbook.caveats_zh:
                        st.caption(caveat)
                    if playbook.playbook_id == "causal_exploration":
                        st.caption("字段齐全不等于因果关系成立。随机化、无未观测混杂、重叠性和时序前提未自动验证；当前实现不执行倾向评分加权。没有协变量时不生成调整估计。")
                    elif playbook.playbook_id == "experiment_comparison":
                        st.caption("需确认独立统计单位、组方向和指标类型；比例指标绝对差采用百分点。字段可用不等于随机化或独立性已验证。")
                    elif playbook.playbook_id == "cohort_retention":
                        st.caption("按实体去重并保留观察窗口；未观察的未来期间不能记为零留存。")
                    elif playbook.playbook_id == "dimension_contribution":
                        st.caption("当前指标份额与跨期变化贡献不同；不同维度的贡献不能相加。")
                    st.caption("配置只更新草稿；安全、审批与统计前提仍由统一预检和执行门禁核对。")


def render_method_gallery(advice, *, filters=True):
    methods = get_playbook_registry().list_all()
    candidates = candidate_index(advice)
    if filters:
        st.subheader("分析方法", anchor=False)
        st.caption("按分析目的查找方法。目录包含全部注册方法；当前数据不适配的方法仍可查看要求并配置。")
        with st.container(horizontal=True):
            search = st.text_input("搜索分析方法", key="method_search", placeholder="名称、用途或主要输出")
            category = st.selectbox("方法分类", ["全部", "数据理解", "变化与诊断", "实验与效果", "用户与多表"], key="method_category")
            st.button("清除方法筛选", on_click=clear_method_filters, key="method_clear_filters")
        needle = search.strip().casefold()
        visible = [p for p in methods if (category == "全部" or CATEGORIES.get(p.playbook_id) == category)
            and (not needle or needle in " ".join([p.display_name, p.description, p.result_description_zh, *p.tags]).casefold())]
    else:
        visible = methods
    st.caption(f"显示 {len(visible)} / {len(methods)} 个分析方法；状态来自当前草稿的适配检查，不代表统计结论已成立。")
    if not visible:
        st.info("当前搜索或分类没有匹配方法，可清除筛选查看完整目录。")
    with st.container(horizontal=True, gap=16, key="method_gallery_cards"):
        for playbook in visible:
            with st.container(width=350):
                render_method_card(playbook, candidates.get("playbook:" + playbook.playbook_id, {}))


def render_common_methods(advice):
    candidates = candidate_index(advice)
    methods = {p.playbook_id: p for p in get_playbook_registry().list_all()}
    st.subheader("常用分析方法", anchor=False)
    st.caption("先查看适配状态，再配置；点击卡片不会开始分析。")
    with st.container(horizontal=True, gap=16, key="common_method_cards"):
        for identifier in COMMON_IDS:
            if identifier in methods:
                with st.container(width=320):
                    render_method_card(methods[identifier], candidates.get("playbook:" + identifier, {}), compact=True, key_prefix="common_choose_")
