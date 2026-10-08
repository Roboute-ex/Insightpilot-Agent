from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_multi_table_commerce_data


def _all_dict_keys_are_ascii(value: object) -> bool:
    if isinstance(value, dict):
        return all(str(key).isascii() and _all_dict_keys_are_ascii(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_all_dict_keys_are_ascii(item) for item in value)
    return True


def test_query_plan_and_manifest_keep_stable_english_keys() -> None:
    result = run_agent_analysis(
        "按城市分析总金额",
        generate_multi_table_commerce_data(seed=42),
        playbook_id="semantic_metric_query",
        playbook_parameters={"metric": "total_revenue", "dimensions": ["customer_city"]},
    )
    query_plan = result["query_plan"]
    assert set(query_plan) == {
        "plan_id",
        "semantic_model_id",
        "request",
        "base_entity",
        "metric_dependencies",
        "required_entities",
        "join_plan",
        "sql_template",
        "parameters",
        "parameter_count",
        "output_columns",
        "risk_level",
        "requires_approval",
        "executable",
        "warnings",
        "errors",
        "model_fingerprint",
        "data_fingerprint",
        "compiler_version",
        "sql_policy_version",
        "entity_keys",
    }
    assert len(query_plan["model_fingerprint"]) == 64
    assert len(query_plan["data_fingerprint"]) == 64
    assert query_plan["compiler_version"] == "0.1.0"
    from insightpilot.tools.sql_safety import SQL_POLICY_VERSION
    assert query_plan["sql_policy_version"] == SQL_POLICY_VERSION
    manifest = result["run_manifest"]
    assert {"manifest_version", "project_version", "run_id", "created_at", "workflow_backend", "route_taken", "semantic_model_id", "query_plan_id", "lineage_summary", "telemetry_summary"}.issubset(manifest)
    assert _all_dict_keys_are_ascii(query_plan)
    assert _all_dict_keys_are_ascii(manifest)
