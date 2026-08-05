"""Evaluation case and result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    suite: str
    description: str
    runner: Callable[[], dict[str, Any]]
    minimum_score: float = 1.0


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    suite: str
    status: str
    score: float
    scores: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    actual_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationSuiteResult:
    suite: str
    overall_score: float
    results: list[EvaluationResult]
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(result.status != "FAIL" for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        passed = sum(result.status == "PASS" for result in self.results)
        warned = sum(result.status == "WARN" for result in self.results)
        failed = sum(result.status == "FAIL" for result in self.results)
        slowest = max(self.results, key=lambda result: result.duration_ms).case_id if self.results else ""
        return {
            "suite": self.suite,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "passed_cases": passed,
            "warning_cases": warned,
            "failed_cases": failed,
            "slowest_case": slowest,
            "thresholds": dict(self.thresholds),
            "results": [result.to_dict() for result in self.results],
        }
