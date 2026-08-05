from __future__ import annotations

from dataclasses import replace

from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.join_planner import JoinPlanner
from insightpilot.semantic.models import SemanticRelationship
from insightpilot.semantic.relationships import RelationshipGraph


def test_relationship_graph_uses_stable_shortest_paths() -> None:
    model = load_builtin_catalog().get("commerce_demo")
    graph = RelationshipGraph(model)
    path = graph.shortest_path("order_items", "customers")
    assert [item.relationship_id for item in path] == ["order_items_to_orders", "orders_to_customers"]
    assert graph.connected_entities("orders") == sorted(model.entities)


def test_join_planner_flags_fanout_and_forbids_many_to_many() -> None:
    model = load_builtin_catalog().get("commerce_demo")
    fanout = JoinPlanner(model).plan("customers", ["orders"])
    assert fanout.risk_level == "require_approval"
    assert fanout.requires_approval is True
    assert fanout.executable is True

    relationship = SemanticRelationship(
        relationship_id="customers_to_products",
        from_entity="customers",
        to_entity="products",
        from_column="customer_id",
        to_column="product_id",
        cardinality="many_to_many",
    )
    unsafe_model = replace(model, relationships=[relationship])
    forbidden = JoinPlanner(unsafe_model).plan("customers", ["products"])
    assert forbidden.risk_level == "forbidden"
    assert forbidden.executable is False
    assert forbidden.errors
