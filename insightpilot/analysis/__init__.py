"""Analysis routines."""

from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.analysis.causal_light import estimate_adjusted_effect
from insightpilot.analysis.experiments import analyze_ab_test

__all__ = [
    "analyze_ab_test",
    "detect_metric_anomaly",
    "dimension_contribution",
    "estimate_adjusted_effect",
]
