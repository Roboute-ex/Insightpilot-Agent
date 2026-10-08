"""Safe deterministic metric compiler; this is intentionally not Text-to-SQL."""

from __future__ import annotations

from insightpilot.tools.sql_safety import SQL_POLICY_VERSION

from insightpilot.performance_tasks import cancellation_checkpoint

import hashlib
import json
import re
from typing import Any

import pandas as pd

from insightpilot.semantic.approval import PlanReview, review_query_plan
from insightpilot.semantic.join_planner import JoinPlanner
from insightpilot.semantic.models import SemanticMeasure, SemanticMetric, SemanticModel
from insightpilot.semantic.query import MetricFilter, MetricRequest, QueryPlan
from insightpilot.tools.duckdb_engine import AnalyticsEngine
from insightpilot.observability.tracer import trace_stage


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"identifier 不在安全格式内：{value}")
    return f'"{value}"'


class MetricCompiler:
    """Compile allowlisted semantic requests into one read-only SQL template."""

    def __init__(self, model: SemanticModel) -> None:
        errors = model.validate()
        if errors:
            raise ValueError("semantic model 校验失败：" + "；".join(errors))
        self.model = model
        self._column_allowlist = model.column_allowlist()

    def _metric_dependencies(self, metric_id: str, stack: tuple[str, ...] = ()) -> list[str]:
        if metric_id in stack:
            raise ValueError(f"指标依赖存在循环：{' -> '.join([*stack, metric_id])}")
        metric = self.model.metrics.get(metric_id)
        if metric is None:
            raise ValueError(f"未知指标：{metric_id}")
        values: list[str] = []
        for dependency in metric.dependencies():
            values.append(dependency)
            values.extend(self._metric_dependencies(dependency, (*stack, metric_id)))
        return list(dict.fromkeys(values))

    def _base_entity_for_metric(self, metric_id: str) -> str:
        metric = self.model.metrics[metric_id]
        if metric.metric_type == "simple":
            return self.model.measures[str(metric.measure_id)].entity_id
        dependencies = metric.dependencies()
        if not dependencies:
            raise ValueError(f"指标 {metric_id} 缺少可解析依赖。")
        return self._base_entity_for_metric(dependencies[0])

    def _validate_column(self, entity_id: str, column: str) -> None:
        if entity_id not in self.model.entities or column not in self._column_allowlist.get(entity_id, set()):
            raise ValueError(f"字段不在语义模型 allowlist：{entity_id}.{column}")

    def _measure_expression(self, measure: SemanticMeasure, aliases: dict[str, str]) -> str:
        alias = aliases[measure.entity_id]
        if measure.aggregation == "count" and measure.column is None:
            return "COUNT(*)"
        column = str(measure.column)
        self._validate_column(measure.entity_id, column)
        ref = f"{_quote_identifier(alias)}.{_quote_identifier(column)}"
        aggregation = "AVG" if measure.aggregation in {"mean", "avg", "average"} else measure.aggregation.upper()
        if aggregation == "COUNT_DISTINCT":
            return f"COUNT(DISTINCT {ref})"
        return f"{aggregation}({ref})"

    def _metric_expression(
        self,
        metric_id: str,
        aliases: dict[str, str],
        stack: tuple[str, ...] = (),
        window_order_by: str | None = None,
    ) -> str:
        if metric_id in stack:
            raise ValueError(f"指标依赖存在循环：{' -> '.join([*stack, metric_id])}")
        metric: SemanticMetric = self.model.metrics[metric_id]
        if metric.metric_type == "simple":
            return self._measure_expression(self.model.measures[str(metric.measure_id)], aliases)
        if metric.metric_type == "ratio":
            numerator = self._metric_expression(
                str(metric.numerator_metric), aliases, (*stack, metric_id), window_order_by
            )
            denominator = self._metric_expression(
                str(metric.denominator_metric), aliases, (*stack, metric_id), window_order_by
            )
            return f"(({numerator}) / NULLIF(({denominator}), 0))"
        if metric.metric_type == "derived":
            parts = [
                self._metric_expression(item, aliases, (*stack, metric_id), window_order_by)
                for item in metric.input_metrics
            ]
            operator = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}[str(metric.operation)]
            expression = parts[0]
            for part in parts[1:]:
                if operator == "/":
                    expression = f"(({expression}) / NULLIF(({part}), 0))"
                else:
                    expression = f"(({expression}) {operator} ({part}))"
            return expression
        if not window_order_by:
            raise ValueError(f"累计指标 {metric_id} 需要时间维度。")
        base = self._metric_expression(str(metric.base_metric), aliases, (*stack, metric_id), window_order_by)
        return (
            f"SUM(({base})) OVER ({window_order_by} "
            "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"
        )

    def _compile_filter(
        self,
        item: MetricFilter,
        aliases: dict[str, str],
        parameters: list[Any],
    ) -> str:
        dimension = self.model.dimensions.get(item.dimension_id)
        if dimension is None:
            raise ValueError(f"未知筛选维度：{item.dimension_id}")
        self._validate_column(dimension.entity_id, dimension.column)
        ref = f'{_quote_identifier(aliases[dimension.entity_id])}.{_quote_identifier(dimension.column)}'
        if item.operator == "eq":
            parameters.append(item.value)
            return f"{ref} = ?"
        if item.operator in {"gt", "gte", "lt", "lte"}:
            parameters.append(item.value)
            operator = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[item.operator]
            return f"{ref} {operator} ?"
        if item.operator == "in":
            values = list(item.value) if isinstance(item.value, (list, tuple, set)) else [item.value]
            if not values:
                raise ValueError("in 筛选值不能为空。")
            parameters.extend(values)
            return f"{ref} IN ({', '.join('?' for _ in values)})"
        values = list(item.value) if isinstance(item.value, (list, tuple)) else []
        if len(values) != 2:
            raise ValueError("between 筛选需要两个边界值。")
        parameters.extend(values)
        return f"{ref} BETWEEN ? AND ?"

    def compile(self, request: MetricRequest | dict[str, Any], tables: dict[str, pd.DataFrame] | None = None, *, _input_fingerprint: str | None = None) -> QueryPlan:
        if isinstance(request, dict):
            request = MetricRequest.from_dict(request)
        unknown_metrics = sorted(set(request.metrics) - set(self.model.metrics))
        unknown_dimensions = sorted(set(request.dimensions) - set(self.model.dimensions))
        if request.date_dimension and request.date_dimension not in self.model.dimensions:
            unknown_dimensions.append(request.date_dimension)
        if unknown_metrics or unknown_dimensions:
            details = []
            if unknown_metrics:
                details.append("未知指标：" + ", ".join(unknown_metrics))
            if unknown_dimensions:
                details.append("未知维度：" + ", ".join(sorted(set(unknown_dimensions))))
            raise ValueError("；".join(details))

        current_fingerprint = _input_fingerprint if _input_fingerprint is not None else data_fingerprint(tables) if tables is not None else None
        base_entity = self._base_entity_for_metric(request.metrics[0])
        dependencies = {metric_id: self._metric_dependencies(metric_id) for metric_id in request.metrics}
        required_entities = {base_entity}
        for metric_id in request.metrics:
            required_entities.add(self._base_entity_for_metric(metric_id))
            for dependency in dependencies[metric_id]:
                required_entities.add(self._base_entity_for_metric(dependency))
        requested_dimensions = list(request.dimensions)
        if request.date_dimension and request.date_dimension not in requested_dimensions:
            requested_dimensions.insert(0, request.date_dimension)
        for dimension_id in requested_dimensions:
            required_entities.add(self.model.dimensions[dimension_id].entity_id)
        for item in request.filters:
            if item.dimension_id not in self.model.dimensions:
                raise ValueError(f"未知筛选维度：{item.dimension_id}")
            required_entities.add(self.model.dimensions[item.dimension_id].entity_id)

        leaf_metrics = {item for key, values in dependencies.items() for item in [key, *values] if self.model.metrics[item].metric_type == "simple"}
        measure_entities = {self._base_entity_for_metric(item) for item in leaf_metrics}
        if len(measure_entities) > 1:
            from insightpilot.semantic.cross_fact import compile_cross_fact
            return compile_cross_fact(self, request, dependencies, leaf_metrics, tables, current_fingerprint)

        join_plan = JoinPlanner(self.model).plan(
            base_entity,
            sorted(required_entities),
            output_grain=", ".join(requested_dimensions) or self.model.entities[base_entity].grain,
        )
        leaf_metrics = {item for key, values in dependencies.items() for item in [key, *values] if self.model.metrics[item].metric_type == "simple"}
        measure_entities = {self._base_entity_for_metric(item) for item in leaf_metrics}
        compile_errors = list(join_plan.errors)
        if any(step.cardinality in {"one_to_many", "many_to_many"} for step in join_plan.steps):
            if any(self.model.measures[str(self.model.metrics[item].measure_id)].aggregation != "count_distinct" for item in leaf_metrics):
                compile_errors.append("一对多连接会重复累计该指标；尚无安全预聚合策略，审批也不能解除禁止。")
        aliases = {base_entity: "t0"}
        for index, step in enumerate(join_plan.steps, start=1):
            aliases.setdefault(step.source_entity, f"t{max(0, index - 1)}")
            aliases.setdefault(step.target_entity, f"t{index}")

        base_table = self.model.entities[base_entity].table_name
        if base_table not in self.model.table_allowlist():
            raise ValueError("基础表不在语义模型 allowlist。")
        select_parts: list[str] = []
        group_parts: list[str] = []
        time_order_parts: list[str] = []
        output_columns: list[str] = []
        for dimension_id in requested_dimensions:
            dimension = self.model.dimensions[dimension_id]
            self._validate_column(dimension.entity_id, dimension.column)
            ref = f'{_quote_identifier(aliases[dimension.entity_id])}.{_quote_identifier(dimension.column)}'
            if dimension.is_time_dimension:
                ref = f"DATE_TRUNC('{request.time_grain}', {ref})"
                time_order_parts.append(ref)
            select_parts.append(f"{ref} AS {_quote_identifier(dimension_id)}")
            group_parts.append(ref)
            output_columns.append(dimension_id)
        for metric_id in request.metrics:
            partition_parts = [part for part in group_parts if part not in time_order_parts]
            window_order_by = (("PARTITION BY " + ", ".join(partition_parts) + " ") if partition_parts else "") + "ORDER BY " + ", ".join(time_order_parts) if time_order_parts else None
            select_parts.append(
                f"{self._metric_expression(metric_id, aliases, window_order_by=window_order_by)} "
                f"AS {_quote_identifier(metric_id)}"
            )
            output_columns.append(metric_id)

        lines = [
            "SELECT",
            "  " + ",\n  ".join(select_parts),
            f"FROM {_quote_identifier(base_table)} AS {_quote_identifier(aliases[base_entity])}",
        ]
        for step in join_plan.steps:
            source_alias = aliases[step.source_entity]
            target_alias = aliases[step.target_entity]
            self._validate_column(step.source_entity, step.source_column)
            self._validate_column(step.target_entity, step.target_column)
            lines.append(
                f"{step.join_type.upper()} JOIN {_quote_identifier(step.target_table)} AS {_quote_identifier(target_alias)} "
                f"ON {_quote_identifier(source_alias)}.{_quote_identifier(step.source_column)} = "
                f"{_quote_identifier(target_alias)}.{_quote_identifier(step.target_column)}"
            )

        parameters: list[Any] = []
        where_parts = [self._compile_filter(item, aliases, parameters) for item in request.filters]
        if request.date_from or request.date_to:
            if not request.date_dimension:
                raise ValueError("日期范围筛选需要 date_dimension。")
            date_dimension = self.model.dimensions[request.date_dimension]
            ref = f'{_quote_identifier(aliases[date_dimension.entity_id])}.{_quote_identifier(date_dimension.column)}'
            if request.date_from:
                where_parts.append(f"{ref} >= ?")
                parameters.append(request.date_from)
            if request.date_to:
                where_parts.append(f"{ref} <= ?")
                parameters.append(request.date_to)
        if where_parts:
            lines.append("WHERE " + " AND ".join(where_parts))
        if group_parts:
            lines.append("GROUP BY " + ", ".join(group_parts))
        if request.sort:
            lines.append("ORDER BY " + ", ".join(_quote_identifier(item["field"]) + " " + item["direction"].upper() for item in request.sort))
        elif group_parts:
            lines.append("ORDER BY " + ", ".join(str(index) for index in range(1, len(group_parts) + 1)))
        lines.append("LIMIT ?")
        parameters.append(request.limit)
        sql_template = "\n".join(lines)
        canonical = {
            "model": self.model.computation_payload(),
            "request": {key: value for key, value in request.to_dict().items() if key != "execution_mode"},
            "compiler_version": "0.1.0",
            "sql_policy_version": SQL_POLICY_VERSION,
            "data_fingerprint": current_fingerprint,
            "join_plan_id": join_plan.plan_id,
            "sql_template": sql_template,
        }
        plan_id = "query_" + hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        plan = QueryPlan(
            plan_id=plan_id,
            semantic_model_id=self.model.model_id,
            request=request,
            base_entity=base_entity,
            metric_dependencies=dependencies,
            required_entities=sorted(required_entities),
            join_plan=join_plan,
            sql_template=sql_template,
            parameters=parameters,
            output_columns=output_columns,
            risk_level=join_plan.risk_level,
            requires_approval=join_plan.requires_approval,
            executable=join_plan.executable and not compile_errors,
            warnings=list(join_plan.warnings),
            errors=compile_errors,
            model_fingerprint=self.model.computation_fingerprint(),
            data_fingerprint=current_fingerprint,
            entity_keys={entity.table_name: entity.primary_key for entity in self.model.entities.values()},
        )

        plan._binding_fingerprint = _binding_fingerprint(plan)
        return plan


def _binding_fingerprint(plan: QueryPlan) -> str:
    values = {"model": plan.model_fingerprint, "data": plan.data_fingerprint, "compiler": plan.compiler_version, "sql_policy_version": plan.sql_policy_version, "request": {key: value for key, value in plan.request.to_dict().items() if key != "execution_mode"}, "parameters": plan.parameters, "sql": plan.sql_template, "join": plan.join_plan.to_dict(), "executable": plan.executable}
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def execute_query_plan(
    plan: QueryPlan,
    tables: dict[str, pd.DataFrame],
    *,
    approved_plan_id: str | None = None,
) -> tuple[pd.DataFrame | None, PlanReview]:
    """Execute an approved read-only plan, or return a structured pending review."""

    if plan.request.execution_mode == "plan_only":
        return None, PlanReview(plan.plan_id, "pending", "当前为仅预览方案模式，未执行 SQL。", False)
    if plan.sql_policy_version != SQL_POLICY_VERSION:
        return None, PlanReview(plan.plan_id, "rejected", "SQL 安全策略版本已变化，请重新编译和审批。", False)
    if not plan._binding_fingerprint or plan._binding_fingerprint != _binding_fingerprint(plan):
        return None, PlanReview(plan.plan_id, "rejected", "计划内容或参数已被修改，请重新编译和审批。", False)
    integrity_error = validate_plan_data(plan, tables)
    if integrity_error:
        return None, PlanReview(plan.plan_id, "rejected", integrity_error, False)
    if plan.requires_approval and plan.data_fingerprint is None:
        return None, PlanReview(plan.plan_id, "pending", "审批计划未绑定数据指纹，请使用当前数据重新预览。", False)
    review = review_query_plan(
        plan,
        decision="approved",
        approved_plan_id=approved_plan_id,
    )
    if review.decision != "approved":
        return None, review
    with AnalyticsEngine() as engine:
        from insightpilot.tools.sql_safety import validate_sql, SQLPolicyError
        validation = validate_sql(plan.sql_template, allowed_tables=set(tables), table_columns={name: list(frame.columns) for name, frame in tables.items()}, dialect="duckdb")
        if not validation.allowed:
            raise SQLPolicyError(validation)
        names = {name.casefold(): name for name in tables}
        required = {names[name.casefold()] for name in validation.referenced_tables}
        engine.register_tables({name: tables[name] for name in required})
        frame = engine.run_parameterized_sql(plan.sql_template, plan.parameters)
    return frame, review


def data_fingerprint(tables: dict[str, pd.DataFrame]) -> str:
    """Full-frame, order-sensitive fingerprint (including columns, dtype and index)."""
    with trace_stage("semantic_fingerprint",table_count=len(tables),rows=sum(len(frame) for frame in tables.values())):
        digest = hashlib.sha256()
        frame_bytes={}
        for name, frame in sorted(tables.items()):
            cancellation_checkpoint()
            digest.update(name.encode())
            digest.update(json.dumps([(str(c), str(t)) for c, t in frame.dtypes.items()]).encode())
            if id(frame) not in frame_bytes:
                frame_bytes[id(frame)]=pd.util.hash_pandas_object(frame,index=True).values.tobytes()
            digest.update(frame_bytes[id(frame)])
        return digest.hexdigest()


def validate_plan_data(plan: QueryPlan, tables: dict[str, pd.DataFrame]) -> str | None:
    if plan.data_fingerprint is not None and plan.data_fingerprint != data_fingerprint(tables):
        return "数据指纹已变化，原审批失效，请重新预览并审批。"
    for table, key in plan.entity_keys.items():
        cancellation_checkpoint()
        if table not in tables:
            continue
        if key not in tables[table] or tables[table][key].isna().any() or tables[table][key].duplicated().any():
            return f"表 {table} 的主键 {key} 缺失、为空或不唯一，查询已拒绝。"
    for step in plan.join_plan.steps:
        if step.source_table not in tables or step.target_table not in tables:
            return "连接所需数据表缺失。"
        source, target = tables[step.source_table], tables[step.target_table]
        if step.source_column not in source or step.target_column not in target:
            return "连接字段缺失。"
        left, right = source[step.source_column], target[step.target_column]
        if left.isna().any() or right.isna().any():
            return "连接键存在空值，无法验证基数。"
        if step.cardinality in {"many_to_one", "one_to_one"} and right.duplicated().any():
            return "连接目标键不唯一，与声明基数不符。"
        if step.cardinality in {"one_to_many", "one_to_one"} and left.duplicated().any():
            return "连接来源键不唯一，与声明基数不符。"
        if step.cardinality == "many_to_many":
            return "多对多连接被禁止。"
    return None
