"""Command-line quality gate for local evaluation suites."""

from __future__ import annotations

import argparse
import json

from insightpilot.evaluation.harness import run_core_evaluation, run_determinism_evaluation, run_safety_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 InsightPilot 本地评估套件。")
    parser.add_argument("--suite", choices=["core", "safety", "determinism", "all"], default="all")
    parser.add_argument("--output-format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    runners = {
        "core": run_core_evaluation,
        "safety": run_safety_evaluation,
        "determinism": run_determinism_evaluation,
    }
    selected = runners if args.suite == "all" else {args.suite: runners[args.suite]}
    results = {name: runner().to_dict() for name, runner in selected.items()}
    if args.output_format == "json":
        print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    else:
        for name, result in results.items():
            print(f"评估套件={name} 总体得分={result['overall_score']:.6f} 通过={result['passed']}")
    passed = all(result["passed"] for result in results.values())
    thresholds_ok = all(
        result["overall_score"] >= (0.95 if name == "core" else 1.0)
        for name, result in results.items()
    )
    if not (passed and thresholds_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
