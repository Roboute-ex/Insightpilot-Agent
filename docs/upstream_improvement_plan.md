# 开源借鉴增量改造实施计划

读取日期：2026-09-23。规范实际路径：`D:/InsightPilot Agent/UPSTREAM_IMPROVEMENT_SPEC.md.md`。项目保持0.1.0；source-original只读，不发布或执行Git写操作。

## 修改前保护与测量

- 已完成：完整读取规范、项目AGENTS/README/requirements-lock/pyproject及性能验收记录；核对解释器Python3.14.7和SQLGlot30.18.0。现有SQLGlot已有初步AST校验，本轮补强，不重复引入。
- 已完成：白名单快照`../recovery-backups/insightpilot-agent-0.1.0-source-20260923T115636978648Z.zip`，291源码文件，SHA256 `23b615a761596e4e353fdf94bd43915db39140ae37ba004c766062f89fa407c9`。逐文件核验后解压至`reports/upstream/source-before`，保留未提交源码，不覆盖旧备份。
- 已完成修改前基线：本轮同机固定seed42核心/会话路径各3次、全量pytest、浏览器标准场景与单格式导出；不沿用9月7日结果作为本次成绩。核心计时期间禁止并行重负载测试。
- 已完成：五个上游项目有限只读研究。研究与来源记录见upstream_references.md；未核实内容不能作为事实。

## 阶段顺序和验收门

|阶段|最小实施范围|阶段验证|状态|
|---|---|---|---|
|P0-A|扩充现有指标/映射契约，轻量必要澄清入口，明确ready/needs_clarification/unsupported/invalid_input，口径卡及计算/展示指纹分离|模糊转化率→明确选择→执行；已明确内置示例不反复询问；无澄清无SQL|实现与定向验证完成|
|P0-B|补强已有SQLGlot校验，作用域/列白名单/完整节点/资源上限，DuckDB与SQLite执行前统一检查及失败关闭|合法CTE、中文/字符串/参数；危险后续分支拒绝且执行0次；现有语义/审批保持|实现与定向验证完成|
|P0-C|复用AnalysisSession/RunManifest/任务管理器，有限不可变历史、配置分支、受约束比较及选定run导出|城市/渠道不可逐行比较；同口径窗口描述性差异；淘汰可见；跨会话及旧任务隔离|实现与综合验证完成|
|P0-D|复用evaluation框架增加独立预期任务族；质量维度分开显示；闭环、数值、性能及打包恢复验证|全量pytest、三原套件、新任务族、AppTest与浏览器分别记录、wheel与独立恢复|实现与综合验证完成|
|P1可选|明确确认的口径配置/模板导入导出|仅P0全部通过且性能未回归后考虑|未开始，不作为P0替代|

每阶段先完成一个可运行闭环再扩展，定向测试通过后继续。保留失败日志，不删除失败测试或自动更新预期。最终更新README、验收报告与本计划的逐项状态。

## 不变约束

保留三种中文模式、12pt/10.5pt卡片、十剧本、39问题、三个主Demo、CSV/Excel/只读数据库/字段映射、完整统计/独立user_id/证据、审批、PDF优先六导出、惰性展示和后台取消。数据/结果/展示/导出总预算不增加，不新增无隔离全局用户缓存或临时磁盘缓存。分析只由明确提交触发；历史/对比/口径卡浏览不计算全表指纹或分析。新依赖缺失时SQL失败关闭，非SQL界面给出可理解错误。

## 恢复与记录入口

本轮原始运行记录均在`reports/upstream/`，基线环境见`baseline-environment.json`。本轮综合结果见upstream_improvement_acceptance.md；最终源码恢复证据由reports/upstream/source-restore-result.json记录。源码恢复以本轮修改前快照为基准，source-original不参与修改。工具默认执行返回Windows1385，已在用户授权项目范围通过提权执行工具读写；未改变系统策略。
