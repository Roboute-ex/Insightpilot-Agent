"""Synthetic data helpers."""

from insightpilot.data.synthetic import generate_all_demo_data, generate_multi_table_commerce_data

__all__ = ["generate_all_demo_data", "generate_multi_table_commerce_data", "DemoDataset", "DemoScale", "generate_demo_scenario", "generate_scenario"]

from insightpilot.data.scenarios import DemoDataset, DemoScale, generate_demo_scenario, generate_scenario
