from __future__ import annotations

import pytest

from insightpilot.semantic.catalog import load_builtin_catalog, load_semantic_model_yaml
from insightpilot.semantic.validate import validate_builtin_models


def test_builtin_semantic_catalog_is_valid_and_deterministic() -> None:
    first = load_builtin_catalog()
    second = load_builtin_catalog()
    model = first.get("commerce_demo")
    assert model.validate() == []
    assert first.fingerprint() == second.fingerprint()
    assert set(model.entities) == {"customers", "sessions", "orders", "order_items", "products", "channels", "calendar"}
    assert {metric.metric_type for metric in model.metrics.values()} == {"simple", "ratio", "derived", "cumulative"}
    assert validate_builtin_models()["status"] == "PASS"


def test_semantic_yaml_loader_uses_safe_construction() -> None:
    with pytest.raises(ValueError, match="YAML"):
        load_semantic_model_yaml("!!python/object/apply:os.system ['echo unsafe']")
