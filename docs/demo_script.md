# Demo 演示脚本

本演示只使用 synthetic data。所有输出用于学习研究、数据分析自动化和 Agent 工程化实践，不代表真实业务结论。

## v0.2 展示步骤

1. 选择 demo 场景。
2. 选择 Analysis Goal Mode，默认 `auto`。
3. 选择 Workflow Backend，默认 Rule-based。
4. 运行分析。
5. 查看 route_taken，确认 workflow 节点路径。
6. 查看 Reviewer Score、status、issues 和 suggestions。
7. 查看 Trace ID、workflow_backend、caveats 和 errors。
8. 查看 Markdown Report。

## Demo 1：交易转化异常分析

推荐 goal_mode：`metric_diagnosis`

问题：

```text
为什么昨天某城市订单量下降？
```

推荐命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis
```

预期输出：

- 订单量相对前 7 日均值的变化。
- 异常严重度。
- city、channel、user_segment、device、merchant_type 的贡献度排序。
- route_taken 包含 `route_metric_diagnosis`、`run_anomaly`、`run_attribution`。
- Reviewer Score 为 PASS 区间。

解释重点：

- synthetic data 中目标日期的 South City 被注入订单下降信号。
- 归因排序用于定位优先排查方向，不代表最终因果结论。

## Demo 2：内容消费与实验分析

推荐 goal_mode：`experiment_analysis` 或 `content_performance`

问题：

```text
新策略是否提升了内容完播率？
```

推荐命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario content --goal-mode experiment_analysis
```

预期输出：

- 对照组和实验组 completion_rate。
- absolute_lift、relative_lift、p_value、confidence interval。
- sample_size 与分层效果。
- route_taken 包含 `route_experiment_analysis` 和 `run_experiment`。
- Reviewer 结果包含实验检查项。

解释重点：

- experiments 表中 treatment 组被注入完播率提升信号。
- p_value < 0.05 只说明 synthetic 样本中存在统计显著差异。
- 仍需关注样本量和分层稳定性。

## Demo 3：体验质量分析

推荐 goal_mode：`live_quality`

问题：

```text
请定位直播体验异常的主要维度。
```

推荐命令：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario live --goal-mode live_quality
```

预期输出：

- stutter_rate、watch_time、interaction_rate 的变化。
- device、network_type、city、hour_bucket 的贡献度排序。
- route_taken 包含 `route_live_quality`、`run_live_quality`、`run_attribution`。
- 风险提示、限制说明和下一步建议。

解释重点：

- synthetic data 中目标日期的 Tablet 或 Cellular 流量被注入卡顿率上升信号。
- 体验质量需要同时看卡顿、停留和互动。
- 相关性不能直接解释为因果关系。

## Optional LangGraph fallback 展示

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis --use-langgraph
```

预期行为：

- 如果 LangGraph 可用，workflow_backend 显示 `langgraph`。
- 如果 LangGraph 未安装或 API 不兼容，workflow_backend 显示 `langgraph_unavailable_fallback`。
- 无论是否安装 LangGraph，命令不应要求 API key，也不应接入在线 LLM。
