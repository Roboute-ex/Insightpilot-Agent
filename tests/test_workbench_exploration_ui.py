"""Explicit exploration controls, immutable runs and zero-work navigation."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import pandas as pd
import pytest
from test_method_discovery_ui import start, press, watch, assert_no_work_since
from ui_session_support import session_snapshot


def navigate(app, value):
    app.segmented_control(key="workbench_page").set_value(value).run()
    assert not app.exception


def small_table(monkeypatch):
    import app.components.data_source_panel as sources
    frame = pd.DataFrame({"city":["A","A","B","B"],"channel":["x","y","x","y"],"amount":[10.,30.,20.,60.],"user_id":["u1","u1","u2","u1"]})
    monkeypatch.setattr(sources,"load_synthetic_tables",lambda *a,**k: {"small":frame})
    return frame


def configure_pivot(app, aggregation="mean"):
    navigate(app,"explore")
    app.segmented_control(key="exploration_section").set_value("pivot").run()
    app.selectbox(key="exploration_aggregation").set_value(aggregation).run()
    app.selectbox(key="exploration_metric").set_value("amount")
    app.selectbox(key="exploration_row").set_value("city")
    app.selectbox(key="exploration_column").set_value("channel")
    app.checkbox(key="exploration_confirmed").check()


def test_navigation_and_form_draft_do_no_work(monkeypatch):
    small_table(monkeypatch)
    counts = watch(monkeypatch)
    app = start()
    before = counts.copy()
    for page in ("methods","history","explore","workbench","explore"):
        navigate(app,page)
    app.segmented_control(key="exploration_section").set_value("pivot").run()
    app.selectbox(key="exploration_aggregation").set_value("mean").run()
    assert_no_work_since(counts,before)
    press(app,"exploration_generate")
    assert_no_work_since(counts,before)
    assert any("明确确认" in str(x.value) for x in app.warning)
    assert not session_snapshot(app).get("performance_pending_branch")


def test_workbench_results_follow_question_and_run_button_without_rerunning(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    press(app, "guided_run")
    result = app.session_state["last_analysis_result"]
    assert result["execution_status"] == "COMPLETED"
    assert counts["analysis"] == 1 and counts["export"] == 0
    run_id = result["run_manifest"]["run_id"]

    def assert_results_after_inputs():
        # AppTest iterates containers in their displayed order. Checking the
        # whole tree catches a result placeholder reserved above the inputs,
        # even when the result rendering function is called after execution.
        keys = [getattr(element, "key", None) for element in app.main]
        assert keys.index("question") < keys.index("guided_run") < keys.index("result_tabs"), keys

    assert_results_after_inputs()
    assert not any(item.key in {"workbench_all_methods", "workbench_result_methods", "workbench_edit_config"} for item in app.button)
    visible = "\n".join(str(item.value) for kind in ("caption", "markdown") for item in getattr(app, kind))
    assert "当前任务：已完成" not in visible
    assert "表单中未提交的编辑尚未参与本结果" not in visible
    assert run_id not in visible
    before = counts.copy()
    for tab in ("可视化诊断", "结果明细", "报告导出", "分析概览"):
        app.segmented_control(key="result_tabs").set_value(tab).run()
        assert not app.exception
        assert_results_after_inputs()
        assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == run_id
        assert_no_work_since(counts, before)
    app.session_state["guided_technical"] = True
    app.run()
    assert not app.exception
    technical = next(item for item in app.expander if item.key == "guided_technical")
    technical_text = "\n".join(str(item.value) for item in technical if item.type in {"caption", "markdown"})
    assert run_id in technical_text
    assert "数据修订" in technical_text
    assert_no_work_since(counts, before)


def test_explicit_pivot_runs_once_and_renders_real_result(monkeypatch):
    small_table(monkeypatch)
    counts = watch(monkeypatch)
    app = start()
    configure_pivot(app)
    before = counts.copy()
    press(app,"exploration_generate")
    assert counts["analysis"]-before["analysis"] == 1
    assert counts["export"] == 0
    result = app.session_state["last_analysis_result"]
    assert result is not None, ([x.value for x in app.warning], [x.value for x in app.error], session_snapshot(app).get("exploration_errors"))
    assert result["execution_status"] == "COMPLETED", result.get("errors")
    totals = result["result_tables"]["exploration_totals"]
    assert totals.loc[totals["scope"].eq("all"),"metric_value"].item() == 30
    assert "交叉表概览" in [x.value for x in app.subheader]
    before = counts.copy()
    for page in ("methods","workbench","history","explore"):
        navigate(app,page)
    assert_no_work_since(counts,before)
    assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == result["run_manifest"]["run_id"]


def test_city_event_identity_and_explicit_child(monkeypatch):
    from app.components.data_source_panel import current_dataset
    from insightpilot.analysis.drilldown import city_candidates, validate_selection, build_drilldown_config
    from app.components.exploration_panel import exploration_preflight
    counts = watch(monkeypatch)
    app = start()
    press(app,"guided_run")
    state = session_snapshot(app)
    session = state["performance_result"]
    data = state["performance_dataset"].current
    result = state["last_analysis_result"]
    node = session.history.nodes[-1]
    before_config = node.config
    before = counts.copy()
    candidates = city_candidates(result,node,data)
    assert candidates
    event = candidates[0]["payload"]
    validate_selection(event,result,node,data)
    config = build_drilldown_config(event,result,node,data)
    prepared = exploration_preflight(data,config)
    assert prepared["planning_status"] == "ready", prepared["clarification"]
    assert_no_work_since(counts,before)
    assert node.config == before_config
    for key,value in (("run_id","stale"),("dataset_revision","old"),("table_key","other"),("metric_id","other"),("value","injected' OR 1=1 --"),("group_key","fake")):
        with pytest.raises(ValueError):
            validate_selection({**event,key:value},result,node,data)
    assert_no_work_since(counts,before)
    # Streamlit AppTest does not yet expose dataframe selection; the real
    # browser covers that click. This protocol check stages the exact validated
    # frozen request and verifies the common pump, rather than injecting results.
    app.session_state["performance_pending_branch"]={"parent_run_id":node.run_id,"config":config}
    app.session_state["workbench_submit_requested"]=True
    app.run()
    assert not app.exception
    assert counts["analysis"]-before["analysis"]==1
    new = session.history.nodes[-1]
    assert app.session_state["exploration_section"] == "grouped"
    expected_date = config["parameters"]["exploration_request"]["date_from"]
    assert any(x.value.endswith(f"当日概览（{expected_date}）") for x in app.subheader)
    assert new.parent_run_id==node.run_id
    assert new.run_id!=node.run_id
    assert node.config == before_config
    assert not session.history.result_available(node,session.current)
    assert new.config["parameters"]["exploration_request"]["filters"][-1] == {"column":"city","operator":"eq","value":event["value"]}
    app.segmented_control(key="result_tabs").set_value("报告导出").run()
    assert not app.exception
    before_exports = counts.copy()
    from app.components.export_panel import export_cache_key
    selected_result = app.session_state["last_analysis_result"]
    for format_name in ("pdf","excel","bundle"):
        press(app,"generate_export_"+format_name)
        assert not app.error, [item.value for item in app.error]
        assert app.session_state["performance_export_cache"].get(export_cache_key(selected_result,format_name)) is not None
    assert counts["analysis"]==before_exports["analysis"]
    assert session.history.nodes[-1].run_id==new.run_id


def test_distribution_chart_switch_reuses_statistics(monkeypatch):
    small_table(monkeypatch)
    counts = watch(monkeypatch)
    app = start()
    navigate(app,"explore")
    app.segmented_control(key="exploration_section").set_value("distribution").run()
    app.selectbox(key="exploration_field").set_value("amount")
    app.checkbox(key="exploration_confirmed").check()
    press(app,"exploration_generate")
    result = app.session_state["last_analysis_result"]
    assert result is not None, ([x.value for x in app.warning], [x.value for x in app.error], session_snapshot(app).get("exploration_errors"))
    assert result["execution_status"] == "COMPLETED", result.get("errors")
    stats = result["result_tables"]["distribution_summary"].iloc[0]
    assert stats["mean"] == 30
    assert stats["median"] == 25
    before = counts.copy()
    app.segmented_control(key="result_tabs").set_value("可视化诊断").run()
    assert not app.exception
    chart_key = "exploration_chart_type_" + result["run_manifest"]["run_id"]
    app.selectbox(key=chart_key).set_value("box").run()
    assert not app.exception
    assert_no_work_since(counts,before)
    assert result["result_tables"]["distribution_summary"].iloc[0]["mean"] == 30
