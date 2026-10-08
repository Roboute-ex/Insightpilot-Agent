# 本地能力差距分析

审计日期：2026-09-23。依据实际源码，不以README声明代替执行证据。本轮修改前快照和测量状态见upstream_improvement_plan.md。上游参考已按固定路径/提交核验；下表参考方向不等于已复制代码或验证整套平台。

|能力|本地真实入口与已有实现|本轮具体缺口|最小改动与新增回归|参考方向|
|---|---|---|---|---|
|指标定义|insightpilot/metrics/dictionary.py::MetricDefinition已有单位、聚合、分子分母、粒度；semantic/models.py::SemanticMetric已有注册依赖|缺统一口径版本/计算与展示fingerprint、统计单位/有效样本/时区/来源状态等兼容字段|扩充现有模型与映射；明确定义复用；测试只改标题不重算、语义修改失效|MetricFlow实体粒度与指标语义；WrenAI可审查上下文|
|必要澄清|planning/planner.py::create_analysis_plan、metrics/resolver.py、agents/workflow.py；已有规则识别/NEEDS_INPUT|多个候选可能全部匹配/选首列；未知目标可能降级概览，没有必要问题结构与明确确认入口|在现有Planner前置轻量决策，兼容状态与CLI；歧义/不支持禁止分析SQL；内置明确口径免追问|WrenAI计划校验/结构化错误|
|字段映射|ingestion/mapping.py::ColumnMapping与app/components/mapping_panel.py|自动建议与明确确认来源未区分；聚合/时间无效值有回退行为需审计|保留原映射入口，新增必要角色和确认，拒绝影响答案的无效配置|本地需求主导|
|SQL AST|tools/sql_safety.py已使用SQLGlot30.18.0解析所有节点、函数和表；DuckDB/SQLite有只读/限流|CTE名称用全树集合可能作用域混淆；无列校验/完整节点白名单/解析资源上限；依赖顶层导入不够友好|扩展同一校验层和结构化结果，接全部现有入口；两方言实际正反测试，拒绝时执行0次|SQLGlot AST/scope测试|
|语义/连接治理|semantic/catalog/compiler/join_planner/approval；contracts、lineage|本轮要把新增语义与SQL策略版本绑定计划/缓存；不得绕过已有fanout和数据指纹复核|最小字段/校验接入，回归现有审批、跨事实拒绝和证据|MetricFlow连接边界；WrenAI可审查计划|
|历史/分支|RunManifest、app/session_data.py::AnalysisSession、ui_streamlit.py已有最近配置和结果|没有有界历史父子关系、显式恢复配置、可比性检查与按键对齐差异|只保存有限不可变元数据/摘要与受控引用，复用结果预算；被淘汰显示需重跑；历史不重算|Data Formulator Data Thread分支探索|
|缓存与后台|performance.py::BoundedCache、performance_tasks.py::TaskManager、app/background_tasks.py|已有数量/字节/TTL/owner/revision/request隔离；新分支需加node绑定和口径指纹|扩展身份绑定和失效，不创建第二调度器，不加并发/总内存预算；晚到结果/取消/隔离测试|DB-GPT任务状态和执行边界，仅借鉴设计|
|结果与导出|analysis/results.py、reports/manifest.py、app/components/export_panel.py；PDF第一且按请求生成|新口径/比较/历史选定run要与报告一致；不可混入未提交编辑参数|复用报告协议和格式，仅加必要元数据/摘要；历史PDF/Excel/JSON/ZIP闭环；单PDF无其他生成|本地现有能力|
|质量与评估|evaluation/harness.py已有core/safety/determinism独立小表；Reviewer评分及contracts面板|缺新任务族评估与执行/口径/质量/统计前提/证据五维展示|增加真实问题任务与手算expected；未验证前提明确显示；保留旧Reviewer接口|DB-GPT任务状态与WrenAI结构化错误，本地独立验证|
|性能与恢复|benchmark_performance/browser、compare_playbook_snapshots、export_source_snapshot、restore_and_verify|必须建立本轮新基线，不能引用历史355/1或性能数字当成绩|3次同机前后、完整结果证据对比、全套测试、真实浏览器/PDF、wheel/package data/独立恢复|不做外部平台性能横向宣称|

## 已确认保留的能力

语义目录、精确数据指纹、RunManifest、Tracer、审批器、任务管理器、PDF、六类导出、十个剧本均已有实际实现，本轮不重建。已有SQLGlot通路已完成完整作用域和正反测试补强；最终全量524通过/1项可选依赖跳过，实际LangGraph另在独立环境验证。

## 研究与实施边界

默认独立实现。上游证据与具体许可证核验集中在upstream_references.md，访问失败按未核实记录。本轮阶段测试、性能和独立恢复证据详见upstream_improvement_acceptance.md。未验证的统计前提仍显示未验证。

## 实施后状态

P0-A/B/C/D均已落地并由真实入口调用：指标与Planner契约、SQL作用域策略、现有会话上的有界历史与对比、任务评估/五维质量与报告口径。全量、浏览器、性能、打包恢复的具体运行结果及仍未覆盖边界集中在验收文档，不用本文最初“已有能力”判断代替实际成绩。

本轮不覆盖任意自然语言多轮理解、任意自由公式、跨事实时间关联或未认证数据库方言。PG/MySQL/MariaDB查询现在在连接前明确拒绝；DuckDB/SQLite经本机验证。历史只保留一个完整结果及最多10条小摘要；旧大结果释放后须显式重跑。P1持久模板/完整口径目录导入未实施；JSON历史核验不恢复执行授权。
