from __future__ import annotations

from insightpilot.data.example_questions import get_example_questions


def test_each_primary_scenario_has_at_least_twelve_chinese_questions() -> None:
    for scenario in ("transaction", "content", "live"):
        questions = get_example_questions(scenario)
        assert len(questions) >= 12
        assert all(any("\u4e00" <= character <= "\u9fff" for character in item.question_zh) for item in questions)


def test_demo_common_questions_are_bounded_to_six() -> None:
    assert len(get_example_questions("transaction", common_only=True)) == 6
