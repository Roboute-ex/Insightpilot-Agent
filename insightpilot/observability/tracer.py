"""Local in-memory tracing without network export."""

from __future__ import annotations

import importlib.util
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any, Iterator
from uuid import uuid4

from insightpilot.performance_tasks import TaskCancelledError, cancellation_checkpoint, report_stage



def _sanitize_trace_value(value: Any, key: str = "") -> Any:
    """Keep trace attributes serializable without importing the report package."""

    if isinstance(value, dict):
        return {str(item_key): _sanitize_trace_value(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_trace_value(item, key) for item in value]
    if isinstance(value, str):
        lowered = key.lower()
        if any(term in lowered for term in ("password", "passwd", "token", "secret", "api_key", "credential")):
            return "***"
        masked = re.sub(r"(://[^:/@\s]+:)[^@/\s]+(@)", r"\1***\2", value)
        if any(term in lowered for term in ("path", "file", "source_name")) and (
            re.match(r"^[A-Za-z]:[\\/]", masked) or masked.startswith("/")
        ):
            return PurePath(masked).name
        return masked
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    return value


@dataclass
class TraceSpan:
    span_id: str
    name: str
    parent_span_id: str | None
    started_at: str
    ended_at: str | None = None
    duration_ms: float = 0.0
    status: str = "running"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_trace_value(asdict(self))


@dataclass(frozen=True)
class ObservabilitySummary:
    total_duration_ms: float
    query_count: int
    slowest_step: str
    warning_count: int
    error_count: int
    join_risk_count: int
    export_size_bytes: int
    span_count: int
    opentelemetry_available: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalTracer:
    """Collect spans locally; no exporter, API key, or online service is used."""

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or str(uuid4())
        self.spans: list[TraceSpan] = []
        self._starts: dict[str, float] = {}
        self._stack: list[str] = []

    def start_span(self, name: str, parent_span_id: str | None = None, attributes: dict[str, Any] | None = None) -> TraceSpan:
        span = TraceSpan(
            span_id=str(uuid4()),
            name=name,
            parent_span_id=parent_span_id or (self._stack[-1] if self._stack else None),
            started_at=datetime.now(UTC).isoformat(),
            attributes=_sanitize_trace_value(attributes or {}),
        )
        self.spans.append(span)
        self._starts[span.span_id] = time.perf_counter()
        return span

    def end_span(self, span: TraceSpan, status: str = "completed", error: str | None = None) -> TraceSpan:
        started = self._starts.pop(span.span_id, time.perf_counter())
        span.duration_ms = round((time.perf_counter() - started) * 1000, 3)
        span.ended_at = datetime.now(UTC).isoformat()
        span.status = "error" if error else status
        if error:
            span.events.append({"name": "error", "message": str(error)})
        return span

    @contextmanager
    def span(self, name: str, parent_span_id: str | None = None, attributes: dict[str, Any] | None = None) -> Iterator[TraceSpan]:
        report_stage(name)
        current = self.start_span(name, parent_span_id, attributes)
        self._stack.append(current.span_id)
        try:
            yield current
            cancellation_checkpoint()
        except TaskCancelledError:
            self.end_span(current, status="cancelled")
            raise
        except BaseException as exc:
            self.end_span(current, error=str(exc))
            raise
        else:
            self.end_span(current)
        finally:
            self._stack.pop()
        if self._stack:
            parent = next(span for span in reversed(self.spans) if span.span_id == self._stack[-1])
            report_stage(parent.name)
        else:
            report_stage(name + ":completed")

    def add_event(self, span: TraceSpan, name: str, attributes: dict[str, Any] | None = None) -> None:
        span.events.append({"name": name, "attributes": _sanitize_trace_value(attributes or {})})

    def summary(
        self,
        *,
        query_count: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
        join_risk_count: int = 0,
        export_size_bytes: int = 0,
    ) -> ObservabilitySummary:
        total = round(sum(span.duration_ms for span in self.spans if span.parent_span_id is None), 3)
        slowest = max(self.spans, key=lambda span: span.duration_ms).name if self.spans else ""
        return ObservabilitySummary(
            total_duration_ms=total,
            query_count=int(query_count),
            slowest_step=slowest,
            warning_count=int(warning_count),
            error_count=int(error_count),
            join_risk_count=int(join_risk_count),
            export_size_bytes=int(export_size_bytes),
            span_count=len(self.spans),
            opentelemetry_available=importlib.util.find_spec("opentelemetry") is not None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "spans": [span.to_dict() for span in self.spans]}


_active_tracer: ContextVar[LocalTracer | None] = ContextVar("insightpilot_local_tracer", default=None)

@contextmanager
def use_tracer(tracer: LocalTracer):
    token = _active_tracer.set(tracer)
    try:
        yield tracer
    finally:
        _active_tracer.reset(token)

@contextmanager
def trace_stage(name: str, **attributes: Any):
    """Reuse the calling workflow tracer; never keep a process-global data cache."""
    tracer = _active_tracer.get()
    if tracer is not None:
        with tracer.span(name, attributes=attributes) as span:
            yield span
    else:
        report_stage(name)
        yield None
        cancellation_checkpoint()
        report_stage(name + ":completed")
