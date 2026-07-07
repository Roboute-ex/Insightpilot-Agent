# Metric Dictionary

| metric_name | display_name | formula | explanation |
| --- | --- | --- | --- |
| active_users | 活跃用户数 | count_distinct(user_id) | 衡量整体参与规模。 |
| impressions | 曝光量 | sum(impressions) | 衡量上游流量供给。 |
| clicks | 点击量 | sum(clicks) | 衡量用户初步兴趣。 |
| ctr | 点击率 | sum(clicks) / sum(impressions) | 衡量曝光到点击的吸引力。 |
| orders | 订单量 | sum(orders) | 衡量交易转化规模。 |
| cvr | 转化率 | sum(orders) / sum(clicks) | 衡量点击后的转化效率。 |
| payment_success_rate | 支付成功率 | successful_payments / payment_attempts | 衡量支付链路稳定性。 |
| revenue | 收入 | sum(revenue) | 衡量交易价值。 |
| completion_rate | 完播率 | sum(completed) / count(events) | 衡量内容消费质量。 |
| retention_rate | 留存率 | retained_users / eligible_users | 衡量持续参与情况。 |
| stutter_rate | 卡顿率 | avg(stutter_rate) | 衡量体验流畅性。 |
| watch_time | 观看时长 | avg(watch_time) | 衡量停留和消费深度。 |
| interaction_rate | 互动率 | avg(interaction_rate) | 衡量参与活跃度。 |

所有指标口径服务于 synthetic data demo，不代表真实业务口径。新增指标时应补充 definition、formula、business_meaning 和 required_columns。
