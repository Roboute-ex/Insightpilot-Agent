"""Run guided independent tasks and (optionally) all examples with variants.

Usage: .venv/Scripts/python.exe scripts/check_guided_cases.py --examples --scale standard
Reports contain synthetic fixture results only. No baseline auto-update occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.example_questions import get_example_questions
from insightpilot.data.scenarios import generate_demo_scenario
from insightpilot.evaluation.guided_suite import build_guided_task_cases
from insightpilot.evaluation.harness import EvaluationHarness
from insightpilot.planning.planner import prepare_analysis_request

# Human-authored paraphrases retain the original intent, independently of advisor.
VARIANTS = (
    ("tx01", "请解释最近完整日的订单量下滑，按历史基准看看哪些维度变化了", "route:legacy"),
    ("tx02", "收入过去30天走势怎么样？", "playbook:metric_trend"),
    ("tx03", "订单量按城市拆开后各占多少？", "playbook:dimension_contribution"),
    ("tx11", "不做因果推断，只比较本周和上周订单量", "playbook:period_comparison"),
    ("ct02", "AB实验中处理组相对对照组的完播率提高了吗？", "playbook:experiment_comparison"),
    ("ct10", "在控制历史活跃度等协变量后，策略和完播率有什么关联？", "playbook:causal_exploration"),
    ("lv03", "按客户端版本比较直播崩溃率", "playbook:dimension_contribution"),
    ("tx15", "订单明细的空值与重复记录情况如何？", "playbook:data_profile"),
)
BLOCKED_VARIANTS = (
    ("forecast_30", "未来30天的订单量会是多少？请预测", "unsupported"),
    ("prove_cause", "证明城市导致订单量下降的因果关系", "unsupported"),
    ("incomplete", "分析一下", "needs_clarification"),
    ("empty", "", ("invalid_input", "needs_clarification")),
)


def _request(example, question):
    config = example.apply_settings()
    return {"question": question, "goal_mode": "auto", "playbook_id": None,
            "column_mapping": config["column_mapping"], "playbook_parameters": config["parameters"]}


def _example_row(identifier, kind, scenario, question, request, expected_method, prepared):
    started = time.perf_counter()
    row = {"case_id": identifier, "kind": kind, "scenario": scenario, "question": question,
           "expected": {"planning_status": "ready", "effective_method": expected_method, "execution_status": "COMPLETED"}}
    try:
        planned = prepare_analysis_request(**request, table_metadata=prepared.metadata, dataset_revision=prepared.revision, selection_source="example_applied")
        advice = planned.get("analysis_advice", {})
        actual = run_agent_analysis(**request, tables={}, prepared_dataset=prepared,
                                    presentation_mode="deferred", data_source_type="synthetic")
        actual_advice = actual.get("analysis_advice", actual.get("preflight", {}))
        method = advice.get("effective_method", {}).get("method_ref")
        tables = actual.get("result_tables", {})
        checks = {"planning_ready": planned.get("planning_status") == "ready",
                  "method_matches_intent": method == expected_method,
                  "execution_completed": actual.get("execution_status") == "COMPLETED",
                  "real_result_tables": bool(tables) and sum(len(table) for table in tables.values()) > 0,
                  "workflow_method_matches": actual_advice.get("effective_method", {}).get("method_ref") == method}
        row.update(passed=all(checks.values()), checks=checks,
                   planning_status=planned.get("planning_status"), effective_method=method,
                   recommended_method=advice.get("recommended_method", {}).get("method_ref"),
                   execution_status=actual.get("execution_status"), blocking_issues=advice.get("blocking_issues", []),
                   result_tables={name: len(table) for name, table in tables.items()},
                   metric_ids=[item.get("metric_id") for item in actual.get("metric_definitions", [])])
    except Exception as exc:
        row.update(passed=False, error=f"{type(exc).__name__}: {exc}")
    row["duration_seconds"] = round(time.perf_counter() - started, 6)
    return row


def check_examples(scale):
    from unittest.mock import patch
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    examples = get_example_questions(); by_id = {item.question_id: item for item in examples}
    prepared = {}
    rows = []
    for scenario in ("transaction", "content", "live"):
        dataset = generate_demo_scenario(scenario, scale=scale, seed=42)
        prepared[scenario] = PreparedDataset.from_tables(dataset.tables, dataset_id="guided-examples-" + scenario, revision="fixture-v1")
        for item in [entry for entry in examples if entry.scenario == scenario]:
            expected = "playbook:" + item.recommended_playbook if item.recommended_playbook else "route:legacy"
            rows.append(_example_row(item.question_id, "original", scenario, item.question_zh,
                                     _request(item, item.question_zh), expected, prepared[scenario]))
    for identifier, question, expected in VARIANTS:
        item = by_id[identifier]
        rows.append(_example_row(identifier + "_paraphrase", "paraphrase", item.scenario, question,
                                 _request(item, question), expected, prepared[item.scenario]))
    for identifier, question, expected in BLOCKED_VARIANTS:
        snap = prepared["transaction"]
        with patch.object(AnalyticsEngine, "run_sql", side_effect=AssertionError("blocked query")) as query, patch.object(AnalyticsEngine, "run_parameterized_sql", side_effect=AssertionError("blocked parameterized query")) as bound:
            planned = prepare_analysis_request(question, table_metadata=snap.metadata, dataset_revision=snap.revision)
            actual = run_agent_analysis(question, {}, prepared_dataset=snap, presentation_mode="deferred")
        row = {"case_id": identifier, "kind": "boundary", "question": question,
               "expected": {"planning_status": expected, "sql_calls": 0},
               "planning_status": planned.get("planning_status"), "execution_status": actual.get("execution_status"),
               "sql_calls": query.call_count + bound.call_count,
               "effective_method": planned.get("analysis_advice", {}).get("effective_method", {}).get("method_ref")}
        row["passed"] = row["planning_status"] in ((expected,) if isinstance(expected, str) else expected) and row["sql_calls"] == 0 and row["execution_status"] != "COMPLETED"
        rows.append(row)
    groups = {}
    for kind in ("original", "paraphrase", "boundary"):
        subset = [row for row in rows if row["kind"] == kind]
        groups[kind] = {"total": len(subset), "passed": sum(row["passed"] for row in subset),
                        "planning_statuses": dict(Counter(row.get("planning_status", "exception") for row in subset)),
                        "execution_statuses": dict(Counter(row.get("execution_status", "exception") for row in subset)),
                        "effective_methods": dict(Counter(row.get("effective_method", "exception") for row in subset))}
    return {"scale": scale, "passed": all(row["passed"] for row in rows), "groups": groups, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description="独立小表、39个示例及中文变体的引导分析验收。")
    parser.add_argument("--examples", action="store_true", help="同时实际执行39个示例和中文变体")
    parser.add_argument("--scale", choices=("small", "standard", "large"), default="standard")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "reports" / "guided" / ("guided-cases-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    tasks = EvaluationHarness().run(build_guided_task_cases()).to_dict()
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "guided_task": tasks}
    if args.examples:
        result["examples"] = check_examples(args.scale)
    result["passed"] = tasks["passed"] and (not args.examples or result["examples"]["passed"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "report": str(output.resolve()),
                      "guided_task": {key: tasks[key] for key in ("passed_cases", "failed_cases", "task_families")},
                      "examples": result.get("examples", {}).get("groups")}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
