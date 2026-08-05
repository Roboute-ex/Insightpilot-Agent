"""Small deterministic scorers used by local evaluation suites."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from insightpilot.contracts.models import ContractCheckResult
from insightpilot.semantic.join_planner import JoinPlan
from insightpilot.semantic.query import QueryPlan
from insightpilot.tools.duckdb_engine import AnalyticsEngine


class PlanValidityScorer:
    def score(self, plan: QueryPlan | dict[str, Any]) -> float:
        values = plan.to_dict() if hasattr(plan, "to_dict") else plan
        required = ["plan_id", "semantic_model_id", "sql_template", "output_columns", "risk_level", "executable"]
        return 1.0 if isinstance(values, dict) and all(key in values for key in required) and bool(values.get("plan_id")) else 0.0


class JoinPathScorer:
    def score(self, plan: JoinPlan | dict[str, Any]) -> float:
        values = plan.to_dict() if hasattr(plan, "to_dict") else plan
        if not isinstance(values, dict) or not values.get("base_entity"):
            return 0.0
        steps = values.get("steps", [])
        required = set(values.get("required_entities", []))
        covered = {values["base_entity"]}
        for step in steps:
            if isinstance(step, dict):
                covered.update([step.get("source_entity"), step.get("target_entity")])
        return 1.0 if required.issubset(covered) else 0.0


class SQLSafetyScorer:
    def score(self, sql_or_plan: str | QueryPlan | dict[str, Any]) -> float:
        if isinstance(sql_or_plan, str):
            sql = sql_or_plan
        elif hasattr(sql_or_plan, "sql_template"):
            sql = str(sql_or_plan.sql_template)
        elif isinstance(sql_or_plan, dict):
            sql = str(sql_or_plan.get("sql_template", ""))
        else:
            return 0.0
        try:
            AnalyticsEngine._validate_query(sql)
        except ValueError:
            return 0.0
        return 1.0


class NumericalCorrectnessScorer:
    def score(self, expected: Any, actual: Any, tolerance: float = 1e-8) -> float:
        if isinstance(expected, pd.DataFrame) and isinstance(actual, pd.DataFrame):
            if list(expected.columns) != list(actual.columns) or expected.shape != actual.shape:
                return 0.0
            left = expected.reset_index(drop=True)
            right = actual.reset_index(drop=True)
            matches: list[bool] = []
            for column in left.columns:
                if pd.api.types.is_numeric_dtype(left[column]) and pd.api.types.is_numeric_dtype(right[column]):
                    matches.extend(np.isclose(left[column].to_numpy(), right[column].to_numpy(), rtol=tolerance, atol=tolerance, equal_nan=True).tolist())
                else:
                    matches.extend((left[column].astype(str) == right[column].astype(str)).tolist())
            return float(sum(matches) / len(matches)) if matches else 1.0
        try:
            return 1.0 if math.isclose(float(expected), float(actual), rel_tol=tolerance, abs_tol=tolerance) else 0.0
        except (TypeError, ValueError):
            return 1.0 if expected == actual else 0.0


class DeterminismScorer:
    VOLATILE_KEYS = {"trace_id", "run_id", "created_at", "started_at", "ended_at", "duration_ms", "span_id"}

    def _normalize(self, value: Any) -> Any:
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        if isinstance(value, dict):
            return {key: self._normalize(item) for key, item in sorted(value.items()) if key not in self.VOLATILE_KEYS}
        if isinstance(value, list):
            return [self._normalize(item) for item in value]
        return value

    def score(self, first: Any, second: Any) -> float:
        left = json.dumps(self._normalize(first), ensure_ascii=False, sort_keys=True, default=str)
        right = json.dumps(self._normalize(second), ensure_ascii=False, sort_keys=True, default=str)
        return 1.0 if left == right else 0.0


class TraceCompletenessScorer:
    def score(self, trace: dict[str, Any]) -> float:
        required = ["trace_id", "created_at", "workflow_backend", "route_taken", "caveats", "errors"]
        return sum(key in trace for key in required) / len(required) if isinstance(trace, dict) else 0.0


class LineageCompletenessScorer:
    def score(self, lineage: dict[str, Any]) -> float:
        if not isinstance(lineage, dict):
            return 0.0
        checks = [bool(lineage.get("datasets")), bool(lineage.get("operations")), bool(lineage.get("edges")), bool(lineage.get("lineage_fingerprint"))]
        return sum(checks) / len(checks)


class ReviewerConsistencyScorer:
    def score(self, reviewer: dict[str, Any]) -> float:
        if not isinstance(reviewer, dict):
            return 0.0
        status = reviewer.get("status")
        score = reviewer.get("score")
        checks = reviewer.get("checks")
        if status not in {"PASS", "WARN", "FAIL"} or not isinstance(score, (int, float)) or not isinstance(checks, dict):
            return 0.0
        consistent = (status == "PASS" and score >= 80) or (status == "WARN" and score < 100) or (status == "FAIL" and score < 80)
        return 1.0 if consistent else 0.0


class ExportIntegrityScorer:
    def score(self, export_value: str | bytes, required_markers: list[str] | None = None) -> float:
        if isinstance(export_value, bytes):
            passed = len(export_value) > 100
            text = export_value[:1000].decode("utf-8", errors="ignore")
        else:
            passed = bool(export_value.strip())
            text = export_value
        if required_markers:
            passed = passed and all(marker in text for marker in required_markers)
        lowered = text.lower()
        passed = passed and not any(token in lowered for token in ["api_key=", "password=", "token="])
        return 1.0 if passed else 0.0


class ContractComplianceScorer:
    def score(self, results: list[ContractCheckResult | dict[str, Any]]) -> float:
        if not results:
            return 1.0
        passed = 0
        for item in results:
            status = item.status if isinstance(item, ContractCheckResult) else item.get("status")
            passed += status == "PASS"
        return passed / len(results)
