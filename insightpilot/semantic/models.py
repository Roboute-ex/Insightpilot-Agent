"""Stable, JSON-serializable semantic model definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}
MEASURE_AGGREGATIONS = {"sum", "mean", "avg", "count", "count_distinct", "min", "max"}
METRIC_TYPES = {"simple", "ratio", "derived", "cumulative"}
DERIVED_OPERATIONS = {"add", "subtract", "multiply", "divide"}


@dataclass(frozen=True)
class SemanticEntity:
    entity_id: str
    table_name: str
    primary_key: str
    display_name: str = ""
    grain: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticDimension:
    dimension_id: str
    entity_id: str
    column: str
    data_type: str = "string"
    display_name: str = ""
    description: str = ""
    is_time_dimension: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticMeasure:
    measure_id: str
    entity_id: str
    column: str | None
    aggregation: str
    display_name: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if self.aggregation not in MEASURE_AGGREGATIONS:
            raise ValueError(f"不支持的度量聚合方式：{self.aggregation}")
        if self.aggregation != "count" and not self.column:
            raise ValueError(f"度量 {self.measure_id} 需要声明 column。")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticMetric:
    metric_id: str
    metric_type: str
    display_name: str
    description: str = ""
    measure_id: str | None = None
    numerator_metric: str | None = None
    denominator_metric: str | None = None
    input_metrics: list[str] = field(default_factory=list)
    operation: str | None = None
    base_metric: str | None = None
    format: str = "number"

    def __post_init__(self) -> None:
        if self.metric_type not in METRIC_TYPES:
            raise ValueError(f"不支持的指标类型：{self.metric_type}")
        if self.metric_type == "simple" and not self.measure_id:
            raise ValueError(f"simple 指标 {self.metric_id} 需要 measure_id。")
        if self.metric_type == "ratio" and not (self.numerator_metric and self.denominator_metric):
            raise ValueError(f"ratio 指标 {self.metric_id} 需要 numerator_metric 和 denominator_metric。")
        if self.metric_type == "derived":
            if self.operation not in DERIVED_OPERATIONS or len(self.input_metrics) < 2:
                raise ValueError(f"derived 指标 {self.metric_id} 需要安全 operation 和至少两个 input_metrics。")
        if self.metric_type == "cumulative" and not self.base_metric:
            raise ValueError(f"cumulative 指标 {self.metric_id} 需要 base_metric。")

    def dependencies(self) -> list[str]:
        if self.metric_type == "ratio":
            return [str(self.numerator_metric), str(self.denominator_metric)]
        if self.metric_type == "derived":
            return list(self.input_metrics)
        if self.metric_type == "cumulative":
            return [str(self.base_metric)]
        return []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticRelationship:
    relationship_id: str
    from_entity: str
    to_entity: str
    from_column: str
    to_column: str
    cardinality: str
    join_type: str = "left"
    description: str = ""

    def __post_init__(self) -> None:
        if self.cardinality not in CARDINALITIES:
            raise ValueError(f"不支持的关系基数：{self.cardinality}")
        if self.join_type not in {"left", "inner"}:
            raise ValueError("语义关系仅允许 left 或 inner join。")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticModel:
    model_id: str
    version: str
    display_name: str
    entities: dict[str, SemanticEntity]
    dimensions: dict[str, SemanticDimension]
    measures: dict[str, SemanticMeasure]
    metrics: dict[str, SemanticMetric]
    relationships: list[SemanticRelationship] = field(default_factory=list)
    description: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        table_names: set[str] = set()
        for key, entity in self.entities.items():
            if key != entity.entity_id:
                errors.append(f"entity key 与 entity_id 不一致：{key}")
            if entity.table_name in table_names:
                errors.append(f"table_name 重复：{entity.table_name}")
            table_names.add(entity.table_name)
        for key, dimension in self.dimensions.items():
            if key != dimension.dimension_id:
                errors.append(f"dimension key 与 dimension_id 不一致：{key}")
            if dimension.entity_id not in self.entities:
                errors.append(f"维度 {key} 引用了未知实体：{dimension.entity_id}")
        for key, measure in self.measures.items():
            if key != measure.measure_id:
                errors.append(f"measure key 与 measure_id 不一致：{key}")
            if measure.entity_id not in self.entities:
                errors.append(f"度量 {key} 引用了未知实体：{measure.entity_id}")
        for key, metric in self.metrics.items():
            if key != metric.metric_id:
                errors.append(f"metric key 与 metric_id 不一致：{key}")
            if metric.measure_id and metric.measure_id not in self.measures:
                errors.append(f"指标 {key} 引用了未知度量：{metric.measure_id}")
            for dependency in metric.dependencies():
                if dependency not in self.metrics:
                    errors.append(f"指标 {key} 引用了未知指标：{dependency}")
        relationship_ids: set[str] = set()
        for relationship in self.relationships:
            if relationship.relationship_id in relationship_ids:
                errors.append(f"relationship_id 重复：{relationship.relationship_id}")
            relationship_ids.add(relationship.relationship_id)
            if relationship.from_entity not in self.entities or relationship.to_entity not in self.entities:
                errors.append(f"关系 {relationship.relationship_id} 引用了未知实体。")
        return errors

    def table_allowlist(self) -> set[str]:
        return {entity.table_name for entity in self.entities.values()}

    def column_allowlist(self) -> dict[str, set[str]]:
        values = {
            entity.entity_id: {entity.primary_key}
            for entity in self.entities.values()
        }
        for dimension in self.dimensions.values():
            values.setdefault(dimension.entity_id, set()).add(dimension.column)
        for measure in self.measures.values():
            if measure.column:
                values.setdefault(measure.entity_id, set()).add(measure.column)
        for relationship in self.relationships:
            values.setdefault(relationship.from_entity, set()).add(relationship.from_column)
            values.setdefault(relationship.to_entity, set()).add(relationship.to_column)
        return values

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "entities": {key: value.to_dict() for key, value in sorted(self.entities.items())},
            "dimensions": {key: value.to_dict() for key, value in sorted(self.dimensions.items())},
            "measures": {key: value.to_dict() for key, value in sorted(self.measures.items())},
            "metrics": {key: value.to_dict() for key, value in sorted(self.metrics.items())},
            "relationships": [item.to_dict() for item in sorted(self.relationships, key=lambda item: item.relationship_id)],
        }


def semantic_model_from_dict(values: dict[str, Any]) -> SemanticModel:
    """Build and validate a semantic model from safe parsed data."""

    if not isinstance(values, dict):
        raise ValueError("semantic model 必须是 object。")

    def keyed(items: Any, cls: type[Any], id_field: str) -> dict[str, Any]:
        if isinstance(items, dict):
            result: dict[str, Any] = {}
            for key, item in items.items():
                payload = dict(item or {})
                payload.setdefault(id_field, str(key))
                result[str(key)] = cls(**payload)
            return result
        if isinstance(items, list):
            result = {}
            for item in items:
                payload = dict(item or {})
                key = str(payload[id_field])
                result[key] = cls(**payload)
            return result
        return {}

    relationships = [SemanticRelationship(**dict(item)) for item in values.get("relationships", [])]
    model = SemanticModel(
        model_id=str(values.get("model_id", "")),
        version=str(values.get("version", "1.0")),
        display_name=str(values.get("display_name", values.get("model_id", ""))),
        description=str(values.get("description", "")),
        entities=keyed(values.get("entities", {}), SemanticEntity, "entity_id"),
        dimensions=keyed(values.get("dimensions", {}), SemanticDimension, "dimension_id"),
        measures=keyed(values.get("measures", {}), SemanticMeasure, "measure_id"),
        metrics=keyed(values.get("metrics", {}), SemanticMetric, "metric_id"),
        relationships=relationships,
    )
    errors = model.validate()
    if not model.model_id:
        errors.insert(0, "model_id 不能为空。")
    if errors:
        raise ValueError("semantic model 校验失败：" + "；".join(errors))
    return model
