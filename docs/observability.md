# 本地 Observability

## LocalTracer

LocalTracer 在内存中记录 TraceSpan，不配置网络 exporter，不要求密钥。

## Span 字段

每个 span 包含 span_id、parent_span_id、开始时间、结束时间、耗时、状态、脱敏属性和事件。

## 摘要

ObservabilitySummary 记录总耗时、查询次数、最慢步骤、警告数量、错误数量、Join 风险数量、导出大小和 span 数量。

## 脱敏

密码、token、secret、credential 和 API key 属性会被掩码；连接字符串中的密码和绝对路径也会清理。

## UI 分层

简洁和专业模式只显示中文运行摘要。原始 spans、属性和事件仅在开发者模式展示。

## 可选 OpenTelemetry

`insightpilot.observability.otel` 只检测本地 API 并提供 allowlisted 属性预览。依赖缺失时继续使用 LocalTracer；即使可用，也不自动配置在线导出。

## 当前限制

运行摘要用于本地诊断，不是分布式生产追踪系统，也不保存源数据。
