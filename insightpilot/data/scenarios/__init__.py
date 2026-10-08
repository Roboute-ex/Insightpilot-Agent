"""Independently load only the requested deterministic demo scenario."""
from .common import DemoDataset, DemoScale
from .content import generate_content_scenario
from .live import generate_live_scenario
from .transaction import generate_transaction_scenario
from .quality import with_quality_issues


def generate_demo_scenario(scenario: str, scale: str | DemoScale = "standard", seed: int = 42) -> DemoDataset:
    generators = {"transaction": generate_transaction_scenario, "content": generate_content_scenario, "live": generate_live_scenario}
    if scenario in {"multi_table", "multi_table_commerce"}:
        from insightpilot.data.synthetic import generate_multi_table_commerce_data
        from .common import metadata
        DemoScale(scale)
        tables = generate_multi_table_commerce_data(seed=seed)
        return DemoDataset("multi_table_commerce", tables, metadata("multi_table_commerce", scale, seed, tables, [], scale_note="原有七表商业演示保持原规模；scale 不改变此历史场景的规模。"))
    try:
        generate = generators[scenario]
    except KeyError as exc:
        raise ValueError(f"未知模拟场景：{scenario}") from exc
    return generate(scale=scale, seed=seed)


__all__ = ["DemoDataset", "DemoScale", "generate_demo_scenario", "generate_transaction_scenario", "generate_content_scenario", "generate_live_scenario", "generate_scenario", "with_quality_issues"]

# CLI-compatible concise name; the existing UI name remains stable.
generate_scenario = generate_demo_scenario
