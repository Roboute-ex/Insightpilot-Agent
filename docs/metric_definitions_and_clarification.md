# 指标口径与分析前澄清

本轮在现有 `MetricDefinition`、`SemanticMetric`、`ColumnMapping` 和规则 Planner 上增量扩充；软件版本仍为 0.1.0。口径卡是现有指标定义在实际输入表、聚合方法和实验单位上的适配结果，不是第二套指标目录。设计借鉴和固定来源由 `upstream_references.md` 记录，相关代码为本地独立实现。

## 公共入口

`insightpilot.planning.prepare_analysis_request(question, *, table_metadata, goal_mode="auto", playbook_id=None, column_mapping=None, playbook_parameters=None, metric_request=None, semantic_model_id="commerce_demo", clarification_answers=None)` 只读取已摄入的列名、schema 建议和来源元数据，不接收 DataFrame，不执行 SQL、画像、精确数据指纹或统计计算。返回：

- `planning_status`：`ready`、`needs_clarification`、`unsupported`、`invalid_input`。
- `clarification`：`items`、`unresolved_count`、`display_limit=3`、`errors` 和 `unsupported_reasons`。每个 item 有 `role`、中文 `question`、`candidates`、`reason` 和 `required`；不是统计置信度。
- `metric_definitions`：口径卡列表。
- `semantic_fingerprint` 与 `presentation_fingerprint`：当前已解析口径的计算和展示指纹。
- `normalized_request`：可用于现有工作流的规范化请求字段。

`run_agent_analysis` 接收同名 `clarification_answers` 参数，并在结果顶层输出上述五个状态/口径字段。工作流结果和 Manifest 1.1 保存同一份口径，导出不读取正在编辑的界面配置。Manifest 1.0 仍可读取；软件版本与 Manifest schema 版本不同。

`clarification_answers` 仅由明确确认动作提供。支持 `metric`（推荐使用 `表名:指标列`，也接受 `metric_id`）、`table_name`、`date_column`、`date_range`（两个 ISO 日期，含边界）、`group_column`、`control_value`、`treatment_value`、`statistical_unit`、`aggregation`、`goal_mode`、`retention_definition`。自由文本留存定义不会自动变成可执行公式。默认控件值不能伪装成用户确认。自动映射携带 `source="automatic_suggestion"`；显式映射为 `source="user_selected"`，已有 API 的显式字段映射保持兼容。

`needs_clarification` 对应原 `NEEDS_INPUT`；不可用能力为 `UNSUPPORTED`，无效输入为 `INVALID_INPUT`。这些状态在 SQL/统计执行前停止，不产生数字结论。原 `PREVIEW` 仍不执行 SQL；预览本身缺少必需口径时先返回澄清，而不是生成默认指标方案。

## 口径卡及指纹

每张卡至少包含 `metric_id`、中文标题、同义词、场景/模型、`definition_version`、业务含义、输入表、注册表达式或分子/分母、`aggregation`、`unit`、`format`、`grain`、`statistical_unit`、`date_column`、`timezone`、`valid_sample`、`deduplication_key`、`null_policy`、`zero_denominator_policy`、`additivity`、允许维度和时间粒度、来源及定义状态，并带窗口、基准与已有质量说明。

表达式是已有实现的描述，不作为 SQL 或 Python 执行。连续实验完播率采用用户级结果均值，不改成把播放次数当独立样本的二项检验。不同输入中的 `conversion_rate` 分别展示 `orders/visitors` 或 `converted/sessions`；观看时长按实际可用的播放数或会话数计算。交易 visitors 和历史 *_users 漏斗字段是转化旅程计数，不伪称全站去重用户。支付明细去重用户单独注明仅包含支付行为。

状态 `builtin_verified` 只来自实际内置生成器的来源信号与注册指标定义；单传 `data_source_type="synthetic"` 不足以确认口径。该状态说明内置定义来源，不证明所有数据、统计前提或因果关系正确。显式澄清选择为本请求 `user_confirmed`；未确认的自定义含义保持 `draft`。导入配置不能由自报的状态获得全局权限。

`computation_payload` 只在已知定义记录中移除纯展示字段，保留 registry 中名为 title/color 等的真实指标 ID。中文标题、颜色、显示格式不改变计算指纹；单位、计算引用、去重、统计单位、版本、条件和窗口等变化会改变它。语义模型现在显式声明单位，显示格式不再隐式决定计量单位。Catalog 的 `fingerprint()` 是计算指纹，`presentation_fingerprint()` 是完整展示指纹。语义编译与跨事实计划使用计算指纹；SQL 策略版本同时进入 plan identity、绑定指纹和执行前校验。原精确数据指纹、连接基数、审批约束不变。

## 必需澄清与能力边界

含糊的转化率列出实际可用环节；收入区分现存的支付/毛收入、净收入和确认收入列。没有已注册的净收入表达式和没有相应输入列时明确拒绝，不自动减去某个疑似退款列。人数选择明确的实体 ID 与 `count_distinct`，不把行数、会话数或分组 UV 求和称为人数。

实验必须有指标、分组、对照值、实验值和统计单位。`statistical_unit="row"` 是显式独立行声明，不等于系统已验证随机化。自定义 ID 名可以直接传入；重复连续观测沿用原有按独立单位取均值处理。跨组重复单位仍拒绝。已有内置实验携带已验证的 user_id 和 control/treatment 定义，不重复询问。

本周等相对窗口在缺少明确范围时要求日期，不把电脑时间当数据日期。明确 `date_range` 由实际执行路径应用，起止日均包含。已有剧本按其既有日期参数执行。任意自然语言条件、自由文本公式、未注册留存定义或跨事实时间关联不由规则推测；支持范围不足时返回澄清或 unsupported。已有 cohort_retention 和已映射的观测留存指标仍可使用，但不能声称自动实现了任意 D1/D7 或活跃回访定义。

## 已修复的旧问题与行为变化

1. `_column_mapping_from_state` 原来漏传 `aggregation`、`covariates` 和原始请求，使显式 mean 在通用趋势中变成 sum。现完整转交 ColumnMapping；小表 `[10,30]`、`[20,60]` 的两日结果为 `[20,40]`，不再是错误的 `[40,80]`。
2. 自定义维度拆解原来忽略显式聚合，并直接平均比率。现显式映射路径使用相同聚合和分子分母；手算基准 `10/92`、当前 `5/20`，不变成分组比率均值。历史未提供映射的路径保留原行为。
3. 无效映射原来会移除字段后生成无关概览。现保存原始请求并返回 INVALID_INPUT；低层 normalize 的兼容警告 API 保留。
4. 缺统计单位/方向的实验现在要求澄清。原独立行 fixture 测试补上显式 row 与方向，保留数值意图；没有删除失败测试或把旧统计值当新真值。
5. 原单指标语义预览测试补上明确 MetricRequest，继续断言查询次数为零；新增策略字段纳入英文 JSON schema 的兼容断言。

这些自定义旧错误口径的修正可能改变旧输出，不能概括为所有历史请求都数值零差异。

## 本轮实际验证

- `reports/upstream/p0a-tests.xml`：口径/澄清、原映射与自定义路由、十剧本相关编译/多表、性能核心、英文 schema 和 fallback 的定向结果。精确通过数量见本轮 XML，不沿用旧验收数字。
- `reports/upstream/metric-39-examples.json` 保留首次 37/39 完成和两个新参数未注册失败；修复后 `metric-39-examples-fixed.json` 中 39/39 为 COMPLETED。
- `reports/upstream/p0a-playbook-comparison.json` 保留未确认旧实验配置所触发的 NEEDS_INPUT。
- `reports/upstream/p0a-playbook-confirmed-comparison.json`：以本轮精确修改前源码 `reports/upstream/source-before/insightpilot-agent`，两个独立子进程执行十剧本。明确确认现有独立行 fixture 后，55 张表、664 行、55 条结构化证据的 `numerical_evidence_difference_count=0`。完整表包含列、dtype、索引、有序行，不只比较摘要。
- 上述完整严格 payload 仍有 33 处新增映射字段、参数确认、SQL 策略绑定/计划 ID 等差异；`passed=false` 与退出码 1 如实保留，`numerical_evidence_compatible=true` 是单独的统计/证据比较结果。没有把这些协议变化当作随机元数据删除。
- 新测试独立小表验证均值、加权比率、重复用户去重、实验独立单位、日期窗口实际过滤、无效输入与澄清的零查询、标题和单位指纹边界。十剧本兼容性检查不替代独立统计真值评估。

复测示例（项目根目录 PowerShell）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_upstream_definitions_clarification.py -q
.\.venv\Scripts\python.exe -B scripts/compare_playbook_snapshots.py --before reports/upstream/source-before/insightpilot-agent --confirm-experiment-fixture --output reports/upstream/playbook-new-run.json
.\.venv-langgraph\Scripts\python.exe -B scripts/check_langgraph.py --output reports/upstream/langgraph-new-run.json
```

比较脚本不覆盖既有报告；请为新运行使用新文件名。完整验收、真实浏览器、导出视觉、性能和快照恢复由本轮统一验收另行记录，不以本节定向测试代替。


## 最后界面确认审查

实际 AppTest 复现了自定义实验参数控件的方向预选风险：只确认字段映射并填写 user_id，未操作对照/实验组值，点击开始仍调用了分析一次。首次失败保留在 `reports/upstream/experiment-confirmation-before.xml`，没有删除或改成通过记录。

`app/components/semantic_panel.py` 现以数据集身份、revision、表及分组字段隔离方向控件。自定义方向默认空选择/空文本，未选不会进入参数；变化时清除旧方向及统计单位。可信内置生成器定义可保留 control/treatment；同数据、同分组、同剧本的当前会话受控历史节点可恢复已经确认的方向，不读取外部配置的自报确认状态。缓存中的分组候选保留原标量类型。

新增真实 AppTest 验证未确认时0次分析、明确方向后手算差2且每组4个独立单位、切换分组/数据revision清除选择、同来源历史恢复不执行，以及内置实验无需重复询问。相关界面回归36项通过，另内置边界1项通过，见 `experiment-confirmation-regression.xml` 和 `experiment-confirmation-builtin.xml`。这次只增补控件确认边界，统计引擎和样本方法没有改变。

同时修复了本轮 preflight 的日期格式兼容问题：既有日期控件产生 `{start,end}`，澄清入口产生二元素列表；两者现在先归一化为同一个含边界窗口，使用相同计算指纹并实际执行过滤。对应小表单日加权比率为0.25，不只是修改显示。
