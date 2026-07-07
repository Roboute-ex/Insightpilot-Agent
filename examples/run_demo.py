"""Run built-in synthetic demo scenarios from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data
from insightpilot.planning.goal_modes import GOAL_MODE_DISPLAY_NAMES
from insightpilot.reports.export import write_text_report


SCENARIO_QUESTIONS = {
    "transaction": "为什么昨天某城市订单量下降？",
    "content": "新策略是否提升了内容完播率？",
    "live": "请定位直播体验异常的主要维度。",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run InsightPilot Agent synthetic demos.")
    parser.add_argument(
        "--scenario",
        choices=["transaction", "content", "live", "all"],
        default="transaction",
        help="Demo scenario to run.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Synthetic data seed.")
    parser.add_argument(
        "--goal-mode",
        choices=list(GOAL_MODE_DISPLAY_NAMES.keys()),
        default="auto",
        help="Analysis goal mode. Defaults to auto.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tables = generate_all_demo_data(seed=args.seed)
    scenarios = SCENARIO_QUESTIONS.keys() if args.scenario == "all" else [args.scenario]
    report_dir = PROJECT_ROOT / "reports"
    for scenario in scenarios:
        question = SCENARIO_QUESTIONS[scenario]
        result = run_agent_analysis(question, tables, goal_mode=args.goal_mode)
        report_path = write_text_report(report_dir / f"{scenario}_report.md", result["report_markdown"])
        print(
            f"[{scenario}] intent={result['intent']} goal_mode={result['goal_mode']} "
            f"source={result['goal_mode_source']} reviewer={result['reviewer']['status']}"
        )
        print(f"report: {report_path}")
        for finding in result["findings"][:3]:
            print(f"- {finding}")


if __name__ == "__main__":
    main()
