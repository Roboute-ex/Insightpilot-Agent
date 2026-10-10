"""The same data and definition must give the same answer through every entry point."""
from __future__ import annotations

import json
import math
import re
import sys

import numpy as np
import pandas as pd
import pytest

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.analysis.anomaly import detect_metric_anomaly
from insightpilot.analysis.attribution import dimension_contribution
from insightpilot.analysis.causal_light import TreatmentDirectionError, estimate_adjusted_effect
from insightpilot.analysis.metric_diagnosis import compare_metric_baselines
from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.executor import execute_playbook


def _causal_frame(labels: tuple[str, str] = ("control", "treatment")) -> pd.DataFrame:
    covariate = np.random.default_rng(0).normal(size=24).round(3)
    arms = [labels[index % 2] for index in range(24)]
    return pd.DataFrame({
        "arm": arms,
        "x": covariate,
        "y": [10 + (2 if arm == labels[1] else 0) + value for arm, value in zip(arms, covariate)],
        "seg": ["s1", "s2", "s3"] * 8,
    })


CAUSAL_MAPPING = {"table_name": "t", "treatment_column": "arm", "outcome_column": "y", "covariates": ["x"],
                  "dimension_columns": ["seg"], "metric_columns": ["y"]}


def _playbook_effect(frame: pd.DataFrame, treatment: str, control: str) -> float:
    result = execute_playbook("causal_exploration", {"t": frame}, ColumnMapping(**CAUSAL_MAPPING),
                              {"treatment_value": treatment, "control_value": control, "covariates": ["x"]})
    return float(result.result_tables["adjusted_effect_summary"].iloc[0]["adjusted_effect"])


def _legacy_workflow(frame: pd.DataFrame, parameters: dict[str, str]) -> dict:
    result = run_agent_analysis("处理组对结果的影响", {"t": frame}, goal_mode="causal_exploration",
                                data_source_type="uploaded_files", column_mapping=dict(CAUSAL_MAPPING),
                                playbook_parameters=parameters)
    assert "run_generic_causal_light" in result["route_taken"]
    return result


def _cli_effect(monkeypatch, capsys, tmp_path, frame: pd.DataFrame, playbook: str, treatment: str, control: str) -> float:
    from insightpilot import cli

    source = tmp_path / "t.csv"
    frame.to_csv(source, index=False)
    dimension = "seg" if "seg" in frame else "x"
    monkeypatch.setattr(sys, "argv", ["insightpilot", "--data-source", "file", "--input-file", str(source), "--table-name", "t",
        "--treatment-column", "arm", "--outcome-column", "y", "--metric-columns", "y", "--dimension-columns", dimension,
        "--covariates", "x", "--goal-mode", "causal_exploration", "--playbook", playbook,
        "--treatment-value", treatment, "--control-value", control, "--output-format", "json", "--export-dir", str(tmp_path)])
    assert cli.main() == 0
    findings = json.loads(capsys.readouterr().out)["runs"][0]["findings"]
    values = [float(match) for item in findings for match in re.findall(r"adjusted effect=(-?\d+\.\d+)|adjusted_effect=(-?\d+\.\d+)", item) for match in match if match]
    assert values, findings
    return values[0]


@pytest.mark.parametrize("labels", [("control", "treatment"), ("a", "b")])
def test_causal_direction_follows_explicit_choice_in_every_entry(labels):
    frame = _causal_frame(labels)
    control, treatment = labels
    forward = {"treatment_value": treatment, "control_value": control}
    swapped = {"treatment_value": control, "control_value": treatment}

    playbook_forward = _playbook_effect(frame, treatment, control)
    playbook_swapped = _playbook_effect(frame, control, treatment)
    legacy_forward = _legacy_workflow(frame, forward)["artifacts"]["generic_causal_light"]["adjusted_effect"]
    legacy_swapped = _legacy_workflow(frame, swapped)["artifacts"]["generic_causal_light"]["adjusted_effect"]

    assert playbook_forward == pytest.approx(2.0) and legacy_forward == pytest.approx(playbook_forward)
    assert playbook_swapped == pytest.approx(-2.0) and legacy_swapped == pytest.approx(playbook_swapped)


def test_cli_legacy_and_playbook_routes_agree_on_swapped_direction(monkeypatch, capsys, tmp_path):
    frame = _causal_frame()
    legacy = _cli_effect(monkeypatch, capsys, tmp_path, frame, "__legacy__", "control", "treatment")
    playbook = _cli_effect(monkeypatch, capsys, tmp_path, frame, "causal_exploration", "control", "treatment")
    assert legacy == pytest.approx(-2.0) and playbook == pytest.approx(-2.0)


def test_ambiguous_treatment_labels_are_not_guessed():
    frame = _causal_frame(("a", "b"))
    with pytest.raises(TreatmentDirectionError):
        estimate_adjusted_effect(frame, "arm", "y", ["x"])
    with pytest.raises(TreatmentDirectionError):
        estimate_adjusted_effect(frame, "arm", "y", ["x"], treatment_value="b", control_value="missing")
    result = run_agent_analysis("处理组对结果的影响", {"t": frame}, goal_mode="causal_exploration",
                                data_source_type="uploaded_files", column_mapping=dict(CAUSAL_MAPPING), playbook_parameters={})
    assert result["execution_status"] == "NEEDS_INPUT"
    assert "run_generic_causal_light" not in result["route_taken"]


def test_unambiguous_binary_encodings_still_work_without_explicit_values():
    frame = _causal_frame(("0", "1")).assign(arm=lambda data: data["arm"].astype(int))
    assert estimate_adjusted_effect(frame, "arm", "y", ["x"])["adjusted_effect"] == pytest.approx(2.0)
    assert estimate_adjusted_effect(frame.assign(arm=frame["arm"].astype(bool)), "arm", "y", ["x"])["adjusted_effect"] == pytest.approx(2.0)


def _ratio_frame() -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2026-01-01", periods=9):
        rows.append({"date": day, "city": "A", "orders": 5, "visitors": 50})
        rows.append({"date": day, "city": "B", "orders": 3, "visitors": 30})
    target = pd.Timestamp("2026-01-10")
    rows += [{"date": target, "city": "A", "orders": 1, "visitors": 10}, {"date": target, "city": "A", "orders": 45, "visitors": 90}]
    return pd.DataFrame(rows)


def test_ratio_is_weighted_consistently_across_modules():
    frame = _ratio_frame()
    contribution = dimension_contribution(frame, "cvr", "city").set_index("dimension_value")
    comparisons, final_anomaly = compare_metric_baselines(frame, "cvr")
    legacy = detect_metric_anomaly(frame, "cvr")

    assert contribution.loc["A", "current_value"] == pytest.approx(46 / 100)
    assert legacy["current_value"] == pytest.approx(46 / 100) == pytest.approx(final_anomaly.actual_value)
    assert legacy["baseline_value"] == pytest.approx(final_anomaly.expected_value)
    assert legacy["severity"] == final_anomaly.severity


def test_missing_group_is_not_zero_for_ratios_but_is_zero_for_sums():
    frame = _ratio_frame()
    ratio = dimension_contribution(frame, "cvr", "city").set_index("dimension_value")
    assert ratio.loc["B", "group_presence"] == "baseline_only"
    assert math.isnan(ratio.loc["B", "current_value"]) and math.isnan(ratio.loc["B", "contribution_share"])
    assert ratio["contribution_share"].dropna().sum() == pytest.approx(1.0)

    total = dimension_contribution(frame, "orders", "city", aggregation="sum").set_index("dimension_value")
    assert total.loc["B", "group_presence"] == "baseline_only"
    assert total.loc["B", "current_value"] == 0 and total.loc["B", "change"] == pytest.approx(-3)


def test_explicit_mean_is_preserved_for_non_ratio_metrics():
    frame = _ratio_frame()
    mean = dimension_contribution(frame, "orders", "city", aggregation="mean").set_index("dimension_value")
    assert mean.loc["A", "current_value"] == pytest.approx(23)


def test_zero_baseline_is_not_computable_in_legacy_and_final_paths():
    frame = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=10), "orders": [0] * 9 + [5]})
    legacy = detect_metric_anomaly(frame, "orders")
    comparisons, final_anomaly = compare_metric_baselines(frame, "orders")
    assert math.isnan(legacy["relative_change"]) and math.isnan(comparisons[0].relative_change)
    assert legacy["severity"] == final_anomaly.severity == "UNKNOWN"
    assert legacy["is_anomaly"] is False


def _unequal_denominator_frame() -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2026-01-01", periods=10):
        numerator, denominator = (45, 90) if day.day == 9 else (16, 100) if day.day == 10 else (1, 10)
        rows.append({"date": day, "city": "A", "orders": numerator, "visitors": denominator, "cvr": numerator / denominator})
    return pd.DataFrame(rows)


def test_one_row_per_day_keeps_denominator_weights():
    frame = _unequal_denominator_frame()
    legacy = detect_metric_anomaly(frame, "cvr")
    comparisons, final_anomaly = compare_metric_baselines(frame, "cvr")
    contribution = dimension_contribution(frame, "cvr", "city").iloc[0]
    expected_baseline = 51 / 150

    assert comparisons[0].baseline_value == pytest.approx(expected_baseline)
    assert legacy["baseline_value"] == pytest.approx(expected_baseline)
    assert legacy["relative_change"] == pytest.approx((0.16 - 0.34) / 0.34)
    assert legacy["severity"] == final_anomaly.severity == "HIGH"
    assert contribution["baseline_value"] == pytest.approx(expected_baseline)
    assert detect_metric_anomaly(pd.concat([frame, frame]), "cvr")["baseline_value"] == pytest.approx(expected_baseline)


def test_ratio_column_without_components_is_averaged_not_summed():
    frame = pd.DataFrame([{"date": day, "city": "A", "cvr": value}
                          for day in pd.date_range("2026-01-01", periods=10)
                          for value in ([0.2] if day.day == 10 else [0.1, 0.3])])
    legacy = detect_metric_anomaly(frame, "cvr")
    comparisons, final_anomaly = compare_metric_baselines(frame, "cvr")
    contribution = dimension_contribution(frame, "cvr", "city").iloc[0]

    assert legacy["baseline_value"] == pytest.approx(0.2) == pytest.approx(comparisons[0].baseline_value)
    assert legacy["relative_change"] == pytest.approx(0.0, abs=1e-12)
    assert legacy["severity"] == final_anomaly.severity == "LOW"
    assert contribution["baseline_value"] == pytest.approx(0.2) and contribution["current_value"] == pytest.approx(0.2)


@pytest.fixture(scope="module")
def content_tables():
    from insightpilot.data.scenarios import generate_demo_scenario
    return generate_demo_scenario("content", scale="small", seed=42).tables


def _builtin(tables, goal_mode: str, control: str, treatment: str) -> dict:
    return run_agent_analysis("Does treatment affect completion rate?", tables, goal_mode=goal_mode,
                              playbook_parameters={"control_value": control, "treatment_value": treatment})


def test_builtin_causal_route_follows_selected_direction(content_tables):
    forward = _builtin(content_tables, "causal_exploration", "control", "treatment")
    swapped = _builtin(content_tables, "causal_exploration", "treatment", "control")
    assert "run_causal_light" in forward["route_taken"]
    effect = forward["artifacts"]["causal_light"]["adjusted_effect"]
    assert effect > 0
    assert swapped["artifacts"]["causal_light"]["adjusted_effect"] == pytest.approx(-effect)


def test_builtin_experiment_route_follows_selected_direction(content_tables):
    forward = _builtin(content_tables, "experiment_analysis", "control", "treatment")
    swapped = _builtin(content_tables, "experiment_analysis", "treatment", "control")
    assert "run_experiment" in forward["route_taken"]
    lift = forward["artifacts"]["ab_test"]["absolute_lift"]
    assert swapped["artifacts"]["ab_test"]["absolute_lift"] == pytest.approx(-lift)
    forward_strata = {row["user_segment"]: row["lift"] for row in forward["artifacts"]["strata"]}
    swapped_strata = {row["user_segment"]: row["lift"] for row in swapped["artifacts"]["strata"]}
    assert swapped_strata == pytest.approx({key: -value for key, value in forward_strata.items()})


def test_builtin_route_rejects_group_values_absent_from_data(content_tables):
    result = _builtin(content_tables, "causal_exploration", "control", "variant_b")
    assert result["execution_status"] in {"FAILED", "NEEDS_INPUT", "INVALID_INPUT"}
    assert "causal_light" not in result["artifacts"]


def test_numeric_group_values_match_regardless_of_int_or_float():
    covariate = np.random.default_rng(0).normal(size=24)
    frame = pd.DataFrame({"arm": np.tile([0.0, 1.0], 12), "x": covariate, "y": 10 + covariate + np.tile([0, 2], 12)})
    mapping = {"table_name": "t", "treatment_column": "arm", "outcome_column": "y",
               "metric_columns": ["y"], "covariates": ["x"], "dimension_columns": ["x"]}
    effects = {}
    for name, playbook in (("legacy", None), ("manual", "causal_exploration")):
        result = run_agent_analysis("Treatment effect on y", {"t": frame}, goal_mode="causal_exploration",
                                    data_source_type="uploaded_files", column_mapping=dict(mapping),
                                    playbook_parameters={"treatment_value": 1, "control_value": 0, "covariates": ["x"]},
                                    playbook_id=playbook)
        assert result["execution_status"] == "COMPLETED", result["errors"]
        if playbook:
            effects[name] = float(result["result_tables"]["adjusted_effect_summary"].iloc[0]["adjusted_effect"])
        else:
            effects[name] = result["artifacts"]["generic_causal_light"]["adjusted_effect"]
    assert effects["legacy"] == pytest.approx(2.0) and effects["manual"] == pytest.approx(2.0)
    assert estimate_adjusted_effect(frame, "arm", "y", ["x"], treatment_value="1", control_value="0")["adjusted_effect"] == pytest.approx(2.0)
    with pytest.raises(TreatmentDirectionError):
        estimate_adjusted_effect(frame, "arm", "y", ["x"], treatment_value=1, control_value=1.0)


def _text_group_frame(labels: list[str]) -> pd.DataFrame:
    return pd.DataFrame([{"arm": label, "x": x, "y": 10 + x + (2 if label == "1" else 100 if label == "01" else 0)}
                         for label in labels for x in range(12)])


TEXT_GROUP_MAPPING = {"table_name": "t", "treatment_column": "arm", "outcome_column": "y", "metric_columns": ["y"],
                      "covariates": ["x"], "dimension_columns": ["x"]}


def _both_causal_routes(frame: pd.DataFrame, treatment: str, control: str) -> dict[str, dict]:
    routes = {}
    for name, playbook in (("manual", "causal_exploration"), ("legacy", None)):
        result = run_agent_analysis("Treatment effect on y", {"t": frame}, goal_mode="causal_exploration",
                                    data_source_type="uploaded_files", column_mapping=dict(TEXT_GROUP_MAPPING),
                                    playbook_parameters={"treatment_value": treatment, "control_value": control, "covariates": ["x"]},
                                    playbook_id=playbook)
        summary = result["result_tables"].get("adjusted_effect_summary") if playbook else None
        effect = summary.iloc[0].to_dict() if summary is not None else result["artifacts"].get("generic_causal_light")
        routes[name] = {"status": result["execution_status"], "effect": effect, "errors": result["errors"]}
    return routes


@pytest.mark.parametrize(("labels", "treatment", "control", "expected"), [
    (["0", "1", "01"], "1", "0", 2.0),
    (["01", "1"], "1", "01", -98.0),
])
def test_text_group_labels_keep_their_identity(labels, treatment, control, expected):
    routes = _both_causal_routes(_text_group_frame(labels), treatment, control)
    for name, route in routes.items():
        assert route["status"] == "COMPLETED", (name, route["errors"])
        assert route["effect"]["naive_difference"] == pytest.approx(expected), name
        assert route["effect"]["adjusted_effect"] == pytest.approx(expected), name
        assert route["effect"]["sample_size"] == 24, name


def test_absent_or_conflicting_group_values_block_both_routes():
    routes = _both_causal_routes(_text_group_frame(["0", "1"]), "1", "02")
    for name, route in routes.items():
        assert route["status"] in {"FAILED", "NEEDS_INPUT"}, name
        assert not route["effect"] or not np.isfinite(route["effect"].get("adjusted_effect", float("nan"))), name
    frame = _text_group_frame(["0", "1"])
    with pytest.raises(TreatmentDirectionError, match="不存在"):
        estimate_adjusted_effect(frame, "arm", "y", ["x"], treatment_value="1", control_value="02")
    blocked = execute_playbook("causal_exploration", {"t": frame}, ColumnMapping(**TEXT_GROUP_MAPPING),
                               {"treatment_value": "1", "control_value": "02", "covariates": ["x"]})
    assert blocked.status == "FAIL" and not blocked.result_tables
    numeric = pd.DataFrame({"arm": np.tile([0.0, 1.0], 12), "x": range(24), "y": range(24)})
    with pytest.raises(TreatmentDirectionError):
        estimate_adjusted_effect(numeric, "arm", "y", ["x"], treatment_value=1, control_value=1.0)


LARGE_IDS = (9007199254740992, 9007199254740993)


def _large_integer_frame() -> pd.DataFrame:
    labels = (0, *LARGE_IDS)
    return pd.DataFrame([{"arm": label, "x": x, "y": 10 + x + (2 if label == LARGE_IDS[0] else 100 if label == LARGE_IDS[1] else 0)}
                         for label in labels for x in range(12)])


@pytest.mark.parametrize("treatment", [LARGE_IDS[0], str(LARGE_IDS[0])])
def test_large_integer_groups_are_not_merged_by_float_rounding(treatment):
    frame = _large_integer_frame()
    assert frame["arm"].dtype.kind == "i"
    routes = _both_causal_routes(frame, treatment, 0)
    for name, route in routes.items():
        assert route["status"] == "COMPLETED", (name, route["errors"])
        assert route["effect"]["naive_difference"] == pytest.approx(2.0), name
        assert route["effect"]["sample_size"] == 24, name


def test_large_integer_groups_through_csv_and_cli(monkeypatch, capsys, tmp_path):
    frame = _large_integer_frame()
    for playbook in ("causal_exploration", "__legacy__"):
        assert _cli_effect(monkeypatch, capsys, tmp_path, frame, playbook, str(LARGE_IDS[0]), "0") == pytest.approx(2.0), playbook


def test_numeric_selection_stays_compatible_with_int_and_float_columns():
    from insightpilot.analysis.causal_light import treatment_indicator

    integers = pd.Series([0, 1, 1, 0])
    floats = pd.Series([0.0, 1.0, 1.0, 0.0])
    for series in (integers, floats, integers.astype("Int64")):
        for treatment, control in ((1, 0), (1.0, 0.0), ("1", "0")):
            assert treatment_indicator(series, treatment_value=treatment, control_value=control).tolist() == [0.0, 1.0, 1.0, 0.0]
    with pytest.raises(TreatmentDirectionError, match="不存在"):
        treatment_indicator(floats, treatment_value=float(LARGE_IDS[1]) + 0.5, control_value=0)


def _experiment_frame(labels: tuple, lifts: dict) -> pd.DataFrame:
    rows = [{"user_id": f"u{index}-{position}", "arm": label, "y": 10.0 + lifts.get(label, 0.0) + (index % 4)}
            for position, label in enumerate(labels) for index in range(40)]
    return pd.DataFrame(rows)


def _experiment_routes(frame: pd.DataFrame, treatment, control) -> dict[str, dict]:
    mapping = {"table_name": "t", "group_column": "arm", "metric_columns": ["y"], "statistical_unit": "user_id"}
    parameters = {"treatment_value": treatment, "control_value": control, "statistical_unit": "user_id", "metric_type": "mean"}
    routes = {}
    for name, playbook in (("manual", "experiment_comparison"), ("legacy", None)):
        result = run_agent_analysis("Experiment lift on y", {"t": frame}, goal_mode="experiment_analysis",
                                    data_source_type="uploaded_files", column_mapping=dict(mapping),
                                    playbook_parameters=dict(parameters), playbook_id=playbook)
        statistics = result["result_tables"].get("experiment_statistics") if playbook else None
        values = statistics.iloc[0].to_dict() if statistics is not None else result["artifacts"].get("generic_ab_test")
        routes[name] = {"status": result["execution_status"], "values": values, "errors": result["errors"]}
    return routes


@pytest.mark.parametrize(("labels", "treatment", "control"), [
    ((0, *LARGE_IDS), LARGE_IDS[0], 0),
    ((0, *LARGE_IDS), str(LARGE_IDS[0]), "0"),
    (("0", "1", "01"), "1", "0"),
])
def test_experiment_routes_select_the_same_groups(labels, treatment, control):
    lifts = {LARGE_IDS[0]: 2.0, LARGE_IDS[1]: 100.0, "1": 2.0, "01": 100.0}
    routes = _experiment_routes(_experiment_frame(labels, lifts), treatment, control)
    for name, route in routes.items():
        assert route["status"] == "COMPLETED", (name, route["errors"])
        assert route["values"]["absolute_lift"] == pytest.approx(2.0), name
        assert dict(route["values"]["sample_size"]) == {"control": 40, "treatment": 40}, name


def test_experiment_routes_block_absent_group_values():
    routes = _experiment_routes(_experiment_frame((0, LARGE_IDS[0]), {}), LARGE_IDS[1], 0)
    for name, route in routes.items():
        assert route["status"] in {"FAILED", "NEEDS_INPUT", "INVALID_INPUT"}, name
        assert not route["values"], name


def _content_package(frame: pd.DataFrame):
    from insightpilot.agents.state import WorkflowState
    from insightpilot.analysis.package_builder import build_analysis_result_package

    mapping = {"table_name": "content_events", "date_column": "date", "metric_columns": ["ctr"],
               "dimension_columns": ["content_category"], "aggregation": "mean"}
    state = WorkflowState(user_question="Content click through rate", goal_mode="content_performance", column_mapping=mapping)
    return build_analysis_result_package(state, {"content_events": frame})


def _ctr_rows(category: str, history: list[float], target: list[float] | None) -> list[dict]:
    rows = []
    for day in pd.date_range("2026-01-01", periods=10):
        values = (target if day.day == 10 else history) or []
        rows += [{"date": day, "content_category": category, "ctr": value, "completion_rate": 0.5, "watch_time": 10.0,
                  "retention_rate": 0.5} for value in values]
    return rows


def test_final_package_contribution_averages_ratio_column_like_overall_comparison():
    package = _content_package(pd.DataFrame(_ctr_rows("A", [0.1, 0.3], [0.2])))
    overall = package.metric_comparisons[0]
    [group] = package.dimension_contributions

    assert overall.baseline_value == pytest.approx(0.2) and overall.current_value == pytest.approx(0.2)
    assert group.baseline_value == pytest.approx(overall.baseline_value)
    assert group.current_value == pytest.approx(0.2) and group.contribution_value == pytest.approx(0.0)
    assert not [item for item in package.evidence if item.result_table == "dimension_contributions"]


def test_final_package_others_and_missing_groups_never_sum_or_zero_fill_averages():
    rows = _ctr_rows("A", [0.1, 0.3], [0.2]) + _ctr_rows("B", [0.2], [0.2]) + _ctr_rows("C", [0.4], None)
    package = _content_package(pd.DataFrame(rows))
    by_value = {item.dimension_value: item for item in package.dimension_contributions}

    overall = package.metric_comparisons[0]
    others = by_value["Others"]
    assert set(by_value) == {"Others"}
    assert others.current_value == pytest.approx(0.2) == pytest.approx(overall.current_value)
    assert others.baseline_value == pytest.approx((0.1 + 0.3 + 0.2 + 0.4) / 4) == pytest.approx(overall.baseline_value)
    assert all(item.current_value != 0 for item in package.dimension_contributions)
    assert all(np.isfinite(item.contribution_pct) for item in package.dimension_contributions if np.isfinite(item.contribution_value))


def test_others_keeps_the_note_that_merged_groups_were_seen_in_one_period_only():
    rows = _ctr_rows("A", [0.6], [0.5]) + _ctr_rows("B", [0.8], None) + _ctr_rows("C", [], [0.2])
    by_value = {item.dimension_value: item for item in _content_package(pd.DataFrame(rows)).dimension_contributions}

    others, regular = by_value["Others"], by_value["A"]
    assert others.baseline_value == pytest.approx(0.8) and others.current_value == pytest.approx(0.2)
    assert "仅一期有观测" in others.confidence_flag and "组成变化" in others.confidence_flag
    assert "仅一期有观测" not in regular.confidence_flag and "组成变化" not in regular.confidence_flag


def test_single_period_groups_are_labelled_in_ratio_contributions():
    rows = []
    for day in pd.date_range("2026-01-01", periods=10):
        rows.append({"date": day, "content_category": "A", "clicks": 20, "impressions": 100})
        if day.day < 10:
            rows.append({"date": day, "content_category": "B", "clicks": 40, "impressions": 100})
    from insightpilot.analysis.dimension_contribution import dimension_contribution_results

    by_value = {item.dimension_value: item for item in dimension_contribution_results(pd.DataFrame(rows), "ctr", ["content_category"], include_drilldown=False)}
    assert "仅基准期有观测" in by_value["B"].confidence_flag
    assert "仅" not in by_value["A"].confidence_flag.replace("仅以有观测日期计算", "")


def test_stutter_rise_is_flagged_and_matches_final_result():
    rows = []
    for day in pd.date_range("2026-01-01", periods=10):
        buffering = 120 if day == pd.Timestamp("2026-01-10") else 30
        rows += [{"date": day, "buffering_seconds": buffering, "observation_seconds": 600, "stutter_rate": buffering / 600}] * 3
    frame = pd.DataFrame(rows)
    legacy = detect_metric_anomaly(frame, "stutter_rate")
    _, final_anomaly = compare_metric_baselines(frame, "stutter_rate")

    assert legacy["direction"] == "上升" and legacy["good_direction"] == "lower" and legacy["is_adverse"] is True
    assert legacy["is_anomaly"] is True
    assert legacy["severity"] == final_anomaly.severity == "HIGH"
    assert legacy["relative_change"] == pytest.approx(final_anomaly.deviation_pct)
