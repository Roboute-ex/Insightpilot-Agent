"""Analysis routines."""

from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.analysis.causal_light import estimate_adjusted_effect
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.analysis.package_builder import build_analysis_result_package, deduplicate_findings, findings_from_package
from insightpilot.analysis.results import (
    ActionRecommendation,
    AnalysisEvidence,
    AnalysisResultPackage,
    AnomalyResult,
    DimensionContributionResult,
    ExperimentComparisonResult,
    FunnelStageResult,
    MetricComparisonResult,
)

__all__ = [
    "analyze_ab_test",
    "detect_metric_anomaly",
    "dimension_contribution",
    "estimate_adjusted_effect",
    "ActionRecommendation",
    "AnalysisEvidence",
    "AnalysisResultPackage",
    "AnomalyResult",
    "DimensionContributionResult",
    "ExperimentComparisonResult",
    "FunnelStageResult",
    "MetricComparisonResult",
    "build_analysis_result_package",
    "deduplicate_findings",
    "findings_from_package",
]
