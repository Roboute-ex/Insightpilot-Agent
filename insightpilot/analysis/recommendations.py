"""Evidence-bound deterministic recommendation rules."""

from __future__ import annotations

from insightpilot.analysis.results import (
    ActionRecommendation,
    AnalysisEvidence,
    DimensionContributionResult,
    FunnelStageResult,
    MetricComparisonResult,
)


def build_recommendations(
    comparisons: list[MetricComparisonResult],
    funnel: list[FunnelStageResult],
    contributions: list[DimensionContributionResult],
    evidence: list[AnalysisEvidence],
) -> list[ActionRecommendation]:
    evidence_ids = {item.evidence_id for item in evidence}
    by_metric = {
        item.metric_id: item
        for item in comparisons
        if item.baseline_period == "前 7 日均值"
    }
    recommendations: list[ActionRecommendation] = []

    payment = by_metric.get("payment_success_rate")
    payment_segments = [
        item for item in contributions
        if item.metric_id == "payment_success_rate" and item.contribution_value < 0
        and ("app_version" in item.dimension or item.dimension == "device")
    ]
    payment_evidence = [item.evidence_id for item in evidence if item.metric == "payment_success_rate"][:3]
    if payment and payment.relative_change <= -0.02 and payment_segments and payment_evidence:
        recommendations.append(ActionRecommendation(
            priority="高",
            action="优先复核负向设备与版本的支付组件、接口失败分布和版本变更记录。",
            reason=f"支付成功率较前 7 日均值下降 {abs(payment.relative_change):.1%}，且版本维度存在集中负向贡献。",
            supporting_evidence_ids=tuple(item for item in payment_evidence if item in evidence_ids),
            suggested_owner="支付链路维护方",
            verification_metric="支付成功率、支付失败类型分布",
            expected_direction="支付成功率回升，集中失败占比下降",
            limitation="当前数据为内置模拟数据，建议仅用于演示排查顺序。",
        ))

    impressions = by_metric.get("impressions")
    paid_search = [
        item for item in contributions
        if item.metric_id == "orders" and item.dimension == "channel" and item.dimension_value == "Paid Search" and item.contribution_value < 0
    ]
    traffic_evidence = [item.evidence_id for item in evidence if item.metric in {"impressions", "orders"} and "Paid Search" in item.claim][:2]
    if impressions and impressions.relative_change < -0.05 and paid_search:
        ids = traffic_evidence or [item.evidence_id for item in evidence if item.metric == "impressions"][:1]
        recommendations.append(ActionRecommendation(
            priority="高",
            action="检查付费搜索流量计划、预算节奏和入口可用性，并与自然流量对照。",
            reason=f"曝光量较前 7 日均值下降 {abs(impressions.relative_change):.1%}，付费搜索同时表现为负向订单贡献。",
            supporting_evidence_ids=tuple(item for item in ids if item in evidence_ids),
            suggested_owner="流量运营维护方",
            verification_metric="曝光量、点击量、到站访问量",
            expected_direction="流量恢复且订单负向贡献收窄",
            limitation="贡献分析反映同步变化，不直接证明单一原因。",
        ))

    city_negative = [item for item in contributions if item.metric_id == "orders" and item.dimension == "city" and item.contribution_value < 0][:3]
    if city_negative:
        names = "、".join(item.dimension_value for item in city_negative)
        ids = [item.evidence_id for item in evidence if item.metric == "orders" and any(name in item.claim for name in [row.dimension_value for row in city_negative])][:3]
        if not ids:
            ids = [
                item.evidence_id for item in evidence
                if item.metric == "orders" and item.result_table == "dimension_contributions"
            ][:2]
        if not ids:
            ids = [item.evidence_id for item in evidence if item.metric == "orders"][:1]
        recommendations.append(ActionRecommendation(
            priority="中",
            action=f"按渠道、设备和用户分层继续复核 {names} 的订单链路。",
            reason="这些城市位于目标日订单负向贡献前列。",
            supporting_evidence_ids=tuple(item for item in ids if item in evidence_ids),
            suggested_owner="区域分析维护方",
            verification_metric="订单量、转化率、支付成功率",
            expected_direction="主要城市负向贡献占比下降",
            limitation="维度贡献会受到样本规模和维度交叉影响。",
        ))

    funnel_negative = sorted((item for item in funnel if item.estimated_order_impact < 0), key=lambda item: item.estimated_order_impact)[:2]
    if funnel_negative:
        names = "、".join(item.stage_name for item in funnel_negative)
        ids = [item.evidence_id for item in evidence if item.result_table == "funnel_decomposition" and any(name in item.claim for name in [row.stage_name for row in funnel_negative])][:2]
        recommendations.append(ActionRecommendation(
            priority="中",
            action=f"优先验证 {names} 环节的输入量和阶段转化率。",
            reason="顺序分解显示这些环节对最终支付成功量缺口的估算影响最大。",
            supporting_evidence_ids=tuple(item for item in ids if item in evidence_ids),
            suggested_owner="转化链路维护方",
            verification_metric="阶段人数、阶段转化率、支付成功量",
            expected_direction="关键阶段影响值向零收敛",
            limitation="顺序分解是近似归因，结果受阶段替换顺序影响。",
        ))

    if not recommendations and evidence:
        recommendations.append(ActionRecommendation(
            priority="低",
            action="复核当前最显著的结构化证据，并扩大日期窗口确认变化是否持续。",
            reason="当前仅识别到描述性变化，尚未触发更具体的规则。",
            supporting_evidence_ids=(evidence[0].evidence_id,),
            suggested_owner="分析维护方",
            verification_metric=evidence[0].metric,
            expected_direction="在更长窗口中确认变化方向",
            limitation="该建议不包含因果判断。",
        ))
    return recommendations
