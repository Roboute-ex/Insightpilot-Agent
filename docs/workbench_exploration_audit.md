# 数据探索核心审计与最小接入方案

读取日期：2026-09-29；范围：当前 0.1.0 工作项目。本文为修改前实际代码审计，不以旧验收成绩作本轮结果。

## 已有实现及复用点

- `insightpilot/planning/planner.py:prepare_analysis_request` 与 `analysis_advisor.py` 已统一 UI/CLI/workflow 的元数据预检。只读取 PreparedDataset 的 readiness_summary，不扫描数据。
- `insightpilot/ingestion/mapping.py:ColumnMapping` 已表达目标表、指标、维度、日期、聚合方式、独立单位、去重键和单位。显式空 outcome 的语义必须保留。
- `insightpilot/metrics/definitions.py:column_metric_card` 从已有 MetricDefinition 构建口径卡；`metric_components` 支持分子/分母映射；不能再建另一指标目录。
- `insightpilot/playbooks/sql_templates.py:metric_aggregate_sql` 对已知比率采用分子总量/分母总量，对 active_users 使用 user_id 去重。现有维度模板带 Top N LIMIT，不能作为完整透视中间结果直接复用。
- `insightpilot/tools/duckdb_engine.py:AnalyticsEngine.run_parameterized_sql` 统一 AST、表列白名单、标量绑定、超时、10 万行输出限制；连接禁外部访问及磁盘溢写。新探索查询继续经过此接口，超限拒绝而非截断。
- `execute_playbook` → `PlaybookExecutionResult` → `_generic_package` → `AnalysisResultPackage` 已提供查询记录、实际表、ChartSpec、质量与数值证据、六类导出；不另建结果协议。
- `app/background_tasks.py:request_work` / `performance_tasks.py` 已约束会话任务和取消，探索仍以普通分析请求提交；无需另一工作线程框架。
- `visualization/factory.py` 支持 bar/line/histogram/box/heatmap；图型切换应仅修改 ChartSpec。箱线需要实际分位数适配，不能将采样结果冒充全量统计。

## 建议最小契约

现有 `data_profile` 处理单字段分布；现有 `dimension_contribution` 处理分组/二维透视。为两者增加受控 `playbook_parameters.exploration_request` 适配，不新增第 11 剧本。请求仅允许固定 kind/字段/行列维度/有限过滤/日期粒度/显示预算；不允许 SQL、自由表达式或 Python。

请求参数仍参与原有请求指纹、历史冻结、预检、审批和后台任务身份。执行后返回原 PlaybookExecutionResult，结果表保存完整受控聚合、独立计算的行/列/总体合计、必要的显示视图与口径元数据。运行结果进入原报告绑定链。

## 数值与安全门禁

- mean 用全范围 SUM/COUNT 或原范围 AVG；比率用各范围分子/分母汇总；去重人数在各合计范围重新 COUNT DISTINCT，不加格子。
- 只显示观测单元格，未观测组合在展示时明确缺失；缺失维度使用独立真实空值键，不与字符串“缺失”合并。
- Top N 对完整聚合排序后显示。Others 是余集，需从原始范围重聚合，不能把显示值 Others 当真实筛选。
- 高基数限制是展示预算，查询仍计算全量；结果超现有 10 万行上限明确拒绝。
- 字段/过滤列来自当前 schema 白名单，值只作绑定参数。无效请求在构造 engine 前拒绝；客户端选择不得带任意表达式。
- 所有统计标为描述性；预检通过不代表独立性、因果或显著性前提成立。

以上最小契约经确认后已在原分析链实现。实现与手算验收见 `docs/data_exploration.md`；本审计中的“已有实现”仍指修改前状态，不作为本轮通过成绩。
