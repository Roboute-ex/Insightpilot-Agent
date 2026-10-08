"""Independent reconciliation, grain and executable-example acceptance checks."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import pytest

from insightpilot.data.example_questions import get_example_questions
from insightpilot.data.scenarios import generate_demo_scenario
from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.metrics.aggregation import metric_components
from insightpilot.metrics.dictionary import get_metric, list_metrics


def test_transaction_detail_reconciles_exactly_and_keys_are_valid(transaction_dataset):
    tables = transaction_dataset.tables
    daily, detail = tables["daily_metrics"], tables["transaction_detail"]
    assert len(detail) >= 60000
    assert len(tables["users"]) == 20000
    assert len(tables["merchants"]) >= 3000
    assert detail["order_id"].is_unique
    assert set(detail["user_id"]).issubset(tables["users"]["user_id"])
    assert set(detail["merchant_id"]).issubset(tables["merchants"]["merchant_id"])
    expected = detail.groupby("daily_row_id")[["orders", "amount_cents", "refund_orders", "refund_amount_cents"]].sum()
    actual = daily.set_index("daily_row_id")[expected.columns]
    pd.testing.assert_frame_equal(expected.reindex(actual.index, fill_value=0), actual)
    stages = ["impressions", "clicks", "visitors", "add_to_cart_users", "checkout_users", "payment_attempts", "successful_payments"]
    assert (daily[stages] >= 0).all().all()
    assert (np.diff(daily[stages].to_numpy(), axis=1) <= 0).all()
    assert daily.loc[daily["payment_attempts"] == 0, "payment_success_rate"].isna().all()


def test_content_detail_reconciles_and_experiment_unit_is_unique(content_dataset):
    tables = content_dataset.tables
    daily, events, assignments = tables["content_daily_metrics"], tables["content_events"], tables["experiment_assignments"]
    assert events["event_id"].is_unique
    assert set(events["content_id"]).issubset(tables["content_items"]["content_id"])
    expected = events.groupby("daily_row_id").agg(plays=("event_id", "size"), completed=("completed", "sum"), watch_time_total=("watch_time", "sum"), engaged=("engaged", "sum"))
    pd.testing.assert_frame_equal(expected, daily.set_index("daily_row_id")[expected.columns])
    assert assignments["user_id"].is_unique and len(assignments) >= 10000
    assert assignments["group"].value_counts().nunique() == 1
    assert np.allclose(assignments["completion_rate"], assignments["completed_count"] / assignments["plays"])
    assert events.loc[(events["content_length"] == "长内容") & (events["device"] == "Android"), "completed"].mean() < events.loc[(events["content_length"] == "长内容") & (events["device"] == "iOS"), "completed"].mean()


def test_live_totals_and_quality_tables_reconcile(live_dataset):
    tables = live_dataset.tables
    sessions, daily = tables["live_sessions"], tables["live_daily_metrics"]
    assert sessions["session_id"].is_unique
    assert len(tables["live_quality_logs"]) == len(sessions) == len(tables["live_interactions"])
    for metric in ["sessions", "viewers", "buffering_seconds", "observation_seconds", "crashed", "interaction_count", "converted"]:
        assert np.isclose(daily[metric].sum(), sessions[metric].sum())
    assert np.isclose(daily["watch_time_total"].sum(), sessions["watch_time"].sum())
    assert sessions["buffering_rate"].between(0, 1).all()
    target = sessions["date"].max()
    recent = sessions[sessions["date"] >= target - pd.Timedelta(days=2)]
    assert recent[recent["app_version"] == "6.2"]["crashed"].mean() > recent[recent["app_version"] == "6.1"]["crashed"].mean()
    stable = sessions[(sessions["device"] == "iOS") & (sessions["network_type"] == "WiFi") & (sessions["app_version"] == "6.1")]
    before = stable[stable["date"] < target - pd.Timedelta(days=2)]["buffering_rate"].mean()
    after = stable[stable["date"] >= target - pd.Timedelta(days=2)]["buffering_rate"].mean()
    assert abs(after - before) < .02


@pytest.mark.parametrize("scenario", ["transaction", "content", "live"])
def test_small_full_frames_are_seed_deterministic(scenario):
    first = generate_demo_scenario(scenario, "small", 42)
    second = generate_demo_scenario(scenario, "small", 42)
    for name in first.tables:
        pd.testing.assert_frame_equal(first.tables[name], second.tables[name])
    assert first.metadata == second.metadata
    changed = generate_demo_scenario(scenario, "small", 43)
    assert not first.tables["users"].equals(changed.tables["users"])


def test_exact_question_counts_fields_and_selection_config():
    assert len(get_example_questions()) == 39
    identifiers = []
    for scenario, count in [("transaction", 15), ("content", 12), ("live", 12)]:
        tables = generate_demo_scenario(scenario, "small").tables
        questions = get_example_questions(scenario)
        assert len(questions) == count
        assert len(get_example_questions(scenario, common_only=True)) == 6
        for question in questions:
            identifiers.append(question.question_id)
            config = question.apply_settings()
            frame = tables[config["column_mapping"]["table_name"]]
            assert set(question.required_fields).issubset(frame.columns), question.question_id
            assert config["question"] == question.question_zh
            assert config["goal_mode"] == question.recommended_goal_mode
            assert question.explanation
            config["column_mapping"]["metric_columns"].clear()
            assert question.selection_config["column_mapping"]["metric_columns"]
    assert len(set(identifiers)) == 39


def test_multitable_event_order_and_flags_reconcile():
    tables = generate_multi_table_commerce_data()
    events, sessions = tables["events"], tables["sessions"]
    assert events["event_id"].is_unique
    assert set(events["session_id"]).issubset(sessions["session_id"])
    for flag, stage in [("visited", "visit"), ("viewed_product", "view"), ("added_to_cart", "cart"), ("submitted_order", "submit"), ("paid", "paid")]:
        assert set(events.loc[events["event_name"] == stage, "session_id"]) == set(sessions.loc[sessions[flag] == 1, "session_id"])
    assert events.groupby("session_id")["event_time"].apply(lambda value: value.is_monotonic_increasing).all()


def test_metric_metadata_has_directions_units_and_unique_display_labels():
    assert get_metric("latency_ms").unit == "毫秒"
    assert get_metric("stutter_rate").good_direction == "lower"
    assert get_metric("orders").good_direction == "higher"
    assert get_metric("cvr").denominator == "visitors"
    assert get_metric("退款率").metric_name == "refund_rate"
    labels = [metric.display_name for metric in list_metrics()]
    assert len(labels) == len(set(labels))
    assert metric_components("watch_time", ["watch_time_total", "plays"]) == ("watch_time_total", "plays")
    assert metric_components("completion_rate", ["completed_count", "plays"]) is None


def test_demo_file_generator_roundtrips_and_refuses_overwrite(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "generate_demo_files.py"
    spec = importlib.util.spec_from_file_location("generate_demo_files", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = module.generate_demo_files(tmp_path, "live", "small")
    assert paths
    with pd.ExcelFile(tmp_path / "live_demo.xlsx") as workbook:
        assert "live_sessions" in workbook.sheet_names
        excel = pd.read_excel(workbook, sheet_name="live_sessions")
    csv = pd.read_csv(tmp_path / "live_live_sessions.csv")
    with sqlite3.connect(f"file:{(tmp_path / 'live_demo.sqlite').as_posix()}?mode=ro", uri=True) as connection:
        count = connection.execute("SELECT COUNT(*) FROM live_sessions").fetchone()[0]
    assert len(csv) == len(excel) == count == 2800
    original = {path.name: path.stat().st_size for path in paths}
    with pytest.raises(FileExistsError):
        module.generate_demo_files(tmp_path, "live", "small")
    assert {path.name: path.stat().st_size for path in paths} == original


def test_opt_in_quality_faults_preserve_clean_baseline():
    from insightpilot.data.scenarios import with_quality_issues
    clean = generate_demo_scenario("live", "small")
    original = clean.tables["live_sessions"].copy(deep=True)
    dirty = with_quality_issues(clean, "live_sessions", missing_column="city", duplicate_rows=2)
    pd.testing.assert_frame_equal(clean.tables["live_sessions"], original)
    assert dirty.tables["live_sessions"].duplicated().sum() == 2
    assert dirty.tables["live_sessions"]["city"].isna().sum() == 2
    assert dirty.metadata["quality_test_faults"]["faults"]


def test_all_example_selections_execute_and_primary_metric_changes():
    from insightpilot.agents.workflow import run_agent_analysis
    from insightpilot.playbooks.executor import execute_playbook
    summaries = {}
    expected_primary = {"tx01": "orders", "tx05": "payment_success_rate", "lv01": "buffering_rate", "lv06": "stutter_rate"}
    for scenario in ["transaction", "content", "live"]:
        dataset = generate_demo_scenario(scenario, "small")
        for question in get_example_questions(scenario):
            config = question.apply_settings()
            if config["playbook_id"]:
                result = execute_playbook(config["playbook_id"], dataset.tables, config["column_mapping"], config["parameters"])
                assert result.status != "FAIL", (question.question_id, result.warnings)
                assert any(not table.empty for table in result.result_tables.values()), question.question_id
                assert not any("查询失败" in warning for warning in result.warnings), question.question_id
            else:
                result = run_agent_analysis(config["question"], dataset.tables, goal_mode=config["goal_mode"], column_mapping=config["column_mapping"])
                assert not result["errors"], question.question_id
                package = result["analysis_result_package"]
                assert package["metric_comparisons"][0]["metric_id"] == expected_primary[question.question_id]
                summaries[question.question_id] = package["executive_summary"]
                if question.question_id == "lv06":
                    assert not result["result_tables"]["quality_conversion_association"].empty
                    assert not result["result_tables"]["quality_conversion_groups"].empty
                    assert "LIVE-ASSOC-001" in {item["evidence_id"] for item in package["evidence"]}
    assert summaries["tx01"] != summaries["tx05"]


def test_live_broadcasts_have_distinct_hosts_times_and_reconciled_viewer_sessions(live_dataset):
    tables = live_dataset.tables
    broadcasts, hosts, sessions = tables["live_broadcasts"], tables["live_hosts"], tables["live_sessions"]
    assert len(broadcasts) >= 50000 and broadcasts["date"].nunique() >= 90
    assert broadcasts["broadcast_id"].is_unique and hosts["host_id"].is_unique
    assert not broadcasts.duplicated(["host_id", "date"]).any()
    assert set(broadcasts["host_id"]).issubset(hosts["host_id"])
    assert set(sessions["broadcast_id"]) == set(broadcasts["broadcast_id"])
    linked = sessions.merge(broadcasts[["broadcast_id", "host_id", "start_time", "end_time", "host_tier", "live_category"]], on="broadcast_id", validate="many_to_one", suffixes=("", "_broadcast"))
    assert (linked["host_id"] == linked["host_id_broadcast"]).all()
    assert (linked["host_tier"] == linked["host_tier_broadcast"]).all()
    assert (linked["live_category"] == linked["live_category_broadcast"]).all()
    assert (linked["session_start_time"] >= linked["start_time"]).all()
    assert (linked["session_end_time"] <= linked["end_time"]).all()
    assert (linked["session_end_time"] > linked["session_start_time"]).all()
    expected = sessions.groupby("broadcast_id").agg(observed_sessions=("session_id", "size"), observed_viewers=("user_id", "nunique"), observed_watch_time_total=("watch_time", "sum"))
    pd.testing.assert_frame_equal(expected, broadcasts.set_index("broadcast_id")[expected.columns])
    assert broadcasts["observed_sessions"].sum() == len(sessions)
    assert len(broadcasts) != len(sessions)


def test_overall_and_stratified_experiment_examples_have_distinct_outputs():
    from insightpilot.data.example_questions import get_example_question
    from insightpilot.playbooks.executor import execute_playbook
    tables = generate_demo_scenario("content", "small").tables
    results = []
    for identifier in ["ct02", "ct09"]:
        config = get_example_question(identifier).apply_settings()
        results.append(execute_playbook(config["playbook_id"], tables, config["column_mapping"], config["parameters"]))
    assert "experiment_stratified" not in results[0].result_tables
    assert not results[1].result_tables["experiment_stratified"].empty


@pytest.mark.parametrize("scenario", ["transaction", "content", "live"])
def test_large_observed_events_never_precede_user_registration(scenario):
    tables = generate_demo_scenario(scenario, "large").tables
    users = tables["users"].set_index("user_id")
    fact_tables = {
        "transaction": ["transaction_detail"],
        "content": ["content_events", "experiment_assignments"],
        "live": ["live_sessions"],
    }[scenario]
    for name in fact_tables:
        events = tables[name]
        signup = events["user_id"].map(users["signup_date"])
        assert signup.notna().all(), name
        assert (events["date"] >= signup).all(), name


def test_registration_window_keeps_business_random_stream_and_distribution():
    from insightpilot.data.scenarios.common import make_users
    original_rng = np.random.default_rng(42)
    bounded_rng = np.random.default_rng(42)
    original = make_users(original_rng, 40000)
    bounded = make_users(bounded_rng, 40000, registered_by=pd.Timestamp("2025-07-01"))
    assert bounded["signup_date"].max() <= pd.Timestamp("2025-07-01")
    # Every user's registration shifts by the same duration, retaining diversity.
    assert (original["signup_date"] - bounded["signup_date"]).nunique() == 1
    pd.testing.assert_frame_equal(original.drop(columns="signup_date"), bounded.drop(columns="signup_date"))
    assert original_rng.bit_generator.state == bounded_rng.bit_generator.state
