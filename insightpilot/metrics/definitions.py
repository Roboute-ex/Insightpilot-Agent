"""Contextual cards adapted from the existing metric and semantic catalogues.

This module owns no metric registry and executes no query or DataFrame scan.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
from typing import Any
from insightpilot.metrics.dictionary import get_metric_dictionary
from insightpilot.metrics.aggregation import metric_components

# Only presentation-only fields are excluded. Descriptions/definitions remain
# semantic: changing business meaning must invalidate computation and approval.
PRESENTATION_FIELDS = {"display_name", "name_zh", "title", "color", "format", "display_format"}


def computation_payload(value: Any, *, _record: bool | None = None) -> Any:
    if isinstance(value, dict):
        record = _record if _record is not None else bool(set(value) & {"model_id", "metric_id", "metric_name", "entity_id", "dimension_id", "measure_id", "relationship_id", "expression"})
        result = {}
        for key, item in value.items():
            if record and key in PRESENTATION_FIELDS | {"computation_fingerprint", "presentation_fingerprint", "semantic_fingerprint"}:
                continue
            if key in {"metrics", "entities", "dimensions", "measures"} and isinstance(item, dict):
                # Registry IDs are data, even when an ID equals 'title' or 'color'.
                result[key] = {name: computation_payload(definition, _record=True) for name, definition in item.items()}
            else:
                result[key] = computation_payload(item)
        return result
    if isinstance(value, (list, tuple)):
        return [computation_payload(item) for item in value]
    return value


def stable_fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def finalize_card(card: dict[str, Any]) -> dict[str, Any]:
    for key in ("computation_fingerprint", "presentation_fingerprint", "semantic_fingerprint"):
        card.pop(key, None)
    card["computation_fingerprint"] = stable_fingerprint(computation_payload(card))
    card["presentation_fingerprint"] = stable_fingerprint({k: v for k, v in card.items() if k not in {"computation_fingerprint", "presentation_fingerprint"}})
    card["semantic_fingerprint"] = card["computation_fingerprint"]
    return card


def column_metric_card(metric: str, *, table_name: str, metadata: dict[str, Any], mapping: dict[str, Any], parameters: dict[str, Any], experiment: bool = False, confirmed: bool = False) -> dict[str, Any]:
    columns = list(metadata.get("columns", []))
    definition = get_metric_dictionary().get(metric)
    builtin = bool(metadata.get("builtin_scenario"))
    registered = definition is not None
    raw = definition.to_dict() if definition else {}
    explicit_pair = (mapping.get("numerator_column"), mapping.get("denominator_column"))
    pair = explicit_pair if all(explicit_pair) else metric_components(metric, columns)
    aggregation = str(parameters.get("aggregation") or mapping.get("aggregation") or raw.get("aggregation") or "sum")
    statistical_unit = parameters.get("statistical_unit") or mapping.get("statistical_unit")
    numerator, denominator = pair if pair else (None, None)
    expression = f"{aggregation}({metric})"
    additivity = "additive" if aggregation in {"sum", "count"} else "distinct" if aggregation == "count_distinct" else "non_additive"
    if pair:
        aggregation = "ratio_of_sums"
        expression = f"sum({numerator}) / nullif(sum({denominator}), 0)"
        additivity = "ratio" if all(explicit_pair) or raw.get("unit") == "比例" or "rate" in metric or metric in {"cvr", "ctr"} else "weighted_mean"
    elif metric == "active_users" and "user_id" in columns:
        aggregation, expression, additivity = "count_distinct", "count_distinct(user_id)", "distinct"
    elif raw.get("aggregation") == "ratio" and metric in columns:
        aggregation, expression, additivity = "mean", f"mean({metric})", "non_additive"
    if experiment:
        aggregation, numerator, denominator = "mean_per_independent_unit", None, None
        expression = f"mean_by({statistical_unit or 'unconfirmed'}, {metric})"
        additivity = "non_additive"
    unit = mapping.get("unit") or ("比例" if all(explicit_pair) else raw.get("unit")) or "未声明"
    if metric == "active_users":
        unit = "人"
    name = raw.get("display_name", metric)
    if metric == "revenue" and aggregation == "mean":
        name = "平均订单金额"
    if metric == "conversion_rate" and pair == ("converted", "sessions"):
        name = "观看会话转化率"
    card = {
        "metric_id": metric, "display_name": name, "aliases": raw.get("aliases", []),
        "scenario": metadata.get("builtin_scenario", "custom"), "model_id": None,
        "definition_version": raw.get("definition_version", "0.1.0"),
        "business_meaning": raw.get("business_meaning", "用户映射的观测指标，业务含义需复核"),
        "scope": table_name, "table_name": table_name, "expression": expression,
        "numerator": numerator, "denominator": denominator, "aggregation": aggregation,
        "unit": unit, "format": "percent" if unit == "比例" else "number",
        "grain": ("独立实验单位" if experiment else raw.get("grain", "观测行")),
        "statistical_unit": statistical_unit or ("user_id" if metric == "active_users" else "not_applicable"),
        "date_column": mapping.get("date_column"), "timezone": mapping.get("timezone", "naive"),
        "valid_sample": ("已指定对照/实验组中指标非空的独立单位；跨组重复单位拒绝" if experiment else raw.get("valid_sample", "当前过滤范围内有效观测")),
        "deduplication_key": mapping.get("deduplication_key") or ("user_id" if aggregation == "count_distinct" and metric == "active_users" else metric if aggregation == "count_distinct" else statistical_unit if experiment and statistical_unit != "row" else None),
        "null_policy": raw.get("null_policy", "exclude_invalid_numeric"), "zero_denominator_policy": "undefined",
        "additivity": additivity, "allowed_dimensions": list(metadata.get("schema_mapping", {}).get("possible_dimension_columns", [])),
        "allowed_time_grains": ["day", "week", "month"],
        "source": "user_confirmation" if confirmed else "builtin_definition" if builtin and registered else "user_mapping" if mapping.get("source") == "user_selected" else "automatic_suggestion",
        "definition_status": "user_confirmed" if confirmed else "builtin_verified" if builtin and registered else "draft",
        "time_range": parameters.get("date_range"), "comparison_baseline": {key: parameters[key] for key in ("current_start", "current_end", "previous_start", "previous_end") if key in parameters},
        "data_quality_notes": list(metadata.get("warnings", [])),
    }
    if experiment:
        card.update(control_value=parameters.get("control_value"), treatment_value=parameters.get("treatment_value"), metric_type=parameters.get("metric_type", "mean"), confidence_level=parameters.get("confidence_level", .95))
    if not pair and raw.get("aggregation") == "ratio" and not experiment:
        card["data_quality_notes"].append("缺少原始分子分母，本次只能对观测比率求均值；不能解释为总量加权比率。")
    if metric == "revenue" and not builtin:
        card["business_meaning"] = "已映射金额列；是否包含退款/税项由输入数据定义，不自动认定净收入。"
    exploration = parameters.get("exploration_request")
    if isinstance(exploration, dict):
        card["exploration_scope"] = {key: exploration.get(key) for key in ("kind", "row_dimension", "column_dimension", "date_from", "date_to", "time_grain") if exploration.get(key) is not None}
        # Manifest exports intentionally redact raw filter values. The governed
        # definition retains their identity, not the values, so exact report
        # binding compares the same definition before and after redaction.
        card["exploration_scope"]["filters"] = [
            {"column": item.get("column"), "operator": item.get("operator"),
             "value_fingerprint": stable_fingerprint(item.get("value"))}
            for item in exploration.get("filters", []) if isinstance(item, dict)
        ]
        if exploration.get("date_from") is not None:
            card["time_range"] = [exploration.get("date_from"), exploration.get("date_to")]
    return finalize_card(card)


def semantic_metric_card(model, metric_id: str, request: dict[str, Any]) -> dict[str, Any]:
    metric = model.metrics[metric_id]
    measure = model.measures.get(metric.measure_id)
    entity = model.entities.get(measure.entity_id) if measure else None
    aggregation = measure.aggregation if measure else metric.metric_type
    unit = metric.unit or "未声明"
    card = {
        "metric_id": metric_id, "display_name": metric.display_name, "aliases": metric.aliases,
        "scenario": "semantic", "model_id": model.model_id, "definition_version": metric.definition_version,
        "business_meaning": metric.description, "scope": entity.table_name if entity else model.model_id,
        "expression": {"measure_id": metric.measure_id, "operation": metric.operation, "input_metrics": metric.dependencies()},
        "numerator": metric.numerator_metric, "denominator": metric.denominator_metric,
        "aggregation": aggregation, "unit": unit, "format": metric.format,
        "grain": entity.grain if entity else "共同维度上的聚合结果",
        "statistical_unit": metric.statistical_unit or "not_applicable",
        "date_column": request.get("date_dimension"), "timezone": metric.timezone,
        "valid_sample": metric.valid_sample, "deduplication_key": measure.column if measure and aggregation == "count_distinct" else None,
        "null_policy": metric.null_policy, "zero_denominator_policy": metric.zero_denominator_policy,
        "additivity": "distinct" if aggregation == "count_distinct" else "ratio" if metric.metric_type == "ratio" else "additive" if aggregation in {"sum", "count"} else "non_additive",
        "allowed_dimensions": list(model.dimensions), "allowed_time_grains": ["day", "week", "month", "quarter", "year"],
        "source": "registered_definition", "definition_status": "draft",
        "time_range": [request.get("date_from"), request.get("date_to")], "comparison_baseline": {},
        "model_computation_fingerprint": model.computation_fingerprint(), "data_quality_notes": [],
    }
    if metric_id == "revenue_minus_orders":
        card["data_quality_notes"].append("此历史演示表达式把金额减去订单数，单位不相容，仅用于表达式编译演示，不作业务结论或直接比较。")
        card["unit"] = "混合单位（演示）"
    return finalize_card(card)
