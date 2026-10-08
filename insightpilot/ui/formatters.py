"""Central mapping from stable English enums to Chinese display values."""

from __future__ import annotations

import re
from typing import Any


GOAL_MODE_DISPLAY_NAMES = {
    "auto": "自动识别",
    "metric_diagnosis": "指标波动诊断",
    "growth_trend": "增长与趋势分析",
    "experiment_analysis": "实验效果评估",
    "content_performance": "内容表现分析",
    "live_quality": "体验质量分析",
    "causal_exploration": "轻量因果探索",
    "periodic_report": "周期分析报告",
}
INTENT_DISPLAY_NAMES = {
    "metric_drop_diagnosis": "指标下降诊断",
    "metric_growth_analysis": "指标增长与趋势分析",
    "experiment_analysis": "实验效果评估",
    "content_performance_analysis": "内容表现分析",
    "live_quality_analysis": "体验质量分析",
    "causal_exploration": "轻量因果探索",
    "general_summary": "综合分析摘要",
}
BACKEND_DISPLAY_NAMES = {
    "rule_based": "确定性规则工作流",
    "langgraph": "可选 LangGraph 编排",
    "langgraph_unavailable_fallback": "LangGraph 不可用，已回退规则工作流",
}
PLAYBOOK_DISPLAY_NAMES = {
    "data_profile": "数据概览与质量检查",
    "metric_trend": "指标趋势分析",
    "period_comparison": "周期对比分析",
    "dimension_contribution": "维度贡献分析",
    "experiment_comparison": "实验组与对照组比较",
    "causal_exploration": "轻量因果探索",
    "periodic_summary": "周期分析摘要",
    "semantic_metric_query": "语义指标查询",
    "funnel_analysis": "漏斗转化分析",
    "cohort_retention": "队列留存分析",
    "segment_drilldown": "分层下钻分析",
}
ROUTE_STEP_DISPLAY_NAMES = {
    "load_data_source": "加载数据来源",
    "validate_tables": "检查数据表",
    "infer_schema": "识别字段结构",
    "prepare_column_mapping": "准备字段映射",
    "resolve_metrics": "解析分析指标",
    "create_plan": "生成分析方案",
    "preview_analysis_plan": "预览分析方案",
    "recommend_playbooks": "推荐分析剧本",
    "select_playbook": "选择分析剧本",
    "validate_playbook": "检查分析剧本要求",
    "build_safe_query": "生成安全只读查询",
    "load_semantic_model": "加载语义模型",
    "build_relationship_graph": "构建多表关系图",
    "plan_joins": "规划多表连接",
    "compile_metric_query": "编译语义指标查询",
    "review_query_plan": "审查查询计划",
    "execute_playbook": "执行分析剧本",
    "execute_query_plan": "执行只读查询计划",
    "generate_charts": "生成可视化诊断",
    "build_analysis_results": "生成结构化分析结果",
    "check_data_contracts": "执行数据契约检查",
    "build_lineage": "生成数据血缘",
    "summarize_observability": "汇总运行性能",
    "build_manifest": "生成运行清单",
    "review": "执行分析质量检查",
    "generate_report": "生成分析报告",
    "generate_exports": "准备导出文件",
    "generic_analysis_fallback": "执行通用分析回退",
    "run_generic_trend": "计算通用指标趋势",
    "run_generic_anomaly": "检查通用指标异常",
    "run_generic_dimension_breakdown": "拆解通用分析维度",
    "run_generic_metric_summary": "汇总通用指标",
    "run_generic_experiment": "执行通用实验比较",
    "run_generic_causal_light": "执行轻量因果探索",
    "route_metric_diagnosis": "进入指标诊断流程",
    "route_growth_trend": "进入趋势分析流程",
    "route_experiment_analysis": "进入实验分析流程",
    "route_content_performance": "进入内容表现流程",
    "route_live_quality": "进入体验质量流程",
    "route_causal_exploration": "进入轻量因果流程",
    "route_periodic_report": "进入周期报告流程",
    "run_anomaly": "检测指标异常",
    "run_attribution": "拆解指标贡献",
    "run_experiment": "评估实验差异",
    "run_content_performance": "分析内容表现",
    "run_live_quality": "分析体验质量",
    "run_causal_light": "执行轻量因果探索",
    "run_growth_trend": "分析指标趋势",
    "run_periodic_report": "生成周期摘要",
}
REVIEWER_CHECK_DISPLAY_NAMES = {
    "has_goal_mode": "已记录分析目标模式",
    "has_plan": "已生成分析方案",
    "has_metrics": "已识别指标口径",
    "has_findings": "已生成核心发现",
    "has_route_taken": "已记录执行路径",
    "has_caveats": "已说明风险与限制",
    "has_reviewer_context": "审查上下文完整",
    "experiment_has_p_value_when_needed": "实验结果包含显著性与样本量",
    "causal_has_caveat_when_needed": "因果探索边界完整",
    "errors_are_reported": "错误已结构化记录",
    "no_overclaimed_causality": "未过度解释因果关系",
    "synthetic_data_disclaimer_present": "已声明模拟数据边界",
    "has_data_source": "已记录数据来源",
    "has_table_metadata": "已记录表结构摘要",
    "has_schema_validation": "已执行字段结构检查",
    "custom_data_limitations_reported": "已说明自定义数据限制",
    "unsafe_query_blocked": "已阻止不安全查询",
    "has_column_mapping_for_custom_data": "自定义数据字段映射完整",
    "mapping_warnings_reported": "字段映射警告已记录",
    "manual_mapping_respected": "已优先使用手动映射",
    "custom_data_has_metric_selection": "自定义数据已选择指标",
    "custom_data_has_date_selection_when_trend": "趋势分析已选择日期",
    "has_playbook_when_selected": "分析剧本执行结果完整",
    "playbook_requirements_satisfied": "分析剧本字段要求满足",
    "playbook_parameters_valid": "分析剧本参数有效",
    "safe_query_generated": "已生成安全查询",
    "chart_specs_valid": "可视化规格有效",
    "manifest_generated": "已生成运行清单",
    "mapping_matches_playbook": "字段映射匹配分析剧本",
    "result_tables_available": "已生成结构化结果表",
    "export_contains_no_raw_credentials": "导出不含明文凭据",
    "export_limitations_reported": "已说明导出与复现边界",
    "semantic_plan_valid": "语义查询计划完整",
    "join_risk_reviewed": "多表连接风险已审查",
    "contract_checks_available": "数据契约检查完整",
    "lineage_generated": "已生成数据血缘",
    "observability_generated": "已生成本地运行摘要",
}
DATA_SOURCE_DISPLAY_NAMES = {
    "synthetic": "内置模拟数据",
    "uploaded_files": "上传 CSV / Excel",
    "upload": "上传 CSV / Excel",
    "file": "上传 CSV / Excel",
    "database": "数据库只读查询",
    "mixed": "混合数据来源",
}
CHART_TYPE_DISPLAY_NAMES = {
    "metric_card": "指标卡片",
    "time_series": "时间趋势图",
    "line": "折线图",
    "bar": "柱状图",
    "grouped_bar": "分组柱状图",
    "contribution_bar": "贡献度柱状图",
    "histogram": "分布直方图",
    "box": "箱线图",
    "missingness_bar": "缺失率图",
    "confidence_interval": "置信区间图",
    "funnel": "漏斗图",
    "heatmap": "留存热图",
    "table": "结果表",
}
JOIN_RISK_DISPLAY_NAMES = {
    "safe": "安全",
    "warn": "需要注意",
    "require_approval": "需要人工审批",
    "forbidden": "禁止执行",
    "one_to_one": "一对一",
    "one_to_many": "一对多",
    "many_to_one": "多对一",
    "many_to_many": "多对多",
}
CONTRACT_STATUS_DISPLAY_NAMES = {
    "PASS": "通过",
    "WARN": "需要注意",
    "FAIL": "未通过",
    "info": "提示",
    "warning": "警告",
    "error": "错误",
}
STATUS_DISPLAY_NAMES = {
    "PASS": "通过",
    "WARN": "需要注意",
    "FAIL": "未通过",
    "pending": "等待审批",
    "approved": "已批准",
    "rejected": "已拒绝",
    "running": "运行中",
    "completed": "已完成",
}
METRIC_DISPLAY_NAMES = {
    "orders": "订单量",
    "order_count": "订单量",
    "revenue": "收入",
    "total_revenue": "总金额",
    "impressions": "曝光量",
    "clicks": "点击量",
    "visitors": "访问次数",
    "active_users": "活跃用户数",
    "ctr": "点击率",
    "conversion_rate": "转化率",
    "cvr": "转化率",
    "payment_success_rate": "支付成功率",
    "average_order_value": "客单价",
    "refund_rate": "退款率",
    "refund_orders": "退款订单量",
    "refund_amount": "退款金额",
    "add_to_cart_users": "加购用户数",
    "checkout_users": "结算用户数",
    "payment_attempts": "支付尝试量",
    "successful_payments": "支付成功量",
    "add_to_cart_rate": "加购率",
    "checkout_rate": "结算率",
    "completion_rate": "完播率",
    "starts": "播放开始量",
    "completions": "播放完成量",
    "likes": "点赞量",
    "comments": "评论量",
    "shares": "分享量",
    "follows": "关注量",
    "engagement_rate": "互动率",
    "buffering_rate": "卡顿率",
    "stutter_rate": "卡顿率",
    "crash_rate": "崩溃率",
    "latency_ms": "启动延迟",
    "startup_latency": "启动延迟",
    "watch_time": "观看时长",
    "interaction_rate": "互动率",
    "follow_rate": "关注率",
    "session_count": "会话数",
    "viewer_count": "观看用户数",
    "customer_count": "客户数",
    "paid_session_count": "支付完成会话数",
    "session_conversion_rate": "会话转化率",
    "revenue_minus_orders": "金额与订单量差值",
    "cumulative_revenue": "累计金额",
    "order_revenue": "订单金额合计",
    "order_count_measure": "订单数",
    "customer_count_measure": "客户数",
    "session_count_measure": "会话数",
    "paid_session_measure": "支付会话数",
    "item_revenue": "商品明细金额",
}


_CATEGORY_MAPS: dict[str, dict[str, str]] = {
    "goal_mode": GOAL_MODE_DISPLAY_NAMES,
    "intent": INTENT_DISPLAY_NAMES,
    "backend": BACKEND_DISPLAY_NAMES,
    "playbook": PLAYBOOK_DISPLAY_NAMES,
    "route_step": ROUTE_STEP_DISPLAY_NAMES,
    "reviewer_check": REVIEWER_CHECK_DISPLAY_NAMES,
    "data_source": DATA_SOURCE_DISPLAY_NAMES,
    "chart_type": CHART_TYPE_DISPLAY_NAMES,
    "join_risk": JOIN_RISK_DISPLAY_NAMES,
    "contract_status": CONTRACT_STATUS_DISPLAY_NAMES,
    "status": STATUS_DISPLAY_NAMES,
}


def format_enum_value(category: str, value: Any) -> str:
    text = str(value or "")
    return _CATEGORY_MAPS.get(category, {}).get(text, text or "未知")


def format_route_steps(route_taken: list[str]) -> list[str]:
    return [format_enum_value("route_step", item) for item in route_taken]


def format_reviewer_check_name(check_name: str) -> str:
    return format_enum_value("reviewer_check", check_name)


def format_status(status: str) -> str:
    return format_enum_value("status", status)


def format_value_with_id(category: str, value: Any, *, show_id: bool = False) -> str:
    display = format_enum_value(category, value)
    return f"{display}（{value}）" if show_id and display != str(value) else display


def format_metric_name(metric_id: Any, developer_mode: bool = False) -> str:
    stable_id = str(metric_id or "")
    display = METRIC_DISPLAY_NAMES.get(stable_id, stable_id or "未知指标")
    return f"{display}（{stable_id}）" if developer_mode and stable_id and display != stable_id else display


def format_metric_text(value: Any, developer_mode: bool = False) -> str:
    """Replace stable metric identifiers in user-facing prose."""

    text = str(value or "")
    if developer_mode:
        return text
    for metric_id in sorted(METRIC_DISPLAY_NAMES, key=len, reverse=True):
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(metric_id)}(?![A-Za-z0-9_])",
            METRIC_DISPLAY_NAMES[metric_id],
            text,
        )
    return text
