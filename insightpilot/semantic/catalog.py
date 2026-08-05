"""Deterministic semantic model catalog with safe YAML loading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from insightpilot.semantic.models import SemanticModel, semantic_model_from_dict


def load_semantic_model_yaml(source: str | bytes | Path) -> SemanticModel:
    """Load one semantic model with ``yaml.safe_load`` only."""

    if isinstance(source, Path):
        content = source.read_text(encoding="utf-8")
    elif isinstance(source, bytes):
        content = source.decode("utf-8")
    else:
        content = source
    try:
        values = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"语义模型 YAML 无法解析：{exc}") from exc
    return semantic_model_from_dict(values)


class SemanticCatalog:
    """In-memory allowlist of validated semantic models."""

    def __init__(self) -> None:
        self._models: dict[str, SemanticModel] = {}

    def register(self, model: SemanticModel) -> None:
        if model.model_id in self._models:
            raise ValueError(f"semantic model 已存在：{model.model_id}")
        errors = model.validate()
        if errors:
            raise ValueError("semantic model 校验失败：" + "；".join(errors))
        self._models[model.model_id] = model

    def load_yaml(self, source: str | bytes | Path) -> SemanticModel:
        model = load_semantic_model_yaml(source)
        self.register(model)
        return model

    def load_directory(self, directory: str | Path) -> list[SemanticModel]:
        root = Path(directory)
        loaded: list[SemanticModel] = []
        for path in sorted([*root.glob("*.yaml"), *root.glob("*.yml")]):
            loaded.append(self.load_yaml(path))
        return loaded

    def get(self, model_id: str) -> SemanticModel:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise ValueError(f"未找到语义模型：{model_id}") from exc

    def list_models(self) -> list[SemanticModel]:
        return [self._models[key] for key in sorted(self._models)]

    def to_dict(self) -> dict[str, Any]:
        return {"models": [model.to_dict() for model in self.list_models()], "fingerprint": self.fingerprint()}

    def fingerprint(self) -> str:
        payload = [model.to_dict() for model in self.list_models()]
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_builtin_catalog() -> SemanticCatalog:
    catalog = SemanticCatalog()
    catalog.load_directory(Path(__file__).with_name("models"))
    return catalog
