"""Real form interactions: suggested experiment directions require a choice."""
from collections import Counter
from pathlib import Path
import functools
import pandas as pd
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app/ui_streamlit.py"
PREFIX = "playbook_parameter_experiment_comparison_"


def click(app, label):
    # Parameters live in their own form: explicitly apply them before submitting
    # the analysis request, rather than relying on an unsubmitted widget value.
    if label == "开始分析" and any(item.label == "应用参数并更新建议" for item in app.button):
        next(item for item in app.button if item.label == "应用参数并更新建议").click().run()
        assert not app.exception
    next(item for item in app.button if item.label == label).click().run()
    assert not app.exception


def fixture_csv():
    return pd.DataFrame({"date": ["2026-01-01"] * 8, "user_id": [f"u{i}" for i in range(8)],
        "arm": ["control"] * 4 + ["treatment"] * 4,
        "other_arm": ["control", "treatment"] * 4,
        "score": [1, 2, 3, 4, 3, 4, 5, 6]}).to_csv(index=False).encode("utf-8")


def custom_experiment(monkeypatch):
    import insightpilot.agents.workflow as workflow
    counts = Counter()
    original = workflow.run_agent_analysis
    @functools.wraps(original)
    def watched(*args, **kwargs):
        counts["analysis"] += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(workflow, "run_agent_analysis", watched)
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["demo_scale"] = "small"
    app.session_state["data_source_selector"] = "upload"
    app.run()
    app.file_uploader[0].set_value(("trial.csv", fixture_csv(), "text/csv")).run()
    app.session_state["guided_advanced"] = True
    app.session_state["guided_mapping_open"] = True; app.run()
    app.text_input(key="question").set_value("实验效果")
    app.session_state["guided_advanced"] = True; app.run()
    app.selectbox(key="goal_mode_selector").set_value("experiment_analysis")
    app.selectbox(key="playbook_selector").set_value("experiment_comparison").run()
    app.multiselect(key="mapping_metrics").set_value(["score"])
    app.multiselect(key="mapping_dimensions").set_value([])
    app.selectbox(key="mapping_group").set_value("arm").run()
    click(app, "确认当前字段映射")
    app.text_input(key=PREFIX + "statistical_unit").set_value("user_id").run()
    assert not app.exception
    return app, counts


def test_custom_experiment_directions_are_not_implicitly_confirmed(monkeypatch):
    app, counts = custom_experiment(monkeypatch)
    # Neither direction was touched; confirming column roles is not direction consent.
    click(app, "应用参数并更新建议")
    assert app.button(key="guided_run").disabled
    assert counts["analysis"] == 0, "Untouched default control/treatment values reached the analysis engine"
    assert app.selectbox(key=PREFIX + "control_value").value is None
    assert app.selectbox(key=PREFIX + "treatment_value").value is None
    app.selectbox(key=PREFIX + "control_value").set_value("control")
    app.selectbox(key=PREFIX + "treatment_value").set_value("treatment")
    click(app, "开始分析")
    assert counts["analysis"] == 1
    result = app.session_state["last_analysis_result"]
    assert result["execution_status"] == "COMPLETED"
    values = result["analysis_result_package"]["experiment_results"][0]
    assert values["control_sample_size"] == values["treatment_sample_size"] == 4
    assert values["absolute_lift"] == 2


def test_experiment_direction_choices_are_scoped_to_dataset_and_group(monkeypatch):
    app, counts = custom_experiment(monkeypatch)
    app.selectbox(key=PREFIX + "control_value").set_value("control")
    app.selectbox(key=PREFIX + "treatment_value").set_value("treatment")
    click(app, "开始分析")
    assert counts["analysis"] == 1
    app.selectbox(key="mapping_group").set_value("other_arm").run()
    assert app.selectbox(key=PREFIX + "control_value").value is None
    assert app.selectbox(key=PREFIX + "treatment_value").value is None
    # Even identical group labels in another dataset revision are not confirmation.
    app.selectbox(key=PREFIX + "control_value").set_value("control")
    app.selectbox(key=PREFIX + "treatment_value").set_value("treatment").run()
    before = app.session_state["performance_dataset"].current.revision
    changed = fixture_csv().replace(b",1\n", b",9\n")
    app.file_uploader[0].set_value(("trial.csv", changed, "text/csv")).run()
    assert app.session_state["performance_dataset"].current.revision != before
    # A new revision also clears invalid field mappings; the direction control
    # can become empty text until a real group field is selected again.
    controls = [*app.selectbox, *app.text_input]
    assert next(x for x in controls if x.key == PREFIX + "control_value").value in (None, "")
    assert next(x for x in controls if x.key == PREFIX + "treatment_value").value in (None, "")
    assert counts["analysis"] == 1


def test_confirmed_history_restores_direction_only_within_its_original_context(monkeypatch):
    app, counts = custom_experiment(monkeypatch)
    app.selectbox(key=PREFIX + "control_value").set_value("control")
    app.selectbox(key=PREFIX + "treatment_value").set_value("treatment")
    click(app, "开始分析")
    assert counts["analysis"] == 1
    app.selectbox(key="mapping_group").set_value("other_arm").run()
    assert app.selectbox(key=PREFIX + "control_value").value is None
    app.segmented_control(key="workbench_page").set_value("history").run()
    click(app, "恢复此运行配置")
    assert app.selectbox(key="mapping_group").value == "arm"
    assert app.selectbox(key=PREFIX + "control_value").value == "control"
    assert app.selectbox(key=PREFIX + "treatment_value").value == "treatment"
    assert app.text_input(key=PREFIX + "statistical_unit").value == "user_id"
    assert counts["analysis"] == 1


def test_builtin_experiment_keeps_verified_direction_without_reasking():
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["demo_scale"] = "small"
    app.run()
    scenario = next(value for value in app.selectbox(key="demo_scenario").options if "内容" in value)
    app.selectbox(key="demo_scenario").set_value(scenario).run()
    app.session_state["guided_advanced"] = True; app.run()
    app.selectbox(key="goal_mode_selector").set_value("experiment_analysis")
    app.selectbox(key="playbook_selector").set_value("experiment_comparison").run()
    assert not app.exception
    assert app.selectbox(key=PREFIX + "control_value").value == "control"
    assert app.selectbox(key=PREFIX + "treatment_value").value == "treatment"
    click(app, "开始分析")
    assert app.session_state["last_analysis_result"]["execution_status"] == "COMPLETED"


def test_auto_experiment_history_restores_only_confirmed_same_context_directions(monkeypatch):
    app, counts = custom_experiment(monkeypatch)
    app.selectbox(key="playbook_selector").set_value("auto").run()
    app.text_input(key=PREFIX + "statistical_unit").set_value("user_id")
    app.selectbox(key=PREFIX + "control_value").set_value("control")
    app.selectbox(key=PREFIX + "treatment_value").set_value("treatment")
    click(app, "开始分析")
    assert counts["analysis"] == 1
    node = app.session_state["performance_result"].history.nodes[-1]
    assert node.config["playbook_id"] == "auto"
    assert node.config["effective_playbook_id"] == "experiment_comparison"
    app.selectbox(key="mapping_group").set_value("other_arm").run()
    assert app.selectbox(key=PREFIX + "control_value").value is None
    assert app.selectbox(key=PREFIX + "treatment_value").value is None
    app.segmented_control(key="workbench_page").set_value("history").run()
    click(app, "恢复此运行配置")
    assert app.selectbox(key="playbook_selector").value == "auto"
    assert app.selectbox(key="mapping_group").value == "arm"
    assert app.selectbox(key=PREFIX + "control_value").value == "control"
    assert app.selectbox(key=PREFIX + "treatment_value").value == "treatment"
    assert app.text_input(key=PREFIX + "statistical_unit").value == "user_id"
    assert app.session_state["guided_parameters"]["treatment_value"] == "treatment"
    assert counts["analysis"] == 1
