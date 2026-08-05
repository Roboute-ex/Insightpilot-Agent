"""Optional OpenTelemetry bridge with a dependency-free local fallback."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any


def opentelemetry_available() -> bool:
    return importlib.util.find_spec("opentelemetry") is not None


@dataclass(frozen=True)
class OpenTelemetryPreview:
    enabled: bool
    backend: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "backend": self.backend, "reason": self.reason}


def get_opentelemetry_preview(enabled: bool = False) -> OpenTelemetryPreview:
    """Describe optional integration without creating an exporter or network connection."""

    if not enabled:
        return OpenTelemetryPreview(False, "local_tracer", "未启用可选 OpenTelemetry 桥接。")
    if not opentelemetry_available():
        return OpenTelemetryPreview(False, "local_tracer", "OpenTelemetry 未安装，继续使用本地追踪。")
    return OpenTelemetryPreview(True, "opentelemetry_preview", "已检测到本地 OpenTelemetry API；未配置在线导出器。")


def trace_attributes(telemetry: dict[str, Any]) -> dict[str, object]:
    """Return a small allowlisted attribute set suitable for an optional span."""

    summary = telemetry.get("summary", {}) if isinstance(telemetry.get("summary"), dict) else {}
    return {
        "insightpilot.trace_id": str(telemetry.get("trace_id", "")),
        "insightpilot.span_count": int(summary.get("span_count", 0)),
        "insightpilot.error_count": int(summary.get("error_count", 0)),
        "insightpilot.warning_count": int(summary.get("warning_count", 0)),
    }
