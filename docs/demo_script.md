# Demo 演示脚本

## Demo 1：交易转化异常分析

推荐 goal_mode：`metric_diagnosis`

业务问题：

```text
为什么昨天某城市订单量下降？
```

预期输出：

- 订单量相对前 7 日均值的变化。
- 异常严重度。
- city、channel、user_segment、device、merchant_type 的贡献度排序。
- 针对曝光、点击率、转化率和支付成功率的下一步建议。

解释重点：

- synthetic data 中目标日期的 South City 被注入订单下降信号。
- 归因排序用于定位优先排查方向，不代表最终因果结论。

注意事项：

- 结果只用于 synthetic demo。
- 需要继续拆解上游流量和支付链路指标。

## Demo 2：内容消费与实验分析

推荐 goal_mode：`experiment_analysis` 或 `content_performance`

业务问题：

```text
新策略是否提升了内容完播率？
```

预期输出：

- 对照组和实验组 completion_rate。
- absolute_lift、relative_lift、p-value、confidence interval。
- 用户分层效果。
- 是否建议继续观察。

解释重点：

- experiments 表中 treatment 组被注入完播率提升信号。
- p-value < 0.05 只能说明 synthetic 样本中存在统计显著差异。

注意事项：

- 需要关注样本量和分层稳定性。
- 不能把轻量调整分析直接当成严格因果结论。

## Demo 3：直播体验质量分析

推荐 goal_mode：`live_quality`

业务问题：

```text
请定位直播体验异常的主要维度。
```

预期输出：

- stutter_rate、watch_time、interaction_rate 的变化。
- device、network_type、city、hour_bucket 的贡献度排序。
- 风险提示和优化建议。

解释重点：

- synthetic data 中目标日期的 Tablet 或 Cellular 流量被注入卡顿率上升信号。
- 体验质量需要同时看卡顿、停留和互动。

注意事项：

- 卡顿率上升是风险信号，需要结合日志继续复核。
- 相关性不能直接解释为因果关系。
