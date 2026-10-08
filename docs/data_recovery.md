# 数据能力恢复与验收

本次在公开仓库可见分支、标签和历史中未找到 `data/scenarios/`、`data/example_questions.py` 与 `examples/generate_demo_files.py` 的可兼容源码，因此在新的 0.1.0 工作副本中按重建规格补齐。原 `source-original/` 和来源快照不变；提交来源和历史核查记录见 `migration_notes.md` 及外层 `recovery-notes/`。

## 保留、修复与补建

| 范围 | 本次处理 | 验证状态 |
| --- | --- | --- |
| `data/synthetic.py` 原三场景及七表商业生成器 | 保留原实现；统一访问转化率口径，支付成功率改为观测成功数/尝试数，零分母保留不可计算；商业场景追加真实有序事件 | 原入口及数值/外键回归已执行 |
| `data/scenarios/` | 补建按需加载的 small/standard/large 交易、内容、直播场景，固定参考日和seed | 标准规模、确定性、真实信号及明细汇总对账通过 |
| `data/example_questions.py` | 补建39个中文示例，附目标、剧本、字段、说明和可执行配置 | 字段存在、配置独立、39个配置逐条实际执行；39配置逐条执行无FAIL；当前35个显式剧本、4个自动流程，保留合理比率不可加总WARN |
| `metrics/dictionary.py`、`metrics/aggregation.py` | 保留指标字典接口，补充别名、分子分母、单位、粒度、聚合方式、维度和好坏方向 | 字典兼容及比率组件解析通过 |
| `metrics/resolver.py`、`planning/planner.py` | 补充退款、客单价、崩溃、延迟与互动事件词；未知问题不臆选收入和用户数 | 原Planner/指标解析回归通过 |
| `examples/generate_demo_files.py` | 用户指定目录输出CSV、多工作表Excel和SQLite，拒绝覆盖 | 文件往返、行数、工作表及拒绝覆盖测试通过 |

## 本机实际标准规模

固定 `seed=42`，所有场景数据参考日为 **2026-06-30**。演示中的“昨日”指该参考日，不随电脑日期改变。下表来自本次实际生成结果。

| 场景 | 日期跨度 | 主要实际行数 | 维度类别 | 示例问题 |
| --- | --- | --- | --- | --- |
| 交易 | 180天 | 日分组36,000；逐订单明细316,035；商户3,000；用户20,000 | 14 | 15，简洁模式6 |
| 内容 | 120天 | 内容20,000；日分组43,200；逐播放108,042；实验分配12,000 | 11 | 12，简洁模式6 |
| 直播 | 90天 | 独立主播开播50,400；主播8,000；观看会话54,000；质量/互动各54,000；日分组53,695 | 10 | 12，简洁模式6 |

规模配置：交易 small 为35天×40个稀疏分组，standard 为180×200，large 为365×400；内容分别为35×50、120×360、240×720个观测分组；直播分别为35×80、90×600、180×1,200个会话。large 本次实际生成：交易146,000日分组/1,283,484逐订单；内容172,800日分组/432,023播放/24,000实验用户；直播180,000独立开播/216,000观看会话/213,423日分组。生成逻辑已实际执行；新增独立场次后不沿用早先直播耗时，large全量UI交互以最终验收记录为准。

交易按稀疏观测分组重复日期，不生成全部维度笛卡尔积。为兼容恢复源码中的维度断言，交易保留 `South City`、`Android`、`social` 等稳定标识，元数据附中文标签；其他维度尽量用中文。设备品牌及版本保留技术名称。

七表商业演示保持原来规模；`scale` 不改变这一历史场景，并在元数据明确说明。现在另外提供 `events`，所以返回八张表。事件由每条session的实际嵌套阶段标记生成，时间为对应日期12:00起每阶段相隔2分钟；不从订单结果臆造购物车事件。

## 统计单位、对账与确定信号

交易七阶段统一使用**转化旅程数**：曝光→点击→访问→加购→结算→支付尝试→支付成功，每阶段是上阶段的子集。历史字段名 `add_to_cart_users`、`checkout_users` 不表示全站UV，每次支付最多对应一张订单。逐订单表按 `daily_row_id` 汇总的订单数、金额分、退款数及退款金额分与日表精确对账。金额以整数分生成和核对。用户数必须按实体ID去重，日分组中的支付用户数不能累加冒充全站UV。

交易注入南城订单下降、社交推荐流量下降、新客转化下降、Android 6.2支付成功率下降，同时合作入口有正向流量变化、其他组保留稳定基准。本次标准数据参考日订单量为772，前7日均值为1,710.285714，变化为-54.861343%；该数值来自抽样生成后的实际汇总，不是分析器读取元数据输出的目标值。

内容逐播放 `completed` 是二元观测，日完播率为完播次数/播放次数，观看时长使用总秒数/播放次数。分类差异、长内容在Android上的差异在观测数据中注入。日播放数、完播数、互动次数和观看总时长均与事件表对账。

内容实验每行是一名唯一随机分配用户，观测15–35次播放。`completion_rate` 为该用户实际完播数/播放数，实验比较使用用户均值，不将同一用户的播放错误视为独立随机样本。实验与自然内容流量是不同观察窗口，不能重复相加。本次标准实验实测：

- 对照组6,000人，实验组6,000人。
- 对照用户平均完播率53.961660%，实验组56.839544%。
- 绝对提升2.877884个百分点，相对提升5.333202%。
- Welch t检验双侧p-value为 `1.4098989398539446e-25`。
- 95%均值差置信区间为 `[0.023394925759012024, 0.03416276293541821]`，即 `[2.339493, 3.416276]` 个百分点。

统计显著性不等于业务重要性，上述数据全部为本地模拟观测。不同seed或代码修改后必须重新计算，不以这些值作为新测试的硬编码目标。

直播现在同时包含三个实体：`live_hosts`为主播，`live_broadcasts`为独立开播，`live_sessions`为观众观看会话。标准数据具有50,400个不同broadcast_id及90个日期，满足至少50,000独立开播的规模要求，不以观看会话冒充场次。每场包含host_id、开始/结束时间、独立类别属性；同一主播每天最多开播一次；观看会话通过broadcast_id关联，继承主播层级和直播类别，观测开始/结束时间位于对应开播窗口内。

small具有2,100场/180主播/2,800观看会话；standard为50,400场/8,000主播/54,000观看会话；large为180,000场/12,000主播/216,000观看会话。开播表中的observed_sessions、observed_viewers、observed_watch_time_total分别从观看会话计数、每场user_id去重、观看秒数合计得到并严格对账。standard全体观测用户去重为18,622；逐场去重人数不可累加冒充全域去重人数。观测会话只是模拟观测覆盖，不宣称完整场内观众数量。每会话有600秒质量观测窗，因此卡顿率的会话均值等于总卡顿秒数/总观测秒数；日表保存分子分母以便正确加权。质量和互动各恰好一行/session，主外键有效。平板与移动网络交集在最后3天出现更高卡顿和更短观看时长，6.2版本出现更高崩溃率；其他版本的WiFi/Wired组保留稳定基准。

零分母比率保留NaN并由分析层提示不可计算，不填零。`latency_ms` 和 `startup_latency` 都以毫秒定义，兼容别名在指标列表去重。日表不同样本量比率必须用分子分母聚合，不能直接平均。`metric_components(metric, columns)` 为引擎提供按实际字段选择的口径；它刻意不把实验用户均值改成逐播放检验。

## 示例的实际应用

每个 `ExampleQuestion` 包含稳定ID、场景、中文分类与问题、推荐目标与剧本、所需字段及说明。`selection_config` / `apply_settings()` 返回 `question`、`goal_mode`、`playbook_id`、`column_mapping` 和 `parameters`。显式配置真正切换指标、维度、表、聚合方式或剧本，近一个月和两个七日窗口均绑定数据参考日。

比率或平均时长问题优先选择原子观测表，避免在日分组间不加权平均；例如退款率用逐订单退款标记均值，内容完播率用逐播放二元标记均值。设备网络、内容长度设备及活动客群用稳定组合维度展示，保留对照组。

39个配置在最终绑定更新后重新逐条用small数据执行：当前35条显式剧本无FAIL且都有非空结果，保留比率组值不能相加的合理WARN；4条自动工作流无errors且有结构化结果。交易订单问题与支付问题分别以orders和payment_success_rate为第一指标，执行摘要不同。ct02是总体实验，不产生experiment_stratified；ct09是按user_segment分层的实验，产生真实分层表。lv06选择卡顿率与转化率两指标，输出按唯一session_id配对的quality_conversion_association和quality_conversion_groups，并关联LIVE-ASSOC-001证据；Pearson相关只用于描述，不做把重复用户会话冒充独立用户的显著性检验。周期查询已恢复；最终UI点击状态仍以整体验收记录为准。

## 可控质量测试与边界

默认数据不注入不可识别的重复。`with_quality_issues(dataset, table_name, missing_column=..., duplicate_rows=...)` 显式创建目标表副本，注入一处字段缺失和最多10条精确重复，并记录源行、插入位置和警告；原干净表不变。重复可被常规重复检测识别，不能带着重复直接作业务计数。

注入信号及质量元数据只供评估和复核，分析器从实际表计算，不读取ground truth生成答案。内容 `retained` 是模拟后续观察结果，真正队列留存应使用多表留存剧本。

## 文件生成与本次测试

在项目目录使用项目解释器，不需要激活环境：

```powershell
.venv\Scripts\python.exe examples\generate_demo_files.py --scenario transaction --scale small --seed 42 --output-dir .\local_data\demo_transaction_01
.venv\Scripts\python.exe examples\generate_demo_files.py --scenario content --scale standard --formats csv sqlite --output-dir .\local_data\demo_content_01
.venv\Scripts\python.exe examples\generate_demo_files.py --scenario live --scale small --formats excel --output-dir .\local_data\demo_live_01
```

必须显式给出输出目录。同场景输出已存在时预检拒绝，写文件再使用独占创建；不会覆盖同名数据。生成物包括选定格式及清晰标识模拟来源的metadata。CSV采用UTF-8-SIG；CSV/Excel对危险公式前缀转义；SQLite新建于指定输出目录。Excel使用.xlsx，不宣称生成旧.xls文件。large若超过Excel单表行数上限会拒绝并建议CSV/SQLite。

本次数据子任务最终一轮命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_data_recovery.py tests/test_large_synthetic_transaction.py tests/test_large_synthetic_content.py tests/test_large_synthetic_live.py tests/test_example_questions.py tests/test_metric_dictionary.py tests/test_planner.py tests/test_multi_table_synthetic_v06.py tests/test_synthetic_data.py tests/test_anomaly.py tests/test_attribution.py tests/test_experiments.py -ra
```

实测 **29 passed in 5.88s，退出码0**。额外标准交易结果/实验输出/目标模式检查一轮为13 passed；最终全量pytest和快照恢复另由项目整体验收记录，不能把本页局部结果冒充完整项目成绩。

数据生成和分析在依赖安装完成后不需要网络、在线LLM、API key、GPU或模型训练。未运行任何git add、commit、tag或push。

## 真实文件格式补充验收

`tests/test_data_format_recovery.py` 与原 `tests/test_file_loader.py` 本次合计 **12 passed in 0.21s，退出码0**：

- `.xls` 为真实OLE/BIFF文件，文件头 `D0 CF 11 E0 A1 B1 1A E1`，用xlrd读取中文交易/退款两张工作表及金额125.5/5.25；不是改扩展名的xlsx。
- 纯模拟夹具 `tests/fixtures/format_recovery.xls` 共5,632字节；SHA256为 `1B86016915917DD46AD6C95A50468DB6222720B014768907E81C85C952B2A51F`。生成器xlwt 1.3.0只在本机生成该夹具时使用，未加入默认依赖；后续测试直接用随源码保存的夹具和xlrd。
- `.xlsm` 是包含 `application/vnd.ms-excel.sheet.macroEnabled.main+xml` 内容类型的真正宏启用OOXML包，包含两张中文表，未包含VBA项目，也未执行宏；此测试不代表包含复杂VBA项目的第三方文件已经验收。
- `.xlsx` 实际按指定顺序读取多个工作表并放入TableRegistry，重名生成后缀，既有表不被覆盖。
- UTF-8-SIG、UTF-8、GBK均实际编码后按显式分号读取；另验GBK自动重试重置读取位置、重复中文列消歧。

原三场景路由、目标模式和文本格式又一轮为 **15 passed in 3.33s，退出码0**。这些均为各次局部检查，不叠加冒充最终全量pytest统计。

新增39示例执行回归后，数据恢复、真实文件格式、原文件加载、示例问题及文本格式联合检查为 **31 passed in 8.87s，退出码0**。

最终补齐独立主播场次、总体/分层实验区分及体验转化关联后，数据恢复、标准直播及问题回归为 **18 passed in 10.47s，退出码0**。读取限制另修复nrows=1返回2行和超CSV上限误报编码问题；CSV/Excel显式nrows现严格兑现，上限溢出给出具体提示，格式及原加载器定向回归为 **14 passed in 0.26s，退出码0**。

## 用户注册与观测时间补充核查

最终只读审查发现large交易的1,283,484笔明细中有81,994笔日期早于原通用用户注册日期；standard不受影响。这一真实缺陷已修复，未删失败条件：三场景调用make_users时都传入实际观察起点，必要时将完整300天注册窗口整体前移，避免把所有越界用户裁剪到同一天。用户ID、其他用户属性、随机数生成器状态及后续业务信号保持不变。

新增回归逐条关联large交易订单、内容播放/实验分配、直播观看会话的user_id，验证观测日期不早于注册日期；另验证注册窗口保留分布、随机流不变，并复验既有确定性和明细对账。定向命令为 `python -m pytest tests/test_data_recovery.py -k "registration or seed_deterministic or detail_reconciles or totals_and_quality" -ra`，本次结果 **10 passed, 8 deselected in 3.42s，退出码0**。这是局部回归，不替代最终全量测试。
