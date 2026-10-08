"""Metadata-only method advice layered on the existing metric planner/registry.

This module selects and checks methods. It never reads rows, opens a database,
creates a task, compiles SQL, runs statistics, or grants plan approval.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import re
from typing import Any

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.metrics.definitions import stable_fingerprint
from insightpilot.metrics.aggregation import metric_components
from insightpilot.playbooks.registry import get_playbook_registry
from insightpilot.playbooks.validation import validate_playbook_parameters
from insightpilot.tools.sql_safety import SQL_POLICY_VERSION

ADVICE_VERSION = "0.1.0-guidance-1"
AUTO_IDS = {None, "", "auto", "auto_recommended"}


def affirmative_question(question: str) -> str:
    """Limited explicit negation handling; not general natural-language parsing."""
    return re.sub(r"(?:不做|不要|无需|不进行|不考虑|不分析|不需要)(?:任何)?(?:因果(?:分析|推断|探索|证明)?|实验(?:分析)?|预测)", "", question.lower())


def _asks_about_change(question: str) -> bool:
    return any(word in affirmative_question(question) for word in ("下降", "变化", "下滑", "增长", "减少", "上升", "昨天", "昨日"))


def method_ref(method_id: str | None, goal_name: str = "自动分析工作流") -> dict[str, Any]:
    if not method_id or method_id == "__legacy__":
        return {"method_ref": "route:legacy", "kind": "route", "id": "legacy", "display_name": goal_name}
    try:
        name = get_playbook_registry().get(method_id).display_name
    except ValueError:
        name = str(method_id)
    return {"method_ref": "playbook:" + method_id, "kind": "playbook", "id": method_id, "display_name": name}


def issue(code: str, message: str, fields: list[str], action: str, *, readiness: str = "needs_mapping") -> dict[str, Any]:
    return {"code": code, "message_zh": message, "related_fields": fields,
            "recovery_actions": [{"action": "edit_configuration", "label": action}], "data_readiness": readiness}


def preferred_method(question: str, goal_mode: str, metadata: dict[str, Any], mapping=None, parameters=None) -> str | None:
    """Question/confirmed fields determine the route, never question IDs or order."""
    q = affirmative_question(question)
    mapping = mapping or {}
    if any(word in q for word in ("队列", "留存", "cohort")):
        return "cohort_retention"
    if any(word in q for word in ("数据质量", "数据概览", "缺失", "字段类型", "数据画像", "重复订单", "重复行", "空值", "重复记录")):
        return "data_profile"
    if "控制" in q and ("后" in q or "调整" in q) and any(word in q for word in ("关联", "策略", "效应")):
        return "causal_exploration"
    if goal_mode == 'causal_exploration' or "因果" in q:
        return 'causal_exploration' if mapping else None
    if goal_mode == 'experiment_analysis' or any(word in q for word in ('实验', '新策略', 'a/b')):
        return 'experiment_comparison' if mapping.get('group_column') or mapping.get('treatment_column') else None
    if any(word in q for word in ("比较", "对比", "相比")) and any(word in q for word in ("本周", "上周", "前一周", "本月", "上月", "周期")):
        return "period_comparison"
    if "漏斗" in q and "events" in metadata:
        return "funnel_analysis"
    if any(word in q for word in ("趋势", "走势", "随日期", "每日", "每天", "持续增加", "trend")) or ("最近" in q and any(word in q for word in ("下降", "增长"))):
        return "metric_trend"
    if any(word in q for word in ("摘要", "汇总")) and any(word in q for word in ("本期", "周期", "近期", "表现", "质量")):
        return "periodic_summary"
    if not any(word in q for word in ("为什么", "为何", "定位", "异常", "关联")) and any(word in q for word in ("贡献", "构成", "各城市", "各渠道", "各时段", "各支付", "不同", "哪类", "哪个", "各直播", "差异", "拆开", "各占", "按客户端版本比较")):
        # The registered contribution playbook calculates static shares only.
        # Temporal attribution belongs to the existing diagnosis route.
        return None if _asks_about_change(q) else "dimension_contribution"
    return None


def _mapping_for_candidate(method_id, prepared, metadata):
    normalized = prepared["normalized_request"]
    mapping = deepcopy(normalized.get("column_mapping") or {})
    cards = prepared.get("metric_definitions", [])
    if not mapping.get("table_name"):
        card_table = next((card.get("source_table") or card.get("table_name") for card in cards if card.get("source_table") or card.get("table_name")), None)
        preferred = "experiments" if method_id in {"experiment_comparison", "causal_exploration"} else "daily_metrics"
        mapping["table_name"] = card_table if card_table in metadata else preferred if preferred in metadata else next(iter(metadata)) if len(metadata) == 1 else None
    name = mapping.get("table_name")
    meta = metadata.get(name, {})
    columns = meta.get("columns", [])
    schema = meta.get("schema_mapping", {})
    builtin = bool(meta.get("builtin_scenario"))
    metrics = list(mapping.get("metric_columns") or [card["metric_id"] for card in cards if card.get("metric_id") in columns])
    if not metrics and mapping.get("outcome_column"):
        metrics = [mapping["outcome_column"]]
    mapping["metric_columns"] = metrics
    if not mapping.get("date_column"):
        candidates = schema.get("detected_date_columns", [])
        if builtin and "date" in columns:
            mapping["date_column"] = "date"
        elif len(candidates) == 1:
            mapping["date_column"] = candidates[0]
    if not mapping.get("dimension_columns") and builtin:
        mapping["dimension_columns"] = [column for column in ("city", "channel", "user_segment", "device", "network_type", "content_category") if column in columns]
    if builtin and name == "experiments":
        mapping.setdefault("group_column", "group" if "group" in columns else None)
        mapping.setdefault("treatment_column", "group" if "group" in columns else None)
        mapping.setdefault("outcome_column", "completion_rate" if "completion_rate" in columns else None)
        if not metrics and "completion_rate" in columns:
            mapping["metric_columns"] = ["completion_rate"]
    elif builtin and "outcome_column" not in mapping and metrics:
        # An explicit empty mapping is a user choice, not permission to infer it.
        mapping["outcome_column"] = metrics[0]
    return mapping, meta


def _candidate(method_id, prepared, metadata, plan, question, *, selected=False):
    ref = method_ref(method_id, plan.goal_mode_display_name)
    mapping, meta = _mapping_for_candidate(method_id, prepared, metadata)
    params = dict(prepared["normalized_request"].get("playbook_parameters") or {})
    if method_id and method_id != prepared["normalized_request"].get("playbook_id") and method_id in {item.playbook_id for item in get_playbook_registry().list_all()}:
        names = {item.name for item in get_playbook_registry().get(method_id).parameters}
        params = {key: value for key, value in params.items() if key in names}
    columns = meta.get("columns", [])
    summary = meta.get("readiness_summary", {})
    facts = summary.get("columns", {}) if summary.get("exact") else {}
    missing, caveats = [], []
    required = []
    q = affirmative_question(question)
    goal = plan.goal_mode
    experiment = method_id == "experiment_comparison" or method_id is None and goal == "experiment_analysis"
    causal = method_id == "causal_exploration" or method_id is None and goal == "causal_exploration"
    temporal = method_id in {"metric_trend", "period_comparison", "periodic_summary"} or method_id is None and not (experiment or causal)
    change = _asks_about_change(q)
    if method_id == "dimension_contribution" and change:
        temporal = True
    if method_id:
        try:
            playbook = get_playbook_registry().get(method_id)
        except ValueError as exc:
            problem = issue("UNKNOWN_METHOD", str(exc), ["playbook_id"], "选择已注册方法", readiness="incompatible")
            return {**ref, "goal_fit": "unrelated", "data_readiness": "incompatible", "reason_codes": ["UNKNOWN_METHOD"], "reason_zh": str(exc), "required_inputs": [], "missing_inputs": [problem], "suggested_actions": problem['recovery_actions'], "supported_scope": "无此方法", "necessary_caveats": []}
        requirements = playbook.requirements
        goal_fit = "matches" if playbook.supports_goal_mode(goal) else "unrelated"
        # A descriptive profile cannot answer a diagnosis even when its historic
        # broad supported_goal_modes includes that goal.
        if method_id == "data_profile" and goal not in {"periodic_report", "auto"}:
            goal_fit = "unrelated"
        if goal == "periodic_report" and not any(word in q for word in ("因果", "实验", "趋势", "下降", "增长", "留存")):
            goal_fit = "matches"  # Explicit method supplies an otherwise unspecified goal.
        if any(word in q for word in ("数据缺失", "缺失率", "字段类型", "数据质量", "数据概览")):
            goal_fit = "matches" if method_id == "data_profile" else "unrelated"
        if method_id == "funnel_analysis" and "漏斗" in q:
            goal_fit = "matches"
        if method_id == "dimension_contribution" and change:
            goal_fit = "unrelated"
            caveats.append("此方法只计算观察期内的静态分布占比，没有基准周期，不能回答上升或下降的变化贡献。")
        required = [key.removeprefix("requires_") for key, value in requirements.to_dict().items() if key.startswith("requires_") and value]
        for table in requirements.required_tables:
            if table not in metadata:
                missing.append(issue("MISSING_TABLE", f"当前方法需要数据表：{table}。", [table], "加载所需表或改用推荐方法", readiness="incompatible"))
        if requirements.requires_table:
            try:
                cm = ColumnMapping(**{key: value for key, value in mapping.items() if key in ColumnMapping.__dataclass_fields__})
                for message in playbook.validate_mapping(cm):
                    field = next((key for key in ("treatment_column", "outcome_column", "group_column", "date_column", "metric_column", "dimension_column") if key in message), "table_name")
                    labels = {"treatment_column": "处理/对照分组字段", "outcome_column": "结果变量", "group_column": "实验分组字段", "date_column": "日期字段", "metric_column": "指标字段", "dimension_column": "分析维度", "table_name": "目标表"}
                    extra = "treatment、control 只是组别取值，不能代替数据表中的分组字段。" if field in {"treatment_column", "group_column"} else ""
                    missing.append(issue("MISSING_" + field.upper(), "缺少" + labels[field] + "。" + extra, [field], "补充字段配置"))
                if selected:
                    for message in validate_playbook_parameters(playbook, params, cm, columns):
                        if message not in playbook.validate_mapping(cm):
                            missing.append(issue("INVALID_PARAMETER", message, ["playbook_parameters"], "修正当前方法参数", readiness="needs_parameters"))
            except (TypeError, ValueError) as exc:
                missing.append(issue("INVALID_MAPPING", str(exc), ["column_mapping"], "修正字段配置"))
            if meta and meta.get("row_count", 0) < requirements.minimum_rows:
                missing.append(issue("INSUFFICIENT_ROWS", f"当前表仅 {meta.get('row_count', 0)} 行，方法至少需要 {requirements.minimum_rows} 行。", [str(mapping.get("table_name"))], "选择足够样本的数据", readiness="incompatible"))
    else:
        goal_fit = "matches"
        if not mapping.get("table_name"):
            missing.append(issue("MISSING_TABLE", "请选择本次分析目标表。", ["table_name"], "选择目标表"))
    multi = method_id in {"semantic_metric_query", "funnel_analysis", "cohort_retention"}
    if not metadata:
        missing.append(issue("NO_DATA", "尚未加载可用数据。", [], "先加载数据", readiness="needs_preparation"))
    elif not multi and meta.get("row_count", 0) == 0:
        missing.append(issue("EMPTY_TABLE", "目标表没有可用数据行。", [str(mapping.get("table_name"))], "重新加载非空数据", readiness="incompatible"))
    metrics = list(mapping.get("metric_columns") or [])
    if causal and mapping.get("outcome_column"):
        metrics = [mapping["outcome_column"]]
    if not multi and method_id != "data_profile":
        if not metrics:
            missing.append(issue("MISSING_METRIC", "尚未明确本次结果指标。", ["metric_columns"], "确认指标口径"))
        for metric in metrics:
            explicit_pair = (mapping.get("numerator_column"), mapping.get("denominator_column"))
            parts = explicit_pair if all(explicit_pair) else metric_components(metric, columns)
            for column in parts or (metric,):
                fact = facts.get(column)
                if column not in columns:
                    missing.append(issue("MISSING_COLUMN", f"当前表不存在指标列：{column}。", [column], "重新选择真实字段"))
                elif not fact:
                    missing.append(issue("PREPARATION_REQUIRED", f"尚未准备 {column} 的精确有效数值摘要。", [column], "重新准备当前数据", readiness="needs_preparation"))
                elif mapping.get("aggregation") not in {"count_distinct", "count"} and fact.get("valid_numeric_count", 0) == 0:
                    missing.append(issue("NO_VALID_NUMERIC_VALUES", f"结果列 {column} 没有有效有限数值，不能计算。", [column], "修正结果列或更换数据", readiness="incompatible"))
    period_dates_valid = True
    for key in ('current_start', 'current_end', 'previous_start', 'previous_end'):
        if params.get(key):
            try:
                date.fromisoformat(str(params[key])[:10])
            except (ValueError, TypeError):
                period_dates_valid = False
                missing.append(issue("INVALID_PARAMETER", f"{key} 不是有效ISO日期。", [key], "修正周期日期", readiness="needs_parameters"))
    if temporal and not multi:
        date_column = mapping.get("date_column")
        if not date_column:
            missing.append(issue("MISSING_DATE_COLUMN", "当前时间分析需要明确可用日期字段；静态分布不能回答变化原因。", ["date_column"], "补充日期字段或明确改为静态分析"))
        elif date_column not in facts:
            missing.append(issue("PREPARATION_REQUIRED", "尚未准备日期有效性与覆盖摘要。", [date_column], "重新准备数据", readiness="needs_preparation"))
        else:
            date_fact = facts[date_column]
            days = date_fact.get("observed_dates")
            if not date_fact.get("valid_date_count"):
                missing.append(issue("NO_VALID_DATES", f"日期字段 {date_column} 没有可解析日期。", [date_column], "修正日期格式", readiness="incompatible"))
            elif date_fact.get("distinct_day_count", 0) < 2:
                missing.append(issue("INSUFFICIENT_DATE_COVERAGE", "只有一个有效日期，无法比较时间变化。", [date_column], "补充历史日期或选择静态分析", readiness="incompatible"))
            else:
                caveats.append(f"数据日期范围 {date_fact['date_min']} 至 {date_fact['date_max']}；“昨日”指数据中最近完整日，非电脑当前日期。")
                if date_fact.get("distinct_day_count", 0) < 8:
                    caveats.append("历史不足7个完整基准日；短窗口只作描述性比较，不能视为完整7日基准。")
                if method_id == "period_comparison" and days and period_dates_valid and not prepared["clarification"].get("errors") and not any(item["code"] == "INVALID_PARAMETER" for item in missing):
                    end = date.fromisoformat(str(params.get("current_end") or date_fact['date_max'])[:10])
                    start = date.fromisoformat(str(params.get("current_start") or end-timedelta(days=6))[:10])
                    prev_end = date.fromisoformat(str(params.get("previous_end") or start-timedelta(days=1))[:10])
                    prev_start = date.fromisoformat(str(params.get("previous_start") or prev_end-(end-start))[:10])
                    for label, low, high in (("当前", start, end), ("对比", prev_start, prev_end)):
                        observed = sum(str(low) <= day <= str(high) for day in days)
                        if not observed:
                            missing.append(issue("EMPTY_COMPARISON_WINDOW", f"{label}窗口 {low} 至 {high} 没有可用日期。", ["current_start", "previous_start"], "调整两个周期范围", readiness="needs_parameters"))
                        elif observed < (high-low).days+1:
                            caveats.append(f"{label}窗口仅覆盖 {observed} 个观测日；周期覆盖不完整。")
    if method_id == "dimension_contribution":
        for dimension in mapping.get("dimension_columns", []):
            if dimension in facts and facts[dimension].get("non_null_count", 0) == 0:
                missing.append(issue("EMPTY_DIMENSION", f"维度 {dimension} 全部为空，无法形成有效分组。", [dimension], "提供有效维度或选择其它方法", readiness="incompatible"))
    if experiment or causal:
        group_column = mapping.get("treatment_column") if causal else mapping.get("group_column")
        if not group_column:
            role = "treatment_column" if causal else "group_column"
            if not any(role in entry['related_fields'] for entry in missing):
                missing.append(issue("MISSING_"+role.upper(), "缺少处理/对照分组字段；组别取值不能替代字段。", [role], "补充分组字段"))
        else:
            fact = facts.get(group_column, {})
            values = fact.get("values", [])
            if not fact or not fact.get("values_complete"):
                missing.append(issue("GROUP_PREPARATION_REQUIRED", "尚无当前分组字段的完整可选组值摘要（最多100项）。", [group_column], "准备适合实验的分组字段", readiness="needs_preparation"))
            elif fact.get("unique_count", 0) < 2:
                missing.append(issue("SINGLE_GROUP", "分组字段只有一个有效组，无法进行两组比较。", [group_column], "提供真实处理组和对照组", readiness="incompatible"))
            for role in ("control_value", "treatment_value"):
                value = params.get(role)
                if value is None and meta.get("builtin_scenario") and meta.get("columns") and mapping.get("table_name") == "experiments":
                    value = "control" if role == "control_value" else "treatment"
                if value is None or value == "":
                    missing.append(issue("MISSING_"+role.upper(), "请明确选择对照组取值。" if role == "control_value" else "请明确选择处理组取值。", [role], "选择当前数据的真实组值", readiness="needs_parameters"))
                elif fact.get("values_complete") and value not in values:
                    missing.append(issue("GROUP_VALUE_NOT_FOUND", f"指定组值 {value!r} 不存在于 {group_column}。", [group_column, role], "重新选择当前数据的组值", readiness="needs_parameters"))
                elif value in values and metrics:
                    valid_counts = fact.get("valid_numeric_by_value", {}).get(metrics[0])
                    if valid_counts is not None and valid_counts[values.index(value)] == 0:
                        missing.append(issue("GROUP_NO_VALID_OUTCOME", f"组 {value!r} 的结果列没有有效数值。", [group_column, metrics[0]], "修正组内结果数据", readiness="incompatible"))
            if params.get("control_value") is not None and params.get("control_value") == params.get("treatment_value"):
                missing.append(issue("IDENTICAL_GROUP_VALUES", "处理组和对照组不能相同。", ["control_value", "treatment_value"], "明确比较方向", readiness="needs_parameters"))
        if experiment:
            unit = params.get("statistical_unit") or mapping.get("statistical_unit")
            if not unit and meta.get("builtin_scenario") and "user_id" in columns:
                unit = "user_id"
            if not unit:
                missing.append(issue("MISSING_STATISTICAL_UNIT", "请确认独立统计单位；不能把每行自动当作独立用户。", ["statistical_unit"], "确认独立单位", readiness="needs_parameters"))
            elif unit != "row" and (unit not in columns or facts.get(unit, {}).get("non_null_count", 0) == 0):
                missing.append(issue("INVALID_STATISTICAL_UNIT", "指定独立单位字段不存在或全部为空。", [unit], "选择有效的单位标识", readiness="incompatible"))
            kind = params.get("metric_type", "mean")
            if kind in {"proportion", "binary"} and metrics and not facts.get(metrics[0], {}).get("binary_numeric", False):
                missing.append(issue("NON_BINARY_OUTCOME", "比例检验要求单位级0/1结果，当前结果列不是二元值。", metrics, "确认连续型均值比较或提供二元结果", readiness="needs_parameters"))
            caveats.append("独立性及随机分配是研究设计前提，字段齐全不表示已经验证；连续型采用Welch均值比较，二元指标采用比例检验。")
        else:
            controls = params.get("covariates") or mapping.get("covariates") or mapping.get("dimension_columns") or []
            if not controls:
                caveats.append("未指定协变量：只能输出未经调整的两组差异，不能声称已控制混杂。")
            caveats.append("轻量因果探索不证明因果：随机化、无未观测混杂、重叠性和时序前提仍需研究设计与诊断支持。")
    if method_id in {"funnel_analysis", "cohort_retention"}:
        contracts = {"events": ["session_id", "event_name", "event_time"]} if method_id == "funnel_analysis" else {"customers": ["customer_id", "signup_date"], "sessions": ["customer_id", "session_date"]}
        for table, required_columns in contracts.items():
            if table not in metadata:
                continue
            for column in required_columns:
                if column not in metadata[table].get("columns", []):
                    missing.append(issue("MISSING_ENTITY_EVENT_COLUMN", f"缺少 {table}.{column}；日聚合计数不能替代实体追踪。", [table+"."+column], "提供实体和事件时间明细", readiness="incompatible"))
        for table, required_columns in contracts.items():
            meta_facts = metadata.get(table, {}).get("readiness_summary", {}).get("columns", {})
            for column in required_columns:
                fact = meta_facts.get(column, {})
                if column not in metadata.get(table, {}).get("columns", []):
                    continue
                if not fact:
                    missing.append(issue("PREPARATION_REQUIRED", f"尚未准备 {table}.{column} 的精确有效性摘要。", [table+"."+column], "准备当前数据", readiness="needs_preparation"))
                elif column.endswith("date") or column.endswith("time"):
                    if not fact.get("valid_date_count"):
                        missing.append(issue("NO_VALID_DATES", f"{table}.{column} 没有有效日期。", [table+"."+column], "修正实体事件时间", readiness="incompatible"))
                elif not fact.get("non_null_count"):
                    missing.append(issue("EMPTY_ENTITY_FIELD", f"{table}.{column} 全为空，无法追踪实体。", [table+"."+column], "提供实体标识", readiness="incompatible"))
        if method_id == "funnel_analysis" and "events" in metadata:
            event_facts = metadata['events'].get('readiness_summary', {}).get('columns', {})
            event_names = event_facts.get('event_name', {})
            if event_names.get('values_complete'):
                absent = sorted({'visit', 'view', 'cart', 'submit', 'paid'} - set(event_names.get('values', [])))
                if absent:
                    missing.append(issue("MISSING_FUNNEL_STAGES", "缺少必要事件类型：" + ', '.join(absent) + "；几个计数列不能替代时序漏斗。", ['events.event_name'], "提供完整事件定义", readiness="incompatible"))
            for column in ('session_id', 'event_time'):
                fact = event_facts.get(column, {})
                count = fact.get('valid_date_count') if column == 'event_time' else fact.get('non_null_count')
                if count is not None and count < metadata['events'].get('row_count', 0):
                    missing.append(issue("INVALID_FUNNEL_ENTITY_TIME", f"events.{column} 存在空值或无效时间，当前漏斗不支持。", ['events.'+column], "修复事件实体或时间", readiness="incompatible"))
        if method_id == "cohort_retention":
            fact = metadata.get('customers', {}).get('readiness_summary', {}).get('columns', {}).get('customer_id', {})
            if fact.get('unique_count') is not None and fact['unique_count'] != metadata.get('customers', {}).get('row_count'):
                missing.append(issue("DUPLICATE_COHORT_ENTITY", "队列表的customer_id必须每实体唯一且非空。", ['customers.customer_id'], "明确每实体唯一的队列时间", readiness="incompatible"))
        caveats.append("仅支持已实现的事件/队列定义；不完整观察窗需按成熟资格披露，不能把未观察当作流失。")
    unique = {(entry['code'], entry['message_zh']): entry for entry in missing}
    missing = list(unique.values())
    states = [entry['data_readiness'] for entry in missing]
    readiness = next((state for state in ("incompatible", "needs_preparation", "needs_mapping", "needs_parameters") if state in states), "ready")
    return {**ref, "goal_fit": goal_fit, "data_readiness": readiness,
            "reason_codes": [entry['code'] for entry in missing] or ["SUPPORTED_INPUTS"],
            "reason_zh": ("此方法仅计算静态占比，当前问题要求与历史基准比较变化；请改用指标诊断或明确改问静态分布。" if method_id == "dimension_contribution" and change else "比较订单历史基准，检查漏斗和主要维度变化；这些是描述性诊断，不等于因果证明。" if method_id is None and goal == "metric_diagnosis" else "当前方法与已确认指标及字段适配，执行时继续检查数据与安全契约。") if not missing else "；".join(entry['message_zh'] for entry in missing),
            "required_inputs": required, "missing_inputs": missing,
            "suggested_actions": [action for entry in missing for action in entry['recovery_actions']],
            "supported_scope": "现有本地确定性方法，保持完整统计口径。", "necessary_caveats": caveats}


def enrich_analysis_advice(prepared, *, question, table_metadata, goal_mode, requested_playbook_id,
                           dataset_revision="", selection_source=None, analysis_scope=None):
    from insightpilot.planning.planner import create_analysis_plan
    metadata = table_metadata
    plan = create_analysis_plan(question, goal_mode=goal_mode)
    normalized = prepared['normalized_request']
    effective_id = normalized.get('playbook_id')
    selected = requested_playbook_id not in AUTO_IDS
    source = selection_source or ("user_selected" if selected else "automatic")
    recommended_id = preferred_method(question, goal_mode, metadata, normalized.get("column_mapping"), normalized.get("playbook_parameters"))
    main = _candidate(recommended_id, prepared, metadata, plan, question)
    effective = _candidate(effective_id, prepared, metadata, plan, question, selected=True)
    blocking = list(effective['missing_inputs'])
    if effective['goal_fit'] == 'unrelated':
        blocking.append(issue("METHOD_GOAL_MISMATCH", f"当前方法“{effective['display_name']}”与当前问题目标不匹配。", ["playbook_id", "goal_mode"], "改用推荐方法或明确更改本次分析目标", readiness="needs_parameters"))
    q = affirmative_question(question)
    unsupported = []
    if re.search(r"预测|forecast|未来.*(?:订单|收入|增长)|证明.*因果|因果.*证明|必然.*导致", q):
        unsupported.append(issue("UNSUPPORTED_ANALYSIS_GOAL", "当前引擎不支持未来预测或因果证明；历史趋势与关联不能代替这些结论。", ["question"], "改问历史变化或明确探索性比较", readiness="incompatible"))
    if not question.strip():
        blocking.append(issue("EMPTY_QUESTION", "请先输入要分析的问题。", ["question"], "填写问题", readiness="needs_parameters"))
    if source == "legacy_unconfirmed":
        blocking.append(issue("UNCONFIRMED_LEGACY_SELECTION", "检测到来源不明的旧方法选择，请恢复自动推荐或明确确认本次方法。", ["selection_source"], "恢复自动推荐", readiness="needs_parameters"))
    if re.search(r"同时|以及|并且", q) and sum(word in q for word in ("因果", "实验", "留存", "预测")) >= 2:
        blocking.append(issue("MULTIPLE_ANALYSIS_GOALS", "本次包含不同研究目标，请先选择其中一项分析。", ["goal_mode"], "确认一个主要目标", readiness="needs_parameters"))
    current_mapping = normalized.get('column_mapping') or {}
    if "策略" in q and any(word in q for word in ("有效", "提升", "效果")) and not current_mapping.get('group_column') and not current_mapping.get('treatment_column') and not any(meta.get('builtin_scenario') and 'group' in meta.get('columns', []) for meta in metadata.values()):
        blocking.append(issue("RESEARCH_DESIGN_REQUIRED", "请说明策略比较来自随机实验还是观测分组，并提供对应分组字段。", ["group_column", "treatment_column"], "明确研究设计与分组", readiness="needs_mapping"))
    clarification = deepcopy(prepared['clarification'])
    for entry in unsupported:
        clarification['unsupported_reasons'].append(entry['message_zh'])
    for entry in blocking:
        if entry['message_zh'] not in [item['question'] for item in clarification['items']]:
            clarification['items'].append({"role": entry['related_fields'][0] if entry['related_fields'] else 'configuration', "question": entry['message_zh'], "candidates": [], "reason": entry['recovery_actions'][0]['label'], "required": True, "code": entry['code']})
    for entry in clarification.get('errors', []):
        blocking.append(issue("INVALID_REQUEST", entry, [], "修正输入", readiness="needs_parameters"))
    for entry in clarification.get('unsupported_reasons', []):
        if entry not in [item['message_zh'] for item in unsupported]:
            unsupported.append(issue("UNSUPPORTED_REQUEST", entry, [], "选择已支持的口径", readiness="incompatible"))
    # Preserve original metric/direction clarification; advice does not confirm it.
    for entry in prepared['clarification'].get('items', []):
        if entry['question'] not in [item['message_zh'] for item in blocking]:
            blocking.append(issue("CLARIFICATION_REQUIRED", entry['question'], [entry['role']], "确认必要口径", readiness="needs_parameters"))
    status = 'invalid_input' if clarification.get('errors') else 'unsupported' if unsupported else 'needs_clarification' if blocking else 'ready'
    blocking += unsupported
    clarification.update(status=status, unresolved_count=len(clarification['items']))
    versions = {"advisor": ADVICE_VERSION, "mapping": "0.1.0", "semantic": prepared.get('semantic_fingerprint'), "sql_policy": SQL_POLICY_VERSION}
    dataset_identity = {name: {key: meta.get(key) for key in ('dataset_id', 'dataset_revision', 'data_fingerprint')} for name, meta in metadata.items()}
    identity = {"dataset_identity": dataset_identity, "request": normalized, "requested_playbook_id": requested_playbook_id, "selection_source": source, "dataset_revision": str(dataset_revision), "analysis_scope": analysis_scope or {}, "versions": versions}
    fingerprint = stable_fingerprint(identity)
    others = [_candidate(playbook.playbook_id, prepared, metadata, plan, question) for playbook in get_playbook_registry().list_all() if playbook.playbook_id != recommended_id]
    if recommended_id is not None:
        others.append(_candidate(None, prepared, metadata, plan, question))
    relevant = [item for item in others if item['goal_fit'] == 'matches' and item['data_readiness'] == 'ready']
    advice = {"advice_id": fingerprint[:24], "advice_version": ADVICE_VERSION, "status": status,
              "interpreted_goal": {"id": plan.goal_mode, "display_name": plan.goal_mode_display_name},
              "requested_method": method_ref(requested_playbook_id, plan.goal_mode_display_name) if selected else None,
              "recommended_method": main, "effective_method": effective,
              "candidates": [main, *relevant[:2]], "other_methods": others,
              "missing_requirements": blocking, "blocking_issues": blocking,
              "question_clarifications": clarification['items'], "can_submit": status == 'ready',
              "dataset_revision": str(dataset_revision), "request_fingerprint": fingerprint,
              "versions": versions, "recommendation_source": "automatic", "selection_source": source}
    prepared.update(planning_status=status, clarification=clarification, analysis_advice=advice,
                    preflight={"status": status, "can_submit": status == 'ready', "blocking_issues": blocking,
                               "request_fingerprint": fingerprint, "dataset_revision": str(dataset_revision)})
    return prepared
