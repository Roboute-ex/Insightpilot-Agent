"""Independent, deterministic task contracts for guided method selection.

Fixtures and expected values are authored here, independently of production
routing and statistical functions. No production output generates an oracle.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import math
from unittest.mock import patch

import pandas as pd

from insightpilot.evaluation.models import EvaluationCase

GUIDED_FAMILIES = {
    "inputs": "引导预检：字段与真实取值",
    "intent": "引导推荐：目标与表达边界",
    "valid": "引导执行：独立小表数值",
    "identity": "引导契约：身份与轻量预检",
}


def causal_fixture() -> pd.DataFrame:
    """24 rows; each group has x=0..11. E[Y|T=1]-E[Y|T=0]=2.

    The outcome is 10+x+2*T+alternating residual with mean zero in both
    groups. Covariate distributions are identical, so adjusted effect is 2.
    This is an arithmetic fixture, not proof of observational identification.
    """
    rows = []
    for group, effect in (("control", 0), ("treatment", 2)):
        for index in range(12):
            rows.append({"user_id": f"{group}-{index}", "group": group,
                         "outcome": 10 + index + effect + (-.25 if index % 2 else .25),
                         "covariate": index, "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=index)})
    return pd.DataFrame(rows)


def experiment_fixture() -> pd.DataFrame:
    """Eight rows, four independent users; user means [2,4] versus [4,6]."""
    return pd.DataFrame({"user_id": [1, 1, 2, 2, 3, 3, 4, 4],
                         "group": ["control"] * 4 + ["treatment"] * 4,
                         "outcome": [1, 3, 3, 5, 3, 5, 5, 7]})


def causal_request() -> dict:
    return {"question": "控制协变量后比较处理组与对照组的结果关联",
            "goal_mode": "causal_exploration", "playbook_id": "causal_exploration",
            "column_mapping": {"table_name": "sample", "metric_columns": ["outcome"],
                               "treatment_column": "group", "outcome_column": "outcome",
                               "dimension_columns": ["covariate"], "aggregation": "mean"},
            "playbook_parameters": {"covariates": ["covariate"], "control_value": "control", "treatment_value": "treatment"}}


def experiment_request() -> dict:
    return {"question": "按独立用户比较实验组和对照组的结果均值",
            "goal_mode": "experiment_analysis", "playbook_id": "experiment_comparison",
            "column_mapping": {"table_name": "sample", "metric_columns": ["outcome"],
                               "group_column": "group", "statistical_unit": "user_id", "aggregation": "mean"},
            "playbook_parameters": {"metric": "outcome", "metric_type": "mean",
                                    "control_value": "control", "treatment_value": "treatment", "confidence_level": .95}}


def _prepared(tables):
    from insightpilot.agents.dataset import PreparedDataset
    return PreparedDataset.from_tables(tables, dataset_id="guided-independent-fixture", revision="fixture-v1")


def _advice(prepared, request):
    from insightpilot.planning.planner import prepare_analysis_request
    return prepare_analysis_request(**request, table_metadata=prepared.metadata,
                                    dataset_revision=prepared.revision)


def _run(prepared, request):
    from insightpilot.agents.workflow import run_agent_analysis
    return run_agent_analysis(**request, tables={}, prepared_dataset=prepared,
                              data_source_type="csv", presentation_mode="deferred")


def _observed(checks, **observed):
    checks = {key: bool(value) for key, value in checks.items()}
    return {"scores": {"task_contract": float(all(checks.values()))}, "checks": checks,
            "failures": [key for key, value in checks.items() if not value], "observed": observed}


def _close(value, expected):
    return isinstance(value, (int, float)) and math.isfinite(value) and math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-9)


def _blocked(tables, request, *, statuses=("needs_clarification", "invalid_input"), field=None, reason=None):
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    prepared = _prepared(tables)
    with ExitStack() as stack:
        calls = {name: stack.enter_context(patch.object(AnalyticsEngine, name,
                 side_effect=AssertionError("预检阻断后执行了分析SQL")))
                 for name in ("run_sql", "run_parameterized_sql")}
        for name in ("execute_playbook", "analyze_ab_test", "estimate_adjusted_effect"):
            calls[name] = stack.enter_context(patch("insightpilot.agents.workflow." + name,
                          side_effect=AssertionError("预检阻断后调用了统计")))
        planned = _advice(prepared, request)
        actual = _run(prepared, request)
    advice = planned.get("analysis_advice", {})
    issues = advice.get("blocking_issues", [])
    issue_text = str(issues)
    counts = {key: value.call_count for key, value in calls.items()}
    checks = {"规划阻断状态": planned.get("planning_status") in statuses,
              "不可提交": advice.get("can_submit") is False,
              "没有已完成结果": actual.get("execution_status") != "COMPLETED",
              "分析SQL与统计零执行": all(value == 0 for value in counts.values()),
              "workflow与预检状态一致": actual.get("planning_status") == planned.get("planning_status"),
              "workflow与预检原因一致": [item.get("code") for item in actual.get("analysis_advice", {}).get("blocking_issues", [])] == [item.get("code") for item in issues],
              "具体中文原因与恢复动作": bool(issues) and all(item.get("code") and item.get("message_zh") and item.get("recovery_actions") for item in issues)}
    if field:
        checks["列出真实缺失字段"] = field in issue_text
    if field == "treatment_column":
        checks["不伪报缺少已存在结果列"] = not any(item.get("code") == "MISSING_OUTCOME_COLUMN" for item in issues)
    if reason:
        checks["解释真实取值或输入原因"] = any(word in issue_text for word in reason)
    return _observed(checks, planning_status=planned.get("planning_status"), execution_status=actual.get("execution_status"),
                     calls=counts, issues=issues, effective_method=advice.get("effective_method"))


def build_guided_task_cases() -> list[EvaluationCase]:
    """Add focused families to task; retain every historical case and oracle."""
    from insightpilot.evaluation.task_suite import daily_fixture
    cases = []

    def case(identifier, family, question, runner, expected, fixture="独立24行处理/对照小表"):
        cases.append(EvaluationCase("guided_" + identifier, "task", question, runner,
            family=GUIDED_FAMILIES[family], question=question,
            input_fixture={"name": fixture, "source": "evaluation.guided_suite 中人工固定小表"},
            expected=expected, required_evidence=("实际预检状态", "结构化原因或独立数值"),
            forbidden_behaviors=("缺输入仍执行SQL", "用生产输出生成expected", "推荐分冒充统计置信度")))

    def missing(role):
        request = causal_request()
        request["column_mapping"].pop(role)
        if role == "outcome_column":
            request["column_mapping"]["metric_columns"] = []
            table = causal_fixture().drop(columns="outcome")
        else:
            table = causal_fixture().drop(columns="group")
        return _blocked({"sample": table}, request, field=role)
    case("missing_treatment", "inputs", "仅有control/treatment组值但没有分组字段", lambda: missing("treatment_column"), {"can_submit": False, "sql_calls": 0, "missing": "treatment_column"})
    case("missing_outcome", "inputs", "没有结果字段不能计算轻量关联", lambda: missing("outcome_column"), {"can_submit": False, "sql_calls": 0, "missing": "outcome_column"})
    case("one_group", "inputs", "分组列只有对照组", lambda: _blocked({"sample": causal_fixture().assign(group="control")}, causal_request(), reason=("组",)), {"can_submit": False, "sql_calls": 0, "groups": 1})
    def absent_group():
        request = causal_request(); request["playbook_parameters"]["treatment_value"] = "not-present"
        return _blocked({"sample": causal_fixture()}, request, reason=("组", "取值"))
    case("absent_group", "inputs", "处理组取值不存在于真实数据", absent_group, {"can_submit": False, "sql_calls": 0})
    case("null_outcome", "inputs", "结果字段全为空值", lambda: _blocked({"sample": causal_fixture().assign(outcome=float("nan"))}, causal_request(), reason=("空", "有效")), {"can_submit": False, "sql_calls": 0, "valid_outcomes": 0})
    case("text_outcome", "inputs", "结果字段全部为无法转换的文本", lambda: _blocked({"sample": causal_fixture().assign(outcome="不是数字")}, causal_request(), reason=("数值", "数字", "有效")), {"can_submit": False, "sql_calls": 0})
    def missing_unit():
        request = experiment_request(); request["column_mapping"].pop("statistical_unit")
        return _blocked({"sample": experiment_fixture().drop(columns="user_id")}, request, reason=("单位", "独立"))
    case("experiment_unit", "inputs", "两组事件没有独立统计单位定义", missing_unit, {"can_submit": False, "sql_calls": 0}, "8事件无user_id")
    def missing_direction():
        request = experiment_request(); request["playbook_parameters"].pop("control_value"); request["playbook_parameters"].pop("treatment_value")
        return _blocked({"sample": experiment_fixture().replace({"control": "甲组", "treatment": "乙组"})}, request, reason=("组", "方向"))
    case("experiment_direction", "inputs", "两组真实存在但用户未明确对照方向", missing_direction, {"can_submit": False, "sql_calls": 0}, "8事件两组为甲组/乙组")
    trend_request = {"question": "查看订单量趋势", "goal_mode": "growth_trend", "playbook_id": "metric_trend",
                     "column_mapping": {"table_name": "daily", "metric_columns": ["orders"], "aggregation": "sum"}}
    case("trend_without_date", "inputs", "订单数据没有日期，不能回答时间趋势", lambda: _blocked({"daily": daily_fixture().drop(columns="date")}, deepcopy(trend_request), field="date"), {"can_submit": False, "sql_calls": 0}, "16行订单小表，移除date")
    def invalid_date():
        request = deepcopy(trend_request); request["column_mapping"]["date_column"] = "date"
        return _blocked({"daily": daily_fixture().assign(date="非法日期")}, request, reason=("日期", "时间"))
    case("trend_bad_date", "inputs", "日期字段存在但全部不可解析", invalid_date, {"can_submit": False, "sql_calls": 0}, "16行date均不可解析")
    for identifier, question in (("ambiguous_conversion", "转化率为什么下降？"), ("ambiguous_revenue", "收入是多少？")):
        case(identifier, "intent", question,
             lambda q=question: _blocked({"daily": daily_fixture()}, {"question": q}, statuses=("needs_clarification",)),
             {"planning_status": "needs_clarification", "sql_calls": 0}, "16行，多转化率/支付金额，未确认口径")
    for identifier, question in (("forecast", "预测未来30天订单量"), ("causal_proof", "证明城市导致订单量下降的因果关系")):
        case(identifier, "intent", question,
             lambda q=question: _blocked({"daily": daily_fixture()}, {"question": q}, statuses=("unsupported",)),
             {"planning_status": "unsupported", "sql_calls": 0}, "16行订单小表")
    case("empty_request", "intent", "空问题不能默认执行画像", lambda: _blocked({"daily": daily_fixture()}, {"question": ""}, statuses=("invalid_input", "needs_clarification")), {"can_submit": False, "sql_calls": 0}, "16行订单小表")

    def negation():
        request = {"question": "不做因果，只比较本周和上周的订单量", "column_mapping": {"table_name": "daily", "date_column": "date", "metric_columns": ["orders"], "aggregation": "sum"}}
        planned = _advice(_prepared({"daily": daily_fixture()}), request)
        advice = planned.get("analysis_advice", {}); chosen = advice.get("effective_method", {})
        return _observed({"否定因果不选因果": chosen.get("method_ref") != "playbook:causal_exploration",
                          "采用周期比较": chosen.get("method_ref") == "playbook:period_comparison"}, advice=advice)
    case("negated_causal", "intent", "不做因果，只比较本周和上周的订单量", negation, {"method_ref": "playbook:period_comparison"}, "16行订单小表")

    def valid_causal():
        prepared = _prepared({"sample": causal_fixture()}); request = causal_request()
        planned = _advice(prepared, request); actual = _run(prepared, request)
        table = actual.get("result_tables", {}).get("adjusted_effect_summary", pd.DataFrame())
        row = table.iloc[0].to_dict() if len(table) else {}
        caveats = str(actual.get("playbook_result", {})) + str(actual.get("analysis_result_package", {}))
        return _observed({"预检就绪": planned.get("planning_status") == "ready", "因果探索可执行": actual.get("execution_status") == "COMPLETED",
                          "朴素差独立预期2": _close(row.get("naive_difference"), 2), "调整差独立预期2": _close(row.get("adjusted_effect"), 2),
                          "保留识别边界": "因果" in caveats and any(word in caveats for word in ("不代表", "不能", "不等于", "谨慎"))}, summary=row, execution_status=actual.get("execution_status"))
    case("valid_causal", "valid", "已知平衡协变量两组的轻量关联", valid_causal, {"naive_difference": 2, "adjusted_effect": 2, "status": "COMPLETED"})

    def valid_experiment():
        prepared = _prepared({"sample": experiment_fixture()}); request = experiment_request()
        planned = _advice(prepared, request); actual = _run(prepared, request)
        items = actual.get("analysis_result_package", {}).get("experiment_results", []); row = items[0] if items else {}
        return _observed({"预检就绪": planned.get("planning_status") == "ready", "实验成功": actual.get("execution_status") == "COMPLETED",
                          "每组两个独立用户": row.get("control_sample_size") == row.get("treatment_sample_size") == 2,
                          "差为2": _close(row.get("absolute_lift"), 2), "Welch闭式p值": _close(row.get("p_value"), 1 - 1 / math.sqrt(2))}, result=row, execution_status=actual.get("execution_status"))
    case("valid_user_experiment", "valid", "重复事件按user_id作为独立单位执行实验", valid_experiment, {"n_each": 2, "difference": 2, "p_value": 1 - 1 / math.sqrt(2)}, "user均值[2,4]与[4,6]，四个用户八个事件")

    def manual_mismatch():
        request = experiment_request(); request["question"] = "查看数据缺失和类型"; request["goal_mode"] = "auto"; request["playbook_id"] = "experiment_comparison"
        planned = _advice(_prepared({"sample": experiment_fixture()}), request)
        advice = planned.get("analysis_advice", {}); current = advice.get("requested_method", {})
        candidates = [current, *advice.get("candidates", []), *advice.get("other_methods", [])]
        candidate = next((item for item in candidates if item.get("method_ref") == "playbook:experiment_comparison" and "goal_fit" in item), {})
        return _observed({"手动选择不被偷换": current.get("method_ref") == "playbook:experiment_comparison",
                          "不匹配不能提交": advice.get("can_submit") is False,
                          "数据可用与问题匹配分开": candidate.get("goal_fit") == "unrelated" and candidate.get("data_readiness") == "ready"}, advice=advice)
    case("manual_goal_conflict", "intent", "实验可以执行但不能回答数据质量问题", manual_mismatch, {"goal_fit": "unrelated", "data_readiness": "ready", "can_submit": False}, "四个独立用户小表")

    def identity_and_lightness():
        prepared = _prepared({"sample": causal_fixture()}); request = causal_request()
        with patch("insightpilot.agents.dataset.fingerprint_dataframe", side_effect=AssertionError("建议重做完整哈希")), patch("insightpilot.agents.dataset.infer_schema_mapping", side_effect=AssertionError("建议重做画像")), patch("insightpilot.agents.workflow.run_agent_analysis", side_effect=AssertionError("建议触发分析")):
            first = _advice(prepared, request)["analysis_advice"]
            second = _advice(prepared, request)["analysis_advice"]
            changed = deepcopy(request); changed["playbook_parameters"]["treatment_value"] = "absent"
            third = _advice(prepared, changed)["analysis_advice"]
        return _observed({"同请求身份稳定": first.get("request_fingerprint") == second.get("request_fingerprint") and bool(first.get("request_fingerprint")),
                          "参数变更身份失效": first.get("request_fingerprint") != third.get("request_fingerprint"),
                          "旧建议不允许新错误参数": first.get("can_submit") is True and third.get("can_submit") is False}, first_fingerprint=first.get("request_fingerprint"), changed_fingerprint=third.get("request_fingerprint"))
    case("identity_lightness", "identity", "建议复用摘要且组值变化使旧建议失效", identity_and_lightness, {"profile_calls": 0, "full_hash_calls": 0, "analysis_calls": 0, "parameter_change_invalidates": True})
    def one_valid_outcome_group():
        frame = causal_fixture()
        frame.loc[frame["group"] == "treatment", "outcome"] = float("nan")
        return _blocked({"sample": frame}, causal_request(), reason=("有效", "组"))
    case("outcome_missing_in_treatment", "inputs", "处理组字段存在但处理组结果全部为空", one_valid_outcome_group,
         {"can_submit": False, "sql_calls": 0, "valid_treatment_outcomes": 0})

    def metadata_without_values():
        from insightpilot.planning.planner import prepare_analysis_request
        request = causal_request()
        metadata = {"sample": {"columns": ["group", "outcome", "covariate"], "row_count": 24,
                              "schema_mapping": {"possible_metric_columns": ["outcome"], "possible_dimension_columns": ["group", "covariate"]}}}
        planned = prepare_analysis_request(**request, table_metadata=metadata)
        advice = planned.get("analysis_advice", {})
        issues = advice.get("blocking_issues", [])
        return _observed({"列名不冒充已检查真实值": advice.get("can_submit") is False,
                          "明确需要数据准备": any(item.get("data_readiness") == "needs_preparation" for item in issues)}, advice=advice)
    case("metadata_not_value_evidence", "identity", "仅有列清单时不得宣称真实两组和有效结果已经核实", metadata_without_values,
         {"can_submit": False, "data_readiness": "needs_preparation"}, "仅有列名和行数，没有精确值摘要")
    return cases
