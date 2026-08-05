"""Built-in evaluation suites using only local synthetic data."""

from __future__ import annotations

import time
from typing import Any

from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.evaluation.models import EvaluationCase, EvaluationResult, EvaluationSuiteResult
from insightpilot.evaluation.scorers import DeterminismScorer, NumericalCorrectnessScorer, PlanValidityScorer, SQLSafetyScorer
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.compiler import MetricCompiler, execute_query_plan
from insightpilot.semantic.query import MetricRequest


class EvaluationHarness:
    def run(self, cases: list[EvaluationCase]) -> EvaluationSuiteResult:
        results: list[EvaluationResult] = []
        for case in cases:
            started = time.perf_counter()
            errors: list[str] = []
            actual: dict[str, Any] = {}
            try:
                actual = case.runner()
                scores = {key: float(value) for key, value in actual.get("scores", {}).items()}
                score = sum(scores.values()) / len(scores) if scores else float(actual.get("score", 0.0))
            except Exception as exc:
                scores = {}
                score = 0.0
                errors.append(str(exc))
            duration = round((time.perf_counter() - started) * 1000, 3)
            status = "PASS" if score >= case.minimum_score else ("WARN" if score > 0 else "FAIL")
            results.append(
                EvaluationResult(
                    case_id=case.case_id,
                    suite=case.suite,
                    status=status,
                    score=round(score, 6),
                    scores=scores,
                    duration_ms=duration,
                    errors=errors,
                    actual_summary={key: value for key, value in actual.items() if key != "scores"},
                )
            )
        suite = cases[0].suite if cases else "empty"
        overall = sum(result.score for result in results) / len(results) if results else 0.0
        return EvaluationSuiteResult(suite, round(overall, 6), results)


def _compiler_fixture() -> tuple[MetricCompiler, dict[str, Any]]:
    model = load_builtin_catalog().get("commerce_demo")
    return MetricCompiler(model), generate_multi_table_commerce_data(seed=42)


def run_core_evaluation() -> EvaluationSuiteResult:
    compiler, tables = _compiler_fixture()

    def plan_case() -> dict[str, Any]:
        request = MetricRequest(metrics=["total_revenue"], dimensions=["customer_city"])
        plan = compiler.compile(request)
        return {"scores": {"plan_validity": PlanValidityScorer().score(plan), "sql_safety": SQLSafetyScorer().score(plan)}}

    def numerical_case() -> dict[str, Any]:
        request = MetricRequest(metrics=["total_revenue"], dimensions=[])
        plan = compiler.compile(request)
        frame, review = execute_query_plan(plan, tables)
        actual = float(frame["total_revenue"].iloc[0]) if frame is not None else float("nan")
        expected = float(tables["orders"]["total_amount"].sum())
        return {
            "scores": {"numerical_correctness": NumericalCorrectnessScorer().score(expected, actual, tolerance=1e-9)},
            "review": review.decision,
        }

    result = EvaluationHarness().run(
        [
            EvaluationCase("semantic_plan_validity", "core", "检查语义查询计划结构与 SQL 安全。", plan_case, 1.0),
            EvaluationCase("semantic_numerical_correctness", "core", "核对语义聚合与本地直接计算。", numerical_case, 0.98),
        ]
    )
    return EvaluationSuiteResult(result.suite, result.overall_score, result.results, {"overall": 0.95, "numerical_correctness": 0.98})


def run_safety_evaluation() -> EvaluationSuiteResult:
    compiler, _ = _compiler_fixture()

    def safe_plan() -> dict[str, Any]:
        plan = compiler.compile(
            MetricRequest(
                metrics=["order_count"],
                dimensions=["customer_segment"],
                filters=[],
                execution_mode="plan_only",
            )
        )
        return {"scores": {"sql_safety": SQLSafetyScorer().score(plan), "plan_only": float(plan.request.execution_mode == "plan_only")}}

    def reject_write() -> dict[str, Any]:
        return {"scores": {"reject_write_sql": 1.0 - SQLSafetyScorer().score("DELETE FROM orders")}}

    result = EvaluationHarness().run(
        [
            EvaluationCase("safe_parameterized_plan", "safety", "安全参数化只读计划。", safe_plan, 1.0),
            EvaluationCase("reject_write_sql", "safety", "拒绝写操作 SQL。", reject_write, 1.0),
        ]
    )
    return EvaluationSuiteResult(result.suite, result.overall_score, result.results, {"sql_safety": 1.0})


def run_determinism_evaluation() -> EvaluationSuiteResult:
    compiler, _ = _compiler_fixture()

    def deterministic_plan() -> dict[str, Any]:
        request = MetricRequest(metrics=["average_order_value"], dimensions=["customer_city"], execution_mode="plan_only")
        first = compiler.compile(request)
        second = compiler.compile(request)
        return {"scores": {"determinism": DeterminismScorer().score(first, second)}}

    result = EvaluationHarness().run(
        [EvaluationCase("stable_query_plan", "determinism", "同一输入生成相同查询计划。", deterministic_plan, 1.0)]
    )
    return EvaluationSuiteResult(result.suite, result.overall_score, result.results, {"determinism": 1.0})
