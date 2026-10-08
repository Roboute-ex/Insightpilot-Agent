"""Deterministic rule-based analysis planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from insightpilot.metrics.resolver import resolve_metrics_from_question
from insightpilot.planning.goal_modes import (
    get_goal_mode_display_name,
    infer_goal_mode_from_intent,
    infer_intent_from_goal_mode,
    normalize_goal_mode,
)


UNRESOLVED_METRIC_STEP = "未从问题唯一识别指标；请指定指标或配置字段映射，预检通过后方可执行。"

@dataclass(frozen=True)
class AnalysisPlan:
    intent: str
    goal_mode: str
    goal_mode_display_name: str
    goal_mode_source: str
    related_metrics: list[str]
    comparison_method: str
    dimensions: list[str]
    required_tables: list[str]
    analysis_steps: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _detect_intent(question: str) -> str:
    from insightpilot.planning.analysis_advisor import affirmative_question
    q = affirmative_question(question)
    if "控制" in q and ("后" in q or "调整" in q) and any(term in q for term in ("关联", "效应", "策略")):
        return "causal_exploration"
    if any(term in q for term in ("因果", "causal", "影响是否", "是否影响")):
        return "causal_exploration"
    if any(term in q for term in ("实验", "a/b", "策略", "treatment", "control")) or re.search(r"\bab\b", q):
        return "experiment_analysis"
    if any(term in q for term in ("趋势", "走势", "随日期", "每日", "持续增加")) or ("最近" in q and "下降" in q):
        return "metric_growth_analysis"
    if any(term in q for term in ("摘要", "汇总", "缺失", "数据质量")):
        return "general_summary"
    if any(term in q for term in ("直播", "卡顿", "stutter", "停留", "体验", "崩溃", "启动延迟")):
        return "live_quality_analysis"
    if any(term in q for term in ("内容", "完播", "推荐", "消费", "content")):
        return "content_performance_analysis"
    if any(term in q for term in ("下降", "下滑", "降低", "减少", "drop", "decline", "异常")):
        return "metric_drop_diagnosis"
    if any(term in q for term in ("增长", "提升", "上升", "increase", "growth")):
        return "metric_growth_analysis"
    return "general_summary"


def _plan_parts(intent: str) -> tuple[str, list[str], list[str], list[str]]:
    if intent == "experiment_analysis":
        return (
            "experiment_control_vs_treatment",
            ["user_segment", "city", "channel"],
            ["experiments", "content_events", "users"],
            [
                "识别实验指标和分组字段。",
                "计算对照组与实验组均值或比例。",
                "执行显著性检验并输出 p-value 与区间估计。",
                "检查样本量并给出谨慎结论。",
            ],
        )
    if intent == "live_quality_analysis":
        return (
            "current_day_vs_previous_7d_average",
            ["device", "network_type", "city", "hour_bucket"],
            ["live_sessions", "live_quality_logs", "live_interactions"],
            [
                "检测卡顿率、观看时长和互动率变化。",
                "按设备、网络类型、地区和时段做贡献度排序。",
                "结合体验指标生成风险提示。",
                "保留 synthetic data 与相关性限制说明。",
            ],
        )
    if intent == "content_performance_analysis":
        return (
            "recent_period_profile",
            ["content_category", "device", "user_segment"],
            ["content_items", "content_events", "experiments"],
            [
                "汇总内容类型的消费表现。",
                "比较完播率、观看时长和留存相关指标。",
                "识别表现差异较大的内容分层。",
                "给出继续观察和优化建议。",
            ],
        )
    if intent == "metric_growth_analysis":
        return (
            "current_period_vs_previous_period",
            ["city", "channel", "user_segment", "device"],
            ["daily_metrics"],
            [
                "计算目标指标当前周期与上一周期差异。",
                "按核心维度拆解增长来源。",
                "检查是否存在结构性变化。",
                "输出可复核的下一步分析建议。",
            ],
        )
    if intent == "metric_drop_diagnosis":
        return (
            "yesterday_vs_previous_7d_average",
            ["city", "channel", "user_segment", "device", "merchant_type"],
            ["daily_metrics", "traffic_events", "orders"],
            [
                "检测目标日期相对前 7 日均值的异常程度。",
                "拆解曝光、点击率、转化率和支付成功率变化。",
                "按城市、渠道、用户分层、设备和商户类型排序贡献度。",
                "生成可执行建议并标注限制说明。",
            ],
        )
    if intent == "causal_exploration":
        return (
            "exploratory_adjusted_effect",
            ["city", "channel", "user_segment"],
            ["experiments", "users"],
            [
                "识别 treatment、outcome 和可用控制变量。",
                "计算未经调整均值差；有有效控制变量时执行回归调整。",
                "倾向评分加权默认关闭，当前剧本不执行该可选方法。",
                "明确该模式仅用于探索，不能把相关性直接解释为因果关系。",
            ],
        )
    return (
        "descriptive_summary",
        ["city", "channel", "user_segment"],
        ["daily_metrics"],
        [
            "识别问题中的指标口径。",
            "生成基础描述性汇总。",
            "列出建议优先查看的维度。",
            "保留不确定性与 synthetic data 限制说明。",
        ],
    )


def create_analysis_plan(question: str, goal_mode: str = "auto") -> AnalysisPlan:
    """Create a stable structured analysis plan from a natural-language question."""

    normalized_goal_mode = normalize_goal_mode(goal_mode)
    if normalized_goal_mode == "auto":
        intent = _detect_intent(question)
        resolved_goal_mode = infer_goal_mode_from_intent(intent)
        goal_mode_source = "auto_detected"
    else:
        intent = infer_intent_from_goal_mode(normalized_goal_mode)
        resolved_goal_mode = normalized_goal_mode
        goal_mode_source = "user_selected"

    metrics = [metric.metric_name for metric in resolve_metrics_from_question(question)]
    comparison_method, dimensions, required_tables, steps = _plan_parts(intent)
    if not metrics:
        steps = [UNRESOLVED_METRIC_STEP, *steps]
    return AnalysisPlan(
        intent=intent,
        goal_mode=resolved_goal_mode,
        goal_mode_display_name=get_goal_mode_display_name(resolved_goal_mode),
        goal_mode_source=goal_mode_source,
        related_metrics=metrics,
        comparison_method=comparison_method,
        dimensions=dimensions,
        required_tables=required_tables,
        analysis_steps=steps,
    )


@dataclass(frozen=True)
class ClarificationItem:
    role: str
    question: str
    candidates: list[dict[str, object]]
    reason: str
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _prepare_metric_request(
    question: str, *, table_metadata: dict[str, dict[str, object]], goal_mode: str = "auto",
    playbook_id: str | None = None, column_mapping: dict[str, object] | None = None,
    playbook_parameters: dict[str, object] | None = None, metric_request: dict[str, object] | None = None,
    semantic_model_id: str = "commerce_demo", clarification_answers: dict[str, object] | None = None,
) -> dict[str, object]:
    """Resolve definitions from compact schema only; never scan, hash or query data.

    Answers are request-local explicit choices. Imported definition status is not
    consulted. The caller must only supply answers after an explicit user action.
    """
    from copy import deepcopy
    from insightpilot.metrics.definitions import column_metric_card, semantic_metric_card, stable_fingerprint
    from insightpilot.metrics.dictionary import get_metric_dictionary
    from insightpilot.metrics.aggregation import metric_components
    from insightpilot.ingestion.mapping import ColumnMapping, normalize_column_mapping
    mapping = deepcopy(column_mapping.to_dict() if isinstance(column_mapping, ColumnMapping) else column_mapping or {})
    if mapping.get("source") == "automatic_suggestion":
        # A cleared outcome is a blocking constraint, not a confirmed metric.
        # Preserve it while discarding all unconfirmed positive suggestions.
        mapping = {"outcome_column": None, "source": "automatic_suggestion"} if "outcome_column" in mapping and mapping["outcome_column"] in (None, "") else {}
        column_mapping = mapping or None
    elif mapping:
        # A mapping explicitly supplied to this API is a user choice unless its
        # caller labels it an automatic suggestion. All entrances share this
        # default before constructing metric cards and computation identities.
        mapping.setdefault("source", "user_selected")
    # Keep malformed original intent visible, even if a previous normalizer removed it.
    original = mapping.get("original_request") or mapping
    parameters = deepcopy(playbook_parameters or {})
    request = deepcopy(metric_request or {})
    answers = deepcopy(clarification_answers or {})
    items: list[ClarificationItem] = []
    errors: list[str] = []
    unsupported: list[str] = []
    cards: list[dict[str, object]] = []
    metadata = {str(name): meta for name, meta in table_metadata.items() if isinstance(meta, dict)}
    from insightpilot.planning.goal_modes import GOAL_MODE_DISPLAY_NAMES
    if goal_mode not in GOAL_MODE_DISPLAY_NAMES:
        errors.append(f"不支持的分析目标：{goal_mode}")
    plan = create_analysis_plan(question, goal_mode=goal_mode)
    experiment = playbook_id == "experiment_comparison" or (not playbook_id and plan.intent == "experiment_analysis")
    explicit_metric = bool(mapping.get("metric_columns") or parameters.get("metric"))
    allowed_answers = {"metric", "metric_id", "table_name", "date_column", "date_range", "group_column", "control_value", "treatment_value", "statistical_unit", "aggregation", "goal_mode", "retention_definition"}
    if set(answers) - allowed_answers:
        errors.append("不支持的澄清字段：" + ", ".join(sorted(set(answers) - allowed_answers)))
    if "goal_mode" in answers:
        goal_mode = str(answers["goal_mode"])
        if goal_mode not in GOAL_MODE_DISPLAY_NAMES:
            errors.append(f"不支持的分析目标：{goal_mode}")
        plan = create_analysis_plan(question, goal_mode=goal_mode)
    for key in ("table_name", "date_column", "group_column", "statistical_unit", "aggregation"):
        if key in answers:
            mapping[key] = answers[key]
    for key in ("control_value", "treatment_value", "date_range"):
        if key in answers:
            parameters[key] = answers[key]
    selected_answer = answers.get("metric", answers.get("metric_id"))
    if selected_answer:
        mapping["source"] = "user_selected"
        selected_answer = str(selected_answer)
        if ":" in selected_answer:
            mapping["table_name"], selected_answer = selected_answer.split(":", 1)
        mapping["metric_columns"] = [selected_answer]
        if playbook_id in {"dimension_contribution", "experiment_comparison", "semantic_metric_query"}:
            parameters["metric"] = selected_answer
        explicit_metric = True
        if selected_answer in {"user_id", "customer_id", "participant_id"} and any(term in question.lower() for term in ("用户", "人数", "uv")):
            mapping.update(aggregation="count_distinct", deduplication_key=selected_answer, unit="人")
    # Raw invalid mapping is not silently normalized into a different analysis.
    table_name = str(mapping.get("table_name") or parameters.get("table_name") or "")
    if table_name and table_name not in metadata:
        errors.append(f"指定指标表不存在：{table_name}")
    semantic = playbook_id == "semantic_metric_query"
    known_playbooks = {"data_profile", "metric_trend", "period_comparison", "dimension_contribution", "experiment_comparison", "causal_exploration", "periodic_summary", "semantic_metric_query", "funnel_analysis", "cohort_retention", "auto", "auto_recommended"}
    if playbook_id and playbook_id not in known_playbooks:
        unsupported.append(f"不支持的分析剧本：{playbook_id}")
    if not metadata:
        errors.append("没有可用表，请先加载数据。")
    if semantic:
        from insightpilot.semantic.catalog import load_builtin_catalog
        from insightpilot.semantic.query import MetricRequest
        try:
            model = load_builtin_catalog().get(semantic_model_id)
            if not request:
                request = {key: parameters[key] for key in ("metrics", "dimensions", "filters", "date_dimension", "date_from", "date_to", "time_grain", "limit", "sort") if key in parameters}
            if not request.get("metrics") and parameters.get("metric"):
                request["metrics"] = [parameters["metric"]]
            if selected_answer:
                request["metrics"] = [str(selected_answer)]
            if not request.get("metrics"):
                items.append(ClarificationItem("metric", "请选择已注册的语义指标。", [{"value": key, "label": metric.display_name} for key, metric in model.metrics.items()], "未指定 MetricRequest.metrics。"))
            else:
                MetricRequest.from_dict(request)
                unknown = set(request["metrics"]) - set(model.metrics)
                if unknown:
                    errors.append("未注册语义指标：" + ", ".join(sorted(unknown)))
                else:
                    cards = [semantic_metric_card(model, name, request) for name in request["metrics"]]
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    else:
        columns_by_table = {name: list(meta.get("columns", [])) for name, meta in metadata.items()}
        metrics = list(mapping.get("metric_columns") or ([parameters["metric"]] if parameters.get("metric") else [mapping["outcome_column"]] if mapping.get("outcome_column") else []))
        if not table_name:
            # Actual generator metadata declares its prevalidated table contract;
            # a caller passing data_source_type='synthetic' alone gets no exemption.
            preferred = "experiments" if experiment or plan.intent == "causal_exploration" else "live_sessions" if plan.intent == "live_quality_analysis" else "content_events" if plan.intent == "content_performance_analysis" else "daily_metrics"
            if preferred == "content_events" and "content_daily_metrics" in metadata:
                preferred = "content_daily_metrics"
            elif preferred == "live_sessions" and "live_daily_metrics" in metadata:
                preferred = "live_daily_metrics"
            if preferred in metadata and metadata[preferred].get("builtin_scenario"):
                table_name = preferred
            else:
                candidates = [name for name, columns in columns_by_table.items() if not metrics or all(metric in columns or metric_components(metric, columns) for metric in metrics)]
                if len(candidates) == 1:
                    table_name = candidates[0]
                elif playbook_id not in {"data_profile", "funnel_analysis", "cohort_retention"}:
                    items.append(ClarificationItem("table_name", "本次分析使用哪张指标表？", [{"value": name, "label": name} for name in candidates], "多张表可用于分析，不能默认选择第一张或直接连接。"))
        columns = columns_by_table.get(table_name, [])
        meta = metadata.get(table_name, {})
        builtin = bool(meta.get("builtin_scenario"))
        if table_name:
            mapping["table_name"] = table_name
            for role in ("date_column", "group_column", "treatment_column", "outcome_column", "statistical_unit", "deduplication_key"):
                value = mapping.get(role)
                if value and value != "row" and value not in columns:
                    errors.append(f"{role} 指定的列不存在：{value}")
            for role in ("metric_columns", "dimension_columns", "covariates"):
                values = mapping.get(role) or []
                if isinstance(values, str):
                    values = [values]
                    mapping[role] = values
                for value in values:
                    if value not in columns and not (role == "metric_columns" and metric_components(value, columns)):
                        errors.append(f"{role} 指定的列不存在：{value}")
            if not answers and isinstance(original, dict):
                for role in ("date_column", "group_column", "treatment_column", "outcome_column", "numerator_column", "denominator_column", "deduplication_key"):
                    value = original.get(role)
                    if value and value not in columns:
                        errors.append(f"原映射 {role} 不存在：{value}")
                for role in ("metric_columns", "dimension_columns", "covariates"):
                    for value in original.get(role, []) or []:
                        if value not in columns and not (role == "metric_columns" and metric_components(value, columns)):
                            errors.append(f"原映射 {role} 不存在：{value}")
            if mapping.get("aggregation", "sum") not in ({"sum", "mean", "count", "count_distinct", "min", "max", "ratio_of_sums"} if parameters.get("exploration_request") else {"sum", "mean", "count", "count_distinct", "min", "max"}):
                errors.append("aggregation 必须为 sum/mean/count/count_distinct/min/max。")
            if mapping.get("time_grain", "day") not in {"day", "week", "month"}:
                unsupported.append("单表时间粒度仅支持 day/week/month。")
        q = question.lower()
        if any(term in q for term in ("确认收入", "收入确认", "净收入", "扣退款")) and not explicit_metric and not any(name in columns for name in ("net_revenue", "net_income", "recognized_revenue", "净收入", "确认收入")):
            unsupported.append("当前已注册收入是支付金额；未注册扣退款净收入或会计确认收入，请提供明确指标列及口径映射。")
        ambiguous = None
        candidates = []
        dictionary = get_metric_dictionary()
        if not explicit_metric and "转化" in q and not any(term in q for term in ("支付成功", "访问到", "访问至", "下单转化")):
            ambiguous = ("metric", "请选择本次转化率的分子和分母。", "不同转化环节会得到不同答案，不能替用户默认选择。")
            ids = ("cvr", "ctr", "payment_success_rate", "conversion_rate")
        elif not explicit_metric and "收入" in q:
            ambiguous = ("metric", "本次收入采用什么口径？", "支付金额、扣退款净收入与确认收入不能同名混算。")
            ids = ("revenue", "gross_revenue", "net_revenue", "net_income", "recognized_revenue", "支付金额", "净收入", "确认收入")
        elif not explicit_metric and any(term in q for term in ("用户数", "人数", "uv")):
            ambiguous = ("metric", "需要统计行数、会话数还是去重用户？", "行数和会话数不等于去重人数。")
            ids = ("user_id", "customer_id", "sessions", "visitors")
        elif not explicit_metric and "留存" in q and playbook_id != "cohort_retention":
            ambiguous = ("retention_definition", "请选择留存对象和观察窗口。", "新用户留存、活跃回访及 D1/D7 不是同一指标。")
            ids = ("retention_rate",)
        else:
            ids = ()
        for candidate_table, candidate_columns in columns_by_table.items():
            if table_name and candidate_table != table_name:
                continue
            for metric in ids:
                if metric in candidate_columns:
                    pair = metric_components(metric, candidate_columns)
                    label = dictionary[metric].display_name if metric in dictionary else metric
                    if pair:
                        label += f"：{pair[0]} / {pair[1]}"
                    elif metric in {"user_id", "customer_id"}:
                        label += "：按此字段去重统计人数"
                    elif metric == "revenue":
                        label += "：已注册支付金额，未扣退款"
                    candidates.append({"value": f"{candidate_table}:{metric}", "label": label, "metric_id": metric, "table_name": candidate_table})
        if ambiguous and not selected_answer and not (builtin and (playbook_id or goal_mode != "auto")):
            role, prompt, reason = ambiguous
            items.append(ClarificationItem(role, prompt, candidates, reason))
        if any(term in q for term in ("d1", "d7", "次日留存", "七日留存", "活跃回访")) and playbook_id != "cohort_retention" and not explicit_metric:
            unsupported.append("当前未为该输入注册指定对象和 D1/D7 观察资格定义，不能用周队列或简单均值替代。")
        if answers.get("retention_definition"):
            unsupported.append("留存对象与窗口需要现有 cohort_retention 配置或明确预计算指标映射；自由文本定义不会自动执行。")
        if not mapping.get("date_column") and table_name:
            date_candidates = list(meta.get("schema_mapping", {}).get("detected_date_columns", []))
            if builtin and "date" in columns:
                mapping["date_column"] = "date"
            elif len(date_candidates) == 1:
                mapping["date_column"] = date_candidates[0]
            elif len(date_candidates) > 1 and playbook_id != "data_profile":
                items.append(ClarificationItem("date_column", "本次使用哪个日期字段？", [{"value": name, "label": name} for name in date_candidates], "下单、支付和退款日期不应混用。"))
        if re.search(r"本周|上周|本月|上月|最近[0-9]+天|近[0-9]+天", q) and not parameters.get("date_range") and not parameters.get("current_start") and not explicit_metric:
            items.append(ClarificationItem("date_range", "请明确本次起止日期（含边界）。", [], "离线数据日期不一定等于电脑当前日期，不推测未提供的观察窗口。"))
        if parameters.get("date_range"):
            value = parameters["date_range"]
            # Existing playbook widgets use {start, end}; explicit clarification
            # uses a pair. Both describe the same inclusive window and cache key.
            if isinstance(value, dict) and set(value) == {"start", "end"}:
                value = [value["start"], value["end"]]
                parameters["date_range"] = value
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                errors.append("date_range 需要两个 ISO 日期。")
            else:
                from datetime import date
                try:
                    if date.fromisoformat(str(value[0])) > date.fromisoformat(str(value[1])):
                        raise ValueError("开始日期不能晚于结束日期")
                except ValueError as exc:
                    errors.append("date_range 无效：" + str(exc))
        if not metrics and builtin:
            metrics = [metric.metric_name for metric in resolve_metrics_from_question(question) if metric.metric_name in columns or metric_components(metric.metric_name, columns)]
            if not metrics and goal_mode != "auto":
                defaults = {"live_quality_analysis": ["stutter_rate", "watch_time", "interaction_rate"], "causal_exploration": ["completion_rate"], "content_performance_analysis": ["completion_rate", "watch_time"], "general_summary": ["orders"]}
                metrics = [name for name in defaults.get(plan.intent, []) if name in columns]
            if experiment and "completion_rate" in columns:
                metrics = ["completion_rate"]
        if not metrics and not builtin and not experiment and goal_mode != "auto" and not items and not unsupported:
            numeric = list(meta.get("schema_mapping", {}).get("possible_metric_columns", []))
            if len(numeric) == 1:
                metrics = numeric
                mapping["metric_columns"] = metrics
                mapping["source"] = "automatic_suggestion"
        if selected_answer:
            metrics = [str(selected_answer)]
        if not metrics and not semantic and playbook_id not in {"data_profile", "funnel_analysis", "cohort_retention"} and not items and not unsupported and not errors:
            numeric = list(meta.get("schema_mapping", {}).get("possible_metric_columns", []))
            items.append(ClarificationItem("metric", "请选择支持的指标和分析目标。", [{"value": f"{table_name}:{name}", "label": name} for name in numeric], "规则规划器无法从当前问题唯一确定实际指标，不自动降级为数据概览。"))
        if experiment and table_name:
            if builtin:
                if not mapping.get("group_column"):
                    mapping["group_column"] = "group" if "group" in columns else None
                if not mapping.get("statistical_unit"):
                    mapping["statistical_unit"] = "user_id" if "user_id" in columns else None
                parameters.setdefault("control_value", "control")
                parameters.setdefault("treatment_value", "treatment")
                parameters.setdefault("metric_type", "mean")
            roles = (("group_column", mapping.get("group_column"), "请选择实验分组字段。"), ("control_value", parameters.get("control_value"), "请明确对照组的值。"), ("treatment_value", parameters.get("treatment_value"), "请明确实验组的值。"), ("statistical_unit", parameters.get("statistical_unit") or mapping.get("statistical_unit"), "请选择独立统计单位；只有每行确为独立单位时选择 row。"))
            for role, value, prompt in roles:
                if value is None or value == "":
                    options = [{"value": name, "label": name} for name in columns if (role == "group_column" or name.endswith("_id"))] if role in {"group_column", "statistical_unit"} else []
                    if role == "statistical_unit":
                        options.append({"value": "row", "label": "每行是一个独立实验单位（需明确确认）"})
                    items.append(ClarificationItem(role, prompt, options, "实验方向和独立单位改变样本量、估计和置信区间，不能自动假定。"))
            if parameters.get("control_value") is not None and parameters.get("control_value") == parameters.get("treatment_value"):
                errors.append("对照值和实验值不能相同。")
            if parameters.get("statistical_unit") and parameters["statistical_unit"] != "row" and parameters["statistical_unit"] not in columns:
                errors.append("指定的统计单位列不存在。")
            if parameters.get("statistical_unit"):
                mapping["statistical_unit"] = parameters["statistical_unit"]
        # Preserve unmapped legacy built-in routing; only apply a newly normalized
        # mapping when the caller selected fields or answered a clarification.
        if explicit_metric or answers:
            mapping["metric_columns"] = metrics
            mapping.setdefault("aggregation", "sum")
        card_mapping = dict(mapping)
        if not explicit_metric and builtin:
            card_mapping.pop("aggregation", None)
        for metric in metrics:
            source_table, source_meta = table_name, meta
            if metric == "active_users" and "user_id" not in columns:
                detail = metadata.get("transaction_detail", {})
                if builtin and {"date", "user_id"}.issubset(detail.get("columns", [])) and not playbook_id:
                    source_table, source_meta = "transaction_detail", detail
                else:
                    unsupported.append("缺少该口径所需的用户标识明细；不能把分组用户数求和或对其数值去重当作全站人数。")
            card = column_metric_card(metric, table_name=source_table, metadata=source_meta, mapping=card_mapping, parameters=parameters, experiment=experiment, confirmed=bool(answers))
            if source_table == "transaction_detail" and metric == "active_users":
                card["business_meaning"] = "支付明细中的每日去重支付用户；不是全站访问用户数。"
                from insightpilot.metrics.definitions import finalize_card
                card = finalize_card(card)
            cards.append(card)
    status = "invalid_input" if errors else "unsupported" if unsupported else "needs_clarification" if items else "ready"
    normalized_mapping = mapping if (column_mapping or answers or (not semantic and not builtin and mapping.get("metric_columns"))) else None
    if normalized_mapping and not errors:
        # Retain original raw intent in the returned mapping; validation already ran.
        normalized_mapping = normalize_column_mapping(normalized_mapping, list(metadata.get(str(mapping.get("table_name")), {}).get("columns", []))).to_dict()
    normalized_parameters = parameters
    if experiment:
        if mapping.get("statistical_unit"):
            normalized_parameters["statistical_unit"] = mapping["statistical_unit"]
        if mapping.get("group_column") and normalized_mapping is None and not metadata.get(str(mapping.get("table_name")), {}).get("builtin_scenario"):
            normalized_mapping = mapping
    return {
        "planning_status": status,
        "clarification": {"status": status, "items": [item.to_dict() for item in items], "unresolved_count": len(items), "display_limit": 3, "errors": list(dict.fromkeys(errors)), "unsupported_reasons": list(dict.fromkeys(unsupported))},
        "metric_definitions": cards,
        "semantic_fingerprint": stable_fingerprint([card["computation_fingerprint"] for card in cards]),
        "presentation_fingerprint": stable_fingerprint([card["presentation_fingerprint"] for card in cards]),
        "normalized_request": {"question": question, "goal_mode": goal_mode, "playbook_id": playbook_id, "column_mapping": normalized_mapping, "playbook_parameters": normalized_parameters, "metric_request": request or None, "semantic_model_id": semantic_model_id},
    }


def prepare_analysis_request(
    question: str, *, table_metadata: dict[str, dict[str, object]], goal_mode: str = "auto",
    playbook_id: str | None = None, column_mapping: dict[str, object] | None = None,
    playbook_parameters: dict[str, object] | None = None, metric_request: dict[str, object] | None = None,
    semantic_model_id: str = "commerce_demo", clarification_answers: dict[str, object] | None = None,
    dataset_revision: str = "", selection_source: str | None = None,
    analysis_scope: dict[str, object] | None = None,
) -> dict[str, object]:
    """One metadata-only contract for UI advice, CLI and workflow submission.

    No user choice is invented from a recommendation. None/auto selects the
    existing legacy route when appropriate; __legacy__ explicitly requests it.
    Missing exact preparation facts are reported instead of scanning source rows.
    """
    from copy import deepcopy
    from insightpilot.planning.analysis_advisor import AUTO_IDS, preferred_method, enrich_analysis_advice
    requested = playbook_id
    effective = preferred_method(question, goal_mode, table_metadata, column_mapping, playbook_parameters) if playbook_id in AUTO_IDS else None if playbook_id == "__legacy__" else playbook_id
    # Existing API callers with an explicit goal and no method/source keep the
    # legacy generic/specialized route. New UI auto is explicitly source-tagged.
    if playbook_id is None and selection_source is None and goal_mode != "auto":
        effective = None
    params = deepcopy(playbook_parameters or {})
    if params.get("metric_type") in {"continuous", "binary"}:
        params["metric_type"] = {"continuous": "mean", "binary": "proportion"}[params["metric_type"]]
    prepared = _prepare_metric_request(question, table_metadata=table_metadata, goal_mode=goal_mode,
        playbook_id=effective, column_mapping=column_mapping, playbook_parameters=params,
        metric_request=metric_request, semantic_model_id=semantic_model_id, clarification_answers=clarification_answers)
    if "exploration_request" in params:
        from insightpilot.analysis.exploration import validate_exploration_request
        normalized_mapping = prepared["normalized_request"].get("column_mapping") or column_mapping or {}
        if hasattr(normalized_mapping, "to_dict"):
            normalized_mapping = normalized_mapping.to_dict()
        meta = table_metadata.get(normalized_mapping.get("table_name"), {})
        exploration_errors = validate_exploration_request(params["exploration_request"], normalized_mapping, list(meta.get("columns", [])), meta)
        if exploration_errors:
            prepared["planning_status"] = "invalid_input"
            prepared["clarification"]["status"] = "invalid_input"
            prepared["clarification"]["errors"] = list(dict.fromkeys([*prepared["clarification"]["errors"], *exploration_errors]))
    return enrich_analysis_advice(prepared, question=question, table_metadata=table_metadata,
        goal_mode=goal_mode, requested_playbook_id=requested, dataset_revision=dataset_revision,
        selection_source=selection_source, analysis_scope=analysis_scope)
