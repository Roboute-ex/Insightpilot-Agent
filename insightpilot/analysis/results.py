"""Structured analysis result protocol shared by workflows and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MetricComparisonResult:
    metric_id: str
    metric_name: str
    current_value: float
    baseline_value: float
    absolute_change: float
    relative_change: float
    current_period: str
    baseline_period: str
    sample_size: int
    unit: str
    direction: str
    severity: str
    z_score: float
    confidence_note: str


@dataclass(frozen=True)
class AnomalyResult:
    metric_id: str
    date: str
    actual_value: float
    expected_value: float
    lower_bound: float
    upper_bound: float
    deviation: float
    deviation_pct: float
    z_score: float
    severity: str
    method: str
    evidence: str


@dataclass(frozen=True)
class FunnelStageResult:
    stage_id: str
    stage_name: str
    current_count: float
    baseline_count: float
    current_rate: float
    baseline_rate: float
    rate_change_pp: float
    estimated_order_impact: float
    contribution_pct: float
    severity: str


@dataclass(frozen=True)
class DimensionContributionResult:
    metric_id: str
    dimension: str
    dimension_value: str
    current_value: float
    baseline_value: float
    absolute_change: float
    relative_change: float
    contribution_value: float
    contribution_pct: float
    rank: int
    sample_size: int
    confidence_flag: str


@dataclass(frozen=True)
class ExperimentComparisonResult:
    metric_id: str
    metric_name: str
    control_group: str
    treatment_group: str
    control_value: float
    treatment_value: float
    control_sample_size: int
    treatment_sample_size: int
    total_sample_size: int
    absolute_lift: float
    relative_lift: float
    p_value: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    confidence_level: float
    is_significant: bool
    significance_conclusion: str
    method: str


@dataclass(frozen=True)
class AnalysisEvidence:
    evidence_id: str
    claim: str
    metric: str
    method: str
    result_table: str
    supporting_values: dict[str, Any]
    confidence: str
    caveat: str


@dataclass(frozen=True)
class ActionRecommendation:
    priority: str
    action: str
    reason: str
    supporting_evidence_ids: tuple[str, ...]
    suggested_owner: str
    verification_metric: str
    expected_direction: str
    limitation: str


@dataclass
class AnalysisResultPackage:
    run_id: str
    scenario: str
    question: str
    executive_summary: str
    metric_comparisons: list[MetricComparisonResult] = field(default_factory=list)
    anomalies: list[AnomalyResult] = field(default_factory=list)
    funnel_results: list[FunnelStageResult] = field(default_factory=list)
    dimension_contributions: list[DimensionContributionResult] = field(default_factory=list)
    experiment_results: list[ExperimentComparisonResult] = field(default_factory=list)
    evidence: list[AnalysisEvidence] = field(default_factory=list)
    recommendations: list[ActionRecommendation] = field(default_factory=list)
    result_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def result_table_summaries(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "row_count": int(len(frame)),
                "columns": [str(column) for column in frame.columns],
            }
            for name, frame in self.result_tables.items()
            if isinstance(frame, pd.DataFrame)
        }

    def to_dict_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "question": self.question,
            "executive_summary": self.executive_summary,
            "metric_comparisons": [asdict(item) for item in self.metric_comparisons],
            "anomalies": [asdict(item) for item in self.anomalies],
            "funnel_results": [asdict(item) for item in self.funnel_results],
            "dimension_contributions": [asdict(item) for item in self.dimension_contributions],
            "experiment_results": [asdict(item) for item in self.experiment_results],
            "evidence": [asdict(item) for item in self.evidence],
            "recommendations": [asdict(item) for item in self.recommendations],
            "result_tables": self.result_table_summaries(),
            "chart_specs": list(self.chart_specs),
            "caveats": list(self.caveats),
            "metadata": dict(self.metadata),
            "has_structured_results": self.has_structured_results(),
        }

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.run_id:
            issues.append("run_id is required")
        if not self.question:
            issues.append("question is required")
        if not self.executive_summary:
            issues.append("executive_summary is required")
        if not self.has_structured_results():
            issues.append("at least one non-empty result table is required")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            issues.append("evidence_id values must be unique")
        for recommendation in self.recommendations:
            if not recommendation.supporting_evidence_ids:
                issues.append("recommendation must reference at least one evidence_id")
            missing = set(recommendation.supporting_evidence_ids) - evidence_ids
            if missing:
                issues.append(f"recommendation references unknown evidence: {', '.join(sorted(missing))}")
        for name, frame in self.result_tables.items():
            if not isinstance(frame, pd.DataFrame):
                issues.append(f"result table {name} is not a DataFrame")
        return issues

    def has_structured_results(self) -> bool:
        return any(isinstance(frame, pd.DataFrame) and not frame.empty for frame in self.result_tables.values())


def records_frame(values: list[Any]) -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in values])


__all__ = [
    "ActionRecommendation",
    "AnalysisEvidence",
    "AnalysisResultPackage",
    "AnomalyResult",
    "DimensionContributionResult",
    "ExperimentComparisonResult",
    "FunnelStageResult",
    "MetricComparisonResult",
    "records_frame",
]
