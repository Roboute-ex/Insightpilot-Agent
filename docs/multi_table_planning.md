# 多表规划与审批

## RelationshipGraph

RelationshipGraph 根据语义模型构建无向遍历视图，并以确定性顺序查找最短关系路径。

## JoinPlanner

JoinPlanner 生成稳定 JoinPlan，记录基础实体、目标实体、连接字段、基数、输出粒度、风险、警告和错误。

## 风险规则

- many-to-one 与 one-to-one 通常为安全。
- one-to-many 可能产生 fanout，要求人工审批。
- 多条一对多路径会提高粒度冲突风险。
- many-to-many 默认禁止执行。

## Plan Preview

`plan_only` 只生成 QueryPlan 和 PlanReview，不执行 SQL。专业模式可查看只读 SQL 预览，但不能编辑后直接执行。

## 审批绑定

高风险计划必须提供与当前 QueryPlan 完全一致的 `approved_plan_id`。计划内容变化后 ID 改变，旧批准自动失效。

## 模拟多表

七张表为 customers、sessions、orders、order_items、products、channels 和 calendar。所有引用关系由固定 seed 生成并在测试中核对。

## 多表剧本

当前整合版 提供语义指标查询、漏斗转化分析和队列留存分析，结果与限制均使用中文展示。
