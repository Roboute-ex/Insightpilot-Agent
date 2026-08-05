"""Structured caveats with compatibility for legacy string messages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CaveatItem:
    code: str
    message_zh: str
    message_en: str | None = None
    severity: str = "warning"
    related_component: str = "workflow"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
