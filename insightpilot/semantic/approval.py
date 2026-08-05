"""Plan review decisions tied to stable query plan identifiers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from insightpilot.semantic.query import QueryPlan


PLAN_DECISIONS = {"pending", "approved", "rejected"}


@dataclass(frozen=True)
class PlanReview:
    plan_id: str
    decision: str
    reason: str = ""
    approved_for_read_only_execution: bool = False

    def __post_init__(self) -> None:
        if self.decision not in PLAN_DECISIONS:
            raise ValueError(f"不支持的审批决定：{self.decision}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def review_query_plan(
    plan: QueryPlan,
    decision: str | None = None,
    approved_plan_id: str | None = None,
    reason: str = "",
) -> PlanReview:
    """Return a review that can never approve a stale plan id."""

    if not plan.executable:
        return PlanReview(plan.plan_id, "rejected", "查询计划包含禁止执行的关系或校验错误。", False)
    normalized = decision or ("pending" if plan.requires_approval else "approved")
    if normalized == "approved" and plan.requires_approval and approved_plan_id != plan.plan_id:
        return PlanReview(plan.plan_id, "pending", "当前计划编号尚未获得匹配审批。", False)
    if normalized == "rejected":
        return PlanReview(plan.plan_id, "rejected", reason or "用户已拒绝当前分析方案。", False)
    if normalized == "approved":
        return PlanReview(plan.plan_id, "approved", reason or "已批准执行当前只读查询计划。", True)
    return PlanReview(plan.plan_id, "pending", reason or "当前计划等待审批。", False)
