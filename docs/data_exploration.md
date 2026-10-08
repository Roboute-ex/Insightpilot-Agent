# 单表数据探索

版本保持 0.1.0。探索复用现有剧本、字段映射、统一预检、安全 SQL、工作流、结果包和报告，不另设任务系统或指标目录。原十个剧本不增不减。

## 入口与提交

在主导航“数据探索”查看摄入阶段已准备的字段信息；字段分布、分组图与交叉表需要显式生成请求。字段选择、维度、时间范围、过滤和粒度组成分析草稿。只有提交“生成探索结果”才计算。已有运行切换图型仅构造 ChartSpec 和对应图表，不重新执行查询。已执行范围与未提交草稿分别展示。

单字段分布由 `data_profile` 承载；分组汇总与二维交叉表由 `dimension_contribution` 承载。它们是原剧本的有限请求适配，不能据此声称新增预测、显著性或因果识别能力。

## 请求与口径

原 `ColumnMapping` 仍指定目标表、指标、维度、日期、聚合、单位和去重键。新增可选 `numerator_column` / `denominator_column`，仅在明确选择 `ratio_of_sums` 时用于自定义加权比率。指标口径卡由原 `column_metric_card` 生成，不接收用户 SQL 或自由公式。

`playbook_parameters.exploration_request` 支持：

- `kind`：`distribution` / `grouped` / `pivot`。
- `field`：分布字段；`distribution_type`：`auto` / `numeric` / `categorical` / `date`。
- `row_dimension`、`column_dimension`：单表一行维度、一列维度。
- `filters`：至多八项 `{column, operator, value}`；沿用有限 `eq/in/gt/gte/lt/lte/between`。真实空值用 `eq: null`，编译为 `IS NULL`；值全部绑定，不拼接。
- `date_from/date_to`：含端点的 ISO 日期范围；需要已明确日期字段。`time_grain` 仅在日期为行维度时支持 `day/week/month`。
- `top_n`、`include_others`、`max_display_rows`、`max_display_columns`：显示规则，上限分别为 100、布尔、50、30。

未知参数、越权字段、自由表达式、无效过滤、缺失指标/维度、非法日期范围均在原预检链拒绝；不会先执行 SQL 再猜测口径。日期字符串在已有元数据确认后可自动作为日期分布；数值日期不会猜测 epoch 单位。

## 全量计算与显示边界

统计对本次完整筛选范围计算。显示预算不会减少统计样本，也不对原始表抽样来代替统计。

- `sum`：有限有效数值求和，全空单元格未定义。
- `mean`：对应原始范围的有效值均值，行列总计独立重算，不平均格子均值。
- 加权比率：分子总量 / 分母总量，分母为 0 未定义；分子、分母各自有效数目保存在结果中。已有 `cvr/ctr` 等口径仍按既有分子分母定义计算，即使旧参数写作 `mean`，也不改成比率的等权平均；页面实际口径卡写 `ratio_of_sums`。
- `count`：选定字段非空观测计数，不叫去重用户数。其行/列百分比是分类频数占比，不是业务转化率。
- `count_distinct`：在各单元格、各行、各列和全范围重新计算实体去重；不同格子的去重数不得相加。实体可能跨格，因此不显示误导性的归一化去重占比。
- `min/max`：在对应原始范围计算。

`exploration_cells` 保存完整受控观测分组；`exploration_totals` 保存 `all/row/column` 原始范围合计；`exploration_display` 保存有界图表视图。分布保存全量统计摘要及全量频数或分箱。

Top N 对完整结果排序后显示，并以稳定真实键处理并列。Others 从原始余集重新聚合（分类频数则可安全相加）；它不是源数据字符串，不能直接下钻。原始字符串恰好与“缺失值”或“其他分组”标签相同仍保留不同键和区分标签。

未观测交叉组合保留缺失，不无条件补 0。完整聚合超过既有 100000 行查询输出上限时拒绝并要求缩小明确范围，不返回一个冒充完整的前缀结果。高基数统计和图表显示成本分别计量；完整结果仍受原 256 MiB 总预算约束。

数值分布输出有效/缺失/转换失败/非有限数量、极值、四分位、中位数、均值和样本标准差（ddof=1）。直方图按全部有限值分箱；箱线图直接使用全量分位数，须线为最小/最大值，不宣称已经实施 Tukey 异常点识别。分类占比分母包含缺失观测。日期分布单列解析失败与范围。

## 结果、历史与导出

结果通过原 `PlaybookExecutionResult` → `AnalysisResultPackage`；`metadata.exploration` 保存冻结请求、实际口径卡、范围行数和显示边界。证据引用实际结果值及真实行/列分组键。PDF、Markdown、HTML、Excel、Manifest、ZIP 均沿原按需生成链绑定选定运行。

历史只保存总体及至多 127 个单元格的小摘要；大结果没有额外保留。比较前检查 nested exploration 请求中的筛选、维度、时间粒度、字段/类型和日期范围。不同筛选不可直接相减；时间窗不同明确标记上下文差异，缺失分组保持空，不补 0。仅 Top N 显示变化不改变完整数值比较的身份。

## 当前边界

仅受控单表；不新增任意 SQL/Python/表达式，不替代既有安全语义多表入口。没有语义模型的上传表仍可显式选择指标和字段，不强制编写 YAML。探索本身不新增基准比较、显著性检验、独立性认证或因果推断；需要这些任务应使用对应原剧本。已有直播质量与转化的领域受限 Pearson 描述性模块保留，本轮不新增通用 Pearson/Spearman 方法。

安全查询仍通过 AnalyticsEngine 的 AST、表列白名单、参数绑定、禁止外部访问、超时与内存上限；只增明确需要的精确分位数函数 `QUANTILE_CONT`（SQLGlot规范名 `PERCENTILE_CONT`），没有放宽写操作、外部表函数或作用域访问。

## 独立数值验收

本轮核心测试使用手算答案，不由被测代码生成 expected：10、30、20、60 的总和 120、均值 30、分组均值 20/40；9/90 与 1/2 的总体比率 10/92；跨格相同实体全局去重 2，单格和 3；Top N 余集均值按四行原数据得到 20，而非组均值平均 30。测试另覆盖空值、零分母、未观测组合、高基数、真空值与同名标签、日期、绑定筛选、超限拒绝、历史范围、图型零查询及六类导出。

本机已执行：

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/test_workbench_exploration.py tests/test_upstream_threads.py tests/test_upstream_threads_adversarial.py -q
```

该次实际结果：96 项通过，其中本轮探索核心 34 项。整轮全量、UI、浏览器与恢复成绩见本轮工作台验收说明；这里的小集不替代全量验收。


## CLI 配置恢复与复测

CLI 的 `--config-in` 保留有限的 `playbook_parameters.exploration_request`，再交给同一预检；只有 data_profile 的分布和 dimension_contribution 的分组/透视可接受，其他剧本或字段错误明确阻断。CLI 不把恢复的探索配置静默丢弃成普通分析。字段映射仍由 `column_mapping` 提供；自定义比率需明确 `numerator_column`、`denominator_column` 和 `aggregation: ratio_of_sums`。

本机另外实际执行：

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/test_workbench_cli.py -q
& ./.venv/Scripts/python.exe -m pytest tests/test_causal_result_presentation.py tests/test_workbench_exploration.py -q
```

前一命令 5 项通过，包含真实子进程读取 CSV/config、实际 Excel 中四行全范围均值 30 和加权比率 10/92，以及三个不合法或剧本不匹配请求的零分析 SQL、零报告生成。后一命令在 CLI 补丁前实际执行为 48 项通过；它包含无协变量与有协变量的因果图展示回归，未改变因果计算。

有筛选的下钻口径将实际筛选值的指纹写入定义，而非把原值复制到会被脱敏的公开口径卡。执行请求仍持有原绑定值，Manifest 仍脱敏；导出严格定义校验未放宽。测试验证真实过滤后的 PDF/Excel/Manifest/ZIP 能生成，同时篡改筛选指纹仍拒绝沿用旧数值。

另修复原因果图的展示协议：原始差与实际调整估计并列显示，不相加堆叠；未计算的倾向评分加权不显示，没有协变量时不画伪造调整值。原因果结果表、统计值和证据链未改变。


最终补充了恢复安全回归：真实 CLI 先生成带筛选的结果并导出 Manifest，再恢复时必须由统一探索预检拒绝 `<已脱敏，需重新输入>` 保留标记，要求明确重新输入原值。标量和 `in` 列表均拒绝；不会自动找回原值，也不会把占位符当作实际分组。最后实际执行命令与结果为：

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/test_workbench_cli.py tests/test_workbench_exploration.py -q
```

43 项通过（CLI 6 项、探索核心 37 项）；恢复阻断的分析执行器、分析 SQL 和导出调用全部为 0。
