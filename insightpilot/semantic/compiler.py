"""Safe deterministic metric compiler; this is intentionally not Text-to-SQL."""

from __future__ import annotations

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
        aggregation = "AVG" if measure.aggregation in {"mean", "avg"} else measure.aggregation.upper()
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
            f"SUM(({base})) OVER (ORDER BY {window_order_by} "
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

    def compile(self, request: MetricRequest | dict[str, Any]) -> QueryPlan:
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

        join_plan = JoinPlanner(self.model).plan(
            base_entity,
            sorted(required_entities),
            output_grain=", ".join(requested_dimensions) or self.model.entities[base_entity].grain,
        )
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
            window_order_by = time_order_parts[0] if time_order_parts else None
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
            lines.append("ORDER BY " + ", ".join(str(index) for index in range(1, len(group_parts) + 1)))
        lines.append("LIMIT ?")
        parameters.append(request.limit)
        sql_template = "\n".join(lines)
        canonical = {
            "model": self.model.to_dict(),
            "request": request.to_dict(),
            "join_plan_id": join_plan.plan_id,
            "sql_template": sql_template,
        }
        plan_id = "query_" + hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        return QueryPlan(
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
            executable=join_plan.executable,
            warnings=list(join_plan.warnings),
            errors=list(join_plan.errors),
        )


def execute_query_plan(
    plan: QueryPlan,
    tables: dict[str, pd.DataFrame],
    *,
    approved_plan_id: str | None = None,
) -> tuple[pd.DataFrame | None, PlanReview]:
    """Execute an approved read-only plan, or return a structured pending review."""

    if plan.request.execution_mode == "plan_only":
        return None, PlanReview(plan.plan_id, "pending", "当前为仅预览方案模式，未执行 SQL。", False)
    review = review_query_plan(
        plan,
        decision="approved",
        approved_plan_id=approved_plan_id,
    )
    if review.decision != "approved":
        return None, review
    engine = AnalyticsEngine()
    engine.register_tables(tables)
    frame = engine.run_parameterized_sql(plan.sql_template, plan.parameters)
    return frame, review
