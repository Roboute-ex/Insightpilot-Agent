"""Safe cross-fact aggregation at a shared non-temporal dimension grain."""
from __future__ import annotations
from insightpilot.tools.sql_safety import SQL_POLICY_VERSION

import hashlib
import json
from dataclasses import replace
from typing import Any

import pandas as pd

from insightpilot.semantic.join_planner import JoinPlan
from insightpilot.semantic.query import MetricRequest, QueryPlan


def compile_cross_fact(compiler, request: MetricRequest, dependencies: dict[str, list[str]], leaves: set[str], tables: dict[str, pd.DataFrame] | None, fingerprint: str | None = None) -> QueryPlan:
    # Import at call time to keep the existing single-fact compiler independent.
    from insightpilot.semantic.compiler import _binding_fingerprint, _quote_identifier, data_fingerprint
    model = compiler.model
    entities = sorted({compiler._base_entity_for_metric(metric) for metric in leaves})
    all_metrics = {metric for key, values in dependencies.items() for metric in [key, *values]}
    dimension_ids = list(request.dimensions)
    referenced_dims = set(dimension_ids) | {item.dimension_id for item in request.filters}
    if request.date_dimension or request.date_from or request.date_to or any(model.dimensions[item].is_time_dimension for item in referenced_dims):
        raise ValueError("跨事实时间口径尚未定义，请分别使用各事实的日期查询；本通路仅支持整体或共同非时间维度。")
    if any(model.metrics[item].metric_type == "cumulative" for item in all_metrics):
        raise ValueError("跨事实累计指标需要统一时间轴，当前不支持。")
    if any(model.dimensions[item].entity_id in entities for item in referenced_dims):
        raise ValueError("跨事实维度/筛选必须来自共同维表，不能使用某一事实的字段作为共同粒度。")

    subplans = []
    leaf_aliases = {}
    parameters: list[Any] = []
    ctes = []
    for index, entity in enumerate(entities):
        metrics = sorted(item for item in leaves if compiler._base_entity_for_metric(item) == entity)
        subrequest = replace(request, metrics=metrics, sort=[], limit=10000)
        plan = compiler.compile(subrequest, tables=tables, _input_fingerprint=fingerprint)
        # Even DISTINCT metrics must not take a fanout path for common grain.
        if not plan.executable or plan.requires_approval or any(step.cardinality not in {"many_to_one", "one_to_one"} for step in plan.join_plan.steps):
            raise ValueError("共同维度无法从各事实沿安全多对一/一对一关系取得，拒绝跨事实合并。")
        subplans.append(plan)
        alias = f"fact_{index}"
        # Each CTE aggregates ALL groups before the final output LIMIT, otherwise
        # sparse/non-overlapping groups would be silently lost or miscomputed.
        sql = plan.sql_template.rsplit("\nLIMIT ?", 1)[0]
        ctes.append(f'{_quote_identifier(alias)} AS (\n{sql}\n)')
        parameters.extend(plan.parameters[:-1])
        for metric_id in metrics:
            ref = f'{_quote_identifier(alias)}.{_quote_identifier(metric_id)}'
            aggregation = model.measures[str(model.metrics[metric_id].measure_id)].aggregation
            leaf_aliases[metric_id] = f"COALESCE({ref}, 0)" if aggregation in {"sum", "count", "count_distinct"} else ref

    def expression(metric_id: str) -> str:
        metric = model.metrics[metric_id]
        if metric.metric_type == "simple":
            return leaf_aliases[metric_id]
        if metric.metric_type == "ratio":
            return f'(({expression(str(metric.numerator_metric))}) / NULLIF(({expression(str(metric.denominator_metric))}), 0))'
        if metric.metric_type == "derived":
            parts = [expression(item) for item in metric.input_metrics]
            operator = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}[str(metric.operation)]
            value = parts[0]
            for part in parts[1:]:
                value = f"(({value}) / NULLIF(({part}), 0))" if operator == "/" else f"(({value}) {operator} ({part}))"
            return value
        raise ValueError("跨事实仅支持 simple、ratio、derived 指标。")

    def dimension_ref(dimension: str, count: int) -> str:
        refs = [f'{_quote_identifier(f"fact_{index}")}.{_quote_identifier(dimension)}' for index in range(count)]
        return refs[0] if len(refs) == 1 else f'COALESCE({", ".join(refs)})'

    select = [f'{dimension_ref(item, len(entities))} AS {_quote_identifier(item)}' for item in dimension_ids]
    select.extend(f'{expression(item)} AS {_quote_identifier(item)}' for item in request.metrics)
    lines = ["WITH " + ",\n".join(ctes), "SELECT " + ",\n  ".join(select), 'FROM "fact_0"']
    for index in range(1, len(entities)):
        if dimension_ids:
            conditions = [f'{dimension_ref(item, index)} IS NOT DISTINCT FROM {_quote_identifier(f"fact_{index}")}.{_quote_identifier(item)}' for item in dimension_ids]
            lines.append(f'FULL OUTER JOIN {_quote_identifier(f"fact_{index}")} ON ' + " AND ".join(conditions))
        else:
            lines.append(f'CROSS JOIN {_quote_identifier(f"fact_{index}")}')
    if request.sort:
        lines.append("ORDER BY " + ", ".join(_quote_identifier(item["field"]) + " " + item["direction"].upper() for item in request.sort))
    elif dimension_ids:
        lines.append("ORDER BY " + ", ".join(_quote_identifier(item) for item in dimension_ids))
    lines.append("LIMIT ?")
    parameters.append(request.limit)
    sql = "\n".join(lines)
    required = sorted({item for plan in subplans for item in plan.required_entities})
    steps = list({(step.source_entity, step.target_entity, step.relationship_id): step for plan in subplans for step in plan.join_plan.steps}.values())
    warning = "各事实先独立聚合到相同整体/共同维度粒度，再全外连接聚合结果；缺失分组的加总/计数记0，比率零分母不可计算；未定义跨事实日期口径。"
    canonical = {"model": model.computation_payload(), "request": {key: value for key, value in request.to_dict().items() if key != "execution_mode"}, "compiler_version": "0.1.0", "sql_policy_version": SQL_POLICY_VERSION, "data_fingerprint": fingerprint, "sql": sql}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()
    join = JoinPlan("join_preaggregate_" + digest[:16], model.model_id, entities[0], required, steps, "safe", False, True, ", ".join(dimension_ids) or "overall", [warning])
    plan = QueryPlan(plan_id="query_" + digest[:20], semantic_model_id=model.model_id, request=request, base_entity=entities[0], metric_dependencies=dependencies, required_entities=required, join_plan=join, sql_template=sql, parameters=parameters, output_columns=[*dimension_ids, *request.metrics], risk_level="safe", requires_approval=False, executable=True, warnings=[warning], model_fingerprint=model.computation_fingerprint(), data_fingerprint=fingerprint, entity_keys={entity.table_name: entity.primary_key for entity in model.entities.values()})
    plan._binding_fingerprint = _binding_fingerprint(plan)
    return plan
