# InsightPilot Agent 项目路线图

当前代码版本为 `0.2.0`。路线图保持工程记录和学习实践口吻，不写成发布宣传；所有能力继续限定在 synthetic data、deterministic workflow 和 no API key 边界内。

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

- v0.1 合并了基础分析能力。
- 所有 demo 数据均为 synthetic data。
- 不接入真实外部数据、不接入在线 LLM、不要求 API key。

## v0.1.1：Analysis Goal Mode 与交互补丁

范围：

- 增加 `goal_mode` 集中定义。
- Planner 支持 `auto` 自动识别和用户手动指定目标模式。
- Workflow、Trace、Reviewer、Markdown Report、Streamlit 和 CLI 透传 goal_mode。
- 保持旧的 CLI 和 workflow 调用兼容。

说明：

- 当 goal_mode 为 `auto` 时，仍使用 deterministic keyword rules。
- 当用户选择具体 goal_mode 时，用户选择优先于关键词识别。
- 无效 goal_mode 回退到 `auto`。

## v0.2：当前目标

目标名称：Agent Workflow, Trace and Reviewer Hardening

范围：

- `WorkflowState` 作为中心 workflow state。
- `route_taken` 写入 workflow state、trace、report、CLI 和 Streamlit。
- `workflow_backend` 支持 `rule_based`、`langgraph`、`langgraph_unavailable_fallback`。
- rule-based workflow 保持默认 backend。
- optional LangGraph workflow 单独管理，未安装或 API 不兼容时自动 fallback。
- `AnalysisTrace` 增强 trace_id、created_at、workflow_backend、route_taken、caveats 和 errors。
- `ReviewerResult` 增强 status、score、checks、issues 和 suggestions。
- CLI 增加 `--use-langgraph`。
- Streamlit 增加 Workflow Backend selector。
- GitHub Actions CI 使用 Python 3.11 和 pytest。

说明：

- Analysis Goal Mode 在 v0.2 中是可选的 user-facing routing signal。
- `auto` 继续使用 deterministic keyword rules。
- 用户手动选择的 goal_mode 优先于自动识别。
- reviewer score 用于解释 workflow 质量，不代表真实业务质量。
- 所有报告必须明确 synthetic data、相关性和不确定性边界。

## v0.3：Streamlit visualization and report export polish

候选方向：

- 增强图表交互和 artifact 预览。
- 补充 Markdown、JSON 或 PDF 导出整理。
- 改进 Streamlit 页面布局和状态展示。
- 保持 synthetic-data-only 和 deterministic workflow 边界。

## v0.4：metric dictionary expansion and SQL template hardening

候选方向：

- 扩展指标字典、同义词和 goal_mode 映射测试。
- 增强 SQL template 管理和只读安全检查覆盖。
- 增加更多 synthetic 场景和可解释异常。
- 继续避免真实外部数据、在线 LLM 和 API key。
