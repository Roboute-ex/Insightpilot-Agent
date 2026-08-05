"""Pure presenter functions that convert stable schemas into Chinese view models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from insightpilot.ui.formatters import (
    GOAL_MODE_DISPLAY_NAMES,
    JOIN_RISK_DISPLAY_NAMES,
    format_enum_value,
    format_route_steps,
    format_status,
    METRIC_DISPLAY_NAMES,
)


COMPARISON_DISPLAY_NAMES = {
    "experiment_control_vs_treatment": "实验组与对照组比较",
    "current_day_vs_previous_7d_average": "当前值与前 7 日均值比较",
    "recent_period_profile": "近期周期描述性分析",
    "current_period_vs_previous_period": "当前周期与上一周期比较",
    "yesterday_vs_previous_7d_average": "昨日与前 7 日均值比较",
    "exploratory_adjusted_effect": "原始差异与轻量调整结果对照",
    "descriptive_summary": "描述性汇总",
}
DIMENSION_DISPLAY_NAMES = {
    "city": "城市",
    "channel": "渠道",
    "user_segment": "用户分层",
    "device": "设备",
    "merchant_type": "类型",
    "content_category": "内容分类",
    "network_type": "网络类型",
    "hour_bucket": "时段",
    "customer_city": "城市",
    "customer_segment": "客户分层",
    "channel_name": "渠道",
    "product_category": "商品分类",
    "order_date": "订单日期",
    "session_date": "会话日期",
}
@dataclass(frozen=True)
class AnalysisPlanView:
    goal_name: str
    intent_name: str
    goal_source_text: str
    metric_names: list[str]
    comparison_method_text: str
    dimension_names: list[str]
    required_table_names: list[str]
    step_descriptions: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticModelView:
    model_name: str
    version_text: str
    entity_count: int
    dimension_count: int
    measure_count: int
    metric_count: int
    relationship_count: int
    entity_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricRequestView:
    metric_names: list[str]
    dimension_names: list[str]
    date_range_text: str
    time_grain_text: str
    execution_mode_text: str
    filter_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JoinPlanView:
    table_count: int
    step_count: int
    risk_text: str
    requires_approval_text: str
    executable_text: str
    output_grain: str
    step_rows: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueryPlanView:
    plan_id: str
    metric_names: list[str]
    dimension_names: list[str]
    date_range_text: str
    time_grain_text: str
    table_names: list[str]
    risk_text: str
    executable_text: str
    output_grain: str
    metric_dependencies: list[str]
    filter_summary: str
    parameter_count: int
    sql_preview: str
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanReviewView:
    plan_id: str
    decision_text: str
    reason: str
    approved_for_execution_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _display_many(values: Any, mapping: dict[str, str]) -> list[str]:
    if not isinstance(values, list):
        values = [values] if values else []
    return [mapping.get(str(value), str(value)) for value in values]


def present_analysis_plan(plan: dict[str, Any]) -> AnalysisPlanView:
    values = plan if isinstance(plan, dict) else {}
    source = str(values.get("goal_mode_source") or "auto_detected")
    warnings = [str(item) for item in values.get("warnings", [])] if isinstance(values.get("warnings"), list) else []
    return AnalysisPlanView(
        goal_name=GOAL_MODE_DISPLAY_NAMES.get(str(values.get("goal_mode", "auto")), str(values.get("goal_mode_display_name") or "自动识别")),
        intent_name=format_enum_value("intent", values.get("intent", "general_summary")),
        goal_source_text="用户手动选择" if source == "user_selected" else "根据问题自动识别",
        metric_names=_display_many(values.get("related_metrics", []), METRIC_DISPLAY_NAMES) or ["待识别"],
        comparison_method_text=COMPARISON_DISPLAY_NAMES.get(str(values.get("comparison_method", "")), str(values.get("comparison_method") or "描述性汇总")),
        dimension_names=_display_many(values.get("dimensions", []), DIMENSION_DISPLAY_NAMES) or ["整体"],
        required_table_names=[str(item) for item in values.get("required_tables", [])],
        step_descriptions=[str(item) for item in values.get("analysis_steps", [])],
        warnings=warnings,
    )


def present_semantic_model(model: dict[str, Any]) -> SemanticModelView:
    values = model if isinstance(model, dict) else {}
    entities = values.get("entities", {}) if isinstance(values.get("entities"), dict) else {}
    rows = []
    for entity_id, entity in entities.items():
        item = entity if isinstance(entity, dict) else {}
        rows.append(
            {
                "实体": item.get("display_name") or entity_id,
                "数据表": item.get("table_name") or entity_id,
                "主键": item.get("primary_key") or "-",
                "粒度": item.get("grain") or "-",
            }
        )
    return SemanticModelView(
        model_name=str(values.get("display_name") or values.get("model_id") or "未选择"),
        version_text=str(values.get("version") or "-"),
        entity_count=len(entities),
        dimension_count=len(values.get("dimensions", {})) if isinstance(values.get("dimensions"), dict) else int(values.get("dimension_count", 0) or 0),
        measure_count=len(values.get("measures", {})) if isinstance(values.get("measures"), dict) else int(values.get("measure_count", 0) or 0),
        metric_count=len(values.get("metrics", {})) if isinstance(values.get("metrics"), dict) else int(values.get("metric_count", 0) or 0),
        relationship_count=len(values.get("relationships", [])) if isinstance(values.get("relationships"), list) else int(values.get("relationship_count", 0) or 0),
        entity_rows=rows,
    )


def present_metric_request(request: dict[str, Any]) -> MetricRequestView:
    values = request if isinstance(request, dict) else {}
    date_from = values.get("date_from") or "不限"
    date_to = values.get("date_to") or "不限"
    grain = {"day": "按日", "week": "按周", "month": "按月"}.get(str(values.get("time_grain")), str(values.get("time_grain") or "按日"))
    mode = "仅预览方案" if values.get("execution_mode") == "plan_only" else "执行分析"
    return MetricRequestView(
        metric_names=_display_many(values.get("metrics", []), METRIC_DISPLAY_NAMES),
        dimension_names=_display_many(values.get("dimensions", []), DIMENSION_DISPLAY_NAMES),
        date_range_text=f"{date_from} 至 {date_to}",
        time_grain_text=grain,
        execution_mode_text=mode,
        filter_count=len(values.get("filters", [])) if isinstance(values.get("filters"), list) else 0,
    )


def present_join_plan(plan: dict[str, Any]) -> JoinPlanView:
    values = plan if isinstance(plan, dict) else {}
    steps = values.get("steps", []) if isinstance(values.get("steps"), list) else []
    rows: list[dict[str, Any]] = []
    table_names: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        table_names.update([str(step.get("source_table", "")), str(step.get("target_table", ""))])
        rows.append(
            {
                "起始表": step.get("source_table"),
                "目标表": step.get("target_table"),
                "连接字段": f"{step.get('source_column')} = {step.get('target_column')}",
                "关系类型": JOIN_RISK_DISPLAY_NAMES.get(str(step.get("cardinality")), str(step.get("cardinality"))),
                "风险": JOIN_RISK_DISPLAY_NAMES.get(str(step.get("risk_level")), str(step.get("risk_level"))),
            }
        )
    if values.get("base_entity") and not table_names:
        table_names.add(str(values.get("base_entity")))
    return JoinPlanView(
        table_count=len([item for item in table_names if item]),
        step_count=len(rows),
        risk_text=JOIN_RISK_DISPLAY_NAMES.get(str(values.get("risk_level", "safe")), str(values.get("risk_level", "safe"))),
        requires_approval_text="需要" if values.get("requires_approval") else "不需要",
        executable_text="可以执行" if values.get("executable", False) else "暂停执行",
        output_grain=str(values.get("output_grain") or "未声明"),
        step_rows=rows,
        warnings=[str(item) for item in values.get("warnings", [])],
        errors=[str(item) for item in values.get("errors", [])],
    )


def present_query_plan(plan: dict[str, Any]) -> QueryPlanView:
    values = plan if isinstance(plan, dict) else {}
    request = values.get("request", {}) if isinstance(values.get("request"), dict) else {}
    request_view = present_metric_request(request)
    join_plan = values.get("join_plan", {}) if isinstance(values.get("join_plan"), dict) else {}
    dependencies = values.get("metric_dependencies", {}) if isinstance(values.get("metric_dependencies"), dict) else {}
    required = [str(item) for item in values.get("required_entities", [])]
    return QueryPlanView(
        plan_id=str(values.get("plan_id") or "-"),
        metric_names=request_view.metric_names,
        dimension_names=request_view.dimension_names,
        date_range_text=request_view.date_range_text,
        time_grain_text=request_view.time_grain_text,
        table_names=required,
        risk_text=JOIN_RISK_DISPLAY_NAMES.get(str(values.get("risk_level", "safe")), str(values.get("risk_level", "safe"))),
        executable_text="可以执行" if values.get("executable", False) else "暂停执行",
        output_grain=str(join_plan.get("output_grain") or "未声明"),
        metric_dependencies=[f"{METRIC_DISPLAY_NAMES.get(str(key), key)}：{', '.join(_display_many(value, METRIC_DISPLAY_NAMES)) or '基础度量'}" for key, value in dependencies.items()],
        filter_summary=f"{request_view.filter_count} 个筛选条件",
        parameter_count=int(values.get("parameter_count", len(values.get("parameters", []))) or 0),
        sql_preview=str(values.get("sql_template") or ""),
        warnings=[str(item) for item in values.get("warnings", [])],
        errors=[str(item) for item in values.get("errors", [])],
    )


def present_plan_review(review: dict[str, Any]) -> PlanReviewView:
    values = review if isinstance(review, dict) else {}
    return PlanReviewView(
        plan_id=str(values.get("plan_id") or "-"),
        decision_text=format_status(str(values.get("decision") or "pending")),
        reason=str(values.get("reason") or "等待计划审查。"),
        approved_for_execution_text="已授权只读执行" if values.get("approved_for_read_only_execution") else "尚未授权执行",
    )


_CAVEAT_TRANSLATIONS = {
    "synthetic data": "当前结果仅基于内置模拟数据，不代表真实业务结论。",
    "correlation": "相关性不能直接解释为因果关系。",
    "missing date_column": "缺少日期字段，无法执行时间趋势分析。",
    "missing metric": "缺少数值指标字段，分析能力已降级。",
    "fanout": "多表连接存在行扩展风险，请复核指标粒度。",
    "many-to-many": "多对多连接默认禁止执行。",
    "many_to_many": "多对多连接默认禁止执行。",
    "langgraph": "可选编排后端不可用，已回退到确定性规则工作流。",
}


def translate_caveat(message: Any, context: dict[str, Any] | None = None) -> str:
    del context
    if hasattr(message, "message_zh"):
        return str(message.message_zh)
    if isinstance(message, dict):
        if message.get("message_zh"):
            return str(message["message_zh"])
        message = str(message.get("message_en") or message.get("code") or "未提供限制说明。")
    text = str(message)
    lowered = text.lower()
    for marker, translated in _CAVEAT_TRANSLATIONS.items():
        if marker in lowered:
            return translated
    return text


def present_route_timeline(route_taken: list[str], *, compact: bool = False, show_ids: bool = False) -> list[dict[str, Any]]:
    if not compact:
        labels = format_route_steps(route_taken)
        return [
            {"step": index, "name": label, "step_id": route_taken[index - 1] if show_ids else None}
            for index, label in enumerate(labels, start=1)
        ]
    groups = [
        ("数据准备", {"load_data_source", "validate_tables", "infer_schema", "prepare_column_mapping"}),
        ("指标与字段识别", {"resolve_metrics"}),
        ("分析方案生成", {"create_plan", "preview_analysis_plan", "recommend_playbooks", "select_playbook", "validate_playbook", "load_semantic_model", "build_relationship_graph", "plan_joins", "compile_metric_query", "review_query_plan"}),
        ("分析计算", {"build_safe_query", "execute_playbook", "execute_query_plan", "generate_charts", "build_analysis_results", "run_anomaly", "run_attribution", "run_experiment", "run_growth_trend"}),
        ("质量检查", {"check_data_contracts", "build_lineage", "summarize_observability", "review"}),
        ("报告输出", {"build_manifest", "generate_report", "generate_exports"}),
    ]
    present = set(route_taken)
    rows = []
    for label, members in groups:
        matched = [item for item in route_taken if item in members]
        if matched:
            rows.append({"step": len(rows) + 1, "name": label, "step_ids": matched if show_ids else None})
    return rows
