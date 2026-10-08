"""Small Chinese definition cards bound to the exported run, never current UI state."""
from __future__ import annotations
from typing import Any
from insightpilot.reports.manifest import sanitize_manifest_value


def bind_report_metadata(result: dict[str, Any], manifest=None) -> dict[str, Any]:
    if manifest is None:
        return result
    embedded = result.get("run_manifest") or {}
    package = result.get("analysis_result_package") or {}
    for run_id in (embedded.get("run_id"), package.get("run_id")):
        if run_id and str(run_id) != str(manifest.run_id):
            raise ValueError("导出结果与运行清单的运行编号不一致，拒绝混合不同分析。")
    if manifest.semantic_fingerprint and result.get("semantic_fingerprint") and manifest.semantic_fingerprint != result["semantic_fingerprint"]:
        raise ValueError("导出结果与运行清单的指标口径不一致。")
    if manifest.metric_definitions:
        from insightpilot.metrics.definitions import computation_payload
        original = result.get("metric_definitions") or []
        if original and computation_payload(original) != computation_payload(manifest.metric_definitions):
            raise ValueError("导出口径的实际计算定义与原结果不一致，拒绝沿用旧数值。")
        return {**result, "metric_definitions": manifest.metric_definitions}
    return result


def definition_cards(result: dict[str, Any]) -> list[dict[str, str]]:
    definitions = result.get("metric_definitions") or (result.get("run_manifest") or {}).get("metric_definitions") or []
    source_names = {"user_confirmation": "用户明确确认", "builtin_definition": "内置显式定义", "registered_definition": "已注册语义定义", "automatic_suggestion": "自动建议"}
    status_names = {"builtin_verified": "内置已验证", "user_confirmed": "用户已确认", "draft": "待确认"}
    aggregation_names = {"sum": "合计", "mean": "平均值", "count": "行数", "count_distinct": "去重计数", "ratio_of_sums": "分子分母分别求和再相除", "mean_per_independent_unit": "独立统计单位均值"}
    def display(value):
        if value in (None, "", [], {}): return "未声明/不适用"
        if isinstance(value, dict):
            labels={"current_start":"当前期开始", "current_end":"当前期结束", "previous_start":"基准期开始", "previous_end":"基准期结束", "measure_id":"已注册度量", "operation":"运算", "input_metrics":"输入指标"}
            return "；".join(f"{labels.get(str(k), str(k))}：{display(v)}" for k,v in sanitize_manifest_value(value).items())
        if isinstance(value, (list, tuple)): return "、".join(display(v) for v in value)
        return {"undefined": "未定义（不可计算）", "exclude_invalid_numeric": "排除缺失或无效数值", "naive": "未附时区（按输入定义解释）"}.get(str(value), str(sanitize_manifest_value(value)))
    output=[]
    for d in definitions[:32]:
        if not isinstance(d, dict): continue
        output.append({"指标": display(d.get("display_name") or d.get("metric_id")), "指标标识": display(d.get("metric_id")),
            "单位": display(d.get("unit")), "口径版本": display(d.get("definition_version")),
            "业务含义": display(d.get("business_meaning")), "适用范围": display(d.get("scope") or d.get("table_name")),
            "表达式": display(d.get("expression")), "聚合方式": aggregation_names.get(d.get("aggregation"), display(d.get("aggregation"))),
            "分子 / 分母": display(d.get("numerator")) + " / " + display(d.get("denominator")),
            "去重对象": display(d.get("deduplication_key")), "统计单位": "不适用（描述性聚合）" if d.get("statistical_unit") == "not_applicable" else display(d.get("statistical_unit")),
            "分析粒度": display(d.get("grain")), "日期字段 / 时区": display(d.get("date_column")) + " / " + display(d.get("timezone")),
            "时间范围 / 基准": display(d.get("time_range")) + " / " + display(d.get("comparison_baseline")),
            "有效样本": display(d.get("valid_sample")), "空值 / 零分母": display(d.get("null_policy")) + " / " + display(d.get("zero_denominator_policy")),
            "来源与状态": source_names.get(d.get("source"), display(d.get("source"))) + "；" + status_names.get(d.get("definition_status"), "待确认"),
            "数据质量说明": display(d.get("data_quality_notes")), "语义指纹": display(d.get("semantic_fingerprint") or d.get("computation_fingerprint"))})
    if len(definitions)>32: output.append({"说明": "口径卡仅展示前32项；完整定义见运行清单。"})
    return output
