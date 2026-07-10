"""Deterministic registry and recommendation rules for analysis playbooks."""

from __future__ import annotations

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.builtins import get_builtin_playbooks
from insightpilot.playbooks.models import AnalysisPlaybook


class PlaybookRegistry:
    def __init__(self) -> None:
        self._playbooks: dict[str, AnalysisPlaybook] = {}

    def register(self, playbook: AnalysisPlaybook) -> None:
        if playbook.playbook_id in self._playbooks:
            raise ValueError(f"playbook_id 已存在：{playbook.playbook_id}")
        self._playbooks[playbook.playbook_id] = playbook

    def get(self, playbook_id: str) -> AnalysisPlaybook:
        try:
            return self._playbooks[playbook_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._playbooks)) or "暂无"
            raise ValueError(f"未找到分析剧本：{playbook_id}。可用剧本：{available}") from exc

    def list_all(self) -> list[AnalysisPlaybook]:
        return [self._playbooks[key] for key in sorted(self._playbooks)]

    def list_for_goal_mode(self, goal_mode: str) -> list[AnalysisPlaybook]:
        return [playbook for playbook in self.list_all() if playbook.supports_goal_mode(goal_mode)]

    def list_for_mapping(self, mapping: ColumnMapping) -> list[AnalysisPlaybook]:
        return [playbook for playbook in self.list_all() if not playbook.validate_mapping(mapping)]

    def recommend(self, goal_mode: str, mapping: ColumnMapping) -> list[AnalysisPlaybook]:
        preferred = {
            "metric_diagnosis": "dimension_contribution",
            "growth_trend": "metric_trend",
            "experiment_analysis": "experiment_comparison",
            "content_performance": "dimension_contribution",
            "live_quality": "dimension_contribution",
            "causal_exploration": "causal_exploration",
            "periodic_report": "periodic_summary",
        }.get(goal_mode)
        scored: list[tuple[int, str, AnalysisPlaybook]] = []
        for playbook in self.list_all():
            mapping_errors = playbook.validate_mapping(mapping)
            goal_score = 40 if playbook.supports_goal_mode(goal_mode) else 0
            mapping_score = max(0, 35 - len(mapping_errors) * 12)
            role_score = 0
            if mapping.date_column and playbook.requirements.requires_date_column:
                role_score += 8
            if mapping.metric_columns and playbook.requirements.requires_metric_columns:
                role_score += 8
            if mapping.dimension_columns and playbook.requirements.requires_dimension_columns:
                role_score += 6
            if mapping.group_column and playbook.requirements.requires_group_column:
                role_score += 8
            if mapping.treatment_column and playbook.requirements.requires_treatment_column:
                role_score += 8
            if mapping.outcome_column and playbook.requirements.requires_outcome_column:
                role_score += 8
            if playbook.playbook_id == "data_profile":
                role_score += 2
            preferred_score = 30 if playbook.playbook_id == preferred else 0
            scored.append((goal_score + mapping_score + role_score + preferred_score, playbook.playbook_id, playbook))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored]


def create_default_registry() -> PlaybookRegistry:
    registry = PlaybookRegistry()
    for playbook in get_builtin_playbooks():
        registry.register(playbook)
    return registry


DEFAULT_PLAYBOOK_REGISTRY = create_default_registry()
PLAYBOOK_REGISTRY = DEFAULT_PLAYBOOK_REGISTRY


def get_playbook_registry() -> PlaybookRegistry:
    return DEFAULT_PLAYBOOK_REGISTRY
