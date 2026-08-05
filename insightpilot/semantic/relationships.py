"""Standard-library relationship graph traversal."""

from __future__ import annotations

from collections import deque

from insightpilot.semantic.models import SemanticModel, SemanticRelationship


class RelationshipGraph:
    """Undirected traversal view over directed semantic relationships."""

    def __init__(self, model: SemanticModel) -> None:
        self.model = model
        self._adjacency: dict[str, list[tuple[str, SemanticRelationship]]] = {
            entity_id: [] for entity_id in model.entities
        }
        for relationship in model.relationships:
            self._adjacency[relationship.from_entity].append((relationship.to_entity, relationship))
            self._adjacency[relationship.to_entity].append((relationship.from_entity, relationship))
        for neighbors in self._adjacency.values():
            neighbors.sort(key=lambda item: (item[0], item[1].relationship_id))

    def neighbors(self, entity_id: str) -> list[str]:
        return [neighbor for neighbor, _ in self._adjacency.get(entity_id, [])]

    def shortest_path(self, source: str, target: str) -> list[SemanticRelationship]:
        if source not in self._adjacency or target not in self._adjacency:
            raise ValueError("Join 路径包含未知实体。")
        if source == target:
            return []
        queue: deque[tuple[str, list[SemanticRelationship]]] = deque([(source, [])])
        visited = {source}
        while queue:
            current, path = queue.popleft()
            for neighbor, relationship in self._adjacency[current]:
                if neighbor in visited:
                    continue
                next_path = [*path, relationship]
                if neighbor == target:
                    return next_path
                visited.add(neighbor)
                queue.append((neighbor, next_path))
        raise ValueError(f"实体 {source} 与 {target} 之间没有可用 Join 路径。")

    def connected_entities(self, source: str) -> list[str]:
        if source not in self._adjacency:
            return []
        stack = [source]
        visited: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(reversed(self.neighbors(current)))
        return sorted(visited)

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model.model_id,
            "entities": sorted(self.model.entities),
            "relationships": [item.to_dict() for item in sorted(self.model.relationships, key=lambda item: item.relationship_id)],
        }
