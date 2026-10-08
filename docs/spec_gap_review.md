# 完整规格差距复核

本页依据完整阅读外层 `REBUILD_SPEC.md.md`（第0–20节）、恢复后实际源码与本机执行结果进行独立复核。范围包含恢复来源、数据、统计、剧本与语义、中文界面、导出、治理、打包和备份。它不引用旧仓库测试数量作为本次成绩，也不把接口存在等同于完成验收。最终统一成绩与快照路径由 `acceptance_report.md` 和外层 `recovery-notes/` 记录。

## 最终必需验收闭环

| 项目 | 最终实际结果 | 证据 |
| --- | --- | --- |
| 安全跨事实聚合 | 受限整体/共同非时间维度独立预聚合通过；多指标、筛选、排序、审批绑定和null日期完整保留，不安全请求明确拒绝。 | engine_audit.md；外层final-cross-fact-cli.json。 |
| 最终源码快照独立恢复 | 268文件逐项哈希核验，独立目录新venv离线安装，项目外导入及完整pytest 281项通过、0失败/错误/跳过；三场景六导出及语义预览通过。 | 外层clean_restore_validation.json；recovery-backups/source-restore-validation-final/。 |
| 收尾整体验收 | core 5、safety 4、determinism 2案例重新全部通过；真实LangGraph三场景和零查询预览、PDF31页视觉、最终Chrome分析及六按钮首位PDF下载通过；最终wheel另一新venv项目外CLI通过。 | acceptance_report.md；ui_export_verification.md；外层最终JSON日志。 |

本轮已证实的必需缺口均已修复并按上述范围复验。此结论不代表所有自定义业务数据或未实测外部环境的正确性担保；下面的明确环境边界继续有效。

## 已关闭的高风险误报点

| 规格关注点 | 复核与修复后的事实 | 证据 |
| --- | --- | --- |
| 第4节：50,000直播场次 | standard为50,400个独立broadcast_id、8,000主播、90天；54,000是观众观看会话，不能用于冒充场次。会话有有效broadcast_id/host_id，时间在开播区间内；53,695是日分组数。 | `test_live_broadcasts_have_distinct_hosts_times_and_reconciled_viewer_sessions`；`recovery-notes/standard_measurements.json`。 |
| 第4/6节：直播观看人数 | 开播表observed_viewers按每场user_id去重；standard全域观測观众为18,622，逐场去重数不可累加冒充全域UV。模拟观测覆盖不等于完整场内观众。 | 对账测试及 `data_recovery.md` 的三个统计单位说明；UI已分别展示主播、开播、会话表。 |
| 第4节：注册早于业务事件 | large交易曾有81,994笔交易早于注册日期，已整体前移注册窗口。三场景均绑定观察起点，保留随机流和业务统计。 | 新增三个large场景逐事件外键时间检查与随机流检查；最后定向回归10 passed，退出0。 |
| 第4/6节：七阶段统计单位 | 交易七阶段均为嵌套转化旅程计数，历史带_users的字段不表示全站去重UV；支付至多一张订单。固定顺序算术分解披露非因果、净贡献/绝对影响和残差；单位已写入真实结果method。 | 数据对账回归；引擎七阶段守恒回归；`FunnelStageResult.method`。 |
| 第5节：39问题不是换文字 | 交易15、内容12、直播12；每场景6个常用项。全部配置实际执行有结果；当前35个显式剧本与4个自动流程。ct02总体实验与ct09分层实验输出不同；lv06实际生成设备网络体验与转化关联。 | `test_all_example_selections_execute_and_primary_metric_changes`、`test_overall_and_stratified_experiment_examples_have_distinct_outputs`；本轮18项定向回归通过。 |
| 第3节：真实文件格式和上限 | 真实BIFF .xls、宏启用OOXML .xlsm、多工作表.xlsx、UTF-8-SIG/UTF-8/GBK与分号均往返读取；CSV/Excel显式nrows严格兑现，CSV超限不再误报编码。 | `test_data_format_recovery.py` 与原file_loader回归14 passed，退出0；纯模拟xls夹具不是改名文件。 |
| 第6节：四类基准与缺日 | 使用目标日前7/28天均值、上周同日及近7对前7；不把目标日纳入基准；缺日和不完整周期提示，零分母为不可计算/UNKNOWN。阈值异常不冒称统计显著。 | `test_weighted_ratio_zero_denominator_and_calendar_completeness`、`test_metric_diagnosis_has_multiple_baselines_and_detects_drop`及实际零分母探查。 |
| 第6节：聚合、UV与贡献 | 比率按分子/分母加权，支付活跃用户按交易明细ID逐日去重，不声称全站访问UV。Top负10/正5按贡献符号筛选，缺失日期不会悄悄除以固定7天。 | `test_active_users_are_entity_distinct_not_summed_group_uv`、`test_dimension_top_positive_negative_limits_and_missing_days`。 |
| 第3/9节：季度和年度语义 | 语义API的quarter/year已实际编译、审批执行；季度2组、年度1组的收入合计均与原订单对齐。UI的day/week/month选择满足必需映射要求，季度/年度UI扩展不是未完成必需项。 | 独立只读query探查；已有语义编译器实现与回归。 |
| 第9节：累计与排序 | 累计按非时间维度PARTITION BY，城市不会串组累计。结构化排序使用输出字段及asc/desc白名单，并绑定审批。 | `test_cumulative_metric_partitions_by_non_time_dimensions`、`test_structured_sort_is_whitelisted_and_bound_to_plan`。 |
| 第8节：十剧本输入不适用 | 十个剧本均实际执行过有效small数据；逐个空输入探查返回FAIL、具体warnings且无结果表，不把不适用输入当成完整成功。工作流层还区分NEEDS_INPUT/PREVIEW等状态。 | `engine_audit.md` 逐项执行表与本轮空输入探查。 |
| 第6/7节：统计与证据 | 内容实验以唯一user_id为随机单位，Welch均值差与CI一致，标准6000/6000；p-value实际为1.4098989398539446e-25，不舍入为0。通用结果证据绑定真实数值行，lv06关联有LIVE-ASSOC-001。 | `standard_measurements.json`、`test_playbook_numeric_evidence_references_actual_result_rows`、直播关联回归。 |
| 第17节：源码快照安全 | 白名单保留合法隐藏配置、语义YAML及纯模拟xls夹具；排除环境/业务输出/敏感文件名；目录和文件均检查链接/Windows reparse point及解析路径边界；预检私钥和常见访问凭据格式。 | `test_snapshot_whitelist_and_hashes`、`test_snapshot_excludes_nested_environments_and_secret_names`。安全过滤与最终新venv独立恢复均已实际完成。 |

## 环境尚未验收与明确边界

- 远程CI没有运行。本机为Python 3.14.7；CI配置中的Python 3.11/Linux矩阵不能写成本轮已取得远程通过结果。保留配置与本地结果的区别。
- SQLite已实测；可选PostgreSQL/MySQL没有连接实际外部服务。其驱动、服务端只读权限和超时行为需在具备服务的环境另验收，无需为本轮索取凭据。
- .xlsm验证的是真实宏启用文件格式和多表读取，没有VBA项目，且不执行宏；不宣称各种复杂第三方VBA工作簿均已验收。
- 实验为本地模拟观测。二元比例差使用Wald近似并提示稀疏样本限制；未宣称精确检验。会话层体验与转化相关为描述性分析，重复用户会话不冒充独立用户样本，也不证明因果。
- 语义支持受控指标表达式与关系规则，不是通用Text-to-SQL。没有安全预聚合路径或会发生fanout的请求应明确拒绝；审批不是修复重复计算的手段。
- MCP Preview只有schema/本地接口；完整transport、远程OpenTelemetry collector和复杂多表DAG属于规格明确列出的可选扩展，不能据此把本轮必需功能说成缺失，也不能反向宣称它们已完整实现。
- 安装依赖需要网络或已备好的wheelhouse；安装完成后的默认分析不依赖在线模型、API key或旧账号。

原始 `source-original/` 未被本子任务改动；所有源码修复仅在新0.1.0工作副本完成。本子任务没有执行git add、commit、tag、push或上传数据。
