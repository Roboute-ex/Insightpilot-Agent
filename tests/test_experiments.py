from __future__ import annotations

from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.data.synthetic import generate_all_demo_data


def test_ab_test_outputs_p_value_and_lift() -> None:
    tables = generate_all_demo_data(seed=42)
    result = analyze_ab_test(tables["experiments"], "group", "completion_rate", metric_type="mean")
    assert "p_value" in result
    assert result["sample_size"]["control"] > 100
    assert result["sample_size"]["treatment"] > 100
    assert result["treatment_mean"] > result["control_mean"]
