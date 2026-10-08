"""All-method discovery and real causal configuration through the Streamlit UI.

Only the small-table loader is replaced in the arithmetic fixture. All mapping,
method, goal, group direction, execution and export changes use actual widgets.
Expander bool events use the project's AppTest adapter; a real browser is checked
separately because AppTest itself has no native Expander.click().
"""
from collections import Counter
from io import BytesIO
from pathlib import Path
import functools
import json
import re

import pandas as pd
import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest
from ui_session_support import session_snapshot
from streamlit.testing.v1.errors import AppTestError

from insightpilot.playbooks.registry import get_playbook_registry

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "ui_streamlit.py"
EXPECTED_IDS = {
    "causal_exploration", "cohort_retention", "data_profile", "dimension_contribution",
    "experiment_comparison", "funnel_analysis", "metric_trend", "period_comparison",
    "periodic_summary", "semantic_metric_query",
}


def start(scale="small"):
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["demo_scale"] = scale
    app.run()
    assert not app.exception
    return app


def panel(app, key, value=True):
    if key == "guided_all_methods" and any(item.key == "workbench_page" for item in app.segmented_control):
        app.segmented_control(key="workbench_page").set_value("methods" if value else "workbench").run()
    else:
        app.session_state[key] = value
        app.run()
    assert not app.exception


def press(app, key):
    app.button(key=key).click().run()
    assert not app.exception


def text(app):
    return "\n".join(str(x.value) for kind in ("markdown", "caption", "info", "warning", "success") for x in getattr(app, kind))


def watch(monkeypatch):
    import insightpilot.agents.dataset as dataset
    import insightpilot.agents.workflow as workflow
    import insightpilot.playbooks.executor as executor
    import app.components.data_source_panel as sources
    import app.components.export_panel as exports
    import app.background_tasks as background
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    from insightpilot.performance_tasks import TaskManager
    counts = Counter()
    targets = (
        (sources, "load_synthetic_tables", "load"), (dataset, "fingerprint_dataframe", "fingerprint"),
        (workflow, "run_agent_analysis", "analysis"), (workflow, "execute_playbook", "playbook"),
        (executor, "estimate_adjusted_effect", "causal_statistics"),
        (AnalyticsEngine, "run_sql", "sql"), (AnalyticsEngine, "run_parameterized_sql", "bound_sql"),
        (exports, "prepare_export_payload", "export"), (background, "request_work", "request_work"),
        (TaskManager, "submit", "submit"),
    )
    counts.update({key: 0 for _, _, key in targets})
    for owner, name, key in targets:
        original = getattr(owner, name)
        @functools.wraps(original)
        def counted(*args, _function=original, _key=key, **kwargs):
            counts[_key] += 1
            return _function(*args, **kwargs)
        monkeypatch.setattr(owner, name, counted)
    return counts


def assert_no_work_since(counts, before):
    assert counts == before, dict(counts - before)


def record(name, payload):
    destination = ROOT / "reports" / "method-discovery"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def test_directory_is_top_level_complete_and_lazy_without_advanced(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    assert "查看全部分析方法" in [item.label for item in app.button]
    assert not session_snapshot(app).get("guided_advanced", False)
    assert not any(str(item.key).startswith("guided_choose_") for item in app.button)
    before = counts.copy()
    panel(app, "guided_all_methods")
    methods = get_playbook_registry().list_all()
    assert {item.playbook_id for item in methods} == EXPECTED_IDS
    assert {str(item.key).removeprefix("guided_choose_") for item in app.button if str(item.key).startswith("guided_choose_")} == EXPECTED_IDS
    body = text(app)
    for item in methods:
        assert item.display_name in body
        assert item.description in body
        assert not app.button(key="guided_choose_" + item.playbook_id).disabled
    assert "轻量因果探索" in body and "处理" in body
    assert not session_snapshot(app).get("guided_advanced", False)
    panel(app, "guided_all_methods", False)
    assert not any(str(item.key).startswith("guided_choose_") for item in app.button)
    assert_no_work_since(counts, before)
    record("directory-apptest.json", {"methods": [{"id": x.playbook_id, "name": x.display_name} for x in methods], "before": dict(before), "after": dict(counts), "top_level": True, "lazy": True})


def test_registry_directory_does_not_depend_on_recommendation_array_completeness():
    app = AppTest.from_string("""
from app.components.guidance_panel import initialize_guidance, render_all_methods
initialize_guidance()
render_all_methods({'candidates': [], 'other_methods': []})
""")
    app.run()
    panel(app, "guided_all_methods")
    assert {str(item.key).removeprefix("guided_choose_") for item in app.button if str(item.key).startswith("guided_choose_")} == EXPECTED_IDS
    assert "待补充" in text(app)


def test_every_method_configuration_button_selects_stable_id_without_work(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    panel(app, "guided_all_methods")
    before = counts.copy()
    original_question = app.session_state["question"]
    original_goal = app.session_state["goal_mode_selector"]
    for identifier in sorted(EXPECTED_IDS):
        press(app, "guided_choose_" + identifier)
        assert app.selectbox(key="playbook_selector").value == identifier
        assert app.session_state["guided_selection_source"] == "user_selected"
        assert app.session_state["guided_advanced"] is True
        assert app.toggle(key="guided_mapping_open").value is True
        assert app.text_input(key="question").value == original_question
        assert app.session_state["goal_mode_selector"] == original_goal
        assert_no_work_since(counts, before)
        panel(app, "guided_advanced", False)
        assert "查看全部分析方法" in [item.label for item in app.button]
        panel(app, "guided_all_methods")
        assert app.button(key="guided_choose_" + identifier)
    assert not app.session_state["performance_result"].history.nodes



def test_opening_causal_configuration_preserves_current_table_and_metric(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    panel(app, "guided_advanced")
    app.toggle(key="guided_mapping_open").set_value(True).run()
    app.selectbox(key="mapping_table").set_value("daily_metrics").run()
    app.multiselect(key="mapping_metrics").set_value(["orders"]).run()
    app.selectbox(key="mapping_outcome").set_value("orders").run()
    press(app, "confirm_current_mapping")
    expected = dict(app.session_state["guided_mapping"])
    panel(app, "guided_advanced", False)
    before = counts.copy()
    panel(app, "guided_all_methods")
    press(app, "guided_choose_causal_exploration")
    actual = app.session_state["guided_mapping"]
    assert actual["table_name"] == expected["table_name"]
    assert actual["outcome_column"] == expected["outcome_column"]
    assert actual["metric_columns"] == expected["metric_columns"]
    assert app.selectbox(key="mapping_table").value == expected["table_name"]
    assert app.selectbox(key="mapping_outcome").value == expected["outcome_column"]
    assert_no_work_since(counts, before)


def test_transaction_causal_stays_visible_and_blocks_exact_missing_field_before_work(monkeypatch):
    counts = watch(monkeypatch)
    app = start(scale="standard")
    panel(app, "guided_all_methods")
    before = counts.copy()
    press(app, "guided_choose_causal_exploration")
    # Reproduce the screenshot's group values without a real treatment field.
    app.text_input(key="playbook_parameter_causal_exploration_control_value").set_value("control")
    app.text_input(key="playbook_parameter_causal_exploration_treatment_value").set_value("treatment")
    next(x for x in app.button if x.label == "应用参数并更新建议").click().run()
    assert not app.exception
    issues = app.session_state["guided_advice"]["blocking_issues"]
    codes = {item["code"] for item in issues}
    assert "MISSING_TREATMENT_COLUMN" in codes
    assert "MISSING_OUTCOME_COLUMN" not in codes
    assert app.session_state["guided_mapping"]["outcome_column"] == "orders"
    assert app.button(key="guided_run").disabled
    assert "treatment" in text(app) and "组别取值" in text(app)
    with pytest.raises(AppTestError, match="disabled"):
        app.button(key="guided_run").click()
    assert_no_work_since(counts, before)
    assert not app.session_state["performance_result"].history.nodes
    # With an explicitly removed outcome, the missing-field message must change.
    app.selectbox(key="mapping_outcome").set_value("不选择").run()
    assert "MISSING_OUTCOME_COLUMN" in {item["code"] for item in app.session_state["guided_advice"]["blocking_issues"]}
    assert_no_work_since(counts, before)
    record("invalid-causal-apptest.json", {"issues_with_real_outcome": issues, "before": dict(before), "after": dict(counts), "history_nodes": 0, "run_disabled": True})


def test_manual_method_survives_question_edit_and_requires_explicit_goal_change(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    panel(app, "guided_advanced")
    app.selectbox(key="goal_mode_selector").set_value("metric_diagnosis").run()
    panel(app, "guided_all_methods")
    press(app, "guided_choose_causal_exploration")
    assert app.session_state["goal_mode_selector"] == "metric_diagnosis"
    assert "METHOD_GOAL_MISMATCH" in str(app.session_state["guided_advice"]["blocking_issues"])
    before = counts.copy()
    panel(app, "guided_advanced", False)
    app.text_input(key="question").set_value("看看近期订单变化").run()
    assert app.session_state["playbook_selector"] == "causal_exploration"
    assert app.session_state["guided_selection_source"] == "user_selected"
    assert "已手动选择：轻量因果探索" in text(app)
    assert app.button(key="guided_run").disabled
    assert_no_work_since(counts, before)


def test_valid_causal_table_configured_from_directory_executes_and_exports_real_result(monkeypatch):
    import app.components.data_source_panel as sources
    from app.components.export_panel import export_cache_key
    # Each group has x=0..11; independent hand expectation: both raw and
    # covariate-adjusted group differences equal 2. Never alter demo rows.
    frame = pd.DataFrame([
        {"group": group, "outcome": 10 + x + effect + (-.25 if x % 2 else .25),
         "covariate": x, "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=x)}
        for group, effect in (("control", 0), ("treatment", 2)) for x in range(12)
    ])
    monkeypatch.setattr(sources, "load_synthetic_tables", lambda *args, **kwargs: {"sample": frame.copy()})
    counts = watch(monkeypatch)
    app = start()
    before = counts.copy()
    panel(app, "guided_all_methods")
    press(app, "guided_choose_causal_exploration")
    app.text_input(key="question").set_value("控制协变量后比较处理组与对照组的结果关联").run()
    app.selectbox(key="goal_mode_selector").set_value("causal_exploration").run()
    app.selectbox(key="mapping_table").set_value("sample").run()
    app.multiselect(key="mapping_metrics").set_value(["outcome"]).run()
    app.multiselect(key="mapping_dimensions").set_value(["covariate"]).run()
    app.selectbox(key="mapping_group").set_value("不选择").run()
    app.selectbox(key="mapping_treatment").set_value("group").run()
    app.selectbox(key="mapping_outcome").set_value("outcome").run()
    app.multiselect(key="mapping_covariates").set_value(["covariate"]).run()
    app.selectbox(key="mapping_aggregation").set_value("mean").run()
    press(app, "confirm_current_mapping")
    app.multiselect(key="playbook_parameter_causal_exploration_covariates").set_value(["covariate"])
    app.selectbox(key="playbook_parameter_causal_exploration_control_value").set_value("control")
    app.selectbox(key="playbook_parameter_causal_exploration_treatment_value").set_value("treatment")
    next(x for x in app.button if x.label == "应用参数并更新建议").click().run()
    assert not app.exception
    assert app.session_state["guided_advice"]["can_submit"], app.session_state["guided_advice"]["blocking_issues"]
    assert not app.button(key="guided_run").disabled
    assert_no_work_since(counts, before)
    press(app, "guided_run")
    result = app.session_state["last_analysis_result"]
    assert result["execution_status"] == "COMPLETED"
    summary = result["result_tables"]["adjusted_effect_summary"].iloc[0]
    assert summary["naive_difference"] == pytest.approx(2)
    assert summary["adjusted_effect"] == pytest.approx(2)
    assert summary["sample_size"] == 24
    assert "2.0000" in str(result)
    assert "不能把相关性直接解释为因果关系" in str(result)
    assert counts["analysis"] == counts["playbook"] == counts["causal_statistics"] == 1
    assert counts["export"] == 0
    assert counts["fingerprint"] == before["fingerprint"]
    app.segmented_control(key="result_tabs").set_value("结果明细").run()
    app.selectbox(key="result_table_selector").set_value("adjusted_effect_summary").run()
    assert any("naive_difference" in x.value.columns for x in app.dataframe)
    app.segmented_control(key="result_tabs").set_value("报告导出").run()
    generation = [item.key for item in app.button if str(item.key).startswith("generate_export_")]
    assert generation == ["generate_export_pdf", "generate_export_markdown", "generate_export_html", "generate_export_excel", "generate_export_manifest", "generate_export_bundle"]
    assert counts["export"] == 0
    press(app, "generate_export_pdf")
    payload = app.session_state["performance_export_cache"].get(export_cache_key(result, "pdf"))
    assert payload.startswith(b"%PDF")
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(payload)).pages)
    record("valid-causal-pdf-text.json", {"text": pdf_text})
    compact_pdf = "".join(pdf_text.split())
    for metric in ("naive_difference", "adjusted_effect"):
        match = re.search(r"'" + metric + r"':\s*([-+0-9.eE]+)", compact_pdf)
        assert match is not None, metric
        assert float(match.group(1)) == pytest.approx(2)
    assert "不能把相关性直接解释为因果关系" in pdf_text
    assert app.session_state["export_run_id"] == result["run_manifest"]["run_id"]
    assert counts["export"] == 1 and counts["analysis"] == 1
    record("valid-causal-apptest.json", {"fixture": "24 synthetic rows; each group x=0..11, group effect=2, alternating mean-zero residual", "injection_boundary": "Only load_synthetic_tables returns the independent fixture; all method/mapping/goal/parameter/run/export actions use widgets, no injected advice or final result", "expected_naive": 2, "expected_adjusted": 2, "actual": summary.to_dict(), "status": result["execution_status"], "run_id": result["run_manifest"]["run_id"], "before": dict(before), "after": dict(counts), "pdf_bytes": len(payload), "pdf_contains_result_and_caveat": True})


@pytest.mark.parametrize("readiness,goal_fit,expected", [
    ("ready", "matches", "可用"),
    ("needs_input", "matches", "待补充"),
    ("ready", "unrelated", "与当前问题不匹配"),
    ("incompatible", "unrelated", "当前数据不支持"),
])
def test_directory_presents_four_distinct_adapter_states(readiness, goal_fit, expected):
    # Presentation-only fixture: this tests state labels, never claims execution.
    candidate = {"method_ref": "playbook:causal_exploration", "data_readiness": readiness,
                 "goal_fit": goal_fit, "missing_inputs": []}
    app = AppTest.from_string("""
from app.components.guidance_panel import initialize_guidance, render_all_methods
initialize_guidance()
render_all_methods(ADVICE)
""".replace("ADVICE", repr({"candidates": [candidate], "other_methods": []})))
    app.run()
    panel(app, "guided_all_methods")
    assert any("轻量因果探索 · " + expected in x.value for x in app.markdown)
    assert not app.button(key="guided_choose_causal_exploration").disabled


def test_accepted_order_recommendation_after_catalog_choice_runs_once(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    panel(app, "guided_all_methods")
    press(app, "guided_choose_causal_exploration")
    assert app.button(key="guided_run").disabled
    assert counts["analysis"] == 0
    press(app, "guided_use_recommendation")
    assert app.session_state["playbook_selector"] == "auto"
    assert app.session_state["guided_advice"]["effective_method"]["method_ref"] == "route:legacy"
    assert counts["analysis"] == counts["export"] == 0
    assert not app.button(key="guided_run").disabled
    press(app, "guided_run")
    result = app.session_state["last_analysis_result"]
    assert result["execution_status"] == "COMPLETED"
    assert result["result_tables"]
    assert counts["analysis"] == 1 and counts["export"] == 0
