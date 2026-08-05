"""Deterministic lineage graph suitable for JSON and DOT export."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DatasetNode:
    node_id: str
    name: str
    dataset_type: str
    fingerprint: str = ""
    row_count: int | None = None
    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationNode:
    node_id: str
    operation_type: str
    display_name: str
    plan_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LineageEdge:
    source_id: str
    target_id: str
    relation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class LineageGraph:
    datasets: list[DatasetNode] = field(default_factory=list)
    operations: list[OperationNode] = field(default_factory=list)
    edges: list[LineageEdge] = field(default_factory=list)

    def add_dataset(self, node: DatasetNode) -> None:
        if node.node_id not in {item.node_id for item in self.datasets}:
            self.datasets.append(node)

    def add_operation(self, node: OperationNode) -> None:
        if node.node_id not in {item.node_id for item in self.operations}:
            self.operations.append(node)

    def add_edge(self, edge: LineageEdge) -> None:
        if edge not in self.edges:
            self.edges.append(edge)

    def fingerprint(self) -> str:
        payload = self.to_dict(include_fingerprint=False)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "datasets": [item.to_dict() for item in sorted(self.datasets, key=lambda value: value.node_id)],
            "operations": [item.to_dict() for item in sorted(self.operations, key=lambda value: value.node_id)],
            "edges": [item.to_dict() for item in sorted(self.edges, key=lambda value: (value.source_id, value.target_id, value.relation))],
        }
        if include_fingerprint:
            payload["lineage_fingerprint"] = self.fingerprint()
        return payload

    def to_dot(self) -> str:
        def safe(value: str) -> str:
            return re.sub(r"[^A-Za-z0-9_]", "_", value)

        lines = ["digraph lineage {"]
        for node in sorted(self.datasets, key=lambda item: item.node_id):
            lines.append(f'  {safe(node.node_id)} [label="{node.name}", shape=box];')
        for node in sorted(self.operations, key=lambda item: item.node_id):
            lines.append(f'  {safe(node.node_id)} [label="{node.display_name}", shape=ellipse];')
        for edge in sorted(self.edges, key=lambda item: (item.source_id, item.target_id, item.relation)):
            lines.append(f'  {safe(edge.source_id)} -> {safe(edge.target_id)} [label="{edge.relation}"];')
        lines.append("}")
        return "\n".join(lines)
