# 性能专项实施说明

项目仍为0.1.0。修改前依据实际源码完成标准三场景与10万/50万/100万行基准、真实浏览器和AppTest；所有原始记录在根reports/performance/。源码恢复基线source-original只读。

## P0范围与缓存预算

共享PerformanceConfig和BoundedCache无全局数据实例、无文件存储，必须由会话拥有。默认预算：1个数据源/1 GiB（含仍被上传控件保留的原文件bytes）、1个结果/256 MiB、6个导出/64 MiB；另外单图16 MiB、当前表排序/筛选行号16 MiB、单表CSV64 MiB、开发详情JSON8 MiB，各只保留1项。默认各类保留预算之和为1448 MiB，TTL为1800秒。图表默认每图3000点/20序列，表格默认每页100行（50/100/200/500可选）。DuckDB默认4线程/1024 MiB，禁止静默spill。

预算通过INSIGHTPILOT_PERF_加字段大写的环境变量显式调整，例如INSIGHTPILOT_PERF_DATASET_MAX_BYTES、INSIGHTPILOT_PERF_EXPORT_MAX_BYTES、INSIGHTPILOT_PERF_SESSION_TTL_SECONDS。值必须为有限正数；数量/字节/点数必须整数。超过估计预算明确拒绝，不能截断分析输入。上传原始字节先检查，解析后与受控快照合并计费；超预算清理上传控件引用并提示。图表预算拒绝也显示警告，保留完整统计结果。配置保存在insightpilot/performance.py。

数据对象大小仅摄入/缓存插入时估计，DataFrame用memory_usage(deep=True)，同一对象引用不重复累计，不把缓存大小估计当作RSS硬上限。生成器、统计库和导出器的临时分配仍可能高于保留对象预算；释放引用不保证OS立即回收RSS。

会话保留受控数据快照、精确revision/指纹和已提交结果；展示参数与数值分析配置分离。重算需要用户提交，换数据/解析参数会失效，语义目录的小型YAML按真实内容hash（同长度且保留mtime的替换也失效），当前正在编辑的配置不能修改已完成结果的导出。会话释放按钮只清本会话，每轮页面执行统一检查全部展示/导出缓存过期，即使对应标签页关闭也会释放引用；数据和结果在访问时检查TTL，宿主断连生命周期负责会话释放。没有页面执行时不会启动独立TTL清理线程，释放引用也不承诺RSS立刻下降；没有私有业务数据的跨用户全局缓存或临时磁盘缓存。

## 重复工作与展示

核心按已测热点减少精确hash重复、重复画像/质量检查、无用表注册及整表asdict复制；精确安全检查不能用抽样替代。PreparedDataset负责一次摄入的私有快照，工作流presentation_mode='deferred'供页面只构建结构化结果；默认API/CLI兼容路径保留历史交付。

标签页与折叠详情需要实际open条件，不能仅隐藏DOM。明细表只传当前页，完整结果仍保留；排序/过滤必须先作用于完整结果。图表与大型JSON仅在用户查看时构建，图表展示预算不改变全量统计样本和报告结论。

## 导出

页面按PDF、Markdown、HTML、Excel、Manifest、ZIP顺序显式请求格式。下载使用已有bytes并忽略rerun；缓存绑定result_id、格式/选项和模板版本。ZIP可复用已生成内容，PDF不调用HTML/Excel/ZIP。兼容prepare_export_payloads和CLI明确all请求仍可一次生成全部格式。

PDF/HTML按原有输出行数上限选视图后再脱敏，仍保留原结果总行数及截断说明。Markdown不扫描不会展示的DataFrame。现有Excel公式防护、HTML/PDF转义、ZIP脱敏、中文字体/分页要求继续执行。

## P1决策

P0真实Chrome三次复测仍见大型源准备5.755秒（5.405–6.038秒）、首次分析2.448秒。因此在完成P0后追加P1：数据读取/准备与显式分析使用受限本地线程，页面通过0.5秒fragment轮询真实阶段。后台运行用于保持页面可操作，不宣称降低统计计算耗时。单格式导出仍在用户请求时同步生成；P0实测每次页面生成约0.85秒，无证据需要把导出也改成后台任务。

进程内TaskManager默认最多2个执行槽，每会话随机owner只允许1个任务，无无界队列。至多保留8条任务记录，已完成待接收结果总预算2 GiB；单个数据任务按数据预算、分析任务按256 MiB预算检查。按owner/task_id/完整配置key/数据revision严格取结果，交接移走引用。管理器是会话隔离的短期任务存储，不能作为跨会话数据缓存。工作线程不调用Streamlit或访问session_state；只有主线程接收结果和更新页面。

取消设置请求标志，在真实工作流节点/表处理/指纹/SQL返回等安全边界检查。执行中的pandas、SciPy、文件解析及原生SQL不能立即强杀；界面明确显示当前步骤结束后停止，只有worker退出才显示已取消。连接在finally关闭。取消、异常、接收、TTL过期均释放管理器所持闭包/结果引用。独立守护清理线程每30秒以内检查一次任务TTL（默认1800秒），不依赖浏览器关闭事件。运行任务过期先请求取消，仍须等当前原生步骤返回。close(wait=False)也不承诺进程立刻退出，Python可能等待工作线程结束。

INSIGHTPILOT_UI_SYNC=1提供明确同步兼容入口；CLI保持同步。原AppTest意图显式使用该配置，独立后台AppTest清除此变量并运行真实工作线程，另以Chrome验证实际fragment行为。最终完成时间、提交响应、取消与资源边界的实证见performance_acceptance.md。

## 正确性与复测

compare_performance.py对每张已保存结果表、列、行和嵌套证据对照；计数精确相同，浮点rtol=1e-10/atol=1e-12，p-value用atol=1e-300，避免极小p-value变成0仍被误判相同。独立参考评估和原有测试意图必须保留，不能自动更新expected掩盖变化。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
& ./.venv/Scripts/python.exe scripts/benchmark_performance.py --label after --repeat 3
& ./.venv/Scripts/python.exe scripts/benchmark_ingestion.py --output reports/performance/ingestion-after.json
& ./.venv/Scripts/python.exe -m pytest
& ./.venv/Scripts/python.exe -m insightpilot.evaluation.cli --suite all --output-format json
```

完整具体对照目录、浏览器命令、全量测试与评估真实结果在performance_acceptance.md。浏览器基准依赖本机已安装Playwright及独立Chrome，不使用用户登录profile；基准脚本不属于默认分析依赖。
