# 本地评估套件

## 目标

Evaluation Harness 使用固定模拟数据检查计划有效性、SQL 安全、数值正确性和确定性，不访问在线服务。

## Core

Core 套件验证语义计划结构、只读 SQL 和聚合数值。总体得分门槛为 `0.95`，数值正确性门槛为 `0.98`。

## Safety

Safety 套件检查参数化计划、plan_only 和写操作阻断，SQL Safety 得分必须为 `1.0`。

## Determinism

Determinism 套件对同一输入重复编译，忽略运行时间等波动字段后结果必须一致，得分必须为 `1.0`。

## Scorer

可用 scorer 包括 PlanValidity、JoinPath、SQLSafety、NumericalCorrectness、Determinism、TraceCompleteness、LineageCompleteness、ReviewerConsistency、ExportIntegrity 和 ContractCompliance。

## 运行

```powershell
.\.venv\Scripts\python.exe -m insightpilot.evaluation.cli --suite all
```

Streamlit 评估中心默认展示摘要和失败案例，完整输出只在开发者详情中使用。
