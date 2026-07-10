# Analysis Playbooks

v0.5 将自定义数据工作流组织为可复用的 Analysis Playbook。Playbook 是确定性配置，不调用在线模型，也不接收可执行 SQL 片段。

## 核心概念

每个 playbook 声明 `playbook_id`、中文名称、支持的 goal mode、Column Mapping 要求、参数、执行器、图表类型和输出章节。`PlaybookRegistry` 负责注册、筛选和确定性推荐。

不传 `playbook_id` 时保留 v0.4 自动工作流。选择 `auto` 时，系统根据 goal mode、mapping 完整度和字段角色排序推荐结果。

## 七个内置 Playbook

- `data_profile`：表规模、dtype、缺失率、唯一值、重复行和数值分布。
- `metric_trend`：时间聚合、变化率、滚动均值和异常信号。
- `period_comparison`：当前周期与对比周期的绝对和相对变化。
- `dimension_contribution`：维度贡献值、占比、排名和 Others。
- `experiment_comparison`：组均值或比例比较、lift、p-value 与置信区间。
- `causal_exploration`：naive difference、回归调整和适用边界。
- `periodic_summary`：组合 profile、trend 和 top dimensions。

## Requirements 与 Mapping

ColumnMapping 是 playbook 的输入契约。字段角色包括 table、date、metric、dimension、group、treatment 和 outcome。手动 mapping 优先于自动建议。

缺少必需字段时 executor 返回结构化 `WARN` 或 `FAIL`，并把建议写入 warnings、trace、reviewer 和 report，不执行查询。

`periodic_summary` 只强制要求 table。存在 date + metric 时运行完整摘要；缺少 date 时降级为 profile，并写入 caveat。

## 参数说明

参数类型支持 string、integer、float、boolean、date、column、metric columns、dimension columns、date range 和 choice。

`top_n` 限制在 1 到 100，`rolling_window` 限制在 1 到 90，`confidence_level` 限制在 0.8 到 0.99。日期范围开始时间不能晚于结束时间。

## SQL Safety

表名和列名必须来自当前 TableRegistry 与 ColumnMapping allowlist。所有 identifier 先校验再引用，日期、阈值、Top N 和分组值使用绑定参数。

SQL template 只生成单条 SELECT / WITH。最终执行前仍调用只读安全检查，禁止 DDL、DML、多语句和用户编辑 preview 后执行。

## Fallback 规则

可安全适配时优先运行 DuckDB 参数化 SQL。统计检验和轻量调整复用现有 pandas 分析函数。SQL 执行失败会写入 structured warning，不会切换到用户提供的任意 SQL。
