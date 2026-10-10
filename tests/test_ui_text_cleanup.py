"""Presentation cleanup keeps calculated results and actionable boundaries intact."""
from copy import deepcopy

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.analysis.quality import QUALITY_NOTICE, quality_rows
from test_method_discovery_ui import assert_no_work_since, press, start, watch


REDUNDANT_COPY = (
    "完整观测分组保存在", "exploration_cells", "未观测组合为缺失而非0",
    "行/列/总计均在原始对应范围重聚合", "当前为已选范围的描述性探索",
    "质量摘要：", "依据本次已执行的", "不代表检查范围之外也无问题",
    "当前展示的是描述性结果或规则信号", "不据此认定因果或上线收益",
    "现有证据标识、结果表及建议引用相互对应", "不等于证据内容已被独立复算",
)


def _text(app):
    return "\n".join(str(item.value) for kind in (
        "markdown", "caption", "info", "warning", "error", "success", "subheader"
    ) for item in getattr(app, kind))


def _render(result):
    app = AppTest.from_string('''
import streamlit as st
from app.components.result_panel import render_result_panel
render_result_panel(st.session_state["fixture_result"])
''', default_timeout=90)
    app.session_state["fixture_result"] = result
    app.run()
    assert not app.exception
    return app


def _pivot(*, top_n=20, question="查看城市渠道交叉表", current_day_only=False):
    from test_workbench_exploration import frame4, mapping
    frame = frame4()
    request = {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel", "top_n": top_n}
    cm = mapping("mean")
    if current_day_only:
        frame["date"] = "2026-09-03"
        previous = frame.assign(date="2026-08-27", amount=frame.amount * 3)
        frame = pd.concat([frame, previous], ignore_index=True)
        cm["date_column"] = "date"
        request["filters"] = [{"column": "date", "operator": "eq", "value": "2026-09-03"}]
    result = run_agent_analysis(question, {}, goal_mode="periodic_report",
        playbook_id="dimension_contribution", column_mapping=cm,
        playbook_parameters={"exploration_request": request},
        prepared_dataset=PreparedDataset.from_tables({"sample": frame}),
        data_source_type="uploaded_files", presentation_mode="deferred", selection_source="user_selected")
    assert result["execution_status"] == "COMPLETED", (result.get("errors"), result.get("analysis_advice"))
    return result


@pytest.fixture(scope="module")
def cleanup_results(transaction_result):
    from test_causal_result_presentation import _run
    pivot = _pivot()
    assert pivot["result_tables"]["exploration_totals"].query("scope == 'all'").metric_value.item() == 30
    causal = _run()
    row = causal["result_tables"]["adjusted_effect_summary"].iloc[0]
    assert row.adjusted_effect == pytest.approx(2) and row.sample_size == 24
    return {"transaction": transaction_result, "pivot": pivot, "causal": causal}


@pytest.mark.parametrize("kind", ["transaction", "pivot", "causal"])
def test_default_results_are_concise_and_original_five_dimensions_remain_in_details(cleanup_results, kind, monkeypatch):
    result = deepcopy(cleanup_results[kind])
    original = deepcopy(result)
    expected = quality_rows(result)
    assert len(expected) == 5
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    compact = _text(app).replace(" ", "")
    unexpected = [copy for copy in REDUNDANT_COPY if copy.replace(" ", "") in compact]
    assert not unexpected, (unexpected, _text(app))
    assert "结果表标识：" not in compact and "条结构化证据" not in compact
    assert all(row["依据与边界"] not in _text(app) for row in expected)
    assert app.dataframe and app.segmented_control(key="result_tabs").value == "分析概览"
    if kind == "causal":
        assert "2.0000" in _text(app) and "24" in _text(app)
        assert "不是因果证明" in _text(app)
    elif kind == "pivot":
        assert "30" in _text(app) and "当前范围观测行数" in _text(app)
    else:
        assert "发生了什么" in _text(app) and "变化集中在哪里" in _text(app)

    app.session_state["guided_quality"] = True
    app.run()
    assert not app.exception
    shown = _text(app)
    for row in expected:
        assert row["检查维度"] in shown and row["状态"] in shown
        assert row["依据与边界"] not in shown
    assert QUALITY_NOTICE not in shown
    app.session_state["guided_technical"] = True
    app.run()
    assert not app.exception
    frames = [item.value for item in app.dataframe if list(item.value.columns) == ["检查维度", "状态", "依据与边界"]]
    assert len(frames) == 1 and frames[0].to_dict("records") == expected
    assert _text(app).count(QUALITY_NOTICE) == 1
    assert_no_work_since(counts, before)
    assert quality_rows(result) == expected
    assert result["analysis_result_package"] == original["analysis_result_package"]
    for name, frame in original["result_tables"].items():
        pd.testing.assert_frame_equal(result["result_tables"][name], frame)


@pytest.mark.parametrize("severity", ["WARN", "FAIL"])
@pytest.mark.parametrize("source", ["contract", "reviewer", "data_quality"])
def test_specific_existing_check_messages_remain_visible_without_details(cleanup_results, severity, source, monkeypatch):
    # These are presentation fixtures for the existing upstream check schema;
    # this test does not claim to recompute a source-data quality check.
    result = deepcopy(cleanup_results["transaction"])
    message = "支付订单存在 2 条重复记录，金额汇总需复核"
    if source == "contract":
        result["contract_results"] = [{"status": severity, "message": message}]
    elif source == "reviewer":
        result["reviewer"] = {"status": severity, "issues": [message]}
    else:
        result["result_tables"]["data_quality"] = pd.DataFrame([{"status": severity, "message": message}])
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    expected_alerts = app.warning if severity == "WARN" else app.error
    assert any(message in str(item.value) for item in expected_alerts)
    if severity == "WARN":
        assert not any(message in str(item.value) for item in app.error)
    assert not any(list(item.value.columns) == ["检查维度", "状态", "依据与边界"] for item in app.dataframe)
    assert_no_work_since(counts, before)


def test_pivot_display_limit_stays_visible_once_and_full_result_is_unchanged(monkeypatch):
    result = _pivot(top_n=1)
    note = result["analysis_result_package"]["metadata"]["exploration"]["display_note"]
    assert "展示至多" in note
    original = result["result_tables"]["exploration_cells"].copy(deep=True)
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    shown = _text(app)
    assert "展示至多" in shown and shown.count("展示至多") == 1
    assert "Others" in shown
    assert "完整观测分组保存在" not in shown and "结果表标识：" not in shown
    assert result["analysis_result_package"]["metadata"]["exploration"]["display_note"] == note
    pd.testing.assert_frame_equal(result["result_tables"]["exploration_cells"], original)
    assert len(original) == 4
    assert_no_work_since(counts, before)


def test_unknown_exploration_note_and_mixed_finding_do_not_lose_specific_risk(cleanup_results, monkeypatch):
    result = deepcopy(cleanup_results["pivot"])
    metadata = result["analysis_result_package"]["metadata"]["exploration"]
    original_note = metadata["display_note"]
    unknown = "金额字段的新口径版本缺失，需要先确认退款是否扣除。"
    mixed = original_note + " 其中退款金额缺失 2 条，不能据此判断净收入。"
    metadata["display_note"] = unknown
    result["findings"].append(mixed)
    result["findings"].append("结果表 exploration_cells 第 1 行金额为 10，退款字段仍需复核。")
    result["caveats"].append("本次支付记录缺少交易状态，成功支付率不可计算。")
    result["caveats"].append({"severity": "error", "message_zh": "日期字段解析失败 2 条，不能用于跨期比较。"})
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    assert unknown in _text(app)
    assert "退款金额缺失 2 条" in _text(app)
    assert "成功支付率不可计算" in _text(app)
    assert "第 1 行金额为 10" in _text(app)
    assert any("日期字段解析失败 2 条" in str(item.value) for item in app.error)
    assert mixed in result["findings"] and metadata["display_note"] == unknown
    assert_no_work_since(counts, before)


def test_cross_period_question_with_only_current_day_exploration_reports_incomplete_answer(monkeypatch):
    result = _pivot(current_day_only=True)
    # Historical/imported display fixture; current preflight correctly blocks
    # submitting this broader question to the static method. Do not bypass it.
    result["question"] = "比较昨日金额与上周同日，各城市变化贡献是多少？"
    assert result["analysis_result_package"]["metadata"]["exploration"]["scope_row_count"] == 4
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    warnings = "\n".join(str(item.value) for item in app.warning)
    assert "未完整回答" in warnings
    assert "对比" in warnings or "跨期" in warnings
    assert_no_work_since(counts, before)


def test_experiment_statistics_and_method_limits_remain(experiment_result, monkeypatch):
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(experiment_result)
    shown = _text(app)
    assert "p-value" in shown and "95% 置信区间" in shown and "样本量" in shown
    assert "因果" in shown and ("假设" in shown or "前提" in shown or "随机" in shown)
    assert_no_work_since(counts, before)


def test_complete_baseline_implementation_notes_are_not_repeated_in_result(monkeypatch):
    from test_core_result_focus import _result
    result = _result()
    note = "基准日期完整性 7/7；z-score 使用总体标准差，基准样本数 7"
    result["analysis_result_package"]["metric_comparisons"][0]["confidence_note"] = note
    result["analysis_result_package"]["evidence"][0]["caveat"] = note
    frozen = deepcopy(result["analysis_result_package"])
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    assert "基准日期完整性 7/7" not in _text(app)
    assert "z-score 使用总体标准差" not in _text(app)
    assert "当前值：70" in _text(app) and "100" in _text(app)
    assert result["analysis_result_package"] == frozen
    assert_no_work_since(counts, before)


@pytest.mark.parametrize("note,visible", [
    ("基准日期完整性 3/7；只有 3 个观测日，基准不足", "基准日期完整性 3/7"),
    ("基准日期完整性 7/7，另有退款金额缺失 2 条", "退款金额缺失 2 条"),
])
def test_incomplete_baseline_and_unrecognized_mixed_note_keep_specific_risks(note, visible, monkeypatch):
    from test_core_result_focus import _result
    result = _result()
    result["analysis_result_package"]["metric_comparisons"][0]["confidence_note"] = note
    result["analysis_result_package"]["evidence"][0]["caveat"] = note
    frozen = deepcopy(result["analysis_result_package"])
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render(result)
    assert visible in _text(app)
    assert result["analysis_result_package"] == frozen
    assert_no_work_since(counts, before)


@pytest.mark.parametrize("limited", [False, True])
def test_chart_limit_caption_only_appears_for_recorded_actual_limits(limited, monkeypatch):
    from insightpilot.visualization.specs import ChartSpec
    metadata = {"display_note": "折线图展示 20 个点，原始结果包含 100 个点。", "series_limit_applied": 3} if limited else {}
    spec = ChartSpec("existing", "line", "既有图", "result", metadata=metadata)
    counts = watch(monkeypatch)
    before = counts.copy()
    app = AppTest.from_string('''
import streamlit as st
from app.components.result_layout import render_chart_limits
render_chart_limits(st.session_state["fixture_spec"])
''')
    app.session_state["fixture_spec"] = spec
    app.run()
    assert not app.exception
    if limited:
        assert metadata["display_note"] in _text(app)
        assert "仅展示前3个序列" in _text(app)
    else:
        assert not app.caption
    assert spec.metadata == metadata
    assert_no_work_since(counts, before)


def test_explicit_empty_outcome_still_blocks_submit_and_explains_required_input(monkeypatch):
    counts = watch(monkeypatch)
    app = start()
    before = counts.copy()
    press(app, "common_choose_causal_exploration")
    app.selectbox(key="mapping_outcome").set_value("不选择").run()
    assert not app.exception
    assert app.selectbox(key="mapping_outcome").value == "不选择"
    assert app.button(key="guided_run").disabled
    issues = app.session_state["guided_advice"]["blocking_issues"]
    outcome = next(item for item in issues if item["code"] == "MISSING_OUTCOME_COLUMN")
    assert outcome["message_zh"] in _text(app)
    assert_no_work_since(counts, before)


@pytest.mark.parametrize("city", [None, "***", "<已脱敏，需重新输入>"])
def test_exploration_heading_preserves_actual_date_without_exposing_redaction_marker(city, monkeypatch):
    counts = watch(monkeypatch)
    before = counts.copy()
    result = {"analysis_result_package": {"metadata": {"exploration": {"request": {
        "kind": "grouped", "date_from": "2026-09-03", "date_to": "2026-09-03",
        "filters": [{"column": "city", "operator": "eq", "value": city}],
    }}}}}
    app = AppTest.from_string('''
import streamlit as st
from app.components.result_layout import exploration_heading
st.subheader(exploration_heading(st.session_state["fixture_result"]))
''')
    app.session_state["fixture_result"] = result
    app.run()
    assert not app.exception
    assert [item.value for item in app.subheader] == ["所选城市当日概览（2026-09-03）"]
    assert "已脱敏" not in _text(app) and "***" not in _text(app)
    assert_no_work_since(counts, before)


def test_approval_status_cannot_turn_into_completed_result_or_report(monkeypatch):
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _render({"execution_status": "WAITING_APPROVAL", "execution_mode": "execute",
        "analysis_advice": {"blocking_issues": [{"message_zh": "跨表分析计划需要明确审批。"}]},
        "result_tables": {}, "analysis_result_package": {}})
    assert "等待审批" in _text(app) and "跨表分析计划需要明确审批" in _text(app)
    assert not app.dataframe
    app.segmented_control(key="result_tabs").set_value("报告导出").run()
    assert not app.exception
    assert "不能生成成功分析报告" in _text(app)
    assert not any(str(item.key).startswith("generate_export_") for item in app.button)
    assert_no_work_since(counts, before)


def test_released_parent_and_cancel_restore_keep_visible_boundary_and_draft(monkeypatch):
    from app.session_data import AnalysisSession
    from test_core_workflow_navigation import _add, _config, _context_component_app, _metadata_snapshot, _press, _result
    session = AnalysisSession()
    parent = _add(session.history, "parent", config=_config(outcome=None))
    child = _add(session.history, "child", parent=parent.run_id)
    session.accept("child", _result(child.run_id))
    counts = watch(monkeypatch)
    before = counts.copy()
    app = _context_component_app(session, _metadata_snapshot())
    _press(app, "core_return_parent")
    assert session.history.active_node_id == parent.node_id
    assert "历史摘要" in _text(app) and "释放" in _text(app)
    _press(app, "core_restore_config")
    assert "草稿" in _text(app) and "覆盖" in _text(app)
    _press(app, "core_restore_cancel")
    assert app.text_input(key="question").value == "尚未提交的草稿"
    assert session.current["run_manifest"]["run_id"] == child.run_id
    assert_no_work_since(counts, before)
