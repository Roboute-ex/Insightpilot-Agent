# InsightPilot Agent 项目路线图

当前代码版本为 `0.1.0`，语义上表示 consolidated v0.1：基础分析能力合并版。项目已经一次性实现了部分 v0.2 preview 能力，因此后续路线以工程语义整理和持续打磨为主，不强行拆分已有代码。

## v0.1：基础分析能力合并版

范围：

- synthetic demo data
- metric dictionary
- metric resolver
- deterministic analysis planner
- DuckDB analysis tools
- profiling tools
- anomaly detection
- dimension attribution
- A/B experiment analysis
- basic markdown report
- Streamlit basic demo
- pytest coverage

说明：

- v0.1 合并了原 v0.1 到 v0.4 的基础分析能力。
- 所有 demo 数据仍为 synthetic data。
- 不接入真实外部数据、不接入在线 LLM、不要求 API key。

## v0.1.1：Analysis Goal Mode

范围：

- 增加 `goal_mode` 集中定义。
- Planner 支持 `auto` 自动识别和用户手动指定目标模式。
- Workflow、Trace、Reviewer、Markdown Report、Streamlit 和 CLI 透传 goal_mode。
- 保持旧的 CLI 和 workflow 调用兼容。

说明：

- 该能力属于基础交互补丁，服务于 v0.1 的可演示性。
- 当 goal_mode 为 `auto` 时，仍使用 deterministic keyword rules。
- 当用户选择具体 goal_mode 时，用户选择优先于关键词识别。

## v0.2：workflow / trace / reviewer / optional LangGraph

范围：

- workflow orchestration
- analysis trace
- reviewer
- optional LangGraph integration
- fallback workflow when LangGraph is not installed

说明：

- 当前代码已经包含 workflow、trace 和 reviewer 的 preview 能力。
- v0.2 后续重点是稳定接口、完善 reviewer 检查项、增强 trace 可解释性。
- LangGraph 只能作为 optional dependency，缺少时必须保留 rule-based fallback。

## 后续维护方向

- 增强 goal_mode 与 intent 映射的测试覆盖。
- 增加更多 synthetic 场景和可解释异常。
- 补充 report export 格式与 Streamlit 图表筛选。
- 继续保持 deterministic、synthetic-data-only 和 no API key 的项目边界。
