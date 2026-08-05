"""Dependency-free local tracing and optional OpenTelemetry bridge."""

from insightpilot.observability.tracer import LocalTracer, ObservabilitySummary, TraceSpan
from insightpilot.observability.otel import (
    OpenTelemetryPreview,
    get_opentelemetry_preview,
    opentelemetry_available,
    trace_attributes,
)

__all__ = [
    "LocalTracer",
    "ObservabilitySummary",
    "OpenTelemetryPreview",
    "TraceSpan",
    "get_opentelemetry_preview",
    "opentelemetry_available",
    "trace_attributes",
]
