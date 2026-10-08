"""Built-in evaluation suites using only local synthetic data."""

from __future__ import annotations

import time
import pandas as pd
import numpy as np
from scipy import stats
from unittest.mock import patch
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.analysis.metric_diagnosis import _daily_series
from insightpilot.analysis.funnel_decomposition import decompose_transaction_funnel, FUNNEL_STAGES
from insightpilot.tools.duckdb_engine import AnalyticsEngine
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
                errors.extend(str(item) for item in actual.get("failures", []))
                scores = {key: float(value) for key, value in actual.get("scores", {}).items()}
                score = sum(scores.values()) / len(scores) if scores else float(actual.get("score", 0.0))
            except Exception as exc:
                scores = {}
                score = 0.0
                errors.append(str(exc))
            duration = round((time.perf_counter() - started) * 1000, 3)
            status = "FAIL" if errors else "PASS" if score >= case.minimum_score else ("WARN" if score > 0 else "FAIL")
            results.append(
                EvaluationResult(
                    case_id=case.case_id,
                    suite=case.suite,
                    status=status,
                    score=round(score, 6),
                    scores=scores,
                    duration_ms=duration,
                    errors=errors,
                    family=case.family,
                    actual_summary={**({"question": case.question, "input_fixture": case.input_fixture, "expected": case.expected, "required_evidence": list(case.required_evidence), "forbidden_behaviors": list(case.forbidden_behaviors)} if case.family else {}), **{key: value for key, value in actual.items() if key != "scores"}},
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

    def independent_ratio() -> dict[str, Any]:
        frame = pd.DataFrame({"date": ["2026-01-01"] * 2, "clicks": [1, 80], "impressions": [10, 100], "ctr": [0.1, 0.8]})
        actual = float(_daily_series(frame, "ctr")["metric_value"].iloc[0])
        return {"scores": {"numerical_correctness": NumericalCorrectnessScorer().score(81 / 110, actual)}, "expected": 81 / 110, "actual": actual}

    def independent_experiment() -> dict[str, Any]:
        frame = pd.DataFrame({"user_id": [1, 1, 2, 2, 3, 3, 4, 4], "group": ["control"] * 4 + ["treatment"] * 4, "outcome": [1, 3, 3, 5, 3, 5, 5, 7]})
        result = analyze_ab_test(frame, "group", "outcome")
        # Independent hand-derived user means [2,4] vs [4,6], delta=2, SE=sqrt(2), df=2.
        expected_p = float(2 * stats.t.sf(2 / np.sqrt(2), 2))
        expected_ci = [2 - stats.t.ppf(.975, 2) * np.sqrt(2), 2 + stats.t.ppf(.975, 2) * np.sqrt(2)]
        score = NumericalCorrectnessScorer()
        return {"scores": {"unit": float(result["sample_size"] == {"control": 2, "treatment": 2}), "numerical_correctness": score.score(expected_p, result["p_value"]), "confidence_interval": float(np.allclose(expected_ci, result["confidence_interval"]))}, "expected_p": expected_p, "actual_p": result["p_value"]}

    def independent_funnel() -> dict[str, Any]:
        base, current = [1000, 800, 600, 400, 300, 200, 100], [900, 720, 540, 360, 270, 180, 81]
        rows = [{"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), **dict(zip([x[0] for x in FUNNEL_STAGES], base if i < 7 else current))} for i in range(8)]
        result = decompose_transaction_funnel(pd.DataFrame(rows))
        actual = sum(item.estimated_order_impact for item in result)
        return {"scores": {"conservation": NumericalCorrectnessScorer().score(-19, actual)}, "expected": -19, "actual": actual}

    result = EvaluationHarness().run(
        [
            EvaluationCase("independent_weighted_ratio", "core", "独立小表手算81/110加权比率。", independent_ratio),
            EvaluationCase("independent_experiment_unit_ci", "core", "独立用户小表手算均值/自由度/区间。", independent_experiment),
            EvaluationCase("independent_funnel_conservation", "core", "独立小表验证七阶段净变化为-19。", independent_funnel),
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

    def external_access() -> dict[str, Any]:
        attacks = ["SELECT * FROM read_csv_auto('secret.csv')", "SELECT * FROM read_parquet('https://example.invalid/data')", "SELECT * FROM sqlite_scan('secret.db','users')", "SELECT * FROM 'secret.csv'", "SELECT 1; SELECT 2", "WITH x AS (SELECT 1) DELETE FROM orders", "SELECT getenv('HOME')"]
        scores = {}
        for index, sql in enumerate(attacks):
            try:
                AnalyticsEngine._validate_query(sql)
                scores[f"attack_{index + 1}"] = 0.0
            except ValueError:
                scores[f"attack_{index + 1}"] = 1.0
        return {"scores": scores, "attack_count": len(attacks)}

    def no_preview_execution() -> dict[str, Any]:
        plan = compiler.compile(MetricRequest(metrics=["order_count"], execution_mode="plan_only"))
        with patch.object(AnalyticsEngine, "run_parameterized_sql", side_effect=AssertionError("preview executed SQL")) as query:
            frame, review = execute_query_plan(plan, {})
        return {"scores": {"no_queries": float(query.call_count == 0 and frame is None and review.decision == "pending")}}

    result = EvaluationHarness().run(
        [
            EvaluationCase("external_access_rejections", "safety", "真实解析器拒绝文件/网络/表函数/多语句反例。", external_access),
            EvaluationCase("preview_no_execution", "safety", "拦截执行工具验证预览没有SQL调用。", no_preview_execution),
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

    def deterministic_statistics() -> dict[str, Any]:
        frame = pd.DataFrame({"group": ["control"] * 3 + ["treatment"] * 3, "value": [1, 2, 3, 2, 3, 5]})
        return {"scores": {"determinism": DeterminismScorer().score(analyze_ab_test(frame, "group", "value"), analyze_ab_test(frame, "group", "value"))}}

    result = EvaluationHarness().run(
        [EvaluationCase("stable_statistics", "determinism", "同一小表实验数值与区间保持一致。", deterministic_statistics), EvaluationCase("stable_query_plan", "determinism", "同一输入生成相同查询计划。", deterministic_plan, 1.0)]
    )
    return EvaluationSuiteResult(result.suite, result.overall_score, result.results, {"determinism": 1.0})
