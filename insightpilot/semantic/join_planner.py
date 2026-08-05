"""Deterministic multi-table join planning with fanout controls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from insightpilot.semantic.models import SemanticModel, SemanticRelationship
from insightpilot.semantic.relationships import RelationshipGraph


JOIN_RISKS = {"safe", "warn", "require_approval", "forbidden"}


def _reverse_cardinality(cardinality: str) -> str:
    return {
        "one_to_one": "one_to_one",
        "one_to_many": "many_to_one",
        "many_to_one": "one_to_many",
        "many_to_many": "many_to_many",
    }[cardinality]


@dataclass(frozen=True)
class JoinStep:
    relationship_id: str
    source_entity: str
    target_entity: str
    source_table: str
    target_table: str
    source_column: str
    target_column: str
    cardinality: str
    join_type: str
    risk_level: str = "safe"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JoinPlan:
    plan_id: str
    semantic_model_id: str
    base_entity: str
    required_entities: list[str]
    steps: list[JoinStep]
    risk_level: str
    requires_approval: bool
    executable: bool
    output_grain: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.risk_level not in JOIN_RISKS:
            raise ValueError(f"不支持的 Join 风险等级：{self.risk_level}")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "steps": [step.to_dict() for step in self.steps],
        }


class JoinPlanner:
    def __init__(self, model: SemanticModel, *, allow_many_to_many: bool = False) -> None:
        self.model = model
        self.graph = RelationshipGraph(model)
        self.allow_many_to_many = allow_many_to_many

    def _orient_step(self, current: str, relationship: SemanticRelationship) -> JoinStep:
        forward = current == relationship.from_entity
        source_entity = relationship.from_entity if forward else relationship.to_entity
        target_entity = relationship.to_entity if forward else relationship.from_entity
        source_column = relationship.from_column if forward else relationship.to_column
        target_column = relationship.to_column if forward else relationship.from_column
        cardinality = relationship.cardinality if forward else _reverse_cardinality(relationship.cardinality)
        if cardinality == "many_to_many":
            risk = "require_approval" if self.allow_many_to_many else "forbidden"
        elif cardinality == "one_to_many":
            risk = "require_approval"
        else:
            risk = "safe"
        return JoinStep(
            relationship_id=relationship.relationship_id,
            source_entity=source_entity,
            target_entity=target_entity,
            source_table=self.model.entities[source_entity].table_name,
            target_table=self.model.entities[target_entity].table_name,
            source_column=source_column,
            target_column=target_column,
            cardinality=cardinality,
            join_type=relationship.join_type,
            risk_level=risk,
        )

    def plan(self, base_entity: str, required_entities: list[str], output_grain: str | None = None) -> JoinPlan:
        if base_entity not in self.model.entities:
            raise ValueError(f"未知基础实体：{base_entity}")
        requested = list(dict.fromkeys([base_entity, *required_entities]))
        steps: list[JoinStep] = []
        seen_relationships: set[str] = set()
        errors: list[str] = []
        warnings: list[str] = []
        for target in sorted(requested):
            if target == base_entity:
                continue
            try:
                path = self.graph.shortest_path(base_entity, target)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            current = base_entity
            for relationship in path:
                step = self._orient_step(current, relationship)
                current = step.target_entity
                if relationship.relationship_id in seen_relationships:
                    continue
                seen_relationships.add(relationship.relationship_id)
                steps.append(step)
                if step.cardinality == "many_to_many":
                    message = f"关系 {step.relationship_id} 为多对多，可能造成重复累计。"
                    (warnings if self.allow_many_to_many else errors).append(message)
                elif step.cardinality == "one_to_many":
                    warnings.append(f"关系 {step.relationship_id} 从一侧连接到多侧，存在 fanout 风险。")
        fanout_count = sum(step.cardinality == "one_to_many" for step in steps)
        if fanout_count > 1:
            warnings.append("当前计划包含多条一对多路径，输出粒度可能发生冲突。")
        if errors:
            risk_level = "forbidden"
        elif any(step.risk_level == "require_approval" for step in steps) or fanout_count > 1:
            risk_level = "require_approval"
        elif warnings:
            risk_level = "warn"
        else:
            risk_level = "safe"
        canonical = {
            "model_id": self.model.model_id,
            "base_entity": base_entity,
            "required_entities": sorted(requested),
            "steps": [step.to_dict() for step in steps],
            "output_grain": output_grain or self.model.entities[base_entity].grain,
        }
        plan_id = "join_" + hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return JoinPlan(
            plan_id=plan_id,
            semantic_model_id=self.model.model_id,
            base_entity=base_entity,
            required_entities=sorted(requested),
            steps=steps,
            risk_level=risk_level,
            requires_approval=risk_level == "require_approval",
            executable=not errors,
            output_grain=output_grain or self.model.entities[base_entity].grain,
            warnings=warnings,
            errors=errors,
        )
