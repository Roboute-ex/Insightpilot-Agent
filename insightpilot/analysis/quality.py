"""Read-only quality dimensions over existing evidence, never a probability score."""
from __future__ import annotations
from typing import Any

QUALITY_NOTICE = "流程检查评分不代表统计结论百分之百正确；未验证的前提不会因评分较高而变为已验证。"
QUALITY_DIMENSION_NAMES = {"execution_status": "执行", "definition_status": "指标口径", "data_quality_status": "数据质量", "inference_status": "统计前提", "evidence_status": "证据"}


def derive_quality_status(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Summarize completed checks without rescanning input data or rerunning analysis."""
    package = result.get("analysis_result_package") or {}
    execution = str(result.get("execution_status") or package.get("execution_status") or "UNKNOWN")
    executed = execution == "COMPLETED" and not result.get("errors")
    execution_labels = {"COMPLETED": "已执行", "PREVIEW": "仅预览", "WAITING_APPROVAL": "等待审批", "NEEDS_INPUT": "需要补充输入", "FAILED": "执行失败", "CANCELLED": "已取消"}
    dimensions = {"execution_status": {"status": "completed" if executed else "not_completed", "label": execution_labels.get(execution, "执行状态未确认"), "reason": "已完成本次分析流程；这不验证统计前提。" if executed else "尚无成功完成的分析，不把空结果解释为零。"}}
    definitions = result.get("metric_definitions") or []
    confirmed = bool(definitions) and all(isinstance(d, dict) and d.get("definition_status") in {"user_confirmed", "builtin_verified"} and all(d.get(k) not in (None, "", "未声明", "未确认") for k in ("metric_id", "definition_version", "unit", "expression", "aggregation")) for d in definitions)
    dimensions["definition_status"] = {"status": "confirmed" if confirmed else "unverified", "label": "已确认口径" if confirmed else "口径待确认", "reason": "采用已确认的指标定义；确认来源不等于因果正确性。" if confirmed else "缺少完整且已确认的指标定义；自动建议和导入内容不等于用户授权。"}
    checks = [str(c.get("status", "")) for c in result.get("contract_results", []) if isinstance(c, dict)]
    # The small per-table data_quality summary was already computed by the workflow.
    quality = (result.get("result_tables") or {}).get("data_quality")
    if quality is not None and hasattr(quality, "columns") and "status" in quality.columns:
        checks.extend(str(value) for value in quality["status"].head(256).tolist())
        if len(quality)>256:
            checks.append("PARTIAL")
    failed = any(s == "FAIL" for s in checks)
    warned = any(s != "PASS" for s in checks)
    quality_status = "failed" if failed else "warning" if warned else "checked" if checks else "unverified"
    dimensions["data_quality_status"] = {"status": quality_status, "label": {"failed": "存在未通过检查", "warning": "存在质量提示", "checked": "已通过已执行检查", "unverified": "数据质量未验证"}[quality_status], "reason": f"依据本次已执行的 {len(checks)} 项契约/数据摘要检查；不代表检查范围之外也无问题。" if checks else "当前结果没有可核对的数据检查记录。"}
    inference = bool(package.get("experiment_results")) or str(result.get("goal_mode")) in {"experiment_analysis", "causal_exploration"}
    dimensions["inference_status"] = {"status": "unverified" if inference else "not_applicable", "label": "统计前提尚未验证" if inference else "描述性分析，不作推断认证", "reason": "已有点估计、p 值或区间不能证明随机化、独立性、无混杂等前提；本次未新增这些诊断。" if inference else "当前展示的是描述性结果或规则信号，不据此认定因果或上线收益。"}
    evidence = package.get("evidence") or []
    ids = [str(e.get("evidence_id", "")) for e in evidence if isinstance(e, dict)]
    tables = result.get("result_tables") or {}
    summarized_tables = package.get("result_tables") or {}
    complete = bool(evidence) and len(ids) == len(evidence) and all(ids) and len(set(ids)) == len(ids)
    complete = complete and all(isinstance(e, dict) and e.get("claim") and e.get("method") and e.get("result_table") in (set(tables) | set(summarized_tables)) for e in evidence)
    complete = complete and all(isinstance(r, dict) and r.get("supporting_evidence_ids") and set(r["supporting_evidence_ids"]).issubset(set(ids)) for r in package.get("recommendations", []))
    dimensions["evidence_status"] = {"status": "linked" if complete else "unverified", "label": "证据引用完整" if complete else "证据仍需复核", "reason": "现有证据标识、结果表及建议引用相互对应；不等于证据内容已被独立复算。" if complete else "没有完整且可对应的证据引用，不能仅据流程评分判定结论可信。"}
    return dimensions


def quality_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    return [{"检查维度": QUALITY_DIMENSION_NAMES[key], "状态": item["label"], "依据与边界": item["reason"]} for key, item in derive_quality_status(result).items()]
