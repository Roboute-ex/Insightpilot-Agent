# InsightPilot Agent 维护说明

## 项目边界

InsightPilot Agent 是 synthetic-data-only 的分析自动化工作台，用于学习研究、数据分析自动化、业务分析工作流实践和 Agent 工程化实践。默认工作流是 deterministic rule-based planner，不依赖在线 LLM。

## 数据与凭据边界

- 不允许接入真实用户数据或真实外部业务数据。
- 不允许提交 API key、token、cookie、私钥或其他凭据。
- 所有 demo、测试和文档示例必须使用 synthetic data。
- 不要把 synthetic data 结果描述成真实业务结论。

## 测试要求

- 核心函数需要保持 deterministic，随机过程必须使用 seed。
- 修改 synthetic data、planner、workflow、reviewer、report 或 goal_mode 时，需要运行 `pytest`。
- DuckDB 查询层必须保持只读安全检查，禁止写操作 SQL。
- 三个 demo 场景应保持 PASS，且 CLI 旧命令继续可用。

## 版本语义规则

- 当前 `0.2.0` 表示 Agent Workflow, Trace and Reviewer Hardening。
- v0.1 是基础分析能力合并版。
- v0.2 聚焦 WorkflowState、route_taken、AnalysisTrace、ReviewerResult、workflow_backend 和 optional LangGraph fallback。
- 后续路线保持工程记录和学习实践口吻，不写成发布宣传。

## WorkflowState 维护要求

- WorkflowState 定义集中维护在 `insightpilot/agents/state.py`。
- workflow 内部节点应通过 WorkflowState 传递 user_question、goal_mode、intent、selected_metrics、analysis_plan、route_taken、caveats、errors 和 reviewer 摘要。
- `route_taken` 必须记录实际节点路径，例如 `resolve_metrics`、`create_plan`、`route_metric_diagnosis`、`run_anomaly`、`review`、`generate_report`。
- `to_dict()` 不得直接序列化完整 pandas DataFrame，只能输出安全摘要。
- 新增 workflow 字段时，同步更新 trace、report、CLI、Streamlit 和 tests。

## Analysis Goal Mode 维护要求

- goal_mode 定义集中维护在 `insightpilot/planning/goal_modes.py`。
- 新增模式时同步更新 display name、intent mapping、planner tests、workflow routing、report 和 UI/CLI。
- `auto` 模式必须继续使用 deterministic keyword rules。
- 用户手动选择的 goal_mode 优先于关键词识别。
- 无效 goal_mode 必须回退到 `auto`，不能让程序崩溃。
- goal_mode 是 workflow routing signal、trace explanation field 和 reviewer check context，不要扩展成复杂目标配置系统。

## 可选依赖 Fallback

- LangGraph 只能作为 optional dependency。
- 缺少 LangGraph 时项目必须继续使用 rule-based workflow。
- optional LangGraph 不得成为必需依赖。
- `requirements.txt` 不要加入 LangGraph；`requirements-langgraph.txt` 单独管理。
- `workflow_backend` 只使用 `rule_based`、`langgraph`、`langgraph_unavailable_fallback`。
- statsmodels、scipy 或 scikit-learn 相关能力应保持合理 fallback 或清晰错误边界。

## Reviewer Score 维护要求

- ReviewerResult 定义维护在 `insightpilot/agents/reviewer.py`。
- ReviewerResult 包含 `status`、`score`、`checks`、`issues`、`suggestions`。
- PASS 分数应为 80 及以上；WARN 为 50 到 79；FAIL 低于 50。
- 正常 demo 不应被误判为 FAIL。
- experiment_analysis 应检查 p_value 和 sample_size。
- causal_exploration 应检查因果解释边界。
- errors 非空时至少 WARN，严重缺失时 FAIL。
- reviewer 输出必须写入 trace 和 report。

## GitHub Actions CI 维护要求

- CI 文件维护在 `.github/workflows/ci.yml`。
- push 和 pull_request 时运行。
- 使用 Python 3.11。
- 安装 `requirements.txt` 并运行 `python -m pytest`。
- CI 不安装 `requirements-langgraph.txt`，用于验证 optional LangGraph fallback。

## 文档风格

- 中文为主，表达面向学习研究和工程化实践。
- 不写具体组织或品牌名称。
- 不写与真实数据接入相冲突的示例。
- 所有限制说明要明确 synthetic data、相关性和不确定性边界。

## 后续版本建议

- v0.3：Streamlit visualization and report export polish。
- v0.4：metric dictionary expansion and SQL template hardening。
