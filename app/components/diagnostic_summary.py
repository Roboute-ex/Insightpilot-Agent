"""Small read-only projections of an already selected diagnostic result."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _topic(evidence: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(evidence.get(key, "")) for key in ("result_table", "metric", "method"))


def metric_unit(result: dict[str, Any], metric_id: str, fallback: str = "单位未确认") -> str:
    for item in result.get("metric_definitions", []):
        if isinstance(item, dict) and item.get("metric_id") == metric_id:
            unit = item.get("unit")
            if unit and unit not in {"未声明", "未确认"}:
                return str(unit)
    return fallback


def _comparison_represents_claim(row: dict[str, Any], item: dict[str, Any]) -> bool:
    support = item.get("supporting_values") or {}
    relative = row.get("relative_change")
    if not row.get("metric_name") or not _finite(relative):
        return False
    relative = float(relative)
    direction = row.get("direction") or ("上升" if relative > 0 else "下降" if relative < 0 else "持平")
    claim = f"{row['metric_name']}较{row.get('baseline_period')}{direction}{abs(relative):.1%}。"
    return (row.get("metric_id") == item.get("metric") and item.get("claim") == claim
            and all(support.get(source) == row.get(target) for source, target in (
                ("current", "current_value"), ("baseline", "baseline_value"),
                ("relative_change", "relative_change"))))


def diagnostic_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """Select existing values; no query, aggregation, chart, export or stored copy."""
    package = result.get("analysis_result_package") or {}
    tables = result.get("result_tables") or {}
    specialized = result.get("selected_playbook_id") or (result.get("playbook_result") or {}).get("playbook_id")
    if (package.get("experiment_results") or (package.get("metadata") or {}).get("exploration")
            or "adjusted_effect_summary" in tables
            or specialized in {"experiment_comparison", "causal_exploration", "funnel_analysis", "cohort_retention"}):
        return None
    values = [row for row in package.get("metric_comparisons", []) if isinstance(row, dict)]
    if not values:
        return None
    main = [row for row in values if row.get("baseline_period") == "前 7 日均值"] or values
    # One already computed baseline per metric; the full table retains every baseline.
    comparisons = list({str(row.get("metric_id")): row for row in reversed(main)}.values())[::-1][:6]
    selected = (result.get("column_mapping") or {}).get("metric_columns") or []
    metric = next((str(name) for name in selected if any(row.get("metric_id") == name for row in comparisons)), str(comparisons[0].get("metric_id", "")))
    comparisons.sort(key=lambda row: row.get("metric_id") != metric)
    contributions = [row for row in package.get("dimension_contributions", [])
        if isinstance(row, dict) and row.get("metric_id") == metric
        and all(_finite(row.get(key)) for key in ("current_value", "baseline_value", "contribution_value"))]
    dimensions = list(dict.fromkeys(str(row.get("dimension", "")) for row in contributions))
    dimensions.sort(key=lambda name: name != "city")
    groups = [{"dimension": dimension, "rows": sorted(
        (row for row in contributions if row.get("dimension") == dimension),
        key=lambda row: -abs(float(row["contribution_value"])))[:2]} for dimension in dimensions[:3]]
    evidence, covered, seen = [], [], set()
    for item in package.get("evidence", []):
        if not isinstance(item, dict):
            continue
        frame = tables.get(item.get("result_table"))
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        topic = _topic(item)
        # Exact structured support identifies an already displayed claim. A different
        # baseline, extra statistics, or unmapped prose is never discarded by keywords.
        represented = topic[0] == "metric_comparisons" and any(
            _comparison_represents_claim(row, item) for row in comparisons)
        if represented:
            covered.append(item)
        if topic in seen or len(evidence) >= 3:
            continue
        seen.add(topic)
        evidence.append({"record": item, "represented": represented})
    unit = metric_unit(result, metric, str(comparisons[0].get("unit") or "单位未确认"))
    return {"comparisons": comparisons, "metric_id": metric, "metric_unit": unit, "contribution_groups": groups,
            "evidence": evidence, "covered_evidence": covered}


def supplementary_findings(result: dict[str, Any], covered_evidence: list[dict[str, Any]]) -> list[Any]:
    """Deduplicate only findings mapped to represented structured evidence topics."""
    covered_claims = {_topic(item): str(item.get("claim", "")) for item in covered_evidence}
    # Do not infer risk or statistical content from a shared phrase or percentage.
    # In particular, a finding that appends a limitation to a claim remains intact.
    return [finding for finding in result.get("findings", [])
            if not isinstance(finding, str) or finding not in covered_claims.values()]


def visible_quality_risks(result: dict[str, Any], *, with_severity: bool = False) -> list:
    """Expose recorded problems without rescanning inputs or inferring new checks."""
    def text(value):
        if value is None or pd.api.types.is_scalar(value) and pd.isna(value):
            return ""
        return str(value).strip()

    def status_text(status):
        return {"PASS": "检查记录为通过", "FAIL": "未通过", "WARN": "警告", "PARTIAL": "检查不完整",
                "UNVERIFIED": "尚未验证", "NOT_CHECKED": "尚未检查",
                "NOT_RUN": "尚未执行", "": "状态未记录"}.get(status.upper(), status)

    risks = {}

    def add_risk(message, status):
        severity = "error" if status.upper() in {"FAIL", "ERROR"} else "warning"
        if message not in risks or severity == "error":
            risks[message] = severity

    for check in result.get("contract_results", []):
        if not isinstance(check, dict) or text(check.get("status")).upper() == "PASS":
            continue
        status = text(check.get("status"))
        details = [text(check.get("message")) or text(check.get("check_name")) or "数据检查"]
        for key, label in (("actual_value", "实际"), ("expected_value", "要求")):
            if key in check:
                details.append(label + "：" + (text(check[key]) or "无可用值"))
        subject = text(check.get("object_name"))
        add_risk((subject + "：" if subject else "") + "；".join(details) + "（" + status_text(status) + "）", status)
    reviewer = result.get("reviewer") or {}
    issues = [text(value) for value in reviewer.get("issues", []) or [] if text(value)]
    for issue in issues:
        add_risk(issue, text(reviewer.get("status")))
    if reviewer and text(reviewer.get("status")).upper() != "PASS" and not issues:
        add_risk("流程检查：" + status_text(text(reviewer.get("status"))) + "，未记录具体问题。", text(reviewer.get("status")))
    quality = (result.get("result_tables") or {}).get("data_quality")
    if isinstance(quality, pd.DataFrame):
        columns = [(key, index) for index, key in enumerate(quality.columns)
                   if key in {"table", "status", "message", "check_name", "missing_values", "duplicate_rows"}]
        for values in quality.itertuples(index=False, name=None):
            row = {key: values[index] for key, index in columns}
            status = text(row.get("status"))
            details = []
            for key, label in (("missing_values", "缺失值"), ("duplicate_rows", "重复行")):
                value = row.get(key)
                if _finite(value) and float(value) > 0:
                    details.append(label + " " + text(value))
            if status.upper() == "PASS" and not details:
                continue
            message = text(row.get("message")) or text(row.get("check_name"))
            if message:
                details.insert(0, message)
            if not details:
                details.append("数据质量存在未通过检查" if status.upper() == "FAIL" else "数据质量检查")
            subject = text(row.get("table"))
            add_risk((subject + "：" if subject and subject != "workflow" else "")
                     + "；".join(details) + "（" + status_text(status) + "）", status)
    return [(severity, message) for message, severity in risks.items()] if with_severity else list(risks)
