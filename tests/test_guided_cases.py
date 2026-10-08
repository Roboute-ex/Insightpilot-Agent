"""Independent guided task oracles, kept separate from UI layout assertions."""
from __future__ import annotations

import json

import pytest

from insightpilot.evaluation.guided_suite import GUIDED_FAMILIES, build_guided_task_cases
from insightpilot.evaluation.harness import EvaluationHarness


@pytest.mark.parametrize("case", build_guided_task_cases(), ids=lambda case: case.case_id)
def test_guided_small_table_contract(case):
    result = EvaluationHarness().run([case]).to_dict()
    assert result["passed"], json.dumps(result, ensure_ascii=False)


def test_guided_oracles_are_independent_and_all_families_have_checks():
    cases = build_guided_task_cases()
    assert {case.family for case in cases} == set(GUIDED_FAMILIES.values())
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.expected and case.input_fixture and case.required_evidence and case.forbidden_behaviors for case in cases)
    experiment = next(case for case in cases if case.case_id == "guided_valid_user_experiment")
    assert experiment.expected["n_each"] == 2
    causal = next(case for case in cases if case.case_id == "guided_valid_causal")
    assert causal.expected == {"naive_difference": 2, "adjusted_effect": 2, "status": "COMPLETED"}
