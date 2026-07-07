"""Trace model for analysis runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalysisTrace:
    user_question: str
    identified_intent: str
    selected_metrics: list[str]
    analysis_plan: dict[str, Any]
    goal_mode: str = ""
    goal_mode_display_name: str = ""
    goal_mode_source: str = ""
    executed_queries: list[str] = field(default_factory=list)
    generated_findings: list[str] = field(default_factory=list)
    reviewer_checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
