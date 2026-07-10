"""Reusable analysis playbooks."""

from insightpilot.playbooks.builtins import BUILTIN_PLAYBOOKS, get_builtin_playbooks
from insightpilot.playbooks.executor import execute_playbook
from insightpilot.playbooks.models import (
    AnalysisParameter,
    AnalysisPlaybook,
    PlaybookExecutionResult,
    PlaybookRequirements,
)
from insightpilot.playbooks.registry import (
    DEFAULT_PLAYBOOK_REGISTRY,
    PLAYBOOK_REGISTRY,
    PlaybookRegistry,
    get_playbook_registry,
)
from insightpilot.playbooks.sql_templates import SQLTemplateResult
from insightpilot.playbooks.validation import validate_playbook_parameters

__all__ = [
    "AnalysisParameter",
    "AnalysisPlaybook",
    "BUILTIN_PLAYBOOKS",
    "DEFAULT_PLAYBOOK_REGISTRY",
    "PLAYBOOK_REGISTRY",
    "PlaybookExecutionResult",
    "PlaybookRegistry",
    "PlaybookRequirements",
    "SQLTemplateResult",
    "execute_playbook",
    "get_builtin_playbooks",
    "get_playbook_registry",
    "validate_playbook_parameters",
]
