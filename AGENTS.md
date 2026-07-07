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

## 版本语义规则

- 当前 `0.1.0` 表示 consolidated v0.1：基础分析能力合并版。
- v0.1 合并原 v0.1 到 v0.4 的 synthetic data、指标、planner、DuckDB、profiling、异常检测、归因、实验分析、基础报告、Streamlit basic demo 和 pytest coverage。
- 当前 workflow、trace、reviewer 可视为 v0.2 preview 能力，后续 v0.2 聚焦稳定与打磨这些模块。
- 不要把路线图写成发布宣传，保持工程记录和学习实践口吻。

## Analysis Goal Mode 维护要求

- goal_mode 定义集中维护在 `insightpilot/planning/goal_modes.py`。
- 新增模式时同步更新 display name、intent mapping、planner tests、workflow routing、report 和 UI/CLI。
- `auto` 模式必须继续使用 deterministic keyword rules。
- 用户手动选择的 goal_mode 优先于关键词识别。
- 无效 goal_mode 必须回退到 `auto`，不能让程序崩溃。

## 可选依赖 Fallback

- LangGraph 只能作为 optional dependency。
- 缺少 LangGraph 时项目必须继续使用 rule-based workflow。
- optional LangGraph 不得成为必需依赖。
- statsmodels、scipy 或 scikit-learn 相关能力应保持合理 fallback 或清晰错误边界。

## 文档风格

- 中文为主，表达面向学习研究和工程化实践。
- 不写具体组织或品牌名称。
- 不写与真实数据接入相冲突的示例。
- 所有限制说明要明确 synthetic data、相关性和不确定性边界。

## 后续版本建议

- v0.1：基础分析能力合并版。
- v0.1.1：Analysis Goal Mode 与交互补丁。
- v0.2：workflow、trace、reviewer 与 optional LangGraph 的持续打磨。
